VERDICT: APPROVE

# Secondary Reviewer Report — M7 Phase 2: Tier 5 White-Box Adversarial Hardening (Iteration 2)

## Test Execution Evidence
- **Command**: `.venv/bin/pytest tests/ -v` (CWD: `/home/antigravity/poidowl/tsukinami`)
- **Result**: **170 passed, 0 failed, 0 skipped**, 2 warnings in 190.04s (`0:03:10`)
  - `tests/test_asr_cli.py`: 16 passed
  - `tests/test_asr_data.py`: 20 passed
  - `tests/test_asr_decoding.py`: 38 passed
  - `tests/test_asr_dsp.py`: 45 passed
  - `tests/test_asr_models.py`: 17 passed
  - `tests/test_asr_tier5_hardening.py`: 16 passed
  - `tests/test_asr_web.py`: 18 passed
- **Repository Cleanliness**: `git status --short` confirms zero tracked `tsukinami` TTS files modified and zero `tests_e2e/` modifications.

---

## Line-by-Line Review Against `ch1_iter2/handoff.md`

### 1. Gap 1 — `asr/synth_data.py` (`synthesize_fast_kotoba`, `synthesize_tsukinami`) — **VERIFIED FIXED**
- Lines 257–278: `_validate_positive_int`, `_validate_positive_float`, and `_validate_bounded_float` reject `bool`, non-numeric/non-int types, non-finite values, and out-of-range values with `ValueError` while supporting NumPy integer/number scalars.
- Lines 356–359 (`synthesize_fast_kotoba`): Enforces finite domain bounds `f0_scale ∈ [0.1, 10.0]`, `fscale ∈ [0.1, 10.0]`, and `rate ∈ [0.1, 10.0]`, preventing `OverflowError` / OOM on extreme values like `rate=1e308`.
- Lines 581–585 (`synthesize_tsukinami`): Enforces `hz ∈ [20.0, 2000.0]`, `fscale ∈ [0.25, 4.0]`, `rate ∈ [0.1, 10.0]`, and `tsubu ∈ [1.0, 4096.0]` (cast to `int`, also preventing fractional truncation like `tsubu=0.5 → 0`), eliminating `ZeroDivisionError` in `carve.py`.
- Tests (`tests/test_asr_tier5_hardening.py:178-210`): Covers `hz` (`0`, `-100`, `nan`, `1e-308`, `1e6`), `fscale` (`0`, `-0.5`, `100.0`), `rate` (`0`, `-1`, `inf`, `1e308`), `tsubu` (`0`, `-1`, `0.5`, `inf`, `True`), and `synthesize_fast_kotoba` extreme `rate`/`f0_scale`/`fscale`.

### 2. Gap 2 — `asr/audio.py` (`save_wav`, `load_wav`, `load_wav_bytes`, `resample`, `detect_vad`, `apply_corruption`) — **VERIFIED FIXED**
- Lines 60–63: Shared `_validate_positive_int_sr(name, sr)` rejects `bool`, `float`, `NaN`, `Inf`, and `<= 0` with `ValueError`.
- Used at entry of `resample` (lines 68–69), `load_wav_bytes` (line 235), `load_wav` (line 265), `save_wav` (line 300 — before any filesystem/file-creation operations at line 310), `detect_vad` (line 328), and `apply_corruption` (line 444).
- Lines 329–351 (`detect_vad`): Rejects `bool`, non-numeric, and non-finite inputs for `frame_ms` (`> 0`), `hangover_ms` (`>= 0`), and `threshold_db` with `ValueError`.
- Lines 428–429, 449–499 (`apply_corruption`): Bounds `speed ∈ [0.1, 10.0]` (`_MIN_SPEED`/`_MAX_SPEED`) and validates `band_limit` is a 2-element `(list, tuple)` of non-bool finite numbers, raising `ValueError` instead of `OverflowError`/`TypeError`.
- Tests (`tests/test_asr_tier5_hardening.py:398-429`): Verifies `save_wav` raises `ValueError` and leaves no file on disk (`assert not out_path.exists()`), and verifies `load_wav`, `load_wav_bytes`, `detect_vad`, and `apply_corruption` parameter rejections.

### 3. Gap 3 — `asr/features.py` (`_stft_power_f64` / `stft_power`, `mel_filterbank`) — **VERIFIED FIXED**
- Lines 58–61: `_validate_positive_int(name, value)` rejects `bool`, `float`, `NaN`/`Inf`, and `<= 0` with `ValueError`.
- Applied to `n_fft`, `win_length`, `hop_length` in `_stft_power_f64` (lines 70–72, covering `stft_power`) and `sr`, `n_fft`, `n_mels` in `mel_filterbank` (lines 157–159).
- Tests (`tests/test_asr_tier5_hardening.py:363-375`): Verifies `ValueError` for `mel_filterbank(sr=inf)`, `mel_filterbank(n_mels=3.5)`, `mel_filterbank(sr=True, ...)`, and `stft_power` with float/bool `hop_length`, `n_fft`, `win_length`.

### 4. Gap 4 — `asr/tokenizer.py` (`Tokenizer.from_dict`) — **VERIFIED FIXED**
- Lines 258–263: Explicitly enforces `isinstance(vocab, (list, tuple))` before passing to `cls(...)`, raising `ValueError` for non-iterables (`int`) as well as string/bytes iterables (`"abc"`, `b"abc"`).
- Tests (`tests/test_asr_tier5_hardening.py:441-446`): Verifies `ValueError` for `vocab=123`, `vocab="abc"`, and `vocab=b"abc"`.

### 5. Gap 5 — `asr/train.py` (`train_asr` resume path) — **VERIFIED FIXED**
- Lines 316–352: Validates `history` is a `list` of `Mapping` entries, rejects `bool` for `best_val_cer` and `bool`/non-integer for `epoch`, and wraps `model.load_state_dict`, `optimizer.load_state_dict`, `scheduler.load_state_dict`, and metadata parsing in `try/except (RuntimeError, TypeError, ValueError, KeyError)` raising `ValueError("Corrupt or incompatible resume checkpoint ...")`.
- Tests (`tests/test_asr_tier5_hardening.py:290-338`): Verifies `ValueError` with `"Corrupt or incompatible resume checkpoint"` for both `"history": None` and mismatched `"model_state_dict"`.

---

## Conclusion
All 5 fixes genuinely resolve their root causes without regressions, all 170/170 unit + Tier 5 tests pass, and scope/cleanliness constraints are fully respected. **VERDICT: APPROVE**.
