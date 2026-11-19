# Forensic Audit Report — Intermediate Milestone Audit (M7 Phase 1 — Tier 2 E2E, Iteration 1)

- **Audit Label**: Intermediate Milestone Audit (M7 Phase 1 — Tier 2 E2E)
- **Auditor**: `iter1_auditor`
- **Declared Sub-Scope Paths**:
  - `asr/`
  - `tests/`
  - `tests_e2e/conftest.py`
  - `tests_e2e/test_tier1_features.py`
  - `tests_e2e/test_tier2_boundaries.py`
- **Verdict**: **CLEAN**

---

## 1. Executive Summary

Independent forensic inspection of the M7 Phase 1 Tier 2 E2E iteration 1 changes confirms complete integrity:
1. The fix in `asr/dataset.py` (`build_manifest_from_wav_dir`, line 366) is genuine, general, and free of any hardcoding, test-path special-casing, or dummy/facade behavior.
2. The new unit regression test in `tests/test_asr_data.py` (`test_build_manifest_from_wav_dir_empty_and_unmatched`, lines 642–668) rigorously verifies both the valid empty-input boundary and all three unmatched/non-empty `ValueError` cases.
3. Zero `skip`, `xfail`, `pytest.skip`, `pytest.xfail`, weakened assertions, or unauthorized edits exist in `tests/`, `tests_e2e/conftest.py`, `tests_e2e/test_tier1_features.py`, or `tests_e2e/test_tier2_boundaries.py`. All `tests_e2e/` files remain untouched since initial E2E suite authoring (`2026-11-19 03:13–03:25`).
4. Zero existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) were modified (`git diff --stat` and `git ls-files -m -d` are empty).
5. Zero stray untracked files or leftover probes exist in the repository.
6. Target-scoped unit test suite (`.venv/bin/pytest tests/ -v`) passed **154/154** (`exit 0`).

---

## 2. Forensic Checks & Evidence

### 2.1 Implementation Integrity (`asr/dataset.py`)
- Inspected `build_manifest_from_wav_dir` (`asr/dataset.py:310-370`) and `write_manifest`/`load_manifest` (`asr/dataset.py:28-75`).
- Line 366 changed from `if not records:` to:
  ```python
  if not records and (wav_files or tmap):
      raise ValueError(f"No matching WAV files found in {wav_root}")

  return write_manifest(records, out_path)
  ```
- **Assessment**: Clean, semantically sound boundary logic. When both `wav_files` and `tmap` are empty, `write_manifest([], out_path)` legitimately creates an empty UTF-8 JSONL file and returns `out_path`. Whenever either `wav_files` or `tmap` is non-empty and no matches occur, `ValueError` is still raised. No test-name/path hardcoding or shortcuts.

### 2.2 Unit Test Integrity (`tests/test_asr_data.py`)
- Inspected `test_build_manifest_from_wav_dir_empty_and_unmatched` (`tests/test_asr_data.py:642-668`).
- Covers all 4 combinations:
  1. Empty `wav_dir` + `{}` -> writes empty JSONL file and `load_manifest(out_empty) == []`.
  2. Empty `wav_dir` + `{"a.wav": "ア"}` -> raises `ValueError`.
  3. Non-empty `wav_dir` + `{}` -> raises `ValueError`.
  4. Non-empty `wav_dir` + `{"unmatched": "ア"}` -> raises `ValueError`.
- Existing error-handling assertions (`tests/test_asr_data.py:620-640`) remain intact and unweakened.

### 2.3 Anti-Tampering & Skip/Xfail Scan (`tests/` & `tests_e2e/`)
- Command: `grep -rnE "skip|xfail|pytest\.skip|pytest\.xfail|mark\.skip|mark\.xfail" tests/ tests_e2e/conftest.py tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py`
- Output (comments/docstrings only; **0 test skips or xfails**):
  ```text
  tests/test_asr_dsp.py:551:    # Empty & unknown chars skipped cleanly
  tests/test_asr_decoding.py:457:    # Distinct consecutive tokens with T == 2 (skip+2 transition without blank)
  tests_e2e/conftest.py:6:against missing or broken ``asr/`` modules fails genuinely (no skipped stubs,
  ```
- File modification timestamps (`find asr tests tests_e2e -type f ! -path '*/__pycache__/*' -printf '%T+ %p\n' | sort -r`):
  - Only `tests/test_asr_data.py` (`2026-11-19+05:36:54`) and `asr/dataset.py` (`2026-11-19+05:36:53`) were modified during Iteration 1.
  - All `tests_e2e/` files remain untouched (`2026-11-19+03:13:59` to `03:25:38`).
- Inspected `tests_e2e/test_tier2_boundaries.py:509-518` (`test_build_manifest_from_wav_dir_empty_dir`): intact and unweakened.

### 2.4 Repository Cleanliness & Existing TTS Protection
- Command: `git status --short && echo "=== DIFF STAT ===" && git diff --stat && echo "=== TRACKED FILES CHECK ===" && git ls-files -m -d`
- Verbatim Output:
  ```text
  ?? .agents/
  ?? .gitignore
  ?? PROJECT.md
  ?? TEST_INFRA.md
  ?? TEST_READY.md
  ?? asr/
  ?? pyproject.toml
  ?? tests/
  ?? tests_e2e/
  === DIFF STAT ===
  === TRACKED FILES CHECK ===
  ```
- Repository file listing (`find . -maxdepth 3 ...`) confirmed zero stray files, temporary scripts, or leftover probes.

### 2.5 Target-Scoped Test Execution
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Command**: `.venv/bin/pytest tests/ -v` (Note: `tests_e2e/` intentionally NOT executed to avoid concurrency with Primary Reviewer)
- **Exit Code**: `0`
- **Summary**: `154 passed, 2 warnings in 175.71s (0:02:55)`
  - `tests/test_asr_cli.py`: 16 passed
  - `tests/test_asr_data.py`: 20 passed
  - `tests/test_asr_decoding.py`: 38 passed
  - `tests/test_asr_dsp.py`: 45 passed
  - `tests/test_asr_models.py`: 17 passed
  - `tests/test_asr_web.py`: 18 passed

---

## 3. Final Verdict

**CLEAN** — No integrity violations, cheating, test weakening, or unauthorized modifications detected.
