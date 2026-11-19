# Milestone M6 Implementation Worker (`worker_1`) Handoff

## Created Files (Exclusive Ownership)
1. `/home/antigravity/poidowl/tsukinami/asr/server.py`
2. `/home/antigravity/poidowl/tsukinami/asr/web/index.html`
3. `/home/antigravity/poidowl/tsukinami/tests/test_asr_web.py`

No other repository files were created or modified.

---

## Implementation Summary

### 1. FastAPI Backend (`asr/server.py`)
- **`create_app(checkpoint_path: str | Path | None = None, engine: ASREngine | None = None) -> FastAPI`**:
  - Explicit `engine` takes precedence over `checkpoint_path`; omitting both starts in no-model mode (`app.state.engine = None`).
  - Guards `engine` calls with `app.state.engine_lock = threading.Lock()` for thread safety.
  - Sanitizes all API responses via `_sanitize_json` (converting numpy scalars/arrays and replacing any non-finite floats with `None`).
- **`GET /`**: Serves `asr/web/index.html` (`200 OK`, `text/html; charset=utf-8`).
- **`GET /api/health`**: Returns `{"status": "ok", "model_loaded": bool}`.
- **`GET /api/info`**: Returns `engine.info()` enriched with `model_loaded: True`, full `yomu.PRESETS` keys (`tsukinami_presets`), and `preset_details`; returns a clean structured payload with `model_loaded: False` and `tsukinami_presets` when no model is loaded.
- **`POST /api/transcribe`**:
  - Supports both `multipart/form-data` (`file` upload + optional form/query decode & corruption fields or JSON strings, with strict boolean parsing so `"false"`/`"0"` → `False` and empty strings for optional numeric params → `None`) AND `application/json` (`audio_b64` with optional `data:...;base64,` prefix + `decode_cfg` + `corruption` + `include_visuals`).
  - Uses `asr.audio.load_wav_bytes` and `asr.audio.apply_corruption`, enforcing payload size caps (20 MiB audio / 30 MiB JSON), `beam_width <= 64`, `0.25 <= speed <= 4.0`, and rejecting partial `band_limit_low`/`band_limit_high`.
  - Cleanly maps bad/empty/corrupt audio or invalid params to HTTP `400`/`422` (`413` on oversized payload) and `503` when no model is loaded.
- **`POST /api/tts-roundtrip`**:
  - Validates `text` (non-empty, ≤500 chars), `preset` (against `yomu.PRESETS`), `synth_engine` (`"fast"` or `"tsukinami"`), finite parameter bounds (`hz > 0`, `fscale > 0`, `yure >= 0`, `rate > 0`), `decode_cfg`, and `corruption`.
  - Synthesizes via `synthesize_fast_kotoba` (mapping preset relative to `"default"`) or `synthesize_tsukinami`, rejects empty audio or zero speakable moras (`wav.size == 0 or len(moras) == 0`) with HTTP `400`, applies optional corruption, scales `ground_truth_moras` timestamps by `1/speed` when `speed != 1.0`, encodes post-corruption 16-bit PCM WAV to `audio_b64`, runs `engine.transcribe`, and computes `compute_cer([text], [res["text"]], normalize_kana=True)`.
- **`POST /api/redecode`**:
  - Calls `engine.redecode(utterance_id, decode_cfg)` on cached frame posteriors (`<10 ms`).
  - Returns `404` on unknown/evicted `utterance_id`, `422` on invalid `decode_cfg` or empty ID, and `503` when no model is loaded.

### 2. Zero-CDN Interactive Web Playground (`asr/web/index.html`)
- **Strict Zero-CDN**: Zero `http://`, `https://`, protocol-relative `//`, or external CDN references anywhere in the file.
- **6 Interactive Panels** in the dark-navy bilingual (Japanese + English) "月並み ASR" aesthetic:
  1. **Tsukinami TTS → ASR Round-Trip**: Kana input, 6 clickable sample phrase chips, dynamic preset selector, `fast`/`tsukinami` engine toggle, audio player, hypothesis + Ground-Truth + CER/S/D/I/RTF badges.
  2. **Audio Input**: Browser Web Audio API microphone recorder (with live RMS level meter, timer, linear resampling to 16 kHz, pure-JS 16-bit PCM WAV encoder) + drag-and-drop / file-picker WAV upload + re-run button.
  3. **Noise & Filter Corruption Lab**: Additive noise toggle + SNR slider (-5..35 dB) + white/pink selector + telephone band-pass (300–3400 Hz) toggle + speed slider (0.70–1.35x).
  4. **Live CTC Decoding Knobs**: `method` (beam/greedy), `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus` wired to `POST /api/redecode` with 55 ms debounce, monotonic sequence guard (`state.redecodeSeq`), live latency badge, instant client-side Levenshtein CER recomputation, and Top-N beam hypotheses table.
  5. **4 Aligned Canvas 2D Visualizers**: Waveform + VAD overlay, Log-Mel Spectrogram (Inferno LUT + 2nd–98th percentile contrast), CTC Frame Posterior probability heatmap, and Viterbi Alignment + Ground-Truth Mora dual-lane ribbon — all HiDPI-scaled and guarded against empty arrays.
  6. **Model & Training History Inspector**: Architecture/parameters/vocab/checkpoint cards, scrollable vocab strip, and dual-axis Loss + Val CER training curve canvas.

### 3. Unit & Integration Test Suite (`tests/test_asr_web.py`)
- 16 deterministic tests using FastAPI `TestClient` with a fast module-scoped `cnn_bigru` checkpoint fixture (including 3-epoch training history), no-model app, and LM-enabled engine.
- Covers all endpoints, happy paths, resampling, multipart boolean/empty-field edge cases, error codes (`400`/`422`/`404`/`503`), `/api/redecode` fast latency, strict zero-CDN regex verification, HTML structural balance, and `node --check` JS syntax verification.

---

## Verification Commands & Exact Outputs

### 1. `.venv/bin/pytest tests/test_asr_web.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 16 items

tests/test_asr_web.py ................                                   [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 16 passed, 1 warning in 7.85s =========================
```

### 2. `.venv/bin/pytest tests/ -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 151 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ...................                               [ 23%]
tests/test_asr_decoding.py ......................................        [ 48%]
tests/test_asr_dsp.py .............................................      [ 78%]
tests/test_asr_models.py .................                               [ 89%]
tests/test_asr_web.py ................                                   [100%]

================== 151 passed, 2 warnings in 75.86s (0:01:15) ==================
```

### 3. `git status --short`
```text
?? .agents/
?? .gitignore
?? PROJECT.md
?? TEST_INFRA.md
?? TEST_READY.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/
```
(Zero tracked TTS files modified; only the 3 owned M6 files were added.)
