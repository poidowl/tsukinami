"""Conv2dSubsampling + Bidirectional GRU CTC acoustic model."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from asr.config import AudioConfig, ModelConfig
from asr.models.subsampling import Conv2dSubsampling

__all__ = ["CNNBiGRUCTC"]


class CNNBiGRUCTC(nn.Module):
    """Compact CPU-trainable CNN + BiGRU CTC acoustic model (~0.46M params default)."""

    subsampling_factor: int = Conv2dSubsampling.subsampling_factor

    def __init__(
        self,
        cfg: ModelConfig,
        vocab_size: int,
        *,
        conv_channels: int = 32,
    ) -> None:
        super().__init__()
        if isinstance(vocab_size, bool) or not isinstance(vocab_size, int) or vocab_size < 2:
            raise ValueError(f"vocab_size must be an int >= 2, got {vocab_size!r}")

        self.cfg = cfg
        self.vocab_size = vocab_size
        self.n_mels = cfg.n_mels

        self.subsampling = Conv2dSubsampling(
            in_features=cfg.n_mels,
            out_features=cfg.hidden_size,
            conv_channels=conv_channels,
            dropout=cfg.dropout,
        )

        gru_hidden = max(1, cfg.hidden_size // 2)
        self.gru_hidden = gru_hidden
        self.gru = nn.GRU(
            input_size=cfg.hidden_size,
            hidden_size=gru_hidden,
            num_layers=cfg.num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=cfg.dropout if cfg.num_layers > 1 else 0.0,
        )

        encoder_dim = 2 * gru_hidden
        self.post_norm = nn.LayerNorm(encoder_dim)
        self.dropout = nn.Dropout(cfg.dropout)
        self.classifier = nn.Linear(encoder_dim, vocab_size)

    def output_frame_stride_ms(self, audio_cfg: AudioConfig) -> float:
        """Return the time stride in milliseconds between consecutive output frames."""
        return (
            float(self.subsampling_factor)
            * 1000.0
            * float(audio_cfg.hop_length)
            / float(audio_cfg.sample_rate)
        )

    def forward(
        self,
        feats: torch.Tensor,
        feat_lengths: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Compute CTC frame log-probabilities ``(B, T', V)`` and valid lengths ``(B,)``."""
        x, out_lengths = self.subsampling(feats, feat_lengths)
        t_sub = x.size(1)

        packed = pack_padded_sequence(
            x,
            out_lengths.detach().cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        packed_out, _ = self.gru(packed)
        out, _ = pad_packed_sequence(
            packed_out,
            batch_first=True,
            total_length=t_sub,
        )

        out = self.dropout(self.post_norm(out))
        logits = self.classifier(out)
        log_probs = F.log_softmax(logits, dim=-1)
        return log_probs, out_lengths
