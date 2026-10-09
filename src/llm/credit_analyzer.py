import json

from src.llm.client import call_openrouter
from src.llm.prompts import CREDIT_REPORT_SYSTEM_PROMPT


def analyze_credit_report(credit_context: str) -> dict:

    user_prompt = f"""
Analyze the following credit report.

CREDIT REPORT:

{credit_context}

Return ONLY the required JSON.
"""

    response = call_openrouter(
        system_prompt=CREDIT_REPORT_SYSTEM_PROMPT,
        user_prompt=user_prompt,
    )

    response = response.strip()

    # Remove markdown code fences if the model returns them
    if response.startswith("```"):
        response = response.replace("```json", "")
        response = response.replace("```", "")
        response = response.strip()

    try:
        result = json.loads(response)

    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM returned invalid JSON: {response}"
        ) from e

    required_fields = [
        "credit_score",
        "monthly_emi",
        "total_outstanding_amount",
        "total_disbursement",
    ]

    for field in required_fields:
        if field not in result:
            raise ValueError(
                f"Missing field from LLM response: {field}"
            )

    return {
        "credit_score": result["credit_score"],
        "monthly_emi": result["monthly_emi"],
        "total_outstanding_amount": result[
            "total_outstanding_amount"
        ],
        "total_disbursement": result[
            "total_disbursement"
        ],
    }