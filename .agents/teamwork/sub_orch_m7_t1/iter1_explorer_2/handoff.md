# Explorer 2 Handoff — Unit Tests & Features #1–#11 Contract Audit (`sub_orch_m7_t1`)

## 1. Unit Regression Suite Results

- **Command**: `.venv/bin/pytest tests/ -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Summary**: **153 passed, 0 failed, 0 skipped, 0 xfailed** (2 warnings) in `83.75s`
  - `tests/test_asr_cli.py`: 16 passed
  - `tests/test_asr_data.py`: 19 passed
  - `tests/test_asr_decoding.py`: 38 passed
  - `tests/test_asr_dsp.py`: 45 passed
  - `tests/test_asr_models.py`: 17 passed
  - `tests/test_asr_web.py`: 18 passed

---

## 2. Features #1–#11 Contract Audit (`tests_e2e/conftest.py` & `tests_e2e/test_tier1_features.py`)

Cross-checked every fixture in `tests_e2e/conftest.py` and every test in Features #1–#11 (`tests_e2e/test_tier1_features.py`, lines 25–918) against `asr/{config,audio,features,tokenizer,synth_data,dataset,train}.py`, `asr/models/{__init__,subsampling,cnn_bigru,conformer}.py`, and `PROJECT.md § Interface Contracts`.

| Feature | E2E Test Class | Status | Notes |
|---|---|---|---|
| #1 Config & Env | `TestTier1Feature01ConfigEnv` (6 tests) | **PASS / MATCH** | `pyproject.toml`, `.gitignore` (contains `.venv/`), `asr/__init__.py`, and all 4 config dataclasses (`AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig`) match defaults and `.to_dict()`/`.from_dict()` contracts. |
| #2 Audio I/O & Resampling | `TestTier1Feature02AudioIO` (5 tests) | **PASS / MATCH** | `save_wav`, `load_wav`, `resample` match signatures, 1D `float32` mono `[-1, 1]` bounds, 44.1 kHz → 16 kHz resampling, and stereo mixdown. |
| #3 STFT, Log-Mel & MFCC | `TestTier1Feature03Features` (5 tests) | **PASS / MATCH** | `extract_log_mel` (default 64 mels, 80 mels, CMVN) and `extract_mfcc` (13 coeffs, 39 with deltas) match shapes, dtypes, and numerical expectations. |
| #4 Energy VAD | `TestTier1Feature04VAD` (5 tests) | **PASS / MATCH** | `detect_vad` matches signature (`frame_ms`, `threshold_db`, `hangover_ms`), segment separation, hangover extension, and threshold sensitivity. |
| #5 SpecAugment & Corruptions | `TestTier1Feature05Augment` (6 tests) | **PASS / MATCH** | `spec_augment` (non-mutating, seed reproducibility) and `apply_corruption` (white/pink SNR, telephone band-pass `(300, 3400)`, speed, gain_db) match contracts. |
| #6 CTC Tokenizer | `TestTier1Feature06Tokenizer` (6 tests) | **PASS / MATCH** | `Tokenizer` (`kana`, `phoneme`, `ascii`), `blank_id == 0`, hiragana→katakana normalization, `collapse_ctc`, `to_dict`/`from_dict`, and custom `vocab` override match contracts. |
| #7 Fast `kotoba` Synth | `TestTier1Feature07FastSynth` (5 tests) | **PASS / MATCH** | `synthesize_fast_kotoba` returns 1D `float32` + monotonic `{"t", "a", "e"}` moras; `rate`, `f0_scale`, `fscale`, `snr_db`, and `seed` all match. |
| #8 Tsukinami TTS | `TestTier1Feature08TsukinamiTTS` (5 tests) | **PASS / MATCH** | `synthesize_tsukinami` supports presets (`default`, `ossan`, `robot`, etc.), `overrides`, atomic disk `cache_dir` hit, and `sr` resampling. |
| #9 Manifest & Dataset | `TestTier1Feature09Dataset` (6 tests) | **1 MISMATCH** | **`test_generate_dataset_fast_creates_manifests_and_wavs` (line 656)** fails because `row["audio_path"]` is manifest-relative (`"audio/train/train_00000.wav"`), while the test checks `Path(row["audio_path"]).is_file()` against CWD. All other 5 tests match. |
| #10 Acoustic Models | `TestTier1Feature10Models` (6 tests) | **PASS / MATCH** | `build_model` (`cnn_bigru`, `conformer_lite`), `(log_probs, out_lengths)` shapes, `log_softmax` normalization, `subsampling_factor == 4`, `output_frame_stride_ms`, CTC backward gradients, and eval determinism match. |
| #11 Training & Checkpointing | `TestTier1Feature11Training` (5 tests) | **PASS / MATCH** | `train_asr` and `load_checkpoint` match all required keys (`model_state_dict`, `model_config`, `audio_cfg`, `tokenizer`, `history`, `epoch`, `best_val_cer`), resume, `conformer_lite` training, and deterministic seeding. |
| Shared Fixtures | `tests_e2e/conftest.py` | **PASS / MATCH** | `tiny_fast_dataset`, `tiny_checkpoint`, `tiny_engine`, `api_client`, and all synthetic signal/WAV helpers match `asr/` interfaces cleanly. |

---

## 3. Finding Detail & Exact Fix Plan

### Issue: Relative `audio_path` in `tests_e2e/test_tier1_features.py:656`

- **Location**: `tests_e2e/test_tier1_features.py`, `TestTier1Feature09Dataset.test_generate_dataset_fast_creates_manifests_and_wavs`, lines 654–656:
  ```python
        for ln in train_lines + val_lines:
            row = json.loads(ln)
            assert Path(row["audio_path"]).is_file()
  ```
- **Root Cause**:
  - `asr/synth_data.py:786` writes `"audio_path": rel_wav.as_posix()` (e.g., `"audio/train/train_00000.wav"`), relative to `out_dir` (`tmp_path`).
  - `asr/dataset.py:77-86` (`_resolve_audio_path`) resolves relative `audio_path` entries against `manifest_path.parent`, and `build_manifest_from_wav_dir` (`asr/dataset.py:356`) also emits manifest-relative paths for portability.
  - `tests/test_asr_data.py:360` explicitly asserts cross-directory determinism (`out1["train"].read_text() == out2["train"].read_text()` for `tmp_path / "ds1"` vs `tmp_path / "ds2"`), which requires `audio_path` to remain relative rather than absolute.
  - `PROJECT.md § Interface Contracts` (line 158) specifies `"audio_path": "..."` without requiring absolute paths.
  - Evaluating `Path(row["audio_path"]).is_file()` directly checks `<CWD>/audio/train/train_00000.wav` instead of `<tmp_path>/audio/train/train_00000.wav`, which fails when `tmp_path` is outside CWD.

- **Recommended Minimal Fix** (in `tests_e2e/test_tier1_features.py:654-656`, preserving relative portable manifests in `asr/synth_data.py` and full compatibility with `tests/test_asr_data.py`):
  ```python
        for ln in train_lines + val_lines:
            row = json.loads(ln)
            audio_p = Path(row["audio_path"])
            if not audio_p.is_absolute():
                audio_p = tmp_path / audio_p
            assert audio_p.is_file()
  ```
  - This accepts both absolute and manifest-relative `audio_path` values without weakening the assertion (still verifies every referenced WAV file exists on disk).
  - No changes needed to `asr/` modules for Features #1–#11.
