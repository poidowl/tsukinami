# Briefing — Milestone M5 Sub-Orchestrator (`sub_orch_m5`)

## Objective
Implement and verify Milestone M5 (**High-Level Inference Engine, CLI & Demo Workflow**) for Tsukinami ASR (`asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py`), strictly honoring `ORIGINAL_REQUEST.md` and `PROJECT.md § Interface Contracts #7`.

## Exclusive File Ownership
- `asr/inference.py`
- `asr/__main__.py`
- `tests/test_asr_cli.py`

Do NOT modify any M1–M4 files (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/*`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`), existing TTS files, or `tests_e2e/`.

## Canonical Verification Commands
- Target-scoped tests: `.venv/bin/pytest tests/test_asr_cli.py -v`
- Full M1–M5 suite (Primary Reviewer): `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py tests/test_asr_cli.py -v`
(Do NOT run `tests_e2e/` yet since M6 is not implemented.)
