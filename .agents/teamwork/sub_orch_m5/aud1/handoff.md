# Forensic Integrity Audit Report — Intermediate Milestone M5 Audit (Iteration 1)

**Auditor**: `aud1`  
**Scope**: Milestone M5 (`asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py`)  
**Verdict**: **CLEAN**

---

## 1. Exclusive File Ownership Verification

- Checked `git status -uno` and `git diff --stat` in `/home/antigravity/poidowl/tsukinami`:
  - `git status -uno`: `nothing to commit` — zero tracked repository files (including all existing TTS source files and HTML demos) were modified.
  - `git diff --stat`: empty.
- Inspected file modification timestamps across `asr/`, `asr/models/`, `tests/`, and `tests_e2e/`:
  - Only the three M5-scoped files were created/modified in this milestone:
    - `asr/inference.py` (`2026-11-19 04:21:24Z`)
    - `asr/__main__.py` (`2026-11-19 04:22:14Z`)
    - `tests/test_asr_cli.py` (`2026-11-19 04:23:05Z`)
  - All M1–M4 files (`03:10`–`04:05Z`) and `tests_e2e/` (`03:13`–`03:25Z`) remain completely untouched.

**Result**: PASS — Exclusive file ownership strictly respected.

---

## 2. Genuine Implementation Audit

### `asr/inference.py` (`ASREngine`)
- **`from_checkpoint`**: Calls `asr.train.load_checkpoint`, reconstructs `ModelConfig`, `AudioConfig`, `Tokenizer`, and optional `CharNgramLM`, instantiates the PyTorch model via `asr.models.build_model`, loads `ckpt["model_state_dict"]`, moves to `device`, and sets `model.eval()`.
- **`transcribe`**:
  - Validates `sr` (rejecting `bool`/non-positive values) and `decode_cfg`.
  - Mixes 2D audio to mono float32 and sanitizes `NaN`/`±Inf` via `np.nan_to_num`; resamples via `asr.audio.resample` when `sr != audio_cfg.sample_rate`.
  - Cleanly handles empty (`len == 0`) and very short audio without crashing.
  - Runs real Log-Mel extraction (`asr.features.extract_log_mel`), real PyTorch forward pass under `self.model.eval()` and `torch.no_grad()`, slices valid frames by `out_lengths`, and stores real `log_probs` in a bounded `OrderedDict` LRU cache (`max_cache_size`).
  - Runs real `greedy_decode` or `prefix_beam_search` (with optional `CharNgramLM`) and real `viterbi_align`.
  - Computes real `rtf` via `asr.metrics.compute_rtf`.
  - When `include_visuals=True`, computes real `detect_vad`, downsampled `waveform`/`log_mel`, and `ctc_posteriors` (`np.exp` over real `log_probs`, `<blank>` + top-K peak tokens).
- **`redecode`**:
  - Looks up cached `log_probs` by `utterance_id` (raises `KeyError` if unknown/evicted), promotes LRU order via `move_to_end`, and re-runs `_decode_and_align` directly on cached `log_probs` without touching feature extraction or PyTorch.
- **`info`**:
  - Computes actual parameter count (`sum(p.numel() for p in self.model.parameters())`) and returns strictly JSON-serializable metadata (sanitizing non-finite floats).

### `asr/__main__.py` (`python -m asr <subcommand>`)
- **`demo`**: Genuinely executes the full 4-step pipeline (`generate_dataset` → `train_asr` → `ASREngine.from_checkpoint` + `_evaluate_manifest` → live `synthesize_fast_kotoba` + `engine.transcribe` + `compute_cer`). No hardcoded transcripts or bypassed training/inference.
- **`generate`**, **`train`**, **`eval`**, **`transcribe`**: All wire directly into real M2–M5 implementations (`generate_dataset`, `train_asr`, `ASREngine`, `load_wav`, `synthesize_fast_kotoba`, `synthesize_tsukinami`, `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`, `compute_rtf`).
- **`serve`**: Validates port and optional checkpoint path and lazily imports `asr.server.create_app` and `uvicorn` inside `_cmd_serve`, keeping `python -m asr --help` and `serve --help` functional before M6.
- **`main`**: Catches expected CLI/runtime errors cleanly, prints concise message to `sys.stderr`, and returns exit code `1`.

**Result**: PASS — 100% genuine implementation, no hardcoded outputs, no mocked-out core logic, no facade shortcuts.

---

## 3. Test Integrity Audit (`tests/test_asr_cli.py`)

- Inspected all 13 tests (632 lines):
  - Zero skipped (`pytest.mark.skip`) or `xfail` tests.
  - Zero mocking or monkeypatching of core ASR/DSP/training/decoding logic.
  - Module-scoped `tiny_bundle` fixture genuinely generates a synthetic dataset (`generate_dataset`), trains a real `cnn_bigru` PyTorch checkpoint (`train_asr`), and saves a real synthesized WAV (`synthesize_fast_kotoba` + `save_wav`).
  - Tests meaningfully assert real behavior across `ASREngine` (checkpoint loading, metadata JSON serialization, greedy/beam/LM transcription, `include_visuals=True`, `<10 ms` `redecode`, LRU cache eviction, 44.1 kHz stereo + NaN sanitization, empty/short/invalid inputs) and all CLI subcommands (`--help`, `serve --help`, `generate`, `train`, `eval` text & JSON, `transcribe --wav` in-process & subprocess, `transcribe --tts` fast & tsukinami, end-to-end `demo` subprocess, and error exit codes).

**Result**: PASS — Tests are genuine, non-tautological, and exercise real code paths.

---

## 4. Independent Test Execution

Command executed in `/home/antigravity/poidowl/tsukinami`:
```text
.venv/bin/pytest tests/test_asr_cli.py -v
```
Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 13 items

tests/test_asr_cli.py .............                                      [100%]

============================= 13 passed in 31.04s ==============================
```

**Result**: PASS — 13/13 tests passed independently with exit code 0.

---

## Final Verdict

**CLEAN** — Milestone M5 (`asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py`) passes all forensic integrity checks with no violations.
