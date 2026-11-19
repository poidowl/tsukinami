# Challenger 2 — Strict Contract Audit Handoff (Iteration 1, `sub_orch_e2e`)

## Verdict: **FAIL**

Two concrete issues were identified (1 HIGH progressive-testability failure empirically reproduced against live M1 `asr/` modules; 1 MEDIUM contract-ambiguity assumption on `POST /api/tts-roundtrip`). All other contract dimensions (624 AST-verified API calls, 19 CLI invocations, 34 HTTP calls, all return dict schemas, and 65/66 live M1 E2E tests) passed with 100% fidelity to `PROJECT.md § Interface Contracts`.

---

## Findings

### 1. [HIGH — Blocking] Progressive Testability Violation in Feature 1 (M1) Test
- **Location**: `tests_e2e/test_tier2_boundaries.py:23-29` (`TestTier2Feature01ConfigBoundaries.test_model_config_invalid_arch_rejected`)
- **Problem**: This Feature 1 (`asr/config.py`, Milestone M1) test unconditionally executes `from asr.models import build_model` (Milestone M3) on line 25 *before* `with pytest.raises(ValueError):`.
- **Empirical Evidence**: Running the M1 E2E subset against the currently implemented M1 modules (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`):
  ```bash
  .venv/bin/pytest tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py \
    -k "Feature01 or Feature02 or Feature03 or Feature04 or Feature05 or Feature06" -q --tb=short
  ```
  Result: **65 passed, 1 failed**:
  ```text
  FAILED tests_e2e/test_tier2_boundaries.py::TestTier2Feature01ConfigBoundaries::test_model_config_invalid_arch_rejected
  tests_e2e/test_tier2_boundaries.py:25: in test_model_config_invalid_arch_rejected
      from asr.models import build_model
  E   ModuleNotFoundError: No module named 'asr.models'
  ```
- **Why this violates the contract/scope**: `SCOPE.md` mandates progressive testability (earlier feature tests must not depend on later-milestone modules). Furthermore, `ModelConfig(arch="invalid_arch_xyz")` already raises `ValueError` in `asr/config.py`, and `build_model(ModelConfig(arch="resnet_999"), vocab_size=50)` is already covered in Feature 10 (`TestTier2Feature10ModelsBoundaries.test_build_model_invalid_arch_raises_value_error`, line 532).
- **Recommended Fix**: Remove `from asr.models import build_model` from `TestTier2Feature01ConfigBoundaries.test_model_config_invalid_arch_rejected` and assert `ValueError` directly on `ModelConfig(arch="invalid_arch_xyz")` (and optionally `DecodeConfig(method="invalid_method")`).

### 2. [MEDIUM] Rigid Scalar Assumption on `cer` Field in `POST /api/tts-roundtrip`
- **Location**: `tests_e2e/test_tier3_combinations.py:430` (`test_t3_api_tts_roundtrip_corruption_redecode_and_info`)
- **Code**: `assert float(rt_data["cer"]) >= 0.0`
- **Contract (`PROJECT.md § 8`, line 195 vs `§ 6`, line 174)**: `POST /api/tts-roundtrip` returns `audio_b64`, `ground_truth_moras`, `cer`, and `TranscribeResult`, while `compute_cer(...)` returns a dict `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`. A compliant M6 server returning `"cer": {"cer": 0.25, ...}` (instead of a bare float) would raise `TypeError: float() argument must be a string or a real number, not 'dict'`.
- **Contrast**: `tests_e2e/test_tier1_features.py:1415` safely checks `assert "cer" in data`.
- **Recommended Fix**: Accept either scalar numeric `cer` or dict `{"cer": ...}`:
  ```python
  cer_val = rt_data["cer"]["cer"] if isinstance(rt_data["cer"], dict) else rt_data["cer"]
  assert float(cer_val) >= 0.0
  ```

### 3. [LOW / Advisory] Implicit Multipart Field Name `"file"` on `POST /api/transcribe`
- **Locations**: `test_tier1_features.py:1396,1421`, `test_tier2_boundaries.py:1026,1033,1051`, `test_tier4_scenarios.py:188`.
- **Note**: `PROJECT.md § 8` (line 194) states "multipart WAV file (or JSON base64 WAV)" without naming the multipart form field; `tests_e2e/` uses `files={"file": (...)}`. While `file: UploadFile` is standard FastAPI convention, noting this explicitly in `TEST_INFRA.md` avoids any M6 mismatch (e.g., `audio` vs `file`).

---

## Summary of Passed Strict Contract Audits (AST + Live M1 Cross-Check)

| Audit Dimension | Scope | Result |
|---|---|---|
| `asr.*` imports & module paths | All 5 files in `tests_e2e/` (13 `asr.*` modules) | **PASS** — 100% match `PROJECT.md § Code Layout` & `§ Interface Contracts` |
| Function / class / method signatures & kwargs | **624** AST-extracted contract calls across `tests_e2e/` | **PASS** — **0** undocumented kwargs, **0** wrong arg counts |
| Return dict keys & checkpoint schema | All subscript / `.get()` / `in` checks across `tests_e2e/` | **PASS** (except Finding #2 on `/api/tts-roundtrip` `cer` type) |
| CLI subcommands & flags (`PROJECT.md § 7`) | **19** `run_cli(...)` invocations | **PASS** — all subcommands (`demo`, `generate`, `train`, `eval`, `transcribe`, `serve`) & flags match verbatim |
| FastAPI routes, methods, payloads & status codes (`PROJECT.md § 8`) | **34** `TestClient` calls | **PASS** — all routes (`/`, `/api/health`, `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`) match |
| Progressive testability (Tier 1 & Tier 2) | All 201 Tier 1 + Tier 2 tests across F1–F18 | **FAIL** — 1 violation (`test_tier2_boundaries.py:25`, Finding #1); 200/201 clean |
| Live M1 `asr/` execution (F1–F6) | 66 M1 tests against live `asr/{config,audio,features,tokenizer}.py` | **65/66 PASS**, 1 FAIL (Finding #1) |
| `try/except` audit | 5 `try/except` blocks in `test_tier2_boundaries.py` | **PASS** — all narrow (`ValueError` / config empty-dict) for legitimate contract edge ambiguities; zero `ImportError` / `Exception` masking |

---

## Cleanup Verification
- Temporary probe directory (`/tmp/teamwork_probe.EavoFg`) was created via `mktemp -d` and removed prior to reporting (`TEMP_DIR_REMOVED`).
- Working tree was not modified.
