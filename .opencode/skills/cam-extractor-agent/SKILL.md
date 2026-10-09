---
name: CAM Extractor Agent
description: Replace src/extraction/cam_extraction.py deterministic extractor with an LLM/tool-using salary extraction agent while preserving graph and API contracts
---

# CAM Extractor Agent

Replaces the deterministic CAM salary extractor with an agent-based implementation.

## When to use

Use when asked to replace, rewrite, or upgrade `cam_extraction.py` / `cam_extraction_v2.py`
with an agent. Do NOT use for small bug fixes to the current extractor.

## Non-negotiable contracts

Read these files first, in order:

1. `src/extraction/cam_extraction.py` — current logic to replace (**canonical**)
2. `src/graph/income_graph.py` — `extract_cam_node` calls `analyze_monthly_counterparty(cam_path)`
3. `src/graph/state.py` — `cam_result` shape
4. `src/main.py` — expects `probable_salary.latest_salary` (fallback `salary`), `monthly_average_balance`
5. `src/response/response_builder.py` — expects `company, confidence_score, months[], amounts[], payment_mode`
6. `src/agents/income_agent.py` — downstream gatekeeper; candidate must include `payment_mode`

Drop-in interface that MUST be preserved:

```python
def analyze_transactions(excel_file: Path) -> dict
def analyze_monthly_counterparty(excel_file: Path) -> dict
# both return:
# {"probable_salary": dict | None, "monthly_average_balance": float | None}
```

`probable_salary` fields (see `build_result` in current extractor):
`company, latest_salary, average_salary, median_salary, credits, payment_mode, confidence_score, months[], amounts[]`.
`months` and `amounts` must be same-length, date-sorted.

`monthly_average_balance` logic must be kept: last numeric value in the
`Monthly Avg Balance` row of the summary sheet, or `None` (missing summary
sheet → `None`, verified live).

### Raise-vs-None contract (verified live — get this wrong and the API 500s)

- MUST RAISE `ValueError`: file has no transaction sheet
  (`Transaction sheet not found`), or the sheet has no usable date/credit column.
  `extract_cam_node` has no try/except; `main.py` maps these to HTTP 500.
  The replacement must keep raising here, never silently return `None`
  (silent `None` would turn a corrupt upload into a false "no salary" verdict).
- MUST RETURN `{"probable_salary": None, "monthly_average_balance": ...}`:
  empty transaction sheet, zero credit transactions, no recurring chain,
  missing summary sheet (all verified to return `None`, not raise).

### Type and format rules (from live test failures)

- `payment_mode` MUST be uppercase canonical (`UNKNOWN`, `NEFT`, `UPI`, ...).
  v2 returns `"Unknown"` — wrong; v1 returns `"UNKNOWN"` — correct.
  `response_builder` exposes the raw value, so casing leaks to the API.
- All scalars MUST be native `float`/`int`/`str` (v1 wraps with `float()`).
  v2 leaks `numpy.float64` for `confidence_score`, which breaks strict JSON encoders.
- `confidence_score` MUST be calibrated with this formula — it is defined purely
  from the chain's own amounts, so it works on ANY file with no per-file tuning:
  `confidence = clamp(100 - 5 * (#credits >10% off median) - 2 * (#credits 5-10% off median), 0, 100)`.
  The rule cuts both ways: it must HOLD 100 when every credit is tight AND drop
  when any credit exceeds 10%. A constant 100.0 (old v1 behavior) is a bug.
  Worked examples (illustrative, not targets): a 10-credit chain with one credit
  13.4% off and one 8.3% off → 93.0; a 5-credit chain with one 15.6% outlier → 95.0;
  chains with max deviation under 1% → 100.0.
- `company` resolution precedence (applies to any narration style):
  1. Most-frequent non-empty **counterparty** wins, verbatim.
  2. Counterparty empty → classify narration tokens (split on non-alphanumerics):
     drop filler words (`BY TRANSFER THROUGH CREDIT VIA IN OUT CR DR`), drop
     reference codes (any token with digits, single letters), prefer surviving
     payer tokens, fall back to channel tokens (`NEFT IMPS … PFMS UPI ATM`),
     else `Unknown`. Worked pattern: code-heavy narration resolving to its
     single channel token; `BY SALARY`-style narration → `SALARY`.
  3. Do NOT "fix" source-side truncation or expand abbreviations by guessing:
     return what the file says, cleaned but never invented.
  Worked examples (illustrative): code-heavy narration → channel token;
  `BY SALARY`-style narration → `SALARY`.
- Category/tags keyword `SALARY` is a strong accept signal that outweighs unknown mode.
  Example pattern: credits narrated `BY SALARY` with category `SALARY` and no
  mode token → mode `UNKNOWN`, yet a clean monthly chain. The agent must NOT
  penalize `UNKNOWN` mode when `SALARY` appears in category/tags/particulars.

## Workflow

### 0. Environment setup (do this first)

The repo root python may lack deps (`dotenv`, `langgraph`, `fastapi` missing
even though `pandas` is present). Before any test run:

```bash
pip install -r requirements.txt
```

`test_income_graph.py` calls the live LLM via `call_openrouter` (costs money,
needs `OPENROUTER_API_KEY`). Always verify extractor-only first (no LLM cost);
run the graph test last, once.

Note: `salary_test.py` hardcodes one Yuvraj filename and imports the buggy v2;
`test_income_graph.py` hardcodes the Harwansh filename. Pass files explicitly
(see step 4) instead of relying on those hardcoded paths.

### 1. Recon

- Baseline over ALL of `data/input/*.xlsx` (glob, never a hardcoded file list).
  Record per file: salary found or `None`, credits, mode, confidence, MAB.
  Re-run after the change: every chain (dates/amounts) must be unchanged, and
  every `company`/`confidence_score` must follow the generic rules above —
  recompute the formula from the amounts by hand on at least two files instead
  of trusting saved numbers.
- **Anti-overfit rule: the files in `data/input/` are a smoke set, not the spec.**
  Do NOT tune thresholds, tolerances, or cleaning regexes to match specific
  filenames or values. Every rule must be justifiable on a file you have never
  seen. Before declaring done, validate on at least one CAM from outside this
  set (a new upload, a different bank layout) and confirm sensible output.
- **v1 is the source of truth. v2 is a known-buggy fork — do NOT match it.**
  v2 lacks the UPI/ATM filter and the source-consistency check, so on files
  where the only recurring small credits are UPI it invents a UPI "salary"
  while v1 correctly returns `None`. The replacement must reproduce v1's
  `None` on such files, never v2's false positive.

### 2. Design the agent

Propose before coding (1 short paragraph + tool list):

- **Option A (recommended): hybrid** — deterministic tools (`find_transaction_sheet`,
  `extract_credit_transactions`, `extract_monthly_average_balance`) + LLM reasoning
  for chain grouping / source resolution / confidence. Keeps determinism where it
  matters, uses LLM where heuristics are weak (`text_similarity`, `transactions_have_same_source`).
- **Option B: full LLM** — pass normalized credit-transaction JSON to `call_openrouter`
  (see `src/llm/client.py`) and validate output with a pydantic schema. Only choose
  if monthly files fit in context.
- Preserve hard rules as tools/guards, never as prompt-only: `MIN_RECURRING_CREDITS=3`,
  `25-40 day gaps`, `amount >= 3000`, `UPI/ATM hard-excluded`, `UNKNOWN/TRANSFER allowed`.
- Amount consistency is load-bearing: the agent must NOT promote a consistent
  counterparty to salary when amounts swing >20% with no stable median.
  Category example: regular treasury/NEFT credits with irregular amounts and
  only UPI small credits recurring → `None`, not a forced salary.

### 2b. Generality requirements (must hold for ANY cam, not just seen ones)

- **Format-agnostic input**: any bank layout that exposes a transaction sheet
  resolvable by name matching and date/credit columns resolvable by alias
  lists. Never hardcode a bank name, sheet position, or column index.
- **Short history**: fewer than 3 monthly-grade credits → `None`. Never lower
  `MIN_RECURRING_CREDITS` to force a hit on a young file.
- **Sub-3000 credits**: excluded from chains by the floor. Never lower it for
  part-time/low-income files; return `None` instead.
- **Non-monthly cadence**: weekly/biweekly credits fall outside the 25-40 day
  window → `None` under current rules. Never widen the window per file; changing
  it is a product decision, not a tuning knob.
- **Job change / two employers**: single-best chain wins (score, then length,
  then recency). Never merge chains from different sources into one salary.
- **Anonymous credits**: fully empty counterparty/particulars/tags with
  `UNKNOWN` mode can never satisfy source consistency → no chain. Never relax
  this to "timing + amount is enough".
- **Staleness**: a chain ending far before the file's last transaction is still
  returned (no recency rejection), but must be flagged as possibly-stopped
  income for downstream review, never silently and never as a reject.
- **Signed/single-column layouts** (one amount column, no dedicated credit
  column) → raise, don't guess sign conventions.

### 3. Implement (current architecture, Oct 2026)

- Reasoning layer lives IN `src/extraction/cam_extraction.py`
  (`normalize_company` / `resolve_company`, `calibrated_confidence`,
  `build_agent_result`) wired into `analyze_transactions`. Deterministic
  tools in the same module are untouched.
- Agent orchestration lives in `src/agents/cam_agent.py` (`CamAgent.run`):
  owns chain selection, staleness detection, and graph-ready state fragments.
- LLM discovery (Option B, live Oct 2026): the model receives normalized
  credit lines (`index|date|amount|particulars|counterparty|tags|category|mode`,
  floor-filtered, capped) and returns indices + payer name ONLY — amounts and
  dates always come from our transactions. Deterministic guardrails re-verify
  every proposal (count, 25–40d gaps, 20% tolerance, UPI/ATM exclusion); one
  retry on transport/parse errors, guardrail rejections are final, and rule
  chains are the fallback. Proven live: 4/4 salary chains found by the model,
  one forced chain rejected by guards, one transient empty reply cured by retry.
- Routing lives in `src/graph/cam_graph.py` (`CamState` in `src/graph/state.py`):
  extract → candidates → assess → conditional review → gatekeeper → validate.
  `income_graph.py` is legacy and stays untouched.
- `src/main.py` runs `cam_graph` (not `income_graph`): salary passes only
  when the gatekeeper detects AND graph validation holds (a review rejection
  blocks salary even on gatekeeper accept; missing validation preserves the
  legacy gatekeeper-only behavior). Review surfaces additively in the response.
- `salary_test.py` targets `CamAgent.run` (not the extractor), takes file
  args, and asserts agent-response invariants (discovery flag, error
  consistency, confidence/staleness coherence) plus the generic property
  checks (never saved constants).
- `src/response/response_builder.py` accepts optional `review` and
  `agent_meta` and emits additive `review` / `agent_meta` keys only when
  present; all existing keys are unchanged.
- Reuse `src/llm/client.py:call_openrouter` for all LLM calls. No new API clients, no new API keys.
- Validate every LLM JSON response (same pattern as `_validate_agent_output` in
  `income_agent.py`): required fields, types, `months`/`amounts` length match,
  `confidence_score 0-100`, `credits == len(months)`, native types only, uppercase mode.
- Deterministic fallback: if LLM call fails / returns invalid JSON after 1 retry,
  fall back to current `build_recurring_chains + score_candidate` logic so the endpoint
  never 500s on LLM flakiness.
- Delete `cam_extraction_v2.py` and `data/input/extraction/` stale copies as part of
  the change. Update `salary_test.py` import to the new module.

### 4. Verify

Run extractor-only checks over the whole glob (no LLM cost) before the graph test:

```bash
python3 -c "
import glob
from pathlib import Path
from src.extraction.cam_extraction import analyze_transactions
for f in sorted(glob.glob('data/input/*.xlsx')):
    if '/~' in f: continue
    r = analyze_transactions(Path(f))
    ps = r['probable_salary']
    print(Path(f).name[:50], '->', ps['company'] if ps else None, ps['confidence_score'] if ps else None)
"
```

Property checks — every one must hold on EVERY file, seen or unseen:

- [ ] Chain dates/amounts identical to pre-change output (no chain regressions).
- [ ] `months`/`amounts` same length, dates ascending, `credits == len(months)`.
- [ ] `confidence_score` equals the formula recomputed from `amounts` (spot-check
      by hand on two files; never assert a saved constant).
- [ ] `company` non-empty, no reference blobs (`*`, long alphanumeric codes);
      truncation from the source file itself left intact.
- [ ] `payment_mode` uppercase canonical; no `UPI`/`ATM` chain ever returned.
- [ ] `json.dumps(result)` passes (native types only).
- [ ] Irregular-amount files stay `None` (no forced salaries).
- [ ] At least one CAM from OUTSIDE the smoke set validated with sensible output.
- [ ] `python test_income_graph.py` — `income_decision` + `validation` still populated (live LLM, run once).
- [ ] Offline gatekeeper paths still work with no LLM cost:
  `run_income_agent([])` → not-detected, all-`UPI` candidates → not-detected.
  Cover both in a unit test so regressions are caught without API calls.
- [ ] `python -m py_compile` on every file touched
  (e.g. `src/extraction/cam_extraction.py`, `src/agents/cam_agent.py`,
  `src/graph/cam_graph.py`, `src/graph/state.py`, `src/main.py`).
- [ ] Valid-file-no-salary returns `{"probable_salary": None, ...}`: empty sheet,
      no recurring chain, missing summary sheet. Corrupt-file cases still RAISE
      (`ValueError`: no transaction sheet / no date-credit column) — assert both
      behaviors, they are different contracts (see Raise-vs-None above).

### 5. Do NOT

- Do NOT change `IncomeState`, `income_agent.py`, `response_builder.py`, or `final_analyzer.py` field names.
- Do NOT add dependencies to `requirements.txt` without asking (repo already bloated).
- Do NOT commit `.env`, real CAM files, or `data/input/*` outputs.
- Do NOT invent a new `probable_salary` schema — downstream `main.py:478,599` and `response_builder.py:22` depend on it.
- Do NOT copy v2 logic (no UPI/ATM filter, lowercase mode, uncalibrated confidence) — it is the bug list, not a reference.
- Do NOT hardcode filenames, bank names, company strings, or expected numbers
  into code or tests. Rules must be derivable from any file's own data; the
  smoke set only guards against regressions, it is never the spec.
