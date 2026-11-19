# Scope — Milestone M5: High-Level Inference Engine, CLI & Demo Workflow

## Exclusive File Ownership
1. `asr/inference.py` (`ASREngine`)
2. `asr/__main__.py` (CLI: `.venv/bin/python -m asr <subcommand>`)
3. `tests/test_asr_cli.py` (Unit + CLI integration tests)

## Functional Requirements

### 1. `asr/inference.py` (`ASREngine`)
- `ASREngine(model, audio_cfg, model_cfg, tokenizer, *, lm=None, checkpoint_meta=None, max_cache_size=32)`
- `ASREngine.from_checkpoint(path: str | Path, lm: CharNgramLM | None = None) -> ASREngine`
- `engine.transcribe(wav: np.ndarray, sr: int = 16000, decode_cfg: DecodeConfig | None = None, *, include_visuals: bool = False) -> dict`:
  - Resamples `wav` to `audio_cfg.sample_rate` if `sr != audio_cfg.sample_rate`.
  - Handles empty / very short audio cleanly without crashing.
  - Extracts Log-Mel, runs acoustic model in `torch.no_grad()` + `eval()`, converts `log_probs` to NumPy `(T', V)`.
  - Caches `(log_probs, duration_sec, frame_stride_ms)` under a unique `utterance_id` in a bounded LRU/`OrderedDict` cache (`max_cache_size`).
  - Runs Greedy or Prefix Beam Search (`asr.decoding`) + `viterbi_align` on top hypothesis.
  - Always returns dict with keys:
    - `text`: str
    - `hypotheses`: list of `{text, score, acoustic_score, lm_score}`
    - `alignment`: list of `{token, start_sec, end_sec, confidence}`
    - `rtf`: float
    - `duration_sec`: float
    - `utterance_id`: str
  - When `include_visuals=True`: also returns JSON-serializable:
    - `waveform`: downsampled list of floats
    - `log_mel`: 2D list of floats with shape `(T, n_mels)` (or downsampled if needed, preserving n_mels)
    - `ctc_posteriors`: `{times_sec, top_tokens, probs}`
    - `vad_segments`: list of `[start_sec, end_sec]`
- `engine.redecode(utterance_id: str, decode_cfg: DecodeConfig) -> dict`:
  - Looks up cached `log_probs` for `utterance_id` (raises `KeyError` if unknown).
  - Re-runs decoding + Viterbi alignment in `<10 ms` without re-running the neural net.
  - Returns updated `text`, `hypotheses`, `alignment`, `utterance_id`, `duration_sec`, `decode_ms`.
- `engine.info() -> dict`:
  - Returns checkpoint metadata, model config, audio config, vocab size/tokens, training history if present.

### 2. `asr/__main__.py` (CLI: `.venv/bin/python -m asr <subcommand>`)
- Subcommands matching `PROJECT.md § Interface Contracts #7`:
  - `demo [--out-dir DIR] [--epochs N] [--num-train N] [--num-val N] [--arch cnn_bigru|conformer_lite] [--seed N]`
    - One-command end-to-end CPU quickstart: generates compact dataset, trains model, evaluates CER/MER/confusion pairs, runs live TTS→ASR transcription, saves checkpoint (`best.pt`).
  - `generate --out-dir DIR [--num-train N] [--num-val N] [--engine fast|tsukinami|mixed] [--seed N]`
  - `train --train-manifest PATH --val-manifest PATH [--out-dir DIR] [--arch cnn_bigru|conformer_lite] [--epochs N] [--batch-size N] [--lr FLOAT] [--seed N] [--resume PATH]`
  - `eval --checkpoint PATH --manifest PATH [--method greedy|beam] [--beam-width K] [--json]`
  - `transcribe --checkpoint PATH (--wav PATH | --tts TEXT [--preset NAME] [--engine fast|tsukinami]) [--method greedy|beam] [--beam-width K] [--json]`
  - `serve --checkpoint PATH [--host 127.0.0.1] [--port 8000]`
    - Lazily imports `asr.server.create_app` and `uvicorn.run` so `python -m asr --help` works cleanly before M6 creates `asr/server.py`.
- Clean non-zero exit codes + helpful stderr messages on invalid arguments, missing files, or corrupt WAV/checkpoint.

### 3. `tests/test_asr_cli.py`
- Thorough unit + CLI integration tests run via `.venv/bin/pytest tests/test_asr_cli.py`.
- Covers `ASREngine` (`from_checkpoint`, `transcribe`, `include_visuals=True`, `redecode` <10ms & unknown ID `KeyError`, resampling, empty/short audio, LRU cache eviction, `info()`).
- Covers all CLI subcommands (`--help`, `generate`, `train`, `eval`, `transcribe --wav`, `transcribe --tts`, `demo`, error handling with non-zero exit codes).
