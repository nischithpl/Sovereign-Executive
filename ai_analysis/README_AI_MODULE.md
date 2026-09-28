# AI Module — Sovereign Executive (Member 2's part)

Runs a local LLM (via Ollama) to analyze contract clauses and explain invoice
changes. Nothing here calls the internet — everything runs on-device.

## 1. One-time setup

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh      # Mac/Linux
# Windows: download from https://ollama.com/download

# Pull a small model (~2GB)
ollama pull llama3.2
# If your laptop is slow / low on RAM, use this instead — it's smaller:
# ollama pull phi3

# Start the Ollama server (often starts automatically after install —
# if `ollama pull` worked above, it's probably already running)
ollama serve
```

```bash
# In the project folder
pip install -r requirements.txt
```

## 2. Run the test script

```bash
python test_ai_module.py
```

If this prints risk levels and explanations for the sample clauses, the
module works. This is your fallback demo if nothing else integrates in time.

## 3. What this module exposes

```python
from ai_module import analyze_clause, analyze_contract, explain_invoice_change

analyze_clause("The vendor may increase fees by 15% upon renewal.")
# -> {"clause_type": "price_increase", "risk_level": "high",
#     "explanation": "...", "evidence_text": "...", "raw_input": "..."}

analyze_contract(full_contract_text)
# -> list of flagged clauses (medium/high risk only), same shape as above

explain_invoice_change(previous_amount=10000, current_amount=12000, vendor_name="CloudHost Inc.")
# -> {"summary": "...", "severity": "medium", "recommended_action": "...",
#     "percent_change": 20.0}
```

All three functions return plain Python dicts — safe to convert straight to
JSON for an API response or drop into a UI table.

---

## How the other three integrate

### Member 1 (Document Processing) → feeds you clauses

Member 1's PDF extraction should hand you either:
- **One big string** of contract text → pass it to `analyze_contract(text)`, which splits it into paragraphs and analyzes each.
- **A list of already-separated clauses** (better, if Member 1 can isolate them) → loop and call `analyze_clause(clause)` on each one directly, skip `analyze_contract`.

Agree on this interface early today — it's the single handoff point that
matters most.

### Member 3 (Backend/API) → wraps your functions in an endpoint

Example FastAPI route:

```python
from fastapi import FastAPI
from pydantic import BaseModel
from ai_module import analyze_contract, explain_invoice_change

app = FastAPI()

class ContractRequest(BaseModel):
    contract_text: str

class InvoiceRequest(BaseModel):
    previous_amount: float
    current_amount: float
    vendor_name: str = "Unknown Vendor"

@app.post("/analyze-contract")
def analyze_contract_endpoint(req: ContractRequest):
    return {"flagged_clauses": analyze_contract(req.contract_text)}

@app.post("/compare-invoice")
def compare_invoice_endpoint(req: InvoiceRequest):
    return explain_invoice_change(req.previous_amount, req.current_amount, req.vendor_name)
```

Run with: `uvicorn main:app --reload`

### Member 4 (Frontend) → calls the API, displays results

Example Streamlit snippet (adjust to whatever framework you land on):

```python
import streamlit as st
import requests

contract_text = st.text_area("Paste contract text")
if st.button("Analyze"):
    resp = requests.post("http://localhost:8000/analyze-contract",
                          json={"contract_text": contract_text})
    flagged = resp.json()["flagged_clauses"]
    for clause in flagged:
        st.error(f"[{clause['risk_level'].upper()}] {clause['clause_type']}")
        st.write(clause["explanation"])
        st.caption(f"Evidence: {clause['evidence_text']}")
```

---

## Reliability features already built in

- **Normalization**: every model answer is cleaned up (lowercased,
  validated against the allowed risk levels / clause types) before it's
  returned, so a slightly-off answer from the model never breaks your
  backend or crashes the demo.
- **Automatic fallback**: if Ollama isn't running, isn't reachable, or
  times out, `analyze_clause`/`analyze_contract`/`explain_invoice_change`
  silently fall back to keyword-based rules instead of raising an error.
  Real output every time, tested end-to-end without Ollama running at all.
- **Caching**: results are cached in memory by clause text, so re-running
  the same demo contract twice is instant the second time — useful for
  a live demo where you might click "analyze" more than once.
- **Consistency mode**: `analyze_clause(text, verify=True)` calls the
  model up to 3 times and takes the majority risk level. Use this only on
  your 1-2 most important demo clauses — it's 2-3x slower, not for every
  clause in a live scan.
- **Two-tier clause splitting**: `analyze_contract` first tries blank-line
  paragraphs, then falls back to numbered-clause patterns ("1.", "2)",
  "Section 3") for real-world contract formatting without blank lines.

## What you still must test yourself today (this is not optional)

Nothing above can be verified without Ollama actually installed and
running — I don't have it in my environment, so all of the above was
tested against the fallback path and mocked/malformed inputs, not against
a real model response. Before you trust this for the demo:

1. Run `python test_ai_module.py` with Ollama actually running and
   confirm the *real* model output looks sensible, not just the fallback.
2. Feed it your actual demo contract text, not just the sample clauses.
3. Time it — if `analyze_contract` is too slow on your laptop for a live
   multi-clause scan, pre-run it once before the demo and show the cached
   (instant) result live instead of re-running from scratch on stage.
4. If risk levels still seem inconsistent even with the few-shot examples
   in `prompts.py`, that's the file to add more worked examples to — not
   a sign the whole approach is broken.

`llama3.2` is not a specialized legal model — treat its output as a flag
for a human to review, not a verdict. Say this explicitly in your demo;
it's also the safer, more credible framing for judges.
