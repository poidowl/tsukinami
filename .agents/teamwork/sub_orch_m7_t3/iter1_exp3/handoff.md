# Explorer 3 Handoff — M7 Phase 1 Tier 3 Cross-Feature Combinations (Second Half)

## Scope Audited
- **Test file**: `tests_e2e/test_tier3_combinations.py` (tests 8–12, lines 260–447) + `tests_e2e/conftest.py`
- **Implementation files cross-checked**:
  - `asr/decoding.py`
  - `asr/metrics.py`
  - `asr/inference.py`
  - `asr/__main__.py`
  - `asr/server.py`
  - `asr/web/index.html`
  - `asr/synth_data.py` (manifest `audio_path` format & `synthesize_tsukinami` stdout cleanliness)

## Overall Verdict
**CLEAN — No blocking bugs, API schema mismatches, caching defects, or contract violations found** across the 5 audited Tier 3 combination tests and their backing `asr/` implementations. All 5 tests are expected to pass on the first run.

---

## Detailed Test-by-Test Contract Cross-Check

### 1. `test_t3_model_logprobs_greedy_beam_lm_and_viterbi` (`tests_e2e/test_tier3_combinations.py:260-307`)
- **Features**: F10 (`build_model`), F12 (`CharNgramLM`, `greedy_decode`, `prefix_beam_search`), F13 (`viterbi_align`).
- **Cross-check**:
  - `CharNgramLM.to_dict()` / `CharNgramLM.from_dict()` (`asr/decoding.py:145-193`) preserves `order`, `smoothing`, `vocab`, `_ngram_counts`, and `_context_totals`; `lm2.score_next("オハ", "ヨ")` matches `lm.score_next("オハ", "ヨ")` exactly.
  - `greedy_decode` (`asr/decoding.py:206-236`) returns `{"text", "token_ids", "score"}`.
  - `prefix_beam_search` (`asr/decoding.py:239-420`) returns `>= 1` hypotheses with keys `{"text", "score", "acoustic_score", "lm_score"}`, sorted descending by `score` (`key=lambda h: (-h["score"], h["text"])`), both with `lm=None` and `lm=lm2, lm_weight=0.5, insertion_bonus=0.2`.
  - `viterbi_align` (`asr/decoding.py:423-539`) returns one dict per token in `ref_ids` with keys `{"token", "start_sec", "end_sec", "confidence"}`, finite `confidence` in `[0, 1]`, and monotonically non-decreasing `start_sec`. `model.output_frame_stride_ms(audio_cfg)` returns `40.0` ms.
- **Status**: PASS expected.

### 2. `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics` (`tests_e2e/test_tier3_combinations.py:309-350`)
- **Features**: F7 (`synthesize_fast_kotoba`), F13 (`viterbi_align`), F14 (`alignment_boundary_error`, `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`).
- **Cross-check**:
  - `synthesize_fast_kotoba("ワタシ、ニホンゴ", sr=16000, seed=42)` yields ~1.1 s audio (~27 subsampled frames vs. `min_frames = 8`) and mora dicts with `{"t", "a", "e"}`.
  - `alignment_boundary_error(gt_moras, pred_align)` (`asr/metrics.py:245-328`) merges small-kana tokens, aligns via Levenshtein, and returns a 9-key dict (`onset_mae_sec`, `offset_mae_sec`, `mean_start_error_ms`, `mean_end_error_ms`, `mean_boundary_error_ms`, `mean_iou`, `matched`, `gt_count`, `pred_count`) with strictly finite numeric values.
  - `compute_cer` (`asr/metrics.py:114-142`) returns `{"cer", "substitutions", "deletions", "insertions", "ref_len"}` with `cer == (S + D + I) / ref_len`.
  - `compute_mer` (`asr/metrics.py:145-176`) returns `{"mer", ...}` with `mer >= 0.0`.
  - `compute_wer(["hello world"], ["hello earth"])` (`asr/metrics.py:179-205`) returns `wer == 0.5`.
  - `confusion_pairs(refs, hyps, top_k=5)` (`asr/metrics.py:208-242`) returns `list[tuple[str, str, int]]` (2 pairs: `('ゴ', 'コ', 1)` and `('カ', 'ガ', 1)`).
- **Status**: PASS expected.

### 3. `test_t3_engine_transcribe_visuals_corruption_and_redecode` (`tests_e2e/test_tier3_combinations.py:352-368`)
- **Features**: F5 (`apply_corruption`), F12 (`DecodeConfig`), F15 (`ASREngine.transcribe`, `ASREngine.redecode`).
- **Cross-check**:
  - `ASREngine.transcribe(audio, sr=16000, include_visuals=True)` (`asr/inference.py:405-503`) populates all 10 required non-None keys: `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`, and stores `log_probs` in the 32-entry LRU cache (`self._cache`).
  - `ASREngine.redecode(utterance_id, DecodeConfig(...))` (`asr/inference.py:505-536`) hits the LRU cache for both `method="greedy"` and `method="beam", beam_width=4, temperature=1.4, blank_bias=-0.5`, returning `dict` with `str` `"text"`.
  - `viterbi_align` inside `_decode_and_align` (`asr/inference.py:381-399`) is guarded against `ValueError`, preventing edge-case alignment failures when `blank_bias` or `temperature` alters emitted token length.
- **Status**: PASS expected.

### 4. `test_t3_cli_pipeline_generate_train_eval_transcribe` (`tests_e2e/test_tier3_combinations.py:370-408`)
- **Features**: F1, F7, F9, F11, F15, F16 (CLI `generate` → `train` → `eval` → `transcribe --wav` & `--tts`).
- **Cross-check**:
  - `generate --out-dir ... --num-train 6 --num-val 2 --engine fast` (`asr/__main__.py:207-221, 407-421`): writes `train.jsonl` and `val.jsonl`. Verified in `asr/synth_data.py:786` that `audio_path` is written as a resolved absolute path (`str(abs_wav)`), so passing `first_val["audio_path"]` to `transcribe --wav` from `cwd=repo_root` resolves cleanly.
  - `train --train-manifest ... --val-manifest ... --out-dir ... --arch cnn_bigru --epochs 1` (`asr/__main__.py:224-265, 424-445`): writes `best.pt` and `latest.pt` under `--out-dir`. With 6 train / 2 val utterances and 1 epoch, CPU runtime is ~1–2 s (well under `timeout=120`).
  - `eval --checkpoint ... --manifest ... --method greedy` (`asr/__main__.py:268-297, 448-462`): prints `CER: ...` to stdout (`"cer" in (stdout + stderr).lower()`).
  - `transcribe --checkpoint ... --wav <path> --method greedy --json` (`asr/__main__.py:300-348, 465-488`): outputs a single valid JSON object with `"text"`.
  - `transcribe --checkpoint ... --tts あか --preset default --method beam --json`: uses default `--engine tsukinami` (`asr/__main__.py:477`), synthesizes 2-mora `"あか"` (~2–3 s, well under `timeout=60`), and prints a single valid JSON object with `"text"`.
- **Status**: PASS expected.

### 5. `test_t3_api_tts_roundtrip_corruption_redecode_and_info` (`tests_e2e/test_tier3_combinations.py:410-447`)
- **Features**: F5, F8, F12, F15, F17 (`asr/server.py`), F18 (`asr/web/index.html`).
- **Cross-check**:
  - `GET /api/info` (`asr/server.py:518-557`): returns `200` with sanitized JSON dict (`model_loaded: True`, model/vocab/preset/history metadata).
  - `POST /api/tts-roundtrip` (`asr/server.py:75-88, 758-893`):
    - Pydantic v2 `TTSRoundtripRequest` (`extra="forbid"`), `CorruptionParams` (`extra="forbid"`), and `DecodeParams` (`extra="forbid"`) accept all fields sent by the test (`text`, `preset`, `synth_engine`, `corruption: {snr_db, noise_type}`, `decode_cfg: {method, beam_width}`).
    - Returns `200` with `audio_b64` (16-bit mono RIFF WAV), non-empty `ground_truth_moras`, numeric `cer >= 0.0`, and top-level unpacked `TranscribeResult` keys including `text` and `utterance_id`.
    - `helpers.extract_transcribe_payload(rt_data)` extracts `utterance_id` from the flat payload cleanly.
  - `POST /api/redecode` (`asr/server.py:90-101, 895-932`): accepts `{"utterance_id": utt_id, "decode_cfg": {"method": "greedy", "temperature": 1.2, "blank_bias": 0.1}}`, re-decodes under `app.state.engine_lock`, and returns `200` with `"text"`.
  - `GET /` (`asr/server.py:501-509`, `asr/web/index.html`): returns `200` with `content-type: text/html; charset=utf-8`. Static regex inspection confirmed zero external `<script src=...>` or `<link href=...>` CDN URLs, and all frontend API endpoints (`/api/info`, `/api/redecode`, `/api/transcribe`, `/api/tts-roundtrip`) match `asr/server.py`.
- **Status**: PASS expected.

---

## Minor Non-Blocking Observations (No Fixes Required for Tier 3)
- `asr/server.py:797` and `848`: `_resolve_corruption_dict(req.corruption)` is invoked twice on `/api/tts-roundtrip` (once upfront to fail fast before TTS synthesis, once inside `_apply_optional_corruption`). Harmless and keeps validation clean.
- `asr/server.py:487`: `app.state.engine_lock` (`threading.Lock()`) properly serializes `ASREngine` inference, LRU cache mutation, and `info()` reads across concurrent requests.
