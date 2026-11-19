# M2 Secondary Technical Review Report (`iter1_rev2`)

## Scope & Files Audited
- `asr/synth_data.py` (789 lines)
- `asr/dataset.py` (361 lines)
- `tests/test_asr_data.py` (612 lines)
- Verified against `.agents/teamwork/ORIGINAL_REQUEST.md`, `PROJECT.md`, `.agents/teamwork/sub_orch_m2/SCOPE.md`, `kotoba.py`, `yomu.py`, and `asr/audio.py`.

## Independent Verification Results

### 1. Unit Tests: `.venv/bin/pytest tests/test_asr_data.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 19 items

tests/test_asr_data.py ...................                               [100%]

======================== 19 passed in 64.21s (0:01:04) =========================
```

### 2. Repository Integrity: `git status --short && git diff --stat`
- `git diff --stat` is empty; no existing tracked TTS files (`kotoba.py`, `yomu.py`, `carve.py`, `accent.py`, etc.) were modified.

---

## Technical Deep-Audit Findings

### 1. Tier 1 DSP & Phonetic Synthesis (`asr/synth_data.py:322-508` — `synthesize_fast_kotoba`)
- **Voicing excitation (`lines 393-424`)**: Sample-level phase-continuous F0 contour (`np.cumsum(2*pi*f0_s/sr)`), alias-free Gaussian glottal pulse (`sigma_s >= 1.2 * dphase`) with first-order lip-radiation derivative (`pulse[1:] - 0.95 * pulse[:-1]`), RMS-normalized and blended with aspiration/unvoiced noise via `vo_s`.
- **Formant resonance & overlap-add (`lines 426-475`)**: Periodic Hann window (`np.hanning(win_len + 1)[:-1]`) satisfies exact 50% COLA. Parallel F1/F2/F3 Lorentzian transfer functions use Klatt-like bandwidths (`B1/B2/B3`), `kotoba.tracks_from_kana()` per-formant gains (`G1/G2/G3`), and Nyquist-safe frequency clamping with `fscale`. Zero-loop even/odd OLA slicing is bounds-safe for both even and odd frame counts `n`.
- **Fricative & stop-burst noise bands (`lines 452-466`)**: Correctly converts `kotoba.tracks_from_kana()` `bands` timestamps (seconds) back to 5 ms frame indices and injects Gaussian-shaped spectral noise scaled by `fscale` and `gain`.
- **Envelope, VAD & SNR (`lines 477-507`)**: Smooth silence gate `np.clip((loud - (-28.0)) / 5.0, 0.0, 1.0)` cleanly suppresses pre/post silence (`sil = -30 dB` in `kotoba.py`) below VAD thresholds. Optional `snr_db` delegates cleanly to `asr.audio.apply_corruption(..., noise_type="white", seed=noise_seed)` with peak safety clipping to `[-1.0, 1.0]`.
- **Edge cases & mora boundaries (`lines 353-386`)**: Safely guards empty/whitespace/pause-only strings and sokuon-only strings that would otherwise trigger an empty-keypoint `IndexError` in `kotoba.build_tracks()`. Mora dicts are normalized to exact `{"t", "a", "e"}` schema. Speed benchmark (`100` utterances `< 5.0s`) passes cleanly.

### 2. Tier 2 Tsukinami Wrapper & Atomic Disk Cache (`asr/synth_data.py:516-625` — `synthesize_tsukinami`)
- **Preset & override immutability (`lines 572-588`)**: Deep-copies `yomu.PRESETS["default"]`, target preset, and caller `overrides`. Splits `_YOMU_PRM_KEYS` vs. `rc` overrides (supporting dotted keys via `_deep_merge_rc`). Never mutates globals or caller dicts.
- **Audio synthesis & resampling (`lines 589-598`)**: Calls `yomu.build_carve_rc`, `carve.make`, and `yomu.boost_low_pitch_rms`, then resamples `carve.SR` (44.1 kHz) to `sr` via `asr.audio.resample`, returning finite `float32` in `[-1.0, 1.0]` and normalized `{"t", "a", "e"}` moras.
- **Disk cache correctness & atomicity (`lines 547-571, 600-623`)**: SHA-256 cache key over canonicalized JSON (`v`, `text`, `preset`, `sr`, `overrides`). Writes `.wav` and `.json` to unique temp files and commits via `os.replace` in safe order (WAV before JSON), with temp-file cleanup on failure and automatic re-synthesis fallback if a cached entry is corrupted.

### 3. Dataset Generation (`asr/synth_data.py:633-788` — `generate_dataset`)
- **Corpus & split integrity (`lines 52-215`)**: `TRAIN_CORPUS` (120 unique phrases) and `VAL_CORPUS` (30 unique phrases) are strictly disjoint, with 100% of validation characters covered in `TRAIN_CORPUS` and full round-trip compatibility with `Tokenizer("kana")` and `kotoba.tracks_from_kana()`.
- **Determinism & schema (`lines 700-788`)**: Single seeded `np.random.default_rng(seed)` controls sampling, `mixed` engine split, preset cycling, speaker jitter, and per-utterance seeds. Produces exact JSONL schema `{"audio_path", "text", "duration", "speaker", "source", "moras"}` with relative POSIX audio paths and verified 16 kHz WAVs.

### 4. Manifest Dataset, Collation & Tier 3 Helper (`asr/dataset.py:28-360`)
- **`ASRManifestDataset` (`lines 89-174`)**: Validates manifest syntax, non-empty records, file existence (`validate_files=True`), and non-empty encoded targets (`allow_empty_targets=False`). Resolves both manifest-relative and absolute audio paths. Returns `float32 [T, F]` features (with optional `spec_augment`) and `long [L]` targets.
- **`collate_asr_batch` (`lines 177-243`)**: Validates non-empty batch, 2D features with matching feature dim, and 1D targets. Pads to `feats: float32 [B, T_max, F]`, `feat_lengths: long [B]`, `targets: long [B, L_max]` (blank-padded `0`), `target_lengths: long [B]`, `texts: list[str]`. Verified directly with `DataLoader` and `torch.nn.CTCLoss`.
- **`build_manifest_from_wav_dir` (`lines 246-360`)**: Supports Python `Mapping`, `.json`, `.tsv`, JSUT `id:text`, and Kaldi `id text`; matches by relative POSIX path, filename, or stem; validates WAV readability via `load_wav`; raises explicit `FileNotFoundError`/`ValueError` on missing directories, unmatched files, empty transcripts, or corrupt WAVs.

### Non-Blocking Note
- `asr/synth_data.py:172` uses `"キップヲカッテ、デパ地下ヘイク".replace("地下", "チカ")` instead of the direct literal `"キップヲカッテ、デパチカヘイク"`. It evaluates cleanly to valid katakana at import time and requires no action.

VERDICT: APPROVE
