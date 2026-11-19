# Explorer 1 Handoff — Decoding & LM Architecture (`asr/decoding.py`)

## 1. Existing Interface Audit

Inspected `asr/config.py`, `asr/tokenizer.py`, `asr/__init__.py`, `PROJECT.md`, and `sub_orch_m4/SCOPE.md`.

### `DecodeConfig` (`asr/config.py:183-206`)
```python
@dataclass
class DecodeConfig(_ConfigBase):
    method: str = "beam"          # in ("greedy", "beam")
    beam_width: int = 8           # int >= 1
    temperature: float = 1.0      # finite float > 0.0
    blank_bias: float = 0.0       # finite float
    lm_weight: float = 0.0        # finite float >= 0.0
    insertion_bonus: float = 0.0  # finite float
```
All fields are validated in `__post_init__` and serialized via `.to_dict()` / `.from_dict()`.

### `Tokenizer` (`asr/tokenizer.py:75-257`)
- `tokenizer.mode`: `"kana" | "phoneme" | "ascii"`
- `tokenizer.blank_id`: `0` (property; `tokenizer.blank_token == "<blank>"`)
- `tokenizer.vocab`: `list[str]` (index 0 is always `"<blank>"`; default sizes: kana=86, phoneme=29, ascii=42)
- `tokenizer.vocab_size`: `int` (`len(self.vocab)`)
- `tokenizer.token_to_id: dict[str, int]`, `tokenizer.id_to_token: dict[int, str]`
- `tokenizer.encode(text: str) -> list[int]` (returns non-blank IDs)
- `tokenizer.decode_tokens(ids: Sequence[int], collapse_ctc: bool = False) -> list[str]`
- `tokenizer.decode(ids: Sequence[int], collapse_ctc: bool = False) -> str`
  - Joins with `" "` when `mode == "phoneme"`, else `""`.
  - **Important**: Once IDs are already CTC-collapsed (e.g. `[1, 1]` from `[1, 0, 1]`), callers MUST pass `collapse_ctc=False` to `tokenizer.decode(...)` so valid repeated tokens separated by blank are not collapsed a second time.

### Conventions
- Python 3.11+ (`from __future__ import annotations`).
- 100% pure NumPy + Python stdlib in `asr/decoding.py` (no PyTorch dependency).
- Strict input validation raising `ValueError` / `TypeError` on invalid shapes, NaN/+inf, or bad parameter ranges.

---

## 2. Shared Internal Helpers (`asr/decoding.py`)

### `_NEG_INF = -math.inf`

### `_logsumexp2(a: float, b: float) -> float`
Pure Python scalar log-sum-exp for inner DP loops (avoids NumPy scalar overhead and overflow/underflow):
```python
def _logsumexp2(a: float, b: float) -> float:
    if a == -math.inf:
        return b
    if b == -math.inf:
        return a
    if a >= b:
        return a + math.log1p(math.exp(b - a))
    return b + math.log1p(math.exp(a - b))
```

### `_prepare_log_probs(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0) -> np.ndarray`
Shared validation and log-probability normalization for `greedy_decode` and `prefix_beam_search`:
1. Validate `temperature`: not `bool`, `isinstance(..., (int, float))`, finite, `> 0.0`; else raise `ValueError`.
2. Validate `blank_bias`: not `bool`, `isinstance(..., (int, float))`, finite; else raise `ValueError`.
3. Convert `arr = np.asarray(log_probs, dtype=np.float64)`.
4. Validate `arr.ndim == 2`; else raise `ValueError(f"log_probs must be 2D (T, V), got shape {arr.shape}")`.
5. Validate `arr.shape[1] == tokenizer.vocab_size`; else raise `ValueError(...)`.
6. If `arr.shape[0] == 0`: return `arr` (shape `(0, V)`).
7. Reject `NaN` or `+inf`: `if np.isnan(arr).any() or np.isposinf(arr).any(): raise ValueError(...)`. (`-inf` entries for masked/impossible tokens are allowed as long as no frame is all `-inf`.)
8. Apply temperature scaling:
   `scaled = arr / float(temperature)` if `temperature != 1.0` else `arr.copy()`.
9. Apply `blank_bias` before log-softmax:
   `if blank_bias != 0.0: scaled[:, tokenizer.blank_id] += float(blank_bias)`.
   - **Rationale**: Shifting the blank logit before log-softmax shifts the relative log-odds of blank vs every non-blank token by exactly `blank_bias` nats (giving identical argmax and identical beam hypothesis ordering as shifting after), while guaranteeing every frame remains a normalized log-probability distribution (`<= 0.0`, `exp` sums to `1.0`).
10. Numerically stable row-wise log-softmax:
    ```python
    row_max = np.max(scaled, axis=-1, keepdims=True)
    if np.any(np.isneginf(row_max)):
        raise ValueError("log_probs contains a frame with all -inf values")
    lse = row_max + np.log(np.sum(np.exp(scaled - row_max), axis=-1, keepdims=True))
    return scaled - lse
    ```

---

## 3. Component 1: `CharNgramLM`

### Class Signature & Constants
```python
class CharNgramLM:
    BOS: str = "<bos>"
    EOS: str = "<eos>"

    def __init__(self, order: int = 3, smoothing: float = 0.1) -> None: ...
    def fit(self, texts: Sequence[str]) -> CharNgramLM: ...
    def score_next(self, prefix: str, token: str) -> float: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CharNgramLM: ...
    def __eq__(self, other: object) -> bool: ...
```

### Validation & State
- `order`: must be `int` (not `bool`) and `>= 1`.
- `smoothing`: must be finite `int | float` (not `bool`) and `> 0.0`, stored as `float`.
- Internal state:
  - `self.vocab: set[str] = set()` (all observed characters plus `EOS`; `BOS` is context-only).
  - `self._ngram_counts: dict[tuple[str, ...], dict[str, int]] = {}` (context tuple of length `0 .. order - 1` -> `{next_token: count}`).
  - `self._context_totals: dict[tuple[str, ...], int] = {}` (precomputed `sum(counts.values())` per context for O(1) scoring).

### `.fit(texts: Sequence[str]) -> CharNgramLM`
1. Reset `self.vocab`, `self._ngram_counts`, and `self._context_totals` (clean, deterministic re-fit).
2. For each `text` in `texts`:
   - `seq = [self.BOS] * (self.order - 1) + list(text) + [self.EOS]`
   - For `i` in `range(self.order - 1, len(seq))`:
     - `tok = seq[i]`
     - `self.vocab.add(tok)`
     - For `k` in `range(self.order)`:
       - `ctx = tuple(seq[i - k : i])` (for `k == 0`, `ctx == ()`)
       - Increment `self._ngram_counts.setdefault(ctx, {})[tok] += 1`
       - Increment `self._context_totals[ctx] += 1`
3. Return `self`.

### `.score_next(prefix: str, token: str) -> float`
Uses **hierarchical Dirichlet / interpolated add-k backoff**, which is strictly normalized (`sum_{tok in vocab U {<unk>}} P(tok | ctx) == 1.0`), strictly positive for unseen tokens, O(`order`) per call, and automatically backs off when higher-order contexts are unseen:
1. If `not self.vocab` (unfitted LM): return `0.0` (neutral log-prob; no NaN/`-inf`).
2. Let `s = self.smoothing`, `V = len(self.vocab) + 1` (reserving 1 slot for unseen/`<unk>` tokens).
3. Base unigram probability (`k = 0`):
   ```python
   uni_total = self._context_totals.get((), 0)
   uni_count = self._ngram_counts.get((), {}).get(token, 0)
   prob = (uni_count + s) / (uni_total + s * V)
   ```
4. If `self.order > 1`:
   - Construct left-padded context of length `order - 1`:
     ```python
     hist = list(prefix[-(self.order - 1):])
     if len(hist) < self.order - 1:
         hist = [self.BOS] * (self.order - 1 - len(hist)) + hist
     ```
   - For `k` in `range(1, self.order)`:
     ```python
     ctx = tuple(hist[len(hist) - k :])
     total = self._context_totals.get(ctx, 0)
     if total > 0:
         count = self._ngram_counts[ctx].get(token, 0)
         prob = (count + s * prob) / (total + s)
     # If total == 0, prob stays equal to lower-order backoff probability.
     ```
5. Return `float(math.log(prob))`.

### Properties Guaranteed
- Always returns a finite float `<= 0.0`.
- `BOS` handling: `score_next("", tok)` queries `(BOS, ..., BOS)`, giving higher scores to utterance-initial characters.
- `EOS` handling: `score_next(prefix, lm.EOS)` returns valid end-of-sequence log-prob.
- Unseen tokens: `count == 0` at all orders, yielding `prob = (s / (uni_total + s * V)) * prod(s / (total_k + s)) > 0`, strictly lower than seen tokens in the same context.
- 100% deterministic.

### Serialization (`.to_dict()` / `.from_dict(d)`)
JSON-serializable (no tuple keys, no delimiter collisions, deterministic sorted order):
```python
{
    "order": self.order,
    "smoothing": self.smoothing,
    "vocab": sorted(self.vocab),
    "ngrams": [
        [list(ctx), dict(sorted(counts.items()))]
        for ctx, counts in sorted(self._ngram_counts.items())
    ],
}
```
`from_dict(d)`:
- Validates `isinstance(d, Mapping)` and presence of `"order"`, `"smoothing"`, `"vocab"`, `"ngrams"`.
- Constructs `lm = cls(order=d["order"], smoothing=d["smoothing"])`.
- Populates `lm.vocab`, `lm._ngram_counts`, and recomputes `lm._context_totals` from counts (validating non-negative `int` counts).

---

## 4. Component 2: `greedy_decode`

### Signature
```python
def greedy_decode(
    log_probs: np.ndarray,
    tokenizer: Tokenizer,
    *,
    temperature: float = 1.0,
    blank_bias: float = 0.0,
) -> dict[str, Any]:
```
Returns `{"text": str, "token_ids": list[int], "score": float}`.

### Algorithm
1. `lp = _prepare_log_probs(log_probs, tokenizer, temperature=temperature, blank_bias=blank_bias)`
2. If `lp.shape[0] == 0`:
   return `{"text": "", "token_ids": [], "score": 0.0}`.
3. Per-frame argmax and score:
   ```python
   best_ids = np.argmax(lp, axis=-1)
   score = float(np.sum(lp[np.arange(lp.shape[0]), best_ids]))
   ```
4. CTC collapse (remove consecutive repeats first, then remove `blank_id`):
   ```python
   blank_id = tokenizer.blank_id
   collapsed_ids: list[int] = []
   prev: int | None = None
   for tok_id in best_ids.tolist():
       if tok_id != prev:
           if tok_id != blank_id:
               collapsed_ids.append(tok_id)
           prev = tok_id
   ```
5. Decode without double-collapsing:
   `text = tokenizer.decode(collapsed_ids, collapse_ctc=False)`
6. Return `{"text": text, "token_ids": collapsed_ids, "score": score}`.

### Edge Cases
- `T == 0` -> `{"text": "", "token_ids": [], "score": 0.0}`.
- All-blank output -> `{"text": "", "token_ids": [], "score": float(np.sum(lp[:, blank_id]))}`.
- Repeated tokens separated by blank (`[a, a, 0, a]` -> `token_ids=[a, a]`).
- 1D/3D `log_probs`, vocab size mismatch, `temperature <= 0`, NaN/+inf -> `ValueError`.

---

## 5. Component 3: `prefix_beam_search`

### Signature
```python
def prefix_beam_search(
    log_probs: np.ndarray,
    tokenizer: Tokenizer,
    cfg: DecodeConfig,
    lm: CharNgramLM | None = None,
) -> list[dict[str, Any]]:
```
Returns up to `cfg.beam_width` hypotheses sorted descending by `"score"`:
`[{"text": str, "score": float, "acoustic_score": float, "lm_score": float}]`.

### Algorithm (Exact CTC Prefix Beam Search DP in Log Space)
1. Validate `cfg` is a `DecodeConfig` (or extract `beam_width`, `temperature`, `blank_bias`, `lm_weight`, `insertion_bonus`).
2. `lp = _prepare_log_probs(log_probs, tokenizer, temperature=cfg.temperature, blank_bias=cfg.blank_bias)`
3. `T, V = lp.shape`
4. `blank_id = tokenizer.blank_id` (0), `beam_width = cfg.beam_width`, `lm_weight = cfg.lm_weight`, `ins_bonus = cfg.insertion_bonus`.
5. Handle `T == 0`:
   return `[{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]`.
6. Initialize beam:
   - `beam: dict[tuple[int, ...], tuple[float, float]] = {(): (0.0, _NEG_INF)}` mapping `prefix -> (p_b, p_nb)`.
   - Caches (reused across frames to avoid repeated LM & string work):
     - `lm_cache: dict[tuple[int, ...], float] = {(): 0.0}`
     - `text_cache: dict[tuple[int, ...], str] = {(): ""}`
     - `sep = " " if tokenizer.mode == "phoneme" else ""`
     - `id_to_token = tokenizer.id_to_token`
   - Helper to get/compute LM score for `new_prefix = prefix + (c,)`:
     ```python
     def _get_lm_score(prefix: tuple[int, ...], c: int, new_prefix: tuple[int, ...]) -> float:
         if lm is None:
             return 0.0
         cached = lm_cache.get(new_prefix)
         if cached is not None:
             return cached
         parent_text = text_cache[prefix]
         tok_str = id_to_token[c]
         val = lm_cache[prefix] + lm.score_next(parent_text, tok_str)
         lm_cache[new_prefix] = val
         text_cache[new_prefix] = (
             f"{parent_text}{sep}{tok_str}" if (parent_text and sep) else f"{parent_text}{tok_str}"
         )
         return val
     ```
7. Precompute per-frame top-K non-blank token pruning parameter:
   - `num_non_blank = V - 1`
   - `top_k = min(num_non_blank, max(beam_width * 2, 16))`
   - `non_blank_ids = np.arange(1, V, dtype=np.int64)` (since `blank_id == 0`; more generally `[i for i in range(V) if i != blank_id]`).
8. Main frame loop `for t in range(T):`
   - `lp_t = lp[t]`
   - `p_blank_t = float(lp_t[blank_id])`
   - Select pruned non-blank candidate indices:
     - If `num_non_blank == 0`: `cand_ids = []`
     - Else if `top_k < num_non_blank`:
       Use `np.argpartition(lp_t[1:], -top_k)[-top_k:] + 1` (O(V) in C) and filter out any index where `lp_t[c] == -math.inf`.
     - Else:
       `cand_ids = [c for c in range(V) if c != blank_id and lp_t[c] != -math.inf]`.
     - Convert `cand_pairs = [(int(c), float(lp_t[c])) for c in cand_ids]` and `cand_set = {c for c, _ in cand_pairs}`.
   - `next_beam: dict[tuple[int, ...], list[float]] = {}` (storing `[p_b, p_nb]` mutable 2-element list avoids tuple reallocation).
   - For each `prefix, (p_b, p_nb)` in `beam.items()`:
     - `p_total = _logsumexp2(p_b, p_nb)`
     - **Blank transition** (stay on `prefix`, end in blank):
       If `p_blank_t != _NEG_INF`:
         Add `p_total + p_blank_t` into `next_beam[prefix][0]` via `_logsumexp2`.
     - **Ensure self-loop for `last_tok` even if pruned from `top_k`**:
       `last_tok = prefix[-1] if prefix else None`
       If `last_tok is not None and last_tok not in cand_set`:
         `lp_last = float(lp_t[last_tok])`
         If `lp_last != _NEG_INF` and `p_nb != _NEG_INF`:
           Add `p_nb + lp_last` into `next_beam[prefix][1]` via `_logsumexp2`.
     - **Non-blank transitions** `for c, lp_c in cand_pairs`:
       - If `c == last_tok`:
         1. **Self-loop** (stay on `prefix`, only from `p_nb`):
            If `p_nb != _NEG_INF`:
              Add `p_nb + lp_c` into `next_beam[prefix][1]` via `_logsumexp2`.
         2. **Emit repeated token** (`new_prefix = prefix + (c,)`, ONLY from `p_b`!):
            If `p_b != _NEG_INF`:
              Add `p_b + lp_c` into `next_beam[new_prefix][1]` via `_logsumexp2`.
              If `lm is not None` and `new_prefix not in lm_cache`:
                `_get_lm_score(prefix, c, new_prefix)`
       - Else (`c != last_tok`):
         - `new_prefix = prefix + (c,)` (from both `p_b` and `p_nb`, i.e. `p_total`):
           Add `p_total + lp_c` into `next_beam[new_prefix][1]` via `_logsumexp2`.
           If `lm is not None` and `new_prefix not in lm_cache`:
             `_get_lm_score(prefix, c, new_prefix)`
   - **Beam pruning** (keep top `beam_width` prefixes):
     - Compute ranking score for each `pref, (nb_pb, nb_pnb)` in `next_beam.items()`:
       `ac = _logsumexp2(nb_pb, nb_pnb)`
       `lms = lm_cache.get(pref, 0.0) if lm is not None else 0.0`
       `tot = ac + lm_weight * lms + ins_bonus * len(pref)`
     - Sort/select top `beam_width` by `(-tot, pref)` (deterministic tie-breaking!) using `heapq.nsmallest(beam_width, ...)` when `len(next_beam) > beam_width`.
     - Rebind `beam = {pref: (nb_pb, nb_pnb) for ...}`.
9. **Finalization**:
   - Build output list from final `beam`:
     ```python
     hypotheses = []
     for pref, (p_b, p_nb) in beam.items():
         ac = _logsumexp2(p_b, p_nb)
         lms = lm_cache.get(pref, 0.0) if lm is not None else 0.0
         tot = ac + lm_weight * lms + ins_bonus * len(pref)
         text = text_cache[pref] if pref in text_cache else tokenizer.decode(pref, collapse_ctc=False)
         hypotheses.append({
             "text": text,
             "score": float(tot),
             "acoustic_score": float(ac),
             "lm_score": float(lms),
         })
     hypotheses.sort(key=lambda h: (-h["score"], h["text"]))
     return hypotheses[:beam_width]
     ```

### Performance Budget Verification (`<10 ms` target for `T <= 150, V ~ 100, beam_width = 8`)
- Per frame: 1 `np.argpartition` on 100 floats (~5 µs) + `8` beams × `16` candidates = `128` inner iterations.
- Total over `T = 150` frames: `19,200` lightweight Python dict/float ops ≈ **3–6 ms** on CPU.
- LM queries are memoized in `lm_cache` per unique `(prefix, c)` pair, so repeated frames on existing prefixes do zero LM work.

### Key Unit Tests to Include (`tests/test_asr_decoding.py`)
1. `CharNgramLM`:
   - `fit` + `score_next` assigns higher log-prob to seen n-grams than unseen ones; backoff works when trigram context unseen but bigram/unigram seen.
   - `BOS` / `EOS` scoring; unseen token returns finite negative log-prob (never `-inf` or `NaN`); unfitted LM returns `0.0`.
   - `order=1` (unigram) and `order=3` (trigram); probability distribution sums to ~1.0 over `vocab U {<unk>}`.
   - `to_dict()` is JSON-serializable (`json.dumps`/`json.loads`) and `from_dict` reproduces identical scores.
2. `greedy_decode`:
   - Exact CTC collapse (`[a, a, 0, a, b, b, 0]` -> `"アアイ"`), preserving consecutive duplicates separated by blank.
   - `temperature` and `blank_bias` effects (high positive `blank_bias` yields empty output; negative suppresses blanks).
   - Edge cases: `T=0`, all-blank, 1D/3D invalid shape, vocab mismatch, `temperature <= 0`, all 3 tokenizer modes (`kana`, `phoneme`, `ascii`).
3. `prefix_beam_search`:
   - **Genuine CTC prefix merging test**: Construct a 2-frame matrix where `"a"` is split across two alignments `(a, blank)` and `(blank, a)` whose summed probability beats a single peak `(b, b)` — verify `prefix_beam_search` picks `"a"` while `greedy_decode` picks `"b"`.
   - **Repeated token rule test**: Verify `[a, a]` without blank collapses to `"a"`, while `[a, blank, a]` emits `"aa"`.
   - **LM rescoring test**: Ambiguous acoustic frames between two tokens are resolved in favor of the LM-preferred continuation when `lm_weight > 0`.
   - **Knobs**: `blank_bias`, `insertion_bonus`, `temperature`, `beam_width=1` vs `beam_width=8`.
   - **Speed benchmark**: `T=150, V=86, beam_width=8` completes well under 50 ms (target `<10 ms` typical).
   - **Determinism & edge cases**: `T=0`, all-blank, identical repeated calls produce bit-for-bit identical output.
