# Explorer 3 Handoff — Features 12–18 Boundary Analysis (M7 Phase 1, Tier 2 E2E, Iteration 1)

## Verdict
**CLEAN (0 expected Tier 2 failures across all 40 tests in Features 12–18).**

Every boundary, corner-case, and negative test in `tests_e2e/test_tier2_boundaries.py` for Features 12–18 was statically traced against the actual implementations (`asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, `asr/__main__.py`, `asr/server.py`, `asr/web/index.html`, and `asr/audio.py` for `load_wav_bytes`) and cross-checked against `PROJECT.md § Interface Contracts`. All 40 tests align cleanly with both the implementations and the interface contracts.

---

## Feature-by-Feature Audit (40 Tests)

### Feature 12: CTC Decoding & N-gram LM (`asr/decoding.py`) — 7/7 Expected PASS
- `test_beam_width_one`: `prefix_beam_search` with `beam_width=1` preserves the peak path `[0, t_a, t_a, 0, t_i, 0]`, returning 1 hypothesis matching `greedy_decode` (`"アイ"`) with a finite score.
- `test_extreme_temperatures`: `_prepare_log_probs` scales `arr / temp` in `float64` and subtracts `row_max` before `exp`, remaining numerically stable and finite at both `0.1` and `5.0`.
- `test_extreme_blank_bias`: `blank_bias=10.0` forces blank dominance (`text == ""`); `blank_bias=-5.0` produces finite beam scores.
- `test_all_blank_log_probs`: Both `greedy_decode` (`text=""`, `token_ids=[]`) and `prefix_beam_search` (`b[0]["text"] == ""`) return finite scores.
- `test_single_frame_log_probs`: 1-frame `(1, V)` input decodes cleanly to `"ア"` in both greedy and beam search.
- `test_lm_empty_corpus_and_unseen_prefix`: `CharNgramLM.fit([])` returns `0.0` (empty vocab guard at `asr/decoding.py:121`); `fit([""])` has `vocab={EOS}` and positive add-k smoothed probabilities for unseen prefixes/tokens, yielding finite `math.log(prob)`.
- `test_insertion_bonus_effect`: `insertion_bonus=2.0` adds `+2.0 * len(pref)` to non-empty hypotheses, so `h2[0]["score"] >= h0[0]["score"] - 1e-6`.
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #6`.

### Feature 13: Viterbi Forced Alignment (`asr/decoding.py`) — 5/5 Expected PASS
- `test_viterbi_align_empty_token_ids`: `num_tokens == 0` returns `[]` (`asr/decoding.py:467`).
- `test_viterbi_align_single_token_single_frame`: `t_steps == 1 == min_frames`, `dp[0, 1]` selected as `end_state`, returns 1 span with `token="ア"`, `start_sec=0.0`, `end_sec=0.04`, finite confidence.
- `test_viterbi_align_uniform_log_probs`: Constant `emit` values; DP transitions only skip blank states (`can_skip[3::2]`), never odd token states, so all 3 tokens are visited monotonically with finite start/end/confidence.
- `test_viterbi_align_tokens_exceed_frames`: `t_steps < min_frames` raises `ValueError` (`asr/decoding.py:471`), caught and accepted by test.
- `test_viterbi_align_empty_log_probs`: `t_steps == 0 < min_frames == 1` raises `ValueError` (`asr/decoding.py:471`), caught and accepted by test.
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #6`.

### Feature 14: ASR Evaluation Metrics (`asr/metrics.py`) — 6/6 Expected PASS
- `test_metrics_empty_lists`: `_error_rate(0, 0) == 0.0`, `ref_len == 0` for CER/MER/WER.
- `test_metrics_empty_ref_and_empty_hyp_strings`: `compute_cer([""], [""])["cer"] == 0.0`; `compute_cer(["アイウ"], [""])` gives `deletions=3, cer=1.0`; `compute_cer([""], ["アイ"])` gives `insertions=2, cer=1.0` (finite, `>= 0.0`).
- `test_metrics_mismatched_lengths_raises`: `_validate_pair_sequences` raises `ValueError` in all three functions (`asr/metrics.py:101-105`).
- `test_confusion_pairs_no_substitutions_and_top_k_zero`: Returns `[]` for exact matches, deletions-only, `top_k=0` (`asr/metrics.py:221`), and empty lists.
- `test_alignment_boundary_error_empty_inputs`: `matched == 0` branch (`asr/metrics.py:305-308`) returns a dict of all finite floats/ints (`0.0` / `0`).
- `test_compute_cer_exceeds_one_on_heavy_insertions`: `compute_cer(["ア"], ["アイウエオ"])` returns `insertions=4, ref_len=1, cer=4.0`.
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #6`.

### Feature 15: High-Level Inference Engine (`asr/inference.py`) — 5/5 Expected PASS
- `test_from_checkpoint_missing_file_raises`: Re-raises `FileNotFoundError` (`asr/inference.py:246-247`).
- `test_redecode_unknown_utterance_id_raises`: Raises `KeyError` (`asr/inference.py:511-512`), accepted by `pytest.raises((KeyError, ValueError))`.
- `test_transcribe_pure_silence`: 1.0 s silence produces `duration_sec=1.0`, finite `rtf`, string `text`.
- `test_transcribe_empty_audio`: `wav_proc.size == 0` fast path (`asr/inference.py:432-446`) returns `text=""`, `duration_sec=0.0`, `rtf=0.0`.
- `test_redecode_extreme_decode_params`: Cached `log_probs` re-decoded with `beam_width=1`, `temperature in (0.1, 5.0)`, `blank_bias in (-5.0, 5.0)`; `viterbi_align` failures (if any) are caught gracefully (`asr/inference.py:398-399`).
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #7`.

### Feature 16: Full CLI (`asr/__main__.py`) — 6/6 Expected PASS
- `test_cli_unknown_subcommand`: `argparse` exits with code 2, non-empty stderr, no `Traceback`.
- `test_cli_generate_missing_out_dir`: `--out-dir` is `required=True` (`asr/__main__.py:411`); exits with code 2, non-empty stderr, no `Traceback`.
- `test_cli_transcribe_missing_checkpoint`: `FileNotFoundError` caught in `main()` (`asr/__main__.py:509-524`), prints `Error: ...` to stderr, returns exit code 1.
- `test_cli_transcribe_missing_wav`: `FileNotFoundError` caught in `main()`, prints `Error: ...` to stderr, returns exit code 1.
- `test_cli_train_invalid_arch`: `--arch` constrained by `choices=VALID_MODEL_ARCHS` (`asr/__main__.py:431-435`); exits with code 2, non-empty stderr, no `Traceback`.
- `test_cli_transcribe_missing_input_source`: Mutually exclusive group `--wav`/`--tts` has `required=True` (`asr/__main__.py:470`); exits with code 2, non-empty stderr.
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #7`.

### Feature 17: FastAPI Backend (`asr/server.py`) — 6/6 Expected PASS
- `test_api_redecode_unknown_utterance_404`: `KeyError` from `eng.redecode` mapped to HTTP `404` (`asr/server.py:924-928`).
- `test_api_transcribe_corrupt_wav_400_or_422`: `load_wav_bytes` raises `ValueError` (`asr/audio.py:229-255`), mapped to HTTP `400` (`asr/server.py:738-739`).
- `test_api_transcribe_empty_file_400_or_422`: `len(raw_audio_bytes) == 0` returns HTTP `400` (`asr/server.py:592-593`).
- `test_api_tts_roundtrip_missing_text_422_or_400`: Required `text: str` on `TTSRoundtripRequest` (`asr/server.py:78`) triggers FastAPI HTTP `422`.
- `test_api_redecode_malformed_payload_422`: Required `utterance_id: str` on `RedecodeRequest` (`asr/server.py:93`) triggers FastAPI HTTP `422`.
- `test_api_health_without_model_loaded`: `GET /api/health` returns `200` with `{"status": "ok", "model_loaded": False}`; `POST /api/transcribe` calls `_require_engine()` which returns HTTP `503` (`asr/server.py:492-499`).
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #8`.

### Feature 18: Zero-CDN Web Playground (`asr/web/index.html`) — 5/5 Expected PASS
- `test_web_html_well_formed_script_and_style_tags`: Exactly 1 `<style>...</style>` (lines 7–504) and 1 `<script>...</script>` (lines 821–2121), balanced.
- `test_web_no_common_cdn_hosts`: Zero external URLs or CDN hosts anywhere in `asr/web/index.html`.
- `test_web_utf8_charset_declared`: `<meta charset="utf-8">` on line 4; served with `media_type="text/html; charset=utf-8"` (`asr/server.py:509`).
- `test_web_unknown_route_returns_404`: Standard FastAPI 404.
- `test_web_disallowed_method_on_root_returns_405`: Standard FastAPI 405 for `DELETE /`.
- **Contract check**: Exact match with `PROJECT.md § Interface Contracts #8`.

---

## Minor Hardening Note (Out of Scope for Tier 2, Useful for Tier 5)
- In `asr/server.py` (`post_transcribe` lines 748–754), if a client uploads a valid RIFF/WAVE header containing only a handful of samples (e.g., 1–10 samples, shorter than `Conv2dSubsampling`'s minimum frame count), `eng.transcribe(...)` could raise a `ValueError` or `RuntimeError` that is not currently wrapped in an `HTTPException(status_code=400/422)` (would become HTTP 500). Not triggered by Tier 2, but worth hardening during M7 Phase 2 (Tier 5).

## Implementation Plan
**No code changes required for Features 12–18** based on static boundary analysis. Wait for Explorer 1's actual pytest run to confirm 40/40 PASS on Features 12–18.
