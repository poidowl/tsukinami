# Explorer 1 Handoff — Test Infrastructure, `conftest.py`, & Tier 1–2 Design (Features #1–#11)

## 1. Repository & Environment Findings (Read-Only Inspection)

Inspected `/home/antigravity/poidowl/tsukinami` on 2026-11-19:
- **Existing TTS codebase (DO NOT MODIFY)**:
  - `kotoba.py`: Pure-Python 5 ms formant-track generator.
    - `to_kata(s)`: maps hiragana (`ぁ`..`ゖ`) to katakana.
    - `split_moras(text)`: splits into katakana moras, attaches small kana (`ャュョァィゥェォ`) to the preceding mora, collapses punctuation (`、。，．,.!！?？… 　`) to `'、'`, and strips trailing `'、'`.
    - `tracks_from_kana(text=...)`: returns dict with `fp_ms=5.0`, `n`, `F1..F3`, `G1..G3`, `dl`, `loud`, `f0`, `voiced`, `bands`, and `moras` (each dict has keys `t`, `kind`, `c`, `v`, `a`, `b`, `e`).
    - Valid Japanese test phrases: short phrases like `"あいう"`, `"おはよう"`, `"こんにちは"`, `"わたし、にほんご"`, `"きょうはいい天気"` (note: kanji is not converted by `to_kata`, so use hiragana/katakana phrases for TTS/ASR tests, and kanji/ASCII/emoji specifically for Tokenizer unknown-char boundary tests).
  - `yomu.py`: Exposes `PRESETS` with keys `default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`, and `build_carve_rc(text, prm)` (reads `S.txt` and `OO.txt` from repo root).
  - `carve.py`: Pure-Python subtractive TTS at `SR = 44100`. Because `carve.make` runs pure-Python sample loops at 44.1 kHz, synthesizing long sentences takes several seconds per utterance on CPU. **Runtime mitigation**: Tier 1/2 tests calling `synthesize_tsukinami` MUST use short kana strings (`"あい"`, `"あいう"`, `"かき"`) and leverage `cache_dir` where appropriate.
- **Current parallel build state**:
  - `asr/` and `.venv/` do not exist yet at inspection time (Implementation Track M1 is in progress in parallel).
  - `/usr/bin/python3` and `/usr/local/bin/uv` are available on the host.
  - Therefore, `tests_e2e/` MUST use **lazy imports** of `asr.*` (and `torch`/`fastapi`/`httpx`) inside fixtures and test functions so `pytest --collect-only tests_e2e/` succeeds cleanly at any time, while executing any test against missing/broken `asr/` fails genuinely with `ModuleNotFoundError`/`ImportError` (never `pytest.skip` or dummy pass).

---

## 2. Design of `TEST_INFRA.md`

`TEST_INFRA.md` at `/home/antigravity/poidowl/tsukinami/TEST_INFRA.md` will contain:
1. **Opaque-Box E2E Testing Principles**:
   - Tests exercise ONLY public contracts defined in `PROJECT.md § Interface Contracts`.
   - Zero internal implementation coupling, zero mocked SUT internals, zero `pytest.skip` / `pytest.xfail` stubs, zero dummy passes.
   - Lazy imports inside test functions/fixtures so `pytest --collect-only tests_e2e/` succeeds even during parallel M1–M6 development, while running tests fails genuinely if any module/symbol is missing or broken.
2. **Test Runner Commands**:
   - Syntax/collection check: `.venv/bin/pytest --collect-only tests_e2e/`
   - Full E2E suite: `.venv/bin/pytest -v tests_e2e/`
   - Per-tier execution:
     - Tier 1 (Feature Coverage): `.venv/bin/pytest -v tests_e2e/test_tier1_features.py`
     - Tier 2 (Boundary & Corner Cases): `.venv/bin/pytest -v tests_e2e/test_tier2_boundaries.py`
     - Tier 3 (Cross-Feature Combinations): `.venv/bin/pytest -v tests_e2e/test_tier3_combinations.py`
     - Tier 4 (Real-World Scenarios): `.venv/bin/pytest -v tests_e2e/test_tier4_scenarios.py`
   - Per-feature filtering via `-k` (e.g., `-k "Feature02"` or `-k "tokenizer"`).
3. **CPU Runtime Budget (2 vCPUs, 7.8 GiB RAM, 0 swap)**:
   - Target full suite runtime: `< 120s` (with session-scoped tiny `cnn_bigru` checkpoint and disk-cached short `tsukinami` utterances).
   - Per-tier budget: Tier 1 (~25s), Tier 2 (~20s), Tier 3 (~30s), Tier 4 (~45s).
   - Memory guardrails: small batch sizes (`2`–`4`), compact test models (`hidden_size=32`–`48`, `num_layers=1`), short audio (`0.5s`–`1.5s`), no large in-memory tensors retained across tests.
4. **Shared Fixtures & Synthetic Generators (`tests_e2e/conftest.py`)**:
   - Complete table of fixtures and helper functions (detailed in §3 below).
5. **18-Feature Coverage Matrix**:
   - Explicit traceability table mapping every feature `#1`–`#18` from `PROJECT.md § Feature Inventory` to its Tier 1, Tier 2, Tier 3, and Tier 4 test classes/functions.

---

## 3. Design of `tests_e2e/conftest.py`

### 3.1 Import & Collection Safety Rules
- Module-level imports in `conftest.py` and all `test_tier*.py` files are strictly limited to Python stdlib (`base64`, `io`, `json`, `math`, `os`, `pathlib`, `struct`, `subprocess`, `sys`, `time`, `wave`) plus `pytest` and `numpy` (or even lazy `numpy` helper if needed; `numpy` is standard in `.venv`, and keeping `asr.*`, `torch`, `fastapi`, `httpx` lazily imported inside fixtures/tests guarantees `pytest --collect-only` works cleanly).
- Every fixture that imports `asr.*` does a direct `from asr... import ...` with **no `try/except ImportError` and no `pytest.skip`**.

### 3.2 Reusable Helpers (importable from `conftest` or exposed via fixtures)
1. **Pure-stdlib / NumPy Signal Generators (independent of `asr.audio`)**:
   - `make_sine(freq: float = 440.0, duration: float = 1.0, sr: int = 16000, amp: float = 0.5) -> np.ndarray`: returns 1D `float32` sine wave.
   - `make_speech_like(duration: float = 1.2, sr: int = 16000, f0: float = 200.0, pad_sec: float = 0.2, seed: int = 0) -> np.ndarray`: returns 1D `float32` signal with leading/trailing silence (`pad_sec`) and a harmonic formant-modulated active speech middle region (realistic for VAD, STFT, Log-Mel, MFCC, and corruption tests).
   - `make_silence(duration: float = 0.5, sr: int = 16000) -> np.ndarray`: 1D `float32` zeros.
   - `make_clipped(duration: float = 0.5, sr: int = 16000, amp: float = 2.0) -> np.ndarray`: 1D `float32` signal with values exceeding `[-1.0, 1.0]`.
2. **Independent WAV Writer & Corruptor (stdlib `wave` + `struct`, never calls `asr.audio.save_wav`)**:
   - `write_pcm_wav(path: Path, wav: np.ndarray, sr: int = 16000, channels: int = 1, sampwidth: int = 2) -> Path`: writes valid PCM WAV (`sampwidth` 2 for 16-bit signed PCM, `sampwidth` 4 for 32-bit signed PCM; supports stereo by duplicating/stacking channels).
   - `write_corrupt_wav(path: Path, kind: str = "garbage") -> Path`:
     - `"garbage"`: random non-RIFF ASCII/binary bytes `b"NOT_A_WAV_FILE_1234567890"`
     - `"empty"`: 0-byte file
     - `"truncated"`: valid RIFF/WAVE header truncated mid-header (`b"RIFF\x24\x00\x00\x00WAVEfmt "`)
   - `wav_to_bytes(wav: np.ndarray, sr: int = 16000) -> bytes`: writes 16-bit mono WAV into `io.BytesIO` and returns raw bytes (for multipart upload / base64 API tests).
   - `wav_to_b64(wav: np.ndarray, sr: int = 16000) -> str`: base64-encoded WAV bytes.

### 3.3 Pytest Fixtures
- `repo_root() -> Path` (session): returns `Path(__file__).resolve().parent.parent` (`/home/antigravity/poidowl/tsukinami`).
- `python_bin(repo_root) -> Path` (session): returns `repo_root / ".venv" / "bin" / "python"` if it exists, else `Path(sys.executable)`.
- `run_cli(repo_root, python_bin)` (session): returns callable `run(args: list[str], *, cwd: Path | None = None, timeout: int = 180, env: dict | None = None) -> subprocess.CompletedProcess` executing `[str(python_bin), "-m", "asr", *args]` with `capture_output=True, text=True`.
- `tsukinami_cache_dir(tmp_path_factory) -> Path` (session): persistent temporary cache dir for `synthesize_tsukinami(..., cache_dir=...)` to avoid redundant 44.1 kHz synthesis across tests.
- `tiny_fast_dataset(tmp_path_factory) -> dict` (session):
  - Calls `asr.synth_data.generate_dataset(data_dir, num_train=12, num_val=4, engine="fast", seed=42)`.
  - Returns `{"out_dir": data_dir, "train": paths["train"], "val": paths["val"]}`.
- `tiny_checkpoint(tmp_path_factory, tiny_fast_dataset) -> dict` (session):
  - Trains a compact CPU `cnn_bigru` model once per session:
    - `AudioConfig()` (default 16 kHz, 64 mels)
    - `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=48, num_layers=1, dropout=0.0)`
    - `TrainConfig(epochs=2, batch_size=4, lr=3e-3, seed=42, use_spec_augment=False, checkpoint_dir=str(ckpt_dir))`
    - `Tokenizer(mode="kana")`
  - Calls `train_asr(train_manifest, val_manifest, audio_cfg=..., model_cfg=..., train_cfg=..., tokenizer=...)`.
  - Returns `{"best_pt": ckpt_dir / "best.pt", "latest_pt": ckpt_dir / "latest.pt", "ckpt_dir": ckpt_dir, "train_manifest": ..., "val_manifest": ..., "summary": summary, "audio_cfg": audio_cfg, "model_cfg": model_cfg, "tokenizer": tokenizer}`.
- `tiny_engine(tiny_checkpoint)` (session):
  - Returns `ASREngine.from_checkpoint(tiny_checkpoint["best_pt"])`.
- `api_client_factory()` (session):
  - Returns factory `make_client(checkpoint_path=None, engine=None) -> TestClient` that lazily imports `from fastapi.testclient import TestClient` and `from asr.server import create_app` and returns `TestClient(create_app(checkpoint_path=checkpoint_path, engine=engine))`.
- `api_client(tiny_engine, api_client_factory)` (session):
  - Returns `api_client_factory(engine=tiny_engine)`.

---

## 4. Tier 1 Feature Coverage (`tests_e2e/test_tier1_features.py`) — Features #1–#11

Every feature area has **>= 5 isolated happy-path tests** adhering to progressive testability (earlier features do not depend on later features). All signatures, kwargs, and return keys are verified against `PROJECT.md § Interface Contracts`.

### Feature 1: Project Environment, Packaging & Config (`TestTier1Feature01ConfigEnv`) — 6 tests
1. `test_packaging_files_and_asr_import`: verifies `pyproject.toml` and `.gitignore` exist at `repo_root`, `.gitignore` ignores `.venv/`, and `import asr` succeeds.
2. `test_audio_config_defaults_and_roundtrip`: constructs `AudioConfig()`, asserts exact contract defaults (`sample_rate=16000, n_fft=512, win_length=400, hop_length=160, n_mels=64, f_min=80.0, f_max=7600.0, preemphasis=0.97, cmvn=True`), verifies `AudioConfig.from_dict(cfg.to_dict()) == cfg` and JSON serializability (`json.dumps(cfg.to_dict())`).
3. `test_model_config_defaults_and_roundtrip`: constructs `ModelConfig()`, asserts defaults (`arch="cnn_bigru", n_mels=64, hidden_size=192, num_layers=2, dropout=0.1, num_heads=4, conv_kernel_size=15`), verifies `to_dict()` / `from_dict()` round-trip for both `"cnn_bigru"` and `"conformer_lite"`.
4. `test_train_config_defaults_and_roundtrip`: constructs `TrainConfig()`, asserts defaults (`epochs=20, batch_size=16, lr=3e-3, weight_decay=1e-4, grad_clip=5.0, seed=42, use_spec_augment=True, checkpoint_dir="checkpoints"`), verifies `to_dict()` / `from_dict()` round-trip.
5. `test_decode_config_defaults_and_roundtrip`: constructs `DecodeConfig()`, asserts defaults (`method="beam", beam_width=8, temperature=1.0, blank_bias=0.0, lm_weight=0.0, insertion_bonus=0.0`), verifies `to_dict()` / `from_dict()` round-trip for both `"greedy"` and `"beam"`.
6. `test_custom_config_override_serialization`: instantiates all 4 configs with non-default values, serializes to a single JSON payload, deserializes via `.from_dict()`, and asserts field-for-field equality.

### Feature 2: WAV/PCM I/O & Resampling (`TestTier1Feature02AudioIO`) — 5 tests
1. `test_save_and_load_wav_16k_mono_roundtrip`: `save_wav(p, wav, sr=16000)` then `load_wav(p, target_sr=16000)` returns `(out, 16000)` with `out.ndim == 1`, `out.dtype == np.float32`, range `[-1.0, 1.0]`, length matching input, and high correlation / low MAE (`< 1e-3`) with original sine wave.
2. `test_load_wav_independent_16bit_pcm_file`: writes a 16-bit PCM WAV using independent stdlib `write_pcm_wav`, verifies `load_wav` reads exact sample count, `float32` dtype, and amplitude within `[-1.0, 1.0]`.
3. `test_load_wav_resamples_from_44100_to_16000`: writes a 1.0s 44.1 kHz sine wave via `write_pcm_wav`, calls `load_wav(p, target_sr=16000)`, asserts returned `sr == 16000` and `len(out)` within ±2% of `16000` samples.
4. `test_load_wav_stereo_mixdown_to_mono`: writes a 2-channel stereo WAV via `write_pcm_wav(..., channels=2)`, calls `load_wav(p, target_sr=16000)`, asserts `out.ndim == 1`, `out.dtype == np.float32`, non-zero finite waveform.
5. `test_resample_downsample_and_upsample`: calls `resample(wav_44k, 44100, 16000)` and `resample(wav_8k, 8000, 16000)`, asserts `float32` 1D output with expected duration ratio (`len_out / target_sr ≈ len_in / orig_sr` within 1%).

### Feature 3: Pure-NumPy STFT, Log-Mel & MFCC (`TestTier1Feature03Features`) — 5 tests
1. `test_extract_log_mel_default_shape_and_dtype`: runs `extract_log_mel(wav)` on 1.0s 16 kHz speech-like audio (`cfg=None` default), asserts `dtype == np.float32`, `ndim == 2`, `shape[1] == 64`, `shape[0]` around `~98–101` frames (`hop_length=160`), and all finite values.
2. `test_extract_log_mel_custom_80_mels`: runs `extract_log_mel(wav, AudioConfig(n_mels=80))`, asserts `shape[1] == 80` and `dtype == np.float32`.
3. `test_extract_log_mel_cmvn_normalizes_mean_and_std`: compares `AudioConfig(cmvn=True)` vs `AudioConfig(cmvn=False)` on non-stationary speech-like audio; with `cmvn=True`, per-feature (or global) mean is near `0.0` (`abs(mel.mean()) < 0.1`) and std is near `1.0` (`0.5 < mel.std() < 1.5`).
4. `test_extract_mfcc_basic_13_coeffs`: runs `extract_mfcc(wav, AudioConfig(), n_mfcc=13, include_deltas=False)`, asserts `dtype == np.float32`, `shape == (T, 13)`, finite values, and same `T` as `extract_log_mel`.
5. `test_extract_mfcc_with_deltas_39_coeffs`: runs `extract_mfcc(wav, AudioConfig(), n_mfcc=13, include_deltas=True)`, asserts `dtype == np.float32`, `shape == (T, 39)`, finite values, and first 13 dims match static MFCCs.

### Feature 4: Energy VAD & Silence Trimming (`TestTier1Feature04VAD`) — 5 tests
1. `test_detect_vad_finds_single_speech_segment`: creates `[0.4s silence | 0.6s speech-like | 0.4s silence]`, calls `detect_vad(wav, sr=16000)`, asserts `len(segs) >= 1`, each `(start, end)` satisfies `0.0 <= start < end <= 1.4`, and the active middle `[0.4, 1.0]` overlaps detected segments.
2. `test_detect_vad_finds_multiple_separated_segments`: creates `[0.3s sil | 0.4s tone | 0.5s sil | 0.4s tone | 0.3s sil]`, calls `detect_vad(wav, sr=16000, hangover_ms=100.0)`, asserts `len(segs) == 2` and segments are chronologically ordered with `segs[0][1] < segs[1][0]`.
3. `test_detect_vad_hangover_extends_segment_tail`: compares `hangover_ms=20.0` vs `hangover_ms=200.0` on `[0.3s sil | 0.4s tone | 0.5s sil]`, asserts longer `hangover_ms` yields `end_sec` >= shorter `hangover_ms`.
4. `test_detect_vad_threshold_db_sensitivity`: runs `detect_vad` on a quiet `-30 dB` tone with `threshold_db=-45.0` (detects speech) vs `threshold_db=-10.0` (stricter threshold detects fewer/no segments).
5. `test_detect_vad_custom_frame_ms`: runs `detect_vad(wav, sr=16000, frame_ms=10.0)` and `frame_ms=30.0`, asserting valid `list[tuple[float, float]]` with `start < end` in both cases.

### Feature 5: SpecAugment & Waveform Corruptions (`TestTier1Feature05Augment`) — 6 tests
1. `test_spec_augment_preserves_shape_and_masks_values`: calls `spec_augment(mel, freq_mask_param=8, time_mask_param=15, num_freq_masks=2, num_time_masks=2, seed=42)`, asserts same shape & `float32` dtype, does not mutate input `mel` in-place, and output differs from input (masked entries present).
2. `test_spec_augment_reproducible_with_seed`: two calls with `seed=123` produce `np.array_equal(a, b)`.
3. `test_apply_corruption_white_noise_snr`: calls `apply_corruption(wav, 16000, snr_db=10.0, noise_type="white", seed=7)`, asserts same length, `float32`, finite, differs from clean `wav`, and empirical SNR is within a reasonable band of 10 dB (`5.0 < est_snr < 15.0`).
4. `test_apply_corruption_pink_noise`: calls `apply_corruption(wav, 16000, snr_db=10.0, noise_type="pink", seed=7)`, asserts same length, `float32`, finite, and differs from clean `wav`.
5. `test_apply_corruption_band_limit_telephone`: applies `band_limit=(300.0, 3400.0)` to a sum of `100 Hz + 1000 Hz + 6000 Hz` sine waves; verifies via FFT that `1000 Hz` energy is preserved while `100 Hz` and `6000 Hz` are attenuated relative to `1000 Hz`.
6. `test_apply_corruption_speed_and_gain_db`: tests `speed=1.25` (output shorter than input) and `speed=0.8` (output longer than input), and `gain_db=6.0` (RMS increases by ~2×) vs `gain_db=-6.0` (RMS decreases by ~0.5×).

### Feature 6: CTC Tokenizer (`TestTier1Feature06Tokenizer`) — 6 tests
1. `test_kana_mode_blank_id_and_roundtrip`: `tok = Tokenizer(mode="kana")`, asserts `tok.blank_id == 0`, `tok.vocab_size > 40`, `tok.decode(tok.encode("ワタシ、ニホンゴ"))` round-trips cleanly.
2. `test_kana_mode_hiragana_normalizes_to_katakana`: `tok.encode("わたし、にほんご") == tok.encode("ワタシ、ニホンゴ")` (uses `kotoba.to_kata`).
3. `test_decode_collapse_ctc_semantics`: constructs `[0, a, a, 0, a, b, b, 0]` from two distinct valid token IDs `a, b`; asserts `tok.decode(ids, collapse_ctc=True) == tok.decode([a, a, b], collapse_ctc=False)` (consecutive duplicates collapsed, blank separates repeated tokens, blanks removed).
4. `test_phoneme_and_ascii_modes`: instantiates `Tokenizer(mode="phoneme")` and `Tokenizer(mode="ascii")`; verifies `blank_id == 0`, `vocab_size > 10`, and non-empty `encode` + `decode` round-trip (`"こんにちは"` for phoneme, `"hello world"` for ascii).
5. `test_tokenizer_to_dict_from_dict_roundtrip`: serializes `tok.to_dict()` through `json.dumps`/`json.loads`, restores via `Tokenizer.from_dict(d)`, asserts identical `vocab_size`, `blank_id`, and identical `encode`/`decode` outputs.
6. `test_custom_vocab_override`: `Tokenizer(mode="kana", vocab=["ア", "イ", "ウ"])` has `blank_id == 0`, encodes `"アイウ"` into 3 valid non-blank IDs, and decodes back to `"アイウ"`.

### Feature 7: Tier 1 Fast `kotoba` Formant-Track Synth (`TestTier1Feature07FastSynth`) — 5 tests
1. `test_synthesize_fast_kotoba_basic_output`: calls `synthesize_fast_kotoba("おはよう", sr=16000, seed=42)`, asserts `wav.ndim == 1`, `wav.dtype == np.float32`, `len(wav) > 0`, finite values, non-zero RMS, and `moras` is a non-empty `list[dict]`.
2. `test_synthesize_fast_kotoba_mora_timestamps_schema`: verifies every item in `moras` has keys `"t"`, `"a"`, `"e"` with `0.0 <= m["a"] <= m["e"]`, monotonically non-decreasing `a`, and final `e` close to `len(wav) / sr`.
3. `test_synthesize_fast_kotoba_rate_changes_duration`: compares `rate=0.75` vs `rate=1.4` on `"こんにちは"`, asserting duration changes in the expected direction (faster rate -> different/shorter or longer depending on `kotoba.py` convention; check `len(wav_fast) != len(wav_slow)` and both > 0). *(Note: in `kotoba.py`, `rate` scales durations, let's assert `abs(len(w1) - len(w2)) > 500` without assuming sign if rate is multiplier vs speed, or check `kotoba.py`! Let's check `kotoba.py` rule_durations if needed, or assert distinct durations.)*
4. `test_synthesize_fast_kotoba_speaker_variation_and_seed`: `f0_scale=0.8, fscale=0.9` vs `f0_scale=1.3, fscale=1.2` produces distinct waveforms; identical `seed=7` produces identical waveforms (`np.array_equal`).
5. `test_synthesize_fast_kotoba_with_snr_noise`: calls `synthesize_fast_kotoba("テスト", sr=16000, snr_db=15.0, seed=1)` vs `snr_db=None, seed=1`, asserts same length, finite `float32`, and waveform differs due to added noise.

### Feature 8: Tier 2 Authentic `tsukinami` TTS (`TestTier1Feature08TsukinamiTTS`) — 5 tests
*(Use short kana strings `"あい"`, `"あいう"`, `"かき"` and `tsukinami_cache_dir` to keep CPU time ~8–12s total.)*
1. `test_synthesize_tsukinami_default_preset`: calls `synthesize_tsukinami("あいう", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)`, asserts 1D `float32` non-silent waveform, `moras` list with `{"t", "a", "e"}`.
2. `test_synthesize_tsukinami_alternate_presets`: synthesizes `"あい"` with `preset="ossan"` and `preset="robot"`, asserting valid `float32` waveforms and that the two presets produce distinct audio.
3. `test_synthesize_tsukinami_overrides_applied`: synthesizes `"あい"` with `overrides={"hz": 160.0, "fscale": 0.9}` vs `default`, asserting valid `float32` output distinct from default.
4. `test_synthesize_tsukinami_disk_cache_hit`: calls `synthesize_tsukinami("かき", preset="default", sr=16000, cache_dir=tmp_path)` twice; asserts cache files exist in `tmp_path`, second call returns identical `(wav, moras)`, and second call is faster than the first.
5. `test_synthesize_tsukinami_custom_sr_resampling`: calls `synthesize_tsukinami("あい", preset="default", sr=8000, cache_dir=tsukinami_cache_dir)`, asserts output duration matches 16 kHz version (`len(w8k) / 8000 ≈ len(w16k) / 16000` within 5%).

### Feature 9: Tier 3 Unified Manifest & Corpus DataLoader (`TestTier1Feature09Dataset`) — 6 tests
1. `test_generate_dataset_fast_creates_manifests_and_wavs`: calls `generate_dataset(tmp_path, num_train=6, num_val=2, engine="fast", seed=42)`, asserts return dict has keys `"train"` and `"val"` pointing to existing `.jsonl` files with 6 and 2 lines respectively, and every `audio_path` exists on disk.
2. `test_manifest_jsonl_schema_compliance`: parses every line of generated `train.jsonl`, asserts required schema keys `audio_path`, `text`, `duration` (> 0), `speaker`, `source`, `moras` (list of dicts with `t`, `a`, `e`).
3. `test_asr_manifest_dataset_len_and_getitem`: wraps `train.jsonl` in `ASRManifestDataset(manifest, AudioConfig(), Tokenizer("kana"), augment=False)`, asserts `len(ds) == 6` and `ds[0]` returns valid feature tensor/array & target IDs & text.
4. `test_collate_asr_batch_padding_and_shapes`: collates 3 items `[ds[0], ds[1], ds[2]]` with `collate_asr_batch`, asserts returned dict has exact contracted keys `feats` (`Tensor[3, T_max, 64]`), `feat_lengths` (`Tensor[3]`), `targets` (`Tensor[3, L_max]`), `target_lengths` (`Tensor[3]`), `texts` (`list[str]` of len 3), and `feats.shape[1] == int(feat_lengths.max())`.
5. `test_asr_manifest_dataset_augment_flag`: creates dataset with `augment=True`, fetches `ds[0]` multiple times, asserts valid finite features of identical `(T, 64)` shape.
6. `test_build_manifest_from_wav_dir_tier3`: writes 3 synthetic WAVs into `tmp_path / "wavs"`, calls `build_manifest_from_wav_dir(wav_dir, {"u1.wav": "ア", "u2.wav": "イ", "u3.wav": "ウ"}, out_manifest)`, asserts returned `Path` exists with 3 valid JSONL entries loadable by `ASRManifestDataset`.

### Feature 10: Selectable End-to-End CTC Acoustic Models (`TestTier1Feature10Models`) — 6 tests
1. `test_build_model_cnn_bigru_forward_and_log_softmax`: builds `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=32, num_layers=1)` with `vocab_size=50`, runs forward on `(B=2, T=40, F=64)` with `feat_lengths=torch.tensor([40, 28])`; asserts `log_probs` shape `(2, T', 50)`, `out_lengths` shape `(2,)`, `out_lengths[0] > out_lengths[1] > 0`, `torch.isfinite(log_probs).all()`, and `torch.exp(log_probs).sum(dim=-1)` ≈ `1.0` (`atol=1e-4`).
2. `test_build_model_conformer_lite_forward_and_log_softmax`: builds `ModelConfig(arch="conformer_lite", n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)` with `vocab_size=50`, runs same forward check and `log_softmax` probability sum assertion.
3. `test_model_subsampling_factor_and_frame_stride`: asserts `model.subsampling_factor == 4` and `model.output_frame_stride_ms(AudioConfig()) == pytest.approx(40.0)` for both `cnn_bigru` and `conformer_lite`, and `output_frame_stride_ms(AudioConfig(hop_length=320)) == pytest.approx(80.0)`.
4. `test_default_model_config_parameter_count_cpu_friendly`: builds default `ModelConfig(arch="cnn_bigru")` and `ModelConfig(arch="conformer_lite")`, verifies both instantiate cleanly on CPU and run a `(1, 32, 64)` forward pass without error.
5. `test_ctc_loss_backward_gradient_flow_both_archs`: runs `nn.CTCLoss(blank=0, zero_infinity=True)` backward pass on both `cnn_bigru` and `conformer_lite`, asserting finite loss and non-zero parameter gradients.
6. `test_eval_mode_deterministic_inference`: puts model in `model.eval()`, runs two forward passes with identical inputs under `torch.no_grad()`, asserts exact equality `torch.equal(lp1, lp2)`.

### Feature 11: Training Engine & Checkpointing (`TestTier1Feature11Training`) — 5 tests
1. `test_train_asr_creates_best_and_latest_checkpoints`: runs `train_asr` (1 epoch, tiny `cnn_bigru`, `tiny_fast_dataset`), asserts returned summary is a non-empty `dict`, and both `best.pt` and `latest.pt` exist in `train_cfg.checkpoint_dir`.
2. `test_load_checkpoint_contract_keys`: calls `load_checkpoint(best_pt, device="cpu")`, asserts presence of all contracted keys: `model_state_dict`, `model_config`, `audio_cfg`, `tokenizer`, `history`, `epoch`, `best_val_cer`.
3. `test_train_asr_resume_from_checkpoint`: trains 1 epoch to `latest.pt`, then calls `train_asr(..., train_cfg=TrainConfig(epochs=2, ...), resume_from=latest_pt)`, asserts training completes cleanly and final `epoch` / `history` reflects continuation.
4. `test_train_asr_conformer_lite_architecture`: runs 1-epoch `train_asr` with `ModelConfig(arch="conformer_lite", hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)`, asserts checkpoints saved and loadable.
5. `test_train_asr_deterministic_seed`: runs two 1-epoch trainings with identical `seed=42` into separate dirs (using `use_spec_augment=False`), loads both `latest.pt`, and verifies matching `best_val_cer` / `history` loss within tight tolerance (`1e-4`).

---

## 5. Tier 2 Boundary & Corner Cases (`tests_e2e/test_tier2_boundaries.py`) — Features #1–#11

Every feature area has **>= 5 boundary, edge-case, or negative tests**.

### Feature 1: Config Boundaries (`TestTier2Feature01ConfigBoundaries`) — 5 tests
1. `test_model_config_invalid_arch_rejected`: `ModelConfig(arch="invalid_arch")` or passing it to `build_model` raises `ValueError`.
2. `test_decode_config_invalid_method_rejected`: `DecodeConfig(method="viterbi_only")` raises `ValueError` (either at init or decode time; if dataclass accepts it, validate `from_dict` / `DecodeConfig` rejects or `prefix_beam_search` handles — test `AudioConfig.from_dict` with unknown/extra keys or missing keys cleanly). *Refinement*: Let's test `from_dict({})` (empty dict uses defaults or raises `KeyError`/`TypeError` cleanly without crashing mysteriously), `AudioConfig(sample_rate=8000, f_max=3800.0)` edge values, `ModelConfig(dropout=0.0)` and `dropout=0.5`, `DecodeConfig(beam_width=1, temperature=0.1, blank_bias=-2.0)`, and `TrainConfig(epochs=1, batch_size=1, grad_clip=0.0)`.
3. `test_config_from_dict_missing_or_partial_fields`: verifies `.from_dict({})` either fills defaults or raises `(KeyError, TypeError, ValueError)` cleanly.
4. `test_audio_config_extreme_nyquist_values`: `AudioConfig(sample_rate=8000, n_fft=256, win_length=200, hop_length=80, n_mels=32, f_min=0.0, f_max=4000.0)` serializes and round-trips cleanly.
5. `test_decode_config_boundary_numeric_values`: `DecodeConfig(method="greedy", beam_width=1, temperature=0.05, blank_bias=-5.0, lm_weight=0.0, insertion_bonus=-1.0)` round-trips cleanly via `to_dict`/`from_dict`.

### Feature 2: Audio I/O & Resampling Boundaries (`TestTier2Feature02AudioIOBoundaries`) — 6 tests
1. `test_load_wav_missing_file_raises_file_not_found`: `load_wav(tmp_path / "does_not_exist.wav")` raises `FileNotFoundError`.
2. `test_load_wav_corrupt_garbage_raises_value_error`: `write_corrupt_wav(p, "garbage")` -> `load_wav(p)` raises `ValueError`.
3. `test_load_wav_empty_file_raises_value_error`: `write_corrupt_wav(p, "empty")` -> `load_wav(p)` raises `ValueError`.
4. `test_load_wav_truncated_header_raises_value_error`: `write_corrupt_wav(p, "truncated")` -> `load_wav(p)` raises `ValueError`.
5. `test_save_wav_clips_out_of_range_values`: `save_wav(p, make_clipped(amp=3.0), sr=16000)` does not overflow 16-bit PCM wrap-around; reloaded audio stays strictly in `[-1.0, 1.0]` with no sign-flip artifacts.
6. `test_resample_identity_and_empty_and_invalid_sr`: `resample(wav, 16000, 16000)` preserves length & values; `resample(np.zeros(0, dtype=np.float32), 16000, 8000)` returns empty `float32` array; `resample(wav, 0, 16000)` or `resample(wav, 16000, -1)` raises `ValueError`.

### Feature 3: Feature Extraction Boundaries (`TestTier2Feature03FeaturesBoundaries`) — 5 tests
1. `test_extract_log_mel_pure_silence_is_finite`: `extract_log_mel(make_silence(0.5))` produces no NaN/Inf (`np.isfinite(mel).all()`), shape `(T, 64)`, `float32` (guards against `log(0)` and zero-variance CMVN division by zero!).
2. `test_extract_log_mel_very_short_audio_shorter_than_win_length`: 100 samples (< `win_length=400`) produces finite `float32` `(T, 64)` with `T >= 1` (no crash).
3. `test_extract_log_mel_single_sample_and_constant_dc`: constant DC `np.ones(1600, dtype=np.float32) * 0.5` produces finite `float32` output (guards CMVN zero-std).
4. `test_extract_mfcc_silence_and_deltas_short_audio`: `extract_mfcc(make_silence(0.05), n_mfcc=13, include_deltas=True)` produces finite `float32` `(T, 39)` with no NaN/Inf even on very few frames.
5. `test_extract_log_mel_preemphasis_zero_vs_high`: `AudioConfig(preemphasis=0.0)` and `AudioConfig(preemphasis=0.99)` both produce finite `(T, 64)` `float32` arrays without error.

### Feature 4: VAD Boundaries (`TestTier2Feature04VADBoundaries`) — 5 tests
1. `test_detect_vad_pure_silence_returns_empty`: `detect_vad(make_silence(1.0), sr=16000)` returns `[]`.
2. `test_detect_vad_empty_array_returns_empty`: `detect_vad(np.zeros(0, dtype=np.float32), sr=16000)` returns `[]`.
3. `test_detect_vad_continuous_loud_signal_single_span`: full-duration 1.0s loud sine returns 1 segment covering `[~0.0, ~1.0]`.
4. `test_detect_vad_very_short_audio_sub_frame`: 50 samples (< 20 ms frame) does not crash and returns a valid `list`.
5. `test_detect_vad_zero_hangover_and_extreme_thresholds`: `hangover_ms=0.0` works cleanly; `threshold_db=0.0` (above max full-scale) returns `[]`, while `threshold_db=-120.0` on low-amplitude noise detects speech.

### Feature 5: SpecAugment & Corruption Boundaries (`TestTier2Feature05AugmentBoundaries`) — 6 tests
1. `test_spec_augment_zero_masks_returns_unchanged`: `num_freq_masks=0, num_time_masks=0` returns array equal to input `mel`.
2. `test_spec_augment_mask_larger_than_dimensions`: `freq_mask_param=200, time_mask_param=500` on tiny `(5, 16)` mel does not raise `ValueError`/`IndexError` and preserves shape `(5, 16)`.
3. `test_apply_corruption_noop_defaults`: `apply_corruption(wav, 16000)` with all default kwargs returns finite `float32` array matching input length and nearly identical values.
4. `test_apply_corruption_invalid_noise_type_raises`: `apply_corruption(wav, 16000, snr_db=10.0, noise_type="brown")` raises `ValueError`.
5. `test_apply_corruption_extreme_snr_values`: `snr_db=-10.0` (heavy noise) and `snr_db=60.0` (near-clean) both produce finite `float32` waveforms of original length.
6. `test_apply_corruption_silence_input_with_noise`: `apply_corruption(make_silence(0.5), 16000, snr_db=10.0, seed=0)` produces finite `float32` output (no NaN from zero signal power).

### Feature 6: Tokenizer Boundaries (`TestTier2Feature06TokenizerBoundaries`) — 6 tests
1. `test_tokenizer_invalid_mode_raises_value_error`: `Tokenizer(mode="invalid_mode")` raises `ValueError`.
2. `test_tokenizer_empty_string_encode_and_empty_decode`: `tok.encode("") == []` and `tok.decode([]) == ""` across all 3 modes (`kana`, `phoneme`, `ascii`).
3. `test_tokenizer_decode_all_blanks_returns_empty`: `tok.decode([0, 0, 0, 0], collapse_ctc=True) == ""` and `tok.decode([0, 0], collapse_ctc=False) == ""`.
4. `test_tokenizer_unknown_characters_do_not_crash`: `tok.encode("🎵🚀123XYZ漢字")` in `kana` mode returns `list[int]` with all IDs in `[0, tok.vocab_size)` and no unhandled exception.
5. `test_tokenizer_punctuation_and_small_kana_mora_handling`: `"きゃ、きゅ、きょ！っんー"` encodes to non-empty valid IDs and decodes without crashing.
6. `test_tokenizer_ascii_case_and_spaces`: `Tokenizer(mode="ascii")` handles uppercase/lowercase/multiple spaces/empty string cleanly.

### Feature 7: Fast Kotoba Synth Boundaries (`TestTier2Feature07FastSynthBoundaries`) — 5 tests
1. `test_fast_kotoba_single_mora`: `synthesize_fast_kotoba("ア", sr=16000)` returns finite non-empty `float32` audio and `len(moras) >= 1`.
2. `test_fast_kotoba_special_moras_sokuon_hatuon_chouon`: `synthesize_fast_kotoba("カッパ、アンパン、カー", sr=16000)` (geminate `ッ`, moraic nasal `ン`, long vowel `ー`, pause `、`) produces valid finite audio and moras.
3. `test_fast_kotoba_extreme_f0_and_fscale`: `f0_scale=0.5, fscale=0.7` and `f0_scale=1.8, fscale=1.4` both produce finite `float32` waveforms without NaN/Inf.
4. `test_fast_kotoba_empty_or_punctuation_only_text`: `synthesize_fast_kotoba("")` and `synthesize_fast_kotoba("、、、")` either return short finite `float32` silence or raise `ValueError` cleanly (no `IndexError`/`ZeroDivisionError`).
5. `test_fast_kotoba_low_snr_heavy_noise`: `synthesize_fast_kotoba("アイウ", sr=16000, snr_db=-5.0, seed=9)` produces finite `float32` audio.

### Feature 8: Tsukinami TTS Boundaries (`TestTier2Feature08TsukinamiTTSBoundaries`) — 5 tests
1. `test_tsukinami_invalid_preset_raises`: `synthesize_tsukinami("あい", preset="nonexistent_preset")` raises `(ValueError, KeyError)`.
2. `test_tsukinami_single_mora`: `synthesize_tsukinami("あ", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)` returns valid finite `float32` audio and `moras`.
3. `test_tsukinami_hiragana_vs_katakana_equivalence`: `synthesize_tsukinami("あい", ...)` and `synthesize_tsukinami("アイ", ...)` both succeed and produce valid finite audio with matching mora count.
4. `test_tsukinami_whisper_and_chibi_presets`: `preset="whisper"` and `preset="chibi"` on `"あ"` both produce finite `float32` waveforms.
5. `test_tsukinami_cache_dir_none_no_side_effects`: `synthesize_tsukinami("あ", preset="default", sr=16000, cache_dir=None)` works cleanly without requiring a cache directory.

### Feature 9: Manifest & DataLoader Boundaries (`TestTier2Feature09DatasetBoundaries`) — 5 tests
1. `test_dataset_missing_manifest_raises_file_not_found`: `ASRManifestDataset(tmp_path / "missing.jsonl", AudioConfig(), Tokenizer("kana"))` raises `FileNotFoundError`.
2. `test_collate_single_item_batch`: `collate_asr_batch([ds[0]])` returns batch size `B=1` tensors with exact shapes `(1, T, 64)` and `(1, L)`.
3. `test_collate_highly_variable_lengths`: collates a very short utterance (`"ア"`) and a longer utterance (`"アイウエオカキクケコ"`) in one batch; verifies zero-padding on shorter features, `feat_lengths[short] < feat_lengths[long]`, and `target_lengths[short] < target_lengths[long]`.
4. `test_build_manifest_from_wav_dir_empty_dir`: empty `wav_dir` with `{}` map produces an empty (0-line) manifest file without crashing.
5. `test_generate_dataset_invalid_engine_raises`: `generate_dataset(tmp_path, num_train=2, num_val=1, engine="unknown_engine")` raises `ValueError`.

### Feature 10: Acoustic Model Boundaries (`TestTier2Feature10ModelsBoundaries`) — 5 tests
1. `test_build_model_invalid_arch_raises_value_error`: `build_model(ModelConfig(arch="resnet_999"), vocab_size=50)` raises `ValueError`.
2. `test_model_batch_size_one_and_minimum_valid_frames`: runs `B=1, T=16` (4× subsampling -> `T' >= 1`) through both `cnn_bigru` and `conformer_lite`, asserting finite `log_probs` and `out_lengths >= 1`.
3. `test_model_extreme_length_disparity_in_batch`: `B=2`, `feat_lengths=[120, 16]`, verifies `out_lengths[0] > out_lengths[1] >= 1` and no NaN/Inf in padded region for both architectures.
4. `test_model_custom_n_mels_80`: `ModelConfig(arch="cnn_bigru", n_mels=80, hidden_size=32, num_layers=1)` accepts `(2, 32, 80)` input and returns valid `(2, T', V)` `log_probs`.
5. `test_model_dropout_zero_train_vs_eval_consistency`: with `dropout=0.0`, `model.train()` and `model.eval()` produce finite, consistent shapes on identical inputs.

### Feature 11: Training & Checkpointing Boundaries (`TestTier2Feature11TrainingBoundaries`) — 5 tests
1. `test_load_checkpoint_missing_path_raises_file_not_found`: `load_checkpoint(tmp_path / "no_such.pt")` raises `FileNotFoundError`.
2. `test_train_asr_missing_manifest_raises_file_not_found`: `train_asr(tmp_path / "missing.jsonl", val_manifest, ...)` raises `FileNotFoundError`.
3. `test_train_asr_missing_resume_path_raises_file_not_found`: `train_asr(..., resume_from=tmp_path / "missing.pt")` raises `FileNotFoundError`.
4. `test_train_asr_batch_size_larger_than_dataset`: `TrainConfig(epochs=1, batch_size=64, ...)` on a 4-utterance manifest succeeds without dropping all batches (`drop_last=False` behavior) and saves valid checkpoints.
5. `test_train_asr_single_utterance_train_and_val`: 1-utterance train manifest and 1-utterance val manifest with `batch_size=1, epochs=1` completes cleanly with finite loss and valid `best.pt`.

---

## 6. Summary Counts (Features #1–#11)
- **Tier 1 tests designed**: 60 tests across Features #1–#11 (5–6 per feature, all >= 5).
- **Tier 2 tests designed**: 58 tests across Features #1–#11 (5–6 per feature, all >= 5).
- **Zero module-level `asr` imports**, **zero `pytest.skip`**, **100% aligned with `PROJECT.md § Interface Contracts`**.
