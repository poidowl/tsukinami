# SCOPE — M7 Phase 1: Tier 3 E2E (Cross-Feature Combinations)

## Target Test Suite
- **Primary Target**: `.venv/bin/pytest tests_e2e/test_tier3_combinations.py -v` (12 cross-feature combination tests)
- **Regression Guards**:
  - `.venv/bin/pytest tests/ -v` (154 unit tests)
  - `.venv/bin/pytest tests_e2e/test_tier1_features.py -v` (103 tests)
  - `.venv/bin/pytest tests_e2e/test_tier2_boundaries.py -v` (98 tests)
  - Combined verification command: `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py tests_e2e/test_tier3_combinations.py -v` (367 tests)

## Mutable Files (if fixes are needed)
- Implementation: `asr/**`
- Unit regression tests: `tests/**`

## Immutable / Read-Only Files
- `tests_e2e/**` (NEVER weaken, skip, xfail, or modify to make tests pass)
- Existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.)

## Audit Sub-Scope Paths
- `asr/`
- `tests/`
- `tests_e2e/conftest.py`
- `tests_e2e/test_tier1_features.py`
- `tests_e2e/test_tier2_boundaries.py`
- `tests_e2e/test_tier3_combinations.py`
