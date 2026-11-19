# Primary Reviewer (Reviewer 1) Handoff — Milestone M4

## Verdict: `APPROVE`

---

## 1. Scope & File Review Summary

Reviewed files:
- `asr/decoding.py` (540 lines)
- `asr/metrics.py` (352 lines)
- `tests/test_asr_decoding.py` (669 lines, 38 unit tests)
- Cross-checked against `PROJECT.md` (Interface Contract #6), `SCOPE.md`, `asr/config.py`, `asr/tokenizer.py`, and `worker_1/handoff.md`.

Repository cleanliness:
- `git status --short` confirms no existing TTS files or M1 files were modified; only untracked project files (`asr/`, `tests/`, etc.) exist.

---

## 2. Detailed Checklist Verification

### 2.1 Pure NumPy/Python Isolation (No `torch`)
- `asr/decoding.py` imports only Python stdlib (`heapq`, `math`, `collections.abc`, `typing`), `numpy`, `asr.config.DecodeConfig`, and `asr.tokenizer.Tokenizer`.
- `asr/metrics.py` imports only Python stdlib (`math`, `sys`, `collections`, `collections.abc`, `pathlib`, `typing`) and `kotoba`.
- Verified dynamically that `'torch' not in sys.modules` before and after importing and running `asr.decoding` and `asr.metrics`.

### 2.2 Interface Contract #6 & `SCOPE.md` Compliance
- **`CharNgramLM(order=3, smoothing=0.1)`**:
  - `.fit(texts)` counts n-grams for orders `0..order-1` with `<bos>` padding and `<eos>` termination.
  - `.score_next(prefix, token) -> float` computes an exact hierarchical interpolated add-k / Dirichlet backoff distribution summing to `1.0` over `vocab ∪ {<unk>}`, returning finite log-probabilities `<= 0.0` (and `0.0` for unfitted/empty models).
  - `.to_dict()` / `CharNgramLM.from_dict(d)` round-trip cleanly through JSON without tuple keys, with input validation and `__eq__`.
- **`greedy_decode(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0) -> dict`**:
  - Returns `{"text", "token_ids", "score"}`.
  - Properly collapses consecutive duplicate IDs before stripping `blank_id`, preserving repeated tokens separated by blank.
  - `_prepare_log_probs` validates 2D `(T, V)` shape, `V == tokenizer.vocab_size`, positive finite `temperature`, finite `blank_bias`, rejects `NaN`/`+inf`/all-`-inf` frames, applies temperature scaling and pre-softmax `blank_bias`, and re-normalizes with numerically stable log-softmax.
- **`prefix_beam_search(log_probs, tokenizer, cfg, lm=None) -> list[dict]`**:
  - Returns up to `cfg.beam_width` sorted hypotheses `[{"text", "score", "acoustic_score", "lm_score"}]`.
  - Genuine CTC prefix beam search in log-probability space maintaining `(p_b, p_nb)` per prefix and merging equivalent CTC alignments via `_logsumexp2`.
  - Correctly enforces CTC transition rules: blank stays on `prefix` into `p_b`; self-loop on `last_tok` transitions only from `p_nb`; repeated `last_tok` emission transitions only from `p_b`; distinct token emission transitions from `logsumexp(p_b, p_nb)`.
  - Guarantees self-loop retention even when `last_tok` falls outside per-frame top-K candidates, supports `temperature`, `blank_bias`, memoized `lm_weight`, `insertion_bonus`, and deterministic tie-breaking.
- **`viterbi_align(log_probs, token_ids, tokenizer, frame_stride_ms=40.0) -> list[dict]`**:
  - Returns `[{"token", "start_sec", "end_sec", "confidence"}]` with monotonic, non-overlapping spans and confidence clamped to `[0.0, 1.0]`.
  - Extended CTC state sequence `[b, y_0, b, y_1, ..., y_{L-1}, b]` with `can_skip` mask correctly forbidding blank-skipping between identical adjacent tokens.
  - Handles empty `token_ids` (`[]`), single-frame alignment, and raises `ValueError` on insufficient frames (`T < L + num_adjacent_repeats`), `blank_id` in `token_ids`, out-of-range IDs, invalid `frame_stride_ms`, or unreachable `-inf` paths.
- **`asr/metrics.py`**:
  - `levenshtein_align`: Exact DP with deterministic tie-breaking (`match/sub <= del <= ins`).
  - `compute_cer`, `compute_mer`, `compute_wer`: Corpus micro-averaged error rates with exact schema (`{"cer"|"mer"|"wer", "substitutions", "deletions", "insertions", "ref_len"}`), `kotoba.split_moras` integration for MER, safe handling of empty references, and length mismatch validation.
  - `confusion_pairs`: Deterministic top-K substitution pairs `[(ref_tok, hyp_tok, count)]` supporting `char`/`mora`/`word` units.
  - `alignment_boundary_error`: Normalizes kana via `kotoba.to_kata`, merges consecutive `kotoba.SMALL` tokens in `pred_align` against mora-level `gt_moras`, aligns via Levenshtein, and returns onset/offset MAE (sec & ms), mean boundary error (ms), mean IoU, and match counts.
  - `compute_rtf`: Validated non-negative finite RTF helper returning `0.0` when `audio_duration_sec == 0.0`.

### 2.3 Test Suite Quality (`tests/test_asr_decoding.py`)
- 38 well-structured unit tests covering all public APIs, mathematical properties (including an exact analytic proof of CTC prefix merging outperforming greedy), LM rescoring, temperature/blank_bias/insertion_bonus effects, serialization round-trips, latency (`< 50 ms` for `100 × 86` beam 8), Viterbi exact & noisy monotonic alignment, Levenshtein S/D/I, CER/MER/WER, confusion pairs, mora boundary error with small-kana merging, RTF, and error handling.

---

## 3. Independent Verification Commands & Verbatim Outputs

### Command 1: Assigned Primary Reviewer Pytest Suite
```bash
.venv/bin/pytest -v tests/test_asr_dsp.py tests/test_asr_decoding.py
```
Verbatim output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 83 items

tests/test_asr_dsp.py .............................................      [ 54%]
tests/test_asr_decoding.py ......................................        [100%]

============================== 83 passed in 0.38s ==============================
```

### Command 2: Torch Isolation & Edge-Case Probe (blank-only vocab, `-inf` log-probs, phoneme mode + LM)
```bash
.venv/bin/python -c "
import sys, numpy as np
import asr.decoding as d, asr.metrics as m, kotoba
assert 'torch' not in sys.modules, 'torch was imported!'
from asr.tokenizer import Tokenizer
from asr.config import DecodeConfig

# Edge case 1: vocab_size == 1 (blank only)
t1 = Tokenizer('kana', vocab=[])
lp1 = np.zeros((5, 1), dtype=np.float32)
assert d.greedy_decode(lp1, t1)['text'] == ''
assert d.prefix_beam_search(lp1, t1, DecodeConfig(beam_width=4))[0]['text'] == ''
assert d.viterbi_align(lp1, [], t1) == []

# Edge case 2: -inf entries in log_probs (e.g. blank == -inf at a frame)
t2 = Tokenizer('kana', vocab=['ア', 'イ'])
lp2 = np.array([[-np.inf, 0.0, -np.inf], [0.0, -np.inf, -np.inf], [-np.inf, -np.inf, 0.0]], dtype=np.float32)
assert d.greedy_decode(lp2, t2)['text'] == 'アイ'
hyps2 = d.prefix_beam_search(lp2, t2, DecodeConfig(beam_width=4))
assert hyps2[0]['text'] == 'アイ' and abs(hyps2[0]['acoustic_score']) < 1e-6
al2 = d.viterbi_align(lp2, [1, 2], t2, frame_stride_ms=40.0)
assert len(al2) == 2 and al2[0]['token'] == 'ア' and al2[1]['token'] == 'イ'

# Edge case 3: phoneme mode with LM
tp = Tokenizer('phoneme')
lm = d.CharNgramLM(order=3).fit(['k a', 'k i'])
lp_p = np.full((3, tp.vocab_size), -10.0, dtype=np.float32)
lp_p[0, tp.token_to_id['k']] = 0.0
lp_p[1, 0] = 0.0
lp_p[2, tp.token_to_id['a']] = 0.0
hyps_p = d.prefix_beam_search(lp_p, tp, DecodeConfig(beam_width=4, lm_weight=0.5), lm=lm)
assert hyps_p[0]['text'] == 'k a'

assert 'torch' not in sys.modules, 'torch was imported during execution!'
print('ALL_PROBES_OK', 'torch_loaded=' + str('torch' in sys.modules))
"
```
Verbatim output:
```text
ALL_PROBES_OK torch_loaded=False
```

---

## 4. Issues Found
None. No blocking or non-blocking defects found.

## 5. Final Verdict
`APPROVE` — Milestone M4 meets all `PROJECT.md` Interface Contract #6 and `SCOPE.md` requirements cleanly.
