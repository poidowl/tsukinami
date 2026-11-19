# Forensic Audit Report — Milestone M4 (CTC Decoding, N-gram LM, Viterbi Alignment & Metrics)

## Verdict: `CLEAN`

All Milestone M4 deliverables (`asr/decoding.py`, `asr/metrics.py`, `tests/test_asr_decoding.py`) are 100% genuine pure-NumPy/Python implementations with zero `torch` dependencies, zero cheating/facade logic, zero scope violations, and 38/38 independently verified passing unit tests.

---

## 1. Anti-Cheating & Algorithmic Genuineness

Every line of all three M4 files was audited:

### `asr/decoding.py` (540 lines)
- **Pure NumPy/Python Isolation**: Imports only stdlib (`heapq`, `math`, `collections.abc`, `typing`), `numpy`, `asr.config.DecodeConfig`, and `asr.tokenizer.Tokenizer`. Verified at runtime: importing `asr.decoding` and `asr.metrics` results in `'torch' in sys.modules == False`.
- **`_prepare_log_probs`**: Validates 2D `(T, V)` shape, `V == tokenizer.vocab_size`, finite `temperature > 0`, finite `blank_bias`, rejects `NaN`/`+inf`/all-`-inf` frames, applies temperature scaling and blank bias, and re-normalizes with numerically stable log-softmax.
- **`CharNgramLM`**: Genuine character-level N-gram LM with `<bos>`/`<eos>` padding, full `0..order-1` context counting, hierarchical interpolated add-k smoothing (valid probability mass with `<unk>` reservation), and JSON-safe `to_dict()` / `from_dict()` serialization.
- **`greedy_decode`**: Genuine argmax per frame with standard CTC collapse (deduplicating consecutive identical IDs before removing `blank_id`) and summed log-prob score.
- **`prefix_beam_search`**: Genuine CTC prefix beam search in log-probability space maintaining `(log_p_blank, log_p_non_blank)` per prefix, merging equivalent alignments via `_logsumexp2`, enforcing CTC repeated-token rules (self-loop from `p_nb` even if pruned from top-K, repeated emission only from `p_b`, distinct emission from `logsumexp(p_b, p_nb)`), incremental memoized LM scoring, `insertion_bonus`, and deterministic `heapq.nsmallest` beam pruning.
- **`viterbi_align`**: Genuine vectorized CTC Viterbi DP over the `2L + 1` extended state sequence with `can_skip` forbidding blank-skipping between identical adjacent tokens, exact backpointer traceback, frame-span extraction, and clamped `[0.0, 1.0]` mean posterior confidence.

### `asr/metrics.py` (352 lines)
- **Pure Python Isolation**: Imports only stdlib (`math`, `sys`, `collections.Counter`, `collections.abc`, `pathlib`, `typing`) and `kotoba`. Zero `torch` or external metric libraries.
- **`levenshtein_align`**: Genuine O(MN) DP edit distance with full backpointer reconstruction and deterministic tie-breaking (`match/sub <= del <= ins`), returning exact `(ops, substitutions, deletions, insertions)`.
- **`compute_cer`, `compute_mer`, `compute_wer`**: Genuine corpus micro-averaged error rates (`compute_mer` delegates mora splitting to `kotoba.split_moras`), returning exact S/D/I/ref_len dictionaries and safely handling empty references/inputs.
- **`confusion_pairs`**: Genuine extraction of substitution operations with deterministic `(-count, ref_tok, hyp_tok)` ranking across `char`/`mora`/`word` units.
- **`alignment_boundary_error`**: Normalizes via `kotoba.to_kata`, merges consecutive small-kana tokens (`kotoba.SMALL`) in character-level ASR predictions to align with mora-level TTS ground truth via Levenshtein, and computes exact onset/offset MAE, boundary error (ms), and interval IoU.
- **`compute_rtf`**: Validated `elapsed_sec / audio_duration_sec` with safe `0.0` handling for zero-duration inputs.

### `tests/test_asr_decoding.py` (669 lines, 38 tests)
- No mocked-out core algorithms, no skipped/xfail tests, no hardcoded shortcuts.
- Verifies analytical ground truths including exact CTC prefix-merging probabilities (`P("ア") = 0.4184` vs `P("イ") = 0.2508` beating greedy `"イ"`), LM rescoring (`"カキ"` -> `"カク"`), Viterbi frame boundaries and repeated-token blank separation, Levenshtein S/D/I exactness, CER vs MER divergence on `"キャク"` vs `"カク"`, small-kana alignment merging, serialization round-trips, and latency (<50 ms for 100×86 beam 8).

---

## 2. Scope & Ownership Integrity

Command run:
```bash
git status --short && echo "--- DIFF ---" && git diff --stat
```
Output:
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
--- DIFF ---
```
- Zero tracked repository files modified (all existing TTS files `kotoba.py`, `accent.py`, `carve.py`, `yomu.py`, etc. are completely untouched).
- Directory inspection (`ls -la asr/ tests/`) confirms M1 files (`asr/__init__.py`, `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `tests/test_asr_dsp.py`) retain their original M1 timestamps (`03:10`–`03:13`) and were not modified by M4.
- Only M4's exclusively owned files (`asr/decoding.py`, `asr/metrics.py`, `tests/test_asr_decoding.py`) were created by M4 (alongside parallel M2 files `asr/synth_data.py`, `asr/dataset.py`, `tests/test_asr_data.py`).

---

## 3. Independent Test Execution & Runtime Checks

### Pytest (M4 Target Suite)
Command:
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

============================== 38 passed in 0.28s ==============================
```

### Torch Isolation Check
Command:
```bash
.venv/bin/python -c "import sys; import asr.decoding, asr.metrics; print('torch_in_sys_modules:', 'torch' in sys.modules)"
```
Output:
```text
torch_in_sys_modules: False
```
