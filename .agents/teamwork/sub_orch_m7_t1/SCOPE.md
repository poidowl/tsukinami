# Scope — M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`)

## Target Test Suites
- **Tier 1 E2E**: `.venv/bin/pytest tests_e2e/test_tier1_features.py -v` (103 tests covering Features #1–#18 happy paths)
- **Unit Regression**: `.venv/bin/pytest tests/ -v` (153 tests across M1–M6)

## Editable Scope (when fixes are needed)
- `asr/**` (primary fix target for any genuine implementation bug)
- `tests/**` (unit regression tests for any fixes made)
- `tests_e2e/test_tier1_features.py` ONLY if a test genuinely contradicts `PROJECT.md § Interface Contracts` (must be minimal and explicitly justified; never weaken, skip, xfail, or hardcode).

## Forbidden / Untouched
- All existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.)
- Other E2E test files (`test_tier2_boundaries.py`, `test_tier3_combinations.py`, `test_tier4_scenarios.py`, `conftest.py`) unless a genuine contract contradiction in `conftest.py` blocks Tier 1 (must be explicitly documented).

## Gate Criteria
Strict AND across all 5 parallel verifiers:
1. Forensic Auditor: **CLEAN** (binary veto; intermediate milestone audit over `asr/`, `tests/`, `tests_e2e/conftest.py`, `tests_e2e/test_tier1_features.py`).
2. Primary Reviewer: **APPROVE** + independent full run `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py -v` passes 100% (0 failed, 0 skipped, 0 xfailed).
3. Secondary Reviewer: **APPROVE** + independent target-scoped run `.venv/bin/pytest tests/ -v` passes 100%.
4. Challenger 1: Confirms correctness via isolated adversarial probes in temp dir.
5. Challenger 2: Confirms correctness via isolated adversarial probes in temp dir.
