# Milestone M3 Iteration 2 — Secondary Reviewer (`rev2`) Handoff

## Verdict: **APPROVE**

## Review Scope
- Verified against:
  - [`ORIGINAL_REQUEST.md`](file:///home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md)
  - [`PROJECT.md`](file:///home/antigravity/poidowl/tsukinami/PROJECT.md)
  - [`SCOPE.md`](file:///home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m3/SCOPE.md)
  - [`worker2/handoff.md`](file:///home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m3/iter2/worker2/handoff.md)
- Inspected files:
  - [`asr/train.py`](file:///home/antigravity/poidowl/tsukinami/asr/train.py)
  - [`tests/test_asr_models.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_models.py)
  - Read-only cross-checks against [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py) and [`asr/features.py`](file:///home/antigravity/poidowl/tsukinami/asr/features.py)

---

## Detailed Findings

### 1. `_SeededSpecAugmentDataset` (`asr/train.py` L60–L83, L219–L229)
- **Root cause addressed**: `asr.features.spec_augment` instantiates `np.random.default_rng(seed)` internally, so calling `ASRManifestDataset(..., augment=True)` without a seed bypassed `np.random.seed(train_cfg.seed)`.
- **Implementation quality**:
  - `train_asr` instantiates `ASRManifestDataset(..., augment=False)` and wraps it in `_SeededSpecAugmentDataset(base_train_ds, seed=train_cfg.seed)` when `train_cfg.use_spec_augment` is `True`.
  - `_SeededSpecAugmentDataset` holds an instance-level `np.random.default_rng(seed)` and draws a deterministic integer seed `aug_seed = int(self._rng.integers(0, 2**31 - 1))` on each `__getitem__` call.
  - Because `DataLoader` uses `num_workers=0` and a seeded `torch.Generator` (`loader_gen`), sample ordering and per-sample SpecAugment seeds are strictly reproducible across runs while still varying across samples and epochs.
  - Copies the item dict (`dict(self._base_ds[idx])`), converts `feats` safely to NumPy, applies `spec_augment(mel_np, seed=aug_seed)` (which preserves shape `(T, F)` without mutating input), and returns a contiguous `torch.float32` tensor (`np.ascontiguousarray(aug_mel, dtype=np.float32)`).
- **Regression test**: `test_train_asr_deterministic_with_spec_augment` (`tests/test_asr_models.py` L450–L493) verifies exact history equality, bit-for-bit `torch.equal` weights across two runs with `use_spec_augment=True`, and non-trivial augmentation effect (`train_loss` differs from `use_spec_augment=False`).

### 2. `resume_from` `best.pt` / `best_val_cer` Preservation (`asr/train.py` L337–L338, L396–L416)
- **Fresh run (`resume_from is None`)**: `best_val_cer` starts at `inf`, so epoch 1 sets `is_best = True` and creates `best.pt`; subsequent epochs update `best.pt` only on strict improvement (`val_cer < best_val_cer` or `val_cer == best_val_cer and val_loss < best_val_loss`).
- **Resume into a new `checkpoint_dir` (`best_path` missing)**:
  - Before the epoch loop (L337–L338), `_atomic_torch_save(_build_ckpt(start_epoch - 1), best_path)` seeds `best.pt` with the resumed weights, epoch (`start_epoch - 1`), and `best_val_cer`.
  - Inside the loop (L396–L403), `is_best = improved or (resume_from is None and not best_path.exists())` evaluates to `improved`, preventing worse post-resume epochs from clobbering `best_val_cer`, `best_val_loss`, or `best.pt`.
- **Resume into the same `checkpoint_dir` (`best_path` already exists)**:
  - L337 does not overwrite the existing `best.pt` with `latest.pt` weights, and L399 only updates `best.pt` on genuine metric improvement.
- **Resume with `train_cfg.epochs <= ckpt["epoch"]`**: L410–L416 ensures both `latest.pt` and `best.pt` exist in `checkpoint_dir` without running extra epochs.
- **Regression test**: `test_resume_into_new_checkpoint_dir_preserves_best_val_cer` (`tests/test_asr_models.py` L496–L560) confirms returned `best_val_cer`, `latest.pt["best_val_cer"]`, `best.pt["best_val_cer"]`, `best.pt["epoch"] == 2`, and exact resumed weights in `best.pt` are preserved when resuming into a new directory with worse subsequent epochs.

### 3. `load_checkpoint` Error Handling (`asr/train.py` L51–L57, L86–L125)
- Missing path raises `FileNotFoundError`; directory path raises `ValueError`.
- Attempts `torch.load(..., weights_only=True)` first, falling back to `weights_only=False` on `(pickle.UnpicklingError, RuntimeError)` for compatibility.
- Both paths catch `_CORRUPT_CKPT_ERRORS = (EOFError, pickle.UnpicklingError, zipfile.BadZipFile, RuntimeError, OSError)` and raise `ValueError(f"Corrupt or invalid checkpoint {ckpt_path}: {exc}") from exc`.
- Validates that payload is a `dict` containing `_REQUIRED_CKPT_KEYS = ("model_state_dict", "model_config", "tokenizer")` and synchronizes `audio_config` / `audio_cfg` aliases.
- **Regression test**: `test_load_checkpoint_corrupt_and_empty_files` (`tests/test_asr_models.py` L563–L578) covers random-bytes corrupt files, 0-byte empty files, directory paths, and missing paths.

### 4. Workspace Hygiene & Ownership
- No tracked existing TTS repository files were modified.
- Changes are strictly within M3 exclusive ownership (`asr/train.py`, `tests/test_asr_models.py`).

---

## Verification Commands & Exact Outputs

### 1. Target-Scoped M3 Test Suite
Command:
```bash
.venv/bin/pytest tests/test_asr_models.py -v
```
Output (exit code `0`):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 17 items

tests/test_asr_models.py .................                               [100%]

============================= 17 passed in 28.27s ==============================
```

### 2. Working Tree Integrity Check
Command:
```bash
git status --short && git diff --stat
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
```
