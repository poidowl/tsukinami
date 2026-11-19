VERDICT: GAPS_FOUND

# White-Box Challenger 2 — Iteration 1 Audit Report
**Focus Area**: `asr/inference.py`, `asr/__main__.py`, `asr/server.py`, `asr/web/index.html` (plus direct call-chain interaction with `asr/audio.py` corruption bounds)

---

## Executive Summary

Audited all four implementation modules (`asr/inference.py`, `asr/__main__.py`, `asr/server.py`, `asr/web/index.html`) and existing tests (`tests/test_asr_cli.py`, `tests/test_asr_web.py`), and executed isolated adversarial probes against HTTP endpoints, `ASREngine`, CLI subcommands, and JS error-handling logic.

Found **5 concrete, reproducible bugs / robustness defects** (including **HTTP 500 Internal Server Errors** on valid JSON/multipart requests with extreme finite `snr_db`/`gain_db`, broken frontend 422/500 error rendering, inconsistent CLI `--tts` empty/unspeakable handling, unprotected `ASREngine._cache` concurrency, and incomplete corrupt-checkpoint error normalization) plus **concrete untested failure-mode gaps** for `tests/test_asr_tier5_hardening.py`.

Zero files in the repository working tree were modified; all temporary probe directories were removed.

---

## Concrete Reproducible Bugs & Robustness Defects

### Bug 1 (High — HTTP 500 Internal Server Error + Float32 NaN/Inf Overflow): Unbounded `snr_db` and `gain_db` in `/api/transcribe` and `/api/tts-roundtrip`
- **Affected files / lines**:
  - `asr/server.py`: `_resolve_corruption_dict()` (lines 294, 368–369) and `_apply_optional_corruption()` (lines 409–422)
  - `asr/audio.py`: `apply_corruption()` (lines 492, 498–499)
- **Root cause**:
  - `_resolve_corruption_dict()` checks `math.isfinite()` on `snr_db` and `gain_db` but enforces **no numeric range bounds**.
  - Inside `asr/audio.py:apply_corruption()`:
    - Line 492: `target_noise_power = sig_power / (10.0 ** (snr_db / 10.0))`
      - When `snr_db = -5000.0`, `10.0 ** (-500.0)` underflows to `0.0` → **`ZeroDivisionError: float division by zero`**.
      - When `snr_db = 5000.0`, `10.0 ** 500.0` raises **`OverflowError: (34, 'Numerical result out of range')`**.
    - Line 498–499: `gain = np.float32(10.0 ** (gain_db / 20.0)); out = (out * gain).astype(np.float32)`
      - When `gain_db = 10000.0`, `10.0 ** 500.0` raises **`OverflowError`**.
      - When `gain_db = 1000.0`, `10.0 ** 50.0` overflows `float32` to `inf` (`RuntimeWarning: overflow encountered in cast`), and multiplying any zero sample `0.0 * inf` produces `NaN` (`RuntimeWarning: invalid value encountered in multiply`).
  - `_apply_optional_corruption()` in `asr/server.py:420` only catches `ValueError`, so `ZeroDivisionError` and `OverflowError` escape unhandled and return **HTTP 500 Internal Server Error** on both `POST /api/transcribe` (JSON **and** multipart) and `POST /api/tts-roundtrip`.
- **Exact Reproduction**:
  ```python
  # Observed via TestClient(app, raise_server_exceptions=False):
  client.post("/api/transcribe", json={"audio_b64": b64, "corruption": {"snr_db": -5000.0}})   # -> 500 Internal Server Error
  client.post("/api/transcribe", json={"audio_b64": b64, "corruption": {"snr_db": 5000.0}})    # -> 500 Internal Server Error
  client.post("/api/transcribe", json={"audio_b64": b64, "corruption": {"gain_db": 10000.0}})  # -> 500 Internal Server Error
  client.post("/api/transcribe", files={"file": ("a.wav", wav_bytes, "audio/wav")}, data={"snr_db": "-5000"})  # -> 500
  client.post("/api/tts-roundtrip", json={"text": "アイ", "corruption": {"snr_db": -5000.0}})  # -> 500 Internal Server Error
  client.post("/api/tts-roundtrip", json={"text": "アイ", "corruption": {"gain_db": 10000.0}}) # -> 500 Internal Server Error
  ```
- **Expected behavior**:
  - Enforce sane finite bounds in `_resolve_corruption_dict()` in `asr/server.py` (e.g., `snr_db` in `[-100.0, 120.0]`, `gain_db` in `[-100.0, 100.0]`) returning **HTTP 422**, AND harden `asr/audio.py:apply_corruption()` so extreme `snr_db`/`gain_db` never raise `ZeroDivisionError`/`OverflowError` or produce `NaN`/`Inf` waveforms (either validate bounds or clamp exponents safely and sanitize output).

---

### Bug 2 (Medium — Frontend Broken Error Handling): `asr/web/index.html` displays `"[object Object]"` on FastAPI 422 Pydantic errors and throws `SyntaxError` on non-JSON error responses
- **Affected file / lines**:
  - `asr/web/index.html`:
    - `runTtsRoundtrip()` lines 1792–1795
    - `transcribeBlob()` lines 1866–1869
    - `runRedecode()` lines 1913–1921
- **Observed code**:
  ```javascript
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || ("HTTP " + res.status));
  }
  ```
- **Observed behavior** (verified with live FastAPI 422 response + Node.js):
  1. FastAPI Pydantic validation errors (e.g., `POST /api/tts-roundtrip` with missing/invalid field) return `{"detail": [{"type": "missing", "loc": ["body", "text"], "msg": "Field required", ...}]}` where `data.detail` is an **Array of objects**. Passing that array to `new Error(data.detail)` stringifies it to `"[object Object]"`, displaying `"TTS ラウンドトリップエラー: [object Object]"` in `#errorBanner`.
  2. Any non-JSON error response (e.g., HTTP 500 plain-text `"Internal Server Error"`, HTTP 502/504 HTML) causes `await res.json()` to throw `SyntaxError: Unexpected token 'I', "Internal S"... is not valid JSON` before `if (!res.ok)` is reached, hiding the HTTP status code.
- **Expected behavior**:
  - Add a shared helper (e.g. `parseApiResponse(res)` / `formatApiError(data, status)`) that reads text / safely parses JSON, extracts human-readable strings when `data.detail` is an array of Pydantic error dicts (e.g., joining `item.loc.join('.') + ': ' + item.msg`), and falls back cleanly to `"HTTP " + res.status` (plus truncated plain-text body if present).

---

### Bug 3 (Medium — CLI Inconsistency): `python -m asr transcribe --tts ""` and `--tts "!!!"` with `--engine fast` silently succeed with exit code 0
- **Affected file / lines**:
  - `asr/__main__.py`: `_cmd_transcribe()` lines 312–326
- **Observed behavior** (reproduced via subprocess):
  - `python -m asr transcribe --checkpoint CKPT --tts "" --engine fast` → **`returncode=0`**, stdout: `Reference : \nPredicted : \nCER : 0.00% | Duration: 0.00s`
  - `python -m asr transcribe --checkpoint CKPT --tts "!!!" --engine fast` → **`returncode=0`**, stdout: `Reference : !!!\nPredicted : \nCER : 100.00% | Duration: 0.00s`
  - In contrast, `--engine tsukinami` returns `returncode=1` (`Error: text must be a non-empty string` / `text must contain at least one speakable kana mora`), and `POST /api/tts-roundtrip` returns HTTP 422 / 400 (`No speakable Japanese kana moras produced from input text.`).
- **Expected behavior**:
  - Validate `args.tts.strip()` is non-empty and `wav.size > 0` (and `len(_moras) > 0`) in `_cmd_transcribe()` for both engines, raising `ValueError` so the CLI exits cleanly with code 1 and an `Error: ...` message on stderr (no traceback).

---

### Bug 4 (Medium — Concurrency / Thread-Safety): `ASREngine._cache` has no internal synchronization lock
- **Affected file / lines**:
  - `asr/inference.py`: `ASREngine.__init__` (line 219), `_put_cache()` (lines 306–310), `redecode()` (lines 495–503), `info()` (line 554)
- **Root cause**:
  - `ASREngine` stores an unprotected `OrderedDict` (`self._cache`). While `asr/server.py` wraps calls in `app.state.engine_lock`, direct multi-threaded callers of `ASREngine` face:
    - TOCTOU check-then-act in `redecode()`: `if utterance_id not in self._cache:` → `self._cache.move_to_end(utterance_id)` → `entry = self._cache[utterance_id]` (can raise raw `OrderedDict` `KeyError` if evicted between lines 495 and 502).
    - Non-atomic insert + eviction loop in `_put_cache()`: concurrent writers can double-pop or violate `max_cache_size`.
- **Expected behavior**:
  - Protect all `self._cache` reads/writes/evictions inside `ASREngine` with `self._cache_lock = threading.RLock()` (keeping `redecode()` decode/align computation outside the lock after fetching `entry` so concurrent re-decodes don't unnecessarily serialize CPU work, or guarding cache access atomically).

---

### Bug 5 (Low–Medium — Error Normalization): `ASREngine.from_checkpoint()` leaks raw `TypeError` / `RuntimeError` for structurally corrupt `.pt` checkpoints
- **Affected file / lines**:
  - `asr/inference.py`: `ASREngine.from_checkpoint()` lines 248–285
- **Observed behavior** (reproduced in probe):
  - `torch.save({"model_config": "not_a_dict", "tokenizer": tok.to_dict(), "model_state_dict": {}}, p)` → `ASREngine.from_checkpoint(p)` raises raw `TypeError: Expected mapping for ModelConfig.from_dict, got str`.
  - `torch.save({"model_config": mcfg.to_dict(), "tokenizer": tok.to_dict(), "model_state_dict": {"wrong": torch.zeros(1)}}, p)` → raises raw `RuntimeError: Error(s) in loading state_dict ...`.
  - Lines 232–246 carefully normalize `load_checkpoint` corruption errors into `ValueError("Corrupt or invalid checkpoint ...")`, but lines 248–285 are outside that `try/except`.
- **Expected behavior**:
  - Wrap config/tokenizer deserialization and `model.load_state_dict(...)` in `try/except (KeyError, TypeError, ValueError, RuntimeError)` and raise `ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc`.

---

## Security & Robustness Checks That Passed

- **XSS / DOM Injection in `asr/web/index.html`**: All dynamic `innerHTML` assignments (`renderHypotheses`, `renderResultSummary`, `fetchApiInfo` presets & vocab pills, `runRedecode`) properly pass untrusted/API strings through `escapeHtml()`. `errorBannerText` and `gtText` use `.textContent`.
- **Zero-CDN**: No external URLs or CDN references in `asr/web/index.html`.
- **NaN / Infinity in JSON & Multipart**:
  - `POST /api/transcribe` (JSON & multipart), `POST /api/tts-roundtrip`, and `POST /api/redecode` reject `NaN`/`Infinity`/`-Infinity` in `temperature`, `blank_bias`, `snr_db`, `hz`, `rate`, `speed` with HTTP 422.
  - `POST /api/redecode` with `insertion_bonus=1e308` sanitizes `inf` scores to `null` via `_sanitize_json` (strict JSON, no 500).
- **Oversized & Malformed HTTP Payloads**:
  - Multipart upload `> 20 MiB` → HTTP 413.
  - 0-frame header-only WAV → HTTP 400.
  - Invalid UTF-8 JSON body → HTTP 400.
  - `Content-Type: text/plain` → HTTP 400.
  - `Content-Type: multipart/form-data` without boundary → HTTP 400.
  - Multipart `"file"` as plain text field (not UploadFile) → HTTP 422.
  - Non-ASCII base64 (`"あいうえお"`) → HTTP 400.
  - `band_limit` with `low >= Nyquist` (`[8000, 9000]` at 16 kHz) → HTTP 422.
  - `beam_width > 64` → HTTP 422.
- **Ultra-short audio (1-sample, 2-sample, 5-sample WAV)**: Both `cnn_bigru` and `conformer_lite` handle 1-sample WAVs cleanly (including with `band_limit`, `speed=4.0`, `pink` noise) and return valid HTTP 200 JSON.
- **CLI error handling**: `--lr nan`, `--lr inf`, `--arch conformer_lite --hidden-size 30`, empty/malformed/missing-key JSONL manifests, directory passed as `--checkpoint`, and `serve --checkpoint <corrupt.pt>` all exit cleanly with code 1 and `Error: ...` (no Python tracebacks).

---

## Proposed Adversarial Test Specifications for `tests/test_asr_tier5_hardening.py`

1. **`test_server_extreme_corruption_bounds_no_500`**:
   - Send `snr_db` (`-5000.0`, `5000.0`) and `gain_db` (`1000.0`, `10000.0`, `-10000.0`) via:
     - `POST /api/transcribe` (JSON `audio_b64` AND `multipart/form-data`)
     - `POST /api/tts-roundtrip`
   - Assert every request returns HTTP `422` (never `500`), and `apply_corruption()` never raises `ZeroDivisionError`/`OverflowError` or returns `NaN`/`Inf`.
2. **`test_server_nan_inf_and_malformed_http_payloads`**:
   - Raw JSON bodies with `NaN`, `Infinity`, `-Infinity` on `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode` → HTTP 422.
   - Multipart string values `"nan"`, `"inf"`, `"-inf"` for `temperature`, `snr_db`, `speed` → HTTP 422.
   - Invalid UTF-8 body, `text/plain` body, `multipart/form-data` without boundary, 0-frame WAV, non-ASCII `audio_b64`, JSON array/null body, multipart text-field `"file"`, oversized `> 20 MiB` upload (413) → all clean 4xx, never 500.
3. **`test_server_redecode_after_lru_eviction_and_concurrent_requests`**:
   - Create app with `ASREngine(..., max_cache_size=2)`, transcribe 3 utterances via `/api/transcribe`, assert `/api/redecode` returns `404` on evicted ID #1 and `200` on IDs #2 and #3.
   - Run concurrent threads calling `engine.transcribe()`, `engine.redecode()`, and `engine.info()` directly on `ASREngine(max_cache_size=2)` and assert zero exceptions and `len(engine._cache) <= 2`.
4. **`test_server_ultrashort_wav_both_architectures`**:
   - 1-sample and 2-sample WAVs (clean + `band_limit` + `speed=4.0` + `pink` noise) against both `cnn_bigru` and `conformer_lite` → HTTP 200 with strict finite JSON (`json.dumps(..., allow_nan=False)`).
5. **`test_engine_from_checkpoint_structurally_corrupt_raises_value_error`**:
   - Save `.pt` files with non-dict `model_config`, non-dict `tokenizer`, and mismatched `model_state_dict` → assert `ASREngine.from_checkpoint()` raises `ValueError` (not `TypeError`/`RuntimeError`).
6. **`test_cli_transcribe_tts_empty_and_unspeakable_fast_engine_fails_cleanly`**:
   - Run `python -m asr transcribe --checkpoint ... --tts "" --engine fast` and `--tts "!!!" --engine fast` → assert non-zero exit code (`rc == 1`), `"Error:"` in stderr, and `"Traceback"` not in stderr.
7. **`test_index_html_error_formatting_pydantic_422_and_non_json_500`** (Node.js runtime check):
   - Extract the response/error parsing helper from `asr/web/index.html` and verify via Node.js that:
     - FastAPI Pydantic 422 array `detail` formats into a readable message (must NOT contain `"[object Object]"`).
     - Non-JSON 500 plain-text `"Internal Server Error"` produces a readable HTTP 500 error message (must NOT throw `SyntaxError`).
