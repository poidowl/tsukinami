# Final Milestone M7 Phase 1 — Tier 4 E2E Handoff (`sub_orch_m7_t4`)

## Outcome
**GATE STATUS: PASS (Iteration 1)**

- **Tier 4 E2E (`tests_e2e/test_tier4_scenarios.py`)**: **9 / 9 PASSED**
- **Full E2E Suite (`tests_e2e/`, Tiers 1–4)**: **222 / 222 PASSED** (103 Tier 1 + 98 Tier 2 + 12 Tier 3 + 9 Tier 4)
- **Full Unit Suite (`tests/`, M1–M6)**: **154 / 154 PASSED**
- **Combined Independent Full Run (`.venv/bin/pytest tests/ tests_e2e/ -v`)**: **376 / 376 PASSED** (0 failed, 0 skipped, 0 xfailed; exit code `0`, 319.64s)
- **Whole-Project Forensic Audit**: **`CLEAN`**
- **Protected Files**: Zero existing `tsukinami` TTS files modified (`git diff` empty); `tests_e2e/` 100% untouched.

---

## Root Cause Found & Fixed (Iteration 1)

Initial Step a exploration (`iter1_exp1`–`iter1_exp3`) ran `.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -v` and found **7/9 passed, 2 failed** (Scenario 3 line 131 and Scenario 8 lines 374–379) due to a single contract mismatch:
- `asr/inference.py` (`_build_ctc_posteriors`) returned `result["ctc_posteriors"]` as a top-K summary `dict` (`{"times_sec", "top_tokens", "probs"}`), whereas Tier 4 Scenarios 3 & 8 expect a 2D full-vocabulary numeric probability matrix `(T', V)` in `[0.0, 1.0]` whose frame rows sum to `1.0`.

### Changes Applied by Worker (`iter1_worker`)
1. **`asr/inference.py`**: Refactored `_build_ctc_posteriors()` to return a numerically stable, JSON-serializable 2D full-vocabulary posterior probability matrix `list[list[float]]` of shape `(T_vis, V)` (or `[]` on empty audio), sanitizing non-finite values, renormalizing rows to sum to `1.0`, and rounding to 6 decimal places (`atol < 1e-4`), and updated `ASREngine.transcribe()`.
2. **`asr/web/index.html`**: Updated `drawCtcPosteriors()` to natively render 2D `(T, V)` posterior arrays by selecting `blank_id` + top-11 non-blank tokens by peak probability using `state.info.vocab` (retaining fallback support for the legacy `{probs, top_tokens}` format).
3. **`tests/test_asr_cli.py` & `tests/test_asr_web.py`**: Updated unit test assertions to strictly verify the 2D `(T', vocab_size)` shape, finiteness, `[0.0, 1.0]` bounds, row-sum normalization (`atol=1e-4`), and empty audio (`[]`).

---

## 5-Verifier Parallel Wave Summary (`GATE_STATUS.md`)

1. **Whole-Project Forensic Auditor (`iter1_audit/handoff.md`)**: **`CLEAN`**
   - Audited all 18 `asr/` files (`asr/**/*.py`, `asr/web/index.html`), all `tests/` (154/154 PASS, 0 vacuous, 0 skips/xfails), all `tests_e2e/` (222 tests unmodified since freeze, 0 skips/xfails/mocks/vacuous), and `git status` / `git diff` (empty — all existing `tsukinami` TTS files untouched).
2. **Primary Reviewer (`iter1_rev1/handoff.md`)**: **`APPROVE`**
   - Ran full `.venv/bin/pytest tests/ tests_e2e/ -v`: **376/376 PASSED** (exit code 0, 319.64s). Verified all 4 modified files and `git status`.
3. **Secondary Reviewer (`iter1_rev2/handoff.md`)**: **`APPROVE`**
   - Ran `.venv/bin/pytest tests/ -v`: **154/154 PASSED** (exit code 0). Verified numerical edge cases in Python and `drawCtcPosteriors` in Node.js.
4. **Challenger 1 (`iter1_chal1/handoff.md`)**: **`CONFIRMED_CORRECT`**
   - Passed all 5 isolated adversarial probe suites (direct `_build_ctc_posteriors` edge cases, `ASREngine` empty/1-sample/NaN/18s-long audio on `cnn_bigru` & `conformer_lite`, Corruption Lab extremes, 6-preset `tsukinami` round-trip + Viterbi alignment, CLI end-to-end & 12 error cases).
5. **Challenger 2 (`iter1_chal2/handoff.md`)**: **`CONFIRMED_CORRECT`**
   - Passed all isolated adversarial probes (FastAPI `create_app` endpoints + 16 invalid audio/param error cases + `<10 ms` cached redecode, HTTP JSON `ctc_posteriors` 2D normalization, zero-CDN audit + Node.js `drawCtcPosteriors` execution, Tier-3 WAV folder corpus workflow).

---

## State Artifacts
- Gate status: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/GATE_STATUS.md`
- Worker handoff: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/iter1_worker/handoff.md`
- Verifier handoffs:
  - `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/iter1_audit/handoff.md`
  - `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/iter1_rev1/handoff.md`
  - `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/iter1_rev2/handoff.md`
  - `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/iter1_chal1/handoff.md`
  - `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m7_t4/iter1_chal2/handoff.md`
