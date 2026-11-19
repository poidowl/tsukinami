# Scope — E2E Testing Track (`sub_orch_e2e`)

## Deliverables
1. `TEST_INFRA.md` — Documents the E2E test harness, fixtures, synthetic audio/manifest helpers, CPU runtime budget, pytest runner commands (full & per-tier), and exact mapping from all 18 product features in `PROJECT.md § Feature Inventory` to Tiers 1–4 tests.
2. `tests_e2e/conftest.py` — Shared fixtures (session/module-scoped tiny CPU-trained checkpoints or lazy fixtures, synthetic WAV generators, FastAPI `TestClient` factory, CLI subprocess runner using `.venv/bin/python`, temp workspace helpers).
3. `tests_e2e/test_tier1_features.py` — **Tier 1 (Feature Coverage)**: >=5 isolated happy-path tests per feature area covering all 18 product features, adhering to progressive testability (simpler feature tests do not depend on more complex features).
4. `tests_e2e/test_tier2_boundaries.py` — **Tier 2 (Boundary & Corner Cases)**: >=5 boundary/edge/negative tests per feature area (empty audio, silence, clipping, non-16kHz/stereo WAV, corrupt/missing WAV, empty text, unknown chars, beam_width=1, extreme temperature/blank_bias, invalid HTTP payloads, 404 redecode, bad CLI args, etc.).
5. `tests_e2e/test_tier3_combinations.py` — **Tier 3 (Cross-Feature Combinations)**: Pairwise combinations across DSP, features, tokenizer, synth data, DataLoader, `cnn_bigru` vs `conformer_lite`, checkpoint save/reload, greedy vs beam + N-gram LM, Viterbi alignment + metrics, TTS→ASR roundtrip + corruption + redecode, CLI pipeline `generate -> train -> eval -> transcribe`.
6. `tests_e2e/test_tier4_scenarios.py` — **Tier 4 (Real-World Application Scenarios)**: >=9 realistic multi-feature end-user workloads (full `python -m asr demo` CPU workflow, multi-preset Tsukinami TTS→ASR round-trip accuracy & mora alignment comparison, noisy/telephone speech degradation experiment, interactive playground full session via API, custom WAV folder Tier-3 corpus training & evaluation, existing `tsukinami` TTS non-regression, etc.).
7. `TEST_READY.md` — Published ONLY after passing the full 5-verifier gate (2 Reviewers + 2 Challengers + 1 Forensic Auditor), containing Test Runner commands, Coverage Summary, and 18-feature Checklist.

## Timing & Verification Constraints (Parallel Execution with Implementation Track)
- Some `asr/` modules may not exist yet while `tests_e2e/` is authored.
- All test files MUST:
  - Compile cleanly (`py_compile` / `ast.parse`) with zero syntax/import-structure bugs in the harness.
  - Collect cleanly under `pytest --collect-only tests_e2e/` (imports of `asr.*` inside test functions/fixtures so collection succeeds even if `asr/` is partial, while tests fail genuinely if `asr/` is missing or broken — NEVER `pytest.skip` or dummy pass!).
  - Strictly match `PROJECT.md § Interface Contracts` (exact function names, signatures, kwargs, return dict keys, CLI flags, HTTP routes).
  - Contain zero hardcoded dummy passes, zero skipped stubs, and zero implementation-internal coupling.
