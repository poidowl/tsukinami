# Explorer 3 Handoff — Tier 3 (Combinations), Tier 4 (Real-World Scenarios) & CPU Budget

**Track**: E2E Testing Track (`sub_orch_e2e`), Iteration 1
**Author**: Explorer 3
**Target Deliverables Designed**:
- `tests_e2e/test_tier3_combinations.py` (Tier 3 — Cross-Feature Combinations)
- `tests_e2e/test_tier4_scenarios.py` (Tier 4 — Real-World Application Scenarios)
- Shared fixture & CPU/RAM runtime budget recommendations for `tests_e2e/conftest.py` and `TEST_INFRA.md`

---

## 1. Design Principles & Non-Negotiable Constraints

1. **Strict Contract Alignment**: Every symbol, parameter name, default, return key, CLI flag, and HTTP route follows `PROJECT.md § Interface Contracts` verbatim. Zero reliance on private/internal helpers (`_*` functions or undocumented fields).
2. **Collection-Safe Imports (Parallel Execution)**: Because `asr/` is being implemented in parallel, **all `import asr...` statements MUST live inside test functions or fixtures**, never at module top-level. Only stdlib (`json`, `base64`, `io`, `time`, `wave`, `subprocess`, `pathlib`) and `pytest`/`numpy` (or inside fixtures) are imported at top level. This guarantees `pytest --collect-only tests_e2e/` succeeds cleanly even when `asr/` is partial, while tests fail genuinely if `asr/` is missing or broken.
3. **Zero `pytest.skip` / Zero Dummy Passes**: No conditional skips for missing modules and no tautological assertions (`assert True`).
4. **Realistic Assertions for Tiny CPU Models**: Tests that train 1–2 epochs on 6–16 synthetic utterances assert **structural, mathematical, and behavioral invariants** (finite CTC loss, valid log-probabilities summing to `1.0`, monotonic alignment timestamps, valid non-negative CER/MER/WER, checkpoint round-trip equivalence, deterministic seeding, `<10 ms` cached greedy redecode), rather than brittle accuracy thresholds like `cer < 0.05` that depend on long training runs.
5. **Untouched Existing TTS**: Existing files (`kotoba.py`, `accent.py`, `yomu.py`, `carve.py`, etc.) are strictly read-only and verified via Scenario 9.

---

## 2. Empirical Micro-Benchmarks (Measured on This Machine)

Measured directly on this environment (2 vCPUs, 7.8 GiB RAM, 0 swap):
- `kotoba.tracks_from_kana("おはよう")`: **0.68 ms** (`fp_ms=5.0`, returns dict with `F1`, `F2`, `F3`, `G1`, `G2`, `G3`, `dl`, `loud`, `f0`, `voiced`, `bands`, `moras`).
- `carve.make(rc)` (pure-Python 44.1 kHz synthesis):
  - 1 mora (`"あ"`): **~3.0 s** (`len(samples) == 43218`, ~0.98 s audio, returns 2-tuple `(samples_list, info_list)`).
  - 2 moras (`"あか"`): **~3.21 s**.
- **Critical Design Implication**: Any test invoking `synthesize_tsukinami` (Tier 2 authentic TTS) MUST use short 2–3 mora phrases (e.g., `"あか"`, `"おはよ"`) AND pass a shared session-scoped `cache_dir` (except the explicit cache-miss/hit test) so uncached calls stay ~3.2 s each and repeat calls hit disk cache in `< 5 ms`.

---

## 3. Tier 3 Design — Cross-Feature Combinations (`tests_e2e/test_tier3_combinations.py`)

**Goal**: Verify all major pairwise and multi-module interactions across all 18 product features in `PROJECT.md § Feature Inventory`.

### Test Matrix (11 Concrete Test Functions)

| # | Test Function | Features Combined | Key Contract Interactions Verified |
|---|---|---|---|
| 1 | `test_t3_corruption_noise_features_and_vad` | F2, F3, F4, F5, F7 | `synthesize_fast_kotoba` -> `apply_corruption` (`white` & `pink` at `snr_db=10.0, seed=7`) -> `extract_log_mel` & `extract_mfcc(include_deltas=True)` & `detect_vad`. Asserts finite `float32` shapes `(T, 64)` and `(T, 39)`, `T` matches clean, corrupted Log-Mel differs measurably from clean (`mean(abs(diff)) > 1e-3`), and `detect_vad` returns valid `(start, end)` tuples with `0.0 <= start < end <= duration + 0.05`. |
| 2 | `test_t3_corruption_speed_bandlimit_gain_features` | F3, F5, F7 | `apply_corruption` with `speed=1.25` (`T_fast < T_clean`), `speed=0.8` (`T_slow > T_clean`), `band_limit=(300.0, 3400.0)` (high-freq Mel bins `mel[:, -10:]` attenuated vs clean when `AudioConfig(cmvn=False)`), and `gain_db=-6.0` (RMS drops by ~0.5x while `AudioConfig(cmvn=True)` Log-Mel stays mean≈0, std≈1). |
| 3 | `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug` | F2, F3, F5, F6, F7, F9 | Synthesize 4 utterances via `synthesize_fast_kotoba`, persist via `save_wav`, write JSONL manifest (`audio_path`, `text`, `duration`, `speaker`, `source`, `moras`). Load `ASRManifestDataset(..., Tokenizer("kana"), augment=False)` and `augment=True`; batch via `collate_asr_batch`. Assert `feats` `(4, T_max, 64)`, `feat_lengths` `(4,)` with `max == T_max`, `targets` `(4, L_max)` containing no `blank_id == 0` in valid slices, `target_lengths` `(4,)`, `len(texts) == 4`. Also apply `spec_augment(mel, seed=42)` directly and confirm masked frames/bins alter the feature matrix without NaN/Inf. |
| 4 | `test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate` | F6, F7, F9 | Repeat manifest -> `ASRManifestDataset` -> `collate_asr_batch` using `Tokenizer("phoneme")` after a `Tokenizer.from_dict(tok.to_dict())` serialization round-trip. Verify `tok.blank_id == 0`, `tok.vocab_size > 1`, `target_lengths > 0`, and `decode(ids)` round-trips cleanly. |
| 5 | `test_t3_tsukinami_presets_cache_wav_io_logmel` | F2, F3, F8 | Call `synthesize_tsukinami("あか", preset="default", sr=16000, cache_dir=tmp_cache)` and `preset="ossan"`. Verify both return 1D `float32` mono arrays in `[-1.0, 1.0]` and non-empty `moras` with keys `{"t", "a", "e"}`. Verify second call for `("あか", "default", tmp_cache)` hits disk cache (cache directory non-empty, returned array `np.allclose` to first call). Round-trip through `save_wav` -> `load_wav(target_sr=16000)` (correlation `> 0.999`). Extract `extract_log_mel` on `default` vs `ossan` and assert finite `(T, 64)` matrices with measurable acoustic difference (`mean(abs(diff)) > 1e-2` over overlapping frames). |
| 6 | `test_t3_cnn_bigru_train_checkpoint_and_resume` | F1, F10, F11 | Use tiny 6-train / 2-val fast manifest. Run `train_asr(..., model_cfg=ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1), train_cfg=TrainConfig(epochs=1, batch_size=4, seed=42, checkpoint_dir=ckpt_dir))`. Verify `best.pt` and `latest.pt` exist; `load_checkpoint` has keys `{"model_state_dict", "model_config", "audio_cfg", "tokenizer", "history", "epoch", "best_val_cer"}`. Resume with `resume_from=latest_pt` and `epochs=2`; verify resumed `epoch >= 2`, `len(history) >= 2`, and `build_model` loads `model_state_dict` and runs forward pass with `subsampling_factor == 4` and `output_frame_stride_ms(audio_cfg) == 40.0`. |
| 7 | `test_t3_conformer_lite_train_checkpoint_and_forward` | F1, F10, F11 | Same tiny manifest with `ModelConfig(arch="conformer_lite", hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)` and `epochs=1`. Verify `best.pt` loads via `load_checkpoint`, `build_model` produces `(log_probs, out_lengths)` where `log_probs.exp().sum(dim=-1)` is `allclose(1.0, atol=1e-4)` and `out_lengths <= feat_lengths`. |
| 8 | `test_t3_model_logprobs_greedy_beam_lm_and_viterbi` | F10, F12, F13 | Run `session_tiny_checkpoint` model on a val utterance to get `log_probs` `(T', V)`. Fit `CharNgramLM(order=3, smoothing=0.1)` on a small kana corpus and verify `to_dict`/`from_dict` preserves `score_next`. Compare `greedy_decode(lp, tok)` (`{"text", "token_ids", "score"}`), `prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4, lm_weight=0.0))`, and `prefix_beam_search(..., DecodeConfig(method="beam", beam_width=4, lm_weight=0.5, insertion_bonus=0.2), lm=lm)`. Assert beam hypotheses are sorted descending by `score`, contain `{"text", "score", "acoustic_score", "lm_score"}`, and `viterbi_align(lp, tok.encode(ref_text), tok, frame_stride_ms=40.0)` returns monotonic `[{"token", "start_sec", "end_sec", "confidence"}]` with `len == len(token_ids)`. |
| 9 | `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics` | F7, F13, F14 | Synthesize `"ワタシ、ニホンゴ"` via `synthesize_fast_kotoba` -> `(wav, gt_moras)`. Run model forward -> `log_probs`, run `viterbi_align` on target token IDs -> `pred_align`. Call `alignment_boundary_error(gt_moras, pred_align)` and assert returned dict has finite numeric values. Also call `compute_cer`, `compute_mer`, `compute_wer`, and `confusion_pairs` on realistic `(refs, hyps)` pairs (including an intentional substitution/deletion/insertion pair) and assert `cer` dict has `{"cer", "substitutions", "deletions", "insertions", "ref_len"}` with `cer == (S + D + I) / ref_len`, and `confusion_pairs` returns `(ref, hyp, count)` tuples. |
| 10 | `test_t3_engine_transcribe_visuals_corruption_and_redecode` | F5, F12, F15 | Using `session_asr_engine`, transcribe both clean and corrupted (`snr_db=10.0, noise_type="white"`) speech with `include_visuals=True`. Verify all contract keys (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`). Call `engine.redecode(utterance_id, DecodeConfig(method="greedy"))` and `engine.redecode(utterance_id, DecodeConfig(method="beam", beam_width=4, temperature=1.4, blank_bias=-0.5))`; assert valid outputs and no crash/NaN. |
| 11 | `test_t3_cli_pipeline_generate_train_eval_transcribe` | F1, F7, F9, F11, F15, F16 | End-to-end subprocess pipeline via `.venv/bin/python -m asr ...` in `tmp_path`: (1) `generate --out-dir data --num-train 6 --num-val 2 --engine fast`, (2) `train --train-manifest data/train.jsonl --val-manifest data/val.jsonl --out-dir ckpt --arch cnn_bigru --epochs 1`, (3) `eval --checkpoint ckpt/best.pt --manifest data/val.jsonl --method greedy`, (4) `transcribe --checkpoint ckpt/best.pt --wav <val_wav> --method greedy --json` (parse JSON, check `text`, `rtf`, `duration_sec`), (5) `transcribe --checkpoint ckpt/best.pt --tts "あか" --preset default --method beam --json` (parse JSON, check `text`). |
| 12 | `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | F5, F8, F12, F15, F17, F18 | FastAPI `TestClient(create_app(engine=session_asr_engine))`: (1) `GET /api/info` returns 200 with metadata/vocab/presets; (2) `POST /api/tts-roundtrip` with `{text: "あか", preset: "default", synth_engine: "fast", corruption: {"snr_db": 15.0, "noise_type": "white"}, decode_cfg: {"method": "beam", "beam_width": 4}}` returns 200 with valid base64 WAV (`audio_b64`), `ground_truth_moras`, finite `cer >= 0`, `utterance_id`; (3) `POST /api/redecode` with returned `utterance_id` and `{method: "greedy", temperature: 1.2, blank_bias: 0.1}` returns 200; (4) `GET /` returns 200 `text/html` with zero external CDN `<script src="http` / `<link href="http` references. |

*Coverage check*: All 18 product features (F1–F18) are exercised in Tier 3 cross-feature interactions.

---

## 4. Tier 4 Design — Real-World Application Scenarios (`tests_e2e/test_tier4_scenarios.py`)

**Goal**: Exercise 9 realistic, multi-feature end-user workflows from start to finish.

### Scenario Specifications

1. **`test_t4_scenario1_one_command_cpu_quickstart_demo`**
   - **User Story**: New user runs the one-command quickstart `python -m asr demo` on CPU.
   - **Execution**: Subprocess `.venv/bin/python -m asr demo --out-dir <tmp>/demo --epochs 2 --num-train 16 --arch cnn_bigru` (`timeout=120`).
   - **Assertions**:
     - Exit code `0`.
     - Generated data files exist under `<tmp>/demo` (`train.jsonl`, `val.jsonl`, and WAV files referenced by manifests).
     - Checkpoint file (`best.pt` and/or `latest.pt`) exists under `<tmp>/demo`.
     - `ASREngine.from_checkpoint(best_pt)` succeeds and transcribes a fresh synthetic utterance.
     - Combined stdout/stderr reports evaluation metrics and a live transcription result.

2. **`test_t4_scenario2_multi_preset_tsukinami_roundtrip_and_alignment`**
   - **User Story**: User compares authentic `tsukinami` voice presets (`default`, `ossan`, `robot`, `whisper`, `chibi`) through ASR and inspects mora alignment accuracy.
   - **Execution**: Using short phrase `"あか"` and `session_tsukinami_cache_dir` (keeps total uncached synthesis to `5 × ~3.2s ≈ 16s`, and `0s` on repeat), synthesize all 5 presets via `synthesize_tsukinami(text, preset=p, sr=16000, cache_dir=cache_dir)`. For each preset:
     - Run `session_asr_engine.transcribe(wav, sr=16000, decode_cfg=DecodeConfig(method="beam", beam_width=4), include_visuals=True)`.
     - Compute `compute_cer([ref], [res["text"]])`, `compute_mer([ref], [res["text"]])`, and `alignment_boundary_error(gt_moras, pred_align)` (using `viterbi_align` on `tok.encode(ref)` if `res["alignment"]` is empty on a tiny model, or directly on `res["alignment"]` when non-empty).
   - **Assertions**:
     - All 5 presets produce valid non-silent 16 kHz `float32` waveforms with `duration_sec > 0.2`.
     - Pairwise waveforms across distinct presets are not identical (each preset alters acoustics).
     - All 5 presets yield finite `cer >= 0`, `mer >= 0`, `rtf > 0`, and valid `alignment_boundary_error` dicts.

3. **`test_t4_scenario3_noisy_and_telephone_degradation_experiment`**
   - **User Story**: User evaluates speech degradation under clean, white noise (5 dB SNR), pink noise (10 dB SNR), and telephone band-limit (300–3400 Hz) conditions.
   - **Execution**: Synthesize `"ワタシ、ニホンゴ"` via `synthesize_fast_kotoba(..., seed=42)`. Build 4 waveforms via `apply_corruption`:
     - `clean`: unmodified
     - `white_5db`: `snr_db=5.0, noise_type="white", seed=42`
     - `pink_10db`: `snr_db=10.0, noise_type="pink", seed=42`
     - `telephone`: `band_limit=(300.0, 3400.0)`
     For each condition, compute `extract_log_mel(..., AudioConfig(cmvn=False))`, `extract_log_mel(..., AudioConfig(cmvn=True))`, `detect_vad(wav, sr=16000)`, and `session_asr_engine.transcribe(wav, sr=16000, include_visuals=True)` + `compute_cer`.
   - **Assertions**:
     - All 4 conditions produce finite Log-Mel, valid VAD segment lists, finite `ctc_posteriors`, and finite CER.
     - Each degraded condition has strictly positive spectral L1 distance from clean Log-Mel (`cmvn=False`).
     - Telephone band-limit `(300.0, 3400.0)` measurably reduces mean energy in the highest Mel bins (bins above ~4 kHz, e.g., top 12 of 64 bins) relative to clean (`cmvn=False`).

4. **`test_t4_scenario4_interactive_web_playground_full_session`**
   - **User Story**: User opens the zero-CDN web playground, checks status/info, runs a TTS→ASR round-trip, sweeps decoding sliders in real time, and uploads a WAV file.
   - **Execution**: `TestClient(create_app(engine=session_asr_engine))`:
     1. `GET /` -> 200, `text/html`, contains `<canvas`, contains zero external CDN `<script src="http` or `<link href="http` tags.
     2. `GET /api/health` -> 200, `{"status": "ok", "model_loaded": True}`.
     3. `GET /api/info` -> 200, returns model metadata, vocab, presets, history.
     4. `POST /api/tts-roundtrip` (`text="おはよう"`, `preset="default"`, `synth_engine="fast"`, `decode_cfg={"method": "beam", "beam_width": 4}`) -> 200, extract `utterance_id` and `audio_b64`.
     5. `POST /api/redecode` slider sweep (4 requests): greedy; beam (`beam_width=4, temperature=0.8`); beam (`temperature=1.5, blank_bias=-0.5`); beam (`blank_bias=0.8`) -> all 200 with valid `text` & `hypotheses`.
     6. `POST /api/transcribe` multipart file upload using WAV bytes decoded from `audio_b64` -> 200 with `text`, `utterance_id`, `rtf`, `duration_sec`, and visuals.

5. **`test_t4_scenario5_custom_wav_folder_tier3_corpus_workflow`**
   - **User Story**: User brings their own folder of WAV files + transcripts, builds manifests, trains a custom ASR model, and evaluates CER/WER.
   - **Execution**:
     - Write 6 train WAVs and 2 val WAVs to `tmp_path/train_wavs` and `tmp_path/val_wavs` (using `synthesize_fast_kotoba` + `save_wav`; include at least one 22050 Hz WAV to verify resampling inside the pipeline).
     - Build manifests via `build_manifest_from_wav_dir(train_dir, train_map, train_manifest)` and `build_manifest_from_wav_dir(val_dir, val_map, val_manifest)`.
     - Verify `ASRManifestDataset` + `collate_asr_batch` yields valid tensors.
     - Train tiny `cnn_bigru` (`hidden_size=32, num_layers=1, epochs=2, batch_size=4`) via `train_asr`.
     - Load `best.pt` via `ASREngine.from_checkpoint`, transcribe all val WAVs via `load_wav` + `engine.transcribe`, and compute `compute_cer` and `compute_wer`.
   - **Assertions**: Manifests written with expected line counts, training produces `best.pt`, `ASREngine` transcribes all val files, `compute_cer` and `compute_wer` return valid finite dicts with `ref_len > 0`.

6. **`test_t4_scenario6_architecture_comparison_and_checkpoint_resume`**
   - **User Story**: User compares `cnn_bigru` vs `conformer_lite` on the same dataset, resumes training from a checkpoint for an extra epoch, and evaluates both via `ASREngine`.
   - **Execution**: On `session_tiny_dataset`:
     - For `arch` in `("cnn_bigru", "conformer_lite")`:
       * Train 1 epoch (`hidden_size=32, num_layers=1`, `num_heads=4, conv_kernel_size=7` for conformer) -> save `latest.pt`.
       * Resume from `latest.pt` for 1 extra epoch (`epochs=2`).
       * Load `best.pt` into `ASREngine.from_checkpoint` and transcribe the same val utterance.
   - **Assertions**: Both architectures complete training & resume cleanly, `epoch >= 2` in resumed checkpoint, both `ASREngine` instances return valid `TranscribeResult` dicts with finite `rtf > 0`.

7. **`test_t4_scenario7_decoding_strategy_and_ngram_lm_study`**
   - **User Story**: User fits a `CharNgramLM` on a Japanese corpus and compares Greedy vs Beam vs Beam+LM decoding with CER/MER/WER and confusion analysis.
   - **Execution**:
     - Fit `CharNgramLM(order=3, smoothing=0.1)` on a 16-utterance Japanese kana corpus; verify `CharNgramLM.from_dict(lm.to_dict())` matches `score_next`.
     - Load `ASREngine.from_checkpoint(session_tiny_checkpoint, lm=lm)`.
     - Transcribe 4 validation utterances under 3 configs:
       1. `DecodeConfig(method="greedy")`
       2. `DecodeConfig(method="beam", beam_width=6, lm_weight=0.0)`
       3. `DecodeConfig(method="beam", beam_width=6, lm_weight=0.5, insertion_bonus=0.2)`
     - Compute `compute_cer`, `compute_mer`, `compute_wer`, and `confusion_pairs(refs, hyps, top_k=5)` for each strategy.
   - **Assertions**: All 3 strategies produce valid metric dicts (`0.0 <= cer`, `ref_len > 0`, integer `substitutions`/`deletions`/`insertions`) and `confusion_pairs` returns a list of `(str, str, int)` tuples sorted descending by count.

8. **`test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep`**
   - **User Story**: User inspects live visual outputs (`waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`) and interactively sweeps decoding parameters in `<10 ms` using cached `log_probs`.
   - **Execution**:
     - `res = session_asr_engine.transcribe(wav, sr=16000, include_visuals=True)` on a ~1s utterance (`T' ≈ 25`).
     - Validate visual payloads: `waveform` non-empty, `log_mel` 2D `(T, n_mels)`, `ctc_posteriors` 2D `(T', V)` with probabilities in `[0, 1]` and row sums `≈ 1.0`, `vad_segments` list of `(start, end)`.
     - Warm up 1 call, then sweep `session_asr_engine.redecode(res["utterance_id"], cfg)` across:
       * `method="greedy"` × (`temperature` in `[0.5, 1.0, 2.0]`, `blank_bias` in `[-1.0, 0.0, 1.0]`)
       * `method="beam"` × (`beam_width` in `[1, 4, 8]`, `temperature` in `[0.7, 1.3]`, `blank_bias` in `[-0.5, 0.5]`)
   - **Assertions**:
     - Median latency of cached `method="greedy"` `redecode` is **`< 10.0 ms`** (directly validating the `<10 ms` cached redecode contract).
     - Median latency of cached `method="beam"` (`beam_width=4`) `redecode` is `< 50.0 ms` (generous margin for 2-vCPU jitter).
     - All sweep results contain valid `text` and `hypotheses`.

9. **`test_t4_scenario9_existing_tsukinami_tts_non_regression`**
   - **User Story**: Confirm that adding `asr/` caused zero regressions to the original pure-Python `tsukinami` TTS modules.
   - **Execution**:
     - Import `kotoba`, `accent`, `yomu`, `carve` from repo root.
     - `kotoba`: verify `to_kata("わたし、にほんご") == "ワタシ、ニホンゴ"`, `split_moras("きょうも")` == `["キョ", "ウ", "モ"]`, and `tracks_from_kana("おはよう")` returns `fp_ms == 5.0`, `n > 0`, and non-empty `F1`/`F2`/`F3`/`voiced`/`moras`.
     - `accent`: verify `clean, phr = accent.annotate("おはよう、きょ'うも")` and `f0 = accent.f0_rule(r["moras"], r["n"], r["voiced"], phrases=phr, **accent.NORMAL)` returns `len(f0) == r["n"]` with positive voiced Hz values.
     - `yomu`: verify `{"default", "ossan", "robot", "horror", "whisper", "chibi"}.issubset(yomu.PRESETS.keys())`, and `rc = yomu.build_carve_rc("あ", dict(yomu.PRESETS["default"], uta_trance=False, uta_choir=False))` returns a dict.
     - `carve`: verify `samples, info = carve.make(rc)` returns a non-empty list of finite floats with `carve.SR == 44100` and `max(abs(v) for v in samples) > 0.01`, and `carve.write(str(tmp_path / "nr.wav"), samples)` writes a valid 44.1 kHz WAV file readable by stdlib `wave`.

---

## 5. CPU Runtime & Memory Budget (2 vCPUs, 7.8 GiB RAM, 0 Swap)

### Recommended Tiny Training Hyperparameters for E2E Tests
| Context | `num_train` | `num_val` | `arch` | `hidden_size` | `num_layers` | `epochs` | `batch_size` | Est. Wall Time |
|---|---|---|---|---|---|---|---|---|
| `session_tiny_checkpoint` (shared fixture) | 12 | 4 | `cnn_bigru` | 32 | 1 | 2 | 4 | ~1.5–2.5 s |
| Tier 3 `cnn_bigru` train + resume | 6 | 2 | `cnn_bigru` | 32 | 1 | 1 + 1 | 4 | ~1.5 s |
| Tier 3 `conformer_lite` train | 6 | 2 | `conformer_lite` | 32 | 1 (`heads=4, k=7`) | 1 | 4 | ~1.5 s |
| Tier 3 CLI `generate -> train -> eval -> transcribe` | 6 | 2 | `cnn_bigru` | default (CLI) | default (CLI) | 1 | default | ~8–15 s |
| Tier 4 Scenario 1 (`python -m asr demo`) | 16 | default | `cnn_bigru` | default (CLI) | default (CLI) | 2 | default | ~12–25 s |
| Tier 4 Scenario 5 (custom WAV folder) | 6 | 2 | `cnn_bigru` | 32 | 1 | 2 | 4 | ~1.5 s |
| Tier 4 Scenario 6 (`cnn_bigru` vs `conformer_lite` + resume) | 12 (shared) | 4 (shared) | both | 32 | 1 | 1 + 1 each | 4 | ~4 s |

### Full Suite Wall-Clock & Memory Estimate
- **Session fixtures setup** (`session_tiny_dataset`, `session_tiny_checkpoint`, `session_asr_engine`, `session_tsukinami_cache_dir`): **~3 s**
- **Tier 1** (`test_tier1_features.py`): **~15–25 s**
- **Tier 2** (`test_tier2_boundaries.py`): **~10–20 s**
- **Tier 3** (`test_tier3_combinations.py`): **~20–35 s**
- **Tier 4** (`test_tier4_scenarios.py`): **~45–70 s** (dominated by Scenario 1 `asr demo` ~15–25 s and Scenario 2 five-preset `synthesize_tsukinami("あか")` ~16 s)
- **Total Suite Runtime**: **~95–155 seconds (~1.5–2.5 minutes)** — safely within a few-minute CPU budget.
- **Peak Memory**: **~500–750 MiB** (PyTorch CPU runtime + NumPy + FastAPI + tiny `~30K` param models; `< 10%` of 7.8 GiB RAM, zero OOM risk).
- **Subprocess Guardrails in `conftest.py`**:
  - Always invoke CLI via `sys.executable` or `<repo>/.venv/bin/python` with `env={**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"}` to prevent thread oversubscription.
  - Set `timeout=120` on `demo`/`train` subprocess calls and `timeout=60` on `generate`/`eval`/`transcribe`.
  - Keep `torch.set_num_threads(2)` in `conftest.py` (if `torch` is importable) to keep CPU contention predictable.

---

## 6. Shared Fixtures Needed from `tests_e2e/conftest.py`

To keep Tier 3 and Tier 4 fast, clean, and DRY, `tests_e2e/conftest.py` should expose:
1. `repo_root` (`Path`) and `venv_python` (`Path`: `.venv/bin/python` with fallback to `sys.executable`).
2. `run_cli(args: list[str], *, cwd=None, timeout=90) -> subprocess.CompletedProcess` helper wrapping `[str(venv_python), "-m", "asr", *args]` with `OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`, `capture_output=True`, `text=True`.
3. `session_tsukinami_cache_dir` (session-scoped `Path` via `tmp_path_factory.mktemp("tsukinami_cache")`).
4. `session_tiny_dataset` (session-scoped dict `{"dir": Path, "train": Path, "val": Path}` generated with `num_train=12, num_val=4, engine="fast", seed=42`).
5. `session_tiny_checkpoint` (session-scoped `Path` to `best.pt` trained with `cnn_bigru`, `hidden_size=32, num_layers=1, epochs=2, batch_size=4`).
6. `session_asr_engine` (session-scoped `ASREngine.from_checkpoint(session_tiny_checkpoint)`).
7. `api_client` (function- or module-scoped FastAPI `TestClient(create_app(engine=session_asr_engine))`).
