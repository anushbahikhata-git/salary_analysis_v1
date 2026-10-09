from typing import Optional


# ============================================================
# INCOME RESPONSE
# ============================================================

def build_income_response(
    probable_salary: dict,
) -> dict:
    """
    Build the public Income response from the extractor result.

    IMPORTANT:
    The extractor remains the source of truth for all
    salary/income data.

    The Income Agent only decides whether this result
    should be accepted.
    """

    dates = probable_salary.get(
        "months",
        []
    )

    amounts = probable_salary.get(
        "amounts",
        []
    )

    payment_mode = probable_salary.get(
        "payment_mode"
    )

    payouts = []

    for date, amount in zip(
        dates,
        amounts
    ):
        payouts.append([
            date,
            amount,
            payment_mode,
        ])

    return {
        "type": "salary",
        "company": probable_salary.get(
            "company"
        ),
        "confidence_score": probable_salary.get(
            "confidence_score"
        ),
        "Payouts": payouts,
    }


# ============================================================
# CREDIT RESPONSE
# ============================================================

def build_credit_response(
    credit_result: dict,
) -> dict:
    """
    Build the public credit summary.
    """

    return {
        "monthly_emi": credit_result.get(
            "monthly_emi",
            0,
        ),
        "total_outstanding_amount": credit_result.get(
            "total_outstanding_amount",
            0,
        ),
        "total_disbursement": credit_result.get(
            "total_disbursement",
            0,
        ),
    }


# ============================================================
# CREDIT DECISION RESPONSE
# ============================================================

def build_credit_decision_response(
    credit_decision: dict,
) -> dict:
    """
    Build the public credit decision response.
    """

    return {
        "max_emi": credit_decision.get(
            "max_emi_possible"
        ),
        "max_amount": credit_decision.get(
            "maximum_loan_possible"
        ),
    }


# ============================================================
# AGENT RESPONSE
# ============================================================

def build_agent_response(
    income_agent: Optional[dict],
) -> dict:
    """
    Build the public Income Agent gatekeeper response.

    The agent is responsible only for:
        - detected
        - reason

    It does NOT provide salary information.
    """

    if not income_agent:

        return {
            "detected": False,
            "reason": "Income Agent returned no decision.",
        }

    return {
        "detected": income_agent.get(
            "detected",
            False,
        ),
        "reason": income_agent.get(
            "reason",
            "No valid salary detected.",
        ),
    }


# ============================================================
# FINAL RESPONSE
# ============================================================

def build_final_response(
    request_type: str,
    salary_result: Optional[dict] = None,
    monthly_average_balance: Optional[float] = None,
    credit_result: Optional[dict] = None,
    credit_decision: Optional[dict] = None,
    income_agent: Optional[dict] = None,
    review: Optional[dict] = None,
    agent_meta: Optional[dict] = None,
) -> dict:
    """
    Build the final public API response.

    Flow:

        Income Agent
              |
        +-----+-----+
        |           |
      TRUE        FALSE
        |           |
        v           v
    Income data    Income = None

    The extractor result is exposed only when the
    Income Agent has detected valid salary income.
    """

    response = {
        "success": True,
        "request_type": request_type,
    }

    # ---------------------------------------------------------
    # INCOME AGENT
    # ---------------------------------------------------------
    #
    # Keep the agent decision separate from Income.
    #
    # Example:
    #
    # "agent": {
    #     "detected": true,
    #     "reason": "Recurring salary credits..."
    # }
    #
    # ---------------------------------------------------------

    if income_agent is not None:

        response["agent"] = build_agent_response(
            income_agent
        )

    # ---------------------------------------------------------
    # INCOME
    # ---------------------------------------------------------
    #
    # IMPORTANT:
    #
    # salary_result should only be passed here when the
    # Income Agent has approved the extractor result.
    #
    # The response builder also performs the check as an
    # additional safety layer.
    #
    # ---------------------------------------------------------

    agent_detected = (
        income_agent is not None
        and income_agent.get(
            "detected",
            False
        ) is True
    )

    if (
        agent_detected
        and salary_result is not None
    ):

        response["Income"] = build_income_response(
            salary_result
        )

    else:

        response["Income"] = None

    # ---------------------------------------------------------
    # MONTHLY AVERAGE BALANCE
    # ---------------------------------------------------------
    #
    # Balance is independent of salary detection.
    #
    # It should still be returned even when the agent
    # rejects the salary candidate.
    #
    # ---------------------------------------------------------

    if monthly_average_balance is not None:

        response["monthly_average_balance"] = (
            monthly_average_balance
        )

    # ---------------------------------------------------------
    # CREDIT
    # ---------------------------------------------------------

    if credit_result is not None:

        response["credit"] = build_credit_response(
            credit_result
        )

    # ---------------------------------------------------------
    # CREDIT DECISION
    # ---------------------------------------------------------

    if credit_decision is not None:

        response["Credit_Decision"] = (
            build_credit_decision_response(
                credit_decision
            )
        )

    # ---------------------------------------------------------
    # REVIEW
    # ---------------------------------------------------------
    #
    # Additive and optional: present only when the CAM agent
    # graph routed the chain through deterministic review.
    # Explains Income=None cases where the gatekeeper accepted
    # but review rejected, and carries staleness notes.
    # Existing keys are never altered by this block.
    #
    # ---------------------------------------------------------

    if review is not None:

        response["review"] = {
            "passed": review.get(
                "passed",
                True,
            ),
            "flags": review.get(
                "flags",
                [],
            ),
            "notes": review.get(
                "notes",
                [],
            ),
        }

    # ---------------------------------------------------------
    # AGENT PROVENANCE
    # ---------------------------------------------------------
    #
    # Additive and optional: describes how the CamAgent reached
    # its verdict (model vs rule fallback, calibrated confidence,
    # staleness). Existing keys are never altered by this block.
    #
    # ---------------------------------------------------------

    if agent_meta is not None:

        meta = {
            "confidence": agent_meta.get(
                "confidence",
            ),
            "stale": agent_meta.get(
                "stale",
                False,
            ),
            "stale_gap_days": agent_meta.get(
                "stale_gap_days",
            ),
            "discovery": agent_meta.get(
                "discovery",
                "rules",
            ),
        }

        if agent_meta.get("llm_error") is not None:
            meta["llm_error"] = agent_meta["llm_error"]

        response["agent_meta"] = meta

    return response