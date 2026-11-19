# Explorer 2 Handoff — Tier 3 Cross-Feature Contract Audit (First Half: Tests 1–7)

## Scope & Methodology
- **Read-Only Audit**: Inspected the first 7 of 12 tests in `tests_e2e/test_tier3_combinations.py` (DSP, corruption, VAD, fast/tsukinami synthesis, kana/phoneme tokenizers, dataset/collate/SpecAugment, and `cnn_bigru` / `conformer_lite` training/checkpoint/resume) and cross-checked every asserted contract against the actual `asr/` implementations:
  - `asr/config.py`
  - `asr/audio.py`
  - `asr/features.py`
  - `asr/tokenizer.py` (cross-checked with `kotoba.py`)
  - `asr/synth_data.py`
  - `asr/dataset.py`
  - `asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, `asr/models/conformer.py`
  - `asr/train.py`
- **No repository files were modified**, and `pytest` was not run on `tests_e2e/` (per read-only & concurrency rules).

---

## Executive Verdict
- **Zero blocking Tier 3 defects found** across Tests 1–7. Every public interface contract, dtype/shape/finiteness invariant, caching guarantee, serialization round-trip, and checkpoint/resume requirement asserted by Tests 1–7 is satisfied by the current `asr/` implementation.
- **3 non-blocking, low-severity hardening notes** were identified in `asr/train.py` around checkpoint resume edge cases (LR discontinuity when extending `T_max`, partial tokenizer/audio_cfg validation on resume, and SpecAugment RNG reset on resume), plus 1 minor concurrency note on `_atomic_torch_save`. None of these cause Tier 3 failures; concrete optional fixes are documented below if hardening is desired in Tier 5.

---

## Per-Test Contract Cross-Check (Tests 1–7)

| # | Test (`tests_e2e/test_tier3_combinations.py`) | Features | Implementation Verified | Verdict |
|---:|---|---|---|---|
| 1 | `test_t3_corruption_noise_features_and_vad` (`L19–42`) | F2, F3, F4, F5, F7 | `synthesize_fast_kotoba` handles Hiragana (`"おはよう"`) via `kotoba.split_moras` (`to_kata` internally); `apply_corruption` (`snr_db=10.0`, `"white"`/`"pink"`, `seed=7`) uses local `np.random.default_rng(seed)` and preserves sample length; `extract_log_mel` & `extract_mfcc(..., n_mfcc=13, include_deltas=True)` return finite `float32` `(T, 64)` and `(T, 39)`; `detect_vad` clamps `end_sec <= duration` and guarantees `0.0 <= s < e <= dur`. | **PASS expected** |
| 2 | `test_t3_corruption_speed_bandlimit_gain_features` (`L45–73`) | F3, F5, F7 | `apply_corruption(..., speed=1.25)` / `speed=0.8` uses `_resample_to_length` to `round(N / speed)`, guaranteeing `T_fast < T_clean < T_slow`; `band_limit=(300.0, 3400.0)` zeros spectrum above `3450.0` Hz (raised-cosine taper `trans=50.0`), strongly attenuating top 10 mel bins (`-10:`) vs clean; `gain_db=-6.0` scales amplitude by `~0.501` (`rms_quiet < 0.7 * rms_clean`); `cmvn=True` normalizes each mel bin to mean `~0` (`< 0.2`) and std `~1` (`in (0.5, 1.5)`). | **PASS expected** |
| 3 | `test_t3_fast_kotoba_kana_tokenizer_dataset_collate_specaug` (`L76–130`) | F2, F3, F5, F6, F7, F9 | `save_wav` writes 16-bit mono PCM; `ASRManifestDataset` loads WAVs at `16000` Hz, extracts `(T, 64)` Log-Mel, optionally applies `spec_augment`; `collate_asr_batch` returns `feats: [4, T_max, 64]`, `feat_lengths`, `targets: [4, L_max]`, `target_lengths: (4,)`, `texts` (len 4); all encoded target IDs are `!= blank_id (0)`; `spec_augment(..., seed=42)` copies input and applies non-trivial masking (`not np.array_equal`). | **PASS expected** |
| 4 | `test_t3_fast_kotoba_phoneme_tokenizer_dataset_collate` (`L133–146`) | F6, F7, F9 | `Tokenizer("phoneme").to_dict()` -> `from_dict()` preserves `mode="phoneme"`, `blank_id=0`, `vocab_size=29 > 10`. Cross-checked `kotoba.K2V`, `kotoba.PLACE`, and `VAL_CORPUS` (`asr/synth_data.py:180–212`): every consonant/vowel/special mora produced by `kotoba.parse_kana` is covered by `_DEFAULT_PHONEME_TOKENS`, so all `VAL_CORPUS` utterances encode to `target_lengths > 0` and decode to non-empty space-joined phoneme strings. | **PASS expected** |
| 5 | `test_t3_tsukinami_presets_cache_wav_io_logmel` (`L149–178`) | F2, F3, F8 | `synthesize_tsukinami` caches atomically via temp file + `os.replace` (`asr/synth_data.py:612–636`) and reloads from the saved WAV on write (`L636`), making `w_def` and `w_def_cached` bit-identical (`atol=1e-4` trivially holds); `_normalize_moras` guarantees `{"t", "a", "e"}`; `save_wav` -> `load_wav` 16-bit PCM round-trip preserves `corr > 0.999`; `default` vs `ossan` presets produce distinct Log-Mels (`mean(abs(diff)) > 1e-2`). | **PASS expected** |
| 6 | `test_t3_cnn_bigru_train_checkpoint_and_resume` (`L181–225`) | F1, F10, F11 | `train_asr` saves `best.pt` and `latest.pt` with all required keys (`model_state_dict`, `model_config`, `audio_cfg` + `audio_config`, `tokenizer`, `history`, `epoch`, `best_val_cer`); resume from `latest.pt` (`epoch=1` -> `epochs=2`) sets `start_epoch = 2`, runs epoch 2, saves `epoch == 2 >= 2`; `CNNBiGRUCTC` has `subsampling_factor == 4`, `output_frame_stride_ms(AudioConfig()) == 40.0`, and `pack_padded_sequence` + `pad_packed_sequence` produces finite `(1, 10, V)` log-probs with `out_len == [10]`. | **PASS expected** |
| 7 | `test_t3_conformer_lite_train_checkpoint_and_forward` (`L228–257`) | F1, F10, F11 | `ModelConfig(arch="conformer_lite", hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7, dropout=0.0)` passes validation (`32 % 4 == 0`, odd kernel); `SinusoidalPositionalEncoding` registers `pe` with `persistent=False` so `load_state_dict` never mismatches on sequence length; `ConformerLiteCTC` uses frame-wise `LayerNorm` and strict `pad_mask` in MHSA and `_ConformerConvModule`; forward on `(2, 40, 64)` with lengths `[40, 28]` yields `out_len = [10, 7] <= [40, 28]`, finite `log_probs`, and `exp(lp).sum(-1) == 1.0`. | **PASS expected** |

---

## Subtle Findings & Non-Blocking Hardening Opportunities (For Awareness / Tier 5)

None of the items below block Tier 3, so **no code changes are needed unless Tier 3 fails unexpectedly or Tier 5 hardening addresses them**:

1. **Cosine LR discontinuity when extending `epochs` via `resume_from` (`asr/train.py:304–308`)**:
   - When Run 1 trains for `epochs=E1` (`T_max=E1`), the final `scheduler.step()` leaves `optimizer.param_groups[0]["lr"] == eta_min` (`lr * 0.01`).
   - When Run 2 resumes with `epochs=E2 > E1`, `optimizer.load_state_dict` restores `lr = eta_min`, `scheduler.load_state_dict` restores `last_epoch = E1`, and `scheduler.T_max = E2` is mutated *after* loading without recomputing the current LR for `last_epoch = E1` under the new `T_max = E2`.
   - As a result, epoch `E1 + 1` trains at `eta_min` instead of the `T_max = E2` cosine LR at step `E1`, and only after `scheduler.step()` at the end of epoch `E1 + 1` does the LR jump up onto the `T_max = E2` cosine curve.
   - **Proposed fix (optional)**: After updating `scheduler.T_max = max(1, train_cfg.epochs)` on resume, recompute and assign the scheduled LR for `last_epoch` (e.g., set `param_group["lr"]` from the closed-form cosine formula for `last_epoch` / `T_max` when `last_epoch < T_max`).

2. **Incomplete config/tokenizer compatibility check on `resume_from` (`asr/train.py:291–301`)**:
   - `train_asr` checks `ckpt["model_config"] == model_cfg.to_dict()` and `len(ckpt_tok_vocab) == tokenizer.vocab_size`, but does not check full `ckpt["tokenizer"] == tokenizer.to_dict()` (mode + exact token ordering) or `ckpt.get("audio_cfg") == audio_cfg.to_dict()` (e.g. `cmvn`, `sample_rate`, `hop_length`).
   - **Proposed fix (optional)**: Compare `ckpt["tokenizer"].get("mode") != tokenizer.mode or ckpt_tok_vocab != tokenizer.vocab` (and optionally `audio_cfg` mismatch) on resume.

3. **SpecAugment RNG replays from initial seed on resume (`asr/train.py:225–229`)**:
   - `_SeededSpecAugmentDataset(base_train_ds, seed=train_cfg.seed)` always starts from the same `np.random.default_rng(train_cfg.seed)` on resume instead of advancing or offsetting by `start_epoch` (e.g. `train_cfg.seed + start_epoch - 1`), so resumed runs with SpecAugment repeat the epoch-1 mask sequence.

4. **Fixed `.tmp` filename in `_atomic_torch_save` (`asr/train.py:38`)**:
   - Uses `path.with_name(f"{path.name}.tmp")` rather than a PID/UUID-suffixed temp name (unlike `asr/synth_data.py:614`). Safe for single-process training per `checkpoint_dir`, but a UUID suffix avoids collisions if two processes ever write to the same directory.

---

## Summary of Audited Files
- `tests_e2e/test_tier3_combinations.py` (lines 1–258 in detail; full file read)
- `tests_e2e/conftest.py` (full file)
- `asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, `asr/models/conformer.py`, `asr/train.py` (all full files)
- `kotoba.py` (lines 1–160 for phoneme/mora table cross-check)
