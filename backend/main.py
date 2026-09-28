import os
import sys

# 1. Resolve paths
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))

# 2. Add backend and root so analysis.py can find ai_service and database
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 3. Imports
import analysis
import database

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

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
    renewal_date: Optional[str] = None
    notice_days: Optional[int] = None
    clause: Optional[str] = None

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/upload-invoice")
def upload_and_audit(file: UploadFile = File(...)):
    file_bytes = file.file.read()
    parsed_invoice = analysis.parse_pdf_bytes(file_bytes)
    result = analysis.run_audit(parsed_invoice)
    return result

@app.get("/api/vendors/{vendor}/memory")
def get_vendor_memory(vendor: str, limit: int = Query(default=5, ge=1, le=20)):
    history = database.get_history(vendor, limit=limit)
    return {
        "vendor": vendor,
        "history": history
    }

@app.put("/api/contracts")
def update_contract(payload: ContractIn):
    database.save_contract(payload.vendor_name, payload.model_dump())
    return {
        "status": "SUCCESS",
        "message": f"Contract updated for {payload.vendor_name}"
    }

@app.get("/api/contracts/{vendor}")
def get_contract(vendor: str):
    contract = database.get_contract(vendor)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found for vendor")
    return contract
