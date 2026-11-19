# Milestone M6 Scope: Interactive Web Playground ("遊べる ASR")

## Owned Files
1. `asr/server.py` — FastAPI backend
2. `asr/web/index.html` — Zero-CDN single-file HTML5 + CSS + vanilla JS Canvas 2D + Web Audio API interactive playground
3. `tests/test_asr_web.py` — Unit/integration tests via FastAPI `TestClient` + HTML/JS static & zero-CDN checks

## Detailed Requirements

### 1. `asr/server.py`
- `create_app(checkpoint_path: str | Path | None = None, engine: ASREngine | None = None) -> FastAPI`
  - If `engine` is provided, use it; else if `checkpoint_path` is provided, load `ASREngine.from_checkpoint(checkpoint_path)`; else run in no-model mode (`engine = None`).
- `GET /`
  - Serves `asr/web/index.html` (`200 OK`, `text/html; charset=utf-8`).
- `GET /api/health`
  - Returns `{"status": "ok", "model_loaded": bool}`.
- `GET /api/info`
  - Returns loaded checkpoint metadata (`engine.info()`), vocab, model architecture, available `tsukinami` presets (`list(yomu.PRESETS.keys())`), training history curves.
  - Works gracefully even when no model is loaded (`model_loaded: False`).
- `POST /api/transcribe`
  - Accepts BOTH:
    - `multipart/form-data` WAV upload (`file` field: `files={"file": (...)}`) + optional form/query decode & corruption params (`method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`, `snr_db`, `noise_type`, `band_limit_low`/`band_limit_high`, `speed`, `include_visuals`), AND
    - `application/json` body with `audio_b64` (base64 WAV) + `decode_cfg` + `corruption` + `include_visuals`.
  - Returns `TranscribeResult` JSON (with visuals when requested).
  - Returns HTTP `400`/`422` cleanly on invalid/corrupt/empty audio or invalid params; returns HTTP `503` if no model is loaded.
- `POST /api/tts-roundtrip`
  - Accepts JSON `{text, preset="default", hz=None, fscale=None, yure=None, rate=None, synth_engine="fast"|"tsukinami", corruption=None, decode_cfg=None, include_visuals=True}`.
  - Synthesizes Japanese audio via `synthesize_fast_kotoba` or `synthesize_tsukinami`, optionally applies `apply_corruption`, runs `engine.transcribe`, computes CER against `text` (`compute_cer`), encodes audio as base64 WAV (`audio_b64`).
  - Returns `{audio_b64, ground_truth_moras, cer, cer_details, text, hypotheses, alignment, rtf, duration_sec, utterance_id, ...visuals}`.
  - Returns HTTP `400`/`422` on invalid input (e.g., empty text, unknown preset/engine) and HTTP `503` if no model is loaded.
- `POST /api/redecode`
  - Accepts JSON `{utterance_id, decode_cfg}`.
  - Calls `engine.redecode` (<10 ms cached re-decoding without re-running neural net).
  - Returns HTTP `404` if `utterance_id` is unknown, `503` if no model is loaded.

### 2. `asr/web/index.html`
- **Zero external CDN links**: no `<script src="http...">`, no `<link href="http...">`, no Google Fonts, no external JS/CSS — 100% self-contained like `toybox.html`.
- Rich, playful Japanese+English "遊べる ASR" UX:
  - **Tsukinami TTS → ASR Round-Trip Panel**: Japanese kana input, preset selector (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`), engine toggle (`fast` / `tsukinami`), synth/transcribe button, audio playback, Ground-Truth vs ASR Hypothesis & CER readout.
  - **Audio Input Panel**: Browser Microphone recorder (Web Audio API -> WAV encoder) + WAV file upload drag/drop.
  - **Noise & Filter Corruption Lab**: SNR (dB) slider, white/pink noise selector, telephone band-pass (300–3400 Hz) toggle, speed slider.
  - **Live CTC Decoding Knobs**: `method` (greedy/beam), `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus` sliders wired to `POST /api/redecode` for instant `<10 ms` updates + Top-N beam hypotheses table.
  - **4 Canvas 2D Visualizers**: Waveform + VAD segments overlay, Log-Mel Spectrogram heatmap, CTC Frame Posterior probability heatmap, and Mora/Token Alignment timeline ribbon.
  - **Model & Training History Inspector**: Displays `/api/info` architecture, vocab size, and training/val loss & CER curve canvas.

### 3. `tests/test_asr_web.py`
- Thorough FastAPI `TestClient` + HTML/JS static & zero-CDN verification tests run via `.venv/bin/pytest tests/test_asr_web.py`.
- Covers all endpoints (`GET /`, `/api/health`, `/api/info`, `POST /api/transcribe` multipart & base64, `POST /api/tts-roundtrip` fast & tsukinami & corruption, `POST /api/redecode` fast latency & 404, invalid inputs 400/422, no-model 503, zero external CDN URLs in `index.html`, balanced HTML/JS syntax).
- Primary reviewer runs `.venv/bin/pytest tests/ -v` (all M1–M6 unit tests, excluding `tests_e2e/`).
