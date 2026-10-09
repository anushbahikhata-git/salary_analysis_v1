def calculate_credit_capacity(
    monthly_salary: float,
    monthly_emi: float,
    loan_type: str,
) -> dict:
    """
    Calculate credit capacity based on:

    - Monthly salary
    - Existing monthly EMI
    - Loan type

    FOIR limits:
        CDL  -> 70%
        MSME -> 60%

    Returns:
        loan_type
        foir_limit
        foir
        max_emi_possible
        maximum_loan_possible
    """

    # ============================================================
    # 1. VALIDATE SALARY
    # ============================================================

    if monthly_salary is None or monthly_salary <= 0:

        return {
            "loan_type": (
                loan_type.upper()
                if loan_type
                else None
            ),
            "foir_limit": None,
            "foir": None,
            "max_emi_possible": None,
            "maximum_loan_possible": None,
        }

    # ============================================================
    # 2. VALIDATE EMI
    # ============================================================

    if monthly_emi is None or monthly_emi < 0:
        monthly_emi = 0.0

    # ============================================================
    # 3. VALIDATE LOAN TYPE
    # ============================================================

    if not loan_type:

        raise ValueError(
            "loan_type is required. "
            "Allowed values: CDL or MSME."
        )

    loan_type = str(
        loan_type
    ).strip().upper()

    if loan_type not in (
        "CDL",
        "MSME",
    ):

        raise ValueError(
            f"Invalid loan_type '{loan_type}'. "
            "Allowed values: CDL or MSME."
        )

    # ============================================================
    # 4. DETERMINE FOIR LIMIT
    # ============================================================

    if loan_type == "CDL":

        foir_limit = 0.70

    else:

        # MSME
        foir_limit = 0.60

    # ============================================================
    # 5. CURRENT FOIR
    #
    # Existing EMI / Salary
    #
    # Example:
    #
    # Salary = 40,000
    # EMI    = 10,000
    #
    # FOIR = 10,000 / 40,000
    #      = 0.25
    #      = 25%
    # ============================================================

    foir = (
        monthly_emi /
        monthly_salary
    )

    # ============================================================
    # 6. MAXIMUM TOTAL EMI ALLOWED
    #
    # CDL:
    #
    # Salary × 70%
    #
    # MSME:
    #
    # Salary × 60%
    # ============================================================

    maximum_total_emi = (
        monthly_salary *
        foir_limit
    )

    # ============================================================
    # 7. MAXIMUM ADDITIONAL EMI
    #
    # Maximum additional EMI =
    #
    # Maximum allowed total EMI
    # -
    # Existing EMI
    #
    # Never allow negative capacity.
    # ============================================================

    max_emi_possible = (
        maximum_total_emi -
        monthly_emi
    )

    max_emi_possible = max(
        0.0,
        max_emi_possible
    )

    # ============================================================
    # 8. MAXIMUM LOAN POSSIBLE
    #
    # Existing business rule:
    #
    # (Salary - Existing EMI) × 16
    #
    # Never allow negative loan capacity.
    # ============================================================

    maximum_loan_possible = (
        monthly_salary -
        monthly_emi
    ) * 16

    maximum_loan_possible = max(
        0.0,
        maximum_loan_possible
    )

    # ============================================================
    # 9. FINAL RESULT
    # ============================================================

    return {
        "loan_type": loan_type,

        "foir_limit": round(
            foir_limit,
            4
        ),

        "foir": round(
            foir,
            4
        ),

        "max_emi_possible": round(
            max_emi_possible,
            2
        ),

        "maximum_loan_possible": round(
            maximum_loan_possible,
            2
        ),
    }