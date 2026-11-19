"""Unit tests for M4: CTC decoding, CharNgramLM, Viterbi alignment, and ASR metrics."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Sequence

import numpy as np
import pytest

from asr.config import DecodeConfig
from asr.decoding import CharNgramLM, greedy_decode, prefix_beam_search, viterbi_align
from asr.metrics import (
    alignment_boundary_error,
    compute_cer,
    compute_mer,
    compute_rtf,
    compute_wer,
    confusion_pairs,
    levenshtein_align,
)
from asr.tokenizer import Tokenizer


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _tiny_tokenizer() -> Tokenizer:
    """Compact 4-token kana tokenizer: 0=<blank>, 1=ア, 2=イ, 3=ウ."""
    return Tokenizer("kana", vocab=["ア", "イ", "ウ"])


def _log_probs_from_probs(probs: Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(probs, dtype=np.float64)
    np.testing.assert_allclose(arr.sum(axis=-1), 1.0, atol=1e-6)
    return np.log(arr).astype(np.float32)


def _sharp_log_probs(
    frame_token_ids: Sequence[int],
    vocab_size: int,
    peak_prob: float = 0.95,
) -> np.ndarray:
    t_steps = len(frame_token_ids)
    other_prob = (1.0 - peak_prob) / (vocab_size - 1)
    probs = np.full((t_steps, vocab_size), other_prob, dtype=np.float64)
    for t, tok_id in enumerate(frame_token_ids):
        probs[t, tok_id] = peak_prob
    return np.log(probs).astype(np.float32)


def _log_softmax(logits: np.ndarray) -> np.ndarray:
    arr = np.asarray(logits, dtype=np.float64)
    m = np.max(arr, axis=-1, keepdims=True)
    return (arr - (m + np.log(np.sum(np.exp(arr - m), axis=-1, keepdims=True)))).astype(
        np.float32
    )


# ---------------------------------------------------------------------------
# Section 1: CharNgramLM
# ---------------------------------------------------------------------------


def test_char_ngram_lm_fit_and_log_prob_validity() -> None:
    lm = CharNgramLM(order=3, smoothing=0.1).fit(["アイウ", "アイウ", "アイエ", "カキク"])
    for prefix in ("", "ア", "アイ", "カキ", "未知"):
        for tok in ("ア", "イ", "ウ", "エ", "カ", "ン", lm.EOS):
            lp = lm.score_next(prefix, tok)
            assert math.isfinite(lp)
            assert lp <= 0.0

    # Seen twice > seen once > unseen
    assert lm.score_next("アイ", "ウ") > lm.score_next("アイ", "エ")
    assert lm.score_next("アイ", "エ") > lm.score_next("アイ", "カ")

    # Probability sum over known vocab is strictly <= 1.0 (remaining mass is for <unk>)
    prob_sum = sum(math.exp(lm.score_next("アイ", c)) for c in lm.vocab)
    assert 0.0 < prob_sum <= 1.0 + 1e-6


def test_char_ngram_lm_orders_1_2_3() -> None:
    corpus = ["アイウ", "カイエ"]
    lm1 = CharNgramLM(order=1, smoothing=0.1).fit(corpus)
    lm2 = CharNgramLM(order=2, smoothing=0.1).fit(corpus)
    lm3 = CharNgramLM(order=3, smoothing=0.1).fit(corpus)

    # Order 1 ignores context
    assert lm1.score_next("アイ", "ウ") == pytest.approx(lm1.score_next("カイ", "ウ"))

    # Order 2 conditions only on last 1 char
    assert lm2.score_next("アイ", "ウ") == pytest.approx(lm2.score_next("カイ", "ウ"))
    assert lm2.score_next("ア", "イ") > lm2.score_next("ア", "ウ")

    # Order 3 distinguishes 2-char prefixes
    assert lm3.score_next("アイ", "ウ") > lm3.score_next("カイ", "ウ")
    assert lm3.score_next("カイ", "エ") > lm3.score_next("アイ", "エ")


def test_char_ngram_lm_smoothing_effect() -> None:
    lm_low = CharNgramLM(order=3, smoothing=0.01).fit(["アイウ"] * 10)
    lm_high = CharNgramLM(order=3, smoothing=5.0).fit(["アイウ"] * 10)

    gap_low = lm_low.score_next("アイ", "ウ") - lm_low.score_next("アイ", "カ")
    gap_high = lm_high.score_next("アイ", "ウ") - lm_high.score_next("アイ", "カ")
    assert gap_low > gap_high > 0.0


def test_char_ngram_lm_empty_corpus_and_unfitted() -> None:
    unfitted = CharNgramLM(order=3, smoothing=0.1)
    empty_fit = CharNgramLM(order=3, smoothing=0.1).fit([])
    blank_str_fit = CharNgramLM(order=3, smoothing=0.1).fit(["", ""])

    for lm in (unfitted, empty_fit, blank_str_fit):
        for prefix, tok in (("", "ア"), ("アイ", "ウ"), ("", lm.EOS)):
            lp = lm.score_next(prefix, tok)
            assert math.isfinite(lp)
            assert lp <= 0.0


def test_char_ngram_lm_serialization_roundtrip() -> None:
    lm = CharNgramLM(order=3, smoothing=0.15).fit(["ワタシ、ニホンゴ", "ワタシ、キョウ"])
    payload = json.loads(json.dumps(lm.to_dict()))
    restored = CharNgramLM.from_dict(payload)

    assert restored == lm
    assert restored.order == lm.order
    assert restored.smoothing == lm.smoothing
    for prefix in ("", "ワ", "ワタ", "ワタシ、", "未知"):
        for tok in ("ワ", "タ", "ニ", "キ", "ン", lm.EOS):
            assert restored.score_next(prefix, tok) == pytest.approx(
                lm.score_next(prefix, tok), abs=1e-12
            )

    # Empty/unfitted LM round-trip
    empty_lm = CharNgramLM(order=2, smoothing=0.5)
    restored_empty = CharNgramLM.from_dict(json.loads(json.dumps(empty_lm.to_dict())))
    assert restored_empty == empty_lm
    assert restored_empty.score_next("", "ア") == 0.0


@pytest.mark.parametrize(
    ("order", "smoothing"),
    [
        (0, 0.1),
        (-1, 0.1),
        (True, 0.1),
        (2, 0.0),
        (2, -0.5),
        (2, float("nan")),
        (2, float("inf")),
    ],
)
def test_char_ngram_lm_validation(order: object, smoothing: object) -> None:
    with pytest.raises(ValueError):
        CharNgramLM(order=order, smoothing=smoothing)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Section 2: greedy_decode
# ---------------------------------------------------------------------------


def test_greedy_decode_ctc_collapse_and_repeats() -> None:
    tok = _tiny_tokenizer()

    lp1 = _sharp_log_probs([1, 1, 0, 2, 2, 2, 0], tok.vocab_size, peak_prob=0.95)
    res1 = greedy_decode(lp1, tok)
    assert res1["text"] == "アイ"
    assert res1["token_ids"] == [1, 2]
    assert math.isfinite(res1["score"]) and res1["score"] <= 0.0
    assert res1["score"] == pytest.approx(float(np.sum(np.max(lp1, axis=-1))), abs=1e-5)

    # Blank separates identical tokens -> repeated token preserved
    lp2 = _sharp_log_probs([1, 0, 1], tok.vocab_size, peak_prob=0.95)
    res2 = greedy_decode(lp2, tok)
    assert res2["text"] == "アア"
    assert res2["token_ids"] == [1, 1]

    # Consecutive identical tokens without blank -> single token
    lp3 = _sharp_log_probs([1, 1, 1], tok.vocab_size, peak_prob=0.95)
    res3 = greedy_decode(lp3, tok)
    assert res3["text"] == "ア"
    assert res3["token_ids"] == [1]


def test_greedy_decode_temperature_and_blank_bias() -> None:
    tok = _tiny_tokenizer()
    lp = _sharp_log_probs([1, 0, 2], tok.vocab_size, peak_prob=0.8)

    r_sharp = greedy_decode(lp, tok, temperature=0.5)
    r_base = greedy_decode(lp, tok, temperature=1.0)
    r_flat = greedy_decode(lp, tok, temperature=2.0)
    assert r_sharp["text"] == r_base["text"] == r_flat["text"] == "アイ"
    assert r_sharp["score"] > r_base["score"] > r_flat["score"]

    # High positive blank_bias forces all blanks
    r_all_blank = greedy_decode(lp, tok, blank_bias=20.0)
    assert r_all_blank["text"] == ""
    assert r_all_blank["token_ids"] == []

    # Negative blank_bias promotes non-blank over moderate blank peak
    lp_mod = _log_probs_from_probs([[0.60, 0.30, 0.05, 0.05]])
    assert greedy_decode(lp_mod, tok, blank_bias=0.0)["text"] == ""
    assert greedy_decode(lp_mod, tok, blank_bias=-5.0)["text"] == "ア"


def test_greedy_decode_edge_cases_and_modes() -> None:
    tok = _tiny_tokenizer()

    # T = 0
    empty_res = greedy_decode(np.empty((0, tok.vocab_size), dtype=np.float32), tok)
    assert empty_res == {"text": "", "token_ids": [], "score": 0.0}

    # All-blank
    lp_blank = _sharp_log_probs([0, 0, 0, 0], tok.vocab_size, peak_prob=0.95)
    blank_res = greedy_decode(lp_blank, tok)
    assert blank_res["text"] == ""
    assert blank_res["token_ids"] == []
    assert blank_res["score"] <= 0.0

    # Phoneme mode (space-joined)
    ph_tok = Tokenizer("phoneme")
    k_id = ph_tok.token_to_id["k"]
    a_id = ph_tok.token_to_id["a"]
    lp_ph = _sharp_log_probs([k_id, 0, a_id], ph_tok.vocab_size, peak_prob=0.95)
    assert greedy_decode(lp_ph, ph_tok)["text"] == "k a"

    # ASCII mode
    asc_tok = Tokenizer("ascii")
    h_id = asc_tok.token_to_id["h"]
    i_id = asc_tok.token_to_id["i"]
    lp_asc = _sharp_log_probs([h_id, i_id], asc_tok.vocab_size, peak_prob=0.95)
    assert greedy_decode(lp_asc, asc_tok)["text"] == "hi"

    # Validation errors
    with pytest.raises(ValueError):
        greedy_decode(np.zeros((4,), dtype=np.float32), tok)
    with pytest.raises(ValueError):
        greedy_decode(np.zeros((1, 2, 4), dtype=np.float32), tok)
    with pytest.raises(ValueError):
        greedy_decode(np.zeros((2, 5), dtype=np.float32), tok)
    with pytest.raises(ValueError):
        greedy_decode(lp_blank, tok, temperature=0.0)


# ---------------------------------------------------------------------------
# Section 3: prefix_beam_search
# ---------------------------------------------------------------------------


def test_prefix_beam_search_matches_greedy_beam1() -> None:
    tok = _tiny_tokenizer()
    lp = _sharp_log_probs([0, 1, 1, 0, 1, 0, 2, 2], tok.vocab_size, peak_prob=0.95)
    greedy = greedy_decode(lp, tok)
    hyps = prefix_beam_search(lp, tok, DecodeConfig(beam_width=1))

    assert len(hyps) == 1
    assert hyps[0]["text"] == greedy["text"] == "アアイ"
    assert hyps[0]["lm_score"] == 0.0


def test_prefix_beam_search_genuine_ctc_prefix_merging() -> None:
    """Proves genuine CTC prefix merging beats both greedy and naive non-merging beam search."""
    tok = Tokenizer("kana", vocab=["ア", "イ"])  # 0=<blank>, 1=ア, 2=イ
    probs = [
        [0.30, 0.34, 0.36],
        [0.44, 0.42, 0.14],
    ]
    lp = _log_probs_from_probs(probs)

    # Greedy picks [イ, _] -> "イ" (0.36 * 0.44 = 0.1584)
    assert greedy_decode(lp, tok)["text"] == "イ"

    # Merged CTC probabilities:
    # P("ア") = 0.34*0.44 + 0.30*0.42 + 0.34*0.42 = 0.4184
    # P("イ") = 0.36*0.44 + 0.30*0.14 + 0.36*0.14 = 0.2508
    hyps = prefix_beam_search(lp, tok, DecodeConfig(beam_width=5))
    assert hyps[0]["text"] == "ア"
    assert hyps[0]["acoustic_score"] == pytest.approx(math.log(0.4184), abs=1e-5)

    by_text = {h["text"]: h for h in hyps}
    assert "イ" in by_text
    assert by_text["イ"]["acoustic_score"] == pytest.approx(math.log(0.2508), abs=1e-5)


def test_prefix_beam_search_lm_rescoring() -> None:
    tok = Tokenizer("kana", vocab=["カ", "キ", "ク"])  # 0=_, 1=カ, 2=キ, 3=ク
    probs = [
        [0.02, 0.94, 0.02, 0.02],  # sharp カ
        [0.94, 0.02, 0.02, 0.02],  # sharp blank
        [0.04, 0.04, 0.48, 0.44],  # ambiguous キ (0.48) vs ク (0.44)
    ]
    lp = _log_probs_from_probs(probs)
    lm = CharNgramLM(order=2, smoothing=0.05).fit(["カク"] * 30)

    hyps_no_lm = prefix_beam_search(lp, tok, DecodeConfig(beam_width=6, lm_weight=0.0), lm=lm)
    assert hyps_no_lm[0]["text"] == "カキ"
    assert hyps_no_lm[0]["lm_score"] == 0.0

    hyps_with_lm = prefix_beam_search(lp, tok, DecodeConfig(beam_width=6, lm_weight=1.0), lm=lm)
    assert hyps_with_lm[0]["text"] == "カク"
    assert hyps_with_lm[0]["lm_score"] < 0.0
    for h in hyps_with_lm:
        assert h["score"] == pytest.approx(h["acoustic_score"] + 1.0 * h["lm_score"], abs=1e-5)


def test_prefix_beam_search_insertion_bonus_temp_blank_bias() -> None:
    tok = _tiny_tokenizer()
    probs = [
        [0.52, 0.44, 0.02, 0.02],
        [0.52, 0.02, 0.44, 0.02],
    ]
    lp = _log_probs_from_probs(probs)

    hyps_pos_ins = prefix_beam_search(lp, tok, DecodeConfig(beam_width=6, insertion_bonus=2.0))
    hyps_neg_ins = prefix_beam_search(lp, tok, DecodeConfig(beam_width=6, insertion_bonus=-3.0))
    assert hyps_pos_ins[0]["text"] == "アイ"
    assert hyps_neg_ins[0]["text"] == ""

    # blank_bias
    hyps_high_blank = prefix_beam_search(lp, tok, DecodeConfig(beam_width=6, blank_bias=20.0))
    hyps_low_blank = prefix_beam_search(lp, tok, DecodeConfig(beam_width=6, blank_bias=-20.0))
    assert hyps_high_blank[0]["text"] == ""
    assert hyps_low_blank[0]["text"] != ""

    # temperature monotonic effect on acoustic_score for sharp posteriors
    lp_sharp = _sharp_log_probs([1, 0, 2], tok.vocab_size, peak_prob=0.85)
    h_cold = prefix_beam_search(lp_sharp, tok, DecodeConfig(beam_width=4, temperature=0.5))[0]
    h_base = prefix_beam_search(lp_sharp, tok, DecodeConfig(beam_width=4, temperature=1.0))[0]
    h_warm = prefix_beam_search(lp_sharp, tok, DecodeConfig(beam_width=4, temperature=2.0))[0]
    assert h_cold["acoustic_score"] > h_base["acoustic_score"] > h_warm["acoustic_score"]


def test_prefix_beam_search_output_invariants_and_edges() -> None:
    tok = _tiny_tokenizer()
    rng = np.random.default_rng(42)
    lp = _log_softmax(rng.standard_normal((12, tok.vocab_size)))
    lm = CharNgramLM(order=2, smoothing=0.1).fit(["アイウ", "イウア"])
    cfg = DecodeConfig(beam_width=5, lm_weight=0.4, insertion_bonus=0.25)

    hyps = prefix_beam_search(lp, tok, cfg, lm=lm)
    hyps_repeat = prefix_beam_search(lp, tok, cfg, lm=lm)
    assert hyps == hyps_repeat  # deterministic
    assert 1 <= len(hyps) <= cfg.beam_width
    assert all(hyps[i]["score"] >= hyps[i + 1]["score"] - 1e-12 for i in range(len(hyps) - 1))
    for h in hyps:
        expected = (
            h["acoustic_score"]
            + cfg.lm_weight * h["lm_score"]
            + cfg.insertion_bonus * len(h["text"])
        )
        assert h["score"] == pytest.approx(expected, abs=1e-5)

    # T = 0
    empty_hyps = prefix_beam_search(np.empty((0, tok.vocab_size), dtype=np.float32), tok, cfg)
    assert empty_hyps == [{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]

    # All-blank
    lp_blank = _sharp_log_probs([0, 0, 0], tok.vocab_size, peak_prob=0.99)
    blank_hyps = prefix_beam_search(lp_blank, tok, DecodeConfig(beam_width=4))
    assert blank_hyps[0]["text"] == ""

    # Validation errors
    with pytest.raises(ValueError):
        prefix_beam_search(np.zeros((4,), dtype=np.float32), tok, cfg)
    with pytest.raises(ValueError):
        prefix_beam_search(np.zeros((4, 9), dtype=np.float32), tok, cfg)


def test_prefix_beam_search_latency() -> None:
    tok = Tokenizer("kana")  # V = 86
    rng = np.random.default_rng(0)
    lp = _log_softmax(rng.standard_normal((100, tok.vocab_size)))
    cfg = DecodeConfig(beam_width=8)

    # Warm-up
    _ = prefix_beam_search(lp, tok, cfg)

    t0 = time.perf_counter()
    hyps = prefix_beam_search(lp, tok, cfg)
    elapsed = time.perf_counter() - t0

    assert len(hyps) >= 1
    assert elapsed < 0.05, f"prefix_beam_search took {elapsed * 1000:.2f} ms (limit 50 ms)"


# ---------------------------------------------------------------------------
# Section 4: viterbi_align
# ---------------------------------------------------------------------------


def test_viterbi_align_exact_boundaries() -> None:
    tok = _tiny_tokenizer()
    # frames: 0..1 blank, 2..3 ア, 4 blank, 5..7 イ, 8..9 blank
    seq = [0, 0, 1, 1, 0, 2, 2, 2, 0, 0]
    lp = _sharp_log_probs(seq, tok.vocab_size, peak_prob=0.96)
    align = viterbi_align(lp, [1, 2], tok, frame_stride_ms=40.0)

    assert len(align) == 2
    assert align[0]["token"] == "ア"
    assert align[0]["start_sec"] == pytest.approx(0.08)
    assert align[0]["end_sec"] == pytest.approx(0.16)
    assert 0.9 < align[0]["confidence"] <= 1.0

    assert align[1]["token"] == "イ"
    assert align[1]["start_sec"] == pytest.approx(0.20)
    assert align[1]["end_sec"] == pytest.approx(0.32)
    assert 0.9 < align[1]["confidence"] <= 1.0


def test_viterbi_align_repeated_adjacent_tokens() -> None:
    tok = _tiny_tokenizer()
    # frames: 0..1 ア, 2 blank, 3..4 ア, 5 blank
    seq = [1, 1, 0, 1, 1, 0]
    lp = _sharp_log_probs(seq, tok.vocab_size, peak_prob=0.96)
    align = viterbi_align(lp, [1, 1], tok, frame_stride_ms=40.0)

    assert len(align) == 2
    assert align[0]["token"] == "ア"
    assert align[1]["token"] == "ア"
    assert align[0]["start_sec"] == pytest.approx(0.0)
    assert align[0]["end_sec"] == pytest.approx(0.08)
    assert align[1]["start_sec"] == pytest.approx(0.12)
    assert align[1]["end_sec"] == pytest.approx(0.20)
    assert align[0]["end_sec"] < align[1]["start_sec"]


def test_viterbi_align_monotonicity_and_confidence_noisy() -> None:
    tok = _tiny_tokenizer()
    rng = np.random.default_rng(7)
    lp = _log_softmax(rng.standard_normal((30, tok.vocab_size)))
    token_ids = [1, 2, 2, 3, 1]
    align = viterbi_align(lp, token_ids, tok, frame_stride_ms=40.0)

    assert len(align) == len(token_ids)
    max_sec = 30 * 0.04 + 1e-9
    for span in align:
        assert 0.0 <= span["start_sec"] < span["end_sec"] <= max_sec
        assert 0.0 < span["confidence"] <= 1.0
    for i in range(len(align) - 1):
        assert align[i]["end_sec"] <= align[i + 1]["start_sec"] + 1e-9


def test_viterbi_align_edge_cases() -> None:
    tok = _tiny_tokenizer()
    lp5 = _sharp_log_probs([0, 1, 0, 2, 0], tok.vocab_size)

    # Empty token_ids -> []
    assert viterbi_align(lp5, [], tok) == []
    assert viterbi_align(np.empty((0, tok.vocab_size), dtype=np.float32), [], tok) == []

    # Distinct consecutive tokens with T == 2 (skip+2 transition without blank)
    lp2 = _sharp_log_probs([1, 2], tok.vocab_size)
    a2 = viterbi_align(lp2, [1, 2], tok, frame_stride_ms=40.0)
    assert len(a2) == 2
    assert a2[0]["end_sec"] == pytest.approx(a2[1]["start_sec"])

    # Single frame, single token
    lp1 = _sharp_log_probs([1], tok.vocab_size)
    a1 = viterbi_align(lp1, [1], tok, frame_stride_ms=40.0)
    assert len(a1) == 1 and a1[0]["start_sec"] == 0.0 and a1[0]["end_sec"] == pytest.approx(0.04)

    # Insufficient frames for CTC alignment -> ValueError
    with pytest.raises(ValueError):
        viterbi_align(np.empty((0, tok.vocab_size), dtype=np.float32), [1], tok)
    with pytest.raises(ValueError):
        viterbi_align(lp1, [1, 2], tok)
    with pytest.raises(ValueError):
        viterbi_align(lp2, [1, 1], tok)  # repeated token needs >= 3 frames

    # Invalid arguments
    with pytest.raises(ValueError):
        viterbi_align(lp5, [1], tok, frame_stride_ms=0.0)
    with pytest.raises(ValueError):
        viterbi_align(lp5, [0, 1], tok)  # blank_id in token_ids
    with pytest.raises(ValueError):
        viterbi_align(lp5, [99], tok)
    with pytest.raises(ValueError):
        viterbi_align(np.zeros((5,), dtype=np.float32), [1], tok)


# ---------------------------------------------------------------------------
# Section 5: asr/metrics.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ref", "hyp", "exp_s", "exp_d", "exp_i"),
    [
        ("abc", "abc", 0, 0, 0),
        ("abc", "axc", 1, 0, 0),
        ("abc", "ac", 0, 1, 0),
        ("ac", "abc", 0, 0, 1),
        ("kitten", "sitting", 2, 0, 1),
        ("", "abc", 0, 0, 3),
        ("abc", "", 0, 3, 0),
    ],
)
def test_levenshtein_sdi_exactness(
    ref: str, hyp: str, exp_s: int, exp_d: int, exp_i: int
) -> None:
    ops, s, d, i = levenshtein_align(list(ref), list(hyp))
    assert (s, d, i) == (exp_s, exp_d, exp_i)
    assert len(ops) >= max(len(ref), len(hyp))


def test_compute_cer() -> None:
    exact = compute_cer(["ワタシ、ニホンゴ"], ["ワタシ、ニホンゴ"])
    assert exact == {
        "cer": 0.0,
        "substitutions": 0,
        "deletions": 0,
        "insertions": 0,
        "ref_len": 8,
    }

    # Micro-averaging: total errors = 1, total ref_len = 1 + 5 = 6
    micro = compute_cer(["ア", "アイウエオ"], ["イ", "アイウエオ"])
    assert micro["cer"] == pytest.approx(1.0 / 6.0)
    assert micro["substitutions"] == 1
    assert micro["ref_len"] == 6

    # Insertions > ref_len -> cer > 1.0
    over = compute_cer(["ア"], ["アイウエ"])
    assert over["cer"] == pytest.approx(3.0)

    # Empty refs & lists
    assert compute_cer(["", ""], ["", ""])["cer"] == 0.0
    assert compute_cer([], []) == {
        "cer": 0.0,
        "substitutions": 0,
        "deletions": 0,
        "insertions": 0,
        "ref_len": 0,
    }
    empty_ref = compute_cer([""], ["ア"])
    assert empty_ref["ref_len"] == 0
    assert empty_ref["insertions"] == 1
    assert math.isfinite(empty_ref["cer"])

    with pytest.raises(ValueError):
        compute_cer(["ア"], ["ア", "イ"])


def test_compute_mer_mora_vs_char() -> None:
    ref = "キャク"  # moras: ["キャ", "ク"] (len 2), chars: ["キ", "ャ", "ク"] (len 3)
    hyp = "カク"    # moras: ["カ", "ク"] (len 2), chars: ["カ", "ク"] (len 2)

    cer_res = compute_cer([ref], [hyp])
    mer_res = compute_mer([ref], [hyp])

    assert cer_res["cer"] == pytest.approx(2.0 / 3.0)
    assert cer_res["ref_len"] == 3
    assert mer_res["mer"] == pytest.approx(1.0 / 2.0)
    assert mer_res["substitutions"] == 1
    assert mer_res["deletions"] == 0
    assert mer_res["ref_len"] == 2
    assert mer_res["mer"] != cer_res["cer"]

    # Hiragana / Katakana normalization via kotoba.split_moras
    assert compute_mer(["きょうは"], ["キョウハ"])["mer"] == 0.0

    # Empty / pause-only strings handled safely
    assert compute_mer([""], [""])["mer"] == 0.0
    assert compute_mer(["  、。 "], [""])["mer"] == 0.0


def test_compute_wer() -> None:
    res = compute_wer(["hello world foo"], ["hello  bar   foo baz"])
    assert res == {
        "wer": pytest.approx(2.0 / 3.0),
        "substitutions": 1,
        "deletions": 0,
        "insertions": 1,
        "ref_len": 3,
    }
    assert compute_wer(["a b c"], ["a b c"])["wer"] == 0.0
    assert compute_wer([""], [""])["wer"] == 0.0
    assert compute_wer([], [])["wer"] == 0.0
    assert math.isfinite(compute_wer([""], ["hello"])["wer"])

    with pytest.raises(ValueError):
        compute_wer(["a"], [])


def test_confusion_pairs() -> None:
    pairs = confusion_pairs(["アアア", "カカ"], ["イイア", "ガキ"])
    assert pairs[0] == ("ア", "イ", 2)
    assert all(pairs[i][2] >= pairs[i + 1][2] for i in range(len(pairs) - 1))
    assert set(pairs) == {("ア", "イ", 2), ("カ", "ガ", 1), ("カ", "キ", 1)}

    assert confusion_pairs(["アアア", "カカ"], ["イイア", "ガキ"], top_k=1) == [("ア", "イ", 2)]
    assert confusion_pairs(["アアア"], ["イイイ"], top_k=0) == []
    assert confusion_pairs(["アイウ"], ["アイウ"]) == []
    assert confusion_pairs(["アイ"], ["ア"]) == []  # deletion only

    with pytest.raises(ValueError):
        confusion_pairs(["ア"], ["イ"], top_k=-1)
    with pytest.raises(ValueError):
        confusion_pairs(["ア"], ["イ", "ウ"])


def test_alignment_boundary_error() -> None:
    # Perfect alignment
    gt = [{"t": "ア", "a": 0.1, "e": 0.2}, {"t": "イ", "a": 0.2, "e": 0.35}]
    pred = [
        {"token": "ア", "start_sec": 0.1, "end_sec": 0.2, "confidence": 0.99},
        {"token": "イ", "start_sec": 0.2, "end_sec": 0.35, "confidence": 0.98},
    ]
    perfect = alignment_boundary_error(gt, pred)
    assert perfect["onset_mae_sec"] == pytest.approx(0.0)
    assert perfect["offset_mae_sec"] == pytest.approx(0.0)
    assert perfect["mean_boundary_error_ms"] == pytest.approx(0.0)
    assert perfect["mean_iou"] == pytest.approx(1.0)
    assert perfect["matched"] == 2

    # Exact shift (+0.05 s)
    gt_shift = [{"t": "ア", "a": 0.10, "e": 0.30}]
    pred_shift = [{"token": "ア", "start_sec": 0.15, "end_sec": 0.35, "confidence": 0.9}]
    shifted = alignment_boundary_error(gt_shift, pred_shift)
    assert shifted["onset_mae_sec"] == pytest.approx(0.05)
    assert shifted["offset_mae_sec"] == pytest.approx(0.05)
    assert shifted["mean_start_error_ms"] == pytest.approx(50.0)
    assert shifted["mean_end_error_ms"] == pytest.approx(50.0)
    assert shifted["mean_boundary_error_ms"] == pytest.approx(50.0)
    assert shifted["mean_iou"] == pytest.approx(0.15 / 0.25)

    # Character-level small-kana merging ("キ" + "ョ" -> "キョ")
    gt_mora = [{"t": "キョ", "a": 0.0, "e": 0.16}, {"t": "ウ", "a": 0.16, "e": 0.28}]
    pred_chars = [
        {"token": "キ", "start_sec": 0.0, "end_sec": 0.08, "confidence": 0.9},
        {"token": "ョ", "start_sec": 0.08, "end_sec": 0.16, "confidence": 0.9},
        {"token": "ウ", "start_sec": 0.16, "end_sec": 0.28, "confidence": 0.95},
    ]
    merged = alignment_boundary_error(gt_mora, pred_chars)
    assert merged["matched"] == 2
    assert merged["pred_count"] == 2
    assert merged["mean_iou"] == pytest.approx(1.0)

    # Partial / mismatched tokens with pause
    gt_pau = [{"t": "ア", "a": 0.0, "e": 0.1}, {"t": "、", "a": 0.1, "e": 0.2}, {"t": "イ", "a": 0.2, "e": 0.3}]
    pred_partial = [{"token": "ア", "start_sec": 0.0, "end_sec": 0.1}, {"token": "イ", "start_sec": 0.22, "end_sec": 0.32}]
    partial = alignment_boundary_error(gt_pau, pred_partial)
    assert partial["matched"] == 2
    assert 0.0 < partial["mean_iou"] <= 1.0

    # Empty inputs
    for g, p in (([], []), ([], pred), (gt, [])):
        res = alignment_boundary_error(g, p)
        assert res["matched"] == 0
        assert res["mean_iou"] == 0.0
        assert math.isfinite(res["mean_boundary_error_ms"])


def test_compute_rtf() -> None:
    assert compute_rtf(0.25, 1.0) == pytest.approx(0.25)
    assert compute_rtf(0.5, 0.0) == 0.0
    with pytest.raises(ValueError):
        compute_rtf(-0.1, 1.0)
    with pytest.raises(ValueError):
        compute_rtf(0.1, -1.0)
    with pytest.raises(ValueError):
        compute_rtf(float("nan"), 1.0)
