# Explorer 2 Handoff — DSP, Data & Model Boundary Analysis (Features 1–11)

- **Scope**: Static contract & boundary audit of `tests_e2e/test_tier2_boundaries.py` (Features 1–11, lines 1–674, 58 tests) against `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/`, `asr/train.py`, `tests/test_asr_data.py`, `tests/test_asr_dsp.py`, and `PROJECT.md § Interface Contracts`.
- **Mode**: Read-only (no source/test files modified; no E2E suite executed).

---

## Executive Summary

Out of **58 Tier-2 boundary tests across Features 1–11**:
- **57 tests** match their implementations and `PROJECT.md § Interface Contracts` and are expected to pass.
- **1 guaranteed failure** identified in **Feature 9 (`asr/dataset.py`)**:
  - `TestTier2Feature09DatasetBoundaries::test_build_manifest_from_wav_dir_empty_dir` (`tests_e2e/test_tier2_boundaries.py:509-517`).

---

## Confirmed Failure & Root-Cause Analysis

### Failure 1: `build_manifest_from_wav_dir` raises `ValueError` on empty directory with empty transcript map

- **Failing Test**: `tests_e2e/test_tier2_boundaries.py:509-517` (`TestTier2Feature09DatasetBoundaries::test_build_manifest_from_wav_dir_empty_dir`)
  ```python
  empty_dir = tmp_path / "empty_wavs"
  empty_dir.mkdir()
  out = build_manifest_from_wav_dir(empty_dir, {}, tmp_path / "empty.jsonl")
  assert Path(out).is_file()
  lines = [ln for ln in Path(out).read_text(encoding="utf-8").splitlines() if ln.strip()]
  assert len(lines) == 0
  ```
- **Current Implementation** (`asr/dataset.py:366-369`):
  ```python
  if not records:
      raise ValueError(f"No matching WAV files found in {wav_root}")

  return write_manifest(records, out_path)
  ```
- **Root Cause**: `build_manifest_from_wav_dir` unconditionally raises `ValueError` whenever `records` is empty, conflating two distinct situations:
  1. **Unmatched non-empty input** (WAV files or transcript entries exist, but none matched — tested by `tests/test_asr_data.py:624-625`: `build_manifest_from_wav_dir(wav_dir, {"unmatched": "ア"}, ...)` expecting `ValueError`).
  2. **Truly empty input** (`wav_dir` has no `.wav` files AND `transcript_map` is empty `{}` — tested by `test_build_manifest_from_wav_dir_empty_dir`, expecting an empty `.jsonl` manifest file to be written and returned).
- **Contract Alignment**: `PROJECT.md § Interface Contracts` (line 160) specifies `build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path) -> Path` without requiring an exception on empty inputs. Writing an empty manifest when both `wav_files` and `tmap` are empty is clean, idiomatic, and satisfies both the Tier 2 E2E test and the existing unit test `test_build_manifest_from_wav_dir_errors`.

#### Exact Fix Plan
1. **File**: `asr/dataset.py` (function `build_manifest_from_wav_dir`, lines 366–369)
   - Change:
     ```python
     if not records and (wav_files or tmap):
         raise ValueError(f"No matching WAV files found in {wav_root}")

     return write_manifest(records, out_path)
     ```
   - Behavior verification:
     - `wav_files == []` and `tmap == {}` → writes empty JSONL file via `write_manifest([], out_path)` and returns `out_path` (fixes `test_build_manifest_from_wav_dir_empty_dir`).
     - `wav_files` non-empty and `tmap == {"unmatched": "ア"}` → `records == []` and `wav_files or tmap` is truthy → still raises `ValueError` (preserves `tests/test_asr_data.py:625`).
     - `wav_files == []` and `tmap` non-empty → still raises `ValueError` (catches misconfigured/empty WAV folder when transcripts were supplied).
2. **Unit Regression Test**: `tests/test_asr_data.py` (in `test_build_manifest_from_wav_dir_dict_and_files` or a dedicated `test_build_manifest_from_wav_dir_empty_dir_and_map`)
   - Add a test creating an empty directory, calling `build_manifest_from_wav_dir(empty_dir, {}, tmp_path / "empty.jsonl")`, and asserting the returned `Path` exists and `load_manifest(out) == []`.
   - Also assert `build_manifest_from_wav_dir(empty_dir, {"a": "ア"}, tmp_path / "m.jsonl")` still raises `ValueError`.

---

## Feature-by-Feature Audit Matrix (Features 1–11)

| Feature | Test Class | Tests | Expected Result | Notes |
|---|---|---:|---|---|
| 1. Config | `TestTier2Feature01ConfigBoundaries` | 5 | 5/5 PASS | `ModelConfig`/`DecodeConfig` reject invalid `arch`/`method`; boundary values (`f_min=0`, `f_max=sr/2`, `preemphasis=0`, `grad_clip=0`, `seed=0`, `from_dict({})`) all validated cleanly in `asr/config.py`. |
| 2. Audio I/O & Resampling | `TestTier2Feature02AudioIOBoundaries` | 6 | 6/6 PASS | Missing file → `FileNotFoundError`; empty/garbage/truncated → `ValueError`; `save_wav` clips to `[-1, 1]` before `int16` scaling; `resample` handles identity, empty, and `<= 0` sr. |
| 3. STFT / Log-Mel / MFCC | `TestTier2Feature03FeaturesBoundaries` | 5 | 5/5 PASS | Pure silence, sub-window length (100 samples padded to `win_length=400`), DC signal, short MFCC+deltas, `preemphasis=0.0` vs `0.99` all finite `float32`. |
| 4. Energy VAD | `TestTier2Feature04VADBoundaries` | 5 | 5/5 PASS | Pure silence and empty array return `[]`; continuous loud tone returns single span; sub-frame audio handled via tail RMS; `hangover_ms=0.0` and extreme `threshold_db` (`0.0`, `-120.0`) behave as expected. |
| 5. SpecAugment & Corruptions | `TestTier2Feature05AugmentBoundaries` | 6 | 6/6 PASS | Zero masks unchanged; oversized mask params clamped via `min(param, dim)`; no-op defaults preserve signal; invalid `noise_type="brown"` raises `ValueError`; extreme SNR (`-10`, `60`) and silence input remain finite. |
| 6. Tokenizer | `TestTier2Feature06TokenizerBoundaries` | 6 | 6/6 PASS | Invalid mode raises `ValueError`; empty encode/decode and all-blank CTC collapse return `""`; unknown chars skipped safely; small kana & special moras encoded; ASCII lowercasing & spaces handled. |
| 7. Fast Kotoba Synth | `TestTier2Feature07FastSynthBoundaries` | 5 | 5/5 PASS | Single mora, sokuon/hatsuon/chouon, extreme `f0_scale`/`fscale` (clamped safely), empty/punctuation-only text, and `snr_db=-5.0` all produce finite `float32`. |
| 8. Tsukinami TTS | `TestTier2Feature08TsukinamiTTSBoundaries` | 5 | 5/5 PASS | Invalid preset raises `ValueError`; single mora, hiragana/katakana mora-count equivalence, `whisper`/`chibi` presets, and `cache_dir=None` all supported cleanly. |
| 9. Manifest & Dataset | `TestTier2Feature09DatasetBoundaries` | 5 | **4/5 PASS, 1 FAIL** | **FAIL**: `test_build_manifest_from_wav_dir_empty_dir` (see Failure 1 above). Missing manifest, batch size 1, variable-length collation, and invalid `engine` all pass. |
| 10. Acoustic Models | `TestTier2Feature10ModelsBoundaries` | 5 | 5/5 PASS | Invalid arch raises `ValueError`; `B=1` + `T=16`, `[120, 16]` length disparity, `n_mels=80`, and `dropout=0.0` train/eval consistency all pass (no BatchNorm, strict 3-point & pad masking). |
| 11. Training & Checkpointing | `TestTier2Feature11TrainingBoundaries` | 5 | 5/5 PASS | Missing checkpoint/manifest/resume raise `FileNotFoundError`; `batch_size > dataset_size` and 1-utterance train/val (`drop_last=False`, absolute `audio_path`s in manifests) both succeed and write `best.pt`. |
