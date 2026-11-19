# Explorer 2 Handoff: Design Plan for `asr/audio.py` and `asr/features.py`

## Environment Findings
- Python `3.11.2` (`/usr/bin/python3`), `uv` (`/usr/local/bin/uv`), and `ffmpeg` (`/usr/bin/ffmpeg`) are installed on the machine.
- Existing TTS files (`carve.py`, `yomu.py`, `kotoba.py`, etc.) operate at 44.1 kHz (`C.SR`) and must remain untouched.
- Neither `asr/audio.py` nor `asr/features.py` requires PyTorch or SciPy — both are 100% pure NumPy + Python stdlib (`wave`, `struct`, `math`, `shutil`, `subprocess`, `functools`, `pathlib`).

---

## 1. Detailed Design: `asr/audio.py`

### Public API & Contracts
```python
def load_wav(path: str | Path, target_sr: int = 16000) -> tuple[np.ndarray, int]
def save_wav(path: str | Path, wav: np.ndarray, sr: int = 16000) -> None
def resample(wav: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray
def detect_vad(
    wav: np.ndarray,
    sr: int = 16000,
    frame_ms: float = 20.0,
    threshold_db: float = -35.0,
    hangover_ms: float = 150.0,
) -> list[tuple[float, float]]
def apply_corruption(
    wav: np.ndarray,
    sr: int,
    *,
    snr_db: float | None = None,
    noise_type: str = "white",
    band_limit: tuple[float, float] | None = None,
    speed: float = 1.0,
    gain_db: float = 0.0,
    seed: int | None = None,
) -> np.ndarray
```
(Optional helper for M6 server reuse: `load_wav_bytes(data: bytes, target_sr: int = 16000) -> tuple[np.ndarray, int]`.)

### Internal Helper: `_to_mono_float32(wav: np.ndarray) -> np.ndarray`
- Converts input via `np.asarray(wav, dtype=np.float32)`.
- If `ndim == 1`: return as-is.
- If `ndim == 2`: mix down channels via `arr.mean(axis=-1, dtype=np.float32)` (assumes `(N, C)` layout).
- If `ndim == 0` or `ndim > 2`: raise `ValueError`.

### 1.1 `load_wav(path, target_sr=16000)`
1. **Input validation**:
   - Validate `target_sr > 0`, else raise `ValueError`.
   - `p = Path(path)`. If `not p.exists()`: raise `FileNotFoundError(f"Audio file not found: {p}")`.
   - If `p.is_dir()`: raise `ValueError(f"Path is a directory: {p}")`.
   - Read raw bytes (`data = p.read_bytes()`). If `len(data) == 0`: raise `ValueError(f"Audio file is empty: {p}")`.
2. **Pure-Python RIFF/WAVE Parser (`_parse_wav_bytes(data)`)**:
   - Check `len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"`.
   - Iterate chunks starting at `pos = 12`:
     - Unpack `(chunk_id, chunk_size)` via `struct.unpack_from("<4sI", data, pos)`.
     - Advance `chunk_end = min(len(data), pos + 8 + chunk_size)` and next `pos = pos + 8 + chunk_size + (chunk_size & 1)` (RIFF 2-byte word alignment).
     - `fmt ` chunk (requires `>= 16` bytes): unpack `audio_format, n_channels, sample_rate, byte_rate, block_align, bits_per_sample = struct.unpack_from("<HHIIHH", chunk, 0)`.
       - If `audio_format == 0xFFFE` (`WAVE_FORMAT_EXTENSIBLE`) and `len(chunk) >= 40`: extract actual format tag from SubFormat GUID `struct.unpack_from("<H", chunk, 24)[0]`.
     - `data` chunk: slice `raw = data[pos + 8 : chunk_end]`.
   - Validate `fmt ` and `data` were both found, `n_channels >= 1`, `sample_rate > 0`, `bits_per_sample in (8, 16, 24, 32, 64)`.
   - Compute `sampwidth = bits_per_sample // 8`, `frame_bytes = n_channels * sampwidth`, `n_frames = len(raw) // frame_bytes`.
   - If `n_frames == 0`: raise `ValueError("WAV file contains no audio frames")`.
   - Truncate `raw = raw[: n_frames * frame_bytes]` (safe against trailing pad byte).
   - **Sample decoding**:
     - `audio_format == 1` (PCM):
       - `8-bit` unsigned: `(np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0`
       - `16-bit` signed LE: `np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0`
       - `24-bit` signed LE (vectorized, zero Python loops):
         ```python
         b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
         pad = np.zeros((b.shape[0], 4), dtype=np.uint8)
         pad[:, 1:] = b
         samples = (pad.view("<i4").ravel() >> 8).astype(np.float32) / 8388608.0
         ```
       - `32-bit` signed LE: `np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0`
     - `audio_format == 3` (IEEE float):
       - `32-bit`: `np.frombuffer(raw, dtype="<f4").copy()`
       - `64-bit`: `np.frombuffer(raw, dtype="<f8").astype(np.float32)`
     - Other format tags: raise `_UnsupportedWavFormat` so `ffmpeg` fallback can handle compressed WAVs (e.g., ADPCM, mu-law).
   - **Mono mixdown**: if `n_channels > 1`: `samples = samples.reshape(n_frames, n_channels).mean(axis=1, dtype=np.float32)`.
   - Sanitize non-finite values (`np.nan_to_num`) and resample if `sample_rate != target_sr`.
3. **Optional `ffmpeg` Fallback**:
   - Triggered only when RIFF/WAVE parsing fails (e.g. `.mp3`, `.ogg`, `.webm`, `.flac`, compressed WAV).
   - If `ffmpeg_bin := shutil.which("ffmpeg")`:
     - Run `[ffmpeg_bin, "-v", "error", "-i", str(p), "-ac", "1", "-ar", str(target_sr), "-f", "f32le", "pipe:1"]` with `capture_output=True, timeout=30`.
     - If `returncode == 0` and `len(stdout) >= 4`: decode `np.frombuffer(stdout, dtype="<f4").copy()`.
     - Else raise `ValueError(f"Failed to decode audio file '{p}': {stderr}")`.
   - If `ffmpeg` not found: raise `ValueError(f"Invalid or unsupported WAV file '{p}'")`.
4. **Final post-processing**:
   - `wav = np.clip(np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0).astype(np.float32, copy=False)`
   - Return `(wav, int(target_sr))`.

### 1.2 `save_wav(path, wav, sr=16000)`
- Validate `sr > 0`, else raise `ValueError`.
- Convert `wav` via `_to_mono_float32`.
- Sanitize and clip: `clipped = np.clip(np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0)`.
- Quantize to 16-bit signed LE PCM: `pcm = np.round(clipped * 32767.0).astype("<i2")`.
- Create parent dirs if needed: `p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)`.
- Write via `wave.open(str(p), "wb")` (`1` channel, `2` bytes/sample, `int(sr)` Hz).

### 1.3 `resample(wav, orig_sr, target_sr)`
- Validate `orig_sr > 0` and `target_sr > 0`, else raise `ValueError`.
- Convert `wav` via `_to_mono_float32`.
- Edge cases:
  - `wav.size == 0`: return `np.empty(0, dtype=np.float32)`.
  - `orig_sr == target_sr`: return `wav.copy()`.
  - `n_out = max(1, int(round(wav.size * target_sr / orig_sr)))`.
  - If `wav.size == 1`: return `np.full(n_out, wav[0], dtype=np.float32)`.
- **Algorithm — Exact FFT Resampling (`_resample_to_length(wav, n_out)`)**:
  - Matches `scipy.signal.resample` with exact Nyquist handling:
    ```python
    n_in = wav.size
    if n_out == n_in:
        return wav.astype(np.float32, copy=True)
    X = np.fft.rfft(wav.astype(np.float64))
    Y = np.zeros(n_out // 2 + 1, dtype=np.complex128)
    n_copy = min(X.size, Y.size)
    Y[:n_copy] = X[:n_copy]
    if n_out > n_in and n_in % 2 == 0:
        Y[n_in // 2] *= 0.5
    elif n_out < n_in and n_out % 2 == 0:
        Y[n_out // 2] = Y[n_out // 2].real * 2.0
    out = np.fft.irfft(Y, n=n_out) * (n_out / n_in)
    return out.astype(np.float32)
    ```
  - **Why FFT over bare linear interpolation or windowed-sinc**:
    - Ideal brick-wall anti-aliasing when downsampling `44100 -> 16000` (Tsukinami TTS) or `48000 -> 16000` (browser mic) — high-frequency tones above `target_sr / 2` are completely eliminated instead of aliasing.
    - `O(N log N)` (~12 ms for 10s @ 44.1 kHz on CPU, ~10× faster than windowed-sinc for bulk Tier-2 dataset generation).
    - Zero phase shift, exact DC preservation, handles arbitrary non-integer ratios (including `speed` perturbation in `apply_corruption`).

### 1.4 `detect_vad(wav, sr=16000, frame_ms=20.0, threshold_db=-35.0, hangover_ms=150.0)`
- Validate `sr > 0`, `frame_ms > 0`, `hangover_ms >= 0`, else raise `ValueError`.
- Convert via `_to_mono_float32`. If `wav.size == 0`: return `[]`.
- `duration = wav.size / float(sr)`
- `frame_len = max(1, int(round(sr * frame_ms / 1000.0)))`
- Compute per-frame RMS:
  - Full frames: `n_full = wav.size // frame_len`. Reshape `wav[: n_full * frame_len]` to `(n_full, frame_len)` -> `rms = np.sqrt(np.mean(frames ** 2, axis=1, dtype=np.float64))`.
  - Trailing partial frame (if `wav.size % frame_len != 0`): append `np.sqrt(np.mean(wav[n_full * frame_len :] ** 2, dtype=np.float64))`.
- If `np.all(rms == 0.0)`: return `[]` (guarantees silent/all-zero audio always returns `[]`).
- Convert to dBFS: `db = 20.0 * np.log10(np.maximum(rms, 1e-10))`.
- `is_speech = db > threshold_db`
- Apply trailing hangover state machine:
  - `hangover_frames = int(math.ceil(hangover_ms / frame_ms))` if `hangover_ms > 0` else `0`.
  - Walk frames: if `is_speech[i]`, set `active[i] = True, hang = hangover_frames`; else if `hang > 0`, set `active[i] = True, hang -= 1`.
  - Note: this automatically merges speech regions separated by `<= hangover_ms`.
- Extract contiguous `True` runs `[start_idx, end_idx)` into `(start_idx * frame_len / sr, min(end_idx * frame_len / sr, duration))`.
- Invariants: sorted, non-overlapping, `0.0 <= start < end <= duration`, `[]` on silence.

### 1.5 `apply_corruption(wav, sr, *, snr_db=None, noise_type="white", band_limit=None, speed=1.0, gain_db=0.0, seed=None)`
- **Validation**:
  - `sr <= 0` -> `ValueError`
  - `noise_type not in ("white", "pink")` -> `ValueError`
  - `not math.isfinite(speed) or speed <= 0.0` -> `ValueError`
  - `not math.isfinite(gain_db)` -> `ValueError`
  - `snr_db is not None and not math.isfinite(snr_db)` -> `ValueError`
  - `band_limit is not None`: must unpack to `(low_hz, high_hz)` with `0.0 <= low_hz < high_hz` and `low_hz < sr / 2.0`, else `ValueError`.
- Convert via `_to_mono_float32` and `.copy()` (never mutate caller's array). If `out.size == 0`: return `out`.
- `rng = np.random.default_rng(seed)`.
- **Pipeline order**:
  1. **Speed perturbation** (`speed != 1.0`):
     - `n_out = max(1, int(round(out.size / speed)))`
     - `out = _resample_to_length(out, n_out)` (`speed > 1.0` -> shorter/faster; `speed < 1.0` -> longer/slower).
  2. **Band-pass filter** (`band_limit is not None`):
     - `low_hz, high_hz = float(band_limit[0]), min(float(band_limit[1]), sr / 2.0)`
     - Smooth raised-cosine FFT filter (transition skirt `trans = min(50.0, 0.1 * (high_hz - low_hz))`):
       - `freqs = np.fft.rfftfreq(out.size, d=1.0 / sr)`
       - `H = np.zeros_like(freqs, dtype=np.float64)`
       - `H[(freqs >= low_hz) & (freqs <= high_hz)] = 1.0`
       - Lower skirt (when `low_hz > 0` and `trans > 0`): cosine taper on `[max(0.0, low_hz - trans), low_hz)`.
       - Upper skirt (when `high_hz < sr / 2.0` and `trans > 0`): cosine taper on `(high_hz, min(sr / 2.0, high_hz + trans)]`.
       - `out = np.fft.irfft(np.fft.rfft(out.astype(np.float64)) * H, n=out.size).astype(np.float32)`.
  3. **Additive noise at target SNR** (`snr_db is not None`):
     - Generate `noise` of length `out.size`:
       - `"white"`: `rng.standard_normal(out.size)`
       - `"pink"`: FFT `1 / sqrt(f)` spectral shaping (`W = rfft(white)`, `scale[0] = 0.0`, `scale[1:] = 1.0 / np.sqrt(freqs[1:])`, `irfft(W * scale, n=out.size)` — gives exact `-3 dB/octave` PSD `∝ 1/f`; fallback to `white` if `out.size <= 1`).
     - Compute `sig_power = float(np.mean(out.astype(np.float64) ** 2))`, `noise_power = float(np.mean(noise ** 2))`.
     - If `sig_power > 1e-12 and noise_power > 1e-12`:
       - `target_noise_power = sig_power / (10.0 ** (snr_db / 10.0))`
       - `out = (out.astype(np.float64) + noise * math.sqrt(target_noise_power / noise_power)).astype(np.float32)`
     - Silent signal (`sig_power <= 1e-12`): leave `out` unchanged (no NaN / div-by-zero).
  4. **Gain** (`gain_db != 0.0`):
     - `out = (out * np.float32(10.0 ** (gain_db / 20.0))).astype(np.float32)`.
- **Note on clipping**: Do NOT hard-clip `apply_corruption` output so exact SNR and gain ratios remain measurable in tests (`save_wav` handles clipping on PCM export).

---

## 2. Detailed Design: `asr/features.py`

### Public API & Contracts
```python
def preemphasis(wav: np.ndarray, coef: float = 0.97) -> np.ndarray
def stft_power(
    wav: np.ndarray,
    n_fft: int = 512,
    win_length: int = 400,
    hop_length: int = 160,
) -> np.ndarray
def hz_to_mel(hz: float | np.ndarray) -> np.ndarray
def mel_to_hz(mel: float | np.ndarray) -> np.ndarray
def mel_filterbank(
    sr: int = 16000,
    n_fft: int = 512,
    n_mels: int = 64,
    f_min: float = 80.0,
    f_max: float | None = 7600.0,
) -> np.ndarray
def extract_log_mel(wav: np.ndarray, cfg: AudioConfig | None = None) -> np.ndarray
def extract_mfcc(
    wav: np.ndarray,
    cfg: AudioConfig | None = None,
    n_mfcc: int = 13,
    include_deltas: bool = False,
) -> np.ndarray
def spec_augment(
    mel: np.ndarray,
    freq_mask_param: int = 8,
    time_mask_param: int = 20,
    num_freq_masks: int = 2,
    num_time_masks: int = 2,
    seed: int | None = None,
) -> np.ndarray
```
(Imports `AudioConfig` from `asr.config`; no circular dependency.)

### 2.1 `preemphasis(wav, coef=0.97)`
- `x = np.asarray(wav, dtype=np.float32)`
- If `coef == 0.0` or `x.size <= 1`: return `x.copy()`.
- `y = np.empty_like(x); y[0] = x[0]; y[1:] = x[1:] - np.float32(coef) * x[:-1]`.

### 2.2 `stft_power(wav, n_fft=512, win_length=400, hop_length=160)`
- Validate `n_fft > 0`, `win_length > 0`, `hop_length > 0`, `win_length <= n_fft`, else raise `ValueError`.
- Convert `wav` to 1D `float32`.
- Short/empty waveform handling:
  - If `wav.size < win_length` (including `wav.size == 0`): right-pad with zeros to `win_length` so `T >= 1` always holds cleanly without crashing.
- Framing (vectorized, zero loops):
  - `frames = np.lib.stride_tricks.sliding_window_view(x, win_length)[::hop_length]` -> shape `(T, win_length)` where `T = 1 + (len(x) - win_length) // hop_length`.
  - Periodic Hann window (cached by `win_length`):
    `window = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(win_length, dtype=np.float64) / win_length)).astype(np.float32)`
  - `spec = np.fft.rfft(frames * window, n=n_fft, axis=1)`
  - `power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)` -> shape `(T, n_fft // 2 + 1)`.

### 2.3 Slaney Mel Filterbank (`hz_to_mel`, `mel_to_hz`, `mel_filterbank`)
- Exact Slaney constants:
  - `F_SP = 200.0 / 3.0`
  - `MIN_LOG_HZ = 1000.0`
  - `MIN_LOG_MEL = MIN_LOG_HZ / F_SP` (`15.0`)
  - `LOGSTEP = math.log(6.4) / 27.0`
- `hz_to_mel(hz)`:
  - `hz_arr = np.asarray(hz, dtype=np.float64)`
  - `np.where(hz_arr < MIN_LOG_HZ, hz_arr / F_SP, MIN_LOG_MEL + np.log(np.maximum(hz_arr, MIN_LOG_HZ) / MIN_LOG_HZ) / LOGSTEP)`
- `mel_to_hz(mel)`:
  - `mel_arr = np.asarray(mel, dtype=np.float64)`
  - `np.where(mel_arr < MIN_LOG_MEL, mel_arr * F_SP, MIN_LOG_HZ * np.exp(LOGSTEP * (mel_arr - MIN_LOG_MEL)))`
- `mel_filterbank(sr, n_fft, n_mels, f_min, f_max)`:
  - Clamp `f_max = sr / 2.0 if f_max is None else min(float(f_max), sr / 2.0)`.
  - Validate `sr > 0`, `n_fft > 0`, `n_mels >= 1`, `0.0 <= f_min < f_max`.
  - `mel_pts = np.linspace(hz_to_mel(f_min), hz_to_mel(f_max), n_mels + 2)`
  - `hz_pts = mel_to_hz(mel_pts)`
  - `fft_freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)`
  - Triangular filters vectorized over `(n_mels, n_fft // 2 + 1)`:
    ```python
    f_left = hz_pts[:-2, None]
    f_center = hz_pts[1:-1, None]
    f_right = hz_pts[2:, None]
    lower = (fft_freqs[None, :] - f_left) / np.maximum(f_center - f_left, 1e-12)
    upper = (f_right - fft_freqs[None, :]) / np.maximum(f_right - f_center, 1e-12)
    fb = np.maximum(0.0, np.minimum(lower, upper))
    enorm = 2.0 / np.maximum(hz_pts[2:] - hz_pts[:-2], 1e-12)
    fb *= enorm[:, None]
    ```
  - Cache via `@functools.lru_cache(maxsize=32)` in `_mel_filterbank_cached(...)` (public `mel_filterbank` returns `.copy()` so callers cannot corrupt the cache).

### 2.4 `extract_log_mel(wav, cfg=None)`
- `cfg = cfg or AudioConfig()`
- Convert `wav` to 1D `float32` (mixdown if 2D, raise `ValueError` if `ndim == 0` or `ndim > 2`).
- `x = preemphasis(wav, cfg.preemphasis)`
- `power = stft_power(x, n_fft=cfg.n_fft, win_length=cfg.win_length, hop_length=cfg.hop_length)`
- `fb = _mel_filterbank_cached(cfg.sample_rate, cfg.n_fft, cfg.n_mels, cfg.f_min, cfg.f_max)`
- `mel_energy = power @ fb.T` -> `(T, cfg.n_mels)`
- `log_mel = np.log(np.maximum(mel_energy, np.float32(1e-10))).astype(np.float32)`
- If `cfg.cmvn`:
  - `mean = log_mel.mean(axis=0, keepdims=True)`
  - `std = log_mel.std(axis=0, keepdims=True)`
  - `log_mel = (log_mel - mean) / (std + np.float32(1e-6))`
- Guarantees: `float32`, shape `(T, cfg.n_mels)` with `T >= 1`, no NaN/Inf even on silent or 1-sample/empty input.

### 2.5 `extract_mfcc(wav, cfg=None, n_mfcc=13, include_deltas=False)`
- `cfg = cfg or AudioConfig()`
- Validate `1 <= n_mfcc <= cfg.n_mels`, else raise `ValueError`.
- `log_mel = extract_log_mel(wav, cfg)` -> `(T, M)`.
- Cached orthonormal DCT-II matrix `_dct_matrix(M, n_mfcc)` of shape `(M, n_mfcc)`:
  ```python
  n = np.arange(M, dtype=np.float64)[:, None]
  k = np.arange(n_mfcc, dtype=np.float64)[None, :]
  dct = np.cos(np.pi * k * (n + 0.5) / M)
  scale = np.full((1, n_mfcc), math.sqrt(2.0 / M), dtype=np.float64)
  scale[0, 0] = math.sqrt(1.0 / M)
  return (dct * scale).astype(np.float32)
  ```
- `mfcc = (log_mel @ _dct_matrix(cfg.n_mels, n_mfcc)).astype(np.float32)` -> `(T, n_mfcc)`.
- If `include_deltas`:
  - Regression delta helper `_compute_deltas(feat, half_width=2)`:
    - Edge-pad `feat` along `axis=0` by `half_width` on both sides (`mode="edge"`).
    - `denom = 2.0 * sum(i * i for i in range(1, half_width + 1))` (`10.0` for `half_width=2`).
    - Accumulate `i * (padded[half_width + i : half_width + i + T] - padded[half_width - i : half_width - i + T]) / denom`.
    - Safely handles `T == 1` (returns zeros of shape `(1, D)`).
  - `d1 = _compute_deltas(mfcc)`
  - `d2 = _compute_deltas(d1)`
  - `mfcc = np.concatenate([mfcc, d1, d2], axis=1).astype(np.float32)` -> `(T, 3 * n_mfcc)`.

### 2.6 `spec_augment(mel, freq_mask_param=8, time_mask_param=20, num_freq_masks=2, num_time_masks=2, seed=None)`
- Validate `mel.ndim == 2` and all mask params/counts `>= 0`, else raise `ValueError`.
- Non-mutating copy: `out = np.asarray(mel, dtype=np.float32).copy()`.
- `T, F = out.shape`; if `T == 0 or F == 0`: return `out`.
- `rng = np.random.default_rng(seed)`.
- Frequency masks: `max_f = min(freq_mask_param, F)`; for each mask, `f = int(rng.integers(0, max_f + 1))`, if `f > 0`: `f0 = int(rng.integers(0, F - f + 1))`, `out[:, f0 : f0 + f] = 0.0`.
- Time masks: `max_t = min(time_mask_param, T)`; for each mask, `t = int(rng.integers(0, max_t + 1))`, if `t > 0`: `t0 = int(rng.integers(0, T - t + 1))`, `out[t0 : t0 + t, :] = 0.0`.

---

## 3. Recommended Unit Tests (`tests/test_asr_dsp.py`)
1. **WAV I/O**:
   - Round-trip `save_wav` -> `load_wav` (16-bit PCM, sine wave correlation > 0.9999, dtype `float32`, range `[-1, 1]`).
   - Manually craft 8-bit unsigned, 24-bit signed, 32-bit signed PCM, and 32-bit IEEE float WAVs + stereo WAVs; verify `load_wav` decodes all accurately and mixes stereo to mono.
   - Missing file -> `FileNotFoundError`; 0-byte file, random garbage bytes, truncated WAV -> `ValueError`.
2. **Resampling**:
   - `44100 -> 16000` and `8000 -> 16000` preserve 440 Hz sine dominant frequency and output length `round(N * target_sr / orig_sr)`.
   - Anti-aliasing: 10 kHz sine at 44.1 kHz resampled to 16 kHz has RMS < 0.02 (not aliased).
   - Edge cases: `orig_sr == target_sr`, empty array, 1-sample array, invalid `sr <= 0` -> `ValueError`.
3. **VAD**:
   - Silence -> `[]`.
   - `[0.5s silence, 0.5s tone, 0.5s silence]` -> 1 segment with start near `0.5s` and end near `1.0s + hangover_ms`, clamped to `1.5s`.
   - Two bursts separated by `< hangover_ms` merge into 1 segment; separated by `> hangover_ms` yield 2 segments.
4. **Corruptions**:
   - White & pink noise at `snr_db = 10.0` achieves measured SNR within `±0.5 dB`; pink noise has higher low-freq/high-freq power ratio than white noise.
   - Silent signal + `snr_db = 10.0` produces finite zeros (no NaN/Inf).
   - `band_limit=(300.0, 3400.0)` preserves 1000 Hz tone and strongly attenuates 100 Hz and 6000 Hz tones.
   - `speed=1.25` shortens length by ~`1/1.25`; `gain_db=6.0` doubles RMS; same `seed` gives bit-exact equality.
   - Invalid `noise_type`, `speed <= 0`, invalid `band_limit` -> `ValueError`.
5. **Features & SpecAugment**:
   - Slaney `hz_to_mel` / `mel_to_hz` round-trip accuracy (`< 1e-9`) and continuity at `1000 Hz` (`15.0` mel).
   - `extract_log_mel` shape `(T, 64)`, `float32`, finite on silence and short (`< 400` samples) inputs; CMVN yields ~0 mean and ~1 std on non-silent audio.
   - `extract_mfcc` shapes `(T, 13)` and `(T, 39)` with `include_deltas=True`; safe on `T=1` short audio.
   - `spec_augment` does not mutate input, deterministic with `seed`, handles `freq_mask_param > F` and `time_mask_param > T`, zeros out masked regions.
