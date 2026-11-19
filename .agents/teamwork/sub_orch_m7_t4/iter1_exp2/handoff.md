# Explorer 2 Handoff — Tier 4 Scenarios 1–5 Code & Contract Audit

## Summary
Audited `tests_e2e/test_tier4_scenarios.py` Scenarios 1–5 (plus cross-checked Scenario 8 where the same `ctc_posteriors` contract appears) against `asr/__main__.py`, `asr/inference.py`, `asr/server.py`, `asr/web/index.html`, `asr/synth_data.py`, `asr/dataset.py`, `asr/audio.py`, `asr/metrics.py`, and `PROJECT.md § Interface Contracts`.

**Result**: Found **1 definite P0 contract mismatch bug** that breaks Scenario 3 (and Scenario 8). Scenarios 1, 2, 4, and 5 are clean and contract-compliant.

---

## Definite Bug (P0)

### 1. `ASREngine.transcribe(..., include_visuals=True)["ctc_posteriors"]` returns a `dict` instead of a 2D `(T', V)` probability matrix
- **Affected E2E tests** (read-only):
  - `tests_e2e/test_tier4_scenarios.py:131` (Scenario 3 — `test_t4_scenario3_noisy_and_telephone_degradation_experiment`):
    ```python
    assert np.isfinite(np.asarray(res["ctc_posteriors"], dtype=np.float32)).all()
    ```
  - `tests_e2e/test_tier4_scenarios.py:374-379` (Scenario 8 — `test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep`):
    ```python
    post = np.asarray(res["ctc_posteriors"], dtype=np.float32)
    assert post.ndim == 2 and post.shape[0] > 0 and np.isfinite(post).all()
    assert float(np.min(post)) >= -1e-4 and float(np.max(post)) <= 1.0 + 1e-4
    assert np.allclose(post.sum(axis=-1), np.ones(post.shape[0]), atol=1e-2)
    ```
- **Root cause**:
  - `asr/inference.py:147-189` (`_build_ctc_posteriors`) and `asr/inference.py:496-500` return a `dict` `{"times_sec": [...], "top_tokens": [...], "probs": [...]}` containing only the top-12 tokens.
  - Passing this `dict` to `np.asarray(..., dtype=np.float32)` raises `TypeError: float() argument must be a string or a real number, not 'dict'`.
  - Furthermore, Scenario 8 requires `post.sum(axis=-1)` to equal `1.0` (`atol=1e-2`), which requires the full `(T', V)` vocabulary posterior distribution `exp(log_probs)`, not a top-K subset.
- **No other E2E test expects a `dict`**:
  - Checked all `ctc_posteriors` references in `tests_e2e/`:
    - `test_tier1_features.py:1247, 1401` and `test_tier3_combinations.py:363` and `test_tier4_scenarios.py:191` only check key presence / non-None.
    - `test_tier4_scenarios.py:131, 374-379` require a 2D numeric `(T', V)` probability array whose rows sum to `1.0`.
- **Concrete Fix Plan**:
  1. **`asr/inference.py:147-189, 496-500`**:
     - Update `_build_ctc_posteriors(log_probs, max_frames=_MAX_POSTERIOR_FRAMES)` to return a 2D `list[list[float]]` of shape `(T_vis, V)` with full posterior probabilities `probs = np.exp(np.clip(sub_lp, -700.0, 0.0))` (re-normalized or rounded to 6 decimal places via `np.round(probs, 6)` so row sums stay within `~6e-5 << 1e-2` of `1.0`, and values stay in `[0.0, 1.0]`).
     - Return `[]` when `log_probs.shape[0] == 0` or `vocab_size == 0`.
  2. **`asr/web/index.html:1353-1405` (`drawCtcPosteriors`)**:
     - Support 2D array `Array.isArray(post)` (shape `[T][V]`): pick `blank_id` (0) + top 11 non-blank tokens by peak probability across frames, look up labels from `state.info && state.info.vocab` (falling back to `"<blank>"` / `"#" + id`), and render the heatmap identically. Keep the legacy `{probs, top_tokens, times_sec}` object path as a fallback.
  3. **Implementation-track unit tests**:
     - Update `tests/test_asr_cli.py:216-228` and `tests/test_asr_cli.py:337` to assert the 2D `list[list[float]]` `(T', V)` shape, `[0, 1]` bounds, row sums `≈ 1.0`, and `[]` on empty audio.
     - Update `tests/test_asr_web.py:240-242` to assert `isinstance(data["ctc_posteriors"], list)` and valid 2D `(T', V)` posterior rows instead of checking `times_sec`/`top_tokens`/`probs` keys.

---

## Scenario-by-Scenario Audit (Scenarios 1–5)

| Scenario | Test Function | Status | Findings |
|----------|---------------|--------|----------|
| **Scenario 1** | `test_t4_scenario1_one_command_cpu_quickstart_demo` (`:21-52`) | **PASS expected** | `_cmd_demo` (`asr/__main__.py:126-205`) supports `--out-dir`, `--epochs`, `--num-train`, `--arch`; writes `data/{train,val}.jsonl`, `best.pt`, `latest.pt`; prints `"Val CER:"` and `"CER"` to stdout; 16 train / 12 val / 2 epochs fits easily within 180s timeout under `OMP_NUM_THREADS=2`. |
| **Scenario 2** | `test_t4_scenario2_multi_preset_tsukinami_roundtrip_and_alignment` (`:55-97`) | **PASS expected** | All 5 presets (`default`, `ossan`, `robot`, `whisper`, `chibi`) exist in `yomu.PRESETS`; `synthesize_tsukinami` returns finite 1D `float32` 16 kHz audio + normalized `moras`; `alignment_boundary_error` handles empty or non-empty `pred_align`; distinct presets produce acoustically distinct waveforms. |
| **Scenario 3** | `test_t4_scenario3_noisy_and_telephone_degradation_experiment` (`:100-141`) | **FAIL (P0 bug)** | Fails at line 131: `np.asarray(res["ctc_posteriors"], dtype=np.float32)` raises `TypeError` because `ctc_posteriors` is a `dict`. All other checks (`apply_corruption` white/pink/telephone, `extract_log_mel` raw/cmvn, `detect_vad`, high-freq attenuation on top 12 Mel bins) are sound. |
| **Scenario 4** | `test_t4_scenario4_interactive_web_playground_full_session` (`:143-193`) | **PASS expected** | `GET /` serves zero-CDN HTML with 5 `<canvas>` elements; `GET /api/health` returns exact `{"status": "ok", "model_loaded": True}`; `GET /api/info` returns dict; `POST /api/tts-roundtrip`, `POST /api/redecode` (4 sweep configs), and multipart `POST /api/transcribe` match Pydantic schemas (`extra="forbid"`) and return all required keys. |
| **Scenario 5** | `test_t4_scenario5_custom_wav_folder_tier3_corpus_workflow` (`:195-256`) | **PASS expected** | `synthesize_fast_kotoba` handles `sr=22050`; `save_wav` creates parent dirs; `build_manifest_from_wav_dir` matches filenames and resamples 22.05→16 kHz; `ASRManifestDataset` + `collate_asr_batch` + `train_asr` + `ASREngine.from_checkpoint` + `compute_cer`/`compute_wer` all align with contracts. |
