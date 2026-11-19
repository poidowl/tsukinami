# Secondary Reviewer Handoff — M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`, Iteration 1)

## 1. Review Scope & Verdict
- **Reviewed Files**:
  - `asr/synth_data.py` (`generate_dataset`, lines 690–801)
  - `asr/dataset.py` (`_resolve_audio_path`, lines 77–86; `ASRManifestDataset`, lines 89–174; `build_manifest_from_wav_dir`, lines 306–370)
  - `tests/test_asr_data.py` (`test_generate_dataset_fast_and_determinism`, lines 332–377; `test_dataset_path_resolution_and_error_handling`, lines 492–547; `test_build_manifest_from_wav_dir_dict_and_files`, lines 555–607)
- **Working Tree Integrity**: Verified via `git diff --stat` (empty — zero edits to any tracked `tsukinami` TTS files).
- **Verdict**: **APPROVE**

---

## 2. Detailed Code Audit

### 1. `asr/synth_data.py`
- **Line 709**: `root = Path(out_dir).resolve()` resolves both relative and absolute `out_dir` arguments into a canonical absolute root before creating `audio/train` and `audio/val`.
- **Lines 742–743 & 782**: `rel_wav = Path("audio") / split_name / f"{split_name}_{i:05d}.wav"` and `abs_wav = root / rel_wav`, followed by `save_wav(abs_wav, wav, sr=sr)`. No dead variables remain (`rel_wav` constructs `abs_wav`).
- **Line 786**: Emits `"audio_path": str(abs_wav)`, guaranteeing a valid absolute filesystem path pointing to an existing WAV file in every generated `train.jsonl` and `val.jsonl` record.

### 2. `asr/dataset.py`
- **Lines 328 & 353 (`build_manifest_from_wav_dir`)**: Removed the previously unused `out_dir_resolved` variable and emits `stored_audio_path = str(wav_path.resolve())`. No leftover dead variables exist, and every emitted `audio_path` is a valid resolved absolute path even when `wav_dir` is passed as a relative path.
- **Lines 77–86 (`_resolve_audio_path`)**: Preserved unchanged.
  - Absolute paths (`p.is_absolute()`) are returned directly.
  - Relative paths first resolve against `manifest_dir` (`rel = manifest_dir / p`, returning `rel.resolve()` if it exists), then fall back to CWD-relative (`p.exists()`), and otherwise return `rel` so `ASRManifestDataset.__init__` raises `FileNotFoundError` cleanly when `validate_files=True`.
  - Full compatibility with both absolute and manifest-relative paths is maintained.

### 3. `tests/test_asr_data.py`
- **`test_generate_dataset_fast_and_determinism` (lines 332–377)**:
  - Verifies `Path(rec["audio_path"]).is_absolute()` and `Path(rec["audio_path"]).is_file()` for every record in `train` and `val`, and loads each WAV directly via `load_wav(wav_path, target_sr=16000)`.
  - Cross-directory determinism check (`ds1` vs `ds2`) is genuine and not weakened: `_normalize` rewrites only `audio_path` via `Path(r["audio_path"]).relative_to(base.resolve()).as_posix()` (which also enforces that every emitted path resides under its respective dataset root), compares full record lists for both `train` and `val`, asserts `train_recs1[0]["audio_path"] != train_recs2[0]["audio_path"]`, and checks byte-for-byte WAV equality (`wav1_bytes == wav2_bytes`).
- **`test_build_manifest_from_wav_dir_dict_and_files` (lines 555–607)**:
  - Line 583 adds the regression check `assert all(Path(r["audio_path"]).is_absolute() and Path(r["audio_path"]).is_file() for r in recs)` and verifies direct ingestion via `ASRManifestDataset` + `DataLoader`.
- **Non-blocking minor observation**: Since `generate_dataset` now emits absolute paths, adding an explicit manifest-relative path case inside `test_dataset_path_resolution_and_error_handling` in a future pass would keep direct unit coverage on the relative-path branch of `_resolve_audio_path` alongside the absolute-path test. Not blocking for M7 Phase 1 Tier 1.

---

## 3. Independent Verification Commands & Exact Outputs

### Command 1: Target-Scoped Unit Test Suite
- **Command**: `.venv/bin/pytest tests/ -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Output Summary**:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 153 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ...................                               [ 22%]
tests/test_asr_decoding.py ......................................        [ 47%]
tests/test_asr_dsp.py .............................................      [ 77%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_web.py ..................                                 [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 153 passed, 2 warnings in 189.21s (0:03:09) ==================
```
- **Result**: **153 passed, 0 failed, 0 skipped, 0 xfailed** (100% pass).

### Command 2: Git Status & Diff Check
- **Command**: `git diff --stat && echo "---" && git status --short`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Output**:
```text
---
?? .agents/
?? .gitignore
?? PROJECT.md
?? TEST_INFRA.md
?? TEST_READY.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/
```

---

## Final Verdict
**APPROVE**
