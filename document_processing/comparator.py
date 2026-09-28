from extractor import extract_pdf_text
from parser import create_invoice_data
def compare_invoices(previous, current):

    previous_total = previous["amounts"]["total"]
    current_total = current["amounts"]["total"]

    flags = []

    # Check if totals are available
    if previous_total is None or current_total is None:
        return {
            "status": "ERROR",
            "message": "Unable to compare invoices because total amount is missing.",
            "flags": []
        }

    # Calculate change
    change_amount = current_total - previous_total

    # Calculate percentage change
    if previous_total != 0:
        change_percentage = (
            change_amount / previous_total
        ) * 100
    else:
        change_percentage = 0

    # Detect price increase
    if change_percentage > 10:

        flags.append({
            "type": "PRICE_INCREASE",
            "severity": "HIGH",
            "description": (
                f"Invoice amount increased by "
                f"{change_percentage:.2f}%."
            ),
            "evidence": (
                f"Previous: {previous_total:.2f} "
                f"→ Current: {current_total:.2f}"
            )
        })

    elif change_percentage > 0:

        flags.append({
            "type": "PRICE_INCREASE",
            "severity": "MEDIUM",
            "description": (
                f"Invoice amount increased by "
                f"{change_percentage:.2f}%."
            ),
            "evidence": (
                f"Previous: {previous_total:.2f} "
                f"→ Current: {current_total:.2f}"
            )
        })

    return {
        "status": "SUCCESS",

        "vendor_name": current["vendor"]["name"],

        "previous_invoice_number": (
            previous["invoice"]["number"]
        ),

        "current_invoice_number": (
            current["invoice"]["number"]
        ),

        "currency": current["invoice"]["currency"],

        "previous_total": previous_total,

        "current_total": current_total,

        "change_amount": round(change_amount, 2),

        "change_percentage": round(
            change_percentage,
            2
        ),

        "flags": flags
    }


if __name__ == "__main__":

    previous_file = "samples/invoice_2_bluepeak_it_services.pdf"
    current_file = "samples/invoice_2b_bluepeak_it_services.pdf"

    # Extract previous invoice
    previous_pages = extract_pdf_text(previous_file)

    previous_text = ""

    for page in previous_pages:
        previous_text += page["text"] + "\n"

    previous_invoice = create_invoice_data(previous_text)

    # Extract current invoice
    current_pages = extract_pdf_text(current_file)

    current_text = ""

    for page in current_pages:
        current_text += page["text"] + "\n"

    current_invoice = create_invoice_data(current_text)

    # Compare
    result = compare_invoices(
        previous_invoice,
        current_invoice
    )

    print("\n========== INVOICE COMPARISON ==========\n")

    print(f"Vendor: {result['vendor_name']}")

    print(
        f"Previous invoice: "
        f"{result['previous_invoice_number']}"
    )

    print(
        f"Current invoice: "
        f"{result['current_invoice_number']}"
    )

    print(
        f"\nPrevious total: "
        f"{result['currency']} "
        f"{result['previous_total']:.2f}"
    )

    print(
        f"Current total: "
        f"{result['currency']} "
        f"{result['current_total']:.2f}"
    )

    print(
        f"Change: "
        f"{result['currency']} "
        f"{result['change_amount']:.2f}"
    )

    print(
        f"Percentage change: "
        f"{result['change_percentage']:.2f}%"
    )

    print("\n========== FLAGS ==========\n")

    if result["flags"]:

        for flag in result["flags"]:

            print(f"Type: {flag['type']}")
            print(f"Severity: {flag['severity']}")
            print(f"Description: {flag['description']}")
            print(f"Evidence: {flag['evidence']}")
            print()

    else:
        print("No suspicious changes detected.")