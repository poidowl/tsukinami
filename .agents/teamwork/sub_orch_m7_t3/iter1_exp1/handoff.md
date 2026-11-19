# Explorer Handoff — M7 Phase 1: Tier 3 E2E (`test_tier3_combinations.py`)

## Summary
- **Result**: **12/12 PASSED** (0 failed, 0 errors, 0 skipped, 0 xfailed) across two consecutive runs.
- **Wall-Clock Duration**:
  - Run 1 (`.venv/bin/pytest tests_e2e/test_tier3_combinations.py -v`): **22.47s**
  - Run 2 (`.venv/bin/pytest tests_e2e/test_tier3_combinations.py -vv -o addopts="" --durations=0`): **21.50s**
  - Well within the `TEST_INFRA.md` budget of `~20–35 s`.
- **Warnings**: 1 benign third-party warning (`StarletteDeprecationWarning` from `fastapi/testclient.py:1`), zero warnings originating from `asr/`.
- **Git Status**: Zero existing tracked `tsukinami` TTS files modified (`git diff --stat` is empty).
- **Fix Plan Needed?**: **No** — all 12 Tier 3 cross-feature combination tests pass deterministically on the first try. Ready for combined regression guard verification (`tests/` + Tiers 1–3) and audit.

---

## 1. Exact Test Output — Run 1 (Requested Command)

Command:
```bash
.venv/bin/pytest tests_e2e/test_tier3_combinations.py -v
```

Output (exit code `0`):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 12 items

tests_e2e/test_tier3_combinations.py ............                        [100%]

=============================== warnings summary ===============================
tests_e2e/test_tier3_combinations.py::test_t3_api_tts_roundtrip_corruption_redecode_and_info
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 12 passed, 1 warning in 22.47s ========================
```
*(Note: `pyproject.toml` sets `addopts = "-q"`, which suppresses per-test names when only `-v` is passed.)*

---

## 2. Exact Test Names & Per-Test Timings — Run 2 (Reproducibility Check)

Command:
```bash
.venv/bin/pytest tests_e2e/test_tier3_combinations.py -vv -o addopts="" --durations=0
```

Output (exit code `0`, **12 passed, 1 warning in 21.50s**):

| # | Test Name (`tests_e2e/test_tier3_combinations.py::...`) | Status | Call Duration | Setup Duration |
|---:|---|---|---:|---:|
| 1 | `test_t3_corruption_noise_features_and_vad` | PASSED | 0.08s | 0.00s |
| 2 | `test_t3_corruption_speed_bandlimit_gain_features` | PASSED | 0.01s | 0.00s |
| 3 | `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug` | PASSED | 1.01s | 0.00s |
| 4 | `test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate` | PASSED | 0.00s | 0.09s |
| 5 | `test_t3_tsukinami_presets_cache_wav_io_logmel` | PASSED | 6.36s | 0.00s |
| 6 | `test_t3_cnn_bigru_train_checkpoint_and_resume` | PASSED | 1.42s | 0.00s |
| 7 | `test_t3_conformer_lite_train_checkpoint_and_forward` | PASSED | 0.29s | 0.00s |
| 8 | `test_t3_model_logprobs_greedy_beam_lm_and_viterbi` | PASSED | 0.02s | 0.42s |
| 9 | `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics` | PASSED | 0.02s | 0.00s |
| 10 | `test_t3_engine_transcribe_visuals_corruption_and_redecode` | PASSED | 0.02s | 0.01s |
| 11 | `test_t3_cli_pipeline_generate_train_eval_transcribe` | PASSED | 11.30s | 0.00s |
| 12 | `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | PASSED | 0.03s | 0.37s |

All teardowns were `0.00s`.

---

## 3. Warnings & Flakiness Assessment
- **Warnings**: Only 1 warning appeared in both runs:
  - `StarletteDeprecationWarning: Using 'httpx' with 'starlette.testclient' is deprecated; install 'httpx2' instead.` at `.venv/lib/python3.11/site-packages/fastapi/testclient.py:1` during `test_t3_api_tts_roundtrip_corruption_redecode_and_info`.
  - This is an upstream Starlette/FastAPI packaging deprecation notice and is completely unrelated to `asr/` logic. No `RuntimeWarning`, `UserWarning`, PyTorch warning, NumPy NaN/divide-by-zero warning, or resource leak warning occurred.
- **Flakiness**: None observed. Both consecutive runs passed all 12 tests with consistent timing (`22.47s` vs `21.50s`).

---

## 4. Repository Cleanliness (`git status --short` & `git diff --stat`)

Command: `git status --short`
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

Command: `git diff --stat`
```text
(no output — 0 tracked files modified)
```

- **Confirmed**: No existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) have been modified.
- All changes are strictly additive untracked files/directories belonging to Tsukinami ASR and teamwork state.
