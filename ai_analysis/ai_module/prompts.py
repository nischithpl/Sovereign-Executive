"""
All prompt templates live here so they're easy to tune without touching
the analysis logic. If the model's answers seem inconsistent during the
hackathon, this is the first file to edit — add another worked example
below in the same format.
"""

CLAUSE_ANALYSIS_PROMPT = """You are a contract clause risk analyzer for a financial auditing tool.
Read the clause below and respond with ONLY valid JSON. No preamble, no markdown, no explanation outside the JSON.

Respond in EXACTLY this JSON format:
{{
  "clause_type": "price_increase | auto_renewal | termination | liability | payment_terms | other",
  "risk_level": "low | medium | high",
  "explanation": "one sentence explaining why this risk level was chosen",
  "evidence_text": "the exact phrase from the clause that supports this finding"
}}

Worked examples (follow this exact pattern):

Clause: "The vendor may increase the subscription fee by up to 15% upon each annual renewal, with no requirement for customer approval."
Answer: {{"clause_type": "price_increase", "risk_level": "high", "explanation": "Allows a unilateral price increase with no customer approval required.", "evidence_text": "no requirement for customer approval"}}

Clause: "Either party may terminate this agreement with 30 days written notice."
Answer: {{"clause_type": "termination", "risk_level": "low", "explanation": "Termination rights are mutual and notice period is standard.", "evidence_text": "Either party may terminate"}}

Clause: "This agreement automatically renews for successive one-year terms unless cancelled in writing at least 60 days before the renewal date."
Answer: {{"clause_type": "auto_renewal", "risk_level": "medium", "explanation": "Auto-renews by default but gives a reasonable 60-day opt-out window.", "evidence_text": "automatically renews for successive one-year terms"}}

Now analyze this clause the same way:

Clause:
\"\"\"{clause_text}\"\"\"

Answer:
"""

INVOICE_COMPARISON_EXPLANATION_PROMPT = """You are a financial auditing assistant.
Two invoices from the same vendor are being compared. Explain the change in plain, professional language suitable for a business owner.

Vendor: {vendor_name}
Previous invoice amount: {previous_amount}
Current invoice amount: {current_amount}
Percentage change: {percent_change}%

Respond with ONLY valid JSON in this format:
{{
  "summary": "one sentence summary of the change",
  "severity": "low | medium | high",
  "recommended_action": "one sentence recommendation for the user"
}}
"""
