# Worker 2 (`worker2`) Handoff — Milestone M5 (Iteration 2)

## Summary of Fixes

All 4 targeted fixes from Verification Wave 1 (`chal1` and `chal2`) were implemented strictly within the 3 exclusively owned files:

1. **`/home/antigravity/poidowl/tsukinami/asr/inference.py` — `_prepare_waveform` (Channels-first stereo `(C, N)`)**
   - Updated 2D waveform handling so channels-first arrays with `0 < arr.shape[0] <= 8` and `arr.shape[1] > arr.shape[0]` average along `axis=0`.
   - Preserved samples-first `(N, C)` averaging along `axis=-1` and `ValueError("2D audio array must have at least 1 channel")` when `arr.shape[1] == 0`.
2. **`/home/antigravity/poidowl/tsukinami/asr/inference.py` — `_prepare_waveform` (Integer PCM normalization)**
   - Inspected `raw = np.asarray(wav)` prior to `float32` conversion:
     - Signed integer arrays (`np.signedinteger`, e.g., `int16`, `int32`) are cast to `float32` and divided by `float(-int(np.iinfo(raw.dtype).min))` (e.g., `32768.0` for `int16`).
     - Unsigned integer arrays (`np.unsignedinteger`, e.g., `uint8`) are centered around `mid = float(int(np.iinfo(raw.dtype).max) + 1) / 2.0` and divided by `mid`.
     - Floating-point arrays are converted to `np.float32` as before.
3. **`/home/antigravity/poidowl/tsukinami/asr/inference.py` (`ASREngine.from_checkpoint`) & `/home/antigravity/poidowl/tsukinami/asr/__main__.py` (`main`) — Corrupt checkpoint exception normalization**
   - Wrapped `load_checkpoint(ckpt_path, device=device)` in `ASREngine.from_checkpoint` so `FileNotFoundError` and `IsADirectoryError` propagate as-is, while `(OverflowError, EOFError, IndexError, UnicodeDecodeError, pickle.PickleError, zipfile.BadZipFile, struct.error, RuntimeError)` are raised as `ValueError(f"Corrupt or invalid checkpoint '{ckpt_path}': {exc}") from exc`.
   - Expanded the `except` tuple in `asr/__main__.py:main()` to include `(OverflowError, EOFError, pickle.PickleError, zipfile.BadZipFile, struct.error)` so all subcommands (including `train --resume`) emit `Error: ...` on stderr and exit with code `1` without an uncaught traceback.
4. **`/home/antigravity/poidowl/tsukinami/tests/test_asr_cli.py` — Regression tests**
   - Added `test_engine_channels_first_stereo_and_zero_channel` verifying `(2, 16000)` and `(16000, 2)` both yield `duration_sec == 1.0` and identical outputs, while `(16000, 0)` raises `ValueError`.
   - Added `test_engine_integer_pcm_normalization` verifying `int16` and `uint8` waveforms normalize into `[-1.0, 1.0]` and `-50 dBFS` `int16` noise produces identical `vad_segments` (`[]`) and normalized amplitude range as `float32`.
   - Added `test_corrupt_pickle_frame_checkpoint` verifying `b"\x80\x04\x95\xff\xff\xff\xff\xff\xff\xff\xff" + b"\x00" * 32` raises `ValueError` in `ASREngine.from_checkpoint` and exits cleanly with `rc=1`, `"Error:"` in stderr, and no `"Traceback"` in `python -m asr eval`.

## Modified Files
- `/home/antigravity/poidowl/tsukinami/asr/inference.py`
- `/home/antigravity/poidowl/tsukinami/asr/__main__.py`
- `/home/antigravity/poidowl/tsukinami/tests/test_asr_cli.py`

## Verification Results

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
======================== 16 passed, 1 warning in 17.27s ========================
```
