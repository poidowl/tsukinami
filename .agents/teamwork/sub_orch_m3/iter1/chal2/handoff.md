# Challenger 2 (`chal2`) Adversarial Report — Milestone M3 (`asr/train.py`)

## Verdict: **FAIL**

Isolated adversarial probes against [asr/train.py](file:///home/antigravity/poidowl/tsukinami/asr/train.py) passed 19/23 checks and uncovered **3 concrete bugs** (4 failed assertions) in determinism under default `use_spec_augment=True`, `load_checkpoint` corrupt/empty-file exception handling, and `resume_from` preservation of `best_val_cer` when resuming into a new `checkpoint_dir`.

---

## Failures (with Exact Reproduction & Root Cause)

### 1. Non-Deterministic Training with Default `TrainConfig(use_spec_augment=True)`
- **Observed**:
  - `determinism(use_spec_augment=False)`: **PASS** (`hist_match=True`, `max_weight_diff=0.000e+00`)
  - `determinism(use_spec_augment=True)` (the default in [`TrainConfig`](file:///home/antigravity/poidowl/tsukinami/asr/config.py#L156-L164)): **FAIL**
    - `hist_match=False`, `max_weight_diff=1.777e-02`
    - Run 1 train losses: `[16.440486, 14.049475]`
    - Run 2 train losses: `[16.464702, 14.053461]`
- **Root Cause**:
  - [`train_asr`](file:///home/antigravity/poidowl/tsukinami/asr/train.py#L173-L178) passes `augment=train_cfg.use_spec_augment` directly to [`ASRManifestDataset`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py#L162-L163), which calls `spec_augment(mel)` with `seed=None`.
  - In [`spec_augment`](file:///home/antigravity/poidowl/tsukinami/asr/features.py#L237), `np.random.default_rng(None)` draws fresh OS entropy and ignores `np.random.seed(train_cfg.seed)` set by `_seed_everything`.
- **Recommended Fix (in `asr/train.py` only)**:
  - Instantiate `train_ds` with `augment=False`, and apply `spec_augment` deterministically inside `asr/train.py` (e.g., via a lightweight seeded wrapper `Dataset` around `train_ds` or per-sample before collation/training) using a deterministic `seed` drawn from a `np.random.default_rng(train_cfg.seed)` generator.

### 2. `resume_from` into a New `checkpoint_dir` Clobbers `best_val_cer`
- **Observed**:
  - Resuming a checkpoint with `best_val_cer=0.001` (epoch 2) into a new `checkpoint_dir` for epochs 3–4 where epoch 3 has worse `val_cer=0.9722`: **FAIL**
  - Returned `best_val_cer=0.9722` and `latest.pt["best_val_cer"]=0.9722` (clobbered `0.001`).
- **Root Cause**:
  - In [`train_asr`](file:///home/antigravity/poidowl/tsukinami/asr/train.py#L342-L349):
    ```python
    is_best = (
        (val_cer < best_val_cer)
        or (val_cer == best_val_cer and val_loss < best_val_loss)
        or (not best_path.exists())
    )
    if is_best:
        best_val_cer = float(val_cer)
        best_val_loss = float(val_loss)
    ```
    When `best.pt` does not exist yet in the new directory, `not best_path.exists()` forces `is_best=True` and overwrites `best_val_cer` and `best_val_loss` with the worse validation metrics.
- **Recommended Fix**:
  - Separate metric improvement from `best.pt` existence:
    - `improved = (val_cer < best_val_cer) or (val_cer == best_val_cer and val_loss < best_val_loss)`
    - Only update `best_val_cer` / `best_val_loss` when `improved` is `True`.
    - When resuming into a new `checkpoint_dir` where `best.pt` does not yet exist, either write the resumed checkpoint to `best.pt` before the epoch loop or save `best.pt` when `improved or not best_path.exists()` without clobbering `best_val_cer`/`best_val_loss`.

### 3. `load_checkpoint` Leaks Raw `pickle.UnpicklingError` and `EOFError` on Corrupt/Empty Files
- **Observed**:
  - Random bytes file (`b"not a valid torch checkpoint at all 1234567890"`): **FAIL** — raised `pickle.UnpicklingError: invalid load key, 'n'.`
  - Empty 0-byte file (`b""`): **FAIL** — raised `EOFError: `
- **Root Cause**:
  - [`load_checkpoint`](file:///home/antigravity/poidowl/tsukinami/asr/train.py#L57-L60) catches `(pickle.UnpicklingError, RuntimeError)` only to fall back to `weights_only=False`, leaving corrupt/empty files to leak raw `pickle.UnpicklingError`, `EOFError`, or `zipfile.BadZipFile` instead of a clean `ValueError` / `RuntimeError`.
- **Recommended Fix**:
  - Wrap the fallback `torch.load(..., weights_only=False)` (and any `EOFError` / `zipfile.BadZipFile` / `pickle.UnpicklingError` / `OSError`) and raise `ValueError(f"Corrupt or invalid checkpoint {ckpt_path}: {exc}") from exc` (or `RuntimeError`).

---

## Passing Checks (19/23)

| Category | Check | Result | Evidence |
|---|---|---|---|
| 1. Determinism | `use_spec_augment=False` | PASS | `hist_match=True`, `max_weight_diff=0.000e+00` |
| 2. Checkpoint Integrity | `torch.load(..., weights_only=True)` on `best.pt` & `latest.pt` | PASS | Both loaded cleanly with 11 keys |
| 2. Checkpoint Integrity | Required keys in `best.pt` & `latest.pt` | PASS | All 8 required keys present + `audio_cfg` alias |
| 2. Checkpoint Integrity | Exact logit reconstruction (`atol=1e-5`) | PASS | `max_diff=0.000e+00`, identical `out_lengths` |
| 2. Error Handling | Missing file / directory / non-dict / missing keys | PASS | `FileNotFoundError`, `ValueError`, `ValueError`, `ValueError` |
| 3. `resume_from` | Epoch 2 -> 4 in same `checkpoint_dir` | PASS | `epochs=[1, 2, 3, 4]`, `len(history)==4`, `best_val_cer` preserved |
| 3. `resume_from` | `train_cfg.epochs == ckpt["epoch"]` (same dir) | PASS | `len_hist=4`, `epochs_completed=4`, no crash/corruption |
| 3. `resume_from` | `train_cfg.epochs < ckpt["epoch"]` (new dir) | PASS | `len_hist=4`, `ckpt_epoch=4`, `best.pt` & `latest.pt` valid |
| 4. CTC Edge Case | `out_length < target_length` (`cnn_bigru`, mixed & all-short) | PASS | All weights & losses finite; no crash |
| 4. CTC Edge Case | `out_length < target_length` (`conformer_lite`, mixed & all-short) | PASS | All weights & losses finite; no crash |
| 5. Genuine Learning | `cnn_bigru` on fresh synthetic utterances | PASS | Loss `15.340 -> 2.585` (`83.1%` drop) |
| 5. Genuine Learning | `conformer_lite` on fresh synthetic utterances | PASS | Loss `16.335 -> 2.961` (`81.9%` drop) |

All probe scripts and temporary data were staged in `/tmp/teamwork_probe.c4rzFE` and removed (`rm -rf`) after execution. The working tree was not modified.
