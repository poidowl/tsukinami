# Milestone M1 Challenger 1 Report (`iter1_chal1`)

**Target**: `asr/audio.py` and `asr/features.py`
**Runtime**: `/home/antigravity/poidowl/tsukinami/.venv/bin/python` with `PYTHONPATH=/home/antigravity/poidowl/tsukinami`
**Probe Staging**: All adversarial scripts and temporary WAV/FLAC artifacts were staged in ephemeral `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` directories and automatically removed on exit (`trap 'rm -rf "$PROBE_DIR"' EXIT`). No working-tree files were modified.

## VERDICT: PASS

All **28/28** independent adversarial probes passed with zero failures.

---

## Probe Results

### 1. `load_wav` & `load_wav_bytes` (`asr/audio.py`)

| # | Probe | Result | Observed Evidence |
|---|---|---|---|
| 1 | Missing file | PASS | Raises `FileNotFoundError` |
| 2 | Directory path | PASS | Raises `ValueError` |
| 3 | 0-byte file | PASS | Raises `ValueError` |
| 4 | Random garbage bytes (2048 B) | PASS | Raises `ValueError` |
| 5 | Truncated / malformed RIFF headers (6 variants: short RIFF, RIFF+WAVE only, truncated `fmt `, missing `data`, 0-byte `data`, 1-byte partial 16-bit frame) | PASS | All 6 raise `ValueError` |
| 6 | PCM 8/16/24/32-bit, IEEE float32/64, `WAVE_FORMAT_EXTENSIBLE` (PCM24 & float32) | PASS | Max abs errors vs ground-truth 440 Hz sine: `pcm8=8.42e-03`, `pcm16=3.35e-05`, `pcm24=1.26e-07`, `pcm32=2.88e-08`, `float32=2.88e-08`, `float64=2.88e-08`, `ext_pcm24=1.26e-07`, `ext_float32=2.88e-08` |
| 7 | Stereo & 4-channel mixdown | PASS | Opposite-phase stereo cancels to `max=0.00e+00`; 4-channel `[0.4, 0.4, 0.2, 0.2]` mixes down to `mean=0.3000` |
| 8 | IEEE float32 WAV with `NaN`, `±Inf`, out-of-range (`2.5`, `-3.0`) | PASS | Sanitized and clipped cleanly to `[-1.0, 1.0]` finite `float32` |
| 9 | Sample rate conversion (`44100 -> 16000`, `8000 -> 16000`) | PASS | Both preserve 1000 Hz sine peak within `< 5 Hz` and expected sample count |
| 10 | Non-WAV audio via `ffmpeg` fallback (FLAC via `load_wav` & `load_wav_bytes`) | PASS | Decoded FLAC to 16 kHz mono `float32`, peak `660.0 Hz`, file vs bytes match within `1e-5` |
| 11 | Odd-sized `JUNK` chunk padding + malicious `chunk_size=0xFFFFFFFF`, `n_channels=0`, `sample_rate=0` | PASS | Odd `JUNK` pad chunk parsed cleanly; all 3 malformed headers raise `ValueError` |

### 2. `resample` (`asr/audio.py`)

| # | Probe | Result | Observed Evidence |
|---|---|---|---|
| 12 | Empty array, 1-sample up/down, `orig_sr == target_sr` copy semantics, invalid `sr <= 0` / `bool` | PASS | Empty returns `(0,) float32`; 1-sample repeats value; `orig_sr == target_sr` does not alias input; all 6 invalid SR cases raise `ValueError` |
| 13 | Anti-aliasing & Nyquist preservation (`44100 -> 16000`, `32000 -> 16000`) | PASS | 10 kHz tone (> 8 kHz target Nyquist) attenuated by `-158.3 dB`; 1 kHz tone preserved with max err `4.75e-08`; exact-Nyquist 8 kHz cosine downsampled `32000 -> 16000` preserves amplitude `1.000` |

### 3. `detect_vad` (`asr/audio.py`)

| # | Probe | Result | Observed Evidence |
|---|---|---|---|
| 14 | All-zero silence, empty array, very short audio (`50` samples and `1` sample) | PASS | Silence `[]`, empty `[]`, 50-sample loud `[(0.0, 0.003125)]`, 1-sample loud `[(0.0, 6.25e-05)]` |
| 15 | Hangover merge (`80 ms < 150 ms`), split (`300 ms > 150 ms`), end-of-audio clamping | PASS | Merged: `[(0.2, 1.06)]`; split: `[(0.2, 0.66), (0.8, 1.26)]`; end burst clamped to `[(0.4, 0.5)]` |
| 16 | `hangover_ms=0.0`, stereo 2D input, invalid params (`sr<=0`, `frame_ms<=0`, `hangover_ms<0`, non-finite `threshold_db`) | PASS | `hangover=0` exact `[(0.2, 0.4)]`; stereo matches mono; all 7 invalid param cases raise `ValueError` |

### 4. `apply_corruption` (`asr/audio.py`)

| # | Probe | Result | Observed Evidence |
|---|---|---|---|
| 17 | White noise SNR accuracy (`-5, 0, 10, 20 dB`) | PASS | Measured `-5.00, -0.00, 10.00, 20.00 dB` (all within `< 0.1 dB` of target) |
| 18 | Pink noise SNR & spectral tilt | PASS | Measured SNR `0.00 dB`; low-band `[50, 500] Hz` vs high-band `[4000, 7500] Hz` PSD ratio `+14.7 dB` |
| 19 | Silent input + noise / band-pass / speed / gain | PASS | All outputs finite `float32` (no `NaN`/`Inf`) |
| 20 | Band-pass filter `(300, 3400) Hz` on `100 + 1000 + 5000 Hz` composite | PASS | `100 Hz = -179.7 dB`, `1000 Hz = 0.00 dB`, `5000 Hz = -181.2 dB` |
| 21 | Speed perturbation (`1.25x`, `0.8x`), non-mutation, determinism | PASS | Lengths `12800` and `20000`; input array unmodified; bitwise identical with same `seed` |
| 22 | Invalid params (`noise_type="purple"`, `speed<=0/nan/bool`, reversed/negative/above-Nyquist/malformed `band_limit`, non-finite `snr_db`/`gain_db`) | PASS | All 12 invalid param cases raise `ValueError` |
| 23 | 1-sample, 2-sample, 0-sample waveforms & edge `band_limit` (`(0, 3400)`, `(300, 8000)`, `(300, 12000)`) | PASS | All finite and clean without FFT length errors |

### 5. `extract_log_mel`, `mel_filterbank`, `extract_mfcc`, `spec_augment` (`asr/features.py`)

| # | Probe | Result | Observed Evidence |
|---|---|---|---|
| 24 | `extract_log_mel` on silent, empty, 1-sample, short (`100 < 400`), DC constant with `cmvn=True` and `cmvn=False` | PASS | All return finite `float32` `(T >= 1, 64)` |
| 25 | Slaney `mel_filterbank` properties (`hz_to_mel`/`mel_to_hz` continuity at `1000 Hz = 15.0 mel`, non-negative, non-zero, peaks at mel centers) | PASS | All 64 filters non-negative & non-zero; max peak offset `15.95 Hz` (`<= bin width 31.25 Hz`) |
| 26 | `extract_mfcc` + deltas on `T=1` and `T=5`, invalid `n_mfcc` | PASS | `T=1` -> `(1, 39)` with zero deltas; `T=5` -> `(5, 39)` finite; `0, -1, 65, True` raise `ValueError` |
| 27 | `spec_augment` with oversized mask params (`100 > T, F`), empty 2D `(0, 64)`/`(10, 0)`, determinism, non-mutation, invalid args | PASS | Input untouched, bitwise deterministic with `seed`, different seeds diverge, invalid dims/negative/bool params raise `ValueError` |
| 28 | 80-mel `AudioConfig(n_mels=80, f_min=0.0, f_max=8000.0)`, stereo 2D input, `mel_filterbank(f_max=None)`, `stft_power` validation | PASS | `(48, 80)` finite, stereo matches mono, `f_max=None` defaults to Nyquist, invalid `stft_power` args raise `ValueError` |
