# Milestone M3 Iteration 2 — Primary Reviewer (`rev1`) Handoff

## Verdict: **APPROVE**

All 3 Iteration 2 fixes in `asr/train.py` and their regression tests in `tests/test_asr_models.py` are verified, `asr/models/*.py` remain clean and intact, there are zero out-of-scope edits, and the full M1–M4 unit test suite passes (119/119).

---

## Code Inspection Summary

### 1. Deterministic SpecAugment (`asr/train.py`)
- `_SeededSpecAugmentDataset` wraps `ASRManifestDataset(..., augment=False)` using a dedicated `np.random.default_rng(seed)` to generate deterministic per-sample integer seeds for `asr.features.spec_augment(mel_np, seed=aug_seed)`, returning contiguous `float32` tensors.
- Combined with `DataLoader(..., num_workers=0, generator=loader_gen)` seeded with `train_cfg.seed`, repeated `train_asr` runs with `use_spec_augment=True` and the same seed produce bit-for-bit identical histories and model weights while genuinely applying SpecAugment.
- Regression test `test_train_asr_deterministic_with_spec_augment` verifies exact history equality, exact tensor equality (`torch.equal`) across all `model_state_dict` entries, and non-trivial difference in epoch-1 `train_loss` vs `use_spec_augment=False`.

### 2. Preserving `best_val_cer` on `resume_from` into a New `checkpoint_dir` (`asr/train.py`)
- Before the epoch loop, when `resume_from is not None and not best_path.exists()`, `train_asr` atomically writes `_build_ckpt(start_epoch - 1)` to `best_path`, seeding the new `checkpoint_dir` with the resumed weights and `best_val_cer`.
- Inside the epoch loop, `improved` checks strict improvement (`val_cer < best_val_cer` or tied `val_cer` with lower `val_loss`), and `is_best = improved or (resume_from is None and not best_path.exists())`, preventing worse resumed epochs from clobbering `best_val_cer`, `best_val_loss`, or `best.pt`.
- Regression test `test_resume_into_new_checkpoint_dir_preserves_best_val_cer` confirms `best_val_cer`, `best.pt["epoch"]`, and `best.pt["model_state_dict"]` are preserved across worse subsequent epochs in a brand-new `checkpoint_dir`.

### 3. Clean Error Handling on Corrupt/Empty Checkpoints (`asr/train.py`)
- `load_checkpoint` preserves `FileNotFoundError` for missing files and `ValueError` for directories, non-dict payloads, and missing required keys (`model_state_dict`, `model_config`, `tokenizer`).
- Catches `_CORRUPT_CKPT_ERRORS = (EOFError, pickle.UnpicklingError, zipfile.BadZipFile, RuntimeError, OSError)` on both `weights_only=True` and `weights_only=False` fallback paths and raises `ValueError(f"Corrupt or invalid checkpoint {ckpt_path}: {exc}") from exc`.
- Regression test `test_load_checkpoint_corrupt_and_empty_files` verifies corrupt random bytes, 0-byte empty files, directories, and missing paths.

### 4. Model Modules & Scope Hygiene
- Inspected `asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, and `asr/models/conformer.py`: all remain clean, intact, and compliant with `PROJECT.md` and `SCOPE.md` contracts (`build_model`, 4× subsampling, padding-mask invariance, `output_frame_stride_ms`, dynamic sinusoidal positional encoding).
- Zero tracked TTS repository files modified; no out-of-scope edits.

---

## Exact Verification Commands & Outputs

### 1. Scope & Working Tree Check
Command:
```bash
git status --short && git diff --stat
```
Output (exit code 0):
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

### 2. Full M1–M4 Unit Test Suite
Command:
```bash
.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py -v
```
Output (exit code 0):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 119 items

tests/test_asr_dsp.py .............................................      [ 37%]
tests/test_asr_data.py ...................                               [ 53%]
tests/test_asr_decoding.py ......................................        [ 85%]
tests/test_asr_models.py .................                               [100%]

======================== 119 passed in 83.52s (0:01:23) ========================
```
