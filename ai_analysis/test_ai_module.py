"""
Run this to prove the AI module works end to end.

    python test_ai_module.py

Requires Ollama running locally with a model pulled:
    ollama serve
    ollama pull llama3.2
"""

from ai_module import analyze_clause, analyze_contract, explain_invoice_change

SAMPLE_CLAUSES = [
    "The vendor may increase the subscription fee by up to 15% upon each "
    "annual renewal, with no requirement for customer approval.",

    "Either party may terminate this agreement with 30 days written notice.",

    "This agreement automatically renews for successive one-year terms "
    "unless cancelled in writing at least 60 days before the renewal date.",

    "Payment is due within 30 days of invoice receipt.",
]


def main():
    print("=== 1. Individual clause analysis ===\n")
    for clause in SAMPLE_CLAUSES:
        result = analyze_clause(clause)
        print(f"Clause: {clause}")
        print(f"  Type:      {result['clause_type']}")
        print(f"  Risk:      {result['risk_level'].upper()}")
        print(f"  Why:       {result['explanation']}")
        print(f"  Evidence:  {result['evidence_text']}\n")

    print("=== 2. Invoice comparison ===\n")
    invoice_result = explain_invoice_change(10000, 12000, "CloudHost Inc.")
    print(invoice_result, "\n")

    print("=== 3. Full contract scan (paragraph splitting) ===\n")
    sample_contract = "\n\n".join(SAMPLE_CLAUSES)
    flagged = analyze_contract(sample_contract)
    print(f"Flagged {len(flagged)} risky clause(s) out of {len(SAMPLE_CLAUSES)}")
    for f in flagged:
        print(f" - [{f['risk_level'].upper()}] {f['clause_type']}: {f['explanation']}")


if __name__ == "__main__":
    main()
