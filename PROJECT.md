# Project: Tsukinami ASR (月並み ASR — "ASRをつくって遊びたい")

## Architecture

Tsukinami ASR extends the existing `/home/antigravity/poidowl/tsukinami` pure-Python Japanese TTS repository (`kotoba.py`, `accent.py`, `carve.py`, `yomu.py`) into a complete, transparent, interactive **TTS ↔ ASR closed-loop Japanese speech recognition playground**, without modifying any existing TTS source files or HTML demos.

### Design Principles
- **Transparent DSP & Decoding (Pure NumPy + Python stdlib)**: WAV I/O, resampling, energy VAD, STFT, Slaney Mel filterbank, Log-Mel, MFCC, CMVN, SpecAugment, waveform corruptions (white/pink noise, band-pass filter, speed), Greedy CTC, Prefix Beam Search CTC, character/mora N-gram LM, Viterbi forced alignment, and CER/MER/WER/RTF/confusion metrics are all implemented from scratch in readable pure NumPy/Python.
- **Genuine End-to-End Neural CTC Acoustic Models (PyTorch CPU)**: Compact CPU-trainable models (`cnn_bigru` default ~0.5M params; `conformer_lite` optional ~1.0M params) trained with `nn.CTCLoss` and `AdamW` inside a project-local virtual environment (`.venv`).
- **Zero-Download 3-Tier Speech Data Pipeline**:
  1. **Tier 1 — Fast `kotoba` Formant-Track Synth**: Vectorized NumPy synthesizer driven by `kotoba.tracks_from_kana()` (5 ms formant/voicing/noise tracks + exact mora boundaries) with speaker randomization (`f0`, `fscale`, `rate`, SNR noise) — generates hundreds of 16 kHz Japanese utterances in seconds on CPU.
  2. **Tier 2 — Authentic `tsukinami` TTS**: Wraps `yomu.build_carve_rc` + `carve.make` across presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`) with disk caching for authentic TTS→ASR round-trip play and fine-tuning.
  3. **Tier 3 — Real Audio & External Corpus Manifests**: Unified JSONL manifest loader for arbitrary WAV folders, user microphone recordings, and external Japanese/English corpora (JSUT, CommonVoice, SpeechCommands).
- **Interactive Playability ("遊べる ASR")**:
  - One-command CLI quickstart (`python -m asr demo`) that generates data, trains a working model on CPU, evaluates CER/MER, and runs a live TTS→ASR transcription.
  - Zero-CDN FastAPI + HTML5 Canvas 2D / Web Audio interactive playground (`python -m asr serve`) with live `tsukinami` TTS→ASR round-trip, browser microphone recording, WAV upload, Noise/Filter Corruption Lab, Waveform / Log-Mel / CTC Posterior Heatmap / Mora Alignment visualizers, and `<10 ms` `/api/redecode` decoding sliders.

### Data Flow
```text
[Audio: Mic / WAV / Tsukinami TTS / Fast Kotoba Synth / Manifest]
        │  float32 @ 16 kHz mono
        ▼
asr/audio.py & asr/features.py  (Pure NumPy DSP)
        │  feats: (B, T, n_mels=64), feat_lengths: (B,)
        ▼
asr/models/  (PyTorch CPU: Conv2dSubsampling 4x -> BiGRU or Conformer-Lite -> log_softmax)
        │  log_probs: (B, T', V), out_lengths: (B,)
        ▼
asr/decoding.py & asr/metrics.py  (Pure NumPy/Python: Greedy, Prefix Beam Search + LM, Viterbi Alignment, CER/MER/WER)
        │
        ├──▶ CLI: .venv/bin/python -m asr {demo,generate,train,eval,transcribe,serve}
        └──▶ Web Playground: FastAPI (asr/server.py) + Zero-CDN Canvas UI (asr/web/index.html)
```

### Runtime & Virtual Environment Convention
- **Environment**: CPU-only Debian 12 x86_64 (2 vCPUs, 7.8 GiB RAM, 0 swap, 20 GiB disk under `/home/antigravity`).
- **Python Environment**: Project-local `.venv` at `/home/antigravity/poidowl/tsukinami/.venv` created with `uv venv .venv --python 3.11`.
- **Canonical Python executable**: `.venv/bin/python` (and `.venv/bin/pytest`).
- **Installed packages in `.venv`**: `torch` (CPU wheel from `https://download.pytorch.org/whl/cpu`), `numpy`, `fastapi`, `uvicorn`, `python-multipart`, `pytest`, `httpx`.
- **Constraint**: Existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) MUST remain unmodified and functional.

---

## Code Layout

```text
/home/antigravity/poidowl/tsukinami/
├── (existing TTS files — DO NOT MODIFY)
├── pyproject.toml               # Project metadata, dependencies, pytest config (M1)
├── .gitignore                   # Ignore .venv/, __pycache__/, checkpoints/, data/, *.pyc (M1)
├── .venv/                       # Project-local Python 3.11 virtual environment (M1)
├── asr/
│   ├── __init__.py              # Package exports & version (M1)
│   ├── __main__.py              # CLI entry: `python -m asr <subcommand>` (M5)
│   ├── config.py                # Dataclasses: AudioConfig, ModelConfig, TrainConfig, DecodeConfig (M1)
│   ├── audio.py                 # WAV I/O, resampling, mono mixdown, normalization, VAD, corruptions (M1)
│   ├── features.py              # Pure-NumPy STFT, Mel filterbank, Log-Mel, MFCC, CMVN, SpecAugment (M1)
│   ├── tokenizer.py             # Kana/Mora/Phoneme/ASCII CTC Tokenizer (uses kotoba.py) (M1)
│   ├── synth_data.py            # Tier 1 Fast Kotoba Formant Synth + Tier 2 Tsukinami TTS Builder (M2)
│   ├── dataset.py               # JSONL Manifest Dataset, PyTorch DataLoader & collate, corpus loaders (M2)
│   ├── models/
│   │   ├── __init__.py          # build_model(config, vocab_size) factory (M3)
│   │   ├── subsampling.py       # Conv2dSubsampling (4x time reduction) (M3)
│   │   ├── cnn_bigru.py         # Conv2dSubsampling + BiGRU-CTC (M3)
│   │   └── conformer.py         # Conformer-Lite-CTC (M3)
│   ├── train.py                 # Trainer, CTC loss, AdamW, LR schedule, checkpoint save/load (M3)
│   ├── decoding.py              # Greedy CTC, Prefix Beam Search, N-gram LM, Viterbi Alignment (M4)
│   ├── metrics.py               # CER, MER, WER, S/D/I breakdown, confusion pairs, RTF, alignment IoU (M4)
│   ├── inference.py             # ASREngine (checkpoint load, transcribe, redecode, visual payload) (M5)
│   ├── server.py                # FastAPI REST API + static UI server (M6)
│   └── web/
│       └── index.html           # Zero-CDN interactive Canvas 2D + Web Audio ASR Playground (M6)
├── tests/                       # Implementation Track unit tests (per-milestone)
│   ├── test_asr_dsp.py          # M1 unit tests
│   ├── test_asr_data.py         # M2 unit tests
│   ├── test_asr_models.py       # M3 unit tests
│   ├── test_asr_decoding.py     # M4 unit tests
│   ├── test_asr_cli.py          # M5 unit tests
│   └── test_asr_web.py          # M6 unit tests
└── tests_e2e/                   # E2E Testing Track opaque-box test suite (owned by E2E Track)
```

---

## Feature Inventory

Every Survey feature is assigned to a specific milestone (none unassigned).

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Project Environment & Packaging | `.venv` with PyTorch CPU + deps, `pyproject.toml`, `.gitignore`, non-invasive `asr/` layout | M1 | survey_1, survey_2, survey_3 |
| 2 | WAV/PCM I/O & Resampling | 16/32-bit WAV read/write via stdlib `wave` + `numpy`, mono mixdown, resampling to 16 kHz, optional `ffmpeg` fallback | M1 | survey_3 |
| 3 | Pure-NumPy STFT, Log-Mel & MFCC | Pre-emphasis (0.97), 25 ms/10 ms Hann STFT, 64/80-bin Slaney Mel filterbank, Log-Mel, DCT MFCC + delta, per-utterance CMVN | M1 | survey_3 |
| 4 | Energy VAD & Silence Trimming | Frame-level RMS energy VAD with threshold & hangover padding returning speech segment timestamps | M1 | survey_3 |
| 5 | SpecAugment & Waveform Corruptions | Freq/time masking, white/pink noise at target SNR (dB), random gain, speed perturbation, telephone band-pass filter (300–3400 Hz) | M1 | survey_3 |
| 6 | CTC Tokenizer (Kana/Phoneme/ASCII) | Built on `kotoba.to_kata` & `kotoba.split_moras`; `<blank>=0`, serializable `to_dict`/`from_dict` | M1 | survey_1, survey_3 |
| 7 | Tier 1: Fast `kotoba` Formant-Track Synth | Vectorized NumPy formant + fricative synth from `kotoba.tracks_from_kana()` with speaker randomization & exact mora timestamps | M2 | survey_1, survey_3 |
| 8 | Tier 2: Authentic `tsukinami` TTS Dataset Builder | Wraps `yomu.build_carve_rc` + `carve.make` across presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`) with disk cache | M2 | survey_1, survey_3 |
| 9 | Tier 3: Unified Manifest & Corpus DataLoader | JSONL manifest schema, PyTorch `Dataset` + `collate_asr_batch`, external WAV folder / JSUT / CommonVoice / mic manifest helpers | M2 | survey_3 |
| 10 | Selectable End-to-End CTC Acoustic Models | `Conv2dSubsampling` (4× time stride), `cnn_bigru` (default), `conformer_lite` (Macaron FFN + MHSA + ConvModule), `build_model` factory | M3 | survey_3 |
| 11 | Training Engine & Checkpointing | `nn.CTCLoss`, `AdamW`, cosine/OneCycle LR, grad clipping, validation loss/CER, deterministic seeding, `.pt` checkpoint save/load/resume | M3 | survey_3 |
| 12 | CTC Decoding (Greedy + Prefix Beam Search + LM) | Pure-NumPy Greedy CTC, Prefix Beam Search (`beam_width`, `temperature`, `blank_bias`), lightweight char/mora N-gram LM (`lm_weight`, `insertion_bonus`) | M4 | survey_3 |
| 13 | Viterbi Forced Alignment | Frame-level monotonic token alignment returning `{token, start_sec, end_sec, confidence}` | M4 | survey_3 |
| 14 | ASR Evaluation Metrics | Levenshtein S/D/I breakdown, CER, MER, WER, RTF, top-K substitution confusion pairs, TTS-vs-ASR mora boundary offset/IoU | M4 | survey_3 |
| 15 | High-Level Inference Engine (`ASREngine`) | Load checkpoint, transcribe WAV/array with optional visuals (`waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`), cached `redecode` | M5 | survey_3 |
| 16 | Full CLI (`python -m asr ...`) | Subcommands: `demo`, `generate`, `train`, `eval`, `transcribe` (WAV or `--tts`), `serve`; one-command CPU demo | M5 | survey_3 |
| 17 | FastAPI Backend (`asr/server.py`) | Endpoints: `GET /`, `GET /api/info`, `POST /api/transcribe`, `POST /api/tts-roundtrip`, `POST /api/redecode` (<10 ms cached re-decoding) | M6 | survey_2, survey_3 |
| 18 | Zero-CDN Interactive Web Playground (`asr/web/index.html`) | Browser Mic record, WAV upload, Tsukinami TTS→ASR round-trip, Noise/Filter Corruption Lab, Waveform/Mel/CTC-Posterior/Alignment canvases, live Beam Search sliders | M6 | survey_1, survey_3 |
| 19 | E2E Test Suite Pass & Adversarial Hardening | Pass 100% of E2E Testing Track suite (Tiers 1–4) and harden with white-box Tier 5 adversarial testing | M7 | project_pattern |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core DSP, Features, Tokenizer & Env | `.venv`, `pyproject.toml`, `.gitignore`, `asr/__init__.py`, `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `tests/test_asr_dsp.py` | none | DONE (45/45 tests, Auditor CLEAN) |
| M2 | Built-in Speech Data & Corpus Pipeline | `asr/synth_data.py`, `asr/dataset.py`, `tests/test_asr_data.py` | M1 | DONE (19/19 tests, Auditor CLEAN) |
| M3 | Acoustic Models & Training Engine | `asr/models/{__init__,subsampling,cnn_bigru,conformer}.py`, `asr/train.py`, `tests/test_asr_models.py` | M1, M2 | DONE (17/17 tests, Auditor CLEAN) |
| M4 | CTC Decoding, N-gram LM, Alignment & Metrics | `asr/decoding.py`, `asr/metrics.py`, `tests/test_asr_decoding.py` | M1 | DONE (38/38 tests, Auditor CLEAN) |
| M5 | Inference Engine, CLI & Demo Workflow | `asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py` | M2, M3, M4 | DONE (16/16 tests, Auditor CLEAN) |
| M6 | Interactive Web Playground ("遊べる ASR") | `asr/server.py`, `asr/web/index.html`, `tests/test_asr_web.py` | M5 | DONE (18/18 tests, Auditor CLEAN) |
| M7 | Final Milestone: E2E Pass (Tiers 1–4) & Tier 5 Hardening | Phase 1: pass 100% E2E tests (`TEST_READY.md`, Tiers 1–4); Phase 2: Tier 5 white-box adversarial hardening | M6, TEST_READY.md | IN_PROGRESS (Phase 1 DONE 376/376; Phase 2 Tier 5 launching) |

---

## Interface Contracts

### 1. Config (`asr/config.py`)
- `AudioConfig(sample_rate=16000, n_fft=512, win_length=400, hop_length=160, n_mels=64, f_min=80.0, f_max=7600.0, preemphasis=0.97, cmvn=True)`
- `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=192, num_layers=2, dropout=0.1, num_heads=4, conv_kernel_size=15)` (`arch` in `{"cnn_bigru", "conformer_lite"}`)
- `TrainConfig(epochs=20, batch_size=16, lr=3e-3, weight_decay=1e-4, grad_clip=5.0, seed=42, use_spec_augment=True, checkpoint_dir="checkpoints")`
- `DecodeConfig(method="beam", beam_width=8, temperature=1.0, blank_bias=0.0, lm_weight=0.0, insertion_bonus=0.0)` (`method` in `{"greedy", "beam"}`)
- All dataclasses support `.to_dict()` and `.from_dict(d)` for JSON/checkpoint serialization.

### 2. Audio & Features (`asr/audio.py`, `asr/features.py`)
- `load_wav(path: str | Path, target_sr: int = 16000) -> tuple[np.ndarray, int]` — returns 1D `float32` mono array in `[-1.0, 1.0]` and `target_sr`. Raises `FileNotFoundError` / `ValueError` on missing or corrupt/invalid files (never crashes silently).
- `save_wav(path: str | Path, wav: np.ndarray, sr: int = 16000) -> None` — writes 16-bit PCM WAV.
- `resample(wav: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray` — `float32` 1D.
- `detect_vad(wav: np.ndarray, sr: int = 16000, frame_ms: float = 20.0, threshold_db: float = -35.0, hangover_ms: float = 150.0) -> list[tuple[float, float]]` — list of `(start_sec, end_sec)` speech segments.
- `apply_corruption(wav: np.ndarray, sr: int, *, snr_db: float | None = None, noise_type: str = "white", band_limit: tuple[float, float] | None = None, speed: float = 1.0, gain_db: float = 0.0, seed: int | None = None) -> np.ndarray` — `noise_type` in `{"white", "pink"}`.
- `extract_log_mel(wav: np.ndarray, cfg: AudioConfig | None = None) -> np.ndarray` — returns `float32` shape `(T, cfg.n_mels)`.
- `extract_mfcc(wav: np.ndarray, cfg: AudioConfig | None = None, n_mfcc: int = 13, include_deltas: bool = False) -> np.ndarray` — returns `float32` shape `(T, n_mfcc)` or `(T, 3 * n_mfcc)`.
- `spec_augment(mel: np.ndarray, freq_mask_param: int = 8, time_mask_param: int = 20, num_freq_masks: int = 2, num_time_masks: int = 2, seed: int | None = None) -> np.ndarray`.

### 3. Tokenizer (`asr/tokenizer.py`)
- `Tokenizer(mode: str = "kana", vocab: list[str] | None = None)` — `mode` in `{"kana", "phoneme", "ascii"}`.
- `tokenizer.blank_id == 0`, `tokenizer.vocab_size: int`.
- `encode(text: str) -> list[int]`
- `decode(ids: Sequence[int], collapse_ctc: bool = False) -> str`
- `to_dict() -> dict` / `Tokenizer.from_dict(d: dict) -> Tokenizer`

### 4. Speech Data & Dataset (`asr/synth_data.py`, `asr/dataset.py`)
- `synthesize_fast_kotoba(text: str, *, sr: int = 16000, f0_scale: float = 1.0, fscale: float = 1.0, rate: float = 1.0, snr_db: float | None = None, seed: int | None = None) -> tuple[np.ndarray, list[dict]]` — returns `(wav_float32, moras)` where each mora dict has `{"t", "a", "e"}`.
- `synthesize_tsukinami(text: str, *, preset: str = "default", sr: int = 16000, overrides: dict | None = None, cache_dir: str | Path | None = None) -> tuple[np.ndarray, list[dict]]` — wraps `yomu.build_carve_rc` + `carve.make` and resamples 44.1 kHz → `sr`.
- `generate_dataset(out_dir: str | Path, *, num_train: int = 200, num_val: int = 40, engine: str = "fast", seed: int = 42, presets: Sequence[str] | None = None) -> dict[str, Path]` — writes `train.jsonl`, `val.jsonl`, and WAV files under `out_dir`; returns `{"train": ..., "val": ...}`.
- JSONL manifest schema:
  `{"audio_path": "...", "text": "ワタシ、ニホンゴ", "duration": 1.42, "speaker": "default", "source": "kotoba_fast", "moras": [{"t": "ワ", "a": 0.1, "e": 0.22}]}`
- `ASRManifestDataset(manifest_path, audio_cfg, tokenizer, augment=False)` + `collate_asr_batch(items) -> dict` returning `feats: Tensor[B, T_max, F]`, `feat_lengths: Tensor[B]`, `targets: Tensor[B, L_max]`, `target_lengths: Tensor[B]`, `texts: list[str]`.
- `build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path) -> Path` (Tier 3 real-audio helper).

### 5. Acoustic Models & Training (`asr/models/`, `asr/train.py`)
- `build_model(cfg: ModelConfig, vocab_size: int) -> nn.Module`
- `model(feats: Tensor[B, T, F], feat_lengths: Tensor[B]) -> tuple[Tensor[B, T', V], Tensor[B]]` — returns `(log_probs, out_lengths)` where `log_probs` is `log_softmax` over `dim=-1`.
- `model.subsampling_factor: int` (4), `model.output_frame_stride_ms(audio_cfg) -> float` (`40.0` ms for 10 ms hop).
- `train_asr(train_manifest, val_manifest, *, audio_cfg, model_cfg, train_cfg, tokenizer, resume_from=None) -> dict` — saves `best.pt` & `latest.pt` (containing `model_state_dict`, `model_config`, `audio_cfg`, `tokenizer`, `history`, `epoch`, `best_val_cer`) and returns summary metrics dict.
- `load_checkpoint(path: str | Path, device: str = "cpu") -> dict`.

### 6. Decoding, Alignment & Metrics (`asr/decoding.py`, `asr/metrics.py`)
- `CharNgramLM(order: int = 3, smoothing: float = 0.1)` with `.fit(texts: Sequence[str])`, `.score_next(prefix: str, token: str) -> float`, `.to_dict()` / `.from_dict(d)`.
- `greedy_decode(log_probs: np.ndarray, tokenizer: Tokenizer, *, temperature: float = 1.0, blank_bias: float = 0.0) -> dict` — returns `{"text", "token_ids", "score"}`.
- `prefix_beam_search(log_probs: np.ndarray, tokenizer: Tokenizer, cfg: DecodeConfig, lm: CharNgramLM | None = None) -> list[dict]` — returns top-N hypotheses `[{"text", "score", "acoustic_score", "lm_score"}]`.
- `viterbi_align(log_probs: np.ndarray, token_ids: Sequence[int], tokenizer: Tokenizer, frame_stride_ms: float = 40.0) -> list[dict]` — returns `[{"token", "start_sec", "end_sec", "confidence"}]`.
- `compute_cer(refs: Sequence[str], hyps: Sequence[str]) -> dict` (returns `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`), `compute_mer(refs, hyps) -> dict`, `compute_wer(refs, hyps) -> dict`, `confusion_pairs(refs, hyps, top_k: int = 10) -> list[tuple[str, str, int]]`, `alignment_boundary_error(gt_moras, pred_align) -> dict`.

### 7. Inference Engine & CLI (`asr/inference.py`, `asr/__main__.py`)
- `ASREngine.from_checkpoint(path: str | Path, lm: CharNgramLM | None = None) -> ASREngine`
- `engine.transcribe(wav: np.ndarray, sr: int = 16000, decode_cfg: DecodeConfig | None = None, *, include_visuals: bool = False) -> dict`
  - Keys: `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id` (cached for `redecode`), plus when `include_visuals=True`: `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`.
- `engine.redecode(utterance_id: str, decode_cfg: DecodeConfig) -> dict` — re-runs decoding on cached `log_probs` in `<10 ms`.
- CLI entry point: `.venv/bin/python -m asr <subcommand>`:
  - `demo [--out-dir DIR] [--epochs N] [--num-train N] [--arch cnn_bigru|conformer_lite]`
  - `generate --out-dir DIR [--num-train N] [--num-val N] [--engine fast|tsukinami|mixed]`
  - `train --train-manifest PATH --val-manifest PATH [--out-dir DIR] [--arch ...] [--epochs N]`
  - `eval --checkpoint PATH --manifest PATH [--method greedy|beam] [--beam-width K]`
  - `transcribe --checkpoint PATH (--wav PATH | --tts TEXT [--preset NAME]) [--method greedy|beam] [--json]`
  - `serve --checkpoint PATH [--host 127.0.0.1] [--port 8000]`

### 8. Web Playground API (`asr/server.py`, `asr/web/index.html`)
- `create_app(checkpoint_path: str | Path | None = None, engine: ASREngine | None = None) -> FastAPI`
- `GET /` — serves zero-CDN `asr/web/index.html` (`200 OK`, `text/html`).
- `GET /api/health` — `{"status": "ok", "model_loaded": bool}`.
- `GET /api/info` — loaded checkpoint metadata, vocab, model architecture, `tsukinami` presets, training history curves.
- `POST /api/transcribe` — multipart WAV file (or JSON base64 WAV) + decode & corruption params → `TranscribeResult` JSON (with visuals); returns `400`/`422` cleanly on invalid audio.
- `POST /api/tts-roundtrip` — JSON `{text, preset, hz, fscale, yure, rate, synth_engine, corruption, decode_cfg}` → synthesizes Japanese audio, runs ASR, computes CER against `text`, returns `audio_b64`, `ground_truth_moras`, `cer`, and `TranscribeResult`.
- `POST /api/redecode` — JSON `{utterance_id, decode_cfg}` → re-decodes cached `log_probs` (<10 ms); returns `404` if `utterance_id` unknown.
