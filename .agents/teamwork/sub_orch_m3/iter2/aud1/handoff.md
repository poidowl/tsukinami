# Milestone M3 Iteration 2 — Forensic Audit Report (`aud1`)

## Verdict: **CLEAN**

---

## 1. Scope & Diff Integrity

- **Working tree check (`git status --short` & `git diff --stat`)**:
  - `git diff --stat` returned empty output: **0 tracked TTS repository files** were modified.
  - `git status --short` shows only expected untracked project additions (`.agents/`, `.gitignore`, `PROJECT.md`, `TEST_INFRA.md`, `TEST_READY.md`, `asr/`, `pyproject.toml`, `tests/`, `tests_e2e/`).
- **Timestamp & File Ownership Check (`ls -l --full-time asr/ asr/models/ tests/ tests_e2e/`)**:
  - Only [`asr/train.py`](file:///home/antigravity/poidowl/tsukinami/asr/train.py) (`04:05:09`) and [`tests/test_asr_models.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_models.py) (`04:05:25`) were updated in Iteration 2.
  - All out-of-scope files (`asr/dataset.py`, `asr/features.py`, `asr/audio.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/decoding.py`, `asr/metrics.py`, `tests_e2e/*`, and existing TTS files) remain completely untouched.

---

## 2. Anti-Cheating & Genuine Implementation Audit

### A. Iteration 2 Changes in [`asr/train.py`](file:///home/antigravity/poidowl/tsukinami/asr/train.py)
1. **`_SeededSpecAugmentDataset` (lines 60–83)**:
   - Wraps `ASRManifestDataset(..., augment=False)` when `train_cfg.use_spec_augment=True`.
   - Maintains a per-dataset `np.random.default_rng(seed)` and draws a fresh deterministic integer seed (`aug_seed = int(self._rng.integers(0, 2**31 - 1))`) on every `__getitem__` call, passing it to genuine [`asr.features.spec_augment`](file:///home/antigravity/poidowl/tsukinami/asr/features.py#L211-L255) with default masking parameters (`freq_mask_param=8, time_mask_param=20, num_freq_masks=2, num_time_masks=2`).
   - Confirmed **not** a no-op: `spec_augment` masks frequency bands and time frames to `0.0` on a copy of the mel spectrogram, varies masks across samples/epochs, and produces bit-for-bit reproducible runs under `num_workers=0` + seeded `DataLoader` `generator`.
2. **Preserving `best_val_cer` on `resume_from` into a new `checkpoint_dir` (lines 337–338, 396–407)**:
   - Atomically seeds `best.pt` from the resumed state (`_build_ckpt(start_epoch - 1)`) before the epoch loop when `resume_from is not None and not best_path.exists()`.
   - Separates strict improvement (`improved = (val_cer < best_val_cer) or (val_cer == best_val_cer and val_loss < best_val_loss)`) from fresh-run initialization (`is_best = improved or (resume_from is None and not best_path.exists())`), preventing worse resumed epochs from clobbering `best_val_cer` or `best.pt`.
3. **`load_checkpoint` corrupt/empty file handling (lines 51–57, 86–125)**:
   - Cleanly preserves `FileNotFoundError` for missing paths, `ValueError` for directories / non-dicts / missing required keys, and catches `(EOFError, pickle.UnpicklingError, zipfile.BadZipFile, RuntimeError, OSError)` on both `weights_only=True` and `weights_only=False` fallback paths, re-raising `ValueError(f"Corrupt or invalid checkpoint {ckpt_path}: {exc}") from exc`.

### B. Acoustic Models (`asr/models/`)
- [`asr/models/__init__.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/__init__.py): Clean `build_model` factory validating `vocab_size >= 2` and `arch in {"cnn_bigru", "conformer_lite"}`.
- [`asr/models/subsampling.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/subsampling.py): Genuine 2-layer stride-2 `Conv2d` (`4x` time reduction) with 3-point zero-masking and exact `output_lengths`.
- [`asr/models/cnn_bigru.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/cnn_bigru.py): Genuine `Conv2dSubsampling` + bidirectional `nn.GRU` with `pack_padded_sequence`/`pad_packed_sequence` + `LayerNorm` + `Linear` + `log_softmax(dim=-1)`.
- [`asr/models/conformer.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/conformer.py): Genuine `Conv2dSubsampling` + dynamic `SinusoidalPositionalEncoding` + Macaron `ConformerBlock` (`0.5 * FFN`, masked `MultiheadAttention`, GLU depthwise separable `_ConformerConvModule` with frame-wise `LayerNorm`, `0.5 * FFN`, final `LayerNorm`) + `Linear` + `log_softmax(dim=-1)`.
- No stubs, hardcoded outputs, fake loss curves, or broken gradient flow detected.

### C. Unit Tests ([`tests/test_asr_models.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_models.py))
- All 17 test cases are genuine, unskipped, and non-weakened:
  - Includes shape/log-prob/short-input checks, dynamic positional encoding (`T=4200`), padding-mask invariance (both mutated padding and unpadded single-item vs padded batch), full parameter gradient flow under `nn.CTCLoss`, genuine CPU overfit sanity test (`>50%` CTC loss drop and CER drop on synthetic Japanese utterances), checkpoint exact logit reproduction and resume, `conformer_lite` training smoke test, deterministic SpecAugment verification (confirming both bit-for-bit reproducibility AND genuine divergence from `use_spec_augment=False`), resume-into-new-dir `best_val_cer` + weight preservation, and corrupt/empty checkpoint error handling.

---

## 3. Independent Target-Scoped Test Execution

Command: `.venv/bin/pytest tests/test_asr_models.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 17 items

tests/test_asr_models.py .................                               [100%]

============================= 17 passed in 28.29s ==============================
```

Exit code: `0`.

---

## 4. Conclusion

No integrity violations, scope leaks, or anti-cheating issues were found. All Iteration 2 fixes and regression tests are genuine and independently verified. Verdict: **CLEAN**.
