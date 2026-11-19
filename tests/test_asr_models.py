"""Unit tests for M3 acoustic models (`asr/models/`) and CTC training engine (`asr/train.py`)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
import torch.nn as nn

from asr.audio import save_wav
from asr.config import AudioConfig, ModelConfig, TrainConfig
from asr.dataset import write_manifest
from asr.models import (
    CNNBiGRUCTC,
    ConformerLiteCTC,
    Conv2dSubsampling,
    build_model,
)
from asr.synth_data import synthesize_fast_kotoba
from asr.tokenizer import Tokenizer
from asr.train import load_checkpoint, train_asr


def _build_tiny_synth_dataset(tmp_path: Path, utterances: list[str] | None = None) -> Path:
    """Create a small deterministic synthetic Japanese WAV + JSONL manifest."""
    texts = utterances if utterances is not None else ["アオ", "イヌ", "ウミ", "エキ"]
    audio_dir = tmp_path / "wavs"
    audio_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for idx, text in enumerate(texts):
        wav, moras = synthesize_fast_kotoba(
            text,
            sr=16000,
            f0_scale=1.0,
            fscale=1.0,
            rate=1.0,
            snr_db=None,
            seed=100 + idx,
        )
        wav_path = audio_dir / f"utt_{idx:02d}.wav"
        save_wav(wav_path, wav, sr=16000)
        records.append(
            {
                "audio_path": str(wav_path),
                "text": text,
                "duration": float(len(wav) / 16000.0),
                "speaker": "default",
                "source": "kotoba_fast",
                "moras": moras,
            }
        )
    manifest_path = tmp_path / "manifest.jsonl"
    write_manifest(records, manifest_path)
    return manifest_path


def test_subsampling_output_lengths_and_short_inputs() -> None:
    sub = Conv2dSubsampling(in_features=64, out_features=96, conv_channels=16, dropout=0.0)
    assert sub.subsampling_factor == 4

    test_lens = torch.tensor([0, 1, 2, 3, 4, 5, 7, 8, 16, 101], dtype=torch.long)
    expected = torch.tensor([0, 1, 1, 1, 1, 2, 2, 2, 4, 26], dtype=torch.long)
    assert torch.equal(sub.output_lengths(test_lens), expected)

    for t in (1, 2, 4, 5, 7, 16):
        x = torch.randn(2, t, 64)
        lengths = torch.tensor([t, max(1, t - 1)], dtype=torch.long)
        out, out_lens = sub(x, lengths)
        assert out.shape == (2, (t + 3) // 4, 96)
        assert torch.equal(out_lens, sub.output_lengths(lengths))
        assert torch.isfinite(out).all()


@pytest.mark.parametrize("arch", ["cnn_bigru", "conformer_lite"])
def test_build_model_factory_and_metadata(arch: str) -> None:
    tok = Tokenizer("kana")
    cfg = ModelConfig(arch=arch, n_mels=64, hidden_size=192, num_layers=2, num_heads=4)
    model = build_model(cfg, vocab_size=tok.vocab_size)

    if arch == "cnn_bigru":
        assert isinstance(model, CNNBiGRUCTC)
    else:
        assert isinstance(model, ConformerLiteCTC)

    assert model.subsampling_factor == 4
    audio_cfg = AudioConfig(sample_rate=16000, hop_length=160)
    assert model.output_frame_stride_ms(audio_cfg) == pytest.approx(40.0)
    audio_cfg_half = AudioConfig(sample_rate=16000, hop_length=80)
    assert model.output_frame_stride_ms(audio_cfg_half) == pytest.approx(20.0)

    n_params = sum(p.numel() for p in model.parameters())
    if arch == "cnn_bigru":
        assert 300_000 < n_params < 700_000
    else:
        assert 800_000 < n_params < 1_800_000


def test_build_model_validation_errors() -> None:
    fake_cfg = SimpleNamespace(arch="unknown_arch", n_mels=64, hidden_size=64, num_layers=1)
    with pytest.raises(ValueError, match="Unknown model architecture"):
        build_model(fake_cfg, vocab_size=10)  # type: ignore[arg-type]

    cfg = ModelConfig(arch="cnn_bigru")
    with pytest.raises(ValueError, match="vocab_size"):
        build_model(cfg, vocab_size=0)
    with pytest.raises(ValueError, match="vocab_size"):
        build_model(cfg, vocab_size=1)


@pytest.mark.parametrize("arch", ["cnn_bigru", "conformer_lite"])
def test_model_forward_shapes_log_probs_and_edge_cases(arch: str) -> None:
    torch.manual_seed(7)
    vocab_size = 32
    cfg = ModelConfig(
        arch=arch,
        n_mels=64,
        hidden_size=64,
        num_layers=2,
        dropout=0.1,
        num_heads=4,
        conv_kernel_size=7,
    )
    model = build_model(cfg, vocab_size=vocab_size)
    model.eval()

    feats = torch.randn(3, 101, 64)
    feat_lengths = torch.tensor([101, 73, 40], dtype=torch.long)
    log_probs, out_lengths = model(feats, feat_lengths)

    expected_t = (101 + 3) // 4
    assert log_probs.shape == (3, expected_t, vocab_size)
    assert out_lengths.dtype == torch.long
    assert out_lengths.tolist() == [26, 19, 10]
    assert torch.isfinite(log_probs).all()
    probs_sum = log_probs.exp().sum(dim=-1)
    assert torch.allclose(probs_sum, torch.ones_like(probs_sum), atol=1e-5)

    # Very short inputs in train() mode (catches any BatchNorm1d B=1,T'=1 crash)
    model.train()
    for t in (1, 4):
        short_feats = torch.randn(1, t, 64)
        short_lens = torch.tensor([t], dtype=torch.long)
        short_lp, short_out_lens = model(short_feats, short_lens)
        assert short_lp.shape == (1, 1, vocab_size)
        assert short_out_lens.tolist() == [1]
        assert torch.isfinite(short_lp).all()


def test_conformer_dynamic_positional_encoding_long_sequence() -> None:
    cfg = ModelConfig(
        arch="conformer_lite",
        n_mels=16,
        hidden_size=16,
        num_layers=1,
        dropout=0.0,
        num_heads=4,
        conv_kernel_size=5,
    )
    model = build_model(cfg, vocab_size=12)
    model.eval()

    # T = 4200 -> T' = 1050 > initial max_len = 1024
    feats = torch.randn(1, 4200, 16)
    lengths = torch.tensor([4200], dtype=torch.long)
    with torch.no_grad():
        log_probs, out_lengths = model(feats, lengths)
    assert log_probs.shape == (1, 1050, 12)
    assert out_lengths.tolist() == [1050]
    assert torch.isfinite(log_probs).all()


@pytest.mark.parametrize("arch", ["cnn_bigru", "conformer_lite"])
def test_padding_mask_invariance(arch: str) -> None:
    torch.manual_seed(11)
    cfg = ModelConfig(
        arch=arch,
        n_mels=64,
        hidden_size=64,
        num_layers=2,
        dropout=0.0,
        num_heads=4,
        conv_kernel_size=7,
    )
    model = build_model(cfg, vocab_size=24)
    model.eval()

    # 1) Mutated padding invariance
    feats1 = torch.randn(2, 80, 64)
    lengths = torch.tensor([80, 37], dtype=torch.long)
    feats2 = feats1.clone()
    feats2[1, 37:, :] = 9999.0

    with torch.no_grad():
        lp1, out_lens1 = model(feats1, lengths)
        lp2, out_lens2 = model(feats2, lengths)

    assert torch.equal(out_lens1, out_lens2)
    valid_len = int(out_lens1[1].item())
    assert torch.allclose(lp1[1, :valid_len], lp2[1, :valid_len], atol=1e-5)

    # 2) Unpadded single-item vs padded-batch invariance
    single_feats = feats1[1:2, :37, :].clone()
    single_lens = torch.tensor([37], dtype=torch.long)
    with torch.no_grad():
        lp_single, out_len_single = model(single_feats, single_lens)

    assert int(out_len_single[0].item()) == valid_len
    assert torch.allclose(lp_single[0, :valid_len], lp1[1, :valid_len], atol=1e-5)


@pytest.mark.parametrize("arch", ["cnn_bigru", "conformer_lite"])
def test_gradient_flow_with_ctc_loss(arch: str) -> None:
    torch.manual_seed(23)
    vocab_size = 20
    cfg = ModelConfig(
        arch=arch,
        n_mels=64,
        hidden_size=48,
        num_layers=2,
        dropout=0.1,
        num_heads=4,
        conv_kernel_size=7,
    )
    model = build_model(cfg, vocab_size=vocab_size)
    model.train()

    feats = torch.randn(2, 60, 64)
    feat_lengths = torch.tensor([60, 44], dtype=torch.long)
    targets = torch.tensor([[1, 2, 3, 4], [5, 6, 0, 0]], dtype=torch.long)
    target_lengths = torch.tensor([4, 2], dtype=torch.long)

    criterion = nn.CTCLoss(blank=0, reduction="mean", zero_infinity=True)
    log_probs, out_lengths = model(feats, feat_lengths)
    loss = criterion(log_probs.transpose(0, 1), targets, out_lengths, target_lengths)

    assert torch.isfinite(loss)
    assert loss.item() > 0.0

    loss.backward()
    total_norm_sq = 0.0
    for name, param in model.named_parameters():
        if param.requires_grad:
            assert param.grad is not None, f"Missing gradient for parameter {name}"
            assert torch.isfinite(param.grad).all(), f"Non-finite gradient for {name}"
            total_norm_sq += float(param.grad.pow(2).sum().item())
    assert total_norm_sq > 0.0


def test_train_asr_overfit_sanity_cpu(tmp_path: Path) -> None:
    manifest = _build_tiny_synth_dataset(
        tmp_path,
        utterances=["オハヨウ", "コンニチハ", "アリガトウ", "サヨウナラ"],
    )
    audio_cfg = AudioConfig(n_mels=64)
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=64,
        hidden_size=192,
        num_layers=2,
        dropout=0.0,
    )
    train_cfg = TrainConfig(
        epochs=60,
        batch_size=2,
        lr=5e-3,
        weight_decay=1e-4,
        grad_clip=5.0,
        seed=42,
        use_spec_augment=False,
        checkpoint_dir=str(tmp_path / "ckpts"),
    )
    tok = Tokenizer("kana")

    result = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg,
        tokenizer=tok,
    )

    history = result["history"]
    assert len(history) == 60
    initial_loss = history[0]["train_loss"]
    final_loss = result["final_train_loss"]
    assert final_loss < 0.5 * initial_loss, (
        f"Expected >50% CTC loss drop: initial={initial_loss:.4f}, final={final_loss:.4f}"
    )

    initial_cer = history[0]["val_cer"]
    assert result["best_val_cer"] < 0.5
    assert result["best_val_cer"] < initial_cer

    assert Path(result["best_checkpoint"]).is_file()
    assert Path(result["latest_checkpoint"]).is_file()


def test_checkpoint_exact_logit_reproduction_and_resume(tmp_path: Path) -> None:
    manifest = _build_tiny_synth_dataset(tmp_path)
    audio_cfg = AudioConfig(n_mels=64)
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=64,
        hidden_size=48,
        num_layers=1,
        dropout=0.0,
    )
    ckpt_dir = tmp_path / "ckpts_resume"
    train_cfg_1 = TrainConfig(
        epochs=2,
        batch_size=4,
        lr=4e-3,
        seed=123,
        use_spec_augment=False,
        checkpoint_dir=str(ckpt_dir),
    )
    tok = Tokenizer("kana")

    res1 = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg_1,
        tokenizer=tok,
    )

    best_path = Path(res1["best_checkpoint"])
    latest_path = Path(res1["latest_checkpoint"])

    # Verify weights_only=True succeeds directly
    raw_ckpt = torch.load(best_path, map_location="cpu", weights_only=True)
    assert isinstance(raw_ckpt, dict)

    ckpt = load_checkpoint(best_path, device="cpu")
    for key in (
        "model_state_dict",
        "optimizer_state_dict",
        "scheduler_state_dict",
        "model_config",
        "audio_config",
        "audio_cfg",
        "tokenizer",
        "history",
        "epoch",
        "best_val_cer",
    ):
        assert key in ckpt, f"Missing checkpoint key: {key}"

    # Exact logit reproduction across two loaded model instances
    reloaded_cfg = ModelConfig.from_dict(ckpt["model_config"])
    reloaded_tok = Tokenizer.from_dict(ckpt["tokenizer"])
    model_a = build_model(reloaded_cfg, vocab_size=reloaded_tok.vocab_size)
    model_a.load_state_dict(ckpt["model_state_dict"])
    model_a.eval()

    model_b = build_model(reloaded_cfg, vocab_size=reloaded_tok.vocab_size)
    model_b.load_state_dict(load_checkpoint(best_path, device="cpu")["model_state_dict"])
    model_b.eval()

    torch.manual_seed(999)
    probe_feats = torch.randn(2, 40, 64)
    probe_lens = torch.tensor([40, 28], dtype=torch.long)
    with torch.no_grad():
        lp_a, lens_a = model_a(probe_feats, probe_lens)
        lp_b, lens_b = model_b(probe_feats, probe_lens)
    assert torch.equal(lens_a, lens_b)
    assert torch.allclose(lp_a, lp_b, atol=1e-5)

    # Resume from latest.pt to epoch 4
    train_cfg_2 = TrainConfig(
        epochs=4,
        batch_size=4,
        lr=4e-3,
        seed=123,
        use_spec_augment=False,
        checkpoint_dir=str(ckpt_dir),
    )
    res2 = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg_2,
        tokenizer=tok,
        resume_from=latest_path,
    )
    assert [h["epoch"] for h in res2["history"]] == [1, 2, 3, 4]
    assert res2["history"][:2] == res1["history"]
    assert res2["best_val_cer"] <= res1["best_val_cer"]
    assert res2["epochs_completed"] == 4

    # Resuming with epochs <= completed epochs succeeds cleanly without extra epochs
    res3 = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg_1,  # epochs=2 <= 4
        tokenizer=tok,
        resume_from=latest_path,
    )
    assert res3["epochs_completed"] == 4
    assert len(res3["history"]) == 4

    # Missing checkpoint raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        load_checkpoint(tmp_path / "does_not_exist.pt")


def test_train_asr_conformer_lite_smoke(tmp_path: Path) -> None:
    manifest = _build_tiny_synth_dataset(tmp_path)
    audio_cfg = AudioConfig(n_mels=64)
    model_cfg = ModelConfig(
        arch="conformer_lite",
        n_mels=64,
        hidden_size=64,
        num_layers=1,
        dropout=0.0,
        num_heads=4,
        conv_kernel_size=7,
    )
    train_cfg = TrainConfig(
        epochs=2,
        batch_size=4,
        lr=3e-3,
        seed=7,
        use_spec_augment=False,
        checkpoint_dir=str(tmp_path / "ckpts_conf"),
    )
    tok = Tokenizer("kana")

    result = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg,
        tokenizer=tok,
    )
    assert len(result["history"]) == 2
    assert torch.isfinite(torch.tensor(result["final_train_loss"]))
    ckpt = load_checkpoint(result["best_checkpoint"], device="cpu")
    assert ckpt["model_config"]["arch"] == "conformer_lite"


def test_train_asr_deterministic_with_spec_augment(tmp_path: Path) -> None:
    manifest = _build_tiny_synth_dataset(tmp_path)
    audio_cfg = AudioConfig(n_mels=64)
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=64,
        hidden_size=48,
        num_layers=1,
        dropout=0.0,
    )
    tok = Tokenizer("kana")

    def _run(subdir: str, *, use_spec_augment: bool) -> dict:
        cfg = TrainConfig(
            epochs=2,
            batch_size=2,
            lr=3e-3,
            seed=42,
            use_spec_augment=use_spec_augment,
            checkpoint_dir=str(tmp_path / subdir),
        )
        return train_asr(
            manifest,
            manifest,
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=cfg,
            tokenizer=tok,
        )

    res_a = _run("spec_run_a", use_spec_augment=True)
    res_b = _run("spec_run_b", use_spec_augment=True)
    res_no_aug = _run("no_aug_run", use_spec_augment=False)

    assert res_a["history"] == res_b["history"]

    sd_a = load_checkpoint(res_a["latest_checkpoint"], device="cpu")["model_state_dict"]
    sd_b = load_checkpoint(res_b["latest_checkpoint"], device="cpu")["model_state_dict"]
    assert sd_a.keys() == sd_b.keys()
    for key in sd_a:
        assert torch.equal(sd_a[key], sd_b[key]), f"Weight mismatch for {key}"

    # Verify SpecAugment actually altered training compared to augment=False
    assert res_a["history"][0]["train_loss"] != res_no_aug["history"][0]["train_loss"]


def test_resume_into_new_checkpoint_dir_preserves_best_val_cer(tmp_path: Path) -> None:
    manifest = _build_tiny_synth_dataset(tmp_path)
    audio_cfg = AudioConfig(n_mels=64)
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=64,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
    )
    tok = Tokenizer("kana")

    dir1 = tmp_path / "dir1"
    cfg1 = TrainConfig(
        epochs=2,
        batch_size=4,
        lr=3e-3,
        seed=17,
        use_spec_augment=False,
        checkpoint_dir=str(dir1),
    )
    res1 = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=cfg1,
        tokenizer=tok,
    )

    # Simulate a resumed checkpoint with an already-strong best_val_cer=0.001
    seeded_ckpt_path = tmp_path / "seeded_resume.pt"
    ckpt1 = load_checkpoint(res1["latest_checkpoint"], device="cpu")
    ckpt1["best_val_cer"] = 0.001
    torch.save(ckpt1, seeded_ckpt_path)

    dir2 = tmp_path / "dir2_new"
    cfg2 = TrainConfig(
        epochs=4,
        batch_size=4,
        lr=3e-3,
        seed=17,
        use_spec_augment=False,
        checkpoint_dir=str(dir2),
    )
    res2 = train_asr(
        manifest,
        manifest,
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=cfg2,
        tokenizer=tok,
        resume_from=seeded_ckpt_path,
    )

    assert res2["epochs_completed"] == 4
    assert res2["best_val_cer"] == pytest.approx(0.001)

    latest_ckpt = load_checkpoint(dir2 / "latest.pt", device="cpu")
    best_ckpt = load_checkpoint(dir2 / "best.pt", device="cpu")
    assert latest_ckpt["best_val_cer"] == pytest.approx(0.001)
    assert best_ckpt["best_val_cer"] == pytest.approx(0.001)
    assert best_ckpt["epoch"] == 2
    for key, tensor in ckpt1["model_state_dict"].items():
        assert torch.equal(best_ckpt["model_state_dict"][key], tensor)


def test_load_checkpoint_corrupt_and_empty_files(tmp_path: Path) -> None:
    corrupt_path = tmp_path / "corrupt.pt"
    corrupt_path.write_bytes(b"not a valid torch checkpoint at all 1234567890")
    with pytest.raises(ValueError, match="Corrupt or invalid checkpoint"):
        load_checkpoint(corrupt_path)

    empty_path = tmp_path / "empty.pt"
    empty_path.write_bytes(b"")
    with pytest.raises(ValueError, match="Corrupt or invalid checkpoint"):
        load_checkpoint(empty_path)

    with pytest.raises(ValueError, match="directory"):
        load_checkpoint(tmp_path)

    with pytest.raises(FileNotFoundError):
        load_checkpoint(tmp_path / "missing.pt")

