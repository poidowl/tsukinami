# Forensic Integrity Audit Report — Intermediate Milestone M5 Audit (Iteration 2)

- **Auditor**: `aud2`
- **Milestone**: M5 — Inference Engine, CLI & Demo Workflow (Iteration 2)
- **Sub-scope**: `asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py`
- **Verdict**: **CLEAN**

---

## 1. Exclusive File Ownership Audit

- **`git diff --stat`**: Empty — zero modifications to any tracked existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.).
- **`git status --short --untracked-files=all`**: No stray or unauthorized files created outside the M5 sub-scope.
- **File modification timestamps (`stat`)**:
  - `asr/inference.py`: `2026-11-19 04:30:47 +0000`
  - `asr/__main__.py`: `2026-11-19 04:30:47 +0000`
  - `tests/test_asr_cli.py`: `2026-11-19 04:31:10 +0000`
  - All M1–M4 files (`asr/__init__.py`, `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/*.py`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`, `tests/test_asr_{dsp,data,models,decoding}.py`), `pyproject.toml`, `.gitignore`, and `tests_e2e/*.py` have timestamps `<= 2026-11-19 04:05:25 +0000` (untouched during M5). `PROJECT.md` was last modified at `04:14:55 +0000` prior to M5 work.
- **Result**: **PASS** — Exclusive file ownership strictly respected.

---

## 2. Genuine Implementation Audit

### `asr/inference.py` (583 lines)
- **Integer PCM normalization (`_prepare_waveform`, lines 86–120)**:
  - Inspects `raw = np.asarray(wav)` prior to `float32` conversion.
  - Signed integers (`np.signedinteger`) divide by `float(-int(np.iinfo(raw.dtype).min))` (e.g., `32768.0` for `int16`, avoiding signed-min overflow).
  - Unsigned integers (`np.unsignedinteger`) center around `mid = float(int(np.iinfo(raw.dtype).max) + 1) / 2.0` and divide by `mid` (e.g., `128.0` for `uint8`).
  - Floating-point arrays cast cleanly to `np.float32`, and non-finite values are sanitized via `np.nan_to_num(..., nan=0.0, posinf=1.0, neginf=-1.0)`.
- **Channels-first `(C, N)` stereo handling (`_prepare_waveform`, lines 100–107)**:
  - Correctly detects channels-first 2D audio (`arr.shape[0] > 0 and arr.shape[0] <= 8 and arr.shape[1] > arr.shape[0]`) and averages along `axis=0`.
  - Preserves samples-first `(N, C)` averaging along `axis=-1` and raises `ValueError("2D audio array must have at least 1 channel")` when `arr.shape[1] == 0`.
- **Corrupt checkpoint exception normalization (`ASREngine.from_checkpoint`, lines 244–258)**:
  - Wraps only `load_checkpoint(ckpt_path, device=device)`.
  - Lets `FileNotFoundError` and `IsADirectoryError` propagate untouched.
  - Converts specific corrupt-file exceptions `(OverflowError, EOFError, IndexError, UnicodeDecodeError, pickle.PickleError, zipfile.BadZipFile, struct.error, RuntimeError)` into `ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc`, preserving causal tracebacks without catching broad `Exception` or hiding bugs in model instantiation or `load_state_dict`.
- **Core inference logic**: 100% genuine — real `extract_log_mel`, `self.model(feats, feat_lengths)` under `torch.no_grad()`, `greedy_decode`, `prefix_beam_search`, `viterbi_align`, `OrderedDict` LRU cache in `redecode`, `detect_vad`, `_build_ctc_posteriors`, and JSON-safe `info()`. Zero stubs, mocks, or hardcoded outputs.

### `asr/__main__.py` (529 lines)
- **Exception normalization (`main`, lines 507–524)**:
  - Expands the explicit exception tuple to include `(OverflowError, EOFError, pickle.PickleError, zipfile.BadZipFile, struct.error)` alongside the existing expected CLI/IO/validation errors, emitting `Error: {exc}` to `stderr` and returning exit code `1`. Does not catch bare `Exception` or swallow unexpected programming errors (e.g., `AttributeError`, `NameError`, `ZeroDivisionError`).
- **Subcommands**: All 6 subcommands (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) invoke genuine end-to-end functions with lazy import of `asr.server.create_app` and `uvicorn`.

- **Result**: **PASS** — 100% genuine implementation.

---

## 3. Test Integrity Audit

### `tests/test_asr_cli.py` (709 lines, 16 tests)
- Zero `pytest.skip`, zero `xfail`, zero mocking/monkeypatching of core ASR logic, zero trivialized assertions.
- Module fixture `tiny_bundle` genuinely generates synthetic data via `generate_dataset`, trains a real `cnn_bigru` model with `train_asr`, and saves a real `.pt` checkpoint.
- **3 new Iteration 2 regression tests**:
  1. `test_engine_channels_first_stereo_and_zero_channel` (lines 634–653): Compares `(2, 16000)` and `(16000, 2)` through real `engine.transcribe(..., include_visuals=True)`, verifying `duration_sec == 1.0`, identical `text` and `waveform`, and `ValueError` for `(16000, 0)`.
  2. `test_engine_integer_pcm_normalization` (lines 656–690): Exercises `int16` sine, `-50 dBFS` `int16` quiet noise vs `float32` (confirming identical `vad_segments == []` and normalized amplitude range), and `uint8` sine normalization into `[-1.0, 1.0]`.
  3. `test_corrupt_pickle_frame_checkpoint` (lines 693–707): Writes malformed pickle protocol 4 `FRAME` header bytes (`b"\x80\x04\x95\xff\xff\xff\xff\xff\xff\xff\xff" + b"\x00" * 32`), asserts `ASREngine.from_checkpoint` raises `ValueError`, and runs a real subprocess `python -m asr eval` asserting `returncode == 1`, `"Error:"` in stderr, and `"Traceback"` absent from stderr.

- **Result**: **PASS** — Tests are genuine and thorough.

---

## 4. Independent Test Execution

Command executed in `/home/antigravity/poidowl/tsukinami`:
```bash
.venv/bin/pytest tests/test_asr_cli.py -v
```

Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 16 items

tests/test_asr_cli.py ................                                   [100%]

=============================== warnings summary ===============================
tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/how-to-capture-warnings.html
======================== 16 passed, 1 warning in 19.91s ========================
```

- **Result**: **PASS** — `16/16` tests passed independently (exit code `0`).

---

## Final Verdict

**CLEAN** — All Iteration 2 fixes and existing M5 code/tests are 100% genuine, exclusive file ownership is intact, and all 16 tests pass independently.
