# Scope — M7 Phase 1: Tier 2 E2E (Boundary & Corner Cases)

## Target Test Suite
- Primary target: `.venv/bin/pytest tests_e2e/test_tier2_boundaries.py -v` (98 tests across all 18 features)
- Regression guard 1: `.venv/bin/pytest tests_e2e/test_tier1_features.py -v` (103 tests)
- Regression guard 2: `.venv/bin/pytest tests/ -v` (153 unit tests)

## Allowed Modification Scope
- `asr/**`: Fix genuine implementation bugs, boundary handling, input validation, error handling, and interface contract compliance.
- `tests/**`: Add targeted unit regression tests for any bugs fixed in `asr/`.
- `tests_e2e/test_tier2_boundaries.py`: **READ-ONLY by default**. NEVER weaken, skip, xfail, or hardcode. Only touch if a test demonstrably contradicts `PROJECT.md § Interface Contracts` (must be justified with exact line citations from `PROJECT.md`).

## Forbidden Scope
- Existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) — MUST NOT be modified.
- `tests_e2e/test_tier1_features.py`, `tests_e2e/test_tier3_combinations.py`, `tests_e2e/test_tier4_scenarios.py`, `tests_e2e/conftest.py` — MUST NOT be modified unless an explicit contract conflict is proven.

## Verification Requirements
- Primary Reviewer: Full run `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py -v` (354+ tests, 100% pass).
- Secondary Reviewer: Target-scoped `.venv/bin/pytest tests/ -v` + code review of any fixes.
- 2 Challengers: Adversarial boundary/corner-case probes in isolated temp directories.
- 1 Forensic Auditor: Intermediate milestone audit covering `asr/`, `tests/`, `tests_e2e/conftest.py`, `tests_e2e/test_tier1_features.py`, `tests_e2e/test_tier2_boundaries.py` (runs target-scoped `tests/` + anti-cheating checks; no concurrent E2E run).
