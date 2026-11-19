# Handoff — Final Milestone M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`)

## Outcome: **PASS** (Iteration 1 Gate Cleared)

- **Tier 1 E2E Suite**: `.venv/bin/pytest tests_e2e/test_tier1_features.py -v` — **103/103 passed** (100% PASS, 0 failed, 0 skipped, 0 xfailed)
- **M1–M6 Unit Suite**: `.venv/bin/pytest tests/ -v` — **153/153 passed** (100% PASS, 0 failed, 0 skipped, 0 xfailed)
- **Combined Run (Primary Reviewer Independent Verification)**: `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py -v` — **256 passed, 0 failed, 0 skipped, 0 errors** (exit code `0`)
- **`tests_e2e/` Modified**: **None** (0 edits; all 4 E2E test files and `conftest.py` untouched)
- **Existing `tsukinami` TTS Files Modified**: **None** (`git diff --name-only` and `git diff --cached --name-only` are empty)

---

## Root Cause & Fix Summary

### Diagnosis (Iteration 1 — Step a)
- Initial Tier 1 run scored **102/103 passed**, with 1 failure:
  `tests_e2e/test_tier1_features.py::TestTier1Feature09Dataset::test_generate_dataset_fast_creates_manifests_and_wavs` (line 656: `assert Path(row["audio_path"]).is_file()`).
- Root cause: `asr/synth_data.py::generate_dataset` wrote manifest-relative `audio_path` values (`"audio/train/train_00000.wav"`) instead of resolved absolute filesystem paths. Notably, Tier 3 (`test_tier3_combinations.py:399`) and Tier 4 (`test_tier4_scenarios.py:338`) also consume `row["audio_path"]` directly as a standalone path.

### Implementation Changes (Iteration 1 — Step b)
1. **`asr/synth_data.py`** (`generate_dataset`, lines 709, 786):
   - Resolved `root = Path(out_dir).resolve()` and emitted `"audio_path": str(abs_wav)` in generated JSONL manifests.
2. **`asr/dataset.py`** (`build_manifest_from_wav_dir`, lines 328, 353):
   - Emitted `stored_audio_path = str(wav_path.resolve())` for consistency across manifest generators (removed now-unused `out_dir_resolved`).
   - Preserved `ASRManifestDataset._resolve_audio_path()` unchanged so user-authored manifests with relative `audio_path` entries remain 100% backward-compatible.
3. **`tests/test_asr_data.py`**:
   - Updated `test_generate_dataset_fast_and_determinism` to assert `Path(rec["audio_path"]).is_absolute()` and `Path(rec["audio_path"]).is_file()`, and to verify cross-directory determinism via root-normalized paths + distinct absolute paths + byte-identical WAV files across `ds1` and `ds2`.
   - Added `is_absolute()` and `is_file()` regression assertions to `test_build_manifest_from_wav_dir_dict_and_files`.

---

## Parallel Verification Wave Results (Iteration 1 — Steps c, d, e, f)

All 5 independent verifiers passed under strict AND gate (`GATE_STATUS.md`):
- **Forensic Auditor** (`iter1_auditor/handoff.md`): **CLEAN** — Intermediate milestone audit over `asr/`, `tests/`, `tests_e2e/conftest.py`, `tests_e2e/test_tier1_features.py`; 153/153 unit tests passed; 0 skips/xfails/hardcoding/weakening; clean repo and `.agents/teamwork/` hygiene.
- **Primary Reviewer** (`iter1_reviewer_1/handoff.md`): **APPROVE** — Independent run of `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py -v`: **256 passed**, 0 failed, 0 skipped.
- **Secondary Reviewer** (`iter1_reviewer_2/handoff.md`): **APPROVE** — Independent run of `.venv/bin/pytest tests/ -v`: **153 passed**; confirmed code quality and relative-path backward compatibility.
- **Challenger 1** (`iter1_challenger_1/handoff.md`): **PASS** — Isolated temp-dir probes verified relative `out_dir`, CLI `generate`, Unicode/space dirs, symlinks/broken symlinks, mixed relative+absolute backward compatibility across CWD changes, and cross-directory determinism for `fast` & `mixed`.
- **Challenger 2** (`iter1_challenger_2/handoff.md`): **PASS** — Isolated temp-dir probes verified E2E mini-pipeline, cross-CWD CLI `eval`/`transcribe`, tricky DSP/VAD/corruption/tokenizer/LM/metrics edge cases, and FastAPI routes (including 3.20 ms cached `/api/redecode`).

Ready for M7 Phase 1 — Tier 2 E2E!
