from extractor import extract_pdf_text
import re
import json


def extract_invoice_number(text):
    patterns = [
        r"Invoice\s*(?:No|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-]+)",
        r"Bill\s*(?:No|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-]+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(1).strip()

    return None


def extract_invoice_date(text):
    pattern = (
        r"(?:Invoice\s*)?Date\s*[:\-]?\s*"
        r"(?:\n\s*)?"
        r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    )

    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        return match.group(1).strip()

    return None


def extract_total(text):
    patterns = [
        # Most specific/common labels first
        r"(?:TOTAL\s+DUE)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:AMOUNT\s+DUE)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:BALANCE\s+DUE)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:AMOUNT\s+PAYABLE)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:GRAND\s+TOTAL)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:TOTAL\s+AMOUNT)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:INVOICE\s+TOTAL)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        r"(?:NET\s+AMOUNT)\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)",

        # Plain "Total" should come LAST
        r"(?:^|\n)\s*TOTAL\s*[:\-]?\s*(?:\n\s*)?[₹$€£]?\s*([\d,]+(?:\.\d+)?)"
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            amount = match.group(1)
            amount = amount.replace(",", "")

            return float(amount)

    return None


def extract_currency(text):

    if "₹" in text or re.search(r"\bINR\b", text, re.IGNORECASE):
        return "INR"

    if "$" in text or re.search(r"\bUSD\b", text, re.IGNORECASE):
        return "USD"

    if "€" in text or re.search(r"\bEUR\b", text, re.IGNORECASE):
        return "EUR"

    if "£" in text or re.search(r"\bGBP\b", text, re.IGNORECASE):
        return "GBP"

    return None


def extract_vendor_name(text):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for i, line in enumerate(lines):

        if re.fullmatch(r"Terms\s*:?", line, re.IGNORECASE):

            # Terms value is the next line
            # Vendor name is the line after that
            if i + 2 < len(lines):
                return lines[i + 2]

    return None
def extract_tax_id(text):

    pattern = r"Tax\s*ID\s*[:\-]?\s*([A-Za-z0-9\-]+)"

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return None
def extract_due_date(text):

    pattern = (
        r"Due\s+Date\s*[:\-]?\s*"
        r"(?:\n\s*)?"
        r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return None

def create_invoice_data(text):

    invoice_data = {
        "document_type": "invoice",

        "vendor": {
            "name": extract_vendor_name(text),
            "address": None,
            "tax_id": extract_tax_id(text)
        },

        "invoice": {
            "number": extract_invoice_number(text),
            "date": extract_invoice_date(text),
            "due_date": extract_due_date(text),
            "currency": extract_currency(text)
        },

        "customer": {
            "name": None,
            "address": None
        },

        "items": [],

        "amounts": {
            "subtotal": None,
            "discount": None,
            "tax": None,
            "total": extract_total(text)
        }
    }

    return invoice_data


if __name__ == "__main__":

    file_path = "samples/invoice_2_bluepeak_it_services.pdf"

    pages = extract_pdf_text(file_path)

    full_text = ""

    for page in pages:
        full_text += page["text"] + "\n"
    # print("\n========== RAW EXTRACTED TEXT ==========\n")
    # print(full_text)
    # print("\n========================================\n")    

    invoice = create_invoice_data(full_text)

    print(json.dumps(invoice, indent=4))