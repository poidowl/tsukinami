# Scope — M7 Phase 2: Tier 5 White-Box Adversarial Hardening

## Allowed Modifications (via Worker only)
- Bug fixes & hardening in `asr/` (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/*.py`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, `asr/__main__.py`, `asr/server.py`, `asr/web/index.html`)
- New adversarial hardening tests in `tests/test_asr_tier5_hardening.py`

## Strictly Forbidden Modifications
- Existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.)
- `tests_e2e/` (opaque-box E2E test suite — NEVER weaken or modify)

## Canonical Test Commands
- Full suite: `.venv/bin/pytest tests/ tests_e2e/ -v`
- Unit + Tier 5 suite: `.venv/bin/pytest tests/ -v`
