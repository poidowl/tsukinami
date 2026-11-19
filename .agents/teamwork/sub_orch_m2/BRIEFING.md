# Milestone M2 Briefing (`sub_orch_m2`)

- **Original Request**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- **Project Scope Document**: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- **Parent Conversation ID**: `dae8e1c02ad3da5e30ef373936de6d57`
- **Working Directory**: `/home/antigravity/poidowl/tsukinami`
- **State Folder**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m2`
- **Canonical Python / Pytest**: `.venv/bin/python`, `.venv/bin/pytest`

## Exclusive File Ownership
- `asr/synth_data.py`
- `asr/dataset.py`
- `tests/test_asr_data.py`

## Off-Limits Files
- Existing TTS files (`kotoba.py`, `accent.py`, `carve.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.)
- M1 files (`pyproject.toml`, `.gitignore`, `asr/__init__.py`, `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `tests/test_asr_dsp.py`)
- M4 files (`asr/decoding.py`, `asr/metrics.py`, `tests/test_asr_decoding.py`) — running in parallel
- `tests_e2e/` — owned by E2E Testing Track

## Verification Commands
- Target-scoped tests: `.venv/bin/pytest tests/test_asr_data.py`
- Primary Reviewer tests: `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py` (do NOT run `tests_e2e/`)
