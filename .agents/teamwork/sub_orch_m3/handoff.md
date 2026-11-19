# Milestone M3 Completion Handoff (`sub_orch_m3`)

## Status: **DONE (GATE PASS — Iteration 2)**

Milestone M3 (Acoustic Models & Training Engine) has been implemented, adversarially hardened across 2 iterations, and unanimously verified by all 5 verification agents (2 Reviewers, 2 Challengers, 1 Forensic Auditor).

---

## Deliverables Created (Exclusive M3 Ownership)

1. **`/home/antigravity/poidowl/tsukinami/asr/models/subsampling.py`**
   - `Conv2dSubsampling` (4× time reduction via two `Conv2d(kernel_size=3, stride=2, padding=1)` layers, no BatchNorm2d) + `make_valid_mask`.
   - Exact `output_lengths(feat_lengths)` formula: `(L + 3) // 4` for `L >= 1` (`0` for `L == 0`), cleanly handling short inputs down to `T = 1`.
   - 3-point zero-masking (before `conv1`, after `conv1`, after `conv2`/`out_proj`) guaranteeing strict padding/length invariance (even with `±1e5` or `NaN`/`Inf` in padded tails).

2. **`/home/antigravity/poidowl/tsukinami/asr/models/cnn_bigru.py`**
   - `CNNBiGRUCTC`: `Conv2dSubsampling` + bidirectional `nn.GRU` using `pack_padded_sequence(..., enforce_sorted=False)` and `pad_packed_sequence(..., total_length=t_sub)` + `LayerNorm` + `Dropout` + `Linear` + `F.log_softmax(dim=-1)`.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float` (`40.0` ms for 16 kHz / hop 160).
   - Default `ModelConfig` (`n_mels=64, hidden_size=192, num_layers=2`, `vocab_size=86`): ~0.46M parameters.

3. **`/home/antigravity/poidowl/tsukinami/asr/models/conformer.py`**
   - `ConformerLiteCTC`, `ConformerBlock`, `SinusoidalPositionalEncoding` (non-persistent buffer with dynamic extension for arbitrarily long utterances).
   - Macaron Conformer block: half-step FFN + Masked MHSA (`key_padding_mask`) + Depthwise Separable ConvModule (pointwise -> GLU -> pre-depthwise zero-mask -> depthwise conv -> frame-wise `LayerNorm` -> SiLU -> pointwise -> dropout -> zero-mask) + half-step FFN + final `LayerNorm`.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float`.
   - Default `ModelConfig`: ~1.25M parameters, safe for `B=1, T=1` in both `train()` and `eval()` modes.

4. **`/home/antigravity/poidowl/tsukinami/asr/models/__init__.py`**
   - `build_model(cfg: ModelConfig, vocab_size: int) -> nn.Module` factory supporting `"cnn_bigru"` and `"conformer_lite"`, raising `ValueError` on unknown arch or invalid `vocab_size`.
   - Exports `Conv2dSubsampling`, `CNNBiGRUCTC`, `ConformerLiteCTC`, and `build_model`.

5. **`/home/antigravity/poidowl/tsukinami/asr/train.py`**
   - `train_asr(train_manifest, val_manifest, *, audio_cfg, model_cfg, train_cfg, tokenizer, resume_from=None) -> dict`:
     - Uses `nn.CTCLoss(blank=tokenizer.blank_id, reduction="mean", zero_infinity=True)`, `AdamW`, resumable `CosineAnnealingLR`, gradient clipping, deterministic seeding (including `_SeededSpecAugmentDataset` for deterministic SpecAugment under `use_spec_augment=True`), and CPU-friendly `torch.set_num_threads(min(2, os.cpu_count() or 1))`.
     - Validation loop computes weighted-average CTC loss and greedy CER using `asr.decoding.greedy_decode` (properly sliced to `out_lengths[i]`) and `asr.metrics.compute_cer`.
     - Atomically saves `best.pt` and `latest.pt` under `train_cfg.checkpoint_dir` using tensors + plain dicts/primitives (compatible with `torch.load(..., weights_only=True)`), containing `model_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, `model_config`, `audio_config` (plus `audio_cfg` alias), `train_config`, `tokenizer`, `history`, `epoch`, `best_val_cer`.
     - Full `resume_from` support (validates compatibility, preserves `best_val_cer` and `best.pt` even when resuming into a new `checkpoint_dir`, and handles `train_cfg.epochs <= ckpt["epoch"]` gracefully).
     - Returns summary dict with `best_checkpoint`, `latest_checkpoint`, `best_val_cer`, `final_train_loss`, `final_val_loss`, `final_val_cer`, `epochs_completed`, `history`.
   - `load_checkpoint(path: str | Path, device: str = "cpu") -> dict`: safely loads `.pt` checkpoints on CPU (`weights_only=True` with fallback), raising `FileNotFoundError` for missing files and clean `ValueError` for directories, corrupt/empty files, or invalid payloads.

6. **`/home/antigravity/poidowl/tsukinami/tests/test_asr_models.py`**
   - 17 comprehensive unit tests covering subsampling lengths & short inputs, `build_model` factory & metadata, forward shapes & log-prob normalization, dynamic PE extension (`T=4200`), strict padding mask invariance, full-parameter CTC gradient flow for both architectures, mandatory CPU overfit sanity test (>50% CTC loss reduction & greedy CER drop), checkpoint `weights_only=True` save/load exact logit reproduction (`atol=1e-5`) & `resume_from`, `conformer_lite` training smoke test, deterministic SpecAugment, resume-into-new-dir `best_val_cer` preservation, and corrupt/empty checkpoint handling.

---

## Verification Summary (Iteration 2 Gate: PASS)

- **Forensic Auditor (`iter2/aud1/handoff.md`)**: **CLEAN** — `17/17` M3 tests passed (`28.29s`), zero out-of-scope edits (`git diff --stat` empty), all implementations and tests verified genuine.
- **Primary Reviewer (`iter2/rev1/handoff.md`)**: **APPROVE** — Full M1–M4 unit test suite (`.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py -v`): **119 passed in 83.52s**.
- **Secondary Reviewer (`iter2/rev2/handoff.md`)**: **APPROVE** — Target-scoped M3 suite (`.venv/bin/pytest tests/test_asr_models.py -v`): **17 passed in 28.27s**.
- **Challenger 1 (`iter2/chal1/handoff.md`)**: **PASS** — Short inputs (`T=1..7`), `B=1` train/eval, `T=5000` dynamic PE, strict masking invariance (`±1e5`, `NaN`/`Inf`), full-parameter CTC gradient flow, and end-to-end model/trainer integration all passed.
- **Challenger 2 (`iter2/chal2/handoff.md`)**: **PASS** — **27/27** adversarial training/checkpoint probes passed (determinism with `use_spec_augment=True` & `False`, `resume_from` into new & same dirs, corrupt/empty/truncated checkpoint errors, CTC `out_length < target_length` edge cases).
