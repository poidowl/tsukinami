VERDICT: APPROVE

# Secondary Reviewer Report — M7 Phase 2: Tier 5 White-Box Adversarial Hardening (Iteration 1)

## Summary
Performed an independent line-by-line audit of all production fixes in `asr/` and all 15 adversarial hardening tests in `tests/test_asr_tier5_hardening.py` against all 12 bug groups (8 from Challenger 1, 5 from Challenger 2 with 1 overlap on `snr_db`/`gain_db` bounds) and all 15 test specifications, and executed the target-scoped unit + Tier 5 test suite.

Every fix genuinely addresses its underlying root cause without band-aids, swallowed exceptions, or regressions. No existing `tsukinami` TTS files or `tests_e2e/` files were modified.

---

## Test Execution Evidence

### 1. Target-Scoped Unit + Tier 5 Test Suite
Command:
```bash
.venv/bin/pytest tests/ -v
```
Working directory: `/home/antigravity/poidowl/tsukinami`
Exit code: `0`
Result: **`169 passed, 2 warnings in 195.31s (0:03:15)`**

Per-file breakdown:
- `tests/test_asr_cli.py`: 16 passed
- `tests/test_asr_data.py`: 20 passed
- `tests/test_asr_decoding.py`: 38 passed
- `tests/test_asr_dsp.py`: 45 passed
- `tests/test_asr_models.py`: 17 passed
- `tests/test_asr_tier5_hardening.py`: 15 passed
- `tests/test_asr_web.py`: 18 passed

### 2. Repository Working Tree Integrity Check
Command:
```bash
git status -s && git diff --stat
```
Output:
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
Confirmed zero tracked existing `tsukinami` TTS files were modified.

---

## Line-by-Line Review Against All 12 Bug Groups & 15 Test Specs

| # | Bug Group | File(s) & Lines Verified | Root-Cause Assessment | Test Coverage in `tests/test_asr_tier5_hardening.py` |
|---|---|---|---|---|
| 1 | Ch1 Bug 1 [HIGH]: `_prepare_log_probs` numerical overflow / NaN / positive scores | `asr/decoding.py:62-81` | **FIXED.** Checks `isnan`/`isposinf` and all-`-inf` rows on `arr` first, subtracts `base_max` before dividing by `temperature` (guaranteeing `shifted <= 0.0` with at least one `0.0` per frame), applies `blank_bias`, and normalizes via `norm_diff - log_sum` under `np.errstate(over="ignore", under="ignore")`. Mathematically guarantees finite log-probs `<= 0.0` for any finite `temperature > 0` and finite `blank_bias`. | Spec 1: `test_decoding_extreme_temperature_and_blank_bias_stability` |
| 2 | Ch1 Bug 2 & Ch2 Bug 1 [HIGH]: Unbounded `snr_db`/`gain_db` causing `ZeroDivisionError`/`OverflowError`/`NaN`/`Inf` & HTTP 500 | `asr/audio.py:409-452, 509-528`; `asr/synth_data.py:351-357`; `asr/server.py:43-46, 298-303, 377-383` | **FIXED.** Enforces consistent finite domain bounds (`snr_db` in `[-100.0, 120.0]`, `gain_db` in `[-100.0, 100.0]`) at both the API layer (returning HTTP `422`) and DSP/synth layer (raising `ValueError`), performs noise scaling and gain arithmetic in `float64`, and guards output finiteness. | Spec 2: `test_apply_corruption_extreme_snr_and_gain_no_crash_or_nan`; Spec 9: `test_server_extreme_corruption_bounds_no_500`; Spec 10: `test_server_nan_inf_and_malformed_http_payloads` |
| 3 | Ch1 Bug 3 [HIGH]: `synthesize_tsukinami` `ZeroDivisionError` and silent `rate <= 0` | `asr/synth_data.py:572-574` | **FIXED.** Validates `prm["hz"]`, `prm["fscale"]`, and `prm["rate"]` via `_validate_positive_float` after applying `overrides` and before cache lookup/synthesis. | Spec 3: `test_synthesize_tsukinami_invalid_overrides_rejected` |
| 4 | Ch1 Bug 4 [MED-HIGH]: `TrainConfig` out-of-range `seed` | `asr/config.py:16-28, 180` | **FIXED.** `_check_int` supports `max_val`; `TrainConfig.__post_init__` enforces `0 <= seed <= 2**32 - 1`. | Spec 4: `test_train_config_seed_bounds_validation` |
| 5 | Ch1 Bug 5 [MED-HIGH]: `train_asr(resume_from=...)` malformed or same-length mismatched tokenizer | `asr/train.py:297-314` | **FIXED.** Validates `isinstance(ckpt_tok, Mapping)`, exact vocabulary equality (`isinstance(ckpt_tok_vocab, list) and ckpt_tok_vocab == tokenizer.vocab`), and tokenizer mode match when present, raising `ValueError`. | Spec 5: `test_train_resume_rejects_malformed_or_mismatched_tokenizer` |
| 6 | Ch1 Bug 6 [MEDIUM]: `asr/features.py` NaN filterbank bypass, `float32` power overflow, float param `TypeError` | `asr/features.py:47-98, 155-171, 174-203, 239-245, 270-281` | **FIXED.** `mel_filterbank` rejects non-finite/bool/non-numeric `f_min`/`f_max`; `extract_log_mel` rejects non-finite `wav` and runs pre-emphasis, STFT power (`_stft_power_f64`), Mel energy, `log`, and CMVN in `float64` before casting to `float32`; `extract_mfcc` and `spec_augment` validate integer params with `ValueError`. | Spec 6: `test_features_nan_filterbank_large_signal_and_type_validation` |
| 7 | Ch1 Bug 7 [MEDIUM]: `resample` accepts `NaN`/`Inf`/float sample rates | `asr/audio.py:62-67` | **FIXED.** Rejects `bool`, floats, `NaN`, `Inf`, and non-positive values; requires positive `(int, np.integer)`. | Spec 7: `test_resample_rejects_non_int_and_non_finite_sr` |
| 8 | Ch1 Bug 8 [LOW-MED]: `Tokenizer`, `CharNgramLM.from_dict`, `alignment_boundary_error` validation inconsistencies | `asr/tokenizer.py:103-107, 213-216`; `asr/decoding.py:178-200`; `asr/metrics.py:245-276` | **FIXED.** All four validation paths now raise `ValueError` cleanly (non-str vocab entries, bool/float token IDs via `numbers.Integral`, non-list/tuple LM `vocab`/`ngrams`/`raw_ctx`, and non-finite/bool alignment timestamps via `_validate_finite_timestamp`). | Spec 8: `test_tokenizer_and_lm_malformed_inputs_and_model_nan_padding_isolation` (also verifies NaN padding isolation & Conformer dynamic positional encoding `T=4100`) |
| 9 | Ch2 Bug 2 [MEDIUM]: `asr/web/index.html` broken 422 Pydantic array & non-JSON 500 error rendering | `asr/web/index.html:1704-1751, 1756, 1840, 1911, 1960` | **FIXED.** Added shared `formatApiError(data, status, rawText)` and `parseApiResponse(res)` helpers and replaced all raw `res.json()` calls across all 4 `fetch()` endpoints (`fetchApiInfo`, `runTtsRoundtrip`, `transcribeBlob`, `runRedecode`). Confirmed via `grep` that zero raw `res.json()` calls remain. | Spec 15: `test_index_html_error_formatting_pydantic_422_and_non_json_500` (live Node.js execution) |
| 10 | Ch2 Bug 3 [MEDIUM]: CLI `transcribe --tts ""` / `"!!!"` with `--engine fast` silently exiting 0 | `asr/__main__.py:312-328` | **FIXED.** Validates `args.tts.strip()` is non-empty and `wav.size > 0` and `len(_moras) > 0` for both `--engine fast` and `--engine tsukinami`, raising `ValueError` (clean `rc=1` + `Error:` on stderr). | Spec 14: `test_cli_transcribe_tts_empty_and_unspeakable_fast_engine_fails_cleanly` |
| 11 | Ch2 Bug 4 [MEDIUM]: `ASREngine._cache` thread-safety | `asr/inference.py:221, 311-316, 505-516, 540-541` | **FIXED.** Protects all `_cache` mutations/lookups/evictions/length reads with `self._cache_lock = threading.RLock()` while keeping `_decode_and_align` outside the lock. | Spec 11: `test_server_redecode_after_lru_eviction_and_concurrent_requests`; Spec 12: `test_server_ultrashort_wav_both_architectures` |
| 12 | Ch2 Bug 5 [LOW-MED]: `ASREngine.from_checkpoint()` raw `TypeError`/`RuntimeError` on structurally corrupt `.pt` | `asr/inference.py:250-287` | **FIXED.** Wraps config/tokenizer/LM deserialization, `build_model`, and `model.load_state_dict` in `try/except (KeyError, TypeError, ValueError, RuntimeError)` raising `ValueError("Corrupt or invalid checkpoint ...")`. | Spec 13: `test_engine_from_checkpoint_structurally_corrupt_raises_value_error` |

---

## Conclusion
All 12 bug groups are cleanly fixed at their root causes, all 15 adversarial hardening tests pass with zero skips and zero mocks (`169/169` passed in `tests/`), and repository integrity is intact.

**VERDICT: APPROVE**
