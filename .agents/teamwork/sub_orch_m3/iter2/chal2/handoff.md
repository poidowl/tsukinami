# Challenger 2 (`chal2`) Iteration 2 Adversarial Report — Milestone M3 (`asr/train.py`)

## Verdict: **PASS**

All **27/27** isolated adversarial probes against [`asr/train.py`](file:///home/antigravity/poidowl/tsukinami/asr/train.py) passed with 0 failures. All 3 bugs identified in Iteration 1 are genuinely fixed without regressions or silent bypasses.

---

## Verification Matrix (27/27 Passed)

| Category | Check | Result | Evidence |
|---|---|---|---|
| 1. Determinism & SpecAugment | `determinism(use_spec_augment=False)` (`cnn_bigru`) | PASS | `hist_match=True`, `max_weight_diff=0.000e+00`, losses `[11.522197, 7.804504]` |
| 1. Determinism & SpecAugment | `determinism(use_spec_augment=True)` (`cnn_bigru`) | PASS | `hist_match=True`, `max_weight_diff=0.000e+00`, losses `[11.556349, 7.809852]` |
| 1. Determinism & SpecAugment | `determinism(use_spec_augment=True)` (`conformer_lite`) | PASS | `hist_match=True`, `max_weight_diff=0.000e+00` |
| 1. Determinism & SpecAugment | SpecAugment genuinely active (`True` vs `False`) | PASS | `hist_diff=True`, `max_weight_diff=2.157e-02` (not silently disabled) |
| 1. Determinism & SpecAugment | Default `TrainConfig().use_spec_augment` | PASS | `True` |
| 2. Checkpoint Integrity | `torch.load(..., weights_only=True)` on `best.pt` & `latest.pt` | PASS | Both loaded cleanly (`keys=11`) |
| 2. Checkpoint Integrity | Required keys in `best.pt` & `latest.pt` | PASS | All required keys + `audio_config` & `audio_cfg` aliases present |
| 2. Checkpoint Integrity | Exact logit reproduction (`atol=1e-5`) | PASS | `max_diff=0.000e+00`, identical `out_lengths` |
| 3. `resume_from` | New `checkpoint_dir`, `best_val_cer=0.001`, subsequent worse epochs | PASS | `ret_best=0.001`, `best.pt` (`epoch=2`, `best_val_cer=0.001`, `wdiff=0.000e+00` vs resumed), `latest.pt` (`epoch=4`, `best_val_cer=0.001`, `wdiff=1.862e-04`) |
| 3. `resume_from` | New `checkpoint_dir`, `best_val_cer=99.0`, subsequent better epoch | PASS | `ret_best=1.0`, `best.pt` updated (`epoch=4`, `wdiff=1.862e-04` vs resumed) |
| 3. `resume_from` | Same `checkpoint_dir`, epochs 2 -> 4 | PASS | `epochs=[1, 2, 3, 4]`, `best_val_cer` preserved |
| 3. `resume_from` | `train_cfg.epochs == ckpt["epoch"]` (same dir) | PASS | `len_hist=4`, `epochs_completed=4`, checkpoints intact |
| 3. `resume_from` | `train_cfg.epochs < ckpt["epoch"]` (new dir) | PASS | `len_hist=4`, `best.pt` & `latest.pt` written at `epoch=4` with preserved `best_val_cer` |
| 4. `load_checkpoint` Errors | Missing file | PASS | Raised `FileNotFoundError` |
| 4. `load_checkpoint` Errors | Directory path | PASS | Raised `ValueError` |
| 4. `load_checkpoint` Errors | Random bytes file | PASS | Raised `ValueError: Corrupt or invalid checkpoint ...` |
| 4. `load_checkpoint` Errors | 0-byte empty file | PASS | Raised `ValueError: Corrupt or invalid checkpoint ...` |
| 4. `load_checkpoint` Errors | Truncated valid `.pt` zip (5 cut points: `1, 4, 32, 50%, -10B`) | PASS | All 5 raised `ValueError` |
| 4. `load_checkpoint` Errors | Valid zip with corrupt inner `archive/data.pkl` | PASS | Raised `ValueError: Corrupt or invalid checkpoint ...` |
| 4. `load_checkpoint` Errors | Non-dict tensor `.pt` | PASS | Raised `ValueError` |
| 4. `load_checkpoint` Errors | Dict missing required keys | PASS | Raised `ValueError` |
| 5. CTC Edge Cases | `out_length < target_length` (`cnn_bigru`, `all_short` & `mixed`) | PASS | All weights & losses finite; no crash |
| 5. CTC Edge Cases | `out_length < target_length` (`conformer_lite`, `all_short` & `mixed`) | PASS | All weights & losses finite; no crash |

---

## Cleanup & Isolation Confirmation
- All temporary probe scripts and synthetic datasets were staged under `/tmp/teamwork_probe.M11g2F` and `/tmp/teamwork_probe.l8fzSG` and removed (`rm -rf`) immediately after execution.
- No files in the working tree were modified; only this `handoff.md` was written.
