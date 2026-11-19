"""High-level ASR inference engine with LRU posterior caching and visual payloads."""

from __future__ import annotations

import math
import pickle
import struct
import threading
import time
import uuid
import zipfile
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn

from asr.audio import detect_vad, resample
from asr.config import AudioConfig, DecodeConfig, ModelConfig
from asr.decoding import (
    CharNgramLM,
    greedy_decode,
    prefix_beam_search,
    viterbi_align,
)
from asr.features import extract_log_mel
from asr.metrics import compute_rtf
from asr.models import build_model
from asr.synth_data import DEFAULT_TSUKINAMI_PRESETS
from asr.tokenizer import Tokenizer
from asr.train import load_checkpoint

__all__ = ["ASREngine"]

_MAX_WAVEFORM_POINTS = 2000
_MAX_MEL_FRAMES = 600
_MAX_POSTERIOR_FRAMES = 400


@dataclass(slots=True)
class _CachedUtterance:
    log_probs: np.ndarray
    duration_sec: float
    frame_stride_ms: float


def _finite_float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.floating, np.integer)):
        fval = float(value)
        return fval if math.isfinite(fval) else None
    return None


def _sanitize_json_value(value: Any) -> Any:
    """Recursively convert values into strictly JSON-serializable Python types."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        fval = float(value)
        return fval if math.isfinite(fval) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return _sanitize_json_value(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json_value(v) for v in value]
    return str(value)


def _validate_sample_rate(sr: Any) -> int:
    if isinstance(sr, bool) or not isinstance(sr, int) or sr <= 0:
        raise ValueError(f"sr must be a positive int, got {sr!r}")
    return sr


def _prepare_waveform(wav: np.ndarray) -> np.ndarray:
    """Convert input audio to contiguous 1D float32 mono in [-1, 1] and sanitize NaN/Inf."""
    raw = np.asarray(wav)
    if np.issubdtype(raw.dtype, np.signedinteger):
        scale = float(-int(np.iinfo(raw.dtype).min))
        arr = raw.astype(np.float32) / np.float32(scale)
    elif np.issubdtype(raw.dtype, np.unsignedinteger):
        mid = float(int(np.iinfo(raw.dtype).max) + 1) / 2.0
        arr = (raw.astype(np.float32) - np.float32(mid)) / np.float32(mid)
    else:
        arr = np.asarray(raw, dtype=np.float32)

    if arr.ndim == 1:
        mono = arr
    elif arr.ndim == 2:
        if arr.shape[0] > 0 and arr.shape[0] <= 8 and arr.shape[1] > arr.shape[0]:
            mono = arr.mean(axis=0, dtype=np.float32)
        else:
            if arr.shape[1] == 0:
                raise ValueError("2D audio array must have at least 1 channel")
            mono = arr.mean(axis=-1, dtype=np.float32)
    else:
        raise ValueError(
            f"Expected 1D or 2D audio array, got shape {arr.shape} (ndim={arr.ndim})"
        )

    if mono.size > 0 and not np.all(np.isfinite(mono)):
        mono = np.nan_to_num(
            mono,
            nan=0.0,
            posinf=1.0,
            neginf=-1.0,
        ).astype(np.float32, copy=False)

    return np.ascontiguousarray(mono, dtype=np.float32)


def _downsample_waveform(wav: np.ndarray, max_points: int = _MAX_WAVEFORM_POINTS) -> list[float]:
    n = int(wav.size)
    if n == 0:
        return []
    if n > max_points:
        idx = np.linspace(0, n - 1, max_points, dtype=np.int64)
        ds = wav[idx]
    else:
        ds = wav
    return [float(x) for x in np.round(ds, 5).tolist()]


def _downsample_log_mel(mel: np.ndarray, max_frames: int = _MAX_MEL_FRAMES) -> list[list[float]]:
    if mel.size == 0 or mel.shape[0] == 0:
        return []
    t_len = int(mel.shape[0])
    if t_len > max_frames:
        idx = np.linspace(0, t_len - 1, max_frames, dtype=np.int64)
        mel_vis = mel[idx]
    else:
        mel_vis = mel
    return [[float(v) for v in row] for row in np.round(mel_vis, 4).tolist()]


def _build_ctc_posteriors(
    log_probs: np.ndarray,
    *,
    max_frames: int = _MAX_POSTERIOR_FRAMES,
) -> list[list[float]]:
    if log_probs.ndim != 2:
        return []
    t_len = int(log_probs.shape[0])
    vocab_size = int(log_probs.shape[1])
    if t_len == 0 or vocab_size == 0:
        return []

    if t_len > max_frames:
        frame_idx = np.linspace(0, t_len - 1, max_frames, dtype=np.int64)
    else:
        frame_idx = np.arange(t_len, dtype=np.int64)

    sub_lp = np.asarray(log_probs[frame_idx], dtype=np.float64)
    sub_lp = np.where(np.isfinite(sub_lp), sub_lp, -700.0)
    row_max = np.max(sub_lp, axis=-1, keepdims=True)
    shifted = np.clip(sub_lp - row_max, -700.0, 0.0)
    probs_full = np.exp(shifted)
    row_sums = probs_full.sum(axis=-1, keepdims=True)
    probs_full = np.where(
        row_sums > 0.0,
        probs_full / np.maximum(row_sums, 1e-12),
        1.0 / float(vocab_size),
    )
    probs_full = np.clip(probs_full, 0.0, 1.0)

    probs_rounded = np.round(probs_full, 6)
    return [[float(v) for v in row] for row in probs_rounded.tolist()]


class ASREngine:
    """High-level CPU inference engine with LRU cached posterior re-decoding."""

    def __init__(
        self,
        model: nn.Module,
        audio_cfg: AudioConfig,
        model_cfg: ModelConfig,
        tokenizer: Tokenizer,
        *,
        lm: CharNgramLM | None = None,
        checkpoint_meta: dict[str, Any] | None = None,
        max_cache_size: int = 32,
        device: str = "cpu",
    ) -> None:
        if isinstance(max_cache_size, bool) or not isinstance(max_cache_size, int) or max_cache_size < 1:
            raise ValueError(
                f"max_cache_size must be a positive int, got {max_cache_size!r}"
            )

        self.device = torch.device(device)
        self.model = model.to(self.device)
        self.model.eval()

        self.audio_cfg = audio_cfg
        self.model_cfg = model_cfg
        self.tokenizer = tokenizer
        self.lm = lm
        self.checkpoint_meta: dict[str, Any] = dict(checkpoint_meta) if checkpoint_meta else {}
        self.max_cache_size = max_cache_size

        if hasattr(self.model, "output_frame_stride_ms"):
            self.frame_stride_ms = float(self.model.output_frame_stride_ms(self.audio_cfg))
        else:
            sub = int(getattr(self.model, "subsampling_factor", 4))
            self.frame_stride_ms = (
                float(sub) * 1000.0 * float(self.audio_cfg.hop_length) / float(self.audio_cfg.sample_rate)
            )

        self._cache: OrderedDict[str, _CachedUtterance] = OrderedDict()
        self._cache_lock = threading.RLock()

    @classmethod
    def from_checkpoint(
        cls,
        path: str | Path,
        lm: CharNgramLM | None = None,
        *,
        device: str = "cpu",
        max_cache_size: int = 32,
    ) -> ASREngine:
        """Load an ``ASREngine`` from a saved ``.pt`` training checkpoint."""
        ckpt_path = Path(path)
        try:
            ckpt = load_checkpoint(ckpt_path, device=device)
        except (FileNotFoundError, IsADirectoryError):
            raise
        except (
            OverflowError,
            EOFError,
            IndexError,
            UnicodeDecodeError,
            pickle.PickleError,
            zipfile.BadZipFile,
            struct.error,
            RuntimeError,
        ) as exc:
            raise ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc

        try:
            raw_model_cfg = ckpt["model_config"]
            model_cfg = (
                raw_model_cfg
                if isinstance(raw_model_cfg, ModelConfig)
                else ModelConfig.from_dict(raw_model_cfg)
            )

            raw_audio_cfg = ckpt.get("audio_config") or ckpt.get("audio_cfg")
            if isinstance(raw_audio_cfg, AudioConfig):
                audio_cfg = raw_audio_cfg
            elif raw_audio_cfg is not None:
                audio_cfg = AudioConfig.from_dict(raw_audio_cfg)
            else:
                audio_cfg = AudioConfig(n_mels=model_cfg.n_mels)

            raw_tokenizer = ckpt["tokenizer"]
            tokenizer = (
                raw_tokenizer
                if isinstance(raw_tokenizer, Tokenizer)
                else Tokenizer.from_dict(raw_tokenizer)
            )

            resolved_lm = lm
            if resolved_lm is None and ckpt.get("lm") is not None:
                raw_lm = ckpt["lm"]
                resolved_lm = (
                    raw_lm
                    if isinstance(raw_lm, CharNgramLM)
                    else CharNgramLM.from_dict(raw_lm)
                )

            model = build_model(model_cfg, vocab_size=tokenizer.vocab_size)
            model.load_state_dict(ckpt["model_state_dict"])
            model.to(device)
            model.eval()
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc

        raw_history = ckpt.get("history", [])
        history = [dict(entry) for entry in raw_history] if isinstance(raw_history, list) else []

        checkpoint_meta: dict[str, Any] = {
            "checkpoint_path": str(ckpt_path),
            "epoch": ckpt.get("epoch"),
            "best_val_cer": ckpt.get("best_val_cer"),
            "train_config": ckpt.get("train_config"),
            "history": history,
        }

        return cls(
            model=model,
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            tokenizer=tokenizer,
            lm=resolved_lm,
            checkpoint_meta=checkpoint_meta,
            max_cache_size=max_cache_size,
            device=device,
        )

    def _put_cache(self, utterance_id: str, entry: _CachedUtterance) -> None:
        with self._cache_lock:
            self._cache[utterance_id] = entry
            self._cache.move_to_end(utterance_id)
            while len(self._cache) > self.max_cache_size:
                self._cache.popitem(last=False)

    def _decode_and_align(
        self,
        log_probs: np.ndarray,
        decode_cfg: DecodeConfig,
        frame_stride_ms: float,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(decode_cfg, DecodeConfig):
            raise TypeError(
                f"decode_cfg must be a DecodeConfig, got {type(decode_cfg).__name__}"
            )

        if log_probs.shape[0] == 0:
            empty_hyp = {
                "text": "",
                "score": 0.0,
                "acoustic_score": 0.0,
                "lm_score": 0.0,
            }
            return "", [empty_hyp], []

        if decode_cfg.method == "greedy":
            res = greedy_decode(
                log_probs,
                self.tokenizer,
                temperature=decode_cfg.temperature,
                blank_bias=decode_cfg.blank_bias,
            )
            text = str(res["text"])
            score = float(res["score"])
            token_ids: list[int] = [int(t) for t in res["token_ids"]]
            hypotheses = [
                {
                    "text": text,
                    "score": score,
                    "acoustic_score": score,
                    "lm_score": 0.0,
                }
            ]
        else:
            raw_hyps = prefix_beam_search(
                log_probs,
                self.tokenizer,
                decode_cfg,
                lm=self.lm,
            )
            hypotheses = [
                {
                    "text": str(h["text"]),
                    "score": float(h["score"]),
                    "acoustic_score": float(h["acoustic_score"]),
                    "lm_score": float(h["lm_score"]),
                }
                for h in raw_hyps
            ]
            text = hypotheses[0]["text"] if hypotheses else ""
            token_ids = self.tokenizer.encode(text) if text else []

        if token_ids:
            try:
                raw_align = viterbi_align(
                    log_probs,
                    token_ids,
                    self.tokenizer,
                    frame_stride_ms=frame_stride_ms,
                )
                alignment = [
                    {
                        "token": str(seg["token"]),
                        "start_sec": float(seg["start_sec"]),
                        "end_sec": float(seg["end_sec"]),
                        "confidence": float(seg["confidence"]),
                    }
                    for seg in raw_align
                ]
            except ValueError:
                alignment = []
        else:
            alignment = []

        return text, hypotheses, alignment

    def transcribe(
        self,
        wav: np.ndarray,
        sr: int = 16000,
        decode_cfg: DecodeConfig | None = None,
        *,
        include_visuals: bool = False,
    ) -> dict[str, Any]:
        """Transcribe a waveform and cache its acoustic posteriors for fast re-decoding."""
        sr_val = _validate_sample_rate(sr)
        cfg = decode_cfg if decode_cfg is not None else DecodeConfig()
        if not isinstance(cfg, DecodeConfig):
            raise TypeError(
                f"decode_cfg must be a DecodeConfig or None, got {type(cfg).__name__}"
            )

        t0 = time.perf_counter()
        mono = _prepare_waveform(wav)

        if mono.size > 0 and sr_val != self.audio_cfg.sample_rate:
            wav_proc = resample(mono, sr_val, self.audio_cfg.sample_rate)
        else:
            wav_proc = mono

        duration_sec = float(wav_proc.size) / float(self.audio_cfg.sample_rate)
        utterance_id = uuid.uuid4().hex[:16]

        if wav_proc.size == 0:
            log_probs_np = np.empty((0, self.tokenizer.vocab_size), dtype=np.float32)
            mel = np.empty((0, self.audio_cfg.n_mels), dtype=np.float32)
            self._put_cache(
                utterance_id,
                _CachedUtterance(
                    log_probs=log_probs_np,
                    duration_sec=0.0,
                    frame_stride_ms=self.frame_stride_ms,
                ),
            )
            text, hypotheses, alignment = self._decode_and_align(
                log_probs_np, cfg, self.frame_stride_ms
            )
            rtf = 0.0
        else:
            mel = extract_log_mel(wav_proc, self.audio_cfg)
            feats = torch.from_numpy(np.ascontiguousarray(mel, dtype=np.float32)).unsqueeze(0).to(self.device)
            feat_lengths = torch.tensor([mel.shape[0]], dtype=torch.long, device=self.device)

            self.model.eval()
            with torch.no_grad():
                lp_tensor, out_lengths = self.model(feats, feat_lengths)

            valid_len = int(out_lengths[0].item())
            log_probs_np = np.ascontiguousarray(
                lp_tensor[0, :valid_len].detach().cpu().numpy(),
                dtype=np.float32,
            )

            self._put_cache(
                utterance_id,
                _CachedUtterance(
                    log_probs=log_probs_np,
                    duration_sec=duration_sec,
                    frame_stride_ms=self.frame_stride_ms,
                ),
            )

            text, hypotheses, alignment = self._decode_and_align(
                log_probs_np, cfg, self.frame_stride_ms
            )
            elapsed = time.perf_counter() - t0
            rtf = float(compute_rtf(elapsed, duration_sec))

        result: dict[str, Any] = {
            "text": text,
            "hypotheses": hypotheses,
            "alignment": alignment,
            "rtf": rtf,
            "duration_sec": float(duration_sec),
            "utterance_id": utterance_id,
        }

        if include_visuals:
            if wav_proc.size == 0:
                vad_segments: list[list[float]] = []
            else:
                raw_vad = detect_vad(wav_proc, sr=self.audio_cfg.sample_rate)
                vad_segments = [
                    [round(float(s), 4), round(float(e), 4)] for s, e in raw_vad
                ]
            result["waveform"] = _downsample_waveform(wav_proc)
            result["log_mel"] = _downsample_log_mel(mel)
            result["ctc_posteriors"] = _build_ctc_posteriors(log_probs_np)
            result["vad_segments"] = vad_segments

        return result

    def redecode(
        self,
        utterance_id: str,
        decode_cfg: DecodeConfig,
    ) -> dict[str, Any]:
        """Re-run CTC decoding and Viterbi alignment on cached posteriors."""
        if not isinstance(decode_cfg, DecodeConfig):
            raise TypeError(
                f"decode_cfg must be a DecodeConfig, got {type(decode_cfg).__name__}"
            )
        with self._cache_lock:
            if utterance_id not in self._cache:
                raise KeyError(f"Unknown or evicted utterance_id: {utterance_id!r}")
            self._cache.move_to_end(utterance_id)
            entry = self._cache[utterance_id]

        t0 = time.perf_counter()
        text, hypotheses, alignment = self._decode_and_align(
            entry.log_probs,
            decode_cfg,
            entry.frame_stride_ms,
        )
        decode_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "text": text,
            "hypotheses": hypotheses,
            "alignment": alignment,
            "utterance_id": utterance_id,
            "duration_sec": float(entry.duration_sec),
            "decode_ms": float(decode_ms),
        }

    def info(self) -> dict[str, Any]:
        """Return strictly JSON-serializable model, audio, tokenizer, and checkpoint metadata."""
        num_params = int(sum(p.numel() for p in self.model.parameters()))
        meta = self.checkpoint_meta
        checkpoint_path = (
            str(meta["checkpoint_path"]) if meta.get("checkpoint_path") is not None else None
        )
        epoch = int(meta["epoch"]) if meta.get("epoch") is not None else None
        best_val_cer = _finite_float_or_none(meta.get("best_val_cer"))
        train_config = _sanitize_json_value(meta.get("train_config"))
        history = _sanitize_json_value(meta.get("history", []))

        with self._cache_lock:
            cache_size = len(self._cache)

        return {
            "arch": str(self.model_cfg.arch),
            "num_parameters": num_params,
            "param_count": num_params,
            "subsampling_factor": int(getattr(self.model, "subsampling_factor", 4)),
            "frame_stride_ms": float(self.frame_stride_ms),
            "model_config": _sanitize_json_value(self.model_cfg.to_dict()),
            "audio_config": _sanitize_json_value(self.audio_cfg.to_dict()),
            "vocab_size": int(self.tokenizer.vocab_size),
            "vocab": [str(t) for t in self.tokenizer.vocab],
            "blank_id": int(self.tokenizer.blank_id),
            "tokenizer_mode": str(self.tokenizer.mode),
            "tokenizer": {
                "mode": str(self.tokenizer.mode),
                "vocab_size": int(self.tokenizer.vocab_size),
                "blank_id": int(self.tokenizer.blank_id),
                "vocab": [str(t) for t in self.tokenizer.vocab],
            },
            "tsukinami_presets": list(DEFAULT_TSUKINAMI_PRESETS),
            "has_lm": self.lm is not None,
            "cache_size": cache_size,
            "max_cache_size": int(self.max_cache_size),
            "checkpoint_path": checkpoint_path,
            "epoch": epoch,
            "best_val_cer": best_val_cer,
            "checkpoint": {
                "path": checkpoint_path,
                "epoch": epoch,
                "best_val_cer": best_val_cer,
                "train_config": train_config,
            },
            "history": history if isinstance(history, list) else [],
        }
