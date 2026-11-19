# Implementation Worker Handoff — Milestone M4 (CTC Decoding, N-gram LM, Viterbi Alignment & Metrics)

## 1. Files Created (Exclusive Ownership)

1. `/home/antigravity/poidowl/tsukinami/asr/decoding.py` (100% Pure NumPy/Python — zero `torch` imports)
2. `/home/antigravity/poidowl/tsukinami/asr/metrics.py` (100% Pure Python — zero `torch` imports, uses `kotoba.split_moras` / `kotoba.to_kata`)
3. `/home/antigravity/poidowl/tsukinami/tests/test_asr_decoding.py` (38 comprehensive unit tests)

No existing TTS files, M1 files, M2 files, or `tests_e2e/` files were modified.

---

## 2. Implementation Summary & Design Decisions

### `asr/decoding.py`
- **`_prepare_log_probs(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0)`**: Validates 2D `(T, V)` shape, `V == tokenizer.vocab_size`, positive finite `temperature`, finite `blank_bias`, rejects `NaN`/`+inf`/all-`-inf` frames, applies temperature scaling and pre-softmax `blank_bias`, and re-normalizes via numerically stable log-softmax.
- **`CharNgramLM(order=3, smoothing=0.1)`**:
  - `.fit(texts)` counts character n-grams across orders `0..order-1` with `<bos>` left-padding and `<eos>` termination.
  - `.score_next(prefix, token)` computes normalized hierarchical Dirichlet / interpolated add-k backoff log-probabilities (`<= 0.0`, strictly finite, handles unseen tokens and unfitted/empty corpora cleanly).
  - `.to_dict()` / `.from_dict(d)` serialize cleanly to JSON without tuple keys; implements `__eq__`.
- **`greedy_decode(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0)`**:
  - Returns `{"text", "token_ids", "score"}` with proper CTC collapse (removing consecutive duplicates before removing blanks, preserving repeated tokens separated by blank) and `tokenizer.decode(collapsed_ids, collapse_ctc=False)`.
- **`prefix_beam_search(log_probs, tokenizer, cfg: DecodeConfig, lm: CharNgramLM | None = None)`**:
  - Genuine CTC prefix beam search maintaining `(log_p_blank, log_p_non_blank)` per prefix and merging equivalent CTC alignments via `_logsumexp2`.
  - Properly enforces CTC repeated-token rule (self-loop from `p_nb`, repeated emission only from `p_b`, distinct emission from `logsumexp(p_b, p_nb)`).
  - Supports `temperature`, `blank_bias`, `lm_weight` (memoized per-prefix LM scoring when `lm is not None and lm_weight > 0.0`), `insertion_bonus`, vectorized per-frame top-K non-blank candidate selection with guaranteed self-loop retention, and deterministic tie-breaking.
  - Returns up to `cfg.beam_width` sorted hypotheses `[{"text", "score", "acoustic_score", "lm_score"}]`.
- **`viterbi_align(log_probs, token_ids, tokenizer, frame_stride_ms=40.0)`**:
  - Vectorized CTC Viterbi DP over extended state sequence `[b, y_0, b, y_1, ..., y_{L-1}, b]` with `can_skip` mask forbidding blank-skipping between identical adjacent tokens.
  - Returns `[]` when `token_ids` is empty; raises `ValueError` when `T < len(token_ids) + num_adjacent_repeats` or on invalid `frame_stride_ms`, `blank_id` in `token_ids`, out-of-range IDs, or invalid `log_probs`.
  - Returns monotonic spans `[{"token", "start_sec", "end_sec", "confidence"}]` with `confidence` clamped to `[0.0, 1.0]`.

### `asr/metrics.py`
- **`levenshtein_align(ref, hyp)`**: Exact DP edit alignment with deterministic tie-breaking (`match/sub <= del <= ins`) returning `(ops, substitutions, deletions, insertions)`.
- **`compute_cer(refs, hyps, *, normalize_kana=False)`**: Corpus micro-averaged CER returning `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`.
- **`compute_mer(refs, hyps, *, ignore_pauses=False)`**: Corpus micro-averaged Mora Error Rate using `kotoba.split_moras`, returning `{"mer", "substitutions", "deletions", "insertions", "ref_len"}`.
- **`compute_wer(refs, hyps)`**: Corpus micro-averaged whitespace-delimited WER returning `{"wer", "substitutions", "deletions", "insertions", "ref_len"}`.
- **`confusion_pairs(refs, hyps, top_k=10, *, unit="char")`**: Deterministic top-K substitution pairs `[(ref_tok, hyp_tok, count), ...]`.
- **`alignment_boundary_error(gt_moras, pred_align)`**: Normalizes via `kotoba.to_kata`, merges consecutive small-kana tokens (`kotoba.SMALL`) in `pred_align` so character-level ASR spans match mora-level TTS ground truth, aligns via Levenshtein, and returns `{"onset_mae_sec", "offset_mae_sec", "mean_start_error_ms", "mean_end_error_ms", "mean_boundary_error_ms", "mean_iou", "matched", "gt_count", "pred_count"}`.
- **`compute_rtf(elapsed_sec, audio_duration_sec)`**: Validated Real-Time Factor helper returning `0.0` when `audio_duration_sec == 0.0`.

---

## 3. Verification Commands & Verbatim Outputs (Run After Final Edit)

### Command 1
```bash
.venv/bin/pytest -v tests/test_asr_decoding.py
```
Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 38 items

tests/test_asr_decoding.py ......................................        [100%]

============================== 38 passed in 0.15s ==============================
```

### Command 2
```bash
.venv/bin/pytest -v tests/test_asr_dsp.py tests/test_asr_decoding.py
```
Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 83 items

tests/test_asr_dsp.py .............................................      [ 54%]
tests/test_asr_decoding.py ......................................        [100%]

============================== 83 passed in 0.40s ==============================
```

### Torch Isolation & Latency Check
```bash
.venv/bin/python -c "import sys, time, numpy as np; import asr.decoding as d, asr.metrics as m; assert 'torch' not in sys.modules; from asr.tokenizer import Tokenizer; from asr.config import DecodeConfig; tok = Tokenizer('kana'); rng = np.random.default_rng(0); x = rng.standard_normal((100, tok.vocab_size)); lp = (x - np.log(np.exp(x).sum(-1, keepdims=True))).astype(np.float32); cfg = DecodeConfig(beam_width=8); d.prefix_beam_search(lp, tok, cfg); t0 = time.perf_counter(); d.prefix_beam_search(lp, tok, cfg); print(f'100x86 beam8 latency: {(time.perf_counter()-t0)*1000:.2f} ms, torch_imported={\"torch\" in sys.modules}')"
```
Output:
```text
100x86 beam8 latency: 11.93 ms, torch_imported=False
```
