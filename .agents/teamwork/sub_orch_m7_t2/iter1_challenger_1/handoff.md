# Challenger 1 Report (`iter1_challenger_1`) — M7 Phase 1 Tier 2 E2E (`sub_orch_m7_t2`, Iteration 1)

## Verdict: **PASS**

No correctness, boundary, or interface contract defects were found in the fixed path (`asr/dataset.py`) or in Features 1–11 (`asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/config.py`, `asr/synth_data.py`, `asr/models/`).

---

## Probe Scope & Methodology
- Executed isolated adversarial Python probes via `.venv/bin/python` staged in temporary directories created with `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and removed immediately after execution.
- Did **not** modify the working tree or run `tests_e2e/`.

---

## Results Summary (25/25 Probe Groups Passed)

### 1. `asr/dataset.py` (Fixed Path + Manifest/Dataset Boundaries)
| Probe | Input / Scenario | Observed Behavior | Status |
|---|---|---|---|
| `bm_empty_dir_empty_dict` | Empty `wav_dir` + `{}` | Creates empty JSONL file, returns `Path`, `load_manifest(out) == []` | PASS |
| `bm_empty_dir_empty_json` | Empty `wav_dir` + JSON file `{}` | Creates empty JSONL file, `load_manifest(out) == []` | PASS |
| `bm_empty_dir_empty_tsv` | Empty `wav_dir` + whitespace-only TSV | Creates empty JSONL file, `load_manifest(out) == []` | PASS |
| `bm_empty_nested_subdirs_empty_dict` | Empty nested subdirs + `{}` | Creates empty JSONL file, `load_manifest(out) == []` | PASS |
| `bm_empty_dir_nonempty_dict` | Empty `wav_dir` + `{"a.wav": "ア"}` | Raises `ValueError`; does not write output file | PASS |
| `bm_nonempty_dir_nonwav_only_empty_dict` | Dir with `.txt`/`.mp3` only + `{}` | Ignores non-WAV files; creates empty JSONL file | PASS |
| `bm_nonempty_dir_valid_wav_empty_dict` | Dir with valid `.wav` + `{}` | Raises `ValueError` (unmatched WAV files) | PASS |
| `bm_nested_subdirs_and_key_precedence` | Nested subdirs, duplicate filenames, uppercase `.WAV`, nested `out_manifest_path` | Deterministic POSIX-sorted manifest, absolute paths, accurate durations | PASS |
| `bm_relative_key_overrides_stem` | All 3 keys (`sub/a.wav`, `a.wav`, `a`) in map | Relative POSIX path takes precedence per docstring | PASS |
| `bm_jsut_and_kaldi_formats` | JSUT `id:text` and Kaldi `id text` transcript files | Parses and builds manifest cleanly | PASS |
| `bm_nonexistent_wav_dir` | Missing `wav_dir` | Raises `FileNotFoundError` | PASS |
| `bm_wav_dir_is_file` | Regular file passed as `wav_dir` | Raises `ValueError` | PASS |
| `bm_corrupt_wav_matched_and_unmatched` | Corrupt RIFF/WAVE matched in `tmap` or unmatched with `{}` | Raises `ValueError` cleanly | PASS |
| `bm_corrupt_unmatched_alongside_valid_matched` | Corrupt unmatched WAV + valid matched WAV | Skips unmatched corrupt WAV; succeeds on valid matched WAV | PASS |
| `bm_whitespace_transcript` | Valid WAV + whitespace-only transcript `"   "` | Raises `ValueError` | PASS |
| `bm_invalid_tmap_type` | Non-mapping/non-path `tmap`, non-string transcript values | Raises `TypeError` / `ValueError` | PASS |
| `manifest_and_dataset_boundaries` | `load_manifest`, `write_manifest`, `ASRManifestDataset`, `collate_asr_batch` on empty/malformed/missing/mismatched inputs | Raises expected `FileNotFoundError`/`ValueError`; `allow_empty_targets=True` works | PASS |

### 2. Features 1–11 Boundary Probes
- **`asr/audio.py`** (`audio_io_boundaries`, `audio_resample_boundaries`, `audio_vad_boundaries`, `audio_corruption_boundaries`):
  - `load_wav` / `load_wav_bytes` reject missing, directory, empty, corrupt RIFF, random bytes, non-bytes, and invalid `target_sr` (`0`, `-16000`, `True`).
  - `save_wav` sanitizes `NaN`/`Inf` and clips out-of-range floats cleanly; 0-frame WAV raises `ValueError` on reload.
  - `resample`, `detect_vad`, `apply_corruption` handle empty arrays, 1-sample arrays, silence, extreme SNR (`-20 dB`, `100 dB`), full-band `band_limit=(0.0, 8000.0)`, and reject invalid/non-finite/bool parameters with `ValueError`.
- **`asr/features.py`** (`features_boundaries`):
  - `extract_log_mel` and `extract_mfcc` produce finite `float32` tensors on empty, 1-sample, silent (with/without CMVN), and stereo waveforms; reject 3D/0-channel inputs and invalid `n_mfcc`/`stft_power`/`mel_filterbank` args.
  - `spec_augment` preserves input immutability, handles empty `(0, F)`/`(T, 0)` and mask widths > dimension, and rejects invalid shapes/negative/bool params.
- **`asr/tokenizer.py`** (`tokenizer_boundaries`):
  - All modes (`kana`, `phoneme`, `ascii`) maintain `blank_id == 0`, handle empty text/IDs, collapse CTC correctly, reject out-of-range IDs, duplicate tokens, misplaced `<blank>`, and malformed `from_dict` inputs.
- **`asr/config.py`** (`config_boundaries`):
  - `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig` round-trip via `to_dict`/`from_dict` and reject unknown keys, non-mappings, `bool`-as-numeric, `NaN`/`Inf`, and out-of-range invariants.
- **`asr/synth_data.py` & `asr/models/`** (`synth_and_models`):
  - `synthesize_fast_kotoba("")` gracefully returns empty `float32` array + `[]`; invalid `sr`/`rate`/`preset` raise `ValueError`.
  - Both `cnn_bigru` and `conformer_lite` produce finite normalized `log_softmax` outputs.
