from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from src.extraction import cam_tools as base


def _ensure_env() -> None:
    """Load .env without requiring python-dotenv to be installed."""

    import os
    import sys
    import types

    if "dotenv" not in sys.modules:
        try:
            import dotenv  # noqa: F401
        except ImportError:
            stub = types.ModuleType("dotenv")
            stub.load_dotenv = lambda *a, **k: None
            sys.modules["dotenv"] = stub

    env_file = (
        Path(__file__).resolve().parents[2] / ".env"
    )

    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()

            if (
                not line
                or line.startswith("#")
                or "=" not in line
            ):
                continue

            key, _, value = line.partition("=")

            os.environ.setdefault(
                key.strip(),
                value.strip(),
            )


# ============================================================
# REVIEW THRESHOLDS
# ============================================================
#
# Conservative defaults (tuned Oct 2026 on live CAM files):
#
# - Confidence below 90 routes to deterministic review.
#   Current files calibrate to 93/95/100/100, so only genuinely
#   weak chains are flagged.
#
# - A chain ending more than STALE_MISSED_CYCLES monthly pay cycles
#   before the file's last transaction is stale (income may have
#   stopped). Derived from the chain-building window itself
#   (3 * MAX_DAYS_BETWEEN), not tuned to any file.
#
# Staleness never rejects by itself; it only routes to review.
# The extractor contract (return the chain) is preserved.

STALE_MISSED_CYCLES = 3

STALE_THRESHOLD_DAYS = (
    STALE_MISSED_CYCLES * base.MAX_DAYS_BETWEEN
)

# Review triggers only on genuinely weak chains (two penalty bands
# or worse): a single borderline credit still passes straight to
# the gatekeeper.

REVIEW_CONFIDENCE_THRESHOLD = 90.0


# ============================================================
# LLM DISCOVERY BUDGET
# ============================================================
#
# Only credits at or above the salary floor are sent, most recent
# first-capped. Keeps prompts small and costs predictable on any
# file size.

LLM_MAX_TXS = 200

LLM_MAX_FIELD_CHARS = 80


def _truncate(text: str) -> str:
    text = (text or "").strip()

    if len(text) > LLM_MAX_FIELD_CHARS:
        return text[:LLM_MAX_FIELD_CHARS]

    return text


def _serialize_credits(
    transactions: list[dict],
) -> tuple[list[dict], str]:
    """Filter, cap and flatten credits for the LLM prompt."""

    eligible = [
        tx
        for tx in transactions
        if tx["amount"] >= base.MIN_SALARY_AMOUNT
    ]

    eligible = sorted(
        eligible,
        key=lambda tx: tx["date"],
    )[-LLM_MAX_TXS:]

    lines = []

    for index, tx in enumerate(eligible):
        lines.append(
            "|".join(
                [
                    str(index),
                    tx["date"].strftime("%Y-%m-%d"),
                    str(round(tx["amount"], 2)),
                    _truncate(tx.get("particulars", "")),
                    _truncate(tx.get("counterparty", "")),
                    _truncate(tx.get("tags", "")),
                    _truncate(tx.get("category", "")),
                    base.detect_payment_mode(tx),
                ]
            )
        )

    return eligible, "\n".join(lines)


def _verify_chain(
    chain: list[dict],
) -> list[dict]:
    """Deterministic guardrails over an LLM-proposed chain.

    Returns the chain sorted by date, or raises ValueError.
    The LLM proposes; these rules dispose.
    """

    if len(chain) < base.MIN_RECURRING_CREDITS:
        raise ValueError(
            "Chain has fewer than "
            f"{base.MIN_RECURRING_CREDITS} credits."
        )

    chain = sorted(
        chain,
        key=lambda tx: tx["date"],
    )

    median = float(
        np.median(
            [tx["amount"] for tx in chain]
        )
    )

    for previous, current in zip(chain, chain[1:]):
        gap = (current["date"] - previous["date"]).days

        if not (
            base.MIN_DAYS_BETWEEN
            <= gap
            <= base.MAX_DAYS_BETWEEN
        ):
            raise ValueError(
                f"Payout gap {gap} days outside "
                f"{base.MIN_DAYS_BETWEEN}-"
                f"{base.MAX_DAYS_BETWEEN} window."
            )

    for tx in chain:
        if not base.amounts_are_similar(
            tx["amount"],
            median,
        ):
            raise ValueError(
                f"Credit {tx['amount']} inconsistent "
                "with chain median."
            )

        mode = base.detect_payment_mode(tx)

        if mode in base.SALARY_EXCLUDED_PAYMENT_MODES:
            raise ValueError(
                f"Excluded payment mode in chain: {mode}."
            )

    return chain


def _llm_discover_chain(
    transactions: list[dict],
) -> tuple[
    list[dict] | None,
    str | None,
    str | None,
]:
    """Ask the LLM to find the salary chain.

    Returns (chain, company, error). chain/company are None on
    any failure; error describes it for observability.
    Amounts and dates always come from our transactions —
    the LLM only selects indices and names the payer.
    """

    import json

    try:
        _ensure_env()

        from src.llm.client import call_openrouter
        from src.llm.prompts import (
            SALARY_CHAIN_SYSTEM_PROMPT,
        )

        eligible, payload = _serialize_credits(
            transactions
        )

        if len(eligible) < base.MIN_RECURRING_CREDITS:
            return (
                None,
                None,
                "Fewer than 3 floor-eligible credits "
                "to show the model.",
            )

        user_prompt = (
            "Find the monthly salary chain in these "
            f"{len(eligible)} credit transactions "
            "(index|date|amount|particulars|"
            "counterparty|tags|category|mode):\n\n"
            f"{payload}\n\n"
            "Return ONLY the required JSON."
        )

        # One retry on transport / parse failures only.
        # Guardrail rejections are final (no second guess).

        response = None
        last_error = "Model returned nothing."

        for _ in range(2):
            try:
                response = call_openrouter(
                    system_prompt=SALARY_CHAIN_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                )
            except Exception as exc:
                last_error = (
                    f"{type(exc).__name__}: {exc}"
                )
                continue

            response = response.strip()

            if response.startswith("```"):
                response = response.replace("```json", "", 1)
                response = response.replace("```", "")
                response = response.strip()

            try:
                result = json.loads(response)
                break
            except json.JSONDecodeError:
                last_error = "Model returned invalid JSON."
                result = None
        else:
            result = None

        if result is None:
            return (
                None,
                None,
                last_error,
            )

        if not isinstance(result, dict):
            return (
                None,
                None,
                "Model returned a non-object.",
            )

        indices = result.get("chain")
        company = result.get("company", "")

        if (
            not isinstance(indices, list)
            or len(set(indices)) < base.MIN_RECURRING_CREDITS
            or not all(
                isinstance(i, int)
                and 0 <= i < len(eligible)
                for i in indices
            )
        ):
            return (
                None,
                None,
                "Model returned invalid chain indices.",
            )

        if not isinstance(company, str) or not company.strip():
            return (
                None,
                None,
                "Model returned no payer name.",
            )

        chain = _verify_chain(
            [eligible[i] for i in indices]
        )

        return chain, company.strip(), None

    except Exception as exc:
        return (
            None,
            None,
            f"{type(exc).__name__}: {exc}",
        )


def _select_rule_chain(
    transactions: list[dict],
) -> list[dict] | None:
    """Deterministic fallback: best rule-built chain or None."""

    candidates = base.build_recurring_chains(
        transactions
    )

    if not candidates:
        return None

    scored = [
        {
            "chain": chain,
            "score": base.score_candidate(chain),
        }
        for chain in candidates
    ]

    unique: dict = {}

    for candidate in scored:
        signature = tuple(
            (
                tx["date"].date(),
                round(tx["amount"], 2),
            )
            for tx in candidate["chain"]
        )
        unique[signature] = candidate

    scored = list(unique.values())

    if not scored:
        return None

    scored.sort(
        key=lambda item: (
            item["score"],
            len(item["chain"]),
            max(
                tx["date"]
                for tx in item["chain"]
            ),
        ),
        reverse=True,
    )

    return scored[0]["chain"]


class CamAgent:
    """
    Salary extraction agent (skill: cam-extractor-agent, Option B).

    The agent pulls the salary chain itself:

    - Deterministic tools do sheet discovery, credit extraction
      and balance. The LLM finds the recurring chain from the
      normalized transactions (indices + payer name only).
    - Deterministic guardrails re-verify every proposed chain
      (gaps, tolerance, excluded modes). Guards dispose.
    - Rule-built chains are the fallback on any LLM failure.
    - The agent layer owns interpretation: company resolution,
      confidence calibration and staleness detection.

    Amounts and dates in the output always come from our own
    transactions, never from model text.

    Returns state-update dicts for cam_graph, never bare values,
    so nodes can merge results directly into CamState.

    Scope is deliberately Transactions-sheet only: workbooks may
    contain pre-computed Salary sheets, but the agent never switches
    source silently. Single-best chain wins; multi-employer files
    are not merged.
    """

    def run(
        self,
        cam_path: str | Path,
    ) -> dict[str, Any]:
        """
        Run extraction on one CAM file.

        Returns:
            cam_result: {"probable_salary": dict | None,
                         "monthly_average_balance": float | None}
            confidence: calibrated score or None when no salary
            is_stale: chain ended long before the file's last txn
            stale_gap_days: (file_max - chain_last).days or None
            discovery: "llm" when the model found the chain,
                       "rules" for fallback / trivial cases
            llm_error: failure reason or None

        Raises ValueError on corrupt files (no transaction sheet /
        no date-credit column), matching the canonical contract.
        """

        excel_file = Path(cam_path)

        if not excel_file.exists():
            raise FileNotFoundError(
                f"CAM file not found: {excel_file}"
            )

        transaction_sheet = base.find_transaction_sheet(
            excel_file
        )

        df = pd.read_excel(
            excel_file,
            sheet_name=transaction_sheet,
        )

        monthly_average_balance = (
            base.extract_monthly_average_balance(
                excel_file
            )
        )

        empty_result = {
            "cam_result": {
                "probable_salary": None,
                "monthly_average_balance":
                    monthly_average_balance,
            },
            "confidence": None,
            "is_stale": False,
            "stale_gap_days": None,
            "discovery": "rules",
            "llm_error": None,
        }

        if df.empty:
            return empty_result

        columns = base.detect_transaction_columns(df)

        transactions = base.extract_credit_transactions(
            df,
            columns,
        )

        if not transactions:
            return empty_result

        file_max = max(
            tx["date"]
            for tx in transactions
        )

        # ----------------------------------------------------
        # 1. LLM discovery first
        # ----------------------------------------------------

        chain, company, llm_error = _llm_discover_chain(
            transactions
        )

        discovery = "llm"

        # ----------------------------------------------------
        # 2. Rule fallback on any model failure
        # ----------------------------------------------------

        if chain is None:
            chain = _select_rule_chain(
                transactions
            )

            company = None
            discovery = "rules"

        if chain is None:
            return {
                **empty_result,
                "stale_gap_days": None,
                "llm_error": llm_error,
            }

        probable_salary = base.build_result(chain)

        probable_salary["company"] = base.resolve_company(
            chain,
            company or probable_salary["company"],
        )

        probable_salary["confidence_score"] = (
            base.calibrated_confidence(
                probable_salary["amounts"]
            )
        )

        probable_salary["payment_mode"] = str(
            probable_salary["payment_mode"]
        ).strip().upper()

        chain_last = max(
            tx["date"]
            for tx in chain
        )

        stale_gap_days = (
            file_max.date() - chain_last.date()
        ).days

        return {
            "cam_result": {
                "probable_salary": probable_salary,
                "monthly_average_balance":
                    monthly_average_balance,
            },
            "confidence": probable_salary[
                "confidence_score"
            ],
            "is_stale": (
                stale_gap_days > STALE_THRESHOLD_DAYS
            ),
            "stale_gap_days": stale_gap_days,
            "discovery": discovery,
            "llm_error": llm_error,
        }


cam_agent = CamAgent()
