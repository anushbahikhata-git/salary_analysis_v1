from pathlib import Path
import glob
import json
import sys

import numpy as np

from src.agents.cam_agent import (
    cam_agent,
    STALE_THRESHOLD_DAYS,
)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_CAM = Path(
    "data/input/Yuvraj singh chauhan new cam-"
    "State Bank of India00000040914526721Savings.xlsx"
)


# ============================================================
# PROPERTY CHECKS (skill: cam-extractor-agent)
# ============================================================
#
# Generic invariants over the AGENT response — must hold for ANY
# cam, not just this one.

def check_salary(probable_salary: dict) -> list[str]:
    """Validate the salary payload inside cam_result."""

    violations = []

    months = probable_salary.get("months", [])
    amounts = probable_salary.get("amounts", [])
    credits = probable_salary.get("credits", 0)

    if not (
        len(months) == credits == len(amounts)
    ):
        violations.append(
            "months/credits/amounts length mismatch"
        )

    if months != sorted(months):
        violations.append("months not ascending")

    payment_mode = probable_salary.get(
        "payment_mode",
        "",
    )

    if payment_mode != str(payment_mode).upper():
        violations.append("payment_mode not uppercase")

    if payment_mode in {"UPI", "ATM"}:
        violations.append(
            f"excluded payment mode returned: {payment_mode}"
        )

    company = probable_salary.get("company", "")

    if not company:
        violations.append("empty company")

    if len(company) > 40 and "*" in company:
        violations.append(
            "company looks like raw narration"
        )

    # Confidence must equal the calibration formula
    # recomputed from the amounts themselves.
    if amounts:
        median = float(np.median(amounts))

        over_10 = sum(
            abs(amount - median) / median > 0.10
            for amount in amounts
        )

        band = sum(
            0.05 < abs(amount - median) / median <= 0.10
            for amount in amounts
        )

        expected = round(
            max(
                0.0,
                min(100.0, 100.0 - 5.0 * over_10 - 2.0 * band),
            ),
            2,
        )

        if probable_salary.get("confidence_score") != expected:
            violations.append(
                "confidence_score does not match formula "
                f"(got {probable_salary.get('confidence_score')}, "
                f"expected {expected})"
            )

    return violations


def check_agent_response(response: dict) -> list[str]:
    """Validate the full CamAgent.run response shape."""

    violations = []

    for key in (
        "cam_result",
        "confidence",
        "is_stale",
        "stale_gap_days",
        "discovery",
        "llm_error",
    ):
        if key not in response:
            violations.append(f"missing agent key: {key}")

    if response.get("discovery") not in {"llm", "rules"}:
        violations.append(
            f"bad discovery flag: {response.get('discovery')!r}"
        )

    if (
        response.get("discovery") == "llm"
        and response.get("llm_error") is not None
    ):
        violations.append(
            "llm_error set despite llm discovery"
        )

    if not isinstance(response.get("is_stale"), bool):
        violations.append("is_stale not boolean")

    cam_result = response.get("cam_result", {})

    if "probable_salary" not in cam_result:
        violations.append("missing probable_salary")

    if "monthly_average_balance" not in cam_result:
        violations.append("missing monthly_average_balance")

    probable_salary = cam_result.get("probable_salary")

    if probable_salary is None:
        if response.get("confidence") is not None:
            violations.append(
                "confidence set with no salary"
            )

        return violations

    violations.extend(
        check_salary(probable_salary)
    )

    if (
        response.get("confidence")
        != probable_salary.get("confidence_score")
    ):
        violations.append(
            "agent confidence differs from salary confidence"
        )

    gap = response.get("stale_gap_days")

    if gap is not None and response.get("is_stale") != (
        gap > STALE_THRESHOLD_DAYS
    ):
        violations.append(
            "is_stale inconsistent with stale_gap_days"
        )

    try:
        json.dumps(response, default=str)
    except TypeError:
        violations.append("agent response not JSON serializable")

    return violations


# ============================================================
# TEST
# ============================================================

def run_one(cam_file: Path) -> bool:

    print("=" * 60)
    print(f"CAM file: {cam_file}")

    if not cam_file.exists():
        print(f"SKIP: file not found: {cam_file}")
        return True

    response = cam_agent.run(cam_file)

    print(
        json.dumps(
            response,
            indent=4,
            ensure_ascii=False,
            default=str,
        )
    )

    print(
        f"discovery={response.get('discovery')} "
        f"llm_error={response.get('llm_error')} "
        f"stale={response.get('is_stale')} "
        f"gap={response.get('stale_gap_days')}"
    )

    violations = check_agent_response(response)

    if violations:
        print("CHECKS FAILED:")
        for violation in violations:
            print(f"  - {violation}")
        return False

    print("CHECKS PASSED")

    return True


def main() -> None:

    print("=" * 60)
    print("SALARY DETECTION TEST (CamAgent response)")
    print("=" * 60)

    if len(sys.argv) > 1:
        files = [Path(arg) for arg in sys.argv[1:]]
    elif DEFAULT_CAM.exists():
        files = [DEFAULT_CAM]
    else:
        files = [
            Path(path)
            for path in sorted(glob.glob("data/input/*.xlsx"))
            if "/~" not in path
        ]

    if not files:
        print("No CAM files found.")
        raise SystemExit(1)

    ok = True

    for cam_file in files:
        try:
            ok = run_one(cam_file) and ok
        except Exception as exc:
            print(f"ERROR {type(exc).__name__}: {exc}")
            ok = False

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
