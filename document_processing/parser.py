import json
import re

try:
    from .extractor import extract_pdf_text
except ImportError:  # run as a plain script
    from extractor import extract_pdf_text

CUR = r"Rs\.?|INR|USD|EUR|GBP|[^\w\s.,()\-%:/]{0,2}"
NUM = r"-?\(?[\d,]+(?:\.\d+)?\)?"
GSTIN_RE = r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"


def _to_float(raw):
    """'1,234.50' -> 1234.5 ; '(50.00)' -> -50.0 ; '-50' -> -50.0"""
    if raw is None:
        return None
    raw = str(raw).strip()
    neg = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    cleaned = re.sub(r"[^\d.]", "", raw)
    if not cleaned or cleaned == ".":
        return None
    value = float(cleaned)
    return -value if neg else value


def _is_number_line(line):
    return bool(re.fullmatch(rf"\s*(?:{CUR})?\s*{NUM}\s*%?\s*", line)) and any(
        c.isdigit() for c in line
    )


def parse_date_str(raw):
    """Best-effort date string -> 'YYYY-MM-DD' (None if unparseable)."""
    from datetime import datetime
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d",
                "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# Header fields (unchanged behaviour)
# --------------------------------------------------------------------------
def extract_invoice_number(text):
    patterns = [
        r"Invoice\s*(?:No|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)",
        r"Bill\s*(?:No|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-/]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


_DATE = (
    r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})"
)


def extract_invoice_date(text):
    pattern = r"(?<!Due )(?:Invoice\s*)?Date\s*[:\-]?\s*(?:\n\s*)?" + _DATE
    for match in re.finditer(pattern, text, re.IGNORECASE):
        # skip "Due Date"
        start = max(0, match.start() - 5)
        if "due" in text[start:match.start() + 4].lower():
            continue
        return match.group(1).strip()
    return None


def extract_due_date(text):
    pattern = r"Due\s+Date\s*[:\-]?\s*(?:\n\s*)?" + _DATE
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_total(text):
    labels = [
        r"TOTAL\s+DUE", r"AMOUNT\s+DUE", r"BALANCE\s+DUE", r"AMOUNT\s+PAYABLE",
        r"GRAND\s+TOTAL", r"TOTAL\s+AMOUNT", r"INVOICE\s+TOTAL", r"NET\s+AMOUNT",
    ]
    for label in labels:
        pattern = rf"(?:{label})\s*[:\-]?\s*(?:\n\s*)?(?:{CUR})\s*([\d,]+(?:\.\d+)?)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
    # plain "Total" last (must not be "Sub total")
    match = re.search(
        rf"(?:^|\n)\s*TOTAL\s*[:\-]?\s*(?:\n\s*)?(?:{CUR})\s*([\d,]+(?:\.\d+)?)",
        text, re.IGNORECASE,
    )
    if match:
        return float(match.group(1).replace(",", ""))
    return None


def extract_currency(text):
    if "₹" in text or re.search(r"\bINR\b|\bRs\.", text, re.IGNORECASE):
        return "INR"
    if "$" in text or re.search(r"\bUSD\b", text, re.IGNORECASE):
        return "USD"
    if "€" in text or re.search(r"\bEUR\b", text, re.IGNORECASE):
        return "EUR"
    if "£" in text or re.search(r"\bGBP\b", text, re.IGNORECASE):
        return "GBP"
    return None


def extract_vendor_name(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Lines that should NEVER be considered a vendor name
    ignored_patterns = [
        r"^(tax\s+)?invoice$",
        r"^invoice\s*(no|number)?\s*[:#-]?",
        r"^date\s*[:#-]?",
        r"^due\s*date\s*[:#-]?",
        r"^payment\s*terms?\s*[:#-]?",
        r"^terms\s*[:#-]?",
        r"^terms\s+net\b",
        r"^gstin\s*[:#-]?",
        r"^tax\s*id\s*[:#-]?",
        r"^customer\s*[:#-]?",
        r"^bill\s*to\s*[:#-]?",
        r"^ship\s*to\s*[:#-]?",
        r"^from\s*[:#-]?$",
        r"^vendor\s*[:#-]?$",
        r"^supplier\s*[:#-]?$",
        r"^billed\s+by\s*[:#-]?$",
    ]

    def is_metadata(line):
        return any(
            re.match(pattern, line, re.IGNORECASE)
            for pattern in ignored_patterns
        )

    def clean_candidate(line):
        line = line.strip()

        # Remove common labels if vendor is on the same line
        line = re.sub(
            r"^(?:From|Vendor|Supplier|Billed\s+By)\s*:\s*",
            "",
            line,
            flags=re.IGNORECASE,
        )

        # Remove trailing invoice/customer labels accidentally attached
        # to the vendor name during PDF extraction.
        line = re.sub(
            r"\s+(?:BILL\s+TO|CUSTOMER)\s*:?\s*$",
            "",
            line,
            flags=re.IGNORECASE,
        )

        return line.strip()

    # ---------------------------------------------------------
    # 1. Explicit vendor labels
    # ---------------------------------------------------------
    for i, line in enumerate(lines):
        m = re.match(
            r"^(?:From|Vendor|Supplier|Billed\s+By)\s*:?\s*(.*)$",
            line,
            re.IGNORECASE,
        )

        if m:
            candidate = clean_candidate(m.group(1))

            if candidate and not is_metadata(candidate):
                return candidate

            # Vendor name may be on the next line
            if i + 1 < len(lines):
                candidate = clean_candidate(lines[i + 1])

                if candidate and not is_metadata(candidate):
                    return candidate

    # ---------------------------------------------------------
    # 2. Look for a company-style name
    # ---------------------------------------------------------
    company_patterns = [
        r"\bPvt\.?\s*Ltd\.?\b",
        r"\bPrivate\s+Limited\b",
        r"\bLimited\b",
        r"\bLtd\.?\b",
        r"\bLLC\b",
        r"\bInc\.?\b",
        r"\bCorporation\b",
        r"\bCorp\.?\b",
        r"\bSolutions\b",
        r"\bServices\b",
        r"\bTechnologies\b",
        r"\bTechnology\b",
    ]

    for line in lines:
        candidate = clean_candidate(line)

        if not candidate or is_metadata(candidate):
            continue

        if any(
            re.search(pattern, candidate, re.IGNORECASE)
            for pattern in company_patterns
        ):
            return candidate

    # ---------------------------------------------------------
    # 3. Fallback: first meaningful non-metadata line
    # ---------------------------------------------------------
    for line in lines:
        candidate = clean_candidate(line)

        if not candidate:
            continue

        if is_metadata(candidate):
            continue

        # Ignore GSTIN-like values
        if re.fullmatch(
            r"[A-Z]{2}\d{2}[A-Z0-9]{10,}",
            candidate,
            re.IGNORECASE,
        ):
            continue

        # Ignore invoice-number-like values
        if re.match(
            r"^[A-Z]{2,}[-/]\d{2,}",
            candidate,
            re.IGNORECASE,
        ):
            continue

        return candidate

    return None

def extract_tax_id(text):
    match = re.search(r"Tax\s*ID\s*[:\-]?\s*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_gstins(text):
    """All GSTINs in the document, in order (vendor first, customer second usually)."""
    return list(dict.fromkeys(re.findall(GSTIN_RE, text)))


def extract_payment_terms(text):
    match = re.search(r"\bNet\s*(\d{1,3})\b", text, re.IGNORECASE)
    if match:
        return f"Net {match.group(1)}"
    match = re.search(r"Due\s+(?:on\s+)?(?:upon\s+)?receipt", text, re.IGNORECASE)
    return "Due on receipt" if match else None


def extract_po_number(text):
    match = re.search(r"P\.?O\.?\s*(?:No|Number|#)?\s*[:\-]?\s*([A-Za-z0-9\-]{3,})", text)
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# Amounts and taxes
# --------------------------------------------------------------------------
def _amount_after(label_pattern, text):
    pattern = rf"(?:^|\n)\s*(?:{label_pattern})\s*[:\-]?\s*(?:\n\s*)?(?:{CUR})\s*({NUM})"
    match = re.search(pattern, text, re.IGNORECASE)
    return _to_float(match.group(1)) if match else None


def extract_subtotal(text):
    return _amount_after(r"Sub\s*-?\s*total|Taxable\s+(?:Value|Amount)|Net\s+Total", text)


def extract_discount(text):
    value = _amount_after(r"Discount(?:\s*\([^)]*\))?|Promo(?:tion)?\s+Credit|Credit", text)
    return abs(value) if value else None


_TAX_LABEL = r"CGST|SGST|UTGST|IGST|GST|VAT|Sales\s+Tax|Service\s+Tax|Tax"


def extract_taxes(text):
    """
    Returns list of {type, rate, amount}. Handles:
        CGST (9%)   450.00        SGST @ 9%: 450.00
        IGST 18%                  1,800.00       (amount on next line)
        Tax (10%) : $50.00        VAT 20% 100.00
    Falls back to an un-rated "Tax  50.00" line if no rated line is present.
    """
    taxes = []
    seen = set()
    rated = re.compile(
        rf"(?:^|\n)\s*({_TAX_LABEL})\s*(?:\(|@)?\s*(\d+(?:\.\d+)?)\s*%\s*\)?\s*[:\-]?\s*"
        rf"(?:\n\s*)?(?:{CUR})\s*({NUM})",
        re.IGNORECASE,
    )
    for m in rated.finditer(text):
        tax_type = re.sub(r"\s+", " ", m.group(1)).upper()
        rate = float(m.group(2))
        amount = _to_float(m.group(3))
        key = (tax_type, rate, amount)
        if amount is None or key in seen:
            continue
        seen.add(key)
        taxes.append({"type": tax_type, "rate": rate, "amount": amount})

    if not taxes:
        plain = re.search(
            rf"(?:^|\n)\s*({_TAX_LABEL})\s*[:\-]?\s*(?:\n\s*)?(?:{CUR})\s*({NUM})",
            text, re.IGNORECASE,
        )
        if plain:
            amount = _to_float(plain.group(2))
            if amount is not None:
                taxes.append({
                    "type": re.sub(r"\s+", " ", plain.group(1)).upper(),
                    "rate": None,
                    "amount": amount,
                })
    return taxes


# --------------------------------------------------------------------------
# Line items
# --------------------------------------------------------------------------
_TABLE_END = re.compile(
    r"^(sub\s*-?\s*total|taxable|total|discount|cgst|sgst|igst|gst|vat|tax|"
    r"amount\s+due|balance|grand|notes?|payment|bank|thank)",
    re.IGNORECASE,
)
_TABLE_HEAD = re.compile(r"^(description|item|particulars|service|details)\b", re.IGNORECASE)
_HEAD_WORDS = re.compile(
    r"^(qty|quantity|units?|rate|price|unit\s*price|amount|total|hsn|sac|line\s*total)\b",
    re.IGNORECASE,
)


def _row_from_numbers(desc, nums):
    """Map trailing numeric cells to (quantity, unit_price, amount)."""
    nums = [n for n in nums if n is not None]
    if not nums:
        return None
    if len(nums) >= 3:
        qty, unit, amount = nums[-3], nums[-2], nums[-1]
    elif len(nums) == 2:
        qty, unit, amount = None, nums[0], nums[1]
    else:
        qty, unit, amount = None, None, nums[0]
    if qty is None:
        qty = 1.0 if unit is None or unit == amount else (round(amount / unit, 4) if unit else 1.0)
    if unit is None:
        unit = round(amount / qty, 4) if qty else amount
    return {
        "description": desc.strip(),
        "quantity": qty,
        "unit_price": unit,
        "amount": amount,
    }


def extract_line_items(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # locate the table: from header row to the first totals-like line
    start = None
    for i, line in enumerate(lines):
        if _TABLE_HEAD.match(line):
            start = i + 1
            break
    if start is None:
        return []

    # skip remaining column header cells (Qty / Unit Price / Amount ...)
    while start < len(lines) and _HEAD_WORDS.match(lines[start]):
        start += 1

    block = []
    for line in lines[start:]:
        if _TABLE_END.match(line) and not _is_number_line(line):
            break
        block.append(line)

    items = []
    desc_parts, nums = [], []

    def flush():
        nonlocal desc_parts, nums
        if desc_parts and nums:
            row = _row_from_numbers(" ".join(desc_parts), nums)
            if row:
                items.append(row)
        desc_parts, nums = [], []

    for line in block:
        # single-line row: "Cloud Hosting   2   50.00   100.00"
        m = re.match(
            rf"^(.*?[A-Za-z].*?)\s+((?:(?:{CUR})\s*{NUM}\s+){{0,2}}(?:{CUR})\s*{NUM})\s*$", line
        )
        if m and not _is_number_line(line):
            flush()
            cells = re.findall(rf"(?:{CUR})\s*({NUM})", m.group(2))
            row = _row_from_numbers(m.group(1), [_to_float(c) for c in cells])
            if row:
                items.append(row)
            continue

        if _is_number_line(line):
            nums.append(_to_float(re.sub(r"[%]", "", line)))
            continue

        # a text line: if we already have numbers, the previous row is complete
        if nums:
            flush()
        desc_parts.append(line)
    flush()

    return items


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------
def _confidence(data):
    """Crude but honest: how many key fields we could read + arithmetic checks."""
    warnings = []
    score = 0
    checks = 0

    def check(ok, msg):
        nonlocal score, checks
        checks += 1
        if ok:
            score += 1
        else:
            warnings.append(msg)

    check(data["vendor"]["name"], "Vendor name not found")
    check(data["invoice"]["number"], "Invoice number not found")
    check(data["invoice"]["date"], "Invoice date not found")
    check(data["amounts"]["total"] is not None, "Total not found")
    check(data["amounts"]["subtotal"] is not None, "Subtotal not found")
    check(data["items"], "No line items could be read")

    a = data["amounts"]
    if data["items"] and a["subtotal"] is not None:
        item_sum = round(sum(i["amount"] for i in data["items"]), 2)
        check(abs(item_sum - a["subtotal"]) < 0.02 + 0.001 * a["subtotal"],
              f"Line items sum to {item_sum:.2f} but subtotal is {a['subtotal']:.2f}")
    if a["subtotal"] is not None and a["total"] is not None:
        expected = a["subtotal"] - (a["discount"] or 0) + (a["tax"] or 0)
        check(abs(expected - a["total"]) < 0.02 + 0.001 * a["total"],
              f"Subtotal - discount + tax = {expected:.2f} but total is {a['total']:.2f}")

    return round(score / checks, 2), warnings


def create_invoice_data(text):
    taxes = extract_taxes(text)
    tax_total = round(sum(t["amount"] for t in taxes), 2) if taxes else None
    items = extract_line_items(text)
    subtotal = extract_subtotal(text)
    if subtotal is None and items:
        subtotal = round(sum(i["amount"] for i in items), 2)
    gstins = extract_gstins(text)

    invoice_data = {
        "document_type": "invoice",
        "vendor": {
            "name": extract_vendor_name(text),
            "address": None,
            "tax_id": extract_tax_id(text),
            "gstin": gstins[0] if gstins else None,
        },
        "invoice": {
            "number": extract_invoice_number(text),
            "date": extract_invoice_date(text),
            "due_date": extract_due_date(text),
            "currency": extract_currency(text),
            "payment_terms": extract_payment_terms(text),
            "po_number": extract_po_number(text),
        },
        "customer": {
            "name": None,
            "address": None,
            "gstin": gstins[1] if len(gstins) > 1 else None,
        },
        "items": items,
        "amounts": {
            "subtotal": subtotal,
            "discount": extract_discount(text),
            "tax": tax_total,
            "total": extract_total(text),
        },
        "taxes": taxes,
    }
    confidence, warnings = _confidence(invoice_data)
    invoice_data["meta"] = {"confidence": confidence, "warnings": warnings}
    return invoice_data


def parse_pdf_file(file_path):
    pages = extract_pdf_text(file_path)
    full_text = "\n".join(p["text"] for p in pages)
    return create_invoice_data(full_text)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("    python -m document_processing.parser <pdf_path>")
        raise SystemExit(1)

    pdf_path = sys.argv[1]

    try:
        result = parse_pdf_file(pdf_path)
        print(json.dumps(result, indent=4, ensure_ascii=False))
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)