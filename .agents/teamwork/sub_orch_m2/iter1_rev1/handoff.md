# M2 Primary Reviewer Handoff — Built-in Speech Data & Corpus Pipeline

## Review Scope
Audited Milestone M2 deliverables against `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `.agents/teamwork/sub_orch_m2/SCOPE.md`:
- `asr/synth_data.py`
- `asr/dataset.py`
- `tests/test_asr_data.py`

## Independent Verification Outputs

### 1. M1 + M2 Test Suite
Command: `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 64 items

tests/test_asr_dsp.py .............................................      [ 70%]
tests/test_asr_data.py ...................                               [100%]

======================== 64 passed in 65.02s (0:01:05) =========================
```

### 2. Git Hygiene & File Ownership Check
Command: `git status --short && echo "---" && git diff --stat`
```text
?? .agents/
?? .gitignore
?? PROJECT.md
?? TEST_INFRA.md
?? TEST_READY.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/
---
```
- `git diff --stat` is empty: no existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, HTML demos, etc.) were modified.
- M2 files are strictly limited to `asr/synth_data.py`, `asr/dataset.py`, and `tests/test_asr_data.py`.

## Contract & Code Audit

### 1. `asr/synth_data.py`
- **Built-in Corpus (`TRAIN_CORPUS`, `VAL_CORPUS`, `BUILTIN_CORPUS`, lines 52–214)**:
  - 120 train + 30 strictly disjoint val katakana phrases (150 unique total), covering greetings, voice commands, digits/time, everyday/tech vocabulary, and phonetically balanced / special-mora (`ン`, `ッ`, `ー`, `ャ/ュ/ョ`, `、`) phrases.
  - 100% of validation characters appear in `TRAIN_CORPUS`, and every phrase round-trips losslessly through `Tokenizer("kana")` and `kotoba.tracks_from_kana()`.
- **`synthesize_fast_kotoba` (lines 322–508)**:
  - Exact signature & defaults: `(text: str, *, sr: int = 16000, f0_scale: float = 1.0, fscale: float = 1.0, rate: float = 1.0, snr_db: float | None = None, seed: int | None = None) -> tuple[np.ndarray, list[dict[str, Any]]]`.
  - Driven directly by `kotoba.tracks_from_kana()`, using vectorized 50%-overlap-add parallel Lorentzian F1/F2/F3 formant resonators, phase-continuous Gaussian glottal excitation with lip-radiation derivative, consonant fricative/burst noise bands, and smooth silence gating for VAD compatibility.
  - Cleanly reuses M1 `asr.audio.apply_corruption` for optional `snr_db` white noise.
  - Returns 1D `np.float32` in `[-1.0, 1.0]` and normalized mora dicts with exact keys `{"t", "a", "e"}`.
  - Passes the 100-utterance `<5s` CPU speed benchmark (`test_fast_kotoba_speed_benchmark`) and phonetic vowel/fricative distinctiveness checks.
- **`synthesize_tsukinami` (lines 516–625)**:
  - Exact signature & defaults: `(text: str, *, preset: str = "default", sr: int = 16000, overrides: dict[str, Any] | None = None, cache_dir: str | Path | None = None) -> tuple[np.ndarray, list[dict[str, Any]]]`.
  - Wraps `yomu.build_carve_rc` + `carve.make` + `yomu.boost_low_pitch_rms`, supports all `yomu.PRESETS`, deep-copies presets and caller `overrides` (no global or caller mutation), resamples 44.1 kHz -> `sr` via M1 `asr.audio.resample`, and implements SHA-256 keyed atomic disk caching (`.wav` + `.json` via temp file + `os.replace`) with graceful fallback on corrupted cache entries.
- **`generate_dataset` (lines 647–788)**:
  - Exact signature & defaults: `(out_dir: str | Path, *, num_train: int = 200, num_val: int = 40, engine: str = "fast", seed: int = 42, presets: Sequence[str] | None = None) -> dict[str, Path]`.
  - Supports `engine` in `{"fast", "tsukinami", "mixed"}`, writes 16 kHz WAVs under `audio/{train,val}/` and `train.jsonl` / `val.jsonl` with exact schema `{"audio_path", "text", "duration", "speaker", "source", "moras"}`, returns `{"train": Path, "val": Path}`, and is deterministic under `seed`.

### 2. `asr/dataset.py`
- **`ASRManifestDataset` (lines 89–174)**:
  - Matches contract `(manifest_path, audio_cfg=None, tokenizer=None, augment=False)` plus clean optional keyword args (`spec_augment_kwargs`, `validate_files`, `allow_empty_targets`).
  - Reuses M1 `asr.audio.load_wav`, `asr.config.AudioConfig`, `asr.features.extract_log_mel`, `asr.features.spec_augment`, and `asr.tokenizer.Tokenizer`.
  - Handles manifest-relative and absolute paths, strict JSONL schema validation, and empty-target rejection.
- **`collate_asr_batch` (lines 177–243)**:
  - Returns exact contract dictionary: `feats: float32[B, T_max, F]` (zero-padded), `feat_lengths: long[B]`, `targets: long[B, L_max]` (blank-padded `0`), `target_lengths: long[B]`, `texts: list[str]`.
  - Validates non-empty batch, tensor ranks, and consistent feature dimension; verified with `DataLoader` and `torch.nn.CTCLoss`.
- **`build_manifest_from_wav_dir` (lines 292–360)**:
  - Matches contract `(wav_dir, transcript_map, out_manifest_path, ...)` -> `Path`.
  - Supports Python `Mapping`, `.json`, `.tsv`, JSUT `id:text`, and Kaldi `id text`, matching by relative POSIX path, filename, or stem, and validates WAV readability via `load_wav`.

### 3. `tests/test_asr_data.py`
- 19 comprehensive unit tests covering every requirement in `SCOPE.md`: corpus diversity/validity, phonetic formant/fricative distinctiveness, speaker/rate/SNR/seed determinism, edge cases, 100-utterance `<5s` benchmark, all 6 core `tsukinami` presets, overrides/immutability, atomic cache hit/miss, `generate_dataset` across all 3 engines + determinism + error handling, `ASRManifestDataset` + `collate_asr_batch` + `DataLoader` + `nn.CTCLoss`, and `build_manifest_from_wav_dir` across all formats and error cases.

## Minor Non-Blocking Notes
1. `asr/synth_data.py:172`: `"キップヲカッテ、デパ地下ヘイク".replace("地下", "チカ")` produces valid katakana `"キップヲカッテ、デパチカヘイク"`, though a plain literal would be marginally cleaner.
2. `asr/synth_data.py:541`: `synthesize_tsukinami` guards against pause-only strings (`"、"`) but not sokuon-only strings (`"ッ"`), unlike `synthesize_fast_kotoba` (line 358). Low impact in practice.

VERDICT: APPROVE
