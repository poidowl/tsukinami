# Explorer 1 Handoff — M7 Phase 1 Tier 2 E2E (Iteration 1)

## 1. Executive Summary
- **Command**: `.venv/bin/pytest tests_e2e/test_tier2_boundaries.py -v --tb=short` (cwd: `/home/antigravity/poidowl/tsukinami`)
- **Exact Pytest Summary Line**:
  `=================== 1 failed, 97 passed, 1 warning in 29.18s ===================`
  - Passed: `97`
  - Failed: `1`
  - Errors: `0`
  - Skipped: `0`
  - Warnings: `1` (third-party `StarletteDeprecationWarning` from `fastapi.testclient`)
  - Elapsed: `29.18s`
- **Failing Test**:
  `tests_e2e/test_tier2_boundaries.py::TestTier2Feature09DatasetBoundaries::test_build_manifest_from_wav_dir_empty_dir`
- **Root Cause**: `asr/dataset.py:366-367` unconditionally raises `ValueError("No matching WAV files found in ...")` whenever `records` is empty — even when both `wav_dir` has no WAV files and `transcript_map` is empty (`{}`).
- **Contract Alignment**: `PROJECT.md § Interface Contracts` (line 160) specifies `build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path) -> Path` without requiring a `ValueError` on an empty directory + empty transcript map. Therefore the E2E test is valid and MUST NOT be modified.
- **Recommended Fix**: 1-line change in `asr/dataset.py:366` (`if not records and tmap:`) + targeted unit regression tests in `tests/test_asr_data.py`.

---

## 2. Working Tree & Git Status Verification
Ran `git status --short` and `git diff --stat` in `/home/antigravity/poidowl/tsukinami`:
- `git diff --stat`: **(empty — 0 tracked files modified)**. All existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) are completely untouched.
- Untracked paths: `.agents/`, `.gitignore`, `PROJECT.md`, `TEST_INFRA.md`, `TEST_READY.md`, `asr/`, `pyproject.toml`, `tests/`, `tests_e2e/`.

---

## 3. Failure Analysis

### Failure 1 of 1: `TestTier2Feature09DatasetBoundaries::test_build_manifest_from_wav_dir_empty_dir`

#### Full Traceback
```text
_ TestTier2Feature09DatasetBoundaries.test_build_manifest_from_wav_dir_empty_dir _
tests_e2e/test_tier2_boundaries.py:514: in test_build_manifest_from_wav_dir_empty_dir
    out = build_manifest_from_wav_dir(empty_dir, {}, tmp_path / "empty.jsonl")
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
asr/dataset.py:367: in build_manifest_from_wav_dir
    raise ValueError(f"No matching WAV files found in {wav_root}")
E   ValueError: No matching WAV files found in /tmp/pytest-of-antigravity/pytest-11/test_build_manifest_from_wav_d0/empty_wavs
```

#### Test Inspection (`tests_e2e/test_tier2_boundaries.py:509-517`)
```python
    def test_build_manifest_from_wav_dir_empty_dir(self, tmp_path: Path):
        from asr.dataset import build_manifest_from_wav_dir

        empty_dir = tmp_path / "empty_wavs"
        empty_dir.mkdir()
        out = build_manifest_from_wav_dir(empty_dir, {}, tmp_path / "empty.jsonl")
        assert Path(out).is_file()
        lines = [ln for ln in Path(out).read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 0
```

#### Implementation Inspection (`asr/dataset.py:306-370`)
```python
def build_manifest_from_wav_dir(
    wav_dir: str | Path,
    transcript_map: Mapping[str, str] | str | Path,
    out_manifest_path: str | Path,
    *,
    speaker: str = "custom",
    source: str = "wav_dir",
    target_sr: int = 16000,
) -> Path:
    ...
    if not records:
        raise ValueError(f"No matching WAV files found in {wav_root}")

    return write_manifest(records, out_path)
```

#### Cross-Check Against `PROJECT.md § Interface Contracts`
- `PROJECT.md:160`:
  > `- build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path) -> Path (Tier 3 real-audio helper).`
- No clause in `PROJECT.md` requires raising `ValueError` when building a manifest from an empty directory with an empty `transcript_map`. Writing an empty JSONL file and returning its `Path` is completely contract-compliant and natural for the empty-input boundary case.
- Existing unit test `tests/test_asr_data.py:624-625`:
  ```python
  with pytest.raises(ValueError):
      build_manifest_from_wav_dir(wav_dir, {"unmatched": "ア"}, tmp_path / "m.jsonl")
  ```
  Notice that in this existing unit test, `transcript_map` is **non-empty** (`{"unmatched": "ア"}`) and matches zero WAV files in `wav_dir`.

#### Root Cause
`asr/dataset.py:366` checks `if not records:` without distinguishing between:
1. Caller supplied a non-empty `transcript_map` (`tmap`) and zero WAV files matched (likely a key-format mismatch or wrong directory → should raise `ValueError`).
2. Caller supplied an empty `transcript_map` (`tmap == {}`), e.g., an empty WAV directory with `{}` → producing 0 records is expected and should write an empty manifest file via `write_manifest([], out_path)`.

---

## 4. Minimal Fix Plan

### Change 1: `asr/dataset.py` (`build_manifest_from_wav_dir`, line 366)
Change:
```python
    if not records:
        raise ValueError(f"No matching WAV files found in {wav_root}")
```
To:
```python
    if not records and tmap:
        raise ValueError(f"No matching WAV files found in {wav_root}")
```

**Edge-case verification of this change**:
| `wav_files` | `tmap` | `records` | Result |
|---|---|---|---|
| `[]` (empty dir) | `{}` | `[]` | Writes empty JSONL file (0 lines), returns `Path(out_path)` (fixes Tier 2 E2E test) |
| `[good.wav]` | `{}` | `[]` | Writes empty JSONL file (0 lines), returns `Path(out_path)` |
| `[good.wav]` | `{"unmatched": "ア"}` | `[]` | Raises `ValueError` (preserves `tests/test_asr_data.py:624-625`) |
| `[]` (empty dir) | `{"a.wav": "ア"}` | `[]` | Raises `ValueError` (catches missing WAVs when transcripts were provided) |

- `write_manifest([], out_path)` (`asr/dataset.py:64-74`) already creates parent directories, creates an empty UTF-8 file, and returns `Path(out_path)`.
- `load_manifest(empty_jsonl)` (`asr/dataset.py:28-61`) already returns `[]`.
- `ASRManifestDataset(empty_jsonl)` (`asr/dataset.py:120-122`) continues to raise `ValueError("Manifest contains no records: ...")`.

### Change 2: `tests/test_asr_data.py` (Unit Regression Tests)
Add regression assertions in `tests/test_asr_data.py` (e.g., in `test_build_manifest_from_wav_dir_dict_and_files` or a dedicated `test_build_manifest_from_wav_dir_empty_dir_and_unmatched`):
1. Empty `wav_dir` + `{}` → returns `Path`, file exists, `load_manifest(out) == []`.
2. Non-empty `wav_dir` + `{}` → returns `Path`, file exists, `load_manifest(out) == []`.
3. Empty `wav_dir` + `{"a.wav": "ア"}` → raises `ValueError`.
4. Existing `wav_dir` + `{"unmatched": "ア"}` → continues to raise `ValueError`.

### Files NOT to Modify
- `tests_e2e/test_tier2_boundaries.py` (untouched)
- All other `tests_e2e/` files (untouched)
- All existing `tsukinami` TTS files (untouched)
