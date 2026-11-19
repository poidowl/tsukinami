# Milestone M1 Briefing — Core DSP, Features, Tokenizer & Environment Setup

## Original Request
- Path: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md`
- Request: `ASRをつくって遊びたい`

## Project Scope
- Path: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- Working directory: `/home/antigravity/poidowl/tsukinami`
- Parent Orchestrator ID: `dae8e1c02ad3da5e30ef373936de6d57`

## Objective
Set up the project-local Python 3.11 virtual environment (`.venv`) with CPU-only PyTorch and dependencies, create packaging files (`pyproject.toml`, `.gitignore`), and implement the M1 core DSP, feature extraction, CTC tokenizer, and unit test suite without modifying any existing TTS files or `tests_e2e/`.

## Constraints
- Existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) MUST remain completely unmodified and functional (`python3 yomu.py --help` must still work).
- Do NOT touch `tests_e2e/`.
- PEP 668 is active on system Python; use `uv venv .venv --python 3.11` and install into `.venv`.
- `/` has ~3.9 GiB while `/home/antigravity` has ~20 GiB; keep `UV_CACHE_DIR` / temp caches under `/home/antigravity` (e.g. `/home/antigravity/.cache/uv`) to avoid filling `/`.
- Canonical test runner: `.venv/bin/pytest tests/test_asr_dsp.py`.
