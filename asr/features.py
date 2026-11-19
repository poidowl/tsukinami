"""Pure-NumPy acoustic feature extraction: STFT, Slaney Mel, Log-Mel, MFCC, CMVN, SpecAugment."""

from __future__ import annotations

import functools
import math

import numpy as np

from asr.config import AudioConfig

# Slaney Mel scale constants (matching librosa's default htk=False formula)
_F_SP = 200.0 / 3.0
_MIN_LOG_HZ = 1000.0
_MIN_LOG_MEL = _MIN_LOG_HZ / _F_SP  # 15.0
_LOGSTEP = math.log(6.4) / 27.0


def _to_mono_1d(wav: np.ndarray) -> np.ndarray:
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        if arr.shape[1] == 0:
            raise ValueError("Audio array has 0 channels")
        return arr.mean(axis=-1, dtype=np.float32)
    raise ValueError(f"Expected 1D or 2D audio array, got shape {arr.shape}")


@functools.lru_cache(maxsize=32)
def _hann_window(win_length: int) -> np.ndarray:
    idx = np.arange(win_length, dtype=np.float64)
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * idx / win_length)).astype(np.float32)


def preemphasis(wav: np.ndarray, coef: float = 0.97) -> np.ndarray:
    """Apply first-order pre-emphasis filter ``y[t] = x[t] - coef * x[t-1]``."""
    x = _to_mono_1d(wav)
    if coef == 0.0 or x.size <= 1:
        return x.copy()
    y = np.empty_like(x)
    y[0] = x[0]
    y[1:] = x[1:] - np.float32(coef) * x[:-1]
    return y


def _to_mono_1d_f64(wav: np.ndarray) -> np.ndarray:
    arr = np.asarray(wav, dtype=np.float64)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        if arr.shape[1] == 0:
            raise ValueError("Audio array has 0 channels")
        return arr.mean(axis=-1, dtype=np.float64)
    raise ValueError(f"Expected 1D or 2D audio array, got shape {arr.shape}")


def _validate_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return int(value)


def _stft_power_f64(
    wav: np.ndarray,
    n_fft: int = 512,
    win_length: int = 400,
    hop_length: int = 160,
) -> np.ndarray:
    n_fft = _validate_positive_int("n_fft", n_fft)
    win_length = _validate_positive_int("win_length", win_length)
    hop_length = _validate_positive_int("hop_length", hop_length)
    if win_length > n_fft:
        raise ValueError(f"win_length ({win_length}) must be <= n_fft ({n_fft})")

    x = _to_mono_1d_f64(wav)
    if x.size < win_length:
        padded = np.zeros(win_length, dtype=np.float64)
        if x.size > 0:
            padded[: x.size] = x
        x = padded

    frames = np.lib.stride_tricks.sliding_window_view(x, win_length)[::hop_length]
    window = _hann_window(win_length).astype(np.float64)
    spec = np.fft.rfft(frames * window, n=n_fft, axis=1)
    return spec.real ** 2 + spec.imag ** 2


def stft_power(
    wav: np.ndarray,
    n_fft: int = 512,
    win_length: int = 400,
    hop_length: int = 160,
) -> np.ndarray:
    """Compute STFT power spectrogram of shape ``(T, n_fft // 2 + 1)``."""
    return _stft_power_f64(
        wav,
        n_fft=n_fft,
        win_length=win_length,
        hop_length=hop_length,
    ).astype(np.float32)


def hz_to_mel(hz: float | np.ndarray) -> np.ndarray:
    """Convert frequency in Hz to Slaney Mel scale."""
    hz_arr = np.asarray(hz, dtype=np.float64)
    return np.where(
        hz_arr < _MIN_LOG_HZ,
        hz_arr / _F_SP,
        _MIN_LOG_MEL + np.log(np.maximum(hz_arr, _MIN_LOG_HZ) / _MIN_LOG_HZ) / _LOGSTEP,
    )


def mel_to_hz(mel: float | np.ndarray) -> np.ndarray:
    """Convert Slaney Mel scale back to frequency in Hz."""
    mel_arr = np.asarray(mel, dtype=np.float64)
    return np.where(
        mel_arr < _MIN_LOG_MEL,
        mel_arr * _F_SP,
        _MIN_LOG_HZ * np.exp(_LOGSTEP * (mel_arr - _MIN_LOG_MEL)),
    )


@functools.lru_cache(maxsize=32)
def _mel_filterbank_cached(
    sr: int,
    n_fft: int,
    n_mels: int,
    f_min: float,
    f_max: float,
) -> np.ndarray:
    mel_pts = np.linspace(float(hz_to_mel(f_min)), float(hz_to_mel(f_max)), n_mels + 2)
    hz_pts = mel_to_hz(mel_pts)
    fft_freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    f_left = hz_pts[:-2, None]
    f_center = hz_pts[1:-1, None]
    f_right = hz_pts[2:, None]

    lower = (fft_freqs[None, :] - f_left) / np.maximum(f_center - f_left, 1e-12)
    upper = (f_right - fft_freqs[None, :]) / np.maximum(f_right - f_center, 1e-12)
    fb = np.maximum(0.0, np.minimum(lower, upper))

    enorm = 2.0 / np.maximum(hz_pts[2:] - hz_pts[:-2], 1e-12)
    fb *= enorm[:, None]
    return fb.astype(np.float32)


def mel_filterbank(
    sr: int = 16000,
    n_fft: int = 512,
    n_mels: int = 64,
    f_min: float = 80.0,
    f_max: float | None = 7600.0,
) -> np.ndarray:
    """Build Slaney-normalized Mel filterbank of shape ``(n_mels, n_fft // 2 + 1)``."""
    sr = _validate_positive_int("sr", sr)
    n_fft = _validate_positive_int("n_fft", n_fft)
    n_mels = _validate_positive_int("n_mels", n_mels)
    if isinstance(f_min, bool) or not isinstance(f_min, (int, float, np.number)):
        raise ValueError(f"f_min must be a finite number, got {f_min!r}")
    f_min_f = float(f_min)
    if not math.isfinite(f_min_f):
        raise ValueError(f"f_min must be finite, got {f_min!r}")
    if f_max is None:
        resolved_f_max = sr / 2.0
    else:
        if isinstance(f_max, bool) or not isinstance(f_max, (int, float, np.number)):
            raise ValueError(f"f_max must be a finite number or None, got {f_max!r}")
        f_max_f = float(f_max)
        if not math.isfinite(f_max_f):
            raise ValueError(f"f_max must be finite, got {f_max!r}")
        resolved_f_max = min(f_max_f, sr / 2.0)
    if f_min_f < 0.0 or f_min_f >= resolved_f_max:
        raise ValueError(f"Expected 0 <= f_min < f_max, got f_min={f_min_f}, f_max={resolved_f_max}")
    return _mel_filterbank_cached(int(sr), int(n_fft), int(n_mels), f_min_f, resolved_f_max).copy()


def extract_log_mel(wav: np.ndarray, cfg: AudioConfig | None = None) -> np.ndarray:
    """Extract Log-Mel spectrogram of shape ``(T, cfg.n_mels)`` as ``float32``."""
    cfg = cfg or AudioConfig()
    x = _to_mono_1d_f64(wav)
    if x.size > 0 and not np.isfinite(x).all():
        raise ValueError("wav must contain only finite values (no NaN or Inf)")
    if cfg.preemphasis != 0.0 and x.size > 1:
        y = np.empty_like(x)
        y[0] = x[0]
        y[1:] = x[1:] - float(cfg.preemphasis) * x[:-1]
        x = y

    power = _stft_power_f64(
        x,
        n_fft=cfg.n_fft,
        win_length=cfg.win_length,
        hop_length=cfg.hop_length,
    )
    fb = _mel_filterbank_cached(
        cfg.sample_rate, cfg.n_fft, cfg.n_mels, float(cfg.f_min), float(cfg.f_max)
    ).astype(np.float64)
    mel_energy = power @ fb.T
    log_mel = np.log(np.maximum(mel_energy, 1e-10))

    if cfg.cmvn:
        mean = log_mel.mean(axis=0, keepdims=True)
        std = log_mel.std(axis=0, keepdims=True)
        log_mel = (log_mel - mean) / (std + 1e-6)

    return log_mel.astype(np.float32)


@functools.lru_cache(maxsize=32)
def _dct_matrix(n_mels: int, n_mfcc: int) -> np.ndarray:
    n = np.arange(n_mels, dtype=np.float64)[:, None]
    k = np.arange(n_mfcc, dtype=np.float64)[None, :]
    dct = np.cos(np.pi * k * (n + 0.5) / n_mels)
    scale = np.full((1, n_mfcc), math.sqrt(2.0 / n_mels), dtype=np.float64)
    scale[0, 0] = math.sqrt(1.0 / n_mels)
    return (dct * scale).astype(np.float32)


def _compute_deltas(feat: np.ndarray, half_width: int = 2) -> np.ndarray:
    t_len, dim = feat.shape
    if t_len <= 1:
        return np.zeros((t_len, dim), dtype=np.float32)
    padded = np.pad(feat, ((half_width, half_width), (0, 0)), mode="edge")
    denom = 2.0 * sum(i * i for i in range(1, half_width + 1))
    acc = np.zeros_like(feat, dtype=np.float64)
    for i in range(1, half_width + 1):
        acc += i * (
            padded[half_width + i : half_width + i + t_len]
            - padded[half_width - i : half_width - i + t_len]
        )
    return (acc / denom).astype(np.float32)


def extract_mfcc(
    wav: np.ndarray,
    cfg: AudioConfig | None = None,
    n_mfcc: int = 13,
    include_deltas: bool = False,
) -> np.ndarray:
    """Extract MFCC features of shape ``(T, n_mfcc)`` or ``(T, 3 * n_mfcc)``."""
    cfg = cfg or AudioConfig()
    if isinstance(n_mfcc, bool) or not isinstance(n_mfcc, (int, np.integer)):
        raise ValueError(f"n_mfcc must be an integer, got {n_mfcc!r}")
    n_mfcc = int(n_mfcc)
    if n_mfcc < 1 or n_mfcc > cfg.n_mels:
        raise ValueError(
            f"n_mfcc must be in [1, {cfg.n_mels}], got {n_mfcc!r}"
        )

    log_mel = extract_log_mel(wav, cfg)
    mfcc = (log_mel @ _dct_matrix(cfg.n_mels, n_mfcc)).astype(np.float32)

    if include_deltas:
        d1 = _compute_deltas(mfcc)
        d2 = _compute_deltas(d1)
        mfcc = np.concatenate([mfcc, d1, d2], axis=1).astype(np.float32)

    return mfcc


def spec_augment(
    mel: np.ndarray,
    freq_mask_param: int = 8,
    time_mask_param: int = 20,
    num_freq_masks: int = 2,
    num_time_masks: int = 2,
    seed: int | None = None,
) -> np.ndarray:
    """Apply frequency and time masking (SpecAugment) without mutating input."""
    arr = np.asarray(mel, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2D mel spectrogram (T, F), got shape {arr.shape}")
    for name, val in (
        ("freq_mask_param", freq_mask_param),
        ("time_mask_param", time_mask_param),
        ("num_freq_masks", num_freq_masks),
        ("num_time_masks", num_time_masks),
    ):
        if isinstance(val, bool) or not isinstance(val, (int, np.integer)) or int(val) < 0:
            raise ValueError(f"{name} must be a non-negative integer, got {val!r}")
    freq_mask_param = int(freq_mask_param)
    time_mask_param = int(time_mask_param)
    num_freq_masks = int(num_freq_masks)
    num_time_masks = int(num_time_masks)

    out = arr.copy()
    t_len, f_len = out.shape
    if t_len == 0 or f_len == 0:
        return out

    rng = np.random.default_rng(seed)

    max_f = min(freq_mask_param, f_len)
    if max_f > 0:
        for _ in range(num_freq_masks):
            f = int(rng.integers(0, max_f + 1))
            if f > 0:
                f0 = int(rng.integers(0, f_len - f + 1))
                out[:, f0 : f0 + f] = 0.0

    max_t = min(time_mask_param, t_len)
    if max_t > 0:
        for _ in range(num_time_masks):
            t = int(rng.integers(0, max_t + 1))
            if t > 0:
                t0 = int(rng.integers(0, t_len - t + 1))
                out[t0 : t0 + t, :] = 0.0

    return out
