# Secondary Reviewer Handoff — M7 Phase 1 Tier 4 E2E (`sub_orch_m7_t4` / `iter1_rev2`)

## Verdict: **APPROVE**

All 154/154 unit tests in `tests/` pass, code and interface contracts across `asr/inference.py`, `asr/web/index.html`, `tests/test_asr_cli.py`, and `tests/test_asr_web.py` are consistent with `tests_e2e/test_tier4_scenarios.py` and `PROJECT.md § Interface Contracts`, numerical and JS edge cases are handled safely, and no protected TTS or `tests_e2e/` files were modified.

---

## 1. Target-Scoped Unit Test Verification

- **Command**: `.venv/bin/pytest tests/ -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Duration**: `195.22s` (`0:03:15`)
- **Result**: `154 passed, 2 warnings` (0 failed, 0 skipped, 0 errors)
  - `tests/test_asr_cli.py`: 16 passed
  - `tests/test_asr_data.py`: 20 passed
  - `tests/test_asr_decoding.py`: 38 passed
  - `tests/test_asr_dsp.py`: 45 passed
  - `tests/test_asr_models.py`: 17 passed
  - `tests/test_asr_web.py`: 18 passed
- **Note**: `tests_e2e/` was intentionally not executed (owned by Primary Reviewer).

---

## 2. Code Inspection & Cross-Check

### `asr/inference.py` (`_build_ctc_posteriors` & `ASREngine.transcribe`)
- `_build_ctc_posteriors(log_probs, *, max_frames=400) -> list[list[float]]` (L146–L177):
  - Guards non-2D arrays (`ndim != 2`) and empty dimensions (`T == 0` or `V == 0`), returning `[]`.
  - Downsamples frames evenly via `np.linspace(0, t_len - 1, max_frames, dtype=np.int64)` when `T > 400`.
  - Converts to `float64`, replaces non-finite values (`-inf`, `+inf`, `NaN`) with `-700.0`, subtracts row-wise max, clips shifted logits to `[-700.0, 0.0]`, exponentiates, normalizes rows to sum to `1.0` (with uniform `1.0 / V` fallback if `row_sums <= 0.0`), clips to `[0.0, 1.0]`, rounds to 6 decimal places, and returns pure Python `list[list[float]]`.
  - Worst-case rounding drift for `V ≈ 100` is `~5e-5`, well inside both unit (`atol=1e-4`) and Tier 4 E2E (`atol=1e-2`) tolerances.
- `ASREngine.transcribe(..., include_visuals=True)` (L420–L487):
  - Empty audio produces `log_probs_np` of shape `(0, vocab_size)` -> `ctc_posteriors == []`.
  - Non-empty audio produces `(T_vis, vocab_size)` posteriors matching `tests_e2e/test_tier4_scenarios.py` (Scenarios 3, 4, 8) and `PROJECT.md § Interface Contracts`.

### `asr/web/index.html` (`drawCtcPosteriors`)
- `drawCtcPosteriors()` (L1353–L1443):
  - Natively consumes 2D `(T, V)` arrays: computes per-token peak probability across frames, selects `blankId` (from `state.info.blank_id`, validated within `[0, V)`, defaulting to `0`) plus up to 11 highest-peak non-blank tokens, resolves labels from `state.info.vocab` with `"<blank>"` / `"#<id>"` fallbacks, and slices per-frame probabilities safely.
  - Retains fallback support for the legacy `{probs, top_tokens}` format.
  - Handles `null`, `undefined`, `[]`, `[[]]`, missing `state.info`, `V == 1`, and ragged/non-numeric row entries without throwing.
  - Checked all other occurrences of `ctc_posteriors` in `asr/web/index.html` (L850, L1355, L1805, L1879) — no stale references to `{probs, top_tokens}` remain.

### `tests/test_asr_cli.py` & `tests/test_asr_web.py`
- `test_engine_transcribe_include_visuals` (L216–L225): validates 2D shape `(T', vocab_size)`, finiteness, `[0.0, 1.0]` bounds, row sums (`atol=1e-4`), and strict `json.dumps(..., allow_nan=False)`.
- `test_engine_empty_short_and_invalid_inputs` (L335, L352–L360): validates `empty_res["ctc_posteriors"] == []` and non-empty `short_res["ctc_posteriors"]` invariants.
- `test_transcribe_multipart_with_and_without_visuals` (L240–L250): validates `/api/transcribe` `ctc_posteriors` 2D shape against `/api/info`'s `vocab_size`, bounds, finiteness, and row-sum normalization (`atol=1e-4`).

---

## 3. Isolated Edge-Case Probes (Staged in Temp Dir & Removed)

Executed isolated Python and Node.js probes in `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` (cleaned up via `trap`):
- **Python (`_build_ctc_posteriors`)**: Verified `empty_t (0,10)`, `empty_v (5,0)`, `1d`, `3d`, `all_neginf`, `all_nan`, `all_posinf`, `mixed` finite+`-inf`/`NaN`, `downsample (1000,12) -> (400,12)`, `single_vocab (4,1)`, and strict `json.dumps(..., allow_nan=False)`. Result: `PY_PROBE_OK`.
- **Node.js (`drawCtcPosteriors`)**: Verified `null`/`undefined`/`[]`/`[[]]`/`{}` empty placeholders, 2D array with `state.info = null`, 2D array with 15 tokens selecting `<blank>` + top 11 = 12 rows in peak order, `V == 1`, ragged rows containing `null`/`NaN`, and legacy `{probs, top_tokens}` format. Result: `JS_PROBE_OK`.

---

## 4. Repository Integrity Check

- `git status --short` confirms zero tracked `tsukinami` TTS files were modified and `tests_e2e/` was not altered.
