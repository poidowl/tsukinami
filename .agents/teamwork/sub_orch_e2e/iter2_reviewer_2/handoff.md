# Secondary Reviewer Handoff — Iteration 2 (`sub_orch_e2e`)

## Verdict: **APPROVE**

All Iteration 2 targeted fixes within my review scope (`tests_e2e/conftest.py`, `tests_e2e/test_tier3_combinations.py`, `tests_e2e/test_tier4_scenarios.py`, and `TEST_INFRA.md`) are verified against `PROJECT.md`, `SCOPE.md`, and `GATE_STATUS.md`.

---

## Independent Verification Evidence

### 1. Tier 3 & Tier 4 Collection (`--collect-only`)
Command (Cwd: `/home/antigravity/poidowl/tsukinami`):
```bash
.venv/bin/pytest --collect-only tests_e2e/test_tier3_combinations.py tests_e2e/test_tier4_scenarios.py -q
```
Output (exit 0):
```text
tests_e2e/test_tier3_combinations.py: 12
tests_e2e/test_tier4_scenarios.py: 9
```
Result: **21 tests collected** (0 errors).

### 2. Live Existing Tsukinami TTS Non-Regression
Command:
```bash
.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -k test_t4_scenario9_existing_tsukinami_tts_non_regression -v
```
Output (exit 0):
```text
tests_e2e/test_tier4_scenarios.py .                                      [100%]
======================= 1 passed, 8 deselected in 2.89s ========================
```
Result: **1/1 passed**.

### 3. Direct Verification of Iteration 2 Fixes

1. **`tests_e2e/conftest.py`**
   - **32-bit PCM float64 scaling** (line 111):
     `pcm = np.round(clipped.astype(np.float64) * 2147483647.0).astype("<i4").tobytes()`
     Verified independently under `.venv/bin/python -W error` (temporary probe directory created and removed): input `[-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]` wrote and decoded back to exact `<i4` values `[-2147483647, -2147483647, -1073741824, 0, 1073741824, 2147483647, 2147483647]` with zero `RuntimeWarning` or `int32` overflow.
   - **`make_speech_like` zero/negative duration guard** (lines 56–57):
     `if total_n <= 0: return np.zeros(0, dtype=np.float32)`
     Verified with `duration=0.0` and `duration=-0.2` returning shape `(0,)` `float32` cleanly.
   - **Unused imports removed** (lines 12–22): `math` and `struct` are no longer imported.
   - Bytecode compilation (`python3 -m py_compile`) passed on `conftest.py`, `test_tier3_combinations.py`, and `test_tier4_scenarios.py`.

2. **`tests_e2e/test_tier3_combinations.py`**
   - **Resilient `cer` scalar/dict handling** (lines 430–431 in `test_t3_api_tts_roundtrip_corruption_redecode_and_info`):
     ```python
     cer_val = rt_data["cer"]["cer"] if isinstance(rt_data["cer"], dict) else rt_data["cer"]
     assert float(cer_val) >= 0.0
     ```
     Handles both scalar numeric `cer` and `compute_cer(...)` dict `{"cer": float, ...}` cleanly.
   - Audited `tests_e2e/test_tier4_scenarios.py` via `grep -n 'cer'`: all `cer` assertions operate on `compute_cer(...)` dicts or CLI output text; no bare `float(data["cer"])` assumption exists on `/api/tts-roundtrip`.

3. **`TEST_INFRA.md`**
   - Line 7 explicitly documents:
     `For POST /api/transcribe multipart WAV uploads, the suite uses the standard FastAPI form field name "file" (files={"file": (...)}).`

4. **Repository Hygiene (`git status --short`)**
   - Confirmed no existing TTS files were modified. No stray probe files remain.
