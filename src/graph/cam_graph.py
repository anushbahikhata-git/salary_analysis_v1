from datetime import datetime

import numpy as np

from src.graph.state import CamState

from src.extraction.cam_tools import (
    MIN_DAYS_BETWEEN,
    MAX_DAYS_BETWEEN,
    SALARY_AMOUNT_TOLERANCE_PERCENT,
    SALARY_EXCLUDED_PAYMENT_MODES,
)

from src.agents.cam_agent import (
    cam_agent,
    REVIEW_CONFIDENCE_THRESHOLD,
)

from src.agents.income_agent import (
    run_income_agent,
)

from langgraph.graph import (
    StateGraph,
    START,
    END,
)


# ============================================================
# NODE 1
# CAM AGENT EXTRACTION
# ============================================================

def extract_cam_node(
    state: CamState,
) -> CamState:

    result = cam_agent.run(
        state["cam_path"]
    )

    return {
        "cam_result": result["cam_result"],
        "confidence": result["confidence"],
        "is_stale": result["is_stale"],
        "stale_gap_days": result["stale_gap_days"],
        "discovery": result["discovery"],
        "llm_error": result["llm_error"],
    }


# ============================================================
# NODE 2
# PREPARE CANDIDATES
# ============================================================

def prepare_candidates_node(
    state: CamState,
) -> CamState:

    cam_result = state.get(
        "cam_result",
        {}
    )

    probable_salary = cam_result.get(
        "probable_salary"
    )

    if not probable_salary:
        return {
            "candidates": []
        }

    return {
        "candidates": [
            probable_salary
        ]
    }


# ============================================================
# NODE 3
# ASSESS REVIEW NEED
# ============================================================

def assess_review_node(
    state: CamState,
) -> CamState:

    confidence = state.get("confidence")

    is_stale = state.get(
        "is_stale",
        False,
    )

    if confidence is None:
        return {
            "needs_review": False,
        }

    needs_review = (
        confidence < REVIEW_CONFIDENCE_THRESHOLD
        or is_stale is True
    )

    return {
        "needs_review": bool(needs_review),
    }


# ============================================================
# ROUTER
# ============================================================

def route_after_assess(
    state: CamState,
) -> str:

    if state.get(
        "needs_review",
        False,
    ) is True:
        return "review_transactions"

    return "income_agent"


# ============================================================
# NODE 4
# DETERMINISTIC REVIEW (second look, no LLM)
# ============================================================

def review_transactions_node(
    state: CamState,
) -> CamState:

    candidates = state.get(
        "candidates",
        [],
    )

    if not candidates:
        return {
            "review": {
                "needed": True,
                "passed": False,
                "flags": [
                    "No extractor candidate exists."
                ],
                "notes": [],
            }
        }

    candidate = candidates[0]

    flags: list[str] = []
    notes: list[str] = []

    months = candidate.get("months", [])
    amounts = candidate.get("amounts", [])
    credits = candidate.get("credits", 0)
    payment_mode = str(
        candidate.get("payment_mode", "")
    ).strip().upper()
    company = str(
        candidate.get("company", "")
    ).strip()

    # --------------------------------------------------------
    # Shape checks
    # --------------------------------------------------------

    if not (
        len(months) == credits == len(amounts)
    ):
        flags.append(
            "months/credits/amounts length mismatch."
        )

    # --------------------------------------------------------
    # Timing checks (recurring window mirrors the chain tools)
    # --------------------------------------------------------

    try:
        dates = [
            datetime.strptime(month, "%Y-%m-%d")
            for month in months
        ]
    except (ValueError, TypeError):
        dates = []

        flags.append(
            "Unparseable payout dates."
        )

    if dates != sorted(dates):
        flags.append(
            "Payout dates are not in ascending order."
        )

    for earlier, later in zip(dates, dates[1:]):
        gap = (later - earlier).days

        if not MIN_DAYS_BETWEEN <= gap <= MAX_DAYS_BETWEEN:
            flags.append(
                f"Payout gap {gap} days outside "
                f"{MIN_DAYS_BETWEEN}-{MAX_DAYS_BETWEEN} window."
            )

            break

    # --------------------------------------------------------
    # Amount checks (tolerance mirrors the chain tools)
    # --------------------------------------------------------

    if amounts:
        median = float(np.median(amounts))

        for amount in amounts:
            if (
                median > 0
                and abs(amount - median) / median
                > SALARY_AMOUNT_TOLERANCE_PERCENT
            ):
                flags.append(
                    f"Credit {amount} deviates more than "
                    f"{SALARY_AMOUNT_TOLERANCE_PERCENT:.0%} "
                    "from median."
                )

                break

    # --------------------------------------------------------
    # Source checks
    # --------------------------------------------------------

    if payment_mode in SALARY_EXCLUDED_PAYMENT_MODES:
        flags.append(
            f"{payment_mode} credits are excluded "
            "from salary detection."
        )

    if not company or company.upper() == "UNKNOWN":
        flags.append(
            "Unresolved payer identity."
        )

    # --------------------------------------------------------
    # Staleness note (informational, never a lone reject)
    # --------------------------------------------------------

    if state.get("is_stale", False) is True:
        notes.append(
            "Chain ended "
            f"{state.get('stale_gap_days')} days before "
            "the file's last transaction; income may "
            "have stopped."
        )

    return {
        "review": {
            "needed": True,
            "passed": not flags,
            "flags": flags,
            "notes": notes,
        }
    }


# ============================================================
# NODE 5
# INCOME AGENT / GATEKEEPER
# ============================================================

def income_agent_node(
    state: CamState,
) -> CamState:

    candidates = state.get(
        "candidates",
        []
    )

    decision = run_income_agent(
        candidates
    )

    return {
        "income_decision": decision
    }


# ============================================================
# NODE 6
# VALIDATION
# ============================================================

def validate_income_node(
    state: CamState,
) -> CamState:

    # --------------------------------------------------------
    # Review ran and failed -> reject with review reason
    # --------------------------------------------------------

    review = state.get("review")

    if (
        review is not None
        and review.get("passed", True) is not True
    ):
        flags = review.get("flags", [])

        return {
            "validation": {
                "valid": False,
                "reason": (
                    "Review rejected the salary candidate: "
                    + "; ".join(flags)
                    if flags
                    else "Review rejected the salary candidate."
                ),
            }
        }

    # --------------------------------------------------------
    # Gatekeeper decision (same contract as income_graph)
    # --------------------------------------------------------

    decision = state.get(
        "income_decision"
    )

    if not decision:
        return {
            "validation": {
                "valid": False,
                "reason": (
                    "Income Agent returned no decision."
                ),
            }
        }

    detected = decision.get(
        "detected",
        False
    )

    reason = decision.get(
        "reason",
        "No valid salary detected."
    )

    if detected is not True:
        return {
            "validation": {
                "valid": False,
                "reason": reason,
            }
        }

    candidates = state.get(
        "candidates",
        []
    )

    if not candidates:
        return {
            "validation": {
                "valid": False,
                "reason": (
                    "Income Agent detected salary, "
                    "but no extractor candidate exists."
                ),
            }
        }

    return {
        "validation": {
            "valid": True,
            "reason": reason,
        }
    }


# ============================================================
# BUILD GRAPH
# ============================================================

def build_cam_graph():

    graph = StateGraph(
        CamState
    )

    graph.add_node(
        "extract_cam",
        extract_cam_node,
    )

    graph.add_node(
        "prepare_candidates",
        prepare_candidates_node,
    )

    graph.add_node(
        "assess_review",
        assess_review_node,
    )

    graph.add_node(
        "review_transactions",
        review_transactions_node,
    )

    graph.add_node(
        "income_agent",
        income_agent_node,
    )

    graph.add_node(
        "validate_income",
        validate_income_node,
    )

    graph.add_edge(
        START,
        "extract_cam",
    )

    graph.add_edge(
        "extract_cam",
        "prepare_candidates",
    )

    graph.add_edge(
        "prepare_candidates",
        "assess_review",
    )

    graph.add_conditional_edges(
        "assess_review",
        route_after_assess,
        {
            "review_transactions": "review_transactions",
            "income_agent": "income_agent",
        },
    )

    graph.add_edge(
        "review_transactions",
        "income_agent",
    )

    graph.add_edge(
        "income_agent",
        "validate_income",
    )

    graph.add_edge(
        "validate_income",
        END,
    )

    return graph.compile()


# ============================================================
# COMPILED GRAPH
# ============================================================

cam_graph = build_cam_graph()
