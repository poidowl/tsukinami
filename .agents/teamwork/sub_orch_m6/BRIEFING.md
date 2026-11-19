# M6 Sub-Orchestrator Briefing (`sub_orch_m6`)

- **Role**: Milestone M6 Sub-Orchestrator — Interactive Web Playground ("遊べる ASR")
- **Parent Conversation ID**: `dae8e1c02ad3da5e30ef373936de6d57`
- **Workspace**: `/home/antigravity/poidowl/tsukinami`
- **Original Request**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- **Project Spec**: `/home/antigravity/poidowl/tsukinami/PROJECT.md` (especially `§ Interface Contracts #8`)
- **State Folder**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m6`

## Exclusive File Ownership
1. `asr/server.py`
2. `asr/web/index.html`
3. `tests/test_asr_web.py`

## Non-Negotiable Constraints
- Do NOT modify M1–M5 files (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/*`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, `asr/__main__.py`), existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.), or `tests_e2e/`.
- Zero external CDN links in `asr/web/index.html` (100% self-contained HTML5 + CSS + vanilla JS Canvas 2D + Web Audio API).
- Canonical Python/pytest: `.venv/bin/python`, `.venv/bin/pytest`.
