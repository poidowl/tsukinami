# Iteration 2 Step b — E2E Test Writer Handoff (`sub_orch_e2e`)

## Summary of Targeted Fixes

All four required fixes from `GATE_STATUS.md` (Challenger 1 & Challenger 2 findings) were applied strictly within exclusive file ownership (`TEST_INFRA.md`, `tests_e2e/conftest.py`, `tests_e2e/test_tier2_boundaries.py`, `tests_e2e/test_tier3_combinations.py`):

1. **`tests_e2e/conftest.py`**
   - Fixed 32-bit PCM `int32` overflow in `write_pcm_wav` (`sampwidth == 4`) by upcasting `clipped` to `np.float64` before scaling:
     `pcm = np.round(clipped.astype(np.float64) * 2147483647.0).astype("<i4").tobytes()`
   - Added `total_n <= 0` guard in `make_speech_like` (`if total_n <= 0: return np.zeros(0, dtype=np.float32)`).
   - Removed unused `math` and `struct` imports.
2. **`tests_e2e/test_tier2_boundaries.py`**
   - Removed `from asr.models import build_model` (M3) from `TestTier2Feature01ConfigBoundaries.test_model_config_invalid_arch_rejected` so Feature 1 (M1) tests have zero dependency on M3 (`asr.models`), preserving progressive testability.
   - Tested M1-only `ModelConfig(arch="invalid_arch_xyz")` and `DecodeConfig(method="invalid_method")` validation directly.
3. **`tests_e2e/test_tier3_combinations.py`**
   - Updated `test_t3_api_tts_roundtrip_corruption_redecode_and_info` to accept either scalar numeric `cer` or `compute_cer(...)` dict `{"cer": float, ...}`:
     `cer_val = rt_data["cer"]["cer"] if isinstance(rt_data["cer"], dict) else rt_data["cer"]`
     `assert float(cer_val) >= 0.0`
   - Audited `tests_e2e/test_tier4_scenarios.py`: confirmed no `float(data["cer"])` assumption on `/api/tts-roundtrip` exists (so `test_tier4_scenarios.py` required no edits).
4. **`TEST_INFRA.md`**
   - Explicitly documented under § 1 that `POST /api/transcribe` multipart WAV uploads use the standard FastAPI form field name `"file"` (`files={"file": (...)}`).

---

## Post-Edit Canonical Verification

All commands were executed from `/home/antigravity/poidowl/tsukinami` after the final edit:

### 1. Syntax / Bytecode Compilation
```bash
python3 -m py_compile tests_e2e/conftest.py tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py tests_e2e/test_tier3_combinations.py tests_e2e/test_tier4_scenarios.py && echo "PY_COMPILE_OK"
```
Output (exit 0):
```text
PY_COMPILE_OK
```

### 2. Full Suite Collection (`--collect-only`)
```bash
.venv/bin/pytest --collect-only tests_e2e/ -q
```
Output (exit 0):
```text
tests_e2e/test_tier1_features.py: 103
tests_e2e/test_tier2_boundaries.py: 98
tests_e2e/test_tier3_combinations.py: 12
tests_e2e/test_tier4_scenarios.py: 9
```
Total collected: **222 tests** (0 errors).

### 3. Live M1 E2E Subset (Features 1–6)
```bash
.venv/bin/pytest tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py -k "Feature01 or Feature02 or Feature03 or Feature04 or Feature05 or Feature06" -q
```
Output (exit 0):
```text
..................................................................       [100%]
```
Result: **66/66 passed** (up from 65/66; zero warnings/failures).

### 4. Existing Tsukinami TTS Non-Regression
```bash
.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -k test_t4_scenario9_existing_tsukinami_tts_non_regression -q
```
Output (exit 0):
```text
.                                                                        [100%]
```
Result: **1/1 passed**.

### 5. Direct Verification of `conftest.py` 32-bit PCM Fix & Zero-Duration Guard (`-W error`)
```bash
.venv/bin/python -W error -c '
import tempfile, wave
from pathlib import Path
import numpy as np
from tests_e2e.conftest import make_speech_like, write_pcm_wav

z = make_speech_like(duration=0.0, sr=16000)
assert z.shape == (0,) and z.dtype == np.float32

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "pcm32.wav"
    arr = np.array([-1.0, -0.5, 0.0, 0.5, 1.0, 2.0, -2.0], dtype=np.float32)
    write_pcm_wav(p, arr, sr=16000, channels=1, sampwidth=4)
    with wave.open(str(p), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    decoded = np.frombuffer(raw, dtype="<i4")
    assert decoded.tolist() == [-2147483647, -1073741824, 0, 1073741824, 2147483647, 2147483647, -2147483647], decoded.tolist()
print("CONFTEST_HELPER_CHECKS_OK")
'
```
Output (exit 0):
```text
CONFTEST_HELPER_CHECKS_OK
```

### 6. Git Status Check
```bash
git status --short
```
Output (exit 0):
```text
?? .agents/
?? .gitignore
?? PROJECT.md
?? TEST_INFRA.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/
```
Existing TTS files, `TEST_READY.md`, `asr/`, `tests/`, `pyproject.toml`, and `.gitignore` were untouched.
