# Secondary Reviewer (Reviewer 2) Handoff — Milestone M4

- **Verdict**: `APPROVE`
- **Reviewer**: Reviewer 2 (`rev_2`)
- **Milestone**: M4 — CTC Decoding, N-gram LM, Viterbi Alignment & Metrics
- **Reviewed Files**:
  - `/home/antigravity/poidowl/tsukinami/asr/decoding.py`
  - `/home/antigravity/poidowl/tsukinami/asr/metrics.py`
  - `/home/antigravity/poidowl/tsukinami/tests/test_asr_decoding.py`

---

## 1. Independent Test & Verification Results

### 1.1 Assigned Pytest Suite
Command (run from `/home/antigravity/poidowl/tsukinami`):
```bash
.venv/bin/pytest -v tests/test_asr_decoding.py
```
Exact output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 38 items

tests/test_asr_decoding.py ......................................        [100%]

============================== 38 passed in 0.25s ==============================
```

### 1.2 Latency & Torch Isolation Benchmark (`<10 ms` Redecode Readiness)
Measured `prefix_beam_search` with full `Tokenizer("kana")` (`V = 86`), `DecodeConfig(beam_width=8)`, 5 runs median after warm-up, verifying `'torch' not in sys.modules`:
```text
T= 25 rand lm=False -> median=  1.88 ms (min=1.75 ms)
T= 25 rand lm=True  -> median=  5.44 ms (min=5.36 ms)
T= 25 peak lm=False -> median=  1.88 ms (min=1.69 ms)
T= 25 peak lm=True  -> median=  6.48 ms (min=6.30 ms)
T= 50 rand lm=False -> median=  4.23 ms (min=4.10 ms)
T= 50 rand lm=True  -> median= 12.73 ms (min=12.60 ms)
T= 50 peak lm=False -> median=  4.05 ms (min=3.79 ms)
T= 50 peak lm=True  -> median= 15.26 ms (min=15.01 ms)
T= 75 rand lm=False -> median=  7.55 ms (min=7.43 ms)
T= 75 rand lm=True  -> median= 21.08 ms (min=19.89 ms)
T= 75 peak lm=False -> median=  7.37 ms (min=6.98 ms)
T= 75 peak lm=True  -> median= 26.02 ms (min=25.24 ms)
T=100 rand lm=False -> median= 11.46 ms (min=10.84 ms)
T=100 rand lm=True  -> median= 28.69 ms (min=28.10 ms)
T=100 peak lm=False -> median= 11.30 ms (min=10.37 ms)
T=100 peak lm=True  -> median= 40.32 ms (min=39.70 ms)
```
`torch` is not imported anywhere in `asr/decoding.py` or `asr/metrics.py`.

### 1.3 Ad-Hoc Edge-Case Probes (Read-Only)
Verified via read-only `.venv/bin/python -c` (no files written):
- Blank-only tokenizer (`vocab_size == 1`) with `greedy_decode` and `prefix_beam_search`: handled cleanly.
- Mixed `-inf` and `0.0` log-probs (hard one-hot paths with repeated tokens `[1, 0, 1]`): `greedy_decode`, `prefix_beam_search`, and `viterbi_align` all return exact expected outputs and `confidence == 1.0`.
- All-`-inf` frame: all three decoders/aligners cleanly raise `ValueError`.
- Tied uniform probabilities (`0.25` across all 4 tokens): `prefix_beam_search` is 100% deterministic across repeated calls.
- Real `kotoba.tracks_from_kana("キョウハ、イイテンキ")["moras"]` passed into `alignment_boundary_error` against simulated character-level `pred_align`: `matched == 9 == len(gt_moras)`, `mean_iou == 1.0`, `mean_boundary_error_ms == 0.0`.

---

## 2. Detailed Code Review Findings

### 2.1 `asr/decoding.py`
- **Numerical Stability**:
  - `_logsumexp2` safely handles `-inf` operands and uses `a + math.log1p(math.exp(b - a))` for `a >= b`, avoiding overflow and catastrophic cancellation.
  - `_prepare_log_probs` validates 2D `(T, V)` shape, `vocab_size` match, positive finite `temperature`, finite `blank_bias`, rejects `NaN`/`+inf`/all-`-inf` rows, and computes stable row-wise log-softmax in `float64`.
  - `viterbi_align` uses `float64` DP arrays and clips log-probs to `[-700.0, 0.0]` before `np.exp` when computing span confidence, clamping output to `[0.0, 1.0]`.
- **Correctness & Edge Cases**:
  - `CharNgramLM`: Properly normalized hierarchical Dirichlet / interpolated add-k backoff over `vocab ∪ {<unk>}` (probabilities sum to `<= 1.0`, strictly finite log-probs `<= 0.0`), handles unfitted/empty corpora, and round-trips through JSON cleanly via `.to_dict()` / `.from_dict()`.
  - `greedy_decode`: Correctly performs CTC collapse (deduplicating consecutive identical IDs before removing `blank_id`) and returns exact contract keys `{"text", "token_ids", "score"}`.
  - `prefix_beam_search`: Genuine CTC prefix beam search tracking `(p_b, p_nb)` per prefix with log-sum-exp merging, enforcing the repeated-token rule (self-loop from `p_nb`, repeated emission only from `p_b`, distinct emission from `lse2(p_b, p_nb)`). Self-loop retention is explicitly guaranteed even if `last_tok` falls outside the per-frame `top_k` candidates.
  - `viterbi_align`: Correctly constructs the extended CTC state sequence `[b, y_0, b, y_1, ..., y_{L-1}, b]` with `can_skip[3::2] = ext[3::2] != ext[1:-2:2]` forbidding blank-skipping between identical adjacent tokens. Enforces `T >= num_tokens + num_adjacent_repeats` and guarantees monotonic non-empty spans for every token.
- **Determinism**:
  - Pruning uses `heapq.nsmallest` with `(-score, pref, p_b, p_nb)` where `pref` is `tuple[int, ...]`, and final sorting uses `(-h["score"], h["text"])`. `greedy_decode` and `viterbi_align` use `np.argmax` (first-index tie-breaking). Fully deterministic.

### 2.2 `asr/metrics.py`
- **Levenshtein & Error Rates**:
  - `levenshtein_align` implements exact O(mn) DP with deterministic tie-breaking (`match/sub <= del <= ins`).
  - `compute_cer`, `compute_mer`, and `compute_wer` compute corpus micro-averaged error rates with exact S/D/I/ref_len breakdowns, handle `ref_len == 0` without division-by-zero (`0.0` if `errors == 0` else `1.0`), and validate sequence length parity.
  - `confusion_pairs` extracts only `"sub"` operations and sorts deterministically by `(-count, ref_tok, hyp_tok)`.
  - `compute_rtf` validates finite non-negative inputs and returns `0.0` when `audio_duration_sec == 0.0`.
- **`kotoba.split_moras` Integration**:
  - `compute_mer` directly uses `kotoba.split_moras`, properly handling hiragana-to-katakana normalization, small-kana digraph moras (e.g., `キャ` as 1 mora vs 2 chars), and pause stripping/collapsing.
  - `alignment_boundary_error` normalizes via `kotoba.to_kata` and merges consecutive small-kana tokens (`kotoba.SMALL`, excluding `_NON_MERGEABLE_PREV` and `kotoba.PAUSE`) in `pred_align`, aligning cleanly with `kotoba.tracks_from_kana` mora ground truth. IoU calculation is exact for both overlapping and disjoint intervals.

### 2.3 `tests/test_asr_decoding.py`
- High-signal 38-test suite covering all public functions, mathematical CTC prefix merging (explicitly proving merged CTC beats greedy), LM rescoring, decoding hyperparameters, Viterbi exact boundaries and repeated-token blank separation, latency budget, metrics accuracy, `kotoba.split_moras` MER vs. CER divergence, alignment boundary error (including small-kana merging), serialization, and input validation.

---

## 3. Non-Blocking Observations (Advisory Only)

1. **LM Beam-Search Latency on Longer Utterances**: Without LM, `prefix_beam_search` runs in `1.9–7.4 ms` for 1–3 s utterances (`T = 25..75`, `V = 86`, `beam_width = 8`), meeting the `<10 ms` `/api/redecode` target. With `CharNgramLM` enabled (`lm_weight > 0`), latency increases to `12.7–40.3 ms` for `T = 50..100` because `_ensure_lm` is evaluated for all `top_k = 16` candidates per frame even for very low-probability transitions. If future M5/M6 benchmarks require `<10 ms` redecode with LM enabled on 2–4 s utterances, pruning low-probability non-blank candidates (e.g., `lp_c < max_lp - 10.0`) or caching `(ctx, tok)` in `CharNgramLM` would substantially reduce LM overhead.
2. **Pause Token Normalization in `alignment_boundary_error`**: `kotoba.tracks_from_kana` normalizes all `kotoba.PAUSE` characters to `"、"` via `kotoba.split_moras`, whereas `alignment_boundary_error` only applies `kotoba.to_kata` to `pred_align` tokens (so a predicted `"。"` or `" "` pause wouldn't match a GT `"、"` pause). Minor edge case since standard kana alignments use `"、"`.
3. **Optional Kwarg Test Coverage**: `compute_cer(..., normalize_kana=True)`, `compute_mer(..., ignore_pauses=True)`, and `confusion_pairs(..., unit="mora"|"word")` are clean bonus options beyond `SCOPE.md`; adding tests for them later would further harden coverage.

---

## 4. Verdict

**`APPROVE`** — All Milestone M4 scope requirements, interface contracts, numerical stability invariants, determinism guarantees, `kotoba.split_moras` integrations, and unit tests pass cleanly with zero blocking issues.
