import re
from datetime import datetime
 
try:
    from .extractor import extract_pdf_text
except ImportError:
    from extractor import extract_pdf_text
 
_CUR = r"(?:₹|Rs\.?\s*|INR\s*|\$|USD\s*|€|EUR\s*|£|GBP\s*)"
_AMT = r"([\d,]+(?:\.\d+)?)"
_STOP = {"the", "a", "an", "of", "for", "per", "and", "plan", "fee", "charge", "charges",
         "service", "services", "monthly", "annual", "customer", "vendor", "shall", "pay"}
 
_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_DATE_RE = re.compile(
    r"(\d{1,2}\s+(?:%s)\s+\d{4}|(?:%s)\s+\d{1,2},\s+\d{4})" % ("|".join(_MONTHS), "|".join(_MONTHS)),
    re.IGNORECASE,
)
 
 
def _tokens(text):
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOP}
 
 
def _parse_date(raw):
    for fmt in ("%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw.strip().title(), fmt).date().isoformat()
        except ValueError:
            continue
    return None
 
 
def _split_clauses(pages):
    """
    Yields (page, clause_no, text). A clause starts at '4.2 ' style numbering;
    unnumbered paragraphs are yielded with clause_no=None.
    """
    for page in pages:
        text = page["text"]
        parts = re.split(r"\n(?=\s*\d+(?:\.\d+)+\.?\s)", text)
        for part in parts:
            part = re.sub(r"\s*\n\s*", " ", part).strip()
            if len(part) < 25:
                continue
            m = re.match(r"(\d+(?:\.\d+)+)\.?\s+(.*)", part)
            yield page["page"], (m.group(1) if m else None), (m.group(2) if m else part)
 
 
def _cite(page, clause, text, **extra):
    return {"page": page, "clause": clause, "text": text[:400], **extra}
 
 
def extract_contract_terms(pages):
    """
    pages: output of extract_pdf_text(). Returns a dict of terms, each with citation(s).
    Missing terms are simply absent / empty, never guessed.
    """
    terms = {
        "price_points": [],       # [{amount, unit, item_hint, page, clause, text}]
        "price_increase": None,   # {max_percent, notice_days, frequency, consent_for_new_fees, ...}
        "fixed_price_months": None,
        "tax": None,              # {rate, split_when_same_state, ...}
        "payment_terms": None,    # {days}
        "renewal": None,          # {auto, notice_days, term_end, ...}
        "liability_cap": None,
        "discounts": [],
    }
 
    for page, clause, text in _clause_iter(pages):
        low = text.lower()
 
        # ---- price points: "<item> ... ₹40,000 per month / per seat per month / per GB"
        for m in re.finditer(rf"{_CUR}\s*{_AMT}\s*(per\s+[a-z]+(?:\s+per\s+[a-z]+)?)?", text, re.IGNORECASE):
            amount = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            if "discount" in low and "appl" in low:
                terms["discounts"].append(_cite(page, clause, text, amount=amount, unit=unit or "per month"))
                continue
            if unit and not re.search(r"liab|exceed", low):
                terms["price_points"].append(
                    _cite(page, clause, text, amount=amount, unit=unit, item_hint=sorted(_tokens(text)))
                )
 
        # ---- fixed price period
        m = re.search(r"fixed\s+for\s+(?:the\s+first\s+)?(\w+)\s+months", low)
        if m:
            words = {"six": 6, "twelve": 12, "twenty-four": 24, "eighteen": 18, "three": 3}
            n = int(m.group(1)) if m.group(1).isdigit() else words.get(m.group(1))
            if n:
                terms["fixed_price_months"] = _cite(page, clause, text, months=n)
 
        # ---- price increase clause: cap, notice, frequency, consent
        if re.search(r"revise|increase|adjust", low) and re.search(r"fee|price|charge", low):
            cap = re.search(r"(?:not\s+more\s+than|not\s+exceed(?:ing)?|up\s+to|maximum\s+of|capped\s+at)\s+(\d+(?:\.\d+)?)\s*%", low)
            notice = re.search(r"(\d+)\s+days?(?:'|’)?\s+(?:prior\s+)?(?:written\s+)?notice", low) or \
                     re.search(r"(?:at\s+least|minimum\s+of)\s+(\d+)\s+days", low)
            if cap or notice:
                terms["price_increase"] = _cite(
                    page, clause, text,
                    max_percent=float(cap.group(1)) if cap else None,
                    notice_days=int(notice.group(1)) if notice else None,
                    once_per_year=bool(re.search(r"once\s+per\s+year|annual", low)),
                    consent_for_new_fees=bool(re.search(r"new\s+fees?.*consent|consent.*new\s+fees?", low)),
                )
 
        # ---- tax
        m = re.search(r"(?:gst|vat|tax)[^.]{0,40}?(\d+(?:\.\d+)?)\s*%", low)
        if m:
            terms["tax"] = _cite(page, clause, text, rate=float(m.group(1)),
                                 split_when_same_state=bool(re.search(r"cgst.*sgst", low)))
 
        # ---- payment terms
        m = re.search(r"net\s*(\d{1,3})", low) or re.search(r"within\s+(\d{1,3})\s+days", low)
        if m and re.search(r"payable|invoice|payment", low):
            terms["payment_terms"] = _cite(page, clause, text, days=int(m.group(1)))
 
        # ---- renewal
        if re.search(r"auto(?:matically|-)?\s*renew", low):
            notice = re.search(r"(\d+)\s+days", low)
            end = _DATE_RE.search(text)
            terms["renewal"] = _cite(
                page, clause, text, auto=True,
                notice_days=int(notice.group(1)) if notice else None,
                term_end=_parse_date(end.group(1)) if end else None,
            )
 
        # ---- liability cap
        if re.search(r"liabilit", low) and re.search(r"not\s+exceed|cap|limited\s+to", low):
            terms["liability_cap"] = _cite(page, clause, text)
 
    return terms
 
 
def _clause_iter(pages):
    return _split_clauses(pages)
 
 
def extract_contract_file(path):
    pages = extract_pdf_text(path)
    return pages, extract_contract_terms(pages)
 
 
def guess_vendor(pages, known_vendors):
    """Match any already-seen vendor name against contract text (for auto-linking)."""
    blob = " ".join(p["text"] for p in pages).lower()
    blob = re.sub(r"\s+", " ", blob)
    for v in known_vendors:
        if v and v.lower() in blob:
            return v
    return None
 
 
def match_price_point(item_description, price_points):
    """
    Best contract price point for an invoice line item, by keyword overlap.
    Requires >=50% of the item's meaningful words to appear in the clause.
    """
    item_tokens = _tokens(item_description)
    if not item_tokens:
        return None
    best, best_score = None, 0.0
    for pp in price_points:
        overlap = len(item_tokens & set(pp["item_hint"]))
        score = overlap / len(item_tokens)
        if score > best_score:
            best, best_score = pp, score
    return best if best_score >= 0.5 else None
 
 
if __name__ == "__main__":
    import json
    print(json.dumps(extract_contract_file("samples/contract_bluepeak.pdf")[1], indent=2, ensure_ascii=False))
 
