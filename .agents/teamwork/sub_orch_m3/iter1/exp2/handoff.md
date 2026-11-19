# Explorer 2 Handoff — `asr/models/conformer.py` (`ConformerLiteCTC`)

## 1. Environment & Existing Codebase Findings

- **Runtime**: Python `3.11.2`, PyTorch `2.15.0+cpu` (`torch.get_num_threads() == 2`) in `.venv`.
- **`asr/config.py`**:
  - `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=192, num_layers=2, dropout=0.1, num_heads=4, conv_kernel_size=15)`
  - Already validates `arch in ("cnn_bigru", "conformer_lite")`, `conv_kernel_size >= 1` and odd (`% 2 == 1`), and `hidden_size % num_heads == 0` for `conformer_lite`.
  - `AudioConfig`: `sample_rate=16000`, `hop_length=160`, `n_mels=64` -> base frame stride = `10.0 ms`; with `subsampling_factor = 4`, output frame stride = `40.0 ms`.
- **`asr/dataset.py`**:
  - `collate_asr_batch` yields `feats: FloatTensor[B, T_max, F]` (zero-padded), `feat_lengths: LongTensor[B]`, `targets: LongTensor[B, L_max]`, `target_lengths: LongTensor[B]`, `texts: list[str]`.
- **`asr/tokenizer.py`**:
  - `blank_id == 0`, default `Tokenizer("kana").vocab_size == 86`.

---

## 2. Detailed Design for `asr/models/conformer.py`

### Public API & Contract
- Class: `ConformerLiteCTC(nn.Module)` (exported from `asr/models/conformer.py` and `asr/models/__init__.py`).
- Constructor: `ConformerLiteCTC(cfg: ModelConfig, vocab_size: int, *, ffn_expansion: int = 2, conv_channels: int = 32)`
  - Validate `vocab_size >= 2` (or `>= 1`), `cfg.hidden_size % cfg.num_heads == 0`.
  - Store `self.cfg = cfg`, `self.vocab_size = int(vocab_size)`, `self.n_mels = cfg.n_mels`, `self.d_model = cfg.hidden_size`.
- Class attribute: `subsampling_factor: int = 4`.
- Method:
  ```python
  def output_frame_stride_ms(self, audio_cfg: AudioConfig) -> float:
      return (audio_cfg.hop_length / audio_cfg.sample_rate) * 1000.0 * self.subsampling_factor
  ```
- Forward signature:
  ```python
  def forward(
      self,
      feats: torch.Tensor,         # (B, T, n_mels)
      feat_lengths: torch.Tensor,  # (B,)
  ) -> tuple[torch.Tensor, torch.Tensor]:
      # returns (log_probs: (B, T', vocab_size), out_lengths: (B,))
  ```
- Input validation in `forward`:
  - Require `feats.ndim == 3` and `feats.size(2) == self.n_mels`.
  - Require `feat_lengths.ndim == 1` and `feat_lengths.size(0) == feats.size(0)`.
  - Convert `feat_lengths = feat_lengths.to(device=feats.device, dtype=torch.long)`.
  - Raise `ValueError` if `(feat_lengths <= 0).any()` or `(feat_lengths > feats.size(1)).any()` (prevents all-True `key_padding_mask` rows which would produce NaNs in MHSA/CTC).

### Pipeline Overview
1. **`Conv2dSubsampling(n_mels=cfg.n_mels, out_dim=cfg.hidden_size, conv_channels=conv_channels)`** (from `asr/models/subsampling.py`):
   - Maps `(B, T, n_mels) -> (B, T', d_model)` and `feat_lengths -> out_lengths` (`4x` time reduction via two `Conv2d(k=3, s=2, p=1)` layers).
   - **CRITICAL masking requirement for `Conv2dSubsampling`**: Must zero-mask `t >= feat_lengths` BEFORE `conv1`, `t1 >= l1` AFTER `conv1` (where `l1 = (feat_lengths + 1) // 2`), and `t2 >= l2` AFTER `conv2` (`l2 = (l1 + 1) // 2`).
   - Verified experimentally: without intermediate masking in `Conv2dSubsampling`, mutating padded input frames `feats[b, L:, :] = 1e4` leaks `3332.1` error into the last valid subsampled frame due to the `k=3, s=2, p=1` receptive field and `conv1` bias. With 3-point masking, mutated-pad diff is **exact `0.0`**, and unpadded vs padded diff is `3.6e-7`.
   - Note: `Conv2dSubsampling` already ends with a linear projection to `out_dim = cfg.hidden_size` (matching `SCOPE.md`).
2. **`SinusoidalPositionalEncoding(d_model, max_len=1024)`**:
   - Registers `self.register_buffer("pe", ..., persistent=False)` so checkpoints stay compact and independent of inference utterance length.
   - Dynamically extends `self.pe` in `forward(x)` whenever `x.size(1) > self.pe.size(1)` (or device/dtype differs), allocating `max(T', self.pe.size(1) * 2)`.
   - Handles odd `d_model` cleanly (`pe[0, :, 1::2] = torch.cos(pos * div[: d_model // 2])`).
   - Apply `x = self.input_dropout(self.pos_enc(x))`, then zero-mask padded frames: `x = x.masked_fill(pad_mask.unsqueeze(-1), 0.0)`.
   - Construct `pad_mask = torch.arange(T', device=x.device).unsqueeze(0) >= out_lengths.unsqueeze(1)` (`shape (B, T')`, `bool`, `True` = padded).
3. **`nn.ModuleList([ConformerBlock(...) for _ in range(cfg.num_layers)])`**:
   Each `ConformerBlock` executes the Macaron Conformer sequence:
   1. **Half-step Macaron FFN 1**: `x = x + 0.5 * self.ffn1(x)`
      - `_FeedForwardModule`: `LayerNorm(d) -> Linear(d, ffn_expansion * d) -> SiLU() -> Dropout(p) -> Linear(ffn_expansion * d, d) -> Dropout(p)` (`ffn_expansion=2`).
   2. **Masked Multi-Head Self-Attention**:
      - `h = self.mha_norm(x)`
      - `attn_out, _ = self.mha(h, h, h, key_padding_mask=pad_mask, need_weights=False)` using `nn.MultiheadAttention(d_model, num_heads, dropout=dropout, batch_first=True)`
      - `x = x + self.mha_dropout(attn_out)`
      - Verified on PyTorch `2.15.0+cpu` with `-W always`: zero warnings, zero NaNs in both `train()` and `eval()`, and `0.0` valid-frame diff under mutated padding.
   3. **Depthwise Separable ConvModule (`_ConformerConvModule`)**:
      - `h = self.layer_norm(x).transpose(1, 2)` -> `(B, d, T')`
      - `h = F.glu(self.pointwise_conv1(h), dim=1)` (`Conv1d(d, 2*d, kernel_size=1)`) -> `(B, d, T')`
      - **Zero-mask BEFORE depthwise conv**: `h = h.masked_fill(pad_mask.unsqueeze(1), 0.0)` (essential because `pointwise_conv1` has a non-zero bias; otherwise `k=15` depthwise conv reads non-zero padded frames up to 7 frames past `out_lengths[b]`).
      - **Depthwise Conv1d**: `Conv1d(d, d, kernel_size=k, groups=d, padding=k // 2)` for odd `k`; for even `k` (defensive fallback if instantiated directly), use `F.pad(h, ((k - 1) // 2, k // 2))` with `padding=0` so output length is always exactly `T'`.
      - **Normalization — USE `nn.LayerNorm(d_model)` (NOT `BatchNorm1d`, NOT `GroupNorm`)**:
        - `h = self.norm(h.transpose(1, 2)).transpose(1, 2)`
        - **Experimental findings on PyTorch 2.15**:
          - `BatchNorm1d(192)` **crashes** with `ValueError: Expected more than 1 value per channel when training, got input size torch.Size([1, 192, 1])` on `(B=1, C, T'=1)` in `train()` mode, and breaks batch/padding invariance in `train()` mode.
          - `GroupNorm(G, C)` normalizes over `(C // G, T')` — experimentally verified that even with zero-masked padding, changing `T_max` shifts valid-frame outputs by **`0.692`** (breaks length/padding invariance!) and imposes `d_model % G == 0`.
          - `LayerNorm(d_model)` over the channel dim at each `(b, t)` works for any `B >= 1, T' >= 1, d_model >= 1`, has **exact `0.0`** padding/length leakage, and is a standard modern Conformer variant.
      - `h = self.activation(h)` (`nn.SiLU()`)
      - `h = self.dropout(self.pointwise_conv2(h)).transpose(1, 2)` (`Conv1d(d, d, kernel_size=1)`)
      - Re-mask padded positions: `h = h.masked_fill(pad_mask.unsqueeze(-1), 0.0)`
      - Residual: `x = x + h`
   4. **Half-step Macaron FFN 2**: `x = x + 0.5 * self.ffn2(x)`
   5. **Final LayerNorm + Re-mask**:
      - `x = self.final_norm(x)`
      - `x = x.masked_fill(pad_mask.unsqueeze(-1), 0.0)` (prevents `final_norm.bias` from leaking into padded frames of subsequent layers).
4. **CTC Output Head**:
   - `log_probs = F.log_softmax(self.out_proj(x), dim=-1)` where `self.out_proj = nn.Linear(d_model, vocab_size)`.
   - Return `(log_probs, out_lengths)`.

---

## 3. Parameter Count & CPU Performance Verification

For default `ModelConfig(arch="conformer_lite", n_mels=64, hidden_size=192, num_layers=2, num_heads=4, conv_kernel_size=15)` and `vocab_size=86` (default kana tokenizer):

| Configuration | Subsampling | Per Block | CTC Head | Total Params |
|---|---:|---:|---:|---:|
| **`ffn_expansion=2, conv_channels=32` (Recommended)** | 108,064 | 560,832 | 16,598 | **1,246,326 (~1.25M)** |
| `ffn_expansion=4, conv_channels=32` | 108,064 | 856,512 | 16,598 | 1,837,686 (~1.84M) |
| `ffn_expansion=2, conv_channels=64` | 234,368 | 560,832 | 16,598 | 1,372,630 (~1.37M) |

- Matches `PROJECT.md` target (`conformer_lite optional ~1.0M params`).
- Prototype benchmark on this 2-vCPU VM (`B=16, T'=38` ≈ 1.5 s utterances): **~63.5 ms** per forward+backward pass.
- Prototype verification results:
  - Mutated padded frames (`1e5`) valid-frame max abs diff: **`0.0`**
  - Unpadded (`B=1, T'=7`) vs padded (`B=2, T'=20`) valid-frame max abs diff: **`9.5e-7`**
  - `(B=1, T'=1)` in `train()` mode: passes cleanly, `nan=False`
  - Long sequence (`T'=1500 > max_len=64`): dynamic PE extends cleanly, `nan=False`
  - Gradient flow: 100% of parameters receive non-`None` gradients.

---

## 4. Recommended Unit Tests (`tests/test_asr_models.py` coverage for Conformer)

1. Shape & `log_softmax` validity (`exp().sum(-1) ≈ 1.0`, `out_lengths == subsampling.output_lengths(feat_lengths)`).
2. `subsampling_factor == 4` and `output_frame_stride_ms(AudioConfig()) == 40.0`.
3. **Masking invariance**: mutating `feats[b, L:, :]` by `±1e4` produces `atol=1e-6` identical valid `log_probs[b, :out_L]` in `eval()` mode (and `train()` with `dropout=0.0`).
4. **Length/batch invariance**: running an utterance alone `(1, L, F)` vs inside a padded batch `(2, T_max, F)` produces `atol=1e-5` identical valid `log_probs`.
5. **Edge cases**: `(B=1, T=1, F)` and `(B=1, T=4, F)` in `train()` mode (catches any `BatchNorm1d` regression); long utterance `T=4200` (`T'=1050 > 1024`) verifying dynamic sinusoidal PE extension.
6. **Gradient flow**: backward through `nn.CTCLoss` gives finite, non-`None` gradients on all parameters.
7. **Overfit sanity**: small synthetic batch drives CTC loss down >50%.
