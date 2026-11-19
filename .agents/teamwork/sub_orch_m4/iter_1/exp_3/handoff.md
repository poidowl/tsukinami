# Explorer 3 Handoff: Test & Edge-Case Plan for Milestone M4 (`tests/test_asr_decoding.py`)

## 1. Codebase Conventions Observed

Inspected `tests/test_asr_dsp.py`, `pyproject.toml`, `asr/config.py`, `asr/tokenizer.py`, `asr/__init__.py`, and `kotoba.py`:

- **Test runner & config (`pyproject.toml`)**:
  - `pytest>=8.0` via `.venv/bin/pytest`, `pythonpath = ["."]`, `testpaths = ["tests"]`, `addopts = "-q"`.
  - Pure unit tests; no external downloads, no GPU, deterministic seeds where randomness is used.
- **Test style (`tests/test_asr_dsp.py`)**:
  - `from __future__ import annotations`, section banner comments (`# --- ... ---`), plain `test_*` functions (and `@pytest.mark.parametrize` for validation matrices).
  - Small private helper functions at top of module (e.g., `_make_log_probs`, `_sharp_log_probs`).
  - Uses `np.testing.assert_allclose`, `pytest.approx`, `pytest.raises(ValueError, ...)`.
  - Verifies JSON round-trips with `json.loads(json.dumps(obj.to_dict()))`.
- **M1 interface contracts used by M4**:
  - `DecodeConfig(method="beam", beam_width=8, temperature=1.0, blank_bias=0.0, lm_weight=0.0, insertion_bonus=0.0)` — validates `beam_width >= 1`, `temperature > 0`, `lm_weight >= 0`, finite floats.
  - `Tokenizer(mode="kana"|"phoneme"|"ascii", vocab=None)` — `blank_id == 0`, `vocab[0] == "<blank>"`; default `kana` has `vocab_size == 86`, `phoneme` has `29` (space-joined in `decode`), `ascii` has `42`. Custom vocab auto-prepends `<blank>` at index `0` (great for compact 3-5 token synthetic tests!).
  - `kotoba.split_moras(text)` — converts hiragana to katakana, merges small kana (`キャ`, `キョ`, `シャ`, etc.) into single moras, collapses consecutive pauses into `'、'`, strips trailing `'、'`.

---

## 2. Helper Fixtures / Builders for `tests/test_asr_decoding.py`

Define lightweight, deterministic helper builders at the top of `tests/test_asr_decoding.py`:

1. `_tiny_tokenizer() -> Tokenizer`:
   - `Tokenizer("kana", vocab=["ア", "イ", "ウ"])` → `vocab == ["<blank>", "ア", "イ", "ウ"]`, `vocab_size == 4`, `blank_id == 0`.
2. `_log_probs_from_probs(probs: Sequence[Sequence[float]]) -> np.ndarray`:
   - Converts a `(T, V)` probability matrix into `float32` log-probabilities `np.log(np.asarray(probs, dtype=np.float64)).astype(np.float32)` after asserting rows sum to ~1.0.
3. `_sharp_log_probs(frame_token_ids: Sequence[int], vocab_size: int, peak_prob: float = 0.95) -> np.ndarray`:
   - Builds `(T, vocab_size)` `float32` log-probabilities where each frame `t` puts `peak_prob` on `frame_token_ids[t]` and distributes `(1 - peak_prob) / (vocab_size - 1)` uniformly across all other classes. Guarantees exact log-softmax normalization (`np.allclose(np.exp(lp).sum(axis=-1), 1.0)`).

---

## 3. Detailed Test Plan (`tests/test_asr_decoding.py`)

### Section 1: `CharNgramLM` Tests

| Test Function | What It Verifies | Key Assertions & Concrete Inputs |
|---|---|---|
| `test_char_ngram_lm_fit_and_log_prob_validity` | Fitting, log-prob bounds, ranking of seen vs unseen n-grams | Fit `CharNgramLM(order=3, smoothing=0.1)` on `["アイウ", "アイウ", "アイエ", "カキク"]`. Assert `score_next(prefix, tok)` is finite and `<= 0.0` for all tested pairs. Assert `score_next("アイ", "ウ") > score_next("アイ", "エ") > score_next("アイ", "カ")` (seen twice > seen once > unseen). Over the LM's known symbol set, `sum(math.exp(lm.score_next("アイ", c)) for c in vocab) <= 1.0 + 1e-6`. |
| `test_char_ngram_lm_orders_1_2_3` | Order-specific context window (`order=1`, `2`, `3`) | Corpus `["アイウ", "カイエ"]`:<br>- `order=1`: context ignored → `score_next("アイ", "ウ") == pytest.approx(score_next("カイ", "ウ"))`.<br>- `order=2`: uses last 1 char (`"イ"`), so `"アイ"` and `"カイ"` yield identical scores for `"ウ"`, while `"ア"` vs `"イ"` differ (`score_next("ア", "イ") > score_next("ア", "ウ")`).<br>- `order=3`: uses last 2 chars → `score_next("アイ", "ウ") > score_next("カイ", "ウ")` and `score_next("カイ", "エ") > score_next("アイ", "エ")`. |
| `test_char_ngram_lm_smoothing_effect` | Smoothing strength flattens distribution | Fit two LMs on `["アイウ"] * 10` with `smoothing=0.01` vs `smoothing=5.0`. Assert `(lm_low.score_next("アイ", "ウ") - lm_low.score_next("アイ", "カ")) > (lm_high.score_next("アイ", "ウ") - lm_high.score_next("アイ", "カ"))`. |
| `test_char_ngram_lm_empty_corpus_and_unfitted` | Edge cases: unfitted LM, `fit([])`, `fit(["", ""])`, unseen prefix/token | Both unfitted `CharNgramLM()` and `lm.fit([])` return finite `float <= 0.0` for `score_next("", "ア")` and `score_next("アイ", "ウ")` without raising `ZeroDivisionError` or returning `NaN`/`-inf`. |
| `test_char_ngram_lm_serialization_roundtrip` | `to_dict()` / `from_dict()` exact JSON round-trip | Fit on `["ワタシ、ニホンゴ", "ワタシ、キョウ"]`, serialize via `json.loads(json.dumps(lm.to_dict()))`, restore via `CharNgramLM.from_dict(...)`. Assert exact equality of `order`, `smoothing`, and `score_next(p, t)` within `1e-12` across seen, unseen, and empty prefixes. Also test round-trip of an empty/unfitted LM. |
| `test_char_ngram_lm_validation` | Invalid constructor args | `@pytest.mark.parametrize`: `order=0`, `order=-1`, `smoothing=0.0`, `smoothing=-0.5`, `smoothing=float("nan")` raise `ValueError`. |

---

### Section 2: `greedy_decode` Tests

| Test Function | What It Verifies | Key Assertions & Concrete Inputs |
|---|---|---|
| `test_greedy_decode_ctc_collapse_and_repeats` | Collapse of consecutive repeats + blanks; `A _ A -> AA` vs `A A -> A` | Using `_tiny_tokenizer()` (`0=<blank>, 1=ア, 2=イ, 3=ウ`):<br>- `[1, 1, 0, 2, 2, 2, 0]` → `text == "アイ"`, `token_ids == [1, 2]`.<br>- `[1, 0, 1]` → `text == "アア"`, `token_ids == [1, 1]`.<br>- `[1, 1, 1]` → `text == "ア"`, `token_ids == [1]`.<br>- `score` is finite, `<= 0.0`, and equals `float(np.sum(np.max(lp, axis=-1)))` when `temperature=1.0, blank_bias=0.0`. |
| `test_greedy_decode_temperature_and_blank_bias` | Temperature scaling & `blank_bias` effects | - **Temperature**: On `_sharp_log_probs([1, 0, 2], 4, peak_prob=0.8)`, `temperature=0.5` produces higher (closer to 0) `score` than `temperature=1.0`, which produces higher `score` than `temperature=2.0`, while `text` remains `"アイ"`.<br>- **Positive `blank_bias`**: `blank_bias=+20.0` on non-blank posteriors collapses output to `text == ""`, `token_ids == []`.<br>- **Negative `blank_bias`**: On frames with `P(blank)=0.6, P(ア)=0.3, P(イ)=0.05, P(ウ)=0.05`, `blank_bias=0.0` yields `""`, while `blank_bias=-5.0` yields `"ア"`. |
| `test_greedy_decode_edge_cases_and_modes` | `T=0`, all-blank, invalid shapes/args, phoneme/ascii modes | - `np.empty((0, 4), dtype=np.float32)` → `{"text": "", "token_ids": [], "score": 0.0}`.<br>- All-blank `[0, 0, 0, 0]` → `text == ""`, `token_ids == []`, `score <= 0.0`.<br>- `Tokenizer("phoneme")` produces space-separated phoneme string (e.g., `"k a"`).<br>- Invalid `log_probs` (1D, 3D, or `V != tokenizer.vocab_size`) or `temperature <= 0` raises `ValueError`. |

---

### Section 3: `prefix_beam_search` Tests

| Test Function | What It Verifies | Key Assertions & Concrete Inputs |
|---|---|---|
| `test_prefix_beam_search_matches_greedy_beam1` | Equivalence to greedy on sharp posteriors when `beam_width=1, lm_weight=0, insertion_bonus=0` | Run on `_sharp_log_probs([0, 1, 1, 0, 1, 0, 2, 2], 4, peak_prob=0.95)` (`"アアイ"`). Assert `hyps[0]["text"] == greedy["text"] == "アアイ"`, `len(hyps) == 1`, `hyps[0]["lm_score"] == 0.0`. |
| `test_prefix_beam_search_genuine_ctc_prefix_merging` | **Critical**: Proves genuine CTC prefix merging (beats both greedy AND naive non-merging beam search) | Exact hand-verified `T=2, V=3` matrix (`Tokenizer("kana", vocab=["ア", "イ"])`, `0=<blank>, 1=ア, 2=イ`):<br>`probs = [[0.30, 0.34, 0.36], [0.44, 0.42, 0.14]]`<br>`lp = _log_probs_from_probs(probs)`<br>Analytical ground truth:<br>- Greedy argmax path: `[イ, _]` → `"イ"` (`0.36 * 0.44 = 0.1584`).<br>- Single best path for `"ア"`: `[ア, _]` (`0.34 * 0.44 = 0.1496 < 0.1584`, so naive beam search also picks `"イ"`!).<br>- Merged CTC `P("ア") = 0.34*0.44 + 0.30*0.42 + 0.34*0.42 = 0.4184` (`log = -0.871317`).<br>- Merged CTC `P("イ") = 0.36*0.44 + 0.30*0.14 + 0.36*0.14 = 0.2508` (`log = -1.383100`).<br>Assertions:<br>- `greedy_decode(lp, tok)["text"] == "イ"`<br>- `hyps = prefix_beam_search(lp, tok, DecodeConfig(beam_width=5))`<br>- `hyps[0]["text"] == "ア"`<br>- `hyps[0]["acoustic_score"] == pytest.approx(math.log(0.4184), abs=1e-5)`<br>- Hypothesis for `"イ"` exists with `acoustic_score == pytest.approx(math.log(0.2508), abs=1e-5)`. |
| `test_prefix_beam_search_lm_rescoring` | Ambiguous acoustics resolved by `CharNgramLM` when `lm_weight > 0` | `tok = Tokenizer("kana", vocab=["カ", "キ", "ク"])` (`0=_, 1=カ, 2=キ, 3=ク`).<br>Construct `T=3` posteriors: frame 0 sharp on `カ` (`0.94`), frame 1 blank (`0.94`), frame 2 ambiguous `P(キ)=0.48, P(ク)=0.44, P(_)=0.04, P(カ)=0.04`.<br>Fit `CharNgramLM(order=2, smoothing=0.05)` on `["カク"] * 30`.<br>- With `lm_weight=0.0`: `hyps[0]["text"] == "カキ"`, `hyps[0]["lm_score"] == 0.0`.<br>- With `lm_weight=1.0`: `hyps[0]["text"] == "カク"`, `hyps[0]["lm_score"] < 0.0`, and for every hyp `h`: `h["score"] == pytest.approx(h["acoustic_score"] + 1.0 * h["lm_score"], abs=1e-5)`. |
| `test_prefix_beam_search_insertion_bonus_temp_blank_bias` | Effects of `insertion_bonus`, `temperature`, `blank_bias` | - **`insertion_bonus`**: On `T=2` ambiguous frames `[[0.52, 0.44, 0.02, 0.02], [0.52, 0.02, 0.44, 0.02]]`: `insertion_bonus=0.0` favors `""` (or shorter); `insertion_bonus=+2.0` yields longer `"アイ"` as top-1; `insertion_bonus=-3.0` yields `""` as top-1.<br>- **`blank_bias`**: `+20.0` → top-1 `""`; `-20.0` → non-empty top-1.<br>- **`temperature`**: `0.5` vs `2.0` shifts `acoustic_score` monotonically on sharp posteriors. |
| `test_prefix_beam_search_output_invariants_and_edges` | Sorting, beam width cap, score formula, `T=0`, all-blank, invalid shapes | - `1 <= len(hyps) <= cfg.beam_width`.<br>- Strictly/weakly descending: `all(hyps[i]["score"] >= hyps[i+1]["score"] - 1e-12 for i in range(len(hyps)-1))`.<br>- Score identity: `h["score"] == pytest.approx(h["acoustic_score"] + cfg.lm_weight * h["lm_score"] + cfg.insertion_bonus * len(h["text"]), abs=1e-5)` (on kana single-char tokens).<br>- `T=0` (`np.empty((0, 4), np.float32)`) → returns 1 hyp with `text == ""`, `score == 0.0`, `acoustic_score == 0.0`, `lm_score == 0.0`.<br>- All-blank → top-1 `text == ""`.<br>- Wrong `ndim` or `V != vocab_size` → `ValueError`. |
| `test_prefix_beam_search_latency` | Latency budget for interactive `/api/redecode` | `tok = Tokenizer("kana")` (`V=86`), `rng = np.random.default_rng(0)`, `logits = rng.standard_normal((100, tok.vocab_size)).astype(np.float32)`, convert to log-softmax `lp`, `cfg = DecodeConfig(beam_width=8)`. Run 1 warm-up call, then time 1 call with `time.perf_counter()`. Assert `elapsed < 0.05` (50 ms CI-safe ceiling; target `< 10 ms` in warm Python). |

---

### Section 4: `viterbi_align` Tests

| Test Function | What It Verifies | Key Assertions & Concrete Inputs |
|---|---|---|
| `test_viterbi_align_exact_boundaries` | Exact frame boundary & confidence recovery on synthetic posteriors | `tok = _tiny_tokenizer()`, `frame_stride_ms = 40.0` (0.04 s/frame).<br>Build `T=10` sharp posteriors (`peak_prob=0.96`): frames `0..1` blank, `2..3` `ア`, `4` blank, `5..7` `イ`, `8..9` blank.<br>Call `viterbi_align(lp, [1, 2], tok, frame_stride_ms=40.0)`.<br>Assert `len(align) == 2`:<br>- `align[0]`: `token == "ア"`, `start_sec == pytest.approx(0.08)`, `end_sec == pytest.approx(0.16)`, `0.9 < confidence <= 1.0`.<br>- `align[1]`: `token == "イ"`, `start_sec == pytest.approx(0.20)`, `end_sec == pytest.approx(0.32)`, `0.9 < confidence <= 1.0`. |
| `test_viterbi_align_repeated_adjacent_tokens` | Repeated identical tokens (`AA`) enforce mandatory blank separation | `T=6`, `frame_stride_ms=40.0`: frames `0..1` `ア`, frame `2` blank, frames `3..4` `ア`, frame `5` blank.<br>Call `viterbi_align(lp, [1, 1], tok, frame_stride_ms=40.0)`.<br>Assert `len(align) == 2`, both `token == "ア"`, `align[0]["start_sec"] == pytest.approx(0.0)`, `align[0]["end_sec"] == pytest.approx(0.08)`, `align[1]["start_sec"] == pytest.approx(0.12)`, `align[1]["end_sec"] == pytest.approx(0.20)`, and `align[0]["end_sec"] < align[1]["start_sec"]`. |
| `test_viterbi_align_monotonicity_and_confidence_noisy` | Monotonicity & `(0, 1]` confidence on noisy random posteriors | Random log-softmax `(30, 4)` with `rng = np.random.default_rng(7)`, `token_ids = [1, 2, 2, 3, 1]`.<br>Assert `len(align) == 5`, for each span `0.0 <= start_sec < end_sec <= 30 * 0.04 + 1e-9` and `0.0 < confidence <= 1.0`, and for all `i`: `align[i]["end_sec"] <= align[i+1]["start_sec"] + 1e-9`. |
| `test_viterbi_align_edge_cases` | Empty `token_ids`, `T=0`, `T` shorter than minimum required frames, invalid args | - `token_ids = []` (both `T=5` and `T=0`) → returns `[]`.<br>- `T < min_frames` (e.g., `T=0` with `[1]`, `T=1` with `[1, 2]`, or `T=2` with `[1, 1]` where minimum is 3 frames due to mandatory blank): **contract note below** — test expects either `ValueError` or `[]` (recommend raising `ValueError` for impossible alignments when `len(token_ids) > 0`, and returning `[]` for `len(token_ids) == 0`; align with Implementer).<br>- Invalid `frame_stride_ms <= 0`, `blank_id` in `token_ids`, out-of-range `token_id`, or bad `log_probs` shape → `ValueError`. |

---

### Section 5: `asr/metrics.py` Tests

| Test Function | What It Verifies | Key Assertions & Concrete Inputs |
|---|---|---|
| `test_levenshtein_sdi_exactness` | Exact S/D/I breakdown on hand-verified pairs (tested directly if `levenshtein_sdi`/`edit_distance_sdi` is exposed, and via `compute_cer`) | - `("abc", "abc")` → `S=0, D=0, I=0`<br>- `("abc", "axc")` → `S=1, D=0, I=0`<br>- `("abc", "ac")` → `S=0, D=1, I=0`<br>- `("ac", "abc")` → `S=0, D=0, I=1`<br>- `("kitten", "sitting")` → `S=2, D=0, I=1` (total=3)<br>- `("", "abc")` → `S=0, D=0, I=3`<br>- `("abc", "")` → `S=0, D=3, I=0` |
| `test_compute_cer` | Exact match, S/D/I, micro-averaging, Japanese kana, empty refs, length mismatch | - Exact match: `compute_cer(["ワタシ、ニホンゴ"], ["ワタシ、ニホンゴ"])` → `cer == 0.0, S=D=I=0, ref_len=8`.<br>- Micro-averaging: `refs=["ア", "アイウエオ"]` (lengths 1 and 5, total 6), `hyps=["イ", "アイウエオ"]` (1 sub) → `cer == pytest.approx(1/6)` (not macro-avg `0.5`).<br>- Empty refs: `compute_cer(["", ""], ["", ""])` → `cer == 0.0, ref_len == 0`; `compute_cer([""], ["ア"])` → `ref_len == 0, insertions == 1`, `math.isfinite(cer)`; `compute_cer([], [])` → `cer == 0.0, ref_len == 0`.<br>- `len(refs) != len(hyps)` → `ValueError`. |
| `test_compute_mer_mora_vs_char` | Mora-level accuracy via `kotoba.split_moras`; proves `MER != CER` on palatalized moras | - `ref = "キャク"` (`kotoba.split_moras` → `["キャ", "ク"]`, len 2) vs `hyp = "カク"` (`["カ", "ク"]`):<br>  - `compute_cer([ref], [hyp])["cer"] == pytest.approx(2 / 3)` (`S=1, D=1, ref_len=3`)<br>  - `compute_mer([ref], [hyp])["mer"] == pytest.approx(1 / 2)` (`S=1, D=0, ref_len=2`)<br>  - Assert `mer != cer`!<br>- Hiragana/Katakana normalization via `kotoba.split_moras`: `compute_mer(["きょうは"], ["キョウハ"])["mer"] == 0.0`.<br>- Empty refs handled safely without `ZeroDivisionError`. |
| `test_compute_wer` | Whitespace-delimited WER, extra spaces, empty refs | - `refs=["hello world foo"]`, `hyps=["hello  bar   foo baz"]` → `S=1, D=0, I=1, ref_len=3, wer == pytest.approx(2/3)`.<br>- Exact match → `wer == 0.0`.<br>- Empty refs / empty lists → `ref_len == 0`, finite `wer`, no `ZeroDivisionError`.<br>- `len(refs) != len(hyps)` → `ValueError`. |
| `test_confusion_pairs` | Substitution counts, descending order, `top_k`, identical/empty inputs | - `refs=["アアア", "カカ"]`, `hyps=["イイア", "ガキ"]`: substitutions are `("ア","イ"): 2`, `("カ","ガ"): 1`, `("カ","キ"): 1`.<br>  - Assert `pairs[0] == ("ア", "イ", 2)` and counts are non-increasing.<br>  - `top_k=1` returns `[("ア", "イ", 2)]`.<br>  - `top_k=0` returns `[]`.<br>- Identical strings → `[]`.<br>- Insertions/deletions only (`refs=["アイ"]`, `hyps=["ア"]`) → `[]`.<br>- `top_k < 0` or `len(refs) != len(hyps)` → `ValueError`. |
| `test_alignment_boundary_error` | Perfect alignment, exact known shift & IoU, partial/mismatched tokens, empty inputs | - **Perfect**: `gt = [{"t": "ア", "a": 0.1, "e": 0.2}, {"t": "イ", "a": 0.2, "e": 0.35}]`, `pred = [{"token": "ア", "start_sec": 0.1, "end_sec": 0.2, "confidence": 0.99}, {"token": "イ", "start_sec": 0.2, "end_sec": 0.35, "confidence": 0.98}]` → boundary errors `== pytest.approx(0.0)`, `mean_iou == pytest.approx(1.0)`, `matched == 2`.<br>- **Exact shift**: `gt = [{"t": "ア", "a": 0.10, "e": 0.30}]`, `pred = [{"token": "ア", "start_sec": 0.15, "end_sec": 0.35, "confidence": 0.9}]` → start & end offset `== pytest.approx(0.05)` (or `50.0` ms depending on unit — verify key names with Implementer), exact `mean_iou == pytest.approx(0.15 / 0.25)` (`0.6`).<br>- **Partial / mismatched tokens**: extra/missing/wrong tokens do not crash, return finite values with `0 <= mean_iou <= 1.0`.<br>- **Empty inputs**: `([], [])`, `([], pred)`, `(gt, [])` return safe finite dict with `matched == 0` and `mean_iou == 0.0`. |

---

## 4. Contract Alignment Notes for Implementer (Avoid Mismatches)

Before finalizing `tests/test_asr_decoding.py`, verify these 3 small interface details match `asr/decoding.py` and `asr/metrics.py`:

1. **`viterbi_align` when `T < min_required_frames` (and `len(token_ids) > 0`)**:
   - Recommended: return `[]` when `len(token_ids) == 0`; raise `ValueError` when `T < len(token_ids) + num_adjacent_repeats` (including `T == 0` with non-empty `token_ids`), OR return `[]` gracefully. Whichever is chosen in `asr/decoding.py`, assert that exact behavior explicitly in `test_viterbi_align_edge_cases`.
2. **`alignment_boundary_error` return dict keys & units**:
   - Recommended keys: `{"mean_start_error_ms", "mean_end_error_ms", "mean_boundary_error_ms", "mean_iou", "matched", "gt_count", "pred_count"}` (keeping `_ms` explicit in key names prevents sec-vs-ms ambiguity in UI/CLI callers).
3. **`prefix_beam_search` `insertion_bonus` unit**:
   - Applied per emitted non-blank token (`len(token_ids)`). In kana mode with single-char tokens `len(token_ids) == len(text)`, so `score == acoustic_score + lm_weight * lm_score + insertion_bonus * len(token_ids)` holds cleanly.
