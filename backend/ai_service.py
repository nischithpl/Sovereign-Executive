"""
ai_service.py - local LLM (Ollama) writes ONLY the audit note and dispute email.

Reliability rules:
- Every number is computed in Python (analysis.py) and handed to the model as a
  fact. The model is told not to calculate anything.
- If Ollama is down, times out, or returns junk, we fall back to a deterministic
  template so the demo never shows an error where the email should be.
"""
import os
import re

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "60"))

TONES = {
    "firm": "firm and formal; state that the charge is disputed and request a corrected invoice or credit",
    "polite": "polite and cooperative; assume an honest mistake and ask for clarification",
}


def _money(x, cur):
    return f"{cur} {x:,.2f}" if isinstance(x, (int, float)) else "N/A"


def _facts(findings):
    lines = []
    for f in (findings or [])[:6]:
        lines.append(f"- [{f.get('category', f.get('severity', ''))}] {f.get('description', '')}: {f.get('evidence', '')}")
    return "\n".join(lines) or "- Total increased without a clear explanation."


def fallback_summary(vendor, old_amt, new_amt, pct, currency="INR", findings=None,
                     tone="firm", clause=None, recoverable=None):
    """Deterministic note + email built purely from computed facts."""
    facts = _facts(findings)
    note = (
        f"The invoice from {vendor} rose from {_money(old_amt, currency)} to {_money(new_amt, currency)} "
        f"({pct:+.2f}%). The following items require review before payment:\n{facts}"
    )
    ask = (
        f"we request a credit of {_money(recoverable, currency)}" if recoverable
        else "we request a written explanation and, where applicable, a corrected invoice"
    )
    clause_line = f" This appears inconsistent with the agreed terms ({clause})." if clause else ""
    if tone == "polite":
        email = (
            f"Dear {vendor} Billing Team,\n\n"
            f"Thank you for your latest invoice. We noticed the amount changed from {_money(old_amt, currency)} "
            f"to {_money(new_amt, currency)} ({pct:+.2f}%) and would appreciate some clarification.\n"
            f"Specifically:\n{facts}\n{clause_line.strip()}\n"
            f"If this is an error, {ask}. Thank you for your help.\n\nKind regards"
        )
    else:
        email = (
            f"Dear {vendor} Billing Team,\n\n"
            f"Your latest invoice shows an increase from {_money(old_amt, currency)} to "
            f"{_money(new_amt, currency)} ({pct:+.2f}%). We dispute the following charges:\n{facts}\n"
            f"{clause_line.strip()}\n"
            f"Please respond within 7 days; {ask}.\n\nRegards"
        )
    return {"audit_note": note, "dispute_email": email.replace("\n\n\n", "\n\n")}


def generate_audit_summary(vendor: str, old_amt: float, new_amt: float, pct: float,
                           currency: str = "INR", findings: list = None, tone: str = "firm",
                           clause: str = None, recoverable: float = None) -> dict:
    tone_desc = TONES.get(tone, TONES["firm"])
    clause_txt = f"Contract clause: {clause}" if clause else "Contract clause: none on file"
    rec_txt = f"Requested credit: {_money(recoverable, currency)}" if recoverable else "Requested credit: not specified"

    prompt = f"""You are an enterprise financial auditor. Use ONLY the facts below. Do not calculate or invent any numbers.

Vendor: {vendor}
Previous amount: {_money(old_amt, currency)}
Current amount: {_money(new_amt, currency)}
Change: {pct:+.2f}%
{clause_txt}
{rec_txt}
Verified findings:
{_facts(findings)}

Task:
1. Write a 2-sentence formal audit note explaining why this invoice needs review.
2. Write a short dispute email (max 5 sentences) to the vendor's billing team. Tone: {tone_desc}. Quote the amounts and the clause if given.

Format your response strictly as:
AUDIT NOTE: <text>
DISPUTE EMAIL: <text>
"""
    base = dict(vendor=vendor, old_amt=old_amt, new_amt=new_amt, pct=pct, currency=currency,
                findings=findings, tone=tone, clause=clause, recoverable=recoverable)
    payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False,
               "options": {"temperature": 0.2}}

    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        if res.status_code != 200:
            raise RuntimeError(f"Ollama returned HTTP {res.status_code}")
        parsed = parse_ai_response(res.json().get("response", ""))
        if parsed:
            parsed["source"] = "llm"
            return parsed
        reason = "model output could not be parsed"
    except requests.exceptions.ConnectionError:
        reason = "Ollama is not reachable on localhost:11434"
    except requests.exceptions.Timeout:
        reason = f"Ollama timed out after {TIMEOUT}s"
    except Exception as e:  # never let the AI layer break the audit
        reason = str(e)

    out = fallback_summary(**base)
    out["source"] = "template"
    out["error"] = reason
    return out


def parse_ai_response(text: str):
    """Returns {'audit_note','dispute_email'} or None if the format was not followed."""
    m = re.search(r"AUDIT NOTE:\s*(.*?)\s*DISPUTE EMAIL:\s*(.*)", text or "", re.S | re.I)
    if not m:
        return None
    note, email = m.group(1).strip(), m.group(2).strip()
    if len(note) < 20 or len(email) < 40:
        return None
    return {"audit_note": note, "dispute_email": email}
