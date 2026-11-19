"""Unit and CLI integration tests for Milestone M5 (ASREngine & python -m asr)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from asr.__main__ import build_parser, main
from asr.audio import save_wav
from asr.config import AudioConfig, DecodeConfig, ModelConfig, TrainConfig
from asr.decoding import CharNgramLM
from asr.inference import ASREngine
from asr.synth_data import generate_dataset, synthesize_fast_kotoba
from asr.tokenizer import Tokenizer
from asr.train import train_asr

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class _TinyBundle:
    root: Path
    train_manifest: Path
    val_manifest: Path
    checkpoint_path: Path
    sample_wav_path: Path
    sample_wav: np.ndarray
    sample_sr: int
    sample_text: str


@pytest.fixture(scope="module")
def tiny_bundle(tmp_path_factory: pytest.TempPathFactory) -> _TinyBundle:
    """Create a tiny synthetic dataset + trained checkpoint once for the module."""
    root = tmp_path_factory.mktemp("asr_m5_bundle")
    data_dir = root / "data"
    ckpt_dir = root / "checkpoints"

    manifests = generate_dataset(
        data_dir,
        num_train=6,
        num_val=2,
        engine="fast",
        seed=123,
    )

    audio_cfg = AudioConfig()
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=audio_cfg.n_mels,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
    )
    train_cfg = TrainConfig(
        epochs=2,
        batch_size=6,
        lr=3e-3,
        seed=123,
        use_spec_augment=False,
        checkpoint_dir=str(ckpt_dir),
    )
    tokenizer = Tokenizer("kana")

    summary = train_asr(
        manifests["train"],
        manifests["val"],
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg,
        tokenizer=tokenizer,
    )

    sample_text = "オハヨウ"
    sample_wav, _moras = synthesize_fast_kotoba(
        sample_text,
        sr=audio_cfg.sample_rate,
        seed=7,
    )
    sample_wav_path = root / "sample.wav"
    save_wav(sample_wav_path, sample_wav, sr=audio_cfg.sample_rate)

    return _TinyBundle(
        root=root,
        train_manifest=manifests["train"],
        val_manifest=manifests["val"],
        checkpoint_path=Path(summary["best_checkpoint"]),
        sample_wav_path=sample_wav_path,
        sample_wav=sample_wav,
        sample_sr=audio_cfg.sample_rate,
        sample_text=sample_text,
    )


def _run_cli_subprocess(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "asr", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# ASREngine unit tests
# ---------------------------------------------------------------------------


def test_engine_from_checkpoint_and_info(tiny_bundle: _TinyBundle, tmp_path: Path) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)
    info = engine.info()

    assert info["arch"] == "cnn_bigru"
    assert info["num_parameters"] > 0
    assert info["param_count"] == info["num_parameters"]
    assert info["subsampling_factor"] == 4
    assert info["frame_stride_ms"] == pytest.approx(40.0)
    assert info["vocab_size"] == engine.tokenizer.vocab_size
    assert info["blank_id"] == 0
    assert info["tokenizer_mode"] == "kana"
    assert isinstance(info["vocab"], list) and len(info["vocab"]) == info["vocab_size"]
    assert isinstance(info["model_config"], dict)
    assert isinstance(info["audio_config"], dict)
    assert isinstance(info["tsukinami_presets"], list) and len(info["tsukinami_presets"]) > 0
    assert info["epoch"] is not None
    assert isinstance(info["history"], list) and len(info["history"]) == 2
    assert info["checkpoint"]["path"] == str(tiny_bundle.checkpoint_path)

    # Must be strictly JSON-serializable (no NaN/Inf/NumPy types)
    serialized = json.dumps(info, ensure_ascii=False, allow_nan=False)
    assert isinstance(json.loads(serialized), dict)

    # Non-finite best_val_cer should be sanitized to None
    engine.checkpoint_meta["best_val_cer"] = float("inf")
    sanitized_info = engine.info()
    assert sanitized_info["best_val_cer"] is None
    assert sanitized_info["checkpoint"]["best_val_cer"] is None
    json.dumps(sanitized_info, allow_nan=False)

    # Missing & corrupt checkpoint errors
    with pytest.raises(FileNotFoundError):
        ASREngine.from_checkpoint(tmp_path / "does_not_exist.pt")

    bad_ckpt = tmp_path / "corrupt.pt"
    bad_ckpt.write_bytes(b"not a torch checkpoint")
    with pytest.raises(ValueError):
        ASREngine.from_checkpoint(bad_ckpt)


def test_engine_transcribe_greedy_beam_and_lm(tiny_bundle: _TinyBundle) -> None:
    lm = CharNgramLM(order=2, smoothing=0.1).fit(["オハヨウ", "コンニチワ", "サクラ"])
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path, lm=lm)

    res_greedy = engine.transcribe(
        tiny_bundle.sample_wav,
        sr=tiny_bundle.sample_sr,
        decode_cfg=DecodeConfig(method="greedy"),
    )
    res_beam = engine.transcribe(
        tiny_bundle.sample_wav,
        sr=tiny_bundle.sample_sr,
        decode_cfg=DecodeConfig(method="beam", beam_width=4, lm_weight=0.2),
    )

    for res in (res_greedy, res_beam):
        assert set(res.keys()) == {
            "text",
            "hypotheses",
            "alignment",
            "rtf",
            "duration_sec",
            "utterance_id",
        }
        assert isinstance(res["text"], str)
        assert isinstance(res["hypotheses"], list) and len(res["hypotheses"]) >= 1
        for hyp in res["hypotheses"]:
            assert set(hyp.keys()) == {"text", "score", "acoustic_score", "lm_score"}
            assert isinstance(hyp["text"], str)
            assert isinstance(hyp["score"], float)
        for seg in res["alignment"]:
            assert set(seg.keys()) == {"token", "start_sec", "end_sec", "confidence"}
            assert 0.0 <= seg["start_sec"] <= seg["end_sec"]
            assert 0.0 <= seg["confidence"] <= 1.0
        assert res["duration_sec"] > 0.0
        assert res["rtf"] >= 0.0
        assert isinstance(res["utterance_id"], str) and len(res["utterance_id"]) > 0
        json.dumps(res, ensure_ascii=False, allow_nan=False)


def test_engine_transcribe_include_visuals(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)

    res_no_vis = engine.transcribe(tiny_bundle.sample_wav, sr=tiny_bundle.sample_sr)
    assert "waveform" not in res_no_vis
    assert "log_mel" not in res_no_vis
    assert "ctc_posteriors" not in res_no_vis
    assert "vad_segments" not in res_no_vis

    res_vis = engine.transcribe(
        tiny_bundle.sample_wav,
        sr=tiny_bundle.sample_sr,
        include_visuals=True,
    )
    assert isinstance(res_vis["waveform"], list) and len(res_vis["waveform"]) > 0
    assert isinstance(res_vis["log_mel"], list) and len(res_vis["log_mel"]) > 0
    assert len(res_vis["log_mel"][0]) == engine.audio_cfg.n_mels

    post = res_vis["ctc_posteriors"]
    assert isinstance(post, list) and len(post) > 0
    post_arr = np.asarray(post, dtype=np.float64)
    assert post_arr.ndim == 2
    assert post_arr.shape[0] > 0
    assert post_arr.shape[1] == engine.tokenizer.vocab_size
    assert np.isfinite(post_arr).all()
    assert float(np.min(post_arr)) >= 0.0
    assert float(np.max(post_arr)) <= 1.0
    assert np.allclose(post_arr.sum(axis=-1), np.ones(post_arr.shape[0]), atol=1e-4)

    assert isinstance(res_vis["vad_segments"], list)
    for seg in res_vis["vad_segments"]:
        assert isinstance(seg, list) and len(seg) == 2
        assert seg[0] <= seg[1]

    json.dumps(res_vis, ensure_ascii=False, allow_nan=False)


def test_engine_redecode_fast_and_errors(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)
    base = engine.transcribe(
        tiny_bundle.sample_wav,
        sr=tiny_bundle.sample_sr,
        decode_cfg=DecodeConfig(method="greedy"),
    )
    utt_id = base["utterance_id"]

    # Warm-up once, then measure fast cached redecode
    _ = engine.redecode(utt_id, DecodeConfig(method="greedy", blank_bias=-0.5))

    t0 = time.perf_counter()
    re_greedy = engine.redecode(utt_id, DecodeConfig(method="greedy", temperature=0.8))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert set(re_greedy.keys()) == {
        "text",
        "hypotheses",
        "alignment",
        "utterance_id",
        "duration_sec",
        "decode_ms",
    }
    assert re_greedy["utterance_id"] == utt_id
    assert re_greedy["duration_sec"] == pytest.approx(base["duration_sec"])
    assert re_greedy["decode_ms"] < 10.0
    assert elapsed_ms < 20.0
    json.dumps(re_greedy, ensure_ascii=False, allow_nan=False)

    re_beam = engine.redecode(utt_id, DecodeConfig(method="beam", beam_width=4))
    assert re_beam["utterance_id"] == utt_id
    assert re_beam["decode_ms"] < 50.0
    json.dumps(re_beam, ensure_ascii=False, allow_nan=False)

    with pytest.raises(KeyError):
        engine.redecode("nonexistent-utt-id", DecodeConfig(method="greedy"))

    with pytest.raises(TypeError):
        engine.redecode(utt_id, {"method": "greedy"})  # type: ignore[arg-type]


def test_engine_lru_cache_eviction(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path, max_cache_size=2)
    cfg = DecodeConfig(method="greedy")

    id1 = engine.transcribe(tiny_bundle.sample_wav, sr=tiny_bundle.sample_sr, decode_cfg=cfg)["utterance_id"]
    id2 = engine.transcribe(tiny_bundle.sample_wav, sr=tiny_bundle.sample_sr, decode_cfg=cfg)["utterance_id"]

    # Promote id1 to MRU via redecode
    engine.redecode(id1, cfg)

    # Inserting id3 should evict id2 (LRU), keeping id1 and id3
    id3 = engine.transcribe(tiny_bundle.sample_wav, sr=tiny_bundle.sample_sr, decode_cfg=cfg)["utterance_id"]

    assert engine.info()["cache_size"] == 2
    with pytest.raises(KeyError):
        engine.redecode(id2, cfg)
    assert engine.redecode(id1, cfg)["utterance_id"] == id1
    assert engine.redecode(id3, cfg)["utterance_id"] == id3


def test_engine_resampling_stereo_and_nan_sanitization(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)

    # 44.1 kHz stereo waveform with injected NaN/Inf
    t = np.linspace(0.0, 0.5, 22050, endpoint=False, dtype=np.float32)
    mono_44k = 0.2 * np.sin(2.0 * np.pi * 440.0 * t).astype(np.float32)
    mono_44k[10] = np.nan
    mono_44k[20] = np.inf
    mono_44k[30] = -np.inf
    stereo_44k = np.stack([mono_44k, mono_44k * 0.5], axis=-1)

    res = engine.transcribe(
        stereo_44k,
        sr=44100,
        decode_cfg=DecodeConfig(method="greedy"),
        include_visuals=True,
    )
    assert res["duration_sec"] == pytest.approx(0.5, abs=0.02)
    json.dumps(res, ensure_ascii=False, allow_nan=False)


def test_engine_empty_short_and_invalid_inputs(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)
    cfg = DecodeConfig(method="greedy")

    # Empty audio
    empty_res = engine.transcribe(
        np.zeros(0, dtype=np.float32),
        sr=16000,
        decode_cfg=cfg,
        include_visuals=True,
    )
    assert empty_res["text"] == ""
    assert empty_res["duration_sec"] == 0.0
    assert empty_res["rtf"] == 0.0
    assert empty_res["alignment"] == []
    assert empty_res["waveform"] == []
    assert empty_res["log_mel"] == []
    assert empty_res["ctc_posteriors"] == []
    assert empty_res["vad_segments"] == []
    json.dumps(empty_res, ensure_ascii=False, allow_nan=False)

    # Cached empty utterance should still redecode cleanly
    re_empty = engine.redecode(empty_res["utterance_id"], DecodeConfig(method="beam", beam_width=4))
    assert re_empty["text"] == ""
    assert re_empty["alignment"] == []

    # Very short audio (10 samples < win_length=400)
    short_res = engine.transcribe(
        np.zeros(10, dtype=np.float32),
        sr=16000,
        decode_cfg=cfg,
        include_visuals=True,
    )
    assert short_res["duration_sec"] == pytest.approx(10 / 16000.0)
    assert isinstance(short_res["ctc_posteriors"], list)
    if short_res["ctc_posteriors"]:
        short_post = np.asarray(short_res["ctc_posteriors"], dtype=np.float64)
        assert short_post.ndim == 2
        assert short_post.shape[1] == engine.tokenizer.vocab_size
        assert np.isfinite(short_post).all()
        assert float(np.min(short_post)) >= 0.0 and float(np.max(short_post)) <= 1.0
        assert np.allclose(short_post.sum(axis=-1), np.ones(short_post.shape[0]), atol=1e-4)
    json.dumps(short_res, ensure_ascii=False, allow_nan=False)

    # Invalid inputs
    with pytest.raises(ValueError):
        engine.transcribe(tiny_bundle.sample_wav, sr=0)
    with pytest.raises(ValueError):
        engine.transcribe(tiny_bundle.sample_wav, sr=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        engine.transcribe(np.zeros((2, 2, 2), dtype=np.float32), sr=16000)
    with pytest.raises(ValueError):
        engine.transcribe(np.zeros((10, 0), dtype=np.float32), sr=16000)
    with pytest.raises(TypeError):
        engine.transcribe(tiny_bundle.sample_wav, sr=16000, decode_cfg="greedy")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ASREngine(
            engine.model,
            engine.audio_cfg,
            engine.model_cfg,
            engine.tokenizer,
            max_cache_size=0,
        )


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_help_and_lazy_serve_help() -> None:
    proc_help = _run_cli_subprocess("--help")
    assert proc_help.returncode == 0
    for cmd in ("demo", "generate", "train", "eval", "transcribe", "serve"):
        assert cmd in proc_help.stdout

    proc_serve = _run_cli_subprocess("serve", "--help")
    assert proc_serve.returncode == 0
    assert "--checkpoint" in proc_serve.stdout
    assert "--host" in proc_serve.stdout
    assert "--port" in proc_serve.stdout

    parser = build_parser()
    assert parser is not None


def test_cli_generate_and_train(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gen_dir = tmp_path / "gen_data"
    rc_gen = main([
        "generate",
        "--out-dir", str(gen_dir),
        "--num-train", "4",
        "--num-val", "2",
        "--engine", "fast",
        "--seed", "11",
    ])
    assert rc_gen == 0
    assert (gen_dir / "train.jsonl").exists()
    assert (gen_dir / "val.jsonl").exists()
    assert len((gen_dir / "train.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 4
    assert len((gen_dir / "val.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 2

    ckpt_dir = tmp_path / "trained_ckpts"
    rc_train = main([
        "train",
        "--train-manifest", str(gen_dir / "train.jsonl"),
        "--val-manifest", str(gen_dir / "val.jsonl"),
        "--out-dir", str(ckpt_dir),
        "--arch", "cnn_bigru",
        "--epochs", "1",
        "--batch-size", "4",
        "--hidden-size", "32",
        "--num-layers", "1",
        "--no-spec-augment",
        "--seed", "11",
    ])
    assert rc_train == 0
    assert (ckpt_dir / "best.pt").exists()
    assert (ckpt_dir / "latest.pt").exists()
    out = capsys.readouterr().out
    assert "Training complete" in out


def test_cli_eval_text_and_json(tiny_bundle: _TinyBundle, capsys: pytest.CaptureFixture[str]) -> None:
    rc_text = main([
        "eval",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--manifest", str(tiny_bundle.val_manifest),
        "--method", "greedy",
    ])
    assert rc_text == 0
    out_text = capsys.readouterr().out
    assert "CER:" in out_text
    assert "MER:" in out_text

    rc_json = main([
        "eval",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--manifest", str(tiny_bundle.val_manifest),
        "--method", "beam",
        "--beam-width", "4",
        "--json",
    ])
    assert rc_json == 0
    raw_json = capsys.readouterr().out.strip()
    payload = json.loads(raw_json)
    assert payload["num_utterances"] == 2
    assert "cer" in payload
    assert "mer" in payload
    assert "wer" in payload
    assert "confusion_pairs" in payload
    assert "mean_rtf" in payload


def test_cli_transcribe_wav_and_tts(tiny_bundle: _TinyBundle, capsys: pytest.CaptureFixture[str]) -> None:
    # --wav text mode (in-process)
    rc_wav = main([
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--wav", str(tiny_bundle.sample_wav_path),
        "--method", "greedy",
    ])
    assert rc_wav == 0
    assert "Predicted" in capsys.readouterr().out

    # --wav --json mode (real subprocess)
    proc_wav = _run_cli_subprocess(
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--wav", str(tiny_bundle.sample_wav_path),
        "--method", "beam",
        "--beam-width", "4",
        "--json",
    )
    assert proc_wav.returncode == 0, proc_wav.stderr
    wav_payload = json.loads(proc_wav.stdout.strip())
    assert wav_payload["source"] == "wav"
    assert "text" in wav_payload
    assert "hypotheses" in wav_payload
    assert "alignment" in wav_payload
    assert "utterance_id" in wav_payload

    # --tts fast engine --json
    rc_tts_fast = main([
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--tts", "アイウ",
        "--engine", "fast",
        "--method", "greedy",
        "--json",
    ])
    assert rc_tts_fast == 0
    fast_payload = json.loads(capsys.readouterr().out.strip())
    assert fast_payload["source"] == "tts"
    assert fast_payload["reference_text"] == "アイウ"
    assert "cer" in fast_payload

    # --tts tsukinami engine --json (short 2-mora phrase for speed)
    rc_tts_tsuki = main([
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--tts", "アイ",
        "--engine", "tsukinami",
        "--preset", "default",
        "--method", "greedy",
        "--json",
    ])
    assert rc_tts_tsuki == 0
    tsuki_payload = json.loads(capsys.readouterr().out.strip())
    assert tsuki_payload["source"] == "tts"
    assert tsuki_payload["tts_engine"] == "tsukinami"
    assert tsuki_payload["reference_text"] == "アイ"


def test_cli_demo_end_to_end_subprocess(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo_run"
    proc = _run_cli_subprocess(
        "demo",
        "--out-dir", str(demo_dir),
        "--epochs", "1",
        "--num-train", "4",
        "--num-val", "2",
        "--arch", "cnn_bigru",
        "--seed", "42",
    )
    assert proc.returncode == 0, proc.stderr
    assert (demo_dir / "best.pt").exists()
    assert (demo_dir / "data" / "train.jsonl").exists()
    assert (demo_dir / "data" / "val.jsonl").exists()
    assert "Val CER:" in proc.stdout
    assert "Reference" in proc.stdout


def test_cli_error_paths(
    tiny_bundle: _TinyBundle,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Missing checkpoint
    rc = main([
        "transcribe",
        "--checkpoint", str(tmp_path / "missing.pt"),
        "--wav", str(tiny_bundle.sample_wav_path),
    ])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Corrupt checkpoint
    bad_ckpt = tmp_path / "bad.pt"
    bad_ckpt.write_bytes(b"corrupt")
    rc = main([
        "transcribe",
        "--checkpoint", str(bad_ckpt),
        "--wav", str(tiny_bundle.sample_wav_path),
    ])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Missing WAV
    rc = main([
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--wav", str(tmp_path / "missing.wav"),
    ])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Corrupt WAV
    bad_wav = tmp_path / "bad.wav"
    bad_wav.write_bytes(b"RIFF0000WAVEcorrupt")
    rc = main([
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--wav", str(bad_wav),
    ])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Unknown TTS preset
    rc = main([
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--tts", "アイ",
        "--engine", "tsukinami",
        "--preset", "nonexistent_preset_xyz",
    ])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Invalid numeric flag
    rc = main([
        "demo",
        "--out-dir", str(tmp_path / "bad_demo"),
        "--epochs", "0",
    ])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Invalid port for serve
    rc = main(["serve", "--port", "99999"])
    assert rc != 0
    assert capsys.readouterr().err.strip() != ""

    # Mutually exclusive --wav and --tts -> argparse exit code 2
    proc_both = _run_cli_subprocess(
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
        "--wav", str(tiny_bundle.sample_wav_path),
        "--tts", "アイ",
    )
    assert proc_both.returncode == 2
    assert proc_both.stderr.strip() != ""

    # Neither --wav nor --tts -> argparse exit code 2
    proc_neither = _run_cli_subprocess(
        "transcribe",
        "--checkpoint", str(tiny_bundle.checkpoint_path),
    )
    assert proc_neither.returncode == 2
    assert proc_neither.stderr.strip() != ""


def test_engine_channels_first_stereo_and_zero_channel(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)
    cfg = DecodeConfig(method="greedy")

    t = np.linspace(0.0, 1.0, 16000, endpoint=False, dtype=np.float32)
    sine = (0.3 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)

    stereo_cf = np.stack([sine, sine * 0.5], axis=0)   # (2, 16000) channels-first
    stereo_sf = np.stack([sine, sine * 0.5], axis=-1)  # (16000, 2) samples-first

    res_cf = engine.transcribe(stereo_cf, sr=16000, decode_cfg=cfg, include_visuals=True)
    res_sf = engine.transcribe(stereo_sf, sr=16000, decode_cfg=cfg, include_visuals=True)

    assert res_cf["duration_sec"] == pytest.approx(1.0)
    assert res_sf["duration_sec"] == pytest.approx(1.0)
    assert res_cf["text"] == res_sf["text"]
    assert res_cf["waveform"] == res_sf["waveform"]

    with pytest.raises(ValueError):
        engine.transcribe(np.zeros((16000, 0), dtype=np.float32), sr=16000)


def test_engine_integer_pcm_normalization(tiny_bundle: _TinyBundle) -> None:
    engine = ASREngine.from_checkpoint(tiny_bundle.checkpoint_path)
    cfg = DecodeConfig(method="greedy")

    # 0.3-amplitude sine in int16 should normalize cleanly into [-1.0, 1.0]
    t = np.linspace(0.0, 1.0, 16000, endpoint=False, dtype=np.float32)
    sine_f32 = (0.3 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    sine_i16 = np.round(sine_f32 * 32767.0).astype(np.int16)

    res_sine = engine.transcribe(sine_i16, sr=16000, decode_cfg=cfg, include_visuals=True)
    wf_sine = np.asarray(res_sine["waveform"], dtype=np.float32)
    assert wf_sine.size > 0
    assert float(np.max(np.abs(wf_sine))) <= 1.0
    assert float(np.max(np.abs(wf_sine))) == pytest.approx(0.3, abs=0.01)

    # -50 dBFS quiet noise in int16 must match float32 VAD and amplitude range
    rng = np.random.default_rng(0)
    quiet_f32 = (rng.standard_normal(16000) * 0.003).astype(np.float32)
    quiet_i16 = np.round(quiet_f32 * 32767.0).astype(np.int16)

    res_f32 = engine.transcribe(quiet_f32, sr=16000, decode_cfg=cfg, include_visuals=True)
    res_i16 = engine.transcribe(quiet_i16, sr=16000, decode_cfg=cfg, include_visuals=True)

    assert res_i16["vad_segments"] == res_f32["vad_segments"] == []
    wf_f32_max = float(np.max(np.abs(res_f32["waveform"])))
    wf_i16_max = float(np.max(np.abs(res_i16["waveform"])))
    assert wf_i16_max <= 1.0
    assert wf_i16_max == pytest.approx(wf_f32_max, abs=1e-3)

    # Unsigned 8-bit PCM should center around 128 and normalize into [-1.0, 1.0]
    sine_u8 = np.clip(np.round((sine_f32 + 1.0) * 128.0), 0, 255).astype(np.uint8)
    res_u8 = engine.transcribe(sine_u8, sr=16000, decode_cfg=cfg, include_visuals=True)
    wf_u8 = np.asarray(res_u8["waveform"], dtype=np.float32)
    assert float(np.max(np.abs(wf_u8))) <= 1.0
    assert float(np.max(np.abs(wf_u8))) == pytest.approx(0.3, abs=0.02)


def test_corrupt_pickle_frame_checkpoint(tiny_bundle: _TinyBundle, tmp_path: Path) -> None:
    bad_frame_ckpt = tmp_path / "bad_frame.pt"
    bad_frame_ckpt.write_bytes(b"\x80\x04\x95\xff\xff\xff\xff\xff\xff\xff\xff" + b"\x00" * 32)

    with pytest.raises(ValueError, match="Corrupt or invalid checkpoint"):
        ASREngine.from_checkpoint(bad_frame_ckpt)

    proc = _run_cli_subprocess(
        "eval",
        "--checkpoint", str(bad_frame_ckpt),
        "--manifest", str(tiny_bundle.val_manifest),
    )
    assert proc.returncode == 1
    assert "Error:" in proc.stderr
    assert "Traceback" not in proc.stderr

