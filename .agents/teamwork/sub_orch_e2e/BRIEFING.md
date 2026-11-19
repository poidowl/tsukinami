# Briefing — E2E Testing Track Orchestrator (`sub_orch_e2e`)

## Objective
Design, author, verify, and audit an opaque-box, requirement-driven 4-tier E2E test suite for **Tsukinami ASR** (`asr/`), derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` + `§ Interface Contracts`, running in parallel with the Implementation Track.

## Exclusive File Ownership
- `/home/antigravity/poidowl/tsukinami/TEST_INFRA.md`
- `/home/antigravity/poidowl/tsukinami/tests_e2e/` (`conftest.py`, `test_tier1_features.py`, `test_tier2_boundaries.py`, `test_tier3_combinations.py`, `test_tier4_scenarios.py`, and any helper modules)
- `/home/antigravity/poidowl/tsukinami/TEST_READY.md` (published ONLY after all E2E test milestones pass full review + challenger + forensic audit)

## Non-Modification Boundary
NEVER modify any files in `asr/`, `tests/`, `pyproject.toml`, `.gitignore`, or existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.).

## Parent Reference
- Parent conversation ID: `dae8e1c02ad3da5e30ef373936de6d57`
- Original request: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md`
- Project spec: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
