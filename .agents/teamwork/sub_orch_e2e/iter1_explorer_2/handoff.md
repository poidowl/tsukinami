# Explorer 2 Handoff — Tier 1 & Tier 2 Test Design (Features #12–#18)

**Track**: E2E Testing Track (`sub_orch_e2e`) — Iteration 1  
**Scope**: Exact opaque-box test cases for `tests_e2e/test_tier1_features.py` (Tier 1) and `tests_e2e/test_tier2_boundaries.py` (Tier 2) covering **Features #12 through #18** from `PROJECT.md § Feature Inventory` and `§ Interface Contracts` (§6, §7, §8).

---

## 1. Design Principles & Shared Helpers (`tests_e2e/conftest.py`)

### 1.1 Collection Safety & Anti-Coupling Rules
- **Lazy `asr.*` imports**: Every `from asr... import ...` MUST live inside test functions or fixture bodies (never at module top level) so `pytest --collect-only tests_e2e/` passes even if `asr/` is partially implemented, while test execution fails genuinely on missing/broken modules (zero `pytest.skip`, zero dummy passes).
- **Strict Contract Adherence**: Only call documented symbols, kwargs, CLI flags, and HTTP routes from `PROJECT.md § Interface Contracts`. Never hardcode uncontracted internal dict keys (e.g., for `alignment_boundary_error`, validate `dict` structure, finiteness, and relative ordering between exact vs. shifted alignments rather than guessing exact key names).
- **Progressive Testability**:
  - Features **#12 (Decoding)**, **#13 (Viterbi Alignment)**, and **#14 (Metrics)** MUST NOT depend on `asr.models` or `asr.train`. They use pure-NumPy analytical `log_probs` matrices (`log_softmax` over synthetic logits) + `Tokenizer`.
  - Features **#15 (ASREngine)**, **#16 (CLI)**, **#17 (FastAPI)**, and **#18 (Web Playground)** share lightweight **session-scoped** fixtures (`tiny_dataset_dir`, `tiny_checkpoint_path`, `tiny_engine`, `api_client`, `api_client_no_model`, `run_cli`) so CPU runtime remains small on 2 vCPUs.

### 1.2 Shared Analytical & Harness Helpers Needed in `conftest.py`
1. `make_log_probs(frame_token_ids: Sequence[int], vocab_size: int, peak_logit: float = 8.0) -> np.ndarray`:
   - Creates `(T, V)` `float32` logits with `peak_logit` at `(t, tok)` and `0.0` elsewhere, then applies numerically stable `log_softmax` per frame (`x - logsumexp(x)`).
2. `make_weighted_log_probs(frame_logits: Sequence[dict[int, float]], vocab_size: int) -> np.ndarray`:
   - Allows multi-token competing logits per frame (essential for testing `prefix_beam_search` + `CharNgramLM` tie-breaking, `blank_bias`, and `temperature`).
3. `make_wav_bytes(wav: np.ndarray, sr: int = 16000) -> bytes`:
   - Writes 16-bit mono PCM WAV to `io.BytesIO` via stdlib `wave` for `POST /api/transcribe` multipart uploads without needing `asr.audio`.
4. `tiny_checkpoint_path(tmp_path_factory) -> Path` (session-scoped):
   - Generates 4 train + 2 val fast-kotoba utterances via `generate_dataset(..., engine="fast")`, trains 1 epoch of `ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1)` via `train_asr`, returns `best.pt`.
5. `tiny_engine(tiny_checkpoint_path) -> ASREngine` (session-scoped):
   - Returns `ASREngine.from_checkpoint(tiny_checkpoint_path)`.
6. `api_client(tiny_engine)` and `api_client_no_model()` (session/function-scoped):
   - `TestClient(create_app(engine=tiny_engine))` and `TestClient(create_app())`.
7. `run_cli(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess`:
   - Runs `[sys.executable, "-m", "asr", *args]` with `cwd=REPO_ROOT`, `capture_output=True`, `text=True`.

---

## 2. Feature #12: CTC Decoding (`asr/decoding.py`)

**Contract (§6)**:
- `CharNgramLM(order: int = 3, smoothing: float = 0.1)` → `.fit(texts)`, `.score_next(prefix, token) -> float`, `.to_dict()`, `.from_dict(d)`
- `greedy_decode(log_probs, tokenizer, *, temperature=1.0, blank_bias=0.0) -> {"text", "token_ids", "score"}`
- `prefix_beam_search(log_probs, tokenizer, cfg: DecodeConfig, lm: CharNgramLM | None = None) -> list[{"text", "score", "acoustic_score", "lm_score"}]`

### Tier 1 — Happy Path (`test_tier1_features.py`) — 7 tests
1. `test_f12_greedy_decode_exact_ctc_collapse`:
   - Use `Tokenizer(mode="kana")`, encode `"アイウ"` → `[t_a, t_i, t_u]`.
   - Build synthetic `log_probs` for frames `[0, t_a, t_a, 0, t_i, t_i, t_i, 0, t_u, 0]`.
   - Assert `res["text"] == "アイウ"`, `res["token_ids"] == [t_a, t_i, t_u]`, `isinstance(res["score"], float)`, `np.isfinite(res["score"])`.
2. `test_f12_greedy_decode_repeated_char_separated_by_blank`:
   - Build frames `[t_a, t_a, 0, t_a]` for token `t_a` (`"ア"`).
   - Assert `greedy_decode` collapses consecutive duplicates but preserves blank-separated repeat → `res["text"] == "アア"`, `res["token_ids"] == [t_a, t_a]`.
3. `test_f12_prefix_beam_search_matches_greedy_on_peaky_input`:
   - Same unambiguous peaky `log_probs` for `"サクラ"`, `DecodeConfig(method="beam", beam_width=4)`.
   - Assert returns non-empty `list[dict]`, `len(hyps) <= 4`, each dict has keys `{"text", "score", "acoustic_score", "lm_score"}`, `hyps[0]["text"] == "サクラ"`, scores are sorted descending (`hyps[i]["score"] >= hyps[i+1]["score"]`).
4. `test_f12_prefix_beam_search_merges_equivalent_ctc_paths`:
   - Construct 3-frame `log_probs` where `"ア"` has multiple moderate-probability CTC paths (`[t_a, 0, 0]`, `[0, t_a, 0]`, `[t_a, t_a, 0]`) whose summed probability exceeds a single peaky competing token `"イ"` (`[0, t_i, 0]`).
   - Assert `prefix_beam_search` ranks `"ア"` above `"イ"` (classic prefix-beam advantage over greedy).
5. `test_f12_char_ngram_lm_fit_and_score_next`:
   - Fit `CharNgramLM(order=3, smoothing=0.1)` on `["ニホンゴ"] * 20 + ["サクラ"] * 5`.
   - Assert `lm.score_next("ニホ", "ン") > lm.score_next("ニホ", "ア")` and both are finite floats `<= 0.0`.
6. `test_f12_char_ngram_lm_serialization_roundtrip`:
   - Fit `CharNgramLM`, call `d = lm.to_dict()`, verify `json.dumps(d)` succeeds, restore `lm2 = CharNgramLM.from_dict(d)`.
   - Assert `lm2.score_next("ニホ", "ン") == pytest.approx(lm.score_next("ニホ", "ン"))` and `lm2.score_next("ニ", "ホ") == pytest.approx(lm.score_next("ニ", "ホ"))`.
7. `test_f12_prefix_beam_search_with_lm_rescoring`:
   - Fit `CharNgramLM` heavily on `["アイ"] * 50`.
   - Build 3-frame `log_probs` where frame 0 peaks on `"ア"`, frame 1 is blank, frame 2 has nearly tied logits for `"イ"` and `"ウ"` (`"ウ"` slightly higher by `0.05`).
   - With `DecodeConfig(method="beam", beam_width=6, lm_weight=1.5)` and `lm=lm`, assert top hypothesis is `"アイ"` and `hyps[0]["lm_score"] != 0.0`.

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 7 tests
1. `test_f12_beam_width_one`:
   - `prefix_beam_search(log_probs, tok, DecodeConfig(method="beam", beam_width=1))` returns a 1-element list matching the greedy top text with finite scores.
2. `test_f12_extreme_temperatures`:
   - Run both `greedy_decode` and `prefix_beam_search` with `temperature=0.1` and `temperature=5.0` on valid `log_probs`.
   - Assert finite scores (no `NaN`/`Inf`), valid decoded text, no crash.
3. `test_f12_extreme_blank_bias`:
   - On moderate-peak `log_probs` (peak logit `3.0` on `"ア"`):
     - `blank_bias=+5.0` (and `+10.0`) suppresses emission → `text == ""`.
     - `blank_bias=-5.0` on blank-dominant frames encourages non-blank emission and returns finite score without `NaN`/`Inf`.
4. `test_f12_all_blank_log_probs`:
   - `log_probs = make_log_probs([0] * 10, tok.vocab_size, peak_logit=10.0)`.
   - Assert `greedy_decode` returns `text == ""`, `token_ids == []`, finite `score`; `prefix_beam_search` returns top hypothesis with `text == ""` and finite scores.
5. `test_f12_single_frame_log_probs`:
   - `T=1` frame peaking on `"ア"`: both `greedy_decode` and `prefix_beam_search` return `"ア"` cleanly.
6. `test_f12_lm_empty_corpus_and_unseen_prefix`:
   - `CharNgramLM(order=3, smoothing=0.1).fit([])` and `.fit([""])`: `score_next("", "ア")` and `score_next("XYZ", "ア")` return finite float (no `ZeroDivisionError`/`NaN`).
7. `test_f12_insertion_bonus_effect`:
   - Run `prefix_beam_search` with `insertion_bonus=0.0` vs `insertion_bonus=2.0` on identical `log_probs`: assert non-empty hypothesis score increases (or stays finite and valid) when `insertion_bonus > 0`.

---

## 3. Feature #13: Viterbi Forced Alignment (`asr/decoding.py`)

**Contract (§6)**:
- `viterbi_align(log_probs, token_ids, tokenizer, frame_stride_ms=40.0) -> list[{"token", "start_sec", "end_sec", "confidence"}]`

### Tier 1 — Happy Path (`test_tier1_features.py`) — 5 tests
1. `test_f13_viterbi_align_exact_segments`:
   - Encode `"アイウ"` → `[t_a, t_i, t_u]`.
   - Frames: `0..3` peak on `t_a`, `4..5` peak on blank, `6..9` peak on `t_i`, `10..11` peak on blank, `12..15` peak on `t_u` (`T=16`, `frame_stride_ms=40.0`).
   - Assert `len(align) == 3`, tokens are `["ア", "イ", "ウ"]`, each dict has keys `{"token", "start_sec", "end_sec", "confidence"}`.
   - Assert `align[0]["start_sec"] <= 0.08`, `align[1]["start_sec"] >= 0.20`, `align[2]["start_sec"] >= 0.44`.
2. `test_f13_viterbi_align_monotonic_timestamps_and_bounds`:
   - Total duration `dur = T * frame_stride_ms / 1000.0`.
   - Assert for every item: `0.0 <= item["start_sec"] <= item["end_sec"] <= dur + 1e-6`, and `align[i]["start_sec"] <= align[i+1]["start_sec"]`.
3. `test_f13_viterbi_align_frame_stride_scaling`:
   - Run `viterbi_align` on identical `log_probs` & `token_ids` with `frame_stride_ms=40.0` vs `frame_stride_ms=20.0`.
   - Assert every `start_sec` and `end_sec` at `20.0 ms` is `pytest.approx(0.5 * val_at_40ms, abs=1e-6)`.
4. `test_f13_viterbi_align_confidence_reflects_posterior_strength`:
   - Compare peaky `log_probs` (`peak_logit=8.0`) vs uniform `log_probs` (`peak_logit=0.0`).
   - Assert all confidences are finite floats in `[0.0, 1.0]` and mean confidence on peaky `log_probs` is strictly greater than on uniform `log_probs`.
5. `test_f13_viterbi_align_repeated_identical_tokens`:
   - `token_ids = [t_a, t_a]` with frames `[t_a, t_a, 0, 0, t_a, t_a]`.
   - Assert `len(align) == 2`, both tokens `"ア"`, and `align[0]["end_sec"] <= align[1]["start_sec"] + 1e-6` (separated across the blank).

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 5 tests
1. `test_f13_viterbi_align_empty_token_ids`:
   - `viterbi_align(log_probs, [], tok, frame_stride_ms=40.0)` returns `[]` cleanly without crashing.
2. `test_f13_viterbi_align_single_token_single_frame`:
   - `T=1`, `token_ids=[t_a]`: returns 1-element alignment with `token == "ア"`, `0.0 <= start_sec <= end_sec <= 0.04 + 1e-6`, finite confidence.
3. `test_f13_viterbi_align_uniform_log_probs`:
   - All entries `-math.log(V)`, `T=12`, 3 tokens: returns 3 monotonic segments with finite timestamps and confidences (no NaN/Inf).
4. `test_f13_viterbi_align_tokens_exceed_frames`:
   - `T=2`, `token_ids=[t_a, t_i, t_u, t_a, t_i]` (more tokens than frames): must NOT crash with `IndexError` or segfault — either returns a list (empty or best-effort) or raises `ValueError`.
5. `test_f13_viterbi_align_empty_log_probs`:
   - `log_probs = np.empty((0, V), dtype=np.float32)`, `token_ids=[t_a]`: either returns `[]` or raises `ValueError` cleanly (no unhandled `IndexError`).

---

## 4. Feature #14: ASR Evaluation Metrics (`asr/metrics.py`)

**Contract (§6)**:
- `compute_cer(refs, hyps) -> {"cer", "substitutions", "deletions", "insertions", "ref_len"}`
- `compute_mer(refs, hyps) -> dict` (must include `"mer"`)
- `compute_wer(refs, hyps) -> dict` (must include `"wer"`)
- `confusion_pairs(refs, hyps, top_k=10) -> list[tuple[str, str, int]]`
- `alignment_boundary_error(gt_moras, pred_align) -> dict`

### Tier 1 — Happy Path (`test_tier1_features.py`) — 7 tests
1. `test_f14_compute_cer_exact_match`:
   - `compute_cer(["アイウエオ"], ["アイウエオ"])` → `cer == 0.0`, `substitutions == 0`, `deletions == 0`, `insertions == 0`, `ref_len == 5`.
2. `test_f14_compute_cer_s_d_i_breakdown`:
   - Test three isolated cases:
     - Substitution: `["アイウ"]` vs `["アエウ"]` → `S=1, D=0, I=0, ref_len=3, cer == pytest.approx(1/3)`
     - Deletion: `["アイウエ"]` vs `["アイ"]` → `S=0, D=2, I=0, ref_len=4, cer == pytest.approx(0.5)`
     - Insertion: `["アイ"]` vs `["アイウエ"]` → `S=0, D=0, I=2, ref_len=2, cer == pytest.approx(1.0)`
3. `test_f14_compute_cer_corpus_aggregation`:
   - Multi-utterance `refs=["アイウ", "カキクケ"]`, `hyps=["アエウ", "カキ"]` → `S=1, D=2, I=0, ref_len=7, cer == pytest.approx(3/7)`.
4. `test_f14_compute_mer_mora_level`:
   - Exact match `compute_mer(["シャシン"], ["シャシン"])["mer"] == 0.0`.
   - Single mora substitution `compute_mer(["キャ"], ["カ"])["mer"] == pytest.approx(1.0)` (1 mora `"キャ"` vs 1 mora `"カ"`, whereas char-level CER differs).
5. `test_f14_compute_wer_word_level`:
   - Exact match `compute_wer(["hello world foo bar"], ["hello world foo bar"])["wer"] == 0.0`.
   - 1 of 4 words wrong `compute_wer(["hello world foo bar"], ["hello mars foo bar"])["wer"] == pytest.approx(0.25)`.
6. `test_f14_confusion_pairs_ranking_and_top_k`:
   - `refs=["カカカタ"], hyps=["ガガガダ"]` → `confusion_pairs(refs, hyps, top_k=10)` returns `[("カ", "ガ", 3), ("タ", "ダ", 1)]`; with `top_k=1` returns `[("カ", "ガ", 3)]`.
7. `test_f14_alignment_boundary_error_exact_vs_shifted`:
   - `gt = [{"t": "ア", "a": 0.0, "e": 0.2}, {"t": "イ", "a": 0.2, "e": 0.4}]`.
   - `pred_exact = [{"token": "ア", "start_sec": 0.0, "end_sec": 0.2, "confidence": 0.9}, {"token": "イ", "start_sec": 0.2, "end_sec": 0.4, "confidence": 0.9}]`.
   - `pred_shifted = [{"token": "ア", "start_sec": 0.1, "end_sec": 0.3, "confidence": 0.9}, {"token": "イ", "start_sec": 0.3, "end_sec": 0.5, "confidence": 0.9}]`.
   - Assert both return non-empty `dict` with finite numeric values; for any key containing `"iou"`, exact `>=` shifted; for any key containing `"error"`/`"offset"`/`"mae"`, exact `<=` shifted.

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 6 tests
1. `test_f14_metrics_empty_lists`:
   - `compute_cer([], [])`, `compute_mer([], [])`, `compute_wer([], [])`: no `ZeroDivisionError`, error rate `== 0.0`, `ref_len == 0` (for CER).
2. `test_f14_metrics_empty_ref_and_empty_hyp_strings`:
   - `compute_cer([""], [""])` → `cer == 0.0`.
   - `compute_cer(["アイウ"], [""])` → `deletions == 3`, `cer == pytest.approx(1.0)`.
   - `compute_cer([""], ["アイ"])` → no `ZeroDivisionError`, `insertions == 2`, finite `cer >= 0.0`.
3. `test_f14_metrics_mismatched_lengths_raises`:
   - `compute_cer(["ア"], ["ア", "イ"])` raises `ValueError` (same for `compute_mer` and `compute_wer`).
4. `test_f14_confusion_pairs_no_substitutions_and_top_k_zero`:
   - Identical strings → `[]`.
   - Pure deletions/insertions (`["アイウ"]`, `["ア"]`) → `[]`.
   - `top_k=0` → `[]`; empty lists `([], [])` → `[]`.
5. `test_f14_alignment_boundary_error_empty_inputs`:
   - `alignment_boundary_error([], [])`, `alignment_boundary_error(gt, [])`, `alignment_boundary_error([], pred)`: return `dict` with finite values (no `ZeroDivisionError`).
6. `test_f14_compute_cer_exceeds_one_on_heavy_insertions`:
   - `compute_cer(["ア"], ["アイウエオ"])` → `insertions == 4`, `ref_len == 1`, `cer == pytest.approx(4.0)` (CER is not artificially clamped to 1.0).

---

## 5. Feature #15: High-Level Inference Engine (`asr/inference.py`)

**Contract (§7)**:
- `ASREngine.from_checkpoint(path, lm=None) -> ASREngine`
- `engine.transcribe(wav, sr=16000, decode_cfg=None, *, include_visuals=False) -> dict`
  - Required keys: `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`
  - When `include_visuals=True`: also `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`
- `engine.redecode(utterance_id, decode_cfg) -> dict` (cached `log_probs`, `<10 ms`)

### Tier 1 — Happy Path (`test_tier1_features.py`) — 6 tests
1. `test_f15_engine_from_checkpoint_loads`:
   - `engine = ASREngine.from_checkpoint(tiny_checkpoint_path)` succeeds; also verify `ASREngine.from_checkpoint(tiny_checkpoint_path, lm=lm)` succeeds.
2. `test_f15_engine_transcribe_contract_keys`:
   - Synthesize 16 kHz utterance via `synthesize_fast_kotoba("アイウ")`, call `res = tiny_engine.transcribe(wav, sr=16000)`.
   - Assert keys `{"text", "hypotheses", "alignment", "rtf", "duration_sec", "utterance_id"} <= set(res.keys())`.
   - Assert `isinstance(res["text"], str)`, `isinstance(res["hypotheses"], list)`, `isinstance(res["alignment"], list)`, `res["rtf"] >= 0.0`, `res["duration_sec"] == pytest.approx(len(wav)/16000, rel=0.05)`, non-empty `res["utterance_id"]`.
3. `test_f15_engine_transcribe_include_visuals`:
   - Call `res = tiny_engine.transcribe(wav, sr=16000, include_visuals=True)`.
   - Assert keys `{"waveform", "log_mel", "ctc_posteriors", "vad_segments"} <= set(res.keys())` and none are `None`.
4. `test_f15_engine_transcribe_greedy_and_beam_configs`:
   - Call `transcribe` with `DecodeConfig(method="greedy")` and `DecodeConfig(method="beam", beam_width=4)`.
   - Assert both succeed and return valid `text` and `hypotheses`.
5. `test_f15_engine_redecode_uses_cache_and_applies_config`:
   - Call `res1 = tiny_engine.transcribe(wav, sr=16000)` to get `utt_id = res1["utterance_id"]`.
   - Time `res2 = tiny_engine.redecode(utt_id, DecodeConfig(method="beam", beam_width=4, blank_bias=0.0))` and `res3 = tiny_engine.redecode(utt_id, DecodeConfig(method="greedy", blank_bias=50.0))`.
   - Assert `res2` has `"text"` and `"hypotheses"`, `res3["text"] == ""` (proving new `DecodeConfig` is applied), and redecode elapsed time is fast (`< 0.2s` generous CI ceiling for `<10 ms` target).
6. `test_f15_engine_transcribe_non_16khz_resamples`:
   - Pass a 0.5-second `float32` signal at `sr=22050` (`len=11025`): assert `transcribe` succeeds and `duration_sec == pytest.approx(0.5, abs=0.05)`.

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 5 tests
1. `test_f15_from_checkpoint_missing_file_raises`:
   - `ASREngine.from_checkpoint(tmp_path / "does_not_exist.pt")` raises `FileNotFoundError` (or `OSError`).
2. `test_f15_redecode_unknown_utterance_id_raises`:
   - `tiny_engine.redecode("unknown-utt-id-99999", DecodeConfig())` raises `KeyError` (or `ValueError`).
3. `test_f15_transcribe_pure_silence`:
   - `wav = np.zeros(16000, dtype=np.float32)`: returns valid result dict with `duration_sec == pytest.approx(1.0, abs=0.05)` and finite `rtf` (no NaN/crash).
4. `test_f15_transcribe_empty_audio`:
   - `wav = np.array([], dtype=np.float32)`: raises `ValueError` cleanly OR returns empty `text == ""` with `duration_sec == 0.0` (never unhandled PyTorch/NumPy shape crash).
5. `test_f15_redecode_extreme_decode_params`:
   - Using a valid cached `utterance_id`, call `redecode` with `DecodeConfig(method="beam", beam_width=1, temperature=0.1, blank_bias=-5.0)` and `DecodeConfig(method="beam", beam_width=1, temperature=5.0, blank_bias=5.0)`: both succeed with finite scores and valid strings.

---

## 6. Feature #16: Full CLI (`asr/__main__.py`)

**Contract (§7)**:
- `.venv/bin/python -m asr <subcommand>`
  - `demo [--out-dir DIR] [--epochs N] [--num-train N] [--arch cnn_bigru|conformer_lite]`
  - `generate --out-dir DIR [--num-train N] [--num-val N] [--engine fast|tsukinami|mixed]`
  - `train --train-manifest PATH --val-manifest PATH [--out-dir DIR] [--arch ...] [--epochs N]`
  - `eval --checkpoint PATH --manifest PATH [--method greedy|beam] [--beam-width K]`
  - `transcribe --checkpoint PATH (--wav PATH | --tts TEXT [--preset NAME]) [--method greedy|beam] [--json]`
  - `serve --checkpoint PATH [--host 127.0.0.1] [--port 8000]`

### Tier 1 — Happy Path (`test_tier1_features.py`) — 7 tests
1. `test_f16_cli_help_lists_all_subcommands`:
   - `run_cli(["--help"])` exits `0`; stdout contains all 6 subcommands: `demo`, `generate`, `train`, `eval`, `transcribe`, `serve`.
2. `test_f16_cli_generate_fast`:
   - `run_cli(["generate", "--out-dir", str(tmp_path), "--num-train", "3", "--num-val", "2", "--engine", "fast"])` exits `0`; `train.jsonl` (3 lines) and `val.jsonl` (2 lines) exist with valid JSONL rows.
3. `test_f16_cli_train_creates_checkpoints`:
   - Using `tiny_dataset_dir` manifests, `run_cli(["train", "--train-manifest", ..., "--val-manifest", ..., "--out-dir", str(out), "--arch", "cnn_bigru", "--epochs", "1"])` exits `0` and writes `best.pt` and `latest.pt`.
4. `test_f16_cli_eval_runs_on_manifest`:
   - `run_cli(["eval", "--checkpoint", str(tiny_checkpoint_path), "--manifest", str(tiny_val_manifest), "--method", "greedy"])` exits `0` and stdout mentions `cer` (case-insensitive).
5. `test_f16_cli_transcribe_wav_json`:
   - Write a valid 16 kHz WAV file, run `run_cli(["transcribe", "--checkpoint", str(tiny_checkpoint_path), "--wav", str(wav_path), "--method", "greedy", "--json"])`.
   - Assert exit `0`, `json.loads(proc.stdout)` succeeds and contains `"text"`.
6. `test_f16_cli_transcribe_tts_json`:
   - Run `run_cli(["transcribe", "--checkpoint", str(tiny_checkpoint_path), "--tts", "アイウ", "--preset", "default", "--method", "beam", "--json"])`.
   - Assert exit `0`, `json.loads(proc.stdout)` succeeds and contains `"text"`.
7. `test_f16_cli_serve_help_flags`:
   - `run_cli(["serve", "--help"])` exits `0` and stdout documents `--checkpoint`, `--host`, and `--port`.

*(Note: Full `python -m asr demo` end-to-end execution is also covered in Tier 4; we can include a fast 1-epoch `demo --out-dir tmp --epochs 1 --num-train 4 --arch cnn_bigru` test in Tier 1 if runtime budget allows, or keep it as test #8 in Tier 1 — at 4 utterances / 1 epoch it takes ~2–4s on CPU.)*

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 6 tests
1. `test_f16_cli_unknown_subcommand`:
   - `run_cli(["totally_unknown_cmd"])` → `returncode != 0`, non-empty `stderr`, no `"Traceback"` in `stderr`.
2. `test_f16_cli_generate_missing_out_dir`:
   - `run_cli(["generate"])` → `returncode != 0`, non-empty `stderr`, no `"Traceback"`.
3. `test_f16_cli_transcribe_missing_checkpoint`:
   - `run_cli(["transcribe", "--checkpoint", str(tmp_path / "missing.pt"), "--tts", "アイ"])` → `returncode != 0`, non-empty `stderr`.
4. `test_f16_cli_transcribe_missing_wav`:
   - `run_cli(["transcribe", "--checkpoint", str(tiny_checkpoint_path), "--wav", str(tmp_path / "missing.wav")])` → `returncode != 0`, non-empty `stderr`.
5. `test_f16_cli_train_invalid_arch`:
   - `run_cli(["train", "--train-manifest", str(tiny_train_manifest), "--val-manifest", str(tiny_val_manifest), "--arch", "bogus_arch"])` → `returncode != 0`, non-empty `stderr`, no `"Traceback"`.
6. `test_f16_cli_transcribe_missing_input_source`:
   - `run_cli(["transcribe", "--checkpoint", str(tiny_checkpoint_path)])` (neither `--wav` nor `--tts`) → `returncode != 0`, non-empty `stderr`.

---

## 7. Feature #17: FastAPI Backend (`asr/server.py`)

**Contract (§8)**:
- `create_app(checkpoint_path=None, engine=None) -> FastAPI`
- `GET /` → `200`, `text/html`
- `GET /api/health` → `{"status": "ok", "model_loaded": bool}`
- `GET /api/info` → checkpoint metadata, vocab, model architecture, `tsukinami` presets, training history curves
- `POST /api/transcribe` → multipart WAV (or JSON base64 WAV) + decode & corruption params → `TranscribeResult` JSON (with visuals); `400`/`422` on invalid audio
- `POST /api/tts-roundtrip` → JSON `{text, preset, hz, fscale, yure, rate, synth_engine, corruption, decode_cfg}` → `audio_b64`, `ground_truth_moras`, `cer`, and `TranscribeResult`
- `POST /api/redecode` → JSON `{utterance_id, decode_cfg}` → re-decoded result; `404` on unknown `utterance_id`

### Tier 1 — Happy Path (`test_tier1_features.py`) — 6 tests
1. `test_f17_api_health_loaded`:
   - `resp = api_client.get("/api/health")` → `200`, `resp.json() == {"status": "ok", "model_loaded": True}`.
2. `test_f17_api_info_metadata`:
   - `resp = api_client.get("/api/info")` → `200`, JSON dict is non-empty and contains vocab, architecture/model metadata, presets, and history information.
3. `test_f17_api_transcribe_multipart_wav`:
   - Upload valid 16 kHz WAV via `files={"file": ("test.wav", wav_bytes, "audio/wav")}` to `POST /api/transcribe`.
   - Assert `200`, JSON has `"text"`, `"hypotheses"`, `"alignment"`, `"utterance_id"`, `"duration_sec"`, `"rtf"`, plus visual fields (`"waveform"`, `"log_mel"`, `"ctc_posteriors"`, `"vad_segments"`).
4. `test_f17_api_tts_roundtrip_fast`:
   - `POST /api/tts-roundtrip` with `{"text": "アイウ", "preset": "default", "synth_engine": "fast"}`.
   - Assert `200`, JSON has `"audio_b64"` (valid base64 decoding to `b"RIFF"` WAV header), `"ground_truth_moras"` (non-empty list), `"cer"`, and transcription `"text"` (top-level or nested in `result`).
5. `test_f17_api_redecode_cached_utterance`:
   - First `POST /api/transcribe` to obtain `utterance_id`.
   - Then `POST /api/redecode` with `{"utterance_id": utt_id, "decode_cfg": {"method": "beam", "beam_width": 4, "temperature": 1.0, "blank_bias": 0.0}}`.
   - Assert `200`, JSON has `"text"` and `"hypotheses"`.
6. `test_f17_create_app_from_checkpoint_path`:
   - `app = create_app(checkpoint_path=tiny_checkpoint_path)` with `TestClient(app).get("/api/health")` → `200`, `{"status": "ok", "model_loaded": True}`.

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 6 tests
1. `test_f17_api_redecode_unknown_utterance_404`:
   - `POST /api/redecode` with `{"utterance_id": "nonexistent-id-000", "decode_cfg": {"method": "greedy"}}` → status `404`.
2. `test_f17_api_transcribe_corrupt_wav_400_or_422`:
   - `POST /api/transcribe` with `files={"file": ("bad.wav", b"NOT_A_WAV_FILE_12345", "audio/wav")}` → status in `{400, 422}` (never `500`).
3. `test_f17_api_transcribe_empty_file_400_or_422`:
   - `POST /api/transcribe` with `files={"file": ("empty.wav", b"", "audio/wav")}` → status in `{400, 422}` (never `500`).
4. `test_f17_api_tts_roundtrip_missing_text_422`:
   - `POST /api/tts-roundtrip` with `{}` (missing required `text`) → status `422` (or `400`).
5. `test_f17_api_redecode_malformed_payload_422`:
   - `POST /api/redecode` with `{}` (missing `utterance_id`) → status `422`.
6. `test_f17_api_health_without_model_loaded`:
   - `api_client_no_model.get("/api/health")` → `200`, `{"status": "ok", "model_loaded": False}`; `POST /api/transcribe` on unloaded app returns clean `400`/`503` (not unhandled `500` traceback).

---

## 8. Feature #18: Zero-CDN Interactive Web Playground (`asr/web/index.html`)

**Contract (§8 & Feature Inventory #18)**:
- Served at `GET /` (`200 OK`, `text/html`).
- Zero external CDN dependencies (`<script src="http...">`, `<link href="http...">`, etc.).
- Interactive Canvas 2D + Web Audio UI wiring `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`, mic recording, WAV upload, corruption lab, and live beam-search sliders.

### Tier 1 — Happy Path (`test_tier1_features.py`) — 5 tests
1. `test_f18_web_root_serves_html`:
   - `resp = api_client.get("/")` → `200`, `"text/html"` in `resp.headers["content-type"].lower()`, body contains `<html` and `</html>` (case-insensitive) and non-trivial length (`> 1000` bytes).
2. `test_f18_web_zero_cdn_assets`:
   - Parse `resp.text` with stdlib `HTMLParser` + regex:
     - Zero `<script>` tags with `src` starting with `http://`, `https://`, or `//`.
     - Zero `<link>` tags with `href` starting with `http://`, `https://`, or `//`.
     - Zero CSS `@import` referencing `http://`, `https://`, or `//`.
3. `test_f18_web_has_canvas_visualizers`:
   - HTML contains multiple `<canvas` elements (`>= 2`) and JS calls `getContext("2d")` or `getContext('2d')`.
4. `test_f18_web_has_interactive_audio_and_slider_controls`:
   - HTML contains file upload (`type="file"`), range sliders (`type="range"`), and Web Audio / mic API references (`AudioContext` or `MediaRecorder` or `getUserMedia`).
5. `test_f18_web_wires_all_backend_api_endpoints`:
   - HTML/JS references all four interactive backend routes: `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, and `/api/redecode`.

### Tier 2 — Boundary / Edge / Negative (`test_tier2_boundaries.py`) — 5 tests
1. `test_f18_web_html_well_formed_tags`:
   - Stdlib `HTMLParser` parses `GET /` body cleanly; count of `<script` matches `</script>` and `<style` matches `</style>`.
2. `test_f18_web_no_common_cdn_hosts`:
   - Assert none of `cdn.jsdelivr.net`, `unpkg.com`, `cdnjs.cloudflare.com`, `fonts.googleapis.com`, `fonts.gstatic.com` appear anywhere in `GET /` HTML.
3. `test_f18_web_utf8_charset_declared`:
   - `GET /` declares UTF-8 charset (`charset="utf-8"` or `charset=utf-8`, case-insensitive) and decodes cleanly as UTF-8.
4. `test_f18_web_unknown_route_returns_404`:
   - `api_client.get("/nonexistent-route-xyz")` returns `404`.
5. `test_f18_web_disallowed_method_on_root_returns_405`:
   - `api_client.delete("/")` returns `405`.

---

## 9. Coverage Summary Table (Features #12–#18)

| Feature # | Feature Area | Tier 1 Count | Tier 2 Count | Depends on Trained Model? |
|---|---|---:|---:|---|
| 12 | CTC Decoding (`CharNgramLM`, `greedy_decode`, `prefix_beam_search`) | 7 | 7 | No (analytical NumPy `log_probs`) |
| 13 | Viterbi Forced Alignment (`viterbi_align`) | 5 | 5 | No (analytical NumPy `log_probs`) |
| 14 | ASR Evaluation Metrics (`cer`, `mer`, `wer`, `confusion_pairs`, `alignment_boundary_error`) | 7 | 6 | No (pure Python/NumPy) |
| 15 | Inference Engine (`ASREngine`) | 6 | 5 | Yes (session `tiny_checkpoint`) |
| 16 | Full CLI (`python -m asr ...`) | 7 | 6 | Yes (session `tiny_checkpoint` / `generate`) |
| 17 | FastAPI Backend (`asr/server.py`) | 6 | 6 | Yes (session `tiny_engine` + no-model app) |
| 18 | Zero-CDN Web Playground (`asr/web/index.html`) | 5 | 5 | No (served via `create_app()`) |
| **Total** | **Features #12–#18** | **43** | **40** | **83 tests total (>= 5/tier/feature)** |
