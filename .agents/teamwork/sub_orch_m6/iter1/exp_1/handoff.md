# Explorer 1 Handoff — Backend & API Contract Design (`asr/server.py`)

## 1. Verified Existing Interfaces (M1–M5 & TTS)

All signatures and behaviors below were verified directly from source files (zero M1–M5 modifications required).

### 1.1 CLI Entry Point (`asr/__main__.py`, lines 351–377)
- `_cmd_serve` imports and invokes:
  ```python
  from asr.server import create_app
  app = create_app(checkpoint_path=ckpt_path)
  uvicorn.run(app, host=args.host, port=args.port)
  ```
- `ckpt_path` is `str | None` (default `None` when `--checkpoint` is omitted).

### 1.2 Inference Engine (`asr/inference.py`)
- `ASREngine.from_checkpoint(path: str | Path, lm: CharNgramLM | None = None, *, device: str = "cpu", max_cache_size: int = 32) -> ASREngine`
  - Raises `FileNotFoundError`, `IsADirectoryError`, or `ValueError` on corrupt checkpoints.
- `engine.audio_cfg: AudioConfig` (default `sample_rate=16000`).
- `engine.transcribe(wav: np.ndarray, sr: int = 16000, decode_cfg: DecodeConfig | None = None, *, include_visuals: bool = False) -> dict[str, Any]`
  - Always returns:
    - `text: str`
    - `hypotheses: list[dict]` — each `{"text": str, "score": float, "acoustic_score": float, "lm_score": float}`
    - `alignment: list[dict]` — each `{"token": str, "start_sec": float, "end_sec": float, "confidence": float}`
    - `rtf: float`
    - `duration_sec: float`
    - `utterance_id: str` (16-char hex UUID, cached in LRU `OrderedDict` of size 32)
  - When `include_visuals=True`, additionally returns:
    - `waveform: list[float]` (downsampled ≤ 2000 pts, 5 decimals)
    - `log_mel: list[list[float]]` (≤ 600 frames × `n_mels`, 4 decimals)
    - `ctc_posteriors: dict` — `{"times_sec": list[float], "top_tokens": list[str], "probs": list[list[float]]}` (≤ 400 frames, top 12 tokens with `<blank>` at index 0)
    - `vad_segments: list[list[float]]` — `[[start_sec, end_sec], ...]`
- `engine.redecode(utterance_id: str, decode_cfg: DecodeConfig) -> dict[str, Any]`
  - Raises `KeyError` if `utterance_id` is unknown or evicted.
  - Raises `TypeError` if `decode_cfg` is not a `DecodeConfig`.
  - Returns: `{"text", "hypotheses", "alignment", "utterance_id", "duration_sec", "decode_ms"}`.
- `engine.info() -> dict[str, Any]`
  - Strictly JSON-serializable dict with keys:
    `arch`, `num_parameters`, `param_count`, `subsampling_factor`, `frame_stride_ms`, `model_config`, `audio_config`, `vocab_size`, `vocab`, `blank_id`, `tokenizer_mode`, `tokenizer`, `tsukinami_presets`, `has_lm`, `cache_size`, `max_cache_size`, `checkpoint_path`, `epoch`, `best_val_cer`, `checkpoint`, `history`.

### 1.3 Audio I/O & Corruptions (`asr/audio.py`)
- **`load_wav_bytes(data: bytes, target_sr: int = 16000) -> tuple[np.ndarray, int]`** (lines 229–257) **already exists!**
  - Decodes RIFF/WAVE PCM (8/16/24/32-bit) and IEEE float (32/64-bit) completely in-memory (no temp files needed).
  - Performs stereo-to-mono mixdown, FFT resampling to `target_sr`, and NaN/Inf clamping to `[-1.0, 1.0]`.
  - Falls back to `ffmpeg` pipe for non-WAV formats if `ffmpeg` is on PATH.
  - Raises `ValueError` cleanly on empty bytes, corrupt RIFF/WAVE, or unsupported/invalid bytes.
  - Note: Not re-exported in `asr/__init__.py`; import directly from `asr.audio`.
- `save_wav(path, wav, sr)` writes to a `Path` only. For `audio_b64` in `/api/tts-roundtrip`, encode in-memory via `io.BytesIO` + stdlib `wave.open(buf, "wb")` using identical 16-bit PCM quantization (`np.round(np.clip(nan_to_num(wav), -1, 1) * 32767.0).astype("<i2")`).
- `apply_corruption(wav, sr, *, snr_db=None, noise_type="white", band_limit=None, speed=1.0, gain_db=0.0, seed=None) -> np.ndarray`
  - Validates `noise_type in ("white", "pink")`, `speed > 0` finite, `gain_db` finite, `snr_db` finite or None, `band_limit` 2-tuple with `0 <= low < high` and `low < sr / 2`. Raises `ValueError` on invalid params.

### 1.4 Speech Synthesis (`asr/synth_data.py` & `yomu.py`)
- `yomu.PRESETS`: 8 presets — `"default"`, `"ossan"`, `"robot"`, `"horror"`, `"whisper"`, `"chibi"`, `"utahime"`, `"choir"`.
  - Each entry has keys: `description`, `seed`, `tsubu`, `hz`, `fscale`, `yure`, `shimmer`, `tadayoi`, `line_g`, `ap_n`, `rate` (plus optional `uta_trance`, `uta_choir`).
- `synthesize_fast_kotoba(text, *, sr=16000, f0_scale=1.0, fscale=1.0, rate=1.0, snr_db=None, seed=None) -> tuple[np.ndarray, list[dict]]`
  - Each mora dict has `{"t": str, "a": float, "e": float}`.
- `synthesize_tsukinami(text, *, preset="default", sr=16000, overrides=None, cache_dir=None) -> tuple[np.ndarray, list[dict]]`
  - Accepts any key in `yomu.PRESETS`.
  - `overrides` accepts keys in `_YOMU_PRM_KEYS` (including `"hz"`, `"fscale"`, `"yure"`, `"rate"`).

### 1.5 Metrics & Config (`asr/metrics.py`, `asr/config.py`)
- `compute_cer(refs, hyps, *, normalize_kana=False) -> dict`
  - Returns `{"cer": float, "substitutions": int, "deletions": int, "insertions": int, "ref_len": int}`.
  - Pass `normalize_kana=True` for TTS round-trip so Hiragana inputs match Katakana ASR hypotheses (consistent with `asr/__main__.py` lines 199 & 325).
- `alignment_boundary_error(gt_moras, pred_align) -> dict` (optional bonus metric).
- `DecodeConfig(method="beam", beam_width=8, temperature=1.0, blank_bias=0.0, lm_weight=0.0, insertion_bonus=0.0)`
  - Strict `__post_init__` validation: `method in ("greedy", "beam")`, `beam_width >= 1` int, `temperature > 0` finite, `lm_weight >= 0` finite, `blank_bias` & `insertion_bonus` finite. Raises `ValueError` on invalid values.

### 1.6 Installed Web Stack Versions (`.venv`)
- `fastapi==0.165.0`, `pydantic==2.14.3` (Pydantic v2), `starlette==1.10.0`, `uvicorn==0.54.0`, `httpx==0.28.1`.

---

## 2. Subtle Mismatches & Gotchas to Handle in `asr/server.py`

1. **`yomu.PRESETS` (8) vs `DEFAULT_TSUKINAMI_PRESETS` (6)**:
   - `engine.info()` returns `"tsukinami_presets": list(DEFAULT_TSUKINAMI_PRESETS)` (6 items).
   - `GET /api/info` should override `"tsukinami_presets": list(yomu.PRESETS.keys())` (all 8) and add `"preset_details"` (mapping preset name → `{description, hz, fscale, yure, rate}`) so the UI can populate sliders per preset and match `SCOPE.md`.
2. **`engine.info()` omits `model_loaded`**:
   - `GET /api/info` must explicitly include `"model_loaded": True` when loaded, and return a clean JSON object with `"model_loaded": False`, `"tsukinami_presets": list(yomu.PRESETS.keys())`, `"preset_details": ...`, `"arch": None`, `"vocab": []`, `"vocab_size": 0`, `"history": []`, etc. when `engine is None`.
3. **Unvalidated TTS overrides in `synthesize_tsukinami`**:
   - `yomu.build_carve_rc` computes `436.6 / hz` (crashes with `ZeroDivisionError` if `hz == 0`) and does not range-check `hz`, `fscale`, `yure`, `rate`.
   - `asr/server.py` MUST validate before calling synthesis:
     - `hz`: finite, `> 0` (e.g. `40.0 <= hz <= 1200.0` or `> 0`)
     - `fscale`: finite, `> 0` (e.g. `0.2 <= fscale <= 3.0` or `> 0`)
     - `yure`: finite, `>= 0` (e.g. `0.0 <= yure <= 1.0`)
     - `rate`: finite, `> 0` (e.g. `0.2 <= rate <= 4.0` or `> 0`)
4. **Silent empty-array return from `synthesize_fast_kotoba`**:
   - Unlike `synthesize_tsukinami` (which raises `ValueError` when no speakable kana moras exist), `synthesize_fast_kotoba("   ")` or `synthesize_fast_kotoba("123")` returns `(np.zeros(0, dtype=np.float32), [])`.
   - `POST /api/tts-roundtrip` must check `text.strip()` AND check `wav.size == 0` → return HTTP `400`/`422`.
5. **Preset/override mapping for `synth_engine == "fast"`**:
   - Always validate `preset in yomu.PRESETS` (even for `fast`) so unknown preset consistently returns `400`/`422`.
   - Map `yomu.PRESETS[preset]` relative to `yomu.PRESETS["default"]` so `"default"` preset uses `f0_scale=1.0, fscale=1.0, rate=1.0` (matching fast-synth training distribution):
     - `eff_hz = hz if hz is not None else float(yomu.PRESETS[preset]["hz"])`
     - `f0_scale = eff_hz / float(yomu.PRESETS["default"]["hz"])`
     - `eff_fscale = fscale if fscale is not None else float(yomu.PRESETS[preset]["fscale"]) / float(yomu.PRESETS["default"]["fscale"])`
     - `eff_rate = rate if rate is not None else float(yomu.PRESETS[preset]["rate"]) / float(yomu.PRESETS["default"]["rate"])`
6. **Ground-truth mora scaling under speed corruption**:
   - When `corruption.speed != 1.0` in `/api/tts-roundtrip`, scale `m["a"]` and `m["e"]` by `1.0 / speed` so the ground-truth mora ribbon aligns with the time-stretched waveform.
7. **Strict JSON serialization (no NaN/Inf, no raw numpy types)**:
   - FastAPI/Starlette `JSONResponse` fails with HTTP 500 on `NaN`/`Inf`.
   - Add a lightweight `_sanitize_json(obj)` helper in `asr/server.py` (convert `np.integer`→`int`, `np.floating`→finite `float` or `None`, `np.ndarray`→list, recursively) and apply it to all API responses.
8. **`yomu` import path fallback**:
   - Mirror `asr/synth_data.py` lines 20–32 so `import yomu` succeeds even if invoked outside the repo root.

---

## 3. Complete `asr/server.py` Implementation Plan

### 3.1 Module Exports & Factory
```python
__all__ = ["create_app"]

def create_app(
    checkpoint_path: str | Path | None = None,
    engine: ASREngine | None = None,
) -> FastAPI:
```
- Resolution:
  - If `engine is not None`: `resolved_engine = engine`
  - Else if `checkpoint_path is not None`: `resolved_engine = ASREngine.from_checkpoint(checkpoint_path)`
  - Else: `resolved_engine = None`
- Store `app.state.engine = resolved_engine`.
- Helper `_require_engine() -> ASREngine`: reads `app.state.engine`; if `None`, raises `HTTPException(status_code=503, detail="No ASR model loaded. Start server with --checkpoint PATH.")`.

### 3.2 Pydantic v2 Request Schemas & Helpers
- `DecodeParams(BaseModel)`:
  - `method: str = "beam"`, `beam_width: int = 8`, `temperature: float = 1.0`, `blank_bias: float = 0.0`, `lm_weight: float = 0.0`, `insertion_bonus: float = 0.0`
  - Helper `_build_decode_config(params: Mapping | DecodeParams | None) -> DecodeConfig` (raises `HTTPException(422, ...)` on `ValueError`/`TypeError`).
- `CorruptionParams(BaseModel)`:
  - `snr_db: float | None = None`, `noise_type: str = "white"`, `band_limit: list[float] | tuple[float, float] | None = None`, `band_limit_low: float | None = None`, `band_limit_high: float | None = None`, `speed: float = 1.0`, `gain_db: float = 0.0`, `seed: int | None = None`
  - Helper `_apply_optional_corruption(wav, sr, corruption) -> tuple[np.ndarray, float]`: resolves `band_limit` vs `(band_limit_low, band_limit_high)` (rejects half-specified band_limit with 422), applies `apply_corruption` only if any parameter is non-default, catches `ValueError` → `HTTPException(422, ...)`, returns `(wav_out, speed)`.
- `TTSRoundtripRequest(BaseModel)`:
  - `text: str`, `preset: str = "default"`, `hz: float | None = None`, `fscale: float | None = None`, `yure: float | None = None`, `rate: float | None = None`, `synth_engine: str = "fast"`, `corruption: CorruptionParams | None = None`, `decode_cfg: DecodeParams | None = None`, `include_visuals: bool = True`
- `RedecodeRequest(BaseModel)`:
  - `utterance_id: str`, `decode_cfg: DecodeParams | None = None`, plus optional flat overrides (`method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`) merged if `decode_cfg` is omitted.
- `_encode_wav_bytes(wav: np.ndarray, sr: int = 16000) -> bytes`: in-memory 16-bit mono PCM WAV via `io.BytesIO` + `wave`.

### 3.3 Endpoint Contracts

| Endpoint | Method | Success | Error Codes | Details |
|---|---|---|---|---|
| `/` | `GET` | `200` `text/html; charset=utf-8` | `404` if HTML missing | Reads `Path(__file__).resolve().parent / "web" / "index.html"` via `HTMLResponse`. |
| `/api/health` | `GET` | `200` JSON | — | `{"status": "ok", "model_loaded": engine is not None}`. |
| `/api/info` | `GET` | `200` JSON | — | When loaded: `{**engine.info(), "model_loaded": True, "tsukinami_presets": list(yomu.PRESETS.keys()), "preset_details": ...}`. When `engine is None`: `{"model_loaded": False, "arch": None, "num_parameters": 0, "vocab_size": 0, "vocab": [], "tsukinami_presets": list(yomu.PRESETS.keys()), "preset_details": ..., "history": [], "has_lm": False}`. |
| `/api/transcribe` | `POST` | `200` JSON (`TranscribeResult`) | `400` bad/empty audio or malformed JSON/base64, `413` >20 MB, `422` invalid decode/corruption params or missing `file`/`audio_b64`, `503` no model | Uses `request: Request` to support BOTH `multipart/form-data` (`file` upload + form/query params) AND `application/json` (`audio_b64` + `decode_cfg` + `corruption` + `include_visuals`). Strips optional `data:...;base64,` prefix. Decodes with `load_wav_bytes(..., target_sr=engine.audio_cfg.sample_rate)`. |
| `/api/tts-roundtrip` | `POST` | `200` JSON | `400`/`422` empty/unspeakable text, unknown preset/engine, out-of-range TTS/decode/corruption params, `503` no model | Synthesizes via `fast` or `tsukinami`, applies optional corruption (scaling `ground_truth_moras` if `speed != 1.0`), runs `engine.transcribe`, computes `compute_cer([text], [res["text"]], normalize_kana=True)`, encodes `audio_b64`. Returns `{**asr_res, "reference_text", "preset", "synth_engine", "audio_b64", "sample_rate", "ground_truth_moras", "cer", "cer_details"}`. |
| `/api/redecode` | `POST` | `200` JSON | `404` unknown `utterance_id`, `422` invalid `decode_cfg` or empty `utterance_id`, `503` no model | Calls `engine.redecode(utterance_id, decode_cfg)`. Pure cached posterior decoding (`<10 ms`). |

### 3.4 Multipart Param Parsing Rules for `POST /api/transcribe`
- Check `_require_engine()` first so no-model mode always returns `503`.
- Inspect `content_type = (request.headers.get("content-type") or "").lower()`:
  - If `"multipart/form-data"` in `content_type`:
    - `form = await request.form()`
    - `upload = form.get("file")` (if missing or not an `UploadFile` / bytes → `HTTPException(422, "Missing 'file' upload")`).
    - Read bytes (reject empty with `400`, >20 MB with `413`).
    - Merge `request.query_params` and `form` (form wins):
      - Parse `decode_cfg` JSON string if present, plus flat keys `method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`.
      - Parse `corruption` JSON string if present, plus flat keys `snr_db`, `noise_type`, `band_limit` (JSON or `"lo,hi"`), `band_limit_low`, `band_limit_high`, `speed`, `gain_db`, `seed`.
      - Parse `include_visuals` (bool string, default `True`).
      - Catch `ValueError` on numeric/bool parsing → `HTTPException(422, ...)`.
  - Else (`application/json` or empty):
    - Parse JSON body (`try: payload = await request.json()` → `400` on decode error; must be `dict`).
    - Require `audio_b64` non-empty string (`422` if missing, `400` if empty or invalid base64).
    - Strip optional `data:audio/...;base64,` header before `base64.b64decode(..., validate=True)`.
    - Parse `decode_cfg`, `corruption`, `include_visuals` (default `True`).
- Decode WAV via `load_wav_bytes(raw_bytes, target_sr=engine.audio_cfg.sample_rate)` (catch `ValueError` → `400`).
- Apply optional corruption, run `engine.transcribe(...)`, sanitize JSON, and return.

---

## 4. Recommended Backend Test Coverage (`tests/test_asr_web.py`)
1. `GET /` → `200`, `text/html` content-type, non-empty HTML.
2. `GET /api/health` → `{"status": "ok", "model_loaded": True}` (and `False` when `create_app()` has no checkpoint/engine).
3. `GET /api/info` → contains `model_loaded: True`, `arch`, `vocab`, `vocab_size`, `tsukinami_presets` (all `yomu.PRESETS`), `history`; also works cleanly (`200`, `model_loaded: False`) with no model.
4. `POST /api/transcribe` (multipart WAV): valid 16 kHz & 44.1 kHz stereo WAV, with `include_visuals=True` (verifying `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`, `utterance_id`) and with corruption params (`snr_db`, `noise_type="pink"`, `band_limit_low=300`, `band_limit_high=3400`, `speed=1.1`).
5. `POST /api/transcribe` (JSON `audio_b64`): valid base64 WAV (and data-URI prefixed base64) + `decode_cfg` + `corruption`.
6. `POST /api/transcribe` error handling: corrupt bytes → `400`, empty file → `400`, invalid base64 → `400`, invalid `method`/`beam_width`/`snr_db` → `422`, no-model → `503`.
7. `POST /api/tts-roundtrip`:
   - `synth_engine="fast"` with Hiragana/Katakana text, returns `audio_b64` (decodable WAV), `ground_truth_moras`, `cer`, `cer_details`, `utterance_id`, visuals.
   - `synth_engine="tsukinami"` with preset (e.g. `"ossan"`) and overrides (`hz`, `fscale`, `yure`, `rate`).
   - With `corruption` enabled (`snr_db=10`, `band_limit=[300, 3400]`, `speed=1.1`).
   - Error cases: empty text → `400`/`422`, non-kana text → `400`/`422`, unknown preset → `400`/`422`, unknown `synth_engine` → `400`/`422`, `hz=0` → `422`, no-model → `503`.
8. `POST /api/redecode`:
   - Valid `utterance_id` from `/api/transcribe` or `/api/tts-roundtrip` with different `decode_cfg` (`greedy` vs `beam`, `blank_bias`, `temperature`) → `200`, `decode_ms` small (assert fast wall-clock latency), returns `text`, `hypotheses`, `alignment`.
   - Unknown `utterance_id` → `404`.
   - No-model → `503`.
9. `create_app(checkpoint_path=...)` loads a real saved `.pt` checkpoint cleanly (matching `python -m asr serve --checkpoint ...`).
