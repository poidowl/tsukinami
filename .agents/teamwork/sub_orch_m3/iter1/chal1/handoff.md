# Milestone M3 Challenger 1 (`chal1`) Adversarial Report

**Verdict: PASS**

## Scope Reviewed
Adversarial verification of the M3 acoustic model implementation:
- `asr/models/subsampling.py` (`Conv2dSubsampling`, `make_valid_mask`)
- `asr/models/cnn_bigru.py` (`CNNBiGRUCTC`)
- `asr/models/conformer.py` (`ConformerLiteCTC`, `ConformerBlock`, `SinusoidalPositionalEncoding`, `_FeedForwardModule`, `_ConformerConvModule`)
- `asr/models/__init__.py` (`build_model`, exports)

All probes were executed in isolated temporary directories (`mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`) using `PYTHONPATH=. .venv/bin/python` and removed immediately after execution. The working tree was not modified.

---

## Adversarial Probe Results

### 1. Short Inputs (`T = 1..7`) & Single-Item Batches (`B = 1`)
- Tested `T in {1, 2, 3, 4, 5, 6, 7}` with `B = 1` in **both** `train()` and `eval()` modes for both `cnn_bigru` and `conformer_lite`.
- **Result: PASS** — Output shapes strictly matched `(1, (T + 3) // 4, vocab_size)`, `out_lengths == [(T + 3) // 4]`, all `log_probs` finite, and `log_probs.exp().sum(dim=-1)` matched `1.0` within `atol=1e-5`. No BatchNorm/GroupNorm single-frame crashes.

### 2. Long Sequences (`T = 5000`, `T' = 1250 > 1024`) & Dynamic PE Extension
- Tested `conformer_lite` on `T = 5000` (`T' = 1250`).
- **Result: PASS** — `pos_enc.pe` dynamically extended from `1024` to `2048`, output shape `(1, 1250, 40)` was finite with valid `log_softmax` probabilities, `"pos_enc.pe"` is non-persistent (absent from `state_dict()`), and loading `state_dict()` into a fresh model (`strict=True`) succeeded with `0.0` max diff.

### 3. Strict Masking Invariance (Huge Values, `NaN`/`Inf`, Unpadded vs Padded)
- Tested across `L in {1, 2, 3, 4, 13, 14, 15, 16}` (covering all `L % 4` residues) with `pad_extra = 25` in `eval()` mode for both `cnn_bigru` and `conformer_lite`:
  - Mutating padded positions with `+1e5` / `-1e5`: valid frame outputs matched baseline (`max_diff <= 1e-6`).
  - Mutating padded positions with `NaN`, `+Inf`, `-Inf`: valid frame outputs remained strictly finite and matched baseline (`max_diff <= 1e-6`).
  - Forward + `nn.CTCLoss` backward pass with `NaN` in padded positions of `feats`: loss and **every** model parameter gradient remained finite (`bad_params=[]`) for both architectures.
  - Comparing unpadded batch `(B=1, T=L)` vs padded batch `(B=2, T=L+25)` in `eval()` mode: valid frame outputs matched closely (`max_diff <= 1e-5`).
  - Additional subtle probes: batches where **all** sequences are shorter than `T_max` (`lengths=[10, 21]` in `T=40` with `NaN` and `1e6` tails), single-item batches with trailing padding, and large depthwise kernel (`conv_kernel_size=31`) on `T=1` padded to `T=60` all matched unpadded baselines within `4.77e-7`.

### 4. Gradient Flow (Varying Unsorted Lengths)
- Ran `nn.CTCLoss(blank=0, reduction="mean", zero_infinity=True)` backward pass on batch `B=3` with unsorted varying lengths `[21, 45, 33]` in `train()` mode (`dropout=0.1`).
- **Result: PASS**:
  - `cnn_bigru`: all `26/26` trainable parameter tensors received non-`None`, finite, non-zero gradients (`loss=9.0053`).
  - `conformer_lite`: all `68/68` trainable parameter tensors received non-`None`, finite, non-zero gradients (`loss=7.5927`).

### 5. Error Handling & Interface Contracts
- Unknown `arch` raises `ValueError` in both `ModelConfig` and `build_model` (even with a non-`ModelConfig` duck-typed object).
- Invalid `vocab_size` (`0`, `1`, `-5`, `True`, `False`, `3.5`, `"10"`) all raise `ValueError`.
- Out-of-bounds / malformed inputs (`length == 0`, `length < 0`, `length > T`, 2D `feat_lengths`, mismatched batch size, 2D `feats`, mismatched `n_mels`, `T == 0`) all raise `ValueError` for both architectures.
- `model.subsampling_factor == 4` and `output_frame_stride_ms(audio_cfg)` verified for default `AudioConfig` (`40.0` ms) and custom `AudioConfig`s (`8000 Hz / hop 100 -> 50.0 ms`, `22050 Hz / hop 256 -> 46.4399... ms`).
- Additional boundary checks passed: odd `hidden_size` (`1, 3, 17`) in `cnn_bigru`, odd `d_model` (`1, 3, 5`) with `num_heads=1` in `conformer_lite`, `n_mels in {1, 2, 3, 4, 80}`, `int32` `feat_lengths` producing `int64` `out_lengths`, `float64 -> float32` PE roundtrip, `Conv2dSubsampling.output_lengths` exact formula (`0 -> 0`, `1..4 -> 1`, ..., `5000 -> 1250`), and `train()`/`eval()` exact equivalence when `dropout=0.0`.

---

## Conclusion
No bugs, masking leaks, numerical instabilities, or contract violations were found in `asr/models/{__init__,subsampling,cnn_bigru,conformer}.py`. Verdict: **PASS**.
