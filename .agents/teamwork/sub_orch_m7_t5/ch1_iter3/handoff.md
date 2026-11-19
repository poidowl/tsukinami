VERDICT: GAPS_FOUND

# White-Box Challenger 1 Report — M7 Phase 2: Tier 5 Adversarial Coverage Hardening (Iteration 3)

## Executive Summary
Independent white-box audit of the updated core implementation (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/*.py`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`) and `tests/test_asr_tier5_hardening.py` confirmed that **all Iteration 1 & Iteration 2 fixes hold up cleanly** (including `_prepare_log_probs` extreme temperature/blank_bias stability, `features.py` positive-int & float64 guards, `tokenizer.py` `from_dict` vocab type validation, `config.py` bounds, `models/` NaN padding isolation & dynamic PE, and `metrics.py` timestamp validation).

However, isolated adversarial probes uncovered **3 remaining concrete, reproducible bugs** (uncaught `OverflowError`, `ZeroDivisionError`, `AttributeError`, `KeyError`, `struct.error` with partial file creation, and CPU DoS) across `asr/synth_data.py`, `asr/train.py`, and `asr/audio.py`.

---

## Remaining Gaps (Concrete Repros & Test Specs)

### Gap 1: `asr/synth_data.py` — `synthesize_tsukinami` unvalidated `_YOMU_PRM_KEYS` overrides cause `OverflowError`, `ZeroDivisionError`, `TypeError`, and CPU hang
- **Location**: `asr/synth_data.py:573-586`
- **Root Cause**: `synthesize_tsukinami` validates only `hz`, `fscale`, `rate`, and `tsubu` from `_YOMU_PRM_KEYS`, while forwarding `yure`, `shimmer`, `tadayoi`, `line_g`, `ap_n`, `seed`, and `tr_iroke` directly to `yomu.build_carve_rc` / `carve.make` without finite/type/domain checks. Note that `yure` is also exposed on the public `/api/tts-roundtrip` endpoint.
- **Exact Repros**:
  1. `synthesize_tsukinami("ア", overrides={"yure": float("inf")})` -> `OverflowError: cannot convert float infinity to integer`
  2. `synthesize_tsukinami("ア", overrides={"yure": 1e308})` -> `OverflowError: cannot convert float infinity to integer`
  3. `synthesize_tsukinami("ア", overrides={"shimmer": float("nan")})` -> `ZeroDivisionError: division by zero`
  4. `synthesize_tsukinami("ア", overrides={"shimmer": float("inf")})` -> `ZeroDivisionError: division by zero`
  5. `synthesize_tsukinami("ア", overrides={"line_g": float("nan")})` -> `ZeroDivisionError: division by zero`
  6. `synthesize_tsukinami("ア", overrides={"tadayoi": float("inf")})` -> `OverflowError: cannot convert float infinity to integer`
  7. `synthesize_tsukinami("ア", overrides={"seed": None})` -> `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'`
  8. `synthesize_tsukinami("ア", overrides={"ap_n": 100000})` -> CPU hang (>4s; `ap_n=1000000` hung >9m50s)
- **Recommended Fix**: Validate all numeric/int `_YOMU_PRM_KEYS` present in `prm` before `yomu.build_carve_rc`, raising `ValueError`:
  - `yure`, `shimmer`, `tadayoi`, `line_g`, `tr_iroke`: reject `bool`, non-number, non-finite, and out-of-range values (ensuring all built-in `yomu.PRESETS` values remain valid, e.g., finite bounded floats such as `yure in [0.0, 100.0]`, `shimmer in [0.0, 10.0]`, `tadayoi in [0.0, 100.0]`, `line_g in [0.0, 10.0]`, `tr_iroke in [0.0, 10.0]`).
  - `ap_n`: non-bool integer in `[0, 64]` (covers all presets while preventing CPU DoS).
  - `seed`: non-bool integer in `[0, 2**32 - 1]`.
- **Test Spec**: Extend `test_synthesize_tsukinami_invalid_overrides_rejected` in `tests/test_asr_tier5_hardening.py` to assert `ValueError` for `{"yure": float("inf")}`, `{"yure": 1e308}`, `{"shimmer": float("nan")}`, `{"shimmer": float("inf")}`, `{"line_g": float("nan")}`, `{"tadayoi": float("inf")}`, `{"ap_n": 100000}`, `{"seed": None}`, `{"seed": True}`.

### Gap 2: `asr/train.py` — `train_asr(resume_from=...)` uncaught `AttributeError` / `KeyError` and silent corruption on `best_val_cer=NaN` / negative `epoch`
- **Location**: `asr/train.py:316-352`, `asr/train.py:451-454`
- **Root Cause**:
  1. `except (RuntimeError, TypeError, ValueError, KeyError)` at line 349 does not catch `AttributeError`, so `optimizer_state_dict=None` crashes with uncaught `AttributeError: 'NoneType' object has no attribute 'copy'`.
  2. `raw_history` validates each entry is a `Mapping`, but not that required keys (`epoch`, `train_loss`, `val_loss`, `val_cer`) exist; when resuming with `epoch >= train_cfg.epochs` and `history=[{}]`, line 451 crashes with uncaught `KeyError: 'epoch'`.
  3. `raw_best_cer = float("nan")` is silently accepted at line 336, making `val_cer < best_val_cer` permanently `False` and preventing `best.pt` from ever updating.
  4. `raw_epoch = -5` is silently accepted at line 346, causing negative epoch loops (`-4, -3, ...`).
- **Exact Repros**:
  - Save checkpoint with valid `model_state_dict`, `model_config`, `tokenizer` and:
    1. `"optimizer_state_dict": None` -> uncaught `AttributeError`
    2. `"history": [{}], "epoch": 5` (with `train_cfg.epochs=2`) -> uncaught `KeyError: 'epoch'`
    3. `"best_val_cer": float("nan")` -> silently accepted (no `ValueError`)
    4. `"epoch": -5` -> silently accepted (no `ValueError`)
- **Recommended Fix**:
  - Validate `optimizer_state_dict` and `scheduler_state_dict` are `Mapping` (and include `AttributeError` in the `except` tuple at line 349).
  - Validate `best_val_cer` is not `NaN` and `>= 0.0` (`math.isnan(best_val_cer) or best_val_cer < 0.0` -> `ValueError`).
  - Validate `raw_epoch >= 0` (`< 0` -> `ValueError`).
  - Validate each `history` entry contains finite numeric `"epoch"`, `"train_loss"`, `"val_loss"`, `"val_cer"` (or raise `ValueError`).
- **Test Spec**: Extend `test_train_resume_rejects_malformed_or_mismatched_tokenizer` in `tests/test_asr_tier5_hardening.py` to assert `ValueError` for `optimizer_state_dict=None`, `history=[{}]` (with `epoch=5`), `best_val_cer=float("nan")`, and `epoch=-5`.

### Gap 3: `asr/audio.py` — `detect_vad` `OverflowError` on extreme finite `frame_ms`/`hangover_ms` and `save_wav` `struct.error` leaving corrupt 8-byte file on `sr >= 2**32`
- **Location**: `asr/audio.py:300-314`, `asr/audio.py:358`, `asr/audio.py:377`
- **Root Cause**:
  1. In `detect_vad`, `int(round(sr * frame_ms / 1000.0))` (line 358) overflows to `inf` -> `OverflowError` when `frame_ms=1e308`. Likewise `int(math.ceil(hangover_ms / frame_ms))` (line 377) overflows to `inf` -> `OverflowError` when `frame_ms=1e-308, hangover_ms=150.0`.
  2. In `save_wav`, `_validate_positive_int_sr` allows `sr >= 2**32`, which passes validation, creates and opens the file via `wave.open`, and then crashes in `wf.writeframes`/header pack with `struct.error: 'L' format requires 0 <= number <= 4294967295`, leaving a corrupt 8-byte file on disk.
- **Exact Repros**:
  1. `detect_vad(wav, sr=16000, frame_ms=1e308)` -> `OverflowError: cannot convert float infinity to integer`
  2. `detect_vad(wav, sr=16000, frame_ms=1e-308, hangover_ms=150.0)` -> `OverflowError: cannot convert float infinity to integer`
  3. `save_wav(path, wav, sr=2**32)` -> `struct.error` and leaves an 8-byte file at `path`
- **Recommended Fix**:
  - In `detect_vad`: guard `frame_len` against float overflow (e.g., if `not math.isfinite(sr * frame_ms / 1000.0)` or `>= mono.size`, clamp `frame_len = mono.size`), and guard `hangover_frames` (if `not math.isfinite(hangover_ms / frame_ms)` or `>= is_speech.size`, clamp `hangover_frames = is_speech.size`).
  - In `save_wav`: reject `sr > 2**32 - 1` (the RIFF/WAVE 32-bit unsigned framerate limit) with `ValueError` before opening the file.
- **Test Spec**: Extend `test_audio_save_wav_vad_and_corruption_parameter_hardening` in `tests/test_asr_tier5_hardening.py` to verify `detect_vad` with `frame_ms=1e308` and `(frame_ms=1e-308, hangover_ms=150.0)` returns valid finite segment lists without `OverflowError`, and `save_wav(out_path, wav, sr=2**32)` raises `ValueError` without creating `out_path`.

---

## Verified Clean Areas (Iteration 1 & 2 Fixes Confirmed)
- `asr/config.py`: Strict int/float/bool/bounds validation across `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig`.
- `asr/features.py`: `_validate_positive_int`, NaN/Inf rejection, float64 internal precision for `1e20` waveforms, `extract_mfcc` & `spec_augment` type validation.
- `asr/tokenizer.py`: `Tokenizer.from_dict` rejects non-list/tuple `vocab` (`int`, `str`, `bytes`); `decode_tokens` rejects bool/float/out-of-range IDs.
- `asr/decoding.py`: `_prepare_log_probs` is mathematically overflow-safe for all finite/extreme `temperature` and `blank_bias`; `CharNgramLM.from_dict` validates all nested structures; `viterbi_align` validates all inputs.
- `asr/dataset.py`, `asr/models/*.py`, `asr/metrics.py`: Clean against all boundary/NaN/shape probes.

## Hygiene
- Working tree untouched (0 repository files modified).
- All temporary probe directories in `/tmp/teamwork_probe.*` removed.
