from pathlib import Path
import pandas as pd
import numpy as np


MAX_COUNTERPARTIES = 10
AMOUNT_TOLERANCE = 500
MIN_RECURRING_MONTHS = 3


def clean_amount(value):
    """Convert Excel amount to float."""

    if pd.isna(value):
        return None

    if isinstance(value, str):
        value = value.replace(",", "").replace("₹", "").strip()

        if value in ("", "-", "nan", "None"):
            return None

    try:
        amount = float(value)

        if amount <= 0:
            return None

        return amount

    except (ValueError, TypeError):
        return None


def find_monthly_counterparty_sheet(excel_file):

    excel = pd.ExcelFile(excel_file)

    for sheet in excel.sheet_names:

        normalized = (
            sheet.lower()
            .replace("_", " ")
            .replace("-", " ")
            .strip()
        )

        if normalized == "monthly counterparty":
            return sheet

    raise ValueError(
        "Monthly counterparty sheet not found"
    )


def extract_monthly_credit_columns(df):
    """
    Precisa structure:

    Row 0:
        Month

    Row 1:
        Credit(₹), Credit Txns, Debit(₹), Debit Txns

    Return:
        [(column_index, month_name), ...]
    """

    credit_columns = []

    for column_index in range(df.shape[1]):

        month = df.iloc[0, column_index]
        metric = df.iloc[1, column_index]

        if pd.isna(month) or pd.isna(metric):
            continue

        metric = str(metric).strip().lower()

        if metric == "credit(₹)":

            credit_columns.append(
                (
                    column_index,
                    str(month).strip()
                )
            )

    return credit_columns


def find_recurring_salary(monthly_credits):
    """
    Find a recurring salary-like credit pattern.

    monthly_credits:

        [
            {
                "month": "Nov 2023",
                "amount": 37300
            },
            ...
        ]
    """

    if not monthly_credits:
        return None

 

    amounts = [
        item["amount"]
        for item in monthly_credits
    ]

    best_cluster = None

    for base_amount in amounts:

        cluster = []

        for item in monthly_credits:

            if abs(item["amount"] - base_amount) <= AMOUNT_TOLERANCE:
                cluster.append(item)

        if best_cluster is None:
            best_cluster = cluster

        elif len(cluster) > len(best_cluster):
            best_cluster = cluster

    if not best_cluster:
        return None

    if len(best_cluster) < MIN_RECURRING_MONTHS:
        return None

    cluster_amounts = [
        item["amount"]
        for item in best_cluster
    ]

    average_salary = round(
        np.mean(cluster_amounts),
        2
    )

    return {
        "salary": average_salary,
        "credits": len(best_cluster),
        "months": [
            item["month"]
            for item in best_cluster
        ],
        "amounts": cluster_amounts
    }


def analyze_monthly_counterparty(excel_file: Path):

    sheet_name = find_monthly_counterparty_sheet(
        excel_file
    )

    # IMPORTANT:
    # header=None because Precisa has a two-row
    # header structure.
    df = pd.read_excel(
        excel_file,
        sheet_name=sheet_name,
        header=None
    )

    # First column = Counterparty
    counterparty_column = 0

    # Find monthly Credit(₹) columns
    credit_columns = extract_monthly_credit_columns(df)

    if not credit_columns:

        raise ValueError(
            "No monthly Credit(₹) columns found"
        )

    candidates = []

    # Rows 2 onwards are counterparties
    counterparty_rows = df.iloc[
        2:2 + MAX_COUNTERPARTIES
    ]

    for row_index in counterparty_rows.index:

        counterparty = df.iloc[
            row_index,
            counterparty_column
        ]

        if pd.isna(counterparty):
            continue

        counterparty = str(counterparty).strip()

        monthly_credits = []

        for column_index, month in credit_columns:

            amount = clean_amount(
                df.iloc[
                    row_index,
                    column_index
                ]
            )

            if amount is not None:

                monthly_credits.append({
                    "month": month,
                    "amount": amount
                })

        salary_pattern = find_recurring_salary(
            monthly_credits
        )

        if salary_pattern:

            candidates.append({
                "company": counterparty,
                "salary": salary_pattern["salary"],
                "credits": salary_pattern["credits"],
                "months": salary_pattern["months"],
                "amounts": salary_pattern["amounts"]
            })

    # Strongest recurring monthly candidate
    candidates.sort(
        key=lambda x: (
            x["credits"],
            -x["salary"]
        ),
        reverse=True
    )

    probable_salary = None

    if candidates:

        best = candidates[0]

        probable_salary = {
            "company": best["company"],
            "salary": best["salary"],
            "credits": best["credits"]
        }

    return {
        "probable_salary": probable_salary
    }