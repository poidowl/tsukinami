VERDICT: APPROVE

# Primary Review — M7 Phase 2: Tier 5 White-Box Adversarial Hardening (Iteration 1)

## Summary
All 12 adversarial hardening fixes across `asr/` and all 15 white-box adversarial tests in `tests/test_asr_tier5_hardening.py` have been independently reviewed and verified against `PROJECT.md` contracts and `SCOPE.md`. The full canonical test suite passes 100% (`391/391`, 0 failed, 0 skipped), and zero existing `tsukinami` TTS files or `tests_e2e/` files were modified.

---

## 1. Full Canonical Test Suite Execution

Command executed from `/home/antigravity/poidowl/tsukinami`:
```bash
.venv/bin/pytest tests/ tests_e2e/ -v
```

Result:
- **Exit code**: `0`
- **Total**: **`391 passed, 2 warnings in 294.12s (0:04:54)`** (0 failed, 0 skipped, 0 errors)
- **Breakdown**:
  - `tests/test_asr_cli.py`: `16 passed`
  - `tests/test_asr_data.py`: `20 passed`
  - `tests/test_asr_decoding.py`: `38 passed`
  - `tests/test_asr_dsp.py`: `45 passed`
  - `tests/test_asr_models.py`: `17 passed`
  - `tests/test_asr_tier5_hardening.py`: `15 passed`
  - `tests/test_asr_web.py`: `18 passed`
  - `tests_e2e/test_tier1_features.py`: `103 passed`
  - `tests_e2e/test_tier2_boundaries.py`: `98 passed`
  - `tests_e2e/test_tier3_combinations.py`: `12 passed`
  - `tests_e2e/test_tier4_scenarios.py`: `9 passed`

---

## 2. Code Quality & Contract Review

Inspected all 12 modified production files in `asr/` and `tests/test_asr_tier5_hardening.py`:

1. **`asr/decoding.py`**:
   - `_prepare_log_probs`: Validates all-`-inf` rows upfront, shifts by `base_max` before dividing by `temperature`, applies `blank_bias`, and normalizes via `norm_diff - log_sum` inside `np.errstate(over="ignore", under="ignore")`. Guarantees finite `<= 0.0` log-probabilities even for extreme `temperature=1e-308` and `blank_bias=1e308`.
   - `CharNgramLM.from_dict`: Validates `vocab`, `ngrams`, and `raw_ctx` container types, raising `ValueError` rather than `TypeError`.
2. **`asr/audio.py`**:
   - `resample`: Strictly validates positive integer `orig_sr` and `target_sr` (`(int, np.integer)` excluding `bool`), rejecting floats/`NaN`/`Inf`/non-positive values with `ValueError`.
   - `apply_corruption`: Enforces finite domain bounds (`snr_db` in `[-100.0, 120.0]`, `gain_db` in `[-100.0, 100.0]`), validates positive integer `sr`, computes noise/gain in `float64`, and guards output finiteness.
3. **`asr/synth_data.py`**:
   - `synthesize_fast_kotoba`: Enforces `snr_db` in `[-100.0, 120.0]` upfront with `ValueError`.
   - `synthesize_tsukinami`: Merges `overrides` into `prm` and validates `hz`, `fscale`, and `rate` via `_validate_positive_float` prior to cache lookup and synthesis.
4. **`asr/config.py`**:
   - `TrainConfig.__post_init__`: Enforces `0 <= seed <= 2**32 - 1` via `_check_int(..., min_val=0, max_val=2**32 - 1)`.
5. **`asr/train.py`**:
   - `train_asr(resume_from=...)`: Validates `ckpt["tokenizer"]` is a `Mapping`, checks exact vocab list equality (`ckpt_tok_vocab == tokenizer.vocab`), and checks tokenizer mode consistency.
6. **`asr/features.py`**:
   - `mel_filterbank`: Rejects `NaN`/`Inf`/`bool`/non-numeric `f_min` and `f_max` with `ValueError`.
   - `_stft_power_f64` & `extract_log_mel`: Rejects non-finite `wav` with `ValueError` and computes pre-emphasis, STFT power, Mel energy, `log`, and CMVN in `float64` before casting to `float32`, preventing overflow on large finite signals (`1e20`).
   - `extract_mfcc` & `spec_augment`: Validate integer params accepting `(int, np.integer)` and rejecting `bool`/`float` with `ValueError`.
7. **`asr/tokenizer.py`**:
   - `Tokenizer.__init__`: Validates every vocab entry is a `str`, raising `ValueError`.
   - `Tokenizer.decode_tokens`: Uses `numbers.Integral` and explicitly rejects `bool` and non-integral floats with `ValueError`.
8. **`asr/metrics.py`**:
   - `alignment_boundary_error`: Validates all `a`, `e`, `start_sec`, and `end_sec` timestamps via `_validate_finite_timestamp`, raising `ValueError` on `NaN`/`Inf`/`bool`.
9. **`asr/server.py`**:
   - `_resolve_corruption_dict`: Enforces `snr_db` in `[-100.0, 120.0]` and `gain_db` in `[-100.0, 100.0]` returning HTTP `422` across JSON `/api/transcribe`, multipart `/api/transcribe`, and `/api/tts-roundtrip`.
10. **`asr/web/index.html`**:
    - Adds `formatApiError(data, status, rawText)` and `parseApiResponse(res)` used consistently across `fetchApiInfo`, `runTtsRoundtrip`, `transcribeBlob`, and `runRedecode`, formatting FastAPI 422 Pydantic error arrays cleanly and handling non-JSON error bodies without throwing `SyntaxError`.
11. **`asr/__main__.py`**:
    - `_cmd_transcribe`: Rejects empty/whitespace `--tts` strings and zero-length/unspeakable synthesis outputs (`wav.size == 0 or len(_moras) == 0`) with `ValueError`, yielding clean exit code `1` and `Error: ...` on stderr.
12. **`asr/inference.py`**:
    - Protects `self._cache` in `_put_cache`, `redecode`, and `info` with `threading.RLock()` while executing `_decode_and_align` outside the lock.
    - Wraps checkpoint metadata/model deserialization and `load_state_dict` in `ASREngine.from_checkpoint()` to normalize corrupt/malformed checkpoints to `ValueError`.
13. **`tests/test_asr_tier5_hardening.py`**:
    - All 15 adversarial tests are self-contained, use zero mocks and zero skips, exercise real DSP/PyTorch/FastAPI/CLI/Node.js paths, and match `PROJECT.md` contracts.

---

## 3. Repository & Scope Integrity Verification

- `git status --short`:
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
  ```
- `git diff --stat`: Empty — **ZERO** tracked existing `tsukinami` TTS files were modified.
- `stat -c '%y %n' tests_e2e/*.py`: All `tests_e2e/` files remain untouched from `2026-11-19 03:13–03:25 UTC` (prior to M7 Phase 2).

No blocking or non-blocking defects found. Ready to approve.
