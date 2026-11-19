# Secondary Reviewer (`rev2`) Handoff — Milestone M5 (Iteration 1)

## Verdict: APPROVE

## Independent Test Execution

Command:
```bash
.venv/bin/pytest tests/test_asr_cli.py -v
```

Exact output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 13 items

tests/test_asr_cli.py .............                                      [100%]

============================= 13 passed in 18.42s ==============================
```

## Scope & Working Tree Integrity Check
- `git diff --stat`: empty (no existing tracked TTS files or HTML demos modified).
- `git status --short` and file timestamps confirm M5 changes are strictly confined to the three owned files:
  - `asr/inference.py`
  - `asr/__main__.py`
  - `tests/test_asr_cli.py`

## Detailed Review

### 1. M6 Downstream Compatibility (`asr/inference.py`)
- **`/api/info` (`ASREngine.info()`)**:
  - Returns strictly JSON-serializable (`allow_nan=False`) metadata via `_sanitize_json_value` and `_finite_float_or_none` (safely converting non-finite floats like `inf` to `None`).
  - Exposes `arch`, `num_parameters` / `param_count`, `subsampling_factor`, `frame_stride_ms`, `model_config`, `audio_config`, `vocab_size`, `vocab`, `blank_id`, `tokenizer_mode`, nested `tokenizer`, `tsukinami_presets`, `has_lm`, `cache_size`, `max_cache_size`, `checkpoint` metadata, and `history` curves.
- **`/api/transcribe` & `/api/tts-roundtrip` (`ASREngine.transcribe()`)**:
  - Handles 1D/2D audio (stereo-to-mono mixdown), sanitizes `NaN`/`±Inf` via `np.nan_to_num`, resamples when `sr != audio_cfg.sample_rate`, and gracefully short-circuits empty audio (`len == 0`) as well as very short audio (`< win_length`).
  - Returns exact required keys (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`) with strict Python primitive types.
  - When `include_visuals=True`, returns strictly JSON-serializable, bounded visual payloads:
    - `waveform`: downsampled to `<= 2000` floats.
    - `log_mel`: downsampled to `<= 600` frames, preserving `n_mels`.
    - `ctc_posteriors`: `{times_sec, top_tokens, probs}` downsampled to `<= 400` frames, `blank_token` anchored at index 0, `probs` clipped to `[0.0, 1.0]` with aligned dimensions `len(probs) == len(times_sec)` and `len(probs[0]) == len(top_tokens)`.
    - `vad_segments`: list of `[start_sec, end_sec]` float pairs.
- **`/api/redecode` (`ASREngine.redecode()`)**:
  - Uses bounded `OrderedDict` LRU cache (`max_cache_size`), promotes accessed `utterance_id` to MRU on hit, and evicts oldest entry on overflow.
  - Re-runs CTC decoding + Viterbi alignment without touching PyTorch or feature extraction (`< 10 ms` verified in tests).
  - Raises `KeyError` on unknown/evicted `utterance_id` (cleanly mappable to HTTP `404` in M6).
- **Exception Contracts**:
  - `from_checkpoint`: raises `FileNotFoundError` on missing checkpoint and `ValueError` on corrupt checkpoint.
  - `transcribe`: raises `ValueError` on invalid `sr` (including `bool` or `<= 0`), invalid audio `ndim`, or 0-channel 2D arrays; raises `TypeError` on non-`DecodeConfig`.
  - `redecode`: raises `KeyError` on unknown ID and `TypeError` on non-`DecodeConfig`.
  - `viterbi_align` `ValueError` (e.g., when decoded tokens exceed frame count) is caught and returns `[]` cleanly.

### 2. CLI Ergonomics & Completeness (`asr/__main__.py`)
- All 6 subcommands (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) match `PROJECT.md § Interface Contracts #7` and `SCOPE.md`.
- **`--json` cleanliness**: Both `eval --json` and `transcribe --json` emit a single valid JSON object (`ensure_ascii=False, allow_nan=False`) to stdout with no extraneous log lines.
- **`demo` workflow**: Complete 4-step CPU quickstart — generates synthetic dataset (`engine="fast"`), trains model saving `best.pt`/`latest.pt`, evaluates validation CER/MER/Mean RTF and top confusion pairs, and executes live TTS→ASR round-trip (`オハヨウゴザイマス`).
- **`serve` lazy import**: `asr.server.create_app` and `uvicorn` are imported lazily inside `_cmd_serve`, ensuring `python -m asr --help` and `python -m asr serve --help` succeed cleanly before M6.
- **Error handling**: Clean non-zero exit codes (`1` for runtime/file/value errors with `Error: ...` on stderr; `2` for argparse validation errors like mutually exclusive `--wav`/`--tts`).

### 3. Test Suite Quality (`tests/test_asr_cli.py`)
- 13 comprehensive unit and integration tests (including real subprocess checks for `--help`, `serve --help`, `transcribe --json`, `demo`, and argparse exit codes).
- Thoroughly exercises M6 contracts (`allow_nan=False`, visual payload shapes/bounds, `<10 ms` redecode, LRU eviction, non-finite metadata sanitization, resampling/stereo/NaN handling, empty/short/invalid inputs).

## Non-Blocking Observations
- In `_cmd_train`, `if args.lr <= 0.0:` does not explicitly catch `float("nan")`, though `TrainConfig.__post_init__` handles validation and raises `ValueError` which `main()` catches cleanly. No action required.
