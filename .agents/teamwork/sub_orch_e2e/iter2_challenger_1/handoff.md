# Iteration 2 — Challenger 1 Adversarial Probe Report (`sub_orch_e2e`)

## Verdict: **PASS**

All Iteration 1 Challenger 1 blocking findings (`tests_e2e/conftest.py` 32-bit PCM `int32` overflow and `tests_e2e/test_tier2_boundaries.py` M3 `asr.models` cross-milestone leak in Feature 1) are resolved cleanly, verified via independent adversarial probes under `.venv/bin/python -W error`, AST/runtime isolation checks, and broken-implementation mutation tests, with zero regressions.

---

## Adversarial Probe Results

All ad-hoc probe scripts were staged in a temporary directory created via `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and removed automatically on exit (`trap 'rm -rf "$PROBE_DIR"' EXIT`). Zero edits were made to the repository working tree.

### 1. 32-bit PCM `write_pcm_wav` Overflow & `make_speech_like(duration=0.0)` Probe (`.venv/bin/python -W error`)
- **Target**: `tests_e2e/conftest.py` (`write_pcm_wav`, `make_speech_like`)
- **Matrix tested**:
  - Input amplitudes: `[-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]` (`float32`)
  - Sample rates: `8000`, `16000`, `44100` Hz
  - Channel configs: `channels=1` (mono 1D), `channels=2` (auto-stacked stereo from 1D), plus direct 2D stereo `(N, 2)` and 16-bit PCM (`sampwidth=2`)
- **Result**: **PASS** (8/8 PCM WAV write/decode cases passed under `-W error` with zero `RuntimeWarning`s):
  - Decoded `<i4` mono values match exact expected `[-2147483647, -2147483647, -1073741824, 0, 1073741824, 2147483647, 2147483647]` across all SRs (no `+1.0` → `-2147483648` wrap-around).
  - Stereo L/R channels and 2D stereo inputs decode bit-exact.
  - 16-bit PCM (`sampwidth=2`) decodes exact `[-32767, -32767, -16384, 0, 16384, 32767, 32767]`.
- **`make_speech_like` edge durations**:
  - `duration=0.0` and `duration=-0.5`: return `shape=(0,)`, `dtype=float32` cleanly without `ValueError`/`IndexError`.
  - `duration=1/16000` (1 sample) and `duration=0.5`: return finite `float32` arrays bounded within `[-0.95, 0.95]`.

### 2. M1-Only Isolation & Mutation Testing of `TestTier2Feature01ConfigBoundaries.test_model_config_invalid_arch_rejected`
- **Target**: `tests_e2e/test_tier2_boundaries.py:22-30`
- **AST check**: Verified zero `asr.models` imports anywhere inside `TestTier2Feature01ConfigBoundaries` (only `asr.config` is imported across all 5 methods).
- **Runtime M1-only isolation**: Executed `TestTier2Feature01ConfigBoundaries().test_model_config_invalid_arch_rejected()` with `sys.modules["asr.models"] = None` → **PASS** (proves zero runtime dependency on M3).
- **Mutation probes (genuinely fails against broken implementations)**:
  - `broken_model_only` (`ModelConfig` stops validating `arch`): test raised `pytest.fail.Exception` (**FAILED as expected**).
  - `broken_decode_only` (`DecodeConfig` stops validating `method`): test raised `pytest.fail.Exception` (**FAILED as expected**).
  - `both_broken` (neither validates): test raised `pytest.fail.Exception` (**FAILED as expected**).

### 3. Regression, Import-Safety & Collection Checks
- **Top-level import safety (AST)**:
  - `tests_e2e/conftest.py`: clean stdlib + `pytest` only (`['__future__', 'base64', 'io', 'os', 'subprocess', 'sys', 'wave', 'pathlib', 'types', 'typing', 'pytest']`); unused `math` and `struct` imports confirmed removed.
  - `tests_e2e/test_tier2_boundaries.py`: clean stdlib + `pytest` only (`['__future__', 'math', 'html.parser', 'pathlib', 'pytest']`).
- **Bytecode compilation**: `python3 -m py_compile tests_e2e/*.py` → `PY_COMPILE_OK` (exit 0).
- **Full suite collection**: `.venv/bin/pytest --collect-only tests_e2e/ -q` → **222 tests collected**, 0 errors (`test_tier1_features.py`: 103, `test_tier2_boundaries.py`: 98, `test_tier3_combinations.py`: 12, `test_tier4_scenarios.py`: 9).
- **Live M1 E2E subset under `-W error`**:
  - `.venv/bin/pytest tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py -k "Feature01 or Feature02 or Feature03 or Feature04 or Feature05 or Feature06" -W error -q`
  - **66/66 passed** with zero warnings and zero failures.
- **Working tree hygiene**: `git status --short` confirms no existing TTS files or repo files were modified by the challenger.
