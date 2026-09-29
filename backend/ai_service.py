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

def generate_audit_summary(
    vendor,
    old_amt,
    new_amt,
    pct,
    currency,
    findings,
    clause=None,
    recoverable=None,
    tone="executive"
):
    """
    Generate AI wording from deterministic audit findings.

    The AI does not perform financial calculations.
    All numbers and findings come from the deterministic audit engine.
    """

    prompt = f"""
You are an executive accounts-payable audit assistant.

Write a concise audit summary based ONLY on the supplied data.

Vendor: {vendor}
Previous amount: {old_amt} {currency}
Current amount: {new_amt} {currency}
Percentage change: {pct}%
Findings: {json.dumps(findings, default=str)}
Contract clause: {clause}
Potential recoverable amount: {recoverable}
Tone: {tone}

Tone requirements:

If tone is "firm":
- Be direct and assertive.
- Clearly state that the invoice discrepancies require clarification before approval/payment.
- Request specific supporting documentation or an amended invoice where appropriate.
- Do not use aggressive, threatening, or accusatory language.

If tone is "polite":
- Be courteous and collaborative.
- Ask the vendor to clarify the discrepancies.
- Avoid language implying that payment is being withheld or that the vendor has violated an agreement unless the supplied findings explicitly establish that.
- Use softer language such as "Could you please review..." or "We would appreciate clarification..."

If tone is anything else:
- Use a neutral, professional corporate tone.

The email wording MUST visibly reflect the selected tone.

Return your response as JSON with exactly these fields:

{{
    "audit_note": "Short executive audit summary",
    "dispute_email": "Professional email requesting clarification from the vendor",
    "source": "AI-generated from deterministic audit findings"
}}

Rules:
- Do not invent facts.
- Do not change any numbers.
- Do not perform additional calculations.
- Do not claim fraud or wrongdoing.
- Clearly distinguish suspicious discrepancies from confirmed facts.
- Keep the audit note concise.
- Make the email professional, factual, and clearly consistent with the requested tone.
"""

    try:
        response = _query_ollama(prompt)

        # Ollama should return JSON.
        data = json.loads(response)

        return {
            "audit_note": data.get("audit_note", ""),
            "dispute_email": data.get("dispute_email", ""),
            "source": data.get(
                "source",
                "AI-generated from deterministic audit findings"
            ),
            "error": None,
        }

    except Exception as e:

        # Deterministic fallback that still respects the selected tone.
        if tone == "firm":
            fallback_email = (
                f"Dear {vendor},\n\n"
                "Our review identified discrepancies in the invoice that "
                "require clarification before the invoice can be approved. "
                "Please review the identified items and provide the relevant "
                "supporting documentation or an amended invoice.\n\n"
                "Regards,\n"
                "Accounts Payable"
            )

        elif tone == "polite":
            fallback_email = (
                f"Dear {vendor},\n\n"
                "We noticed some discrepancies in the invoice and would "
                "appreciate your clarification. Could you please review the "
                "identified items and provide any relevant supporting "
                "documentation or an amended invoice if necessary?\n\n"
                "Regards,\n"
                "Accounts Payable"
            )

        else:
            fallback_email = (
                f"Dear {vendor},\n\n"
                "We identified discrepancies in the invoice that require "
                "clarification. Please review the invoice and provide "
                "supporting documentation.\n\n"
                "Regards,\n"
                "Accounts Payable"
            )

        return {
            "audit_note": (
                f"Audit identified {len(findings)} finding(s) "
                f"for {vendor}."
            ),
            "dispute_email": fallback_email,
            "source": "Deterministic fallback",
            "error": str(e),
        }

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
