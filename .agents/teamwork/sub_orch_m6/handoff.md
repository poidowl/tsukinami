# Milestone M6 Handoff — Interactive Web Playground ("遊べる ASR")

## Status: **PASS** (Gate Approved in Iteration 2)

Milestone M6 is complete and independently verified across 2 iterations with unanimous approval from all 5 Iteration 2 verifiers (Primary Reviewer, Secondary Reviewer, 2 Adversarial Challengers, and Forensic Integrity Auditor).

---

## Deliverables Created (Exclusive File Ownership Respected)

1. **`/home/antigravity/poidowl/tsukinami/asr/server.py`**
   - `create_app(checkpoint_path: str | Path | None = None, engine: ASREngine | None = None) -> FastAPI` (integrates directly with `asr/__main__.py` `serve` subcommand; supports explicit `engine`, disk `checkpoint_path`, or graceful no-model mode).
   - `GET /` — serves zero-CDN `asr/web/index.html` (`200 OK`, `text/html; charset=utf-8`).
   - `GET /api/health` — returns `{"status": "ok", "model_loaded": bool}`.
   - `GET /api/info` — returns checkpoint metadata (`engine.info()`), architecture, vocab, `tsukinami_presets` (`list(yomu.PRESETS.keys())`), `preset_details`, training history curves, and `model_loaded: bool` (works cleanly even when no model is loaded).
   - `POST /api/transcribe` — supports BOTH `multipart/form-data` WAV uploads (`file` + optional form/query decode & corruption params with strict boolean & empty-string parsing) AND `application/json` (`audio_b64` including `data:` URI prefix + `decode_cfg`, `corruption`, `include_visuals`). Uses `asr.audio.load_wav_bytes` and `asr.audio.apply_corruption`; returns `400`/`422` cleanly on invalid/corrupt/empty audio or invalid params, `413` on oversized payload, `503` when no model is loaded.
   - `POST /api/tts-roundtrip` — synthesizes Japanese audio via `synthesize_fast_kotoba` (`"fast"`) or `synthesize_tsukinami` (`"tsukinami"`) with preset and voice overrides (`hz`, `fscale`, `yure`, `rate`), applies optional `apply_corruption` (scaling `ground_truth_moras` timestamps by `1 / speed`), encodes post-corruption 16-bit PCM WAV to `audio_b64`, runs `engine.transcribe`, and computes `compute_cer([text], [res["text"]], normalize_kana=True)`. Returns `400`/`422` on invalid/unspeakable inputs and `503` when no model is loaded.
   - `POST /api/redecode` — cached frame-posterior re-decoding via `engine.redecode` under `threading.Lock` (`<10 ms` latency; live `uvicorn` median `2.20 ms`, p95 `2.83 ms`), returning `404` on unknown/evicted `utterance_id`, `422` on invalid `decode_cfg`, and `503` when no model is loaded.
   - Strict JSON sanitization (`_sanitize_json`) maps non-finite floats (`NaN`/`Inf`) to `null`.

2. **`/home/antigravity/poidowl/tsukinami/asr/web/index.html`**
   - **Strictly Zero-CDN** (0 `http://`, 0 `https://`, 0 protocol-relative `//`, 0 external `<link>`/`<script src>`/`@import`/fonts).
   - Self-contained Japanese+English "遊べる ASR" interactive playground with all 6 required panels:
     1. Tsukinami TTS → ASR Round-Trip Panel (kana input, sample chips, dynamic preset selector, `fast`/`tsukinami` toggle, audio playback with `URL.revokeObjectURL` cleanup, ground-truth vs hypothesis & CER readout).
     2. Audio Input Panel (Web Audio API microphone recorder with RMS level meter, 16 kHz linear resampler, and 16-bit PCM WAV encoder + drag/drop & file-picker WAV upload).
     3. Noise & Filter Corruption Lab (SNR slider, white/pink noise, telephone 300–3400 Hz band-pass toggle, speed slider).
     4. Live CTC Decoding Knobs (`method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`) wired to debounced, sequence-guarded `POST /api/redecode` + Top-N beam hypotheses table + client-side CER parity with `compute_cer(..., normalize_kana=True)`.
     5. 4 HiDPI-scaled, time-aligned Canvas 2D Visualizers: Waveform + VAD segments overlay, Log-Mel Spectrogram (Inferno LUT), CTC Frame Posterior probability heatmap, and Mora/Token Alignment dual-lane ribbon (ASR + TTS ground truth).
     6. Model & Training History Inspector (`/api/info` architecture, vocab pills, dual-axis train/val loss & CER curve canvas).

3. **`/home/antigravity/poidowl/tsukinami/tests/test_asr_web.py`**
   - 18 deterministic unit/integration & static/runtime regression tests covering all endpoints, error codes (`400`/`404`/`422`/`503`), resampling, corruption, `<10 ms` `/api/redecode`, strict zero-CDN scan, `node --check` JS syntax, DOM click-bubbling non-recursion, and JS↔Python CER parity.

---

## Verification Summary (Iteration 2 — Final Gate)

- **Primary Reviewer (`iter2/rev_1`)**: `APPROVE` — `.venv/bin/pytest tests/ -v`: **153 passed** (82.11s, all M1–M6 unit tests, `tests_e2e/` excluded).
- **Secondary Reviewer (`iter2/rev_2`)**: `APPROVE` — `.venv/bin/pytest tests/test_asr_web.py -v`: **18 passed** (9.42s).
- **API Challenger (`iter2/chal_1`)**: `PASS` — verified all endpoints, strict JSON (no `NaN`/`Inf`), `<10 ms` cached `/api/redecode` (`2.20 ms` median on live uvicorn), LRU eviction `404`, and 16-thread live concurrency (`100/100`).
- **Frontend Challenger (`iter2/chal_2`)**: `PASS` — verified `node --check`, 5/5 DOM click-bubbling paths (Iteration 1 `#dropZone`/`#wavFileInput` recursion bug resolved), 19/19 JS↔Python CER parity pairs, 76/76 DOM IDs, 0 external CDN URLs, and `URL.revokeObjectURL` cleanup.
- **Forensic Auditor (`iter2/auditor_1`)**: `CLEAN` — verified zero edits to M1–M5 files, existing TTS files, or `tests_e2e/`; genuine implementations throughout; independently ran `.venv/bin/pytest tests/test_asr_web.py -v` (`18 passed` in 8.12s).

---

## Audit Trail
- Gate status: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m6/GATE_STATUS.md`
- Progress log: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m6/progress.md`
- Iteration 1 reports: `iter1/{exp_1,exp_2,exp_3,worker_1,rev_1,rev_2,chal_1,chal_2,auditor_1}/handoff.md`
- Iteration 2 reports: `iter2/{worker_2,rev_1,rev_2,chal_1,chal_2,auditor_1}/handoff.md`
