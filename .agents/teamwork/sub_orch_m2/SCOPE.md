# Milestone M2 Scope: Built-in Speech Data & Corpus Pipeline

## Deliverables (Exclusive Ownership)

### 1. `asr/synth_data.py`
- Built-in diverse Japanese kana phrase / word / digit / command corpus (enough variety for real train/val generalization splits, using `kotoba.py`-compatible kana).
- `synthesize_fast_kotoba(text: str, *, sr: int = 16000, f0_scale: float = 1.0, fscale: float = 1.0, rate: float = 1.0, snr_db: float | None = None, seed: int | None = None) -> tuple[np.ndarray, list[dict]]`:
  - Vectorized NumPy formant-track synthesizer driven directly by `kotoba.tracks_from_kana()` (5 ms formant/voicing/noise/loudness tracks + exact mora boundaries `{"t", "a", "e"}`).
  - Must be genuinely phonetic: distinct formant resonances (F1/F2/F3) for vowels + voicing pulse/glottal excitation + fricative/consonant noise bands + envelope shaping.
  - Must be FAST: generate 100+ diverse 16 kHz utterances in `<5s` on a 2-core CPU.
  - Returns `(wav_float32, moras)` where `wav_float32` is 1D `np.float32` in `[-1.0, 1.0]` and each mora dict has `{"t", "a", "e"}`.
- `synthesize_tsukinami(text: str, *, preset: str = "default", sr: int = 16000, overrides: dict | None = None, cache_dir: str | Path | None = None) -> tuple[np.ndarray, list[dict]]`:
  - Wraps `yomu.build_carve_rc` + `carve.make` across presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, etc.), resamples 44.1 kHz -> `sr`, and supports optional disk caching.
  - Returns `(wav_float32, moras)` where each mora dict has `{"t", "a", "e"}`.
- `generate_dataset(out_dir: str | Path, *, num_train: int = 200, num_val: int = 40, engine: str = "fast", seed: int = 42, presets: Sequence[str] | None = None) -> dict[str, Path]`:
  - Supports `engine` in `{"fast", "tsukinami", "mixed"}`.
  - Writes `train.jsonl`, `val.jsonl`, and WAV files under `out_dir`; returns `{"train": Path, "val": Path}`.
  - JSONL record schema: `{"audio_path": ..., "text": ..., "duration": ..., "speaker": ..., "source": ..., "moras": [{"t": ..., "a": ..., "e": ...}]}`.

### 2. `asr/dataset.py`
- `ASRManifestDataset(manifest_path, audio_cfg, tokenizer, augment=False)`:
  - PyTorch `Dataset` loading audio from manifest, extracting log-Mel features via `asr.features.extract_log_mel` (and applying `spec_augment` when `augment=True`), encoding text via `tokenizer.encode`, returning features, lengths, targets, text (and/or metadata compatible with `collate_asr_batch`).
- `collate_asr_batch(items) -> dict`:
  - Returns `feats: Tensor[B, T_max, F]`, `feat_lengths: Tensor[B]`, `targets: Tensor[B, L_max]`, `target_lengths: Tensor[B]`, `texts: list[str]`.
- `build_manifest_from_wav_dir(wav_dir, transcript_map, out_manifest_path) -> Path`:
  - Tier 3 real-audio & external corpus manifest helper.

### 3. `tests/test_asr_data.py`
- Thorough unit tests covering:
  - Built-in corpus diversity, kana validity, train/val split behavior
  - `synthesize_fast_kotoba`: phonetic formant distinctiveness across vowels, voicing/noise, `f0_scale`/`fscale`/`rate`/`snr_db`/`seed` determinism, mora boundary schema & timing, speed benchmark (100+ utterances in <5s)
  - `synthesize_tsukinami`: preset support (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`), overrides, resampling to 16 kHz, disk caching hit/miss behavior, mora boundaries
  - `generate_dataset`: `fast`, `tsukinami`, `mixed` engines, JSONL schema, WAV readability, determinism with `seed`
  - `ASRManifestDataset` & `collate_asr_batch`: shapes, dtypes, padding, `augment=True/False`, PyTorch `DataLoader` integration
  - `build_manifest_from_wav_dir`: manifest generation from WAV directory + transcript map, error handling for missing/invalid entries
