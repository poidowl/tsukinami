"""Tier 3 E2E Tests: Cross-Feature Combinations across all 18 Tsukinami ASR features.

Verifies pairwise and multi-module interactions across DSP, features, tokenizer,
Tier 1/2/3 speech data, DataLoader/collate, cnn_bigru & conformer_lite models,
checkpointing/resume, decoding + CharNgramLM, Viterbi alignment, metrics,
ASREngine, CLI pipeline, FastAPI backend, and zero-CDN web playground.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest


def test_t3_corruption_noise_features_and_vad():
    """F2 + F3 + F4 + F5 + F7: fast synth -> white/pink noise -> Log-Mel, MFCC+deltas, VAD."""
    import numpy as np
    from asr.audio import apply_corruption, detect_vad
    from asr.config import AudioConfig
    from asr.features import extract_log_mel, extract_mfcc
    from asr.synth_data import synthesize_fast_kotoba

    wav, _ = synthesize_fast_kotoba("おはよう", sr=16000, seed=42)
    cfg = AudioConfig()
    mel_clean = extract_log_mel(wav, cfg)

    for noise_type in ("white", "pink"):
        corrupted = apply_corruption(wav, 16000, snr_db=10.0, noise_type=noise_type, seed=7)
        mel = extract_log_mel(corrupted, cfg)
        mfcc = extract_mfcc(corrupted, cfg, n_mfcc=13, include_deltas=True)
        segs = detect_vad(corrupted, sr=16000)

        assert mel.dtype == np.float32 and mel.shape == mel_clean.shape and np.isfinite(mel).all()
        assert mfcc.dtype == np.float32 and mfcc.shape == (mel.shape[0], 39) and np.isfinite(mfcc).all()
        assert float(np.mean(np.abs(mel - mel_clean))) > 1e-3
        dur = len(corrupted) / 16000.0
        for s, e in segs:
            assert 0.0 <= s < e <= dur + 0.05


def test_t3_corruption_speed_bandlimit_gain_features():
    """F3 + F5 + F7: speed, telephone band-limit, and gain corruptions -> Log-Mel invariants."""
    import numpy as np
    from asr.audio import apply_corruption
    from asr.config import AudioConfig
    from asr.features import extract_log_mel
    from asr.synth_data import synthesize_fast_kotoba

    wav, _ = synthesize_fast_kotoba("ワタシ、ニホンゴ", sr=16000, seed=11)
    cfg_raw = AudioConfig(cmvn=False)
    cfg_norm = AudioConfig(cmvn=True)

    mel_clean_raw = extract_log_mel(wav, cfg_raw)
    mel_fast = extract_log_mel(apply_corruption(wav, 16000, speed=1.25), cfg_norm)
    mel_slow = extract_log_mel(apply_corruption(wav, 16000, speed=0.8), cfg_norm)
    assert mel_fast.shape[0] < mel_clean_raw.shape[0] < mel_slow.shape[0]

    tel_wav = apply_corruption(wav, 16000, band_limit=(300.0, 3400.0))
    mel_tel_raw = extract_log_mel(tel_wav, cfg_raw)
    assert np.isfinite(mel_tel_raw).all()
    assert float(np.mean(mel_tel_raw[:, -10:])) < float(np.mean(mel_clean_raw[:, -10:]))

    quiet_wav = apply_corruption(wav, 16000, gain_db=-6.0)
    rms_clean = float(np.sqrt(np.mean(wav ** 2)))
    rms_quiet = float(np.sqrt(np.mean(quiet_wav ** 2)))
    assert rms_quiet < rms_clean * 0.7
    mel_quiet_norm = extract_log_mel(quiet_wav, cfg_norm)
    assert abs(float(np.mean(mel_quiet_norm))) < 0.2
    assert 0.5 < float(np.std(mel_quiet_norm)) < 1.5


def test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug(tmp_path: Path):
    """F2 + F3 + F5 + F6 + F7 + F9: synth -> save_wav -> manifest -> Dataset -> collate + SpecAugment."""
    import numpy as np
    import torch
    from asr.audio import save_wav
    from asr.config import AudioConfig
    from asr.dataset import ASRManifestDataset, collate_asr_batch
    from asr.features import spec_augment
    from asr.synth_data import synthesize_fast_kotoba
    from asr.tokenizer import Tokenizer

    phrases = ["ア", "アイウ", "オハヨウ", "ワタシ、ニホンゴ"]
    manifest = tmp_path / "manifest.jsonl"
    rows = []
    for idx, text in enumerate(phrases):
        wav, moras = synthesize_fast_kotoba(text, sr=16000, seed=idx + 1)
        wpath = tmp_path / f"u{idx}.wav"
        save_wav(wpath, wav, sr=16000)
        rows.append(
            json.dumps(
                {
                    "audio_path": str(wpath),
                    "text": text,
                    "duration": float(len(wav) / 16000.0),
                    "speaker": f"spk_{idx}",
                    "source": "kotoba_fast",
                    "moras": moras,
                },
                ensure_ascii=False,
            )
        )
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")

    tok = Tokenizer("kana")
    audio_cfg = AudioConfig()
    ds_clean = ASRManifestDataset(manifest, audio_cfg, tok, augment=False)
    ds_aug = ASRManifestDataset(manifest, audio_cfg, tok, augment=True)
    batch = collate_asr_batch([ds_clean[i] for i in range(len(phrases))])
    batch_aug = collate_asr_batch([ds_aug[i] for i in range(len(phrases))])

    assert batch["feats"].shape[0] == 4 and batch["feats"].shape[2] == 64
    assert batch["feats"].shape[1] == int(batch["feat_lengths"].max())
    assert batch["targets"].shape[0] == 4
    assert batch["target_lengths"].shape == (4,)
    assert len(batch["texts"]) == 4
    assert torch.isfinite(batch_aug["feats"]).all()
    for i in range(4):
        tlen = int(batch["target_lengths"][i])
        assert tlen > 0
        assert all(int(x) != tok.blank_id for x in batch["targets"][i, :tlen].tolist())

    mel_np = batch["feats"][-1, : int(batch["feat_lengths"][-1])].numpy()
    aug_np = spec_augment(mel_np, freq_mask_param=8, time_mask_param=15, num_freq_masks=2, num_time_masks=2, seed=42)
    assert aug_np.shape == mel_np.shape and np.isfinite(aug_np).all()
    assert not np.array_equal(aug_np, mel_np)


def test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate(tiny_fast_dataset: dict[str, Path]):
    """F6 + F7 + F9: phoneme Tokenizer round-trip serialization + ASRManifestDataset + collate."""
    from asr.config import AudioConfig
    from asr.dataset import ASRManifestDataset, collate_asr_batch
    from asr.tokenizer import Tokenizer

    tok = Tokenizer.from_dict(Tokenizer("phoneme").to_dict())
    assert tok.blank_id == 0 and tok.vocab_size > 10
    ds = ASRManifestDataset(tiny_fast_dataset["val"], AudioConfig(), tok, augment=False)
    batch = collate_asr_batch([ds[0], ds[1]])
    assert batch["feats"].shape[0] == 2
    assert all(int(tl) > 0 for tl in batch["target_lengths"].tolist())
    ids0 = batch["targets"][0, : int(batch["target_lengths"][0])].tolist()
    assert len(tok.decode(ids0)) > 0


def test_t3_tsukinami_presets_cache_wav_io_logmel(tmp_path: Path):
    """F2 + F3 + F8: tsukinami default vs ossan -> disk cache hit -> WAV roundtrip -> Log-Mel."""
    import numpy as np
    from asr.audio import load_wav, save_wav
    from asr.config import AudioConfig
    from asr.features import extract_log_mel
    from asr.synth_data import synthesize_tsukinami

    cache_dir = tmp_path / "t3_cache"
    w_def, m_def = synthesize_tsukinami("あか", preset="default", sr=16000, cache_dir=cache_dir)
    w_oss, m_oss = synthesize_tsukinami("あか", preset="ossan", sr=16000, cache_dir=cache_dir)
    w_def_cached, _ = synthesize_tsukinami("あか", preset="default", sr=16000, cache_dir=cache_dir)

    assert any(cache_dir.rglob("*"))
    assert np.allclose(w_def, w_def_cached, atol=1e-4)
    assert len(m_def) >= 1 and len(m_oss) >= 1
    assert all({"t", "a", "e"} <= set(m.keys()) for m in m_def)

    wav_path = tmp_path / "def.wav"
    save_wav(wav_path, w_def, sr=16000)
    reloaded, sr = load_wav(wav_path, target_sr=16000)
    assert sr == 16000
    corr = float(np.corrcoef(w_def, reloaded)[0, 1])
    assert corr > 0.999

    mel_def = extract_log_mel(w_def, AudioConfig())
    mel_oss = extract_log_mel(w_oss, AudioConfig())
    assert np.isfinite(mel_def).all() and np.isfinite(mel_oss).all()
    t_min = min(mel_def.shape[0], mel_oss.shape[0])
    assert float(np.mean(np.abs(mel_def[:t_min] - mel_oss[:t_min]))) > 1e-2


def test_t3_cnn_bigru_train_checkpoint_and_resume(tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
    """F1 + F10 + F11: cnn_bigru train -> checkpoint -> resume -> build_model + load_state_dict forward."""
    import torch
    from asr.config import AudioConfig, ModelConfig, TrainConfig
    from asr.models import build_model
    from asr.tokenizer import Tokenizer
    from asr.train import load_checkpoint, train_asr

    cdir = tmp_path / "bigru_resume"
    audio_cfg = AudioConfig()
    model_cfg = ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0)
    tok = Tokenizer("kana")

    train_asr(
        tiny_fast_dataset["train"],
        tiny_fast_dataset["val"],
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=TrainConfig(epochs=1, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
        tokenizer=tok,
    )
    assert (cdir / "best.pt").is_file() and (cdir / "latest.pt").is_file()

    train_asr(
        tiny_fast_dataset["train"],
        tiny_fast_dataset["val"],
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=TrainConfig(epochs=2, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
        tokenizer=tok,
        resume_from=cdir / "latest.pt",
    )
    ckpt = load_checkpoint(cdir / "latest.pt", device="cpu")
    required = {"model_state_dict", "model_config", "audio_cfg", "tokenizer", "history", "epoch", "best_val_cer"}
    assert required <= set(ckpt.keys())
    assert int(ckpt["epoch"]) >= 2

    model = build_model(model_cfg, tok.vocab_size)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    assert model.subsampling_factor == 4
    assert model.output_frame_stride_ms(audio_cfg) == pytest.approx(40.0)
    with torch.no_grad():
        lp, out_len = model(torch.randn(1, 40, audio_cfg.n_mels), torch.tensor([40]))
    assert torch.isfinite(lp).all() and int(out_len[0]) > 0


def test_t3_conformer_lite_train_checkpoint_and_forward(tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
    """F1 + F10 + F11: conformer_lite train -> checkpoint load -> build_model log_softmax invariant."""
    import torch
    from asr.config import AudioConfig, ModelConfig, TrainConfig
    from asr.models import build_model
    from asr.tokenizer import Tokenizer
    from asr.train import load_checkpoint, train_asr

    cdir = tmp_path / "conf_train"
    audio_cfg = AudioConfig()
    model_cfg = ModelConfig(arch="conformer_lite", hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7, dropout=0.0)
    tok = Tokenizer("kana")

    train_asr(
        tiny_fast_dataset["train"],
        tiny_fast_dataset["val"],
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=TrainConfig(epochs=1, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
        tokenizer=tok,
    )
    ckpt = load_checkpoint(cdir / "best.pt", device="cpu")
    model = build_model(model_cfg, tok.vocab_size)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    with torch.no_grad():
        lp, out_len = model(torch.randn(2, 40, audio_cfg.n_mels), torch.tensor([40, 28]))
    assert torch.isfinite(lp).all()
    assert (out_len <= torch.tensor([40, 28])).all()
    assert torch.allclose(torch.exp(lp).sum(dim=-1), torch.ones(lp.shape[:2]), atol=1e-4)


def test_t3_model_logprobs_greedy_beam_lm_and_viterbi(tiny_checkpoint: dict):
    """F10 + F12 + F13: trained model log_probs -> greedy, beam, beam+CharNgramLM, viterbi_align."""
    import numpy as np
    import torch
    from asr.config import DecodeConfig
    from asr.dataset import ASRManifestDataset, collate_asr_batch
    from asr.decoding import CharNgramLM, greedy_decode, prefix_beam_search, viterbi_align
    from asr.models import build_model
    from asr.train import load_checkpoint

    ckpt = load_checkpoint(tiny_checkpoint["best_pt"], device="cpu")
    tok = tiny_checkpoint["tokenizer"]
    audio_cfg = tiny_checkpoint["audio_cfg"]
    model = build_model(tiny_checkpoint["model_cfg"], tok.vocab_size)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    ds = ASRManifestDataset(tiny_checkpoint["val_manifest"], audio_cfg, tok, augment=False)
    batch = collate_asr_batch([ds[0]])
    with torch.no_grad():
        lp, out_len = model(batch["feats"], batch["feat_lengths"])
    lp_np = lp[0, : int(out_len[0])].numpy()

    lm = CharNgramLM(order=3, smoothing=0.1)
    lm.fit(["ワタシ、ニホンゴ", "オハヨウ", "コンニチハ"] * 5)
    lm2 = CharNgramLM.from_dict(lm.to_dict())
    assert lm2.score_next("オハ", "ヨ") == pytest.approx(lm.score_next("オハ", "ヨ"))

    g = greedy_decode(lp_np, tok)
    b_no_lm = prefix_beam_search(lp_np, tok, DecodeConfig(method="beam", beam_width=4, lm_weight=0.0))
    b_lm = prefix_beam_search(lp_np, tok, DecodeConfig(method="beam", beam_width=4, lm_weight=0.5, insertion_bonus=0.2), lm=lm2)

    assert {"text", "token_ids", "score"} <= set(g.keys())
    for hyps in (b_no_lm, b_lm):
        assert len(hyps) >= 1
        assert {"text", "score", "acoustic_score", "lm_score"} <= set(hyps[0].keys())
        for i in range(len(hyps) - 1):
            assert hyps[i]["score"] >= hyps[i + 1]["score"] - 1e-6

    ref_ids = tok.encode(batch["texts"][0])
    align = viterbi_align(lp_np, ref_ids, tok, frame_stride_ms=model.output_frame_stride_ms(audio_cfg))
    assert len(align) == len(ref_ids)
    for i, seg in enumerate(align):
        assert {"token", "start_sec", "end_sec", "confidence"} <= set(seg.keys())
        assert np.isfinite(seg["confidence"])
        if i > 0:
            assert align[i - 1]["start_sec"] <= seg["start_sec"] + 1e-6


def test_t3_kotoba_moras_viterbi_boundary_error_and_metrics(tiny_checkpoint: dict):
    """F7 + F13 + F14: fast synth moras -> model + viterbi_align -> boundary error + CER/MER/WER/confusion."""
    import numpy as np
    import torch
    from asr.decoding import viterbi_align
    from asr.features import extract_log_mel
    from asr.metrics import alignment_boundary_error, compute_cer, compute_mer, compute_wer, confusion_pairs
    from asr.models import build_model
    from asr.synth_data import synthesize_fast_kotoba
    from asr.train import load_checkpoint

    wav, gt_moras = synthesize_fast_kotoba("ワタシ、ニホンゴ", sr=16000, seed=42)
    tok = tiny_checkpoint["tokenizer"]
    audio_cfg = tiny_checkpoint["audio_cfg"]
    ckpt = load_checkpoint(tiny_checkpoint["best_pt"], device="cpu")
    model = build_model(tiny_checkpoint["model_cfg"], tok.vocab_size)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    mel = extract_log_mel(wav, audio_cfg)
    with torch.no_grad():
        lp, out_len = model(torch.from_numpy(mel).unsqueeze(0), torch.tensor([mel.shape[0]]))
    lp_np = lp[0, : int(out_len[0])].numpy()
    pred_align = viterbi_align(lp_np, tok.encode("ワタシ、ニホンゴ"), tok, frame_stride_ms=40.0)

    abe = alignment_boundary_error(gt_moras, pred_align)
    assert isinstance(abe, dict) and len(abe) > 0
    for v in abe.values():
        if isinstance(v, (int, float)):
            assert np.isfinite(v)

    refs = ["ワタシ、ニホンゴ", "カキクケ"]
    hyps = ["ワタシ、ニホンコ", "ガキク"]
    cer = compute_cer(refs, hyps)
    assert {"cer", "substitutions", "deletions", "insertions", "ref_len"} <= set(cer.keys())
    assert cer["cer"] == pytest.approx((cer["substitutions"] + cer["deletions"] + cer["insertions"]) / cer["ref_len"])
    assert compute_mer(refs, hyps)["mer"] >= 0.0
    assert compute_wer(["hello world"], ["hello earth"])["wer"] == pytest.approx(0.5)
    pairs = confusion_pairs(refs, hyps, top_k=5)
    assert isinstance(pairs, list) and len(pairs) >= 1
    assert all(len(p) == 3 and isinstance(p[2], int) for p in pairs)


def test_t3_engine_transcribe_visuals_corruption_and_redecode(tiny_engine):
    """F5 + F12 + F15: ASREngine clean & corrupted transcribe(include_visuals=True) -> cached redecode."""
    from asr.audio import apply_corruption
    from asr.config import DecodeConfig
    from asr.synth_data import synthesize_fast_kotoba

    wav, _ = synthesize_fast_kotoba("コンニチハ", sr=16000, seed=5)
    noisy = apply_corruption(wav, 16000, snr_db=10.0, noise_type="white", seed=5)

    for audio in (wav, noisy):
        res = tiny_engine.transcribe(audio, sr=16000, include_visuals=True)
        for key in ("text", "hypotheses", "alignment", "rtf", "duration_sec", "utterance_id", "waveform", "log_mel", "ctc_posteriors", "vad_segments"):
            assert key in res and res[key] is not None
        r_g = tiny_engine.redecode(res["utterance_id"], DecodeConfig(method="greedy"))
        r_b = tiny_engine.redecode(res["utterance_id"], DecodeConfig(method="beam", beam_width=4, temperature=1.4, blank_bias=-0.5))
        assert isinstance(r_g["text"], str) and isinstance(r_b["text"], str)


def test_t3_cli_pipeline_generate_train_eval_transcribe(run_cli, tmp_path: Path):
    """F1 + F7 + F9 + F11 + F15 + F16: full CLI subprocess pipeline generate -> train -> eval -> transcribe."""
    data_dir = tmp_path / "data"
    ckpt_dir = tmp_path / "ckpt"

    p_gen = run_cli(["generate", "--out-dir", str(data_dir), "--num-train", "6", "--num-val", "2", "--engine", "fast"], timeout=60)
    assert p_gen.returncode == 0, p_gen.stderr
    val_manifest = data_dir / "val.jsonl"
    first_val = json.loads(val_manifest.read_text(encoding="utf-8").splitlines()[0])

    p_tr = run_cli(
        [
            "train",
            "--train-manifest", str(data_dir / "train.jsonl"),
            "--val-manifest", str(val_manifest),
            "--out-dir", str(ckpt_dir),
            "--arch", "cnn_bigru",
            "--epochs", "1",
        ],
        timeout=120,
    )
    assert p_tr.returncode == 0, p_tr.stderr
    best_pt = ckpt_dir / "best.pt"
    assert best_pt.is_file()

    p_ev = run_cli(["eval", "--checkpoint", str(best_pt), "--manifest", str(val_manifest), "--method", "greedy"], timeout=60)
    assert p_ev.returncode == 0, p_ev.stderr
    assert "cer" in (p_ev.stdout + p_ev.stderr).lower()

    p_wav = run_cli(["transcribe", "--checkpoint", str(best_pt), "--wav", first_val["audio_path"], "--method", "greedy", "--json"], timeout=60)
    assert p_wav.returncode == 0, p_wav.stderr
    wav_res = json.loads(p_wav.stdout)
    assert "text" in wav_res

    p_tts = run_cli(["transcribe", "--checkpoint", str(best_pt), "--tts", "あか", "--preset", "default", "--method", "beam", "--json"], timeout=60)
    assert p_tts.returncode == 0, p_tts.stderr
    tts_res = json.loads(p_tts.stdout)
    assert "text" in tts_res


def test_t3_api_tts_roundtrip_corruption_redecode_and_info(api_client, helpers):
    """F5 + F8 + F12 + F15 + F17 + F18: API /info -> /tts-roundtrip (with corruption) -> /redecode -> / HTML."""
    r_info = api_client.get("/api/info")
    assert r_info.status_code == 200 and isinstance(r_info.json(), dict)

    r_rt = api_client.post(
        "/api/tts-roundtrip",
        json={
            "text": "あか",
            "preset": "default",
            "synth_engine": "fast",
            "corruption": {"snr_db": 15.0, "noise_type": "white"},
            "decode_cfg": {"method": "beam", "beam_width": 4},
        },
    )
    assert r_rt.status_code == 200, r_rt.text
    rt_data = r_rt.json()
    raw_wav = base64.b64decode(rt_data["audio_b64"])
    assert raw_wav[:4] == b"RIFF"
    assert isinstance(rt_data["ground_truth_moras"], list) and len(rt_data["ground_truth_moras"]) > 0
    cer_val = rt_data["cer"]["cer"] if isinstance(rt_data["cer"], dict) else rt_data["cer"]
    assert float(cer_val) >= 0.0

    tr = helpers.extract_transcribe_payload(rt_data)
    utt_id = tr["utterance_id"]

    r_rd = api_client.post(
        "/api/redecode",
        json={"utterance_id": utt_id, "decode_cfg": {"method": "greedy", "temperature": 1.2, "blank_bias": 0.1}},
    )
    assert r_rd.status_code == 200, r_rd.text
    assert "text" in r_rd.json()

    r_root = api_client.get("/")
    assert r_root.status_code == 200 and "text/html" in r_root.headers.get("content-type", "").lower()
    assert not re.search(r'<script[^>]+src=["\'](?:https?:)?//', r_root.text, re.IGNORECASE)
    assert not re.search(r'<link[^>]+href=["\'](?:https?:)?//', r_root.text, re.IGNORECASE)
