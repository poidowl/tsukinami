# Explorer 1 Handoff — Acoustic Models (`subsampling.py`, `cnn_bigru.py`, `models/__init__.py`)

## 1. Codebase & Environment Inspection

- **Runtime (`.venv`)**: Python 3.11, `torch==2.15.0+cpu` (`torch.get_num_threads() == 2`), `numpy==2.4.6`.
- **Existing M1/M2/M4 interfaces**:
  - `asr/config.py`:
    - `AudioConfig(sample_rate=16000, n_fft=512, win_length=400, hop_length=160, n_mels=64, ...)`
    - `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=192, num_layers=2, dropout=0.1, num_heads=4, conv_kernel_size=15)` — validates `arch in ("cnn_bigru", "conformer_lite")`, `n_mels >= 1`, `hidden_size >= 1`, `num_layers >= 1`, `dropout in [0.0, 1.0)`, `conv_kernel_size` odd. Note: `ModelConfig` is mutable (not frozen) and does **not** require `hidden_size` to be even for `cnn_bigru`.
  - `asr/features.py`: `extract_log_mel` returns `(T, n_mels)` `float32`, with `T >= 1` even for very short audio (`< win_length` is zero-padded to 1 frame).
  - `asr/dataset.py`: `collate_asr_batch` returns `feats: float32[B, T_max, F]` (zero-padded), `feat_lengths: int64[B]`, `targets: int64[B, L_max]`, `target_lengths: int64[B]`, `texts: list[str]`.
  - `asr/tokenizer.py`: Default `Tokenizer("kana")` has `blank_id == 0`, `vocab_size == 86`.

---

## 2. Detailed Design: `asr/models/subsampling.py`

### `padding=1` vs `padding=0` Analysis (`kernel_size=3, stride=2`)

| Criterion | `padding=1` (Recommended) | `padding=0` |
|---|---|---|
| Per-layer length formula | `L_out = (L + 1) // 2` (for `L >= 1`) | `L_out = (L - 1) // 2` (requires `L >= 3`) |
| 2-layer `output_lengths(L)` | `(L + 3) // 4` (for `L >= 1`; `0` if `L == 0`) | `(L - 3) // 4` (requires `L >= 7`) |
| Short-input safety | **Safe for all `T >= 1`** (`T=1..4 -> 1`, `T=5 -> 2`). Matches `extract_log_mel` min 1 frame. | Crashes or returns `0` for `T <= 6` (`< 85 ms`). |
| Freq dim (`n_mels=64`) | `64 -> 32 -> 16` (works for any `n_mels >= 1`) | `64 -> 31 -> 15` (crashes for `n_mels < 7`) |
| Edge frame retention | Preserves boundary frames | Drops 3–6 boundary frames |
| Masking invariance | **Exact** (see 3-point masking below) | Requires masking too (otherwise garbage at `t >= L` still leaks into last valid frame) |

**Decision**: Use `kernel_size=3, stride=2, padding=1` for both `Conv2d` layers, with **no BatchNorm2d** (avoids cross-utterance batch-stat leakage in training mode).

### Exact Masking Invariance Proof (3-Point Masking)

To guarantee **both** forms of masking invariance:
1. **Padded-value invariance**: Perturbing `feats[i, L:, :]` (e.g., setting padded frames to random noise / `100.0`) produces bit-for-bit identical valid outputs `out[i, :L_out, :]`.
2. **Batch-length (`T_max`) invariance**: Running item `i` unpadded (`T = L`) vs padded in a batch (`T_max > L`) produces bit-for-bit identical valid outputs `out[i, :L_out, :]`.

Why single-point input masking alone is insufficient for (2):
- Even if `feats[i, L:, :]` is zeroed before `conv1`, `conv1` at `t1 = L1` can read valid frame `L - 1` (e.g., `L = 10, L1 = 5`, `conv1[5]` reads `[9, 10, 11]`) and also adds `conv1.bias`, producing a non-zero value at `t1 = L1`. Then `conv2` at `t2 = L2 - 1` reads `[2*(L2-1)-1, 2*(L2-1), L1]`, leaking `conv1[L1]` into the last valid frame of `conv2`!

**Solution — mask at 3 points in `Conv2dSubsampling.forward`**:
1. **Before `conv1`**: Zero `feats` where `t >= feat_lengths`.
2. **After `act1(conv1(x))`**: Compute `l1 = _conv_out_length(feat_lengths)` and zero `x` where `t1 >= l1`.
3. **After `act2(conv2(x))` and after `out_proj(x)`**: Compute `l2 = _conv_out_length(l1)` and zero `x` where `t2 >= l2` (since `out_proj` has bias, masking after `out_proj` keeps all padded frames strictly `0.0`).

With this 3-point mask, for every valid output index `t1 < l1` and `t2 < l2`, any kernel tap at `>= l` sees `0.0` — identical to `padding=1` zero-padding in the unpadded case.

### `Conv2dSubsampling` Class Specification

```python
def _conv_out_length(lengths: torch.Tensor) -> torch.Tensor:
    return torch.where(lengths > 0, (lengths + 1) // 2, torch.zeros_like(lengths))

def make_valid_mask(lengths: torch.Tensor, max_len: int) -> torch.Tensor:
    """Boolean mask (B, max_len): True for valid positions < lengths."""
    return torch.arange(max_len, device=lengths.device).unsqueeze(0) < lengths.unsqueeze(1)
```

- Class attribute: `subsampling_factor: int = 4`
- `__init__(self, in_features: int, out_features: int, conv_channels: int = 32, dropout: float = 0.0)`:
  - `self.in_features = in_features`, `self.out_features = out_features`, `self.conv_channels = conv_channels`
  - `self.conv1 = nn.Conv2d(1, conv_channels, kernel_size=3, stride=2, padding=1)`
  - `self.act1 = nn.ReLU()`
  - `self.conv2 = nn.Conv2d(conv_channels, conv_channels, kernel_size=3, stride=2, padding=1)`
  - `self.act2 = nn.ReLU()`
  - `freq_out = ((in_features + 1) // 2 + 1) // 2`
  - `self.out_proj = nn.Linear(conv_channels * freq_out, out_features)`
  - `self.dropout = nn.Dropout(dropout)`
- `output_lengths(self, feat_lengths: torch.Tensor) -> torch.Tensor`:
  - Returns `_conv_out_length(_conv_out_length(feat_lengths.to(torch.long)))`.
- `forward(self, feats: torch.Tensor, feat_lengths: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]`:
  - Validates `feats.ndim == 3`, `feats.size(0) >= 1`, `feats.size(1) >= 1`, `feats.size(2) == self.in_features`, `feat_lengths.ndim == 1`, `feat_lengths.size(0) == B`, `1 <= feat_lengths <= T`.
  - Applies 3-point masking -> `(B, T', out_features)` and `out_lengths: int64[B]`.
- Note: Export `make_valid_mask` (or `_make_valid_mask`) so `conformer.py` and `cnn_bigru.py` can reuse it cleanly.

---

## 3. Detailed Design: `asr/models/cnn_bigru.py`

### Architecture (`CNNBiGRUCTC`)
1. `self.subsampling = Conv2dSubsampling(in_features=cfg.n_mels, out_features=cfg.hidden_size, conv_channels=32, dropout=cfg.dropout)`
2. `gru_hidden = max(1, cfg.hidden_size // 2)` (per direction, so bidirectional output dim is `2 * gru_hidden`, equal to `cfg.hidden_size` for even `hidden_size` and safe for any `hidden_size >= 1`).
3. `self.gru = nn.GRU(input_size=cfg.hidden_size, hidden_size=gru_hidden, num_layers=cfg.num_layers, batch_first=True, bidirectional=True, dropout=cfg.dropout if cfg.num_layers > 1 else 0.0)`
   - Passing `0.0` when `num_layers == 1` prevents PyTorch's `UserWarning`.
4. `self.post_norm = nn.LayerNorm(2 * gru_hidden)`
5. `self.dropout = nn.Dropout(cfg.dropout)`
6. `self.classifier = nn.Linear(2 * gru_hidden, vocab_size)`

### Parameter Count Check (Default `ModelConfig`: `n_mels=64, hidden_size=192, num_layers=2, vocab_size=86`)
- `Conv2dSubsampling` (`conv_channels=32`): **108,064** params (`320 + 9,248 + 98,496`)
- `BiGRU` (`input=192, hidden=96/dir, layers=2, bidir=True`): **334,080** params
- `LayerNorm(192)` + `Linear(192, 86)`: `384 + 16,598` = **16,982** params
- **Total: 459,126 params (~0.46M)** — matches `PROJECT.md`'s `~0.5M params` target and trains ~3× faster on 2 vCPUs than `hidden=192/dir` (~1.25M params).

### Forward Pass & Metadata
- Class attribute: `subsampling_factor: int = 4`
- `output_frame_stride_ms(self, audio_cfg: AudioConfig) -> float`:
  `return float(self.subsampling_factor) * 1000.0 * float(audio_cfg.hop_length) / float(audio_cfg.sample_rate)` (`40.0` ms for 16 kHz / hop 160).
- `forward(self, feats: torch.Tensor, feat_lengths: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]`:
  1. `x, out_lengths = self.subsampling(feats, feat_lengths)` -> `x: (B, T', H)`, `t_sub = x.size(1)`
  2. `packed = pack_padded_sequence(x, out_lengths.cpu(), batch_first=True, enforce_sorted=False)`
  3. `packed_out, _ = self.gru(packed)`
  4. `out, _ = pad_packed_sequence(packed_out, batch_first=True, total_length=t_sub)`
     - Using `total_length=t_sub` guarantees `out.shape[1] == T'` even if `max(out_lengths) < T'`.
  5. `out = self.dropout(self.post_norm(out))`
  6. `logits = self.classifier(out)` -> `(B, T', vocab_size)`
  7. `log_probs = F.log_softmax(logits, dim=-1)`
  8. Return `(log_probs, out_lengths)`.
- Masking invariance check for `CNNBiGRUCTC`:
  - `Conv2dSubsampling` is strictly invariant on `[:, :out_lengths[i], :]`.
  - `pack_padded_sequence` reads ONLY `[:, :out_lengths[i], :]`.
  - `LayerNorm`, `Linear`, `log_softmax` are strictly frame-wise (independent across time `t`).
  - Therefore `CNNBiGRUCTC` has **exact masking invariance** on all valid frames `[:out_lengths[i]]`.

---

## 4. Detailed Design: `asr/models/__init__.py`

- Exports:
  ```python
  __all__ = [
      "Conv2dSubsampling",
      "CNNBiGRUCTC",
      "ConformerLiteCTC",
      "build_model",
  ]
  ```
- `build_model(cfg: ModelConfig, vocab_size: int) -> nn.Module`:
  - Validate `vocab_size`: must be `int` (not `bool`) and `>= 2` (blank + at least 1 token); otherwise raise `ValueError`.
  - Dispatch on `cfg.arch`:
    - `"cnn_bigru"` -> `CNNBiGRUCTC(cfg, vocab_size=vocab_size)`
    - `"conformer_lite"` -> `ConformerLiteCTC(cfg, vocab_size=vocab_size)`
    - anything else -> `raise ValueError(f"Unknown model architecture {cfg.arch!r}; expected one of ('cnn_bigru', 'conformer_lite')")`
  - Checking `cfg.arch` explicitly in `build_model` ensures `ValueError` is raised even if `cfg.arch` was mutated after `ModelConfig` construction or passed via a mock/namespace.

---

## 5. Implementation & Test Checklist for Builder

1. Implement `asr/models/subsampling.py` with `padding=1`, 3-point masking, `output_lengths()`, `make_valid_mask()`, and `subsampling_factor = 4`.
2. Implement `asr/models/cnn_bigru.py` with `CNNBiGRUCTC`, `gru_hidden = max(1, cfg.hidden_size // 2)`, `pack_padded_sequence(..., enforce_sorted=False)`, `pad_packed_sequence(..., total_length=t_sub)`, `subsampling_factor = 4`, and `output_frame_stride_ms(audio_cfg)`.
3. Implement `asr/models/__init__.py` with `build_model(cfg, vocab_size)` and exports.
4. In `tests/test_asr_models.py`, test:
   - Short inputs (`T = 1, 2, 4, 5, 7, 16`) for `Conv2dSubsampling` and `CNNBiGRUCTC`.
   - Both padded-value perturbation invariance AND unpadded-vs-padded `T_max` invariance (`eval()` mode, `atol=1e-5`).
   - Parameter count sanity (~0.46M for default `ModelConfig`).
   - `build_model` with `"cnn_bigru"`, `"conformer_lite"`, unknown arch (`ValueError`), and invalid `vocab_size` (`ValueError`).
   - `subsampling_factor == 4` and `output_frame_stride_ms(AudioConfig()) == 40.0`.
