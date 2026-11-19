"""CTC training engine and checkpoint utilities for Tsukinami ASR."""

from __future__ import annotations

import math
import os
import pickle
import random
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from asr.config import AudioConfig, ModelConfig, TrainConfig
from asr.dataset import ASRManifestDataset, collate_asr_batch
from asr.decoding import greedy_decode
from asr.features import spec_augment
from asr.metrics import compute_cer
from asr.models import build_model
from asr.tokenizer import Tokenizer

__all__ = ["train_asr", "load_checkpoint"]

_REQUIRED_CKPT_KEYS = ("model_state_dict", "model_config", "tokenizer")


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _atomic_torch_save(obj: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    try:
        torch.save(obj, tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


_CORRUPT_CKPT_ERRORS = (
    EOFError,
    pickle.UnpicklingError,
    zipfile.BadZipFile,
    RuntimeError,
    OSError,
)


class _SeededSpecAugmentDataset(Dataset):
    """Wrap an ASR dataset to apply deterministic SpecAugment per sample."""

    def __init__(self, base_ds: Dataset, seed: int) -> None:
        self._base_ds = base_ds
        self._rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self._base_ds)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        item = dict(self._base_ds[idx])
        feats = item["feats"]
        mel_np = (
            feats.detach().cpu().numpy()
            if isinstance(feats, torch.Tensor)
            else np.asarray(feats, dtype=np.float32)
        )
        aug_seed = int(self._rng.integers(0, 2**31 - 1))
        aug_mel = spec_augment(mel_np, seed=aug_seed)
        item["feats"] = torch.from_numpy(
            np.ascontiguousarray(aug_mel, dtype=np.float32)
        )
        return item


def load_checkpoint(path: str | Path, device: str = "cpu") -> dict[str, Any]:
    """Load an ASR checkpoint ``.pt`` file safely on the requested device."""
    ckpt_path = Path(path)
    if not ckpt_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")
    if ckpt_path.is_dir():
        raise ValueError(f"Checkpoint path is a directory: {ckpt_path}")

    try:
        ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
    except (pickle.UnpicklingError, RuntimeError):
        try:
            ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)
        except _CORRUPT_CKPT_ERRORS as exc:
            raise ValueError(
                f"Corrupt or invalid checkpoint {ckpt_path}: {exc}"
            ) from exc
    except _CORRUPT_CKPT_ERRORS as exc:
        raise ValueError(
            f"Corrupt or invalid checkpoint {ckpt_path}: {exc}"
        ) from exc

    if not isinstance(ckpt, dict):
        raise ValueError(
            f"Expected checkpoint dict at {ckpt_path}, got {type(ckpt).__name__}"
        )

    missing = [k for k in _REQUIRED_CKPT_KEYS if k not in ckpt]
    if missing:
        raise ValueError(
            f"Checkpoint {ckpt_path} is missing required key(s): {missing}"
        )

    # Ensure both audio_config and audio_cfg aliases are available.
    if "audio_config" in ckpt and "audio_cfg" not in ckpt:
        ckpt["audio_cfg"] = ckpt["audio_config"]
    elif "audio_cfg" in ckpt and "audio_config" not in ckpt:
        ckpt["audio_config"] = ckpt["audio_cfg"]

    return ckpt


def _evaluate_epoch(
    model: nn.Module,
    val_loader: DataLoader,
    criterion: nn.CTCLoss,
    tokenizer: Tokenizer,
    device: torch.device,
) -> tuple[float, float]:
    """Run validation and return ``(val_loss, val_cer)``."""
    model.eval()
    loss_sum = 0.0
    sample_count = 0
    all_refs: list[str] = []
    all_hyps: list[str] = []

    with torch.no_grad():
        for batch in val_loader:
            feats = batch["feats"].to(device)
            feat_lengths = batch["feat_lengths"].to(device)
            targets = batch["targets"].to(device)
            target_lengths = batch["target_lengths"].to(device)
            texts: list[str] = batch["texts"]

            log_probs, out_lengths = model(feats, feat_lengths)
            loss = criterion(
                log_probs.transpose(0, 1),
                targets,
                out_lengths,
                target_lengths,
            )
            bsz = int(feats.size(0))
            if torch.isfinite(loss):
                loss_sum += float(loss.item()) * bsz
                sample_count += bsz

            lp_np = log_probs.detach().cpu().numpy()
            out_lens = out_lengths.detach().cpu().tolist()
            for i, ref_text in enumerate(texts):
                valid_len = int(out_lens[i])
                lp_i = lp_np[i, :valid_len]
                hyp_text = greedy_decode(lp_i, tokenizer)["text"]
                all_refs.append(ref_text)
                all_hyps.append(hyp_text)

    val_loss = loss_sum / sample_count if sample_count > 0 else 0.0
    val_cer = float(compute_cer(all_refs, all_hyps)["cer"]) if all_refs else 1.0
    return val_loss, val_cer


def train_asr(
    train_manifest: str | Path,
    val_manifest: str | Path,
    *,
    audio_cfg: AudioConfig | None = None,
    model_cfg: ModelConfig | None = None,
    train_cfg: TrainConfig | None = None,
    tokenizer: Tokenizer | None = None,
    resume_from: str | Path | None = None,
) -> dict[str, Any]:
    """Train a CTC acoustic model on JSONL manifests and save ``best.pt`` / ``latest.pt``.

    Args:
        train_manifest: Path to training JSONL manifest.
        val_manifest: Path to validation JSONL manifest.
        audio_cfg: Acoustic feature configuration (defaults to ``AudioConfig()``).
        model_cfg: Model architecture configuration (defaults to ``ModelConfig()``).
        train_cfg: Training hyperparameters (defaults to ``TrainConfig()``).
        tokenizer: CTC tokenizer (defaults to ``Tokenizer("kana")``).
        resume_from: Optional path to an existing checkpoint to resume training from.

    Returns:
        Summary metrics dict including ``best_checkpoint``, ``latest_checkpoint``,
        ``best_val_cer``, ``final_train_loss``, ``final_val_loss``, ``final_val_cer``,
        ``epochs_completed``, and ``history``.
    """
    audio_cfg = audio_cfg if audio_cfg is not None else AudioConfig()
    model_cfg = model_cfg if model_cfg is not None else ModelConfig()
    train_cfg = train_cfg if train_cfg is not None else TrainConfig()
    tokenizer = tokenizer if tokenizer is not None else Tokenizer("kana")

    if audio_cfg.n_mels != model_cfg.n_mels:
        raise ValueError(
            f"audio_cfg.n_mels ({audio_cfg.n_mels}) must match "
            f"model_cfg.n_mels ({model_cfg.n_mels})"
        )

    # CPU-friendly thread count (avoid set_num_interop_threads which errors if called twice).
    torch.set_num_threads(min(2, os.cpu_count() or 1))
    _seed_everything(train_cfg.seed)

    device = torch.device("cpu")

    base_train_ds = ASRManifestDataset(
        train_manifest,
        audio_cfg=audio_cfg,
        tokenizer=tokenizer,
        augment=False,
    )
    train_ds: Dataset = (
        _SeededSpecAugmentDataset(base_train_ds, seed=train_cfg.seed)
        if train_cfg.use_spec_augment
        else base_train_ds
    )
    val_ds = ASRManifestDataset(
        val_manifest,
        audio_cfg=audio_cfg,
        tokenizer=tokenizer,
        augment=False,
    )
    if len(train_ds) == 0:
        raise ValueError(f"Training manifest is empty: {train_manifest}")
    if len(val_ds) == 0:
        raise ValueError(f"Validation manifest is empty: {val_manifest}")

    loader_gen = torch.Generator()
    loader_gen.manual_seed(train_cfg.seed)

    train_loader = DataLoader(
        train_ds,
        batch_size=train_cfg.batch_size,
        shuffle=True,
        num_workers=0,
        collate_fn=collate_asr_batch,
        generator=loader_gen,
        drop_last=False,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=train_cfg.batch_size,
        shuffle=False,
        num_workers=0,
        collate_fn=collate_asr_batch,
        drop_last=False,
    )

    model = build_model(model_cfg, vocab_size=tokenizer.vocab_size).to(device)
    criterion = nn.CTCLoss(
        blank=tokenizer.blank_id,
        reduction="mean",
        zero_infinity=True,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=train_cfg.lr,
        weight_decay=train_cfg.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max(1, train_cfg.epochs),
        eta_min=train_cfg.lr * 0.01,
    )

    ckpt_dir = Path(train_cfg.checkpoint_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    best_path = ckpt_dir / "best.pt"
    latest_path = ckpt_dir / "latest.pt"

    history: list[dict[str, Any]] = []
    best_val_cer: float = float("inf")
    best_val_loss: float = float("inf")
    start_epoch = 1

    if resume_from is not None:
        ckpt = load_checkpoint(resume_from, device="cpu")
        if ckpt["model_config"] != model_cfg.to_dict():
            raise ValueError(
                "Incompatible model_config in resume checkpoint: "
                f"expected {model_cfg.to_dict()}, got {ckpt['model_config']}"
            )
        ckpt_tok = ckpt.get("tokenizer")
        if not isinstance(ckpt_tok, Mapping):
            raise ValueError(
                "Invalid tokenizer metadata in resume checkpoint: "
                f"expected mapping, got {type(ckpt_tok).__name__}"
            )
        ckpt_tok_vocab = ckpt_tok.get("vocab")
        if not isinstance(ckpt_tok_vocab, list) or ckpt_tok_vocab != tokenizer.vocab:
            raise ValueError(
                "Incompatible tokenizer vocabulary in resume checkpoint: "
                f"expected {len(tokenizer.vocab)} tokens matching current tokenizer"
            )
        ckpt_tok_mode = ckpt_tok.get("mode")
        if ckpt_tok_mode is not None and ckpt_tok_mode != tokenizer.mode:
            raise ValueError(
                "Incompatible tokenizer mode in resume checkpoint: "
                f"expected {tokenizer.mode!r}, got {ckpt_tok_mode!r}"
            )

        try:
            model.load_state_dict(ckpt["model_state_dict"])
            if "optimizer_state_dict" in ckpt:
                if not isinstance(ckpt["optimizer_state_dict"], Mapping):
                    raise ValueError(
                        "Invalid 'optimizer_state_dict' in resume checkpoint: "
                        f"expected mapping, got {type(ckpt['optimizer_state_dict']).__name__}"
                    )
                optimizer.load_state_dict(ckpt["optimizer_state_dict"])
            if "scheduler_state_dict" in ckpt:
                if not isinstance(ckpt["scheduler_state_dict"], Mapping):
                    raise ValueError(
                        "Invalid 'scheduler_state_dict' in resume checkpoint: "
                        f"expected mapping, got {type(ckpt['scheduler_state_dict']).__name__}"
                    )
                scheduler.load_state_dict(ckpt["scheduler_state_dict"])
            scheduler.T_max = max(1, train_cfg.epochs)

            raw_history = ckpt.get("history", [])
            if not isinstance(raw_history, list):
                raise ValueError(
                    "Invalid 'history' in resume checkpoint: expected a list of mappings"
                )
            history = []
            for idx, entry in enumerate(raw_history):
                if not isinstance(entry, Mapping):
                    raise ValueError(
                        "Invalid 'history' in resume checkpoint: expected a list of mappings"
                    )
                norm_entry = dict(entry)
                for req_key in ("epoch", "train_loss", "val_loss", "val_cer"):
                    if req_key not in norm_entry:
                        raise ValueError(
                            f"Invalid 'history[{idx}]' in resume checkpoint: missing key {req_key!r}"
                        )
                    val = norm_entry[req_key]
                    if isinstance(val, bool) or not isinstance(val, (int, float, np.number)):
                        raise ValueError(
                            f"Invalid 'history[{idx}][{req_key!r}]' in resume checkpoint: {val!r}"
                        )
                    fval = float(val)
                    if not math.isfinite(fval):
                        raise ValueError(
                            f"Non-finite 'history[{idx}][{req_key!r}]' in resume checkpoint: {val!r}"
                        )
                    if req_key == "epoch" and (
                        not isinstance(val, (int, np.integer)) or int(val) < 0
                    ):
                        raise ValueError(
                            f"Invalid 'history[{idx}][\"epoch\"]' in resume checkpoint: {val!r}"
                        )
                history.append(norm_entry)

            raw_best_cer = ckpt.get("best_val_cer", float("inf"))
            if isinstance(raw_best_cer, bool) or not isinstance(
                raw_best_cer, (int, float, np.number)
            ):
                raise ValueError(f"Invalid 'best_val_cer': {raw_best_cer!r}")
            best_val_cer = float(raw_best_cer)
            if math.isnan(best_val_cer) or best_val_cer < 0.0:
                raise ValueError(f"Invalid 'best_val_cer': {raw_best_cer!r}")
            matching_losses = [
                float(h["val_loss"])
                for h in history
                if "val_cer" in h and "val_loss" in h and float(h["val_cer"]) == best_val_cer
            ]
            if matching_losses:
                best_val_loss = min(matching_losses)

            raw_epoch = ckpt.get("epoch", len(history))
            if (
                isinstance(raw_epoch, bool)
                or not isinstance(raw_epoch, (int, np.integer))
                or int(raw_epoch) < 0
            ):
                raise ValueError(f"Invalid 'epoch': {raw_epoch!r}")
            start_epoch = int(raw_epoch) + 1
        except (RuntimeError, TypeError, ValueError, KeyError, AttributeError) as exc:
            raise ValueError(
                f"Corrupt or incompatible resume checkpoint '{resume_from}': {exc}"
            ) from exc

    def _build_ckpt(epoch_num: int) -> dict[str, Any]:
        audio_dict = audio_cfg.to_dict()
        return {
            "epoch": int(epoch_num),
            "best_val_cer": float(best_val_cer),
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "model_config": model_cfg.to_dict(),
            "audio_config": audio_dict,
            "audio_cfg": dict(audio_dict),
            "train_config": train_cfg.to_dict(),
            "tokenizer": tokenizer.to_dict(),
            "history": [dict(entry) for entry in history],
        }

    if resume_from is not None and not best_path.exists():
        _atomic_torch_save(_build_ckpt(start_epoch - 1), best_path)

    for epoch in range(start_epoch, train_cfg.epochs + 1):
        model.train()
        train_loss_sum = 0.0
        train_samples = 0
        epoch_lr = float(optimizer.param_groups[0]["lr"])

        for batch in train_loader:
            feats = batch["feats"].to(device)
            feat_lengths = batch["feat_lengths"].to(device)
            targets = batch["targets"].to(device)
            target_lengths = batch["target_lengths"].to(device)

            log_probs, out_lengths = model(feats, feat_lengths)
            loss = criterion(
                log_probs.transpose(0, 1),
                targets,
                out_lengths,
                target_lengths,
            )
            if not torch.isfinite(loss):
                continue

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            if train_cfg.grad_clip > 0.0:
                torch.nn.utils.clip_grad_norm_(
                    model.parameters(),
                    max_norm=train_cfg.grad_clip,
                )
            optimizer.step()

            bsz = int(feats.size(0))
            train_loss_sum += float(loss.item()) * bsz
            train_samples += bsz

        scheduler.step()

        train_loss = train_loss_sum / train_samples if train_samples > 0 else 0.0
        val_loss, val_cer = _evaluate_epoch(
            model,
            val_loader,
            criterion,
            tokenizer,
            device,
        )

        history.append(
            {
                "epoch": int(epoch),
                "train_loss": float(train_loss),
                "val_loss": float(val_loss),
                "val_cer": float(val_cer),
                "lr": float(epoch_lr),
            }
        )

        improved = (val_cer < best_val_cer) or (
            val_cer == best_val_cer and val_loss < best_val_loss
        )
        is_best = improved or (resume_from is None and not best_path.exists())
        if is_best:
            best_val_cer = float(val_cer)
            best_val_loss = float(val_loss)

        ckpt_payload = _build_ckpt(epoch)
        _atomic_torch_save(ckpt_payload, latest_path)
        if is_best:
            _atomic_torch_save(ckpt_payload, best_path)

    # If resumed with train_cfg.epochs <= ckpt["epoch"], ensure checkpoints exist in checkpoint_dir.
    if start_epoch > train_cfg.epochs:
        resumed_epoch = start_epoch - 1
        ckpt_payload = _build_ckpt(resumed_epoch)
        if not latest_path.exists():
            _atomic_torch_save(ckpt_payload, latest_path)
        if not best_path.exists():
            _atomic_torch_save(ckpt_payload, best_path)

    epochs_completed = int(history[-1]["epoch"]) if history else 0
    final_train_loss = float(history[-1]["train_loss"]) if history else 0.0
    final_val_loss = float(history[-1]["val_loss"]) if history else 0.0
    final_val_cer = float(history[-1]["val_cer"]) if history else 1.0

    return {
        "best_checkpoint": str(best_path),
        "latest_checkpoint": str(latest_path),
        "best_val_cer": float(best_val_cer if best_val_cer < float("inf") else 1.0),
        "final_train_loss": final_train_loss,
        "final_val_loss": final_val_loss,
        "final_val_cer": final_val_cer,
        "epochs_completed": epochs_completed,
        "history": history,
    }
