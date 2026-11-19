VERDICT: GAPS_FOUND

# Fresh White-Box Challenger 1 Report — M7 Phase 2: Tier 5 Adversarial Hardening (Iteration 2)

## Scope Audited
Independently audited all updated core DSP, data, model, training, decoding, and metrics modules:
- `asr/config.py`
- `asr/audio.py`
- `asr/features.py`
- `asr/tokenizer.py`
- `asr/synth_data.py`
- `asr/dataset.py`
- `asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, `asr/models/conformer.py`
- `asr/train.py`
- `asr/decoding.py`
- `asr/metrics.py`
- `tests/test_asr_tier5_hardening.py`

All Iteration 1 fixes that were tested held up cleanly on their targeted inputs (`_prepare_log_probs` under extreme `temperature=1e-308` / `blank_bias=±1e308`, `CharNgramLM.from_dict`, `TrainConfig` seed bounds, `extract_log_mel` on `float32 * 1e20` and `NaN` inputs, `extract_mfcc`/`spec_augment` float rejection, `alignment_boundary_error` `NaN`/`Inf` rejection, NaN-padding isolation and `T'>1024` dynamic positional encoding on both model architectures).

However, isolated white-box probes uncovered **5 concrete, reproducible bypasses / uncaught crashes** directly adjacent to the Iteration 1 hardening fixes.

---

## Concrete Gaps Found

### Gap 1 — `asr/synth_data.py`: `synthesize_tsukinami` still crashes with `ZeroDivisionError` & `synthesize_fast_kotoba` crashes with `OverflowError` (Bypass of Iteration 1 Fix #3)
- **Affected Files & Lines**:
  - `asr/synth_data.py:572-575` (`synthesize_tsukinami`)
  - `asr/synth_data.py:348-350, 382-390` (`synthesize_fast_kotoba`)
- **Repro**:
  ```python
  from asr.synth_data import synthesize_tsukinami, synthesize_fast_kotoba

  # 1a. Documented _YOMU_PRM_KEYS override 'tsubu=0' -> ZeroDivisionError in carve.py:1487
  synthesize_tsukinami("ア", overrides={"tsubu": 0})

  # 1b. Sub-acoustic positive hz -> passes _validate_positive_float, crashes in carve.py:1404
  synthesize_tsukinami("ア", overrides={"hz": 1e-308})

  # 1c. Extreme positive rate -> OverflowError inside kotoba/synth length calculation
  synthesize_fast_kotoba("ア", rate=1e308)
  ```
- **Observed**:
  - `overrides={"tsubu": 0}` raises uncaught `ZeroDivisionError: division by zero` at `carve.py:1487` (`gm = sum(grain) / Gs`).
  - `overrides={"hz": 1e-308}` raises uncaught `ZeroDivisionError: float division by zero` at `carve.py:1404` (`f / (SR / (2 * L["D_center"]))`).
  - `synthesize_fast_kotoba("ア", rate=1e308)` raises uncaught `OverflowError: cannot convert float infinity to integer`.
- **Expected**:
  - Validate reasonable finite domain bounds upfront and raise `ValueError`:
    - `synthesize_tsukinami`: validate `tsubu` is a positive finite number (e.g., `> 0` / reasonable range), and enforce practical domain bounds on `hz` (e.g., `[20.0, 2000.0]`), `fscale` (e.g., `[0.25, 4.0]`), and `rate` (e.g., `[0.1, 10.0]`).
    - `synthesize_fast_kotoba`: enforce practical finite bounds on `rate` (e.g., `[0.1, 10.0]`), `f0_scale`, and `fscale` so `kotoba.tracks_from_kana` / sample-count computation cannot overflow to `inf` or OOM.
- **Proposed Test Spec**:
  - In `tests/test_asr_tier5_hardening.py`: extend `test_synthesize_tsukinami_invalid_overrides_rejected` to assert `ValueError` for `{"tsubu": 0}`, `{"tsubu": -1}`, `{"hz": 1e-308}`, `{"rate": 1e308}`, and assert `ValueError` for `synthesize_fast_kotoba("ア", rate=1e308)`.

---

### Gap 2 — `asr/audio.py`: `save_wav` leaves 0-byte corrupt file & raises `wave.Error`; `detect_vad` & `apply_corruption` raise `OverflowError` / `TypeError` (Bypass of Iteration 1 Fix #2)
- **Affected Files & Lines**:
  - `asr/audio.py:233, 264, 300, 329-336` (`load_wav_bytes`, `load_wav`, `save_wav`, `detect_vad`)
  - `asr/audio.py:434-436, 453-466, 475-477` (`apply_corruption`)
- **Repro**:
  ```python
  import numpy as np
  from pathlib import Path
  from asr.audio import save_wav, detect_vad, apply_corruption

  wav = np.sin(2.0 * np.pi * 440.0 * np.arange(1600) / 16000.0).astype(np.float32)

  # 2a. save_wav with inf/nan sr -> wave.Error + leaves empty 0-byte file on disk!
  save_wav(Path("/tmp/bad.wav"), wav, sr=float("inf"))
  save_wav(Path("/tmp/bad2.wav"), wav, sr=float("nan"))

  # 2b. detect_vad with inf/nan/float sr or bool frame_ms
  detect_vad(wav, sr=float("inf"))          # OverflowError
  detect_vad(wav, sr=16000.5)               # silently accepted
  detect_vad(wav, frame_ms=True)            # silently accepted

  # 2c. apply_corruption with extreme low speed or non-sequence band_limit
  apply_corruption(wav, 16000, speed=1e-308)    # OverflowError
  apply_corruption(wav, 16000, band_limit=123)  # TypeError: object of type 'int' has no len()
  ```
- **Observed**:
  - `save_wav(..., sr=float("inf"))` and `sr=float("nan")` open and truncate the target file, fail in `wf.setframerate(int(sr))`, then raise `wave.Error: sampling rate not specified` from `__exit__`, leaving a 0-byte corrupt file on disk.
  - `detect_vad(wav, sr=float("inf"))` raises `OverflowError: cannot convert float infinity to integer`.
  - `apply_corruption(wav, 16000, speed=1e-308)` raises `OverflowError: cannot convert float infinity to integer` (and `speed=1e-6` would attempt a ~128 GB allocation / OOM).
  - `apply_corruption(wav, 16000, band_limit=123)` raises `TypeError` instead of `ValueError`.
- **Expected**:
  - Share a single `_validate_positive_int_sr(name, sr)` helper across `resample`, `load_wav`, `load_wav_bytes`, `save_wav`, `detect_vad`, and `apply_corruption` (rejecting `bool`, `float`, `NaN`, `Inf`, and `<= 0` with `ValueError` BEFORE touching the filesystem).
  - In `detect_vad`, reject `bool` for `frame_ms`, `threshold_db`, and `hangover_ms` with `ValueError`.
  - In `apply_corruption`, bound `speed` to a finite safe range (e.g., `[0.1, 10.0]`) and validate `band_limit` is a 2-element sequence of non-bool finite numbers (raising `ValueError`, not `TypeError`).
- **Proposed Test Spec**:
  - In `tests/test_asr_tier5_hardening.py`: test `save_wav` with `sr=float("inf")`/`float("nan")`/`16000.5`/`True` raises `ValueError` and does NOT create the output file; `detect_vad` rejects `sr=float("inf")`/`16000.5`/`frame_ms=True` with `ValueError`; `apply_corruption` rejects `speed=1e-308`, `speed=1e-6`, `band_limit=123`, `band_limit=(False, True)` with `ValueError`.

---

### Gap 3 — `asr/features.py`: `mel_filterbank` & `stft_power` crash with `OverflowError` / `TypeError` or silently truncate floats (Bypass of Iteration 1 Fix #6)
- **Affected Files & Lines**:
  - `asr/features.py:153-155` (`mel_filterbank`)
  - `asr/features.py:64-71` (`_stft_power_f64` / `stft_power`)
- **Repro**:
  ```python
  import numpy as np
  from asr.features import mel_filterbank, stft_power

  wav = np.ones(1600, dtype=np.float32)
  mel_filterbank(sr=float("inf"))         # OverflowError
  mel_filterbank(n_mels=3.5)              # silently returns shape (3, 257)
  mel_filterbank(sr=True, f_min=0.0, f_max=0.4)  # silently returns shape (64, 257)
  stft_power(wav, hop_length=160.5)       # TypeError: slice indices must be integers
  stft_power(wav, n_fft=512.5)            # TypeError: 'float' object cannot be interpreted as an integer
  ```
- **Observed**:
  - `mel_filterbank(sr=float("inf"))` raises `OverflowError`; `mel_filterbank(n_mels=3.5)` and `sr=True` silently succeed with truncated/bool values.
  - `stft_power` raises `TypeError` on float `n_fft`/`win_length`/`hop_length`.
- **Expected**:
  - Validate `sr`, `n_fft`, `n_mels` in `mel_filterbank` and `n_fft`, `win_length`, `hop_length` in `_stft_power_f64` as positive integers (`not isinstance(v, bool) and isinstance(v, (int, np.integer)) and int(v) > 0`), raising `ValueError`.
- **Proposed Test Spec**:
  - In `tests/test_asr_tier5_hardening.py`: extend `test_features_nan_filterbank_large_signal_and_type_validation` to assert `ValueError` for `mel_filterbank(sr=float("inf"))`, `mel_filterbank(n_mels=3.5)`, `mel_filterbank(sr=True, f_min=0.0, f_max=0.4)`, `stft_power(wav, hop_length=160.5)`, and `stft_power(wav, n_fft=512.5)`.

---

### Gap 4 — `asr/tokenizer.py`: `Tokenizer.from_dict` raises `TypeError` on non-iterable `vocab` and silently splits string `vocab` into characters (Parallel to Iteration 1 Fix #1b)
- **Affected Files & Lines**:
  - `asr/tokenizer.py:251-258` (`Tokenizer.from_dict`)
- **Repro**:
  ```python
  from asr.tokenizer import Tokenizer

  Tokenizer.from_dict({"mode": "kana", "vocab": 123})    # TypeError: 'int' object is not iterable
  Tokenizer.from_dict({"mode": "kana", "vocab": "abc"})  # silently creates vocab ['<blank>', 'a', 'b', 'c']!
  ```
- **Observed**:
  - `d["vocab"] = 123` raises `TypeError` instead of `ValueError`.
  - `d["vocab"] = "abc"` (a `str`, which is iterable!) is silently accepted and split into single-character tokens `['<blank>', 'a', 'b', 'c']`, corrupting vocab deserialization.
- **Expected**:
  - Validate `isinstance(d["vocab"], (list, tuple))` (explicitly rejecting `str`, `bytes`, `int`, `dict`, etc.) and raise `ValueError`, matching `CharNgramLM.from_dict`.
- **Proposed Test Spec**:
  - In `tests/test_asr_tier5_hardening.py`: assert `ValueError` for `Tokenizer.from_dict({"mode": "kana", "vocab": 123})` and `Tokenizer.from_dict({"mode": "kana", "vocab": "abc"})`.

---

### Gap 5 — `asr/train.py`: `train_asr(resume_from=...)` crashes with `TypeError` / `RuntimeError` on malformed `history` or mismatched `model_state_dict` (Adjacent to Iteration 1 Fix #5)
- **Affected Files & Lines**:
  - `asr/train.py:316-332` (`train_asr` resume path)
- **Repro**:
  ```python
  # Checkpoint with matching model_config and tokenizer, but:
  # 5a. "history": None -> TypeError: 'NoneType' object is not iterable (line 323)
  # 5b. "model_state_dict": {"bad": torch.zeros(1)} -> RuntimeError (line 316)
  ```
- **Observed**:
  - `train_asr(..., resume_from=ckpt)` raises `TypeError` when `ckpt["history"]` is `None` (or non-list) and `RuntimeError` when `ckpt["model_state_dict"]` has missing/unexpected keys or shape mismatches, instead of normalizing corrupt resume checkpoints to `ValueError` (as `ASREngine.from_checkpoint` now does).
- **Expected**:
  - Validate `history` is a `list` of `Mapping` entries (when present) and wrap `model.load_state_dict` / `optimizer.load_state_dict` / `scheduler.load_state_dict` / `epoch` / `best_val_cer` parsing in `try/except (RuntimeError, TypeError, ValueError, KeyError)` raising `ValueError("Corrupt or incompatible resume checkpoint ...")`.
- **Proposed Test Spec**:
  - In `tests/test_asr_tier5_hardening.py`: extend `test_train_resume_rejects_malformed_or_mismatched_tokenizer` to assert `ValueError` when resuming from a checkpoint with `"history": None` or mismatched `"model_state_dict"`.

---

## Modules Audited Clean (No Concrete Bugs Found)
- `asr/config.py`: All 4 dataclasses validate types, finiteness, bounds, and unknown keys cleanly.
- `asr/dataset.py`: `load_manifest`, `ASRManifestDataset`, `collate_asr_batch`, and `build_manifest_from_wav_dir` handle relative/missing paths, malformed JSONL, empty manifests/batches, and dimension mismatches cleanly.
- `asr/models/{__init__,subsampling,cnn_bigru,conformer}.py`: Both `cnn_bigru` and `conformer_lite` handle `T=1`, `T'>1024`, mixed batch lengths `[1, 17]`, and `NaN` padding isolation cleanly.
- `asr/decoding.py`: `_prepare_log_probs`, `greedy_decode`, `prefix_beam_search`, `CharNgramLM`, and `viterbi_align` handle empty inputs, `vocab_size=1/2`, extreme `temperature=1e-308` / `blank_bias=±1e308`, and all-`-inf` frames cleanly.
- `asr/metrics.py`: `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`, `alignment_boundary_error`, and `compute_rtf` handle empty sequences, `NaN`/`Inf` timestamps, and boundary cases cleanly.

## Cleanliness Verification
- All ad-hoc probe scripts were executed in temporary `mktemp -d` directories under `/tmp` and removed (`rm -rf`) immediately after execution.
- Zero files in `/home/antigravity/poidowl/tsukinami` were modified (`git status --short` verified unchanged).
