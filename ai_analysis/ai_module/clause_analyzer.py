"""
Core AI module for Sovereign Executive.

This is the file Member 3 (backend) imports from, and the file Member 1's
extracted document text eventually flows into.

Public functions:
    analyze_clause(clause_text, verify=False)   -> dict
    analyze_contract(full_contract_text)        -> list[dict]
    explain_invoice_change(prev, curr, vendor)  -> dict

Design choices made for reliability under demo conditions, not just
correctness:
    - Every result is normalized (case, whitespace, unexpected values)
      before it's returned, so a slightly-off model answer never crashes
      the backend or frontend.
    - If Ollama isn't reachable at all, a rule-based fallback kicks in
      automatically so the pipeline still returns *something* real.
    - Results are cached in-memory by clause text, so re-analyzing the
      same demo contract twice is instant the second time.
"""

import hashlib
import json
import re
from collections import Counter

from .ollama_client import OllamaClient
from .prompts import CLAUSE_ANALYSIS_PROMPT, INVOICE_COMPARISON_EXPLANATION_PROMPT

_client = OllamaClient()
_cache: dict = {}

VALID_RISK_LEVELS = {"low", "medium", "high"}
VALID_CLAUSE_TYPES = {
    "price_increase", "auto_renewal", "termination",
    "liability", "payment_terms", "other",
}

# Keyword-based fallback used only if Ollama can't be reached at all.
# Not as accurate as the model, but keeps the demo alive.
_FALLBACK_RULES = [
    (r"increase.{0,40}(fee|price|charge|cost)", "price_increase", "high",
     "Contains language allowing a fee or price increase."),
    (r"automatically renew|auto-renew", "auto_renewal", "medium",
     "Contract renews automatically unless cancelled."),
    (r"sole discretion|without notice|without approval", "liability", "high",
     "Grants one party unilateral control with little recourse for the other."),
    (r"terminate.{0,40}(notice|written)", "termination", "low",
     "Standard termination clause with a notice period."),
    (r"payment.{0,20}due|invoice", "payment_terms", "low",
     "Standard payment terms clause."),
]


def _extract_json(raw_text: str) -> dict:
    """
    Local models frequently wrap JSON in ```json fences or add a stray
    sentence before/after it. This strips that noise and parses the first
    {...} block it finds.
    """
    text = raw_text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {raw_text!r}")

    return json.loads(match.group(0))


def _normalize_result(result: dict, clause_text: str) -> dict:
    """
    Cleans up whatever the model returned so the rest of the app can trust
    the shape and values every time, even if the model:
      - capitalizes values ("High" instead of "high")
      - invents a clause_type not in our enum
      - omits a field entirely
    Never raises — always returns a usable dict.
    """
    risk_level = str(result.get("risk_level", "medium")).strip().lower()
    if risk_level not in VALID_RISK_LEVELS:
        # common variants -> nearest valid value; anything else -> medium (safe default)
        risk_level = {"med": "medium", "moderate": "medium",
                      "critical": "high", "severe": "high",
                      "minor": "low", "none": "low"}.get(risk_level, "medium")

    clause_type = str(result.get("clause_type", "other")).strip().lower()
    if clause_type not in VALID_CLAUSE_TYPES:
        clause_type = "other"

    return {
        "clause_type": clause_type,
        "risk_level": risk_level,
        "explanation": str(result.get("explanation", "")).strip() or "No explanation provided.",
        "evidence_text": str(result.get("evidence_text", "")).strip() or clause_text[:120],
        "raw_input": clause_text,
    }


def _rule_based_fallback(clause_text: str) -> dict:
    """Used only when Ollama cannot be reached at all."""
    lowered = clause_text.lower()
    for pattern, clause_type, risk_level, explanation in _FALLBACK_RULES:
        if re.search(pattern, lowered):
            return {
                "clause_type": clause_type,
                "risk_level": risk_level,
                "explanation": explanation + " (rule-based fallback — Ollama unavailable)",
                "evidence_text": clause_text[:120],
                "raw_input": clause_text,
            }
    return {
        "clause_type": "other",
        "risk_level": "low",
        "explanation": "No known risk pattern matched. (rule-based fallback — Ollama unavailable)",
        "evidence_text": clause_text[:120],
        "raw_input": clause_text,
    }


def _call_model_once(clause_text: str) -> dict:
    prompt = CLAUSE_ANALYSIS_PROMPT.format(clause_text=clause_text)
    raw = _client.generate(prompt)
    try:
        parsed = _extract_json(raw)
    except ValueError:
        raw = _client.generate(prompt + "\n\nReminder: respond with ONLY the JSON object, nothing else.")
        parsed = _extract_json(raw)
    return _normalize_result(parsed, clause_text)


def analyze_clause(clause_text: str, verify: bool = False) -> dict:
    """
    Takes one contract clause (plain string) and returns a normalized dict:
    {
        "clause_type": str,
        "risk_level": "low" | "medium" | "high",
        "explanation": str,
        "evidence_text": str,
        "raw_input": str,
    }

    verify=True: calls the model up to 3 times and takes the majority
    risk_level, to guard against flip-flopping on your one or two most
    important demo clauses. Costs 2-3x the latency — use sparingly, not
    on every clause in a live demo.

    Falls back to keyword rules automatically if Ollama is unreachable,
    so this function never raises during a demo.
    """
    cache_key = hashlib.sha256((clause_text + str(verify)).encode()).hexdigest()
    if cache_key in _cache:
        return _cache[cache_key]

    if not _client.is_available():
        result = _rule_based_fallback(clause_text)
        _cache[cache_key] = result
        return result

    try:
        if not verify:
            result = _call_model_once(clause_text)
        else:
            attempts = [_call_model_once(clause_text) for _ in range(3)]
            votes = Counter(a["risk_level"] for a in attempts)
            majority_level = votes.most_common(1)[0][0]
            # keep the first attempt that matches the winning vote, for its explanation/evidence
            result = next(a for a in attempts if a["risk_level"] == majority_level)
    except (ValueError, RuntimeError):
        # Model reachable but produced unusable output twice in a row, or
        # timed out mid-call — fall back rather than crash the demo.
        result = _rule_based_fallback(clause_text)

    _cache[cache_key] = result
    return result


def _split_into_clauses(full_contract_text: str) -> list:
    """
    Two-tier splitting: try blank-line paragraphs first (works on cleanly
    formatted text). If that produces basically one giant blob, fall back
    to splitting on numbered clause markers (1. / 2) / Section 3), which
    is more common in real contract PDFs.
    """
    paragraphs = [p.strip() for p in full_contract_text.split("\n\n") if len(p.strip()) > 20]
    if len(paragraphs) >= 2:
        return paragraphs

    numbered_split = re.split(r"\n(?=\s*(?:\d+[\.\)]|Section\s+\d+))", full_contract_text)
    numbered_split = [p.strip() for p in numbered_split if len(p.strip()) > 20]
    if len(numbered_split) >= 2:
        return numbered_split

    # last resort: whole text as one clause
    return [full_contract_text.strip()] if full_contract_text.strip() else []


def analyze_contract(full_contract_text: str) -> list:
    """
    Splits a contract into clauses and analyzes each one.
    Returns only the clauses flagged medium or high risk.
    """
    clauses = _split_into_clauses(full_contract_text)
    flagged = []
    for clause in clauses:
        result = analyze_clause(clause)
        if result["risk_level"] in ("medium", "high"):
            flagged.append(result)
    return flagged


def explain_invoice_change(previous_amount: float, current_amount: float, vendor_name: str = "Unknown Vendor") -> dict:
    """
    Takes two invoice amounts for the same vendor and returns:
    {
        "summary": str,
        "severity": "low" | "medium" | "high",
        "recommended_action": str,
        "percent_change": float,
    }
    Falls back to a simple rule if Ollama is unreachable.
    """
    if previous_amount == 0:
        raise ValueError("previous_amount cannot be zero")

    percent_change = round(((current_amount - previous_amount) / previous_amount) * 100, 1)

    if not _client.is_available():
        severity = "high" if abs(percent_change) >= 15 else "medium" if abs(percent_change) >= 5 else "low"
        return {
            "summary": f"{vendor_name}'s invoice changed by {percent_change}% "
                       f"(from {previous_amount} to {current_amount}). (rule-based fallback)",
            "severity": severity,
            "recommended_action": "Review this change with the vendor before approving payment.",
            "percent_change": percent_change,
        }

    prompt = INVOICE_COMPARISON_EXPLANATION_PROMPT.format(
        vendor_name=vendor_name,
        previous_amount=previous_amount,
        current_amount=current_amount,
        percent_change=percent_change,
    )
    try:
        raw = _client.generate(prompt)
        result = _extract_json(raw)
        severity = str(result.get("severity", "medium")).strip().lower()
        if severity not in VALID_RISK_LEVELS:
            severity = "medium"
        return {
            "summary": str(result.get("summary", "")).strip() or f"Invoice changed by {percent_change}%.",
            "severity": severity,
            "recommended_action": str(result.get("recommended_action", "")).strip()
                or "Review this change before approving payment.",
            "percent_change": percent_change,
        }
    except (ValueError, RuntimeError):
        severity = "high" if abs(percent_change) >= 15 else "medium" if abs(percent_change) >= 5 else "low"
        return {
            "summary": f"{vendor_name}'s invoice changed by {percent_change}% "
                       f"(from {previous_amount} to {current_amount}). (rule-based fallback)",
            "severity": severity,
            "recommended_action": "Review this change with the vendor before approving payment.",
            "percent_change": percent_change,
        }
