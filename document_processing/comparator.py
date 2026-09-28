import difflib
import re
from datetime import date, datetime, timedelta

try:
    from .contract_terms import match_price_point
    from .parser import parse_date_str
except ImportError:
    from contract_terms import match_price_point
    from parser import parse_date_str

EPS = 0.51                      # ₹/$ rounding tolerance
CATEGORY_ORDER = {"Violation": 0, "Unexplained": 1, "Informational": 2}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


# ---------------------------------------------------------------- helpers
def _fmt(cur, v):
    if v is None:
        return "n/a"
    sym = SYMBOLS.get(cur, (cur + " ") if cur else "")
    sign = "-" if v < 0 else ""
    return f"{sign}{sym}{abs(v):,.2f}"


def _pct(new, old):
    return round((new - old) / old * 100, 2) if old else 0.0


def _norm(desc):
    d = re.sub(r"\([^)]*\)", " ", desc.lower())
    return re.sub(r"[^a-z0-9 ]", " ", d).split() and " ".join(re.sub(r"[^a-z0-9 ]", " ", d).split())


def _same_item(a, b):
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() >= 0.8


def _view(inv):
    """Flatten an invoice dict into what the analysis needs (None-safe)."""
    a, i = inv.get("amounts", {}), inv.get("invoice", {})
    items = inv.get("items") or []
    taxes = inv.get("taxes") or []
    subtotal = a.get("subtotal")
    if subtotal is None and items:
        subtotal = round(sum(x["amount"] for x in items), 2)
    discount = a.get("discount") or 0.0
    tax_total = a.get("tax")
    if tax_total is None and taxes:
        tax_total = round(sum(t["amount"] for t in taxes), 2)
    tax_total = tax_total or 0.0
    taxable = (subtotal - discount) if subtotal is not None else None
    rates = [t["rate"] for t in taxes if t.get("rate") is not None]
    types = sorted({t["type"] for t in taxes})
    vg, cg = inv.get("vendor", {}).get("gstin"), inv.get("customer", {}).get("gstin")
    return {
        "number": i.get("number"), "date": parse_date_str(i.get("date")) or i.get("date"),
        "due_date": i.get("due_date"), "terms": i.get("payment_terms"),
        "currency": i.get("currency"), "total": a.get("total"), "subtotal": subtotal,
        "discount": discount, "tax": tax_total, "taxable": taxable, "items": items,
        "taxes": taxes, "declared_rate": round(sum(rates), 4) if rates else None,
        "tax_types": types, "vendor_gstin": vg, "customer_gstin": cg,
        "confidence": (inv.get("meta") or {}).get("confidence"),
        "warnings": (inv.get("meta") or {}).get("warnings", []),
    }


def _tax_kind(types):
    if not types:
        return None
    if "IGST" in types:
        return "IGST"
    if "CGST" in types or "SGST" in types or "UTGST" in types:
        return "CGST+SGST"
    return "+".join(types)


def _flag(type_, severity, category, description, evidence, invoice=None, item=None,
          citation=None, impact=0.0, citations=None):
    return {
        "type": type_, "severity": severity, "category": category,
        "description": description, "evidence": evidence, "invoice": invoice, "item": item,
        "citation": citation, "citations": citations or ([citation] if citation else []),
        "impact": round(impact, 2),
    }


def _cite(c):
    if not c:
        return None
    return {"page": c.get("page"), "clause": c.get("clause"), "text": c.get("text")}


def _gross(amount, rate_pct):
    """Pre-tax overcharge -> what was actually paid including tax on it."""
    return amount * (1 + (rate_pct or 0) / 100)


# ---------------------------------------------------------------- item alignment
def _align_items(views):
    """Canonical item rows across all invoices: [{name, cells:[cell|None per invoice]}]."""
    rows = []
    for idx, v in enumerate(views):
        for it in v["items"]:
            row = next((r for r in rows if _same_item(r["name"], it["description"])), None)
            if row is None:
                row = {"name": it["description"], "cells": [None] * len(views)}
                rows.append(row)
            row["cells"][idx] = {"qty": it["quantity"], "unit": it["unit_price"], "amount": it["amount"]}
    return rows


def _pair_items(prev_items, cur_items):
    matched, used = [], set()
    for c in cur_items:
        hit = next((p for k, p in enumerate(prev_items)
                    if k not in used and _same_item(p["description"], c["description"])), None)
        if hit is not None:
            used.add(prev_items.index(hit))
            matched.append((hit, c))
    matched_cur = {id(c) for _, c in matched}
    matched_prev = {id(p) for p, _ in matched}
    new = [c for c in cur_items if id(c) not in matched_cur]
    removed = [p for p in prev_items if id(p) not in matched_prev]
    return matched, new, removed


# ---------------------------------------------------------------- bridge
def _bridge(pv, cv):
    """Reconciling bridge prev.total -> cur.total. Always sums exactly (residual = 'other')."""
    steps = []
    matched, new, removed = _pair_items(pv["items"], cv["items"])
    price = sum((c["unit_price"] - p["unit_price"]) * c["quantity"] for p, c in matched)
    volume = sum((c["quantity"] - p["quantity"]) * p["unit_price"] for p, c in matched)
    new_amt = sum(c["amount"] for c in new)
    rem_amt = -sum(p["amount"] for p in removed)
    disc = -(cv["discount"] - pv["discount"])

    have_items = bool(pv["items"] and cv["items"])
    if have_items:
        steps += [("Base price changes", price), ("Quantity / seat changes", volume),
                  ("New line items", new_amt), ("Removed line items", rem_amt),
                  ("Discount change", disc)]
    else:
        steps.append(("Pre-tax change", (cv["subtotal"] or 0) - (pv["subtotal"] or 0)))

    tax_delta = cv["tax"] - pv["tax"]
    eff_prev = (pv["tax"] / pv["taxable"]) if pv["taxable"] else 0
    tax_on_change = eff_prev * ((cv["taxable"] or 0) - (pv["taxable"] or 0))
    steps += [("Tax on the changes above", tax_on_change),
              ("Tax rate / calculation variance", tax_delta - tax_on_change)]

    total_delta = (cv["total"] or 0) - (pv["total"] or 0)
    residual = total_delta - sum(v for _, v in steps)
    steps.append(("Other / rounding", residual))

    return {
        "from_invoice": pv["number"], "to_invoice": cv["number"],
        "start_total": pv["total"], "end_total": cv["total"], "delta": round(total_delta, 2),
        "steps": [{"label": l, "amount": round(v, 2)} for l, v in steps if abs(v) >= 0.01],
    }



def _vendor_name(inv):
    return ((inv.get("vendor") or {}).get("name") or "").strip()


def _validate_same_vendor(invoices):
    """Prevent accidental cross-vendor comparisons."""
    names = [_vendor_name(inv) for inv in invoices]
    if any(not n for n in names):
        return False, "Vendor information is missing from one or more invoices."
    normalized = {n.casefold() for n in names}
    if len(normalized) > 1:
        return False, "Cannot compare invoices from different vendors."
    return True, None

# ---------------------------------------------------------------- main analysis
def analyze_invoice_series(invoices, contract_terms=None, as_of=None):
    """
    invoices: list of parsed invoice dicts (any order; sorted by date here). Uses the last 3.
    contract_terms: output of contract_terms.extract_contract_terms (optional).
    """
    if not invoices:
        return {"status": "ERROR", "message": "No invoices supplied for analysis.", "flags": []}

    same_vendor, vendor_error = _validate_same_vendor(invoices)
    if not same_vendor:
        return {"status": "ERROR", "message": vendor_error, "flags": []}

    views = [_view(i) for i in invoices]
    views.sort(key=lambda v: v["date"] or "")
    views = views[-3:]
    if not views or any(v["total"] is None for v in views):
        return {"status": "ERROR", "message": "Unable to analyse: an invoice total is missing.", "flags": []}

    terms = contract_terms or {}
    cur = views[-1]["currency"]
    as_of = as_of or date.today()
    flags = []
    n = len(views)

    # ---- duplicates
    seen = {}
    for v in views:
        if v["number"] in seen and v["number"]:
            flags.append(_flag("DUPLICATE_INVOICE", "HIGH", "Violation",
                               f"Invoice number {v['number']} appears more than once.",
                               f"Both copies total {_fmt(cur, v['total'])}", v["number"],
                               impact=v["total"]))
        seen[v["number"]] = True

    price_points = terms.get("price_points", [])
    cap = terms.get("price_increase")
    c_tax = terms.get("tax")
    c_pay = terms.get("payment_terms")
    c_discounts = terms.get("discounts", [])
    contract_discount = sum(d["amount"] for d in c_discounts)

    per_invoice_overpay = {v["number"]: 0.0 for v in views}

    def add(flag, counts_toward_recovery=False):
        flags.append(flag)
        if counts_toward_recovery and flag["invoice"] in per_invoice_overpay:
            per_invoice_overpay[flag["invoice"]] += flag["impact"]

    # ================== per-invoice contract checks (absolute) ==================
    for idx, v in enumerate(views):
        rate = (c_tax or {}).get("rate") or v["declared_rate"] or 0
        prev = views[idx - 1] if idx else None
        matched, new_items, _removed = _pair_items(prev["items"], v["items"]) if prev else ([], v["items"], [])
        prev_of = {id(c): p for p, c in matched}

        for it in v["items"]:
            pp = match_price_point(it["description"], price_points)
            p_item = prev_of.get(id(it))

            if pp and it["unit_price"] > pp["amount"] + 0.005:
                over = (it["unit_price"] - pp["amount"]) * it["quantity"]
                chg = (f" (up {_pct(it['unit_price'], p_item['unit_price']):.1f}% from "
                       f"{_fmt(cur, p_item['unit_price'])})") if p_item else ""
                cites = [_cite(pp)] + ([_cite(cap)] if cap else [])
                extra = ""
                if cap and cap.get("max_percent") is not None and p_item:
                    extra = f" Clause {cap['clause']} caps increases at {cap['max_percent']:g}%."
                add(_flag("CONTRACT_PRICE_EXCEEDED", "HIGH", "Violation",
                          f"'{it['description']}' billed above contract price.",
                          f"Invoiced {_fmt(cur, it['unit_price'])}{chg} vs contract "
                          f"{_fmt(cur, pp['amount'])} ({pp['unit']}, clause {pp['clause']}, "
                          f"p.{pp['page']}).{extra}",
                          v["number"], it["description"], _cite(pp),
                          _gross(over, rate), cites), True)
            elif p_item and it["unit_price"] > p_item["unit_price"] + 0.005:
                inc = _pct(it["unit_price"], p_item["unit_price"])
                ev = f"{_fmt(cur, p_item['unit_price'])} → {_fmt(cur, it['unit_price'])} (+{inc:.1f}%)"
                if not pp and cap and cap.get("max_percent") is not None:
                    allowed = p_item["unit_price"] * (1 + cap["max_percent"] / 100)
                    if it["unit_price"] > allowed + 0.005:
                        over = (it["unit_price"] - allowed) * it["quantity"]
                        add(_flag("PRICE_CAP_EXCEEDED", "HIGH", "Violation",
                                  f"'{it['description']}' rose {inc:.1f}%, above the {cap['max_percent']:g}% cap.",
                                  f"{ev}; clause {cap['clause']} (p.{cap['page']}) caps at {cap['max_percent']:g}%.",
                                  v["number"], it["description"], _cite(cap), _gross(over, rate)), True)
                    else:
                        nd = cap.get("notice_days")
                        add(_flag("PRICE_INCREASE_VERIFY_NOTICE", "MEDIUM", "Unexplained",
                                  f"'{it['description']}' price increased within the cap.",
                                  f"{ev}. Confirm written notice"
                                  f"{f' of {nd} days' if nd else ''} was received (clause {cap['clause']}).",
                                  v["number"], it["description"], _cite(cap)))
                else:
                    add(_flag("PRICE_CHANGE", "MEDIUM", "Unexplained",
                              f"'{it['description']}' unit price increased with no contract basis.",
                              ev, v["number"], it["description"]))
            elif p_item and it["unit_price"] < p_item["unit_price"] - 0.005:
                add(_flag("PRICE_DECREASE", "LOW", "Informational",
                          f"'{it['description']}' unit price decreased.",
                          f"{_fmt(cur, p_item['unit_price'])} → {_fmt(cur, it['unit_price'])}",
                          v["number"], it["description"]))

            if p_item and abs(it["quantity"] - p_item["quantity"]) > 1e-9:
                delta_amt = (it["quantity"] - p_item["quantity"]) * p_item["unit_price"]
                add(_flag("QUANTITY_CHANGE", "LOW" if delta_amt <= 0 else "MEDIUM", "Informational",
                          f"'{it['description']}' quantity changed.",
                          f"{p_item['quantity']:g} → {it['quantity']:g} "
                          f"(cost effect {_fmt(cur, delta_amt)} pre-tax)",
                          v["number"], it["description"]))

        # new / removed lines
        if prev:
            for it in new_items:
                pp = match_price_point(it["description"], price_points)
                if pp and it["unit_price"] <= pp["amount"] + 0.005:
                    add(_flag("NEW_LINE_ITEM", "LOW", "Informational",
                              f"New line item '{it['description']}' is covered by the contract.",
                              f"{_fmt(cur, it['amount'])}, clause {pp['clause']}", v["number"], it["description"]))
                elif cap and cap.get("consent_for_new_fees"):
                    add(_flag("NEW_FEE_WITHOUT_CONSENT", "HIGH", "Violation",
                              f"New charge '{it['description']}' introduced without consent.",
                              f"{_fmt(cur, it['amount'])} appeared this month; clause {cap['clause']} "
                              f"(p.{cap['page']}) bars new fees without written consent.",
                              v["number"], it["description"], _cite(cap), _gross(it["amount"], rate)), True)
                else:
                    add(_flag("NEW_LINE_ITEM", "MEDIUM", "Unexplained",
                              f"New line item '{it['description']}' not present last month.",
                              f"{_fmt(cur, it['amount'])}; no matching contract clause found.",
                              v["number"], it["description"]))
            for p_it in _removed:
                add(_flag("REMOVED_LINE_ITEM", "LOW", "Informational",
                          f"Line item '{p_it['description']}' no longer billed.",
                          f"Was {_fmt(cur, p_it['amount'])} on {prev['number']}", v["number"], p_it["description"]))

        # ---- discounts
        if contract_discount and v["discount"] < contract_discount - EPS:
            missing = contract_discount - v["discount"]
            cd = c_discounts[0]
            add(_flag("DISCOUNT_NOT_APPLIED", "HIGH", "Violation",
                      "Contractual discount not applied in full.",
                      f"Invoice discount {_fmt(cur, v['discount'])} vs contract "
                      f"{_fmt(cur, contract_discount)} (clause {cd['clause']}, p.{cd['page']}).",
                      v["number"], "Discount", _cite(cd), _gross(missing, rate)), True)
        elif prev and v["discount"] < prev["discount"] - EPS:
            add(_flag("DISCOUNT_REDUCED", "MEDIUM", "Unexplained", "Discount reduced vs last invoice.",
                      f"{_fmt(cur, prev['discount'])} → {_fmt(cur, v['discount'])}", v["number"], "Discount"))

        # ---- tax
        base = v["taxable"]
        if v["declared_rate"] is not None and base is not None and v["taxes"]:
            expected = round(base * v["declared_rate"] / 100, 2)
            diff = round(v["tax"] - expected, 2)
            if abs(diff) > max(1.0, 0.001 * v["tax"]):
                add(_flag("TAX_CALC_MISMATCH", "HIGH" if diff > 0 else "MEDIUM",
                          "Violation" if diff > 0 else "Unexplained",
                          "Invoiced tax differs from recomputed tax.",
                          f"Invoiced {_fmt(cur, v['tax'])} vs expected {_fmt(cur, expected)} "
                          f"({v['declared_rate']:g}% × {_fmt(cur, base)}); difference {_fmt(cur, diff)}.",
                          v["number"], "Tax", impact=max(diff, 0)), diff > 0)
        if c_tax and v["declared_rate"] is not None and abs(v["declared_rate"] - c_tax["rate"]) > 0.001:
            excess = base * (v["declared_rate"] - c_tax["rate"]) / 100 if base else 0
            add(_flag("TAX_RATE_VS_CONTRACT", "HIGH", "Violation",
                      "Tax rate differs from the rate stated in the contract.",
                      f"Invoice {v['declared_rate']:g}% vs contract {c_tax['rate']:g}% "
                      f"(clause {c_tax['clause']}, p.{c_tax['page']}).",
                      v["number"], "Tax", _cite(c_tax), max(excess, 0)), excess > 0)

        vs, cs = (v["vendor_gstin"] or "")[:2], (v["customer_gstin"] or "")[:2]
        kind = _tax_kind(v["tax_types"])
        if vs.isdigit() and cs.isdigit() and kind in ("IGST", "CGST+SGST"):
            if vs == cs and kind == "IGST":
                add(_flag("WRONG_TAX_TYPE", "HIGH", "Violation",
                          "IGST charged on an intra-state supply (same state code on both GSTINs).",
                          f"Vendor GSTIN state {vs} = customer state {cs}; CGST+SGST expected"
                          f"{f' (clause {c_tax['clause']})' if c_tax and c_tax.get('split_when_same_state') else ''}. "
                          "Risk: input tax credit may be denied.",
                          v["number"], "Tax", _cite(c_tax) if c_tax and c_tax.get("split_when_same_state") else None))
            elif vs != cs and kind == "CGST+SGST":
                add(_flag("WRONG_TAX_TYPE", "HIGH", "Violation",
                          "CGST+SGST charged on an inter-state supply.",
                          f"Vendor state {vs} ≠ customer state {cs}; IGST expected. Risk: ITC denial.",
                          v["number"], "Tax"))
        if not v["vendor_gstin"] and any(t in ("CGST", "SGST", "IGST", "GST") for t in v["tax_types"]):
            add(_flag("GSTIN_MISSING", "MEDIUM", "Unexplained", "GST charged but no vendor GSTIN found.",
                      "Input tax credit needs a valid vendor GSTIN on the invoice.", v["number"], "Tax"))

        # ---- payment terms
        if c_pay and v["terms"]:
            m = re.search(r"(\d+)", v["terms"])
            if m and int(m.group(1)) < c_pay["days"]:
                add(_flag("PAYMENT_TERMS_VS_CONTRACT", "MEDIUM", "Violation",
                          "Payment window shorter than the contract allows.",
                          f"{v['terms']} vs contract Net {c_pay['days']} (clause {c_pay['clause']}, p.{c_pay['page']}).",
                          v["number"], "Terms", _cite(c_pay)))

    # ================== pairwise checks (latest vs previous, and previous vs earlier) ==================
    for idx in range(1, n):
        p, c = views[idx - 1], views[idx]
        if p["declared_rate"] is not None and c["declared_rate"] is not None \
                and abs(p["declared_rate"] - c["declared_rate"]) > 0.001:
            add(_flag("TAX_RATE_CHANGE", "HIGH", "Unexplained", "Tax rate changed between invoices.",
                      f"{p['declared_rate']:g}% ({p['number']}) → {c['declared_rate']:g}% ({c['number']})",
                      c["number"], "Tax"))
        kp, kc = _tax_kind(p["tax_types"]), _tax_kind(c["tax_types"])
        if kp and kc and kp != kc:
            add(_flag("TAX_TYPE_CHANGE", "MEDIUM", "Unexplained", "Tax structure changed.",
                      f"{kp} on {p['number']} → {kc} on {c['number']}", c["number"], "Tax"))
        if p["vendor_gstin"] and c["vendor_gstin"] and p["vendor_gstin"] != c["vendor_gstin"]:
            add(_flag("GSTIN_CHANGE", "HIGH", "Unexplained", "Vendor GSTIN changed.",
                      f"{p['vendor_gstin']} → {c['vendor_gstin']}; verify before claiming ITC.",
                      c["number"], "Tax"))
        if p["terms"] and c["terms"] and p["terms"] != c["terms"]:
            add(_flag("PAYMENT_TERMS_CHANGE", "MEDIUM", "Unexplained", "Payment terms changed.",
                      f"{p['terms']} → {c['terms']}", c["number"], "Terms"))

        ch = c["total"] - p["total"]
        if ch > 0.005:
            pct = _pct(c["total"], p["total"])
            add(_flag("PRICE_INCREASE", "HIGH" if pct > 10 else "MEDIUM", "Informational",
                      f"Invoice total increased by {pct:.2f}%.",
                      f"Previous: {p['total']:.2f} → Current: {c['total']:.2f}", c["number"], "Total"))

    # ================== renewal ==================
    renewal_info = None
    ren = terms.get("renewal")
    if ren and ren.get("term_end"):
        end = datetime.strptime(ren["term_end"], "%Y-%m-%d").date()
        notice = ren.get("notice_days") or 0
        deadline = end - timedelta(days=notice)
        days_left = (deadline - as_of).days
        renewal_info = {"term_end": end.isoformat(), "notice_days": notice,
                        "cancel_by": deadline.isoformat(), "days_left": days_left,
                        "citation": _cite(ren)}
        if days_left <= 60:
            sev = "HIGH" if days_left <= 30 else "MEDIUM"
            msg = (f"Auto-renewal notice window closes in {days_left} days." if days_left >= 0
                   else f"Notice deadline passed {-days_left} days ago; contract may already have renewed.")
            add(_flag("RENEWAL_DEADLINE", sev, "Informational", msg,
                      f"Term ends {end:%d %b %Y}; give {notice} days' written notice by "
                      f"{deadline:%d %b %Y} (clause {ren['clause']}, p.{ren['page']}).",
                      views[-1]["number"], "Renewal", _cite(ren)))

    # ================== assemble output ==================
    flags.sort(key=lambda f: (CATEGORY_ORDER[f["category"]], SEVERITY_ORDER[f["severity"]]))

    rows = _align_items(views)
    flag_index = {}
    for f in flags:
        if f["item"] and f["invoice"]:
            key = (f["invoice"], _norm(f["item"]))
            cur_rank = flag_index.get(key)
            if cur_rank is None or CATEGORY_ORDER[f["category"]] < CATEGORY_ORDER[cur_rank]:
                if f["category"] != "Informational":
                    flag_index[key] = f["category"]
    trend = []
    for r in rows:
        cells = []
        for k, cell in enumerate(r["cells"]):
            status = "missing"
            if cell is not None:
                cat = flag_index.get((views[k]["number"], _norm(r["name"])))
                status = {"Violation": "red", "Unexplained": "amber"}.get(cat, "green")
                if cell is not None and k > 0 and r["cells"][k - 1] is None and status == "green":
                    status = "amber"  # newly appeared
            cells.append({**(cell or {}), "status": status, "invoice": views[k]["number"]})
        last, prev_c = r["cells"][-1], r["cells"][-2] if n > 1 else None
        delta = None
        if last and prev_c:
            delta = {"unit": round(last["unit"] - prev_c["unit"], 2),
                     "unit_pct": _pct(last["unit"], prev_c["unit"]),
                     "amount": round(last["amount"] - prev_c["amount"], 2)}
        elif last and n > 1:
            delta = {"unit": None, "unit_pct": None, "amount": last["amount"], "note": "new"}
        elif prev_c and n > 1:
            delta = {"unit": None, "unit_pct": None, "amount": -prev_c["amount"], "note": "removed"}
        trend.append({"item": r["name"], "cells": cells, "delta": delta})

    totals = []
    for k, v in enumerate(views):
        row = {"invoice": v["number"], "date": v["date"], "subtotal": v["subtotal"],
               "discount": v["discount"], "tax": v["tax"], "total": v["total"],
               "mom_change": None, "mom_pct": None}
        if k:
            row["mom_change"] = round(v["total"] - views[k - 1]["total"], 2)
            row["mom_pct"] = _pct(v["total"], views[k - 1]["total"])
        totals.append(row)

    tax_rows = []
    for k, v in enumerate(views):
        expected = round(v["taxable"] * v["declared_rate"] / 100, 2) \
            if v["taxable"] is not None and v["declared_rate"] is not None else None
        tax_rows.append({
            "invoice": v["number"], "structure": _tax_kind(v["tax_types"]),
            "breakdown": [f"{t['type']} {t['rate']:g}% = {_fmt(cur, t['amount'])}" if t.get("rate") is not None
                          else f"{t['type']} = {_fmt(cur, t['amount'])}" for t in v["taxes"]],
            "declared_rate": v["declared_rate"], "taxable_value": v["taxable"],
            "invoiced_tax": v["tax"], "expected_tax": expected,
            "difference": round(v["tax"] - expected, 2) if expected is not None else None,
            "effective_rate": round(v["tax"] / v["taxable"] * 100, 3) if v["taxable"] else None,
            "vendor_gstin": v["vendor_gstin"], "customer_gstin": v["customer_gstin"],
            "tax_change_vs_prev": round(v["tax"] - views[k - 1]["tax"], 2) if k else None,
        })

    bridges = [_bridge(views[k - 1], views[k]) for k in range(1, n)]

    violations = [f for f in flags if f["category"] == "Violation"]
    recoverable = round(sum(per_invoice_overpay.values()), 2)
    latest_over = per_invoice_overpay[views[-1]["number"]]
    billed = sum(v["total"] for v in views)

    review = [{"invoice": v["number"], "confidence": v["confidence"], "warnings": v["warnings"]}
              for v in views if (v["confidence"] is not None and v["confidence"] < 0.8) or v["warnings"]]

    headline = {
        "recoverable_amount": recoverable,
        "overpaid_by_invoice": {k: round(x, 2) for k, x in per_invoice_overpay.items()},
        "violations": len(violations),
        "unexplained": sum(1 for f in flags if f["category"] == "Unexplained"),
        "informational": sum(1 for f in flags if f["category"] == "Informational"),
        "leakage_pct": round(recoverable / billed * 100, 2) if billed else 0.0,
        "projected_annual_overpay": round(latest_over * 12, 2),
        "billed_in_period": round(billed, 2),
        "renewal": renewal_info,
    }

    return {
        "status": "SUCCESS", "vendor_name": _vendor_name(invoices[0]), "currency": cur, "invoice_count": n,
        "invoices": [v["number"] for v in views], "periods": [v["date"] for v in views],
        "headline": headline, "totals": totals, "trend_table": trend, "tax_analysis": tax_rows,
        "bridges": bridges, "flags": flags, "needs_review": review,
        "contract_used": bool(terms), "actions": _actions(flags, headline, cur),
    }


def _actions(flags, headline, cur):
    acts = []
    if headline["recoverable_amount"] > 0:
        acts.append({"priority": 1, "action": f"Dispute {_fmt(cur, headline['recoverable_amount'])} of contract "
                     "violations and request a credit note.", "deadline": None})
    if any(f["type"] in ("WRONG_TAX_TYPE", "TAX_CALC_MISMATCH", "GSTIN_CHANGE", "GSTIN_MISSING") for f in flags):
        acts.append({"priority": 2, "action": "Ask the vendor for a corrected tax invoice before claiming input tax credit.",
                     "deadline": None})
    if any(f["type"] in ("PRICE_INCREASE_VERIFY_NOTICE", "NEW_LINE_ITEM", "PRICE_CHANGE", "DISCOUNT_REDUCED") for f in flags):
        acts.append({"priority": 3, "action": "Ask the vendor to justify the unexplained changes in writing.",
                     "deadline": None})
    r = headline.get("renewal")
    if r and r["days_left"] <= 60:
        acts.append({"priority": 1 if r["days_left"] <= 30 else 3,
                     "action": "Decide on renewal / renegotiation and send written notice if cancelling.",
                     "deadline": r["cancel_by"]})
    acts.sort(key=lambda a: a["priority"])
    return acts


# ---------------------------------------------------------------- backward-compatible 2-invoice API
def compare_invoices(previous, current, contract_terms=None):
    """Original two-invoice API with same-vendor protection."""
    previous_vendor = _vendor_name(previous)
    current_vendor = _vendor_name(current)

    if not previous_vendor or not current_vendor:
        return {
            "status": "ERROR",
            "message": "Unable to compare invoices because vendor information is missing.",
            "previous_vendor": previous_vendor or None,
            "current_vendor": current_vendor or None,
            "flags": [],
        }

    if previous_vendor.casefold() != current_vendor.casefold():
        return {
            "status": "ERROR",
            "message": "Cannot compare invoices from different vendors.",
            "previous_vendor": previous_vendor,
            "current_vendor": current_vendor,
            "flags": [],
        }

    pt = previous.get("amounts", {}).get("total")
    ct = current.get("amounts", {}).get("total")
    if pt is None or ct is None:
        return {
            "status": "ERROR",
            "message": "Unable to compare invoices because total amount is missing.",
            "flags": [],
        }

    analysis = analyze_invoice_series([previous, current], contract_terms)
    if analysis["status"] != "SUCCESS":
        return analysis

    change = ct - pt
    return {
        "status": "SUCCESS",
        "vendor_name": current_vendor,
        "previous_invoice_number": previous.get("invoice", {}).get("number"),
        "current_invoice_number": current.get("invoice", {}).get("number"),
        "currency": current.get("invoice", {}).get("currency"),
        "previous_total": pt,
        "current_total": ct,
        "change_amount": round(change, 2),
        "change_percentage": round(_pct(ct, pt), 2),
        "flags": analysis["flags"],
        "analysis": analysis,
    }


if __name__ == "__main__":
    import json
    import sys
    try:
        from .parser import parse_pdf_file
        from .contract_terms import extract_contract_file
    except ImportError:
        from parser import parse_pdf_file
        from contract_terms import extract_contract_file

    files = sys.argv[1:] or [f"samples/invoice_bluepeak_2026_0{m}.pdf" for m in (7, 8, 9)]
    invs = [parse_pdf_file(f) for f in files]
    _, terms = extract_contract_file("samples/contract_bluepeak.pdf")
    out = analyze_invoice_series(invs, terms)
    print(json.dumps(out["headline"], indent=2, ensure_ascii=False))
    for f in out["flags"]:
        print(f"[{f['category']:<13}|{f['severity']:<6}] {f['type']:<28} {f['description']}")