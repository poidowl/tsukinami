"""2D convolutional subsampling front-end with 4x time reduction and strict padding masking."""

from __future__ import annotations

import torch
import torch.nn as nn

__all__ = ["Conv2dSubsampling", "make_valid_mask"]


def _conv_out_length(lengths: torch.Tensor) -> torch.Tensor:
    """Exact output length for Conv2d(kernel_size=3, stride=2, padding=1)."""
    return torch.where(lengths > 0, (lengths + 1) // 2, torch.zeros_like(lengths))


def make_valid_mask(lengths: torch.Tensor, max_len: int) -> torch.Tensor:
    """Return boolean mask of shape ``(B, max_len)`` where ``True`` marks valid frames."""
    positions = torch.arange(max_len, device=lengths.device).unsqueeze(0)
    return positions < lengths.unsqueeze(1)


class Conv2dSubsampling(nn.Module):
    """Two-layer stride-2 Conv2d front-end (4x time and frequency subsampling).

    Uses ``kernel_size=3, stride=2, padding=1`` without BatchNorm2d, combined with
    3-point zero-masking (before conv1, after conv1, after conv2/out_proj) to
    guarantee exact masking invariance on valid frames even for short inputs
    (``T >= 1``).
    """

    subsampling_factor: int = 4

    def __init__(
        self,
        in_features: int,
        out_features: int,
        conv_channels: int = 32,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        if isinstance(in_features, bool) or not isinstance(in_features, int) or in_features < 1:
            raise ValueError(f"in_features must be an int >= 1, got {in_features!r}")
        if isinstance(out_features, bool) or not isinstance(out_features, int) or out_features < 1:
            raise ValueError(f"out_features must be an int >= 1, got {out_features!r}")
        if isinstance(conv_channels, bool) or not isinstance(conv_channels, int) or conv_channels < 1:
            raise ValueError(f"conv_channels must be an int >= 1, got {conv_channels!r}")
        if isinstance(dropout, bool) or not isinstance(dropout, (int, float)) or not (0.0 <= float(dropout) < 1.0):
            raise ValueError(f"dropout must be in [0.0, 1.0), got {dropout!r}")

        self.in_features = in_features
        self.out_features = out_features
        self.conv_channels = conv_channels

        self.conv1 = nn.Conv2d(1, conv_channels, kernel_size=3, stride=2, padding=1)
        self.act1 = nn.ReLU()
        self.conv2 = nn.Conv2d(conv_channels, conv_channels, kernel_size=3, stride=2, padding=1)
        self.act2 = nn.ReLU()

        freq_out = ((in_features + 1) // 2 + 1) // 2
        self.freq_out = freq_out
        self.out_proj = nn.Linear(conv_channels * freq_out, out_features)
        self.dropout = nn.Dropout(float(dropout))

    def output_lengths(self, feat_lengths: torch.Tensor) -> torch.Tensor:
        """Compute exact subsampled frame lengths: ``(L + 3) // 4`` for ``L >= 1``, else ``0``."""
        lengths = feat_lengths.to(dtype=torch.long)
        return _conv_out_length(_conv_out_length(lengths))

    def forward(
        self,
        feats: torch.Tensor,
        feat_lengths: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Subsample acoustic features from ``(B, T, F)`` to ``(B, T', out_features)``.

        Args:
            feats: Float tensor of shape ``(B, T, in_features)``.
            feat_lengths: Integer tensor of shape ``(B,)`` with values in ``[1, T]``.

        Returns:
            Tuple of ``(subsampled_feats, out_lengths)``.
        """
        if feats.ndim != 3:
            raise ValueError(f"feats must be 3D (B, T, F), got shape {tuple(feats.shape)}")
        batch_size, max_t, feat_dim = feats.shape
        if batch_size < 1 or max_t < 1:
            raise ValueError(f"feats must have B >= 1 and T >= 1, got shape {tuple(feats.shape)}")
        if feat_dim != self.in_features:
            raise ValueError(
                f"Expected feats feature dim {self.in_features}, got {feat_dim}"
            )
        if feat_lengths.ndim != 1 or feat_lengths.size(0) != batch_size:
            raise ValueError(
                f"feat_lengths must be 1D of length {batch_size}, got shape {tuple(feat_lengths.shape)}"
            )

        lengths = feat_lengths.to(device=feats.device, dtype=torch.long)
        if bool((lengths < 1).any()) or bool((lengths > max_t).any()):
            raise ValueError(
                f"feat_lengths must satisfy 1 <= length <= {max_t}, got {lengths.tolist()}"
            )

        # Point 1: Zero-mask padded input frames before conv1.
        valid0 = make_valid_mask(lengths, max_t).unsqueeze(-1)
        x = feats.masked_fill(~valid0, 0.0)

        # Conv1: (B, 1, T, F) -> (B, C, T1, F1)
        x = self.act1(self.conv1(x.unsqueeze(1)))
        l1 = _conv_out_length(lengths)
        # Point 2: Zero-mask frames >= l1 so conv1 bias/receptive field cannot leak into conv2.
        valid1 = make_valid_mask(l1, x.size(2)).unsqueeze(1).unsqueeze(-1)
        x = x.masked_fill(~valid1, 0.0)

        # Conv2: (B, C, T1, F1) -> (B, C, T2, F2)
        x = self.act2(self.conv2(x))
        l2 = _conv_out_length(l1)
        valid2 = make_valid_mask(l2, x.size(2)).unsqueeze(1).unsqueeze(-1)
        x = x.masked_fill(~valid2, 0.0)

        # Flatten channel & frequency dims: (B, T2, C * F2) -> (B, T2, out_features)
        b, c, t2, f2 = x.shape
        x = x.transpose(1, 2).contiguous().view(b, t2, c * f2)
        x = self.dropout(self.out_proj(x))

        # Point 3: Zero-mask padded output frames after out_proj (which has a bias).
        valid_out = make_valid_mask(l2, t2).unsqueeze(-1)
        x = x.masked_fill(~valid_out, 0.0)

        return x, l2
