# Adversarial Challenger 1 Handoff — Decoding, LM & Viterbi (`asr/decoding.py`)

## Verdict: `PASS`

All 5 adversarial stress-test suites and additional corner-case probes passed with **0 failures**. No bugs, numerical instabilities, mathematical invariant violations, or contract violations were found in `asr/decoding.py`.

---

## Probe Results

All probe scripts were staged in `/tmp/teamwork_probe.dTq9ll`, executed with `.venv/bin/python`, and removed prior to reporting (`TEMP_CLEAN` verified). Zero repository files were modified.

### 1. Exact CTC Marginalization Oracle — PASS
- **Setup**: 25 random `(T=4, V=4)` probability matrices across `temperature ∈ {0.05, 0.5, 1.0, 2.5, 10.0}`, `blank_bias ∈ {-2.0, 0.0, 1.5, 5.0}`, and injected `-inf` entries, plus an additional exact oracle trial with `CharNgramLM` (`lm_weight=0.7`) and `insertion_bonus=0.25`.
- **Method**: Enumerated all `V^T = 256` paths, collapsed each to its CTC label, summed path probabilities in linear space, and compared `log(sum_prob)` against `prefix_beam_search(..., beam_width=64)`.
- **Result**:
  - Exact agreement across all hypotheses and rankings: **`max_abs_err = 2.842e-14`** (float64 precision).
  - Total probability mass across returned prefixes summed to `1.0` within `1e-9` on all 25 trials.
  - Exact `acoustic_score`, `lm_score`, and combined `score` match on the LM + `insertion_bonus` oracle.

### 2. Viterbi Optimality Oracle — PASS
- **Setup**: 32 random `(T=6, V=4)` and minimum-length `(T=4, V=4)` / `(T=5, V=4)` trials covering repeated-token targets (`[1, 1, 2]`, `[1, 1, 1]`, `[2, 1, 1, 2]`, `[3, 3]`), single-token targets (`[1]`), distinct targets (`[1, 2, 3, 1]`), and injected `-inf` cells.
- **Method**: Brute-force enumerated all `V^T` paths collapsing to the target, found all optimal max-log-prob paths, and verified `viterbi_align` recovered an exact optimal span sequence (`start_sec`, `end_sec`, `token`, `confidence`).
- **Result**: 32/32 exact optimal matches; strict monotonicity (`0 <= start_sec < end_sec <= T * stride_s`, `prev.end_sec <= next.start_sec`) and `confidence ∈ [0.0, 1.0]` held in all cases.

### 3. `CharNgramLM` Probability Distribution & Serialization — PASS
- **Setup**: Tested `order ∈ {1, 2, 3, 4}` × `smoothing ∈ {1e-4, 0.1, 1.0, 5.0}` over Japanese kana corpus and 8 prefixes (empty, short, long, unseen).
- **Result**:
  - `sum(exp(score_next(prefix, t)) for t in vocab | {<eos>, <unk>}) == 1.0` within `1e-9` (strictly `<= 1.0 + 1e-6`) across all orders, smoothings, and prefixes.
  - Distinct unseen characters receive identical finite negative log-probabilities.
  - JSON round-trip (`json.loads(json.dumps(lm.to_dict()))` → `CharNgramLM.from_dict`) preserved exact equality (`lm == lm2`) and bit-identical `score_next` values.
  - Empty-string corpus `fit([""])` sums to `1.0`; empty/unfitted LM safely returns `0.0` (neutral fallback when `vocab` is empty) and round-trips cleanly.
  - Invalid constructor args (`order <= 0`, `bool`, `smoothing <= 0`, `nan`/`inf`) and malformed `from_dict` payloads cleanly raise `ValueError`.

### 4. Extreme / Adversarial Inputs — PASS
- **`T=0` and `T=1`**: Handled cleanly across `kana`, `phoneme`, and `ascii` tokenizer modes (including `prefix_beam_search` with `CharNgramLM` in `phoneme` and `ascii` modes, and custom single-token `["<blank>"]` vocab).
- **Numerical extremes**: Very negative `log_probs` (`-1e6`), `temperature ∈ {0.05, 10.0}`, `blank_bias ∈ {-50.0, +50.0}`, deterministic `-inf` single-path matrices, all-blank `-inf` matrices, `float16` arrays, and list-of-lists inputs all produced finite, contract-compliant outputs (`blank_bias=+50.0` forces empty output; `blank_bias=-50.0` suppresses blanks).
- **Contract validation**: `NaN`, `+inf`, all-`-inf` frames, wrong shapes `(T,)`, `(1, T, V)`, `()`, wrong `V != vocab_size`, `token_ids` longer than `T` or exceeding `min_frames` due to adjacent repeats, `blank_id`/negative/out-of-range/`bool` in `token_ids`, invalid `temperature`/`blank_bias`/`frame_stride_ms`, and non-`DecodeConfig` `cfg` all raised `ValueError`/`TypeError` as expected.
- **Determinism & Isolation**: Deterministic outputs on tied uniform log-probs; `"torch" not in sys.modules` confirmed (100% pure NumPy/Python).

### 5. Latency Benchmark (`T=100, V=86, beam_width=8`, 25 runs after warm-up) — PASS
| Operation | Min | Median | Mean | Max |
|-----------|-----|--------|------|-----|
| `prefix_beam_search` (no LM) | 12.31 ms | 21.22 ms | 20.85 ms | 37.05 ms |
| `prefix_beam_search` (with 3-gram LM) | 24.21 ms | 33.48 ms | 42.83 ms | 81.22 ms |
| `greedy_decode` | 0.09 ms | 0.10 ms | — | — |
| `viterbi_align` (8 tokens) | 1.17 ms | 1.34 ms | — | — |

*(Note: `T=100` at 40 ms stride is a 4.0 s utterance; typical 1.5 s playground utterances at `T≈37` scale linearly to ~4.5–8 ms without LM.)*

### Minor Informational Notes (Non-Blocking)
- When `CharNgramLM` is unfitted (`vocab` is empty), `score_next` returns `0.0` as a neutral no-op fallback so an unfitted LM passed to `prefix_beam_search` does not distort scores.
- `CharNgramLM` operates on characters (`list(str(text))`), so multi-character tokens in `phoneme` mode (e.g., `"sh"`, `"pau"`) are treated as unseen tokens without error, which matches the `CharNgramLM` contract.
