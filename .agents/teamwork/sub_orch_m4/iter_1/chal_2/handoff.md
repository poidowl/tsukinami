# Adversarial Challenger 2 Handoff — Milestone M4 (Metrics & Integration)

## Verdict: PASS

`asr/metrics.py` and its end-to-end integration with M1 (`Tokenizer`, `DecodeConfig`, `kotoba`) and M4 (`CharNgramLM`, `greedy_decode`, `prefix_beam_search`, `viterbi_align`) passed all adversarial probes without errors or contract violations. Zero `torch` imports occurred.

---

## Probe Results Summary

All probes were executed in an isolated temporary directory (`/tmp/teamwork_probe.1IiRFh`, removed before reporting) using `.venv/bin/python`, without modifying the repository working tree.

### 1. Levenshtein Mathematical Properties (`levenshtein_align`) — PASS
- Fuzzed 200 random string pairs & triplets (lengths 0–25 over Japanese katakana + special moras) plus empty/identical/all-different edge cases against an independent 1D-DP reference implementation:
  - `S + D + I == edit_distance` held for 100% of cases.
  - Symmetry: `dist(a, b) == dist(b, a)` and exact net del/ins symmetry `D(a,b) - I(a,b) == I(b,a) - D(b,a)` held for 100% of cases.
  - Triangle inequality: `dist(a, c) <= dist(a, b) + dist(b, c)` held for all 200 triplets.
  - Exact length conservation: `ref_len - D + I == hyp_len` held in both directions for 100% of cases.
  - Alignment reconstruction from `ops` reproduced `ref` and `hyp` exactly, with consistent `match`/`sub`/`del`/`ins` counts.

### 2. CER / MER / WER / RTF Adversarial Cases — PASS
- **Empty & mismatched inputs**:
  - `([], [])` and `([""], [""])` return `0.0` error rate and `ref_len == 0` without `ZeroDivisionError`.
  - `([""], ["アイ"])` returns `1.0` with `insertions > 0`; `(["アイ"], [""])` returns `1.0` with `deletions > 0`.
  - Mismatched `len(refs) != len(hyps)` raises `ValueError` consistently across `compute_cer`, `compute_mer`, and `compute_wer`.
- **Japanese tricky cases**:
  - 拗音 (`キャ`, `シュ`, `チョ`, `ファ`, `ティ`): `"キャ"` vs `"シャ"` yields `CER = 0.5` (`1/2`) vs `MER = 1.0` (`1/1`), confirming `compute_mer` uses `kotoba.split_moras` and properly diverges from character-level CER.
  - 促音 (`ッ`), 長音 (`ー`), 濁音/半濁音 (`ガ`, `パ`): `"ガッコウノパーティー"` splits into 9 moras vs 10 chars; substitution `"ガッコウノバーテー"` yields `CER = 2/10 = 0.2` vs `MER = 2/9 = 0.2222...`.
  - Mixed Hiragana & Katakana (`"きょう"` vs `"キョウ"`): `compute_cer(..., normalize_kana=False)` yields `1.0`, `compute_cer(..., normalize_kana=True)` yields `0.0`, and `compute_mer` yields `0.0` (`ref_len=2`).
  - Whitespace & punctuation (`"ワタシ、ニホンゴ"` vs `"ワタシ ニホンゴ"`): `CER = 0.125`, `MER = 0.0` (both pause characters normalize to `"、"` via `kotoba.split_moras`), and `ignore_pauses=True` yields `0.0` against `"ワタシニホンゴ"`.
- **WER & RTF**:
  - Multiple spaces/tabs tokenize cleanly via `.split()`.
  - `compute_rtf` handles `audio_duration_sec == 0.0` (returns `0.0`) and rejects negative, `NaN`, `inf`, and `bool` inputs with `ValueError`.

### 3. `confusion_pairs` Edge Cases — PASS
- Tie-breaking is deterministic and order-invariant (`(-count, ref_tok, hyp_tok)`).
- `top_k=0` returns `[]`; `top_k > unique_pairs` returns all unique pairs.
- Pure insertions and pure deletions produce `[]` (never misclassified as substitutions).
- Multi-utterance aggregation works accurately across `unit="char"` (`[('キ', 'シ', 2), ('シ', 'チ', 1)]`) and `unit="mora"` (`[('キャ', 'シャ', 2), ('シュ', 'チュ', 1)]`).
- Invalid `top_k` (`-1`, `True`) and invalid `unit` raise `ValueError`.

### 4. `alignment_boundary_error` Stress Tests — PASS
- **Perfect alignment**: `onset_mae_sec == 0.0`, `offset_mae_sec == 0.0`, `mean_iou == 1.0`.
- **Uniform shift (+50 ms on 200 ms spans)**: `onset_mae_sec == 0.05`, `offset_mae_sec == 0.05`, `mean_boundary_error_ms == 50.0`, `mean_iou == 0.6`.
- **Scaled/stretched spans (2×)**: finite MAE and `mean_iou` in `[0.0, 1.0]`.
- **Non-overlapping spans**: `mean_iou == 0.0`.
- **Zero-duration spans**: identical point spans yield `mean_iou == 1.0`; mismatched or point-vs-interval spans yield `mean_iou == 0.0` (no `ZeroDivisionError`).
- **Small-kana merging**: `キ` + `ャ` in `pred_align` merges cleanly to `キャ` (`matched == 2`, `mean_iou == 1.0`); small kana after pause/space does not merge; leading small kana does not crash.
- **Missing/extra tokens & empty inputs**: handled cleanly with `matched == 0`, `mean_iou == 0.0` on empty inputs.
- **Hiragana vs Katakana**: normalized via `kotoba.to_kata` (`きょ` + `う` matches `キ` + `ョ` + `ウ`, `mean_iou == 1.0`).

### 5. End-to-End M1+M4 Pipeline Probe — PASS
- Tested `Tokenizer("kana")` + `DecodeConfig` + `CharNgramLM` (with `to_dict`/`from_dict` round-trip) + `greedy_decode` + `prefix_beam_search` + `viterbi_align` + `compute_cer` + `compute_mer` + `alignment_boundary_error` (against real `kotoba.tracks_from_kana(text)["moras"]`) on `"ワタシ、ニホンゴ"` and `"キョウワ イイ テンキ"`:
  - Both greedy and beam search recovered exact transcripts (`CER = 0.0`, `MER = 0.0`).
  - `viterbi_align` produced monotonic spans with `start_sec < end_sec` and `confidence` in `[0.0, 1.0]`.
  - `"torch" not in sys.modules` confirmed pure-NumPy/Python execution.

---

## Non-Blocking Observation
- In `alignment_boundary_error`, `kotoba.tracks_from_kana("キョウワ イイ テンキ")["moras"]` normalizes spaces to `"、"` (`['キョ', 'ウ', 'ワ', '、', 'イ', 'イ', '、', 'テ', 'ン', 'キ']`), while `Tokenizer("kana")` + `viterbi_align` emits `" "` (`['キ', 'ョ', 'ウ', 'ワ', ' ', 'イ', 'イ', ' ', 'テ', 'ン', 'キ']`). Because `" "` != `"、"` in `alignment_boundary_error`, the 2 pause tokens are treated as substitutions while all 8 speech moras match cleanly (`matched=8/10`). This does not corrupt speech-mora boundary errors and is acceptable behavior; if pause-token matching across `" "`/`"、"` is ever desired in future milestones, normalizing `tok in kotoba.PAUSE` to `"、"` in `alignment_boundary_error` would align them.
