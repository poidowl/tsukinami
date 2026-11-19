"""Built-in Japanese speech data synthesis pipeline (Tier 1 Fast Kotoba & Tier 2 Tsukinami TTS)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from asr.audio import apply_corruption, load_wav, resample, save_wav

try:
    import accent
    import carve
    import kotoba
    import yomu
except ImportError:  # pragma: no cover - fallback when invoked outside repo root
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    import accent
    import carve
    import kotoba
    import yomu


__all__ = [
    "TRAIN_CORPUS",
    "VAL_CORPUS",
    "BUILTIN_CORPUS",
    "DEFAULT_TSUKINAMI_PRESETS",
    "VALID_ENGINES",
    "synthesize_fast_kotoba",
    "synthesize_tsukinami",
    "generate_dataset",
]


# ---------------------------------------------------------------------------
# Built-in diverse Japanese Katakana corpus (disjoint train / val splits)
# Every entry uses only Tokenizer(mode="kana") characters and valid kotoba moras.
# ---------------------------------------------------------------------------

TRAIN_CORPUS: tuple[str, ...] = (
    # 1. Greetings & Conversational Phrases (24)
    "オハヨウゴザイマス",
    "コンニチハ",
    "コンバンハ",
    "アリガトウゴザイマス",
    "ワタシ、ニホンゴ、チョットシャベレマス",
    "キョウモイッショニガンバロウネ",
    "オツカレサマデシタ",
    "ヨロシクオネガイシマス",
    "スミマセン",
    "ゴメンナサイ",
    "ダイジョウブデス",
    "マタアシタ",
    "オヤスミナサイ",
    "イッテラッシャイ",
    "タダイマ",
    "オカエリナサイ",
    "イタダキマス",
    "ゴチソウサマ",
    "ゲンキデスカ",
    "トテモタノシイデス",
    "ヨクデキマシタ",
    "モウイチドオネガイシマス",
    "ハジメマシテ",
    "サヨウナラ",
    # 2. Voice Commands & Playground Actions (24)
    "オンガクヲサイセイシテ",
    "ボリュームヲアゲテ",
    "ボリュームヲサゲテ",
    "ストップ",
    "スタート",
    "ツギノキョク",
    "マエノキョク",
    "タイマーヲセット",
    "テンキヲオシエテ",
    "ライトヲツケテ",
    "ライトヲケシテ",
    "アラームヲトメテ",
    "ロクオンヲカイシ",
    "ロクオンヲテイシ",
    "キャンセル",
    "モドル",
    "ススム",
    "カクダイ",
    "シュクショウ",
    "ホゾンシテ",
    "ケンサクシテ",
    "オンセイヲニュウリョク",
    "スピードヲハヤク",
    "ノイズヲフヤシテ",
    # 3. Digits, Numbers & Time (20)
    "ゼロ",
    "イチ、ニ、サン",
    "ヨン、ゴ、ロク",
    "ナナ、ハチ、キュウ、ジュウ",
    "ヒャク",
    "セン",
    "イチマン",
    "サンジハン",
    "ゴフンマエ",
    "ジュウニガツ",
    "イッカイ",
    "ニカイ",
    "サンカイ",
    "ゴジュウ",
    "ハチジュウ",
    "キュウジュウキュウ",
    "イッポン",
    "ニホン",
    "サンボン",
    "ゼロテンゴ",
    # 4. Everyday Words, Nature, Food & Tech (34)
    "サクラ",
    "ツキナミ",
    "タイヨウ",
    "アメ",
    "カゼ",
    "ヤマ",
    "ウミ",
    "ソラ",
    "ホシ",
    "ネコ",
    "イヌ",
    "トリ",
    "ラーメン",
    "スシ",
    "コーヒー",
    "オチャ",
    "パン",
    "リンゴ",
    "ミカン",
    "トウキョウ",
    "オオサカ",
    "キョウト",
    "ホッカイドウ",
    "デンシャ",
    "ヒコウキ",
    "コンピュータ",
    "プログラム",
    "オンセイニンシキ",
    "ロボット",
    "ギター",
    "ピアノ",
    "カメラ",
    "テレビ",
    "ラジオ",
    # 5. Phonetically Balanced & Special Mora Phrases (18)
    "パピプペポ、バビブベボ",
    "ザジズゼゾ、ダヂヅデド",
    "ガギグゲゴ、カキクケコ",
    "キャキュキョ、シャシュショ",
    "チャチュチョ、ニャニュニョ",
    "ヒャヒュヒョ、ミャミュミョ",
    "リャリュリョ、ギャギュギョ",
    "ジャジュジョ、ビャビュビョ",
    "ピャピュピョ、ファフィフェフォ",
    "ヴァヴィヴヴェヴォ",
    "アイウエオ、ヤユヨ",
    "ラリルレロ、ワヲン",
    "キップヲカッテ、デパチカヘイク",
    "サッカヲミテ、オウエンスル",
    "チョットマッテ、イマキマス",
    "シンカンセンデ、リョコウシヨウ",
    "チョコレートト、アイスクリーム",
    "ツキナミオンセイデ、アソボウ",
)

VAL_CORPUS: tuple[str, ...] = (
    # Disjoint validation phrases whose characters are a 100% subset of TRAIN_CORPUS
    "オハヨウ",
    "アリガトウ",
    "マタネ",
    "イッショニアソボウ",
    "キョウハヨイテンキ",
    "アシタモガンバロウ",
    "オンガクヲトメテ",
    "ボリュームヲゼロニシテ",
    "ツギヘススム",
    "マエヘモドル",
    "ロクオンヲホゾンシテ",
    "タイマーヲストップ",
    "イチ、ニ、サン、ヨン",
    "ゴ、ロク、ナナ、ハチ",
    "ジュウニジハン",
    "サンジュップンマエ",
    "ニヒャクゴジュウ",
    "サクラトソラ",
    "ウミトヤマ",
    "ネコトイヌ",
    "アツアツノラーメン",
    "ツメタイコーヒー",
    "リンゴトミカン",
    "トウキョウカラキョウトヘ",
    "デンシャトヒコウキ",
    "ロボットトオンセイ",
    "ピアノトギター",
    "シャシンヲカメラデトル",
    "パズルヲトク、タノシイ",
    "ツキナミデ、ニホンゴヲヨム",
)

BUILTIN_CORPUS: tuple[str, ...] = TRAIN_CORPUS + VAL_CORPUS

DEFAULT_TSUKINAMI_PRESETS: tuple[str, ...] = (
    "default",
    "ossan",
    "robot",
    "horror",
    "whisper",
    "chibi",
)

VALID_ENGINES: tuple[str, ...] = ("fast", "tsukinami", "mixed")

_YOMU_PRM_KEYS: frozenset[str] = frozenset(
    {
        "seed",
        "tsubu",
        "hz",
        "fscale",
        "yure",
        "shimmer",
        "tadayoi",
        "line_g",
        "ap_n",
        "rate",
        "uta_trance",
        "uta_choir",
        "tr_iroke",
    }
)

_ACCENT_MARKS: tuple[str, ...] = ("'", "’", "0", "/", "|", " ", "　", "?", "？")

_FAST_SPEAKER_PROFILES: tuple[dict[str, float | str], ...] = (
    {"name": "fast_alto", "f0": 1.00, "fscale": 1.00},
    {"name": "fast_soprano", "f0": 1.24, "fscale": 1.10},
    {"name": "fast_tenor", "f0": 0.84, "fscale": 0.94},
    {"name": "fast_baritone", "f0": 0.72, "fscale": 0.88},
    {"name": "fast_bright", "f0": 1.12, "fscale": 1.14},
    {"name": "fast_warm", "f0": 0.92, "fscale": 0.92},
)


def _validate_positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    return int(value)


def _validate_positive_float(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    fval = float(value)
    if not math.isfinite(fval) or fval <= 0.0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return fval


def _validate_bounded_float(name: str, value: Any, min_val: float, max_val: float) -> float:
    fval = _validate_positive_float(name, value)
    if fval < min_val or fval > max_val:
        raise ValueError(
            f"{name} must be finite and in [{min_val}, {max_val}], got {value!r}"
        )
    return fval


def _validate_bounded_number(name: str, value: Any, min_val: float, max_val: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
        raise ValueError(
            f"{name} must be finite and in [{min_val}, {max_val}], got {value!r}"
        )
    fval = float(value)
    if not math.isfinite(fval) or fval < min_val or fval > max_val:
        raise ValueError(
            f"{name} must be finite and in [{min_val}, {max_val}], got {value!r}"
        )
    return fval


def _validate_bounded_int(name: str, value: Any, min_val: int, max_val: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(
            f"{name} must be an integer in [{min_val}, {max_val}], got {value!r}"
        )
    ival = int(value)
    if ival < min_val or ival > max_val:
        raise ValueError(
            f"{name} must be an integer in [{min_val}, {max_val}], got {value!r}"
        )
    return ival


def _sanitize_whitespace(text: str) -> str:
    """Normalize control/Unicode whitespace to single ASCII spaces."""
    return " ".join(text.split())


def _normalize_moras(raw_moras: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "t": str(m["t"]),
            "a": round(float(m["a"]), 6),
            "e": round(float(m["e"]), 6),
        }
        for m in raw_moras
    ]


def _canonicalize_json(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {str(k): _canonicalize_json(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize_json(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _deep_merge_rc(rc: dict[str, Any], overrides: Mapping[str, Any]) -> None:
    for key, val in overrides.items():
        if "." in key:
            parts = key.split(".")
            cur: dict[str, Any] = rc
            for part in parts[:-1]:
                nxt = cur.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[part] = nxt
                cur = nxt
            leaf = parts[-1]
            if isinstance(val, Mapping) and isinstance(cur.get(leaf), dict):
                _deep_merge_rc(cur[leaf], val)
            else:
                cur[leaf] = copy.deepcopy(val)
        elif isinstance(val, Mapping) and isinstance(rc.get(key), dict):
            _deep_merge_rc(rc[key], val)
        else:
            rc[key] = copy.deepcopy(val)


# ---------------------------------------------------------------------------
# Tier 1: Fast Vectorized Kotoba Formant-Track Synthesizer
# ---------------------------------------------------------------------------


def synthesize_fast_kotoba(
    text: str,
    *,
    sr: int = 16000,
    f0_scale: float = 1.0,
    fscale: float = 1.0,
    rate: float = 1.0,
    snr_db: float | None = None,
    seed: int | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Synthesize Japanese kana quickly from ``kotoba.tracks_from_kana()``.

    Uses vectorized NumPy overlap-add parallel Lorentzian formant resonators
    driven by a phase-continuous glottal pulse train and consonant noise bands.

    Returns ``(wav_float32, moras)`` where ``wav_float32`` is 1D ``np.float32``
    in ``[-1.0, 1.0]`` and each mora dict has exact keys ``{"t", "a", "e"}``.
    """
    if not isinstance(text, str):
        raise ValueError(f"text must be a string, got {type(text).__name__}")
    sr = _validate_positive_int("sr", sr)
    f0_scale = _validate_bounded_float("f0_scale", f0_scale, 0.1, 10.0)
    fscale = _validate_bounded_float("fscale", fscale, 0.1, 10.0)
    rate = _validate_bounded_float("rate", rate, 0.1, 10.0)
    if snr_db is not None:
        if isinstance(snr_db, bool) or not isinstance(snr_db, (int, float)):
            raise ValueError(f"snr_db must be a finite number or None, got {snr_db!r}")
        snr_db = float(snr_db)
        if not math.isfinite(snr_db) or snr_db < -100.0 or snr_db > 120.0:
            raise ValueError(f"snr_db must be finite and between -100.0 and 120.0, got {snr_db!r}")

    cleaned_text = _sanitize_whitespace(text)
    if not cleaned_text:
        return np.zeros(0, dtype=np.float32), []

    ms = kotoba.split_moras(cleaned_text)
    if not ms:
        return np.zeros(0, dtype=np.float32), []

    # Guard against sokuon/pause-only strings that crash kotoba.build_tracks()
    if all(m in ("ッ", "、") for m in ms):
        pre = 0.1
        post = 0.1
        cur_t = pre
        moras: list[dict[str, Any]] = []
        for m in ms:
            dur = (kotoba.DEF["pau"] if m == "、" else kotoba.DEF["qn"]) * rate
            moras.append({"t": m, "a": round(cur_t, 6), "e": round(cur_t + dur, 6)})
            cur_t += dur
        total_sec = cur_t + post
        n_samples = max(1, int(round(total_sec * sr)))
        return np.zeros(n_samples, dtype=np.float32), moras

    rng = np.random.default_rng(seed)

    params = {
        "rate": rate,
        "pau": kotoba.DEF["pau"] * rate,
        "qn": kotoba.DEF["qn"] * rate,
        "devmax": kotoba.DEF["devmax"] * rate,
        "f0": kotoba.DEF["f0"] * f0_scale,
    }
    tr = kotoba.tracks_from_kana(cleaned_text, params=params)
    n = int(tr["n"])
    fp_s = float(tr["fp_ms"]) / 1000.0
    moras = _normalize_moras(tr["moras"])

    if n <= 0:
        return np.zeros(0, dtype=np.float32), moras

    hop = max(1, int(round(sr * fp_s)))
    win_len = 2 * hop
    n_fft = max(256, 1 << (win_len - 1).bit_length())
    n_samples = (n + 1) * hop

    # 1. Sample-level phase-continuous glottal + aspiration/noise excitation
    f0_arr = np.asarray(tr["f0"], dtype=np.float64)
    vo_arr = np.asarray(tr["voiced"], dtype=np.float64)
    t_fr = np.arange(n, dtype=np.float64) * hop + 0.5 * hop
    t_s = np.arange(n_samples, dtype=np.float64)

    valid_f0 = f0_arr > 0.0
    if np.any(valid_f0):
        f0_filled = np.interp(np.arange(n, dtype=np.float64), np.flatnonzero(valid_f0), f0_arr[valid_f0])
    else:
        f0_filled = np.full(n, kotoba.DEF["f0"] * f0_scale, dtype=np.float64)

    f0_s = np.interp(t_s, t_fr, f0_filled)
    f0_s = np.clip(f0_s, 40.0, 0.4 * sr)
    vo_s = np.interp(t_s, t_fr, vo_arr)

    dphase = 2.0 * np.pi * f0_s / float(sr)
    phase = np.cumsum(dphase)
    p_mod = np.mod(phase, 2.0 * np.pi)

    # Alias-free Gaussian glottal pulse (>= 1.2 samples wide) + lip radiation derivative
    sigma_s = np.maximum(0.08, 1.2 * dphase)
    pulse = np.exp(-0.5 * ((p_mod - np.pi) / sigma_s) ** 2)
    glottal = np.empty_like(pulse)
    glottal[0] = 0.0
    glottal[1:] = pulse[1:] - 0.95 * pulse[:-1]
    g_std = float(np.std(glottal))
    if g_std > 1e-8:
        glottal /= g_std

    noise = rng.standard_normal(n_samples)
    exc = vo_s * (glottal + 0.04 * noise) + (1.0 - vo_s) * (0.25 * noise)

    # 2. Vectorized frame-domain parallel Lorentzian formant filtering
    win = np.hanning(win_len + 1)[:-1]  # periodic Hann: sums to exact 1.0 at 50% overlap
    exc_frames = np.lib.stride_tricks.sliding_window_view(exc, win_len)[::hop][:n]
    E = np.fft.rfft(exc_frames * win[None, :], n=n_fft, axis=1)

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / float(sr))[None, :]  # (1, K)

    F1 = np.clip(np.asarray(tr["F1"], dtype=np.float64) * fscale, 80.0, 0.45 * sr)[:, None]
    F2 = np.clip(np.asarray(tr["F2"], dtype=np.float64) * fscale, 150.0, 0.45 * sr)[:, None]
    F3 = np.clip(np.asarray(tr["F3"], dtype=np.float64) * fscale, 300.0, 0.47 * sr)[:, None]

    G1 = np.asarray(tr["G1"], dtype=np.float64)[:, None]
    G2 = np.asarray(tr["G2"], dtype=np.float64)[:, None]
    G3 = np.asarray(tr["G3"], dtype=np.float64)[:, None]

    B1 = 70.0 + 0.05 * F1
    B2 = 100.0 + 0.06 * F2
    B3 = 140.0 + 0.06 * F3

    H = (
        (1.00 * G1) / np.sqrt(((freqs - F1) / (0.5 * B1)) ** 2 + 1.0)
        + (0.85 * G2) / np.sqrt(((freqs - F2) / (0.5 * B2)) ** 2 + 1.0)
        + (0.55 * G3) / np.sqrt(((freqs - F3) / (0.5 * B3)) ** 2 + 1.0)
    )
    Y = E * H

    # 3. Fricative & stop-burst consonant noise bands
    bands = tr.get("bands") or []
    if bands:
        noise_frames = np.lib.stride_tricks.sliding_window_view(noise, win_len)[::hop][:n]
        N_spec = np.fft.rfft(noise_frames * win[None, :], n=n_fft, axis=1)
        freqs_1d = freqs[0]
        for t0, t1, cen, sd, gain in bands:
            i0 = max(0, min(n, int(round(float(t0) / fp_s))))
            i1 = max(i0, min(n, int(round(float(t1) / fp_s))))
            if i1 <= i0:
                continue
            c_hz = min(float(cen) * fscale, 0.47 * sr)
            s_hz = max(100.0, float(sd) * fscale)
            band_h = (0.12 * float(gain)) * np.exp(-0.5 * ((freqs_1d - c_hz) / s_hz) ** 2)
            Y[i0:i1] += N_spec[i0:i1] * band_h[None, :]

    # 4. Zero-loop 50%-overlap-add synthesis
    y_frames = np.fft.irfft(Y, n=n_fft, axis=1)[:, :win_len]
    wav = np.zeros(n_samples, dtype=np.float64)
    even = y_frames[0::2].ravel()
    wav[: even.size] += even
    if y_frames.shape[0] > 1:
        odd = y_frames[1::2].ravel()
        wav[hop : hop + odd.size] += odd

    # 5. Loudness envelope with smooth silence gating (keeps pre/post silence < -60 dB for VAD)
    loud = np.asarray(tr["loud"], dtype=np.float64)
    dl = np.asarray(tr["dl"], dtype=np.float64)
    sil_gate = np.clip((loud - (-28.0)) / 5.0, 0.0, 1.0)
    env_fr = sil_gate * (10.0 ** ((loud + dl) / 20.0))
    env_s = np.interp(t_s, t_fr, env_fr)
    wav *= env_s

    peak = float(np.max(np.abs(wav)))
    if peak > 1e-8:
        wav *= 0.85 / peak

    wav_f32 = np.clip(np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0).astype(
        np.float32
    )

    # 6. Optional additive white noise at target SNR (dB)
    if snr_db is not None and wav_f32.size > 0:
        noise_seed = int(rng.integers(0, 2**31 - 1))
        wav_f32 = apply_corruption(
            wav_f32,
            sr,
            snr_db=snr_db,
            noise_type="white",
            seed=noise_seed,
        )
        peak_noisy = float(np.max(np.abs(wav_f32)))
        if peak_noisy > 1.0:
            wav_f32 = (wav_f32 * (0.99 / peak_noisy)).astype(np.float32)
        wav_f32 = np.clip(wav_f32, -1.0, 1.0).astype(np.float32, copy=False)

    return wav_f32, moras


# ---------------------------------------------------------------------------
# Tier 2: Authentic Tsukinami TTS Wrapper with Atomic Disk Caching
# ---------------------------------------------------------------------------


def synthesize_tsukinami(
    text: str,
    *,
    preset: str = "default",
    sr: int = 16000,
    overrides: dict[str, Any] | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Synthesize Japanese speech via ``yomu.build_carve_rc`` + ``carve.make``.

    Resamples 44.1 kHz output to ``sr`` and optionally caches results on disk
    under ``cache_dir``. Never mutates global ``yomu.PRESETS`` or ``overrides``.
    """
    sr = _validate_positive_int("sr", sr)
    if not isinstance(preset, str) or preset not in yomu.PRESETS:
        avail = ", ".join(sorted(yomu.PRESETS.keys()))
        raise ValueError(f"Unknown tsukinami preset {preset!r}; available presets: {avail}")
    if not isinstance(text, str):
        raise ValueError("text must be a non-empty string")
    sanitized_text = _sanitize_whitespace(text)
    if not sanitized_text:
        raise ValueError("text must be a non-empty string")

    if any(ch in sanitized_text for ch in _ACCENT_MARKS):
        clean_text, _ = accent.annotate(sanitized_text)
    else:
        clean_text = sanitized_text
    ms = kotoba.split_moras(clean_text)
    if not any(m not in ("ッ", "、") for m in ms):
        raise ValueError(f"text must contain at least one speakable kana mora, got {text!r}")

    if overrides is not None and not isinstance(overrides, Mapping):
        raise TypeError(f"overrides must be a mapping or None, got {type(overrides).__name__}")

    prm: dict[str, Any] = copy.deepcopy(yomu.PRESETS["default"])
    prm.setdefault("uta_trance", False)
    prm.setdefault("uta_choir", False)
    prm.update(copy.deepcopy(yomu.PRESETS[preset]))

    rc_overrides: dict[str, Any] = {}
    if overrides:
        for k, v in overrides.items():
            if k in _YOMU_PRM_KEYS:
                prm[k] = copy.deepcopy(v)
            else:
                rc_overrides[k] = copy.deepcopy(v)

    prm["hz"] = _validate_bounded_float("hz", prm["hz"], 20.0, 2000.0)
    prm["fscale"] = _validate_bounded_float("fscale", prm["fscale"], 0.25, 4.0)
    prm["rate"] = _validate_bounded_float("rate", prm["rate"], 0.1, 10.0)
    if "tsubu" in prm:
        prm["tsubu"] = int(_validate_bounded_float("tsubu", prm["tsubu"], 1.0, 4096.0))
    if "yure" in prm:
        prm["yure"] = _validate_bounded_number("yure", prm["yure"], 0.0, 100.0)
    if "shimmer" in prm:
        prm["shimmer"] = _validate_bounded_number("shimmer", prm["shimmer"], 0.0, 10.0)
    if "tadayoi" in prm:
        prm["tadayoi"] = _validate_bounded_number("tadayoi", prm["tadayoi"], 0.0, 100.0)
    if "line_g" in prm:
        prm["line_g"] = _validate_bounded_number("line_g", prm["line_g"], 0.0, 10.0)
    if "tr_iroke" in prm:
        prm["tr_iroke"] = _validate_bounded_number("tr_iroke", prm["tr_iroke"], 0.0, 10.0)
    if "ap_n" in prm:
        prm["ap_n"] = _validate_bounded_int("ap_n", prm["ap_n"], 0, 64)
    if "seed" in prm:
        prm["seed"] = _validate_bounded_int("seed", prm["seed"], 0, 2**32 - 1)

    wav_cache_path: Path | None = None
    meta_cache_path: Path | None = None
    if cache_dir is not None:
        cache_root = Path(cache_dir)
        payload = {
            "v": 1,
            "text": sanitized_text,
            "preset": preset,
            "sr": sr,
            "overrides": _canonicalize_json(overrides or {}),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        wav_cache_path = cache_root / f"tsukinami_{digest}.wav"
        meta_cache_path = cache_root / f"tsukinami_{digest}.json"
        if wav_cache_path.is_file() and meta_cache_path.is_file():
            try:
                cached_wav, _ = load_wav(wav_cache_path, target_sr=sr)
                cached_meta = json.loads(meta_cache_path.read_text(encoding="utf-8"))
                if isinstance(cached_meta, dict) and isinstance(cached_meta.get("moras"), list):
                    return cached_wav, _normalize_moras(cached_meta["moras"])
            except Exception:
                pass  # Corrupted cache entry: re-synthesize cleanly

    rc = yomu.build_carve_rc(sanitized_text, prm)
    if rc_overrides:
        _deep_merge_rc(rc, rc_overrides)

    samples, raw_moras = carve.make(rc)
    samples = yomu.boost_low_pitch_rms(samples, prm["hz"])

    wav = np.asarray(samples, dtype=np.float32)
    if sr != carve.SR:
        wav = resample(wav, carve.SR, sr)
    wav = np.clip(np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0).astype(
        np.float32, copy=False
    )
    moras = _normalize_moras(raw_moras)

    if wav_cache_path is not None and meta_cache_path is not None:
        wav_cache_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
        tmp_wav = wav_cache_path.with_name(wav_cache_path.name + suffix)
        tmp_meta = meta_cache_path.with_name(meta_cache_path.name + suffix)
        try:
            save_wav(tmp_wav, wav, sr=sr)
            os.replace(tmp_wav, wav_cache_path)
            meta_obj = {
                "v": 1,
                "text": sanitized_text,
                "preset": preset,
                "sr": sr,
                "moras": moras,
            }
            tmp_meta.write_text(json.dumps(meta_obj, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_meta, meta_cache_path)
        except Exception:
            for tmp_p in (tmp_wav, tmp_meta):
                try:
                    tmp_p.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        wav, _ = load_wav(wav_cache_path, target_sr=sr)

    return wav, moras


# ---------------------------------------------------------------------------
# Dataset Generator (Fast / Tsukinami / Mixed)
# ---------------------------------------------------------------------------


def _sample_phrases(pool: Sequence[str], count: int, rng: np.random.Generator) -> list[str]:
    if count <= 0:
        return []
    out: list[str] = []
    n_pool = len(pool)
    while len(out) < count:
        order = rng.permutation(n_pool)
        for idx in order:
            out.append(pool[int(idx)])
            if len(out) >= count:
                break
    return out


def generate_dataset(
    out_dir: str | Path,
    *,
    num_train: int = 200,
    num_val: int = 40,
    engine: str = "fast",
    seed: int = 42,
    presets: Sequence[str] | None = None,
) -> dict[str, Path]:
    """Generate synthetic Japanese ASR train/val manifests and 16 kHz WAV files.

    Parameters
    ----------
    out_dir:
        Output directory where ``train.jsonl``, ``val.jsonl``, and ``audio/``
        will be written.
    num_train, num_val:
        Number of utterances for train and validation splits.
    engine:
        One of ``"fast"``, ``"tsukinami"``, or ``"mixed"``.
    seed:
        Deterministic RNG seed.
    presets:
        Optional subset of ``yomu.PRESETS`` names used for ``tsukinami`` / ``mixed``.

    Returns
    -------
    dict[str, Path]
        ``{"train": Path(.../train.jsonl), "val": Path(.../val.jsonl)}``.
    """
    if engine not in VALID_ENGINES:
        raise ValueError(f"engine must be one of {VALID_ENGINES}, got {engine!r}")
    if isinstance(num_train, bool) or not isinstance(num_train, int) or num_train <= 0:
        raise ValueError(f"num_train must be a positive integer, got {num_train!r}")
    if isinstance(num_val, bool) or not isinstance(num_val, int) or num_val <= 0:
        raise ValueError(f"num_val must be a positive integer, got {num_val!r}")

    if presets is None:
        preset_list = list(DEFAULT_TSUKINAMI_PRESETS)
    else:
        preset_list = list(presets)
        if not preset_list:
            raise ValueError("presets must be non-empty when provided")
        unknown = [p for p in preset_list if p not in yomu.PRESETS]
        if unknown:
            raise ValueError(
                f"Unknown preset(s) {unknown!r}; available: {sorted(yomu.PRESETS.keys())}"
            )

    root = Path(out_dir).resolve()
    (root / "audio" / "train").mkdir(parents=True, exist_ok=True)
    (root / "audio" / "val").mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    sr = 16000

    split_specs = (
        ("train", TRAIN_CORPUS, num_train),
        ("val", VAL_CORPUS, num_val),
    )
    manifest_paths: dict[str, Path] = {}

    for split_name, phrase_pool, count in split_specs:
        phrases = _sample_phrases(phrase_pool, count, rng)

        if engine == "fast":
            use_tsuki = [False] * count
        elif engine == "tsukinami":
            use_tsuki = [True] * count
        else:  # mixed: ~25% tsukinami, guaranteed >= 1 of each when count >= 2
            n_tsuki = max(1, count // 4) if count >= 2 else 0
            flags = np.array([True] * n_tsuki + [False] * (count - n_tsuki), dtype=bool)
            rng.shuffle(flags)
            use_tsuki = [bool(x) for x in flags]

        # Shuffle preset order once per split so even small splits cover distinct presets
        preset_order = [preset_list[int(idx)] for idx in rng.permutation(len(preset_list))]
        tsuki_idx = 0

        records: list[dict[str, Any]] = []
        for i, phrase in enumerate(phrases):
            text = kotoba.to_kata(phrase)
            rel_wav = Path("audio") / split_name / f"{split_name}_{i:05d}.wav"
            abs_wav = root / rel_wav

            if use_tsuki[i]:
                preset = preset_order[tsuki_idx % len(preset_order)]
                tsuki_idx += 1
                base_prm = yomu.PRESETS[preset]
                utt_seed = int(rng.integers(0, 2**31 - 1))
                overrides = {
                    "seed": utt_seed,
                    "hz": round(float(base_prm["hz"]) * float(rng.uniform(0.95, 1.05)), 2),
                    "rate": round(float(base_prm["rate"]) * float(rng.uniform(0.95, 1.05)), 3),
                }
                wav, moras = synthesize_tsukinami(
                    text,
                    preset=preset,
                    sr=sr,
                    overrides=overrides,
                )
                speaker = preset
                source = "tsukinami"
            else:
                prof = _FAST_SPEAKER_PROFILES[int(rng.integers(0, len(_FAST_SPEAKER_PROFILES)))]
                f0_scale = float(prof["f0"]) * float(rng.uniform(0.92, 1.08))
                fscale = float(prof["fscale"]) * float(rng.uniform(0.94, 1.06))
                rate = float(rng.uniform(0.85, 1.20))
                snr_db = None if float(rng.random()) < 0.35 else float(rng.uniform(15.0, 35.0))
                utt_seed = int(rng.integers(0, 2**31 - 1))
                wav, moras = synthesize_fast_kotoba(
                    text,
                    sr=sr,
                    f0_scale=f0_scale,
                    fscale=fscale,
                    rate=rate,
                    snr_db=snr_db,
                    seed=utt_seed,
                )
                speaker = str(prof["name"])
                source = "kotoba_fast"

            save_wav(abs_wav, wav, sr=sr)
            duration = round(float(wav.size) / float(sr), 4)
            records.append(
                {
                    "audio_path": str(abs_wav),
                    "text": text,
                    "duration": duration,
                    "speaker": speaker,
                    "source": source,
                    "moras": moras,
                }
            )

        manifest_path = root / f"{split_name}.jsonl"
        with manifest_path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        manifest_paths[split_name] = manifest_path

    return manifest_paths
