from src.graph.state import IncomeState

from src.extraction.cam_extraction import (
    analyze_monthly_counterparty,
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
# CAM EXTRACTION
# ============================================================

def extract_cam_node(
    state: IncomeState,
) -> IncomeState:

    cam_path = state["cam_path"]

    result = analyze_monthly_counterparty(
        cam_path
    )


    return {
        "cam_result": result
    }


# ============================================================
# NODE 2
# PREPARE CANDIDATES
# ============================================================

def prepare_candidates_node(
    state: IncomeState,
) -> IncomeState:

    cam_result = state.get(
        "cam_result",
        {}
    )

    """
    The current extractor returns one `probable_salary`
    result rather than multiple candidates.

    Therefore, for now, treat probable_salary as candidate #0.

    Later, if the extractor exposes multiple candidates,
    this node can simply pass those candidates through.
    """

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
# INCOME AGENT / GATEKEEPER
# ============================================================

def income_agent_node(
    state: IncomeState,
) -> IncomeState:

    candidates = state.get(
        "candidates",
        []
    )

    # --------------------------------------------------------
    # The Income Agent is ONLY a gatekeeper.
    #
    # It does NOT generate:
    # - salary
    # - company
    # - payouts
    # - payment mode
    # - confidence score
    #
    # It only returns:
    #
    # {
    #     "detected": True/False,
    #     "reason": "..."
    # }
    # --------------------------------------------------------

    decision = run_income_agent(
        candidates
    )

    return {
        "income_decision": decision
    }


# ============================================================
# NODE 4
# VALIDATION
# ============================================================

def validate_income_node(
    state: IncomeState,
) -> IncomeState:

    decision = state.get(
        "income_decision"
    )

    # --------------------------------------------------------
    # No agent decision
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # AGENT REJECTED
    # --------------------------------------------------------

    if detected is not True:

        return {
            "validation": {
                "valid": False,
                "reason": reason,
            }
        }

    # --------------------------------------------------------
    # AGENT ACCEPTED
    # --------------------------------------------------------

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

def build_income_graph():

    graph = StateGraph(
        IncomeState
    )

    # --------------------------------------------------------
    # Nodes
    # --------------------------------------------------------

    graph.add_node(
        "extract_cam",
        extract_cam_node,
    )

    graph.add_node(
        "prepare_candidates",
        prepare_candidates_node,
    )

    graph.add_node(
        "income_agent",
        income_agent_node,
    )

    graph.add_node(
        "validate_income",
        validate_income_node,
    )

    # --------------------------------------------------------
    # Edges
    # --------------------------------------------------------

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

income_graph = build_income_graph()