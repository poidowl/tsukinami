# Primary Reviewer (`rev3`) Handoff — Milestone M5 (Iteration 2)

## Verdict: **APPROVE**

## Independent Verification — M1–M5 Unit Test Suite

### Command
```bash
.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py tests/test_asr_cli.py -v
```

### Exact Output
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 135 items

tests/test_asr_dsp.py .............................................      [ 33%]
tests/test_asr_data.py ...................                               [ 47%]
tests/test_asr_decoding.py ......................................        [ 75%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_cli.py ................                                   [ 100%]

=============================== warnings summary ===============================
tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 135 passed, 1 warning in 76.35s (0:01:16) ===================
```
*(Note: The single `UserWarning` is expected PyTorch unpickler output triggered by `test_corrupt_pickle_frame_checkpoint` intentionally passing a malformed protocol-4 pickle `FRAME` header.)*

---

## Line-by-Line Code Review

### 1. Iteration 2 Targeted Fixes Verification

1. **`asr/inference.py` — `_prepare_waveform` channels-first stereo `(C, N)` (L98–L110)**:
   - Verified: 2D arrays with `0 < arr.shape[0] <= 8` and `arr.shape[1] > arr.shape[0]` average across `axis=0` with `dtype=np.float32`, preserving full sample length for `(2, 16000)` and multi-channel `(C, N)` layouts.
   - Verified: Samples-first `(N, C)` layouts average across `axis=-1`, and zero-channel shapes `(N, 0)`, `(2, 0)`, `(0, 0)` raise `ValueError("2D audio array must have at least 1 channel")`.
   - Verified: 3D+ arrays still raise `ValueError`.

2. **`asr/inference.py` — `_prepare_waveform` integer PCM normalization (L88–L96)**:
   - Verified: Inspects `raw = np.asarray(wav)` prior to casting to `float32`.
   - Signed integers (`np.signedinteger`, e.g., `int16`, `int32`, `int8`) divide by `float(-int(np.iinfo(raw.dtype).min))` (using arbitrary-precision Python `int` to avoid integer negation overflow), mapping `int16` `[-32768, 32767]` cleanly into `[-1.0, 1.0)`.
   - Unsigned integers (`np.unsignedinteger`, e.g., `uint8`, `uint16`) center around `mid = float(int(np.iinfo(raw.dtype).max) + 1) / 2.0` and divide by `mid`, mapping `uint8` `[0, 255]` cleanly into `[-1.0, 1.0)`.
   - Floating-point inputs convert to `float32` without rescaling, and non-finite values (`NaN`, `±Inf`) are sanitized afterward.

3. **`asr/inference.py` (`ASREngine.from_checkpoint`, L244–L258) & `asr/__main__.py` (`main`, L507–L524) — Corrupt checkpoint exception normalization**:
   - Verified: `ASREngine.from_checkpoint` lets `FileNotFoundError` and `IsADirectoryError` propagate cleanly, and normalizes `(OverflowError, EOFError, IndexError, UnicodeDecodeError, pickle.PickleError, zipfile.BadZipFile, struct.error, RuntimeError)` from `load_checkpoint` into `ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc`.
   - Verified: `asr/__main__.py:main()` catches `(FileNotFoundError, ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError, OverflowError, EOFError, pickle.PickleError, zipfile.BadZipFile, struct.error)`, printing `Error: {exc}` to `stderr` and returning exit code `1` with no uncaught traceback across all subcommands (including `train --resume`).

4. **`tests/test_asr_cli.py` — Iteration 2 regression tests (L634–L708)**:
   - `test_engine_channels_first_stereo_and_zero_channel`: Confirms `(2, 16000)` and `(16000, 2)` yield identical `duration_sec == 1.0`, `text`, and `waveform`, and `(16000, 0)` raises `ValueError`.
   - `test_engine_integer_pcm_normalization`: Confirms `int16` sine, `-50 dBFS` `int16` quiet noise (matching `float32` `vad_segments == []` and amplitude), and `uint8` sine all normalize cleanly into `[-1.0, 1.0]`.
   - `test_corrupt_pickle_frame_checkpoint`: Confirms corrupt pickle `FRAME` header raises `ValueError` in `ASREngine.from_checkpoint` and exits `1` with `"Error:"` and no `"Traceback"` in `python -m asr eval`.

### 2. Contract & Scope Compliance (`PROJECT.md § Interface Contracts #7` & `SCOPE.md`)
- **`ASREngine`** (`asr/inference.py`):
  - Constructor, `from_checkpoint`, `transcribe` (base keys + `include_visuals=True` JSON-serializable `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`), `redecode` (<10 ms cached re-decoding + `KeyError` on unknown/evicted ID), bounded LRU `OrderedDict` cache, and strictly JSON-serializable `info()` all match `PROJECT.md` and `SCOPE.md`.
- **CLI** (`asr/__main__.py`):
  - All 6 subcommands (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) match documented flags, defaults, JSON output modes, lazy `asr.server`/`uvicorn` imports in `serve`, and clean non-zero error exit handling.
- **Working Tree Hygiene**:
  - `git status --short` confirms no existing TTS files were modified and all M5 changes are strictly within `asr/inference.py`, `asr/__main__.py`, and `tests/test_asr_cli.py`.

## Final Decision
**APPROVE** — All Iteration 2 fixes are complete, clean, well-tested, and all 135 M1–M5 unit tests pass with zero regressions.
