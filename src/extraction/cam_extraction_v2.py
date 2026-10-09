from pathlib import Path
import re
import math

import pandas as pd
import numpy as np


# ============================================================
# CONFIGURATION
# ============================================================

MIN_RECURRING_CREDITS = 3

MIN_DAYS_BETWEEN = 25
MAX_DAYS_BETWEEN = 40

MIN_SALARY_AMOUNT = 3000

SALARY_AMOUNT_TOLERANCE_PERCENT = 0.20

MIN_ABSOLUTE_TOLERANCE = 500


# ============================================================
# BASIC CLEANING
# ============================================================

def clean_amount(value):
    """
    Convert Excel values into positive float amounts.
    """

    if pd.isna(value):
        return None

    if isinstance(value, str):

        value = (
            value
            .replace(",", "")
            .replace("₹", "")
            .replace("Rs.", "")
            .replace("Rs", "")
            .strip()
        )

        if value.lower() in {
            "",
            "-",
            "nan",
            "none",
            "null",
        }:
            return None

    try:

        amount = float(value)

        if not math.isfinite(amount):
            return None

        if amount <= 0:
            return None

        return amount

    except (ValueError, TypeError):

        return None


def normalize_text(value):

    if pd.isna(value):
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).upper().strip()
    )


def normalize_for_matching(value):

    text = normalize_text(value)

    text = re.sub(
        r"[^A-Z0-9 ]",
        " ",
        text
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# ============================================================
# FIND TRANSACTION SHEET
# ============================================================

def find_transaction_sheet(excel_file):

    excel = pd.ExcelFile(excel_file)

    exact_names = {
        "transaction",
        "transactions",
        "transaction details",
        "transactions details",
        "transaction detail",
    }

    for sheet in excel.sheet_names:

        normalized = (
            str(sheet)
            .lower()
            .replace("_", " ")
            .replace("-", " ")
            .strip()
        )

        if normalized in exact_names:
            return sheet

    # Fallback
    for sheet in excel.sheet_names:

        if "transaction" in str(sheet).lower():

            return sheet

    raise ValueError(
        "Transaction sheet not found."
    )


# ============================================================
# FIND SUMMARY SHEET
# ============================================================

def find_summary_sheet(excel_file):

    excel = pd.ExcelFile(excel_file)

    exact_names = {
        "summary",
        "summaries",
        "account summary",
        "bank summary",
    }

    for sheet in excel.sheet_names:

        normalized = (
            str(sheet)
            .lower()
            .replace("_", " ")
            .replace("-", " ")
            .strip()
        )

        if normalized in exact_names:

            return sheet

    # Fallback
    for sheet in excel.sheet_names:

        if "summary" in str(sheet).lower():

            return sheet

    return None


# ============================================================
# GENERIC COLUMN FINDER
# ============================================================

def find_column(df, names):

    normalized_columns = {}

    for column in df.columns:

        normalized_columns[
            normalize_for_matching(column)
        ] = column

    # Exact match
    for name in names:

        key = normalize_for_matching(name)

        if key in normalized_columns:

            return normalized_columns[key]

    # Partial match
    for column in df.columns:

        column_name = normalize_for_matching(
            column
        )

        for name in names:

            search_name = normalize_for_matching(
                name
            )

            if search_name in column_name:

                return column

    return None


# ============================================================
# TRANSACTION COLUMN DETECTION
# ============================================================

def detect_transaction_columns(df):

    date_column = find_column(
        df,
        [
            "Txn date",
            "Transaction Date",
            "Date",
            "Value Date",
            "Posting Date",
        ]
    )

    credit_column = find_column(
        df,
        [
            "Credit(₹)",
            "Credit",
            "Credit Amount",
            "Credits",
            "Credit Amount (INR)",
        ]
    )

    particulars_column = find_column(
        df,
        [
            "Particulars",
            "Description",
            "Narration",
            "Transaction Details",
            "Remarks",
        ]
    )

    counterparty_column = find_column(
        df,
        [
            "Counterparty",
            "Counter Party",
            "Beneficiary",
            "Payer",
            "Sender",
        ]
    )

    tags_column = find_column(
        df,
        [
            "Tags",
        ]
    )

    category_column = find_column(
        df,
        [
            "Category",
        ]
    )

    if date_column is None:

        raise ValueError(
            "Transaction date column not found."
        )

    if credit_column is None:

        raise ValueError(
            "Credit column not found."
        )

    return {
        "date": date_column,
        "credit": credit_column,
        "particulars": particulars_column,
        "counterparty": counterparty_column,
        "tags": tags_column,
        "category": category_column,
    }


# ============================================================
# EXTRACT CREDIT TRANSACTIONS
# ============================================================

def extract_credit_transactions(
    df,
    columns
):

    transactions = []

    for index, row in df.iterrows():

        amount = clean_amount(
            row[
                columns["credit"]
            ]
        )

        if amount is None:
            continue

        date = pd.to_datetime(
            row[
                columns["date"]
            ],
            errors="coerce"
        )

        if pd.isna(date):
            continue

        particulars = ""

        if columns["particulars"] is not None:

            particulars = normalize_text(
                row[
                    columns["particulars"]
                ]
            )

        counterparty = ""

        if columns["counterparty"] is not None:

            counterparty = normalize_text(
                row[
                    columns["counterparty"]
                ]
            )

        tags = ""

        if columns["tags"] is not None:

            tags = normalize_text(
                row[
                    columns["tags"]
                ]
            )

        category = ""

        if columns["category"] is not None:

            category = normalize_text(
                row[
                    columns["category"]
                ]
            )

        transactions.append(
            {
                "row_index": int(index),
                "date": date.to_pydatetime(),
                "amount": amount,
                "particulars": particulars,
                "counterparty": counterparty,
                "tags": tags,
                "category": category,
            }
        )

    transactions.sort(
        key=lambda x: x["date"]
    )

    return transactions


# ============================================================
# AMOUNT SIMILARITY
# ============================================================

def amounts_are_similar(
    amount1,
    amount2
):

    if amount1 <= 0 or amount2 <= 0:
        return False

    difference = abs(
        amount1 - amount2
    )

    reference = (
        amount1 + amount2
    ) / 2

    allowed_absolute = max(
        MIN_ABSOLUTE_TOLERANCE,
        reference
        * SALARY_AMOUNT_TOLERANCE_PERCENT
    )

    relative_difference = (
        difference / reference
    )

    return (
        difference <= allowed_absolute
        and
        relative_difference
        <= SALARY_AMOUNT_TOLERANCE_PERCENT
    )


# ============================================================
# TEXT SIMILARITY
# ============================================================

def text_similarity(
    text1,
    text2
):

    text1 = normalize_for_matching(
        text1
    )

    text2 = normalize_for_matching(
        text2
    )

    if not text1 or not text2:
        return False

    if text1 == text2:
        return True

    tokens1 = set(
        text1.split()
    )

    tokens2 = set(
        text2.split()
    )

    if not tokens1 or not tokens2:
        return False

    overlap = (
        len(tokens1 & tokens2)
        /
        max(
            len(tokens1),
            len(tokens2)
        )
    )

    return overlap >= 0.5


# ============================================================
# PAYMENT MODE DETECTION
# ============================================================

def detect_payment_mode(tx):

    text = (
        tx["particulars"]
        + " "
        + tx["tags"]
        + " "
        + tx["category"]
    ).upper()

    modes = [
        "NEFT",
        "IMPS",
        "RTGS",
        "NACH",
        "ACH",
        "ECS",
        "UPI",
        "PFMS",
        "TRANSFER",
    ]

    for mode in modes:

        if mode in text:

            return mode

    return "Unknown"


# ============================================================
# SOURCE CONSISTENCY
# ============================================================

def transactions_have_same_source(
    tx1,
    tx2
):

    # Counterparty match
    if (
        tx1["counterparty"]
        and
        tx2["counterparty"]
    ):

        if text_similarity(
            tx1["counterparty"],
            tx2["counterparty"]
        ):

            return True

    # Particulars match
    if text_similarity(
        tx1["particulars"],
        tx2["particulars"]
    ):

        return True

    # Tags match
    if text_similarity(
        tx1["tags"],
        tx2["tags"]
    ):

        return True

    # Payment mode match
    mode1 = detect_payment_mode(tx1)
    mode2 = detect_payment_mode(tx2)

    if (
        mode1 != "Unknown"
        and
        mode1 == mode2
    ):

        return True

    return False


# ============================================================
# BUILD RECURRING SALARY CHAINS
# ============================================================

def build_recurring_chains(
    transactions
):

    candidates = []

    salary_transactions = [
        tx
        for tx in transactions
        if tx["amount"]
        >= MIN_SALARY_AMOUNT
    ]

    for start_index in range(
        len(salary_transactions)
    ):

        chain = [
            salary_transactions[
                start_index
            ]
        ]

        for next_index in range(
            start_index + 1,
            len(salary_transactions)
        ):

            previous = chain[-1]

            current = (
                salary_transactions[
                    next_index
                ]
            )

            days = (
                current["date"]
                -
                previous["date"]
            ).days

            if days < MIN_DAYS_BETWEEN:
                continue

            if days > MAX_DAYS_BETWEEN:
                break

            median_amount = np.median(
                [
                    tx["amount"]
                    for tx in chain
                ]
            )

            if not amounts_are_similar(
                current["amount"],
                median_amount
            ):

                continue

            chain.append(
                current
            )

        if (
            len(chain)
            >= MIN_RECURRING_CREDITS
        ):

            candidates.append(
                chain
            )

    return candidates


# ============================================================
# SCORE SALARY CANDIDATE
# ============================================================

def score_candidate(
    chain
):

    if len(chain) < 2:
        return 0

    score = 0

    # --------------------------------------------------------
    # Timing score = 40
    # --------------------------------------------------------

    intervals = []

    for i in range(
        1,
        len(chain)
    ):

        intervals.append(
            (
                chain[i]["date"]
                -
                chain[i - 1]["date"]
            ).days
        )

    valid_intervals = sum(
        MIN_DAYS_BETWEEN
        <= days
        <= MAX_DAYS_BETWEEN
        for days in intervals
    )

    score += (
        valid_intervals
        /
        len(intervals)
    ) * 40

    # --------------------------------------------------------
    # Amount consistency = 30
    # --------------------------------------------------------

    median_amount = np.median(
        [
            tx["amount"]
            for tx in chain
        ]
    )

    similar_amounts = sum(
        amounts_are_similar(
            tx["amount"],
            median_amount
        )
        for tx in chain
    )

    score += (
        similar_amounts
        /
        len(chain)
    ) * 30

    # --------------------------------------------------------
    # Source / payment consistency = 30
    # --------------------------------------------------------

    source_matches = 0

    for i in range(
        1,
        len(chain)
    ):

        if transactions_have_same_source(
            chain[i - 1],
            chain[i]
        ):

            source_matches += 1

    score += (
        source_matches
        /
        len(intervals)
    ) * 30

    return round(
        min(score, 100),
        2
    )


# ============================================================
# EXTRACT COMPANY / COUNTERPARTY
# ============================================================

def extract_source(
    chain
):

    counterparties = [
        tx["counterparty"]
        for tx in chain
        if tx["counterparty"]
    ]

    if counterparties:

        counts = {}

        for value in counterparties:

            counts[value] = (
                counts.get(value, 0)
                + 1
            )

        return max(
            counts,
            key=counts.get
        )

    particulars = [
        tx["particulars"]
        for tx in chain
        if tx["particulars"]
    ]

    if particulars:

        counts = {}

        for value in particulars:

            counts[value] = (
                counts.get(value, 0)
                + 1
            )

        return max(
            counts,
            key=counts.get
        )

    return "Unknown"


# ============================================================
# BUILD SALARY RESULT
# ============================================================

def build_result(
    chain
):

    chain = sorted(
        chain,
        key=lambda x: x["date"]
    )

    amounts = [
        tx["amount"]
        for tx in chain
    ]

    latest = chain[-1]

    return {
        "company": extract_source(
            chain
        ),

        "latest_salary": round(
            latest["amount"],
            2
        ),

        "average_salary": round(
            float(np.mean(amounts)),
            2
        ),

        "median_salary": round(
            float(np.median(amounts)),
            2
        ),

        "credits": len(chain),

        "payment_mode": detect_payment_mode(
            latest
        ),

        "confidence_score": score_candidate(
            chain
        ),

        # Date and amount positions correspond.
        "months": [
            tx["date"].strftime(
                "%Y-%m-%d"
            )
            for tx in chain
        ],

        "amounts": [
            round(
                tx["amount"],
                2
            )
            for tx in chain
        ],
    }


# ============================================================
# MONTHLY AVERAGE BALANCE
# ============================================================

def extract_monthly_average_balance(
    excel_file
):
    """
    Find the row containing:

        Monthly Avg Balance

    Then scan the ENTIRE row from left to right.

    The LAST numeric value in that row is returned.

    Example:

        Monthly Avg Balance | 1200 | 1800 | 2200 | 4550.61

    Result:

        4550.61
    """

    sheet_name = find_summary_sheet(
        excel_file
    )

    if sheet_name is None:
        return None

    df = pd.read_excel(
        excel_file,
        sheet_name=sheet_name,
        header=None
    )

    if df.empty:
        return None

    matching_rows = []

    # --------------------------------------------------------
    # Find ALL rows containing Monthly Avg Balance
    # --------------------------------------------------------

    for row_index in range(
        df.shape[0]
    ):

        row_text = " ".join(
            normalize_text(value)
            for value in df.iloc[row_index]
            if not pd.isna(value)
        )

        normalized_row = normalize_for_matching(
            row_text
        )

        if (
            "MONTHLY AVG BALANCE"
            in normalized_row
            or
            "MONTHLY AVERAGE BALANCE"
            in normalized_row
        ):

            matching_rows.append(
                row_index
            )

    if not matching_rows:
        return None

    # --------------------------------------------------------
    # Use the LAST matching row
    # --------------------------------------------------------

    target_row = matching_rows[-1]

    numeric_values = []

    # --------------------------------------------------------
    # Scan EVERY column in the row
    # --------------------------------------------------------

    for column_index in range(
        df.shape[1]
    ):

        value = clean_amount(
            df.iloc[
                target_row,
                column_index
            ]
        )

        if value is not None:

            numeric_values.append(
                value
            )

    # --------------------------------------------------------
    # RETURN THE LAST VALUE
    # --------------------------------------------------------

    if not numeric_values:
        return None

    return round(
        numeric_values[-1],
        2
    )


# ============================================================
# MAIN TRANSACTION ANALYZER
# ============================================================

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
        "probable_salary": build_result(
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

    Old FastAPI code can continue using:

        analyze_monthly_counterparty()

    Internally it now uses transaction-based
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