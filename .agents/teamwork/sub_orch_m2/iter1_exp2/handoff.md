# Explorer 2 Handoff: Tier 2 Tsukinami TTS Wrapper & `generate_dataset`

## 1. Research Findings on Existing TTS & M1 DSP Code

### 1.1 `yomu.py`, `carve.py`, `accent.py`, `kotoba.py`
- **Available presets in `yomu.PRESETS`** (8 total):
  - Core speech presets: `"default"`, `"ossan"`, `"robot"`, `"horror"`, `"whisper"`, `"chibi"`.
  - Singing/trance presets: `"utahime"` (`uta_trance=True`), `"choir"` (`uta_trance=True, uta_choir=True`, runs 4 voice passes).
  - Recommended constant in `asr/synth_data.py`:
    - `DEFAULT_TSUKINAMI_PRESETS: tuple[str, ...] = ("default", "ossan", "robot", "horror", "whisper", "chibi")` (used as default pool in `generate_dataset`).
    - `synthesize_tsukinami` accepts **any** preset present in `yomu.PRESETS` (all 8).
- **Exact `yomu.build_carve_rc(text, prm)` behavior**:
  - Reads `S.txt` and `OO.txt` using `os.path.join(yomu.HERE, ...)` — completely CWD-independent.
  - Deep-copies `carve.E79` and calls `carve.variant(...)` (which JSON round-trips `BASE` and changes), so `carve.E79` and `carve.BASE` are never mutated.
  - Consumes `prm` keys: `seed` (int), `tsubu` (int), `hz` (float), `fscale` (float), `yure` (float), `shimmer` (float), `tadayoi` (float), `line_g` (float), `ap_n` (int), `rate` (float), plus optional `uta_trance` (bool), `uta_choir` (bool), `tr_iroke`.
  - If `text` contains any accent/phrase mark in `("'", "’", "0", "/", "|", " ", "　", "?", "？")`, calls `accent.annotate(text)` to strip marks into `clean_kana` and inject `phrases` + `question` into `r["kotoba"]["accent_kw"]`.
- **Exact `carve.make(rc)` behavior**:
  - When `rc.get("text")` is truthy, dispatches to `carve.make_text(rc)`.
  - Returns `(samples, raw_moras)`:
    - `samples`: Python `list[float]` mono at `carve.SR == 44100` Hz, peak <= `0.891` (`E79` uses `out_dbfs=-20`, capped at `0.891`).
    - `yomu.boost_low_pitch_rms(samples, prm["hz"])`: applied in `yomu.main()` when `float(prm["hz"]) < 220.0` (e.g., `ossan` 155 Hz, `horror` 195 Hz) using soft-knee `0.92 * tanh((v * gain) / 0.92)`. `synthesize_tsukinami` should apply this same boost so low-pitch presets have consistent RMS and match `yomu.py`.
    - `raw_moras`: `list[dict]` directly from `kotoba.tracks_from_kana()`, where each element has `{'t', 'kind', 'c', 'v', 'a', 'b', 'e'}` with `a` (start_sec) and `e` (end_sec) in seconds. Timestamps in seconds are invariant to 44.1 kHz -> `sr` resampling.
- **Critical edge cases verified empirically**:
  1. `text == ""`: `rc["text"]` is falsy, causing `carve.make(rc)` to fall back to the 6-second legacy babble synthesizer returning span tuples instead of mora dicts. **Fix**: validate non-empty speakable kana before calling `yomu.build_carve_rc`.
  2. Pause-only `text == "、"` or whitespace: `kotoba.split_moras` returns `[]` and `accent._targets` raises `IndexError`. **Fix**: validate that `kotoba.split_moras(clean_kana)` contains at least one mora `!= "、"`, else raise `ValueError`.
  3. Repo-root import safety: `asr/synth_data.py` should use the same fallback `sys.path` guard as `asr/tokenizer.py` when importing `kotoba`, `yomu`, `carve`, and `accent` so imports work even if invoked from another CWD.
- **CPU performance characteristics (measured on this 2-core machine)**:
  - 4-mora utterance (`"おはよう"`, ~1.5 s audio including `E79`'s `pre=0.6s`, `post=0.2s` at 44.1 kHz):
    - `default`: 4.22 s | `ossan`: 4.05 s | `robot`: 3.60 s | `horror`: 4.25 s | `whisper`: 4.28 s | `chibi`: 3.95 s.
  - Because each `carve.make()` call takes ~3.5–4.3 s on CPU:
    - Disk caching (`cache_dir`) in `synthesize_tsukinami` is high value for repeated evaluations, CLI, and Web Playground.
    - Unit tests in `tests/test_asr_data.py` should use very short kana (e.g. `"あ"`, `"あい"`, `"か"`) and small dataset counts (`num_train=2, num_val=1` for `tsukinami` and `num_train=4, num_val=2` for `mixed`) so the entire M2 test suite runs quickly and reliably.

### 1.2 M1 DSP Primitives to Reuse (`asr/audio.py`)
- `asr.audio.resample(wav, orig_sr, target_sr) -> np.ndarray`: exact FFT-based band-limited resampling returning 1D `np.float32`.
- `asr.audio.save_wav(path, wav, sr) -> None`: writes 16-bit signed PCM mono WAV, automatically creating parent directories and clipping to `[-1.0, 1.0]`.
- `asr.audio.load_wav(path, target_sr) -> tuple[np.ndarray, int]`: loads WAV as 1D `np.float32` in `[-1.0, 1.0]` at `target_sr`.

---

## 2. Implementation Plan

### 2.1 `synthesize_tsukinami` in `asr/synth_data.py`

```python
_YOMU_PRM_KEYS: frozenset[str] = frozenset({
    "seed", "tsubu", "hz", "fscale", "yure", "shimmer",
    "tadayoi", "line_g", "ap_n", "rate",
    "uta_trance", "uta_choir", "tr_iroke",
})

DEFAULT_TSUKINAMI_PRESETS: tuple[str, ...] = (
    "default", "ossan", "robot", "horror", "whisper", "chibi",
)

def synthesize_tsukinami(
    text: str,
    *,
    preset: str = "default",
    sr: int = 16000,
    overrides: dict[str, Any] | None = None,
    cache_dir: str | Path | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
```

#### Step-by-step behavior
1. **Validation**:
   - `sr`: if `isinstance(sr, bool) or not isinstance(sr, int) or sr <= 0`: raise `ValueError`.
   - `preset`: if `preset not in yomu.PRESETS`: raise `ValueError(f"Unknown tsukinami preset {preset!r}; available presets: {', '.join(sorted(yomu.PRESETS.keys()))}")`.
   - `text`: if `not isinstance(text, str) or not text.strip()`: raise `ValueError("text must be a non-empty string")`.
     - Check speakable moras: if `any(ch in text for ch in ("'", "’", "0", "/", "|", " ", "　", "?", "？"))`, run `clean_text, _ = accent.annotate(text)`, else `clean_text = text`. Verify `any(m != "、" for m in kotoba.split_moras(clean_text))`, else raise `ValueError("text must contain at least one speakable kana mora")`.
   - `overrides`: if `overrides is not None and not isinstance(overrides, Mapping)`: raise `TypeError` (or `ValueError`).
2. **Disk cache lookup (when `cache_dir is not None`)**:
   - Build canonical cache key:
     - Payload: `{"v": 1, "text": text, "preset": preset, "sr": int(sr), "overrides": _canonicalize_json(overrides or {})}`.
     - `digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]`.
     - `wav_path = Path(cache_dir) / f"tsukinami_{digest}.wav"`
     - `meta_path = Path(cache_dir) / f"tsukinami_{digest}.json"`
   - If both `wav_path.is_file()` and `meta_path.is_file()`:
     - Try loading `wav, _ = load_wav(wav_path, target_sr=sr)` and `meta = json.loads(meta_path.read_text(encoding="utf-8"))`.
     - Validate `isinstance(meta, dict)` and `isinstance(meta.get("moras"), list)`.
     - Return `(wav, meta["moras"])`. (On any read/parse error, fall through and re-synthesize.)
3. **Non-mutating parameter & `rc` construction**:
   - `prm = copy.deepcopy(yomu.PRESETS["default"])`
   - `prm.setdefault("uta_trance", False)`
   - `prm.setdefault("uta_choir", False)`
   - `prm.update(copy.deepcopy(yomu.PRESETS[preset]))`
   - Split `overrides` (deep-copied so caller dict is never mutated):
     - Keys in `_YOMU_PRM_KEYS` -> `prm[k] = copy.deepcopy(v)` BEFORE `yomu.build_carve_rc(text, prm)`.
     - Remaining keys -> `rc_overrides` applied AFTER `yomu.build_carve_rc(text, prm)` via `_deep_merge_rc(rc, rc_overrides)`:
       - Dotted keys (e.g. `"kotoba.pre"`, `"line.D_center"`) traverse/create nested dicts.
       - Nested dict values recursively merge into `rc[k]` if `isinstance(rc.get(k), dict)`.
       - Scalar/list values replace `rc[k]`.
   - Never mutate `yomu.PRESETS`, `carve.E79`, `carve.BASE`, or `overrides`.
4. **Synthesis, RMS boost, resampling, normalization**:
   - `samples, raw_moras = carve.make(rc)`
   - `samples = yomu.boost_low_pitch_rms(samples, prm["hz"])`
   - `wav = np.asarray(samples, dtype=np.float32)`
   - If `sr != carve.SR`: `wav = resample(wav, carve.SR, sr)`
   - `wav = np.clip(np.nan_to_num(wav, nan=0.0, posinf=1.0, neginf=-1.0), -1.0, 1.0).astype(np.float32, copy=False)`
   - Normalize moras:
     ```python
     moras = [
         {"t": str(m["t"]), "a": round(float(m["a"]), 6), "e": round(float(m["e"]), 6)}
         for m in raw_moras
     ]
     ```
5. **Atomic disk cache write (when `cache_dir is not None`)**:
   - `Path(cache_dir).mkdir(parents=True, exist_ok=True)`
   - Generate unique suffix `f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"`.
   - Write WAV via `save_wav(tmp_wav, wav, sr=sr)` then `os.replace(tmp_wav, wav_path)`.
   - Write JSON `{"v": 1, "text": text, "preset": preset, "sr": int(sr), "moras": moras}` to `tmp_meta` (UTF-8, `ensure_ascii=False`) then `os.replace(tmp_meta, meta_path)`.
   - Writing WAV before JSON guarantees that if `meta_path` exists, `wav_path` is already atomically committed. Clean up temp files in `except` on any error.
   - Return `(wav, moras)`.

---

### 2.2 `generate_dataset` in `asr/synth_data.py`

```python
VALID_ENGINES: tuple[str, ...] = ("fast", "tsukinami", "mixed")

def generate_dataset(
    out_dir: str | Path,
    *,
    num_train: int = 200,
    num_val: int = 40,
    engine: str = "fast",
    seed: int = 42,
    presets: Sequence[str] | None = None,
) -> dict[str, Path]:
```

#### Step-by-step behavior
1. **Validation**:
   - `engine`: if `engine not in VALID_ENGINES`: raise `ValueError(f"engine must be one of {VALID_ENGINES}, got {engine!r}")`.
   - `num_train`, `num_val`: reject `bool`, non-int, or `< 0` -> raise `ValueError`.
   - `presets`:
     - If `presets is None`: `preset_list = list(DEFAULT_TSUKINAMI_PRESETS)`.
     - Else: convert to `list(presets)`; if empty -> raise `ValueError("presets must be non-empty")`; validate every `p in yomu.PRESETS`, else raise `ValueError` listing unknown presets.
2. **Directory & path layout**:
   - `root = Path(out_dir)`
   - Create `root / "audio" / "train"` and `root / "audio" / "val"`.
   - WAV files: `audio/train/train_{i:05d}.wav`, `audio/val/val_{i:05d}.wav` at `sr = 16000`.
   - Manifests: `root / "train.jsonl"`, `root / "val.jsonl"`.
   - **CWD-independent `audio_path` contract**:
     - Store `audio_path` as relative POSIX path from `out_dir` (e.g. `"audio/train/train_00000.wav"`).
     - `ASRManifestDataset` in `asr/dataset.py` MUST resolve relative `audio_path` values against `manifest_path.parent` (while passing absolute paths through unchanged). This guarantees manifests work from any CWD and remain portable if `out_dir` is moved.
3. **Corpus split strategy & determinism**:
   - Use `rng = np.random.default_rng(seed)`.
   - Split the built-in Japanese kana corpus deterministically into disjoint `train_phrases` (~80%) and `val_phrases` (~20%) via a seeded permutation so validation evaluates generalization on held-out phrases. (If `num_train` > `len(train_phrases)`, cycle/sample with replacement using `rng` while varying speaker/synthesis parameters so every utterance is acoustically distinct.)
   - Store `"text"` in katakana (`kotoba.to_kata(phrase)`) for direct consistency with `Tokenizer(mode="kana")`.
4. **Per-engine synthesis & speaker randomization**:
   - **`engine == "fast"`**:
     - Define a small set of named fast speaker profiles (or sample continuous params per utterance):
       - `f0_scale = float(rng.uniform(0.75, 1.35))`
       - `fscale = float(rng.uniform(0.88, 1.18))`
       - `rate = float(rng.uniform(0.85, 1.20))`
       - `snr_db = None if rng.random() < 0.3 else float(rng.uniform(15.0, 35.0))`
       - `utt_seed = int(rng.integers(0, 2**31 - 1))`
     - Call `wav, moras = synthesize_fast_kotoba(text, sr=16000, f0_scale=f0_scale, fscale=fscale, rate=rate, snr_db=snr_db, seed=utt_seed)`.
     - `speaker = f"fast_spk_{int(rng.integers(0, 8))}"` (or derived from speaker profile index), `source = "kotoba_fast"`.
   - **`engine == "tsukinami"`**:
     - Choose `preset = preset_list[i % len(preset_list)]` (or `preset_list[int(rng.integers(0, len(preset_list)))]` — cycling after shuffling guarantees preset coverage even for small `num_train`/`num_val`).
     - `base_prm = yomu.PRESETS[preset]`
     - `utt_seed = int(rng.integers(0, 2**31 - 1))`
     - Small deterministic perturbation around preset defaults so repeated phrases/presets remain diverse while preserving preset identity:
       `overrides = {"seed": utt_seed, "hz": round(float(base_prm["hz"]) * float(rng.uniform(0.95, 1.05)), 2), "rate": round(float(base_prm["rate"]) * float(rng.uniform(0.95, 1.05)), 3)}`.
     - Call `wav, moras = synthesize_tsukinami(text, preset=preset, sr=16000, overrides=overrides)`.
     - `speaker = preset`, `source = "tsukinami"`.
   - **`engine == "mixed"`**:
     - Deterministic ~75% `kotoba_fast` / ~25% `tsukinami` schedule: e.g., for split of size `N`, mark `n_tsuki = max(1, N // 4) if N >= 2 else 0` (so any split with `N >= 2` is guaranteed to contain both `"kotoba_fast"` and `"tsukinami"` sources, even in small unit tests like `num_train=4, num_val=2`).
     - Shuffle the boolean mask with `rng` and synthesize each item with the corresponding engine above.
5. **Exact JSONL record schema**:
   ```json
   {
     "audio_path": "audio/train/train_00000.wav",
     "text": "ワタシ、ニホンゴ",
     "duration": 1.42,
     "speaker": "default",
     "source": "tsukinami",
     "moras": [{"t": "ワ", "a": 0.6, "e": 0.72}]
   }
   ```
   - `duration = round(len(wav) / 16000.0, 4)`.
   - Write one JSON object per line (`json.dumps(rec, ensure_ascii=False) + "\n"`).
   - Return `{"train": root / "train.jsonl", "val": root / "val.jsonl"}`.

---

## 3. Verification Criteria for `tests/test_asr_data.py`

1. **`synthesize_tsukinami`**:
   - Works for all 6 core presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`) on a short kana input (e.g. `"あい"`): returns `(wav, moras)` with `wav.dtype == np.float32`, 1D, values in `[-1.0, 1.0]`, non-zero RMS, resampled to requested `sr=16000` (and verify custom `sr=8000` produces ~half the samples).
   - Every mora dict has exact keys `{"t", "a", "e"}` with `0.0 <= a <= e` and `e <= duration + 0.05`.
   - `overrides` (e.g. `{"hz": 180.0, "rate": 1.0, "seed": 7}`) changes output deterministically without mutating `yomu.PRESETS["default"]` or the passed `overrides` dict.
   - Disk caching (`cache_dir=tmp_path`):
     - First call creates `.wav` + `.json` cache files.
     - Second call with same args hits cache (verify via timing `<0.05s` or monkeypatching `carve.make` to fail on second call) and returns matching `moras` and audio (within 16-bit PCM quantization tolerance `atol=1e-3`).
     - Changing `preset`, `sr`, `text`, or `overrides` produces a distinct cache miss.
   - Error handling: unknown preset -> `ValueError`; empty/pause-only text (`""`, `"、"`) -> `ValueError`; invalid `sr <= 0` -> `ValueError`.
2. **`generate_dataset`**:
   - `engine="fast"` with `num_train=10, num_val=4, seed=42`: creates `train.jsonl`, `val.jsonl`, WAV files; every JSONL line has exact required keys `{"audio_path", "text", "duration", "speaker", "source", "moras"}`, `source == "kotoba_fast"`, WAV readable via `load_wav`, `duration` matches WAV length.
   - Determinism: running `generate_dataset` twice into two directories with the same `seed` produces identical JSONL contents and identical WAV bytes.
   - `engine="tsukinami"` with `num_train=2, num_val=1, presets=["default", "ossan"]`: `source == "tsukinami"`, speakers in `{"default", "ossan"}`, valid WAVs and moras.
   - `engine="mixed"` with `num_train=4, num_val=2`: both `"kotoba_fast"` and `"tsukinami"` appear in `train.jsonl`.
   - Invalid `engine="bogus"` or invalid preset in `presets` -> `ValueError`.
