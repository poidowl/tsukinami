# Challenger 3 (`chal3`) Handoff — Milestone M5 (Iteration 2)

## Verdict: **CONFIRMED**

All Iteration 2 fixes in `asr/inference.py` (`ASREngine`) were adversarially probed across 22 targeted edge-case checks with **22/22 PASS, 0 FAIL**, and `tests/test_asr_cli.py` passed **16/16**. No regressions or unhandled edge cases were found. All ad-hoc probe scripts were staged in `/tmp/teamwork_probe.4XwZ9T` and removed prior to reporting.

---

## Probe Results Summary (22/22 PASS)

### 1. Stereo, Multi-Channel & Degenerate Audio Shapes
| Probe | Result | Observed Details |
|-------|--------|------------------|
| `1a_stereo_2x16000_and_16000x2` | **PASS** | Both `(2, 16000)` and `(16000, 2)` yielded `duration_sec == 1.0`, identical `text`, identical downsampled `waveform`, and identical `vad_segments`. |
| `1b_stereo_8x16000_channels_first` | **PASS** | `(8, 16000)` channels-first averaged along `axis=0` with `duration_sec == 1.0`. |
| `1c_shape_16000x0_raises_ValueError` | **PASS** | Raised `ValueError: 2D audio array must have at least 1 channel`. |
| `1d_shape_0x2_clean` | **PASS** | Handled cleanly as empty audio (`duration_sec == 0.0`, `text == ''`, strict JSON valid). |
| `1e_shape_2x0_clean` | **PASS** | Handled cleanly via `ValueError: 2D audio array must have at least 1 channel`. |
| `1f_shape_0x0_clean` | **PASS** | Handled cleanly via `ValueError: 2D audio array must have at least 1 channel`. |
| `1g_3d_raises_ValueError` | **PASS** | Raised `ValueError: Expected 1D or 2D audio array, got shape (1, 2, 1600) (ndim=3)`. |
| `1h_1d_empty_1sample_10sample_and_redecode` | **PASS** | 1D arrays of length `0`, `1`, and `10` transcribed with exact `duration_sec` (`0.0`, `0.0000625`, `0.000625`), strict JSON valid, and `redecode` succeeded on all three. |
| `1i_nan_inf_waveform_sanitized` | **PASS** | `NaN`, `+inf`, `-inf` sanitized to `[0.0, 1.0, -1.0]`, all finite, strict JSON valid. |

### 2. Integer PCM Normalization & VAD Consistency
| Probe | Result | Observed Details |
|-------|--------|------------------|
| `2_int_pcm_normalization_and_vad_consistency` | **PASS** | On `-50 dBFS` quiet noise: `float32`, `int16`, `int32`, `uint8`, plus stereo `int16` `(2, 16000)` and `(16000, 2)` all normalized within `[-1.0, 1.0]` (`i16_max=0.01309`, `i32_max=0.01308`, `u8_max=0.01562`) and produced identical empty `vad_segments == []`. Full-scale extremes (`int16` `[-32768, 32767]`, `int32` `[-2147483648, 2147483647]`, `uint8` `[0, 255]`) all stayed within `[-1.0, 1.0]`. |

### 3. `ASREngine.from_checkpoint` Corrupt / Invalid / Missing Paths
| Probe | Result | Observed Details |
|-------|--------|------------------|
| `3a_ckpt_pickle_frame_overflow` | **PASS** | `b"\x80\x04\x95\xff\xff\xff\xff\xff\xff\xff\xff" + b"\x00"*32` raised `ValueError: Corrupt or invalid checkpoint ...: FRAME length exceeds ...` (no leaked `OverflowError`). |
| `3b_ckpt_truncated_eof_bytes` | **PASS** | Empty file (`b""`), truncated protocol-4 header (`b"\x80\x04"`), and truncated ZIP (`b"PK\x03\x04..."`) all raised `ValueError`. |
| `3c_ckpt_invalid_utf8_and_random_bytes` | **PASS** | Invalid UTF-8 bytes, 256 random bytes, and plain text all raised `ValueError`. |
| `3d_ckpt_missing_file` | **PASS** | Missing path raised `FileNotFoundError`. |
| `3e_ckpt_directory` | **PASS** | Directory path raised `ValueError: Checkpoint path is a directory: ...`. |
| `3f_ckpt_wrong_schema_pt` | **PASS** | Valid `.pt` containing `[1, 2, 3]` or `{"foo": "bar"}` raised `ValueError`. |

### 4. Performance (`<10 ms` `redecode`), LRU Cache, Visuals Strict JSON & `info()` Sanitization
| Probe | Result | Observed Details |
|-------|--------|------------------|
| `4a_redecode_under_10ms_and_no_model_forward` | **PASS** | With `model.forward` patched to raise `AssertionError`, greedy & beam (`beam_width=4, 8` with 3-gram LM) `redecode` never invoked `model.forward`; median latency **3.121 ms**, max **7.149 ms** (`<10 ms`). |
| `4b_lru_eviction_promotion_and_KeyError` | **PASS** | With `max_cache_size=2`, transcribing `u1, u2`, promoting `u1` via `redecode`, then transcribing `u3` evicted `u2` while retaining `u1` and `u3`; both evicted `u2` and unknown ID raised `KeyError`. |
| `4c_include_visuals_strict_json_both_arches` | **PASS** | Both `cnn_bigru` and `conformer_lite` passed `json.dumps(..., allow_nan=False)` with all required keys (`waveform`, `log_mel` `(T, 64)`, `ctc_posteriors`, `vad_segments`). |
| `4d_info_inf_nan_sanitized_to_None` | **PASS** | `best_val_cer=float("inf")`, `train_config` `nan`/`-inf`, and `history` `inf`/`-inf`/`nan` all sanitized to `None` and passed `json.dumps(..., allow_nan=False)`. |
| `4e_invalid_sr_and_max_cache_size` | **PASS** | Invalid `sr` (`0`, `-16000`, `True`, `16000.0`) and `max_cache_size` (`0`, `-5`, `True`) all raised `ValueError`. |
| `4f_resampling_8khz_and_44100hz` | **PASS** | 8 kHz and 44.1 kHz waveforms resampled cleanly to `duration_sec ≈ 1.0` and passed strict JSON serialization. |

---

## Regression Suite Check
- Command: `.venv/bin/pytest tests/test_asr_cli.py -q`
- Result: **16 passed** (exit code 0).
- Working tree: untouched (no source/test files modified; temporary probe directory `/tmp/teamwork_probe.4XwZ9T` removed).
