# Milestone M3 Forensic Audit Report (`aud1`)

## Verdict
**CLEAN**

---

## 1. Scope & Diff Integrity

- Verified via `git status --short` and `git diff --stat` in `/home/antigravity/poidowl/tsukinami`:
  - `git diff --stat` returned empty: **zero** tracked existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) were modified.
  - `git status --short` showed only untracked project files (`asr/`, `tests/`, `tests_e2e/`, `PROJECT.md`, `pyproject.toml`, `.gitignore`, `.agents/`, `TEST_INFRA.md`, `TEST_READY.md`).
  - Only the 6 assigned M3 deliverables exist in the M3 sub-scope:
    - `asr/models/__init__.py`
    - `asr/models/subsampling.py`
    - `asr/models/cnn_bigru.py`
    - `asr/models/conformer.py`
    - `asr/train.py`
    - `tests/test_asr_models.py`
  - No out-of-scope M1/M2/M4 files or `tests_e2e/` files were modified or tampered with.

---

## 2. Anti-Cheating & Genuine Implementation Audit

Every line of all 6 M3 files was inspected:

1. **`asr/models/__init__.py`** (37 lines):
   - Genuine `build_model(cfg: ModelConfig, vocab_size: int) -> nn.Module` factory supporting `"cnn_bigru"` (`CNNBiGRUCTC`) and `"conformer_lite"` (`ConformerLiteCTC`).
   - Validates `vocab_size` (rejects `bool`, non-int, `< 2`) and raises `ValueError` on unknown architectures.
   - Cleanly exports `Conv2dSubsampling`, `CNNBiGRUCTC`, `ConformerLiteCTC`, and `build_model`.

2. **`asr/models/subsampling.py`** (130 lines):
   - Genuine two-layer stride-2 `nn.Conv2d(..., kernel_size=3, stride=2, padding=1)` + `nn.ReLU` + `nn.Linear` + `nn.Dropout`.
   - Exact `output_lengths(feat_lengths)` calculation (`(L + 3) // 4` for `L >= 1`, `0` for `L == 0`) handling inputs down to `T = 1`.
   - Strict 3-point zero-masking (before `conv1`, after `conv1`, after `conv2`, and after `out_proj`) prevents padding leakage.

3. **`asr/models/cnn_bigru.py`** (94 lines):
   - Genuine `Conv2dSubsampling` + bidirectional `nn.GRU` with `pack_padded_sequence(..., enforce_sorted=False)` and `pad_packed_sequence(..., total_length=t_sub)` + `nn.LayerNorm` + `nn.Dropout` + `nn.Linear` + `F.log_softmax(logits, dim=-1)`.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float`.

4. **`asr/models/conformer.py`** (270 lines):
   - Genuine `SinusoidalPositionalEncoding` (non-persistent buffer with dynamic length extension).
   - Genuine `ConformerBlock` implementing half-step Macaron `_FeedForwardModule` (pre-LN, `Linear`, `SiLU`, `Dropout`, `Linear`, `Dropout`), `nn.MultiheadAttention(..., batch_first=True)` with `key_padding_mask=pad_mask`, `_ConformerConvModule` (pre-LN, pointwise `Conv1d(D, 2D, 1)` -> `F.glu` -> pre-depthwise zero-mask -> depthwise `Conv1d(D, D, K, groups=D)` -> frame-wise `LayerNorm(D)` -> `SiLU` -> pointwise `Conv1d(D, D, 1)` -> `Dropout` -> zero-mask), second half-step Macaron FFN, and final `LayerNorm` + zero-mask.
   - Output `nn.Linear` + `F.log_softmax(logits, dim=-1)`, `subsampling_factor = 4`, and `output_frame_stride_ms(audio_cfg) -> float`.

5. **`asr/train.py`** (380 lines):
   - Genuine PyTorch training engine using `ASRManifestDataset` + `DataLoader` (`augment=train_cfg.use_spec_augment` for train, `augment=False` for val), `nn.CTCLoss(blank=tokenizer.blank_id, reduction="mean", zero_infinity=True)`, `torch.optim.AdamW`, and `CosineAnnealingLR`.
   - Real optimization steps: `optimizer.zero_grad(set_to_none=True)`, `loss.backward()`, `clip_grad_norm_`, `optimizer.step()`, `scheduler.step()`.
   - Real per-epoch validation under `model.eval()` and `torch.no_grad()` computing CTC loss and greedy CER via `asr.decoding.greedy_decode` (sliced to valid `out_lengths[i]`) and `asr.metrics.compute_cer`.
   - Atomic checkpoint writes (`best.pt`, `latest.pt`) compatible with `torch.load(..., weights_only=True)` and full `resume_from` state restoration and compatibility checks.
   - Zero hardcoded predictions, zero dummy/stub layers, zero synthetic/fake loss decay, zero validation leakage into training.

6. **`tests/test_asr_models.py`** (448 lines):
   - 14 genuine unit tests with meaningful assertions (no skipped, weakened, or tautological tests):
     - `Conv2dSubsampling` length math and short-input safety (`T=1..16`).
     - `build_model` factory, parameter count bounds, `subsampling_factor`, `output_frame_stride_ms`, and validation errors.
     - Forward shapes, valid `log_softmax` probability normalization (`exp().sum(-1) == 1`), and `(B=1, T=1..4)` train-mode safety for both architectures.
     - Dynamic positional encoding extension (`T=4200 -> T'=1050 > 1024`).
     - Strict padding mask invariance (both mutated padding and single-vs-padded batch) for both architectures.
     - End-to-end CTC gradient flow verifying non-None, finite, non-zero gradients across all trainable parameters for both architectures.
     - Genuine CPU overfit sanity test (60 epochs on 4 synthetic Japanese utterances) verifying `>50%` CTC loss drop and greedy CER `< 0.5` and `< initial_cer`.
     - Checkpoint `weights_only=True` loading, required keys, exact logit reproduction (`atol=1e-5`), and `resume_from` continuity.
     - `conformer_lite` training loop smoke test.

---

## 3. Independent Target-Scoped Test Execution

Command:
```bash
.venv/bin/pytest tests/test_asr_models.py -v
```

Exact verbatim output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 14 items

tests/test_asr_models.py ..............                                  [100%]

============================= 14 passed in 52.89s ==============================
```

---

## 4. Conclusion

All M3 deliverables (`asr/models/{__init__,subsampling,cnn_bigru,conformer}.py`, `asr/train.py`, `tests/test_asr_models.py`) are genuinely implemented, strictly scoped, free of any cheating or integrity violations, and pass all 14 unit tests independently.

**Final Verdict: CLEAN**
