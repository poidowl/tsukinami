# Primary Reviewer (`rev1`) Handoff — Milestone M5 (Iteration 1)

## Verdict: APPROVE

Milestone M5 (`asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py`) fully satisfies `PROJECT.md § Interface Contracts #7` and `SCOPE.md`, passes all 132 M1–M5 unit tests, and leaves all existing TTS files untouched.

---

## Independent Test Execution

Command:
```bash
.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py tests/test_asr_cli.py -v
```

Exact Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 132 items

tests/test_asr_dsp.py .............................................      [ 34%]
tests/test_asr_data.py ...................                               [ 48%]
tests/test_asr_decoding.py ......................................        [ 77%]
tests/test_asr_models.py .................                               [ 90%]
tests/test_asr_cli.py .............                                      [ 100%]

======================== 132 passed in 89.42s (0:01:29) ========================
```

Repository cleanliness check (`git status --short`):
- Confirmed zero modifications to any existing TTS source or HTML files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `index.html`, etc.).

---

## Detailed Line-by-Line Review

### 1. `asr/inference.py` (`ASREngine`)
- **Constructor & `from_checkpoint`**:
  - Signature matches `SCOPE.md` (`ASREngine(model, audio_cfg, model_cfg, tokenizer, *, lm=None, checkpoint_meta=None, max_cache_size=32, device="cpu")`) with strict validation on `max_cache_size` (rejects `bool`, non-`int`, `< 1`).
  - `ASREngine.from_checkpoint` loads checkpoints via `asr.train.load_checkpoint`, reconstructs `ModelConfig`, `AudioConfig` (supporting both `audio_config` and `audio_cfg` keys), `Tokenizer`, optional `CharNgramLM`, and model weights, and sets `eval()` mode.
- **`transcribe`**:
  - Validates `sr > 0` (rejecting `bool`), mixes 2D multi-channel waveforms to 1D `float32` mono (rejecting 0-channel or >2D arrays), sanitizes `NaN`/`±Inf`, and resamples when `sr != audio_cfg.sample_rate`.
  - Handles empty (`len == 0`) and very short (`< win_length`) waveforms cleanly without crashing, returning valid cached `utterance_id` and empty/finite payloads.
  - Runs `extract_log_mel` and acoustic model under `eval()` + `torch.no_grad()`, caches `(log_probs, duration_sec, frame_stride_ms)` in a bounded `OrderedDict` LRU cache (`max_cache_size`).
  - Runs Greedy or Prefix Beam Search (`asr.decoding`) + `viterbi_align` (guarded against `ValueError`), returning the exact required keys: `text`, `hypotheses` (`{text, score, acoustic_score, lm_score}`), `alignment` (`{token, start_sec, end_sec, confidence}`), `rtf`, `duration_sec`, `utterance_id`.
  - When `include_visuals=True`, adds strictly JSON-serializable `waveform` (downsampled), `log_mel` (preserving `n_mels`), `ctc_posteriors` (`{times_sec, top_tokens, probs}` with blank token first and probabilities clipped to `[0, 1]`), and `vad_segments` (`[[start_sec, end_sec], ...]`).
- **`redecode`**:
  - Raises `KeyError` for unknown/evicted `utterance_id` and `TypeError` for non-`DecodeConfig`.
  - Promotes `utterance_id` to MRU (`move_to_end`), skips feature extraction and PyTorch inference, runs `<10 ms`, and returns `text`, `hypotheses`, `alignment`, `utterance_id`, `duration_sec`, `decode_ms`.
- **`info`**:
  - Returns strictly JSON-serializable (`allow_nan=False`) metadata including `arch`, `num_parameters`/`param_count`, `subsampling_factor`, `frame_stride_ms`, `model_config`, `audio_config`, `tokenizer` & flat vocab fields, `tsukinami_presets`, `has_lm`, `cache_size`, `max_cache_size`, `checkpoint` metadata, and `history`, sanitizing non-finite floats (e.g., `inf`) to `None`.

### 2. `asr/__main__.py` (CLI: `.venv/bin/python -m asr <subcommand>`)
- All 6 required subcommands (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) and all flags specified in `PROJECT.md § Interface Contracts #7` and `SCOPE.md` are present and wired cleanly.
- `demo`: one-command CPU quickstart generating data, training (`hidden_size=128` compatible with both `cnn_bigru` and `conformer_lite`), evaluating CER/MER/RTF/confusions, and running a live TTS→ASR round-trip.
- `eval` & `transcribe`: support `--json` outputting a single strict JSON object (`allow_nan=False`); `transcribe` enforces mutually exclusive required `--wav` / `--tts` group and supports `--engine fast|tsukinami` and `--preset`.
- `serve`: lazily imports `asr.server.create_app` and `uvicorn` inside `_cmd_serve`, ensuring `python -m asr --help` and `python -m asr serve --help` succeed before M6 creates `asr/server.py`.
- Error handling: catches expected runtime/IO/validation errors in `main()`, prints concise messages to `stderr`, and exits non-zero (`1` for handler errors, `2` for argparse errors).

### 3. `tests/test_asr_cli.py`
- 13 thorough, fast, deterministic tests covering `ASREngine` (`from_checkpoint`, `info`, greedy/beam/LM `transcribe`, `include_visuals=True`, `<10 ms` `redecode`, LRU eviction, resampling/stereo/NaN sanitization, empty/short/invalid inputs) and all CLI subcommands (`--help`, `serve --help`, `generate`, `train`, `eval`, `transcribe --wav`/`--tts`, end-to-end `demo` subprocess, and 9 CLI error paths).

---

## Findings
- **Blocking issues**: None.
- **Minor observations**: None requiring changes.
