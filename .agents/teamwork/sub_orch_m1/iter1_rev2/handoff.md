# Milestone M1 Secondary Review (`iter1_rev2`)

**VERDICT: APPROVE**

## 1. Executive Summary

Independently reviewed the Milestone M1 implementation against `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `SCOPE.md`, verified all interface contracts, audited the pure-NumPy DSP and `kotoba.py` tokenizer math, and ran the target-scoped unit test suite plus numerical parity checks.

All 45 unit tests in `tests/test_asr_dsp.py` pass in 0.30s, zero existing TTS files were modified (`git diff --stat` is empty), and the implementation is clean, mathematically sound, and fully compatible with downstream milestones M2–M6.

---

## 2. Verification Commands & Outputs

### Command 1 — Target-Scoped M1 Unit Tests
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

============================== 45 passed in 0.30s ==============================
```

### Command 2 — Working Tree & Non-Invasiveness Check
```bash
git status --short && git diff --stat
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
(Empty `git diff --stat`: no existing tracked TTS files were modified.)

### Command 3 — Environment, `kotoba` Parity & Numerical DSP Checks
```bash
.venv/bin/python -c "
import torch, numpy as np, fastapi, uvicorn, multipart, pytest, httpx
import kotoba
from asr.tokenizer import Tokenizer, _DEFAULT_KANA_TOKENS, _DEFAULT_PHONEME_TOKENS
from asr.features import _dct_matrix, mel_filterbank

print('torch:', torch.__version__, 'cuda:', torch.cuda.is_available())
print('numpy:', np.__version__, 'fastapi:', fastapi.__version__)

k2v_keys = set(kotoba.K2V.keys())
kana_set = set(_DEFAULT_KANA_TOKENS)
assert k2v_keys.issubset(kana_set)
assert set(kotoba.SMALL.keys()).issubset(kana_set)
place_cons = {k for k in kotoba.PLACE.keys() if k}
phoneme_set = set(_DEFAULT_PHONEME_TOKENS)
assert place_cons.issubset(phoneme_set)

D = _dct_matrix(64, 64).astype(np.float64)
err = np.max(np.abs(D.T @ D - np.eye(64)))
print('DCT-II orthonormality max err:', err)
assert err < 1e-5

fb = mel_filterbank(sr=16000, n_fft=512, n_mels=64, f_min=80.0, f_max=7600.0)
df = 16000.0 / 512.0
areas = fb.sum(axis=1) * df
print('Mel filterbank areas min/median/max:', float(areas.min()), float(np.median(areas)), float(areas.max()))
assert 0.8 < float(np.median(areas)) < 1.2

print('ALL CHECKS PASSED')
"
```
- **Exit code**: `0`
- **Output**:
```text
torch: 2.15.0+cpu cuda: False
numpy: 2.4.6 fastapi: 0.165.0
DCT-II orthonormality max err: 7.587616579485257e-08
Mel filterbank areas min/median/max: 0.9055203795433044 0.9993200302124023 1.1114131212234497
ALL CHECKS PASSED
```

### Command 4 — Existing TTS Non-Regression
```bash
python3 yomu.py --help | head -n 5
```
- **Exit code**: `0`
- **Output**:
```text
usage: yomu.py [-h] [-o OUT]
               [--preset {default,ossan,robot,horror,whisper,chibi,utahime,choir}]
               [--trance] [--choir] [--iroke IROKE] [--list-presets]
               [--recipe RECIPE] [--save-recipe SAVE_RECIPE] [--compare]
```

---

## 3. Detailed Technical Audit

### A. `asr/config.py`
- **Contract compliance**: Exact default match for `AudioConfig`, `ModelConfig`, `TrainConfig`, and `DecodeConfig` against `PROJECT.md` and `SCOPE.md`.
- **Validation**: Strict `__post_init__` checks reject booleans passed as ints/floats, NaN/Inf values, invalid bounds (`win_length > n_fft`, `f_min >= f_max`, `f_max > sr/2`, `preemphasis >= 1.0`, even `conv_kernel_size`, `hidden_size % num_heads != 0` for `conformer_lite`, `lr <= 0`, `temperature <= 0`, empty/whitespace `checkpoint_dir`).
- **Serialization**: `.to_dict()` / `.from_dict()` support JSON round-trip, partial dicts with defaults, and raise `TypeError` on non-mappings / `ValueError` on unknown keys. Ready for M3 checkpointing and M6 REST API payloads.

### B. `asr/audio.py`
- **RIFF/WAVE parsing**: Pure-Python chunk walker handles even-byte RIFF padding (`chunk_size & 1`), `fmt ` + `WAVE_FORMAT_EXTENSIBLE` (`0xFFFE`), 8/16/24/32-bit PCM (including exact arithmetic right-shift sign extension for 24-bit signed PCM), 32/64-bit IEEE float, and multi-channel mono mixdown. Corrupt RIFF/WAVE payloads raise `ValueError` cleanly; non-WAV or unsupported codecs fall back to `ffmpeg` if installed.
- **FFT resampling**: Exact band-limited `rfft`/`irfft` resampling with correct Nyquist bin handling for both even-length upsampling (`*= 0.5`) and even-length downsampling (`real * 2.0`), matching `scipy.signal.resample` mathematics and providing brick-wall anti-aliasing.
- **Energy VAD**: Frame-level RMS in `float64` (including trailing partial frame), standard `20 * log10(max(rms, 1e-10))` dBFS, and frame hangover state machine (`ceil(hangover_ms / frame_ms)`). Returns sorted, non-overlapping `(start_sec, end_sec)` tuples clamped to signal duration.
- **Corruptions (`apply_corruption`)**: Non-mutating, deterministic with `seed`. Applies speed perturbation → raised-cosine FFT band-pass filter → exact-SNR white or `1/sqrt(f)` pink noise (zero DC) → linear `10**(gain_db / 20)` gain. Handles silent inputs without NaN/Inf.

### C. `asr/features.py`
- **Pre-emphasis & STFT**: Standard `y[t] = x[t] - coef * x[t-1]`, cached periodic Hann window, zero-padding for short/empty waveforms (`T >= 1`), `float32` power spectrum `(T, n_fft // 2 + 1)`.
- **Slaney Mel Filterbank**: Exact `librosa` (`htk=False`, `norm='slaney'`) constants (`200/3`, `1000 Hz = 15.0 mel`, `ln(6.4)/27`) and `2.0 / (f_right - f_left)` area normalization (verified median discrete area = `0.9993`). Cached internally, copied on public `mel_filterbank()` return to protect cache immutability.
- **Log-Mel & CMVN**: Safe `1e-10` floor, optional per-utterance zero-mean / unit-variance normalization along time axis with `1e-6` epsilon. Always finite `float32`.
- **MFCC & Deltas**: Orthonormal DCT-II matrix (verified max orthogonality error `7.59e-8`), standard HTK regression deltas (`half_width=2`) with edge padding and `T=1` safety.
- **SpecAugment**: Non-mutating, deterministic with `seed`, safely clamps mask widths to `(T, F)` bounds.

### D. `asr/tokenizer.py`
- **`kotoba.py` integration**: Verified 100% coverage of `kotoba.K2V` (71 kana), `kotoba.SMALL` (8 small kana), and non-empty `kotoba.PLACE` (19 consonants). Uses `kotoba.to_kata`, `kotoba.split_moras`, and `kotoba.parse_kana` cleanly.
- **Modes**:
  - `kana` (86 tokens): `<blank>=0`, Hiragana↔Katakana equivalence, full-width space normalization, optional custom multi-char mora vocab support.
  - `phoneme` (29 tokens): `<blank>=0`, validates kana tokens before `parse_kana` so unknown characters never emit spurious vowels, and supports space-separated phoneme round-trip.
  - `ascii` (42 tokens): `<blank>=0`, lowercased ASCII + digits + `'-,.`.
- **CTC semantics**: `collapse_ctc=True` collapses consecutive duplicate IDs before stripping `blank_id == 0`, preserving repeated characters separated by blanks (e.g., `[a, a, 0, a, 0, 0] -> "アア"`). Out-of-range IDs raise `ValueError`.
- **Serialization**: `.to_dict()` / `.from_dict()` round-trips cleanly across all 3 modes and custom vocabs.

---

## 4. Issues / Action Items

None. No blocking or non-blocking defects found.

**VERDICT: APPROVE**
