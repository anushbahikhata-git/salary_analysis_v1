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