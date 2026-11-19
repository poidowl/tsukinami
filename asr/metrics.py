"""Pure-Python ASR evaluation metrics: Levenshtein S/D/I, CER, MER, WER, confusions, RTF, and alignment error."""

from __future__ import annotations

import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    import kotoba
except ImportError:  # pragma: no cover - fallback when invoked outside repo root
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    import kotoba

_OP_MATCH = 0
_OP_SUB = 1
_OP_DEL = 2
_OP_INS = 3
_OP_NAMES = ("match", "sub", "del", "ins")

_NON_MERGEABLE_PREV = ("、", "ッ", "ン", "ー")


def levenshtein_align(
    ref: Sequence[str],
    hyp: Sequence[str],
) -> tuple[list[tuple[str, str | None, str | None]], int, int, int]:
    """Compute Levenshtein alignment and (substitutions, deletions, insertions).

    Tie-breaking is deterministic: match/sub <= del <= ins.
    Returns ``(ops, substitutions, deletions, insertions)`` where each op is
    ``(op_name, ref_token_or_None, hyp_token_or_None)``.
    """
    m = len(ref)
    n = len(hyp)

    dp: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    back: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(1, m + 1):
        dp[i][0] = i
        back[i][0] = _OP_DEL
    for j in range(1, n + 1):
        dp[0][j] = j
        back[0][j] = _OP_INS

    for i in range(1, m + 1):
        r_tok = ref[i - 1]
        dp_i = dp[i]
        dp_prev = dp[i - 1]
        back_i = back[i]
        for j in range(1, n + 1):
            is_match = r_tok == hyp[j - 1]
            diag = dp_prev[j - 1] + (0 if is_match else 1)
            up = dp_prev[j] + 1
            left = dp_i[j - 1] + 1
            if diag <= up and diag <= left:
                dp_i[j] = diag
                back_i[j] = _OP_MATCH if is_match else _OP_SUB
            elif up <= left:
                dp_i[j] = up
                back_i[j] = _OP_DEL
            else:
                dp_i[j] = left
                back_i[j] = _OP_INS

    ops: list[tuple[str, str | None, str | None]] = []
    subs = 0
    dels = 0
    ins = 0
    i, j = m, n
    while i > 0 or j > 0:
        op = back[i][j]
        if op == _OP_MATCH:
            ops.append((_OP_NAMES[_OP_MATCH], ref[i - 1], hyp[j - 1]))
            i -= 1
            j -= 1
        elif op == _OP_SUB:
            ops.append((_OP_NAMES[_OP_SUB], ref[i - 1], hyp[j - 1]))
            subs += 1
            i -= 1
            j -= 1
        elif op == _OP_DEL:
            ops.append((_OP_NAMES[_OP_DEL], ref[i - 1], None))
            dels += 1
            i -= 1
        else:
            ops.append((_OP_NAMES[_OP_INS], None, hyp[j - 1]))
            ins += 1
            j -= 1

    ops.reverse()
    return ops, subs, dels, ins


def _validate_pair_sequences(refs: Sequence[str], hyps: Sequence[str]) -> None:
    if len(refs) != len(hyps):
        raise ValueError(
            f"refs and hyps must have the same length, got {len(refs)} and {len(hyps)}"
        )


def _error_rate(errors: int, ref_len: int) -> float:
    if ref_len == 0:
        return 0.0 if errors == 0 else 1.0
    return float(errors / ref_len)


def compute_cer(
    refs: Sequence[str],
    hyps: Sequence[str],
    *,
    normalize_kana: bool = False,
) -> dict[str, Any]:
    """Compute corpus Character Error Rate (CER) and S/D/I breakdown."""
    _validate_pair_sequences(refs, hyps)
    total_s = 0
    total_d = 0
    total_i = 0
    total_ref = 0

    for ref, hyp in zip(refs, hyps):
        r_seq = list(kotoba.to_kata(ref)) if normalize_kana else list(ref)
        h_seq = list(kotoba.to_kata(hyp)) if normalize_kana else list(hyp)
        _, s, d, i = levenshtein_align(r_seq, h_seq)
        total_s += s
        total_d += d
        total_i += i
        total_ref += len(r_seq)

    return {
        "cer": _error_rate(total_s + total_d + total_i, total_ref),
        "substitutions": total_s,
        "deletions": total_d,
        "insertions": total_i,
        "ref_len": total_ref,
    }


def compute_mer(
    refs: Sequence[str],
    hyps: Sequence[str],
    *,
    ignore_pauses: bool = False,
) -> dict[str, Any]:
    """Compute corpus Mora Error Rate (MER) using ``kotoba.split_moras``."""
    _validate_pair_sequences(refs, hyps)
    total_s = 0
    total_d = 0
    total_i = 0
    total_ref = 0

    for ref, hyp in zip(refs, hyps):
        r_seq = kotoba.split_moras(ref)
        h_seq = kotoba.split_moras(hyp)
        if ignore_pauses:
            r_seq = [m for m in r_seq if m != "、"]
            h_seq = [m for m in h_seq if m != "、"]
        _, s, d, i = levenshtein_align(r_seq, h_seq)
        total_s += s
        total_d += d
        total_i += i
        total_ref += len(r_seq)

    return {
        "mer": _error_rate(total_s + total_d + total_i, total_ref),
        "substitutions": total_s,
        "deletions": total_d,
        "insertions": total_i,
        "ref_len": total_ref,
    }


def compute_wer(
    refs: Sequence[str],
    hyps: Sequence[str],
) -> dict[str, Any]:
    """Compute corpus Word Error Rate (WER) on whitespace-delimited tokens."""
    _validate_pair_sequences(refs, hyps)
    total_s = 0
    total_d = 0
    total_i = 0
    total_ref = 0

    for ref, hyp in zip(refs, hyps):
        r_seq = ref.split()
        h_seq = hyp.split()
        _, s, d, i = levenshtein_align(r_seq, h_seq)
        total_s += s
        total_d += d
        total_i += i
        total_ref += len(r_seq)

    return {
        "wer": _error_rate(total_s + total_d + total_i, total_ref),
        "substitutions": total_s,
        "deletions": total_d,
        "insertions": total_i,
        "ref_len": total_ref,
    }


def confusion_pairs(
    refs: Sequence[str],
    hyps: Sequence[str],
    top_k: int = 10,
    *,
    unit: str = "char",
) -> list[tuple[str, str, int]]:
    """Return top-K substitution confusion pairs ``[(ref_tok, hyp_tok, count), ...]``."""
    _validate_pair_sequences(refs, hyps)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 0:
        raise ValueError(f"top_k must be an int >= 0, got {top_k!r}")
    if unit not in ("char", "mora", "word"):
        raise ValueError(f"unit must be one of ('char', 'mora', 'word'), got {unit!r}")
    if top_k == 0:
        return []

    counts: Counter[tuple[str, str]] = Counter()
    for ref, hyp in zip(refs, hyps):
        if unit == "char":
            r_seq = list(ref)
            h_seq = list(hyp)
        elif unit == "mora":
            r_seq = kotoba.split_moras(ref)
            h_seq = kotoba.split_moras(hyp)
        else:
            r_seq = ref.split()
            h_seq = hyp.split()

        ops, _, _, _ = levenshtein_align(r_seq, h_seq)
        for op, r_tok, h_tok in ops:
            if op == "sub" and r_tok is not None and h_tok is not None:
                counts[(r_tok, h_tok)] += 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
    return [(r_tok, h_tok, cnt) for (r_tok, h_tok), cnt in ranked[:top_k]]


def _validate_finite_timestamp(name: str, val: Any) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"{name} must be a finite number, got {val!r}")
    fval = float(val)
    if not math.isfinite(fval):
        raise ValueError(f"{name} must be finite, got {val!r}")
    return fval


def alignment_boundary_error(
    gt_moras: Sequence[Mapping[str, Any]],
    pred_align: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare TTS ground-truth mora boundaries against ASR Viterbi alignment spans.

    Merges consecutive small-kana tokens in ``pred_align`` (e.g., ``キ`` + ``ョ`` -> ``キョ``)
    so character-level ASR alignments compare cleanly against mora-level ground truth.
    """
    gt: list[tuple[str, float, float]] = [
        (
            kotoba.to_kata(str(m["t"])),
            _validate_finite_timestamp("gt_moras['a']", m["a"]),
            _validate_finite_timestamp("gt_moras['e']", m["e"]),
        )
        for m in gt_moras
    ]

    pred: list[tuple[str, float, float]] = []
    for p in pred_align:
        tok = kotoba.to_kata(str(p["token"]))
        start = _validate_finite_timestamp("pred_align['start_sec']", p["start_sec"])
        end = _validate_finite_timestamp("pred_align['end_sec']", p["end_sec"])
        if (
            pred
            and tok in kotoba.SMALL
            and pred[-1][0] not in _NON_MERGEABLE_PREV
            and pred[-1][0] not in kotoba.PAUSE
        ):
            prev_tok, prev_start, prev_end = pred[-1]
            pred[-1] = (prev_tok + tok, prev_start, max(prev_end, end))
        else:
            pred.append((tok, start, end))

    ops, _, _, _ = levenshtein_align([g[0] for g in gt], [p[0] for p in pred])

    onset_errs: list[float] = []
    offset_errs: list[float] = []
    ious: list[float] = []
    gi = 0
    pi = 0
    for op, _, _ in ops:
        if op == "match":
            _, gt_a, gt_e = gt[gi]
            _, pr_a, pr_e = pred[pi]
            onset_errs.append(abs(pr_a - gt_a))
            offset_errs.append(abs(pr_e - gt_e))
            inter = max(0.0, min(gt_e, pr_e) - max(gt_a, pr_a))
            union = max(gt_e, pr_e) - min(gt_a, pr_a)
            if union > 0.0:
                ious.append(inter / union)
            else:
                ious.append(1.0 if (gt_a == pr_a and gt_e == pr_e) else 0.0)
            gi += 1
            pi += 1
        elif op == "sub":
            gi += 1
            pi += 1
        elif op == "del":
            gi += 1
        else:  # "ins"
            pi += 1

    matched = len(ious)
    if matched == 0:
        onset_mae = 0.0
        offset_mae = 0.0
        mean_iou = 0.0
    else:
        onset_mae = float(sum(onset_errs) / matched)
        offset_mae = float(sum(offset_errs) / matched)
        mean_iou = float(sum(ious) / matched)

    mean_start_ms = onset_mae * 1000.0
    mean_end_ms = offset_mae * 1000.0
    mean_boundary_ms = 0.5 * (mean_start_ms + mean_end_ms)

    return {
        "onset_mae_sec": onset_mae,
        "offset_mae_sec": offset_mae,
        "mean_start_error_ms": mean_start_ms,
        "mean_end_error_ms": mean_end_ms,
        "mean_boundary_error_ms": mean_boundary_ms,
        "mean_iou": mean_iou,
        "matched": matched,
        "gt_count": len(gt),
        "pred_count": len(pred),
    }


def compute_rtf(elapsed_sec: float, audio_duration_sec: float) -> float:
    """Compute Real-Time Factor (elapsed_sec / audio_duration_sec)."""
    if isinstance(elapsed_sec, bool) or not isinstance(elapsed_sec, (int, float)):
        raise ValueError(f"elapsed_sec must be a non-negative finite float, got {elapsed_sec!r}")
    if isinstance(audio_duration_sec, bool) or not isinstance(
        audio_duration_sec, (int, float)
    ):
        raise ValueError(
            f"audio_duration_sec must be a non-negative finite float, got {audio_duration_sec!r}"
        )
    el = float(elapsed_sec)
    dur = float(audio_duration_sec)
    if not math.isfinite(el) or el < 0.0:
        raise ValueError(f"elapsed_sec must be finite and >= 0, got {elapsed_sec!r}")
    if not math.isfinite(dur) or dur < 0.0:
        raise ValueError(
            f"audio_duration_sec must be finite and >= 0, got {audio_duration_sec!r}"
        )
    if dur == 0.0:
        return 0.0
    return float(el / dur)
