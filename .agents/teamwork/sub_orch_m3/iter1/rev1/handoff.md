# Milestone M3 Primary Review (`rev1`) Handoff

## Verdict
**APPROVE**

## Summary
All 6 Milestone M3 deliverables (`asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, `asr/models/conformer.py`, `asr/train.py`, and `tests/test_asr_models.py`) were independently inspected and verified against `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `SCOPE.md`. The implementation is clean, mathematically sound, adheres strictly to all interface contracts and exclusive file ownership, and passes the full M1–M4 unit test suite (116/116 passed).

---

## Detailed Inspection Checklist

1. **Exclusive File Ownership & Repo Hygiene**
   - `git status --short` and `git diff --stat` confirm zero modifications to any tracked existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `index.html`, etc.).
   - Directory listing and timestamps confirm no edits to M1/M2/M4 source or test files; only the 6 assigned M3 files were added.

2. **`asr/models/subsampling.py` (`Conv2dSubsampling`, `make_valid_mask`)**
   - Two-layer `Conv2d(kernel_size=3, stride=2, padding=1)` without `BatchNorm2d`, `subsampling_factor = 4`.
   - Exact `output_lengths(feat_lengths)` computing `(L + 3) // 4` for `L >= 1` (`0` for `L == 0`), handling short inputs down to `T = 1`.
   - 3-point zero-masking (before `conv1`, after `conv1`, and after `conv2`/`out_proj`) guarantees exact padding/length invariance between padded batches and unpadded single utterances.
   - Thorough input shape/dtype/bounds validation.

3. **`asr/models/cnn_bigru.py` (`CNNBiGRUCTC`)**
   - `Conv2dSubsampling` + bidirectional `nn.GRU` with `pack_padded_sequence(..., enforce_sorted=False)` and `pad_packed_sequence(..., total_length=t_sub)` + `LayerNorm` + `Dropout` + `Linear` + `F.log_softmax(..., dim=-1)`.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float` (`40.0` ms for 160-sample hop @ 16 kHz).
   - Matches `forward(feats: Tensor[B, T, F], feat_lengths: Tensor[B]) -> tuple[Tensor[B, T', V], Tensor[B]]`.

4. **`asr/models/conformer.py` (`ConformerLiteCTC`, `ConformerBlock`, `SinusoidalPositionalEncoding`)**
   - `Conv2dSubsampling` + non-persistent dynamically-extensible `SinusoidalPositionalEncoding` + Macaron Conformer blocks (`FFN/2 -> Masked MHSA (key_padding_mask=pad_mask) -> Depthwise Separable ConvModule -> FFN/2 -> Final LayerNorm`) + `out_proj` + `F.log_softmax(..., dim=-1)`.
   - `_ConformerConvModule` masks padded frames prior to depthwise conv and uses frame-wise `LayerNorm(d_model)`, ensuring strict padding invariance and safe `(B=1, T'=1)` training without BatchNorm1d crashes.
   - Exposes `subsampling_factor = 4` and `output_frame_stride_ms(audio_cfg) -> float`.

5. **`asr/models/__init__.py` (`build_model`)**
   - Supports `"cnn_bigru"` and `"conformer_lite"`, raises `ValueError` on unknown architecture or invalid `vocab_size < 2` (including `bool`).
   - Exports `Conv2dSubsampling`, `CNNBiGRUCTC`, `ConformerLiteCTC`, and `build_model`.

6. **`asr/train.py` (`train_asr`, `load_checkpoint`)**
   - Uses `nn.CTCLoss(blank=tokenizer.blank_id, reduction="mean", zero_infinity=True)`, `AdamW`, resumable `CosineAnnealingLR`, gradient clipping, deterministic seeding, and CPU-friendly `torch.set_num_threads(min(2, os.cpu_count() or 1))`.
   - Validation loop properly slices `log_probs` to `out_lengths[i]` before `asr.decoding.greedy_decode` and computes CER via `asr.metrics.compute_cer`.
   - Atomically writes `best.pt` and `latest.pt` compatible with `torch.load(..., weights_only=True)` (with safe fallback in `load_checkpoint`), storing both `audio_config` and `audio_cfg` aliases alongside `model_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, `model_config`, `train_config`, `tokenizer`, `history`, `epoch`, and `best_val_cer`.
   - `resume_from` validates model/tokenizer compatibility and cleanly restores model, optimizer, scheduler, history, `best_val_cer`, and epoch numbering.

7. **`tests/test_asr_models.py`**
   - 14 comprehensive unit tests covering subsampling lengths & short inputs, `build_model` factory & error cases, shapes/log-probs/`(B=1, T=1..4)` train-mode safety, dynamic PE extension (`T=4200`), strict padding mask invariance (mutated padding + unpadded vs padded batch), CTC gradient flow for both architectures, CPU overfit sanity test (>50% CTC loss drop and CER improvement), checkpoint `weights_only=True` & exact logit reproduction (`atol=1e-5`) & `resume_from`, and `conformer_lite` training smoke test.

---

## Verification Commands & Exact Outputs

### 1. Git Status & Diff Check
Command:
```bash
git status --short && git diff --stat
```
Output:
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
(Exit code 0; empty `git diff --stat` confirms zero edits to tracked TTS files.)

### 2. Full M1–M4 Unit Test Suite
Command:
```bash
.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py -v
```
Output:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 116 items

tests/test_asr_dsp.py .............................................      [ 38%]
tests/test_asr_data.py ...................                               [ 55%]
tests/test_asr_decoding.py ......................................        [ 87%]
tests/test_asr_models.py ..............                                  [100%]

======================== 116 passed in 98.95s (0:01:38) ========================
```
(Exit code 0; all 116 tests passed.)
