# Briefing: Milestone M4 — CTC Decoding, N-gram LM, Viterbi Alignment & Metrics

## Role
Milestone M4 Sub-Orchestrator (`sub_orch_m4`), Parent ID: `dae8e1c02ad3da5e30ef373936de6d57`.

## Original Request
Verbatim path: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md`
Content: "ASRをつくって遊びたい"

## Project Scope
`/home/antigravity/poidowl/tsukinami/PROJECT.md`

## Exclusive File Ownership
- `asr/decoding.py` (100% Pure NumPy/Python)
- `asr/metrics.py` (100% Pure Python/NumPy)
- `tests/test_asr_decoding.py`

## Non-Modification Constraints
- Do NOT modify M1 files (`asr/__init__.py`, `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `tests/test_asr_dsp.py`, `pyproject.toml`, `.gitignore`).
- Do NOT modify M2 files (`asr/synth_data.py`, `asr/dataset.py`, `tests/test_asr_data.py`) — M2 is running in parallel.
- Do NOT modify existing TTS files (`kotoba.py`, `accent.py`, `carve.py`, `yomu.py`, etc.).
- Do NOT touch `tests_e2e/`.

## Canonical Test Commands
- Target-scoped tests: `.venv/bin/pytest tests/test_asr_decoding.py`
- Primary Reviewer tests: `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_decoding.py` (do NOT run `tests_e2e/` or `test_asr_data.py`).
