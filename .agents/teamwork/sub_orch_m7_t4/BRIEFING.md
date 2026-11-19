# Briefing — Final Milestone M7 Phase 1: Tier 4 E2E (`sub_orch_m7_t4`)

- **Role**: DISPATCH-ONLY Project Pattern Sub-Orchestrator for Final Milestone M7 Phase 1 — Tier 4 E2E Pass & Full Suite Gate.
- **Working Directory**: `/home/antigravity/poidowl/tsukinami`
- **State Folder**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4`
- **Parent Conversation ID**: `dae8e1c02ad3da5e30ef373936de6d57`
- **Original Request**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- **References**:
  - `/home/antigravity/poidowl/tsukinami/PROJECT.md`
  - `/home/antigravity/poidowl/tsukinami/TEST_READY.md`
  - `/home/antigravity/poidowl/tsukinami/TEST_INFRA.md`

## Objective
Achieve **100% PASS** on:
1. Tier 4 E2E tests: `.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -v` (9 real-world scenarios)
2. Full E2E suite (Tiers 1–4): `.venv/bin/pytest tests_e2e/ -v` (all 222 tests)
3. All M1–M6 unit tests: `.venv/bin/pytest tests/ -v` (154+ tests)
4. Zero modifications to existing `tsukinami` TTS source files or HTML demos.
5. Pass the full 5-verifier parallel verification wave including a **WHOLE-PROJECT Forensic Audit** (`teamwork_preview_auditor`).

## Hard Constraints
- Fix implementation bugs in `asr/` (and add unit regression tests in `tests/` as appropriate).
- NEVER weaken, skip, xfail, or hardcode results in `tests_e2e/`.
- All subagents MUST read `ORIGINAL_REQUEST.md` first.
- Fresh subagents per dispatch; unique state folder per subagent.
