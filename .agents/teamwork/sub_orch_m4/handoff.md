# Milestone M4 Handoff — CTC Decoding, N-gram LM, Viterbi Alignment & Metrics

## Status: `COMPLETE` (Gate PASSED on Iteration 1)

Milestone M4 (`sub_orch_m4`) has been implemented and independently verified through the full Project Pattern Iteration Loop (3 Explorers → 1 Worker → 2 Reviewers + 2 Challengers + 1 Forensic Auditor).

---

## Delivered Files (Exclusive M4 Ownership)

1. **`/home/antigravity/poidowl/tsukinami/asr/decoding.py`** (100% Pure NumPy/Python; zero `torch` imports):
   - `CharNgramLM(order: int = 3, smoothing: float = 0.1)` with `.fit(texts)`, `.score_next(prefix, token) -> float` (normalized log-probability with hierarchical interpolated add-k backoff), `.to_dict()`, `.from_dict(d)`, and JSON-safe serialization.
   - `greedy_decode(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0) -> dict` returning `{"text", "token_ids", "score"}` with proper CTC collapse (deduplicating consecutive repeats before removing blanks).
   - `prefix_beam_search(log_probs, tokenizer, cfg: DecodeConfig, lm: CharNgramLM | None = None) -> list[dict]` returning top-N hypotheses `[{"text", "score", "acoustic_score", "lm_score"}]` via genuine log-space CTC prefix beam search (`(p_b, p_nb)` log-sum-exp merging, repeated-token transition rules, `temperature`, `blank_bias`, memoized `lm_weight`, `insertion_bonus`, deterministic beam pruning).
   - `viterbi_align(log_probs, token_ids, tokenizer, frame_stride_ms=40.0) -> list[dict]` returning monotonic frame spans `[{"token", "start_sec", "end_sec", "confidence"}]` over the extended CTC state sequence `[b, y_0, b, ..., y_{L-1}, b]` enforcing blank separation between identical adjacent tokens.

2. **`/home/antigravity/poidowl/tsukinami/asr/metrics.py`** (100% Pure Python; zero `torch` imports):
   - `levenshtein_align(ref, hyp)` with exact O(mn) edit distance, deterministic tie-breaking, and S/D/I breakdown.
   - `compute_cer(refs, hyps) -> dict` returning `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`.
   - `compute_mer(refs, hyps) -> dict` using `kotoba.split_moras`, returning `{"mer", "substitutions", "deletions", "insertions", "ref_len"}`.
   - `compute_wer(refs, hyps) -> dict` returning `{"wer", "substitutions", "deletions", "insertions", "ref_len"}`.
   - `confusion_pairs(refs, hyps, top_k=10) -> list[tuple[str, str, int]]`.
   - `alignment_boundary_error(gt_moras, pred_align) -> dict` with Hiragana/Katakana normalization (`kotoba.to_kata`), small-kana digraph merging (`kotoba.SMALL`), Levenshtein token alignment, onset/offset MAE (sec & ms), mean boundary error (ms), and mean interval IoU.
   - `compute_rtf(elapsed_sec, audio_duration_sec) -> float`.

3. **`/home/antigravity/poidowl/tsukinami/tests/test_asr_decoding.py`** (38 comprehensive unit tests):
   - Covers `CharNgramLM` normalization/backoff/serialization, `greedy_decode`, analytic proof of genuine CTC prefix merging beating greedy, LM rescoring, temperature/blank_bias/insertion_bonus, Viterbi exact & noisy monotonic alignment, Levenshtein S/D/I, CER vs MER (`kotoba.split_moras`), WER, confusion pairs, alignment boundary error + small-kana merging, RTF, latency, and input validation.

---

## Verification Summary (Gate `PASS`)

- **Forensic Auditor (`auditor_1`)**: `CLEAN` — 100% genuine pure-NumPy/Python implementations, `'torch' in sys.modules == False`, zero modifications to existing TTS or M1 files, `.venv/bin/pytest -v tests/test_asr_decoding.py` -> **38 passed in 0.28s**.
- **Primary Reviewer (`rev_1`)**: `APPROVE` — `.venv/bin/pytest -v tests/test_asr_dsp.py tests/test_asr_decoding.py` -> **83 passed in 0.38s**.
- **Secondary Reviewer (`rev_2`)**: `APPROVE` — `.venv/bin/pytest -v tests/test_asr_decoding.py` -> **38 passed in 0.25s**; verified numerical stability, determinism, `kotoba.split_moras` integration, and latency (`1.9–7.4 ms` for 1–3 s utterances without LM).
- **Challenger 1 (`chal_1`)**: `PASS` — Exact brute-force `V^T` CTC marginalization oracle (`max_abs_err = 2.842e-14`), 32/32 brute-force Viterbi optimality oracle matches, LM probability normalization `== 1.0`, extreme inputs & latency checks.
- **Challenger 2 (`chal_2`)**: `PASS` — 200-pair Levenshtein math fuzzing (S+D+I, symmetry, triangle inequality, length conservation), tricky Japanese kana/mora/punctuation cases, `confusion_pairs`, `alignment_boundary_error` stress tests, and full M1+M4 pipeline probe.

---

## Artifacts
- Gate record: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m4/GATE_STATUS.md`
- Worker handoff: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m4/iter_1/worker_1/handoff.md`
- Verifier handoffs: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m4/iter_1/{auditor_1,rev_1,rev_2,chal_1,chal_2}/handoff.md`
