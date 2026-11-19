# Explorer 1 Handoff — Tier 4 Live Run & Failure Diagnosis (`sub_orch_m7_t4` / `iter1_exp1`)

## 1. Execution Summary

- **Command**: `.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -v --tb=short`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `1`
- **Wall-Clock Duration**: `31.07s`
- **Result**: **7 passed, 2 failed**, 1 warning (`StarletteDeprecationWarning` on `httpx` in `fastapi.testclient`)

### Per-Test Results (All 9 Tier 4 Scenarios)

| # | Test Function | Status |
|---|---|---|
| 1 | `test_t4_scenario1_one_command_cpu_quickstart_demo` | **PASS** |
| 2 | `test_t4_scenario2_multi_preset_tsukinami_roundtrip_and_alignment` | **PASS** |
| 3 | `test_t4_scenario3_noisy_and_telephone_degradation_experiment` | **FAIL** |
| 4 | `test_t4_scenario4_interactive_web_playground_full_session` | **PASS** |
| 5 | `test_t4_scenario5_custom_wav_folder_tier3_corpus_workflow` | **PASS** |
| 6 | `test_t4_scenario6_architecture_comparison_and_checkpoint_resume` | **PASS** |
| 7 | `test_t4_scenario7_decoding_strategy_and_ngram_lm_study` | **PASS** |
| 8 | `test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep` | **FAIL** |
| 9 | `test_t4_scenario9_existing_tsukinami_tts_non_regression` | **PASS** |

---

## 2. Git Status Check (TTS Non-Modification Verification)

Command: `git status --short` (exit code `0`):
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
**Confirmed**: Zero tracked files have been modified; all existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) are completely untouched.

---

## 3. Root-Cause Diagnosis

Both failures share a **single, identical root cause**: `ASREngine.transcribe(..., include_visuals=True)` returns `res["ctc_posteriors"]` as a top-K summary `dict`, whereas the E2E tests expect a **2D numeric probability matrix `(T', V)`** whose rows sum to `1.0`.

### Exact Failing Assertions
1. `tests_e2e/test_tier4_scenarios.py:131` (`test_t4_scenario3_noisy_and_telephone_degradation_experiment`):
   ```python
   assert np.isfinite(np.asarray(res["ctc_posteriors"], dtype=np.float32)).all()
   # TypeError: float() argument must be a string or a real number, not 'dict'
   ```
2. `tests_e2e/test_tier4_scenarios.py:374-379` (`test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep`):
   ```python
   post = np.asarray(res["ctc_posteriors"], dtype=np.float32)
   # TypeError: float() argument must be a string or a real number, not 'dict'
   ...
   assert post.ndim == 2 and post.shape[0] > 0 and np.isfinite(post).all()
   assert float(np.min(post)) >= -1e-4 and float(np.max(post)) <= 1.0 + 1e-4
   assert np.allclose(post.sum(axis=-1), np.ones(post.shape[0]), atol=1e-2)
   ```

### Current Implementation Cause
- In `asr/inference.py:147-189`, `_build_ctc_posteriors()` returns:
  ```python
  {"times_sec": times_sec, "top_tokens": top_tokens, "probs": probs_list}
  ```
  where `probs` is truncated to `top_k_tokens=12` columns (blank + top 11 tokens).
- In `asr/inference.py:496-500`, `ASREngine.transcribe()` assigns that `dict` directly to `result["ctc_posteriors"]`.
- Because it is a `dict` (and even its `"probs"` sub-array is top-K truncated and does not sum to `1.0` across the vocabulary), `np.asarray(res["ctc_posteriors"], dtype=np.float32)` raises `TypeError`, and row sums would also fail `np.allclose(post.sum(axis=-1), np.ones(post.shape[0]), atol=1e-2)` if truncated.

---

## 4. Concrete Fix Plan

All changes stay strictly inside `asr/` and `tests/` (never touching `tests_e2e/` or existing TTS files).

### Step 1 — `asr/inference.py`
- **Lines 147–189** (`_build_ctc_posteriors`):
  - Replace (or refactor) `_build_ctc_posteriors(log_probs, max_frames=_MAX_POSTERIOR_FRAMES)` to return a **JSON-serializable 2D full-vocabulary posterior probability matrix** `list[list[float]]` of shape `(T_vis, V)`:
    - If `t_len == 0 or vocab_size == 0`, return `[]` (consistent with `waveform: []` and `log_mel: []` on empty audio).
    - Downsample frames to at most `max_frames` (`_MAX_POSTERIOR_FRAMES = 400`) via `np.linspace(0, t_len - 1, max_frames, dtype=np.int64)` when `t_len > max_frames`.
    - Compute full-vocab probabilities: `probs_full = np.exp(np.clip(sub_lp, -700.0, 0.0))` and clip to `[0.0, 1.0]`. (Optional safety: renormalize `probs_full / np.maximum(probs_full.sum(axis=-1, keepdims=True), 1e-12)` so every row sums to `1.0` even under numerical drift.)
    - Round to **6 decimal places** (`np.round(probs_full, 6)`) — NOT 4 decimals, because with `vocab_size ~ 100+`, 4-decimal rounding can accumulate up to `~0.0055` row-sum error, whereas 6-decimal rounding guarantees row-sum error `< 1e-4 << atol=1e-2`.
    - Convert to `[[float(v) for v in row] for row in probs_rounded.tolist()]`.
- **Lines 496–500** (`ASREngine.transcribe`):
  - Assign `result["ctc_posteriors"] = _build_ctc_posteriors(log_probs_np)` (2D `list[list[float]]`).
  - Verify `json.dumps(result, ensure_ascii=False, allow_nan=False)` still passes cleanly.

### Step 2 — `asr/web/index.html`
- **Lines 1353–1405** (`drawCtcPosteriors`):
  - Update `drawCtcPosteriors()` to natively render a 2D array `post` (`Array.isArray(post)` with shape `(T, V)`):
    - If `Array.isArray(post)` and `post.length > 0 && Array.isArray(post[0]) && post[0].length > 0`:
      - Compute per-token peak probability across all frames `t = 0..T-1`.
      - Select `blankId` (`(state.info && Number.isInteger(state.info.blank_id)) ? state.info.blank_id : 0`) first, followed by top `11` non-blank token indices sorted by descending peak probability (matching the previous `top_k_tokens = 12` heatmap layout).
      - Resolve token labels from `(state.info && Array.isArray(state.info.vocab) && state.info.vocab[tid]) || ("#" + tid)`.
      - Render the exact same amber (blank) + sky-blue (non-blank) heatmap and time ticks.
    - Keep a fallback branch for the legacy `{probs, top_tokens}` object format just in case.

### Step 3 — Update Implementation-Track Unit Tests (`tests/`)
- **`tests/test_asr_cli.py`**:
  - **Lines 216–228**: Update assertions on `res_vis["ctc_posteriors"]` to check 2D `list[list[float]]` of shape `(T', engine.tokenizer.vocab_size)` with `T' > 0`, values in `[0.0, 1.0]`, and row sums `pytest.approx(1.0, abs=1e-2)`.
  - **Line 337**: Update `assert empty_res["ctc_posteriors"] == []` (matching `waveform == []` and `log_mel == []`).
- **`tests/test_asr_web.py`**:
  - **Lines 240–242**: Update assertions on `data["ctc_posteriors"]` to verify `isinstance(data["ctc_posteriors"], list)`, non-empty 2D numeric matrix with width `vocab_size`, values in `[0.0, 1.0]`, and row sums `≈ 1.0`.

### Step 4 — Verification Commands After Fix
1. `.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -v --tb=short` → expect **9/9 PASS**
2. `.venv/bin/pytest tests_e2e/ -v --tb=short` → expect **222/222 PASS** (Tiers 1–4)
3. `.venv/bin/pytest tests/ -v --tb=short` → expect **100% PASS** (M1–M6 unit tests)
4. `git status --short` → confirm zero existing TTS files modified
