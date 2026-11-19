# Forensic Audit Handoff — M7 Phase 1 Whole-Project Audit (`sub_orch_m7_t4` / `iter1_audit`)

## Explicit Binary Verdict

**VERDICT: `CLEAN`**

Zero integrity violations, zero hardcoded test answers, zero dummy/facade implementations, zero weakened/skipped/xfailed/vacuous tests, zero tampering with `tests_e2e/`, and 100% preservation of all existing `tsukinami` TTS files.

---

## 1. Whole-Project Codebase Audit (`asr/**/*.py`, `asr/web/index.html`)

Every source file under `asr/` was read in full and verified for genuine, non-cheating implementation:

| Module | Lines | Forensic Findings |
|---|---:|---|
| `asr/__init__.py` | 25 | Clean public re-exports and version string (`0.1.0`). |
| `asr/config.py` | 205 | Dataclasses (`AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig`) with strict `__post_init__` validation, `.to_dict()`, `.from_dict()` rejecting unknown keys. |
| `asr/audio.py` | 501 | Pure-NumPy/stdlib RIFF/WAVE parser (8/16/24/32-bit PCM + 32/64-bit IEEE float), FFT band-limited resampling, optional `ffmpeg` fallback, RMS energy VAD with hangover, raised-cosine FFT band-pass + white/pink noise + speed/gain corruptions. |
| `asr/features.py` | 255 | Pure-NumPy pre-emphasis, Hann-windowed STFT power, Slaney Mel filterbank, Log-Mel + per-utterance CMVN, DCT-II MFCC + deltas, SpecAugment. |
| `asr/tokenizer.py` | 256 | Kana/Phoneme/ASCII CTC tokenizer built on `kotoba.to_kata`, `kotoba.split_moras`, `kotoba.parse_kana`; `<blank>` fixed at index `0`; JSON-serializable. |
| `asr/synth_data.py` | 801 | Tier 1 vectorized NumPy Lorentzian formant + fricative synth driven by `kotoba.tracks_from_kana()`; Tier 2 authentic `yomu.build_carve_rc` + `carve.make` wrapper with atomic disk cache; deterministic `generate_dataset` across disjoint `TRAIN_CORPUS`/`VAL_CORPUS`. |
| `asr/dataset.py` | 369 | JSONL manifest reader/writer, `ASRManifestDataset`, `collate_asr_batch`, and Tier-3 `build_manifest_from_wav_dir` supporting dict/JSON/TSV/JSUT/Kaldi maps. |
| `asr/models/subsampling.py` | 129 | Two-layer stride-2 `Conv2d` (4× time reduction) with 3-point explicit zero-masking for strict padding invariance. |
| `asr/models/cnn_bigru.py` | 93 | `Conv2dSubsampling` + packed bidirectional `nn.GRU` + `LayerNorm` + `Linear` + `F.log_softmax`. |
| `asr/models/conformer.py` | 269 | Genuine Macaron `ConformerBlock` (FFN/2 → masked `MultiheadAttention` → depthwise separable GLU `ConvModule` → FFN/2 → `LayerNorm`) + dynamic `SinusoidalPositionalEncoding`. |
| `asr/models/__init__.py` | 36 | `build_model` factory supporting `cnn_bigru` and `conformer_lite`. |
| `asr/train.py` | 432 | Genuine PyTorch `nn.CTCLoss` + `AdamW` + `CosineAnnealingLR` + grad clipping + deterministic SpecAugment + atomic `best.pt`/`latest.pt` checkpointing and full resume (model/optimizer/scheduler/history). |
| `asr/decoding.py` | 539 | Pure-Python/NumPy `CharNgramLM` (interpolated add-k backoff), `greedy_decode`, `prefix_beam_search` (genuine `(p_b, p_nb)` log-space prefix merging with LM & insertion bonus), and `viterbi_align` (full CTC extended-state DP). |
| `asr/metrics.py` | 351 | Pure-Python Levenshtein DP (`levenshtein_align`), `compute_cer`, `compute_mer` (via `kotoba.split_moras`), `compute_wer`, `confusion_pairs`, `alignment_boundary_error` (with small-kana merging), `compute_rtf`. |
| `asr/inference.py` | 566 | `ASREngine` with checkpoint loading, LRU posterior cache (`OrderedDict`), genuine `transcribe`/`redecode`, and refactored `_build_ctc_posteriors` returning a numerically stable full-vocabulary 2D `list[list[float]]` of shape `(T_vis, V)` (or `[]` on empty audio). |
| `asr/__main__.py` | 528 | Full `argparse` CLI (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) delegating to real pipeline modules with clean error handling. |
| `asr/server.py` | 934 | Genuine FastAPI app (`/`, `/api/health`, `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`) with Pydantic v2 validation, size caps, and thread-safe engine lock. |
| `asr/web/index.html` | 2161 | Single self-contained zero-CDN HTML5 Canvas 2D + Web Audio playground; `drawCtcPosteriors()` natively consumes the 2D `(T, V)` posterior array and selects `<blank>` + top 11 tokens by peak probability. |

### Static Grep Verification Across `asr/`
- `grep -rnE "pytest|tests_e2e|test_tier|NotImplementedError|TODO|FIXME|HACK|XXX" asr/` → `NONE`
- `grep -rnE "https?://|<script[^>]+src=|<link[^>]+href=" asr/web/index.html` → `NONE` (strictly zero-CDN)

---

## 2. Unit Test Suite Audit (`tests/`)

### Execution Evidence
- **Command**: `.venv/bin/pytest tests/ -v`
- **Cwd**: `/home/antigravity/poidowl/tsukinami`
- **Exit Code**: `0`
- **Verbatim Output**:
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 154 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ....................                              [ 23%]
tests/test_asr_decoding.py ......................................        [ 48%]
tests/test_asr_dsp.py .............................................      [ 77%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_web.py ..................                                 [100%]

================= 154 passed, 2 warnings in 212.15s (0:03:32) ==================
```

### Integrity & Assertion Audit
- **AST vacuous-test check**: `tests: 110 test functions, vacuous=0` (every test function contains explicit `assert` or `pytest.raises`/`pytest.warns`).
- **Skip/xfail/mock scan**: Zero `pytest.skip`, zero `pytest.xfail`, zero `unittest.mock`/`MagicMock`. The only `monkeypatch` usages are two legitimate tests in `tests/test_asr_data.py`:
  - Line 312 (`test_tsukinami_disk_cache_hit_and_miss`): replaces `carve.make` with a raising sentinel *after* populating the cache to verify cache hits bypass synthesis and cache misses invoke `carve.make`.
  - Lines 384–385 (`test_generate_dataset_tsukinami_mixed_and_errors`): uses short 1-mora kana subsets for fast CPU integration testing of `engine="tsukinami"` / `"mixed"`.
- **Iter1 worker updates (`tests/test_asr_cli.py`, `tests/test_asr_web.py`)**: Strengthened/aligned assertions to verify 2D `(T', vocab_size)` shape, finiteness, `[0.0, 1.0]` bounds, and row sums equal to `1.0` (`atol=1e-4`), plus `[]` on empty audio.

---

## 3. E2E Test Suite Integrity Audit (`tests_e2e/`)

- **Zero skips/xfails/mocks**: `grep -rnE "pytest\.skip|pytest\.xfail|@pytest\.mark\.skip|@pytest\.mark\.xfail|unittest\.mock|MagicMock|monkeypatch|mock\." tests_e2e/` → `NONE`.
- **AST vacuous-test check**: `tests_e2e: 222 test functions, vacuous=0`.
- **Collection count**: `.venv/bin/pytest --collect-only tests_e2e/ -q` confirms exact `TEST_READY.md` counts:
  - `tests_e2e/test_tier1_features.py`: `103`
  - `tests_e2e/test_tier2_boundaries.py`: `98`
  - `tests_e2e/test_tier3_combinations.py`: `12`
  - `tests_e2e/test_tier4_scenarios.py`: `9`
  - Total: `222`
- **Timestamps & SHA-256 checksums** (all unmodified since `2026-11-19 03:13`–`03:25` UTC when the E2E suite was frozen):
```text
2026-11-19 03:25:35.089031521 +0000 12370 tests_e2e/conftest.py
2026-11-19 03:13:59.624081849 +0000 65999 tests_e2e/test_tier1_features.py
2026-11-19 03:25:36.267031439 +0000 45150 tests_e2e/test_tier2_boundaries.py
2026-11-19 03:25:38.150031309 +0000 20242 tests_e2e/test_tier3_combinations.py
2026-11-19 03:17:17.507067527 +0000 18386 tests_e2e/test_tier4_scenarios.py

ecb0cf15320ad762033e2dcee0d7246b5c3046f34dbb54a80504802973f99d3f  tests_e2e/conftest.py
808960c80cc38f33af87b3f5a0c71433a4ee164594d1ee48efbe59e886ec33de  tests_e2e/test_tier1_features.py
db36760fd7439d49fda32fe7fdbe60918862721744ed3f83d15d8be86cce1d0c  tests_e2e/test_tier2_boundaries.py
2324b3937502ea6272faa8e1d2ac67efeb0c15e6d19e1f3d00c6721ab20a889d  tests_e2e/test_tier3_combinations.py
d683c7fc78a82d03b8f579817f3f9913839becab2513fd8d131de414b6709917  tests_e2e/test_tier4_scenarios.py
```

---

## 4. Version-Control & Protected Files Audit

- **Command**: `git status --short && git diff --stat && git log -n 5 --oneline`
- **Verbatim Output**:
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
=== GIT DIFF ===
(empty)
=== GIT LOG ===
d2ab3ce Merge pull request #4 from poidowl/kusanagi-sync-24d3049
c0ecb97 Sync kusanagi_player.html with kusanagi @24d3049 reading fixes
16fbde6 Merge pull request #3 from poidowl/kusanagi-x-card
209dad7 Add kusanagi pure-JS X Player Card pages (kusanagi.html + kusanagi_player.html)
3858e11 Merge pull request #2 from poidowl/fix-tour-full-span
```
- **Confirmed**: `git diff` is completely empty. All existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) are 100% unmodified.
