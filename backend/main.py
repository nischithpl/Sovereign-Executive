"""
main.py - FastAPI backend. Run from the project root:  uvicorn main:app --reload

All logic lives in analysis.py so the API and the Streamlit UI behave identically.
"""
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import analysis
import database

app = FastAPI(title="Sovereign Executive API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class ContractIn(BaseModel):
    vendor_name: str
    agreed_amount: Optional[float] = None
    max_increase_pct: Optional[float] = None
    renewal_date: Optional[str] = None  # YYYY-MM-DD
    notice_days: Optional[int] = None
    clause: Optional[str] = None


@app.get("/api/health")
def health():
    return {"ok": True}


# Plain `def` (not async): parsing + Ollama are blocking, FastAPI runs them in a threadpool.
@app.post("/api/upload-invoice")
def upload_and_audit(
    file: UploadFile = File(...),
    tone: str = Query("firm", pattern="^(firm|polite)$"),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF invoices are supported.")
    try:
        current = analysis.parse_pdf_bytes(file.file.read())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read the PDF: {e}")

    result = analysis.run_audit(current, tone=tone, save=True, use_memory=True)
    if result.get("status") == "ERROR":
        raise HTTPException(status_code=400, detail=result.get("message"))
    result.pop("ai_args", None)
    return result


# --- Vendor History / Memory ---
@app.get("/api/vendors/{vendor}/memory")
def get_vendor_memory(vendor: str, limit: int = Query(default=5, ge=1, le=20)):
    history = database.get_history(vendor, limit=limit)
    return {
        "vendor": vendor,
        "history": history
    }

# --- Contracts (Put / Update) ---
@app.put("/api/contracts")
def update_contract(payload: ContractIn):
    # Converts the Pydantic model into a dictionary and saves it
    database.save_contract(payload.vendor_name, payload.model_dump())
    return {
        "status": "SUCCESS",
        "message": f"Contract updated for {payload.vendor_name}"
    }

# --- Contracts (Get) ---
@app.get("/api/contracts/{vendor}")
def get_contract(vendor: str):
    contract = database.get_contract(vendor)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found for vendor")
    return contract


@app.get("/api/renewals")
def renewals():
    out = []
    for c in database.list_contracts():
        r = analysis.renewal_info(c)
        if r:
            out.append({"vendor": c["vendor_name"], **r})
    return sorted(out, key=lambda x: x["days_to_cancel"])
