
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.2:1b"

def generate_audit_summary(vendor: str, old_amt: float, new_amt: float, pct: float) -> dict:
    prompt = f"""
You are an enterprise financial auditor.
Vendor: {vendor}
Previous Amount: INR {old_amt}
Current Amount: INR {new_amt}
Price Increase: {pct:.2f}%

Task:
1. Provide a concise 2-sentence formal audit note explaining why this charge needs review.
2. Provide a 3-sentence dispute email draft to the vendor's billing team requesting clarification.

Format your response strictly as:
AUDIT NOTE: 
DISPUTE EMAIL: 
"""
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    }

    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=40)
        if res.status_code == 200:
            text = res.json().get("response", "")
            return parse_ai_response(text)
        return {
            "audit_note": "AI generation returned an unexpected status.",
            "dispute_email": "N/A"
        }
    except requests.exceptions.ConnectionError:
        return {
            "audit_note": "Ollama service is not reachable on localhost:11434.",
            "dispute_email": "N/A"
        }

def parse_ai_response(text: str) -> dict:
    note = "Unexplained price variance detected."
    email = "Please contact vendor for billing clarification."
    
    if "AUDIT NOTE:" in text and "DISPUTE EMAIL:" in text:
        parts = text.split("DISPUTE EMAIL:")
        note = parts[0].replace("AUDIT NOTE:", "").strip()
        email = parts[1].strip()
    elif "AUDIT NOTE:" in text:
        note = text.replace("AUDIT NOTE:", "").strip()
        
    return {
        "audit_note": note,
        "dispute_email": email
    }