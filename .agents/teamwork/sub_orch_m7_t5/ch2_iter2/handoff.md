VERDICT: NO_REMAINING_GAPS

# White-Box Challenger 2 Report — M7 Phase 2: Tier 5 Adversarial Coverage Hardening (Iteration 2 — Post-Hardening Verification)

## Focus Area Audited
- `asr/inference.py` (`ASREngine`, checkpoint loading, LRU cache concurrency, visual payload generation)
- `asr/__main__.py` (CLI subcommands `demo`, `generate`, `train`, `eval`, `transcribe`, `serve`)
- `asr/server.py` (FastAPI REST API: `GET /`, `GET /api/health`, `GET /api/info`, `POST /api/transcribe` JSON & multipart, `POST /api/tts-roundtrip`, `POST /api/redecode`)
- `asr/web/index.html` (Zero-CDN UI, `escapeHtml`, `formatApiError`, `parseApiResponse`, Canvas 2D visualizers, Web Audio recorder)
- `tests/test_asr_tier5_hardening.py` (Iteration 1 Tier 5 hardening test suite)

---

## Executive Summary
All Iteration 1 fixes in `asr/inference.py`, `asr/__main__.py`, `asr/server.py`, and `asr/web/index.html` were independently verified against adjacent edge cases, bypass attempts, malformed payloads, concurrency stress, and XSS/zero-CDN invariants using isolated scratch probes (staged in `mktemp -d` under `/tmp` and deleted cleanly).

No remaining concrete, reproducible bugs, HTTP 500s, security vulnerabilities, concurrency races, or critical untested failure modes were found.

---

## Modules Audited & Probes Executed

### 1. `asr/server.py` — HTTP API Robustness, Bounds & Concurrency
- **Corruption parameter bounds (`snr_db`, `gain_db`, `speed`, `band_limit`, `seed`)**:
  - Verified extreme `snr_db` / `gain_db` bounds (`[-100, 120]` / `[-100, 100]`) return HTTP `422` consistently across JSON `/api/transcribe`, multipart `/api/transcribe`, and `/api/tts-roundtrip`.
  - Probed negative and huge `seed` values (`-1`, `-999`, `2**64`, `10**100`): negative seeds cleanly return HTTP `422`; large positive seeds succeed (`200`) with finite JSON.
  - Probed malformed `band_limit` strings/lists (`"300,3400,5000"`, `"[300]"`, `"nan,3400"`, `[true, 3400]`): all return HTTP `422`.
  - Probed empty multipart form fields (`snr_db=""`, `band_limit=""`, `beam_width=""`, `method=""`): safely fall back to defaults (`200`).
- **Decoding parameter extremes (`temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`, `beam_width`, `method`)**:
  - Probed `temperature=1e-308`, `blank_bias=±1e308`, `lm_weight=1e308`, `insertion_bonus=±1e308` on `/api/transcribe` and `/api/redecode`: all return `200` with strict finite JSON (`json.dumps(..., allow_nan=False)` passes).
  - Probed `beam_width=0`, `beam_width=65`, `method="viterbi"`, `decode_cfg={"temperature": True}`, `decode_cfg=[]`, `decode_cfg={"lm_weight": "abc"}`: all return HTTP `422`.
- **`/api/tts-roundtrip` synthesis & validation boundaries**:
  - Probed `text` length boundary (`500` -> `200`, `501` -> `422`), `yure` bounds (`0.0`/`1.0` -> `200`, `-0.1`/`1.1` -> `422`).
  - Probed extreme small/large `hz` (`1e-9`), `fscale` (`1e-9`), and `rate` (`1e-9`, `1e-4`, `5.0`) on both `fast` and `tsukinami` engines: all return `200` cleanly with finite durations and JSON (no OOM or `ZeroDivisionError`).
  - Probed special text inputs (`"   "`, `"、、、"`, `"ッッッ"`, `"hello"`, `"漢字"`, `"ア'イ"`, `"ア/イ"`, `"ア0イ"`, `"ー"`) on both engines: zero HTTP 500s (`422` on whitespace, `400` on unspeakable inputs, `200` on valid/convertible inputs).
- **Malformed/crafted audio & payload size limits**:
  - Probed IEEE 32-bit float WAV with `NaN`/`Inf`/`-Inf`, IEEE float WAV with `1e30`, `sr=1` WAV, `sr=1000000` WAV, `data:audio/wav;base64,...` data URI, and base64 with embedded newlines: zero HTTP 500s (`200` with strict finite JSON or clean `400`).
  - Probed `> 30 MiB` JSON body -> HTTP `413`; `> 20 MiB` multipart upload -> HTTP `413`.
- **No-model mode & concurrent HTTP requests**:
  - Verified `create_app()` with no checkpoint returns `200` on `/`, `/api/health`, `/api/info` (`model_loaded: false`) and `503` on `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`.
  - Ran 18 concurrent requests across 6 threads mixing `/api/transcribe`, `/api/tts-roundtrip`, and `/api/info`: all returned HTTP `200`.

### 2. `asr/inference.py` — `ASREngine` Cache Lock & Checkpoint Loading
- **Cache thread safety**: Inspected `self._cache_lock = threading.RLock()` protecting all `_cache` mutations, LRU evictions, lookups, and `len()` accesses in `_put_cache`, `redecode`, and `info`, while keeping `_decode_and_align` outside the lock.
- **Corrupt checkpoint handling**:
  - Verified `ASREngine.from_checkpoint` normalizes structurally corrupt `model_config`, `audio_config`, `tokenizer`, `lm`, `model_state_dict`, and non-dict top-level checkpoints to `ValueError`.
  - *Minor non-blocking observation*: In `asr/inference.py` line 290 (`history = [dict(entry) for entry in raw_history]`), if a hand-crafted `.pt` checkpoint places non-mapping scalars inside `history` (e.g. `history=[123]`), `dict(entry)` sits just outside the `try/except` block and raises `TypeError` (which the CLI still catches cleanly and exits with `rc=1`, `Error: ...`). Similarly, `epoch="not_int"` is deferred to `int(meta["epoch"])` in `info()`. Neither affects real checkpoints or warrants another hardening cycle.

### 3. `asr/__main__.py` — CLI Subcommands & Error Handling
- Probed all CLI error paths via subprocess execution (`.venv/bin/python -m asr ...`):
  - `transcribe --tts "ア" --preset nonexistent` -> `rc=1`, `Error: Unknown tsukinami preset ...`, no traceback.
  - `transcribe --tts "!!!" --engine tsukinami` -> `rc=1`, `Error: text must contain at least one speakable kana mora ...`, no traceback.
  - `transcribe --wav <0-frame-wav>` -> `rc=1`, `Error: Corrupt WAV file ...`, no traceback.
  - `transcribe --checkpoint <corrupt>` and `serve --checkpoint <corrupt>` -> `rc=1`, `Error: ...`, no traceback.
  - `train --lr nan`, `train --seed -1`, `demo --seed -1`, `serve --port 0`, `serve --port 70000` -> all `rc=1`, `Error: ...`, no traceback.

### 4. `asr/web/index.html` — Zero-CDN, XSS Safety & Error Formatting
- **Zero-CDN check**: Regex scan for `https?://` confirmed `0` external URLs in `asr/web/index.html`.
- **XSS safety**: Audited every `innerHTML` write (`hypothesesBody`, `resultText`, `ttsPresetSelect`, `vocabPreview`) — all dynamic strings pass through `escapeHtml()`. Verified `escapeHtml('<img src=x onerror="alert(1)">\'&')` in Node.js escapes all HTML metacharacters.
- **Error formatting (`formatApiError` & `parseApiResponse`)**: Executed extracted JS helpers in Node.js across Pydantic 422 error arrays (single & multi-item), `{detail: null}`, `{detail: "   "}`, `{detail: {err: "bad"}}`, plain-text HTTP 500/502 responses, and `ok: true` with non-JSON body — all handled cleanly without `[object Object]` leaks or uncaught `SyntaxError`.

---

## Hygiene & Repository Integrity
- Zero working-tree files modified (`git status --short` unchanged).
- All temporary `/tmp/teamwork_probe.*` directories created via `mktemp -d` were removed via `rm -rf` prior to reporting.
