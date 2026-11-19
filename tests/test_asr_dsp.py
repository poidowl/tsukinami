"""Unit tests for Milestone M1: config, audio DSP, features, tokenizer, and TTS non-regression."""

from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import asr
import kotoba
from asr.audio import (
    apply_corruption,
    detect_vad,
    load_wav,
    load_wav_bytes,
    resample,
    save_wav,
)
from asr.config import AudioConfig, DecodeConfig, ModelConfig, TrainConfig
from asr.features import (
    extract_log_mel,
    extract_mfcc,
    hz_to_mel,
    mel_filterbank,
    mel_to_hz,
    spec_augment,
)
from asr.tokenizer import Tokenizer


def _sine(freq_hz: float, duration_sec: float, sr: int = 16000, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(round(duration_sec * sr)), dtype=np.float64) / sr
    return (amp * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32)


def _write_custom_wav(
    path: Path,
    audio_format: int,
    n_channels: int,
    sr: int,
    bits_per_sample: int,
    raw_frames: bytes,
) -> None:
    byte_rate = sr * n_channels * (bits_per_sample // 8)
    block_align = n_channels * (bits_per_sample // 8)
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ",
        16,
        audio_format,
        n_channels,
        sr,
        byte_rate,
        block_align,
        bits_per_sample,
    )
    data_chunk = struct.pack("<4sI", b"data", len(raw_frames)) + raw_frames
    if len(raw_frames) % 2 == 1:
        data_chunk += b"\x00"
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    header = struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE")
    path.write_bytes(header + fmt_chunk + data_chunk)


# ---------------------------------------------------------------------------
# 1. Package & Config tests
# ---------------------------------------------------------------------------


def test_package_exports():
    assert isinstance(asr.__version__, str) and asr.__version__
    for name in (
        "AudioConfig",
        "ModelConfig",
        "TrainConfig",
        "DecodeConfig",
        "load_wav",
        "save_wav",
        "resample",
        "detect_vad",
        "apply_corruption",
        "extract_log_mel",
        "extract_mfcc",
        "spec_augment",
        "Tokenizer",
    ):
        assert hasattr(asr, name), f"Missing export: {name}"


def test_config_defaults_and_json_roundtrip():
    configs = [
        AudioConfig(),
        ModelConfig(),
        TrainConfig(),
        DecodeConfig(),
        AudioConfig(sample_rate=8000, n_fft=256, win_length=200, hop_length=80, n_mels=40, f_min=50.0, f_max=3800.0, preemphasis=0.95, cmvn=False),
        ModelConfig(arch="conformer_lite", n_mels=80, hidden_size=128, num_layers=3, dropout=0.2, num_heads=4, conv_kernel_size=7),
        TrainConfig(epochs=5, batch_size=8, lr=1e-3, weight_decay=0.0, grad_clip=1.0, seed=123, use_spec_augment=False, checkpoint_dir="ckpt_out"),
        DecodeConfig(method="greedy", beam_width=4, temperature=0.8, blank_bias=-0.5, lm_weight=0.3, insertion_bonus=0.1),
    ]
    for cfg in configs:
        payload = json.dumps(cfg.to_dict())
        restored = type(cfg).from_dict(json.loads(payload))
        assert restored == cfg


def test_config_partial_from_dict_and_unknown_keys():
    assert AudioConfig.from_dict({"n_mels": 80}).n_mels == 80
    assert ModelConfig.from_dict({"arch": "conformer_lite"}).hidden_size == 192
    assert TrainConfig.from_dict({"epochs": 3}).seed == 42
    assert DecodeConfig.from_dict({"method": "greedy"}).beam_width == 8

    for cls in (AudioConfig, ModelConfig, TrainConfig, DecodeConfig):
        with pytest.raises(ValueError, match="Unknown"):
            cls.from_dict({"bogus_key": 1})
        with pytest.raises(TypeError):
            cls.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sample_rate": 0},
        {"sample_rate": -16000},
        {"n_mels": 0},
        {"win_length": 600, "n_fft": 512},
        {"f_min": 4000.0, "f_max": 3000.0},
        {"f_max": 9000.0, "sample_rate": 16000},
        {"preemphasis": 1.0},
        {"preemphasis": -0.1},
    ],
)
def test_audio_config_validation(kwargs):
    with pytest.raises(ValueError):
        AudioConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"arch": "unknown"},
        {"dropout": 1.0},
        {"dropout": -0.1},
        {"conv_kernel_size": 4},
        {"arch": "conformer_lite", "hidden_size": 190, "num_heads": 4},
        {"num_layers": 0},
    ],
)
def test_model_config_validation(kwargs):
    with pytest.raises(ValueError):
        ModelConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"epochs": 0},
        {"batch_size": 0},
        {"lr": 0.0},
        {"lr": float("nan")},
        {"weight_decay": -1e-4},
        {"grad_clip": -1.0},
        {"checkpoint_dir": "   "},
    ],
)
def test_train_config_validation(kwargs):
    with pytest.raises(ValueError):
        TrainConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": "invalid"},
        {"beam_width": 0},
        {"temperature": 0.0},
        {"lm_weight": -0.1},
        {"blank_bias": float("nan")},
        {"insertion_bonus": float("inf")},
    ],
)
def test_decode_config_validation(kwargs):
    with pytest.raises(ValueError):
        DecodeConfig(**kwargs)


# ---------------------------------------------------------------------------
# 2. Audio I/O & Resampling tests
# ---------------------------------------------------------------------------


def test_save_and_load_wav_roundtrip(tmp_path: Path):
    sr = 16000
    sig = _sine(440.0, 0.5, sr=sr, amp=0.6)
    wav_path = tmp_path / "sub" / "sine.wav"
    save_wav(wav_path, sig, sr=sr)

    loaded, out_sr = load_wav(wav_path, target_sr=sr)
    assert out_sr == sr
    assert loaded.dtype == np.float32
    assert loaded.ndim == 1
    assert loaded.shape == sig.shape
    assert float(np.min(loaded)) >= -1.0 and float(np.max(loaded)) <= 1.0
    corr = float(np.corrcoef(sig, loaded)[0, 1])
    assert corr > 0.9999
    assert float(np.max(np.abs(sig - loaded))) < 1e-3

    # load_wav_bytes parity
    loaded_bytes, out_sr_b = load_wav_bytes(wav_path.read_bytes(), target_sr=sr)
    assert out_sr_b == sr
    np.testing.assert_allclose(loaded, loaded_bytes, atol=1e-6)


def test_load_wav_formats_and_stereo_mixdown(tmp_path: Path):
    sr = 16000
    base = _sine(500.0, 0.1, sr=sr, amp=0.5)

    # 8-bit unsigned PCM
    p8 = tmp_path / "pcm8.wav"
    pcm8 = np.clip(np.round(base * 127.0 + 128.0), 0, 255).astype(np.uint8)
    _write_custom_wav(p8, 1, 1, sr, 8, pcm8.tobytes())
    w8, _ = load_wav(p8, target_sr=sr)
    assert np.corrcoef(base, w8)[0, 1] > 0.999

    # 24-bit signed PCM
    p24 = tmp_path / "pcm24.wav"
    i24 = np.round(base * 8388607.0).astype("<i4")
    raw24 = i24.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
    _write_custom_wav(p24, 1, 1, sr, 24, raw24)
    w24, _ = load_wav(p24, target_sr=sr)
    assert float(np.max(np.abs(base - w24))) < 1e-5

    # 32-bit signed PCM
    p32 = tmp_path / "pcm32.wav"
    i32 = np.round(base * 2147483647.0).astype("<i4")
    _write_custom_wav(p32, 1, 1, sr, 32, i32.tobytes())
    w32, _ = load_wav(p32, target_sr=sr)
    assert float(np.max(np.abs(base - w32))) < 1e-5

    # 32-bit IEEE float
    pf32 = tmp_path / "float32.wav"
    _write_custom_wav(pf32, 3, 1, sr, 32, base.astype("<f4").tobytes())
    wf32, _ = load_wav(pf32, target_sr=sr)
    np.testing.assert_allclose(base, wf32, atol=1e-6)

    # Stereo 16-bit PCM (left = base, right = zeros -> mono = 0.5 * base)
    p_stereo = tmp_path / "stereo.wav"
    stereo = np.stack([base, np.zeros_like(base)], axis=1)
    pcm16_st = np.round(stereo * 32767.0).astype("<i2")
    _write_custom_wav(p_stereo, 1, 2, sr, 16, pcm16_st.tobytes())
    w_mono, _ = load_wav(p_stereo, target_sr=sr)
    assert w_mono.ndim == 1
    np.testing.assert_allclose(w_mono, 0.5 * base, atol=1e-3)


def test_load_wav_errors(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_wav(tmp_path / "does_not_exist.wav")

    with pytest.raises(ValueError):
        load_wav(tmp_path)

    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        load_wav(empty)

    garbage = tmp_path / "garbage.wav"
    garbage.write_bytes(b"not a valid audio file at all 1234567890")
    with pytest.raises(ValueError):
        load_wav(garbage)

    truncated = tmp_path / "truncated.wav"
    truncated.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    with pytest.raises(ValueError):
        load_wav(truncated)


def test_resample_accuracy_and_antialiasing():
    # Downsample 44100 -> 16000 preserves 440 Hz tone
    sig44 = _sine(440.0, 0.5, sr=44100, amp=0.7)
    sig16 = resample(sig44, 44100, 16000)
    assert sig16.dtype == np.float32
    assert sig16.size == int(round(sig44.size * 16000 / 44100))
    freqs = np.fft.rfftfreq(sig16.size, d=1.0 / 16000)
    peak_hz = float(freqs[int(np.argmax(np.abs(np.fft.rfft(sig16))))])
    assert abs(peak_hz - 440.0) < 5.0

    # Upsample 8000 -> 16000 preserves 440 Hz tone
    sig8 = _sine(440.0, 0.5, sr=8000, amp=0.7)
    up16 = resample(sig8, 8000, 16000)
    assert up16.size == sig8.size * 2
    freqs_up = np.fft.rfftfreq(up16.size, d=1.0 / 16000)
    peak_up = float(freqs_up[int(np.argmax(np.abs(np.fft.rfft(up16))))])
    assert abs(peak_up - 440.0) < 5.0

    # Anti-aliasing: 10 kHz tone at 44.1 kHz is above 8 kHz Nyquist at 16 kHz
    hi_tone = _sine(10000.0, 0.5, sr=44100, amp=0.8)
    down = resample(hi_tone, 44100, 16000)
    rms = float(np.sqrt(np.mean(down ** 2)))
    assert rms < 0.02

    # Edge cases
    same = resample(sig16, 16000, 16000)
    np.testing.assert_array_equal(same, sig16)
    assert same is not sig16
    assert resample(np.empty(0, dtype=np.float32), 16000, 8000).size == 0
    one = resample(np.array([0.25], dtype=np.float32), 8000, 16000)
    assert one.size == 2 and np.allclose(one, 0.25)

    with pytest.raises(ValueError):
        resample(sig16, 0, 16000)
    with pytest.raises(ValueError):
        resample(sig16, 16000, -1)


# ---------------------------------------------------------------------------
# 3. Energy VAD tests
# ---------------------------------------------------------------------------


def test_detect_vad():
    sr = 16000
    assert detect_vad(np.zeros(sr, dtype=np.float32), sr=sr) == []
    assert detect_vad(np.empty(0, dtype=np.float32), sr=sr) == []

    # Silence - Speech - Silence
    sil = np.zeros(int(0.5 * sr), dtype=np.float32)
    tone = _sine(440.0, 0.5, sr=sr, amp=0.4)
    wav = np.concatenate([sil, tone, sil])
    segs = detect_vad(wav, sr=sr, frame_ms=20.0, threshold_db=-35.0, hangover_ms=150.0)
    assert len(segs) == 1
    start, end = segs[0]
    assert abs(start - 0.5) <= 0.03
    assert 1.1 <= end <= 1.25

    # Two bursts with gap < hangover_ms merge into 1 segment
    short_gap = np.zeros(int(0.08 * sr), dtype=np.float32)
    burst = _sine(440.0, 0.2, sr=sr, amp=0.4)
    merged_wav = np.concatenate([sil[: int(0.2 * sr)], burst, short_gap, burst, sil[: int(0.3 * sr)]])
    merged_segs = detect_vad(merged_wav, sr=sr, frame_ms=20.0, threshold_db=-35.0, hangover_ms=150.0)
    assert len(merged_segs) == 1

    # Two bursts with gap > hangover_ms yield 2 ordered non-overlapping segments
    long_gap = np.zeros(int(0.4 * sr), dtype=np.float32)
    split_wav = np.concatenate([sil[: int(0.2 * sr)], burst, long_gap, burst, sil[: int(0.3 * sr)]])
    split_segs = detect_vad(split_wav, sr=sr, frame_ms=20.0, threshold_db=-35.0, hangover_ms=100.0)
    assert len(split_segs) == 2
    assert split_segs[0][0] < split_segs[0][1] < split_segs[1][0] < split_segs[1][1]


# ---------------------------------------------------------------------------
# 4. Waveform Corruptions tests
# ---------------------------------------------------------------------------


def test_apply_corruption_noise_snr_and_determinism():
    sr = 16000
    clean = _sine(440.0, 1.0, sr=sr, amp=0.5)
    clean_orig = clean.copy()

    # No-op does not mutate input
    noop = apply_corruption(clean, sr)
    np.testing.assert_array_equal(noop, clean_orig)
    assert noop is not clean

    # White noise at 10 dB SNR + seed determinism
    w1 = apply_corruption(clean, sr, snr_db=10.0, noise_type="white", seed=7)
    w2 = apply_corruption(clean, sr, snr_db=10.0, noise_type="white", seed=7)
    np.testing.assert_array_equal(w1, w2)
    noise_w = w1 - clean
    snr_w = 10.0 * math.log10(float(np.mean(clean ** 2)) / float(np.mean(noise_w ** 2)))
    assert abs(snr_w - 10.0) < 0.5

    # Pink noise at 10 dB SNR + spectral tilt check
    p1 = apply_corruption(clean, sr, snr_db=10.0, noise_type="pink", seed=7)
    noise_p = p1 - clean
    snr_p = 10.0 * math.log10(float(np.mean(clean ** 2)) / float(np.mean(noise_p ** 2)))
    assert abs(snr_p - 10.0) < 0.5

    freqs = np.fft.rfftfreq(clean.size, d=1.0 / sr)
    spec_w = np.abs(np.fft.rfft(noise_w)) ** 2
    spec_p = np.abs(np.fft.rfft(noise_p)) ** 2
    lo = (freqs >= 100.0) & (freqs <= 500.0)
    hi = (freqs >= 3000.0) & (freqs <= 7000.0)
    ratio_w = float(np.mean(spec_w[lo]) / np.mean(spec_w[hi]))
    ratio_p = float(np.mean(spec_p[lo]) / np.mean(spec_p[hi]))
    assert ratio_p > ratio_w * 5.0

    # Silent signal stays finite zeros
    silent_out = apply_corruption(np.zeros(sr, dtype=np.float32), sr, snr_db=10.0, seed=1)
    assert np.all(np.isfinite(silent_out)) and np.all(silent_out == 0.0)


def test_apply_corruption_bandpass_speed_gain_and_errors():
    sr = 16000
    t100 = _sine(100.0, 1.0, sr=sr, amp=0.3)
    t1000 = _sine(1000.0, 1.0, sr=sr, amp=0.3)
    t6000 = _sine(6000.0, 1.0, sr=sr, amp=0.3)
    multi = t100 + t1000 + t6000

    bp = apply_corruption(multi, sr, band_limit=(300.0, 3400.0))
    freqs = np.fft.rfftfreq(bp.size, d=1.0 / sr)
    mag = np.abs(np.fft.rfft(bp))
    m100 = float(mag[int(np.argmin(np.abs(freqs - 100.0)))])
    m1000 = float(mag[int(np.argmin(np.abs(freqs - 1000.0)))])
    m6000 = float(mag[int(np.argmin(np.abs(freqs - 6000.0)))])
    assert m1000 > m100 * 10.0
    assert m1000 > m6000 * 10.0

    # Speed perturbation
    fast = apply_corruption(t1000, sr, speed=1.25)
    slow = apply_corruption(t1000, sr, speed=0.8)
    assert abs(fast.size - int(round(t1000.size / 1.25))) <= 1
    assert abs(slow.size - int(round(t1000.size / 0.8))) <= 1

    # Gain
    louder = apply_corruption(t1000, sr, gain_db=6.0)
    rms_ratio = float(np.sqrt(np.mean(louder ** 2)) / np.sqrt(np.mean(t1000 ** 2)))
    assert abs(rms_ratio - 10.0 ** (6.0 / 20.0)) < 1e-3

    # Validation errors
    with pytest.raises(ValueError):
        apply_corruption(t1000, sr, noise_type="brown")
    with pytest.raises(ValueError):
        apply_corruption(t1000, sr, speed=0.0)
    with pytest.raises(ValueError):
        apply_corruption(t1000, sr, band_limit=(3400.0, 300.0))


# ---------------------------------------------------------------------------
# 5. Features & SpecAugment tests
# ---------------------------------------------------------------------------


def test_slaney_mel_scale_and_filterbank():
    hz = np.array([0.0, 100.0, 500.0, 1000.0, 2500.0, 7600.0])
    mel = hz_to_mel(hz)
    hz_back = mel_to_hz(mel)
    np.testing.assert_allclose(hz, hz_back, atol=1e-9)
    assert abs(float(hz_to_mel(1000.0)) - 15.0) < 1e-12

    fb = mel_filterbank(sr=16000, n_fft=512, n_mels=64, f_min=80.0, f_max=7600.0)
    assert fb.shape == (64, 257)
    assert fb.dtype == np.float32
    assert float(np.min(fb)) >= 0.0
    assert np.all(fb.sum(axis=1) > 0.0)


def test_extract_log_mel_and_mfcc():
    sr = 16000
    sig = _sine(440.0, 0.5, sr=sr, amp=0.5)
    mel = extract_log_mel(sig)
    assert mel.dtype == np.float32
    assert mel.ndim == 2 and mel.shape[1] == 64
    assert np.all(np.isfinite(mel))

    # CMVN check on non-stationary signal
    rng = np.random.default_rng(0)
    non_const = (sig + 0.1 * rng.standard_normal(sig.size)).astype(np.float32)
    mel_cmvn = extract_log_mel(non_const, AudioConfig(cmvn=True))
    assert float(np.max(np.abs(mel_cmvn.mean(axis=0)))) < 1e-4
    assert float(np.mean(np.abs(mel_cmvn.std(axis=0) - 1.0))) < 1e-2

    # Frequency selectivity (without CMVN)
    cfg_raw = AudioConfig(cmvn=False)
    mel_lo = extract_log_mel(_sine(440.0, 0.5, sr=sr), cfg_raw).mean(axis=0)
    mel_hi = extract_log_mel(_sine(3000.0, 0.5, sr=sr), cfg_raw).mean(axis=0)
    assert int(np.argmax(mel_lo)) < int(np.argmax(mel_hi))

    # Silence, empty, and short (< win_length) inputs
    for edge in (
        np.zeros(sr, dtype=np.float32),
        np.empty(0, dtype=np.float32),
        np.ones(10, dtype=np.float32) * 0.1,
    ):
        m_edge = extract_log_mel(edge)
        assert m_edge.dtype == np.float32
        assert m_edge.shape[0] >= 1 and m_edge.shape[1] == 64
        assert np.all(np.isfinite(m_edge))

    # Custom n_mels=80
    mel80 = extract_log_mel(sig, AudioConfig(n_mels=80))
    assert mel80.shape[1] == 80

    # MFCC & deltas
    mfcc13 = extract_mfcc(non_const, n_mfcc=13, include_deltas=False)
    mfcc39 = extract_mfcc(non_const, n_mfcc=13, include_deltas=True)
    assert mfcc13.shape == (mel_cmvn.shape[0], 13)
    assert mfcc39.shape == (mel_cmvn.shape[0], 39)
    np.testing.assert_allclose(mfcc39[:, :13], mfcc13, atol=1e-6)

    # T=1 safe delta computation
    mfcc_short = extract_mfcc(np.ones(10, dtype=np.float32), n_mfcc=13, include_deltas=True)
    assert mfcc_short.shape == (1, 39)
    assert np.all(np.isfinite(mfcc_short))

    with pytest.raises(ValueError):
        extract_mfcc(sig, n_mfcc=0)
    with pytest.raises(ValueError):
        extract_mfcc(sig, n_mfcc=65)


def test_spec_augment():
    mel = np.ones((50, 64), dtype=np.float32) * 3.0
    mel_copy = mel.copy()
    aug1 = spec_augment(mel, freq_mask_param=8, time_mask_param=12, num_freq_masks=2, num_time_masks=2, seed=42)
    aug2 = spec_augment(mel, freq_mask_param=8, time_mask_param=12, num_freq_masks=2, num_time_masks=2, seed=42)

    np.testing.assert_array_equal(mel, mel_copy)  # no mutation
    np.testing.assert_array_equal(aug1, aug2)  # deterministic
    assert aug1.shape == mel.shape and aug1.dtype == np.float32
    assert np.any(aug1 == 0.0)

    # Zero masks leaves array unchanged
    no_mask = spec_augment(mel, num_freq_masks=0, num_time_masks=0, seed=0)
    np.testing.assert_array_equal(no_mask, mel)

    # Mask params larger than spectrogram dimensions do not crash
    tiny = np.ones((3, 4), dtype=np.float32)
    aug_tiny = spec_augment(tiny, freq_mask_param=20, time_mask_param=20, seed=1)
    assert aug_tiny.shape == (3, 4)


# ---------------------------------------------------------------------------
# 6. Tokenizer tests
# ---------------------------------------------------------------------------


def test_tokenizer_kana_mode():
    tok = Tokenizer("kana")
    assert tok.blank_id == 0
    assert tok.vocab[0] == "<blank>"
    assert tok.vocab_size == 86

    # Hiragana <-> Katakana equivalence
    assert tok.encode("わたし、にほんご") == tok.encode("ワタシ、ニホンゴ")

    # Round-trip with small kana, special moras, voiced/special chars, punctuation, space
    sample = "キョウハ、イッショニ コーヒーヲ ヴヂヅァィゥェォ。"
    ids = tok.encode(sample)
    assert all(i != 0 for i in ids)
    assert tok.decode(ids) == sample

    # Empty & unknown chars skipped cleanly
    assert tok.encode("") == []
    assert tok.decode(tok.encode("漢字ABCア")) == "ア"


def test_tokenizer_phoneme_mode():
    tok = Tokenizer("phoneme")
    assert tok.blank_id == 0
    assert tok.vocab_size == 29

    assert tok.decode(tok.encode("きょう")) == "k y o u"
    assert tok.decode(tok.encode("しゃしん")) == "sh a sh i N"
    assert tok.decode(tok.encode("いっしょ")) == "i Q sh o"
    assert tok.decode(tok.encode("こーひー")) == "k o : h i :"
    assert tok.decode(tok.encode("わたし、にほんご")) == "w a t a sh i pau n i h o N g o"

    # Space-separated phoneme string round-trip
    p_str = "k y o u pau sh a sh i N"
    assert tok.decode(tok.encode(p_str)) == p_str

    # Unknown chars must NOT emit spurious vowels
    assert tok.encode("漢字123") == []


def test_tokenizer_ascii_mode():
    tok = Tokenizer("ascii")
    assert tok.blank_id == 0
    assert tok.vocab_size == 42
    assert tok.decode(tok.encode("Hello, World 123! It's-ok.")) == "hello, world 123 it's-ok."


def test_tokenizer_ctc_collapse_and_serialization():
    tok = Tokenizer("kana")
    a_id = tok.token_to_id["ア"]
    seq = np.array([a_id, a_id, 0, a_id, 0, 0], dtype=np.int64)
    assert tok.decode(seq, collapse_ctc=True) == "アア"
    assert tok.decode(seq, collapse_ctc=False) == "アアア"
    assert tok.decode([0, 0, 0], collapse_ctc=True) == ""

    with pytest.raises(ValueError):
        tok.decode([tok.vocab_size])
    with pytest.raises(ValueError):
        tok.decode([-1])

    # JSON round-trip for all 3 modes
    for mode in ("kana", "phoneme", "ascii"):
        t = Tokenizer(mode)
        restored = Tokenizer.from_dict(json.loads(json.dumps(t.to_dict())))
        assert restored == t

    # Custom vocab auto-prepends <blank> at 0
    custom = Tokenizer("kana", vocab=["ア", "イ", "ウ"])
    assert custom.blank_id == 0
    assert custom.vocab == ["<blank>", "ア", "イ", "ウ"]
    assert Tokenizer.from_dict(custom.to_dict()) == custom

    # Validation errors
    with pytest.raises(ValueError):
        Tokenizer("invalid_mode")
    with pytest.raises(ValueError):
        Tokenizer("kana", vocab=["ア", "ア"])
    with pytest.raises(ValueError):
        Tokenizer("kana", vocab=["ア", "<blank>"])


# ---------------------------------------------------------------------------
# 7. Existing TTS Non-Regression
# ---------------------------------------------------------------------------


def test_existing_tts_non_regression():
    assert kotoba.split_moras("きょう") == ["キョ", "ウ"]
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, str(repo_root / "yomu.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0
    assert "--preset" in proc.stdout
