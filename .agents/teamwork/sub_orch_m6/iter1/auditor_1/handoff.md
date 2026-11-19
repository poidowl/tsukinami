# Milestone M6 Forensic Integrity Audit (`auditor_1`)

## Verdict: `CLEAN`

All Milestone M6 deliverables (`asr/server.py`, `asr/web/index.html`, `tests/test_asr_web.py`) are genuine, self-contained, scope-compliant, and independently verified with all 16 tests passing.

---

## 1. Scope & Git Integrity

- **Git working tree check** (`git status --short && git diff --stat`):
  - Zero tracked repository files were modified (`git diff --stat` is empty).
  - Existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) remain completely untouched.
- **M1–M5 & `tests_e2e/` integrity**:
  - Directory listing (`ls -lt`) confirms only the three M6-owned files were created during M6 (`Nov 19 04:49–04:50`):
    - `asr/server.py` (33,377 bytes)
    - `asr/web/index.html` (70,160 bytes)
    - `tests/test_asr_web.py` (21,367 bytes)
  - All M1–M5 source/test files (`03:10–04:31`) and `tests_e2e/` (`03:13–03:25`) are untouched.

---

## 2. Genuineness & Anti-Cheating Inspection

### `asr/server.py` (935 lines)
- **Genuine integration with M1–M5 & `yomu`**:
  - `ASREngine.from_checkpoint` (`L477`) in `create_app`, with explicit `engine` taking precedence and no-model mode (`None`) handled cleanly.
  - `eng.info()` (`L553`) in `GET /api/info`, enriched with `yomu.PRESETS` (`L427`, `L520`).
  - `asr.audio.load_wav_bytes` (`L737`), `asr.audio.apply_corruption` (`L410`), and `eng.transcribe` (`L749`) in `POST /api/transcribe` (supporting both `multipart/form-data` and JSON `audio_b64`).
  - `asr.synth_data.synthesize_fast_kotoba` (`L816`), `asr.synth_data.synthesize_tsukinami` (`L833`), `asr.audio.apply_corruption` (`L848`), `eng.transcribe` (`L873`), and `asr.metrics.compute_cer` (`L880`) in `POST /api/tts-roundtrip`.
  - `eng.redecode` (`L923`) in `POST /api/redecode` for cached frame-posterior re-decoding (`404` on unknown/evicted ID, `422` on invalid config, `503` when no model is loaded).
  - `GET /api/health` (`L511–L516`) returns real `{"status": "ok", "model_loaded": bool}`.
- **No cheating detected**: Zero hardcoded transcriptions, zero fake CERs, zero stubbed/mocked neural inference, proper thread-safe locking (`threading.Lock`), and non-finite float sanitization (`_sanitize_json`).

### `asr/web/index.html` (2,108 lines)
- **Strict Zero-CDN**: Zero `http://`, `https://`, protocol-relative `//`, `@import`, or external CDN/font/script/CSS references.
- **Genuine Backend API Calls**: Real `fetch()` calls to `/api/info` (`L1668`), `/api/tts-roundtrip` (`L1749`), `/api/transcribe` (`L1820`), and `/api/redecode` (`L1863`). *(Note: UI reads `model_loaded` from `/api/info` rather than issuing a separate `/api/health` call; `/api/health` is implemented on the backend and tested.)*
- **Genuine Canvas 2D Visualizers**: Real `getContext("2d")` HiDPI rendering for all 4 time-aligned visualizers (`drawWaveform` with VAD overlay, `drawMelSpectrogram` with 256-entry Inferno LUT + `ImageData`, `drawCtcPosteriors`, `drawAlignment` with ASR + Ground-Truth Mora dual lanes) plus `drawHistory` dual-axis training curve chart.
- **Genuine Web Audio API Mic & WAV Pipeline**: Real `navigator.mediaDevices.getUserMedia`, `AudioContext`, `createMediaStreamSource`, `createScriptProcessor`, live RMS level meter, `linearResample` to 16 kHz, and 16-bit PCM WAV header/sample encoding (`encodeWav16BitPCM`).

### `tests/test_asr_web.py` (672 lines, 16 tests)
- Exercises real FastAPI `TestClient` against real `cnn_bigru` PyTorch checkpoint (`build_model`, `torch.save`, `ASREngine.from_checkpoint`), real `CharNgramLM`, and real `synthesize_fast_kotoba` / `synthesize_tsukinami` audio synthesis.
- No mocks, no monkeypatches, no skipped tests, no tautological assertions.
- Includes static zero-CDN regex verification, HTML structural balance checks, and `node --check` JavaScript syntax verification.

---

## 3. Independent Test Execution

Command: `.venv/bin/pytest tests/test_asr_web.py -v`

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
======================== 16 passed, 1 warning in 10.47s ========================
```
