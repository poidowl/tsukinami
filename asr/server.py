"""FastAPI backend for the Tsukinami ASR interactive web playground."""

from __future__ import annotations

import base64
import binascii
import io
import json
import math
import sys
import threading
import wave
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from asr.audio import apply_corruption, load_wav_bytes
from asr.config import DecodeConfig
from asr.inference import ASREngine
from asr.metrics import compute_cer
from asr.synth_data import synthesize_fast_kotoba, synthesize_tsukinami

# Ensure repo root is importable for `yomu` even when launched outside cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yomu  # noqa: E402

__all__ = ["create_app"]

_WEB_INDEX_PATH = Path(__file__).resolve().parent / "web" / "index.html"
_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MiB raw audio cap
_MAX_JSON_BYTES = 30 * 1024 * 1024  # 30 MiB JSON body cap (base64 overhead)
_MAX_BEAM_WIDTH = 64
_MIN_SPEED = 0.25
_MAX_SPEED = 4.0
_MIN_SNR_DB = -100.0
_MAX_SNR_DB = 120.0
_MIN_GAIN_DB = -100.0
_MAX_GAIN_DB = 100.0
_MAX_TTS_TEXT_LEN = 500


# ---------------------------------------------------------------------------
# Request schemas (Pydantic v2)
# ---------------------------------------------------------------------------


class DecodeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "beam"
    beam_width: int = 8
    temperature: float = 1.0
    blank_bias: float = 0.0
    lm_weight: float = 0.0
    insertion_bonus: float = 0.0


class CorruptionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snr_db: float | None = None
    noise_type: str = "white"
    band_limit: list[float] | tuple[float, float] | None = None
    band_limit_low: float | None = None
    band_limit_high: float | None = None
    speed: float = 1.0
    gain_db: float = 0.0
    seed: int | None = None


class TTSRoundtripRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    preset: str = "default"
    hz: float | None = None
    fscale: float | None = None
    yure: float | None = None
    rate: float | None = None
    synth_engine: str = "fast"
    corruption: CorruptionParams | None = None
    decode_cfg: DecodeParams | None = None
    include_visuals: bool = True


class RedecodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utterance_id: str
    decode_cfg: DecodeParams | None = None
    method: str | None = None
    beam_width: int | None = None
    temperature: float | None = None
    blank_bias: float | None = None
    lm_weight: float | None = None
    insertion_bonus: float | None = None


# ---------------------------------------------------------------------------
# Serialization, parsing & validation helpers
# ---------------------------------------------------------------------------


def _sanitize_json(value: Any) -> Any:
    """Recursively convert numpy types and non-finite floats for strict JSON."""
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
        return _sanitize_json(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _sanitize_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(v) for v in value]
    return str(value)


def _encode_wav_bytes(wav: np.ndarray, sr: int = 16000) -> bytes:
    """Encode a 1D float32 waveform in [-1, 1] to 16-bit mono PCM WAV bytes."""
    arr = np.asarray(wav, dtype=np.float32).reshape(-1)
    if arr.size > 0 and not np.all(np.isfinite(arr)):
        arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0).astype(
            np.float32, copy=False
        )
    pcm = np.round(np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _parse_bool(value: Any, *, field_name: str, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s == "":
            return default
        if s in ("true", "1", "yes", "on"):
            return True
        if s in ("false", "0", "no", "off"):
            return False
    raise HTTPException(
        status_code=422,
        detail=f"Invalid boolean value for '{field_name}': {value!r}",
    )


def _parse_optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' must be a number, got bool",
        )
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            fval = float(s)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid float for '{field_name}': {value!r}",
            ) from exc
    elif isinstance(value, (int, float, np.integer, np.floating)):
        fval = float(value)
    else:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid float for '{field_name}': {value!r}",
        )
    if not math.isfinite(fval):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' must be finite, got {value!r}",
        )
    return fval


def _parse_optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise HTTPException(
            status_code=422,
            detail=f"'{field_name}' must be an integer, got bool",
        )
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            return int(s)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid integer for '{field_name}': {value!r}",
            ) from exc
    if isinstance(value, (int, np.integer)):
        return int(value)
    raise HTTPException(
        status_code=422,
        detail=f"Invalid integer for '{field_name}': {value!r}",
    )


def _build_decode_config(params: DecodeParams | Mapping[str, Any] | None) -> DecodeConfig:
    """Construct and validate a DecodeConfig, raising HTTP 422 on invalid values."""
    if params is None:
        return DecodeConfig()

    if isinstance(params, DecodeParams):
        raw = params.model_dump()
    elif isinstance(params, Mapping):
        raw = dict(params)
    else:
        raise HTTPException(status_code=422, detail="decode_cfg must be an object")

    defaults = DecodeConfig()
    method_val = raw.get("method")
    if method_val is None or (isinstance(method_val, str) and method_val.strip() == ""):
        method = defaults.method
    elif isinstance(method_val, str):
        method = method_val.strip().lower()
    else:
        raise HTTPException(status_code=422, detail="decode_cfg.method must be a string")

    bw = _parse_optional_int(raw.get("beam_width"), field_name="beam_width")
    beam_width = defaults.beam_width if bw is None else bw
    if beam_width < 1 or beam_width > _MAX_BEAM_WIDTH:
        raise HTTPException(
            status_code=422,
            detail=f"beam_width must be between 1 and {_MAX_BEAM_WIDTH}, got {beam_width}",
        )

    temp = _parse_optional_float(raw.get("temperature"), field_name="temperature")
    temperature = defaults.temperature if temp is None else temp

    bb = _parse_optional_float(raw.get("blank_bias"), field_name="blank_bias")
    blank_bias = defaults.blank_bias if bb is None else bb

    lw = _parse_optional_float(raw.get("lm_weight"), field_name="lm_weight")
    lm_weight = defaults.lm_weight if lw is None else lw

    ib = _parse_optional_float(raw.get("insertion_bonus"), field_name="insertion_bonus")
    insertion_bonus = defaults.insertion_bonus if ib is None else ib

    try:
        return DecodeConfig(
            method=method,
            beam_width=beam_width,
            temperature=temperature,
            blank_bias=blank_bias,
            lm_weight=lm_weight,
            insertion_bonus=insertion_bonus,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _resolve_corruption_dict(
    params: CorruptionParams | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate and normalize corruption parameters; return None if clean."""
    if params is None:
        return None
    if isinstance(params, CorruptionParams):
        raw = params.model_dump()
    elif isinstance(params, Mapping):
        raw = dict(params)
    else:
        raise HTTPException(status_code=422, detail="corruption must be an object")

    snr_db = _parse_optional_float(raw.get("snr_db"), field_name="snr_db")
    if snr_db is not None and (snr_db < _MIN_SNR_DB or snr_db > _MAX_SNR_DB):
        raise HTTPException(
            status_code=422,
            detail=f"snr_db must be between {_MIN_SNR_DB} and {_MAX_SNR_DB}, got {snr_db}",
        )

    noise_type_raw = raw.get("noise_type")
    if noise_type_raw is None or (
        isinstance(noise_type_raw, str) and noise_type_raw.strip() == ""
    ):
        noise_type = "white"
    elif isinstance(noise_type_raw, str):
        noise_type = noise_type_raw.strip().lower()
    else:
        raise HTTPException(status_code=422, detail="noise_type must be a string")
    if noise_type not in ("white", "pink"):
        raise HTTPException(
            status_code=422,
            detail=f"noise_type must be 'white' or 'pink', got {noise_type!r}",
        )

    band_limit_raw = raw.get("band_limit")
    band_low = _parse_optional_float(
        raw.get("band_limit_low"), field_name="band_limit_low"
    )
    band_high = _parse_optional_float(
        raw.get("band_limit_high"), field_name="band_limit_high"
    )

    band_limit: tuple[float, float] | None = None
    if band_limit_raw is not None and band_limit_raw != "":
        if isinstance(band_limit_raw, str):
            s = band_limit_raw.strip()
            try:
                if s.startswith("["):
                    parsed = json.loads(s)
                else:
                    parsed = [float(part.strip()) for part in s.split(",")]
            except (ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid band_limit format: {band_limit_raw!r}",
                ) from exc
        elif isinstance(band_limit_raw, (list, tuple)):
            parsed = list(band_limit_raw)
        else:
            raise HTTPException(
                status_code=422,
                detail="band_limit must be a 2-element [low_hz, high_hz] list",
            )
        if not isinstance(parsed, list) or len(parsed) != 2:
            raise HTTPException(
                status_code=422,
                detail="band_limit must have exactly 2 values [low_hz, high_hz]",
            )
        lo = _parse_optional_float(parsed[0], field_name="band_limit[0]")
        hi = _parse_optional_float(parsed[1], field_name="band_limit[1]")
        if lo is None or hi is None:
            raise HTTPException(
                status_code=422, detail="band_limit values must be numeric"
            )
        band_limit = (lo, hi)
    elif band_low is not None or band_high is not None:
        if band_low is None or band_high is None:
            raise HTTPException(
                status_code=422,
                detail="Both band_limit_low and band_limit_high must be provided together",
            )
        band_limit = (band_low, band_high)

    speed_val = _parse_optional_float(raw.get("speed"), field_name="speed")
    speed = 1.0 if speed_val is None else speed_val
    if speed < _MIN_SPEED or speed > _MAX_SPEED:
        raise HTTPException(
            status_code=422,
            detail=f"speed must be between {_MIN_SPEED} and {_MAX_SPEED}, got {speed}",
        )

    gain_val = _parse_optional_float(raw.get("gain_db"), field_name="gain_db")
    gain_db = 0.0 if gain_val is None else gain_val
    if gain_db < _MIN_GAIN_DB or gain_db > _MAX_GAIN_DB:
        raise HTTPException(
            status_code=422,
            detail=f"gain_db must be between {_MIN_GAIN_DB} and {_MAX_GAIN_DB}, got {gain_db}",
        )

    seed = _parse_optional_int(raw.get("seed"), field_name="seed")

    if band_limit is not None:
        lo, hi = band_limit
        if lo < 0.0 or hi <= lo:
            raise HTTPException(
                status_code=422,
                detail=f"band_limit must satisfy 0 <= low < high, got {band_limit}",
            )

    is_noop = (
        snr_db is None
        and band_limit is None
        and math.isclose(speed, 1.0, rel_tol=0.0, abs_tol=1e-9)
        and math.isclose(gain_db, 0.0, rel_tol=0.0, abs_tol=1e-9)
    )
    if is_noop:
        return None

    return {
        "snr_db": snr_db,
        "noise_type": noise_type,
        "band_limit": band_limit,
        "speed": speed,
        "gain_db": gain_db,
        "seed": seed,
    }


def _apply_optional_corruption(
    wav: np.ndarray,
    sr: int,
    params: CorruptionParams | Mapping[str, Any] | None,
) -> tuple[np.ndarray, float]:
    """Validate and apply optional waveform corruption; returns (wav, speed)."""
    resolved = _resolve_corruption_dict(params)
    if resolved is None:
        return wav, 1.0
    try:
        corrupted = apply_corruption(
            wav,
            sr,
            snr_db=resolved["snr_db"],
            noise_type=resolved["noise_type"],
            band_limit=resolved["band_limit"],
            speed=resolved["speed"],
            gain_db=resolved["gain_db"],
            seed=resolved["seed"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return corrupted, float(resolved["speed"])


def _preset_details_map() -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for name, cfg in yomu.PRESETS.items():
        details[str(name)] = {
            "description": str(cfg.get("description", "")),
            "hz": float(cfg.get("hz", 230.0)),
            "fscale": float(cfg.get("fscale", 1.0)),
            "yure": float(cfg.get("yure", 0.0)),
            "rate": float(cfg.get("rate", 1.0)),
        }
    return details


def _validate_positive_finite(
    val: float | None, *, name: str, lo: float = 0.0, hi: float = 1e6, inclusive_lo: bool = False
) -> float | None:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise HTTPException(status_code=422, detail=f"'{name}' must be a number")
    fval = float(val)
    if not math.isfinite(fval):
        raise HTTPException(status_code=422, detail=f"'{name}' must be finite")
    too_low = fval < lo if inclusive_lo else fval <= lo
    if too_low or fval > hi:
        op = ">=" if inclusive_lo else ">"
        raise HTTPException(
            status_code=422,
            detail=f"'{name}' must satisfy {name} {op} {lo} and <= {hi}, got {fval}",
        )
    return fval


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------


def create_app(
    checkpoint_path: str | Path | None = None,
    engine: ASREngine | None = None,
) -> FastAPI:
    """Create the Tsukinami ASR FastAPI application.

    If ``engine`` is provided, it takes precedence over ``checkpoint_path``.
    If neither is provided, the app starts in no-model mode (``GET /``,
    ``GET /api/health``, and ``GET /api/info`` still succeed while inference
    endpoints return HTTP 503).
    """
    if engine is not None:
        resolved_engine: ASREngine | None = engine
    elif checkpoint_path is not None:
        resolved_engine = ASREngine.from_checkpoint(checkpoint_path)
    else:
        resolved_engine = None

    app = FastAPI(
        title="Tsukinami ASR Playground",
        description="Interactive Japanese CTC ASR & Tsukinami TTS round-trip playground.",
        version="0.1.0",
    )
    app.state.engine = resolved_engine
    app.state.engine_lock = threading.Lock()

    def _get_engine() -> ASREngine | None:
        return app.state.engine

    def _require_engine() -> ASREngine:
        eng = _get_engine()
        if eng is None:
            raise HTTPException(
                status_code=503,
                detail="No ASR model loaded. Launch server with --checkpoint PATH.",
            )
        return eng

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> HTMLResponse:
        if not _WEB_INDEX_PATH.is_file():
            raise HTTPException(
                status_code=404,
                detail="Web playground index.html not found.",
            )
        html = _WEB_INDEX_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=html, media_type="text/html; charset=utf-8")

    @app.get("/api/health")
    async def get_health() -> dict[str, Any]:
        return {
            "status": "ok",
            "model_loaded": _get_engine() is not None,
        }

    @app.get("/api/info")
    async def get_info() -> dict[str, Any]:
        presets = list(yomu.PRESETS.keys())
        preset_details = _preset_details_map()
        eng = _get_engine()
        if eng is None:
            return _sanitize_json(
                {
                    "model_loaded": False,
                    "arch": None,
                    "num_parameters": 0,
                    "param_count": 0,
                    "subsampling_factor": None,
                    "frame_stride_ms": None,
                    "model_config": None,
                    "audio_config": None,
                    "vocab_size": 0,
                    "vocab": [],
                    "blank_id": 0,
                    "tokenizer_mode": None,
                    "tokenizer": None,
                    "tsukinami_presets": presets,
                    "preset_details": preset_details,
                    "has_lm": False,
                    "cache_size": 0,
                    "max_cache_size": 0,
                    "checkpoint_path": None,
                    "epoch": None,
                    "best_val_cer": None,
                    "checkpoint": None,
                    "history": [],
                }
            )

        with app.state.engine_lock:
            info = eng.info()
        info["model_loaded"] = True
        info["tsukinami_presets"] = presets
        info["preset_details"] = preset_details
        return _sanitize_json(info)

    @app.post("/api/transcribe")
    async def post_transcribe(request: Request) -> dict[str, Any]:
        eng = _require_engine()
        content_type = (request.headers.get("content-type") or "").lower()

        decode_dict: dict[str, Any] = {}
        corruption_dict: dict[str, Any] = {}
        include_visuals = True
        raw_audio_bytes: bytes

        if "multipart/form-data" in content_type:
            try:
                form = await request.form()
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to parse multipart form data: {exc}",
                ) from exc

            upload = form.get("file")
            if upload is None:
                raise HTTPException(
                    status_code=422, detail="Missing 'file' field in multipart upload."
                )
            if hasattr(upload, "read"):
                raw_audio_bytes = await upload.read()
            elif isinstance(upload, (bytes, bytearray)):
                raw_audio_bytes = bytes(upload)
            else:
                raise HTTPException(
                    status_code=422, detail="'file' field must be an uploaded audio file."
                )

            if len(raw_audio_bytes) == 0:
                raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
            if len(raw_audio_bytes) > _MAX_AUDIO_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Audio file exceeds {_MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit.",
                )

            # Merge query params and form fields (form takes precedence)
            merged: dict[str, Any] = dict(request.query_params)
            for key, val in form.multi_items():
                if key == "file":
                    continue
                if isinstance(val, str):
                    merged[key] = val

            # Optional JSON blobs in form fields
            if merged.get("decode_cfg"):
                try:
                    parsed_dec = json.loads(str(merged["decode_cfg"]))
                except json.JSONDecodeError as exc:
                    raise HTTPException(
                        status_code=422, detail=f"Invalid JSON in decode_cfg: {exc}"
                    ) from exc
                if not isinstance(parsed_dec, dict):
                    raise HTTPException(
                        status_code=422, detail="decode_cfg must be a JSON object"
                    )
                decode_dict.update(parsed_dec)

            if merged.get("corruption"):
                try:
                    parsed_corr = json.loads(str(merged["corruption"]))
                except json.JSONDecodeError as exc:
                    raise HTTPException(
                        status_code=422, detail=f"Invalid JSON in corruption: {exc}"
                    ) from exc
                if not isinstance(parsed_corr, dict):
                    raise HTTPException(
                        status_code=422, detail="corruption must be a JSON object"
                    )
                corruption_dict.update(parsed_corr)

            for k in (
                "method",
                "beam_width",
                "temperature",
                "blank_bias",
                "lm_weight",
                "insertion_bonus",
            ):
                if k in merged and str(merged[k]).strip() != "":
                    decode_dict[k] = merged[k]

            for k in (
                "snr_db",
                "noise_type",
                "band_limit",
                "band_limit_low",
                "band_limit_high",
                "speed",
                "gain_db",
                "seed",
            ):
                if k in merged and str(merged[k]).strip() != "":
                    corruption_dict[k] = merged[k]

            if "include_visuals" in merged:
                include_visuals = _parse_bool(
                    merged["include_visuals"],
                    field_name="include_visuals",
                    default=True,
                )
        else:
            raw_body = await request.body()
            if len(raw_body) > _MAX_JSON_BYTES:
                raise HTTPException(
                    status_code=413, detail="JSON request body too large."
                )
            if not raw_body:
                raise HTTPException(status_code=400, detail="Empty request body.")
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"Invalid JSON body: {exc}"
                ) from exc

            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=422, detail="JSON body must be an object."
                )

            if "audio_b64" not in payload:
                raise HTTPException(
                    status_code=422, detail="Missing 'audio_b64' field in JSON body."
                )
            audio_b64 = payload["audio_b64"]
            if not isinstance(audio_b64, str) or not audio_b64.strip():
                raise HTTPException(
                    status_code=400, detail="'audio_b64' must be a non-empty base64 string."
                )
            b64_str = audio_b64.strip()
            if b64_str.startswith("data:") and "," in b64_str:
                b64_str = b64_str.split(",", 1)[1].strip()
            try:
                raw_audio_bytes = base64.b64decode(b64_str, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail=f"Invalid base64 in 'audio_b64': {exc}"
                ) from exc

            if len(raw_audio_bytes) == 0:
                raise HTTPException(status_code=400, detail="Decoded audio is empty.")
            if len(raw_audio_bytes) > _MAX_AUDIO_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Decoded audio exceeds {_MAX_AUDIO_BYTES // (1024 * 1024)} MiB limit.",
                )

            if payload.get("decode_cfg") is not None:
                if not isinstance(payload["decode_cfg"], dict):
                    raise HTTPException(
                        status_code=422, detail="decode_cfg must be an object."
                    )
                decode_dict.update(payload["decode_cfg"])

            if payload.get("corruption") is not None:
                if not isinstance(payload["corruption"], dict):
                    raise HTTPException(
                        status_code=422, detail="corruption must be an object."
                    )
                corruption_dict.update(payload["corruption"])

            if "include_visuals" in payload:
                include_visuals = _parse_bool(
                    payload["include_visuals"],
                    field_name="include_visuals",
                    default=True,
                )

        decode_cfg = _build_decode_config(decode_dict if decode_dict else None)

        target_sr = eng.audio_cfg.sample_rate
        try:
            wav, sr = load_wav_bytes(raw_audio_bytes, target_sr=target_sr)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if wav.size == 0:
            raise HTTPException(status_code=400, detail="Decoded audio has zero samples.")

        wav, _ = _apply_optional_corruption(
            wav, sr, corruption_dict if corruption_dict else None
        )

        with app.state.engine_lock:
            result = eng.transcribe(
                wav,
                sr=sr,
                decode_cfg=decode_cfg,
                include_visuals=include_visuals,
            )

        return _sanitize_json(result)

    @app.post("/api/tts-roundtrip")
    async def post_tts_roundtrip(req: TTSRoundtripRequest) -> dict[str, Any]:
        eng = _require_engine()

        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="'text' must be non-empty.")
        if len(text) > _MAX_TTS_TEXT_LEN:
            raise HTTPException(
                status_code=422,
                detail=f"'text' must be at most {_MAX_TTS_TEXT_LEN} characters.",
            )

        preset = req.preset.strip()
        if preset not in yomu.PRESETS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown preset {preset!r}. "
                    f"Available presets: {sorted(yomu.PRESETS.keys())}"
                ),
            )

        synth_engine = req.synth_engine.strip().lower()
        if synth_engine not in ("fast", "tsukinami"):
            raise HTTPException(
                status_code=422,
                detail=f"synth_engine must be 'fast' or 'tsukinami', got {req.synth_engine!r}",
            )

        hz = _validate_positive_finite(req.hz, name="hz", lo=0.0, hi=2000.0)
        fscale = _validate_positive_finite(req.fscale, name="fscale", lo=0.0, hi=5.0)
        yure = _validate_positive_finite(
            req.yure, name="yure", lo=0.0, hi=1.0, inclusive_lo=True
        )
        rate = _validate_positive_finite(req.rate, name="rate", lo=0.0, hi=5.0)

        decode_cfg = _build_decode_config(req.decode_cfg)
        # Validate corruption upfront before synthesis
        _ = _resolve_corruption_dict(req.corruption)

        target_sr = eng.audio_cfg.sample_rate
        try:
            if synth_engine == "fast":
                default_p = yomu.PRESETS["default"]
                cur_p = yomu.PRESETS[preset]
                eff_hz = hz if hz is not None else float(cur_p["hz"])
                f0_scale = eff_hz / float(default_p["hz"])
                eff_fscale = (
                    fscale
                    if fscale is not None
                    else float(cur_p["fscale"]) / float(default_p["fscale"])
                )
                eff_rate = (
                    rate
                    if rate is not None
                    else float(cur_p["rate"]) / float(default_p["rate"])
                )
                wav, moras = synthesize_fast_kotoba(
                    text,
                    sr=target_sr,
                    f0_scale=f0_scale,
                    fscale=eff_fscale,
                    rate=eff_rate,
                )
            else:
                overrides: dict[str, Any] = {}
                if hz is not None:
                    overrides["hz"] = hz
                if fscale is not None:
                    overrides["fscale"] = fscale
                if yure is not None:
                    overrides["yure"] = yure
                if rate is not None:
                    overrides["rate"] = rate
                wav, moras = synthesize_tsukinami(
                    text,
                    preset=preset,
                    sr=target_sr,
                    overrides=overrides or None,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if wav.size == 0 or len(moras) == 0:
            raise HTTPException(
                status_code=400,
                detail="No speakable Japanese kana moras produced from input text.",
            )

        wav_out, eff_speed = _apply_optional_corruption(wav, target_sr, req.corruption)

        if not math.isclose(eff_speed, 1.0, rel_tol=0.0, abs_tol=1e-9):
            scaled_moras = [
                {
                    "t": str(m["t"]),
                    "a": round(float(m["a"]) / eff_speed, 5),
                    "e": round(float(m["e"]) / eff_speed, 5),
                }
                for m in moras
            ]
        else:
            scaled_moras = [
                {
                    "t": str(m["t"]),
                    "a": round(float(m["a"]), 5),
                    "e": round(float(m["e"]), 5),
                }
                for m in moras
            ]

        wav_bytes = _encode_wav_bytes(wav_out, sr=target_sr)
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

        with app.state.engine_lock:
            asr_res = eng.transcribe(
                wav_out,
                sr=target_sr,
                decode_cfg=decode_cfg,
                include_visuals=req.include_visuals,
            )

        cer_details = compute_cer([text], [asr_res["text"]], normalize_kana=True)

        payload = {
            **asr_res,
            "reference_text": text,
            "preset": preset,
            "synth_engine": synth_engine,
            "audio_b64": audio_b64,
            "sample_rate": target_sr,
            "ground_truth_moras": scaled_moras,
            "cer": float(cer_details["cer"]),
            "cer_details": cer_details,
        }
        return _sanitize_json(payload)

    @app.post("/api/redecode")
    async def post_redecode(req: RedecodeRequest) -> dict[str, Any]:
        eng = _require_engine()
        utt_id = req.utterance_id.strip()
        if not utt_id:
            raise HTTPException(
                status_code=422, detail="'utterance_id' must be non-empty."
            )

        dec_dict: dict[str, Any] = (
            req.decode_cfg.model_dump() if req.decode_cfg is not None else {}
        )
        for field in (
            "method",
            "beam_width",
            "temperature",
            "blank_bias",
            "lm_weight",
            "insertion_bonus",
        ):
            val = getattr(req, field)
            if val is not None:
                dec_dict[field] = val

        decode_cfg = _build_decode_config(dec_dict if dec_dict else None)

        try:
            with app.state.engine_lock:
                result = eng.redecode(utt_id, decode_cfg)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown or evicted utterance_id: {utt_id!r}",
            ) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return _sanitize_json(result)

    return app
