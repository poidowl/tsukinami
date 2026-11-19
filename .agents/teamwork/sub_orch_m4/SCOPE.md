# Scope: Milestone M4 — CTC Decoding, N-gram LM, Viterbi Alignment & Metrics

## Owned Files
1. `asr/decoding.py` (100% Pure NumPy/Python):
   - `CharNgramLM(order: int = 3, smoothing: float = 0.1)`:
     - `.fit(texts: Sequence[str])`
     - `.score_next(prefix: str, token: str) -> float` (log-probability)
     - `.to_dict() -> dict` / `CharNgramLM.from_dict(d: dict) -> CharNgramLM`
   - `greedy_decode(log_probs: np.ndarray, tokenizer: Tokenizer, *, temperature: float = 1.0, blank_bias: float = 0.0) -> dict`:
     - Returns `{"text", "token_ids", "score"}`
   - `prefix_beam_search(log_probs: np.ndarray, tokenizer: Tokenizer, cfg: DecodeConfig, lm: CharNgramLM | None = None) -> list[dict]`:
     - Returns top-N hypotheses `[{"text", "score", "acoustic_score", "lm_score"}]`
     - Genuine CTC prefix beam search with log-sum-exp blank/non-blank probabilities, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`, beam pruning.
   - `viterbi_align(log_probs: np.ndarray, token_ids: Sequence[int], tokenizer: Tokenizer, frame_stride_ms: float = 40.0) -> list[dict]`:
     - Returns monotonic frame spans `[{"token", "start_sec", "end_sec", "confidence"}]`.

2. `asr/metrics.py` (100% Pure Python/NumPy):
   - Levenshtein edit distance with S/D/I breakdown.
   - `compute_cer(refs: Sequence[str], hyps: Sequence[str]) -> dict` returning `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`.
   - `compute_mer(refs: Sequence[str], hyps: Sequence[str]) -> dict` (Mora Error Rate using `kotoba.split_moras`, returning `{"mer", "substitutions", "deletions", "insertions", "ref_len"}`).
   - `compute_wer(refs: Sequence[str], hyps: Sequence[str]) -> dict` returning `{"wer", "substitutions", "deletions", "insertions", "ref_len"}`.
   - `confusion_pairs(refs: Sequence[str], hyps: Sequence[str], top_k: int = 10) -> list[tuple[str, str, int]]`.
   - `alignment_boundary_error(gt_moras, pred_align) -> dict` (TTS-vs-ASR mora boundary offset & IoU metrics).

3. `tests/test_asr_decoding.py`:
   - Thorough unit tests covering all components, edge cases, numerical stability, serialization, alignment monotonicity, metrics accuracy, and integration with M1 (`DecodeConfig`, `Tokenizer`, `kotoba.split_moras`).
