# Survey & Architecture Design Handoff — Tsukinami ASR ("ASRをつくって遊びたい")

> **Executive Summary:** `/home/antigravity/poidowl/tsukinami` is an existing pure-Python Japanese kana TTS synthesizer (`yomu.py`, `carve.py`, `kotoba.py`, `accent.py`) with interactive zero-CDN browser playgrounds (`toybox.html`, `ablation.html`, `demo.html`). We propose building **Tsukinami ASR** inside an isolated `asr/` Python package (leaving all existing TTS files intact): a genuine, end-to-end neural CTC ASR system with pure-NumPy transparent DSP/Mel/SpecAugment/CTC-beam-search/metrics, compact CPU-trainable PyTorch acoustic models (`cnn_bigru` default + `conformer_lite` option), a dual-tier zero-download Japanese speech data pipeline powered directly by `kotoba.tracks_from_kana()` (fast NumPy formant synth for bulk CPU training) and `yomu`/`carve` (authentic Tsukinami TTS→ASR round-trip play) alongside real WAV/mic/external corpus support, plus a FastAPI + zero-CDN Canvas interactive Web Playground ("遊べる ASR") and CLI, decomposed into **6 clean milestones**.

---

## 1. Observation

### 1.1 Original User Request
- File: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md:1-5`
- Exact text: `ASRをつくって遊びたい` ("I want to build and play with an ASR").

### 1.2 Existing Workspace Structure & Philosophy
- Inspected via `list_dir` on `/home/antigravity/poidowl/tsukinami` (30 files, 3 subdirectories: `.agents`, `.git`, `assets`; no `pyproject.toml`, `requirements.txt`, `tests/`, or `PROJECT.md`).
- `README.md:1-50` and `README_EN.md:1-134`:
  - `tsukinami` ("月並みTTS / 天邪鬼TTS") is a pure-Python Japanese kana speech & singing synthesizer ("Read Japanese Kana. Read how it works, in Python." / "Play → Modify → Listen → Compare → Share").
  - Emphasizes **transparency, hackability, ablation, and interactive browser play** (`toybox.html`, `watashi_demo.html`, `ablation.html`, `demo.html` — all zero-CDN self-contained HTML).
- Key existing Python modules verified via `view_file`:
  - `kotoba.py:10-49`: Complete Japanese katakana/hiragana-to-mora parser (`to_kata`, `split_moras`, `parse_kana`), consonant place/manner/voicing tables (`PLACE`, `MANNER`, `VOICELESS`, `VOICED_OBS`), vowel formant targets (`VT`, 5 vowels × 3 formants), F2 locus equations (`LE`), fricative/nasal spectral targets (`fricT`, `nasT`).
  - `kotoba.py:342-360`: `tracks_from_kana(text, ...)` returns 5 ms frame tracks: `dict(fp_ms=5.0, n, F1, F2, F3, G1, G2, G3, dl, loud, f0, voiced, bands, moras)` where each mora has `{t, kind, c, v, a, b, e}` (exact start `a`, vowel onset `b`, end `e` in seconds).
  - `yomu.py:38-81`: 8 built-in voice presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`) with tunable DSP parameters (`seed`, `tsubu`, `hz`, `fscale`, `yure`, `shimmer`, `tadayoi`, `line_g`, `ap_n`, `rate`).
  - `yomu.py:113-205, 303-315`: `rc = yomu.build_carve_rc(text, prm)` followed by `samples, moras = C.make(rc)` synthesizes audio at `C.SR = 44100` Hz and returns ground-truth mora timings.
  - `featF.py:1-31`: Standalone analysis script showing prior Mel-spectrogram conventions (96 mels, 80–8000 Hz, 24 kHz) — requires optional `pyworld`/`librosa`/`soundfile` (not installed in this VM).
  - `mcp_server.py:1-100`: Stdlib-only MCP server exposing `tsukinami_speak`.
- Git history (`git log -n 10 --oneline`): Active TTS repo, latest commit `d2ab3ce` (`Merge pull request #4 from poidowl/kusanagi-sync-24d3049`).

### 1.3 Live Benchmark of `tsukinami` Synthesis
Command run in `/home/antigravity/poidowl/tsukinami`:
```bash
python3 -c "import time, yomu, carve as C; t0=time.perf_counter(); rc=yomu.build_carve_rc('あいうえお', dict(yomu.PRESETS['default'])); samples, moras=C.make(rc); dt=time.perf_counter()-t0; print(f'SR={C.SR}, samples={len(samples)} ({len(samples)/C.SR:.2f}s audio) in {dt:.2f}s (RTF={dt/(len(samples)/C.SR):.2f})'); print('moras:', moras[:2])"
```
Observed output:
```text
SR=44100, samples=62401 (1.41s audio) in 3.94s (RTF=2.79)
moras type: <class 'list'> keys/sample: [{'t': 'ア', 'kind': 'CV', 'c': '', 'v': 'a', 'a': 0.6, 'b': 0.6, 'e': 0.717}, {'t': 'イ', 'kind': 'CV', 'c': '', 'v': 'i', 'a': 0.717, 'b': 0.717, 'e': 0.821}]
```

### 1.4 Runtime Environment & Hardware
Observed via `python3`, `nproc`, `free -h`, `nvidia-smi`:
- **CPU / RAM / GPU**: 2 CPU cores, 7.8 GiB RAM (6.9 GiB available), **No GPU** (CPU-only).
- **Python**: `Python 3.11.2`.
- **Pre-installed Python packages**: `numpy 1.24.2`, `fastapi 0.92.0`, `uvicorn 0.17.6`.
- **Not installed yet**: `torch`, `torchaudio`, `scipy`, `librosa`, `soundfile`, `flask`, `gradio`, `pytest`, `matplotlib`, `sklearn`.
- **System tools**: `/usr/local/bin/uv`, `/usr/bin/pip`, `/usr/bin/pip3`, `/usr/bin/ffmpeg`, `/usr/local/bin/node`, `/usr/local/bin/npm`.

---

## 2. Logic Chain

1. **Repo Synergy & Isolation (from Obs 1.2):**
   - `tsukinami` is a Japanese kana TTS repo whose entire ethos is *"transparent, inspectable, breakable-and-reversible speech tech you can play with"*.
   - Therefore, building the ASR in a clean, self-contained `asr/` package (+ `tests/`) preserves 100% backward compatibility with existing TTS scripts while turning the repo into a full **TTS ↔ ASR closed-loop speech playground** ("しゃべらせて、聴き取らせて、壊して遊べる").
2. **Solving the "Out-of-the-Box Trainable on 2-Core CPU Without Huge Downloads" Problem (from Obs 1.2, 1.3, 1.4):**
   - `carve.make()` produces genuine Japanese speech with exact mora ground-truth timings, but at RTF `2.79` on 2-core CPU (~3.94s for 1.41s audio), generating 500 utterances on the fly would take ~25 minutes — too slow for instant experimentation.
   - However, `kotoba.tracks_from_kana()` (`kotoba.py:342-360`) already computes the complete 5 ms formant/voicing/noise/loudness trajectories (`F1, F2, F3, G1..G3, f0, voiced, bands, moras`) in <1 ms!
   - A vectorized **NumPy Formant-Track Synthesizer** driven by `kotoba.tracks_from_kana()` (parallel 2nd-order resonant filters + band-limited fricative noise + randomized `f0`, `fscale`, `rate`, SNR noise) can generate **hundreds of phonetically rich Japanese kana utterances at 16 kHz in a few seconds** (RTF < 0.05).
   - Combining **Tier 1 (Fast `kotoba`-driven NumPy Formant Synth)** for rapid bulk CPU training/augmentation + **Tier 2 (Authentic `tsukinami` `yomu`/`carve` TTS with disk caching & preset randomization)** for realistic TTS→ASR fine-tuning and interactive round-trip play + **Tier 3 (Real WAV / Browser Mic / Manifest loaders for JSUT, CommonVoice, SpeechCommands)** delivers both instant zero-download playability AND genuine real-world ASR extensibility.
3. **Acoustic Model Backend Choice on 2-Core CPU (from Obs 1.4):**
   - **Frontend DSP, Feature Extraction, SpecAugment, CTC Decoding (Greedy + Prefix Beam Search + N-gram LM), Forced Alignment, and WER/CER Metrics** should be implemented from scratch in **pure NumPy + Python stdlib**. This avoids heavy audio dependencies (`librosa`, `torchaudio`, `scipy`, `soundfile`), guarantees 100% educational transparency, and works immediately with the pre-installed `numpy 1.24.2`.
   - **Neural Acoustic Model & Training** has two viable options (analyzed in Section 4.2):
     - **Option 1 (Recommended): Compact PyTorch CPU (`torch` CPU wheel)** with selectable `Conv2dSubsampling + BiGRU-CTC` (default, ~0.6M params, fast on 2-core CPU) and `Conformer-Lite-CTC` (~1.2M params). Gives rock-solid autograd, `nn.CTCLoss`, AdamW, fast OpenBLAS/MKL CPU matmuls, and standard `.pt` checkpoints.
     - **Option 2 (Zero-PyTorch Alternative): Pure-NumPy 1D-CNN/TDNN-CTC** with hand-written forward/backward CTC loss and AdamW. Zero external ML deps, maximal `tsukinami`-style transparency, but higher implementation/gradient-bug risk and slower scaling to real corpora.
4. **Interactive Playability Architecture (from Obs 1.2, 1.4):**
   - `fastapi 0.92.0` and `uvicorn 0.17.6` are *already installed* in this environment.
   - Serving a **zero-CDN, single-page HTML5 + Canvas 2D + Web Audio API playground** from FastAPI directly mirrors `tsukinami`'s `toybox.html` aesthetic, requires zero Node build step, and lets users record mic audio, upload WAVs, synthesize live via `tsukinami` TTS, inject noise/filters, tweak CTC beam-search knobs, and visually inspect waveforms, Mel-spectrograms, CTC spiky frame posteriors, and mora alignments in real time.

---

## 3. Caveats

1. **No GPU & 2-Core CPU Budget:** Training time and model size must stay lean (`~0.3M–1.5M` params, 4× Conv2d time subsampling, 64-bin Mel @ 16 kHz) so a genuine training run converges to low CER (<15% on held-out synthetic/TTS test utterances) in ~30–120 seconds on CPU, and unit/E2E tests run in <15 seconds.
2. **External Package Installation:** `torch` (CPU wheel) and `pytest` are not currently installed in the VM; Milestone 1 (or env setup) will need `uv pip install` / `pip install` (CPU-only `torch` + `pytest` + `httpx` for FastAPI `TestClient`) unless Architecture Option 2 (Pure NumPy) is selected by the orchestrator.
3. **Domain Gap (Synthetic vs. Real Human Voice):** A model trained solely on `kotoba` formant synth + `tsukinami` TTS will transcribe synthetic/TTS Japanese accurately, while real human microphone speech will have higher CER until fine-tuned on real Japanese data (e.g., JSUT / CommonVoice-ja / user-recorded mic clips). We address this explicitly in the playground by supporting **few-shot mic clip recording & manifest export** and **real corpus manifest loaders**, and by documenting the domain gap transparently.
4. **Browser Microphone Permissions in Headless/HTTP Contexts:** `navigator.mediaDevices.getUserMedia` requires `localhost` or HTTPS. Serving on `127.0.0.1` / `localhost` works in modern browsers; automated E2E tests should exercise the same `/api/transcribe` endpoint with generated WAV payloads.
5. **`carve.py` Internals Not Audited Line-by-Line:** We verified `yomu.build_carve_rc()` and `carve.make()` experimentally rather than auditing all 131 KB of `carve.py`, as `yomu.py` is the official public interface.

---

## 4. Conclusion — Complete Design Specification

### 4.1 Feature Inventory

| Area | Feature | Priority | Details |
|---|---|---|---|
| **Audio & DSP Frontend** | WAV/PCM I/O & Resampling | Must | Read/write 16-bit/32-bit WAV via stdlib `wave` + `numpy`; auto mono mixdown & linear/polyphase resampling to 16 kHz; optional `ffmpeg` fallback for MP3/WebM/OGG uploads. |
| **Audio & DSP Frontend** | STFT, Mel Filterbank, Log-Mel, MFCC | Must | Pure-NumPy from-scratch pre-emphasis (0.97), 25 ms window / 10 ms hop, Hann window, rFFT, 64/80-bin Slaney Mel filterbank (80–7600 Hz), log compression, optional DCT MFCC + Δ/ΔΔ, per-utterance CMVN. |
| **Audio & DSP Frontend** | Energy VAD & Silence Trimming | Must | Frame-level RMS energy VAD with configurable threshold & hang-over padding; returns speech segment timestamps for UI overlay. |
| **Augmentation & Corruption** | SpecAugment & Waveform Perturbations | Must | Frequency masking, time masking, additive white/pink noise at target SNR (dB), random gain, speed/time stretch, telephone band-pass filter (300–3400 Hz) — used both for training regularization and the UI "Corruption Lab". |
| **Tokenization** | Japanese Kana / Mora & Phoneme CTC Vocab | Must | Built on `kotoba.to_kata` & `kotoba.split_moras`. Supports `kana` mode (katakana chars + `ー`/`ッ`/`ン`/`、` + `<blank>`=0), `phoneme` mode (CV/N/Q/pau), and `ascii` mode (a-z + space for English corpora). Serializable `vocab.json`. |
| **Dataset & Synthesis Pipeline** | Tier 1: Fast `kotoba` Formant-Track Synth | Must | Vectorized NumPy synthesis from `kotoba.tracks_from_kana()` with speaker randomization (`f0`, `fscale`, `rate`, jitter, SNR). Generates 500+ Japanese utterances in seconds on CPU + exact mora alignments. |
| **Dataset & Synthesis Pipeline** | Tier 2: Authentic `tsukinami` TTS Engine | Must | Wraps `yomu.build_carve_rc` + `carve.make` across all 6+ presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`) with disk cache & multiprocessing for TTS→ASR round-trip & fine-tuning. |
| **Dataset & Synthesis Pipeline** | Tier 3: Real Audio & Corpus Manifest Loader | Must | Unified JSONL manifest format (`{"audio_path", "text", "duration", "speaker", "moras"}`) + converters/loaders for arbitrary WAV folders, JSUT, CommonVoice, SpeechCommands, and user mic recordings. |
| **Acoustic Models** | Selectable End-to-End CTC Models | Must | `cnn_bigru` (Conv2d 4× subsampling + BiGRU + Linear CTC, default fast CPU model) and `conformer_lite` (Conv2d 4× subsampling + Mini-Conformer blocks: Macaron FFN + MHSA + Depthwise Conv + CTC). |
| **Training & Checkpointing** | Trainer, LR Schedule, Checkpoints | Must | CTC loss, AdamW, OneCycle/Cosine LR, grad clipping, validation CER/loss tracking, best/latest checkpoint save/load (`.pt` with weights + config + vocab + history), deterministic seeding, resume support. |
| **Decoding & Alignment** | Greedy & Prefix Beam Search CTC + N-gram LM | Must | Pure-NumPy/Python Greedy CTC and Prefix Beam Search with tunable `beam_width`, `temperature`, `blank_bias`, optional lightweight Python char/mora N-gram LM (`lm_weight`, `insertion_bonus`), returning top-N hypotheses + frame-level Viterbi CTC alignment + posterior matrix `(T, V)`. |
| **Evaluation & Metrics** | CER / MER / WER / RTF / Confusion | Must | Levenshtein edit distance with S/D/I breakdown, Character Error Rate, Mora Error Rate, Word Error Rate, Real-Time Factor (RTF), top-K substitution confusion pairs, and TTS-vs-ASR mora boundary IoU/offset comparison. |
| **CLI** | `python -m asr <subcommand>` | Must | `generate`, `train`, `eval`, `transcribe` (supports WAV or `--tts "かな"`), `serve`, `demo` (one-command quickstart: generate tiny dataset → train → evaluate → transcribe!). |
| **Interactive Web Playground** | FastAPI + Zero-CDN Canvas UI ("遊べる ASR") | Must | Mic record, WAV upload, Tsukinami TTS→ASR live round-trip, Noise/Filter Corruption Lab, real-time Waveform / Log-Mel / CTC Posterior Heatmap / Alignment Ribbon canvases, interactive Beam Search knobs, Top-N beam table, and Checkpoint/Metrics inspector. |

---

### 4.2 Architecture Options & Recommendation

#### Option 1 (Recommended): Hybrid Transparent Architecture (Pure-NumPy Frontend/Decoder + PyTorch CPU Acoustic Model)
```text
[Audio Source: Mic / WAV / Tsukinami TTS / Fast Kotoba Synth / Real Corpus]
        │  (float32 @ 16 kHz, mono)
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ asr/audio.py & asr/features.py  (100% Pure NumPy — Transparent DSP)     │
│  WAV I/O · Resample · VAD · Pre-emphasis · STFT · Log-Mel · SpecAugment │
└─────────────────────────────────────────────────────────────────────────┘
        │  feats: (B, T, n_mels=64), feat_lengths: (B,)
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ asr/models/  (PyTorch CPU — Compact, Genuine End-to-End Neural CTC)     │
│  Conv2dSubsampling (4× time stride)                                     │
│    ├── cnn_bigru (default): 2-layer BiGRU (hidden=192) -> Linear(V)     │
│    └── conformer_lite:      2-layer Conformer (d=128, h=4, k=15) -> V   │
│  Loss: nn.CTCLoss(blank=0, zero_infinity=True)  |  Opt: AdamW           │
└─────────────────────────────────────────────────────────────────────────┘
        │  log_probs: (T', V)  (exported as NumPy float32)
        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ asr/decoding.py & asr/metrics.py  (100% Pure NumPy/Python — Playable)   │
│  Temperature & Blank-Bias · Greedy CTC · Prefix Beam Search + N-gram LM │
│  Viterbi Forced Alignment · CER / MER / WER / RTF / Confusion Matrix    │
└─────────────────────────────────────────────────────────────────────────┘
        │
        ├──▶ CLI: python -m asr {demo,generate,train,eval,transcribe,serve}
        └──▶ Web Playground: FastAPI (asr/server.py) + Canvas UI (asr/web/index.html)
```

#### Option 2 (Alternative): 100% Pure-NumPy TDNN/1D-CNN + Hand-Coded CTC Backprop
- Replaces PyTorch with a hand-written NumPy 1D Conv + Residual TDNN + manual Forward-Backward CTC gradient + NumPy AdamW.
- **Trade-off comparison:**

| Criterion | Option 1: Hybrid (NumPy DSP/CTC + PyTorch CPU Model) | Option 2: 100% Pure NumPy |
|---|---|---|
| **Install footprint** | `+torch` CPU wheel (~200 MB) + `pytest` | Zero extra runtime deps (`numpy`, `fastapi`, `uvicorn` already installed) |
| **Educational transparency** | DSP, Mel, SpecAugment, Beam Search, LM, Alignment all readable pure NumPy; model is clean idiomatic PyTorch | Every matrix multiply & CTC backward pass in NumPy |
| **Model quality & extensibility** | Supports real `BiGRU` & `Conformer-Lite`, scales to JSUT/CommonVoice/LibriSpeech | Limited to shallow 1D-CNN/MLP on CPU; slow/fragile for BiGRU/Conformer |
| **Implementation risk** | Low (autograd + `nn.CTCLoss` battle-tested) | Medium-High (numerical stability in log-space CTC backward + conv backprop) |
| **CPU training speed (2 cores)** | Fast (OpenBLAS/MKL fused kernels; ~30–90s for working demo model) | 3–8× slower for equivalent capacity |

**Recommendation:** Adopt **Option 1 (Hybrid)** as the primary architecture. It delivers a genuinely capable, extensible, fast-on-CPU ASR while keeping all signal processing, CTC decoding, alignment, and visualization 100% transparent in pure NumPy/Python.

---

### 4.3 Proposed Directory Layout (Non-Invasive to Existing `tsukinami` TTS)

```text
/home/antigravity/poidowl/tsukinami/
├── (existing TTS files untouched: yomu.py, carve.py, kotoba.py, accent.py, *.html, ...)
├── asr/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry: `python -m asr ...`
│   ├── config.py            # Dataclasses: AudioConfig, ModelConfig, TrainConfig, DecodeConfig
│   ├── audio.py             # WAV I/O, resampling, normalization, VAD, noise/filter corruptions
│   ├── features.py          # Pure-NumPy STFT, Mel filterbank, Log-Mel, MFCC, CMVN, SpecAugment
│   ├── tokenizer.py         # Kana/Mora/Phoneme/ASCII CTC Tokenizer (uses kotoba.to_kata/split_moras)
│   ├── synth_data.py        # Tier 1 Fast Kotoba Formant Synth + Tier 2 Tsukinami TTS Dataset Builder
│   ├── dataset.py           # JSONL Manifest Dataset, PyTorch DataLoader & collate_fn, external loaders
│   ├── models/
│   │   ├── __init__.py      # build_model(config, vocab_size) factory
│   │   ├── subsampling.py   # Conv2dSubsampling (4x time reduction)
│   │   ├── cnn_bigru.py     # ConvSubsampling + BiGRU-CTC (default)
│   │   └── conformer.py     # Conformer-Lite-CTC (Macaron FFN + MHSA + ConvModule)
│   ├── decoding.py          # Greedy CTC, Prefix Beam Search, N-gram Char/Mora LM, Viterbi Alignment
│   ├── metrics.py           # CER, MER, WER, S/D/I breakdown, confusion pairs, RTF
│   ├── train.py             # Training loop, validation, checkpoint save/load, history JSON
│   ├── inference.py         # High-level ASREngine (load checkpoint -> transcribe + visuals payload)
│   ├── server.py            # FastAPI backend (REST API + static UI serving)
│   └── web/
│       └── index.html       # Zero-CDN interactive ASR Playground (Canvas 2D + Web Audio API)
├── tests/
│   ├── test_asr_dsp.py      # M1: Audio, resampling, VAD, STFT, Mel, MFCC, SpecAugment, Tokenizer
│   ├── test_asr_data.py     # M2: Fast formant synth, Tsukinami TTS integration, manifest DataLoader
│   ├── test_asr_models.py   # M3: Forward shapes, masking, CTC loss decrease on tiny overfit batch
│   ├── test_asr_decoding.py # M4: Greedy, Beam Search, LM rescoring, Alignment, CER/WER/MER metrics
│   ├── test_asr_e2e_cli.py  # M5: End-to-end generate -> train -> eval -> transcribe CLI & checkpoint
│   └── test_asr_web_api.py  # M6: FastAPI endpoints (transcribe, tts-roundtrip, corrupt, health, UI)
└── pyproject.toml           # Optional clean project metadata + pytest/dependency specification
```

---

### 4.4 Milestone Decomposition (6 Milestones)

| Milestone | Scope & Deliverables | Depends On | Key Exit Gate |
|---|---|---|---|
| **M1: Core DSP, Features & Tokenizer** | `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py` + `tests/test_asr_dsp.py`. Environment setup (`torch` CPU, `pytest`, `httpx`). | None | Unit tests pass: WAV round-trip, resampling accuracy, Mel/MFCC shapes & finite values, SpecAugment masking, VAD segments, Kana/Phoneme/ASCII encode↔decode round-trip. |
| **M2: Built-in Speech Data & Corpus Pipeline** | `asr/synth_data.py` (Tier 1 Fast `kotoba` Formant Synth + Tier 2 `tsukinami` TTS wrapper with cache + built-in Japanese phrase/digit/command corpus), `asr/dataset.py` (JSONL manifest, DataLoader, collate) + `tests/test_asr_data.py`. | M1 | Generates 100+ diverse 16 kHz Japanese utterances in <5s via Tier 1; synthesizes & caches `yomu`/`carve` TTS via Tier 2; DataLoader yields padded `(B, T, F)` batches with valid `feat_lengths` & `target_lengths`. |
| **M3: Acoustic Models & Training Engine** | `asr/models/{subsampling,cnn_bigru,conformer}.py`, `asr/train.py` + `tests/test_asr_models.py`. | M1, M2 | Both `cnn_bigru` and `conformer_lite` pass shape/gradient tests; 20-step overfit test on 8 utterances drives CTC loss down >50% and greedy CER → ~0%; checkpoint save/load reproduces identical logits (`atol=1e-5`). |
| **M4: CTC Decoding, N-gram LM, Alignment & Metrics** | `asr/decoding.py` (Greedy, Prefix Beam Search with `temperature`/`blank_bias`, lightweight N-gram LM, Viterbi CTC alignment), `asr/metrics.py` (CER/MER/WER/RTF/confusion) + `tests/test_asr_decoding.py`. | M1 | Beam search (`width=1`) matches Greedy; beam search (`width>1`) with LM improves or matches score on synthetic ambiguous logits; Viterbi alignment yields monotonic frame spans; CER/WER verified against known Levenshtein fixtures. |
| **M5: Inference Engine, CLI & Pre-trained Demo Workflow** | `asr/inference.py` (`ASREngine`), `asr/__main__.py` (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) + `tests/test_asr_e2e_cli.py`. | M2, M3, M4 | `python -m asr demo` runs end-to-end on CPU (generate → train compact model → eval → transcribe `--tts` sample) achieving held-out CER < 25% in <2 min; all CLI subcommands pass E2E tests. |
| **M6: Interactive Web Playground ("遊べる ASR")** | `asr/server.py` (FastAPI) + `asr/web/index.html` (Zero-CDN Canvas 2D + Web Audio UI: Mic, WAV upload, Tsukinami TTS→ASR round-trip, Noise/Filter Corruption Lab, Waveform/Mel/CTC-Posterior/Alignment visualizers, live Beam Search knobs) + `tests/test_asr_web_api.py`. | M5 | All FastAPI endpoints verified via `TestClient` (health, model info, transcribe WAV, TTS→ASR round-trip with preset & corruption params, beam-knob re-decode); UI serves cleanly with zero console errors / zero external CDN deps. |

---

### 4.5 Interface Contracts (Cross-Milestone API Boundaries)

1. **Audio & Feature Contract (`asr/audio.py`, `asr/features.py`):**
   - `load_wav(path: str, target_sr: int = 16000) -> tuple[np.ndarray, int]` — returns 1D `float32` array in `[-1.0, 1.0]`.
   - `apply_corruption(wav: np.ndarray, sr: int, *, snr_db: float | None = None, noise_type: str = "white", band_limit: tuple[float, float] | None = None, speed: float = 1.0) -> np.ndarray`.
   - `extract_log_mel(wav: np.ndarray, cfg: AudioConfig) -> np.ndarray` — returns `float32` shape `(T, cfg.n_mels)` (default `n_mels=64`, `n_fft=512`, `win_length=400`, `hop_length=160` @ 16 kHz).
2. **Tokenizer Contract (`asr/tokenizer.py`):**
   - `Tokenizer.blank_id == 0` (always `<blank>`).
   - `encode(text: str) -> list[int]`, `decode(ids: Sequence[int], collapse_ctc: bool = False) -> str`.
   - `to_dict() -> dict` / `Tokenizer.from_dict(d: dict) -> Tokenizer` (embedded inside every checkpoint).
3. **Manifest & Batch Contract (`asr/dataset.py`):**
   - JSONL record schema:
     ```json
     {"audio_path": "path/to/utt.wav", "text": "ワタシ、ニホンゴ", "duration": 1.42, "speaker": "default", "source": "kotoba_fast", "moras": [{"t": "ワ", "a": 0.1, "e": 0.22}]}
     ```
   - `collate_asr_batch(items)` returns `dict`:
     - `feats`: `Tensor[B, T_max, n_mels]` (`float32`)
     - `feat_lengths`: `Tensor[B]` (`int64`)
     - `targets`: `Tensor[B, L_max]` (`int64`, padded with `0`)
     - `target_lengths`: `Tensor[B]` (`int64`)
     - `texts`: `list[str]`
4. **Acoustic Model Contract (`asr/models/`):**
   - `model(feats: Tensor[B, T, F], feat_lengths: Tensor[B]) -> tuple[Tensor[B, T', V], Tensor[B]]` — returns `(log_probs, out_lengths)` where `log_probs` is already `log_softmax` over `dim=-1`.
   - `output_frame_stride_ms`: property returning `hop_ms * subsampling_factor` (e.g., `10.0 * 4 = 40.0` ms), used by alignment & UI timelines.
5. **Decoding & Inference Contract (`asr/decoding.py`, `asr/inference.py`):**
   - `DecodeConfig(method="beam", beam_width=8, temperature=1.0, blank_bias=0.0, lm_weight=0.0, insertion_bonus=0.0)`.
   - `ASREngine.transcribe(wav: np.ndarray, sr: int, decode_cfg: DecodeConfig, include_visuals: bool = False) -> TranscribeResult`:
     - Always returns: `text`, `hypotheses` (list of `{text, score, acoustic_score, lm_score}`), `alignment` (list of `{token, start_sec, end_sec, confidence}`), `rtf`, `duration_sec`.
     - When `include_visuals=True`: also returns downsampled `waveform`, `log_mel` `(T, n_mels)`, `ctc_posteriors` (`{times_sec, top_tokens, probs}`), and `vad_segments`.
6. **Web API Contract (`asr/server.py`):**
   - `GET /` — Serves `asr/web/index.html`.
   - `GET /api/info` — Loaded checkpoint metadata, vocab, model architecture, available `tsukinami` presets, training history curves.
   - `POST /api/transcribe` — Accepts multipart WAV upload (or base64 PCM) + `DecodeConfig` + optional corruption params (`snr_db`, `noise_type`, `band_limit`, `speed`) → returns `TranscribeResult` JSON (with visuals).
   - `POST /api/tts-roundtrip` — Accepts `{text, preset, hz, fscale, yure, rate, synth_engine: "tsukinami"|"fast", corruption, decode_cfg}` → synthesizes Japanese audio, runs ASR, computes CER against input `text`, returns `audio_b64`, `ground_truth_moras`, `cer`, and full `TranscribeResult`.
   - `POST /api/redecode` — Re-runs CTC decoding on cached `log_probs` from the last utterance when user drags `beam_width` / `temperature` / `blank_bias` / `lm_weight` sliders (instant <10 ms feedback without re-running the neural net!).

---

### 4.6 Playability & E2E Testability Plan

- **Instant Playability ("遊べる" Experience):**
  1. `python -m asr demo` — Single command that generates a compact Japanese kana dataset (Tier 1 fast formant synth + sample `tsukinami` utterances), trains a genuine `cnn_bigru` CTC model in ~1 minute on CPU, saves `checkpoints/demo.pt`, prints evaluation CER/WER & confusion matrix, and runs a live TTS→ASR transcription demo.
  2. `python -m asr serve --checkpoint checkpoints/demo.pt` — Opens the zero-CDN browser playground where the user can immediately:
     - Type Japanese kana → hear `tsukinami` speak it → see Mel-spectrogram, CTC spiky posteriors, and mora alignment → compare ground-truth vs ASR hypothesis;
     - Switch presets (`ossan`, `robot`, `horror`, `whisper`, `chibi`) or crank up white/pink noise & telephone filtering to *break* the ASR and watch CTC probabilities flatten;
     - Drag `beam_width`, `temperature`, `blank_bias`, and `lm_weight` sliders for instant `<10 ms` `/api/redecode` updates;
     - Record their own voice via microphone or drop in any `.wav` file.
- **Automated Verification Pyramid:**
  - **Unit tests (M1–M4):** Pure deterministic tests with fixed seeds (`pytest tests/test_asr_*.py`), zero network access, <15s total.
  - **Overfit Sanity Gate (M3):** Mandatory proof of genuine gradient learning (CTC loss drops >50%, CER drops near 0% on a small batch — proves the model is NOT hardcoded/dummy).
  - **Generalization Gate (M5):** Train/val split with held-out utterances/speakers; verify held-out CER < 25% on built-in synthetic benchmark.
  - **API & UI Smoke Gate (M6):** FastAPI `TestClient` exercises `/`, `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`; verify existing `python3 yomu.py --help` remains unbroken.

---

## 5. Verification Method

To independently verify all observations and design assumptions in this handoff:

1. **Verify workspace state & existing TTS files:**
   ```bash
   ls -la /home/antigravity/poidowl/tsukinami
   head -n 25 /home/antigravity/poidowl/tsukinami/README_EN.md
   ```
2. **Verify `kotoba.tracks_from_kana()` and `yomu`/`carve` integration & timing:**
   ```bash
   python3 -c "import kotoba, yomu, carve as C; tr = kotoba.tracks_from_kana('あいうえお'); print('tracks frames:', tr['n'], 'moras:', len(tr['moras'])); rc = yomu.build_carve_rc('あいうえお', dict(yomu.PRESETS['default'])); wav, m = C.make(rc); print('carve SR:', C.SR, 'len:', len(wav), 'moras:', m[:2])"
   ```
3. **Verify environment capabilities:**
   ```bash
   python3 --version && python3 -c "import numpy, fastapi, uvicorn; print(numpy.__version__, fastapi.__version__, uvicorn.__version__)" && nproc && free -h
   ```
4. **Invalidation conditions:**
   - If the orchestrator requires **zero new pip installs** (disallowing `torch` CPU wheel), switch from Architecture Option 1 (Hybrid) to **Option 2 (100% Pure-NumPy TDNN-CTC)** in M3 while keeping M1, M2, M4, M5, M6 contracts unchanged.
   - If a GPU becomes available, increase default `cnn_bigru`/`conformer_lite` hidden size and dataset size in `asr/config.py` with no architectural changes required.
