# M2 Challenger 1 Handoff — Adversarial Audit of `asr/synth_data.py`

## Scope & Methodology

Executed isolated adversarial probes in a temporary directory (`/tmp/teamwork_probe.*`, removed after testing) via `.venv/bin/python` against [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py) without modifying the working tree.

---

## Probe Results Summary

### 1. Phonetic Formant & Fricative Verification — **PASS**
- **Vowels (`ア`, `イ`, `ウ`, `エ`, `オ`)**:
  - Synthesized formant envelopes track `kotoba.tracks_from_kana()` accurately (measured with `f0_scale=0.55` to resolve formant peaks cleanly):
    - `ア`: `kotoba` F1=977 Hz / F2=1610 Hz → synth envelope peaks ~1008 Hz, 1602 Hz (centroid 1826 Hz)
    - `イ`: `kotoba` F1=379 Hz / F2=3162 Hz → synth envelope peaks ~414 Hz, 3027–3141 Hz (centroid 2821 Hz)
    - `ウ`: `kotoba` F1=437 Hz / F2=1840 Hz → synth envelope peak ~1836 Hz, F1 ~430 Hz (centroid 2089 Hz)
    - `エ`: `kotoba` F1=598 Hz / F2=2702 Hz → synth envelope peaks ~539–652 Hz, 2668 Hz (centroid 2513 Hz)
    - `オ`: `kotoba` F1=610 Hz / F2=1092 Hz → synth envelope peaks ~652 Hz, 1012–1125 Hz (centroid 1612 Hz)
  - Pairwise un-normalized log-Mel L2 distances across all 5 vowels are strongly separated: minimum `8.56` (`イ` vs `エ`), maximum `15.29` (`ア` vs `イ`), `ア` vs `オ` = `9.44`.
- **Fricatives (`サ`, `シ`, `ハ`)**:
  - Initial 60 ms onset high-frequency (> 3 kHz) energy ratio vs vowel reference:
    - `サ` vs `ア`: `0.998` vs `0.154`
    - `シ` vs `イ`: `0.821` vs `0.665` (> 2 kHz: `0.993` vs `0.880`)
    - `ハ` vs `ア`: `0.276` vs `0.154` (> 2 kHz: `0.365` vs `0.253`)

### 2. Speed & Scale Stress — **PASS**
- Synthesized all **150** utterances in `BUILTIN_CORPUS` (`TRAIN_CORPUS` + `VAL_CORPUS`) with `synthesize_fast_kotoba` in **0.694 s** (well under the 5.0 s budget).
- All 150 outputs were finite 1D `float32` in `[-1.0, 1.0]` with non-empty, non-overlapping monotonic moras having exact keys `{"t", "a", "e"}`.

### 3. Edge Cases & Hostile Inputs (`synthesize_fast_kotoba`) — **1 ISSUE FOUND**
- **Passed**: `""`, `"   "`, `"、。！？..."`, `",,,"`, `"ッ"`, `"ッッ"`, `"ッ、ッ"`, `"ー"`, `"ーーー"`, `"ッー"`, `"、ー"`, `"ァ"`, `"ャ"`, `"ョ"`, `"ン"`, hiragana, mixed hiragana/katakana, long vowels, extreme `f0_scale` (`0.05`–`100.0`), `fscale` (`0.1`–`10.0`), `rate` (`0.05`–`5.0`), `sr` (`100`–`44100`), `snr_db` (`-10.0`, `0.0`, `40.0`), seed determinism, and `ValueError` on all invalid `rate<=0`, `sr<=0`, `f0_scale<=0`, `fscale<=0`, `NaN`/`Inf`/`bool`, and non-string `text`.
- **Failed (Issue #2 below)**: whitespace-only input containing tabs/newlines (`"   \t\n  "`) produces audible audio (`len=6960`, peak `0.85`) and fake moras `[{'t': '\t', ...}, {'t': '\n', ...}]`.

### 4. `synthesize_tsukinami` — **2 ISSUES FOUND**
- **Passed**:
  - Global `yomu.PRESETS` and caller `overrides` (including nested dicts) are never mutated.
  - Unknown preset, `sr <= 0`, `""`, `"   "`, `"、、、"` raise `ValueError`.
  - Cache hit avoids re-synthesis (verified by monkeypatching `carve.make` to fail on warm hit) and returns identical moras.
  - Different `preset`, `overrides`, and `sr` produce distinct cache files with zero collisions, and corrupted cache files recover cleanly.
- **Failed (Issue #1 below)**: `synthesize_tsukinami("ッ")` crashes with unhandled `IndexError: list index out of range`.
- **Failed (Issue #3 below)**: Cold-call waveform vs warm-cache-hit waveform are NOT identical (`np.array_equal` is `False`, `max_abs_diff = 3.49e-5`) due to 16-bit PCM quantization on disk save.

### 5. `generate_dataset` — **PASS**
- `engine="fast"` and `engine="mixed"` are bit-for-bit deterministic with `seed` (both JSONL text and WAV file bytes match identically across runs).
- Invalid `engine`, `num_train <= 0`, `num_val <= 0`, `bool` counts, empty `presets`, and unknown `presets` all raise `ValueError`.
- JSONL schema matches `{"audio_path", "text", "duration", "speaker", "source", "moras"}`, and all generated WAVs load cleanly via `asr.audio.load_wav(..., target_sr=16000)`.

---

## Concrete Issues Found

### Issue 1 (Crash Bug): `synthesize_tsukinami("ッ")` crashes with unhandled `IndexError`
- **Location**: [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L540-L542)
- **Reproduction**:
  ```bash
  PYTHONPATH=. .venv/bin/python -c 'from asr.synth_data import synthesize_tsukinami; synthesize_tsukinami("ッ")'
  ```
- **Observed**: Raises unhandled `IndexError: list index out of range` inside `kotoba.build_tracks()`.
- **Cause**: Line 541 only checks `if not any(m != "、" for m in ms):`, omitting `"ッ"` (unlike `synthesize_fast_kotoba` at line 358 which explicitly guards `all(m in ("ッ", "、") for m in ms)`).
- **Recommended Fix**: Change line 541 to `if not any(m not in ("ッ", "、") for m in ms): raise ValueError(...)`.

### Issue 2 (Edge-Case Bug): `synthesize_fast_kotoba("   \t\n  ")` synthesizes audible audio & fake moras for whitespace
- **Location**: [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L353-L355)
- **Reproduction**:
  ```bash
  PYTHONPATH=. .venv/bin/python -c 'from asr.synth_data import synthesize_fast_kotoba; w, m = synthesize_fast_kotoba("   \t\n  "); print(w.size, float(abs(w).max()), m)'
  ```
- **Observed**: Prints `6960 0.8500000238418579 [{'t': '\t', 'a': 0.1, 'e': 0.19}, {'t': '\n', 'a': 0.19, 'e': 0.325}]` — audible non-zero speech for a whitespace-only string!
- **Cause**: `kotoba.split_moras()` only ignores `" "` and `"　"`, not `\t`, `\n`, `\r`, and `synthesize_fast_kotoba` does not check `if not text.strip():` before calling `kotoba.split_moras(text)`.
- **Recommended Fix**: Add `if not text.strip(): return np.zeros(0, dtype=np.float32), []` (and strip control whitespace such as `\t`/`\n`/`\r` before `kotoba.split_moras(text)`).

### Issue 3 (Cache Contract Mismatch): `synthesize_tsukinami` cold call vs warm cache hit waveforms are not identical
- **Location**: [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L563-L625)
- **Reproduction**:
  ```bash
  PYTHONPATH=. .venv/bin/python -c '
  import tempfile, numpy as np
  from asr.synth_data import synthesize_tsukinami
  with tempfile.TemporaryDirectory() as d:
      w1, m1 = synthesize_tsukinami("ツキナミ", preset="default", sr=16000, cache_dir=d)
      w2, m2 = synthesize_tsukinami("ツキナミ", preset="default", sr=16000, cache_dir=d)
      print("array_equal:", np.array_equal(w1, w2), "max_diff:", float(np.max(np.abs(w1 - w2))))
  '
  ```
- **Observed**: `array_equal: False max_diff: 3.486872e-05` (16-bit PCM quantization error from `save_wav` / `load_wav` on disk).
- **Recommended Fix**: When `cache_dir` is used and a cache entry is written, return the cached `load_wav(wav_cache_path, target_sr=sr)[0]` (or apply the same 16-bit round-trip) so cold-call and warm-hit return bit-identical waveforms (`np.array_equal(w1, w2) == True`).

---

VERDICT: ISSUES_FOUND
