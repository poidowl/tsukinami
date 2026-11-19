# Secondary Reviewer Handoff — M7 Phase 1: Tier 3 E2E (`test_tier3_combinations.py`)

## Verdict: **APPROVE**

All 154 unit tests pass cleanly, all 12 Tier 3 cross-feature combination tests in `tests_e2e/test_tier3_combinations.py` genuinely exercise real multi-module paths and satisfy `PROJECT.md § Interface Contracts`, and the repository working tree has zero modifications to existing `tsukinami` TTS files.

---

## 1. Target-Scoped Unit Test Verification

Command:
```bash
.venv/bin/pytest tests/ -v
```

Output (exit code `0`):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 154 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ....................                              [ 23%]
tests/test_asr_decoding.py ......................................        [ 48%]
tests/test_asr_dsp.py .............................................      [ 77%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_web.py ..................                                 [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 154 passed, 2 warnings in 178.89s (0:02:58) ==================
```

- **Result**: **154/154 PASSED** (0 failed, 0 errors, 0 skipped, 0 xfailed).
- **Warnings**: Both warnings are benign third-party notices (Starlette `TestClient` deprecation and PyTorch's `weights_only` unpickler warning on the intentional corrupt-pickle negative test `test_corrupt_pickle_frame_checkpoint`).

---

## 2. Independent Cross-Feature Review (`tests_e2e/test_tier3_combinations.py` vs `asr/` & `PROJECT.md`)

Independently inspected `tests_e2e/test_tier3_combinations.py` (all 12 tests, lines 1–447) and verified against `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/__init__.py`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, `asr/__main__.py`, and `asr/server.py`:

| # | Test | Cross-Feature Path Verified | `PROJECT.md § Interface Contracts` Compliance |
|---:|---|---|---|
| 1 | `test_t3_corruption_noise_features_and_vad` | F2 + F3 + F4 + F5 + F7: `synthesize_fast_kotoba` → `apply_corruption` (`white`/`pink`, 10 dB SNR) → `extract_log_mel` & `extract_mfcc(n_mfcc=13, include_deltas=True)` → `detect_vad` | Exact: `float32` `(T, 64)` & `(T, 39)`, finite outputs, measurable spectral delta, valid `(start_sec, end_sec)` VAD segments. |
| 2 | `test_t3_corruption_speed_bandlimit_gain_features` | F3 + F5 + F7: speed (`1.25` / `0.8`), telephone band-limit `(300.0, 3400.0)`, gain (`-6.0` dB) → raw & CMVN Log-Mel | Exact: frame-count monotonicity `T_fast < T_clean < T_slow`, high-frequency attenuation on top 10 Mel bins, RMS scaling, CMVN mean/std invariants. |
| 3 | `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug` | F2 + F3 + F5 + F6 + F7 + F9: fast synth → `save_wav` → JSONL manifest → `Tokenizer("kana")` → `ASRManifestDataset` (`augment=False/True`) → `collate_asr_batch` + `spec_augment` | Exact: batch keys (`feats`, `feat_lengths`, `targets`, `target_lengths`, `texts`), non-blank target IDs, non-mutating non-trivial SpecAugment. |
| 4 | `test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate` | F6 + F7 + F9: `Tokenizer("phoneme").to_dict()` / `from_dict()` → `ASRManifestDataset` → `collate_asr_batch` → `decode` | Exact: `blank_id == 0`, `vocab_size > 10`, non-empty targets & decoded phoneme strings. |
| 5 | `test_t3_tsukinami_presets_cache_wav_io_logmel` | F2 + F3 + F8: `synthesize_tsukinami` (`default` vs `ossan`, `cache_dir`) → atomic disk cache hit → `save_wav`/`load_wav` round-trip → `extract_log_mel` | Exact: cache populated & bit-consistent (`atol=1e-4`), mora dicts contain `{"t", "a", "e"}`, WAV round-trip correlation `> 0.999`, distinct preset Log-Mels. |
| 6 | `test_t3_cnn_bigru_train_checkpoint_and_resume` | F1 + F10 + F11: `train_asr` (`cnn_bigru`, 1 epoch) → `resume_from=latest.pt` (2 epochs) → `load_checkpoint` → `build_model` + `load_state_dict` forward | Exact: all required checkpoint keys (`model_state_dict`, `model_config`, `audio_cfg`, `tokenizer`, `history`, `epoch`, `best_val_cer`), `subsampling_factor == 4`, `output_frame_stride_ms == 40.0`, finite log-probs. |
| 7 | `test_t3_conformer_lite_train_checkpoint_and_forward` | F1 + F10 + F11: `train_asr` (`conformer_lite`, 1 epoch) → `load_checkpoint` → `build_model` forward on padded batch | Exact: finite `log_probs`, `out_len <= feat_lengths`, `exp(log_probs).sum(-1) == 1.0`. |
| 8 | `test_t3_model_logprobs_greedy_beam_lm_and_viterbi` | F10 + F12 + F13: real trained model `log_probs` → `CharNgramLM` `to_dict`/`from_dict` → `greedy_decode`, `prefix_beam_search` (with & without LM), `viterbi_align` | Exact: required dict keys for greedy/beam/alignment, descending beam scores, monotonic `start_sec`, finite confidence. |
| 9 | `test_t3_kotoba_moras_viterbi_boundary_error_and_metrics` | F7 + F13 + F14: `synthesize_fast_kotoba` moras → model + `viterbi_align` → `alignment_boundary_error` + `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs` | Exact: finite boundary error metrics, `cer == (S + D + I) / ref_len`, `mer >= 0`, `wer == 0.5`, 3-tuple confusion pairs. |
| 10 | `test_t3_engine_transcribe_visuals_corruption_and_redecode` | F5 + F12 + F15: `ASREngine.transcribe(include_visuals=True)` on clean & white-noise corrupted audio → cached `redecode` (greedy & beam with `temperature`, `blank_bias`) | Exact: all 10 required result keys present and non-None, LRU cache hit for both `redecode` calls. |
| 11 | `test_t3_cli_pipeline_generate_train_eval_transcribe` | F1 + F7 + F9 + F11 + F15 + F16: real subprocess CLI `generate` → `train` → `eval` → `transcribe --wav --json` & `transcribe --tts --json` | Exact: exit code 0 on all 5 subprocesses, manifest/checkpoint files written, CER reported, valid JSON transcription outputs. |
| 12 | `test_t3_api_tts_roundtrip_corruption_redecode_and_info` | F5 + F8 + F12 + F15 + F17 + F18: FastAPI `GET /api/info` → `POST /api/tts-roundtrip` (with corruption & beam decode) → `POST /api/redecode` → `GET /` zero-CDN HTML | Exact: `RIFF` WAV base64, non-empty `ground_truth_moras`, numeric `cer >= 0`, cached `utterance_id` redecode, zero external `<script src>` / `<link href>` CDN references. |

- **Non-blocking observations noted for Tier 5**: Agree with Explorer 2 & 3 that the minor `asr/train.py` resume edge-case items (cosine LR recomputation on extended `T_max`, stricter tokenizer/audio_cfg validation on resume, SpecAugment seed offset on resume, unique temp filename in `_atomic_torch_save`) do not violate any Tier 3 contract and are best deferred to Tier 5 hardening.

---

## 3. Repository Cleanliness Check

Command:
```bash
git status --short && echo "---DIFF---" && git diff --stat
```

Output (exit code `0`):
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
---DIFF---
```

- **Confirmed**: `git diff --stat` is completely empty (0 tracked files modified). All existing `tsukinami` TTS files remain untouched, and no stray edits or temporary files exist.
