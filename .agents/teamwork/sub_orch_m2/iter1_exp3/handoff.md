# Explorer Handoff: `asr/dataset.py` & `tests/test_asr_data.py` Design

## 1. M1 Codebase Findings & Conventions

Inspected:
- `pyproject.toml`: Python >= 3.11, `.venv` has `torch 2.15.0+cpu` and `numpy 2.4.6`. `pytest` runs with `pythonpath = ["."]`, `testpaths = ["tests"]`, `addopts = "-q"`.
- `asr/__init__.py`: Re-exports M1 public APIs. **Do NOT modify `asr/__init__.py` in M2** because `SCOPE.md` assigns exclusive ownership of `asr/synth_data.py`, `asr/dataset.py`, and `tests/test_asr_data.py` (M4 is running concurrently).
- `asr/config.py`: `AudioConfig(sample_rate=16000, n_fft=512, win_length=400, hop_length=160, n_mels=64, f_min=80.0, f_max=7600.0, preemphasis=0.97, cmvn=True)`. All configs use `from __future__ import annotations`, strict validation raising `ValueError`/`TypeError`.
- `asr/audio.py`:
  - `load_wav(path: str | Path, target_sr: int = 16000) -> tuple[np.ndarray, int]`: returns 1D `np.float32` mono in `[-1.0, 1.0]` at `target_sr`. Raises `FileNotFoundError` if missing, `ValueError` if directory/empty/corrupt.
  - `save_wav(path: str | Path, wav: np.ndarray, sr: int = 16000) -> None`: writes 16-bit mono PCM WAV, auto-creates parent dirs.
- `asr/features.py`:
  - `extract_log_mel(wav: np.ndarray, cfg: AudioConfig | None = None) -> np.ndarray`: returns `np.float32` shape `(T, cfg.n_mels)`, guaranteed `T >= 1` even for very short audio.
  - `spec_augment(mel: np.ndarray, freq_mask_param: int = 8, time_mask_param: int = 20, num_freq_masks: int = 2, num_time_masks: int = 2, seed: int | None = None) -> np.ndarray`: non-mutating, returns `np.float32` `(T, F)`, uses `np.random.default_rng(seed)` (fresh entropy when `seed=None`).
- `asr/tokenizer.py`:
  - `Tokenizer(mode: str = "kana", vocab: list[str] | None = None)` with `blank_id == 0`, `vocab_size` (86 for `"kana"`, 29 for `"phoneme"`, 42 for `"ascii"`).
  - `encode(text: str) -> list[int]` returns non-blank token IDs (may return `[]` if text has only unknown/empty characters).
  - `decode(ids: Sequence[int], collapse_ctc: bool = False) -> str`.
- `yomu.py`: Built-in presets are `"default"`, `"ossan"`, `"robot"`, `"horror"`, `"whisper"`, `"chibi"`, `"utahime"`, `"choir"`.
- `tests/test_asr_dsp.py`: Organized into numbered sections, uses `tmp_path`, `pytest.mark.parametrize`, deterministic seeds, and exact dtype/shape/value/error assertions.

---

## 2. Detailed Design for `asr/dataset.py`

### Module Exports (`__all__`)
- `load_manifest`
- `write_manifest`
- `ASRManifestDataset`
- `collate_asr_batch`
- `build_manifest_from_wav_dir`

### 2.1 Manifest I/O Helpers

```python
def load_manifest(manifest_path: str | Path) -> list[dict[str, Any]]:
```
- Validates `p = Path(manifest_path)`:
  - Missing -> `FileNotFoundError(f"Manifest not found: {p}")`
  - Directory -> `ValueError(f"Manifest path is a directory: {p}")`
- Reads UTF-8 lines; skips empty/whitespace-only lines.
- Parses each non-empty line via `json.loads`:
  - `json.JSONDecodeError` -> `ValueError(f"Malformed JSONL at {p}:{line_no}: {exc}") from exc`
  - `not isinstance(obj, dict)` -> `ValueError(f"Expected JSON object at {p}:{line_no}, got {type(obj).__name__}")`
- Validates required fields:
  - `"audio_path"` must be a non-empty `str` (`audio_path.strip() != ""`).
  - `"text"` must be a `str`.
  - Otherwise raises `ValueError` with `{p}:{line_no}`.
- Returns `list[dict[str, Any]]`.

```python
def write_manifest(
    records: Sequence[Mapping[str, Any]],
    manifest_path: str | Path,
) -> Path:
```
- Creates `out.parent.mkdir(parents=True, exist_ok=True)`.
- Writes one JSON object per line with `json.dumps(dict(rec), ensure_ascii=False)` in UTF-8.
- Returns `Path(manifest_path)`.

### 2.2 Path Resolution Helper

```python
def _resolve_audio_path(raw_audio_path: str, manifest_dir: Path) -> Path:
```
1. `p = Path(raw_audio_path)`
2. If `p.is_absolute()`: return `p`
3. `rel = manifest_dir / p`
4. If `rel.exists()`: return `rel.resolve()`
5. If `p.exists()`: return `p.resolve()` (convenience fallback if manifest stored CWD-relative path)
6. Return `rel` (so downstream `FileNotFoundError` reports the expected manifest-relative path clearly).

### 2.3 `ASRManifestDataset`

```python
class ASRManifestDataset(Dataset):
    def __init__(
        self,
        manifest_path: str | Path,
        audio_cfg: AudioConfig | None = None,
        tokenizer: Tokenizer | None = None,
        augment: bool = False,
        *,
        spec_augment_kwargs: Mapping[str, Any] | None = None,
        validate_files: bool = True,
        allow_empty_targets: bool = False,
    ) -> None:
```
- Positional/keyword compatibility: `ASRManifestDataset(manifest_path, audio_cfg, tokenizer, augment=False)` matches `PROJECT.md` and `SCOPE.md` exactly.
- Defaults: `self.audio_cfg = audio_cfg if audio_cfg is not None else AudioConfig()`, `self.tokenizer = tokenizer if tokenizer is not None else Tokenizer("kana")`, `self.augment = bool(augment)`.
- Loads records via `load_manifest(manifest_path)`.
- If `len(raw_records) == 0`: raises `ValueError(f"Manifest contains no records: {manifest_path}")`.
- For each record (with 1-based index for error messages):
  - Resolves `resolved_path = _resolve_audio_path(rec["audio_path"], self.manifest_path.parent)`.
  - If `validate_files` and not `resolved_path.is_file()`:
    - If `resolved_path.is_dir()`: raise `ValueError(f"Audio path is a directory: {resolved_path}")`
    - Else: raise `FileNotFoundError(f"Audio file not found: {resolved_path}")`
  - Pre-encodes `target_ids = self.tokenizer.encode(rec["text"])`.
  - If `not allow_empty_targets and len(target_ids) == 0`:
    - Raise `ValueError(f"Empty encoded target for text={rec['text']!r} (record {idx} in {self.manifest_path})")`.
  - Stores normalized internal entry:
    - `audio_path`: `resolved_path` (`Path`)
    - `text`: `rec["text"]` (`str`)
    - `target_ids`: `target_ids` (`list[int]`)
    - `duration`: `rec.get("duration")`
    - `speaker`: `rec.get("speaker", "unknown")`
    - `source`: `rec.get("source", "unknown")`
    - `moras`: `rec.get("moras", [])`

```python
def __len__(self) -> int:
    return len(self._items)

def __getitem__(self, idx: int) -> dict[str, Any]:
```
1. `entry = self._items[idx]` (supports negative indexing natively).
2. `wav, _ = load_wav(entry["audio_path"], target_sr=self.audio_cfg.sample_rate)`
3. `mel = extract_log_mel(wav, self.audio_cfg)` -> `np.float32` shape `(T, F)`.
4. If `self.augment`: `mel = spec_augment(mel, **self._spec_augment_kwargs)`.
5. `feats = torch.from_numpy(np.ascontiguousarray(mel, dtype=np.float32))` -> `torch.float32` `[T, F]`.
6. `targets = torch.tensor(entry["target_ids"], dtype=torch.long)` -> `torch.long` `[L]`.
7. Returns:
```python
{
    "feats": feats,                         # torch.float32 [T, F]
    "feat_length": int(feats.shape[0]),     # int
    "targets": targets,                     # torch.long [L]
    "target_length": int(targets.shape[0]), # int
    "text": entry["text"],                  # str
    "audio_path": str(entry["audio_path"]), # str
}
```

### 2.4 `collate_asr_batch`

```python
def collate_asr_batch(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
```
- If `len(items) == 0`: raises `ValueError("Cannot collate an empty batch")`.
- Converts each item's `feats` via `torch.as_tensor(item["feats"], dtype=torch.float32)` and validates `ndim == 2` and consistent feature dimension `F` across all items (raises `ValueError` on mismatch).
- Converts each item's `targets` via `torch.as_tensor(item["targets"], dtype=torch.long)` and validates `ndim == 1`.
- Computes:
  - `B = len(items)`
  - `feat_lens = [int(f.shape[0]) for f in feat_list]`
  - `target_lens = [int(t.shape[0]) for t in target_list]`
  - `t_max = max(feat_lens)`
  - `l_max = max(target_lens)` (handles `0` cleanly -> `[B, 0]`)
- Allocates:
  - `feats_padded = torch.zeros((B, t_max, F), dtype=torch.float32)`
  - `targets_padded = torch.zeros((B, l_max), dtype=torch.long)` (padded with `0` == `blank_id`)
- Copies each sequence into `feats_padded[i, :t_len, :]` and `targets_padded[i, :l_len]`.
- Returns exact contract dict:
```python
{
    "feats": feats_padded,                                    # torch.float32 [B, T_max, F]
    "feat_lengths": torch.tensor(feat_lens, dtype=torch.long),    # torch.long [B]
    "targets": targets_padded,                                # torch.long [B, L_max]
    "target_lengths": torch.tensor(target_lens, dtype=torch.long),# torch.long [B]
    "texts": [str(item["text"]) for item in items],           # list[str]
}
```
- **PyTorch `nn.CTCLoss` compatibility**:
  - `nn.CTCLoss(blank=0, zero_infinity=True)` accepts 2D `targets` of shape `(B, L_max)` with `target_lengths` of shape `(B,)` and `input_lengths` of shape `(B,)`, slicing each row to `target_lengths[i]` and ignoring padded `0`s.
  - Works seamlessly with `torch.utils.data.DataLoader(dataset, batch_size=..., shuffle=..., collate_fn=collate_asr_batch)`.

### 2.5 `build_manifest_from_wav_dir`

```python
def build_manifest_from_wav_dir(
    wav_dir: str | Path,
    transcript_map: Mapping[str, str] | str | Path,
    out_manifest_path: str | Path,
    *,
    speaker: str = "custom",
    source: str = "wav_dir",
    target_sr: int = 16000,
) -> Path:
```
- Validates `wav_root = Path(wav_dir)`:
  - Missing -> `FileNotFoundError`
  - Not a directory -> `ValueError`
- Parses `transcript_map`:
  - If `isinstance(transcript_map, Mapping)`: copy `{str(k): str(v) for k, v in transcript_map.items()}`.
  - If `isinstance(transcript_map, (str, Path))`: load file (`FileNotFoundError` if missing, `ValueError` if dir/malformed):
    - `.json`: JSON object `dict[str, str]`.
    - `.tsv` / `.txt` / other text: per non-empty line, split on first `"\t"` if present; else if `":"` present and left side has no spaces (JSUT `transcript_utf8.txt` format `BASIC5000_0001:...`), split on first `":"`; else split on first whitespace (Kaldi `text` format). Raise `ValueError` if a non-empty line cannot be split into `(key, text)`.
  - Otherwise: raise `TypeError`.
- Discovers WAV files recursively under `wav_root` (`p.is_file() and p.suffix.lower() == ".wav"`), sorted by `p.relative_to(wav_root).as_posix()`.
- For each WAV file, looks up transcript in order:
  1. `rel_posix = wav_path.relative_to(wav_root).as_posix()` (e.g. `"sub/utt01.wav"`)
  2. `wav_path.name` (e.g. `"utt01.wav"`)
  3. `wav_path.stem` (e.g. `"utt01"`)
  - If unmatched, skip.
  - If matched:
    - `text = raw_text.strip()` -> if empty, raise `ValueError(f"Empty transcript for {wav_path.name}")`.
    - Validate WAV & compute duration via `wav, sr = load_wav(wav_path, target_sr=target_sr)` (raises `ValueError` on corrupt/empty WAV).
    - `duration = round(float(wav.size) / float(sr), 4)`
    - Resolve `audio_path` string to store in JSONL: if `wav_path.resolve()` is under `out_path.resolve().parent`, store relative POSIX path; otherwise store `str(wav_path.resolve())`.
    - Append standard schema record:
      `{"audio_path": ..., "text": text, "duration": duration, "speaker": speaker, "source": source, "moras": []}`.
- If 0 records matched: raise `ValueError(f"No matching WAV files found in {wav_root}")`.
- Writes JSONL via `write_manifest(records, out_manifest_path)` and returns `Path(out_manifest_path)`.

---

## 3. Comprehensive Test Suite Plan for `tests/test_asr_data.py`

Target total execution time: **< 10 seconds** on 2-core CPU, 100% deterministic, zero external downloads.

### Section 1: Built-in Japanese Corpus & Split
1. `test_builtin_corpus_diversity_and_kana_validity`:
   - Verify built-in corpus has broad variety (e.g., >= 50 unique utterances covering phrases, words, digits, commands, palatalized moras, `ン`/`ッ`/`ー`).
   - Verify every utterance encodes to non-empty IDs with `Tokenizer("kana")` and produces non-empty tracks via `kotoba.tracks_from_kana`.

### Section 2: `synthesize_fast_kotoba` (Tier 1)
2. `test_fast_kotoba_basic_schema_and_determinism`:
   - Output `(wav, moras)`: `wav.dtype == np.float32`, 1D, finite, `[-1.0, 1.0]`, non-silent (`rms > 0.01`).
   - `moras`: non-empty `list[dict]`, each has `{"t", "a", "e"}`, `0.0 <= a < e`, monotonic, `moras[-1]["e"]` matches `len(wav) / sr` within tolerance.
   - Same `seed` -> bit-exact identical `(wav, moras)`; different `seed` with `snr_db=15.0` -> different waveforms.
   - Hiragana and Katakana produce identical clean output with same seed.
3. `test_fast_kotoba_phonetic_vowel_and_fricative_distinctiveness`:
   - Synthesize `"アアア"`, `"イイイ"`, `"ウウウ"`, `"エエエ"`, `"オオオ"` with fixed seed.
   - Compute mean Log-Mel (`AudioConfig(cmvn=False)`) or FFT band energies:
     - All 5 vowels have pairwise distinct spectral profiles (min pairwise L2 distance > threshold).
     - `"ア"` has stronger low-mid F1 band (600–1000 Hz) than `"イ"`.
     - `"イ"` has stronger high-mid F2 band (1800–2800 Hz) than `"ウ"` / `"オ"`.
   - Synthesize `"シシシ"` vs `"アアア"`: `"シシシ"` has significantly higher high-frequency (>3000 Hz) to low-frequency (<1000 Hz) energy ratio (verifying fricative noise band).
4. `test_fast_kotoba_speaker_params_and_edge_cases`:
   - `f0_scale=0.7` vs `1.5`, `fscale=0.8` vs `1.25`, `rate=0.75` vs `1.35`, `snr_db=10.0` vs `None`, custom `sr=8000`.
   - Verify `fscale=1.25` increases spectral centroid relative to `fscale=0.8`.
   - Verify `rate` changes waveform duration and mora timestamps stay consistent with `len(wav) / sr`.
   - Verify invalid inputs (`sr <= 0`, `rate <= 0`, `f0_scale <= 0`, `fscale <= 0`, empty/unpronounceable text) raise `ValueError`.
5. `test_fast_kotoba_speed_benchmark`:
   - Synthesize 100 diverse utterances at 16 kHz and assert `elapsed < 5.0` seconds.

### Section 3: `synthesize_tsukinami` (Tier 2)
6. `test_tsukinami_presets_and_overrides`:
   - Short utterance `"アイ"` across presets `("default", "ossan", "robot", "horror", "whisper", "chibi")` at `sr=16000`.
   - Assert valid `float32` 1D waveform in `[-1.0, 1.0]`, non-silent, valid `moras` (`{"t", "a", "e"}`), duration consistent with resampled 16 kHz length.
   - Assert `"ossan"` != `"chibi"` and `overrides={"hz": 170.0, "fscale": 0.85}` differs from `"default"`.
   - Unknown preset raises `ValueError`.
7. `test_tsukinami_disk_cache_hit_and_miss`:
   - First call with `cache_dir=tmp_path / "tts_cache"` populates cache files.
   - Use `monkeypatch` to replace `carve.make` with a failing stub; second identical call succeeds from cache and returns matching `(wav, moras)` (`np.allclose` within 16-bit PCM quantization tolerance `1e-3`, exact `moras` equality).
   - Call with different `preset` or `overrides` triggers cache miss (reaches stub).

### Section 4: `generate_dataset`
8. `test_generate_dataset_fast_and_determinism`:
   - `generate_dataset(tmp_path / "ds1", num_train=8, num_val=4, engine="fast", seed=42)` and repeat into `ds2`.
   - Verify `{"train", "val"}` paths exist, exact line counts (8 and 4), full JSONL schema (`audio_path`, `text`, `duration`, `speaker`, `source`, `moras`), readable 16 kHz WAVs with matching duration, and deterministic parity between `ds1` and `ds2`.
9. `test_generate_dataset_tsukinami_mixed_and_errors`:
   - Tiny `engine="tsukinami"` (`num_train=2, num_val=1, presets=["default", "ossan"]`) and `engine="mixed"` (`num_train=4, num_val=2, presets=["default"]`).
   - Verify sources/speakers and readable WAVs.
   - Invalid `engine`, `num_train <= 0`, `num_val <= 0` raise `ValueError`.

### Section 5: `ASRManifestDataset`, `collate_asr_batch`, & `DataLoader`
10. `test_dataset_and_dataloader_integration`:
    - Generate small dataset (`num_train=6, num_val=2, engine="fast", seed=7`).
    - Verify `len(ds) == 6`, item keys/shapes/dtypes, negative indexing `ds[-1]`, determinism when `augment=False`, non-trivial masking when `augment=True`, and `Tokenizer("phoneme")` compatibility.
    - Verify `DataLoader(ds, batch_size=4, shuffle=False, collate_fn=collate_asr_batch)`:
      - Exact keys `{"feats", "feat_lengths", "targets", "target_lengths", "texts"}`.
      - Exact dtypes (`float32`, `long`, `long`, `long`, `list[str]`) and shapes (`[B, T_max, 64]`, `[B]`, `[B, L_max]`, `[B]`).
      - Zero-padding beyond `feat_lengths[i]` and blank-padding (`0`) beyond `target_lengths[i]`.
    - Pass collated batch into `torch.nn.CTCLoss(blank=0, zero_infinity=True)` with dummy `(T_max, B, vocab_size)` log-probs -> finite scalar loss.
11. `test_dataset_path_resolution_and_errors`:
    - Test both manifest-relative and absolute `audio_path` entries.
    - Test error cases: missing manifest (`FileNotFoundError`), malformed JSONL (`ValueError`), missing required keys (`ValueError`), empty manifest (`ValueError`), missing WAV (`FileNotFoundError`), empty encoded target (`ValueError`), `collate_asr_batch([])` (`ValueError`), feature-dim mismatch in `collate_asr_batch` (`ValueError`).

### Section 6: `build_manifest_from_wav_dir` (Tier 3)
12. `test_build_manifest_from_wav_dir_dict_and_files`:
    - Create WAVs in `wav_dir` (including a subdirectory and an unmatched WAV).
    - Test `dict` map keyed by filename (`"a.wav"`), stem (`"b"`), and relative path (`"sub/c.wav"`).
    - Verify returned `Path`, JSONL schema, accurate `duration`, and end-to-end loading into `ASRManifestDataset` + `DataLoader`.
    - Test file-based `transcript_map` for `.tsv`, `.txt` (JSUT `id:text` format), and `.json`.
13. `test_build_manifest_from_wav_dir_errors`:
    - Missing `wav_dir` (`FileNotFoundError`), file-as-`wav_dir` (`ValueError`), corrupt matched WAV (`ValueError`), no matching WAVs (`ValueError`), empty transcript (`ValueError`).

---

## 4. Verification Criteria
- `.venv/bin/pytest tests/test_asr_data.py tests/test_asr_dsp.py` passes 100% with 0 failures and 0 warnings of concern.
- Speed benchmark verifies 100+ `synthesize_fast_kotoba` 16 kHz utterances in `< 5s`.
- Existing TTS files remain completely unmodified (`git status`).
