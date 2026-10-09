"""Legacy CAM extractor (backward compatibility).

The shared toolkit now lives in `src.extraction.cam_tools`. This
module keeps the original entry points (`analyze_transactions`,
`analyze_monthly_counterparty`) working for existing callers such
as `src.graph.income_graph`. New code should use `cam_tools`
directly (tools) or `src.agents.cam_agent` (agent pipeline).
"""

from pathlib import Path

import numpy as np
import pandas as pd

from src.extraction.cam_tools import (
    build_agent_result,
    build_recurring_chains,
    detect_transaction_columns,
    extract_credit_transactions,
    extract_monthly_average_balance,
    find_transaction_sheet,
    score_candidate,
)

def analyze_transactions(
    excel_file: Path
):

    excel_file = Path(
        excel_file
    )

    if not excel_file.exists():

        raise FileNotFoundError(
            f"CAM file not found: {excel_file}"
        )

    # ========================================================
    # 1. FIND TRANSACTION SHEET
    # ========================================================

    transaction_sheet = find_transaction_sheet(
        excel_file
    )

    df = pd.read_excel(
        excel_file,
        sheet_name=transaction_sheet
    )

    # ========================================================
    # 2. MONTHLY AVERAGE BALANCE
    # ========================================================

    monthly_average_balance = (
        extract_monthly_average_balance(
            excel_file
        )
    )

    # ========================================================
    # 3. HANDLE EMPTY TRANSACTION SHEET
    # ========================================================

    if df.empty:

        return {
            "probable_salary": None,
            "monthly_average_balance":
                monthly_average_balance,
        }

    # ========================================================
    # 4. DETECT COLUMNS
    # ========================================================

    columns = detect_transaction_columns(
        df
    )

    # ========================================================
    # 5. EXTRACT CREDIT TRANSACTIONS
    # ========================================================

    transactions = extract_credit_transactions(
        df,
        columns
    )

    if not transactions:

        return {
            "probable_salary": None,
            "monthly_average_balance":
                monthly_average_balance,
        }

    # ========================================================
    # 6. FIND RECURRING SALARY PATTERNS
    # ========================================================

    candidates = build_recurring_chains(
        transactions
    )

    if not candidates:

        return {
            "probable_salary": None,
            "monthly_average_balance":
                monthly_average_balance,
        }

    # ========================================================
    # 7. SCORE CANDIDATES
    # ========================================================

    scored = []

    for chain in candidates:

        scored.append(
            {
                "chain": chain,
                "score": score_candidate(
                    chain
                ),
            }
        )

    # ========================================================
    # 8. REMOVE DUPLICATE CHAINS
    # ========================================================

    unique = {}

    for candidate in scored:

        chain = candidate["chain"]

        signature = tuple(
            (
                tx["date"].date(),
                round(
                    tx["amount"],
                    2
                )
            )
            for tx in chain
        )

        unique[signature] = candidate

    scored = list(
        unique.values()
    )

    if not scored:

        return {
            "probable_salary": None,
            "monthly_average_balance":
                monthly_average_balance,
        }

    # ========================================================
    # 9. SELECT BEST SALARY CANDIDATE
    # ========================================================

    scored.sort(
        key=lambda item: (
            item["score"],
            len(item["chain"]),
            max(
                tx["date"]
                for tx in item["chain"]
            ),
        ),
        reverse=True
    )

    best_chain = scored[0]["chain"]

    # ========================================================
    # 10. FINAL RESULT
    # ========================================================

    return {
        "probable_salary": build_agent_result(
            best_chain
        ),

        "monthly_average_balance":
            monthly_average_balance,
    }


# ============================================================
# BACKWARD COMPATIBILITY
# ============================================================

def analyze_monthly_counterparty(
    excel_file: Path
):
    """
    Backward-compatible function.

    Existing FastAPI code can continue using:

        analyze_monthly_counterparty()

    Internally it uses transaction-based
    salary detection.
    """

    return analyze_transactions(
        excel_file
    )


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    import sys
    import json

    if len(sys.argv) < 2:

        print(
            "Usage:"
        )

        print(
            "python cam_extraction_v2.py <CAM_FILE>"
        )

        raise SystemExit(1)

    file_path = Path(
        sys.argv[1]
    )

    result = analyze_transactions(
        file_path
    )

    print(
        json.dumps(
            result,
            indent=4,
            default=str
        )
    )