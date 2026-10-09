import json
from typing import Any

from src.llm.client import call_openrouter


INCOME_AGENT_SYSTEM_PROMPT = """
You are an Income Detection Gatekeeper for a credit assessment system.

Your ONLY responsibility is to decide whether the supplied transaction candidate
qualifies as genuine salary income.

IMPORTANT:
- You are a GATEKEEPER, not a data extractor.
- Do NOT generate salary amounts.
- Do NOT generate payout dates.
- Do NOT generate company information.
- Do NOT modify or reconstruct the extractor's data.
- Do NOT calculate salary.
- Do NOT select or create a different income source.
- Only decide whether the supplied candidate should be accepted as salary income.

SALARY DETECTION RULES:

1. The candidate must show a recurring income pattern.
2. There should normally be at least 3 recurring credits.
3. Credits should have reasonably consistent timing.
4. Credits should have reasonably consistent amounts.
5. The source/counterparty should be reasonably consistent.
6. UPI transactions MUST NOT be considered salary.
7. ATM transactions MUST NOT be considered salary.
8. Unknown payment mode MAY be considered salary if the transaction pattern
   itself strongly supports salary.
9. TRANSFER payment mode MAY be considered salary if the recurring pattern
   strongly supports salary.
10. Do not require NEFT/IMPS/RTGS/etc. specifically.
11. Do not reject a candidate merely because the payment mode is UNKNOWN.
12. A one-off large credit is not salary merely because the amount is large.
13. Random transfers, personal transfers, refunds, cash deposits, or irregular
    credits should not be treated as salary.
14. The extractor has already performed the initial transaction analysis.
    Your job is to validate whether its candidate satisfies salary criteria.

CRITICAL:
If the payment mode is UPI or ATM, reject the candidate.

Your response MUST be valid JSON and contain ONLY these fields:

{
    "detected": true,
    "reason": "Short concise reason"
}

OR

{
    "detected": false,
    "reason": "Short concise reason"
}

The reason must be one short sentence explaining the decision.
Do not include markdown.
Do not include additional fields.
"""


def _clean_json_response(response: str) -> str:
    """
    Remove accidental markdown code fences from the LLM response.
    """
    response = response.strip()

    if response.startswith("```"):
        response = response.replace("```json", "", 1)
        response = response.replace("```", "")
        response = response.strip()

    return response


def _normalize_payment_mode(value: Any) -> str:
    """
    Normalize payment mode for deterministic validation.
    """
    if value is None:
        return ""

    return str(value).strip().upper()


def _contains_hard_excluded_mode(candidate: dict[str, Any]) -> bool:
    """
    UPI and ATM are hard exclusions.

    The extractor may provide payment_mode at candidate level.
    """
    payment_mode = _normalize_payment_mode(
        candidate.get("payment_mode")
    )

    return payment_mode in {"UPI", "ATM"}


def _validate_agent_output(result: Any) -> dict[str, Any]:
    """
    Ensure the LLM follows the strict gatekeeper contract.
    """
    if not isinstance(result, dict):
        raise ValueError(
            f"Income agent returned invalid JSON object: {result}"
        )

    if "detected" not in result:
        raise ValueError(
            "Income agent response missing required field: detected"
        )

    if "reason" not in result:
        raise ValueError(
            "Income agent response missing required field: reason"
        )

    detected = result["detected"]

    if not isinstance(detected, bool):
        raise ValueError(
            "Income agent field 'detected' must be boolean"
        )

    reason = result["reason"]

    if reason is None:
        reason = ""

    reason = str(reason).strip()

    if not reason:
        reason = (
            "Salary income detected."
            if detected
            else "No valid salary detected."
        )

    return {
        "detected": detected,
        "reason": reason,
    }


def evaluate_income_candidate(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate one extractor-generated income candidate.

    This function is intentionally a gatekeeper.

    It does NOT return or generate salary data.
    It only returns:
        detected: bool
        reason: str
    """

    if not isinstance(candidate, dict):
        return {
            "detected": False,
            "reason": "Invalid income candidate supplied by extractor.",
        }

    # ---------------------------------------------------------
    # HARD PYTHON VALIDATION
    # ---------------------------------------------------------
    # Never allow the LLM to override these exclusions.
    if _contains_hard_excluded_mode(candidate):
        payment_mode = _normalize_payment_mode(
            candidate.get("payment_mode")
        )

        return {
            "detected": False,
            "reason": (
                f"{payment_mode} credits are excluded from salary detection."
            ),
        }

    # ---------------------------------------------------------
    # PREPARE EVIDENCE FOR THE LLM
    # ---------------------------------------------------------
    # The agent receives the extractor's candidate as evidence.
    # It does not create any new financial information.
    candidate_json = json.dumps(
        candidate,
        default=str,
        ensure_ascii=False,
        indent=2,
    )

    user_prompt = f"""
Evaluate the following income candidate produced by the transaction extractor.

Your task is ONLY to decide whether this candidate qualifies as salary income.

EXTRACTOR CANDIDATE:

{candidate_json}

Remember:
- Do not generate or modify any financial data.
- Do not create salary information.
- Do not infer a different candidate.
- UPI and ATM must be rejected.
- UNKNOWN and TRANSFER may be accepted if the recurring pattern supports salary.
- Return ONLY the required JSON object.
"""

    response = call_openrouter(
        system_prompt=INCOME_AGENT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    response = _clean_json_response(response)

    try:
        result = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Income agent returned invalid JSON: {response}"
        ) from exc

    return _validate_agent_output(result)


def run_income_agent(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Run the Income Agent against extractor-generated candidates.

    The agent acts as a gatekeeper.

    Returns ONLY:
        {
            "detected": bool,
            "reason": str
        }

    If no valid candidate exists, salary is not detected.
    """

    if not candidates:
        return {
            "detected": False,
            "reason": "No income candidate was provided by the extractor.",
        }

    # ---------------------------------------------------------
    # REMOVE HARD-EXCLUDED CANDIDATES BEFORE LLM
    # ---------------------------------------------------------
    eligible_candidates = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        if _contains_hard_excluded_mode(candidate):
            continue

        eligible_candidates.append(candidate)

    if not eligible_candidates:
        return {
            "detected": False,
            "reason": (
                "All supplied income candidates use excluded payment modes."
            ),
        }

    # ---------------------------------------------------------
    # EVALUATE CANDIDATES
    # ---------------------------------------------------------
    #
    # We intentionally stop at the first candidate accepted by
    # the agent because the extractor has already ranked candidates.
    #
    # The agent does NOT return the candidate itself.
    #
    for candidate in eligible_candidates:
        decision = evaluate_income_candidate(candidate)

        if decision["detected"] is True:
            return {
                "detected": True,
                "reason": decision["reason"],
            }

    # ---------------------------------------------------------
    # NO CANDIDATE PASSED
    # ---------------------------------------------------------
    return {
        "detected": False,
        "reason": "No supplied income candidate satisfies the salary criteria.",
    }


class IncomeAgent:
    """
    Thin wrapper around the income gatekeeper.

    This keeps the graph interface clean while ensuring that the agent
    remains responsible only for salary detection.
    """

    def run(
        self,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return run_income_agent(candidates)


income_agent = IncomeAgent()