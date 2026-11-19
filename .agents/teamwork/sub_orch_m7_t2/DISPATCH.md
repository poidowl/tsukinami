# Dispatch Log — `sub_orch_m7_t2`

## Iteration 1 — Step a (Explorers)
- `iter1_explorer_1` (`4958d8159118e712ee0fcc6f3141ad70`): Tier 2 Live Test Runner & Failure Diagnostician
- `iter1_explorer_2` (`1c544328bc0eca82843487866c9b55c1`): Features 1–11 Boundary Analyst
- `iter1_explorer_3` (`4326ecdd6307c1d6529c3d7d437a48b1`): Features 12–18 Boundary Analyst

## Iteration 1 — Step b (Worker)
- `iter1_worker` (`47c0c1780b5113631d82ab2bd0fed868`): Fix `build_manifest_from_wav_dir` in `asr/dataset.py`, add unit regression tests in `tests/test_asr_data.py`, verify full unit + Tier 1 + Tier 2 suites.

## Iteration 1 — Steps c, d, e (Parallel Verification Wave)
- `iter1_reviewer_primary` (`1f5e6ba86106315939ee62df429e179b`): Primary Reviewer (full `tests/` + Tier 1 + Tier 2 E2E run)
- `iter1_reviewer_secondary` (`2a72a4c4be81dccab99a63141ffb39c2`): Secondary Reviewer (unit `tests/` + diff review)
- `iter1_challenger_1` (`f9e491b7e53752948c8e2135611e34ff`): Challenger 1 (Dataset & F1–11 boundary probes)
- `iter1_challenger_2` (`3527b7f712a3fe7e3453b0ec454c4e3d`): Challenger 2 (F12–18 boundary probes)
- `iter1_auditor` (`2a0e5124bbd422d9f0749455db78f770`): Forensic Auditor (Intermediate Milestone Audit)
