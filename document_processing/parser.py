from extractor import extract_pdf_text
import re
import json


def extract_invoice_number(text):

    patterns = [
        r"Invoice\s*(?:No|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-]+)",
        r"Bill\s*(?:No|Number|#)\s*[:\-]?\s*([A-Za-z0-9\-]+)"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return match.group(1)

    return None
def extract_invoice_date(text):

    pattern = r"(?:Invoice\s*)?Date\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"

    match = re.search(
        pattern,
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)

    return None  
def extract_total(text):

    patterns = [
        r"(?:Grand\s+Total|Total\s+Amount|Amount\s+Payable|Net\s+Amount)\s*[:\-]?\s*[₹$€£]?\s*([\d,]+(?:\.\d+)?)"
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

    if "₹" in text or "INR" in text:
        return "INR"

    if "$" in text or "USD" in text:
        return "USD"

    if "€" in text or "EUR" in text:
        return "EUR"

    if "£" in text or "GBP" in text:
        return "GBP"

    return None
def create_invoice_data(text):

    invoice_data = {
        "document_type": "invoice",

        "vendor": {
            "name": None,
            "address": None,
            "tax_id": None
        },

        "invoice": {
            "number": extract_invoice_number(text),
            "date": extract_invoice_date(text),
            "due_date": None,
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

    file_path = "document_processing\samples\invoice_2_bluepeak_it_services.pdf"

    pages = extract_pdf_text(file_path)

    full_text = ""

    for page in pages:
        full_text += page["text"] + "\n"

    invoice = create_invoice_data(full_text)

    print(json.dumps(invoice, indent=4))

  