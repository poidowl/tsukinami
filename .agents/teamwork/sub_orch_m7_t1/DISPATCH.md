# Dispatch Log — `sub_orch_m7_t1`

## Iteration 1 — Step a (Explorers)
- **Explorer 1** (`122d3d17b1cc443fbe4f0766a614fd9c`): Tier 1 E2E Runner & Failure Diagnostician -> `iter1_explorer_1/handoff.md`
- **Explorer 2** (`917a6affea9002184eee9165391bdd0b`): Unit Tests & Features #1–#11 Contract Auditor -> `iter1_explorer_2/handoff.md`
- **Explorer 3** (`7488943c1b8ec7501ad2bf962d3e5d8b`): Features #12–#18 Contract & TTS Non-Regression Auditor -> `iter1_explorer_3/handoff.md`

## Iteration 1 — Step b (Worker)
- **Worker 1**: Tier 1 Manifest Path Fix Worker -> `iter1_worker/handoff.md` (exclusive ownership: `asr/synth_data.py`, `asr/dataset.py`, `tests/test_asr_data.py`)

## Iteration 1 — Steps c, d, e (Parallel Verification Wave)
- **Primary Reviewer** (`iter1_reviewer_1/handoff.md`): Full suite `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py -v` + code/contract review
- **Secondary Reviewer** (`iter1_reviewer_2/handoff.md`): Target-scoped `.venv/bin/pytest tests/ -v` + code/compatibility review
- **Challenger 1** (`iter1_challenger_1/handoff.md`): Isolated temp-dir adversarial probes on manifest/dataset pipeline
- **Challenger 2** (`iter1_challenger_2/handoff.md`): Isolated temp-dir adversarial probes on Tier 1 contracts & cross-module handoffs
- **Forensic Auditor** (`iter1_auditor/handoff.md`): Intermediate milestone audit (`asr/`, `tests/`, `tests_e2e/conftest.py`, `tests_e2e/test_tier1_features.py`)
