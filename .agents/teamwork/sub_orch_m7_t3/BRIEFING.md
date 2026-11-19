# BRIEFING — Final Milestone M7 Phase 1: Tier 3 E2E (`sub_orch_m7_t3`)

## Context
- **Original Request**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- **Working Directory**: `/home/antigravity/poidowl/tsukinami`
- **State Folder**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t3`
- **Parent Conversation ID**: `dae8e1c02ad3da5e30ef373936de6d57`
- **Project Scope**: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- **Test Readiness**: `/home/antigravity/poidowl/tsukinami/TEST_READY.md`
- **Test Infra**: `/home/antigravity/poidowl/tsukinami/TEST_INFRA.md`

## Prior State
- Milestones M1–M6 DONE (154 unit tests in `tests/`).
- M7 Phase 1 Tier 1 (`tests_e2e/test_tier1_features.py`, 103 tests) and Tier 2 (`tests_e2e/test_tier2_boundaries.py`, 98 tests) DONE.
- Existing `tsukinami` TTS files untouched.

## Objective
Achieve **100% PASS** on Tier 3 E2E tests (`.venv/bin/pytest tests_e2e/test_tier3_combinations.py -v`, 12 tests) while keeping **100% PASS** on Tier 1 (103 tests), Tier 2 (98 tests), and all M1–M6 unit tests (`tests/`, 154 tests), leaving existing `tsukinami` TTS files untouched.

## Rules & Constraints
- Fix implementation bugs in `asr/` (and add unit regression tests in `tests/` as appropriate).
- NEVER weaken, skip, xfail, or hardcode results in `tests_e2e/`.
- Follow Project Pattern 2B Iteration Loop strictly:
  - Step a: 3 parallel `teamwork_preview_explorer` agents run/inspect Tier 3 tests and diagnose any failures.
  - Step b: If ANY test fails, dispatch 1 `teamwork_preview_worker` (with MANDATORY INTEGRITY WARNING verbatim) to fix all failures and verify `tests/` + Tier 1 + Tier 2 + Tier 3. (If 12/12 Tier 3 tests already pass with zero issues, proceed directly to the 5-verifier parallel verification wave.)
  - Step c, d, e: Parallel 5-verifier wave (Primary Reviewer running full `tests/` + Tier 1–3, Secondary Reviewer running target-scoped `tests/` and inspecting fixes, 2 Challengers running isolated adversarial probes in temp dir, 1 Forensic Auditor labeled as intermediate milestone audit on explicit sub-scope paths running `tests/` + anti-cheating checks).
  - Step f: Gate in `GATE_STATUS.md` (strict AND; Auditor binary veto).
