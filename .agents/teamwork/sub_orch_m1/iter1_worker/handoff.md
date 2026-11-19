# Milestone M1 Worker Handoff (`iter1_worker`)

## 1. Summary of Completed Work

Implemented the complete Milestone M1 scope — project-local Python 3.11 `.venv` with CPU-only PyTorch, packaging & ignore files, validated configuration dataclasses, pure-NumPy/stdlib audio DSP & corruptions, pure-NumPy acoustic features & SpecAugment, `kotoba`-backed CTC tokenizer, and a 45-test unit test suite — without modifying any existing TTS files or `tests_e2e/`.

## 2. Files Created

| File | Description |
|---|---|
| `.venv/` | Project-local Python 3.11.2 venv created via `uv venv .venv --python /usr/bin/python3.11` with CPU-only `torch==2.15.0+cpu` (`https://download.pytorch.org/whl/cpu`), `numpy==2.4.6`, `fastapi==0.165.0`, `uvicorn==0.54.0`, `python-multipart==0.0.34`, `pytest==9.2.0`, `httpx==0.28.1`. |
| `.gitignore` | Ignores `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, build artifacts, `checkpoints/`, `data/`, `out/`. |
| `pyproject.toml` | Project metadata (`tsukinami-asr==0.1.0`), dependencies, `[tool.pytest.ini_options]` (`pythonpath = ["."]`, `testpaths = ["tests"]`), and `[[tool.uv.index]]` / `[tool.uv.sources]` pinning `torch` to `pytorch-cpu`. |
| `asr/__init__.py` | Exports `__version__ = "0.1.0"` and all M1 public symbols without importing `torch`. |
| `asr/config.py` | Dataclasses `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig` matching exact `PROJECT.md` defaults, with `.to_dict()`, strict `.from_dict()` (rejects unknown keys and non-mappings), and `__post_init__` validation. |
| `asr/audio.py` | Pure-NumPy/stdlib `load_wav`, `load_wav_bytes`, `save_wav`, `resample`, `detect_vad`, and `apply_corruption`. |
| `asr/features.py` | Pure-NumPy `preemphasis`, `stft_power`, Slaney `hz_to_mel`/`mel_to_hz`/`mel_filterbank`, `extract_log_mel` (with optional per-utterance CMVN), `extract_mfcc` (with optional delta & delta-delta), and `spec_augment`. |
| `asr/tokenizer.py` | `Tokenizer(mode="kana"|"phoneme"|"ascii", vocab=None)` with `blank_id == 0`, `encode`, `decode_tokens`, `decode(collapse_ctc=...)`, `to_dict`, `from_dict`. |
| `tests/test_asr_dsp.py` | 45 unit tests covering package exports, config validation/serialization, WAV I/O & formats, FFT resampling & anti-aliasing, energy VAD, noise/band-pass/speed/gain corruptions, Slaney Mel/Log-Mel/MFCC/SpecAugment, all 3 tokenizer modes & CTC collapse, and existing TTS non-regression. |

## 3. Key Design Choices

- **Two-Step CPU-Only PyTorch Install**: Installed `torch` exclusively from `--index-url https://download.pytorch.org/whl/cpu` first, then installed PyPI packages in a second step (avoiding `uv`'s `--extra-index-url` priority pitfall).
- **WAV I/O & Resampling (`asr/audio.py`)**:
  - Pure-Python RIFF/WAVE parser supports 8/16/24/32-bit PCM, 32/64-bit IEEE float, `WAVE_FORMAT_EXTENSIBLE`, and multi-channel mono mixdown.
  - Corrupt RIFF/WAVE payloads raise `ValueError` directly rather than being partially salvaged; non-WAV formats and unsupported WAV codec tags fall back to `ffmpeg` if available.
  - Exact FFT-based resampling provides brick-wall anti-aliasing (verified on 10 kHz sine downsampled `44100 -> 16000`) and fast `O(N log N)` speed perturbation.
  - `apply_corruption` applies speed perturbation → raised-cosine FFT band-pass filter → exact-SNR white or `1/sqrt(f)` pink noise → gain, without mutating input arrays.
- **Acoustic Features (`asr/features.py`)**:
  - Cached periodic Hann windows, Slaney Mel filterbanks (exact `1000 Hz = 15.0 mel` continuity), and orthonormal DCT-II matrices.
  - Short/empty/silent waveforms are safely zero-padded so `T >= 1` and outputs are always finite `float32`.
- **CTC Tokenizer (`asr/tokenizer.py`)**:
  - `kana` mode (86 tokens): `<blank>` + 71 `kotoba.K2V` katakana + `ン/ッ/ー` + 8 `kotoba.SMALL` + `、/。/space`; converts Hiragana via `kotoba.to_kata`.
  - `phoneme` mode (29 tokens): `<blank>` + 5 vowels + 19 `kotoba.PLACE` consonants + `N/Q/:/pau`; validates kana tokens before calling `kotoba.parse_kana` so unknown characters never emit spurious vowels, and supports space-separated phoneme string round-trip.
  - `ascii` mode (42 tokens): `<blank>` + space + `a-z` + `0-9` + `'-,.`.
  - `collapse_ctc=True` collapses consecutive duplicate IDs *before* stripping `blank_id == 0`.

## 4. Verification Command Outputs (Run After Final Edit)

### Command 1 — `.venv` Package Imports
```bash
.venv/bin/python -c "import torch, numpy, fastapi, uvicorn, multipart, pytest, httpx; print('torch:', torch.__version__, 'cuda:', torch.cuda.is_available())"
```
- **Exit code**: `0`
- **Output**:
```text
torch: 2.15.0+cpu cuda: False
```

### Command 2 — M1 Unit Tests
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

============================== 45 passed in 0.55s ==============================
```

### Command 3 — Existing TTS Non-Regression
```bash
python3 yomu.py --help
```
- **Exit code**: `0`
- **Output**:
```text
usage: yomu.py [-h] [-o OUT]
               [--preset {default,ossan,robot,horror,whisper,chibi,utahime,choir}]
               [--trance] [--choir] [--iroke IROKE] [--list-presets]
               [--recipe RECIPE] [--save-recipe SAVE_RECIPE] [--compare]
               [--seed SEED] [--tsubu TSUBU] [--hz HZ] [--yure YURE]
               [--shimmer SHIMMER] [--tadayoi TADAYOI] [--line-g LINE_G]
               [--fscale FSCALE] [--rate RATE] [--ap-n AP_N]
               [texts ...]

日本語かな・カナを読む。その仕組みを、Pythonで読む。 — 月並みTTS (tsukinami)
...
```

### Command 4 — Git Status
```bash
git status --short
```
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
```
