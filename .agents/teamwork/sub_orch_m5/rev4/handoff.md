# Secondary Reviewer (`rev4`) Handoff — Milestone M5 (Iteration 2)

## Verdict: **APPROVE**

## Independent Test Execution

### Command
```bash
.venv/bin/pytest tests/test_asr_cli.py -v
```

### Output
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

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 16 passed, 1 warning in 20.58s ========================
```

## Detailed Review Findings

### 1. `_prepare_waveform` Edge-Case Verification (`asr/inference.py:86-120`)
- **Signed integer PCM (`int16`, `int32`, `int8`, `int64`)**: `np.issubdtype(raw.dtype, np.signedinteger)` divides by `np.float32(-int(np.iinfo(raw.dtype).min))` (exact powers of two: `32768.0`, `2147483648.0`, etc.), normalizing cleanly into `[-1.0, 1.0]` so downstream VAD (`-35 dB` relative to `1.0`) and `waveform` visuals match `float32` inputs.
- **Unsigned integer PCM (`uint8`, `uint16`, `uint32`)**: `np.issubdtype(raw.dtype, np.unsignedinteger)` centers around `mid = (max + 1) / 2.0` (`128.0` for `uint8`) and divides by `mid`, mapping `[0, 255]` cleanly into `[-1.0, 127/128]`.
- **`bool` arrays**: Neither `np.signedinteger` nor `np.unsignedinteger` matches `np.bool_`, so `bool` arrays fall through to `np.asarray(raw, dtype=np.float32)` without crashing on `np.iinfo`.
- **2D shapes**:
  - `(2, N)` (e.g. `(2, 16000)`): `0 < arr.shape[0] <= 8 and arr.shape[1] > arr.shape[0]` is `True` -> averages along `axis=0`, yielding `(N,)` with `duration_sec = N / sr` and identical output to `(N, 2)`.
  - `(N, 2)` (e.g. `(16000, 2)` or `(5, 2)`): goes to `else` -> averages along `axis=-1`, yielding `(N,)`.
  - `(N, 0)` and `(0, 0)`: `arr.shape[1] == 0` -> raises `ValueError("2D audio array must have at least 1 channel")`.
  - `(0, 2)`: `arr.shape[0] > 0` is `False` -> goes to `else`, averages along `axis=-1` -> produces empty `(0,)` `float32` array (avoiding empty-axis NaN reduction), which `transcribe` handles cleanly as zero-duration empty audio.
  - `ndim >= 3` or `ndim == 0`: raises `ValueError`.
- **NaN/Inf sanitization**: Replaces non-finite values with `0.0` / `±1.0` and returns contiguous `float32`.

### 2. Exception Normalization (`asr/inference.py:244-258`, `asr/__main__.py:507-524`)
- `ASREngine.from_checkpoint` lets `FileNotFoundError` and `IsADirectoryError` propagate cleanly, while normalizing `(OverflowError, EOFError, IndexError, UnicodeDecodeError, pickle.PickleError, zipfile.BadZipFile, struct.error, RuntimeError)` from `load_checkpoint` into `ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc`.
- `asr/__main__.py:main()` catches `(FileNotFoundError, ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError, OverflowError, EOFError, pickle.PickleError, zipfile.BadZipFile, struct.error)` and prints `Error: ...` to stderr with exit code `1` (no uncaught Python traceback). Note that `UnicodeDecodeError` is a subclass of `ValueError` and is therefore also caught.
- Minor non-blocking observation: `IndexError` is caught in `ASREngine.from_checkpoint` (normalized to `ValueError`), though not in `main()`'s `except` tuple directly (relevant only if `train --resume` receives a crafted pickle file triggering `IndexError` inside `load_checkpoint`). Not a blocker and matches `GATE_STATUS.md` requirements.

### 3. Regression Tests (`tests/test_asr_cli.py:634-708`)
- `test_engine_channels_first_stereo_and_zero_channel` verifies `(2, 16000)` vs `(16000, 2)` equivalence (`duration_sec`, `text`, `waveform`) and `(16000, 0)` raising `ValueError`.
- `test_engine_integer_pcm_normalization` verifies `int16` sine, `-50 dBFS` quiet `int16` vs `float32` VAD/amplitude parity, and `uint8` centering/normalization.
- `test_corrupt_pickle_frame_checkpoint` verifies both `ASREngine.from_checkpoint` raising `ValueError` and `python -m asr eval` exiting `1` with `"Error:"` and no `"Traceback"` on stderr.

### 4. M6 Downstream Compatibility & Scope Cleanliness
- `ASREngine` (`from_checkpoint`, `transcribe(..., include_visuals=True)`, `redecode` raising `KeyError` on unknown/evicted IDs and executing in `<10 ms`, `info()`) matches `PROJECT.md § Interface Contracts #7 & #8` with strictly JSON-serializable payloads (`allow_nan=False`).
- `asr/__main__.py` `serve` subcommand lazily imports `asr.server.create_app` and `uvicorn`, passing `checkpoint_path=ckpt_path` as contracted for M6.
- `git diff --stat` confirms zero modifications to any existing tracked TTS files; changes are strictly confined to M5's exclusively owned files (`asr/inference.py`, `asr/__main__.py`, `tests/test_asr_cli.py`).
