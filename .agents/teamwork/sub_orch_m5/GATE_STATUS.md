# Gate Status — Milestone M5 (`sub_orch_m5`)

## Iteration 1 Gate — **FAIL**

| Role | Agent | Test Result | Verdict |
|------|-------|-------------|---------|
| Forensic Auditor | `aud1` | 13/13 (`test_asr_cli.py`) | **CLEAN** |
| Primary Reviewer | `rev1` | 132/132 (M1–M5 full suite) | **APPROVE** |
| Secondary Reviewer | `rev2` | 13/13 (`test_asr_cli.py`) | **APPROVE** |
| Challenger 1 | `chal1` | Adversarial `ASREngine` probes | **FAIL** (2 bugs in `_prepare_waveform`) |
| Challenger 2 | `chal2` | 51/52 CLI probes | **FAIL** (1 bug: uncaught `OverflowError` on corrupt checkpoint) |

Issues fixed in Iteration 2 (`worker2`):
1. Channels-first stereo `(C, N)` handling in `_prepare_waveform`.
2. Signed/unsigned integer PCM normalization to `[-1.0, 1.0]` in `_prepare_waveform`.
3. Corrupt checkpoint exception normalization in `ASREngine.from_checkpoint` and `asr/__main__.py:main()`.
4. Added 3 regression tests in `tests/test_asr_cli.py`.

---

## Iteration 2 Gate — **PASS**

### Verifier Verdicts (Strict AND)
| Role | Agent | Verification Result | Verdict |
|------|-------|---------------------|---------|
| Forensic Auditor | `aud2` | 16/16 (`test_asr_cli.py`), scope & anti-cheating verified | **CLEAN** |
| Primary Reviewer | `rev3` | 135/135 (full M1–M5 unit test suite, 76.35s) | **APPROVE** |
| Secondary Reviewer | `rev4` | 16/16 (`test_asr_cli.py`, 20.58s) | **APPROVE** |
| Challenger 3 | `chal3` | 22/22 adversarial `ASREngine` probes | **CONFIRMED** |
| Challenger 4 | `chal4` | 51/51 adversarial CLI subprocess probes | **CONFIRMED** |

### Final Decision
**PASS** — Forensic Auditor is `CLEAN`, both Reviewers `APPROVE`, both Challengers `CONFIRMED`, and all 135 M1–M5 unit tests pass independently with zero regressions and intact exclusive file ownership.
