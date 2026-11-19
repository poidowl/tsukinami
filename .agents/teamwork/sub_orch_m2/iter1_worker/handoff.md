# M2 Worker Handoff — Built-in Speech Data & Corpus Pipeline

## Summary of Changes

Implemented the complete Milestone M2 3-tier Japanese speech data and PyTorch dataset pipeline strictly within the assigned exclusive file ownership:

1. **`asr/synth_data.py`** (created):
   - **Built-in Japanese Katakana Corpus**: `TRAIN_CORPUS` (120 utterances across greetings, voice commands, digits/time, everyday/nature/tech words, and phonetically balanced/special-mora sentences), `VAL_CORPUS` (30 strictly disjoint utterances with 100% character coverage in `TRAIN_CORPUS`), and `BUILTIN_CORPUS` (150 unique utterances). All entries round-trip losslessly through `Tokenizer(mode="kana")` and `kotoba.tracks_from_kana()`.
   - **Tier 1 — `synthesize_fast_kotoba(text, *, sr=16000, f0_scale=1.0, fscale=1.0, rate=1.0, snr_db=None, seed=None)`**:
     - Vectorized NumPy 50%-overlap-add synthesizer driven directly by `kotoba.tracks_from_kana()` (5 ms formant/voicing/noise/loudness tracks).
     - Phase-continuous alias-free Gaussian glottal pulse train with lip-radiation derivative, parallel F1/F2/F3 Lorentzian formant resonators with Klatt-like bandwidths, fricative/stop-burst consonant noise bands, smooth silence gating for clean VAD compatibility, and optional additive white noise via `asr.audio.apply_corruption`.
     - Safely handles empty/whitespace/punctuation/sokuon-only edge cases without crashing `kotoba`.
     - Synthesizes 100 diverse 16 kHz utterances well under the 5 s budget.
   - **Tier 2 — `synthesize_tsukinami(text, *, preset="default", sr=16000, overrides=None, cache_dir=None)`**:
     - Wraps `yomu.build_carve_rc` + `carve.make` + `yomu.boost_low_pitch_rms`, supports all `yomu.PRESETS` (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`), resamples 44.1 kHz -> `sr`, and supports deterministic atomic disk caching (`.wav` + `.json` via temp files + `os.replace`) when `cache_dir` is provided.
     - Deep-copies presets and caller `overrides` so globals and caller dicts are never mutated.
   - **`generate_dataset(out_dir, *, num_train=200, num_val=40, engine="fast", seed=42, presets=None)`**:
     - Supports `engine` in `{"fast", "tsukinami", "mixed"}`, writes 16 kHz WAVs under `audio/{train,val}/` and `train.jsonl` / `val.jsonl` with relative POSIX `audio_path` and exact schema `{"audio_path", "text", "duration", "speaker", "source", "moras"}`, and returns `{"train": Path, "val": Path}`.

2. **`asr/dataset.py`** (created):
   - `load_manifest` / `write_manifest`: UTF-8 JSONL I/O with strict schema validation.
   - `ASRManifestDataset(manifest_path, audio_cfg=None, tokenizer=None, augment=False)`: PyTorch `Dataset` resolving manifest-relative and absolute audio paths, loading audio via `asr.audio.load_wav`, extracting log-Mel features via `asr.features.extract_log_mel`, optionally applying `asr.features.spec_augment`, and encoding targets via `tokenizer.encode`.
   - `collate_asr_batch(items) -> dict`: pads variable-length features (zero-padded) and targets (blank-padded `0`) into `{"feats": [B, T_max, F], "feat_lengths": [B], "targets": [B, L_max], "target_lengths": [B], "texts": list[str]}`, verified directly with `torch.nn.CTCLoss`.
   - `build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path)`: Tier 3 real-audio manifest builder supporting Python dicts, `.json`, `.tsv`, JSUT `id:text`, and Kaldi `id text` files, matching by relative POSIX path, filename, or stem.

3. **`tests/test_asr_data.py`** (created):
   - 19 unit tests covering built-in corpus invariants, phonetic vowel/fricative distinctiveness, speaker/rate/SNR/seed controls, edge cases, 100-utterance `<5s` speed benchmark, all 6 core `tsukinami` presets, overrides & immutability, atomic disk cache hit/miss, `generate_dataset` (`fast`, `tsukinami`, `mixed`, determinism, errors), `ASRManifestDataset` + `collate_asr_batch` + `DataLoader` + `nn.CTCLoss`, and `build_manifest_from_wav_dir` across all formats and error cases.

## Files Created / Modified

- Created: `asr/synth_data.py`
- Created: `asr/dataset.py`
- Created: `tests/test_asr_data.py`
- Existing tracked TTS files and M1/M4 files: untouched (`git diff --stat` is empty).

## Verification Commands & Outputs

### 1. `.venv/bin/pytest tests/test_asr_data.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 19 items

tests/test_asr_data.py ...................                               [100%]

============================= 19 passed in 41.99s ==============================
```

### 2. `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 64 items

tests/test_asr_dsp.py .............................................      [ 70%]
tests/test_asr_data.py ...................                               [100%]

============================= 64 passed in 43.20s ==============================
```

### 3. `git status --short` & `git diff --stat`
```text
$ git status --short
?? .agents/
?? .gitignore
?? PROJECT.md
?? TEST_INFRA.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/

$ git diff --stat
(empty)
```
