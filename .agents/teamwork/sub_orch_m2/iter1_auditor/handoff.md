# Forensic Audit Report — Milestone M2 (Built-in Speech Data & Corpus Pipeline)

## Audit Classification
- **Type**: INTERMEDIATE MILESTONE AUDIT (Milestone M2)
- **Target Scope**:
  - `asr/synth_data.py`
  - `asr/dataset.py`
  - `tests/test_asr_data.py`

## 1. Working Tree Integrity
- Checked `git status --short` and `git diff --stat`:
  - `git diff --stat` is completely empty: zero existing tracked TTS files (`kotoba.py`, `accent.py`, `carve.py`, `yomu.py`, etc.) were modified.
  - Only the three M2 scope files (`asr/synth_data.py`, `asr/dataset.py`, `tests/test_asr_data.py`) were created by M2; M1 files, M4 files, and `tests_e2e/` were untouched.

## 2. Independent Test Verification
- Executed `.venv/bin/pytest tests/test_asr_data.py -v`:
  - **Result**: `19 passed in 63.19s` (exit code `0`).
- Executed independent temporary runtime probe (staged in `/tmp/teamwork_probe.XXXXXX` and removed on exit) instrumenting `kotoba.tracks_from_kana`, `yomu.build_carve_rc`, and `carve.make`:
  - 100 diverse utterances via `synthesize_fast_kotoba(BUILTIN_CORPUS[:100])` completed in **0.386 s** (`< 5.0 s` requirement), invoking `kotoba.tracks_from_kana` 100 times.
  - 1 utterance via `synthesize_tsukinami("ア", preset="default", sr=16000)` invoked `yomu.build_carve_rc` (1×), `carve.make` (1×), and `kotoba.tracks_from_kana` (1× internally via `carve.make`).

## 3. Anti-Cheating & Forensic Code Inspection

### `asr/synth_data.py`
- **Built-in Corpus**: `TRAIN_CORPUS` (120 phrases) and `VAL_CORPUS` (30 strictly disjoint phrases, 100% character subset of `TRAIN_CORPUS`) form `BUILTIN_CORPUS` (150 unique katakana utterances) covering greetings, commands, numbers, everyday words, and special moras (`ン`, `ッ`, `ー`, palatalized kana).
- **`synthesize_fast_kotoba`**:
  - Genuinely invokes `kotoba.tracks_from_kana(text, params=params)` (line 380) and uses the returned 5 ms `f0`, `voiced`, `F1`/`F2`/`F3`, `G1`/`G2`/`G3`, `bands`, `loud`, `dl`, and `moras` tracks.
  - Performs genuine vectorized DSP: phase-continuous alias-free Gaussian glottal pulse train with lip-radiation derivative (`pulse[1:] - 0.95 * pulse[:-1]`), voiced/unvoiced noise mixing, periodic-Hann 50%-overlap-add parallel Lorentzian formant resonators (`F1/F2/F3` with Klatt-like bandwidths `B1/B2/B3`), Gaussian frequency-domain fricative/stop-burst consonant bands, silence-gated loudness envelope, peak normalization, and optional SNR white noise via `asr.audio.apply_corruption`.
  - No hardcoded waveforms, sine-wave stubs, or lookup-table shortcuts.
- **`synthesize_tsukinami`**:
  - Genuinely wraps `yomu.build_carve_rc(text, prm)` (line 585), `carve.make(rc)` (line 589), and `yomu.boost_low_pitch_rms(samples, prm["hz"])` (line 590), resampling `carve.SR` (44.1 kHz) → `sr` via `asr.audio.resample`.
  - Deep-copies `yomu.PRESETS` and caller `overrides` (no mutation of globals or caller dicts), and implements deterministic SHA-256 atomic disk caching (`.wav` + `.json` via temp files + `os.replace`) when `cache_dir` is set.
- **`generate_dataset`**:
  - Genuine implementation supporting `engine` in `{"fast", "tsukinami", "mixed"}`, deterministic `seed`, preset validation, 16 kHz WAV generation, and exact JSONL schema `{"audio_path", "text", "duration", "speaker", "source", "moras"}`.

### `asr/dataset.py`
- **`load_manifest` / `write_manifest`**: Strict UTF-8 JSONL validation of `audio_path` and `text`.
- **`ASRManifestDataset`**: Genuine PyTorch `Dataset` resolving manifest-relative and absolute audio paths, loading audio via `asr.audio.load_wav`, extracting log-Mel features via `asr.features.extract_log_mel`, applying `asr.features.spec_augment` when `augment=True`, and encoding targets with `tokenizer.encode`.
- **`collate_asr_batch`**: Genuine variable-length batch padding returning `feats [B, T_max, F]` (zero-padded `float32`), `feat_lengths [B]` (`long`), `targets [B, L_max]` (blank-padded `long`), `target_lengths [B]` (`long`), and `texts: list[str]`.
- **`build_manifest_from_wav_dir`**: Genuine Tier 3 manifest builder supporting Python `Mapping`, `.json`, `.tsv`, JSUT `id:text`, and Kaldi `id text`, validating WAVs via `load_wav` and recording durations.

### `tests/test_asr_data.py`
- 19 unit tests with real, substantive assertions and zero skipped/xfail tests.
- Phonetic tests verify pairwise Log-Mel L2 distinctiveness across all 5 vowels, F1 `/a/ > /i/`, F2 `/i/ > /o/`, fricative `/sh/` vs `/a/` >3 kHz energy ratio, `fscale` spectral centroid shift, `f0_scale` autocorrelation pitch shift, `rate` duration/mora scaling, `snr_db` noise floor, and 100-utterance `< 5.0 s` speed benchmark.
- Only two `monkeypatch` usages, both completely legitimate:
  1. `test_tsukinami_disk_cache_hit_and_miss`: patches `carve.make` *after* initial real synthesis to prove cache hits skip synthesis and cache misses invoke `carve.make`.
  2. `test_generate_dataset_tsukinami_mixed_and_errors`: restricts `TRAIN_CORPUS`/`VAL_CORPUS` to short 1-mora strings so real `carve.make` synthesis inside `generate_dataset` runs quickly without mocking out synthesis.

## Verdict
VERDICT: CLEAN
