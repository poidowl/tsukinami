# Explorer 2 Handoff — Viterbi Forced Alignment (`asr/decoding.py`) & Evaluation Metrics (`asr/metrics.py`)

## 1. Codebase Inspection Summary

### `kotoba.py`
- `to_kata(s)` (`kotoba.py:22-23`): converts Hiragana (`ぁ`–`ゖ`) to Katakana (`ァ`–`ヶ`); leaves Katakana, `ー`, ASCII, punctuation, and spaces unchanged.
- `PAUSE = set("、。，．,.!！?？… 　")` (`kotoba.py:20`): includes ASCII space `' '` and full-width space `'\u3000'`.
- `SMALL = {"ャ": "a", "ュ": "u", "ョ": "o", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}` (`kotoba.py:18`).
- `split_moras(text)` (`kotoba.py:25-33`):
  - Applies `to_kata(text)` first, so Hiragana and Katakana produce identical mora lists (e.g., `"きょうも"` and `"キョウモ"` both yield `["キョ", "ウ", "モ"]`).
  - Merges `SMALL` characters onto the previous mora unless the previous mora is in `('、', 'ッ', 'ン', 'ー')`.
  - Collapses internal `PAUSE` runs into a single `'、'`; strips leading and trailing pauses.
  - Empty strings `""` and pause/whitespace-only strings `"  、。 "` return `[]`.
- `tracks_from_kana(...)["moras"]` (`kotoba.py:360`): list of dicts containing `{'t', 'kind', 'c', 'v', 'a', 'b', 'e'}` where `'t'` is the mora string (including `'、'` with `kind='pau'`), `'a'` is start time (sec), and `'e'` is end time (sec). Manifests (`PROJECT.md`) store at least `{"t": str, "a": float, "e": float}`.

### `asr/tokenizer.py` & `asr/config.py`
- `Tokenizer`: `blank_id == 0` (`BLANK_TOKEN = "<blank>"`), `vocab_size == len(vocab)`, `vocab[idx]` maps ID → token string.
- **Important interaction with `kotoba.split_moras`**: Default `Tokenizer(mode="kana")` uses **single-character** katakana tokens (`"キ"`, `"ョ"` are separate tokens), whereas `gt_moras` from `kotoba` uses **merged moras** (`"キョ"`). `alignment_boundary_error` must merge consecutive `SMALL` kana spans in `pred_align` so character-level ASR alignments compare cleanly against mora-level TTS ground truth (while leaving already-merged mora tokens untouched).
- `asr/tokenizer.py:10-16` uses a safe `try: import kotoba / except ImportError:` fallback inserting repo root into `sys.path`; `asr/metrics.py` should use the same pattern.
- `DecodeConfig` (`asr/config.py:184-205`) validates `method`, `beam_width >= 1`, `temperature > 0`, `blank_bias`, `lm_weight >= 0`, `insertion_bonus`.

---

## 2. Detailed Plan: `viterbi_align` (in `asr/decoding.py`)

### Signature & Return Schema
```python
def viterbi_align(
    log_probs: np.ndarray,
    token_ids: Sequence[int],
    tokenizer: Tokenizer,
    frame_stride_ms: float = 40.0,
) -> list[dict[str, Any]]:
```
Returns a list of monotonic dicts (one per token in `token_ids`):
```python
{
    "token": str,         # tokenizer.vocab[tok_id]
    "start_sec": float,   # start_frame * (frame_stride_ms / 1000.0)
    "end_sec": float,     # (end_frame + 1) * (frame_stride_ms / 1000.0)
    "confidence": float,  # mean posterior exp(log_prob[t, tok_id]) over [start_frame, end_frame], clamped to [0.0, 1.0]
}
```

### Input Validation & Edge Cases
1. `frame_stride_ms`: must be finite and `> 0.0`; else raise `ValueError`.
2. `log_probs`: convert with `lp = np.asarray(log_probs, dtype=np.float64)`.
   - Must be 2D `(T, V)` with `V == tokenizer.vocab_size`; else raise `ValueError`.
   - If `np.isnan(lp).any()`: raise `ValueError("log_probs must not contain NaN")`.
3. `token_ids`: convert to `ids = [int(x) for x in token_ids]`.
   - For each `idx` in `ids`:
     - If `idx < 0 or idx >= V`: raise `ValueError(f"Token ID {idx} out of range [0, {V - 1}]")`.
     - If `idx == tokenizer.blank_id`: raise `ValueError("token_ids must not contain blank_id (0)")`.
4. Empty inputs:
   - If `len(ids) == 0` or `T == 0`: return `[]`.
5. Insufficient frames for CTC alignment:
   - Compute `min_frames = len(ids) + sum(1 for k in range(1, len(ids)) if ids[k] == ids[k - 1])`.
   - Each token needs ≥ 1 frame, and each adjacent repeated token pair requires ≥ 1 intervening blank frame.
   - If `T < min_frames`: raise `ValueError(f"Insufficient frames T={T} to align {len(ids)} tokens (minimum required: {min_frames})")`.

### CTC Extended State Sequence & Vectorized Viterbi DP
1. Extended sequence `ext` of length `S = 2 * L + 1` (where `L = len(ids)`):
   - `ext = np.full(S, tokenizer.blank_id, dtype=np.int64)`
   - `ext[1::2] = ids` → `[b, y_0, b, y_1, b, ..., y_{L-1}, b]`.
2. Precompute emission matrix `emit = lp[:, ext]` of shape `(T, S)` (`float64`).
3. Precompute skip mask `can_skip` of shape `(S,)` (`bool`):
   - `can_skip = np.zeros(S, dtype=bool)`
   - For `s >= 2`: `can_skip[s] = (ext[s] != blank_id) and (ext[s] != ext[s - 2])`
   - (Equivalently, `can_skip[3::2] = (ext[3::2] != ext[1:-2:2])`.)
4. DP tables:
   - `dp = np.full((T, S), -np.inf, dtype=np.float64)`
   - `backptr = np.zeros((T, S), dtype=np.int32)`
   - `state_idx = np.arange(S, dtype=np.int32)`
5. Initialization (`t = 0`):
   - `dp[0, 0] = emit[0, 0]` (start on leading blank)
   - `dp[0, 1] = emit[0, 1]` (start on `y_0`; always valid since `L >= 1` ⇒ `S >= 3`)
6. Recursion (`t = 1 .. T - 1`):
   - `prev = dp[t - 1]`
   - `c0 = prev` (stay: `s -> s`)
   - `c1 = np.empty(S, dtype=np.float64); c1[0] = -np.inf; c1[1:] = prev[:-1]` (step +1: `s - 1 -> s`)
   - `c2 = np.full(S, -np.inf, dtype=np.float64); c2[2:] = np.where(can_skip[2:], prev[:-2], -np.inf)` (skip +2: `s - 2 -> s`)
   - Stack `cands = np.stack((c0, c1, c2), axis=0)` (shape `(3, S)`).
   - `best_step = np.argmax(cands, axis=0)` (deterministic tie-breaking: stay `0` > step+1 `1` > skip+2 `2`).
   - `dp[t] = cands[best_step, state_idx] + emit[t]`
   - `backptr[t] = state_idx - best_step`
7. Termination (`t = T - 1`):
   - Valid final states are `S - 2` (`y_{L-1}`) and `S - 1` (trailing blank).
   - If `dp[T - 1, S - 2] == -np.inf and dp[T - 1, S - 1] == -np.inf`: raise `ValueError("No valid CTC alignment path found (all paths have -inf score)")`.
   - `end_state = (S - 2) if dp[T - 1, S - 2] >= dp[T - 1, S - 1] else (S - 1)`.
8. Backtrace:
   - `path = np.empty(T, dtype=np.int32)`
   - `s = end_state`
   - For `t` from `T - 1` down to `0`:
     - `path[t] = s`
     - If `t > 0`: `s = int(backptr[t, s])`
9. Collapsing to monotonic token spans:
   - `stride_s = float(frame_stride_ms) / 1000.0`
   - For `k, tok_id` in `enumerate(ids)`:
     - `frames = np.flatnonzero(path == (2 * k + 1))` (guaranteed non-empty & contiguous because transitions are non-decreasing and skip+2 never skips an odd state).
     - `start_frame = int(frames[0])`
     - `end_frame = int(frames[-1])`
     - `start_sec = float(start_frame * stride_s)`
     - `end_sec = float((end_frame + 1) * stride_s)`
     - `mean_prob = float(np.mean(np.exp(np.clip(lp[start_frame : end_frame + 1, tok_id], -700.0, 0.0))))`
     - `confidence = float(np.clip(mean_prob, 0.0, 1.0))`
     - Append `{"token": tokenizer.vocab[tok_id], "start_sec": start_sec, "end_sec": end_sec, "confidence": confidence}`.
   - Guaranteed invariants:
     - `len(result) == len(token_ids)`
     - `span["start_sec"] < span["end_sec"]` for every span
     - `result[k]["end_sec"] <= result[k + 1]["start_sec"]` for all `k`
     - `0.0 <= span["confidence"] <= 1.0`

---

## 3. Detailed Plan: `asr/metrics.py`

100% pure Python (plus `kotoba` import with `sys.path` fallback identical to `asr/tokenizer.py`).

### 3.1 Core Levenshtein Edit Distance & Alignment Backtrace
```python
def levenshtein_align(
    ref: Sequence[str],
    hyp: Sequence[str],
) -> tuple[list[tuple[str, str | None, str | None]], int, int, int]:
```
- Computes `(m + 1) x (n + 1)` DP table (`m = len(ref)`, `n = len(hyp)`) and op table.
- Op codes: `0 = "match"`, `1 = "sub"`, `2 = "del"`, `3 = "ins"`.
- Deterministic tie-breaking: prefer `diag` (match/sub) ≤ `up` (del) ≤ `left` (ins):
  - `if diag <= up and diag <= left:` → `match` if `ref[i-1] == hyp[j-1]` else `sub`
  - `elif up <= left:` → `del`
  - `else:` → `ins`
- Backtrace from `(m, n)` to `(0, 0)` producing aligned operations `[(op_str, ref_tok, hyp_tok), ...]` in forward order, plus exact counts `(substitutions, deletions, insertions)` satisfying `S + D + I == edit_distance`.

### 3.2 Shared Rate Helper & Validation
- Validate `len(refs) == len(hyps)`; else raise `ValueError`.
- Corpus error rate helper:
  ```python
  def _error_rate(errors: int, ref_len: int) -> float:
      if ref_len == 0:
          return 0.0 if errors == 0 else 1.0
      return float(errors / ref_len)
  ```
  (Avoids `ZeroDivisionError` and non-JSON-safe `inf`; allows rate `> 1.0` when `ref_len > 0` and insertions exceed `ref_len`.)

### 3.3 `compute_cer`
```python
def compute_cer(
    refs: Sequence[str],
    hyps: Sequence[str],
    *,
    normalize_kana: bool = False,
) -> dict[str, Any]:
```
- Tokenizes each utterance into characters: `list(kotoba.to_kata(s))` if `normalize_kana` else `list(s)`.
- Accumulates `substitutions`, `deletions`, `insertions`, `ref_len` across all pairs.
- Returns `{"cer": _error_rate(S + D + I, ref_len), "substitutions": S, "deletions": D, "insertions": I, "ref_len": ref_len}`.

### 3.4 `compute_mer`
```python
def compute_mer(
    refs: Sequence[str],
    hyps: Sequence[str],
    *,
    ignore_pauses: bool = False,
) -> dict[str, Any]:
```
- Tokenizes each utterance via `kotoba.split_moras(s)` (handles Hiragana/Katakana normalization, small-kana merging, pause collapsing, empty/whitespace-only → `[]`).
- If `ignore_pauses=True`, filters out `'、'`. (Default `False` preserves exact `kotoba.split_moras` output so `ref_len == len(kotoba.split_moras(ref))`.)
- Returns `{"mer": _error_rate(S + D + I, ref_len), "substitutions": S, "deletions": D, "insertions": I, "ref_len": ref_len}`.

### 3.5 `compute_wer`
```python
def compute_wer(
    refs: Sequence[str],
    hyps: Sequence[str],
) -> dict[str, Any]:
```
- Tokenizes each utterance via `s.split()` (handles empty and whitespace-only strings → `[]`).
- Returns `{"wer": _error_rate(S + D + I, ref_len), "substitutions": S, "deletions": D, "insertions": I, "ref_len": ref_len}`.

### 3.6 `confusion_pairs`
```python
def confusion_pairs(
    refs: Sequence[str],
    hyps: Sequence[str],
    top_k: int = 10,
    *,
    unit: str = "char",
) -> list[tuple[str, str, int]]:
```
- Validates `len(refs) == len(hyps)`, `top_k >= 0`, `unit in ("char", "mora", "word")`.
- If `top_k == 0`, returns `[]`.
- Runs `levenshtein_align` on tokenized `(ref, hyp)` pairs (`list(s)` for `"char"`, `kotoba.split_moras(s)` for `"mora"`, `s.split()` for `"word"`).
- Counts all `(ref_tok, hyp_tok)` from `"sub"` operations.
- Sorts deterministically by `(-count, ref_tok, hyp_tok)` and returns top `top_k` as `list[tuple[str, str, int]]`.

### 3.7 `alignment_boundary_error`
```python
def alignment_boundary_error(
    gt_moras: Sequence[Mapping[str, Any]],
    pred_align: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
```
- **Ground truth normalization**:
  - Extract `(kotoba.to_kata(str(m["t"])), float(m["a"]), float(m["e"]))` for each `m` in `gt_moras`.
- **Predicted alignment normalization + small-kana mora merging**:
  - Extract `(kotoba.to_kata(str(p["token"])), float(p["start_sec"]), float(p["end_sec"]))` for each `p` in `pred_align`.
  - Merge consecutive small-kana tokens (`tok in kotoba.SMALL`) onto the preceding predicted span when the preceding token is not in `('、', 'ッ', 'ン', 'ー')` and not in `kotoba.PAUSE`:
    - `prev_tok + tok`, `start = prev_start`, `end = max(prev_end, curr_end)`.
  - Leaves already-merged mora tokens (e.g., `"キョ"`) untouched.
- **Sequence alignment & boundary error computation**:
  - Run `levenshtein_align([g[0] for g in gt], [p[0] for p in pred])` and track running indices `(gi, pi)` to collect all `"match"` pairs `(gt[gi], pred[pi])`.
  - Using Levenshtein matching handles pauses, insertions, deletions, and substitutions gracefully without index drift.
  - For each matched pair `((gt_t, gt_a, gt_e), (pr_t, pr_a, pr_e))`:
    - `onset_err = abs(pr_a - gt_a)`
    - `offset_err = abs(pr_e - gt_e)`
    - `inter = max(0.0, min(gt_e, pr_e) - max(gt_a, pr_a))`
    - `union = max(gt_e, pr_e) - min(gt_a, pr_a)`
    - `iou = (inter / union) if union > 0.0 else (1.0 if gt_a == pr_a and gt_e == pr_e else 0.0)`
- **Return dict**:
  ```python
  {
      "onset_mae_sec": float,   # 0.0 when matched == 0
      "offset_mae_sec": float,  # 0.0 when matched == 0
      "mean_iou": float,        # 0.0 when matched == 0
      "matched": int,
      "gt_count": int,          # len(gt)
      "pred_count": int,        # len(pred) after small-kana merging
  }
  ```

### 3.8 `compute_rtf` Helper (Feature #14 in `PROJECT.md`)
```python
def compute_rtf(elapsed_sec: float, audio_duration_sec: float) -> float:
```
- Validates both are finite real numbers `>= 0.0` (else `ValueError`).
- Returns `0.0` if `audio_duration_sec == 0.0`, else `float(elapsed_sec / audio_duration_sec)`.

---

## 4. Key Test Cases to Include in `tests/test_asr_decoding.py`

### `viterbi_align`
1. Synthetic sharp log-probs for known spans (including blanks before/between/after tokens) → exact `start_sec`, `end_sec`, `confidence ≈ 1.0`, strict monotonicity (`end_sec[k] <= start_sec[k+1]`).
2. Repeated consecutive tokens (e.g., `"アア"` → `[id, id]`) force an intervening blank frame; fails with `ValueError` when `T == 2`, succeeds when `T == 3` with blank at frame 1.
3. Distinct consecutive tokens (`[id1, id2]`) succeed with `T == 2` (skip+2 transition without blank).
4. Single frame `T == 1`, single token `L == 1` succeeds.
5. Empty `token_ids == []` or `T == 0` returns `[]`.
6. Validation errors: `blank_id` in `token_ids`, out-of-range token ID, wrong `log_probs` ndim or vocab size, `frame_stride_ms <= 0`, NaN in `log_probs`.

### `asr/metrics.py`
1. `compute_cer`: exact match (`0.0`), known S/D/I counts, insertions > ref_len (`cer > 1.0`), empty refs/hyps (`0.0`), empty ref with non-empty hyp (`1.0`), mismatched list lengths (`ValueError`).
2. `compute_mer`: Hiragana vs Katakana equivalence (`"きょうも"` vs `"キョウモ"` → `mer == 0.0`), small-kana mora merging (`"きゃ"` vs `"きや"` → 1 mora vs 2 moras), pauses/punctuation/empty strings.
3. `compute_wer`: multi-word English/space-delimited strings, extra whitespace, empty strings.
4. `confusion_pairs`: deterministic descending-count / ascending-pair tie-breaking, `top_k` truncation, `top_k == 0`, identical refs/hyps → `[]`.
5. `alignment_boundary_error`:
   - Perfect match → `onset_mae_sec == 0.0`, `offset_mae_sec == 0.0`, `mean_iou == 1.0`, `matched == gt_count`.
   - Constant shift `+0.04s` → `onset_mae_sec ≈ 0.04`, `offset_mae_sec ≈ 0.04`, `0 < mean_iou < 1`.
   - Character-level `pred_align` (`"キ"`, `"ョ"`) vs mora-level `gt_moras` (`"キョ"`) merges and matches cleanly.
   - Presence of `'、'` pause or missing/inserted mora still aligns remaining moras accurately.
   - Empty `gt_moras` or `pred_align` returns zeros cleanly.
6. `compute_rtf`: normal ratio, `audio_duration_sec == 0.0` → `0.0`, negative/non-finite raises `ValueError`.
