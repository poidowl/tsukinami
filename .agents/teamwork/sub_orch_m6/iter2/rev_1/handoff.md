# Primary Reviewer (`rev_1`, Iteration 2) Handoff — Milestone M6

## Verdict: `APPROVE`

All Iteration 2 fixes in `asr/web/index.html` and `tests/test_asr_web.py` are verified, `asr/server.py` remains clean and fully compliant with `PROJECT.md §8` and `SCOPE.md`, all 153 M1–M6 unit tests pass, and zero tracked TTS files or M1–M5 files were modified.

---

## Code Inspection Summary

### 1. `asr/web/index.html` — Iteration 2 Fixes Verified
- **Blocking Fix (`chal_2` Defect 1 — `#dropZone` / `#btnPickWav` / `#wavFileInput` click recursion)** (`asr/web/index.html:2030-2045`):
  - `el.wavFileInput` stops click propagation (`e.stopPropagation()`), preventing programmatic `.click()` on the nested `<input type="file">` from bubbling back to `#dropZone`.
  - `el.btnPickWav` calls `e.stopPropagation()` before `el.wavFileInput.click()`.
  - `el.dropZone` guards with `e.target !== el.btnPickWav && e.target !== el.wavFileInput && !el.btnPickWav.contains(e.target)` before triggering `el.wavFileInput.click()`.
  - Defense-in-depth prevents infinite recursion across all click targets (`#btnPickWav`, children of `#btnPickWav`, `#dropZone`, children of `#dropZone`, and `#wavFileInput` directly).
- **UX Consistency Fix (`chal_2` Defect 2 — Client/Server CER Parity)** (`asr/web/index.html:973-985`):
  - `normalizeKanaClient(s)` now maps hiragana (`U+3041..U+3096`) to katakana (`+ 0x60`) and returns `out` directly without stripping punctuation (`、`, `。`, etc.), matching `asr/metrics.py` (`compute_cer(..., normalize_kana=True)` via `kotoba.to_kata`).
  - Client-side CER recalculation during `/api/redecode` slider adjustments now matches server-side `/api/tts-roundtrip` CER exactly.
- **Minor Polish (`rev_1`/`rev_2` — Object URL cleanup)** (`asr/web/index.html:1773-1779`):
  - `runTtsRoundtrip()` revokes `state.lastObjectUrl` and resets it to `null` before assigning the base64 data URI to `el.audioPlayer.src`, preventing blob URL leaks when switching from uploaded/mic audio to TTS round-trip.
- **Zero-CDN & Self-Containment**:
  - Verified zero external URLs or CDN references remain; JS passes `node --check`.

### 2. `tests/test_asr_web.py` — Regression Coverage Verified
- `test_dropzone_click_no_infinite_recursion_regression` (`tests/test_asr_web.py:675-793`): validates both static guards and executes the extracted click handlers in a Node.js DOM event-bubbling harness across all 5 click target scenarios.
- `test_client_cer_normalization_matches_server_compute_cer` (`tests/test_asr_web.py:796-850`): executes the extracted `normalizeKanaClient` + `computeClientCer` in Node.js and verifies exact equality (`ref_len`, `substitutions`, `deletions`, `insertions`, `cer`) against `asr.metrics.compute_cer(..., normalize_kana=True)` across 7 Japanese/punctuation/empty test pairs.

### 3. `asr/server.py` — Compliance with `PROJECT.md §8` & `SCOPE.md`
- `create_app(checkpoint_path=None, engine=None) -> FastAPI`: engine precedence over `checkpoint_path`, graceful no-model mode.
- `GET /`: serves `asr/web/index.html` (`200 OK`, `text/html; charset=utf-8`).
- `GET /api/health`: returns `{"status": "ok", "model_loaded": bool}`.
- `GET /api/info`: returns checkpoint metadata, vocab, architecture, `tsukinami_presets`, `preset_details`, and `history` (including when `model_loaded` is `False`).
- `POST /api/transcribe`: handles both multipart WAV uploads and JSON `audio_b64` payloads with decode & corruption parameters; returns `400`/`422` on invalid inputs and `503` when no model is loaded.
- `POST /api/tts-roundtrip`: supports `fast` and `tsukinami` engines, presets/overrides, optional corruption with speed-adjusted `ground_truth_moras`, base64 WAV encoding, ASR transcription, and `compute_cer(..., normalize_kana=True)`; returns `400`/`422` on invalid inputs and `503` when no model is loaded.
- `POST /api/redecode`: cached fast re-decoding under `engine_lock`; returns `404` for unknown `utterance_id`, `422` for invalid decode config, and `503` when no model is loaded.

---

## Independent Verification Commands & Outputs

### 1. Full M1–M6 Unit Test Suite: `.venv/bin/pytest tests/ -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 153 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ...................                               [ 22%]
tests/test_asr_decoding.py ......................................        [ 47%]
tests/test_asr_dsp.py .............................................      [ 77%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_web.py ..................                                 [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 153 passed, 2 warnings in 82.11s (0:01:22) ==================
```

### 2. Repository Integrity: `git status --short && echo "---DIFF---" && git diff --stat`
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
---DIFF---
```
- Exit code `0`. Zero existing tracked TTS files modified.
- No defects found.
