"""Tier 4 E2E Tests: Real-World Multi-Feature Application Scenarios.

Exercises 9 realistic end-user workloads across the full Tsukinami ASR system,
plus non-regression verification of the original pure-Python tsukinami TTS.
"""

from __future__ import annotations

import base64
import json
import re
import statistics
import sys
import time
import wave
from pathlib import Path

import pytest


def test_t4_scenario1_one_command_cpu_quickstart_demo(run_cli, tmp_path: Path):
    """Scenario 1: New user runs one-command `python -m asr demo` on CPU."""
    from asr.inference import ASREngine
    from asr.synth_data import synthesize_fast_kotoba

    demo_dir = tmp_path / "demo_run"
    proc = run_cli(
        [
            "demo",
            "--out-dir", str(demo_dir),
            "--epochs", "2",
            "--num-train", "16",
            "--arch", "cnn_bigru",
        ],
        timeout=180,
    )
    assert proc.returncode == 0, f"demo failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    train_manifests = list(demo_dir.rglob("train.jsonl"))
    val_manifests = list(demo_dir.rglob("val.jsonl"))
    assert len(train_manifests) >= 1 and len(val_manifests) >= 1

    ckpts = list(demo_dir.rglob("best.pt")) or list(demo_dir.rglob("latest.pt"))
    assert len(ckpts) >= 1, f"Expected checkpoint under {demo_dir}"

    engine = ASREngine.from_checkpoint(ckpts[0])
    wav, _ = synthesize_fast_kotoba("おはよう", sr=16000, seed=10)
    res = engine.transcribe(wav, sr=16000)
    assert isinstance(res["text"], str) and float(res["duration_sec"]) > 0.0

    combined = (proc.stdout + proc.stderr).lower()
    assert "cer" in combined


def test_t4_scenario2_multi_preset_tsukinami_roundtrip_and_alignment(
    tiny_engine,
    tsukinami_cache_dir: Path,
):
    """Scenario 2: Multi-preset authentic tsukinami TTS -> ASR round-trip & alignment comparison."""
    import numpy as np
    from asr.config import DecodeConfig
    from asr.metrics import alignment_boundary_error, compute_cer, compute_mer
    from asr.synth_data import synthesize_tsukinami

    presets = ("default", "ossan", "robot", "whisper", "chibi")
    text = "あか"
    ref = "アカ"
    wavs: dict[str, np.ndarray] = {}

    for preset in presets:
        wav, gt_moras = synthesize_tsukinami(text, preset=preset, sr=16000, cache_dir=tsukinami_cache_dir)
        assert wav.ndim == 1 and wav.dtype == np.float32 and np.isfinite(wav).all()
        assert len(wav) / 16000.0 > 0.2
        assert float(np.sqrt(np.mean(wav ** 2))) > 1e-4
        wavs[preset] = wav

        res = tiny_engine.transcribe(
            wav,
            sr=16000,
            decode_cfg=DecodeConfig(method="beam", beam_width=4),
            include_visuals=True,
        )
        cer = compute_cer([ref], [res["text"]])
        mer = compute_mer([ref], [res["text"]])
        abe = alignment_boundary_error(gt_moras, res["alignment"])

        assert float(cer["cer"]) >= 0.0 and np.isfinite(cer["cer"])
        assert float(mer["mer"]) >= 0.0 and np.isfinite(mer["mer"])
        assert float(res["rtf"]) >= 0.0 and np.isfinite(res["rtf"])
        assert isinstance(abe, dict)

    # Distinct presets must produce acoustically distinct waveforms
    for i in range(len(presets)):
        for j in range(i + 1, len(presets)):
            w1, w2 = wavs[presets[i]], wavs[presets[j]]
            n = min(len(w1), len(w2))
            assert float(np.mean(np.abs(w1[:n] - w2[:n]))) > 1e-4


def test_t4_scenario3_noisy_and_telephone_degradation_experiment(tiny_engine):
    """Scenario 3: Clean vs white 5dB vs pink 10dB vs telephone band-limit degradation study."""
    import numpy as np
    from asr.audio import apply_corruption, detect_vad
    from asr.config import AudioConfig
    from asr.features import extract_log_mel
    from asr.metrics import compute_cer
    from asr.synth_data import synthesize_fast_kotoba

    ref = "ワタシ、ニホンゴ"
    clean, _ = synthesize_fast_kotoba(ref, sr=16000, seed=42)
    conditions = {
        "clean": clean,
        "white_5db": apply_corruption(clean, 16000, snr_db=5.0, noise_type="white", seed=42),
        "pink_10db": apply_corruption(clean, 16000, snr_db=10.0, noise_type="pink", seed=42),
        "telephone": apply_corruption(clean, 16000, band_limit=(300.0, 3400.0)),
    }

    cfg_raw = AudioConfig(cmvn=False)
    cfg_norm = AudioConfig(cmvn=True)
    raw_mels: dict[str, np.ndarray] = {}

    for name, wav in conditions.items():
        mel_raw = extract_log_mel(wav, cfg_raw)
        mel_norm = extract_log_mel(wav, cfg_norm)
        segs = detect_vad(wav, sr=16000)
        res = tiny_engine.transcribe(wav, sr=16000, include_visuals=True)
        cer = compute_cer([ref], [res["text"]])

        assert np.isfinite(mel_raw).all() and np.isfinite(mel_norm).all()
        assert isinstance(segs, list)
        assert np.isfinite(np.asarray(res["ctc_posteriors"], dtype=np.float32)).all()
        assert np.isfinite(cer["cer"]) and cer["cer"] >= 0.0
        raw_mels[name] = mel_raw

    for degraded in ("white_5db", "pink_10db", "telephone"):
        t_min = min(raw_mels["clean"].shape[0], raw_mels[degraded].shape[0])
        assert float(np.mean(np.abs(raw_mels["clean"][:t_min] - raw_mels[degraded][:t_min]))) > 1e-2

    # Telephone band-limit (300-3400 Hz) must attenuate high-frequency Mel bins (> ~4 kHz)
    assert float(np.mean(raw_mels["telephone"][:, -12:])) < float(np.mean(raw_mels["clean"][:, -12:]))


def test_t4_scenario4_interactive_web_playground_full_session(api_client, helpers):
    """Scenario 4: Full interactive web playground session via HTTP API."""
    # 1. Load zero-CDN HTML UI
    r_root = api_client.get("/")
    assert r_root.status_code == 200
    assert "text/html" in r_root.headers.get("content-type", "").lower()
    assert "<canvas" in r_root.text.lower()
    assert not re.search(r'<script[^>]+src=["\'](?:https?:)?//', r_root.text, re.IGNORECASE)
    assert not re.search(r'<link[^>]+href=["\'](?:https?:)?//', r_root.text, re.IGNORECASE)

    # 2. Check health & model info
    assert api_client.get("/api/health").json() == {"status": "ok", "model_loaded": True}
    r_info = api_client.get("/api/info")
    assert r_info.status_code == 200 and isinstance(r_info.json(), dict)

    # 3. TTS -> ASR round-trip
    r_rt = api_client.post(
        "/api/tts-roundtrip",
        json={
            "text": "おはよう",
            "preset": "default",
            "synth_engine": "fast",
            "decode_cfg": {"method": "beam", "beam_width": 4},
        },
    )
    assert r_rt.status_code == 200, r_rt.text
    rt_json = r_rt.json()
    wav_bytes = base64.b64decode(rt_json["audio_b64"])
    assert wav_bytes[:4] == b"RIFF"
    utt_id = helpers.extract_transcribe_payload(rt_json)["utterance_id"]

    # 4. Interactive decoding slider sweep via /api/redecode
    sweep_cfgs = [
        {"method": "greedy", "temperature": 1.0, "blank_bias": 0.0},
        {"method": "beam", "beam_width": 4, "temperature": 0.8, "blank_bias": 0.0},
        {"method": "beam", "beam_width": 4, "temperature": 1.5, "blank_bias": -0.5},
        {"method": "beam", "beam_width": 4, "temperature": 1.0, "blank_bias": 0.8},
    ]
    for cfg in sweep_cfgs:
        r_rd = api_client.post("/api/redecode", json={"utterance_id": utt_id, "decode_cfg": cfg})
        assert r_rd.status_code == 200, r_rd.text
        d_rd = r_rd.json()
        assert "text" in d_rd and "hypotheses" in d_rd

    # 5. Re-upload synthesized WAV via /api/transcribe multipart endpoint
    r_up = api_client.post("/api/transcribe", files={"file": ("roundtrip.wav", wav_bytes, "audio/wav")})
    assert r_up.status_code == 200, r_up.text
    up_json = r_up.json()
    for key in ("text", "utterance_id", "rtf", "duration_sec", "waveform", "log_mel", "ctc_posteriors", "vad_segments"):
        assert key in up_json


def test_t4_scenario5_custom_wav_folder_tier3_corpus_workflow(tmp_path: Path):
    """Scenario 5: User brings custom WAV folder (incl. 22.05 kHz), builds manifest, trains, evaluates."""
    from asr.audio import load_wav, save_wav
    from asr.config import AudioConfig, ModelConfig, TrainConfig
    from asr.dataset import ASRManifestDataset, build_manifest_from_wav_dir, collate_asr_batch
    from asr.inference import ASREngine
    from asr.metrics import compute_cer, compute_wer
    from asr.synth_data import synthesize_fast_kotoba
    from asr.tokenizer import Tokenizer
    from asr.train import train_asr

    train_dir = tmp_path / "train_wavs"
    val_dir = tmp_path / "val_wavs"
    train_texts = ["アイウ", "オハヨウ", "サクラ", "ニホンゴ", "コンニチハ", "テスト"]
    val_texts = ["アイウ", "サクラ"]

    train_map: dict[str, str] = {}
    for idx, txt in enumerate(train_texts):
        sr = 22050 if idx == 0 else 16000
        wav, _ = synthesize_fast_kotoba(txt, sr=sr, seed=100 + idx)
        fname = f"tr_{idx}.wav"
        save_wav(train_dir / fname, wav, sr=sr)
        train_map[fname] = txt

    val_map: dict[str, str] = {}
    for idx, txt in enumerate(val_texts):
        wav, _ = synthesize_fast_kotoba(txt, sr=16000, seed=200 + idx)
        fname = f"va_{idx}.wav"
        save_wav(val_dir / fname, wav, sr=16000)
        val_map[fname] = txt

    tr_manifest = build_manifest_from_wav_dir(train_dir, train_map, tmp_path / "train.jsonl")
    va_manifest = build_manifest_from_wav_dir(val_dir, val_map, tmp_path / "val.jsonl")

    audio_cfg = AudioConfig()
    tok = Tokenizer("kana")
    ds = ASRManifestDataset(tr_manifest, audio_cfg, tok)
    batch = collate_asr_batch([ds[0], ds[1]])
    assert batch["feats"].shape[0] == 2 and batch["feats"].shape[2] == audio_cfg.n_mels

    ckpt_dir = tmp_path / "custom_ckpt"
    train_asr(
        tr_manifest,
        va_manifest,
        audio_cfg=audio_cfg,
        model_cfg=ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0),
        train_cfg=TrainConfig(epochs=2, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(ckpt_dir)),
        tokenizer=tok,
    )
    assert (ckpt_dir / "best.pt").is_file()

    engine = ASREngine.from_checkpoint(ckpt_dir / "best.pt")
    hyps = []
    for fname in val_map:
        wav, sr = load_wav(val_dir / fname, target_sr=16000)
        hyps.append(engine.transcribe(wav, sr=sr)["text"])

    refs = list(val_map.values())
    cer = compute_cer(refs, hyps)
    wer = compute_wer(refs, hyps)
    assert cer["ref_len"] > 0 and cer["cer"] >= 0.0
    assert wer["wer"] >= 0.0


def test_t4_scenario6_architecture_comparison_and_checkpoint_resume(
    tmp_path: Path,
    tiny_fast_dataset: dict[str, Path],
):
    """Scenario 6: Compare cnn_bigru vs conformer_lite with checkpoint resume & ASREngine inference."""
    from asr.config import AudioConfig, ModelConfig, TrainConfig
    from asr.inference import ASREngine
    from asr.synth_data import synthesize_fast_kotoba
    from asr.tokenizer import Tokenizer
    from asr.train import load_checkpoint, train_asr

    audio_cfg = AudioConfig()
    tok = Tokenizer("kana")
    probe_wav, _ = synthesize_fast_kotoba("おはよう", sr=16000, seed=77)

    for arch in ("cnn_bigru", "conformer_lite"):
        cdir = tmp_path / f"cmp_{arch}"
        mcfg = ModelConfig(
            arch=arch,
            n_mels=audio_cfg.n_mels,
            hidden_size=32,
            num_layers=1,
            num_heads=4,
            conv_kernel_size=7,
            dropout=0.0,
        )
        train_asr(
            tiny_fast_dataset["train"],
            tiny_fast_dataset["val"],
            audio_cfg=audio_cfg,
            model_cfg=mcfg,
            train_cfg=TrainConfig(epochs=1, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
            tokenizer=tok,
        )
        train_asr(
            tiny_fast_dataset["train"],
            tiny_fast_dataset["val"],
            audio_cfg=audio_cfg,
            model_cfg=mcfg,
            train_cfg=TrainConfig(epochs=2, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
            tokenizer=tok,
            resume_from=cdir / "latest.pt",
        )
        ckpt = load_checkpoint(cdir / "latest.pt", device="cpu")
        assert int(ckpt["epoch"]) >= 2

        eng = ASREngine.from_checkpoint(cdir / "best.pt")
        res = eng.transcribe(probe_wav, sr=16000)
        assert isinstance(res["text"], str) and float(res["rtf"]) >= 0.0


def test_t4_scenario7_decoding_strategy_and_ngram_lm_study(tiny_checkpoint: dict):
    """Scenario 7: Fit CharNgramLM and compare Greedy vs Beam vs Beam+LM with CER/MER/WER/confusion."""
    from asr.audio import load_wav
    from asr.config import DecodeConfig
    from asr.decoding import CharNgramLM
    from asr.inference import ASREngine
    from asr.metrics import compute_cer, compute_mer, compute_wer, confusion_pairs

    corpus = [
        "ワタシ、ニホンゴ",
        "オハヨウ",
        "コンニチハ",
        "サクラ",
        "アイウエオ",
        "カキクケコ",
    ] * 3
    lm = CharNgramLM(order=3, smoothing=0.1)
    lm.fit(corpus)
    lm_restored = CharNgramLM.from_dict(lm.to_dict())
    assert lm_restored.score_next("オハ", "ヨ") == pytest.approx(lm.score_next("オハ", "ヨ"))

    engine = ASREngine.from_checkpoint(tiny_checkpoint["best_pt"], lm=lm_restored)
    val_rows = [
        json.loads(ln)
        for ln in tiny_checkpoint["val_manifest"].read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    refs = [r["text"] for r in val_rows]
    wavs = [load_wav(r["audio_path"], target_sr=16000)[0] for r in val_rows]

    strategies = [
        DecodeConfig(method="greedy"),
        DecodeConfig(method="beam", beam_width=6, lm_weight=0.0),
        DecodeConfig(method="beam", beam_width=6, lm_weight=0.5, insertion_bonus=0.2),
    ]
    for cfg in strategies:
        hyps = [engine.transcribe(w, sr=16000, decode_cfg=cfg)["text"] for w in wavs]
        cer = compute_cer(refs, hyps)
        mer = compute_mer(refs, hyps)
        wer = compute_wer(refs, hyps)
        pairs = confusion_pairs(refs, hyps, top_k=5)

        assert cer["ref_len"] > 0 and cer["cer"] >= 0.0
        assert isinstance(cer["substitutions"], int)
        assert isinstance(cer["deletions"], int)
        assert isinstance(cer["insertions"], int)
        assert mer["mer"] >= 0.0 and wer["wer"] >= 0.0
        assert isinstance(pairs, list)
        for i in range(len(pairs) - 1):
            assert pairs[i][2] >= pairs[i + 1][2]


def test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep(tiny_engine):
    """Scenario 8: Live visual payloads + <10 ms cached greedy redecode parameter sweep."""
    import numpy as np
    from asr.config import DecodeConfig
    from asr.synth_data import synthesize_fast_kotoba

    wav, _ = synthesize_fast_kotoba("オハヨウ", sr=16000, seed=12)
    res = tiny_engine.transcribe(wav, sr=16000, include_visuals=True)
    utt_id = res["utterance_id"]

    wf = np.asarray(res["waveform"], dtype=np.float32)
    mel = np.asarray(res["log_mel"], dtype=np.float32)
    post = np.asarray(res["ctc_posteriors"], dtype=np.float32)
    assert wf.size > 0 and np.isfinite(wf).all()
    assert mel.ndim == 2 and mel.shape[0] > 0 and np.isfinite(mel).all()
    assert post.ndim == 2 and post.shape[0] > 0 and np.isfinite(post).all()
    assert float(np.min(post)) >= -1e-4 and float(np.max(post)) <= 1.0 + 1e-4
    assert np.allclose(post.sum(axis=-1), np.ones(post.shape[0]), atol=1e-2)
    assert isinstance(res["vad_segments"], list)

    # Warm up cache path
    tiny_engine.redecode(utt_id, DecodeConfig(method="greedy"))

    greedy_times_ms: list[float] = []
    for temp in (0.5, 1.0, 2.0):
        for bb in (-1.0, 0.0, 1.0):
            t0 = time.perf_counter()
            r = tiny_engine.redecode(utt_id, DecodeConfig(method="greedy", temperature=temp, blank_bias=bb))
            greedy_times_ms.append((time.perf_counter() - t0) * 1000.0)
            assert isinstance(r["text"], str) and isinstance(r["hypotheses"], list)

    assert statistics.median(greedy_times_ms) < 10.0, f"Greedy redecode median {statistics.median(greedy_times_ms):.2f} ms >= 10 ms"

    beam_times_ms: list[float] = []
    for bw in (1, 4):
        for temp in (0.7, 1.3):
            for bb in (-0.5, 0.5):
                t0 = time.perf_counter()
                r = tiny_engine.redecode(utt_id, DecodeConfig(method="beam", beam_width=bw, temperature=temp, blank_bias=bb))
                beam_times_ms.append((time.perf_counter() - t0) * 1000.0)
                assert isinstance(r["text"], str) and isinstance(r["hypotheses"], list)

    assert statistics.median(beam_times_ms) < 50.0


def test_t4_scenario9_existing_tsukinami_tts_non_regression(repo_root: Path, tmp_path: Path):
    """Scenario 9: Verify original pure-Python tsukinami TTS modules remain completely intact."""
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    import accent
    import carve
    import kotoba
    import yomu

    assert kotoba.to_kata("わたし、にほんご") == "ワタシ、ニホンゴ"
    assert kotoba.split_moras("きょうも") == ["キョ", "ウ", "モ"]
    tracks = kotoba.tracks_from_kana("おはよう")
    assert tracks["fp_ms"] == pytest.approx(5.0)
    assert tracks["n"] > 0
    for key in ("F1", "F2", "F3", "voiced", "moras"):
        assert len(tracks[key]) > 0

    clean, phr = accent.annotate("おはよう、きょ'うも")
    r = kotoba.tracks_from_kana(clean)
    f0 = accent.f0_rule(r["moras"], r["n"], r["voiced"], phrases=phr, **accent.NORMAL)
    assert len(f0) == r["n"]
    voiced_f0 = [hz for hz, v in zip(f0, r["voiced"]) if v > 0.5]
    assert len(voiced_f0) > 0 and min(voiced_f0) > 50.0

    assert {"default", "ossan", "robot", "horror", "whisper", "chibi"}.issubset(yomu.PRESETS.keys())
    prm = dict(yomu.PRESETS["default"], uta_trance=False, uta_choir=False)
    rc = yomu.build_carve_rc("あ", prm)
    assert isinstance(rc, dict)

    samples, info = carve.make(rc)
    assert carve.SR == 44100
    assert len(samples) > 1000
    assert max(abs(float(v)) for v in samples) > 0.01

    out_wav = tmp_path / "tsukinami_non_regression.wav"
    carve.write(str(out_wav), samples)
    with wave.open(str(out_wav), "rb") as wf:
        assert wf.getframerate() == 44100
        assert wf.getnframes() == len(samples)
