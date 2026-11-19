"""Conformer-Lite CTC acoustic model with Macaron FFN, Masked MHSA, and ConvModule."""

from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from asr.config import AudioConfig, ModelConfig
from asr.models.subsampling import Conv2dSubsampling, make_valid_mask

__all__ = ["SinusoidalPositionalEncoding", "ConformerBlock", "ConformerLiteCTC"]


class SinusoidalPositionalEncoding(nn.Module):
    """Non-persistent sinusoidal positional encoding that dynamically extends to any length."""

    def __init__(self, d_model: int, max_len: int = 1024) -> None:
        super().__init__()
        if d_model < 1:
            raise ValueError(f"d_model must be >= 1, got {d_model}")
        if max_len < 1:
            raise ValueError(f"max_len must be >= 1, got {max_len}")
        self.d_model = d_model
        pe = self._build_pe(max_len, d_model, device=torch.device("cpu"), dtype=torch.float32)
        self.register_buffer("pe", pe, persistent=False)

    @staticmethod
    def _build_pe(
        length: int,
        d_model: int,
        *,
        device: torch.device,
        dtype: torch.dtype,
    ) -> torch.Tensor:
        pe = torch.zeros(1, length, d_model, device=device, dtype=dtype)
        position = torch.arange(length, device=device, dtype=dtype).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2, device=device, dtype=dtype)
            * (-math.log(10000.0) / float(d_model))
        )
        pe[0, :, 0::2] = torch.sin(position * div_term)
        if d_model > 1:
            pe[0, :, 1::2] = torch.cos(position * div_term[: d_model // 2])
        return pe

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        seq_len = x.size(1)
        if (
            seq_len > self.pe.size(1)
            or self.pe.device != x.device
            or self.pe.dtype != x.dtype
        ):
            new_len = max(seq_len, self.pe.size(1) * 2 if seq_len > self.pe.size(1) else self.pe.size(1))
            self.pe = self._build_pe(new_len, self.d_model, device=x.device, dtype=x.dtype)
        return x + self.pe[:, :seq_len, :]


class _FeedForwardModule(nn.Module):
    """Pre-norm Swish feed-forward module used in Macaron Conformer blocks."""

    def __init__(self, d_model: int, expansion_factor: int = 2, dropout: float = 0.1) -> None:
        super().__init__()
        inner_dim = d_model * expansion_factor
        self.layer_norm = nn.LayerNorm(d_model)
        self.linear1 = nn.Linear(d_model, inner_dim)
        self.activation = nn.SiLU()
        self.dropout1 = nn.Dropout(dropout)
        self.linear2 = nn.Linear(inner_dim, d_model)
        self.dropout2 = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.layer_norm(x)
        h = self.dropout1(self.activation(self.linear1(h)))
        h = self.dropout2(self.linear2(h))
        return h


class _ConformerConvModule(nn.Module):
    """Depthwise separable Conformer convolution module with strict padding masking.

    Uses per-frame ``LayerNorm(d_model)`` after the depthwise convolution rather than
    ``BatchNorm1d`` or ``GroupNorm`` so that ``(B=1, T'=1)`` trains cleanly and valid
    frames remain strictly invariant to padded batch length.
    """

    def __init__(
        self,
        d_model: int,
        kernel_size: int = 15,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if kernel_size < 1:
            raise ValueError(f"kernel_size must be >= 1, got {kernel_size}")
        self.kernel_size = kernel_size
        self.layer_norm = nn.LayerNorm(d_model)
        self.pointwise_conv1 = nn.Conv1d(d_model, 2 * d_model, kernel_size=1)
        if kernel_size % 2 == 1:
            self._asymmetric_pad: tuple[int, int] | None = None
            dw_padding = kernel_size // 2
        else:
            self._asymmetric_pad = ((kernel_size - 1) // 2, kernel_size // 2)
            dw_padding = 0
        self.depthwise_conv = nn.Conv1d(
            d_model,
            d_model,
            kernel_size=kernel_size,
            groups=d_model,
            padding=dw_padding,
        )
        self.norm = nn.LayerNorm(d_model)
        self.activation = nn.SiLU()
        self.pointwise_conv2 = nn.Conv1d(d_model, d_model, kernel_size=1)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, pad_mask: torch.Tensor) -> torch.Tensor:
        """Apply depthwise separable conv block to ``x: (B, T', D)``.

        Args:
            x: Input tensor ``(B, T', D)``.
            pad_mask: Boolean tensor ``(B, T')`` where ``True`` indicates padded frames.
        """
        h = self.layer_norm(x).transpose(1, 2)  # (B, D, T')
        h = F.glu(self.pointwise_conv1(h), dim=1)  # (B, D, T')

        # Mask padded positions before depthwise conv so pointwise bias cannot leak.
        h = h.masked_fill(pad_mask.unsqueeze(1), 0.0)

        if self._asymmetric_pad is not None:
            h = F.pad(h, self._asymmetric_pad)
        h = self.depthwise_conv(h)

        # Frame-wise LayerNorm over channels for exact length/padding invariance.
        h = self.norm(h.transpose(1, 2)).transpose(1, 2)
        h = self.activation(h)
        h = self.dropout(self.pointwise_conv2(h)).transpose(1, 2)
        h = h.masked_fill(pad_mask.unsqueeze(-1), 0.0)
        return h


class ConformerBlock(nn.Module):
    """Single Macaron Conformer block: FFN/2 -> MHSA -> ConvModule -> FFN/2 -> LayerNorm."""

    def __init__(
        self,
        d_model: int,
        num_heads: int,
        conv_kernel_size: int = 15,
        ffn_expansion: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.ffn1 = _FeedForwardModule(d_model, expansion_factor=ffn_expansion, dropout=dropout)
        self.mha_norm = nn.LayerNorm(d_model)
        self.mha = nn.MultiheadAttention(
            embed_dim=d_model,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.mha_dropout = nn.Dropout(dropout)
        self.conv_module = _ConformerConvModule(
            d_model=d_model,
            kernel_size=conv_kernel_size,
            dropout=dropout,
        )
        self.ffn2 = _FeedForwardModule(d_model, expansion_factor=ffn_expansion, dropout=dropout)
        self.final_norm = nn.LayerNorm(d_model)

    def forward(self, x: torch.Tensor, pad_mask: torch.Tensor) -> torch.Tensor:
        x = x + 0.5 * self.ffn1(x)

        h = self.mha_norm(x)
        attn_out, _ = self.mha(
            h,
            h,
            h,
            key_padding_mask=pad_mask,
            need_weights=False,
        )
        x = x + self.mha_dropout(attn_out)

        x = x + self.conv_module(x, pad_mask)
        x = x + 0.5 * self.ffn2(x)
        x = self.final_norm(x)
        x = x.masked_fill(pad_mask.unsqueeze(-1), 0.0)
        return x


class ConformerLiteCTC(nn.Module):
    """Lightweight CPU-trainable Conformer-CTC acoustic model (~1.25M params default)."""

    subsampling_factor: int = Conv2dSubsampling.subsampling_factor

    def __init__(
        self,
        cfg: ModelConfig,
        vocab_size: int,
        *,
        ffn_expansion: int = 2,
        conv_channels: int = 32,
    ) -> None:
        super().__init__()
        if isinstance(vocab_size, bool) or not isinstance(vocab_size, int) or vocab_size < 2:
            raise ValueError(f"vocab_size must be an int >= 2, got {vocab_size!r}")
        if cfg.hidden_size % cfg.num_heads != 0:
            raise ValueError(
                f"hidden_size ({cfg.hidden_size}) must be divisible by num_heads ({cfg.num_heads})"
            )

        self.cfg = cfg
        self.vocab_size = vocab_size
        self.n_mels = cfg.n_mels
        self.d_model = cfg.hidden_size

        self.subsampling = Conv2dSubsampling(
            in_features=cfg.n_mels,
            out_features=cfg.hidden_size,
            conv_channels=conv_channels,
            dropout=0.0,
        )
        self.pos_enc = SinusoidalPositionalEncoding(d_model=cfg.hidden_size, max_len=1024)
        self.input_dropout = nn.Dropout(cfg.dropout)

        self.blocks = nn.ModuleList(
            [
                ConformerBlock(
                    d_model=cfg.hidden_size,
                    num_heads=cfg.num_heads,
                    conv_kernel_size=cfg.conv_kernel_size,
                    ffn_expansion=ffn_expansion,
                    dropout=cfg.dropout,
                )
                for _ in range(cfg.num_layers)
            ]
        )
        self.out_proj = nn.Linear(cfg.hidden_size, vocab_size)

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

        pad_mask = ~make_valid_mask(out_lengths, t_sub)  # True = padded
        x = self.input_dropout(self.pos_enc(x))
        x = x.masked_fill(pad_mask.unsqueeze(-1), 0.0)

        for block in self.blocks:
            x = block(x, pad_mask)

        logits = self.out_proj(x)
        log_probs = F.log_softmax(logits, dim=-1)
        return log_probs, out_lengths
