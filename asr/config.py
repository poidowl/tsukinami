"""Configuration dataclasses for Tsukinami ASR."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any, TypeVar

T = TypeVar("T", bound="_ConfigBase")

VALID_MODEL_ARCHS = ("cnn_bigru", "conformer_lite")
VALID_DECODE_METHODS = ("greedy", "beam")


def _check_int(
    name: str,
    val: Any,
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> None:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{name} must be an int, got {type(val).__name__}: {val!r}")
    if min_val is not None and val < min_val:
        raise ValueError(f"{name} must be >= {min_val}, got {val}")
    if max_val is not None and val > max_val:
        raise ValueError(f"{name} must be <= {max_val}, got {val}")


def _check_float(
    name: str,
    val: Any,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    min_inclusive: bool = True,
    max_inclusive: bool = True,
) -> None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"{name} must be a real number, got {type(val).__name__}: {val!r}")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValueError(f"{name} must be finite, got {val!r}")
    if min_val is not None:
        if min_inclusive and fval < min_val:
            raise ValueError(f"{name} must be >= {min_val}, got {val}")
        if not min_inclusive and fval <= min_val:
            raise ValueError(f"{name} must be > {min_val}, got {val}")
    if max_val is not None:
        if max_inclusive and fval > max_val:
            raise ValueError(f"{name} must be <= {max_val}, got {val}")
        if not max_inclusive and fval >= max_val:
            raise ValueError(f"{name} must be < {max_val}, got {val}")


def _check_bool(name: str, val: Any) -> None:
    if not isinstance(val, bool):
        raise ValueError(f"{name} must be a bool, got {type(val).__name__}: {val!r}")


class _ConfigBase:
    """Mixin providing JSON-friendly .to_dict() and validated .from_dict()."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls: type[T], data: Mapping[str, Any]) -> T:
        if not isinstance(data, Mapping):
            raise TypeError(
                f"Expected mapping for {cls.__name__}.from_dict, got {type(data).__name__}"
            )
        valid_keys = {f.name for f in fields(cls)}
        unknown = sorted(set(data.keys()) - valid_keys)
        if unknown:
            raise ValueError(f"Unknown {cls.__name__} field(s): {unknown}")
        return cls(**dict(data))


@dataclass
class AudioConfig(_ConfigBase):
    sample_rate: int = 16000
    n_fft: int = 512
    win_length: int = 400
    hop_length: int = 160
    n_mels: int = 64
    f_min: float = 80.0
    f_max: float = 7600.0
    preemphasis: float = 0.97
    cmvn: bool = True

    def __post_init__(self) -> None:
        _check_int("sample_rate", self.sample_rate, min_val=1)
        _check_int("n_fft", self.n_fft, min_val=1)
        _check_int("win_length", self.win_length, min_val=1)
        _check_int("hop_length", self.hop_length, min_val=1)
        _check_int("n_mels", self.n_mels, min_val=1)
        if self.win_length > self.n_fft:
            raise ValueError(
                f"win_length ({self.win_length}) must be <= n_fft ({self.n_fft})"
            )
        _check_float("f_min", self.f_min, min_val=0.0)
        _check_float("f_max", self.f_max, max_val=self.sample_rate / 2.0)
        if self.f_min >= self.f_max:
            raise ValueError(
                f"f_min ({self.f_min}) must be < f_max ({self.f_max})"
            )
        _check_float(
            "preemphasis",
            self.preemphasis,
            min_val=0.0,
            max_val=1.0,
            min_inclusive=True,
            max_inclusive=False,
        )
        _check_bool("cmvn", self.cmvn)
        self.f_min = float(self.f_min)
        self.f_max = float(self.f_max)
        self.preemphasis = float(self.preemphasis)


@dataclass
class ModelConfig(_ConfigBase):
    arch: str = "cnn_bigru"
    n_mels: int = 64
    hidden_size: int = 192
    num_layers: int = 2
    dropout: float = 0.1
    num_heads: int = 4
    conv_kernel_size: int = 15

    def __post_init__(self) -> None:
        if self.arch not in VALID_MODEL_ARCHS:
            raise ValueError(
                f"arch must be one of {VALID_MODEL_ARCHS}, got {self.arch!r}"
            )
        _check_int("n_mels", self.n_mels, min_val=1)
        _check_int("hidden_size", self.hidden_size, min_val=1)
        _check_int("num_layers", self.num_layers, min_val=1)
        _check_int("num_heads", self.num_heads, min_val=1)
        _check_float(
            "dropout",
            self.dropout,
            min_val=0.0,
            max_val=1.0,
            min_inclusive=True,
            max_inclusive=False,
        )
        _check_int("conv_kernel_size", self.conv_kernel_size, min_val=1)
        if self.conv_kernel_size % 2 != 1:
            raise ValueError(
                f"conv_kernel_size must be odd, got {self.conv_kernel_size}"
            )
        if self.arch == "conformer_lite" and self.hidden_size % self.num_heads != 0:
            raise ValueError(
                f"For conformer_lite, hidden_size ({self.hidden_size}) must be "
                f"divisible by num_heads ({self.num_heads})"
            )
        self.dropout = float(self.dropout)


@dataclass
class TrainConfig(_ConfigBase):
    epochs: int = 20
    batch_size: int = 16
    lr: float = 3e-3
    weight_decay: float = 1e-4
    grad_clip: float = 5.0
    seed: int = 42
    use_spec_augment: bool = True
    checkpoint_dir: str = "checkpoints"

    def __post_init__(self) -> None:
        _check_int("epochs", self.epochs, min_val=1)
        _check_int("batch_size", self.batch_size, min_val=1)
        _check_float("lr", self.lr, min_val=0.0, min_inclusive=False)
        _check_float("weight_decay", self.weight_decay, min_val=0.0)
        _check_float("grad_clip", self.grad_clip, min_val=0.0)
        _check_int("seed", self.seed, min_val=0, max_val=2**32 - 1)
        _check_bool("use_spec_augment", self.use_spec_augment)
        if not isinstance(self.checkpoint_dir, str) or not self.checkpoint_dir.strip():
            raise ValueError(
                f"checkpoint_dir must be a non-empty string, got {self.checkpoint_dir!r}"
            )
        self.lr = float(self.lr)
        self.weight_decay = float(self.weight_decay)
        self.grad_clip = float(self.grad_clip)


@dataclass
class DecodeConfig(_ConfigBase):
    method: str = "beam"
    beam_width: int = 8
    temperature: float = 1.0
    blank_bias: float = 0.0
    lm_weight: float = 0.0
    insertion_bonus: float = 0.0

    def __post_init__(self) -> None:
        if self.method not in VALID_DECODE_METHODS:
            raise ValueError(
                f"method must be one of {VALID_DECODE_METHODS}, got {self.method!r}"
            )
        _check_int("beam_width", self.beam_width, min_val=1)
        _check_float("temperature", self.temperature, min_val=0.0, min_inclusive=False)
        _check_float("blank_bias", self.blank_bias)
        _check_float("lm_weight", self.lm_weight, min_val=0.0)
        _check_float("insertion_bonus", self.insertion_bonus)
        self.temperature = float(self.temperature)
        self.blank_bias = float(self.blank_bias)
        self.lm_weight = float(self.lm_weight)
        self.insertion_bonus = float(self.insertion_bonus)
