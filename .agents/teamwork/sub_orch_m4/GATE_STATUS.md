# Gate Status — Milestone M4 (`sub_orch_m4`)

## Iteration 1 Gate Decision: `PASS`

### Evaluation Order (Strict AND; Forensic Auditor Evaluated FIRST)

| Role | Agent | Handoff Path | Independent Verification | Verdict |
|------|-------|--------------|--------------------------|---------|
| **Forensic Auditor** | `auditor_1` | `.agents/teamwork/sub_orch_m4/iter_1/auditor_1/handoff.md` | `.venv/bin/pytest -v tests/test_asr_decoding.py` (38 passed in 0.28s); `'torch' in sys.modules == False`; `git diff --stat` empty; M1 files untouched | **`CLEAN`** |
| **Primary Reviewer** | `rev_1` | `.agents/teamwork/sub_orch_m4/iter_1/rev_1/handoff.md` | `.venv/bin/pytest -v tests/test_asr_dsp.py tests/test_asr_decoding.py` (83 passed in 0.38s); edge-case & torch-isolation probes passed | **`APPROVE`** |
| **Secondary Reviewer** | `rev_2` | `.agents/teamwork/sub_orch_m4/iter_1/rev_2/handoff.md` | `.venv/bin/pytest -v tests/test_asr_decoding.py` (38 passed in 0.25s); numerical stability, determinism, `kotoba.split_moras` & latency verified | **`APPROVE`** |
| **Challenger 1 (Decoding)** | `chal_1` | `.agents/teamwork/sub_orch_m4/iter_1/chal_1/handoff.md` | Exact brute-force CTC marginalization oracle (`max_abs_err = 2.842e-14`), 32/32 brute-force Viterbi oracle matches, LM normalization `== 1.0`, extreme inputs & latency probes | **`PASS`** |
| **Challenger 2 (Metrics)** | `chal_2` | `.agents/teamwork/sub_orch_m4/iter_1/chal_2/handoff.md` | 200-pair Levenshtein math fuzzing (S+D+I, symmetry, triangle inequality, length conservation), Japanese CER/MER/WER/RTF, `confusion_pairs`, `alignment_boundary_error`, M1+M4 E2E probe | **`PASS`** |

### Strict AND Checklist
- [x] Forensic Auditor verdict == `CLEAN` (no binary veto triggered)
- [x] Independent verifier tests pass (83/83 DSP+Decoding; 38/38 Decoding)
- [x] Every Reviewer verdict == `APPROVE` (`rev_1`: APPROVE, `rev_2`: APPROVE)
- [x] Every Challenger confirms correctness (`chal_1`: PASS, `chal_2`: PASS)

### Non-Blocking Advisory Notes (For Downstream M5/M6 Awareness)
- Without LM, `prefix_beam_search` runs in `1.9–7.4 ms` for 1–3 s utterances (`T = 25..75, V = 86, beam_width = 8`), meeting the `<10 ms` `/api/redecode` target. With 3-gram LM enabled on long utterances (`T = 50..100`), latency is `12.7–40.3 ms`; optional candidate pruning or `(ctx, tok)` caching can be added later if M6 needs `<10 ms` with LM on long audio.
- `alignment_boundary_error` matches all speech moras cleanly across Hiragana/Katakana and small-kana digraphs; note that `kotoba.tracks_from_kana` normalizes `" "` to `"、"` while `Tokenizer("kana")` keeps `" "` as `" "`.
