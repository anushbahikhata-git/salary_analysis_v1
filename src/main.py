from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Form,
)

from pathlib import Path
import shutil
import uuid


from src.extraction.credit_extraction import (
    extract_credit_report_text,
)

from src.llm.credit_analyzer import (
    analyze_credit_report,
)

from src.calculations.final_analyzer import (
    calculate_credit_capacity,
)

from src.response.response_builder import (
    build_final_response,
)

from src.graph.income_graph import (
    income_graph,
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Credit Risk Assessment",
    description="CAM Salary + Credit Report Analysis",
    version="1.0.2",
)


# ============================================================
# INPUT DIRECTORY
# ============================================================

INPUT_DIR = Path("data/input")

INPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "status": "running",
        "service": "CDL Credit Risk Assessment",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "healthy",
    }


# ============================================================
# CREDIT ASSESSMENT
# ============================================================

@app.post("/credit-assessment")
async def credit_assessment(

    cam_file: UploadFile | None = File(None),

    credit_file: UploadFile | None = File(None),

    loan_type: str | None = Form(None),
):

    # ========================================================
    # 1. AT LEAST ONE FILE REQUIRED
    # ========================================================

    if (
        cam_file is None
        and credit_file is None
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "At least one file must be uploaded: "
                "CAM or credit report."
            ),
        )


    # ========================================================
    # 2. VALIDATE LOAN TYPE
    # ========================================================

    # Loan type is only required when BOTH files are provided
    # because only then do we calculate final credit capacity.

    if (
        cam_file is not None
        and credit_file is not None
    ):

        if not loan_type:

            raise HTTPException(
                status_code=400,
                detail=(
                    "loan_type is required when both CAM "
                    "and credit report are provided. "
                    "Use CDL or MSME."
                ),
            )

        loan_type = loan_type.strip().upper()

        if loan_type not in (
            "CDL",
            "MSME",
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid loan_type. "
                    "Allowed values: CDL, MSME."
                ),
            )

    elif loan_type is not None:

        loan_type = loan_type.strip().upper()

        if loan_type not in (
            "CDL",
            "MSME",
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid loan_type. "
                    "Allowed values: CDL, MSME."
                ),
            )


    # ========================================================
    # 3. RESULT CONTAINERS
    # ========================================================

    # Complete CAM result after Income Graph
    cam_result = None

    # Validated salary result.
    #
    # IMPORTANT:
    # This will only be populated when the Income Agent
    # detects salary.
    salary_result = None

    # Income Agent decision
    income_agent = None

    # Credit result
    credit_result = None

    # Final credit capacity
    final_result = None

    cam_path = None
    credit_path = None


    # ========================================================
    # 4. SAVE CAM FILE
    # ========================================================

    if cam_file is not None:

        if not cam_file.filename:

            raise HTTPException(
                status_code=400,
                detail="CAM file has no filename.",
            )

        if not cam_file.filename.lower().endswith(
            (".xlsx", ".xls")
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "CAM must be an Excel file "
                    "(.xlsx or .xls)."
                ),
            )

        unique_name = (
            f"{uuid.uuid4().hex}_"
            f"{Path(cam_file.filename).name}"
        )

        cam_path = INPUT_DIR / unique_name

        try:

            with cam_path.open("wb") as buffer:

                shutil.copyfileobj(
                    cam_file.file,
                    buffer,
                )

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Failed to save CAM file: {str(e)}"
                ),
            )


    # ========================================================
    # 5. SAVE CREDIT REPORT
    # ========================================================

    if credit_file is not None:

        if not credit_file.filename:

            raise HTTPException(
                status_code=400,
                detail="Credit report has no filename.",
            )

        if not credit_file.filename.lower().endswith(
            (".pdf", ".xlsx", ".xls")
        ):

            raise HTTPException(
                status_code=400,
                detail=(
                    "Credit report must be "
                    "PDF, XLSX or XLS."
                ),
            )

        unique_name = (
            f"{uuid.uuid4().hex}_"
            f"{Path(credit_file.filename).name}"
        )

        credit_path = INPUT_DIR / unique_name

        try:

            with credit_path.open("wb") as buffer:

                shutil.copyfileobj(
                    credit_file.file,
                    buffer,
                )

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Failed to save credit report: "
                    f"{str(e)}"
                ),
            )


    # ========================================================
    # 6. CAM SALARY ANALYSIS
    # ========================================================

    if cam_path is not None:

        try:

            # ------------------------------------------------
            # Run the complete Income Graph.
            #
            # Graph:
            #
            # CAM
            #  ↓
            # Extractor
            #  ↓
            # Candidate
            #  ↓
            # Income Agent
            #  ↓
            # Validation
            #
            # ------------------------------------------------

            income_graph_result = income_graph.invoke(
                {
                    "cam_path": str(cam_path),
                }
            )

            # ------------------------------------------------
            # Get complete extractor result
            # ------------------------------------------------

            cam_result = income_graph_result.get(
                "cam_result",
                {},
            )

            # ------------------------------------------------
            # Get Income Agent decision
            # ------------------------------------------------

            income_agent = income_graph_result.get(
                "income_decision",
            )

            if income_agent is None:

                income_agent = {
                    "detected": False,
                    "reason": (
                        "Income Agent returned no decision."
                    ),
                }

            # ------------------------------------------------
            # IMPORTANT GATE
            # ------------------------------------------------
            #
            # The extractor is the source of income data.
            #
            # The agent only decides whether that extractor
            # result is valid salary income.
            #
            # TRUE:
            #     pass extractor result forward
            #
            # FALSE:
            #     salary_result remains None
            #
            # ------------------------------------------------

            if income_agent.get(
                "detected",
                False,
            ) is True:

                salary_result = cam_result

            else:

                salary_result = None

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    "CAM salary detection failed: "
                    f"{str(e)}"
                ),
            )


    # ========================================================
    # 7. CREDIT REPORT EXTRACTION
    # ========================================================

    if credit_path is not None:

        try:

            credit_context = extract_credit_report_text(
                credit_path,
            )

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Credit report extraction failed: "
                    f"{str(e)}"
                ),
            )

        # ====================================================
        # 8. CREDIT REPORT LLM ANALYSIS
        # ====================================================

        try:

            credit_result = analyze_credit_report(
                credit_context,
            )

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Credit report LLM analysis failed: "
                    f"{str(e)}"
                ),
            )


    # ========================================================
    # 9. FINAL CREDIT CAPACITY
    # ========================================================
    #
    # Only when BOTH:
    #
    # 1. Salary was detected by Income Agent
    # 2. Credit report exists
    #
    # are we allowed to calculate credit capacity.
    #
    # ========================================================

    if (
        salary_result is not None
        and credit_result is not None
    ):

        probable_salary = salary_result.get(
            "probable_salary",
        )

        if not probable_salary:

            raise HTTPException(
                status_code=422,
                detail=(
                    "Income Agent detected salary, "
                    "but extractor returned no "
                    "probable salary."
                ),
            )


        # ----------------------------------------------------
        # Prefer latest salary
        # ----------------------------------------------------

        monthly_salary = probable_salary.get(
            "latest_salary",
        )


        # ----------------------------------------------------
        # Backward compatibility with old extractor
        # ----------------------------------------------------

        if monthly_salary is None:

            monthly_salary = probable_salary.get(
                "salary",
            )


        if (
            monthly_salary is None
            or monthly_salary <= 0
        ):

            raise HTTPException(
                status_code=422,
                detail=(
                    "Invalid salary detected "
                    "from CAM report."
                ),
            )


        # ----------------------------------------------------
        # Get existing EMI
        # ----------------------------------------------------

        monthly_emi = credit_result.get(
            "monthly_emi",
        )

        if monthly_emi is None:

            raise HTTPException(
                status_code=422,
                detail=(
                    "Monthly EMI could not be "
                    "determined from credit report."
                ),
            )


        # ----------------------------------------------------
        # Final calculation
        # ----------------------------------------------------

        try:

            final_result = calculate_credit_capacity(
                monthly_salary=monthly_salary,
                monthly_emi=monthly_emi,
                loan_type=loan_type,
            )

        except Exception as e:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Final credit calculation failed: "
                    f"{str(e)}"
                ),
            )


    # ========================================================
    # 10. REQUEST TYPE
    # ========================================================

    if (
        cam_path is not None
        and credit_path is not None
    ):

        request_type = "full_assessment"

    elif cam_path is not None:

        request_type = "cam_only"

    else:

        request_type = "credit_only"


    # ========================================================
    # 11. FINAL RESPONSE
    # ========================================================

    return build_final_response(

        request_type=request_type,

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Only pass salary_result when the Income Agent
        # approved it.
        # ----------------------------------------------------

        salary_result=(
            salary_result["probable_salary"]
            if salary_result is not None
            and salary_result.get("probable_salary")
            else None
        ),

        # ----------------------------------------------------
        # Balance is independent of salary detection.
        #
        # Even if salary is rejected, we still expose the
        # monthly average balance calculated by the extractor.
        # ----------------------------------------------------

        monthly_average_balance=(
            cam_result.get(
                "monthly_average_balance"
            )
            if cam_result
            else None
        ),

        # ----------------------------------------------------
        # Credit
        # ----------------------------------------------------

        credit_result=credit_result,

        # ----------------------------------------------------
        # Credit decision
        # ----------------------------------------------------

        credit_decision=final_result,

        # ----------------------------------------------------
        # Income Agent decision
        # ----------------------------------------------------

        income_agent=income_agent,
    )