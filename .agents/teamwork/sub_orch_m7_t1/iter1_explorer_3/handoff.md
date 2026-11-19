# Explorer 3 Handoff — Features #12–#18 Contract & TTS Non-Regression Audit (`sub_orch_m7_t1`)

## Executive Summary
- **TTS Non-Regression Status**: **CLEAN (100% Untouched)**. `git diff --name-only` and `git diff --cached --name-only` are both empty. Only new untracked project files (`asr/`, `tests/`, `tests_e2e/`, `pyproject.toml`, `.gitignore`, `PROJECT.md`, `TEST_INFRA.md`, `TEST_READY.md`, `.agents/`) exist in the working tree. All existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) are completely unmodified.
- **Features #12–#18 Contract Audit Status**: **ALL CLEAR (0 contract mismatches or implementation bugs found)**. Every test in `TestTier1Feature12Decoding` through `TestTier1Feature18WebPlayground` (`tests_e2e/test_tier1_features.py` lines 921–1503) aligns cleanly with `PROJECT.md § Interface Contracts` and the implementations in `asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, `asr/__main__.py`, `asr/server.py`, and `asr/web/index.html`.
- **Implementation Fix Plan**: None required for Features #12–#18 based on static contract audit.

---

## 1. TTS Non-Regression Verification

Commands run in `/home/antigravity/poidowl/tsukinami`:
- `git status --short`:
  ```text
  ?? .agents/
  ?? .gitignore
  ?? PROJECT.md
  ?? TEST_INFRA.md
  ?? TEST_READY.md
  ?? asr/
  ?? pyproject.toml
  ?? tests/
  ?? tests_e2e/
  ```
- `git diff --name-only`: *(empty)*
- `git diff --cached --name-only`: *(empty)*

**Conclusion**: Zero modifications to any tracked `tsukinami` TTS source file, HTML demo, or repo asset.

---

## 2. Feature-by-Feature Contract Cross-Check (Features #12–#18)

### Feature #12: CTC Decoding (`asr/decoding.py`)
Cross-checked `TestTier1Feature12Decoding` (7 tests, lines 925–1033) vs `asr/decoding.py` & `PROJECT.md § 6`:
- `greedy_decode(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0)` → returns `{"text": str, "token_ids": list[int], "score": float}`. Handles blank-separated repeats (`[t_a, t_a, 0, t_a]` → `[t_a, t_a]`, `"アア"`) and empty `(0, V)` inputs.
- `prefix_beam_search(log_probs, tokenizer, cfg, lm=None)` → maintains separate `(p_b, p_nb)` log-probs, merges equivalent CTC prefixes via `_logsumexp2`, preserves self-loops even when pruned from `top_k`, returns up to `cfg.beam_width` hypotheses sorted descending by `score` with keys `{"text", "score", "acoustic_score", "lm_score"}`.
- `CharNgramLM(order=3, smoothing=0.1)` → `.fit(texts)`, `.score_next(prefix, token) -> float` (finite, `<= 0.0`, hierarchical Dirichlet/add-k backoff), `.to_dict()` / `.from_dict(d)` JSON round-trip exact match.
- LM rescoring: `use_lm = lm is not None and lm_weight > 0.0`; updates `lm_cache` incrementally and populates `lm_score != 0.0`.
- **Verdict**: Match (0 discrepancies).

### Feature #13: Viterbi Forced Alignment (`asr/decoding.py`)
Cross-checked `TestTier1Feature13Alignment` (5 tests, lines 1040–1118) vs `asr/decoding.py` (lines 423–539) & `PROJECT.md § 6`:
- `viterbi_align(log_probs, token_ids, tokenizer, frame_stride_ms=40.0)` → returns `[{"token", "start_sec", "end_sec", "confidence"}]`.
- Extended CTC state lattice `[b, y_0, b, y_1, ..., b]` with `can_skip` disabled across identical adjacent tokens (enforcing blank separation for repeated identical tokens).
- Timestamps scale linearly with `frame_stride_ms / 1000.0`, remain within `[0.0, T * stride_s]`, and are monotonically non-decreasing.
- `confidence` is mean frame posterior `exp(lp)` clipped to `[0.0, 1.0]`, strictly higher for peaky vs uniform posteriors.
- **Verdict**: Match (0 discrepancies).

### Feature #14: ASR Evaluation Metrics (`asr/metrics.py`)
Cross-checked `TestTier1Feature14Metrics` (7 tests, lines 1125–1209) vs `asr/metrics.py` & `PROJECT.md § 6`:
- `compute_cer(refs, hyps, *, normalize_kana=False)` → `{"cer", "substitutions", "deletions", "insertions", "ref_len"}` with corpus-level S/D/I aggregation.
- `compute_mer(refs, hyps, *, ignore_pauses=False)` → uses `kotoba.split_moras` (`"キャ"` vs `"カ"` = 1 mora sub / 1 ref = `1.0`).
- `compute_wer(refs, hyps)` → whitespace-delimited word Levenshtein.
- `confusion_pairs(refs, hyps, top_k=10, *, unit="char")` → returns `[(ref_tok, hyp_tok, count)]` sorted by `(-count, ref_tok, hyp_tok)` sliced to `top_k`.
- `alignment_boundary_error(gt_moras, pred_align)` → merges small-kana ASR tokens, aligns via Levenshtein, returns finite `onset_mae_sec`, `offset_mae_sec`, `mean_start_error_ms`, `mean_end_error_ms`, `mean_boundary_error_ms`, `mean_iou`, `matched`, `gt_count`, `pred_count` with exact alignment having higher IoU and lower error than shifted alignment.
- **Verdict**: Match (0 discrepancies).

### Feature #15: High-Level Inference Engine (`asr/inference.py`)
Cross-checked `TestTier1Feature15Engine` (6 tests, lines 1216–1281) vs `asr/inference.py` & `PROJECT.md § 7`:
- `ASREngine.from_checkpoint(path, lm=None, *, device="cpu", max_cache_size=32)` → loads `best.pt`, accepts both `audio_config` and `audio_cfg` keys, supports optional `CharNgramLM`.
- `engine.transcribe(wav, sr=16000, decode_cfg=None, *, include_visuals=False)` → resamples when `sr != audio_cfg.sample_rate`, returns `{"text", "hypotheses", "alignment", "rtf", "duration_sec", "utterance_id"}`, plus `{"waveform", "log_mel", "ctc_posteriors", "vad_segments"}` when `include_visuals=True`.
- `engine.redecode(utterance_id, decode_cfg)` → uses LRU `_cache` (`OrderedDict`) to re-run decoding and alignment without acoustic model forward pass; raises `KeyError` on unknown ID; `blank_bias=50.0` forces blank argmax (`text == ""`).
- **Verdict**: Match (0 discrepancies).

### Feature #16: Full CLI (`asr/__main__.py`)
Cross-checked `TestTier1Feature16CLI` (7 tests, lines 1288–1372) vs `asr/__main__.py` & `PROJECT.md § 7`:
- `--help`: lists all 6 required subcommands (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`).
- `generate`: `--out-dir`, `--num-train`, `--num-val`, `--engine`, `--seed`.
- `train`: `--train-manifest`, `--val-manifest`, `--out-dir`, `--arch`, `--epochs` (plus optional hyperparams) → creates `best.pt` and `latest.pt`.
- `eval`: `--checkpoint`, `--manifest`, `--method`, `--beam-width`, `--json` → prints `CER: ...%` (case-insensitive `"cer"` present).
- `transcribe`: `--checkpoint`, mutually exclusive `--wav` | `--tts`, `--preset`, `--engine`, `--method`, `--beam-width`, `--json` → prints clean single JSON object to stdout with `"text"` key when `--json` is passed.
- `serve --help`: exposes `--checkpoint`, `--host`, `--port`.
- **Verdict**: Match (0 discrepancies).

### Feature #17: FastAPI Backend (`asr/server.py`)
Cross-checked `TestTier1Feature17API` (6 tests, lines 1379–1441) vs `asr/server.py` & `PROJECT.md § 8`:
- `create_app(checkpoint_path=None, engine=None) -> FastAPI`: supports `engine`, `checkpoint_path`, or no-model mode (503 on inference routes).
- `GET /api/health` → `200`, `{"status": "ok", "model_loaded": bool}`.
- `GET /api/info` → `200`, includes `vocab`, `tokenizer`, `tsukinami_presets`, `preset_details`, `arch`, `history`, etc.
- `POST /api/transcribe` → accepts multipart `file` (and JSON `audio_b64`), defaults `include_visuals=True`, returns all core + visual keys (`text`, `hypotheses`, `alignment`, `utterance_id`, `duration_sec`, `rtf`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`); returns `400`/`422` cleanly on invalid audio/params.
- `POST /api/tts-roundtrip` → accepts `{text, preset, hz, fscale, yure, rate, synth_engine, corruption, decode_cfg, include_visuals}`, returns flat `TranscribeResult` merged with `audio_b64` (valid RIFF WAV), `ground_truth_moras`, `cer`, `cer_details`.
- `POST /api/redecode` → accepts `{utterance_id, decode_cfg}` (plus optional flat decode fields), returns re-decoded `text`, `hypotheses`, `alignment`, `decode_ms`; returns `404` on unknown `utterance_id`.
- **Verdict**: Match (0 discrepancies).

### Feature #18: Zero-CDN Interactive Web Playground (`asr/web/index.html`)
Cross-checked `TestTier1Feature18WebPlayground` (5 tests, lines 1469–1503) vs `asr/web/index.html` & `PROJECT.md § 8`:
- `GET /` serves `asr/web/index.html` (`200 OK`, `text/html; charset=utf-8`, 70,482 bytes, valid `<html>...</html>`).
- Zero CDN assets: no external `http://`, `https://`, or `//` `<script src>`, `<link href>`, or CSS `@import url(...)`.
- 5 `<canvas>` elements (`canvasWaveform`, `canvasMel`, `canvasPosterior`, `canvasAlignment`, `canvasHistory`) using `getContext("2d")`.
- Interactive controls: `type="file"`, 7 `type="range"` sliders, Web Audio API (`AudioContext`, `webkitAudioContext`, `navigator.mediaDevices.getUserMedia`).
- Wires all 4 backend endpoints: `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`.
- **Verdict**: Match (0 discrepancies).

---

## 3. Summary & Recommendations
No contract mismatches, missing fields, or implementation bugs were identified across Features #12–#18, and TTS non-regression is 100% clean. Defer to Explorer 1's live `pytest` execution results for runtime confirmation.
