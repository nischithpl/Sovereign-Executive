import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3"  # or "mistral", or whichever model you have pulled in Ollama


def _query_ollama(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Helper to query the local Ollama daemon."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2  # Keep it grounded, factual, and strictly aligned with input data
        }
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"AI generation unavailable: {str(e)}"


def generate_audit_note(audit_result: dict) -> str:
    """
    Summarizes the deterministic comparison findings into a concise
    executive AP audit summary without recomputing any math.
    """
    prompt = f"""
You are an executive accounts payable auditor.
Analyze the following deterministic audit data calculated for an incoming invoice:

{json.dumps(audit_result, indent=2)}

Write a concise, 2-3 paragraph audit report for internal management.
Rules:
1. State clearly whether the invoice has price leaks, unauthorized price increases, or contract term violations.
2. Cite the exact dollar/currency amounts and percentages provided in the data. Do NOT recalculate or invent any numbers.
3. Be direct, authoritative, and professional.
"""
    return _query_ollama(prompt)


def generate_dispute_email(audit_result: dict) -> str:
    """
    Drafts a formal, ready-to-send dispute letter/email to the vendor
    referencing discrepancies, line item price drifts, or contract breaches.
    """
    vendor = audit_result.get("vendor_name") or audit_result.get("vendor", {}).get("name", "Vendor")
    
    prompt = f"""
You are a senior procurement specialist handling vendor relations.
Write a formal dispute email to {vendor} regarding billing discrepancies found in their recent invoice.

Discrepancy and Audit Data:
{json.dumps(audit_result, indent=2)}

Email Guidelines:
- Subject Line: Include vendor name, invoice number, and 'Billing Discrepancy Notice'.
- Opening: Polite yet firm notification that the invoice was flagged during contract compliance review.
- Specifics: Reference the exact discrepant items, rate differences, unapproved fee additions, or contract deviations from the data.
- Call to Action: Request an amended credit note or updated invoice adhering to agreed terms before payment release.
- Tone: Professional, polite, assertive corporate tone.
"""
    return _query_ollama(prompt)
