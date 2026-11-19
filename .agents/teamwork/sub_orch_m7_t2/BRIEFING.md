# Briefing — M7 Phase 1: Tier 2 E2E Sub-Orchestrator (`sub_orch_m7_t2`)

## Mission
Achieve **100% PASS** on Tier 2 E2E boundary & corner-case tests (`.venv/bin/pytest tests_e2e/test_tier2_boundaries.py -v`, 98 tests) while keeping **100% PASS** on:
- Tier 1 E2E tests (`.venv/bin/pytest tests_e2e/test_tier1_features.py -v`, 103 tests)
- All M1–M6 unit tests (`.venv/bin/pytest tests/ -v`, 153 tests)
- Existing `tsukinami` TTS files untouched.

## References
- Original Request: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- Project Scope: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- Test Readiness: `/home/antigravity/poidowl/tsukinami/TEST_READY.md`
- Test Infra: `/home/antigravity/poidowl/tsukinami/TEST_INFRA.md`
- Parent Conversation ID: `dae8e1c02ad3da5e30ef373936de6d57`

## Constraints
- DISPATCH-ONLY orchestrator: never edit source code or run tests directly.
- NEVER weaken, skip, xfail, or hardcode results in `tests_e2e/`. Only propose a minimal contract-alignment fix in `tests_e2e/test_tier2_boundaries.py` if a test genuinely contradicts `PROJECT.md § Interface Contracts`, and document it clearly; otherwise ALWAYS fix `asr/` and add regression unit tests in `tests/`.
- Existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) MUST remain unmodified.
- Strict Project Pattern 2B loop: 3 Explorers -> 1 Worker (if any failures) -> 5 parallel verifiers (2 Reviewers, 2 Challengers, 1 Forensic Auditor) -> Gate (`GATE_STATUS.md`).
