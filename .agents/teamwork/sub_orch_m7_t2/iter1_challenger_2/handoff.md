# Challenger 2 Handoff — M7 Phase 1 Tier 2 E2E (`sub_orch_m7_t2`, Iteration 1)

## Verdict: **PASS**

No correctness, boundary, or interface-contract defects were found across Features 12–18 (`asr/decoding.py`, `asr/metrics.py`, `asr/server.py`, `asr/web/index.html`).

---

## Mandatory Reads Completed
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md`
- `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t2/SCOPE.md`
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t2/iter1_worker/handoff.md`

---

## Adversarial Probes Executed & Results

All ad-hoc probe scripts were staged in temporary directories created via `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`, executed using `PYTHONPATH=. .venv/bin/python`, and removed immediately after execution (`CLEANUP_OK`). Neither the working tree nor `tests_e2e/` was touched.

### 1. `asr/decoding.py` (Features 12 & 13) — **PASS (11/11 probe groups)**
- **`greedy_decode`**:
  - Empty frames `(0, V)` → `{"text": "", "token_ids": [], "score": 0.0}`.
  - Single frame `(1, V)` (blank peak and non-blank peak) → exact expected text, token IDs, and finite score.
  - All-blank `(20, V)` → `text=""`, `token_ids=[]`, finite `score <= 0.0`.
  - Extreme temperatures (`1e-6`, `1e-12`, `1e-100`, `1e-305`, `1e6`, `1e12`) → finite scores and expected decoded output without NaN/Inf overflow; invalid temperatures (`0.0`, `-1.0`, `nan`, `inf`, `-inf`, `True`, `"1.0"`) raise `ValueError`.
  - Extreme `blank_bias` (`+1e6` forces all-blank, `-1e6` suppresses blanks) → finite scores; invalid values (`nan`, `inf`, `-inf`, `True`, `"0.0"`) raise `ValueError`.
  - Malformed `log_probs` (1D, 3D, vocab mismatch, `NaN`, `+inf`, all-`-inf` row) → raise `ValueError`.
- **`prefix_beam_search`**:
  - Empty frames `(0, V)` → `[{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]`.
  - Single frame `(1, V)`, all-blank `(8, V)`, blank-only finite (`-inf` on all non-blanks), non-blank-only finite (`-inf` on blank), and vocab-size-1 (`["<blank>"]`) → all handled cleanly with finite scores.
  - Extreme temperatures (`1e-6`, `1e6`) and extreme `blank_bias` (`+1e4`, `-1e4`) → finite scores, contract-compliant ranking.
  - Exact probability conservation on `(T=3, V=3)` with wide beam (`beam_width=64`) → `sum(exp(acoustic_score)) == 1.0` within `1e-6`.
  - Unfitted & fitted `CharNgramLM`, phoneme tokenizer (`mode="phoneme"`), and non-`DecodeConfig` (`TypeError`) → all contract-compliant.
- **`CharNgramLM`**:
  - Invalid `order` (`0`, `-1`, `True`, `1.5`, `"3"`) and `smoothing` (`0.0`, `-0.5`, `nan`, `inf`, `True`, `"0.1"`) → `ValueError`.
  - Unfitted LM and `.fit([])` return `0.0`; `.fit([""])` returns finite negative log-prob.
  - Orders `1, 2, 3, 5` with unseen contexts/tokens return finite negative log-probs; `to_dict()` / `from_dict()` JSON round-trip preserves equality and scores; malformed `from_dict` inputs raise `TypeError`/`ValueError`.
- **`viterbi_align`**:
  - Empty `token_ids=[]` with `T=0` and `T=5` → `[]`.
  - Single frame `T=1` with 1 token → 1 monotonic span `[0.0, 0.04]` with `confidence in [0, 1]`.
  - Tokens exceeding frames (`T=1`, 2 tokens) → `ValueError`.
  - Repeated adjacent identical tokens `[a, a]` with `T=2` → `ValueError` (enforces mandatory intervening blank, `min_frames = 3`); `[a, i]` with `T=2` and `[a, a]` with `T=3` succeed monotonically.
  - Blocked path (`-inf` on required token across all frames), `blank_id` in `token_ids`, out-of-range/negative/bool token IDs, and invalid `frame_stride_ms` (`0.0`, `-10.0`, `nan`, `inf`, `True`) → `ValueError`.

### 2. `asr/metrics.py` (Feature 14) — **PASS (4/4 probe groups)**
- **`compute_cer`, `compute_mer`, `compute_wer`**:
  - Empty corpora `([], [])` and empty strings `([""], [""])` / whitespace `(["   "], ["  "])` → `0.0` error rate, `ref_len=0`.
  - Empty ref with non-empty hyp → `1.0` error rate with accurate `insertions` count and `ref_len=0`.
  - Non-empty ref with empty hyp → `1.0` error rate with accurate `deletions` count.
  - Mismatched sequence lengths → `ValueError`.
  - Heavy insertions (50 char insertions on 1-char ref → `cer=50.0`; 25 word insertions on 1-word ref → `wer=25.0`) → accurate unbounded error rate.
  - `normalize_kana=True` (hiragana vs katakana → `0.0`) and `ignore_pauses=True/False` → contract-compliant.
- **`confusion_pairs`**:
  - Empty inputs, identical inputs, pure insertions/deletions, and `top_k=0` → `[]`.
  - Deterministic lexicographic tie-breaking, `unit="mora"` and `unit="word"` verified.
  - Mismatched lengths, `top_k=-1`, `top_k=True`, invalid `unit` → `ValueError`.
- **`alignment_boundary_error`**:
  - Both empty, either empty, and disjoint tokens → `matched=0`, `mean_iou=0.0`, `onset_mae_sec=0.0`.
  - Exact match, small-kana merging (`キ` + `ョ` → `キョ`), zero-duration spans (`a == e == 0.5`), and heavy insertions (20 inserted tokens) → accurate `mean_iou=1.0`, `matched=1`.
- **`compute_rtf`**:
  - Zero duration → `0.0`; negative/NaN/Inf/bool inputs → `ValueError`.

### 3. `asr/server.py` (Feature 17) — **PASS (2/2 probe groups)**
- **No-model mode (`create_app(checkpoint_path=None, engine=None)`)**:
  - `GET /` → `200` (`text/html`), `GET /api/health` → `200` (`{"status": "ok", "model_loaded": false}`), `GET /api/info` → `200` (`model_loaded: false`, presets populated).
  - `POST /api/transcribe`, `POST /api/tts-roundtrip`, `POST /api/redecode` → `503`.
  - Disallowed HTTP methods on `/` (`POST`, `PUT`, `DELETE`, `PATCH`) → `405`; unknown route `/api/nonexistent` → `404`.
- **Loaded-model mode (in-memory `ASREngine` with tiny `cnn_bigru`)**:
  - `POST /api/redecode` with unknown `utterance_id` → `404`.
  - Malformed `/api/redecode` (missing/whitespace `utterance_id`, extra fields, `beam_width=0`/`999`, `temperature<=0`, invalid `method`) → `422`.
  - Malformed `/api/tts-roundtrip` (missing/whitespace/501-char `text`, unknown `preset`/`synth_engine`, extra fields, `hz<=0`, `yure>1`, invalid `corruption` fields) → `422`.
  - Malformed `/api/transcribe`: JSON missing `audio_b64` or non-object (`422`), empty/bad JSON/bad base64/corrupt WAV/zero-sample WAV (`400`), multipart missing `file` (`422`), multipart empty/corrupt WAV (`400`), invalid `decode_cfg` JSON or bad `temperature` (`422`).
  - Valid WAV transcribe (`200`) followed by cached `/api/redecode` (`200`) succeeded cleanly.

### 4. `asr/web/index.html` (Feature 18) — **PASS (1/1 probe group)**
- Valid UTF-8 decoding verified.
- Zero external `http://` / `https://` URLs and zero external protocol-relative `src`/`href` tags verified.
- Balanced `<script>`/`</script>` and `<style>`/`</style>` tags (>= 1 each), valid `<!doctype html>`, and single balanced `<html>`, `<head>`, `<body>` tags verified.

---

## Hygiene & Isolation Verification
- Working tree untouched (`git diff --stat` empty; no files created outside `.agents/teamwork/sub_orch_m7_t2/iter1_challenger_2/handoff.md`).
- All temporary probe directories removed (`CLEANUP_OK`).
- `tests_e2e/` was not invoked.
