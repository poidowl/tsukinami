# Secondary Reviewer (`rev_2`) Handoff — Milestone M6: Interactive Web Playground ("遊べる ASR")

**Verdict: `APPROVE`**

---

## 1. Test Execution Results

### Target-Scoped Suite: `.venv/bin/pytest tests/test_asr_web.py -v`
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
======================== 16 passed, 1 warning in 10.40s ========================
```

### Independent Static & Functional Probes (Temporary Dir Cleaned Up)
1. **Zero-CDN scan on `asr/web/index.html`**:
   ```text
   http_matches: []
   proto_rel: []
   raw_double_slash: []
   ```
   Zero `http://`, zero `https://`, and zero `//` occurrences anywhere in the 2,108-line file.
2. **Inline JS syntax & client-side 16-bit PCM WAV encoder round-trip probe** (`node --check` + `linearResample(48k -> 16k)` + `encodeWav16BitPCM` -> `asr.audio.load_wav_bytes`):
   ```text
   Encoded WAV bytes: 8044 resampled len: 4000
   load_wav_bytes OK: len=4000, sr=16000, min=-0.5000, max=0.5000
   ```
3. **`git status --short`**: Confirmed zero modifications to any tracked existing TTS files.

---

## 2. Deep Code Review Summary (`asr/web/index.html` & `asr/server.py`)

### A. Strict Zero-CDN Compliance
- **PASS**: `asr/web/index.html` is 100% self-contained (inline CSS + inline vanilla JS + system font stack). Zero external `<script>`, `<link>`, `@import`, `url()`, `http://`, `https://`, or protocol-relative `//` references exist anywhere in the file.

### B. Frontend-to-Backend Field Name Alignment
Verified every endpoint, request payload, and response field consumed by `asr/web/index.html` against `asr/server.py`, `asr/inference.py`, and `asr/train.py`:
- **`GET /api/info`**:
  - Consumed: `model_loaded`, `tsukinami_presets`, `arch`, `model_config` (`hidden_size`, `num_layers`), `subsampling_factor`, `num_parameters`, `frame_stride_ms`, `vocab_size`, `tokenizer_mode`, `best_val_cer`, `checkpoint_path`, `epoch`, `has_lm`, `vocab`, `history` (`epoch`, `train_loss`, `val_loss`, `val_cer`).
  - Matches `asr/server.py` (both loaded and no-model payloads), `ASREngine.info()`, and `asr/train.py` history entries.
- **`POST /api/tts-roundtrip`**:
  - Request JSON keys: `text`, `preset`, `synth_engine`, `corruption` (`snr_db`, `noise_type`, `band_limit`, `speed`), `decode_cfg` (`method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`), `include_visuals`. All accepted by `TTSRoundtripRequest` / `CorruptionParams` / `DecodeParams` (`extra="forbid"`).
  - Response keys consumed: `detail` (on error), `utterance_id`, `duration_sec`, `ground_truth_moras` (`t`, `a`, `e`), `waveform`, `log_mel`, `ctc_posteriors` (`times_sec`, `top_tokens`, `probs` indexed `[t][r]`), `vad_segments`, `alignment` (`token`, `start_sec`, `end_sec`, `confidence`), `hypotheses` (`text`, `score`, `acoustic_score`, `lm_score`), `audio_b64`, `text`, `rtf`, `cer_details` (`cer`, `substitutions`, `deletions`, `insertions`, `ref_len`), plus `cer` returned at top level. All exact matches.
- **`POST /api/transcribe`**:
  - Multipart `FormData` keys: `file`, `method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`, `include_visuals`, plus optional `snr_db`, `noise_type`, `band_limit_low`, `band_limit_high`, `speed`. All parsed and validated by `post_transcribe`.
  - Response keys consumed: `detail`, `utterance_id`, `duration_sec`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`, `alignment`, `hypotheses`, `text`, `rtf`. All exact matches.
- **`POST /api/redecode`**:
  - Request JSON keys: `utterance_id`, `decode_cfg`. Matches `RedecodeRequest`.
  - Response keys consumed: `detail`, `alignment`, `hypotheses`, `text`, `decode_ms`. Matches `ASREngine.redecode`.

### C. All 6 Interactive UI Panels & 5 Canvas 2D Visualizers
All genuinely implemented (no stubs/placeholders):
1. **Tsukinami TTS → ASR Round-Trip Panel (`#panelTts`)**: Kana input, 6 clickable sample chips, dynamic preset selector, `fast`/`tsukinami` engine toggle, audio player, hypothesis, ground-truth, CER/S/D/I/RTF/duration badges.
2. **Audio Input Panel (`#panelAudioInput`)**: Web Audio mic recorder with timer & RMS level meter, drag-and-drop + file-picker WAV upload, filename display, re-run button.
3. **Noise & Filter Corruption Lab (`#panelCorruption`)**: Additive noise toggle, SNR (-5..35 dB) slider, white/pink selector, telephone band-pass (300–3400 Hz) toggle, speed (0.70–1.35x) slider, reset button.
4. **Live CTC Decoding Knobs (`#panelDecoding`)**: `method` (beam/greedy), `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`, reset button, greedy-mode control disabling, and Top-N beam hypotheses table.
5. **4 Horizontally-Aligned Canvas 2D Visualizers (`#panelVisualizers`)**:
   - `#canvasWaveform` (`drawWaveform`): HiDPI waveform polyline + green VAD segment overlays + amplitude/time axes.
   - `#canvasMel` (`drawMelSpectrogram`): 2nd–98th percentile normalization + 256-entry Inferno RGB LUT rendered via offscreen `ImageData`.
   - `#canvasPosterior` (`drawCtcPosteriors`): Frame-level top-K token posterior heatmap (amber `<blank>`, cyan non-blank tokens).
   - `#canvasAlignment` (`drawAlignment`): Dual-lane Viterbi ASR alignment (confidence-shaded) + TTS Ground-Truth Mora comparison ribbon.
6. **Model & Training History Inspector (`#panelModelInfo`)**: Architecture/params/vocab/checkpoint cards, scrollable vocab pills, and `#canvasHistory` (`drawHistory`) dual-axis Train Loss / Val Loss / Val CER curve canvas.

### D. Client-Side Web Audio Mic Recorder & 16-bit PCM WAV Encoder
- **PASS**: `startMicRecording` copies each `ScriptProcessorNode` input buffer into a fresh `Float32Array`, computes RMS meter, and cleanly tears down nodes/tracks/context on stop. `linearResample` resamples from native `audioCtx.sampleRate` to 16 kHz, and `encodeWav16BitPCM` produces a standard 44-byte RIFF/WAVE header + signed 16-bit little-endian mono PCM payload verified end-to-end with `asr.audio.load_wav_bytes`.

### E. Live `/api/redecode` Slider Wiring, Debouncing & Race Guard
- **PASS**: All 6 decode controls and Reset trigger `triggerRedecodeDebounced()` (55 ms debounce). `runRedecode()` increments a monotonic sequence counter (`const seq = ++state.redecodeSeq`) and drops stale out-of-order responses (`if (seq !== state.redecodeSeq) return;`), gracefully handles HTTP 404 cache eviction, updates alignment canvas/hypotheses/latency badge, and recomputes client-side Levenshtein CER in round-trip mode.

---

## 3. Defects Found
None. (Minor non-blocking observation: `runTtsRoundtrip` sets `el.audioPlayer.src` to a `data:audio/wav;base64,...` URI without revoking any earlier `state.lastObjectUrl` until the next `setAudioSourceBlob` call — harmless in normal usage.)
