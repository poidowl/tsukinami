# Explorer 1 Handoff — Tier 1 E2E Run & Failure Diagnosis (`sub_orch_m7_t1`)

## 1. Execution Summary
- **Command**: `.venv/bin/pytest tests_e2e/test_tier1_features.py -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `1`
- **Results**: **102 passed, 1 failed, 0 skipped, 0 errors** (103 collected)
- **Warnings**: 1 (`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` from `fastapi/testclient.py:1`)
- **Wall Time**: `41.83s`

---

## 2. Failure Analysis

### Failing Test
`tests_e2e/test_tier1_features.py::TestTier1Feature09Dataset::test_generate_dataset_fast_creates_manifests_and_wavs`

### Exact Traceback
```text
self = <test_tier1_features.TestTier1Feature09Dataset object at 0x79e78c336210>
tmp_path = PosixPath('/tmp/pytest-of-antigravity/pytest-6/test_generate_dataset_fast_cre0')

    def test_generate_dataset_fast_creates_manifests_and_wavs(self, tmp_path: Path):
        from asr.synth_data import generate_dataset
    
        paths = generate_dataset(tmp_path, num_train=6, num_val=2, engine="fast", seed=42)
        assert {"train", "val"} <= set(paths.keys())
        train_lines = [ln for ln in Path(paths["train"]).read_text(encoding="utf-8").splitlines() if ln.strip()]
        val_lines = [ln for ln in Path(paths["val"]).read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(train_lines) == 6
        assert len(val_lines) == 2
        for ln in train_lines + val_lines:
            row = json.loads(ln)
>           assert Path(row["audio_path"]).is_file()
E           AssertionError: assert False
E            +  where False = is_file()
E            +    where is_file = PosixPath('audio/train/train_00000.wav').is_file
E            +      where PosixPath('audio/train/train_00000.wav') = Path('audio/train/train_00000.wav')

tests_e2e/test_tier1_features.py:656: AssertionError
```

### Root Cause
In `asr/synth_data.py`, `generate_dataset()` writes a manifest-relative POSIX path into `"audio_path"` instead of the resolved absolute filesystem path:
- `asr/synth_data.py:709`: `root = Path(out_dir)`
- `asr/synth_data.py:742-743`:
  ```python
  rel_wav = Path("audio") / split_name / f"{split_name}_{i:05d}.wav"
  abs_wav = root / rel_wav
  ```
- `asr/synth_data.py:786`:
  ```python
  "audio_path": rel_wav.as_posix(),
  ```

Similarly, `asr/dataset.py:354-358` (`build_manifest_from_wav_dir`) tries `wav_resolved.relative_to(out_dir_resolved).as_posix()` before falling back to `str(wav_resolved)`.

### Contract Check (`PROJECT.md § Interface Contracts`)
- `PROJECT.md` lines 156–158 specify:
  - `generate_dataset(out_dir, ...)` writes `train.jsonl`, `val.jsonl`, and WAV files under `out_dir`; returns `{"train": ..., "val": ...}`.
  - JSONL manifest schema: `{"audio_path": "...", "text": "...", "duration": ..., "speaker": "...", "source": "...", "moras": [...]}`.
- `PROJECT.md` does **not** require `audio_path` to be relative to the manifest directory.
- Crucially, **three** E2E tiers directly consume `row["audio_path"]` as a standalone filesystem path without prepending `manifest_path.parent`:
  1. `tests_e2e/test_tier1_features.py:656`: `assert Path(row["audio_path"]).is_file()`
  2. `tests_e2e/test_tier3_combinations.py:399`: `run_cli(["transcribe", "--checkpoint", str(best_pt), "--wav", first_val["audio_path"], ...])`
  3. `tests_e2e/test_tier4_scenarios.py:338`: `wavs = [load_wav(r["audio_path"], target_sr=16000)[0] for r in val_rows]`
- Meanwhile, `ASRManifestDataset._resolve_audio_path()` (`asr/dataset.py:77-86`) and `_resolve_manifest_audio_path()` (`asr/__main__.py:46-55`) both handle absolute paths directly (`if p.is_absolute(): return p`) while still preserving full backward compatibility with relative paths in user-authored manifests.

Therefore, this is a **genuine `asr/` fix** — `tests_e2e/test_tier1_features.py` does **not** contradict `PROJECT.md` and should remain **untouched**.

---

## 3. Concrete Fix Plan (File-by-File, Line-by-Line)

### 1. `asr/synth_data.py`
- **Line 709**: Change:
  ```python
  root = Path(out_dir)
  ```
  to:
  ```python
  root = Path(out_dir).resolve()
  ```
  (Ensures `abs_wav` is always an absolute path even when callers pass a relative `out_dir`.)
- **Line 786**: Change:
  ```python
  "audio_path": rel_wav.as_posix(),
  ```
  to:
  ```python
  "audio_path": str(abs_wav),
  ```

### 2. `asr/dataset.py` (Preventive Consistency Fix)
- **Lines 354–358** in `build_manifest_from_wav_dir`:
  Currently:
  ```python
        wav_resolved = wav_path.resolve()
        try:
            stored_audio_path = wav_resolved.relative_to(out_dir_resolved).as_posix()
        except ValueError:
            stored_audio_path = str(wav_resolved)
  ```
  Change to:
  ```python
        stored_audio_path = str(wav_path.resolve())
  ```
  (Also remove the now-unused `out_dir_resolved = out_path.resolve().parent` at line 329.)
  This ensures manifests created by `build_manifest_from_wav_dir` also have directly usable `Path(row["audio_path"]).is_file() == True`, consistent with `generate_dataset`, while `ASRManifestDataset._resolve_audio_path()` continues to accept both relative and absolute paths.

### 3. `tests/test_asr_data.py` (Unit Test Update & Regression Check)
Changing `generate_dataset` to emit resolved absolute `audio_path` affects lines 354–364 of `tests/test_asr_data.py::test_generate_dataset_fast_and_determinism`:
- Currently lines 354–364:
  ```python
        wav_path = out1["train"].parent / rec["audio_path"]
        wav, sr = load_wav(wav_path, target_sr=16000)
        assert sr == 16000
        assert abs(rec["duration"] - (wav.size / 16000.0)) < 0.01

    # Determinism across runs with same seed
    assert out1["train"].read_text(encoding="utf-8") == out2["train"].read_text(encoding="utf-8")
    assert out1["val"].read_text(encoding="utf-8") == out2["val"].read_text(encoding="utf-8")
    wav1_bytes = (tmp_path / "ds1" / train_recs1[0]["audio_path"]).read_bytes()
    wav2_bytes = (tmp_path / "ds2" / train_recs1[0]["audio_path"]).read_bytes()
    assert wav1_bytes == wav2_bytes
  ```
- Because `out1` is in `tmp_path / "ds1"` and `out2` is in `tmp_path / "ds2"`, raw text equality on `train.jsonl` / `val.jsonl` would fail due to the different parent directory prefixes, and line 363 would read `ds1`'s file twice if `train_recs1[0]["audio_path"]` is absolute.
- Update lines 354–364 to:
  1. Assert `Path(rec["audio_path"]).is_absolute()` and `Path(rec["audio_path"]).is_file()` (direct regression test for the Tier 1/3/4 requirement).
  2. Load `train_recs2 = load_manifest(out2["train"])` and `val_recs2 = load_manifest(out2["val"])`.
  3. Normalize `audio_path` relative to `ds1` vs `ds2` when comparing determinism across the two directories (verifying every field including relative layout, text, duration, speaker, source, and moras is identical).
  4. Compare `Path(train_recs1[0]["audio_path"]).read_bytes() == Path(train_recs2[0]["audio_path"]).read_bytes()` (and assert `train_recs1[0]["audio_path"] != train_recs2[0]["audio_path"]`).
- Also in `test_build_manifest_from_wav_dir_dict_and_files` (lines 564–570), add `assert all(Path(r["audio_path"]).is_file() for r in recs)` as a regression check.

---

## 4. Verification Plan for Implementer
1. Apply the edits to `asr/synth_data.py`, `asr/dataset.py`, and `tests/test_asr_data.py`.
2. Run `.venv/bin/pytest tests/ -v` (confirm all 153 unit tests pass).
3. Run `.venv/bin/pytest tests_e2e/test_tier1_features.py -v` (confirm all 103 Tier 1 E2E tests pass with 0 failures, 0 skips).
4. Verify `git diff` touches only `asr/` and `tests/` (zero changes to existing TTS files or `tests_e2e/`).
