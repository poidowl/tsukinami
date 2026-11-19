"""Acoustic model factory and exports for Tsukinami ASR."""

from __future__ import annotations

import torch.nn as nn

from asr.config import ModelConfig
from asr.models.cnn_bigru import CNNBiGRUCTC
from asr.models.conformer import ConformerLiteCTC
from asr.models.subsampling import Conv2dSubsampling

__all__ = [
    "Conv2dSubsampling",
    "CNNBiGRUCTC",
    "ConformerLiteCTC",
    "build_model",
]


def build_model(cfg: ModelConfig, vocab_size: int) -> nn.Module:
    """Instantiate an acoustic CTC model from a ``ModelConfig`` and ``vocab_size``.

    Supported architectures: ``"cnn_bigru"`` and ``"conformer_lite"``.
    Raises ``ValueError`` on unknown architecture or invalid ``vocab_size``.
    """
    if isinstance(vocab_size, bool) or not isinstance(vocab_size, int) or vocab_size < 2:
        raise ValueError(f"vocab_size must be an int >= 2, got {vocab_size!r}")

    arch = getattr(cfg, "arch", None)
    if arch == "cnn_bigru":
        return CNNBiGRUCTC(cfg, vocab_size=vocab_size)
    if arch == "conformer_lite":
        return ConformerLiteCTC(cfg, vocab_size=vocab_size)
    raise ValueError(
        f"Unknown model architecture {arch!r}; expected one of ('cnn_bigru', 'conformer_lite')"
    )
