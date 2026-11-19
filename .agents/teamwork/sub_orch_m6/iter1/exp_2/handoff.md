# Explorer 2 Handoff: Frontend & Canvas UI Blueprint (`asr/web/index.html`)

## 1. Verified Backend JSON Schemas & Array Shapes

All schemas below were verified directly against `asr/inference.py`, `asr/train.py`, `asr/config.py`, `asr/synth_data.py`, `yomu.py`, and `SCOPE.md`.

### 1.1 `GET /api/health`
```json
{
  "status": "ok",
  "model_loaded": true
}
```

### 1.2 `GET /api/info` (`ASREngine.info()` + `model_loaded` flag from `asr/server.py`)
When `model_loaded: true`:
- `model_loaded`: `bool` (`true`)
- `arch`: `"cnn_bigru"` | `"conformer_lite"`
- `num_parameters` / `param_count`: `int`
- `subsampling_factor`: `int` (typically `4`)
- `frame_stride_ms`: `float` (typically `40.0`)
- `model_config`: `{arch, n_mels, hidden_size, num_layers, dropout, num_heads, conv_kernel_size}`
- `audio_config`: `{sample_rate, n_fft, win_length, hop_length, n_mels, f_min, f_max, preemphasis, cmvn}`
- `vocab_size`: `int`
- `vocab`: `list[str]` (index 0 is blank token, e.g. `"<blank>"`)
- `blank_id`: `int` (`0`)
- `tokenizer_mode`: `"kana"` | `"phoneme"` | `"ascii"`
- `tsukinami_presets`: `list[str]` (e.g. `["default", "ossan", "robot", "horror", "whisper", "chibi"]` or `list(yomu.PRESETS.keys())` which adds `"utahime"`, `"choir"`)
- `has_lm`: `bool`
- `cache_size`: `int`, `max_cache_size`: `int`
- `checkpoint_path`: `str | null`
- `epoch`: `int | null`
- `best_val_cer`: `float | null`
- `checkpoint`: `{path, epoch, best_val_cer, train_config}`
- `history`: `list[{epoch: int, train_loss: float, val_loss: float, val_cer: float, lr: float}]`

When `model_loaded: false`:
- `model_loaded`: `false`
- `tsukinami_presets`: still populated (fallback to `["default", "ossan", "robot", "horror", "whisper", "chibi"]` if absent)
- Other model fields may be `null`, `0`, or `[]` — UI must handle gracefully with optional chaining / safe defaults and display a prominent warning banner.

### 1.3 `POST /api/transcribe` (from `ASREngine.transcribe(..., include_visuals=True)`)
Accepted inputs:
- `multipart/form-data`: `file` (WAV binary) + optional form fields (`method`, `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`, `snr_db`, `noise_type`, `band_limit_low`, `band_limit_high`, `speed`, `include_visuals`)
- `application/json`: `{audio_b64, decode_cfg, corruption, include_visuals}`

Response JSON:
```json
{
  "text": "ワタシニホンゴ",
  "hypotheses": [
    {"text": "ワタシニホンゴ", "score": -1.23, "acoustic_score": -1.23, "lm_score": 0.0}
  ],
  "alignment": [
    {"token": "ワ", "start_sec": 0.04, "end_sec": 0.16, "confidence": 0.92}
  ],
  "rtf": 0.041,
  "duration_sec": 1.42,
  "utterance_id": "a1b2c3d4e5f60708",
  "waveform": [0.0012, -0.0034, "... up to 2000 floats in [-1, 1]"],
  "log_mel": [
    [-2.1, -1.8, "... n_mels (64) floats; outer length T <= 600 frames"]
  ],
  "ctc_posteriors": {
    "times_sec": [0.0, 0.04, "... length T_post <= 400"],
    "top_tokens": ["<blank>", "ワ", "タ", "... length K <= 12 (index 0 is always blank)"],
    "probs": [
      [0.98, 0.01, "... length K; outer length T_post; values in [0.0, 1.0]"]
    ]
  },
  "vad_segments": [
    [0.08, 1.32]
  ]
}
```
**CRITICAL ARRAY ORIENTATION NOTES**:
- `waveform`: 1D `number[]`, length `<= 2000`, amplitude `[-1, 1]`, spans `[0, duration_sec]`.
- `log_mel`: 2D `number[T][n_mels]`, `T <= 600` (time axis = outer index `t`, mel frequency bin = inner index `m`, with `m = 0` lowest frequency at **bottom** of spectrogram and `m = n_mels - 1` highest frequency at **top**).
- `ctc_posteriors.probs`: 2D `number[T_post][K]`, `T_post <= 400` (time axis = outer index `t`), `K = top_tokens.length <= 12` (token axis = inner index `k`, `k = 0` is `<blank>`).
- `vad_segments`: `Array<[number, number]>` in seconds `[start_sec, end_sec]`.
- `alignment`: `Array<{token: string, start_sec: number, end_sec: number, confidence: number}>` in seconds.

### 1.4 `POST /api/tts-roundtrip`
Request JSON:
```json
{
  "text": "ワタシ、ニホンゴ、チョットシャベレマス",
  "preset": "default",
  "hz": null,
  "fscale": null,
  "yure": null,
  "rate": null,
  "synth_engine": "fast",
  "corruption": {
    "snr_db": 15.0,
    "noise_type": "white",
    "band_limit": [300.0, 3400.0],
    "speed": 1.0
  },
  "decode_cfg": {
    "method": "beam",
    "beam_width": 8,
    "temperature": 1.0,
    "blank_bias": 0.0,
    "lm_weight": 0.0,
    "insertion_bonus": 0.0
  },
  "include_visuals": true
}
```
Response JSON:
- All fields from `TranscribeResult` above (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`) PLUS:
  - `audio_b64`: base64-encoded WAV bytes (playable via `data:audio/wav;base64,${audio_b64}` or `Blob` URL)
  - `ground_truth_moras`: `Array<{t: string, a: number, e: number}>` (`t` = mora string, `a` = start_sec, `e` = end_sec)
  - `cer`: `float` (e.g. `0.0` = 0.0%, `0.25` = 25.0%)
  - `cer_details`: `{cer: float, substitutions: int, deletions: int, insertions: int, ref_len: int}`

### 1.5 `POST /api/redecode`
Request JSON:
```json
{
  "utterance_id": "a1b2c3d4e5f60708",
  "decode_cfg": {
    "method": "beam",
    "beam_width": 8,
    "temperature": 1.0,
    "blank_bias": 0.0,
    "lm_weight": 0.0,
    "insertion_bonus": 0.0
  }
}
```
Response JSON:
```json
{
  "text": "ワタシニホンゴ",
  "hypotheses": [...],
  "alignment": [...],
  "utterance_id": "a1b2c3d4e5f60708",
  "duration_sec": 1.42,
  "decode_ms": 2.4
}
```
Note: `redecode` does NOT return `waveform`, `log_mel`, `ctc_posteriors`, or `vad_segments` (those stay cached in frontend `state` for the current utterance). It updates `text`, `hypotheses`, `alignment`, and `decode_ms` (and if in round-trip mode, frontend can recompute client-side Levenshtein CER against `state.groundTruthText` for instant live CER feedback!).

---

## 2. Zero-CDN & Aesthetic Rules

### 2.1 Strict Zero-CDN Policy
- **ZERO** external URLs anywhere in `asr/web/index.html` — no `http://`, no `https://`, no `//cdn...`, no Google Fonts, no external `<script src>`, no external `<link href>`, no CSS `@import` or `url(http...)`, and **no** `http://`/`https://` strings even inside `<meta>` tags or HTML/JS comments (so regex checks like `re.search(r"https?://", html)` pass cleanly!).
- Use only local relative API paths (`/api/health`, `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`) and system font stacks:
  - Sans: `-apple-system, BlinkMacSystemFont, "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Yu Gothic", sans-serif`
  - Mono: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`

### 2.2 Visual Aesthetic (Matching `toybox.html`)
Reuse the exact dark-navy "Tsukinami Toybox" color palette and playful Japanese+English tone:
- `--bg: #0b1020`, `--panel: #131b31`, `--panel2: #192340`, `--border: #2a3966`
- `--text: #eef2ff`, `--muted: #94a3b8`
- Accents: `--cyan: #38bdf8`, `--amber: #f59e0b`, `--emerald: #10b981`, `--rose: #f43f5e`, `--violet: #a78bfa`
- Header with gradient `linear-gradient(135deg, rgba(56,189,248,0.14), rgba(245,158,11,0.12))`, title `🎙️ 月並み ASR — 遊べる音声認識プレイグラウンド (Interactive CTC Playground)`, and pipeline flow pills: `TTS / Mic / WAV` → `Corruption Lab` → `Log-Mel` → `Neural CTC` → `Live Beam Search`.
- Responsive layout (`max-width: 1180px`, CSS Grid two-column on desktop `>= 900px`, single-column on narrow viewports).
- Top-level alert banners:
  - `#noModelBanner` (amber/rose warning shown when `/api/info` returns `model_loaded: false`, explaining how to launch with `--checkpoint`).
  - `#errorBanner` (dismissible rose error bar for API 400/422/503/network/mic errors).
  - `#statusPill` (live status indicator in header/toolbar).

---

## 3. Complete Architecture of All 6 Interactive Areas

### Area 1: Tsukinami TTS → ASR Round-Trip Panel (`#panelTts`)
- **Text input**: `#ttsTextInput` (default `"ワタシ、ニホンゴ、チョットシャベレマス"`, placeholder `"カタカナ・ひらがなを入力..."`).
- **Quick sample phrase chips** (`.sample-chip` buttons):
  - `"オハヨウゴザイマス"`
  - `"ワタシ、ニホンゴ、チョットシャベレマス"`
  - `"キョウモイッショニガンバロウネ"`
  - `"オンガクヲサイセイシテ"`
  - `"ウシロニ、ダレカ、イマスヨ"`
  - `"アリガトウゴザイマス"`
- **Preset selector**: `#ttsPresetSelect` — dynamically populated from `/api/info` `tsukinami_presets` (fallback: `default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`), with Japanese label hints (`default (標準)`, `ossan (おっさん)`, `robot (ロボ)`, `horror (ホラー)`, `whisper (ささやき)`, `chibi (ちびっ子)`, etc.).
- **Synth engine toggle**: `#ttsEngineSelect` (`fast` = Fast Kotoba Formant Synth [高速], `tsukinami` = Authentic Tsukinami TTS [実機 carve.py]).
- **Action button**: `#btnRoundtrip` (`🔊 合成して認識 / Synth & Transcribe`).
- **Audio playback**: `#audioPlayer` (`<audio controls>`) fed from `data:audio/wav;base64,${audio_b64}` (also reused for recorded mic WAV and uploaded WAV via `URL.createObjectURL(blob)`).
- **Round-Trip Result Readout**:
  - `#resultText`: large highlighted ASR hypothesis string (with `(無音 / 空)` placeholder when empty).
  - `#groundTruthRow` (visible in round-trip mode): displays Ground-Truth text `#gtText`, CER badge `#cerBadge` (color-coded: emerald `<= 10%`, amber `<= 35%`, rose `> 35%`), S/D/I breakdown `#cerBreakdown` (`S:0 D:0 I:0`), plus `#rtfBadge` and `#durationBadge`.

### Area 2: Audio Input Panel (`#panelAudioInput`)
- **Browser Microphone Recorder**:
  - `#btnMicRecord` (`🎙️ 録音開始 / Start Mic`) & `#btnMicStop` (`⏹️ 停止して認識 / Stop & Transcribe`, disabled until recording).
  - `#micTimer` (`00.0s`) + live level meter bar `#micLevelBar`.
  - Implementation: `navigator.mediaDevices.getUserMedia({ audio: true })` → `AudioContext` → `MediaStreamAudioSourceNode` → `ScriptProcessorNode(4096, 1, 1)` collecting `Float32Array` chunks + computing live RMS for `#micLevelBar`.
  - On stop: concatenate chunks, linearly resample from `audioCtx.sampleRate` to `16000` Hz, encode as 16-bit PCM mono WAV via pure-JS `encodeWav16BitPCM(float32Samples, 16000)` (44-byte RIFF/WAVE header + clamped Int16 PCM), set `#audioPlayer.src = URL.createObjectURL(wavBlob)`, and `POST /api/transcribe` as `multipart/form-data` with `file` (`mic_recording.wav`) + current corruption & decode params.
  - Graceful error handling if `navigator.mediaDevices` is unavailable (non-HTTPS/unsupported browser) or permission denied.
- **WAV File Upload & Drag-and-Drop**:
  - `#dropZone` (dragover/dragleave/drop visual highlight) + hidden `<input type="file" id="wavFileInput" accept=".wav,audio/wav,audio/*">` + `#btnPickWav` button.
  - `#uploadedFileName` indicator + `#btnRetranscribeAudio` (`🔁 現在の音声を再認識 / Re-run with Corruption`) so users can tweak Corruption Lab sliders and re-run on the same mic/uploaded WAV!

### Area 3: Noise & Filter Corruption Lab (`#panelCorruption`)
- **Noise enable toggle**: `#corrNoiseEnabled` (checkbox, default `false`) — when unchecked, `snr_db` is sent as `null`.
- **SNR (dB) slider**: `#corrSnrSlider` (`min=-5`, `max=35`, `step=1`, `value=15`) + readout `#corrSnrVal` (`15 dB`), visually dimmed when noise disabled.
- **Noise type selector**: `#corrNoiseType` (`white` = White Noise / ホワイトノイズ, `pink` = Pink Noise / ピンクノイズ).
- **Telephone Band-Pass toggle**: `#corrBandpass` (checkbox, default `false` — `📞 電話帯域フィルタ (300–3400 Hz)`). When checked, sends `band_limit: [300.0, 3400.0]` (JSON) or `band_limit_low=300&band_limit_high=3400` (FormData).
- **Speed perturbation slider**: `#corrSpeedSlider` (`min=0.70`, `max=1.35`, `step=0.05`, `value=1.00`) + readout `#corrSpeedVal` (`1.00x`).
- **Reset button**: `#btnResetCorruption` (resets to clean defaults: noise off, 15 dB, white, bandpass off, speed 1.00x).

### Area 4: Live CTC Decoding Knobs (`#panelDecoding`)
- Wired to `POST /api/redecode` whenever `state.utteranceId` is non-null, with a **60 ms debounce** and a monotonic request sequence ID (`state.redecodeSeq`) so stale out-of-order responses are ignored.
- **Controls** (matching `DecodeConfig` in `asr/config.py`):
  - `#decMethod`: `<select>` (`beam` = Prefix Beam Search, `greedy` = Greedy CTC). When `greedy`, visually disable `beam_width`, `lm_weight`, `insertion_bonus`.
  - `#decBeamWidth`: slider `1..32`, step `1`, default `8` (`#decBeamWidthVal`).
  - `#decTemperature`: slider `0.2..3.0`, step `0.05`, default `1.00` (`#decTemperatureVal`).
  - `#decBlankBias`: slider `-4.0..4.0`, step `0.1`, default `0.0` (`#decBlankBiasVal`).
  - `#decLmWeight`: slider `0.0..2.0`, step `0.05`, default `0.00` (`#decLmWeightVal`) + hint badge if `has_lm === false`.
  - `#decInsertionBonus`: slider `-2.0..2.0`, step `0.1`, default `0.0` (`#decInsertionBonusVal`).
  - `#btnResetDecode`: resets all decode knobs to defaults and triggers redecode if utterance loaded.
- **Live Latency Badge**: `#redecodeLatencyBadge` (`⚡ Redecode: 2.3 ms` — emerald when `< 10 ms`, amber otherwise).
- **Top-N Beam Hypotheses Table**: `#hypothesesTable` (`<tbody>` `#hypothesesBody`) showing Rank `#`, Hypothesis `text`, Total `score`, `acoustic_score`, and `lm_score` formatted to 3 decimals.

### Area 5: 4 Canvas 2D Visualizers (`#panelVisualizers`)
All 4 canvases share a common HiDPI setup helper:
```js
function setupCanvas(canvas, cssHeight) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(240, Math.floor(rect.width || 600));
  const h = cssHeight;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}
```
All 4 canvases align horizontally across `[padLeft, w - padRight]` representing `[0, duration_sec]` so features line up vertically across Waveform → Log-Mel → CTC Posteriors → Alignment!

1. **Waveform + VAD Segments Overlay (`#canvasWaveform`, height `110px`)**:
   - Background `#070b14`, horizontal center zero-line (`rgba(148,163,184,0.22)`).
   - VAD segments: translucent emerald rectangles `rgba(16,185,129,0.18)` with top border `#10b981` mapped from `[s / duration, e / duration]`.
   - Waveform polyline (`#38bdf8`, lineWidth 1.25) plotting `waveform[i]` normalized to `[-1, 1]`.
   - Time ticks along bottom axis (`0.0s`, ..., `${duration}s`).
2. **Log-Mel Spectrogram Heatmap (`#canvasMel`, height `150px`)**:
   - Uses an offscreen `<canvas>` of size `(T, n_mels)` + `ImageData` filled with a 256-entry pure-JS Inferno/Magma colormap LUT, then drawn scaled (`ctx.imageSmoothingEnabled = false` or smooth) into `[padLeft, padTop, plotW, plotH]`.
   - Dynamic min/max normalization using 2nd–98th percentile (or min/max with floor `1e-5`) so CMVN-normalized log-mel spectrograms always have crisp contrast.
   - Y-axis flips bin index: `y = n_mels - 1 - m` (low freq at bottom, high freq at top), labeled `0` .. `${n_mels} mel`.
3. **CTC Frame Posterior Probability Heatmap (`#canvasPosterior`, height `190px`)**:
   - Reads `ctc_posteriors`: `times_sec` (`T_post`), `top_tokens` (`K`), `probs` (`[T_post][K]`).
   - Left label column (`padLeft = 58px`) renders each token label (`<blank>` in amber/muted, speech tokens in `#eef2ff`, monospace 11px).
   - Grid cells `(t, k)` shaded by probability `p in [0, 1]` using cyan/violet/amber intensity ramp (`p -> rgba`), with subtle horizontal row dividers.
4. **Mora / Token Alignment Timeline Ribbon (`#canvasAlignment`, height `115px`)**:
   - Top lane ("ASR Alignment"): rounded colored blocks for each `{token, start_sec, end_sec, confidence}` spanning `[start_sec, end_sec]`. Block color cycles through cyan/violet/emerald/amber; opacity or bottom bar indicates `confidence` (`0..1`); token text centered inside block when width >= 14px.
   - Bottom lane ("Ground-Truth Moras", shown when `state.groundTruthMoras.length > 0`): renders each `{t, a, e}` in amber-outlined blocks directly beneath the ASR alignment lane for visual timing comparison!
   - Empty state message (`"音声を認識するとここに可視化されます"`) drawn cleanly when no utterance is loaded.

### Area 6: Model & Training History Inspector (`#panelModelInfo`)
- **Metadata Cards Grid (`#modelInfoGrid`)**:
  - Architecture (`arch`, `hidden_size`, `num_layers`, `subsampling_factor`, `frame_stride_ms`)
  - Parameters (`num_parameters` formatted e.g. `512.4K`)
  - Vocabulary (`vocab_size`, `tokenizer_mode`, `has_lm`)
  - Checkpoint (`epoch`, `best_val_cer` formatted as `%`, `checkpoint_path` basename)
- **Vocab Preview Strip (`#vocabPreview`)**: scrollable pill strip showing tokens from `info.vocab` (blank highlighted).
- **Training / Val Loss & CER Curve Canvas (`#canvasHistory`, height `170px`)**:
  - Reads `info.history` (`[{epoch, train_loss, val_loss, val_cer, lr}]`).
  - Dual-axis chart:
    - Left Y-axis: Loss (`train_loss` solid `#38bdf8`, `val_loss` dashed `#a78bfa`).
    - Right Y-axis: `val_cer` (`0%`–`100%`, solid `#f59e0b` with point markers).
    - X-axis: `epoch` numbers.
  - Handles edge cases cleanly: 0 epochs (draws `"学習履歴データなし / No training history"`), 1 epoch (draws labeled dots instead of NaN x-division).

---

## 4. JavaScript State Object & Control Flow

```js
const state = {
  info: null,               // GET /api/info payload
  modelLoaded: false,
  utteranceId: null,        // Current cached utterance_id for /api/redecode
  durationSec: 0,
  mode: "idle",             // "idle" | "roundtrip" | "mic" | "upload"
  groundTruthText: null,    // string | null
  groundTruthMoras: [],     // [{t, a, e}]
  lastAudioBlob: null,      // Blob (WAV) for re-transcribing with new corruption settings
  lastAudioName: null,      // string
  visuals: {
    waveform: [],
    log_mel: [],
    ctc_posteriors: null,
    vad_segments: [],
    alignment: [],
  },
  hypotheses: [],
  redecodeTimer: null,
  redecodeSeq: 0,
  // Mic recording state
  mic: {
    recording: false,
    stream: null,
    audioCtx: null,
    source: null,
    processor: null,
    chunks: [],
    sampleRate: 16000,
    startTime: 0,
    timerId: null,
  },
};
```

### Key Helper Functions
- `getDecodeCfg()`: reads the 6 decoding controls into `{method, beam_width, temperature, blank_bias, lm_weight, insertion_bonus}`.
- `getCorruptionCfg()`: reads the corruption controls into `{snr_db, noise_type, band_limit, speed}` (returns `null` if all clean: noise disabled, bandpass off, speed === 1.0).
- `triggerRedecodeDebounced()`: clears `state.redecodeTimer`, sets 60 ms timeout → `runRedecode()`.
- `runRedecode()`: increments `const seq = ++state.redecodeSeq`, posts to `/api/redecode`, ignores response if `seq !== state.redecodeSeq`, updates `#resultText`, `#hypothesesBody`, `#redecodeLatencyBadge`, `state.visuals.alignment`, redraws `#canvasAlignment`, and if `state.groundTruthText` is set, updates client-side Levenshtein CER readout!
- `encodeWav16BitPCM(samples, sampleRate)`: pure-JS 44-byte RIFF/WAVE header + Int16 little-endian PCM `Blob("audio/wav")`.
- `linearResample(samples, srcRate, dstRate)`: pure-JS linear interpolation resampler to 16 kHz.
- `computeClientCer(ref, hyp)`: pure-JS Levenshtein edit distance (ignoring punctuation `、。！？ ` or matching `asr/metrics.py` character-level comparison) for instant live CER update during `/api/redecode`.
- `window.addEventListener("resize", ...)`: debounced redraw of all 5 canvases (`waveform`, `mel`, `posterior`, `alignment`, `history`).
- `escapeHtml(s)`: safe HTML escaping for all dynamic strings (`text`, `token`, `checkpoint_path`, error messages) to prevent XSS.

---

## 5. Error Handling & Edge Cases
- **No model loaded (`model_loaded: false`)**: Show `#noModelBanner`, disable `#btnRoundtrip`, `#btnMicRecord`, `#btnPickWav`, `#btnRetranscribeAudio` (or allow UI exploration while displaying clear 503 guidance if clicked).
- **Empty text on TTS round-trip**: Show inline error in `#errorBanner` before sending.
- **Invalid/corrupt WAV upload**: Display server `detail` error message cleanly in `#errorBanner`.
- **404 on `/api/redecode` (evicted utterance)**: Show friendly info message in `#statusPill` without crashing.
- **Empty/silent audio**: `waveform`, `log_mel`, `ctc_posteriors.probs`, `alignment` may be empty `[]` — every canvas draw function checks length > 0 and renders a clean empty-state placeholder.
- **Audio playback cleanup**: Revoke previous `URL.createObjectURL` before creating a new one to avoid memory leaks.
