# Milestone M1 Handoff — Core DSP, Features, Tokenizer & Environment Setup

## Status
**COMPLETED — GATE PASS (Iteration 1)**

All Milestone M1 deliverables have been implemented, verified by 5 independent verification agents (2 Reviewers, 2 Challengers, 1 Forensic Auditor), and passed the strict AND gate with zero defects and zero modifications to existing TTS files or `tests_e2e/`.

## Environment Setup
- **Virtual environment**: `/home/antigravity/poidowl/tsukinami/.venv` (Python 3.11.2, created with `uv venv .venv --python /usr/bin/python3.11`, cache under `/home/antigravity/.cache/uv`).
- **Canonical executables**: `.venv/bin/python`, `.venv/bin/pytest`.
- **Installed packages**:
  - `torch==2.15.0+cpu` (`torch.cuda.is_available() == False`)
  - `numpy==2.4.6`
  - `fastapi==0.165.0`
  - `uvicorn==0.54.0`
  - `python-multipart==0.0.34`
  - `pytest==9.2.0`
  - `httpx==0.28.1`

## Deliverables Created
1. `pyproject.toml` — `tsukinami-asr==0.1.0` metadata, dependencies, `pytest` configuration (`pythonpath = ["."]`, `testpaths = ["tests"]`), and `uv` `pytorch-cpu` index pinning.
2. `.gitignore` — Ignores `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `checkpoints/`, `data/`, `out/`, build artifacts.
3. `asr/__init__.py` — Package exports (`__version__ = "0.1.0"` and all M1 public APIs) without eager `torch` import (`import asr` takes ~79 ms).
4. `asr/config.py` — `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig` matching exact `PROJECT.md` defaults, strict `__post_init__` validation, and `.to_dict()` / `.from_dict()` (rejecting unknown keys and non-mappings).
5. `asr/audio.py` — Pure-NumPy + stdlib `load_wav`, `load_wav_bytes`, `save_wav`, FFT band-limited `resample` (with Nyquist bin handling and anti-aliasing), RMS dBFS `detect_vad` with hangover padding, and deterministic `apply_corruption` (speed perturbation, raised-cosine FFT band-pass filter, exact-SNR white and `1/sqrt(f)` pink noise, gain). Supports 8/16/24/32-bit PCM, 32/64-bit IEEE float, `WAVE_FORMAT_EXTENSIBLE`, multi-channel mono mixdown, optional `ffmpeg` fallback for non-WAV formats, and clean `FileNotFoundError`/`ValueError` on invalid inputs.
6. `asr/features.py` — Pure-NumPy `preemphasis`, periodic Hann `stft_power`, Slaney Mel filterbank (`mel_filterbank`, `hz_to_mel`, `mel_to_hz`), `extract_log_mel` (with optional per-utterance CMVN), orthonormal DCT-II `extract_mfcc` (with optional delta & delta-delta), and non-mutating deterministic `spec_augment`.
7. `asr/tokenizer.py` — `Tokenizer(mode="kana"|"phoneme"|"ascii", vocab=None)` built on `kotoba.to_kata`, `kotoba.split_moras`, `kotoba.parse_kana`, `kotoba.K2V`, `kotoba.SMALL`, `kotoba.PLACE`. Fixed `<blank>` at index `0` (`blank_id == 0`), `kana` (86 tokens), `phoneme` (29 tokens), `ascii` (42 tokens), genuine CTC collapse (`collapse_ctc=True` deduplicates consecutive IDs before removing blanks), and `.to_dict()` / `.from_dict()` round-trip serialization.
8. `tests/test_asr_dsp.py` — 45 unit tests covering all M1 modules, edge cases, and `yomu.py --help` non-regression.

## Verification Summary
- **Forensic Auditor (`iter1_auditor`)**: `VERDICT: CLEAN` — `.venv/bin/pytest -v tests/test_asr_dsp.py` -> `45 passed in 0.45s`; `git diff` empty; zero stubs/hardcoding.
- **Primary Reviewer (`iter1_rev1`)**: `VERDICT: APPROVE` — `.venv/bin/pytest -v` -> `45 passed in 0.28s`; `python3 yomu.py --help` exit 0.
- **Secondary Reviewer (`iter1_rev2`)**: `VERDICT: APPROVE` — `.venv/bin/pytest -v tests/test_asr_dsp.py` -> `45 passed in 0.30s`; verified DSP math & `kotoba.py` parity.
- **Challenger 1 (`iter1_chal1`)**: `VERDICT: PASS` — 28/28 adversarial DSP & feature probes passed.
- **Challenger 2 (`iter1_chal2`)**: `VERDICT: PASS` — all adversarial config, tokenizer, CTC collapse, and packaging probes passed.

## Key Artifacts
- Gate status: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m1/GATE_STATUS.md`
- Worker handoff: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m1/iter1_worker/handoff.md`
- Verifier handoffs: `iter1_rev1/handoff.md`, `iter1_rev2/handoff.md`, `iter1_chal1/handoff.md`, `iter1_chal2/handoff.md`, `iter1_auditor/handoff.md`
