# Secondary Reviewer Handoff — M7 Phase 1 Tier 2 E2E (`sub_orch_m7_t2`, Iteration 1)

## Verdict: **APPROVE**

---

## 1. Independent Test Execution

- **Command**: `.venv/bin/pytest tests/ -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Result**: **154 passed, 0 failed** (`2 warnings`, `178.99s`) — includes the 153 baseline unit tests plus the 1 newly added regression test (`tests/test_asr_data.py::test_build_manifest_from_wav_dir_empty_and_unmatched`).
- **Breakdown**:
  - `tests/test_asr_cli.py`: 16 passed
  - `tests/test_asr_data.py`: 20 passed
  - `tests/test_asr_decoding.py`: 38 passed
  - `tests/test_asr_dsp.py`: 45 passed
  - `tests/test_asr_models.py`: 17 passed
  - `tests/test_asr_web.py`: 18 passed
- Did **not** run `tests_e2e/` (per Secondary Reviewer instructions to avoid CPU contention with Primary Reviewer).

---

## 2. Code Review Findings

### A. Contract Compliance (`PROJECT.md § Interface Contracts`, line 160)
- `PROJECT.md` line 160 specifies:
  `build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path) -> Path`
- `asr/dataset.py:306-370` matches this signature with optional keyword-only defaults (`speaker`, `source`, `target_sr`) and returns `Path` via `write_manifest(records, out_path)`.
- The fix at `asr/dataset.py:366`:
  ```python
  if not records and (wav_files or tmap):
      raise ValueError(f"No matching WAV files found in {wav_root}")
  ```
  is minimal, clean, and fully compliant with the contract and `tests_e2e/test_tier2_boundaries.py::TestTier2Feature09DatasetBoundaries::test_build_manifest_from_wav_dir_empty_dir`.

### B. Edge Case Analysis (`build_manifest_from_wav_dir` & `write_manifest`)
1. **Empty `wav_dir` + empty `transcript_map` (`{}`)**:
   - `wav_files == []`, `tmap == {}`, `records == []`.
   - `(wav_files or tmap)` evaluates falsy, so no `ValueError` is raised.
   - Calls `write_manifest([], out_path)`, which creates parent directories (`out.parent.mkdir(parents=True, exist_ok=True)`), writes a 0-byte UTF-8 file, and returns `Path(out_path)`.
   - `load_manifest(out_path)` cleanly returns `[]`.
   - Passing the resulting empty manifest to `ASRManifestDataset` still raises `ValueError("Manifest contains no records: ...")` (`asr/dataset.py:121-122`), preserving training-time safety.
2. **Empty `wav_dir` + non-empty `transcript_map`**:
   - `tmap` is truthy → raises `ValueError("No matching WAV files found in ...")`.
3. **Non-empty `wav_dir` + empty `transcript_map` (`{}`)**:
   - `wav_files` is truthy → raises `ValueError("No matching WAV files found in ...")`.
4. **Non-empty `wav_dir` + unmatched `transcript_map`**:
   - `wav_files` and `tmap` are truthy, `records == []` → raises `ValueError("No matching WAV files found in ...")`.
5. **JSON / TSV / JSUT transcript file inputs**:
   - `_load_transcript_map` (`asr/dataset.py:246-303`) returns `{}` for an empty JSON object (`{}`) or an empty/whitespace-only TSV/TXT file, and a non-empty `dict[str, str]` otherwise.
   - Therefore, file-backed empty maps behave consistently with dict `{}`: empty `wav_dir` + empty file → writes empty JSONL manifest; non-empty `wav_dir` + empty file → raises `ValueError`; empty `wav_dir` + non-empty file → raises `ValueError`.
6. **Non-WAV files in `wav_dir`**:
   - `wav_files` filters strictly on `p.is_file() and p.suffix.lower() == ".wav"`. A directory containing only non-WAV files with an empty map is treated as having no WAV files and writes an empty manifest; with a non-empty map it raises `ValueError`.

### C. Regression Test Quality & Scope Adherence
- `tests/test_asr_data.py:642-668` (`test_build_manifest_from_wav_dir_empty_and_unmatched`) clearly and concisely covers all four matrix combinations (empty+empty, empty+non-empty, non-empty+empty, non-empty+unmatched) and verifies `isinstance(out_empty, Path)`, `out_empty.is_file()`, and `load_manifest(out_empty) == []`.
- Scope check via `git status --short && git diff`:
  - Zero tracked `tsukinami` TTS files modified (`git diff` is empty).
  - Zero `tests_e2e/` files modified.
  - Changes are strictly confined to `asr/dataset.py` and `tests/test_asr_data.py` within `SCOPE.md`.
- No defects, regressions, or scope violations found.
