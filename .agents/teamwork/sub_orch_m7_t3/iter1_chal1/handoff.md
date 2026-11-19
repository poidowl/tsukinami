# Challenger 1 Handoff — DSP, Data, Tokenizer, Model & Training Cross-Feature Probes

## Verdict
**`CONFIRMED_CORRECT`**

All **1,977 adversarial cross-feature invariant checks** (Probe 1: 1,625 checks; Probe 2: 113 checks; Probe 3: 239 checks) passed with zero contract defects, zero NaN/Inf corruptions, zero padding-invariance violations, and deterministic behavior under fixed seeds.

- **Repository cleanliness**: Zero source/test files modified (`git diff --stat` empty).
- **Temp probe cleanup**: All temporary probe directories created via `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` were removed via `trap 'rm -rf "$PROBE_DIR"' EXIT` and verified absent (`NO_TEMP_PROBE_DIRS`).

---

## Probe 1 — DSP, Corruption, WAV I/O (Resampling), Features & VAD Chain

### Scope & Cross-Feature Combinations Tested
- `synthesize_fast_kotoba` at 3 sample rates (`8000`, `16000`, `22050` Hz)
- Chained `apply_corruption` across the full Cartesian grid of:
  - `noise_type` ∈ `{"white", "pink"}`
  - `snr_db` ∈ `{-5.0, 10.0, 25.0}`
  - `speed` ∈ `{0.75, 1.0, 1.35}`
  - `gain_db` ∈ `{-18.0, 0.0, 12.0}`
  - `band_limit=(300.0, min(3400.0, orig_sr / 2.0 - 100.0))`
  - Fixed-seed determinism (`np.array_equal` across repeated invocations with `seed=123`)
- `save_wav` (16-bit PCM) → `load_wav(..., target_sr=16000)` (FFT resampling & `[-1.0, 1.0]` clamping)
- `extract_log_mel` (`cmvn=True` and `cmvn=False`) and `extract_mfcc(..., n_mfcc=13, include_deltas=True)`
- `detect_vad` (sorted, non-overlapping segments, `0.0 <= start < end <= duration`)
- **Extreme edge cases**: all-zero 1 s silence, 1-sample, 10-sample, 100-sample, and stereo 2D `(4000, 2)` arrays with `gain_db` ∈ `{-100.0, 0.0, +40.0}` → `save_wav` → `load_wav(target_sr=8000)` → `extract_log_mel`/`extract_mfcc` → `detect_vad`
- **Invalid-input error handling**: missing WAV (`FileNotFoundError`), directory path (`ValueError`), unsupported `noise_type="brown"` (`ValueError`), `speed=0.0` (`ValueError`), inverted `band_limit=(4000.0, 2000.0)` (`ValueError`), `snr_db=nan` (`ValueError`).

### Command & Output
```bash
PROBE_DIR=$(mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX")
trap 'rm -rf "$PROBE_DIR"' EXIT
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python "$PROBE_DIR/probe1_dsp.py"
```
```text
PROBE_DIR=/tmp/teamwork_probe.iXqo8a
PROBE1_PASS: 1625 checks passed across DSP/corruption/WAV/feature/VAD chain.
```

---

## Probe 2 — Synthesis, Tokenizers (`kana`/`phoneme`/`ascii`), Dataset, Collate & SpecAugment

### Scope & Cross-Feature Combinations Tested
- `Tokenizer` across all 3 modes (`kana`, `phoneme`, `ascii`), including:
  - Hiragana, Katakana, small kana (`きゃ`/`きゅ`/`ヴァ`), special moras (`っ`/`ん`/`ー`), punctuation (`、`/`。`/full-width space `\u3000`), pre-tokenized phoneme strings (`"k o N n i ch i w a"`), mixed-case ASCII with digits/punctuation.
  - `to_dict()` / `from_dict()` equality round-trip, `blank_id == 0`, no blank IDs in encoded targets, and `encode(decode(ids)) == ids` idempotence.
- `synthesize_fast_kotoba` (varying `rate` for variable-length utterances) → `save_wav` → `write_manifest` (mixing relative and absolute `audio_path`s) → `ASRManifestDataset` (`augment=False` and `augment=True` with seeded `spec_augment_kwargs`) → `collate_asr_batch`.
- **Invariants verified**:
  - `[B, T_max, 64]` `float32` finite features, `[B, L_max]` `int64` targets, strict zero-padding beyond `feat_lengths[i]` and `target_lengths[i]`, no `blank_id` in valid target slices.
  - Fixed-seed `spec_augment` determinism (`torch.equal`), input non-mutation, `T=1` with `time_mask_param=100`, `num_freq_masks=0, num_time_masks=0` identity.
  - Cross-mode empty-target guard: `Tokenizer("ascii")` on pure Kana manifest raises `ValueError` when `allow_empty_targets=False`, and collates cleanly (`targets.shape == (1, 0)`) when `allow_empty_targets=True`.

### Command & Output
```bash
PROBE_DIR=$(mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX")
trap 'rm -rf "$PROBE_DIR"' EXIT
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python "$PROBE_DIR/probe2_data_tok.py"
```
```text
PROBE_DIR=/tmp/teamwork_probe.igxC1O
PROBE2_PASS: 113 checks passed across synth/tokenizer/dataset/collate/spec_augment.
```

---

## Probe 3 — Acoustic Models (`cnn_bigru`, `conformer_lite`), Padding Invariance, Stride & `train_asr` Checkpoint/Resume Edge Cases

### Scope & Cross-Feature Combinations Tested
- **Strict forward padding invariance** (`model.eval()`) for `cnn_bigru` and `conformer_lite` (`conv_kernel_size=7` and `15`) across all `L mod 4` remainders (`L ∈ {1, 2, 3, 4, 5, 6, 7, 8, 17, 29}`):
  - Filled padded frames `[L:40]` with adversarial `1e5` garbage values in a batch of 2 and verified valid frames `[0:(L+3)//4]` match the unpadded single-utterance forward pass within `1e-4`, all outputs finite, and `exp(log_probs).sum(-1) ≈ 1.0`.
- **`output_frame_stride_ms`** verified across `AudioConfig` combinations (`16000/160 → 40.0 ms`, `8000/80 → 40.0 ms`, `16000/128 → 32.0 ms`, `22050/220 → 39.9093 ms`) and `subsampling_factor == 4`.
- **Dynamic positional encoding extension (`ConformerLiteCTC`)**: forward pass with `T=4200 → T'=1050` (exceeding initial `max_len=1024`), followed by `load_state_dict` into a fresh `max_len=1024` model (verifying `persistent=False` buffer contract).
- **`train_asr` determinism**: identical `history` and bit-identical `model_state_dict` weights across two runs with `seed=42` and `use_spec_augment=True` for both `cnn_bigru` and `conformer_lite`.
- **Checkpoint save/load/resume edge cases**:
  - Extending epochs (`1 → 3`) preserves history `[1, 2, 3]` and updates `best.pt` / `latest.pt`.
  - No-op resume (`epochs=2 <= ckpt["epoch"]=3`) into a new `checkpoint_dir` creates both `best.pt` and `latest.pt` cleanly with `epoch == 3`.
  - Incompatible `model_config` or tokenizer `vocab_size` on `resume_from` raises `ValueError`.
  - `load_checkpoint` cleanly raises `FileNotFoundError` (missing path) and `ValueError` (directory, corrupt bytes, non-dict object, missing required keys).
  - Ultra-short audio (`50 ms` → `out_lengths=1 < target_lengths`) with `Tokenizer("phoneme")` trains without NaN/Inf weights (`CTCLoss(zero_infinity=True)`) and round-trips the phoneme tokenizer in the checkpoint.

### Command & Output
```bash
PROBE_DIR=$(mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX")
trap 'rm -rf "$PROBE_DIR"' EXIT
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python "$PROBE_DIR/probe3_models_train.py"
```
```text
PROBE_DIR=/tmp/teamwork_probe.d7Hcm2
PROBE3_PASS: 239 checks passed across models/padding-invariance/train_asr/checkpoint/resume.
```

---

## Non-Blocking Precision Observation (Not a Defect)
- **Float32 constant-signal CMVN rounding (`asr/features.py:155-157`)**: For an all-zero waveform (`np.zeros(16000, dtype=np.float32)`), `log_mel` is constant `-23.025850f`, and computing `mean = log_mel.mean(axis=0)` in `float32` accumulates ~`1 ULP` (`~1e-6`) rounding error; dividing by `std + 1e-6` (`std == 0`) yields a uniform finite constant `0.9545058f` instead of `0.0f`. All values remain strictly finite, uniform, and bounded, so this violates no contract; optional Tier 5 hardening could compute CMVN `mean`/`std` in `float64`.
