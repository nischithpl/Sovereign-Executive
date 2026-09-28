"""
main.py - FastAPI backend. Run from the project root:  uvicorn main:app --reload

All logic lives in analysis.py so the API and the Streamlit UI behave identically.
"""
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

import analysis
import database

app = FastAPI(title="Sovereign Executive API")


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


@app.get("/api/vendors/{vendor_name}/memory")
def vendor_memory(vendor_name: str):
    history = database.get_history(vendor_name, 3)
    if not history:
        raise HTTPException(status_code=404, detail="No invoices on file for this vendor.")
    latest = history[0]
    return analysis._memory(vendor_name, latest, database.get_contract(vendor_name), history[1:], latest,
                            analysis.get(latest, "invoice", "currency") or "INR")


@app.put("/api/contracts")
def set_contract(c: ContractIn):
    database.save_contract(c.vendor_name, c.agreed_amount, c.max_increase_pct,
                           c.renewal_date, c.notice_days, c.clause)
    return {"saved": c.vendor_name}


@app.get("/api/renewals")
def renewals():
    out = []
    for c in database.list_contracts():
        r = analysis.renewal_info(c)
        if r:
            out.append({"vendor": c["vendor_name"], **r})
    return sorted(out, key=lambda x: x["days_to_cancel"])
