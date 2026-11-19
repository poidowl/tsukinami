# Briefing — M7 Phase 2: Tier 5 White-Box Adversarial Coverage Hardening (`sub_orch_m7_t5`)

## Original Request
Verbatim path: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md`
Content: `ASRをつくって遊びたい` (Build an interactive Japanese ASR playground extending `tsukinami` without modifying existing TTS files).

## Current Baseline
- All 154/154 unit tests (`tests/`) and 222/222 opaque-box E2E tests (`tests_e2e/`, Tiers 1–4) — **376/376 total** — ALREADY PASS.
- M7 Phase 1 Whole-Project Forensic Audit is CLEAN.
- Existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) MUST remain completely unmodified.
- `tests_e2e/` MUST NOT be weakened or modified.

## Mission (Inverted Cycle — Challenger Initiates)
Perform white-box adversarial coverage hardening (Tier 5):
1. **Challengers Initiate**: Dispatch 2 `teamwork_preview_challenger` agents in parallel to inspect ALL `asr/`, `tests/`, and `tests_e2e/` code, run isolated scratch probes in `mktemp -d`, and report `GAPS_FOUND` (with concrete reproducible bugs or untested failure-mode gaps + proposed adversarial tests) or `NO_REMAINING_GAPS`.
   - Challenger 1: Core DSP, data pipeline, acoustic models, training, CTC decoding/alignment/metrics (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/models/`, `asr/train.py`, `asr/decoding.py`, `asr/metrics.py`).
   - Challenger 2: Inference engine, CLI, FastAPI server, and zero-CDN Web UI (`asr/inference.py`, `asr/__main__.py`, `asr/server.py`, `asr/web/index.html`) including security/robustness (malformed inputs, path traversal, NaN/Inf, concurrency, cache eviction, large/empty payloads).
2. **If EITHER Challenger reports `GAPS_FOUND`**:
   - Dispatch 1 `teamwork_preview_worker` to fix concrete bugs in `asr/` and add adversarial hardening tests in `tests/test_asr_tier5_hardening.py`.
   - Dispatch Parallel Verification Wave:
     - Primary Reviewer (`teamwork_preview_reviewer`): full `.venv/bin/pytest tests/ tests_e2e/ -v`.
     - Secondary Reviewer (`teamwork_preview_reviewer`): `.venv/bin/pytest tests/ -v` + code review.
     - Whole-Project Forensic Auditor (`teamwork_preview_auditor`): whole-project audit (NO sub-scope paths) + anti-cheating checks (binary veto).
   - Evaluate Gate in `GATE_STATUS.md`. Once PASS, loop back to Step 1 with 2 FRESH Challengers on the updated codebase.
3. **Termination**:
   - BOTH fresh Challengers report `NO_REMAINING_GAPS` AND latest codebase passed Reviewers + Whole-Project Forensic Auditor (`CLEAN`) + 100% full test suite, OR 32 iterations reached.
