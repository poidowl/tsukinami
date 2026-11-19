# Challenger 1 (`chal1`) Handoff — Milestone M5 (Iteration 1)

## Verdict: **FAIL**

Two concrete input-handling bugs were found in [`_prepare_waveform`](file:///home/antigravity/poidowl/tsukinami/asr/inference.py#L83-L105) inside [`asr/inference.py`](file:///home/antigravity/poidowl/tsukinami/asr/inference.py). All other probed areas (empty/short audio on both `cnn_bigru` and `conformer_lite`, NaN/Inf sanitization, invalid `sr` validation, non-16kHz resampling, `include_visuals=True` schema & strict JSON serializability, `<10 ms` `redecode` for greedy & default beam without invoking `model.forward`, LRU promotion/eviction & `KeyError`, `CharNgramLM` integration, `info()` with `best_val_cer=inf`, and `from_checkpoint` error handling) passed cleanly.

---

## Failing Probes & Concrete Repros

### 1. [HIGH] Channels-first stereo `(2, N)` silently collapses time axis
- **Location**: [`asr/inference.py:88-91`](file:///home/antigravity/poidowl/tsukinami/asr/inference.py#L88-L91) (`_prepare_waveform`)
- **Cause**: Any 2D array is unconditionally averaged along `axis=-1`:
  ```python
  elif arr.ndim == 2:
      if arr.shape[1] == 0:
          raise ValueError("2D audio array must have at least 1 channel")
      mono = arr.mean(axis=-1, dtype=np.float32)
  ```
- **Repro**:
  ```python
  t = np.linspace(0, 1.0, 16000, dtype=np.float32)
  sine = 0.3 * np.sin(2 * np.pi * 440 * t)
  stereo_2n = np.stack([sine, sine * 0.5], axis=0)  # shape (2, 16000), 1.0s audio
  res = engine.transcribe(stereo_2n, sr=16000)
  # Observed: res["duration_sec"] == 0.000125 (2 samples!)
  # Expected: res["duration_sec"] == 1.0
  ```
- **Suggested Fix**: In `_prepare_waveform`, handle channels-first `(C, N)` when `arr.shape[0] <= 8 and arr.shape[1] > arr.shape[0]` by averaging along `axis=0` (and validate that the channel axis is non-zero).

### 2. [MEDIUM] Integer PCM arrays (`int16`, etc.) are not normalized to `[-1.0, 1.0]`
- **Location**: [`asr/inference.py:85`](file:///home/antigravity/poidowl/tsukinami/asr/inference.py#L85) (`_prepare_waveform`)
- **Cause**: `np.asarray(wav, dtype=np.float32)` casts integer PCM directly to float32 without dividing by full-scale (`32768.0` for `int16`).
- **Impact**:
  1. `waveform` in `include_visuals=True` contains raw integer amplitudes up to `±32768.0` instead of `[-1.0, 1.0]`.
  2. `detect_vad` (threshold `-35.0 dB` relative to `1.0`) misclassifies `-50 dBFS` quiet noise as 100% speech.
- **Repro**:
  ```python
  rng = np.random.default_rng(0)
  quiet_f32 = (rng.standard_normal(16000) * 0.003).astype(np.float32)  # ~ -50 dBFS
  quiet_i16 = np.round(quiet_f32 * 32767.0).astype(np.int16)

  res_f32 = engine.transcribe(quiet_f32, sr=16000, include_visuals=True)
  res_i16 = engine.transcribe(quiet_i16, sr=16000, include_visuals=True)
  # Observed:
  #   quiet_f32: vad=[], wf_max=0.01176
  #   quiet_i16: vad=[[0.0, 1.0]], wf_max=385.00000
  ```
- **Suggested Fix**: Before casting to `float32`, if `np.issubdtype(raw.dtype, np.signedinteger)`, normalize by `float(-np.iinfo(raw.dtype).min)` (e.g., `32768.0` for `int16`); if `unsignedinteger`, center and normalize.

---

## Full Probe Matrix Summary

| # | Probe Category | Result | Key Observations |
|---|---|---|---|
| 1a | Empty (`0`), `1`, `10`, `100`, `399`, `400`, `1000` samples (`cnn_bigru` & `conformer_lite`) | **PASS** | All 14 cases succeeded with `include_visuals=True` and `json.dumps(..., allow_nan=False)`. |
| 1b | Stereo `(N, 2)` | **PASS** | `duration_sec=1.000000`. |
| 1c | Stereo `(2, N)` | **FAIL** | Collapsed to 2 samples (`duration_sec=0.000125`). |
| 1d | `float64` input | **PASS** | Handled cleanly, `duration_sec=1.000`. |
| 1e | `int16` input | **FAIL** | Unscaled cast (`wf_max=9830.0` on 0.3-amp sine; `-50 dBFS` noise triggers `vad=[[0.0, 1.0]]`). |
| 1f | `NaN` / `±Inf` & all-`NaN` waveforms | **PASS** | Sanitized; `json.dumps(..., allow_nan=False)` passed. |
| 1g | Invalid `sr` (`0`, `-16000`, `True`, `False`) & bad shapes (`0D`, `3D`, `(16000, 0)`) | **PASS** | All raised `ValueError`. |
| 2 | Non-16kHz resampling (`8000`, `22050`, `44100`, `48000` Hz) | **PASS** | `duration_sec` matched `1.2500s` with `0.00000s` error across all 4 rates. |
| 3 | `include_visuals=True` (normal & empty audio) | **PASS** | Strict JSON (`allow_nan=False`), correct shapes/types for `waveform` (2000), `log_mel` (201×64), `ctc_posteriors` (`times_sec`, `top_tokens`, `probs`), `vad_segments`. |
| 4a | `redecode` no-model check (`model.forward` monkeypatched to raise) | **PASS** | Neural net not invoked during `redecode`. |
| 4b | `redecode` latency (2.02s audio, 51 frames) | **PASS** (note) | Median `decode_ms`: greedy `0.78 ms`, `beam_width=4` `3.39 ms`, `beam_width=8` (default) `4.85 ms`, `beam_width=8` + temp/bias `4.68 ms`. (Note: extreme `beam_width=16` on 2.02s audio measured `13.92 ms`.) |
| 4c | LRU promotion, eviction (`max_cache_size=3`), & `KeyError` | **PASS** | Promoted `uid1` retained, `uid2` evicted, `KeyError` on both evicted and unknown IDs. |
| 5 | `CharNgramLM` + beam decoding (`lm_weight > 0`) | **PASS** | `has_lm=True`, non-zero `lm_score`, `redecode_ms=4.87 ms`, strict JSON. |
| 6 | `engine.info()` with `best_val_cer=inf`, `NaN`/`-Inf` in metadata/history | **PASS** | Sanitized to `None`; `json.dumps(info, allow_nan=False)` passed. |
| 7 | `ASREngine.from_checkpoint` (missing, corrupt bytes, incomplete dict, embedded LM) | **PASS** | Raised `FileNotFoundError` (missing) and `ValueError` (corrupt/incomplete); loaded embedded LM cleanly. |
