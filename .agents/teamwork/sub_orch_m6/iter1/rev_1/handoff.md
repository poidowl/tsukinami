# Milestone M6 Primary Code Review (`rev_1`)

## Verdict: `APPROVE`

All Milestone M6 deliverables (`asr/server.py`, `asr/web/index.html`, `tests/test_asr_web.py`) satisfy `PROJECT.md §8` and `SCOPE.md`, pass the full M1–M6 unit test suite (`151 passed`), and leave all M1–M5 and existing TTS files untouched.

---

## Contract & Implementation Audit

### 1. `asr/server.py` (FastAPI Backend)
- **`create_app(checkpoint_path: str | Path | None = None, engine: ASREngine | None = None) -> FastAPI`**:
  - Matches `PROJECT.md §8` and `SCOPE.md`, and integrates cleanly with `asr/__main__.py` (`_cmd_serve`).
  - Explicit `engine` takes precedence over `checkpoint_path`; omitting both runs cleanly in no-model mode (`app.state.engine = None`).
  - Thread-safe access to `ASREngine` via `app.state.engine_lock` (`threading.Lock`).
  - Strict JSON sanitization (`_sanitize_json`) converts NumPy scalars/arrays and maps non-finite floats to `None`.
- **`GET /`**:
  - Returns `asr/web/index.html` with `200 OK` and `text/html; charset=utf-8` (and `404` if missing).
- **`GET /api/health`**:
  - Returns `{"status": "ok", "model_loaded": bool}` in both loaded and unloaded modes.
- **`GET /api/info`**:
  - Returns `engine.info()` enriched with `model_loaded: True`, `tsukinami_presets` (`list(yomu.PRESETS.keys())`), and `preset_details`; returns a well-formed schema with `model_loaded: False` and `history: []` when unloaded.
  - All keys align with `ASREngine.info()` and the frontend inspector in `asr/web/index.html`.
- **`POST /api/transcribe`**:
  - Supports both `multipart/form-data` (`file` upload + form/query decode & corruption fields or JSON blobs) and `application/json` (`audio_b64` with optional `data:...;base64,` URI prefix + `decode_cfg`, `corruption`, `include_visuals`).
  - Handles strict boolean parsing (`"false"` / `"0"` → `False`), empty optional numeric strings → `None`, partial `band_limit_low`/`band_limit_high` rejection, payload caps (`413`), invalid/empty/corrupt audio (`400`/`422`), and no-model mode (`503`).
- **`POST /api/tts-roundtrip`**:
  - Validates `text` (non-empty, ≤500 chars), `preset` (in `yomu.PRESETS`), `synth_engine` (`"fast"` / `"tsukinami"`), finite parameter bounds (`hz`, `fscale`, `yure`, `rate`), `decode_cfg`, and `corruption`.
  - Rejects empty audio / zero speakable moras with `400`, scales `ground_truth_moras` timestamps by `1 / speed` when speed perturbation is active, encodes post-corruption WAV as `audio_b64`, runs `engine.transcribe`, and computes `compute_cer([text], [asr_res["text"]], normalize_kana=True)`.
  - Returns `400`/`422` on invalid input and `503` when no model is loaded.
- **`POST /api/redecode`**:
  - Re-decodes cached `log_probs` via `engine.redecode(utt_id, decode_cfg)` (`<10 ms` typical latency).
  - Returns `404` on unknown/evicted `utterance_id`, `422` on invalid `decode_cfg` or empty `utterance_id`, and `503` when no model is loaded.

### 2. `asr/web/index.html` (Zero-CDN Interactive Web Playground)
- **Zero-CDN Verified**: No `http://`, `https://`, protocol-relative `//`, Google Fonts, or external JS/CSS links anywhere in the file.
- **Complete 6-Panel UX**:
  1. Tsukinami TTS → ASR Round-Trip panel (kana input, sample chips, preset & engine selectors, audio player, hypothesis + ground truth + CER/RTF/duration).
  2. Audio Input panel (Web Audio API mic recorder with level meter, timer, linear resampling to 16 kHz, 16-bit PCM WAV encoder; drag/drop & file-picker WAV upload; re-run button).
  3. Noise & Filter Corruption Lab (additive white/pink noise + SNR slider, telephone band-pass 300–3400 Hz toggle, speed slider, reset).
  4. Live CTC Decoding Knobs (`method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`) wired to debounced `POST /api/redecode` with monotonic sequence guard (`state.redecodeSeq`), latency badge, client-side Levenshtein CER recomputation, and Top-N beam hypotheses table.
  5. 4 HiDPI-scaled, time-aligned Canvas 2D Visualizers (Waveform + VAD overlay, Log-Mel Spectrogram with Inferno LUT & percentile contrast, CTC Frame Posteriors heatmap, Viterbi Alignment + Ground-Truth Mora dual-lane ribbon), all safely guarded against empty arrays.
  6. Model & Training History Inspector (architecture, parameter count, vocab size, vocab preview, dual-axis Train/Val Loss + Val CER canvas).
- **Minor non-blocking observation**: In `runTtsRoundtrip()`, assigning `el.audioPlayer.src = "data:audio/wav;base64," + data.audio_b64` does not revoke a prior `state.lastObjectUrl` from an earlier file upload/mic recording (it is revoked on the next `setAudioSourceBlob()` call). Harmless and non-blocking.

### 3. `tests/test_asr_web.py`
- 16 deterministic tests covering all endpoints, happy paths, resampling, multipart edge cases, error status codes (`400`/`422`/`404`/`503`), fast `/api/redecode`, strict zero-CDN regex checks, HTML structural balance, and `node --check` JS syntax validation.

---

## Verification Commands & Exact Outputs

### 1. Working Tree Integrity (`git status --short && git diff --stat`)
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
--- GIT DIFF ---
```
Confirmed: Zero tracked TTS files modified; `ls -la asr/ asr/web/ tests/` confirms only the 3 owned M6 files (`asr/server.py`, `asr/web/index.html`, `tests/test_asr_web.py`) were added and no M1–M5 files were altered.

### 2. Full M1–M6 Unit Test Suite (`.venv/bin/pytest tests/ -v`)
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
tests/test_asr_web.py ................                                   [ 100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 151 passed, 2 warnings in 83.61s (0:01:23) ==================
```
