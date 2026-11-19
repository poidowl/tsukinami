# Implementation Worker Handoff — M7 Phase 1 Tier 4 E2E (`sub_orch_m7_t4` / `iter1_worker`)

## 1. Summary
Fixed the `ctc_posteriors` contract mismatch identified by Explorers 1–3 so that `ASREngine.transcribe(..., include_visuals=True)["ctc_posteriors"]` returns a JSON-serializable 2D full-vocabulary posterior probability matrix `list[list[float]]` of shape `(T_vis, V)` (or `[]` on empty audio), updated the Canvas 2D heatmap renderer in `asr/web/index.html` to consume the 2D array natively, and aligned the unit tests in `tests/test_asr_cli.py` and `tests/test_asr_web.py`.

All **376/376 tests** (`tests/` + `tests_e2e/`, including all 9 Tier 4 scenarios) now pass with exit code `0`, and zero existing `tsukinami` TTS files or `tests_e2e/` files were modified.

---

## 2. Files Modified (Strictly Within Exclusive Ownership)

1. **`asr/inference.py`**
   - Removed unused `_DEFAULT_TOP_K_TOKENS = 12`.
   - Refactored `_build_ctc_posteriors(log_probs, *, max_frames=_MAX_POSTERIOR_FRAMES) -> list[list[float]]`:
     - Returns `[]` if `log_probs.ndim != 2` or `T == 0` or `V == 0`.
     - Downsamples frames to at most `max_frames` (`400`) when `T > max_frames`.
     - Computes numerically stable full-vocabulary probabilities in `float64` (sanitizing any non-finite log-probs to `-700.0`, subtracting row max, exponentiating, renormalizing rows to sum to `1.0`, clipping to `[0.0, 1.0]`, and rounding to 6 decimal places so row sums remain within `1e-4` of `1.0`).
   - Updated `ASREngine.transcribe()` to assign `result["ctc_posteriors"] = _build_ctc_posteriors(log_probs_np)`.

2. **`asr/web/index.html`**
   - Updated `drawCtcPosteriors()` to natively handle 2D `(T, V)` numeric posterior arrays:
     - Computes per-token peak probability across all frames.
     - Selects `blank_id` (from `state.info.blank_id`, defaulting to `0`) + top 11 non-blank vocab indices by descending peak probability.
     - Resolves token labels from `state.info.vocab` (falling back to `"<blank>"` or `"#<id>"`).
     - Retains fallback support for the legacy `{probs, top_tokens}` object format.

3. **`tests/test_asr_cli.py`**
   - Updated `test_engine_transcribe_visuals` to assert `res_vis["ctc_posteriors"]` is a non-empty 2D `list[list[float]]` of shape `(T', engine.tokenizer.vocab_size)` with finite values in `[0.0, 1.0]` and row sums matching `1.0` (`atol=1e-4`).
   - Updated `test_engine_empty_short_and_invalid_inputs` to assert `empty_res["ctc_posteriors"] == []` and validate `short_res["ctc_posteriors"]` shape, bounds, and row-sum normalization when non-empty.

4. **`tests/test_asr_web.py`**
   - Updated `test_transcribe_multipart_with_corruptions_and_visuals` to assert `data["ctc_posteriors"]` is a non-empty 2D numeric matrix of shape `(T', vocab_size)` (matching `/api/info`'s `vocab_size`) with finite values in `[0.0, 1.0]` and row sums matching `1.0` (`atol=1e-4`).

---

## 3. Mandatory Final Verification

### Command 1: Full Unit & E2E Test Suite
- **Command**: `.venv/bin/pytest tests/ tests_e2e/ -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Output**:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 376 items

tests/test_asr_cli.py ................                                   [  4%]
tests/test_asr_data.py ....................                              [  9%]
tests/test_asr_decoding.py ......................................        [ 19%]
tests/test_asr_dsp.py .............................................      [ 31%]
tests/test_asr_models.py .................                               [ 36%]
tests/test_asr_web.py ..................                                 [ 40%]
tests_e2e/test_tier1_features.py ....................................... [ 51%]
................................................................         [ 68%]
tests_e2e/test_tier2_boundaries.py ..................................... [ 78%]
.............................................................            [ 94%]
tests_e2e/test_tier3_combinations.py ............                        [ 97%]
tests_e2e/test_tier4_scenarios.py .........                              [100%]

================= 376 passed, 2 warnings in 177.67s (0:02:57) ==================
```

### Command 2: Git Status Check
- **Command**: `git status --short`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Output**:
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
- **Confirmed**: Zero tracked `tsukinami` TTS files modified; `tests_e2e/` untouched.
