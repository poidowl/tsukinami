# Milestone M3 Secondary Reviewer (`rev2`) Handoff

## Verdict: **APPROVE**

All Milestone M3 deliverables (`asr/models/{__init__,subsampling,cnn_bigru,conformer}.py`, `asr/train.py`, `tests/test_asr_models.py`) meet `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `SCOPE.md` requirements with no blocking issues. Existing TTS files and out-of-scope modules remain untouched, and all 14 M3 unit tests pass.

---

## Detailed Review Findings

### 1. `asr/models/conformer.py`
- **Block Architecture (`ConformerBlock`)**: Correctly implements the Macaron Conformer sequence:
  1. Half-step Macaron FFN1 (`x + 0.5 * ffn1(x)` with Pre-LayerNorm, `2x` expansion, `SiLU`, dropout).
  2. Masked Multi-Head Self-Attention (`Pre-LayerNorm` -> `nn.MultiheadAttention(..., batch_first=True, key_padding_mask=pad_mask, need_weights=False)` -> dropout + residual). Since `Conv2dSubsampling` enforces `lengths >= 1`, every batch item has at least one unmasked key, preventing all-`-inf` softmax NaNs.
  3. Depthwise Separable `_ConformerConvModule`: `LayerNorm` -> 1×1 pointwise conv (`d_model -> 2*d_model`) -> `F.glu(..., dim=1)` -> pre-depthwise zero-masking at `pad_mask` -> depthwise conv (`groups=d_model`, supporting both odd and even `kernel_size` via `_asymmetric_pad`) -> frame-wise `LayerNorm(d_model)` (avoids `BatchNorm1d` `(B=1, T'=1)` failures and guarantees exact batch/padding invariance) -> `SiLU` -> 1×1 pointwise conv -> dropout -> output zero-masking.
  4. Half-step Macaron FFN2 (`x + 0.5 * ffn2(x)`).
  5. Final `LayerNorm` + output zero-masking at `pad_mask`.
- **Positional Encoding (`SinusoidalPositionalEncoding`)**: Registered as a non-persistent buffer (`persistent=False`) so checkpoint loading is resilient to dynamic length extension (`seq_len > 1024`), device, and dtype changes.
- **Interface & Metadata**: Exposes `subsampling_factor = 4`, `output_frame_stride_ms(audio_cfg) -> float`, validates `vocab_size >= 2` and `hidden_size % num_heads == 0`, and returns `(log_probs, out_lengths)` via `F.log_softmax(logits, dim=-1)`.

### 2. `asr/train.py`
- **CTC Loss & Optimization**: Uses `nn.CTCLoss(blank=tokenizer.blank_id, reduction="mean", zero_infinity=True)` with `log_probs.transpose(0, 1)`, `AdamW`, `CosineAnnealingLR` (resumable with `T_max = max(1, train_cfg.epochs)`), gradient clipping (`clip_grad_norm_`), and non-finite loss guard.
- **Determinism & CPU Efficiency**: Seeds `random`, `numpy`, `torch`, and `DataLoader` `Generator` via `train_cfg.seed`; caps threads with `torch.set_num_threads(min(2, os.cpu_count() or 1))`.
- **Validation CER**: `_evaluate_epoch` runs in `model.eval()` + `torch.no_grad()`, slices each utterance's `log_probs` to `out_lens[i]` before calling `asr.decoding.greedy_decode`, and computes CER via `asr.metrics.compute_cer`.
- **Checkpoint Schema & `load_checkpoint`**:
  - Atomically writes `best.pt` and `latest.pt` via `.tmp` + `os.replace`.
  - Contains all required keys: `model_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, `model_config`, `audio_config` (plus `audio_cfg` alias), `train_config`, `tokenizer`, `history`, `epoch`, `best_val_cer`.
  - Uses plain primitives/dicts + tensors so `torch.load(..., weights_only=True)` succeeds directly, with safe fallback to `weights_only=False` in `load_checkpoint`.
- **`resume_from` & Summary Dict**: Validates `model_config` and tokenizer vocab compatibility, restores model/optimizer/scheduler state, history, `best_val_cer`, and epoch numbering; returns `best_checkpoint`, `latest_checkpoint`, `best_val_cer`, `final_train_loss`, `final_val_loss`, `final_val_cer`, `epochs_completed`, and `history`.
- *Non-blocking note*: When resuming into a brand-new empty `checkpoint_dir` where `best.pt` does not exist, `or (not best_path.exists())` in `is_best` could update `best_val_cer` even if the new epoch's CER is worse than the resumed `best_val_cer`. Not an issue for normal same-directory resumes; no change required for M3.

### 3. Consistency Check (`subsampling.py`, `cnn_bigru.py`, `__init__.py`)
- `Conv2dSubsampling`: Exact `(L + 3) // 4` length formula for `L >= 1` (`0` for `L == 0`), 3-point zero-masking guarantees strict padding invariance, safely handles `T >= 1`.
- `CNNBiGRUCTC`: Uses `pack_padded_sequence(..., enforce_sorted=False)` and `pad_packed_sequence(..., total_length=t_sub)`, exposes identical `subsampling_factor = 4`, `output_frame_stride_ms`, and `forward` contract.
- `asr/models/__init__.py`: Clean `build_model` factory supporting `cnn_bigru` and `conformer_lite`, raising `ValueError` on unknown architectures or invalid `vocab_size`.

### 4. `tests/test_asr_models.py`
- Comprehensive 14-test suite covering subsampling lengths & short inputs, `build_model` factory/metadata/errors, forward shapes & valid `log_softmax` & `(B=1, T=1..4)` train-mode safety, dynamic PE extension (`T=4200`), strict padding mask invariance (mutated padding + unpadded-vs-padded batch), CTC gradient flow for both architectures, genuine CPU overfit sanity test (>50% CTC loss drop and CER drop `< 0.5`), `weights_only=True` checkpoint load & exact logit reproduction (`atol=1e-5`) & `resume_from`, and `conformer_lite` training smoke test.

---

## Verification Commands & Exact Outputs

### 1. M3 Target-Scoped Unit Tests
Command:
```bash
.venv/bin/pytest tests/test_asr_models.py -v
```
Output (exit code 0):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 14 items

tests/test_asr_models.py ..............                                  [100%]

============================= 14 passed in 56.65s ==============================
```

### 2. Git Status & Diff Check
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
Confirmed zero tracked TTS files modified.
