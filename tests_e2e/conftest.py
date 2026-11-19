"""Shared fixtures and independent synthetic audio/WAV helpers for Tsukinami ASR E2E tests.

All ``asr.*``, ``torch``, ``fastapi``, ``httpx``, and ``numpy`` imports are kept
inside helper/fixture bodies so ``pytest --collect-only tests_e2e/`` succeeds
cleanly even while ``asr/`` is built in parallel, while executing any test
against missing or broken ``asr/`` modules fails genuinely (no skipped stubs,
zero dummy passes).
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import pytest


# ---------------------------------------------------------------------------
# Pure-stdlib / NumPy synthetic signal & WAV helpers (independent of asr.*)
# ---------------------------------------------------------------------------


def make_sine(
    freq: float = 440.0,
    duration: float = 1.0,
    sr: int = 16000,
    amp: float = 0.5,
):
    """Return a 1D float32 sine wave."""
    import numpy as np

    n = int(round(duration * sr))
    t = np.arange(n, dtype=np.float32) / float(sr)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def make_speech_like(
    duration: float = 1.2,
    sr: int = 16000,
    f0: float = 200.0,
    pad_sec: float = 0.2,
    seed: int = 0,
):
    """Return a 1D float32 harmonic formant-modulated signal with silence padding."""
    import numpy as np

    rng = np.random.default_rng(seed)
    total_n = int(round(duration * sr))
    if total_n <= 0:
        return np.zeros(0, dtype=np.float32)
    pad_n = min(int(round(pad_sec * sr)), total_n // 3)
    active_n = max(1, total_n - 2 * pad_n)

    t = np.arange(active_n, dtype=np.float32) / float(sr)
    # Slow amplitude envelope simulating syllables
    env = 0.5 * (1.0 - np.cos(2.0 * np.pi * np.linspace(0.0, 1.0, active_n, dtype=np.float32)))
    syllable = 0.65 + 0.35 * np.sin(2.0 * np.pi * 4.5 * t)
    sig = (
        0.50 * np.sin(2.0 * np.pi * f0 * t)
        + 0.30 * np.sin(2.0 * np.pi * (3.0 * f0) * t)
        + 0.15 * np.sin(2.0 * np.pi * (5.0 * f0) * t)
        + 0.05 * rng.standard_normal(active_n).astype(np.float32)
    )
    active = (0.45 * env * syllable * sig).astype(np.float32)
    out = np.zeros(total_n, dtype=np.float32)
    out[pad_n : pad_n + active_n] = np.clip(active, -0.95, 0.95)
    return out


def make_silence(duration: float = 0.5, sr: int = 16000):
    """Return 1D float32 zeros."""
    import numpy as np

    return np.zeros(int(round(duration * sr)), dtype=np.float32)


def make_clipped(duration: float = 0.5, sr: int = 16000, amp: float = 2.0):
    """Return a 1D float32 waveform exceeding [-1.0, 1.0]."""
    return make_sine(freq=440.0, duration=duration, sr=sr, amp=amp)


def write_pcm_wav(
    path: Path | str,
    wav,
    sr: int = 16000,
    channels: int = 1,
    sampwidth: int = 2,
) -> Path:
    """Write a valid 16-bit or 32-bit PCM WAV file using Python stdlib ``wave``."""
    import numpy as np

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(wav, dtype=np.float32)
    if arr.ndim == 1 and channels == 2:
        arr = np.stack([arr, arr * 0.8], axis=-1)
    elif arr.ndim == 2 and arr.shape[1] != channels:
        raise ValueError(f"Channel mismatch: array has {arr.shape[1]}, expected {channels}")

    clipped = np.clip(arr, -1.0, 1.0)
    if sampwidth == 2:
        pcm = np.round(clipped * 32767.0).astype("<i2").tobytes()
    elif sampwidth == 4:
        pcm = np.round(clipped.astype(np.float64) * 2147483647.0).astype("<i4").tobytes()
    else:
        raise ValueError(f"Unsupported sampwidth: {sampwidth}")

    with wave.open(str(dest), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)
    return dest


def write_corrupt_wav(path: Path | str, kind: str = "garbage") -> Path:
    """Write a deliberately corrupt WAV file ('garbage', 'empty', or 'truncated')."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if kind == "garbage":
        dest.write_bytes(b"NOT_A_WAV_FILE_1234567890_CORRUPT_PAYLOAD")
    elif kind == "empty":
        dest.write_bytes(b"")
    elif kind == "truncated":
        dest.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    else:
        raise ValueError(f"Unknown corrupt WAV kind: {kind}")
    return dest


def wav_to_bytes(wav, sr: int = 16000) -> bytes:
    """Serialize a 1D float32 waveform into 16-bit mono PCM WAV bytes via stdlib."""
    import numpy as np

    buf = io.BytesIO()
    arr = np.clip(np.asarray(wav, dtype=np.float32).reshape(-1), -1.0, 1.0)
    pcm = np.round(arr * 32767.0).astype("<i2").tobytes()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm)
    return buf.getvalue()


def wav_to_b64(wav, sr: int = 16000) -> str:
    """Return base64-encoded 16-bit mono PCM WAV string."""
    return base64.b64encode(wav_to_bytes(wav, sr=sr)).decode("ascii")


def make_synthetic_log_probs(
    frame_token_ids: Sequence[int],
    vocab_size: int,
    peak_logit: float = 8.0,
):
    """Build a (T, V) float32 log-probability matrix peaking at ``frame_token_ids``."""
    import numpy as np

    t_len = len(frame_token_ids)
    logits = np.zeros((t_len, vocab_size), dtype=np.float32)
    for t_idx, tok_id in enumerate(frame_token_ids):
        logits[t_idx, int(tok_id)] = float(peak_logit)
    if t_len == 0:
        return logits
    max_l = np.max(logits, axis=-1, keepdims=True)
    lse = max_l + np.log(np.sum(np.exp(logits - max_l), axis=-1, keepdims=True))
    return (logits - lse).astype(np.float32)


def make_weighted_log_probs(
    frame_logits: Sequence[dict[int, float]],
    vocab_size: int,
):
    """Build a (T, V) float32 log-probability matrix from per-frame {token_id: logit} dicts."""
    import numpy as np

    t_len = len(frame_logits)
    logits = np.zeros((t_len, vocab_size), dtype=np.float32)
    for t_idx, mapping in enumerate(frame_logits):
        for tok_id, val in mapping.items():
            logits[t_idx, int(tok_id)] = float(val)
    if t_len == 0:
        return logits
    max_l = np.max(logits, axis=-1, keepdims=True)
    lse = max_l + np.log(np.sum(np.exp(logits - max_l), axis=-1, keepdims=True))
    return (logits - lse).astype(np.float32)


def extract_transcribe_payload(resp_json: dict[str, Any]) -> dict[str, Any]:
    """Return the TranscribeResult dict from a flat or nested /api/tts-roundtrip payload."""
    if "text" in resp_json:
        return resp_json
    for key in ("result", "transcription", "asr", "transcribe_result"):
        if isinstance(resp_json.get(key), dict) and "text" in resp_json[key]:
            return resp_json[key]
    return resp_json


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def helpers() -> SimpleNamespace:
    """Expose independent synthetic signal/WAV/log-prob helpers to all test modules."""
    return SimpleNamespace(
        make_sine=make_sine,
        make_speech_like=make_speech_like,
        make_silence=make_silence,
        make_clipped=make_clipped,
        write_pcm_wav=write_pcm_wav,
        write_corrupt_wav=write_corrupt_wav,
        wav_to_bytes=wav_to_bytes,
        wav_to_b64=wav_to_b64,
        make_synthetic_log_probs=make_synthetic_log_probs,
        make_weighted_log_probs=make_weighted_log_probs,
        extract_transcribe_payload=extract_transcribe_payload,
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root directory (/home/antigravity/poidowl/tsukinami)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def python_bin(repo_root: Path) -> Path:
    """Canonical Python executable (.venv/bin/python if present, else sys.executable)."""
    venv_py = repo_root / ".venv" / "bin" / "python"
    if venv_py.exists():
        return venv_py
    return Path(sys.executable)


@pytest.fixture(scope="session")
def run_cli(repo_root: Path, python_bin: Path):
    """Run ``python -m asr <args>`` as a subprocess with 2-thread CPU guardrails."""

    def _run(
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        proc_env = dict(os.environ)
        proc_env.setdefault("OMP_NUM_THREADS", "2")
        proc_env.setdefault("MKL_NUM_THREADS", "2")
        if env:
            proc_env.update(env)
        cmd = [str(python_bin), "-m", "asr", *list(args)]
        return subprocess.run(
            cmd,
            cwd=str(cwd or repo_root),
            env=proc_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    return _run


@pytest.fixture(scope="session")
def tsukinami_cache_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped disk cache for authentic 44.1 kHz tsukinami TTS synthesis."""
    return tmp_path_factory.mktemp("tsukinami_tts_cache")


@pytest.fixture(scope="session")
def tiny_fast_dataset(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Session-scoped compact Tier-1 fast-kotoba dataset (12 train / 4 val)."""
    from asr.synth_data import generate_dataset

    out_dir = tmp_path_factory.mktemp("tiny_fast_dataset")
    paths = generate_dataset(out_dir, num_train=12, num_val=4, engine="fast", seed=42)
    return {
        "out_dir": out_dir,
        "train": Path(paths["train"]),
        "val": Path(paths["val"]),
    }


@pytest.fixture(scope="session")
def tiny_checkpoint(
    tmp_path_factory: pytest.TempPathFactory,
    tiny_fast_dataset: dict[str, Path],
) -> dict[str, Any]:
    """Session-scoped compact CPU-trained cnn_bigru checkpoint."""
    import torch
    from asr.config import AudioConfig, ModelConfig, TrainConfig
    from asr.tokenizer import Tokenizer
    from asr.train import train_asr

    torch.set_num_threads(2)
    ckpt_dir = tmp_path_factory.mktemp("tiny_ckpt")
    audio_cfg = AudioConfig()
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=audio_cfg.n_mels,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
    )
    train_cfg = TrainConfig(
        epochs=2,
        batch_size=4,
        lr=3e-3,
        seed=42,
        use_spec_augment=False,
        checkpoint_dir=str(ckpt_dir),
    )
    tokenizer = Tokenizer(mode="kana")
    summary = train_asr(
        tiny_fast_dataset["train"],
        tiny_fast_dataset["val"],
        audio_cfg=audio_cfg,
        model_cfg=model_cfg,
        train_cfg=train_cfg,
        tokenizer=tokenizer,
    )
    return {
        "best_pt": ckpt_dir / "best.pt",
        "latest_pt": ckpt_dir / "latest.pt",
        "ckpt_dir": ckpt_dir,
        "train_manifest": tiny_fast_dataset["train"],
        "val_manifest": tiny_fast_dataset["val"],
        "summary": summary,
        "audio_cfg": audio_cfg,
        "model_cfg": model_cfg,
        "tokenizer": tokenizer,
    }


@pytest.fixture(scope="session")
def tiny_engine(tiny_checkpoint: dict[str, Any]):
    """Session-scoped ASREngine loaded from ``tiny_checkpoint['best_pt']``."""
    from asr.inference import ASREngine

    return ASREngine.from_checkpoint(tiny_checkpoint["best_pt"])


@pytest.fixture(scope="session")
def api_client_factory():
    """Factory creating a FastAPI TestClient from ``asr.server.create_app``."""

    def _make(checkpoint_path: str | Path | None = None, engine: Any = None):
        from fastapi.testclient import TestClient
        from asr.server import create_app

        app = create_app(checkpoint_path=checkpoint_path, engine=engine)
        return TestClient(app)

    return _make


@pytest.fixture(scope="session")
def api_client(tiny_engine, api_client_factory):
    """Session-scoped FastAPI TestClient backed by ``tiny_engine``."""
    return api_client_factory(engine=tiny_engine)


@pytest.fixture(scope="session")
def api_client_no_model(api_client_factory):
    """Session-scoped FastAPI TestClient created with no loaded model."""
    return api_client_factory()
