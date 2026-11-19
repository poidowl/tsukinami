# Milestone M3 Iteration 2 — Worker (`worker2`) Handoff

## Summary of Changes

All 3 bugs reported by Challenger 2 (`chal2`) in `asr/train.py` have been fixed cleanly and genuinely within exclusive M3 file ownership, and regression tests have been added in `tests/test_asr_models.py`.

### Modified Files (Exclusive M3 Ownership)
- [`asr/train.py`](file:///home/antigravity/poidowl/tsukinami/asr/train.py)
- [`tests/test_asr_models.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_models.py)

No out-of-scope files (`asr/dataset.py`, `asr/features.py`, M1/M2/M4 files, existing TTS files, `tests_e2e/`) were modified.

---

### Fixes Implemented in `asr/train.py`

1. **Deterministic SpecAugment under `TrainConfig(use_spec_augment=True)`**:
   - Added `_SeededSpecAugmentDataset(Dataset)` wrapper in `asr/train.py` that holds a `np.random.default_rng(seed)` generator and draws deterministic integer seeds to apply `asr.features.spec_augment(mel, seed=aug_seed)` per sample while preserving exact `float32` tensor dtype and shape.
   - Updated `train_asr` to instantiate `ASRManifestDataset(..., augment=False)` and wrap it in `_SeededSpecAugmentDataset(base_train_ds, seed=train_cfg.seed)` whenever `train_cfg.use_spec_augment` is `True`.
   - Two `train_asr` runs with `use_spec_augment=True` and the same `seed` now produce bit-for-bit identical training histories and model weights, while still genuinely applying SpecAugment (verified to differ from `use_spec_augment=False`).

2. **Preserve `best_val_cer` when `resume_from` targets a new `checkpoint_dir`**:
   - Before entering the epoch loop, when `resume_from is not None and not best_path.exists()`, `train_asr` atomically saves `_build_ckpt(start_epoch - 1)` to `best_path` so the new `checkpoint_dir` starts with the resumed model weights and `best_val_cer`.
   - Inside the epoch loop, separated strict metric improvement (`improved = (val_cer < best_val_cer) or (val_cer == best_val_cer and val_loss < best_val_loss)`) from initial fresh-run creation (`is_best = improved or (resume_from is None and not best_path.exists())`).
   - Subsequent worse epochs no longer clobber `best_val_cer`, `best_val_loss`, or `best.pt`.

3. **Clean error handling in `load_checkpoint` for corrupt/empty files**:
   - Preserved `FileNotFoundError` for missing files and `ValueError` for directories, non-dict payloads, and missing required keys.
   - Caught `(EOFError, pickle.UnpicklingError, zipfile.BadZipFile, RuntimeError, OSError)` on both `weights_only=True` and `weights_only=False` fallback paths and re-raised `ValueError(f"Corrupt or invalid checkpoint {ckpt_path}: {exc}") from exc`.

---

### Regression Tests Added in `tests/test_asr_models.py`

1. `test_train_asr_deterministic_with_spec_augment`:
   - Runs `train_asr` twice with `use_spec_augment=True` and identical `seed=42`; verifies exact history match (`res_a["history"] == res_b["history"]`) and bit-for-bit identical `model_state_dict` tensors (`torch.equal`).
   - Also verifies `use_spec_augment=True` alters epoch-1 `train_loss` compared to `use_spec_augment=False`.
2. `test_resume_into_new_checkpoint_dir_preserves_best_val_cer`:
   - Resumes a checkpoint with `best_val_cer=0.001` into a brand-new `checkpoint_dir` for epochs 3–4 where validation CER is worse; verifies returned `best_val_cer`, `latest.pt["best_val_cer"]`, `best.pt["best_val_cer"]`, `best.pt["epoch"] == 2`, and exact resumed weights in `best.pt` are preserved.
3. `test_load_checkpoint_corrupt_and_empty_files`:
   - Verifies `load_checkpoint` raises `ValueError` matching `"Corrupt or invalid checkpoint"` on corrupt random-bytes and 0-byte empty files, `ValueError` on a directory, and `FileNotFoundError` on a missing path.

---

## Canonical Verification Results

### 1. `.venv/bin/pytest tests/test_asr_models.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 17 items

tests/test_asr_models.py .................                               [100%]

============================= 17 passed in 15.40s ==============================
```

### 2. `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py -v`
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

============================= 119 passed in 58.03s =============================
```

### 3. `git status --short && git diff --stat`
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
(No tracked TTS repository files were modified.)
