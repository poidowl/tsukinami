# Briefing — Final Milestone M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`)

- **Parent Conversation ID**: `dae8e1c02ad3da5e30ef373936de6d57`
- **Working Directory**: `/home/antigravity/poidowl/tsukinami`
- **State Folder**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t1`
- **Original Request**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- **Project Scope**: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- **Test Readiness**: `/home/antigravity/poidowl/tsukinami/TEST_READY.md`
- **Test Infrastructure**: `/home/antigravity/poidowl/tsukinami/TEST_INFRA.md`

## Objective
Achieve **100% PASS** on Tier 1 E2E tests (`.venv/bin/pytest tests_e2e/test_tier1_features.py -v`, 103 tests) while keeping **100% PASS** on all M1–M6 unit tests (`.venv/bin/pytest tests/ -v`, 153 tests) and leaving existing `tsukinami` TTS files untouched.

## Rules & Constraints
1. Fix implementation bugs in `asr/` (and add unit regression tests in `tests/` as appropriate).
2. NEVER weaken, skip, xfail, or hardcode results in `tests_e2e/`. Only if a test in `tests_e2e/test_tier1_features.py` genuinely contradicts `PROJECT.md § Interface Contracts` may a minimal contract-alignment fix be proposed and clearly documented; otherwise ALWAYS fix `asr/`.
3. Existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) MUST remain untouched.
4. Dispatch-only orchestration: follow Iteration Loop Steps a -> b -> (c, d, e parallel) -> f strictly.
