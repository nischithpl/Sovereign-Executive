import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from document_processing.extractor import extract_pdf_text
from document_processing.parser import create_invoice_data
from document_processing.comparator import compare_invoices
import database
import ai_service

app = FastAPI(title="Sovereign Executive API")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def parse_pdf(file_path: str) -> dict:
    pages = extract_pdf_text(file_path)
    full_text = "\n".join([page["text"] for page in pages])
    return create_invoice_data(full_text)

@app.post("/api/upload-invoice")
async def upload_and_audit(file: UploadFile = File(...)):
    temp_path = os.path.join(UPLOAD_DIR, file.filename)

    try:
        # 1. Save uploaded PDF temporarily
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 2. Extract and parse with Member 1's scripts
        current_invoice = parse_pdf(temp_path)
        vendor_name = current_invoice["vendor"]["name"]

        # 3. Check SQLite for an existing previous invoice
        previous_invoice = database.get_latest_invoice_for_vendor(vendor_name)

        # 4. If this is the first time seeing this vendor:
        if previous_invoice is None:
            database.save_invoice(current_invoice)
            return {
                "status": "BASELINE_ESTABLISHED",
                "message": f"First invoice recorded for {vendor_name}. Saved as baseline.",
                "vendor_name": vendor_name,
                "current_total": current_invoice["amounts"]["total"],
                "currency": current_invoice["invoice"]["currency"],
                "flags": []
            }

        # 5. Vendor exists: Run Member 1's comparator
        comparison = compare_invoices(previous_invoice, current_invoice)
        if comparison.get("status") == "ERROR":
            raise HTTPException(status_code=400, detail=comparison.get("message"))

        # Save this current invoice as the new latest record
        database.save_invoice(current_invoice)

        # 6. Generate AI Explanation & Dispute Email if suspicious
        ai_note = None
        dispute_email = None

        if len(comparison.get("flags", [])) > 0:
            ai_data = ai_service.generate_audit_summary(
                vendor=comparison["vendor_name"],
                old_amt=comparison["previous_total"],
                new_amt=comparison["current_total"],
                pct=comparison["change_percentage"]
            )
            ai_note = ai_data.get("audit_note")
            dispute_email = ai_data.get("dispute_email")

        comparison["ai_audit_note"] = ai_note
        comparison["dispute_email_draft"] = dispute_email

        return comparison

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
