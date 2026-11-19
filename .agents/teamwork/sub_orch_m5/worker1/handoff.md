# Worker 1 (`worker1`) Handoff — Milestone M5

## Summary of Implemented Files

1. **`asr/inference.py`** (`ASREngine`):
   - Implemented `ASREngine(model, audio_cfg, model_cfg, tokenizer, *, lm=None, checkpoint_meta=None, max_cache_size=32, device="cpu")` and `ASREngine.from_checkpoint(path, lm=None, *, device="cpu", max_cache_size=32)`.
   - `transcribe(wav, sr=16000, decode_cfg=None, *, include_visuals=False)`:
     - Validates `sr > 0` (rejecting `bool`), mixes 2D stereo/multi-channel waveforms to 1D float32 mono, sanitizes `NaN`/`±Inf` via `np.nan_to_num`, and resamples to `audio_cfg.sample_rate` when `sr != audio_cfg.sample_rate`.
     - Short-circuits empty audio (`len == 0`) cleanly to empty `log_probs (0, V)`, `duration_sec=0.0`, `rtf=0.0`, cached `utterance_id`, and empty visual payloads when requested; handles very short audio (`< win_length`) without crashing.
     - Runs `extract_log_mel` + acoustic model in `eval()` / `torch.no_grad()`, caches `(log_probs, duration_sec, frame_stride_ms)` in a bounded `OrderedDict` LRU cache (`max_cache_size`), and runs Greedy or Prefix Beam Search + `viterbi_align` (with `ValueError` guard returning `[]`).
     - Returns strictly JSON-serializable (`allow_nan=False`) dict with `text`, `hypotheses` (`{text, score, acoustic_score, lm_score}`), `alignment` (`{token, start_sec, end_sec, confidence}`), `rtf`, `duration_sec`, `utterance_id`, plus optional `waveform`, `log_mel`, `ctc_posteriors`, and `vad_segments` when `include_visuals=True`.
   - `redecode(utterance_id, decode_cfg)`:
     - Promotes `utterance_id` in the LRU cache (raises `KeyError` if unknown/evicted) and re-runs CTC decoding + Viterbi alignment without touching PyTorch or feature extraction (`<10 ms`), returning `text`, `hypotheses`, `alignment`, `utterance_id`, `duration_sec`, `decode_ms`.
   - `info()`:
     - Returns strictly JSON-serializable metadata (sanitizing non-finite floats like `inf` to `None`) including `arch`, `num_parameters` / `param_count`, `subsampling_factor`, `frame_stride_ms`, `model_config`, `audio_config`, `tokenizer` & flat vocab fields, `tsukinami_presets`, `has_lm`, `cache_size`, `max_cache_size`, `checkpoint` metadata, and `history`.

2. **`asr/__main__.py`** (CLI: `.venv/bin/python -m asr <subcommand>`):
   - Exposes `build_parser()` and `main(argv: Sequence[str] | None = None) -> int`.
   - Implements all 6 subcommands: `demo`, `generate`, `train`, `eval`, `transcribe` (`--wav` or `--tts` mutually exclusive), and `serve` (with lazy import of `asr.server.create_app` and `uvicorn` inside `_cmd_serve`).
   - `--json` on `eval` and `transcribe` prints a single valid JSON object (`allow_nan=False`) to stdout.
   - Clean non-zero exit codes with concise stderr messages on missing/corrupt files or invalid arguments.

3. **`tests/test_asr_cli.py`**:
   - 13 unit + CLI integration tests covering `ASREngine` (`from_checkpoint`, `info`, `transcribe` greedy/beam/LM, `include_visuals=True`, `<10 ms` `redecode`, LRU cache eviction, resampling/stereo/NaN sanitization, empty/very-short/invalid inputs) and all CLI subcommands (`--help`, `serve --help`, `generate`, `train`, `eval`, `transcribe --wav`, `transcribe --tts` fast & tsukinami, end-to-end `demo` subprocess, and error exit codes).

## Verification Commands & Exact Outputs

### 1. `.venv/bin/pytest tests/test_asr_cli.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 13 items

tests/test_asr_cli.py .............                                      [100%]

============================= 13 passed in 15.47s ==============================
```

### 2. `.venv/bin/python -m asr --help`
```text
usage: python -m asr [-h] {demo,generate,train,eval,transcribe,serve} ...

Tsukinami ASR — pure-NumPy DSP + PyTorch CPU Japanese speech recognition
playground.

positional arguments:
  {demo,generate,train,eval,transcribe,serve}
    demo                One-command CPU quickstart: generate data, train,
                        evaluate, and run live TTS->ASR.
    generate            Generate synthetic Japanese speech dataset and JSONL
                        manifests.
    train               Train a CTC acoustic model from JSONL manifests.
    eval                Evaluate a trained checkpoint on a JSONL manifest.
    transcribe          Transcribe a WAV file or a live synthesized Japanese
                        TTS utterance.
    serve               Launch the interactive FastAPI + Canvas ASR Web
                        Playground.

options:
  -h, --help            show this help message and exit
```
