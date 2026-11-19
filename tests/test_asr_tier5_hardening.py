"""Tier 5 White-Box Adversarial Hardening tests for Tsukinami ASR."""

from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import math
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient

from asr.audio import (
    apply_corruption,
    detect_vad,
    load_wav,
    load_wav_bytes,
    resample,
    save_wav,
)
from asr.config import AudioConfig, DecodeConfig, ModelConfig, TrainConfig
from asr.decoding import CharNgramLM, greedy_decode, prefix_beam_search
from asr.features import extract_log_mel, extract_mfcc, mel_filterbank, spec_augment, stft_power
from asr.inference import ASREngine
from asr.metrics import alignment_boundary_error
from asr.models import build_model
from asr.server import create_app
from asr.synth_data import synthesize_fast_kotoba, synthesize_tsukinami
from asr.tokenizer import Tokenizer
from asr.train import train_asr

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "asr" / "web" / "index.html"


def _make_wav_bytes(samples: np.ndarray, sr: int = 16000) -> bytes:
    buf = io.BytesIO()
    pcm = np.clip(samples, -1.0, 1.0)
    pcm_i16 = (pcm * 32767.0).astype("<i2")
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_i16.tobytes())
    return buf.getvalue()


def _make_tiny_engine(
    arch: str = "cnn_bigru",
    *,
    max_cache_size: int = 8,
) -> ASREngine:
    audio_cfg = AudioConfig(n_mels=32)
    model_cfg = ModelConfig(
        arch=arch,
        n_mels=32,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
        num_heads=4,
        conv_kernel_size=7,
    )
    tok = Tokenizer("kana")
    model = build_model(model_cfg, vocab_size=tok.vocab_size)
    return ASREngine(
        model=model,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        tokenizer=tok,
        max_cache_size=max_cache_size,
    )


def _save_tiny_checkpoint(path: Path, arch: str = "cnn_bigru") -> Path:
    eng = _make_tiny_engine(arch=arch)
    torch.save(
        {
            "epoch": 1,
            "best_val_cer": 0.5,
            "model_state_dict": eng.model.state_dict(),
            "model_config": eng.model_cfg.to_dict(),
            "audio_config": eng.audio_cfg.to_dict(),
            "tokenizer": eng.tokenizer.to_dict(),
            "history": [],
        },
        path,
    )
    return path


# ---------------------------------------------------------------------------
# Challenger 1 Specs (1–8): Core DSP, Data, Models, Training, Decoding, Metrics
# ---------------------------------------------------------------------------


def test_decoding_extreme_temperature_and_blank_bias_stability() -> None:
    """Extreme temperature (1e-308) and blank_bias (1e308) never produce NaN or positive acoustic_score."""
    tok = Tokenizer("kana")
    v = tok.vocab_size

    # 1. Uniform valid log_probs with tiny temperature
    lp_uniform = np.log(np.full((5, v), 1.0 / v, dtype=np.float64))
    g1 = greedy_decode(lp_uniform, tok, temperature=1e-308)
    assert math.isfinite(g1["score"])
    assert g1["score"] <= 0.0

    b1 = prefix_beam_search(lp_uniform, tok, DecodeConfig(temperature=1e-308, beam_width=4))
    assert len(b1) >= 1
    for hyp in b1:
        assert math.isfinite(hyp["score"])
        assert math.isfinite(hyp["acoustic_score"])
        assert hyp["acoustic_score"] <= 1e-9

    # 2. Positive unnormalized logits with tiny temperature
    lp_pos = np.ones((5, v), dtype=np.float64)
    g2 = greedy_decode(lp_pos, tok, temperature=1e-308)
    assert math.isfinite(g2["score"])
    assert g2["score"] <= 0.0

    b2 = prefix_beam_search(lp_pos, tok, DecodeConfig(temperature=1e-308, beam_width=4))
    assert len(b2) >= 1
    for hyp in b2:
        assert math.isfinite(hyp["score"])
        assert math.isfinite(hyp["acoustic_score"])
        assert hyp["acoustic_score"] <= 1e-9

    # 3. Huge logits + huge blank_bias
    lp_huge = np.full((5, v), 1e308, dtype=np.float64)
    g3 = greedy_decode(lp_huge, tok, blank_bias=1e308)
    assert math.isfinite(g3["score"])
    assert g3["score"] <= 0.0
    assert g3["text"] == ""

    b3 = prefix_beam_search(lp_huge, tok, DecodeConfig(blank_bias=1e308, beam_width=4))
    assert len(b3) >= 1
    for hyp in b3:
        assert math.isfinite(hyp["score"])
        assert math.isfinite(hyp["acoustic_score"])
        assert hyp["acoustic_score"] <= 1e-9


def test_apply_corruption_extreme_snr_and_gain_no_crash_or_nan() -> None:
    """Extreme snr_db/gain_db raise ValueError cleanly; boundary values stay finite float32."""
    sr = 16000
    wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / sr).astype(np.float32)

    for bad_snr in (-5000.0, -1000.0, -101.0, 121.0, 4000.0):
        with pytest.raises(ValueError):
            apply_corruption(wav, sr, snr_db=bad_snr, seed=0)

    for bad_gain in (-1000.0, -101.0, 101.0, 800.0, 7000.0):
        with pytest.raises(ValueError):
            apply_corruption(wav, sr, gain_db=bad_gain)

    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", snr_db=-5000.0, seed=0)

    # Boundary values inside allowed domain must succeed with finite float32 output
    for ok_snr in (-100.0, 120.0):
        out = apply_corruption(wav, sr, snr_db=ok_snr, seed=0)
        assert out.dtype == np.float32
        assert np.isfinite(out).all()

    for ok_gain in (-100.0, 100.0):
        out = apply_corruption(wav, sr, gain_db=ok_gain)
        assert out.dtype == np.float32
        assert np.isfinite(out).all()


def test_synthesize_tsukinami_invalid_overrides_rejected() -> None:
    """Invalid hz, fscale, rate, or tsubu overrides raise ValueError instead of ZeroDivisionError/OverflowError."""
    for overrides in (
        {"hz": 0},
        {"hz": -100},
        {"hz": float("nan")},
        {"hz": 1e-308},
        {"hz": 1e6},
        {"fscale": 0},
        {"fscale": -0.5},
        {"fscale": 100.0},
        {"rate": 0},
        {"rate": -1},
        {"rate": float("inf")},
        {"rate": 1e308},
        {"tsubu": 0},
        {"tsubu": -1},
        {"tsubu": 0.5},
        {"tsubu": float("inf")},
        {"tsubu": True},
        {"yure": float("inf")},
        {"yure": 1e308},
        {"yure": -1.0},
        {"yure": True},
        {"shimmer": float("nan")},
        {"shimmer": float("inf")},
        {"line_g": float("nan")},
        {"tadayoi": float("inf")},
        {"tr_iroke": float("inf")},
        {"tr_iroke": True},
        {"ap_n": 100000},
        {"ap_n": -1},
        {"ap_n": True},
        {"seed": None},
        {"seed": True},
        {"seed": -1},
        {"seed": 2**32},
    ):
        with pytest.raises(ValueError):
            synthesize_tsukinami("ア", overrides=overrides)

    # Zero-valued preset fields (robot: yure/shimmer/tadayoi/ap_n=0; whisper: line_g=0) must remain valid
    for preset_name in ("robot", "whisper"):
        wav_p, moras_p = synthesize_tsukinami("ア", preset=preset_name, sr=16000)
        assert wav_p.size > 0 and np.isfinite(wav_p).all()
        assert len(moras_p) >= 1

    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", rate=1e308)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", rate=1e-6)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", f0_scale=1e308)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", fscale=1e308)


def test_train_config_seed_bounds_validation() -> None:
    """TrainConfig rejects seeds outside [0, 2**32 - 1] immediately on construction."""
    with pytest.raises(ValueError):
        TrainConfig(seed=-1)
    with pytest.raises(ValueError):
        TrainConfig(seed=2**32)

    assert TrainConfig(seed=0).seed == 0
    assert TrainConfig(seed=2**32 - 1).seed == 2**32 - 1


def test_train_resume_rejects_malformed_or_mismatched_tokenizer(tmp_path: Path) -> None:
    """train_asr(resume_from=...) rejects non-mapping tokenizer and same-length mismatched vocab."""
    wav_path = tmp_path / "utt.wav"
    wav, _ = synthesize_fast_kotoba("アイ", sr=16000, seed=0)
    save_wav(wav_path, wav, sr=16000)

    manifest = tmp_path / "m.jsonl"
    manifest.write_text(
        json.dumps({"audio_path": str(wav_path), "text": "アイ", "duration": len(wav) / 16000.0})
        + "\n",
        encoding="utf-8",
    )

    audio_cfg = AudioConfig(n_mels=32)
    model_cfg = ModelConfig(arch="cnn_bigru", n_mels=32, hidden_size=16, num_layers=1, dropout=0.0)
    tok_a = Tokenizer("kana", vocab=["<blank>", "ア", "イ", "ウ"])
    tok_b = Tokenizer("kana", vocab=["<blank>", "カ", "キ", "ク"])
    model = build_model(model_cfg, vocab_size=tok_a.vocab_size)

    # 1. Malformed tokenizer=None
    ckpt_none = tmp_path / "ckpt_none.pt"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "model_config": model_cfg.to_dict(),
            "tokenizer": None,
        },
        ckpt_none,
    )
    train_cfg = TrainConfig(
        epochs=1, batch_size=1, checkpoint_dir=str(tmp_path / "out1"), use_spec_augment=False
    )
    with pytest.raises(ValueError, match="tokenizer"):
        train_asr(
            manifest,
            manifest,
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=train_cfg,
            tokenizer=tok_a,
            resume_from=ckpt_none,
        )

    # 2. Same-length mismatched vocab
    ckpt_mismatch = tmp_path / "ckpt_mismatch.pt"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "model_config": model_cfg.to_dict(),
            "tokenizer": tok_b.to_dict(),
        },
        ckpt_mismatch,
    )
    train_cfg2 = TrainConfig(
        epochs=1, batch_size=1, checkpoint_dir=str(tmp_path / "out2"), use_spec_augment=False
    )
    with pytest.raises(ValueError, match="vocabulary"):
        train_asr(
            manifest,
            manifest,
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=train_cfg2,
            tokenizer=tok_a,
            resume_from=ckpt_mismatch,
        )

    # 3. Malformed history=None
    ckpt_bad_hist = tmp_path / "ckpt_bad_hist.pt"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "model_config": model_cfg.to_dict(),
            "tokenizer": tok_a.to_dict(),
            "history": None,
        },
        ckpt_bad_hist,
    )
    train_cfg3 = TrainConfig(
        epochs=1, batch_size=1, checkpoint_dir=str(tmp_path / "out3"), use_spec_augment=False
    )
    with pytest.raises(ValueError, match="Corrupt or incompatible resume checkpoint"):
        train_asr(
            manifest,
            manifest,
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=train_cfg3,
            tokenizer=tok_a,
            resume_from=ckpt_bad_hist,
        )

    # 4. Mismatched model_state_dict
    ckpt_bad_sd = tmp_path / "ckpt_bad_sd.pt"
    torch.save(
        {
            "model_state_dict": {"bad": torch.zeros(1)},
            "model_config": model_cfg.to_dict(),
            "tokenizer": tok_a.to_dict(),
            "history": [],
        },
        ckpt_bad_sd,
    )
    train_cfg4 = TrainConfig(
        epochs=1, batch_size=1, checkpoint_dir=str(tmp_path / "out4"), use_spec_augment=False
    )
    with pytest.raises(ValueError, match="Corrupt or incompatible resume checkpoint"):
        train_asr(
            manifest,
            manifest,
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=train_cfg4,
            tokenizer=tok_a,
            resume_from=ckpt_bad_sd,
        )

    # 5. Malformed optimizer_state_dict=None, scheduler_state_dict, history=[{}], best_val_cer=NaN/-0.1, epoch=-5
    bad_resume_cases = [
        ("opt_none", {"optimizer_state_dict": None, "history": []}, 1),
        ("sched_bad", {"scheduler_state_dict": "not_a_mapping", "history": []}, 1),
        ("hist_empty_entry", {"history": [{}], "epoch": 5}, 2),
        ("best_cer_nan", {"best_val_cer": float("nan"), "history": []}, 1),
        ("best_cer_neg", {"best_val_cer": -0.1, "history": []}, 1),
        ("epoch_neg", {"epoch": -5, "history": []}, 1),
    ]
    for label, extra_fields, num_epochs in bad_resume_cases:
        ckpt_bad = tmp_path / f"ckpt_{label}.pt"
        payload = {
            "model_state_dict": model.state_dict(),
            "model_config": model_cfg.to_dict(),
            "tokenizer": tok_a.to_dict(),
            **extra_fields,
        }
        torch.save(payload, ckpt_bad)
        tcfg = TrainConfig(
            epochs=num_epochs,
            batch_size=1,
            checkpoint_dir=str(tmp_path / f"out_{label}"),
            use_spec_augment=False,
        )
        with pytest.raises(ValueError, match="Corrupt or incompatible resume checkpoint"):
            train_asr(
                manifest,
                manifest,
                audio_cfg=audio_cfg,
                model_cfg=model_cfg,
                train_cfg=tcfg,
                tokenizer=tok_a,
                resume_from=ckpt_bad,
            )


def test_features_nan_filterbank_large_signal_and_type_validation() -> None:
    """Features reject NaN filterbank params, avoid float32 overflow on 1e20 wav, and reject floats."""
    with pytest.raises(ValueError):
        mel_filterbank(f_min=float("nan"))
    with pytest.raises(ValueError):
        mel_filterbank(f_max=float("nan"))
    with pytest.raises(ValueError):
        mel_filterbank(f_min=float("inf"))

    wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / 16000.0).astype(np.float32)
    mel_large = extract_log_mel(wav * np.float32(1e20))
    assert mel_large.dtype == np.float32
    assert np.isfinite(mel_large).all()

    bad_wav = wav.copy()
    bad_wav[10] = np.nan
    with pytest.raises(ValueError):
        extract_log_mel(bad_wav)

    with pytest.raises(ValueError):
        extract_mfcc(wav, n_mfcc=3.5)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        mel_filterbank(sr=float("inf"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        mel_filterbank(n_mels=3.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        mel_filterbank(sr=True, f_min=0.0, f_max=0.4)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        stft_power(wav, hop_length=160.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        stft_power(wav, n_fft=512.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        stft_power(wav, win_length=True)  # type: ignore[arg-type]

    mel = np.ones((10, 64), dtype=np.float32)
    with pytest.raises(ValueError):
        spec_augment(mel, num_freq_masks=2.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        spec_augment(mel, freq_mask_param=1.5)  # type: ignore[arg-type]


def test_resample_rejects_non_int_and_non_finite_sr() -> None:
    """resample rejects float/NaN/Inf/bool sample rates with ValueError."""
    wav = np.ones(1600, dtype=np.float32)
    for bad_orig, bad_target in (
        (float("inf"), 16000),
        (16000, float("inf")),
        (float("nan"), 16000),
        (16000, float("nan")),
        (16000.5, 8000),
        (True, 16000),
    ):
        with pytest.raises(ValueError):
            resample(wav, bad_orig, bad_target)  # type: ignore[arg-type]


def test_audio_save_wav_vad_and_corruption_parameter_hardening(tmp_path: Path) -> None:
    """save_wav never creates 0-byte files on bad sr; detect_vad/apply_corruption reject bad types/bounds."""
    wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / 16000.0).astype(np.float32)

    for idx, bad_sr in enumerate((float("inf"), float("nan"), 16000.5, True, 0, -16000)):
        out_path = tmp_path / f"bad_sr_{idx}.wav"
        with pytest.raises(ValueError):
            save_wav(out_path, wav, sr=bad_sr)  # type: ignore[arg-type]
        assert not out_path.exists(), f"save_wav left corrupt file on disk for sr={bad_sr!r}"

        with pytest.raises(ValueError):
            load_wav(out_path, target_sr=bad_sr)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            load_wav_bytes(b"RIFF", target_sr=bad_sr)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            detect_vad(wav, sr=bad_sr)  # type: ignore[arg-type]

    out_u32 = tmp_path / "bad_sr_u32_overflow.wav"
    with pytest.raises(ValueError):
        save_wav(out_u32, wav, sr=2**32)
    assert not out_u32.exists(), "save_wav left corrupt file on disk for sr=2**32"

    with pytest.raises(ValueError):
        detect_vad(wav, frame_ms=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        detect_vad(wav, threshold_db=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        detect_vad(wav, hangover_ms=False)  # type: ignore[arg-type]

    # Extreme finite frame_ms / hangover_ms must clamp cleanly without OverflowError
    for vad_kwargs in (
        {"frame_ms": 1e308},
        {"frame_ms": 1e-308, "hangover_ms": 150.0},
    ):
        segs = detect_vad(wav, sr=16000, **vad_kwargs)
        assert isinstance(segs, list)
        assert len(segs) >= 1
        for start_s, end_s in segs:
            assert math.isfinite(start_s) and math.isfinite(end_s)
            assert 0.0 <= start_s < end_s <= wav.size / 16000.0 + 1e-9

    for bad_speed in (1e-308, 1e-6, 0.05, 100.0, float("inf"), True):
        with pytest.raises(ValueError):
            apply_corruption(wav, 16000, speed=bad_speed)  # type: ignore[arg-type]

    for bad_band in (123, "300-3400", (False, True), (300.0,), (300.0, 3400.0, 5000.0)):
        with pytest.raises(ValueError):
            apply_corruption(wav, 16000, band_limit=bad_band)  # type: ignore[arg-type]


def test_tokenizer_and_lm_malformed_inputs_and_model_nan_padding_isolation() -> None:
    """Tokenizer/LM/metrics reject malformed inputs; models isolate NaN padding and long sequences."""
    with pytest.raises(ValueError):
        Tokenizer("kana", vocab=["<blank>", 123])  # type: ignore[list-item]

    tok = Tokenizer("kana")
    with pytest.raises(ValueError):
        tok.decode([True])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        tok.decode([1.9])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        Tokenizer.from_dict({"mode": "kana", "vocab": 123})
    with pytest.raises(ValueError):
        Tokenizer.from_dict({"mode": "kana", "vocab": "abc"})
    with pytest.raises(ValueError):
        Tokenizer.from_dict({"mode": "kana", "vocab": b"abc"})

    for bad_lm in (
        {"order": 2, "smoothing": 0.1, "vocab": 123, "ngrams": []},
        {"order": 2, "smoothing": 0.1, "vocab": ["ア"], "ngrams": 123},
        {"order": 2, "smoothing": 0.1, "vocab": ["ア"], "ngrams": [[123, {"ア": 1}]]},
    ):
        with pytest.raises(ValueError):
            CharNgramLM.from_dict(bad_lm)

    with pytest.raises(ValueError):
        alignment_boundary_error(
            [{"t": "ア", "a": float("nan"), "e": 0.2}],
            [{"token": "ア", "start_sec": 0.0, "end_sec": 0.2}],
        )
    with pytest.raises(ValueError):
        alignment_boundary_error(
            [{"t": "ア", "a": 0.0, "e": 0.2}],
            [{"token": "ア", "start_sec": 0.0, "end_sec": float("inf")}],
        )

    # NaN padding isolation in forward & backward for both architectures
    for arch in ("cnn_bigru", "conformer_lite"):
        cfg = ModelConfig(
            arch=arch,
            n_mels=32,
            hidden_size=32,
            num_layers=1,
            dropout=0.0,
            num_heads=4,
            conv_kernel_size=7,
        )
        model = build_model(cfg, vocab_size=tok.vocab_size)
        model.train()
        x = torch.randn(2, 40, 32, requires_grad=True)
        with torch.no_grad():
            x.data[1, 20:, :] = float("nan")
        lengths = torch.tensor([40, 20], dtype=torch.long)
        log_probs, out_lengths = model(x, lengths)
        assert torch.isfinite(log_probs[0, : out_lengths[0]]).all()
        assert torch.isfinite(log_probs[1, : out_lengths[1]]).all()
        loss = (
            log_probs[0, : out_lengths[0]].mean() + log_probs[1, : out_lengths[1]].mean()
        )
        loss.backward()
        assert torch.isfinite(x.grad[0, :40]).all()
        assert torch.isfinite(x.grad[1, :20]).all()
        for p in model.parameters():
            if p.grad is not None:
                assert torch.isfinite(p.grad).all()

    # ConformerLiteCTC dynamic positional encoding beyond initial max_len=1024
    conf_cfg = ModelConfig(
        arch="conformer_lite",
        n_mels=32,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
        num_heads=4,
        conv_kernel_size=7,
    )
    conf = build_model(conf_cfg, vocab_size=tok.vocab_size)
    conf.eval()
    with torch.no_grad():
        x_long = torch.zeros(1, 4100, 32)
        lp_long, out_len = conf(x_long, torch.tensor([4100]))
    assert lp_long.shape == (1, 1025, tok.vocab_size)
    assert int(out_len[0].item()) == 1025
    assert torch.isfinite(lp_long).all()


# ---------------------------------------------------------------------------
# Challenger 2 Specs (9–15): Server, Engine Concurrency/Checkpoints, CLI, Web JS
# ---------------------------------------------------------------------------


def test_server_extreme_corruption_bounds_no_500() -> None:
    """Extreme snr_db and gain_db return HTTP 422 (never 500) across JSON, multipart, and roundtrip."""
    app = create_app(engine=_make_tiny_engine())
    client = TestClient(app, raise_server_exceptions=False)

    wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / 16000.0).astype(np.float32)
    wav_bytes = _make_wav_bytes(wav, sr=16000)
    b64 = base64.b64encode(wav_bytes).decode("ascii")

    for corr in (
        {"snr_db": -5000.0},
        {"snr_db": 5000.0},
        {"gain_db": 1000.0},
        {"gain_db": 10000.0},
        {"gain_db": -10000.0},
    ):
        r_json = client.post("/api/transcribe", json={"audio_b64": b64, "corruption": corr})
        assert r_json.status_code == 422, f"Expected 422 for JSON transcribe {corr}, got {r_json.status_code}"

        r_tts = client.post("/api/tts-roundtrip", json={"text": "アイ", "corruption": corr})
        assert r_tts.status_code == 422, f"Expected 422 for tts-roundtrip {corr}, got {r_tts.status_code}"

    for field, val in (
        ("snr_db", "-5000"),
        ("snr_db", "5000"),
        ("gain_db", "1000"),
        ("gain_db", "10000"),
        ("gain_db", "-10000"),
    ):
        r_mp = client.post(
            "/api/transcribe",
            files={"file": ("a.wav", wav_bytes, "audio/wav")},
            data={field: val},
        )
        assert r_mp.status_code == 422, f"Expected 422 for multipart {field}={val}, got {r_mp.status_code}"


def test_server_nan_inf_and_malformed_http_payloads() -> None:
    """NaN/Infinity, invalid UTF-8, wrong Content-Type, empty WAV, and >20MiB return clean 4xx."""
    app = create_app(engine=_make_tiny_engine())
    client = TestClient(app, raise_server_exceptions=False)

    wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / 16000.0).astype(np.float32)
    wav_bytes = _make_wav_bytes(wav, sr=16000)
    b64 = base64.b64encode(wav_bytes).decode("ascii")

    # Raw JSON with NaN / Infinity / -Infinity
    for token in ("NaN", "Infinity", "-Infinity"):
        r1 = client.post(
            "/api/transcribe",
            content=f'{{"audio_b64": "{b64}", "decode_cfg": {{"temperature": {token}}}}}',
            headers={"Content-Type": "application/json"},
        )
        assert r1.status_code == 422

        r2 = client.post(
            "/api/tts-roundtrip",
            content=f'{{"text": "アイ", "hz": {token}}}',
            headers={"Content-Type": "application/json"},
        )
        assert r2.status_code == 422

        r3 = client.post(
            "/api/redecode",
            content=f'{{"utterance_id": "abc", "decode_cfg": {{"temperature": {token}}}}}',
            headers={"Content-Type": "application/json"},
        )
        assert r3.status_code == 422

    # Multipart string "nan", "inf", "-inf"
    for field in ("temperature", "snr_db", "speed"):
        for val in ("nan", "inf", "-inf"):
            r = client.post(
                "/api/transcribe",
                files={"file": ("a.wav", wav_bytes, "audio/wav")},
                data={field: val},
            )
            assert r.status_code == 422

    # Invalid UTF-8 JSON body
    r_utf8 = client.post(
        "/api/transcribe",
        content=b"\xff\xfe\xfd",
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= r_utf8.status_code < 500

    # text/plain body
    r_txt = client.post(
        "/api/transcribe",
        content=b"hello",
        headers={"Content-Type": "text/plain"},
    )
    assert 400 <= r_txt.status_code < 500

    # multipart/form-data without boundary
    r_nobound = client.post(
        "/api/transcribe",
        content=b"--abc--",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert 400 <= r_nobound.status_code < 500

    # 0-frame WAV
    empty_wav = _make_wav_bytes(np.empty(0, dtype=np.float32), sr=16000)
    r_empty = client.post(
        "/api/transcribe",
        files={"file": ("empty.wav", empty_wav, "audio/wav")},
    )
    assert r_empty.status_code == 400

    # Non-ASCII audio_b64
    r_non_ascii = client.post("/api/transcribe", json={"audio_b64": "あいうえお"})
    assert r_non_ascii.status_code == 400

    # JSON array / null body
    for body in ("[]", "null"):
        r_bad_root = client.post(
            "/api/transcribe",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert 400 <= r_bad_root.status_code < 500

    # Multipart text-field "file" (not UploadFile)
    r_text_file = client.post("/api/transcribe", files={"file": (None, "not_a_file")})
    assert r_text_file.status_code == 422

    # Oversized > 20 MiB upload -> 413
    oversized = b"0" * (20 * 1024 * 1024 + 16)
    r_big = client.post(
        "/api/transcribe",
        files={"file": ("big.wav", oversized, "audio/wav")},
    )
    assert r_big.status_code == 413


def test_server_redecode_after_lru_eviction_and_concurrent_requests() -> None:
    """LRU cache evicts oldest utterance (404) and survives concurrent direct ASREngine calls."""
    eng = _make_tiny_engine(max_cache_size=2)
    app = create_app(engine=eng)
    client = TestClient(app)

    wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / 16000.0).astype(np.float32)
    wav_bytes = _make_wav_bytes(wav, sr=16000)

    ids: list[str] = []
    for _ in range(3):
        r = client.post(
            "/api/transcribe",
            files={"file": ("a.wav", wav_bytes, "audio/wav")},
        )
        assert r.status_code == 200
        ids.append(r.json()["utterance_id"])

    # ID #1 evicted -> 404; IDs #2 and #3 still cached -> 200
    r_evicted = client.post("/api/redecode", json={"utterance_id": ids[0]})
    assert r_evicted.status_code == 404
    for active_id in ids[1:]:
        r_ok = client.post("/api/redecode", json={"utterance_id": active_id})
        assert r_ok.status_code == 200

    # Direct multi-threaded stress on ASREngine._cache
    dec_cfg = DecodeConfig(method="greedy")
    known_ids = list(ids[1:])

    def _worker(i: int) -> None:
        if i % 3 == 0:
            res = eng.transcribe(wav, sr=16000, decode_cfg=dec_cfg)
            known_ids.append(res["utterance_id"])
        elif i % 3 == 1:
            target = known_ids[-1]
            try:
                eng.redecode(target, dec_cfg)
            except KeyError:
                pass  # Expected if concurrently evicted
        else:
            info = eng.info()
            assert info["cache_size"] <= 2

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_worker, i) for i in range(30)]
        for fut in futs:
            fut.result()

    assert len(eng._cache) <= 2


def test_server_ultrashort_wav_both_architectures() -> None:
    """1-sample and 2-sample WAVs (with corruptions) return strict finite JSON 200 for both archs."""
    for arch in ("cnn_bigru", "conformer_lite"):
        app = create_app(engine=_make_tiny_engine(arch=arch))
        client = TestClient(app)
        for n_samples in (1, 2):
            wav = np.full(n_samples, 0.25, dtype=np.float32)
            wav_bytes = _make_wav_bytes(wav, sr=16000)
            b64 = base64.b64encode(wav_bytes).decode("ascii")

            for corr in (
                None,
                {"band_limit": [300.0, 3400.0], "speed": 4.0, "snr_db": 10.0, "noise_type": "pink"},
            ):
                payload: dict[str, object] = {"audio_b64": b64, "include_visuals": True}
                if corr is not None:
                    payload["corruption"] = corr
                r = client.post("/api/transcribe", json=payload)
                assert r.status_code == 200
                data = r.json()
                # Strict finite JSON check
                json.dumps(data, allow_nan=False)


def test_engine_from_checkpoint_structurally_corrupt_raises_value_error(tmp_path: Path) -> None:
    """Structurally corrupt .pt checkpoints normalize to ValueError (not TypeError/RuntimeError)."""
    eng = _make_tiny_engine()

    # 1. Non-dict model_config
    p1 = tmp_path / "bad_mcfg.pt"
    torch.save(
        {
            "model_config": "not_a_dict",
            "tokenizer": eng.tokenizer.to_dict(),
            "model_state_dict": {},
        },
        p1,
    )
    with pytest.raises(ValueError, match="Corrupt or invalid checkpoint"):
        ASREngine.from_checkpoint(p1)

    # 2. Non-dict tokenizer
    p2 = tmp_path / "bad_tok.pt"
    torch.save(
        {
            "model_config": eng.model_cfg.to_dict(),
            "tokenizer": "not_a_dict",
            "model_state_dict": eng.model.state_dict(),
        },
        p2,
    )
    with pytest.raises(ValueError, match="Corrupt or invalid checkpoint"):
        ASREngine.from_checkpoint(p2)

    # 3. Mismatched model_state_dict
    p3 = tmp_path / "bad_sd.pt"
    torch.save(
        {
            "model_config": eng.model_cfg.to_dict(),
            "tokenizer": eng.tokenizer.to_dict(),
            "model_state_dict": {"wrong_key": torch.zeros(1)},
        },
        p3,
    )
    with pytest.raises(ValueError, match="Corrupt or invalid checkpoint"):
        ASREngine.from_checkpoint(p3)


def test_cli_transcribe_tts_empty_and_unspeakable_fast_engine_fails_cleanly(tmp_path: Path) -> None:
    """CLI transcribe --tts '' and '!!!' with --engine fast exit cleanly with rc=1 and Error:."""
    ckpt = _save_tiny_checkpoint(tmp_path / "tiny.pt")
    for bad_text in ("", "   ", "!!!"):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "asr",
                "transcribe",
                "--checkpoint",
                str(ckpt),
                "--tts",
                bad_text,
                "--engine",
                "fast",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 1, f"Expected rc=1 for --tts {bad_text!r}, got {proc.returncode}"
        assert "Error:" in proc.stderr
        assert "Traceback" not in proc.stderr


def test_index_html_error_formatting_pydantic_422_and_non_json_500() -> None:
    """Extracted JS helpers from asr/web/index.html format 422 arrays and non-JSON 500s cleanly."""
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"(function formatApiError\([\s\S]*?\n  async function parseApiResponse\([\s\S]*?\n  \})",
        html,
    )
    assert m is not None, "Could not locate formatApiError / parseApiResponse in asr/web/index.html"
    helpers_js = m.group(1)

    node_script = (
        helpers_js
        + """
        (async () => {
          const pydantic422 = {
            ok: false,
            status: 422,
            text: async () => JSON.stringify({
              detail: [
                { type: "missing", loc: ["body", "text"], msg: "Field required" }
              ]
            })
          };
          let err422 = null;
          try {
            await parseApiResponse(pydantic422);
          } catch (e) {
            err422 = e;
          }
          if (!err422) throw new Error("Expected 422 error");
          if (String(err422.message).includes("[object Object]")) {
            throw new Error("422 message leaked [object Object]: " + err422.message);
          }
          if (!String(err422.message).includes("body.text") || !String(err422.message).includes("Field required")) {
            throw new Error("422 message missing field/msg: " + err422.message);
          }

          const plain500 = {
            ok: false,
            status: 500,
            text: async () => "Internal Server Error"
          };
          let err500 = null;
          try {
            await parseApiResponse(plain500);
          } catch (e) {
            err500 = e;
          }
          if (!err500) throw new Error("Expected 500 error");
          if (err500 instanceof SyntaxError) {
            throw new Error("500 plain-text threw SyntaxError");
          }
          if (!String(err500.message).includes("HTTP 500")) {
            throw new Error("500 message missing HTTP 500: " + err500.message);
          }

          const ok200 = {
            ok: true,
            status: 200,
            text: async () => JSON.stringify({ status: "ok" })
          };
          const parsed = await parseApiResponse(ok200);
          if (parsed.status !== "ok") throw new Error("200 parse failed");
          console.log("JS_OK");
        })().catch((e) => {
          console.error(e);
          process.exit(1);
        });
        """
    )

    proc = subprocess.run(
        ["node", "-e", node_script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"Node.js check failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    assert "JS_OK" in proc.stdout
