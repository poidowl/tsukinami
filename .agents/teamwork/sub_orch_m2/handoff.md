# Milestone M2 Completion Handoff (`sub_orch_m2`)

## Summary
Milestone M2 (**Built-in Speech Data & Corpus Pipeline**) passed the strict Project Pattern verification gate on **Iteration 2** with zero off-limits file modifications.

## Deliverables Created (Exclusive File Ownership)
1. [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py)
   - **Built-in Corpus**: 150 unique katakana utterances (`TRAIN_CORPUS`: 120, `VAL_CORPUS`: 30 strictly disjoint with 100% character coverage in `TRAIN_CORPUS`, `BUILTIN_CORPUS`: 150) covering greetings, commands, digits/time, everyday/tech vocabulary, and special moras (`ン`, `ッ`, `ー`, palatalized kana, pauses), fully lossless under `Tokenizer(mode="kana")` and `kotoba.tracks_from_kana()`.
   - **`synthesize_fast_kotoba(text, *, sr=16000, f0_scale=1.0, fscale=1.0, rate=1.0, snr_db=None, seed=None)`**: Vectorized zero-Python-loop NumPy 50%-COLA Hann overlap-add formant-track synthesizer driven directly by `kotoba.tracks_from_kana()` (phase-continuous Gaussian glottal excitation + lip radiation, parallel Lorentzian F1/F2/F3 resonators, fricative/burst noise bands, silence-gated envelope, optional white noise via `asr.audio.apply_corruption`). Synthesizes 150 utterances in `~0.54 s` (`< 5.0 s` budget) with distinct vowel formant peaks and fricative HF energy.
   - **`synthesize_tsukinami(text, *, preset="default", sr=16000, overrides=None, cache_dir=None)`**: Wraps `yomu.build_carve_rc` + `carve.make` + `yomu.boost_low_pitch_rms` across all `yomu.PRESETS`, deep-copies presets and caller `overrides` (no global/caller mutation), resamples 44.1 kHz -> `sr` via `asr.audio.resample`, and provides SHA-256 keyed atomic disk caching (temp file + `os.replace`, cold-write reload for bit-identical cold/warm waveforms).
   - **`generate_dataset(out_dir, *, num_train=200, num_val=40, engine="fast", seed=42, presets=None)`**: Supports `engine` in `{"fast", "tsukinami", "mixed"}`, writes 16 kHz WAVs + `train.jsonl` and `val.jsonl` with exact schema `{"audio_path", "text", "duration", "speaker", "source", "moras"}` (`{"t", "a", "e"}`), and returns `{"train": Path, "val": Path}` deterministically under `seed`.
2. [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py)
   - **`load_manifest` / `write_manifest`**: Strict UTF-8 JSONL validation.
   - **`ASRManifestDataset(manifest_path, audio_cfg=None, tokenizer=None, augment=False, ...)`**: PyTorch `Dataset` resolving manifest-relative and absolute audio paths (CWD-independent), loading audio via `asr.audio.load_wav`, extracting log-Mel features via `asr.features.extract_log_mel` (+ optional `spec_augment`), and encoding targets via `tokenizer.encode`.
   - **`collate_asr_batch(items) -> dict`**: Pads variable-length batches to `feats: float32[B, T_max, F]`, `feat_lengths: long[B]`, `targets: long[B, L_max]` (blank-padded `0`), `target_lengths: long[B]`, `texts: list[str]`. Verified directly with PyTorch `DataLoader` (`num_workers=0, 2`) and `nn.CTCLoss(blank=0, zero_infinity=True)` forward/backward.
   - **`build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path, ...) -> Path`**: Tier 3 helper supporting Python `Mapping`, `.json`, `.tsv`, JSUT `id:text`, and Kaldi `id text`, validating WAVs via `load_wav` and strictly rejecting non-`str` transcript values.
3. [`tests/test_asr_data.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_data.py)
   - 19 unit tests covering corpus validity, phonetic vowel/fricative distinctiveness, speaker/rate/SNR/seed determinism, 100-utterance `<5s` benchmark, all 6 core `tsukinami` presets, atomic disk caching (cold vs warm `np.array_equal`), dataset generation (`fast`/`tsukinami`/`mixed`), `ASRManifestDataset` + `collate_asr_batch` + `DataLoader` + `nn.CTCLoss`, `build_manifest_from_wav_dir`, and hostile edge cases.

## Verification & Gate Summary
- **Iteration 1**: Explorers (3/3) -> Worker -> 5-verifier wave. Auditor CLEAN, both Reviewers APPROVE, Challenger 2 CONFIRMED, Challenger 1 caught 3 concrete edge-case bugs in `asr/synth_data.py` (`synthesize_tsukinami("ッ")` `IndexError`, `synthesize_fast_kotoba("   \t\n  ")` control-whitespace moras, cold-vs-warm cache 16-bit PCM quantization mismatch).
- **Iteration 2**: Worker fixed all 3 bugs + minor nits + regression tests -> 5 fresh verifiers:
  - **Forensic Auditor (`iter2_auditor`)**: `VERDICT: CLEAN` — `.venv/bin/pytest tests/test_asr_data.py -v` (`19 passed in 62.20s`), `git diff --stat` empty (zero existing TTS/M1/M4/`tests_e2e/` files touched).
  - **Primary Reviewer (`iter2_rev1`)**: `VERDICT: APPROVE` — `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py -v` (`64 passed in 60.93s`).
  - **Secondary Reviewer (`iter2_rev2`)**: `VERDICT: APPROVE` — `.venv/bin/pytest tests/test_asr_data.py -v` (`19 passed in 63.43s`).
  - **Challenger 1 (`iter2_chal1`)**: `VERDICT: CONFIRMED` — all 3 Iter 1 bugs verified fixed + phonetic/speed/immutability/determinism probes pass (`150` utterances in `0.543 s`).
  - **Challenger 2 (`iter2_chal2`)**: `VERDICT: CONFIRMED` — strict non-`str` rejection, CWD independence, `DataLoader` + `nn.CTCLoss`, and hostile manifest probes pass.
- **Gate Status**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m2/GATE_STATUS.md` (**PASS**).
