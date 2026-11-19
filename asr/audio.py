"""Pure-NumPy / stdlib audio I/O, resampling, energy VAD, and waveform corruptions."""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np


class _InvalidWavError(ValueError):
    """Internal marker for malformed RIFF/WAVE payloads."""


class _UnsupportedWavFormatError(ValueError):
    """Internal marker for non-PCM/non-IEEE-float WAV format tags (e.g. ADPCM)."""


def _to_mono_float32(wav: np.ndarray) -> np.ndarray:
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        if arr.shape[1] == 0:
            raise ValueError("Audio array has 0 channels")
        return arr.mean(axis=-1, dtype=np.float32)
    raise ValueError(f"Expected 1D or 2D audio array, got shape {arr.shape}")


def _resample_to_length(wav: np.ndarray, n_out: int) -> np.ndarray:
    """Exact FFT-based band-limited resampling to a target sample count."""
    n_in = wav.size
    if n_out <= 0:
        raise ValueError(f"Target length must be > 0, got {n_out}")
    if n_in == 0:
        return np.empty(0, dtype=np.float32)
    if n_out == n_in:
        return wav.astype(np.float32, copy=True)
    if n_in == 1:
        return np.full(n_out, wav[0], dtype=np.float32)

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


def _validate_positive_int_sr(name: str, sr: object) -> int:
    if isinstance(sr, bool) or not isinstance(sr, (int, np.integer)) or int(sr) <= 0:
        raise ValueError(f"{name} must be a positive integer, got {sr!r}")
    return int(sr)


def resample(wav: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample a mono/stereo waveform from ``orig_sr`` to ``target_sr`` Hz."""
    orig_sr = _validate_positive_int_sr("orig_sr", orig_sr)
    target_sr = _validate_positive_int_sr("target_sr", target_sr)

    mono = _to_mono_float32(wav)
    if mono.size == 0:
        return np.empty(0, dtype=np.float32)
    if orig_sr == target_sr:
        return mono.copy()

    n_out = max(1, int(round(mono.size * target_sr / orig_sr)))
    return _resample_to_length(mono, n_out)


def _parse_wav_bytes(data: bytes) -> tuple[np.ndarray, int]:
    """Decode RIFF/WAVE bytes (PCM 8/16/24/32-bit or IEEE float 32/64-bit)."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise _InvalidWavError("Not a RIFF/WAVE payload")

    fmt_info: tuple[int, int, int, int] | None = None
    raw_audio: bytes | None = None

    pos = 12
    total_len = len(data)
    while pos + 8 <= total_len:
        chunk_id, chunk_size = struct.unpack_from("<4sI", data, pos)
        chunk_start = pos + 8
        chunk_end = min(total_len, chunk_start + chunk_size)

        if chunk_id == b"fmt ":
            chunk = data[chunk_start:chunk_end]
            if len(chunk) < 16:
                raise _InvalidWavError("Truncated WAV fmt chunk")
            (
                audio_format,
                n_channels,
                sample_rate,
                _byte_rate,
                _block_align,
                bits_per_sample,
            ) = struct.unpack_from("<HHIIHH", chunk, 0)
            if audio_format == 0xFFFE:
                if len(chunk) < 40:
                    raise _InvalidWavError("Truncated WAVE_FORMAT_EXTENSIBLE fmt chunk")
                audio_format = struct.unpack_from("<H", chunk, 24)[0]
            fmt_info = (audio_format, n_channels, sample_rate, bits_per_sample)
        elif chunk_id == b"data":
            raw_audio = data[chunk_start:chunk_end]

        pos = chunk_start + chunk_size + (chunk_size & 1)

    if fmt_info is None:
        raise _InvalidWavError("WAV file missing fmt chunk")
    if raw_audio is None:
        raise _InvalidWavError("WAV file missing data chunk")

    audio_format, n_channels, sample_rate, bits_per_sample = fmt_info
    if n_channels < 1:
        raise _InvalidWavError(f"Invalid channel count: {n_channels}")
    if sample_rate <= 0:
        raise _InvalidWavError(f"Invalid sample rate: {sample_rate}")
    if bits_per_sample not in (8, 16, 24, 32, 64):
        raise _UnsupportedWavFormatError(
            f"Unsupported bits_per_sample: {bits_per_sample}"
        )

    sampwidth = bits_per_sample // 8
    frame_bytes = n_channels * sampwidth
    n_frames = len(raw_audio) // frame_bytes
    if n_frames == 0:
        raise _InvalidWavError("WAV file contains no audio frames")

    raw_audio = raw_audio[: n_frames * frame_bytes]

    if audio_format == 1:  # PCM
        if bits_per_sample == 8:
            samples = (
                np.frombuffer(raw_audio, dtype=np.uint8).astype(np.float32) - 128.0
            ) / 128.0
        elif bits_per_sample == 16:
            samples = (
                np.frombuffer(raw_audio, dtype="<i2").astype(np.float32) / 32768.0
            )
        elif bits_per_sample == 24:
            b = np.frombuffer(raw_audio, dtype=np.uint8).reshape(-1, 3)
            pad = np.zeros((b.shape[0], 4), dtype=np.uint8)
            pad[:, 1:] = b
            samples = (pad.view("<i4").ravel() >> 8).astype(np.float32) / 8388608.0
        elif bits_per_sample == 32:
            samples = (
                np.frombuffer(raw_audio, dtype="<i4").astype(np.float32) / 2147483648.0
            )
        else:
            raise _UnsupportedWavFormatError(
                f"Unsupported PCM bit depth: {bits_per_sample}"
            )
    elif audio_format == 3:  # IEEE float
        if bits_per_sample == 32:
            samples = np.frombuffer(raw_audio, dtype="<f4").copy()
        elif bits_per_sample == 64:
            samples = np.frombuffer(raw_audio, dtype="<f8").astype(np.float32)
        else:
            raise _UnsupportedWavFormatError(
                f"Unsupported IEEE float bit depth: {bits_per_sample}"
            )
    else:
        raise _UnsupportedWavFormatError(
            f"Unsupported WAV audio format tag: {audio_format}"
        )

    if n_channels > 1:
        samples = samples.reshape(n_frames, n_channels).mean(axis=1, dtype=np.float32)

    return samples.astype(np.float32, copy=False), int(sample_rate)


def _decode_with_ffmpeg(
    source: Path | bytes, target_sr: int, label: str
) -> np.ndarray:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise ValueError(f"Invalid or unsupported audio format ({label})")

    if isinstance(source, Path):
        cmd = [
            ffmpeg_bin,
            "-v",
            "error",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            "-f",
            "f32le",
            "pipe:1",
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
    else:
        cmd = [
            ffmpeg_bin,
            "-v",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            "-f",
            "f32le",
            "pipe:1",
        ]
        proc = subprocess.run(
            cmd, input=source, capture_output=True, timeout=30, check=False
        )

    if proc.returncode != 0 or len(proc.stdout) < 4:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Failed to decode audio '{label}': {err or 'no audio output'}")

    n_samples = len(proc.stdout) // 4
    return np.frombuffer(proc.stdout[: n_samples * 4], dtype="<f4").copy()


def load_wav_bytes(data: bytes, target_sr: int = 16000) -> tuple[np.ndarray, int]:
    """Decode WAV (or ffmpeg-supported audio) bytes into mono float32 at ``target_sr``."""
    target_sr = _validate_positive_int_sr("target_sr", target_sr)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("Audio data must be bytes-like")
    raw = bytes(data)
    if len(raw) == 0:
        raise ValueError("Audio payload is empty")

    is_riff_wave = len(raw) >= 12 and raw[0:4] == b"RIFF" and raw[8:12] == b"WAVE"
    try:
        wav, orig_sr = _parse_wav_bytes(raw)
        wav = np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0).astype(
            np.float32, copy=False
        )
        if orig_sr != target_sr:
            wav = resample(wav, orig_sr, target_sr)
    except _UnsupportedWavFormatError:
        wav = _decode_with_ffmpeg(raw, target_sr, "<bytes>")
    except _InvalidWavError as exc:
        if is_riff_wave:
            raise ValueError(f"Corrupt WAV payload: {exc}") from exc
        wav = _decode_with_ffmpeg(raw, target_sr, "<bytes>")

    wav = np.clip(
        np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0
    ).astype(np.float32, copy=False)
    return wav, int(target_sr)


def load_wav(path: str | Path, target_sr: int = 16000) -> tuple[np.ndarray, int]:
    """Load an audio file as 1D mono ``float32`` in ``[-1.0, 1.0]`` at ``target_sr`` Hz."""
    target_sr = _validate_positive_int_sr("target_sr", target_sr)

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")
    if p.is_dir():
        raise ValueError(f"Path is a directory, not an audio file: {p}")

    raw = p.read_bytes()
    if len(raw) == 0:
        raise ValueError(f"Audio file is empty: {p}")

    is_riff_wave = len(raw) >= 12 and raw[0:4] == b"RIFF" and raw[8:12] == b"WAVE"
    try:
        wav, orig_sr = _parse_wav_bytes(raw)
        wav = np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0).astype(
            np.float32, copy=False
        )
        if orig_sr != target_sr:
            wav = resample(wav, orig_sr, target_sr)
    except _UnsupportedWavFormatError:
        wav = _decode_with_ffmpeg(p, target_sr, str(p))
    except _InvalidWavError as exc:
        if is_riff_wave:
            raise ValueError(f"Corrupt WAV file '{p}': {exc}") from exc
        wav = _decode_with_ffmpeg(p, target_sr, str(p))

    wav = np.clip(
        np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0
    ).astype(np.float32, copy=False)
    return wav, int(target_sr)


def save_wav(path: str | Path, wav: np.ndarray, sr: int = 16000) -> None:
    """Write a waveform as 16-bit signed little-endian mono PCM WAV."""
    sr = _validate_positive_int_sr("sr", sr)
    if sr > 2**32 - 1:
        raise ValueError(
            f"sr exceeds RIFF/WAVE 32-bit unsigned limit (4294967295), got {sr!r}"
        )

    mono = _to_mono_float32(wav)
    clipped = np.clip(
        np.nan_to_num(mono, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0
    )
    pcm = np.round(clipped * 32767.0).astype("<i2")

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())


def detect_vad(
    wav: np.ndarray,
    sr: int = 16000,
    frame_ms: float = 20.0,
    threshold_db: float = -35.0,
    hangover_ms: float = 150.0,
) -> list[tuple[float, float]]:
    """Frame-level RMS energy Voice Activity Detection with hangover padding.

    Returns sorted, non-overlapping ``(start_sec, end_sec)`` speech segments.
    """
    sr = _validate_positive_int_sr("sr", sr)
    if (
        isinstance(frame_ms, bool)
        or not isinstance(frame_ms, (int, float, np.number))
        or not math.isfinite(float(frame_ms))
        or float(frame_ms) <= 0.0
    ):
        raise ValueError(f"frame_ms must be finite and > 0, got {frame_ms!r}")
    frame_ms = float(frame_ms)
    if (
        isinstance(hangover_ms, bool)
        or not isinstance(hangover_ms, (int, float, np.number))
        or not math.isfinite(float(hangover_ms))
        or float(hangover_ms) < 0.0
    ):
        raise ValueError(f"hangover_ms must be finite and >= 0, got {hangover_ms!r}")
    hangover_ms = float(hangover_ms)
    if (
        isinstance(threshold_db, bool)
        or not isinstance(threshold_db, (int, float, np.number))
        or not math.isfinite(float(threshold_db))
    ):
        raise ValueError(f"threshold_db must be finite, got {threshold_db!r}")
    threshold_db = float(threshold_db)

    mono = _to_mono_float32(wav)
    if mono.size == 0:
        return []

    duration = mono.size / float(sr)
    raw_frame_len = sr * (frame_ms / 1000.0)
    if not math.isfinite(raw_frame_len) or raw_frame_len >= mono.size:
        frame_len = mono.size
    else:
        frame_len = max(1, int(round(raw_frame_len)))

    n_full = mono.size // frame_len
    rms_parts: list[np.ndarray] = []
    if n_full > 0:
        frames = mono[: n_full * frame_len].reshape(n_full, frame_len)
        rms_parts.append(np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)))
    rem = mono.size - n_full * frame_len
    if rem > 0:
        tail = mono[n_full * frame_len :].astype(np.float64)
        rms_parts.append(np.array([math.sqrt(float(np.mean(tail ** 2)))], dtype=np.float64))

    rms = np.concatenate(rms_parts) if len(rms_parts) > 1 else rms_parts[0]
    if np.all(rms == 0.0):
        return []

    db = 20.0 * np.log10(np.maximum(rms, 1e-10))
    is_speech = db > threshold_db

    if hangover_ms > 0.0:
        raw_hangover = hangover_ms / frame_ms
        if not math.isfinite(raw_hangover) or raw_hangover >= is_speech.size:
            hangover_frames = int(is_speech.size)
        else:
            hangover_frames = int(math.ceil(raw_hangover))
    else:
        hangover_frames = 0
    active = np.zeros(is_speech.size, dtype=bool)
    hang = 0
    for i, sp in enumerate(is_speech):
        if sp:
            active[i] = True
            hang = hangover_frames
        elif hang > 0:
            active[i] = True
            hang -= 1

    segments: list[tuple[float, float]] = []
    in_seg = False
    start_idx = 0
    for i, act in enumerate(active):
        if act and not in_seg:
            in_seg = True
            start_idx = i
        elif not act and in_seg:
            in_seg = False
            start_sec = start_idx * frame_len / float(sr)
            end_sec = min(i * frame_len / float(sr), duration)
            if end_sec > start_sec:
                segments.append((start_sec, end_sec))
    if in_seg:
        start_sec = start_idx * frame_len / float(sr)
        end_sec = min(active.size * frame_len / float(sr), duration)
        if end_sec > start_sec:
            segments.append((start_sec, end_sec))

    return segments


def _generate_noise(
    n_samples: int, sr: int, noise_type: str, rng: np.random.Generator
) -> np.ndarray:
    white = rng.standard_normal(n_samples)
    if noise_type == "white" or n_samples <= 1:
        return white
    # Pink noise: 1/f power spectral density -> 1/sqrt(f) amplitude shaping
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sr)
    spec = np.fft.rfft(white)
    scale = np.zeros_like(freqs, dtype=np.float64)
    scale[1:] = 1.0 / np.sqrt(freqs[1:])
    return np.fft.irfft(spec * scale, n=n_samples)


_MIN_SNR_DB = -100.0
_MAX_SNR_DB = 120.0
_MIN_GAIN_DB = -100.0
_MAX_GAIN_DB = 100.0
_MIN_SPEED = 0.1
_MAX_SPEED = 10.0


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
) -> np.ndarray:
    """Apply speed perturbation, band-pass filtering, additive noise, and gain."""
    sr = _validate_positive_int_sr("sr", sr)
    if noise_type not in ("white", "pink"):
        raise ValueError(
            f"noise_type must be 'white' or 'pink', got {noise_type!r}"
        )
    if (
        isinstance(speed, bool)
        or not isinstance(speed, (int, float, np.number))
        or not math.isfinite(float(speed))
        or float(speed) < _MIN_SPEED
        or float(speed) > _MAX_SPEED
    ):
        raise ValueError(
            f"speed must be finite and in [{_MIN_SPEED}, {_MAX_SPEED}], got {speed!r}"
        )
    speed = float(speed)
    if isinstance(gain_db, bool) or not isinstance(gain_db, (int, float, np.number)) or not math.isfinite(float(gain_db)):
        raise ValueError(f"gain_db must be finite, got {gain_db!r}")
    gain_db_f = float(gain_db)
    if gain_db_f < _MIN_GAIN_DB or gain_db_f > _MAX_GAIN_DB:
        raise ValueError(
            f"gain_db must be between {_MIN_GAIN_DB} and {_MAX_GAIN_DB}, got {gain_db!r}"
        )
    snr_db_f: float | None = None
    if snr_db is not None:
        if isinstance(snr_db, bool) or not isinstance(snr_db, (int, float, np.number)) or not math.isfinite(float(snr_db)):
            raise ValueError(f"snr_db must be finite or None, got {snr_db!r}")
        snr_db_f = float(snr_db)
        if snr_db_f < _MIN_SNR_DB or snr_db_f > _MAX_SNR_DB:
            raise ValueError(
                f"snr_db must be between {_MIN_SNR_DB} and {_MAX_SNR_DB}, got {snr_db!r}"
            )
    if band_limit is not None:
        if not isinstance(band_limit, (list, tuple)) or len(band_limit) != 2:
            raise ValueError(f"band_limit must be a 2-element (low_hz, high_hz) sequence, got {band_limit!r}")
        raw_lo, raw_hi = band_limit[0], band_limit[1]
        if (
            isinstance(raw_lo, bool)
            or isinstance(raw_hi, bool)
            or not isinstance(raw_lo, (int, float, np.number))
            or not isinstance(raw_hi, (int, float, np.number))
        ):
            raise ValueError(
                f"band_limit elements must be finite numbers, got {band_limit!r}"
            )
        low_hz, high_hz = float(raw_lo), float(raw_hi)
        if (
            not math.isfinite(low_hz)
            or not math.isfinite(high_hz)
            or low_hz < 0.0
            or low_hz >= high_hz
            or low_hz >= sr / 2.0
        ):
            raise ValueError(
                f"Invalid band_limit {band_limit!r} for sample rate {sr}"
            )

    out = _to_mono_float32(wav).copy()
    if out.size == 0:
        return out

    rng = np.random.default_rng(seed)

    # 1. Speed perturbation
    if speed != 1.0:
        n_out = max(1, int(round(out.size / speed)))
        out = _resample_to_length(out, n_out)

    # 2. Band-pass filter (raised-cosine FFT taper)
    if band_limit is not None:
        low_hz = float(band_limit[0])
        high_hz = min(float(band_limit[1]), sr / 2.0)
        trans = min(50.0, 0.1 * (high_hz - low_hz))
        freqs = np.fft.rfftfreq(out.size, d=1.0 / sr)
        H = np.zeros_like(freqs, dtype=np.float64)
        H[(freqs >= low_hz) & (freqs <= high_hz)] = 1.0

        if low_hz > 0.0 and trans > 0.0:
            lo_start = max(0.0, low_hz - trans)
            mask = (freqs >= lo_start) & (freqs < low_hz)
            if np.any(mask) and low_hz > lo_start:
                H[mask] = 0.5 * (
                    1.0 - np.cos(np.pi * (freqs[mask] - lo_start) / (low_hz - lo_start))
                )

        nyq = sr / 2.0
        if high_hz < nyq and trans > 0.0:
            hi_end = min(nyq, high_hz + trans)
            mask = (freqs > high_hz) & (freqs <= hi_end)
            if np.any(mask) and hi_end > high_hz:
                H[mask] = 0.5 * (
                    1.0 + np.cos(np.pi * (freqs[mask] - high_hz) / (hi_end - high_hz))
                )

        spec = np.fft.rfft(out.astype(np.float64))
        out = np.fft.irfft(spec * H, n=out.size).astype(np.float32)

    # 3. Additive noise at target SNR
    if snr_db_f is not None:
        noise = _generate_noise(out.size, sr, noise_type, rng)
        out_f64 = out.astype(np.float64)
        sig_power = float(np.mean(out_f64 ** 2))
        noise_power = float(np.mean(noise ** 2))
        if sig_power > 1e-12 and noise_power > 1e-12:
            target_noise_power = sig_power / (10.0 ** (snr_db_f / 10.0))
            scale = math.sqrt(target_noise_power / noise_power)
            out = (out_f64 + noise * scale).astype(np.float32)

    # 4. Gain
    if gain_db_f != 0.0:
        gain = 10.0 ** (gain_db_f / 20.0)
        out = (out.astype(np.float64) * gain).astype(np.float32)

    if not np.isfinite(out).all():
        f32_max = float(np.finfo(np.float32).max)
        out = np.nan_to_num(out, nan=0.0, posinf=f32_max, neginf=-f32_max).astype(np.float32)

    return out
