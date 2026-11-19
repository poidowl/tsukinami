# M2 Challenger 1 Handoff (Iteration 2) — Re-Verification & Adversarial Audit of `asr/synth_data.py`

## Scope & Methodology

Executed isolated adversarial probes in a temporary directory (`/tmp/teamwork_probe.*`, automatically removed on exit and verified clean) via `.venv/bin/python` against [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py) without modifying the working tree.

---

## Probe Results Summary

### 1. Iteration 1 Bug Fixes — **ALL 3 CONFIRMED FIXED**
- **Issue 1 (`synthesize_tsukinami` sokuon/pause/whitespace guard)** — **PASS**:
  - `"ッ"`, `"ッッ"`, `"ッ、ッ"`, `"   \t\n  "`, `"\r\n\t"`, `"　\t\n　"`, `""`, `"   "`, `"、、、"`, `"　"` all raise `ValueError` cleanly (no unhandled `IndexError`).
- **Issue 2 (`synthesize_fast_kotoba` whitespace handling)** — **PASS**:
  - `"   \t\n  "`, `"\r\n\t"`, `"　\t\n　"`, `"   "`, `""` all return `(np.zeros(0, dtype=np.float32), [])`.
  - `"ア\tイ\nウ"` synthesizes cleanly with moras `['ア', '、', 'イ', '、', 'ウ']` (matching `kotoba.split_moras("ア イ ウ")` pause conventions, zero `\t`/`\n` fake moras) and is bit-identical to `synthesize_fast_kotoba("ア イ ウ")` with the same seed.
- **Issue 3 (`synthesize_tsukinami` cold vs warm cache consistency)** — **PASS**:
  - `synthesize_tsukinami("ツキナミ", preset="default", sr=16000, cache_dir=d)` cold call vs warm cache hit returns bit-identical waveforms (`np.array_equal(w1, w2) == True`, `max_abs_diff == 0.0`) and identical moras, while skipping `carve.make` on warm hit (verified via `unittest.mock.patch`).
  - Verified bit-identical cold vs warm cache hits at `sr=8000` and `sr=44100` as well.

### 2. Subtle `_sanitize_whitespace` & Adversarial Edge Cases — **PASS**
- **Cache key normalization**: `"ア"`, `" ア "`, `"ア\n"`, `"\tア\r\n"`, `"　ア　"`, `" \t　ア\n　 "` all map to the exact same cache entry (only 2 files created in `cache_dir`: 1 `.wav` + 1 `.json`), skip `carve.make` on subsequent variants, and return bit-identical waveforms & moras.
- **Inter-kana full-width space & control whitespace**: `synthesize_tsukinami("ア　イ")` and `synthesize_tsukinami("ア\tイ\n")` share the same cache entry, return bit-identical audio, and produce moras `['ア', 'イ']`.
- **Hostile/symbol inputs**: Probed `"'"`, `"0"`, `"/"`, `"|"`, `"?"`, `"？"`, `"   '   "`, `"ッ'ッ"`, `"ー"`, `"ーーー"`, `"ッー"`, `"、ー"`, `"ァ"`, `"ン"`, `"。"`, `"！"`, `"abc"`, `"123"`, `"ア'イ"`, `"ツキナミ？"` on both `synthesize_tsukinami` and `synthesize_fast_kotoba`. Zero unhandled crashes: non-speakable inputs raise `ValueError` in `synthesize_tsukinami`, and speakable inputs produce finite `float32` audio.

### 3. Core Invariants — **PASS**
- **Phonetic distinctiveness**:
  - Vowels (`ア`, `イ`, `ウ`, `エ`, `オ`): minimum pairwise un-normalized log-Mel L2 distance is `6.09` (`イ` vs `エ`), well above threshold.
  - Fricative onset (>3 kHz) energy ratios: `サ` (`0.998`) >> `ア` (`0.154`), `シ` (`0.844`) > `イ` (`0.665`), `ハ` (`0.304`) > `ア` (`0.154`).
- **Speed**: Synthesized all **150** utterances in `BUILTIN_CORPUS` via `synthesize_fast_kotoba` in **0.543 s** (`< 5.0 s`), all finite 1D `float32` in `[-1.0, 1.0]` with non-empty moras.
- **Immutability**: `yomu.PRESETS` and caller `overrides` (including nested dicts) remain completely unmutated after `synthesize_tsukinami`.
- **Determinism**: `generate_dataset` for both `engine="fast"` and `engine="mixed"` produces bit-identical `train.jsonl`, `val.jsonl`, and all WAV file bytes across repeated seeded runs.

---

VERDICT: CONFIRMED
