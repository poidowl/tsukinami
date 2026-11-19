# DISPATCH Log — sub_orch_m7_t3

## Iteration 1 — Step a (Explorers)
- `iter1_exp1` (`18264c94702282ff8fd6c4d0b8ba4719`): Tier 3 Test Runner Explorer — running `.venv/bin/pytest tests_e2e/test_tier3_combinations.py -v` and checking `git status`
- `iter1_exp2` (`6b64ebaa9be7c4777305cc8543bf9c05`): DSP Data Model Explorer — inspecting Tier 3 tests 1–6 against `asr/`
- `iter1_exp3` (`c36eadfe450d9380b3cd3b7b157672e9`): Decoding CLI Web Explorer — inspecting Tier 3 tests 7–12 against `asr/`

## Iteration 1 — Steps c, d, e (Parallel 5-Verifier Wave)
- `iter1_rev_primary` (`311030e344284504613c0d9e1f4a1e6c`): Primary Reviewer — full `.venv/bin/pytest tests/ tests_e2e/test_tier1_features.py tests_e2e/test_tier2_boundaries.py tests_e2e/test_tier3_combinations.py -v`
- `iter1_rev_secondary` (`3a38b6eb60d4f965eede90c29f9bbe8c`): Secondary Reviewer — target-scoped `.venv/bin/pytest tests/ -v` + cross-feature review
- `iter1_chal1` (`99b8af70f466b9f44e799f383e49b6b9`): Challenger 1 — DSP/Data/Tokenizer/Model/Training adversarial probes
- `iter1_chal2` (`0bad025f3cb875f551e07004690900fc`): Challenger 2 — Decoding/Alignment/Metrics/Engine/API adversarial probes
- `iter1_auditor` (`2140c4bdb5788ee907c6c701eefb3c4e`): Forensic Auditor — intermediate milestone audit on `asr/`, `tests/`, `tests_e2e/conftest.py`, `test_tier1_features.py`, `test_tier2_boundaries.py`, `test_tier3_combinations.py`
