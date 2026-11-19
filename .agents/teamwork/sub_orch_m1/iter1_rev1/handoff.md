# Milestone M1 Primary Review (`iter1_rev1`)

## Verdict

**VERDICT: APPROVE**

All Milestone M1 deliverables satisfy every interface contract, behavioral requirement, and isolation constraint in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `SCOPE.md`. All 45 unit tests pass, `.venv` has CPU-only PyTorch and all required dependencies installed, and zero existing TTS files or `tests_e2e/` files were modified.

---

## 1. Independent Verification Commands & Outputs

### 1.1 Full Test Suite (`.venv/bin/pytest -v`)
- **Command**: `.venv/bin/pytest -v` (in `/home/antigravity/poidowl/tsukinami`)
- **Exit code**: `0`
- **Output**:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collected 45 items

tests/test_asr_dsp.py .............................................      [100%]

============================== 45 passed in 0.28s ==============================
```

### 1.2 Existing TTS CLI Non-Regression (`python3 yomu.py --help`)
- **Command**: `python3 yomu.py --help`
- **Exit code**: `0`
- **Output**: Full CLI help text printed cleanly with all presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`) and options intact.

### 1.3 `.venv` Package & CPU-Only PyTorch Verification
- **Command**: `.venv/bin/python -c "import sys, torch, numpy, fastapi, uvicorn, multipart, pytest, httpx; print('python:', sys.version.split()[0], 'torch:', torch.__version__, 'cuda:', torch.cuda.is_available(), 'numpy:', numpy.__version__, 'fastapi:', fastapi.__version__, 'uvicorn:', uvicorn.__version__, 'pytest:', pytest.__version__, 'httpx:', httpx.__version__)"`
- **Exit code**: `0`
- **Output**:
```text
python: 3.11.2 torch: 2.15.0+cpu cuda: False numpy: 2.4.6 fastapi: 0.165.0 uvicorn: 0.54.0 pytest: 9.2.0 httpx: 0.28.1
```

### 1.4 Git Status, Diff & File Tree Audit
- **Command**: `git status --short && echo "---GIT DIFF---" && git diff`
- **Exit code**: `0`
- **Output**:
```text
?? .agents/
?? .gitignore
?? PROJECT.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/
---GIT DIFF---
```
- **Command**: `find asr tests -maxdepth 3 -not -path '*/__pycache__*' | sort`
- **Exit code**: `0`
- **Output**:
```text
asr
asr/__init__.py
asr/audio.py
asr/config.py
asr/features.py
asr/tokenizer.py
tests
tests/test_asr_dsp.py
```
Confirmed: **zero modifications** to any tracked TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, HTML demos) or `tests_e2e/`.

---

## 2. Deliverable & Interface Contract Audit

| Deliverable | Contract / Requirement Check | Status |
|---|---|---|
| `pyproject.toml` | Metadata (`tsukinami-asr==0.1.0`, `requires-python = ">=3.11"`), runtime & dev dependencies, pytest `pythonpath = ["."]` / `testpaths = ["tests"]`, `uv` explicit `pytorch-cpu` index pinning `torch`. | PASS |
| `.gitignore` | Ignores `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `checkpoints/`, `data/`, `out/`, build artifacts. | PASS |
| `asr/__init__.py` | Exports `__version__ = "0.1.0"` and all M1 public symbols (`AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig`, `load_wav`, `save_wav`, `resample`, `detect_vad`, `apply_corruption`, `extract_log_mel`, `extract_mfcc`, `spec_augment`, `Tokenizer`) without eager `torch` import. | PASS |
| `asr/config.py` | Exact field names and defaults for `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig` matching `PROJECT.md` & `SCOPE.md`. Strict `.to_dict()` / `.from_dict()` (rejects unknown keys and non-mappings) and thorough `__post_init__` validation (including `bool` vs `int`, finite float checks, `win_length <= n_fft`, `f_min < f_max <= sr/2`, odd `conv_kernel_size`, `conformer_lite` `hidden_size % num_heads == 0`). | PASS |
| `asr/audio.py` | Exact signatures for `load_wav`, `save_wav`, `resample`, `detect_vad`, `apply_corruption` (plus `load_wav_bytes` helper). RIFF/WAVE parser supports 8/16/24/32-bit PCM, 32/64-bit IEEE float, `WAVE_FORMAT_EXTENSIBLE`, stereo mixdown; clean `FileNotFoundError`/`ValueError` on missing/empty/directory/corrupt payloads; `ffmpeg` fallback for non-WAV / unsupported codec tags. FFT band-limited resampling with Nyquist handling & anti-aliasing. Energy VAD with hangover padding and duration clamping. Deterministic `apply_corruption` with speed, raised-cosine FFT band-pass, exact-SNR white/pink (`1/sqrt(f)`) noise, and gain without mutating input. | PASS |
| `asr/features.py` | Exact signatures for `extract_log_mel`, `extract_mfcc`, `spec_augment`. Pure-NumPy pre-emphasis (`0.97`), periodic Hann STFT, Slaney Mel scale (`1000 Hz == 15.0 mel`, area-normalized filterbank), Log-Mel with optional per-utterance CMVN, orthonormal DCT-II MFCC with optional delta & delta-delta (`(T, n_mfcc)` or `(T, 3 * n_mfcc)`), non-mutating deterministic `spec_augment` safe on tiny spectrograms. Short/empty/silent waveforms safely padded to `T >= 1` with finite `float32` outputs. | PASS |
| `asr/tokenizer.py` | Exact `Tokenizer(mode="kana"|"phoneme"|"ascii", vocab=None)` contract: `blank_id == 0`, `vocab_size`, `encode`, `decode(ids, collapse_ctc=False)`, `to_dict`, `from_dict`. Built on `kotoba.to_kata`, `kotoba.split_moras`, `kotoba.K2V`, `kotoba.SMALL`, `kotoba.PLACE`, `kotoba.parse_kana`. Correctly collapses consecutive duplicates *before* stripping `blank_id == 0` when `collapse_ctc=True`. Safely skips unknown tokens in all modes without emitting spurious vowels. | PASS |
| `tests/test_asr_dsp.py` | 45 comprehensive unit tests covering exports, config defaults/validation/JSON round-trip, WAV formats & error paths, resampling accuracy & anti-aliasing, VAD merging/splitting, noise SNR/pink tilt/band-pass/speed/gain, Slaney Mel/Log-Mel/CMVN/MFCC/SpecAugment, all 3 tokenizer modes & CTC collapse, and existing TTS non-regression. | PASS |

---

## 3. Issues / Findings

- **Blocking issues**: None.
- **Non-blocking observations**: None — implementation is clean, defensive, well-structured, and ready for downstream milestones (M2, M3, M4).
