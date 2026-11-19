# Forensic Audit Report — Milestone M2 (Iteration 2)

- **Audit Classification**: Intermediate Milestone Audit (Milestone M2 — Built-in Speech Data & Corpus Pipeline, Iteration 2)
- **Audited Scope**:
  - `asr/synth_data.py`
  - `asr/dataset.py`
  - `tests/test_asr_data.py`
- **Repository**: `/home/antigravity/poidowl/tsukinami`

---

## 1. Independent Test Execution

Command executed:
```bash
.venv/bin/pytest tests/test_asr_data.py -v
```
Result:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 19 items

tests/test_asr_data.py ...................                               [100%]

======================== 19 passed in 62.20s (0:01:02) =========================
```
- **Exit code**: `0`
- **Passed**: `19/19`, **Skipped**: `0`, **Failed**: `0`.

---

## 2. Working Tree & Scope Integrity

Checked via `git status --short`, `git diff --stat`, and `ls -la --full-time asr/ tests/ tests_e2e/`:
- `git diff --stat`: empty (0 tracked existing TTS files modified; `carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, HTML demos are completely untouched).
- `git status --short`: only expected untracked project paths (`.agents/`, `.gitignore`, `PROJECT.md`, `TEST_INFRA.md`, `TEST_READY.md`, `asr/`, `pyproject.toml`, `tests/`, `tests_e2e/`).
- File modification timestamps confirm only the 3 M2-owned files (`asr/synth_data.py`, `asr/dataset.py`, `tests/test_asr_data.py`, modified 03:38:11–03:38:18 UTC) were edited during Iteration 2; M1 files (`03:10–03:13`), M4 files (`03:26–03:28`), and `tests_e2e/` (`03:13–03:25`) were not touched.

---

## 3. Forensic Code & Anti-Cheating Inspection

### 3.1 `asr/synth_data.py`
- **Genuine Tier 1 Formant Synthesis (`synthesize_fast_kotoba`)**:
  - Directly invokes `kotoba.tracks_from_kana(cleaned_text, params=params)` (line 389) with no lookup tables or shortcuts.
  - Builds a sample-level phase-continuous Gaussian glottal pulse train with lip-radiation pre-emphasis and aspiration/unvoiced noise (lines 403–433), applies frame-domain parallel Lorentzian formant resonators for `F1`/`F2`/`F3` with `G1`/`G2`/`G3` and bandwidths `B1`/`B2`/`B3` (lines 436–459), adds fricative/stop-burst noise bands from `tr["bands"]` (lines 462–475), performs 50% overlap-add synthesis (lines 478–484), applies loudness envelope with silence gating (lines 487–492), and optionally adds white noise via `asr.audio.apply_corruption` (lines 503–515).
  - Iteration 2 fix verified: `_sanitize_whitespace` (`" ".join(text.split())`, line 274) runs before `kotoba.split_moras()` / `kotoba.tracks_from_kana()`, returning `(np.zeros(0, dtype=np.float32), [])` on whitespace/control-only strings like `"   \t\n  "` (lines 358–360).
- **Genuine Tier 2 Tsukinami Wrapper (`synthesize_tsukinami`)**:
  - Directly invokes `yomu.build_carve_rc(sanitized_text, prm)` (line 597), `carve.make(rc)` (line 601), `yomu.boost_low_pitch_rms(samples, prm["hz"])` (line 602), and resamples `carve.SR` (44.1 kHz) to `sr` (lines 605–606).
  - Deep-copies `yomu.PRESETS` and `overrides` so global state and caller dicts are never mutated.
  - Iteration 2 speakable-mora guard verified: `if not any(m not in ("ッ", "、") for m in ms): raise ValueError(...)` (lines 553–554), preventing unhandled `IndexError` on `"ッ"` and rejecting `"   \t\n  "` / `"、、、"`.
  - Iteration 2 cache consistency fix verified: atomic write via temp files + `os.replace` (lines 614–628), followed by `wav, _ = load_wav(wav_cache_path, target_sr=sr)` (line 636) so cold cache writes and warm cache hits return bit-identical `float32` waveforms. No fake/in-memory cache shortcuts.
- **Dataset Generator (`generate_dataset`)**:
  - Supports `fast`, `tsukinami`, and `mixed` engines with deterministic seeding, disjoint `TRAIN_CORPUS` (120 phrases) / `VAL_CORPUS` (30 phrases), and exact required JSONL schema.
  - Minor cleanup verified: line 172 uses literal `"キップヲカッテ、デパチカヘイク"`.

### 3.2 `asr/dataset.py`
- **Genuine PyTorch Dataset & Collation**:
  - `ASRManifestDataset` loads audio via `asr.audio.load_wav`, extracts log-Mel features via `asr.features.extract_log_mel`, applies `spec_augment` when `augment=True`, and encodes text via `tokenizer.encode`.
  - `collate_asr_batch` validates tensor shapes/dimensions and zero/blank-pads `feats` (`[B, T_max, F]`, `float32`) and `targets` (`[B, L_max]`, `long`), returning `feat_lengths`, `target_lengths`, and `texts`.
- **Tier 3 Manifest Builder (`build_manifest_from_wav_dir`)**:
  - Iteration 2 fix verified in `_load_transcript_map` (lines 250–253, 277–280): explicitly rejects non-`str` transcript values in both `Mapping` and `.json` inputs with `ValueError` instead of coercing via `str(v)`.

### 3.3 `tests/test_asr_data.py`
- All 19 tests are genuine, non-trivial, and unweakened (no skipped tests, no tautological assertions, no mocked synthesis in functional/benchmark tests).
- Regression assertions for all Iteration 2 fixes are present and verified:
  - `synthesize_fast_kotoba("   \t\n  ")` empty output & `[]` moras (lines 210–211).
  - `synthesize_tsukinami("   \t\n  ")` and `synthesize_tsukinami("ッ")` raising `ValueError` (lines 291–294).
  - `test_tsukinami_disk_cache_hit_and_miss` asserting `np.array_equal(wav1, wav2)` on cold vs warm hit, plus `monkeypatch` guard on `carve.make` confirming genuine cache hit/miss behavior (lines 301–325).
  - `test_build_manifest_from_wav_dir_errors` rejecting `None` in dict and JSON `null` with `ValueError` (lines 616–622).

---

## 4. Verdict

No integrity violations, shortcuts, weakened tests, or unauthorized file modifications were found.

VERDICT: CLEAN
