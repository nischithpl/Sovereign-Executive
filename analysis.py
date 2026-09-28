"""
analysis.py - deterministic audit engine + orchestration (shared by app.py and main.py).

Every number (deltas, tax recompute, bridge, leakage, projections) is plain Python.
The LLM (ai_service.py) only writes wording.

Optional fields it reads if your parser provides them (all guarded, nothing crashes if absent):
  invoice["line_items"]  = [{"description","quantity","unit_price","amount"}]
  invoice["amounts"]     = {"subtotal","tax","total"}
  invoice["tax"]         = {"rate","cgst","sgst","igst"}
  invoice["vendor"]["gstin"], invoice["invoice"]["due_date"], ["payment_terms"]
"""
import csv
import io
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
# parser.py does "from extractor import ...", so the folder itself must be importable too
for _p in (_HERE, os.path.join(_HERE, "document_processing")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai_service  # noqa: E402
import database  # noqa: E402
from document_processing.comparator import compare_invoices  # noqa: E402
from document_processing.extractor import extract_pdf_text  # noqa: E402
from document_processing.parser import create_invoice_data  # noqa: E402

RANK = {"VIOLATION": 0, "UNEXPLAINED": 1, "INFO": 2}


# ------------------------------------------------------------------ helpers
def num(x):
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(re.sub(r"[^\d.\-]", "", str(x)))
    except ValueError:
        return None


def get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def norm(s):
    return re.sub(r"\s+", " ", str(s or "").lower()).strip()


def money(x, cur="INR"):
    return f"{cur} {x:,.2f}" if isinstance(x, (int, float)) else "N/A"


def base_amount(inv):
    return first(num(get(inv, "amounts", "subtotal")), num(get(inv, "amounts", "total")))


def finding(ftype, category, description, evidence="", amount=None):
    # "severity" mirrors category so old consumers of flag["severity"] keep working
    return {"type": ftype, "severity": category, "category": category,
            "description": description, "evidence": evidence, "amount": amount}


def parse_pdf_bytes(data: bytes) -> dict:
    """PDF bytes -> parsed invoice dict. Uses a safe temp file (no user-controlled filenames)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        pages = extract_pdf_text(path)
    finally:
        os.remove(path)
    return create_invoice_data("\n".join(p["text"] for p in pages))


# ------------------------------------------------------------------ line items
def items_of(inv):
    out = {}
    for it in inv.get("line_items") or []:
        key = norm(it.get("description"))
        if not key:
            continue
        qty = first(num(it.get("quantity")), 1.0)
        price = num(it.get("unit_price"))
        amt = num(it.get("amount"))
        if amt is None and price is not None:
            amt = price * qty
        if price is None and amt is not None and qty:
            price = amt / qty
        out[key] = {"description": it.get("description"), "qty": qty, "price": price, "amount": amt or 0.0}
    return out


def diff_items(prev, curr):
    """Returns (changes, effects). 'delta' = effect on the bill (positive = you pay more)."""
    p, c = items_of(prev), items_of(curr)
    changes, fx = [], {"price": 0.0, "qty": 0.0, "new": 0.0, "removed": 0.0}
    for k, n in c.items():
        o = p.get(k)
        if o is None:
            changes.append({"kind": "NEW", "item": n["description"], "prev": None, "curr": n["amount"], "delta": n["amount"]})
            fx["new"] += n["amount"]
            continue
        if n["price"] is not None and o["price"] is not None and abs(n["price"] - o["price"]) > 0.005:
            d = (n["price"] - o["price"]) * o["qty"]
            fx["price"] += d
            changes.append({"kind": "PRICE", "item": n["description"], "prev": o["price"], "curr": n["price"], "delta": d})
        if abs(n["qty"] - o["qty"]) > 1e-9:
            d = (n["qty"] - o["qty"]) * (n["price"] or 0.0)
            fx["qty"] += d
            changes.append({"kind": "QTY", "item": n["description"], "prev": o["qty"], "curr": n["qty"], "delta": d})
    for k, o in p.items():
        if k not in c:
            d = -o["amount"]
            fx["removed"] += d
            changes.append({"kind": "REMOVED", "item": o["description"], "prev": o["amount"], "curr": None, "delta": d})
    return changes, fx


# ------------------------------------------------------------------ tax
def tax_info(inv):
    a = inv.get("amounts") or {}
    t = inv.get("tax") if isinstance(inv.get("tax"), dict) else {}
    subtotal, total = num(a.get("subtotal")), num(a.get("total"))
    cgst, sgst, igst = (num(first(t.get(k), a.get(k))) for k in ("cgst", "sgst", "igst"))
    tax = first(num(a.get("tax")), num(a.get("tax_total")), num(t.get("total")))
    if tax is None and any(v is not None for v in (cgst, sgst, igst)):
        tax = sum(v or 0 for v in (cgst, sgst, igst))
    if tax is None and subtotal is not None and total is not None:
        tax = total - subtotal
    declared = first(num(t.get("rate")), num(a.get("tax_rate")))
    rate = declared
    if rate is None and tax is not None and subtotal:
        rate = round(tax / subtotal * 100, 2)
    kind = "IGST" if igst else ("CGST+SGST" if (cgst or sgst) else None)
    expected = subtotal * declared / 100 if (declared is not None and subtotal is not None) else None
    return {"subtotal": subtotal, "total": total, "invoiced": tax, "rate": rate,
            "expected": expected, "kind": kind, "gstin": get(inv, "vendor", "gstin")}


def tax_findings(prev, curr, cur):
    out, t = [], tax_info(curr)
    if t["expected"] is not None and t["invoiced"] is not None and abs(t["invoiced"] - t["expected"]) > 1.0:
        diff = t["invoiced"] - t["expected"]
        out.append(finding("TAX_MISMATCH", "UNEXPLAINED", "Invoiced tax differs from recomputed tax",
                           f"Invoiced {money(t['invoiced'], cur)} vs expected {money(t['expected'], cur)} "
                           f"({t['rate']}% on {money(t['subtotal'], cur)})", max(diff, 0.0)))
    if None not in (t["subtotal"], t["invoiced"], t["total"]) and abs(t["subtotal"] + t["invoiced"] - t["total"]) > 1.0:
        out.append(finding("TOTAL_ARITHMETIC", "UNEXPLAINED", "Subtotal + tax does not equal the invoice total",
                           f"{money(t['subtotal'], cur)} + {money(t['invoiced'], cur)} = "
                           f"{money(t['subtotal'] + t['invoiced'], cur)}, but total is {money(t['total'], cur)}",
                           max(t["total"] - t["subtotal"] - t["invoiced"], 0.0)))
    if not t["gstin"]:
        out.append(finding("GSTIN_MISSING", "INFO", "No vendor GSTIN found on the invoice",
                           "Missing GSTIN can block input tax credit."))
    if prev:
        p = tax_info(prev)
        if p["rate"] is not None and t["rate"] is not None and abs(p["rate"] - t["rate"]) > 0.01:
            out.append(finding("TAX_RATE_CHANGE", "UNEXPLAINED" if t["rate"] > p["rate"] else "INFO",
                               "Tax rate changed", f"{p['rate']}% -> {t['rate']}%"))
        if p["kind"] and t["kind"] and p["kind"] != t["kind"]:
            out.append(finding("TAX_TYPE_CHANGE", "UNEXPLAINED", "Tax type split changed",
                               f"{p['kind']} -> {t['kind']} (vendor state change or wrongly raised invoice)"))
        if p["gstin"] and t["gstin"] and norm(p["gstin"]) != norm(t["gstin"]):
            out.append(finding("GSTIN_MISMATCH", "UNEXPLAINED", "Vendor GSTIN differs from previous invoice",
                               f"{p['gstin']} -> {t['gstin']}"))
        elif p["gstin"] and not t["gstin"]:
            out.append(finding("GSTIN_MISSING", "UNEXPLAINED", "GSTIN present earlier but missing now", p["gstin"]))
    return out


# ------------------------------------------------------------------ other findings
def diff_findings(prev, curr, changes, cur):
    out = []
    for c in changes:
        cat = "UNEXPLAINED" if c["delta"] > 0 else "INFO"
        k = c["kind"]
        if k == "PRICE":
            out.append(finding("PRICE_CHANGE", cat, f"Unit price changed: {c['item']}",
                               f"{money(c['prev'], cur)} -> {money(c['curr'], cur)} per unit (impact {money(c['delta'], cur)})", c["delta"]))
        elif k == "QTY":
            out.append(finding("QUANTITY_CHANGE", cat, f"Quantity/seats changed: {c['item']}",
                               f"{c['prev']:g} -> {c['curr']:g} (impact {money(c['delta'], cur)})", c["delta"]))
        elif k == "NEW":
            out.append(finding("NEW_LINE_ITEM", cat, f"New line item: {c['item']}",
                               f"Not on the previous invoice; adds {money(c['curr'], cur)}", c["delta"]))
        elif k == "REMOVED":
            disc = c["delta"] > 0
            out.append(finding("DISCOUNT_REMOVED" if disc else "REMOVED_LINE_ITEM",
                               "UNEXPLAINED" if disc else "INFO",
                               f"{'Discount/credit' if disc else 'Line item'} no longer present: {c['item']}",
                               f"Was {money(c['prev'], cur)} on the previous invoice", c["delta"] if disc else None))
    pc, cc = get(prev, "invoice", "currency"), get(curr, "invoice", "currency")
    if pc and cc and norm(pc) != norm(cc):
        out.append(finding("CURRENCY_CHANGE", "UNEXPLAINED", "Invoice currency changed", f"{pc} -> {cc}"))
    for key, label in (("payment_terms", "Payment terms"), ("due_date", "Due date")):
        a, b = get(prev, "invoice", key), get(curr, "invoice", key)
        if a and b and norm(a) != norm(b):
            out.append(finding("TERMS_CHANGE", "UNEXPLAINED", f"{label} changed", f"{a} -> {b}"))
    return out


def renewal_info(contract):
    if not contract or not contract.get("renewal_date"):
        return None
    try:
        rd = datetime.strptime(contract["renewal_date"], "%Y-%m-%d").date()
    except ValueError:
        return None
    deadline = rd - timedelta(days=int(contract.get("notice_days") or 0))
    today = date.today()
    return {"renewal_date": rd.isoformat(), "cancel_by": deadline.isoformat(),
            "days_to_renewal": (rd - today).days, "days_to_cancel": (deadline - today).days}


def contract_findings(curr, pct_change, contract, cur):
    """The contract is ground truth: price vs agreed price, increase cap, renewal window."""
    out = []
    if not contract:
        return out
    clause = contract.get("clause")
    cite = f" Clause: {clause}" if clause else ""
    base = base_amount(curr)
    agreed = contract.get("agreed_amount")
    if agreed and base is not None and base > agreed + 0.5:
        out.append(finding("CONTRACT_PRICE_VIOLATION", "VIOLATION", "Invoice price exceeds the contract price",
                           f"Invoiced {money(base, cur)} vs contract {money(agreed, cur)}.{cite}", base - agreed))
    cap = contract.get("max_increase_pct")
    if cap is not None and pct_change is not None and pct_change > cap + 0.005:
        out.append(finding("CONTRACT_CAP_VIOLATION", "VIOLATION", "Price increase exceeds the contractual cap",
                           f"Increase {pct_change:.2f}% vs cap {cap:g}%.{cite}", None))
    r = renewal_info(contract)
    if r and r["days_to_cancel"] <= 45:
        msg = (f"Cancel by {r['cancel_by']} ({r['days_to_cancel']} days left); renews {r['renewal_date']}"
               if r["days_to_cancel"] >= 0 else
               f"Notice window closed on {r['cancel_by']}; contract renews {r['renewal_date']}")
        out.append(finding("RENEWAL_NOTICE", "INFO", "Auto-renewal approaching", msg))
    return out


# ------------------------------------------------------------------ bridge / trend / confidence
def build_bridge(prev, curr, fx, cur):
    pt, ct = num(get(prev, "amounts", "total")), num(get(curr, "amounts", "total"))
    if pt is None or ct is None:
        return None
    ptax, ctax = tax_info(prev)["invoiced"], tax_info(curr)["invoiced"]
    base_fx = fx["price"]
    if not items_of(prev) and not items_of(curr):
        sp, sc = num(get(prev, "amounts", "subtotal")), num(get(curr, "amounts", "subtotal"))
        base_fx = (sc - sp) if (sp is not None and sc is not None) else 0.0
    steps = [("Base price change", base_fx), ("Quantity / seats", fx["qty"]), ("New fees", fx["new"]),
             ("Removed items / discounts", fx["removed"]),
             ("Tax effect", (ctax - ptax) if (ctax is not None and ptax is not None) else 0.0)]
    residual = (ct - pt) - sum(v for _, v in steps)
    if abs(residual) > 0.5:
        steps.append(("Other / unexplained", residual))
    return {"start": pt, "end": ct, "currency": cur,
            "steps": [{"label": l, "value": round(v, 2)} for l, v in steps if abs(v) > 0.005]}


def build_trend(history, current, has_violation):
    invs = list(reversed(history[:2])) + [current]
    cols = [get(i, "invoice", "date") or get(i, "invoice", "number") or f"Invoice {n + 1}" for n, i in enumerate(invs)]
    per = [items_of(i) for i in invs]
    keys, labels = [], {}
    for it in per:
        for k, v in it.items():
            if k not in labels:
                labels[k] = v["description"]
                keys.append(k)
    rows = [(labels[k], [it[k]["amount"] if k in it else None for it in per]) for k in keys]
    for name, fn in (("Subtotal", lambda i: num(get(i, "amounts", "subtotal"))),
                     ("Tax", lambda i: tax_info(i)["invoiced"]),
                     ("TOTAL", lambda i: num(get(i, "amounts", "total")))):
        rows.append((name, [fn(i) for i in invs]))
    out = []
    for name, vals in rows:
        last, prev = vals[-1], (vals[-2] if len(vals) > 1 else None)
        delta = (last or 0.0) - (prev or 0.0) if (last is not None or prev is not None) else None
        if delta is None or abs(delta) < 0.005:
            status = "green"
        elif delta > 0 and has_violation:
            status = "red"
        else:
            status = "amber"
        out.append({"item": name, "values": vals, "delta": delta, "status": status})
    return {"columns": cols, "rows": out}


def confidence(inv, findings):
    score, reasons = 1.0, []
    for label, val in (("vendor name", get(inv, "vendor", "name")), ("invoice number", get(inv, "invoice", "number")),
                       ("total amount", get(inv, "amounts", "total")), ("invoice date", get(inv, "invoice", "date"))):
        if val in (None, ""):
            score -= 0.15
            reasons.append(f"missing {label}")
    if not inv.get("line_items"):
        score -= 0.10
        reasons.append("no line items extracted")
    if any(f["type"] in ("TOTAL_ARITHMETIC", "TAX_MISMATCH") for f in findings):
        score -= 0.15
        reasons.append("amounts do not reconcile (possible OCR error)")
    return round(max(score, 0.1), 2), reasons


# ------------------------------------------------------------------ orchestration
def _sorted(flags):
    return sorted(flags, key=lambda f: (RANK.get(f["category"], 3), -(f.get("amount") or 0)))


def _leakage(flags):
    unexplained = sum(f["amount"] or 0 for f in flags if f["category"] == "UNEXPLAINED" and (f["amount"] or 0) > 0)
    contract = sum(f["amount"] or 0 for f in flags if f["category"] == "VIOLATION" and (f["amount"] or 0) > 0)
    return round(max(unexplained, contract), 2)


def run_audit(current, previous=None, tone="firm", save=True, use_memory=True):
    """
    current  : parsed invoice dict
    previous : optional parsed invoice dict (explicit comparison). If None and use_memory,
               history comes from SQLite.
    Returns a result dict with status in ERROR | DUPLICATE | BASELINE_ESTABLISHED | SUCCESS.
    """
    vendor = get(current, "vendor", "name") or ""
    number = get(current, "invoice", "number")
    cur = get(current, "invoice", "currency") or "INR"
    ctotal = num(get(current, "amounts", "total"))

    # ---- duplicate detection
    if use_memory and database.invoice_exists(vendor, number):
        return {"status": "DUPLICATE", "vendor_name": vendor, "currency": cur, "current_total": ctotal,
                "message": f"Invoice {number} from {vendor} is already on file.",
                "flags": [finding("DUPLICATE_INVOICE", "VIOLATION", "Same invoice number submitted twice",
                                  f"{vendor} / {number} already recorded; do not pay twice.", ctotal)],
                "leakage": {"recoverable": ctotal or 0.0, "violations": 1, "unexplained": 0, "projected_annual": 0.0},
                "confidence": 1.0, "confidence_reasons": [], "needs_review": False}

    contract = database.get_contract(vendor) if (use_memory and vendor) else None
    history = [previous] if previous else (database.get_history(vendor, 3) if (use_memory and vendor) else [])
    prev = history[0] if history else None

    # ---- baseline (first invoice seen)
    if prev is None:
        flags = tax_findings(None, current, cur) + contract_findings(current, None, contract, cur)
        conf, why = confidence(current, flags)
        if save and vendor:
            database.save_invoice(current)
        return {"status": "BASELINE_ESTABLISHED",
                "message": f"First invoice recorded for {vendor or 'this vendor'}. Saved as baseline." if save
                           else "Invoice analysed (not saved).",
                "vendor_name": vendor, "currency": cur, "current_total": ctotal,
                "current_invoice_number": number, "flags": _sorted(flags),
                "tax_check": tax_info(current),
                "memory": _memory(vendor, current, contract, [], current, cur),
                "leakage": {"recoverable": _leakage(flags),
                            "violations": sum(f["category"] == "VIOLATION" for f in flags),
                            "unexplained": sum(f["category"] == "UNEXPLAINED" for f in flags),
                            "projected_annual": 0.0},
                "confidence": conf, "confidence_reasons": why, "needs_review": conf < 0.75}

    # ---- comparison
    comp = compare_invoices(prev, current)
    if comp.get("status") == "ERROR":
        return comp

    ptotal = first(num(comp.get("previous_total")), num(get(prev, "amounts", "total")))
    ctot = first(num(comp.get("current_total")), ctotal)
    change_amt = first(num(comp.get("change_amount")), (ctot - ptotal) if None not in (ctot, ptotal) else None)
    change_pct = first(num(comp.get("change_percentage")), ((change_amt / ptotal * 100) if ptotal else None))

    changes, fx = diff_items(prev, current)
    mine = (diff_findings(prev, current, changes, cur) + tax_findings(prev, current, cur)
            + contract_findings(current, change_pct, contract, cur))
    mine_types = {f["type"] for f in mine}
    for f in comp.get("flags", []):  # keep comparator flags, normalised
        if f.get("type") in mine_types:
            continue
        mine.append(finding(f.get("type", "FLAG"), "UNEXPLAINED" if f.get("severity") == "HIGH" else "INFO",
                            f.get("description", ""), f.get("evidence", ""), None))
    flags = _sorted(mine)
    has_violation = any(f["category"] == "VIOLATION" for f in flags)
    conf, why = confidence(current, flags)

    agreed = (contract or {}).get("agreed_amount")
    cumulative = None
    if agreed:
        cumulative = round(sum(max(0.0, (base_amount(i) or 0.0) - agreed) for i in history[:2] + [current]), 2)

    rec = _leakage(flags)
    result = dict(comp)
    result.update({
        "status": "SUCCESS", "vendor_name": vendor, "currency": cur,
        "previous_total": ptotal, "current_total": ctot, "change_amount": change_amt,
        "change_percentage": change_pct or 0.0,
        "previous_invoice_number": get(prev, "invoice", "number"), "current_invoice_number": number,
        "flags": flags, "line_item_changes": changes,
        "bridge": build_bridge(prev, current, fx, cur),
        "trend": build_trend(history, current, has_violation),
        "tax_check": tax_info(current),
        "memory": _memory(vendor, current, contract, history, current, cur),
        "leakage": {"recoverable": rec,
                    "violations": sum(f["category"] == "VIOLATION" for f in flags),
                    "unexplained": sum(f["category"] == "UNEXPLAINED" for f in flags),
                    "projected_annual": round(max(change_amt or 0.0, 0.0) * 12, 2),
                    "cumulative_overpayment": cumulative},
        "confidence": conf, "confidence_reasons": why, "needs_review": conf < 0.75,
        "ai_audit_note": None, "dispute_email_draft": None, "ai_source": None,
    })

    # ---- AI wording (numbers already computed above)
    if flags and ptotal is not None and ctot is not None:
        result["ai_args"] = {"vendor": vendor, "old_amt": ptotal, "new_amt": ctot,
                             "pct": change_pct or 0.0, "currency": cur, "findings": flags[:6],
                             "clause": (contract or {}).get("clause"), "recoverable": rec or None}
        ai = ai_service.generate_audit_summary(tone=tone, **result["ai_args"])
        result["ai_audit_note"] = ai.get("audit_note")
        result["dispute_email_draft"] = ai.get("dispute_email")
        result["ai_source"] = ai.get("source")
        result["ai_error"] = ai.get("error")

    # ---- persist only after analysis succeeded
    if save and vendor:
        if previous and not database.invoice_exists(vendor, get(previous, "invoice", "number")):
            database.save_invoice(previous)
        database.save_invoice(current)
    return result


def _memory(vendor, inv, contract, history, current, cur):
    t = tax_info(inv)
    agreed = (contract or {}).get("agreed_amount")
    invs = history[:2] + [current]
    return {
        "vendor": vendor,
        "invoices_on_file": (database.count_invoices(vendor) if vendor else 0),
        "last_seen": {"invoice_number": get(inv, "invoice", "number"), "date": get(inv, "invoice", "date"),
                      "total": num(get(inv, "amounts", "total")), "tax_rate": t["rate"], "tax_type": t["kind"],
                      "gstin": t["gstin"], "currency": cur},
        "contract": contract,
        "renewal": renewal_info(contract),
        "cumulative_overpayment": (round(sum(max(0.0, (base_amount(i) or 0.0) - agreed) for i in invs), 2)
                                   if agreed else None),
    }


# ------------------------------------------------------------------ bank reconciliation
def reconcile_bank(csv_bytes: bytes, invoices: list, tol: float = 1.0) -> dict:
    """
    Match bank debits to saved invoices (amount within tol AND vendor word in narration).
    CSV headers are auto-detected: date | description/narration/particulars | amount/debit/withdrawal.
    """
    text = csv_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").strip().lower(): c for c in (reader.fieldnames or [])}

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_desc = col("description", "narration", "particulars", "details")
    c_amt = col("debit", "withdrawal", "amount", "withdrawal amt.")
    c_date = col("date", "txn date", "value date")
    if not c_amt:
        return {"error": "Could not find an amount/debit column in the CSV."}

    debits = []
    for r in reader:
        a = num(r.get(c_amt))
        if a and a > 0:
            debits.append({"date": r.get(c_date) if c_date else "", "description": r.get(c_desc) if c_desc else "", "amount": a})

    matched, used = [], set()
    unpaid = []
    for inv in invoices:
        total, v = inv.get("total_amount"), norm(inv.get("vendor_name"))
        word = v.split()[0] if v else ""
        hit = None
        for i, d in enumerate(debits):
            if i in used:
                continue
            if total is not None and abs(d["amount"] - total) <= tol and (not word or word in norm(d["description"])):
                hit = i
                break
        if hit is None:
            unpaid.append(inv)
        else:
            used.add(hit)
            matched.append({"vendor": inv["vendor_name"], "invoice": inv["invoice_number"],
                            "invoice_total": total, "debit": debits[hit]["amount"], "date": debits[hit]["date"]})
    orphans = [d for i, d in enumerate(debits) if i not in used]
    return {"matched": matched, "invoices_without_debit": unpaid, "debits_without_invoice": orphans}


# ------------------------------------------------------------------ report
def build_report_md(r: dict) -> str:
    cur = r.get("currency", "INR")
    lk = r.get("leakage", {})
    L = [f"# Audit Report: {r.get('vendor_name') or 'Unknown vendor'}", ""]
    L += ["## 1. Executive summary",
          f"- Status: **{r.get('status')}**",
          f"- Potentially recoverable: **{money(lk.get('recoverable'), cur)}**",
          f"- Violations: {lk.get('violations', 0)} | Unexplained: {lk.get('unexplained', 0)}",
          f"- Projected annual impact if the increase repeats monthly: {money(lk.get('projected_annual'), cur)}",
          f"- Extraction confidence: {r.get('confidence')} {'(NEEDS HUMAN REVIEW: ' + ', '.join(r.get('confidence_reasons', [])) + ')' if r.get('needs_review') else ''}",
          "", "Top findings:"]
    L += [f"{i}. [{f['category']}] {f['description']}: {f['evidence']}" for i, f in enumerate(r.get("flags", [])[:3], 1)] or ["None"]
    if r.get("trend"):
        t = r["trend"]
        L += ["", "## 2. Comparison table", "| Item | " + " | ".join(t["columns"]) + " | Delta |",
              "|---|" + "---|" * (len(t["columns"]) + 1)]
        for row in t["rows"]:
            vals = " | ".join("-" if v is None else f"{v:,.2f}" for v in row["values"])
            d = "-" if row["delta"] is None else format(row["delta"], "+,.2f")
            L.append(f"| {row['item']} | {vals} | {d} ({row['status']}) |")
    if r.get("bridge"):
        b = r["bridge"]
        L += ["", "### Where the increase came from", f"- Previous total: {money(b['start'], cur)}"]
        L += [f"- {s['label']}: {s['value']:+,.2f}" for s in b["steps"]]
        L += [f"- Current total: {money(b['end'], cur)}"]
    tx = r.get("tax_check")
    if tx:
        L += ["", "## 3. Tax analysis", f"- Rate: {tx['rate']}% | Type: {tx['kind'] or 'n/a'} | GSTIN: {tx['gstin'] or 'missing'}",
              f"- Invoiced tax: {money(tx['invoiced'], cur)} vs expected: {money(tx['expected'], cur)}"]
    L += ["", "## 4. All findings (violation > unexplained > info)"]
    L += [f"- **{f['category']}** {f['type']}: {f['description']}. {f['evidence']}" for f in r.get("flags", [])] or ["None"]
    if r.get("dispute_email_draft"):
        L += ["", "## 5. Recommended action: dispute email draft", "", r["dispute_email_draft"]]
    return "\n".join(L)
