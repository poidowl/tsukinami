# White-Box Challenger 1 Report — M7 Phase 2 Tier 5 Adversarial Hardening (Iteration 1)

**VERDICT: GAPS_FOUND**

## Scope Audited
All core DSP, Data, Model, Training, Decoding, and Metrics modules:
- `asr/config.py`
- `asr/audio.py`
- `asr/features.py`
- `asr/tokenizer.py`
- `asr/synth_data.py`
- `asr/dataset.py`
- `asr/models/__init__.py`, `asr/models/subsampling.py`, `asr/models/cnn_bigru.py`, `asr/models/conformer.py`
- `asr/train.py`
- `asr/decoding.py`
- `asr/metrics.py`

All ad-hoc probe scripts were staged in `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`, executed with `/home/antigravity/poidowl/tsukinami/.venv/bin/python`, and deleted (`rm -rf`) immediately after execution. Zero files in the repository working tree were modified.

---

## Concrete Reproducible Bugs & Robustness Gaps

### Bug 1 [HIGH]: Numerical overflow / `NaN` / positive log-prob scores in `asr/decoding.py:_prepare_log_probs`
- **Affected file/lines**: `asr/decoding.py:65-73`
- **Root cause**: `_prepare_log_probs` divides `arr` by `temp` and adds `blank_bias` *before* subtracting the per-frame row maximum. For small finite `temperature` (e.g. `1e-308`, accepted by `DecodeConfig`) or large `blank_bias` (e.g. `1e308`):
  1. Valid negative `log_probs` underflow to `-inf` across the entire row, causing a spurious `ValueError("log_probs contains a frame with all -inf values")`.
  2. Positive unnormalized logits overflow to `+inf`, causing `scaled - row_max` to evaluate to `inf - inf = NaN`, corrupting `greedy_decode` (`score=nan`) and `prefix_beam_search` (which returns bogus **positive** `acoustic_score = 3.401...`).
- **Exact repro**:
  ```python
  import numpy as np
  from asr.config import DecodeConfig
  from asr.decoding import greedy_decode, prefix_beam_search
  from asr.tokenizer import Tokenizer

  tok = Tokenizer("kana")
  lp = np.log(np.full((5, tok.vocab_size), 1.0 / tok.vocab_size, dtype=np.float64))
  greedy_decode(lp, tok, temperature=1e-308)
  # Observed: ValueError: log_probs contains a frame with all -inf values

  lp_pos = np.ones((5, tok.vocab_size), dtype=np.float64)
  prefix_beam_search(lp_pos, tok, DecodeConfig(temperature=1e-308))
  # Observed: [{'text': 'ポヴ', 'score': 3.401197381662155, 'acoustic_score': 3.401197381662155, ...}]

  greedy_decode(np.full((5, tok.vocab_size), 1e308), tok, blank_bias=1e308)
  # Observed: {'text': '', 'token_ids': [], 'score': nan}
  ```
- **Expected behavior**: Valid finite `log_probs` or logits with any valid `DecodeConfig` (`temperature > 0`, finite `blank_bias`) must always produce normalized log-probabilities `<= 0.0` with finite, non-`NaN` scores (`<= 0.0` for acoustic score).
- **Recommended fix**: Check for all-`-inf` rows on `arr` first, subtract `base_max = np.max(arr, axis=-1, keepdims=True)` *before* dividing by `temp` (so `(arr - base_max) / temp <= 0.0` with at least one `0.0` per frame), and handle `blank_bias` overflow safely (e.g. if `scaled[:, blank_id] + bias` overflows `+inf`, assign blank probability `1.0` / log-prob `0.0` and all other tokens `-inf` or clamp before `logsumexp`).

---

### Bug 2 [HIGH]: `ZeroDivisionError`, `OverflowError`, and `NaN`/`Inf` waveforms in `asr/audio.py:apply_corruption` (and `asr/synth_data.py:synthesize_fast_kotoba`)
- **Affected file/lines**: `asr/audio.py:487-500`, `asr/synth_data.py:503-515`
- **Root cause**:
  - `10.0 ** (snr_db / 10.0)` underflows to `0.0` at `snr_db <= -3240` (`ZeroDivisionError`) and overflows at `snr_db >= 3090` (`OverflowError`).
  - Moderate-extreme values like `snr_db = -1000.0` produce `scale ~ 1e49`, which overflows `float32` to `inf`/`-inf`.
  - `gain = np.float32(10.0 ** (gain_db / 20.0))` raises `OverflowError` at `gain_db >= 6170` and overflows `float32` to `inf` at `gain_db >= 771`, turning `0.0 * inf` into **`NaN`** and non-zero samples into **`Inf`**.
- **Exact repro**:
  ```python
  import numpy as np
  from asr.audio import apply_corruption
  from asr.synth_data import synthesize_fast_kotoba

  wav = np.sin(2 * np.pi * 440 * np.arange(1600) / 16000).astype(np.float32)
  apply_corruption(wav, 16000, snr_db=-5000.0, seed=0)  # ZeroDivisionError
  apply_corruption(wav, 16000, snr_db=4000.0, seed=0)   # OverflowError
  np.isfinite(apply_corruption(wav, 16000, snr_db=-1000.0, seed=0)).all()  # False (Inf)
  apply_corruption(wav, 16000, gain_db=7000.0)          # OverflowError
  np.isfinite(apply_corruption(wav, 16000, gain_db=800.0)).all()           # False (NaN & Inf)
  synthesize_fast_kotoba("ア", snr_db=-5000.0, seed=0)  # ZeroDivisionError
  ```
- **Expected behavior**: Never raise `ZeroDivisionError` or `OverflowError` and never emit `NaN`/`Inf` in `float32` output. Either enforce explicit finite domain bounds (raising `ValueError` for extreme non-representable `snr_db` / `gain_db`, e.g., `[-120, 120]` or `[-300, 300]`) or handle large positive `snr_db` as zero noise and cap/reject values that would overflow `float32`.

---

### Bug 3 [HIGH]: `ZeroDivisionError` and silent invalid `rate <= 0` in `asr/synth_data.py:synthesize_tsukinami`
- **Affected file/lines**: `asr/synth_data.py:584-603`
- **Root cause**: `overrides` values for `hz`, `fscale`, and `rate` are copied directly into `prm` without positive-finite validation, and passed to `yomu.build_carve_rc`, `carve.make`, and `yomu.boost_low_pitch_rms`.
- **Exact repro**:
  ```python
  from asr.synth_data import synthesize_tsukinami

  synthesize_tsukinami("ア", overrides={"hz": 0})      # ZeroDivisionError
  synthesize_tsukinami("ア", overrides={"fscale": 0})  # ZeroDivisionError
  synthesize_tsukinami("ア", overrides={"rate": -1})   # Silently succeeds with negative rate
  ```
- **Impact**: Also reachable through `POST /api/tts-roundtrip` if `hz`, `fscale`, or `rate` are non-positive.
- **Expected behavior**: Validate `hz`, `fscale`, and `rate` in `prm` via `_validate_positive_float`, raising `ValueError` for `<= 0` or non-finite values.

---

### Bug 4 [MEDIUM-HIGH]: `TrainConfig` accepts out-of-range `seed` that crashes `train_asr`
- **Affected file/lines**: `asr/config.py:172`, `asr/train.py:30-33,65`
- **Root cause**: `TrainConfig.__post_init__` calls `_check_int("seed", self.seed)` with no bounds, allowing `seed=-1` or `seed=2**32`. When passed to `train_asr`, `_seed_everything` calls `np.random.seed(seed)` which raises `ValueError: Seed must be between 0 and 2**32 - 1`.
- **Exact repro**:
  ```python
  from asr.config import TrainConfig
  cfg = TrainConfig(seed=-1)      # Succeeds!
  cfg2 = TrainConfig(seed=2**32)  # Succeeds!
  # Passing cfg to train_asr(...) crashes in _seed_everything -> np.random.seed(-1)
  ```
- **Expected behavior**: `TrainConfig.__post_init__` should enforce `0 <= seed <= 2**32 - 1` (raising `ValueError` immediately on construction).

---

### Bug 5 [MEDIUM-HIGH]: `train_asr(resume_from=...)` crashes with `AttributeError` on malformed checkpoint `tokenizer` and silently accepts same-length mismatched vocabularies
- **Affected file/lines**: `asr/train.py:296-301`
- **Root cause**:
  1. `ckpt["tokenizer"].get("vocab")` assumes `ckpt["tokenizer"]` is a dict; if `None` or non-mapping, it raises `AttributeError` instead of `ValueError`.
  2. Only `len(ckpt_tok_vocab) != tokenizer.vocab_size` is checked — two tokenizers with identical length (`4`) but completely different tokens (`["<blank>", "ア", "イ", "ウ"]` vs `["<blank>", "カ", "キ", "ク"]`) resume **silently**, corrupting the classifier head mapping.
- **Exact repro**:
  ```python
  # 1. Malformed tokenizer=None in checkpoint -> AttributeError: 'NoneType' object has no attribute 'get'
  # 2. tok_a = Tokenizer("kana", vocab=["<blank>", "ア", "イ", "ウ"])
  #    tok_b = Tokenizer("kana", vocab=["<blank>", "カ", "キ", "ク"])
  #    train_asr(..., tokenizer=tok_a, resume_from=ckpt_saved_with_tok_b) -> silently succeeds!
  ```
- **Expected behavior**: Raise `ValueError` if `ckpt["tokenizer"]` is not a `Mapping`, or if `ckpt_tok_vocab != tokenizer.vocab` (or mode differs when present).

---

### Bug 6 [MEDIUM]: `asr/features.py` `NaN` filterbank bypass, `float32` power overflow in `extract_log_mel`, and `TypeError` on float params
- **Affected file/lines**: `asr/features.py:72,129-135,138-159,195,229`
- **Root cause**:
  1. `mel_filterbank(f_min=float("nan"))` and `mel_filterbank(f_max=float("nan"))` bypass `f_min_f < 0.0 or f_min_f >= resolved_f_max` (all comparisons with `NaN` are `False`) and return an all-`NaN` `(64, 257)` matrix!
  2. `stft_power` casts `(spec.real**2 + spec.imag**2)` to `float32` before `mel_energy = power @ fb.T` and `np.log(...)`. For large finite `float32` waveforms (e.g. amplitude `1e20`), `power` overflows to `inf`, causing `cmvn` (`inf - inf`) to return **`NaN`**.
  3. `extract_log_mel` does not guard against `NaN`/`Inf` in `wav`, propagating `NaN` silently.
  4. `extract_mfcc(wav, n_mfcc=3.5)` and `spec_augment(mel, num_freq_masks=2.5)` omit `isinstance(..., int)` checks and raise `TypeError` instead of `ValueError`.
- **Exact repro**:
  ```python
  import numpy as np
  from asr.features import mel_filterbank, extract_log_mel, extract_mfcc, spec_augment

  np.isnan(mel_filterbank(f_min=float("nan"))).any()   # True (all NaN!)
  np.isnan(mel_filterbank(f_max=float("nan"))).any()   # True (all NaN!)
  wav = np.sin(2 * np.pi * 440 * np.arange(1600) / 16000).astype(np.float32)
  np.isfinite(extract_log_mel(wav * 1e20)).all()       # False (NaN!)
  extract_mfcc(wav, n_mfcc=3.5)                        # TypeError instead of ValueError
  spec_augment(np.ones((10, 64), dtype=np.float32), num_freq_masks=2.5)  # TypeError
  ```
- **Expected behavior**: Reject non-finite `f_min`/`f_max` in `mel_filterbank` with `ValueError`; compute `power` and `mel_energy` in `float64` (taking `log` before casting to `float32`) and sanitize/validate non-finite inputs so `extract_log_mel` always produces finite `float32`; raise `ValueError` for non-integer `n_mfcc` / `spec_augment` params.

---

### Bug 7 [MEDIUM]: `asr/audio.py:resample` accepts `NaN`/`Inf` sample rates
- **Affected file/lines**: `asr/audio.py:62-65`
- **Root cause**: `if isinstance(orig_sr, bool) or orig_sr <= 0:` does not check `isinstance(..., int)` or `math.isfinite`.
- **Exact repro**:
  ```python
  import numpy as np
  from asr.audio import resample
  wav = np.ones(1600, dtype=np.float32)
  resample(wav, float("inf"), 16000).shape  # Silently returns (1,)!
  resample(wav, 16000, float("inf"))        # OverflowError instead of ValueError
  ```
- **Expected behavior**: Validate `orig_sr` and `target_sr` are positive integers (`isinstance(..., int) and not isinstance(..., bool) and val > 0`), raising `ValueError` otherwise.

---

### Bug 8 [LOW-MEDIUM]: Validation inconsistencies in `Tokenizer`, `CharNgramLM.from_dict`, and `alignment_boundary_error`
- **Affected file/lines**: `asr/tokenizer.py:102-111,206-212`, `asr/decoding.py:170-180`, `asr/metrics.py:254-263`
- **Exact repro**:
  - `Tokenizer("kana", vocab=["<blank>", 123])` -> `TypeError: object of type 'int' has no len()` instead of `ValueError`.
  - `tok.decode([True])` and `tok.decode([1.9])` -> silently coerce `bool`/`float` to token ID `1` instead of raising `ValueError` (in contrast to `viterbi_align`, which rejects bool/float token IDs).
  - `CharNgramLM.from_dict({"order": 2, "smoothing": 0.1, "vocab": 123, "ngrams": []})` -> `TypeError: 'int' object is not iterable` instead of `ValueError` (same for `ngrams=123` and `raw_ctx=123`).
  - `alignment_boundary_error([{"t": "ア", "a": float("nan"), "e": 0.2}], [{"token": "ア", "start_sec": 0.0, "end_sec": 0.2}])` -> silently returns `onset_mae_sec: nan`.

---

## Verified Robust Areas (Probes Passed Cleanly)
- `Conv2dSubsampling`, `CNNBiGRUCTC`, and `ConformerLiteCTC`:
  - `NaN` in padded input frames (`t >= length`) is completely isolated in both forward (`log_probs` finite on all valid frames) and backward (`x.grad` and all parameter gradients finite — zero `NaN` leakage).
  - `ConformerLiteCTC` dynamic positional encoding extension beyond `max_len=1024` (`T=4100 -> T'=1025`) produces finite outputs with exact expected shape.
- `asr/audio.py:_parse_wav_bytes` / `load_wav_bytes`:
  - Properly decodes `WAVE_FORMAT_EXTENSIBLE` (PCM subformat), sanitizes `NaN`/`+Inf`/`-Inf` in IEEE float32 WAVs to `[0.0, 1.0, -1.0]`, and cleanly rejects huge corrupt chunk sizes (`0xFFFFFFFF`).
- `asr/synth_data.py:synthesize_fast_kotoba`:
  - Safely handles special/edge strings (`"ー"`, `"ン"`, `"ャ"`, `"ァ"`, `"。"`, `"、ー"`, `"ッー"`, `"abc"`, `"漢字"`, `"ヴ"`, `rate=1e-6`).
- `asr/train.py:load_checkpoint`:
  - Cleanly raises `ValueError` on empty files, random bytes, truncated ZIP archives, and non-dict pickled objects.
- `asr/decoding.py:viterbi_align`:
  - Cleanly handles unnormalized logits, repeated tokens at exact `min_frames`, and clamps confidences to `[0.0, 1.0]`.

---

## Proposed Adversarial Test Specifications for `tests/test_asr_tier5_hardening.py`
1. `test_decoding_extreme_temperature_and_blank_bias_stability`:
   - `greedy_decode` and `prefix_beam_search` with `temperature=1e-308` on uniform `log_probs` AND on positive logits (`+1.0`), and `blank_bias=1e308` on `+1e308` logits -> assert finite `score <= 0.0` and `acoustic_score <= 0.0`, no `NaN`, no spurious `ValueError`.
2. `test_apply_corruption_extreme_snr_and_gain_no_crash_or_nan`:
   - `apply_corruption` with `snr_db` in `(-5000.0, -1000.0, 4000.0)` and `gain_db` in `(800.0, 7000.0)` + `synthesize_fast_kotoba(..., snr_db=-5000.0)` -> assert either clean `ValueError` or finite `float32` output (never `ZeroDivisionError`, `OverflowError`, `NaN`, or `Inf`).
3. `test_synthesize_tsukinami_invalid_overrides_rejected`:
   - `synthesize_tsukinami("ア", overrides=...)` with `{"hz": 0}`, `{"hz": -100}`, `{"fscale": 0}`, `{"rate": 0}`, `{"rate": -1}` -> assert `ValueError` (never `ZeroDivisionError`).
4. `test_train_config_seed_bounds_validation`:
   - `TrainConfig(seed=-1)` and `TrainConfig(seed=2**32)` -> assert `ValueError`.
5. `test_train_resume_rejects_malformed_or_mismatched_tokenizer`:
   - `train_asr(..., resume_from=...)` with `"tokenizer": None` -> assert `ValueError` (not `AttributeError`).
   - `train_asr(..., resume_from=...)` with same-length different vocab -> assert `ValueError`.
6. `test_features_nan_filterbank_large_signal_and_type_validation`:
   - `mel_filterbank(f_min=float("nan"))` and `mel_filterbank(f_max=float("nan"))` -> assert `ValueError`.
   - `extract_log_mel(wav * 1e20)` -> assert all finite `float32`.
   - `extract_mfcc(wav, n_mfcc=3.5)` and `spec_augment(mel, num_freq_masks=2.5)` -> assert `ValueError`.
7. `test_resample_rejects_non_int_and_non_finite_sr`:
   - `resample(wav, float("inf"), 16000)`, `resample(wav, 16000, float("inf"))`, `resample(wav, float("nan"), 16000)` -> assert `ValueError`.
8. `test_tokenizer_and_lm_malformed_inputs_and_model_nan_padding_isolation`:
   - `Tokenizer("kana", vocab=["<blank>", 123])`, `tok.decode([True])`, `tok.decode([1.9])`, `CharNgramLM.from_dict` with non-iterable `vocab`/`ngrams`/`raw_ctx` -> assert `ValueError`.
   - `CNNBiGRUCTC` & `ConformerLiteCTC` forward+backward with `NaN` in padded frames -> assert finite valid outputs and finite gradients.
   - `ConformerLiteCTC` with `T=4100` (exceeding initial `max_len=1024`) -> assert finite output of shape `(1, 1025, V)`.
