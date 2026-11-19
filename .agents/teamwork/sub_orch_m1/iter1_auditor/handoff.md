# Forensic Audit Report — Milestone M1 (`iter1_auditor`)

**VERDICT: CLEAN**

## 1. Audit Scope & Basis
- **Audited Milestone**: M1 (Core DSP, Features, Tokenizer & Env)
- **Audited Paths**:
  - `pyproject.toml`
  - `.gitignore`
  - `asr/__init__.py`
  - `asr/config.py`
  - `asr/audio.py`
  - `asr/features.py`
  - `asr/tokenizer.py`
  - `tests/test_asr_dsp.py`
  - `.venv/` (environment verification only)
- **References Read**: `ORIGINAL_REQUEST.md`, `PROJECT.md`, `sub_orch_m1/SCOPE.md`, `sub_orch_m1/iter1_worker/handoff.md`.

## 2. Scope & Non-Invasiveness Check
- **`git status --short`**:
  ```text
  ?? .agents/
  ?? .gitignore
  ?? PROJECT.md
  ?? asr/
  ?? pyproject.toml
  ?? tests/
  ?? tests_e2e/
  ```
- **`git diff`**: Empty (0 lines modified across all tracked files).
- **Directory listing**:
  - `asr/`: `__init__.py`, `config.py`, `audio.py`, `features.py`, `tokenizer.py` (exact M1 scope).
  - `tests/`: `test_asr_dsp.py` (exact M1 scope).
- **Forbidden paths**: ZERO modifications to existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) or `tests_e2e/`.

## 3. Line-by-Line Genuineness & Anti-Cheating Inspection
Every line of all 8 audited files was read and verified:

- **`pyproject.toml` & `.gitignore`**: Proper `tsukinami-asr==0.1.0` packaging, `pytorch-cpu` index pinning, `pytest` configuration, and ignore rules for `.venv/`, caches, `checkpoints/`, `data/`, `out/`.
- **`asr/__init__.py`**: Exports `__version__` and all M1 public API symbols without importing `torch`.
- **`asr/config.py`**: Implements `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig` with exact `PROJECT.md` defaults, `__post_init__` domain/type validation, `.to_dict()`, and strict `.from_dict()` rejecting unknown keys and non-mappings.
- **`asr/audio.py`**:
  - Genuine pure-Python RIFF/WAVE chunk parser (`_parse_wav_bytes`) decoding 8/16/24/32-bit PCM, 32/64-bit IEEE float, `WAVE_FORMAT_EXTENSIBLE`, and multi-channel mono mixdown, with `ffmpeg` fallback for non-WAV or unsupported codec tags, and explicit `FileNotFoundError` / `ValueError` on missing/empty/corrupt inputs.
  - Genuine FFT-based band-limited resampling (`_resample_to_length`, `resample`) with Nyquist bin handling.
  - Genuine frame-level RMS dBFS VAD (`detect_vad`) with hangover padding and ordered non-overlapping segment extraction.
  - Genuine `apply_corruption` supporting speed perturbation, raised-cosine FFT band-pass filtering, exact-SNR white and `1/sqrt(f)` pink noise, and gain without mutating input arrays.
- **`asr/features.py`**:
  - Genuine pure-NumPy pre-emphasis, periodic Hann-windowed STFT power spectrogram (`sliding_window_view` + `rfft`), Slaney Mel scale (`1000 Hz = 15.0 mel`) and Slaney-normalized triangular filterbank, `extract_log_mel` with optional per-utterance CMVN, orthonormal DCT-II `extract_mfcc` with regression delta/delta-delta, and non-mutating deterministic `spec_augment`.
- **`asr/tokenizer.py`**:
  - Genuinely integrates with `kotoba.py` (`kotoba.to_kata`, `kotoba.split_moras`, `kotoba.parse_kana`, `kotoba.K2V`, `kotoba.SMALL`).
  - Implements `"kana"` (86 tokens), `"phoneme"` (29 tokens), and `"ascii"` (42 tokens) modes with `<blank>` fixed at index `0`, genuine CTC collapse (deduplicate consecutive IDs before removing `blank_id == 0`), and `to_dict()` / `from_dict()`.
- **`tests/test_asr_dsp.py`**:
  - 45 genuine, non-tautological unit tests with zero skipped or `xfail` tests. Exercises real numerical/spectral properties (WAV correlation across bit depths, FFT frequency preservation and 10 kHz anti-aliasing, VAD merge/split behavior, SNR dB accuracy and pink-vs-white spectral tilt, band-pass attenuation, Slaney Mel round-trip and frequency selectivity, CMVN statistics, MFCC/deltas, SpecAugment, all 3 tokenizer modes & CTC collapse, and `yomu.py` non-regression).
- **Anti-cheating**: Zero hardcoded test outputs, stubs, mocks, or bypasses found.

## 4. Independent Verification Outputs

### 1. M1 Unit Tests
```bash
.venv/bin/pytest -v tests/test_asr_dsp.py
```
- **Exit code**: `0`
- **Output**:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 45 items

tests/test_asr_dsp.py .............................................      [100%]

============================== 45 passed in 0.45s ==============================
```

### 2. `.venv` Environment Verification
```bash
.venv/bin/python -c "import torch, numpy, fastapi, uvicorn, multipart, pytest, httpx; print(torch.__version__, torch.cuda.is_available())"
```
- **Exit code**: `0`
- **Output**:
```text
2.15.0+cpu False
```

### 3. Existing TTS Non-Regression
```bash
python3 yomu.py --help
```
- **Exit code**: `0`
- **Output**: Full `yomu.py` argparse usage and option listing printed cleanly without errors.
