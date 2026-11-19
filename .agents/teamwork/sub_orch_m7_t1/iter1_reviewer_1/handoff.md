# Primary Reviewer Handoff — M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`, Iteration 1)

## 1. Review Scope & Checklist

Audited Worker Iteration 1 (`/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t1/iter1_worker/handoff.md`) against:
- `ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- `PROJECT.md § Interface Contracts`
- `sub_orch_m7_t1/SCOPE.md`

### Verification Results
1. **Independent Full Unit + Tier 1 E2E Suite**: **PASS** — 256 passed (153 unit + 103 Tier 1 E2E), 0 failed, 0 skipped, 0 xfailed (exit code `0`).
2. **Code Inspection of Worker Edits**:
   - `asr/synth_data.py` (`generate_dataset`, lines 709, 786):
     - `root = Path(out_dir).resolve()` guarantees an absolute path even when callers pass a relative `out_dir`.
     - `"audio_path": str(abs_wav)` emits resolved absolute WAV paths in `train.jsonl` and `val.jsonl`.
     - Preserves JSONL schema (`audio_path`, `text`, `duration`, `speaker`, `source`, `moras`), determinism, and `dict[str, Path]` return value (`{"train", "val"}`).
   - `asr/dataset.py` (`build_manifest_from_wav_dir`, line 353; `_resolve_audio_path`, lines 77–86):
     - `stored_audio_path = str(wav_path.resolve())` emits resolved absolute WAV paths cleanly; removed unused `out_dir_resolved`.
     - `_resolve_audio_path()` remains unchanged, preserving full backward compatibility for both absolute and manifest-relative paths in `ASRManifestDataset`.
   - `tests/test_asr_data.py` (`test_generate_dataset_fast_and_determinism`, lines 354–377; `test_build_manifest_from_wav_dir_dict_and_files`, line 583):
     - Verifies `Path(rec["audio_path"]).is_absolute()` and `.is_file()` for both `generate_dataset` and `build_manifest_from_wav_dir`.
     - Verifies cross-directory determinism by normalizing `audio_path` relative to each resolved dataset root and checking byte-identical WAV contents.
     - Retains relative-path and error-handling tests for `ASRManifestDataset`.
3. **`tests_e2e/` Integrity**: **VERIFIED UNMODIFIED** — All files under `tests_e2e/` retain their original timestamps (`2026-11-19 03:13–03:25 UTC`), prior to Worker edits (`05:18 UTC`). Zero tests weakened, skipped, or modified.
4. **Existing `tsukinami` TTS Files**: **VERIFIED UNTOUCHED** — `git diff --name-only` returned empty output (exit code `0`).
5. **Contract Compliance**: **COMPLIANT** — Strictly matches `PROJECT.md § Interface Contracts` (§ 4 Speech Data & Dataset) and satisfies `tests_e2e/test_tier1_features.py` (`assert Path(row["audio_path"]).is_file()`).

---

## 2. Independent Verification Commands & Exact Outputs

### Command 1: Full Unit + Tier 1 E2E Suite
- **Command**: `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Exact Output**:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 256 items

tests/test_asr_cli.py ................                                   [  6%]
tests/test_asr_data.py ...................                               [ 13%]
tests/test_asr_decoding.py ......................................        [ 28%]
tests/test_asr_dsp.py .............................................      [ 46%]
tests/test_asr_models.py .................                               [ 52%]
tests/test_asr_web.py ..................                                 [ 59%]
tests_e2e/test_tier1_features.py ....................................... [ 75%]
................................................................         [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 256 passed, 2 warnings in 245.24s (0:04:05) ==================
```

### Command 2: Git Diff & Status Check
- **Command**: `git diff --name-only && echo "===GIT_STATUS===" && git status --short`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Exact Output**:
```text
===GIT_STATUS===
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

### Command 3: File Timestamps Check (`tests_e2e/` vs Edited Files)
- **Command**: `ls -la --full-time tests_e2e/ asr/synth_data.py asr/dataset.py tests/test_asr_data.py`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Exact Output**:
```text
-rw-r--r-- 1 antigravity antigravity 13132 2026-11-19 05:18:59.487300253 +0000 asr/dataset.py
-rw-r--r-- 1 antigravity antigravity 27954 2026-11-19 05:18:53.597302471 +0000 asr/synth_data.py
-rw-r--r-- 1 antigravity antigravity 26398 2026-11-19 05:18:59.562300225 +0000 tests/test_asr_data.py

tests_e2e/:
total 180
drwxr-xr-x  3 antigravity antigravity   171 2026-11-19 03:18:03.477064208 +0000 .
drwxr-xr-x 11 antigravity antigravity  4096 2026-11-19 03:30:06.891011796 +0000 ..
drwxrwxrwx  2 antigravity antigravity  4096 2026-11-19 03:27:52.391021550 +0000 __pycache__
-rw-r--r--  1 antigravity antigravity 12370 2026-11-19 03:25:35.089031521 +0000 conftest.py
-rw-r--r--  1 antigravity antigravity 65999 2026-11-19 03:13:59.624081849 +0000 test_tier1_features.py
-rw-r--r--  1 antigravity antigravity 45150 2026-11-19 03:25:36.267031439 +0000 test_tier2_boundaries.py
-rw-r--r--  1 antigravity antigravity 20242 2026-11-19 03:25:38.150031309 +0000 test_tier3_combinations.py
-rw-r--r--  1 antigravity antigravity 18386 2026-11-19 03:17:17.507067527 +0000 test_tier4_scenarios.py
```

---

## 3. Verdict

**APPROVE**
