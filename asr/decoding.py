"""Pure-NumPy/Python CTC decoding, character N-gram LM, and Viterbi forced alignment."""

from __future__ import annotations

import heapq
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from asr.config import DecodeConfig
from asr.tokenizer import Tokenizer

_NEG_INF = -math.inf


def _logsumexp2(a: float, b: float) -> float:
    """Numerically stable log(exp(a) + exp(b)) for Python floats."""
    if a == _NEG_INF:
        return b
    if b == _NEG_INF:
        return a
    if a >= b:
        return a + math.log1p(math.exp(b - a))
    return b + math.log1p(math.exp(a - b))


def _prepare_log_probs(
    log_probs: np.ndarray,
    tokenizer: Tokenizer,
    *,
    temperature: float = 1.0,
    blank_bias: float = 0.0,
) -> np.ndarray:
    """Validate and normalize (T, V) log-probabilities with temperature and blank_bias."""
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ValueError(
            f"temperature must be a positive finite number, got {temperature!r}"
        )
    temp = float(temperature)
    if not math.isfinite(temp) or temp <= 0.0:
        raise ValueError(f"temperature must be finite and > 0, got {temperature!r}")

    if isinstance(blank_bias, bool) or not isinstance(blank_bias, (int, float)):
        raise ValueError(f"blank_bias must be a finite number, got {blank_bias!r}")
    bias = float(blank_bias)
    if not math.isfinite(bias):
        raise ValueError(f"blank_bias must be finite, got {blank_bias!r}")

    arr = np.asarray(log_probs, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"log_probs must be 2D (T, V), got shape {arr.shape}")
    if arr.shape[1] != tokenizer.vocab_size:
        raise ValueError(
            f"log_probs vocab dimension ({arr.shape[1]}) does not match "
            f"tokenizer.vocab_size ({tokenizer.vocab_size})"
        )
    if arr.shape[0] == 0:
        return arr

    if np.isnan(arr).any() or np.isposinf(arr).any():
        raise ValueError("log_probs must not contain NaN or +inf")

    base_max = np.max(arr, axis=-1, keepdims=True)
    if np.any(np.isneginf(base_max)):
        raise ValueError("log_probs contains a frame with all -inf values")

    with np.errstate(over="ignore", under="ignore"):
        shifted = arr - base_max
        scaled = shifted / temp if temp != 1.0 else shifted
        if bias != 0.0:
            scaled = scaled.copy()
            scaled[:, tokenizer.blank_id] += bias

        row_max = np.max(scaled, axis=-1, keepdims=True)
        if np.any(np.isneginf(row_max)):
            raise ValueError("log_probs contains a frame with all -inf values")
        norm_diff = scaled - row_max
        log_sum = np.log(np.sum(np.exp(norm_diff), axis=-1, keepdims=True))
        return norm_diff - log_sum


class CharNgramLM:
    """Lightweight character-level N-gram language model with interpolated add-k backoff."""

    BOS: str = "<bos>"
    EOS: str = "<eos>"

    def __init__(self, order: int = 3, smoothing: float = 0.1) -> None:
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise ValueError(f"order must be an int >= 1, got {order!r}")
        if isinstance(smoothing, bool) or not isinstance(smoothing, (int, float)):
            raise ValueError(f"smoothing must be a positive finite float, got {smoothing!r}")
        smooth_f = float(smoothing)
        if not math.isfinite(smooth_f) or smooth_f <= 0.0:
            raise ValueError(f"smoothing must be finite and > 0, got {smoothing!r}")

        self.order: int = order
        self.smoothing: float = smooth_f
        self.vocab: set[str] = set()
        self._ngram_counts: dict[tuple[str, ...], dict[str, int]] = {}
        self._context_totals: dict[tuple[str, ...], int] = {}

    def fit(self, texts: Sequence[str]) -> CharNgramLM:
        """Fit character N-gram counts from a sequence of strings."""
        self.vocab = set()
        self._ngram_counts = {}
        self._context_totals = {}

        pad = [self.BOS] * (self.order - 1)
        for text in texts:
            seq = pad + list(str(text)) + [self.EOS]
            for i in range(self.order - 1, len(seq)):
                tok = seq[i]
                self.vocab.add(tok)
                for k in range(self.order):
                    ctx = tuple(seq[i - k : i])
                    counts = self._ngram_counts.get(ctx)
                    if counts is None:
                        counts = {}
                        self._ngram_counts[ctx] = counts
                    counts[tok] = counts.get(tok, 0) + 1
                    self._context_totals[ctx] = self._context_totals.get(ctx, 0) + 1
        return self

    def score_next(self, prefix: str, token: str) -> float:
        """Return log P(token | prefix) using hierarchical Dirichlet / add-k backoff."""
        if not self.vocab:
            return 0.0

        s = self.smoothing
        v_size = len(self.vocab) + 1  # reserve 1 slot for unseen/<unk> tokens

        uni_total = self._context_totals.get((), 0)
        uni_count = self._ngram_counts.get((), {}).get(token, 0)
        prob = (uni_count + s) / (uni_total + s * v_size)

        if self.order > 1:
            ctx_len = self.order - 1
            hist = list(prefix[-ctx_len:]) if prefix else []
            if len(hist) < ctx_len:
                hist = [self.BOS] * (ctx_len - len(hist)) + hist
            for k in range(1, self.order):
                ctx = tuple(hist[ctx_len - k :])
                total = self._context_totals.get(ctx, 0)
                if total > 0:
                    count = self._ngram_counts[ctx].get(token, 0)
                    prob = (count + s * prob) / (total + s)

        return float(math.log(prob))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the LM into a JSON-compatible dictionary."""
        return {
            "order": self.order,
            "smoothing": self.smoothing,
            "vocab": sorted(self.vocab),
            "ngrams": [
                [list(ctx), dict(sorted(counts.items()))]
                for ctx, counts in sorted(self._ngram_counts.items())
            ],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CharNgramLM:
        """Deserialize a CharNgramLM from a dictionary produced by .to_dict()."""
        if not isinstance(d, Mapping):
            raise TypeError(
                f"Expected mapping for CharNgramLM.from_dict, got {type(d).__name__}"
            )
        required = ("order", "smoothing", "vocab", "ngrams")
        missing = [k for k in required if k not in d]
        if missing:
            raise ValueError(f"CharNgramLM dict missing required key(s): {missing}")

        lm = cls(order=d["order"], smoothing=d["smoothing"])
        raw_vocab = d["vocab"]
        if not isinstance(raw_vocab, (list, tuple, set)):
            raise ValueError(
                f"Invalid vocab in CharNgramLM dict: expected list, got {type(raw_vocab).__name__}"
            )
        lm.vocab = {str(tok) for tok in raw_vocab}

        raw_ngrams = d["ngrams"]
        if not isinstance(raw_ngrams, (list, tuple)):
            raise ValueError(
                f"Invalid ngrams in CharNgramLM dict: expected list, got {type(raw_ngrams).__name__}"
            )

        ngram_counts: dict[tuple[str, ...], dict[str, int]] = {}
        context_totals: dict[tuple[str, ...], int] = {}
        for entry in raw_ngrams:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError(f"Invalid ngram entry: {entry!r}")
            raw_ctx, raw_counts = entry
            if not isinstance(raw_ctx, (list, tuple)):
                raise ValueError(
                    f"Invalid ngram context: expected list/tuple, got {type(raw_ctx).__name__}"
                )
            if not isinstance(raw_counts, Mapping):
                raise ValueError(f"Invalid ngram counts mapping: {raw_counts!r}")
            ctx = tuple(str(x) for x in raw_ctx)
            counts: dict[str, int] = {}
            total = 0
            for tok, cnt in raw_counts.items():
                if isinstance(cnt, bool) or not isinstance(cnt, int) or cnt < 0:
                    raise ValueError(f"Invalid ngram count for {tok!r}: {cnt!r}")
                counts[str(tok)] = cnt
                total += cnt
            ngram_counts[ctx] = counts
            context_totals[ctx] = total

        lm._ngram_counts = ngram_counts
        lm._context_totals = context_totals
        return lm

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CharNgramLM):
            return NotImplemented
        return (
            self.order == other.order
            and self.smoothing == other.smoothing
            and self.vocab == other.vocab
            and self._ngram_counts == other._ngram_counts
        )


def greedy_decode(
    log_probs: np.ndarray,
    tokenizer: Tokenizer,
    *,
    temperature: float = 1.0,
    blank_bias: float = 0.0,
) -> dict[str, Any]:
    """Greedy CTC best-path decoding.

    Returns ``{"text": str, "token_ids": list[int], "score": float}``.
    """
    lp = _prepare_log_probs(
        log_probs, tokenizer, temperature=temperature, blank_bias=blank_bias
    )
    if lp.shape[0] == 0:
        return {"text": "", "token_ids": [], "score": 0.0}

    best_ids = np.argmax(lp, axis=-1)
    score = float(np.sum(lp[np.arange(lp.shape[0]), best_ids]))

    blank_id = tokenizer.blank_id
    collapsed_ids: list[int] = []
    prev: int | None = None
    for tok_id in best_ids.tolist():
        if tok_id != prev:
            if tok_id != blank_id:
                collapsed_ids.append(tok_id)
            prev = tok_id

    text = tokenizer.decode(collapsed_ids, collapse_ctc=False)
    return {"text": text, "token_ids": collapsed_ids, "score": score}


def prefix_beam_search(
    log_probs: np.ndarray,
    tokenizer: Tokenizer,
    cfg: DecodeConfig,
    lm: CharNgramLM | None = None,
) -> list[dict[str, Any]]:
    """Genuine CTC prefix beam search in log-probability space.

    Maintains separate log-probabilities ``(p_b, p_nb)`` for paths ending in
    blank vs. non-blank, merging equivalent CTC prefixes via log-sum-exp.

    Returns up to ``cfg.beam_width`` hypotheses sorted descending by ``score``:
    ``[{"text", "score", "acoustic_score", "lm_score"}, ...]``.
    """
    if not isinstance(cfg, DecodeConfig):
        raise TypeError(f"cfg must be a DecodeConfig, got {type(cfg).__name__}")

    lp = _prepare_log_probs(
        log_probs,
        tokenizer,
        temperature=cfg.temperature,
        blank_bias=cfg.blank_bias,
    )
    t_steps, vocab_size = lp.shape
    if t_steps == 0:
        return [{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]

    blank_id = tokenizer.blank_id
    beam_width = cfg.beam_width
    lm_weight = cfg.lm_weight
    ins_bonus = cfg.insertion_bonus
    use_lm = lm is not None and lm_weight > 0.0

    # Prefix -> (log_p_blank, log_p_non_blank)
    beam: dict[tuple[int, ...], tuple[float, float]] = {(): (0.0, _NEG_INF)}
    lm_cache: dict[tuple[int, ...], float] = {(): 0.0}
    text_cache: dict[tuple[int, ...], str] = {(): ""}
    sep = " " if tokenizer.mode == "phoneme" else ""
    id_to_token = tokenizer.id_to_token

    def _ensure_lm(prefix: tuple[int, ...], c: int, new_prefix: tuple[int, ...]) -> None:
        if new_prefix in lm_cache:
            return
        parent_text = text_cache[prefix]
        tok_str = id_to_token[c]
        lm_cache[new_prefix] = lm_cache[prefix] + lm.score_next(parent_text, tok_str)  # type: ignore[union-attr]
        text_cache[new_prefix] = (
            f"{parent_text}{sep}{tok_str}" if (parent_text and sep) else f"{parent_text}{tok_str}"
        )

    num_non_blank = vocab_size - 1
    top_k = min(num_non_blank, max(beam_width * 2, 16))
    lse2 = _logsumexp2
    neg_inf = _NEG_INF

    lp_rows: list[list[float]] = lp.tolist()
    if num_non_blank == 0:
        frame_cands: list[list[int]] = [[] for _ in range(t_steps)]
    elif top_k < num_non_blank and blank_id == 0:
        frame_cands = (
            np.argpartition(lp[:, 1:], -top_k, axis=-1)[:, -top_k:] + 1
        ).tolist()
    else:
        non_blank = [c for c in range(vocab_size) if c != blank_id]
        frame_cands = [non_blank for _ in range(t_steps)]

    for t in range(t_steps):
        lp_t = lp_rows[t]
        p_blank_t = lp_t[blank_id]
        cand_pairs = [
            (c, lp_t[c]) for c in frame_cands[t] if lp_t[c] != neg_inf
        ]
        cand_set = {c for c, _ in cand_pairs}

        next_beam: dict[tuple[int, ...], list[float]] = {}

        for prefix, (p_b, p_nb) in beam.items():
            p_total = lse2(p_b, p_nb)

            # 1. Blank transition: stay on `prefix`, end in blank
            if p_blank_t != neg_inf:
                entry = next_beam.get(prefix)
                if entry is None:
                    next_beam[prefix] = [p_total + p_blank_t, neg_inf]
                else:
                    entry[0] = lse2(entry[0], p_total + p_blank_t)

            # 2. Ensure self-loop for last_tok even if pruned from top_k
            last_tok = prefix[-1] if prefix else None
            if last_tok is not None and last_tok not in cand_set and p_nb != neg_inf:
                lp_last = lp_t[last_tok]
                if lp_last != neg_inf:
                    entry = next_beam.get(prefix)
                    if entry is None:
                        next_beam[prefix] = [neg_inf, p_nb + lp_last]
                    else:
                        entry[1] = lse2(entry[1], p_nb + lp_last)

            # 3. Non-blank transitions
            for c, lp_c in cand_pairs:
                if c == last_tok:
                    # 3a. Self-loop on `prefix` (only from p_nb)
                    if p_nb != neg_inf:
                        entry = next_beam.get(prefix)
                        if entry is None:
                            next_beam[prefix] = [neg_inf, p_nb + lp_c]
                        else:
                            entry[1] = lse2(entry[1], p_nb + lp_c)
                    # 3b. Emit repeated token `prefix + (c,)` (only from p_b)
                    if p_b != neg_inf:
                        new_pref = prefix + (c,)
                        entry = next_beam.get(new_pref)
                        if entry is None:
                            next_beam[new_pref] = [neg_inf, p_b + lp_c]
                        else:
                            entry[1] = lse2(entry[1], p_b + lp_c)
                        if use_lm:
                            _ensure_lm(prefix, c, new_pref)
                else:
                    # 3c. Emit distinct token `prefix + (c,)` (from both p_b and p_nb)
                    new_pref = prefix + (c,)
                    entry = next_beam.get(new_pref)
                    if entry is None:
                        next_beam[new_pref] = [neg_inf, p_total + lp_c]
                    else:
                        entry[1] = lse2(entry[1], p_total + lp_c)
                    if use_lm:
                        _ensure_lm(prefix, c, new_pref)

        # Prune to top beam_width prefixes with deterministic tie-breaking
        if len(next_beam) > beam_width:
            if use_lm:
                scored = [
                    (
                        -(
                            lse2(vals[0], vals[1])
                            + lm_weight * lm_cache.get(pref, 0.0)
                            + ins_bonus * len(pref)
                        ),
                        pref,
                        vals[0],
                        vals[1],
                    )
                    for pref, vals in next_beam.items()
                ]
            elif ins_bonus != 0.0:
                scored = [
                    (
                        -(lse2(vals[0], vals[1]) + ins_bonus * len(pref)),
                        pref,
                        vals[0],
                        vals[1],
                    )
                    for pref, vals in next_beam.items()
                ]
            else:
                scored = [
                    (-lse2(vals[0], vals[1]), pref, vals[0], vals[1])
                    for pref, vals in next_beam.items()
                ]
            top_items = heapq.nsmallest(beam_width, scored)
            beam = {pref: (pb, pnb) for _, pref, pb, pnb in top_items}
        else:
            beam = {pref: (vals[0], vals[1]) for pref, vals in next_beam.items()}

    hypotheses: list[dict[str, Any]] = []
    for pref, (p_b, p_nb) in beam.items():
        ac = lse2(p_b, p_nb)
        lms = lm_cache.get(pref, 0.0) if use_lm else 0.0
        tot = ac + lm_weight * lms + ins_bonus * len(pref)
        text = text_cache[pref] if pref in text_cache else tokenizer.decode(pref, collapse_ctc=False)
        hypotheses.append(
            {
                "text": text,
                "score": float(tot),
                "acoustic_score": float(ac),
                "lm_score": float(lms),
            }
        )

    hypotheses.sort(key=lambda h: (-h["score"], h["text"]))
    return hypotheses[:beam_width]


def viterbi_align(
    log_probs: np.ndarray,
    token_ids: Sequence[int],
    tokenizer: Tokenizer,
    frame_stride_ms: float = 40.0,
) -> list[dict[str, Any]]:
    """CTC Viterbi forced alignment returning monotonic token time spans.

    Returns a list of ``{"token", "start_sec", "end_sec", "confidence"}`` dicts,
    one per token in ``token_ids``.
    """
    if isinstance(frame_stride_ms, bool) or not isinstance(frame_stride_ms, (int, float)):
        raise ValueError(
            f"frame_stride_ms must be a positive finite number, got {frame_stride_ms!r}"
        )
    stride_ms = float(frame_stride_ms)
    if not math.isfinite(stride_ms) or stride_ms <= 0.0:
        raise ValueError(f"frame_stride_ms must be finite and > 0, got {frame_stride_ms!r}")

    lp = np.asarray(log_probs, dtype=np.float64)
    if lp.ndim != 2:
        raise ValueError(f"log_probs must be 2D (T, V), got shape {lp.shape}")
    t_steps, vocab_size = lp.shape
    if vocab_size != tokenizer.vocab_size:
        raise ValueError(
            f"log_probs vocab dimension ({vocab_size}) does not match "
            f"tokenizer.vocab_size ({tokenizer.vocab_size})"
        )
    if t_steps > 0 and (np.isnan(lp).any() or np.isposinf(lp).any()):
        raise ValueError("log_probs must not contain NaN or +inf")

    blank_id = tokenizer.blank_id
    ids: list[int] = []
    for raw_id in token_ids:
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, np.integer)):
            raise ValueError(f"token_ids must contain integers, got {raw_id!r}")
        idx = int(raw_id)
        if idx < 0 or idx >= vocab_size:
            raise ValueError(f"Token ID {idx} out of range [0, {vocab_size - 1}]")
        if idx == blank_id:
            raise ValueError(f"token_ids must not contain blank_id ({blank_id})")
        ids.append(idx)

    num_tokens = len(ids)
    if num_tokens == 0:
        return []

    min_frames = num_tokens + sum(1 for k in range(1, num_tokens) if ids[k] == ids[k - 1])
    if t_steps < min_frames:
        raise ValueError(
            f"Insufficient frames T={t_steps} to align {num_tokens} tokens "
            f"(minimum required: {min_frames})"
        )

    # Extended CTC state sequence: [b, y_0, b, y_1, b, ..., y_{L-1}, b]
    num_states = 2 * num_tokens + 1
    ext = np.full(num_states, blank_id, dtype=np.int64)
    ext[1::2] = ids

    emit = lp[:, ext]  # (T, S)
    can_skip = np.zeros(num_states, dtype=bool)
    if num_tokens > 1:
        can_skip[3::2] = ext[3::2] != ext[1:-2:2]

    dp = np.full((t_steps, num_states), -np.inf, dtype=np.float64)
    backptr = np.zeros((t_steps, num_states), dtype=np.int32)
    state_idx = np.arange(num_states, dtype=np.int32)

    dp[0, 0] = emit[0, 0]
    dp[0, 1] = emit[0, 1]

    for t in range(1, t_steps):
        prev = dp[t - 1]
        c0 = prev
        c1 = np.empty(num_states, dtype=np.float64)
        c1[0] = -np.inf
        c1[1:] = prev[:-1]
        c2 = np.full(num_states, -np.inf, dtype=np.float64)
        c2[2:] = np.where(can_skip[2:], prev[:-2], -np.inf)

        cands = np.stack((c0, c1, c2), axis=0)
        best_step = np.argmax(cands, axis=0)
        dp[t] = cands[best_step, state_idx] + emit[t]
        backptr[t] = state_idx - best_step

    final_tok_score = dp[t_steps - 1, num_states - 2]
    final_blank_score = dp[t_steps - 1, num_states - 1]
    if final_tok_score == -np.inf and final_blank_score == -np.inf:
        raise ValueError("No valid CTC alignment path found (all paths have -inf score)")

    end_state = (num_states - 2) if final_tok_score >= final_blank_score else (num_states - 1)

    path = np.empty(t_steps, dtype=np.int32)
    s = int(end_state)
    for t in range(t_steps - 1, -1, -1):
        path[t] = s
        if t > 0:
            s = int(backptr[t, s])

    stride_s = stride_ms / 1000.0
    spans: list[dict[str, Any]] = []
    for k, tok_id in enumerate(ids):
        frames = np.flatnonzero(path == (2 * k + 1))
        start_frame = int(frames[0])
        end_frame = int(frames[-1])
        mean_prob = float(
            np.mean(np.exp(np.clip(lp[start_frame : end_frame + 1, tok_id], -700.0, 0.0)))
        )
        spans.append(
            {
                "token": tokenizer.vocab[tok_id],
                "start_sec": float(start_frame * stride_s),
                "end_sec": float((end_frame + 1) * stride_s),
                "confidence": float(np.clip(mean_prob, 0.0, 1.0)),
            }
        )
    return spans
