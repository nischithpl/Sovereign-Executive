import re
from datetime import datetime

try:
    from .extractor import extract_pdf_text
except ImportError:
    from extractor import extract_pdf_text




def normalize_date(date_string):
    if not date_string:
        return None

    formats = [
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_string.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_string

def _to_float(value):
    if value is None:
        return None

    value = str(value).strip()

    # Remove currency symbols, commas and other text
    cleaned = re.sub(r"[^\d.]", "", value)

    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_vendor_name(text):
    patterns = [
        # Vendor: BluePeak IT Services Pvt Ltd
        r'(?:Vendor|Supplier|Service Provider)\s*(?:Name)?\s*[:\-]\s*(.+)',

        # ... and BluePeak IT Services Pvt Ltd ("Vendor")
        r'\band\s+(.+?)\s*\("Vendor"\)',

        # BluePeak IT Services Pvt Ltd ("Vendor")
        r'\b(.+?)\s*\("Vendor"\)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def extract_agreed_price(text):
    patterns = [
        r'agreed\s+base\s+price.*?(?:is|:)\s*(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',

        r'(?:monthly|monthly subscription|subscription)\s+'
        r'(?:fee|price|charge).*?(?:of|is|:)\s*'
        r'(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',

        r'(?:agreed|contracted|fixed)\s+'
        r'(?:price|amount|fee).*?(?:of|is|:)\s*'
        r'(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',

        r'(?:price|fee|amount)\s*(?:of|is|:)\s*'
        r'(?:₹|Rs\.?|INR)?\s*([\d,]+(?:\.\d+)?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return _to_float(match.group(1))

    return None


def extract_max_annual_increase(text):
    patterns = [
        r'annual\s+price\s+increase.*?shall\s+not\s+exceed\s+(\d+(?:\.\d+)?)\s*%',

        r'(?:annual|yearly)\s+'
        r'(?:increase|increment|escalation).*?'
        r'(?:not\s+exceed|capped\s+at|limited\s+to)\s*'
        r'(\d+(?:\.\d+)?)\s*%',

        r'(?:increase|increment|escalation).*?'
        r'(?:not\s+exceed|capped\s+at|limited\s+to)\s*'
        r'(\d+(?:\.\d+)?)\s*%',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return float(match.group(1))

    return None


def extract_renewal_date(text):
    patterns = [
        # ending on 31 August 2027 (the "Renewal Date")
        r'ending\s+on\s+'
        r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})'
        r'\s*\(\s*["\']?Renewal Date',

        # renewal date: 31 August 2027
        r'(?:renewal\s+date|renewal).*?'
        r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})',

        # renewal date: 2027-08-31
        r'(?:renewal\s+date|renewal).*?'
        r'(\d{4}-\d{2}-\d{2})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    return None


def extract_notice_days(text):
    patterns = [
        r'at\s+least\s+(\d+)\s+days?.{0,50}notice',
        r'(\d+)\s*days?\s*(?:written\s+)?notice',
        r'notice\s*(?:period)?\s*(?:of|:)?\s*(\d+)\s*days?',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))

    # Handle written numbers such as "thirty (30) days"
    written_numbers = {
        "thirty": 30,
        "sixty": 60,
        "ninety": 90,
    }

    for word, number in written_numbers.items():
        if re.search(
            rf'\b{word}\s*\(\s*{number}\s*\)\s*days?',
            text,
            re.IGNORECASE
        ):
            return number

    return None


def extract_price_clause(text):
    patterns = [
        r"((?:Clause|Section)\s+[\w.\-]+\s*[:\-]?.{0,300}"
        r"(?:price|fee|cost|rate|increase|increment|escalation).{0,300})",

        r"((?:price|pricing|fee|rate)\s+(?:shall|will|is|remains|remain)"
        r".{0,300})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            clause = re.sub(r"\s+", " ", match.group(1)).strip()
            return clause[:600]

    return None


def parse_contract_text(text):
    """
    Extract contractual ground-truth fields from contract text.

    This parser is intentionally conservative.
    Missing fields are returned as None instead of guessed.
    """

    return {
        "vendor_name": extract_vendor_name(text),
        "agreed_price": extract_agreed_price(text),
        "max_annual_increase": extract_max_annual_increase(text),
        "renewal_date": extract_renewal_date(text),
        "notice_days": extract_notice_days(text),
        "price_clause": extract_price_clause(text),
    }


def parse_contract_bytes(data):
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(data)
        temp_path = tmp.name

    try:
        text = extract_pdf_text(temp_path)

        if isinstance(text, list):
           text = "\n".join(
            page.get("text", "")
            for page in text
            if isinstance(page, dict)
    )
    finally:
        os.unlink(temp_path)


    if not text or not text.strip():
        raise ValueError("Could not extract readable text from the contract PDF.")

    result = parse_contract_text(text)

    result["renewal_date"] = normalize_date(
      result.get("renewal_date")
)

    # Keep extracted text available for debugging/review
    result["_text"] = text

    return result