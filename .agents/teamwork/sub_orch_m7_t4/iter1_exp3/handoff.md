# Explorer 3 Handoff — Tier 4 Scenarios 6–9 & Repo Health Audit

## Executive Summary
- **1 Critical Contract Mismatch Found** affecting **Scenario 8** (and also **Scenario 3**) in `tests_e2e/test_tier4_scenarios.py`:
  - `ASREngine.transcribe(..., include_visuals=True)` in `asr/inference.py:147-189,496-500` returns `res["ctc_posteriors"]` as a **`dict`** (`{"times_sec": [...], "top_tokens": [...], "probs": [[...]]}` truncated to top-12 tokens).
  - `tests_e2e/test_tier4_scenarios.py` (Scenario 3 line 131 and Scenario 8 lines 374–379) requires `res["ctc_posteriors"]` to be a **2D array-like `(T', V)` full probability matrix** directly convertible via `np.asarray(res["ctc_posteriors"], dtype=np.float32)` with `post.ndim == 2`, `0 <= post <= 1`, and `post.sum(axis=-1) ≈ 1.0` (`atol=1e-2`).
  - Calling `np.asarray(dict, dtype=np.float32)` raises `TypeError: float() argument must be a string or a real number, not 'dict'`.
- **Scenarios 6, 7, and 9**: All static code & contract checks **PASS** with zero defects found.
- **Repo Health Audit**: **CLEAN**. `git status` and `git diff --stat` confirm **zero modifications** to any existing tracked `tsukinami` TTS files, and **zero stray untracked files or runtime artifacts** exist in the repo root or under `asr/`, `tests/`, `tests_e2e/`.

---

## Detailed Scenario-by-Scenario Audit

### Scenario 6: `test_t4_scenario6_architecture_comparison_and_checkpoint_resume` (`tests_e2e/test_tier4_scenarios.py:259-308`)
- **Status**: **CLEAN (Expected PASS)**
- **Cross-checked against**: `asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, `asr/models/conformer.py`, `asr/train.py`, `asr/inference.py`, `PROJECT.md § Interface Contracts`.
- **Findings**:
  - `ModelConfig(arch=arch, n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7, dropout=0.0)` is valid for both `"cnn_bigru"` (`gru_hidden=16`) and `"conformer_lite"` (`32 % 4 == 0`, odd `conv_kernel_size=7`).
  - `train_asr` epoch 1 saves `best.pt` and `latest.pt` with `epoch=1`, `model_config`, `tokenizer`, `optimizer_state_dict`, `scheduler_state_dict`.
  - Resumed `train_asr(..., epochs=2, resume_from=cdir / "latest.pt")` (`asr/train.py:289-320`) validates `model_config` and `tokenizer.vocab_size`, restores model/optimizer/scheduler state, sets `start_epoch = 2`, runs epoch 2, and atomically writes `latest.pt` with `epoch == 2` (`int(ckpt["epoch"]) >= 2`).
  - `ConformerLiteCTC` registers `SinusoidalPositionalEncoding.pe` with `persistent=False` (`asr/models/conformer.py:28`), preventing state_dict shape mismatches on resume or inference.
  - `ASREngine.from_checkpoint(cdir / "best.pt")` loads both architectures and returns valid `{"text": str, "rtf": float >= 0.0, ...}`.

### Scenario 7: `test_t4_scenario7_decoding_strategy_and_ngram_lm_study` (`tests_e2e/test_tier4_scenarios.py:310-360`)
- **Status**: **CLEAN (Expected PASS)**
- **Cross-checked against**: `asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, `PROJECT.md § Interface Contracts`.
- **Findings**:
  - `CharNgramLM(order=3, smoothing=0.1)` (`asr/decoding.py:76-194`): `.fit(corpus)`, `.to_dict()`, `.from_dict()` preserve all counts/totals; `lm_restored.score_next("オハ", "ヨ") == pytest.approx(lm.score_next("オハ", "ヨ"))` holds exactly.
  - `ASREngine.from_checkpoint(..., lm=lm_restored)` (`asr/inference.py:234,282-290`) passes `lm` to `prefix_beam_search(..., lm=self.lm)` (`asr/inference.py:363-368`).
  - `prefix_beam_search` (`asr/decoding.py:270,284`) activates LM scoring when `lm is not None and lm_weight > 0.0` and applies `insertion_bonus * len(pref)`.
  - `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs` (`asr/metrics.py:114-243`) all return the exact keys and types asserted (`cer`, `ref_len`, `substitutions: int`, `deletions: int`, `insertions: int`, `mer`, `wer`, descending-sorted `list[tuple[str, str, int]]`).

### Scenario 8: `test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep` (`tests_e2e/test_tier4_scenarios.py:362-405`)
- **Status**: **DEFECT FOUND (Will FAIL until fixed; same root cause also breaks Scenario 3 line 131)**
- **Exact Failure Point**:
  - `tests_e2e/test_tier4_scenarios.py:374-379` (Scenario 8):
    ```python
    post = np.asarray(res["ctc_posteriors"], dtype=np.float32)
    assert post.ndim == 2 and post.shape[0] > 0 and np.isfinite(post).all()
    assert float(np.min(post)) >= -1e-4 and float(np.max(post)) <= 1.0 + 1e-4
    assert np.allclose(post.sum(axis=-1), np.ones(post.shape[0]), atol=1e-2)
    ```
  - `tests_e2e/test_tier4_scenarios.py:131` (Scenario 3):
    ```python
    assert np.isfinite(np.asarray(res["ctc_posteriors"], dtype=np.float32)).all()
    ```
- **Root Cause**:
  - In `asr/inference.py:147-189` (`_build_ctc_posteriors`) and `asr/inference.py:496-500`, `result["ctc_posteriors"]` is returned as a `dict`:
    `{"times_sec": [...], "top_tokens": [...], "probs": [[...]]}`
    containing only `top_k_tokens = 12` columns out of `vocab_size` (~90+ for `kana`).
  - Passing this `dict` to `np.asarray(..., dtype=np.float32)` raises `TypeError: float() argument must be a string or a real number, not 'dict'`.
  - Additionally, truncating to top-12 tokens would violate `post.sum(axis=-1) ≈ 1.0` (`atol=1e-2`) whenever non-top-12 tokens carry > 0.01 probability mass (especially on lightly trained / tiny models).
- **Other Assertions in Scenario 8**:
  - `waveform`: `list[float]` (`asr/inference.py:123-132`) — PASS.
  - `log_mel`: `list[list[float]]` `(T, n_mels)` (`asr/inference.py:135-144`) — PASS.
  - `vad_segments`: `list[list[float]]` (`asr/inference.py:487-493`) — PASS.
  - `redecode` latency sweep (`greedy < 10 ms` median, `beam < 50 ms` median): `ASREngine.redecode` (`asr/inference.py:505-536`) runs pure-NumPy `greedy_decode` / `prefix_beam_search` + `viterbi_align` on cached `log_probs` (~15–25 frames), expected well under `< 1 ms` (greedy) and `< 5 ms` (beam).
- **Concrete Fix Plan**:
  1. **`asr/inference.py` (`_build_ctc_posteriors`, lines 147–189, and `transcribe`, lines 496–500)**:
     - Change `_build_ctc_posteriors` to return the full 2D probability matrix `list[list[float]]` of shape `(T_vis, V)` (or `[]` when `T == 0 or V == 0`), computed from `probs_full = np.exp(np.clip(sub_lp, -700.0, 0.0))` and rounded to 5–6 decimal places (e.g., `np.round(probs_full, 5)` or `6`) so each row sums to `1.0` well within `atol=1e-2` (even for `V ≈ 100`).
     - Optionally, if helpful for UI debugging, keep a separate metadata field or let the UI derive top-K directly from the 2D matrix + `state.info.vocab` (keeping `result["ctc_posteriors"]` strictly a 2D `list[list[float]]`).
  2. **`asr/web/index.html` (`drawCtcPosteriors`, lines 1353–1405)**:
     - Update `drawCtcPosteriors()` to handle 2D array `ctc_posteriors` (`Array.isArray(post)`): compute peak probability per vocab index across frames, pick index `0` (`<blank>`) + top-11 non-blank vocab indices, label rows using `state.info.vocab[id]` (falling back to `"id:" + id`), and render the heatmap identically. (Can keep fallback support for `{probs, top_tokens}` dict if desired.)
  3. **Unit tests to align with the 2D `ctc_posteriors` contract**:
     - `tests/test_asr_cli.py:216-227` and `tests/test_asr_cli.py:337`: update assertions from `dict` (`{"times_sec", "top_tokens", "probs"}`) to 2D `list[list[float]]` `(T_vis, V)` with `0 <= p <= 1`, row sums `≈ 1.0`, and `[]` for empty audio.
     - `tests/test_asr_web.py:240-242`: update assertions from `"times_sec" in data["ctc_posteriors"]` etc. to validate `isinstance(data["ctc_posteriors"], list)` and 2D `(T_vis, V)` probabilities.
  4. **Tier 1–3 E2E Impact Check**:
     - `tests_e2e/test_tier1_features.py:1247,1401` and `tests_e2e/test_tier3_combinations.py:363` only check `"ctc_posteriors" in ...`, so changing `ctc_posteriors` to a 2D `list[list[float]]` is 100% compatible with Tiers 1–3 and fixes both Tier 4 Scenario 3 and Scenario 8.

### Scenario 9: `test_t4_scenario9_existing_tsukinami_tts_non_regression` (`tests_e2e/test_tier4_scenarios.py:407-447`)
- **Status**: **CLEAN (Expected PASS)**
- **Findings**:
  - Imports `accent`, `carve`, `kotoba`, `yomu` from `repo_root` and exercises `kotoba.to_kata`, `kotoba.split_moras`, `kotoba.tracks_from_kana`, `accent.annotate`, `accent.f0_rule`, `yomu.PRESETS`, `yomu.build_carve_rc`, `carve.make`, `carve.write`.
  - All original TTS files are completely unmodified in `git`.

---

## Repo Health Audit

### `git status --short` & `git diff --stat`
- **`git diff --stat`**: Empty (0 modified tracked files).
- **All 32 tracked files** (including `carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, `demo.html`, `ablation.html`, `watashi_demo.html`, `hitofude*.html`, `kusanagi*.html`, `README.md`, `README_EN.md`, etc.) are **100% untouched**.
- **Untracked entries in repo root**:
  - Expected project files: `.gitignore`, `PROJECT.md`, `TEST_INFRA.md`, `TEST_READY.md`, `pyproject.toml`, `asr/`, `tests/`, `tests_e2e/`, `.agents/`
  - Ignored runtime/env dirs: `.venv/`, `.pytest_cache/`, `__pycache__/`
  - **No stray temporary files** (`*.wav`, `*.pt`, `*.tmp`, `checkpoints/`, `data/`, `out/`, etc.) exist anywhere in the repo root or under `asr/`, `tests/`, `tests_e2e/`.
