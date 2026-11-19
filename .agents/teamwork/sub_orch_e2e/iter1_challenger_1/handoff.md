# Iteration 1 Challenger 1 Handoff (`sub_orch_e2e`)

## Verdict: FAIL

Two concrete defects were found via adversarial probing in an isolated temporary directory (cleaned up before reporting):
1. **32-bit PCM int32 overflow bug in `tests_e2e/conftest.py` (`write_pcm_wav`, line 111)** — `sampwidth=4` wraps `+1.0` peaks to `-2147483648` with `RuntimeWarning: invalid value encountered in cast`.
2. **Progressive testability violation in `tests_e2e/test_tier2_boundaries.py` (`TestTier2Feature01ConfigBoundaries.test_model_config_invalid_arch_rejected`, lines 23–29)** — Feature 1 (M1) imports `asr.models.build_model` (M3 / Feature 10), breaking M1-only test execution and duplicating Feature 10's test at line 532.

---

## Probe 1: `tests_e2e/conftest.py` Helper Stress-Test

All 11 helper functions in `tests_e2e/conftest.py` were imported dynamically and stress-tested across normal and boundary inputs in an isolated temp dir (`mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`).

### Confirmed Bug (Blocking)
- **Location**: `tests_e2e/conftest.py:101-111` (`write_pcm_wav`)
- **Root Cause**: `clipped` is `np.float32`. Under NumPy 2.x (NEP 50), `clipped * 2147483647.0` retains `float32` dtype. Because `2147483647` exceeds 24-bit `float32` mantissa precision, `np.float32(1.0) * 2147483647.0` rounds up to `2147483648.0` (`2^31`), overflowing `<i4` (`int32` max `2147483647`).
- **Observed Evidence**:
  ```text
  /home/antigravity/poidowl/tsukinami/tests_e2e/conftest.py:111: RuntimeWarning: invalid value encountered in cast
    pcm = np.round(clipped * 2147483647.0).astype("<i4").tobytes()
  FAIL [wav_pcm_sign_4_1_8000]:  arr=[-2147483648, -1073741824, 0, 1073741824, -2147483648, -2147483648, -2147483648]
  FAIL [wav_pcm_sign_4_1_16000]: arr=[-2147483648, -1073741824, 0, 1073741824, -2147483648, -2147483648, -2147483648]
  FAIL [wav_pcm_sign_4_1_44100]: arr=[-2147483648, -1073741824, 0, 1073741824, -2147483648, -2147483648, -2147483648]
  FAIL [wav_pcm_sign_4_2_8000]:  arr=[-2147483648, -1073741824, 0, 1073741824, -2147483648, -2147483648, -2147483648]
  FAIL [wav_pcm_sign_4_2_16000]: arr=[-2147483648, -1073741824, 0, 1073741824, -2147483648, -2147483648, -2147483648]
  FAIL [wav_pcm_sign_4_2_44100]: arr=[-2147483648, -1073741824, 0, 1073741824, -2147483648, -2147483648, -2147483648]
  ```
  For input `[-1.0, -0.5, 0.0, 0.5, 1.0, 2.0, -2.0]`, both `+1.0` and `+2.0` wrapped to `-2147483648`.
- **Required Fix**: Upcast to `float64` before scaling for 32-bit PCM:
  ```python
  elif sampwidth == 4:
      pcm = np.round(clipped.astype(np.float64) * 2147483647.0).astype("<i4").tobytes()
  ```

### Minor Edge Case (Non-Blocking)
- `make_speech_like(duration=0.0)` sets `total_n = 0`, `active_n = max(1, 0) = 1`, and fails broadcasting `active` (len 1) into `out` (len 0). Guarding `if total_n <= 0: return np.zeros(0, dtype=np.float32)` is cleaner.

### Passing Helpers
- `make_sine`, `make_speech_like` (positive durations, deterministic seed), `make_silence`, `make_clipped`, `write_pcm_wav` (16-bit mono/stereo @ 8k/16k/44.1k), `write_corrupt_wav` (`garbage`/`empty`/`truncated`), `wav_to_bytes`, `wav_to_b64`, `make_synthetic_log_probs` (normal & empty, `exp(lp).sum(-1) == 1.0`), `make_weighted_log_probs`, and `extract_transcribe_payload` all passed.

---

## Probe 2: Assertion Strength, False-Positive & Progressive Testability Audit (Tiers 1 & 2)

### Confirmed Issue (Blocking)
- **Location**: `tests_e2e/test_tier2_boundaries.py:23-29` (`TestTier2Feature01ConfigBoundaries.test_model_config_invalid_arch_rejected`)
- **Problem**: Imports `from asr.models import build_model` inside Feature 1 (`M1`, `asr/config.py`) tests. `asr.models` is `M3` / Feature 10. Running Feature 1 tests when only M1 is implemented fails with `ModuleNotFoundError: No module named 'asr.models'`, violating progressive testability in `SCOPE.md`. It also duplicates `TestTier2Feature10ModelsBoundaries.test_build_model_invalid_arch_raises_value_error` (line 532).
- **Required Fix**: Replace `test_model_config_invalid_arch_rejected` in `TestTier2Feature01ConfigBoundaries` with an M1-only config boundary test (no `asr.models` import).

### Assertion Calibration Assessment (Passed)
- No unrealistic CER/accuracy thresholds on 2-epoch toy checkpoints in Tiers 1–2.
- Floating-point comparisons appropriately use `pytest.approx` / `np.allclose` where needed (`test_audio_config_defaults_and_roundtrip`, `test_extract_mfcc_with_deltas_39_coeffs`, `test_synthesize_tsukinami_disk_cache_hit`, `test_compute_cer_*`, etc.).
- Exception assertions match `PROJECT.md § Interface Contracts` (`FileNotFoundError` / `ValueError` for `load_wav`, `ValueError` for invalid `arch`/`mode`/`noise_type`/mismatched metric lengths, `404` for unknown `utterance_id`, `400`/`422` for corrupt API payloads).
- `extract_transcribe_payload` sensibly tolerates both flat and nested `/api/tts-roundtrip` response layouts.

---

## Probe 3: Failure-on-Broken-Target Probe

Using an isolated pytest plugin in the temp dir to shadow `asr` ahead of the repository root:
1. **Missing `asr` package** (`asr/__init__.py` raises `ModuleNotFoundError`):
   - Executed 7 representative Tier 1 tests across Features 1, 2, 3, 4, 6, 12, 14.
   - Result: **7 failed, 0 passed, 0 skipped** (`ModuleNotFoundError`). Zero silent skips or dummy passes.
2. **Broken stub `asr` package** (wrong config defaults, `load_wav` returning float64 zeros @ 8kHz, `extract_log_mel` returning NaN, `detect_vad` returning `[]`, `Tokenizer` with `blank_id=1`, `greedy_decode` returning empty, `compute_cer` returning zeros):
   - Executed 52 Tier 1 tests across Features 1–6 and 12–14.
   - Result: **49 failed, 3 passed, 0 skipped**.
   - The 3 passing tests are expected given the stub:
     - `test_packaging_files_and_asr_import` (checks `pyproject.toml`, `.gitignore`, and `import asr`),
     - `test_kana_mode_hiragana_normalizes_to_katakana` (stub `encode()` returned `[1]` for both inputs; companion `test_kana_mode_blank_id_and_roundtrip` failed),
     - `test_char_ngram_lm_serialization_roundtrip` (stub `score_next()` returned `0.0` for both; companion `test_char_ngram_lm_fit_and_score_next` failed).

---

## Cleanliness Verification
- Working tree untouched (`git status --short` unchanged; zero files modified in repo).
- All temporary probe directories removed via `trap 'rm -rf "$PROBE_DIR"' EXIT`.
