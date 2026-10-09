from typing import TypedDict, Any


class IncomeState(TypedDict, total=False):
    """
    State carried through the Income Agent graph.
    """

    # Input
    cam_path: str

    # Output from existing CAM extractor
    cam_result: dict[str, Any]

    # Salary candidates passed to the agent
    candidates: list[dict[str, Any]]

    # Decision made by Income Agent
    income_decision: dict[str, Any]

    # Final validation result
    validation: dict[str, Any]

    # Error information
    error: str | None


class CamState(IncomeState):
    """
    State carried through the CAM extraction graph.

    Extends IncomeState with agent reasoning metadata so the
    graph can route weak or stale chains to deterministic
    review before the Income Agent gatekeeper runs.
    """

    # Calibrated confidence from CamAgent (None when no salary)
    confidence: float | None

    # Chain ended long before the file's last transaction
    is_stale: bool

    # (file_max - chain_last).days, None when no chain
    stale_gap_days: int | None

    # True when the chain should pass through review node
    needs_review: bool

    # Deterministic second-look outcome, None when skipped
    review: dict[str, Any] | None

    # "llm" when the model found the chain, "rules" otherwise
    discovery: str | None

    # Model failure reason, None on LLM success
    llm_error: str | None