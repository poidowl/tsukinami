# Forensic Integrity Audit — Milestone M6 (Iteration 2, Intermediate Audit)

**Auditor**: `auditor_1` (Iteration 2)  
**Verdict**: **`CLEAN`**

## 1. Scope & Git Integrity

- Executed `git status --short && git diff --stat` in `/home/antigravity/poidowl/tsukinami`:
  - **Zero** existing tracked TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) were modified.
- Checked file modification timestamps across `asr/`, `asr/models/`, `asr/web/`, `tests/`, and `tests_e2e/`:
  - Only `asr/web/index.html` and `tests/test_asr_web.py` were modified in Iteration 2 (`asr/server.py` remains unchanged from Iteration 1).
  - **Zero** M1–M5 implementation/test files or `tests_e2e/` files were touched.

## 2. Genuineness & Anti-Cheating Verification

### `asr/server.py`
- Genuine FastAPI backend using real `ASREngine`, `load_wav_bytes`, `apply_corruption`, `synthesize_fast_kotoba`, `synthesize_tsukinami`, `compute_cer`, and `yomu.PRESETS`.
- Zero hardcoded or mocked inference/synthesis responses, strict Pydantic v2 validation (`extra="forbid"`), finite numeric checks, payload size limits, thread-safe `engine_lock`, and clean `400`/`404`/`413`/`422`/`503` error handling.

### `asr/web/index.html`
- **Zero external CDN links**: verified both by inspection and automated regex checks (no `http://`, `https://`, protocol-relative `//`, Google Fonts, or external JS/CSS).
- **Genuine Canvas 2D & Web Audio implementations**: real waveform + VAD overlay, Log-Mel spectrogram with 256-entry Inferno LUT and offscreen `ImageData`, CTC posterior heatmap, dual-lane ASR/GT-mora alignment ribbon, training history chart, and Web Audio API mic recorder with 16 kHz linear resampler and 16-bit PCM WAV encoder.
- **Verified Iteration 2 fixes**:
  1. **Dropzone click recursion fix** (`L2030-L2045`): `el.wavFileInput` stops click propagation, `el.btnPickWav` calls `e.stopPropagation()` before `el.wavFileInput.click()`, and `el.dropZone` guards `e.target !== el.btnPickWav && e.target !== el.wavFileInput && !el.btnPickWav.contains(e.target)`.
  2. **Client/server CER normalization parity** (`L973-L985`): `normalizeKanaClient(s)` converts hiragana (`U+3041..U+3096`) to katakana (`+ 0x60`) without stripping punctuation, matching `kotoba.to_kata` inside `asr/metrics.py::compute_cer(..., normalize_kana=True)`.
  3. **Object URL cleanup** (`L1773-L1779`): `runTtsRoundtrip()` revokes `state.lastObjectUrl` before setting `el.audioPlayer.src = "data:audio/wav;base64," + data.audio_b64`.

### `tests/test_asr_web.py`
- All 18 tests are non-tautological and exercise real FastAPI `TestClient` endpoints backed by a real PyTorch `cnn_bigru` checkpoint, real `ASREngine`, real `CharNgramLM`, real synthesis, and real audio corruption.
- Both new Iteration 2 regression tests execute actual extracted JS code from `asr/web/index.html` in Node.js:
  - `test_dropzone_click_no_infinite_recursion_regression`: runs extracted click handlers against a real event-bubbling `MockElement` DOM tree across 5 click scenarios.
  - `test_client_cer_normalization_matches_server_compute_cer`: runs extracted `normalizeKanaClient` + `computeClientCer` in Node.js and asserts exact parity (`ref_len`, `substitutions`, `deletions`, `insertions`, `cer`) against Python `compute_cer(..., normalize_kana=True)` across 7 test pairs including Japanese punctuation.

## 3. Independent Test Execution

Command: `.venv/bin/pytest tests/test_asr_web.py -v`  
Result: **`18 passed, 1 warning in 8.12s`** (exit code `0`).

## 4. Final Verdict

**`CLEAN`** — No integrity violations, no out-of-scope edits, no cheating/stubs/CDNs, and all 18 tests pass independently.
