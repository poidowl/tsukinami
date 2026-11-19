# TEST_READY — Tsukinami ASR Opaque-Box E2E Test Suite

The independent, requirement-driven 4-tier E2E test suite (`tests_e2e/`) and infrastructure documentation (`TEST_INFRA.md`) have passed full review, adversarial challenge, and forensic anti-cheating audit (`sub_orch_e2e` Iteration 2 Gate: **PASS**).

---

## Test Runner

Run from `/home/antigravity/poidowl/tsukinami` using the project-local `.venv`:

```bash
# Full E2E suite (all 4 tiers, 222 tests)
.venv/bin/pytest tests_e2e/ -v

# Per-tier execution
.venv/bin/pytest tests_e2e/test_tier1_features.py -v
.venv/bin/pytest tests_e2e/test_tier2_boundaries.py -v
.venv/bin/pytest tests_e2e/test_tier3_combinations.py -v
.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -v

# Collection & syntax verification
python3 -m py_compile tests_e2e/*.py
.venv/bin/pytest --collect-only tests_e2e/ -q
```

### Progressive Milestone Subset Examples
```bash
# M1 (Features #1–#6: Config, Audio I/O, Features, VAD, Augment, Tokenizer) — 66 tests
.venv/bin/pytest tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py \
  -k "Feature01 or Feature02 or Feature03 or Feature04 or Feature05 or Feature06" -v

# M4 (Features #12–#14: Decoding, Alignment, Metrics) — 37 tests (standalone, no trained model needed)
.venv/bin/pytest tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py \
  -k "Feature12 or Feature13 or Feature14" -v

# Existing Tsukinami TTS non-regression — 1 test
.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -k test_t4_scenario9_existing_tsukinami_tts_non_regression -v
```

See [`TEST_INFRA.md`](TEST_INFRA.md) for fixture architecture, synthetic audio/WAV helpers, API multipart conventions (`files={"file": (...)}`), and the 2-vCPU / 7.8 GiB RAM execution budget.

---

## Coverage Summary

| Tier | File | Test Count | Purpose |
|---|---|---:|---|
| Tier 1 | `tests_e2e/test_tier1_features.py` | **103** | Isolated happy-path feature coverage (`>= 5` tests per feature across all 18 features, progressive testability) |
| Tier 2 | `tests_e2e/test_tier2_boundaries.py` | **98** | Boundary, corner-case, and negative error handling (`>= 5` tests per feature across all 18 features) |
| Tier 3 | `tests_e2e/test_tier3_combinations.py` | **12** | Pairwise cross-feature interactions across DSP, data, models, decoding, alignment, metrics, engine, CLI, and Web API |
| Tier 4 | `tests_e2e/test_tier4_scenarios.py` | **9** | Realistic multi-feature end-user application workflows (including `python -m asr demo`, 5-preset Tsukinami round-trip, noisy/telephone degradation, full web playground session, Tier-3 WAV folder corpus, `cnn_bigru` vs `conformer_lite` resume, decoding + N-gram LM study, visuals + `<10 ms` redecode sweep, and existing TTS non-regression) |
| **Total** | **`tests_e2e/`** | **222** | **100% opaque-box, zero skips, zero mocks, zero dummy passes** |

---

## Feature Checklist (All 18 Product Features in `PROJECT.md § Feature Inventory`)

| # | Feature | Milestone | Tier 1 | Tier 2 | Tier 3 | Tier 4 | Status |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | Project Environment & Packaging / Config | M1 | 6 | 5 | ✓ | ✓ | Ready (M1 live: 11/11 pass) |
| 2 | WAV/PCM I/O & Resampling | M1 | 5 | 6 | ✓ | ✓ | Ready (M1 live: 11/11 pass) |
| 3 | Pure-NumPy STFT, Log-Mel & MFCC | M1 | 5 | 5 | ✓ | ✓ | Ready (M1 live: 10/10 pass) |
| 4 | Energy VAD & Silence Trimming | M1 | 5 | 5 | ✓ | ✓ | Ready (M1 live: 10/10 pass) |
| 5 | SpecAugment & Waveform Corruptions | M1 | 6 | 6 | ✓ | ✓ | Ready (M1 live: 12/12 pass) |
| 6 | CTC Tokenizer (Kana/Phoneme/ASCII) | M1 | 6 | 6 | ✓ | ✓ | Ready (M1 live: 12/12 pass) |
| 7 | Tier 1: Fast `kotoba` Formant-Track Synth | M2 | 5 | 5 | ✓ | ✓ | Ready |
| 8 | Tier 2: Authentic `tsukinami` TTS Dataset Builder | M2 | 5 | 5 | ✓ | ✓ | Ready |
| 9 | Tier 3: Unified Manifest & Corpus DataLoader | M2 | 6 | 5 | ✓ | ✓ | Ready |
| 10 | Selectable End-to-End CTC Acoustic Models | M3 | 6 | 5 | ✓ | ✓ | Ready |
| 11 | Training Engine & Checkpointing | M3 | 5 | 5 | ✓ | ✓ | Ready |
| 12 | CTC Decoding (Greedy + Prefix Beam Search + LM) | M4 | 7 | 7 | ✓ | ✓ | Ready |
| 13 | Viterbi Forced Alignment | M4 | 5 | 5 | ✓ | ✓ | Ready |
| 14 | ASR Evaluation Metrics | M4 | 7 | 6 | ✓ | ✓ | Ready |
| 15 | High-Level Inference Engine (`ASREngine`) | M5 | 6 | 5 | ✓ | ✓ | Ready |
| 16 | Full CLI (`python -m asr ...`) | M5 | 7 | 6 | ✓ | ✓ | Ready |
| 17 | FastAPI Backend (`asr/server.py`) | M6 | 6 | 6 | ✓ | ✓ | Ready |
| 18 | Zero-CDN Interactive Web Playground (`asr/web/index.html`) | M6 | 5 | 5 | ✓ | ✓ | Ready |
