# Tsukinami ASR — E2E Test Infrastructure (`TEST_INFRA.md`)

## 1. Architecture & Opaque-Box Testing Principles

The E2E test suite under `tests_e2e/` validates the complete Tsukinami ASR system (**Features #1–#18** in `PROJECT.md § Feature Inventory`) strictly through its documented public interfaces (`PROJECT.md § Interface Contracts`):

- **Opaque-Box Contract Verification**: Tests invoke only documented Python APIs, CLI subcommands (`python -m asr ...`), and FastAPI HTTP routes (`/`, `/api/health`, `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`). Zero private/internal symbols (`_*`) or uncontracted fields are referenced. For `POST /api/transcribe` multipart WAV uploads, the suite uses the standard FastAPI form field name `"file"` (`files={"file": (...)}`).
- **Independent Test Oracles**: Synthetic waveforms (`make_sine`, `make_speech_like`, `make_silence`, `make_clipped`), PCM WAV writers/corruptors (`write_pcm_wav`, `write_corrupt_wav`, `wav_to_bytes`, `wav_to_b64`), and analytical CTC `log_probs` builders (`make_synthetic_log_probs`, `make_weighted_log_probs`) are implemented solely with Python stdlib + NumPy inside `tests_e2e/conftest.py` — never reusing `asr/` code to validate itself.
- **Parallel-Safe Collection, Genuine Execution**:
  - Module-level imports in `tests_e2e/` are strictly limited to Python stdlib and `pytest`. All `asr.*`, `numpy`, `torch`, `fastapi`, and `httpx` imports live inside fixture and test function bodies.
  - Consequently, `pytest --collect-only tests_e2e/` succeeds cleanly even while `asr/` is being developed in parallel.
  - Zero `pytest.skip`, zero `pytest.xfail`, zero `try: import asr ... except ImportError: return`, and zero dummy assertions exist anywhere in `tests_e2e/`. Running any test against missing or broken `asr/` code fails genuinely.
- **Progressive Testability**: Earlier features (Config, Audio I/O, Features, VAD, Augment, Tokenizer, Decoding, Alignment, Metrics) are tested in isolation without depending on neural models or training.

---

## 2. Test Suite Layout

| File | Tier | Purpose |
|---|---|---|
| `tests_e2e/conftest.py` | Harness | Independent synthetic audio/WAV/log-prob helpers + session-scoped fixtures (`tiny_fast_dataset`, `tiny_checkpoint`, `tiny_engine`, `api_client`, `api_client_no_model`, `run_cli`, `tsukinami_cache_dir`) |
| `tests_e2e/test_tier1_features.py` | Tier 1 | Isolated happy-path feature coverage (`>= 5` tests per feature across all 18 features) |
| `tests_e2e/test_tier2_boundaries.py` | Tier 2 | Boundary, corner-case, and negative/error-handling coverage (`>= 5` tests per feature across all 18 features) |
| `tests_e2e/test_tier3_combinations.py` | Tier 3 | 12 pairwise and multi-module cross-feature combination tests spanning all 18 features |
| `tests_e2e/test_tier4_scenarios.py` | Tier 4 | 9 realistic multi-feature end-user workflows (CPU `demo`, 5-preset `tsukinami` round-trip, noisy/telephone study, web playground session, Tier-3 WAV folder corpus, architecture comparison + resume, `CharNgramLM` study, `<10 ms` cached redecode sweep, existing TTS non-regression) |

---

## 3. Shared Fixtures & Helpers (`tests_e2e/conftest.py`)

### Independent Helpers (exposed via `helpers` fixture)
- `make_sine(freq, duration, sr, amp)` — 1D `float32` sine wave.
- `make_speech_like(duration, sr, f0, pad_sec, seed)` — 1D `float32` harmonic formant-modulated signal framed by leading/trailing silence.
- `make_silence(duration, sr)` — 1D `float32` zero array.
- `make_clipped(duration, sr, amp)` — 1D `float32` waveform exceeding `[-1.0, 1.0]`.
- `write_pcm_wav(path, wav, sr, channels, sampwidth)` — stdlib `wave` writer supporting mono/stereo and 16-bit/32-bit PCM.
- `write_corrupt_wav(path, kind)` — writes `"garbage"`, `"empty"` (0-byte), or `"truncated"` RIFF headers.
- `wav_to_bytes(wav, sr)` / `wav_to_b64(wav, sr)` — in-memory 16-bit mono WAV serialization for HTTP API tests.
- `make_synthetic_log_probs(frame_token_ids, vocab_size, peak_logit)` — analytical `(T, V)` `log_softmax` matrix.
- `make_weighted_log_probs(frame_logits, vocab_size)` — competing multi-token per-frame `log_softmax` matrix for beam search + LM tie-breaking tests.
- `extract_transcribe_payload(resp_json)` — extracts `TranscribeResult` keys from flat or nested `/api/tts-roundtrip` payloads.

### Session-Scoped Fixtures
- `repo_root` — `/home/antigravity/poidowl/tsukinami`.
- `python_bin` — `.venv/bin/python` if present, else `sys.executable`.
- `run_cli` — subprocess runner invoking `[python_bin, "-m", "asr", *args]` with `OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`.
- `tsukinami_cache_dir` — shared temporary disk cache for authentic 44.1 kHz `tsukinami` TTS calls.
- `tiny_fast_dataset` — 12 train / 4 val Tier-1 fast-kotoba dataset (`engine="fast"`, `seed=42`).
- `tiny_checkpoint` — compact CPU-trained `cnn_bigru` (`hidden_size=32, num_layers=1, epochs=2, batch_size=4`) saved to `best.pt` and `latest.pt`.
- `tiny_engine` — `ASREngine.from_checkpoint(tiny_checkpoint["best_pt"])`.
- `api_client_factory` — creates FastAPI `TestClient(create_app(checkpoint_path=..., engine=...))`.
- `api_client` — `TestClient` backed by `tiny_engine`.
- `api_client_no_model` — `TestClient` backed by `create_app()` with no loaded checkpoint.

---

## 4. CPU & RAM Runtime Budget

Designed for the project's CPU-only host (**2 vCPUs, 7.8 GiB RAM, 0 swap**):

| Tier / Component | Est. Wall Time | Peak RAM | Guardrails |
|---|---:|---:|---|
| Session fixture setup (`tiny_fast_dataset` + `tiny_checkpoint` + `tiny_engine`) | ~3 s | ~400 MiB | `torch.set_num_threads(2)`, `hidden_size=32`, `num_layers=1`, `epochs=2` |
| Tier 1 (`test_tier1_features.py`) | ~15–25 s | ~500 MiB | Short 1–2 mora `tsukinami` phrases + shared `tsukinami_cache_dir` |
| Tier 2 (`test_tier2_boundaries.py`) | ~10–20 s | ~500 MiB | Reuses session fixtures; pure NumPy for decoding/alignment/metrics |
| Tier 3 (`test_tier3_combinations.py`) | ~20–35 s | ~600 MiB | Tiny 6–12 utterance manifests, 1–2 epochs, `OMP_NUM_THREADS=2` |
| Tier 4 (`test_tier4_scenarios.py`) | ~45–70 s | ~750 MiB | `asr demo --epochs 2 --num-train 16`, cached 2-mora `tsukinami` presets |
| **Full Suite Total** | **~95–155 s** | **< 750 MiB** | `< 10%` of 7.8 GiB RAM, zero swap pressure |

---

## 5. Pytest Runner Commands

Run from `/home/antigravity/poidowl/tsukinami`:

```bash
# Verify collection without executing tests
.venv/bin/pytest --collect-only tests_e2e/ -q

# Run the entire E2E suite (Tiers 1-4)
.venv/bin/pytest -v tests_e2e/

# Run individual tiers
.venv/bin/pytest -v tests_e2e/test_tier1_features.py
.venv/bin/pytest -v tests_e2e/test_tier2_boundaries.py
.venv/bin/pytest -v tests_e2e/test_tier3_combinations.py
.venv/bin/pytest -v tests_e2e/test_tier4_scenarios.py

# Filter by feature (example: Feature 12 CTC Decoding)
.venv/bin/pytest -v tests_e2e/ -k "Feature12"
```

---

## 6. Feature-to-Test Traceability Matrix (Features #1–#18)

| # | Feature (`PROJECT.md`) | Tier 1 (`test_tier1_features.py`) | Tier 2 (`test_tier2_boundaries.py`) | Tier 3 (`test_tier3_combinations.py`) | Tier 4 (`test_tier4_scenarios.py`) |
|---:|---|---|---|---|---|
| 1 | Project Environment, Packaging & Config | `TestTier1Feature01ConfigEnv` (6) | `TestTier2Feature01ConfigBoundaries` (5) | `test_t3_cnn_bigru_train_checkpoint_and_resume`, `test_t3_conformer_lite_train_checkpoint_and_forward`, `test_t3_cli_pipeline_generate_train_eval_transcribe` | `test_t4_scenario1_*`, `test_t4_scenario6_*` |
| 2 | WAV/PCM I/O & Resampling | `TestTier1Feature02AudioIO` (5) | `TestTier2Feature02AudioIOBoundaries` (6) | `test_t3_corruption_noise_features_and_vad`, `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug`, `test_t3_tsukinami_presets_cache_wav_io_logmel` | `test_t4_scenario5_*`, `test_t4_scenario7_*` |
| 3 | Pure-NumPy STFT, Log-Mel & MFCC | `TestTier1Feature03Features` (5) | `TestTier2Feature03FeaturesBoundaries` (5) | `test_t3_corruption_noise_features_and_vad`, `test_t3_corruption_speed_bandlimit_gain_features`, `test_t3_tsukinami_presets_cache_wav_io_logmel` | `test_t4_scenario3_*`, `test_t4_scenario8_*` |
| 4 | Energy VAD & Silence Trimming | `TestTier1Feature04VAD` (5) | `TestTier2Feature04VADBoundaries` (5) | `test_t3_corruption_noise_features_and_vad` | `test_t4_scenario3_*`, `test_t4_scenario8_*` |
| 5 | SpecAugment & Waveform Corruptions | `TestTier1Feature05Augment` (6) | `TestTier2Feature05AugmentBoundaries` (6) | `test_t3_corruption_noise_features_and_vad`, `test_t3_corruption_speed_bandlimit_gain_features`, `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug`, `test_t3_engine_transcribe_visuals_corruption_and_redecode`, `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | `test_t4_scenario3_*` |
| 6 | CTC Tokenizer (Kana/Phoneme/ASCII) | `TestTier1Feature06Tokenizer` (6) | `TestTier2Feature06TokenizerBoundaries` (6) | `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug`, `test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate` | `test_t4_scenario5_*`, `test_t4_scenario6_*` |
| 7 | Tier 1: Fast `kotoba` Formant Synth | `TestTier1Feature07FastSynth` (5) | `TestTier2Feature07FastSynthBoundaries` (5) | `test_t3_corruption_noise_features_and_vad`, `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug`, `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics`, `test_t3_cli_pipeline_generate_train_eval_transcribe` | `test_t4_scenario1_*`, `test_t4_scenario3_*`, `test_t4_scenario5_*` |
| 8 | Tier 2: Authentic `tsukinami` TTS | `TestTier1Feature08TsukinamiTTS` (5) | `TestTier2Feature08TsukinamiTTSBoundaries` (5) | `test_t3_tsukinami_presets_cache_wav_io_logmel`, `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | `test_t4_scenario2_*`, `test_t4_scenario9_*` |
| 9 | Tier 3: Unified Manifest & DataLoader | `TestTier1Feature09Dataset` (6) | `TestTier2Feature09DatasetBoundaries` (5) | `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug`, `test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate`, `test_t3_cli_pipeline_generate_train_eval_transcribe` | `test_t4_scenario5_*` |
| 10 | Selectable CTC Acoustic Models | `TestTier1Feature10Models` (6) | `TestTier2Feature10ModelsBoundaries` (5) | `test_t3_cnn_bigru_train_checkpoint_and_resume`, `test_t3_conformer_lite_train_checkpoint_and_forward`, `test_t3_model_logprobs_greedy_beam_lm_and_viterbi` | `test_t4_scenario6_*` |
| 11 | Training Engine & Checkpointing | `TestTier1Feature11Training` (5) | `TestTier2Feature11TrainingBoundaries` (5) | `test_t3_cnn_bigru_train_checkpoint_and_resume`, `test_t3_conformer_lite_train_checkpoint_and_forward`, `test_t3_cli_pipeline_generate_train_eval_transcribe` | `test_t4_scenario1_*`, `test_t4_scenario5_*`, `test_t4_scenario6_*` |
| 12 | CTC Decoding (Greedy + Beam + LM) | `TestTier1Feature12Decoding` (7) | `TestTier2Feature12DecodingBoundaries` (7) | `test_t3_model_logprobs_greedy_beam_lm_and_viterbi`, `test_t3_engine_transcribe_visuals_corruption_and_redecode`, `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | `test_t4_scenario7_*`, `test_t4_scenario8_*` |
| 13 | Viterbi Forced Alignment | `TestTier1Feature13Alignment` (5) | `TestTier2Feature13AlignmentBoundaries` (5) | `test_t3_model_logprobs_greedy_beam_lm_and_viterbi`, `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics` | `test_t4_scenario2_*` |
| 14 | ASR Evaluation Metrics | `TestTier1Feature14Metrics` (7) | `TestTier2Feature14MetricsBoundaries` (6) | `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics` | `test_t4_scenario2_*`, `test_t4_scenario3_*`, `test_t4_scenario5_*`, `test_t4_scenario7_*` |
| 15 | High-Level Inference Engine (`ASREngine`) | `TestTier1Feature15Engine` (6) | `TestTier2Feature15EngineBoundaries` (5) | `test_t3_engine_transcribe_visuals_corruption_and_redecode`, `test_t3_cli_pipeline_generate_train_eval_transcribe`, `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | `test_t4_scenario1_*`, `test_t4_scenario2_*`, `test_t4_scenario5_*`, `test_t4_scenario6_*`, `test_t4_scenario7_*`, `test_t4_scenario8_*` |
| 16 | Full CLI (`python -m asr ...`) | `TestTier1Feature16CLI` (7) | `TestTier2Feature16CLIBoundaries` (6) | `test_t3_cli_pipeline_generate_train_eval_transcribe` | `test_t4_scenario1_*` |
| 17 | FastAPI Backend (`asr/server.py`) | `TestTier1Feature17API` (6) | `TestTier2Feature17APIBoundaries` (6) | `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | `test_t4_scenario4_*` |
| 18 | Zero-CDN Web Playground (`index.html`) | `TestTier1Feature18WebPlayground` (5) | `TestTier2Feature18WebBoundaries` (5) | `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | `test_t4_scenario4_*` |
| **Total** | **18 Features** | **103 tests** | **98 tests** | **12 tests** | **9 tests** |
