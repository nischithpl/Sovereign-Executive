import csv
import os
 
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
 
OUT = "samples"
VENDOR = "BluePeak IT Services Pvt Ltd"
VENDOR_GSTIN = "29ABCDE1234F1Z5"
CUSTOMER_GSTIN = "29XYZAB9876C1Z2"
styles = getSampleStyleSheet()
 
# Helvetica has no rupee glyph, so register DejaVu when available (falls back to "Rs.")
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
 
FONT, FONT_BOLD, RUPEE = "Helvetica", "Helvetica-Bold", "Rs. "
for reg, bold in [("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                  ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf")]:
    if os.path.exists(reg) and os.path.exists(bold):
        pdfmetrics.registerFont(TTFont("DemoFont", reg))
        pdfmetrics.registerFont(TTFont("DemoFont-Bold", bold))
        FONT, FONT_BOLD, RUPEE = "DemoFont", "DemoFont-Bold", "₹"
        break
for _name in ("Title", "BodyText", "Normal"):
    styles[_name].fontName = FONT_BOLD if _name == "Title" else FONT
 
 
def money(v):
    return f"{RUPEE}{v:,.2f}"
 
 
def build_invoice(path, number, date, due, items, discount, taxes):
    """items: (desc, qty, unit); taxes: (label, rate) list applied on subtotal-discount."""
    doc = SimpleDocTemplate(path, pagesize=A4)
    story = [Paragraph("INVOICE", styles["Title"]), Spacer(1, 8)]
 
    head = Table(
        [
            ["Invoice No:", number], ["Invoice Date:", date], ["Due Date:", due],
            ["Terms", "Net 30"], [VENDOR, ""], ["GSTIN: " + VENDOR_GSTIN, ""],
            ["Bill To: Acme Retail Pvt Ltd", ""], ["GSTIN: " + CUSTOMER_GSTIN, ""],
        ],
        colWidths=[230, 200],
    )
    head.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 10), ("FONTNAME", (0, 0), (-1, -1), FONT)]))
    story += [head, Spacer(1, 14)]
 
    rows = [["Description", "Qty", "Unit Price", "Amount"]]
    subtotal = 0
    for desc, qty, unit in items:
        amt = qty * unit
        subtotal += amt
        rows.append([desc, f"{qty:g}", money(unit), money(amt)])
    t = Table(rows, colWidths=[220, 50, 90, 90])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), FONT), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.grey)]))
    story += [t, Spacer(1, 10)]
 
    taxable = subtotal - discount
    tot = [["Subtotal", money(subtotal)]]
    if discount:
        tot.append(["Discount (Loyalty)", money(discount)])
    total = taxable
    for label, rate, forced_amount in taxes:
        amount = forced_amount if forced_amount is not None else round(taxable * rate / 100, 2)
        total += amount
        tot.append([f"{label} ({rate:g}%)", money(amount)])
    tot.append(["TOTAL DUE", money(total)])
    tt = Table(tot, colWidths=[200, 120], hAlign="RIGHT")
    tt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD)]))
    story.append(tt)
    doc.build(story)
    return total
 
 
def build_contract(path):
    doc = SimpleDocTemplate(path, pagesize=A4)
    p = lambda s: Paragraph(s, styles["BodyText"])
    story = [
        Paragraph("MASTER SERVICES AGREEMENT", styles["Title"]),
        p("This Agreement is made between Acme Retail Pvt Ltd (Customer) and "
          "BluePeak IT Services Pvt Ltd (Vendor), effective 1 December 2025."),
        Spacer(1, 8),
        p("1. Services and Fees"), Spacer(1, 4),
        p("1.1 The Customer shall pay a Managed Cloud Hosting fee of ₹40,000 per month, "
          "fixed for the first twelve months of the term."),
        Spacer(1, 6),
        p("1.2 The Support Plan is charged at ₹1,500 per seat per month."),
        Spacer(1, 6),
        p("1.3 Backup Storage is charged at ₹4 per GB per month."),
        Spacer(1, 6),
        p("1.4 A loyalty discount of ₹2,000 per month applies to each invoice during the initial term."),
        PageBreak(),
        p("4. Price Adjustments"), Spacer(1, 4),
        p("4.2 The Vendor may revise the fees no more than once per year, by not more than 5%, "
          "and only upon at least 60 days prior written notice to the Customer. "
          "No new fees or charges may be introduced without the Customer's written consent."),
        Spacer(1, 6),
        p("4.3 All amounts are exclusive of GST, which shall be charged at 18%. Where the Vendor and "
          "Customer are located in the same state, CGST and SGST shall apply."),
        Spacer(1, 6),
        p("4.4 Invoices are payable within Net 30 days of the invoice date."),
        PageBreak(),
        p("9. Term and Renewal"), Spacer(1, 4),
        p("9.1 This Agreement automatically renews for successive twelve month terms unless either "
          "party gives at least 60 days written notice of non-renewal. The current term ends on "
          "30 November 2026."),
        Spacer(1, 6),
        p("9.2 The Vendor's aggregate liability shall not exceed the fees paid in the preceding "
          "three months."),
    ]
    doc.build(story)
 
 
def main():
    os.makedirs(OUT, exist_ok=True)
    base = [("Managed Cloud Hosting", 1, 40000), ("Support Plan (per seat)", 10, 1500),
            ("Backup Storage (GB)", 500, 4)]
    split = [("CGST", 9, None), ("SGST", 9, None)]
 
    t_jul = build_invoice(f"{OUT}/invoice_bluepeak_2026_07.pdf", "BP-2026-0701", "July 1, 2026",
                          "July 31, 2026", base, 2000, split)
    t_aug = build_invoice(f"{OUT}/invoice_bluepeak_2026_08.pdf", "BP-2026-0801", "August 1, 2026",
                          "August 31, 2026", base, 2000, split)
 
    sept_items = [("Managed Cloud Hosting", 1, 44000), ("Support Plan (per seat)", 10, 1500),
                  ("Backup Storage (GB)", 500, 4), ("Platform Fee", 1, 3000)]
    # taxable = 64,000 ; correct IGST 18% = 11,520 ; vendor billed 12,000
    t_sep = build_invoice(f"{OUT}/invoice_bluepeak_2026_09.pdf", "BP-2026-0901", "September 1, 2026",
                          "October 1, 2026", sept_items, 0, [("IGST", 18, 12000.0)])
 
    build_contract(f"{OUT}/contract_bluepeak.pdf")
 
    with open(f"{OUT}/bank_statement.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Debit", "Credit", "Balance"])
        w.writerow(["2026-07-05", "NEFT BLUEPEAK IT SERVICES BP-2026-0701", f"{t_jul:.2f}", "", "1000000"])
        w.writerow(["2026-07-11", "UPI SWIGGY CORPORATE", "8450.00", "", "991550"])
        w.writerow(["2026-08-04", "NEFT BLUEPEAK IT SERVICES BP-2026-0801", f"{t_aug:.2f}", "", "900000"])
        w.writerow(["2026-09-03", "NEFT BLUEPEAK IT SERVICES BP-2026-0901", f"{t_sep:.2f}", "", "800000"])
        # a charge with no invoice at all
        w.writerow(["2026-09-15", "BLUEPEAK IT SERVICES ADHOC RENEWAL FEE", "4500.00", "", "795500"])
    print("Demo data written to", OUT, "| totals:", t_jul, t_aug, t_sep)
 
 
if __name__ == "__main__":
    main()
 