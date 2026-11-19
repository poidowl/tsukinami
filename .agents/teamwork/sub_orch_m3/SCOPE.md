# Milestone M3 Scope: Acoustic Models & Training Engine

## Deliverables (Exclusive File Ownership)
1. **`asr/models/__init__.py`**
   - `build_model(cfg: ModelConfig, vocab_size: int) -> nn.Module` factory supporting `cnn_bigru` and `conformer_lite`; raises `ValueError` on unknown architecture.
   - Export model classes (`Conv2dSubsampling`, `CNNBiGRUCTC`, `ConformerLiteCTC` or cleanly named classes) and `build_model`.

2. **`asr/models/subsampling.py`**
   - `Conv2dSubsampling` with 4× time reduction (two 2D convolutions with stride=2, e.g., kernel_size=3, stride=2, padding=1 or standard conv formula — must have exact `output_lengths(feat_lengths)` calculation).
   - Handles short inputs cleanly without crashing or producing invalid shapes/zero lengths when input is reasonably sized (or clearly documents/enforces minimum frames).
   - Projects `(B, T, n_mels)` -> `(B, T', out_dim)`.

3. **`asr/models/cnn_bigru.py`**
   - `Conv2dSubsampling` + BiGRU (using `pack_padded_sequence` / `pad_packed_sequence` for proper length masking!) + Linear + `log_softmax(dim=-1)`.
   - Forward signature: `forward(feats: Tensor[B, T, F], feat_lengths: Tensor[B]) -> tuple[Tensor[B, T', V], Tensor[B]]`.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float` (`40.0` ms for 10 ms hop).

4. **`asr/models/conformer.py`**
   - `Conformer-Lite-CTC`: `Conv2dSubsampling` + linear projection + positional encoding + Conformer blocks:
     - half-step Macaron FFN
     - Masked Multi-Head Self-Attention with key padding mask
     - Depthwise Separable ConvModule (pointwise -> GLU -> depthwise conv with mask/zero-padding -> BatchNorm/GroupNorm -> Swish -> pointwise -> dropout)
     - half-step Macaron FFN
     - Final LayerNorm
   - Output Linear + `log_softmax(dim=-1)`.
   - Forward signature: `forward(feats: Tensor[B, T, F], feat_lengths: Tensor[B]) -> tuple[Tensor[B, T', V], Tensor[B]]`.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float`.

5. **`asr/train.py`**
   - `train_asr(train_manifest, val_manifest, *, audio_cfg, model_cfg, train_cfg, tokenizer, resume_from=None) -> dict`
   - Uses `nn.CTCLoss(blank=tokenizer.blank_id, zero_infinity=True)`, `AdamW`, cosine/OneCycle LR schedule, gradient clipping, deterministic seeding, validation loss & CER tracking per epoch (using `asr.decoding.greedy_decode` and `asr.metrics.compute_cer`).
   - Saves `best.pt` and `latest.pt` under `train_cfg.checkpoint_dir` containing:
     `model_state_dict`, `optimizer_state_dict`, `model_config`, `audio_config`, `tokenizer`, `history`, `epoch`, `best_val_cer` (also consider checkpoint compatibility with PROJECT.md naming: note prompt explicitly lists `audio_config` while PROJECT.md line 166 says `audio_cfg` — check what explorers recommend or store `audio_config` as primary and ensure consistency).
   - Supports `resume_from` (loads model & optimizer state, continues epoch numbering, preserves history & `best_val_cer`).
   - Returns summary metrics dict including `best_checkpoint`, `latest_checkpoint`, `best_val_cer`, `final_train_loss`, `history`.
   - `load_checkpoint(path: str | Path, device: str = "cpu") -> dict` — safely loads `.pt` checkpoint on CPU (`weights_only=False` if needed for dicts/metadata or clean serialization).
   - CPU-threading friendly for 2 vCPUs (`torch.set_num_threads` or lean defaults) and fast convergence on CPU.

6. **`tests/test_asr_models.py`**
   - Thorough unit tests run via `.venv/bin/pytest tests/test_asr_models.py`:
     - Shape, masking (changing padded region does not affect valid outputs), and gradient flow checks for BOTH `cnn_bigru` and `conformer_lite`.
     - `build_model` factory test including `ValueError` on unknown arch.
     - `subsampling_factor == 4` and `output_frame_stride_ms(audio_cfg)` checks.
     - Mandatory overfit sanity test: training on a small synthetic batch drives CTC loss down >50% and greedy CER significantly down (proving genuine gradient learning).
     - Checkpoint save/load exact logit reproduction (`atol=1e-5`) and `resume_from` test.
   - Primary reviewer runs `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py -v`.
