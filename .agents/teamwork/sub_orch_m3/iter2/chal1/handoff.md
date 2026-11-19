# Milestone M3 Iteration 2 — Challenger 1 (`chal1`) Adversarial Report

## Verdict: **PASS**

All adversarial probes targeting M3 acoustic models (`Conv2dSubsampling`, `CNNBiGRUCTC`, `ConformerLiteCTC`, `build_model`) and model/trainer/checkpoint integration (`train_asr`, `load_checkpoint`) passed with zero failures.

---

## Scope Verified
- [`asr/models/__init__.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/__init__.py)
- [`asr/models/subsampling.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/subsampling.py)
- [`asr/models/cnn_bigru.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/cnn_bigru.py)
- [`asr/models/conformer.py`](file:///home/antigravity/poidowl/tsukinami/asr/models/conformer.py)
- [`asr/train.py`](file:///home/antigravity/poidowl/tsukinami/asr/train.py)

---

## Adversarial Probes Executed

All probes were staged in isolated temporary directories (`mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`), executed via `.venv/bin/python`, and removed (`rm -rf`) prior to reporting.

| # | Probe | Result | Details |
|---|---|---|---|
| 1 | Short inputs (`T=1..7`) & single-item batches (`B=1`, train & eval) | **PASS** | Verified both `cnn_bigru` and `conformer_lite` for every `T in 1..7` at `B=1` in both `train()` and `eval()` modes, plus mixed-length short batches (`lengths=[1, 7, 2, 6, 3, 5, 4]`). Output shapes `(B, (T+3)//4, V)`, `out_lengths`, `exp(log_probs).sum(-1) == 1.0` (`atol=1e-5`), and finite backward gradients on `B=1, T=1..7` all confirmed. |
| 2 | Dynamic PE extension (`T=5000`) & non-persistent buffer safety | **PASS** | Verified `T=5000` (`T'=1250 > max_len=1024`) on both `cnn_bigru` and `conformer_lite`. `SinusoidalPositionalEncoding` dynamically extended `pe` (`>= 1250`), remained non-persistent (`"pos_enc.pe" not in state_dict()`), preserved `state_dict` keys, and loaded cleanly into a fresh `max_len=1024` model. |
| 3 | Strict padding invariance (`±1e5`, `NaN`, `+Inf`, `-Inf` in padded tail) + unpadded `B=1` equivalence | **PASS** | Verified for both `cnn_bigru` and `conformer_lite` (`lengths=[17, 5, 33, 1, 12]`, `T_max=40`). Valid-frame `log_probs` matched unpadded `B=1` runs (`max_diff < 1e-5`) and were strictly invariant (`max_diff < 1e-6`, all finite) when padded tails were overwritten with `+1e5`, `-1e5`, `NaN`, `+Inf`, or `-Inf`. Also verified backward pass with `NaN`/`Inf` in padded tails produced finite gradients for every parameter. |
| 4 | Full-parameter CTC gradient flow with unsorted lengths | **PASS** | Ran `nn.CTCLoss(blank=0, reduction="mean", zero_infinity=True)` with unsorted `feat_lengths=[21, 61, 13, 49, 33]` on both `cnn_bigru` and `conformer_lite`. Confirmed `out_lengths == subsampling.output_lengths(feat_lengths)` and that **every** trainable parameter received a non-`None`, finite, non-zero gradient. |
| 5 | End-to-end `build_model` + `train_asr` + `load_checkpoint` + `resume_from` + `output_frame_stride_ms` | **PASS** | Trained both `cnn_bigru` and `conformer_lite` via `train_asr` (`use_spec_augment=True`, 2 epochs) on synthetic fast-kotoba manifests, loaded `best.pt` and `latest.pt` via `load_checkpoint`, verified all required keys (`model_state_dict`, `optimizer_state_dict`, `model_config`, `audio_config`, `audio_cfg`, `tokenizer`, `history`, `epoch`, `best_val_cer`), reconstructed models via `build_model`, verified exact validation loss/CER match with `history[-1]`, verified exact logit reproduction (`atol=1e-5`), verified `resume_from` to epoch 3 for both architectures, and verified `subsampling_factor == 4` and `output_frame_stride_ms(audio_cfg)` (`40.0 ms` default, `50.0 ms` custom `hop_length=200`). |
| 6 | Edge configs, input validation & `conformer_lite` deterministic SpecAugment | **PASS** | Verified odd `conv_kernel_size in (1, 3, 15, 31)` on `ConformerLiteCTC`, even `conv_kernel_size=4` directly on `ConformerBlock`, `num_layers=1` + odd `hidden_size=65` on `CNNBiGRUCTC`, `ValueError` validation on `Conv2dSubsampling` and `build_model`, and bit-for-bit identical history & weights across repeated `train_asr` runs with `use_spec_augment=True` on `conformer_lite`. |

---

## Hygiene Verification
- Working tree untouched (verified via `git status --short`).
- All temporary `/tmp/teamwork_probe.*` directories removed (`NO_TEMP_PROBES`).
