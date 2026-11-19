# Scope — M7 Phase 1: Tier 4 E2E & Full-Suite Final Verification

## In-Scope Targets
1. **Tier 4 Real-World Application Scenarios** (`tests_e2e/test_tier4_scenarios.py`, 9 tests):
   - Scenario 1: One-command CPU `python -m asr demo` workflow
   - Scenario 2: 5-preset `tsukinami` TTS→ASR round-trip (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`)
   - Scenario 3: Noisy / telephone band-limit degradation study
   - Scenario 4: Full Web Playground session (`/`, `/api/health`, `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`)
   - Scenario 5: Tier-3 WAV folder corpus (`build_manifest_from_wav_dir` → train → eval → transcribe)
   - Scenario 6: `cnn_bigru` vs `conformer_lite` comparison & checkpoint resume
   - Scenario 7: CTC decoding + `CharNgramLM` study
   - Scenario 8: Visuals (`waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`) + `<10 ms` cached redecode sweep
   - Scenario 9: Existing `tsukinami` TTS non-regression
2. **Full E2E Suite** (`tests_e2e/`, 222 tests across Tiers 1–4)
3. **Full Unit Test Suite** (`tests/`, 154+ tests across M1–M6)
4. **Whole-Project Integrity**:
   - All `asr/` modules (`asr/**/*.py`, `asr/web/index.html`)
   - All `tests/` unit tests
   - All `tests_e2e/` E2E tests (read-only; NEVER weaken/skip/xfail/hardcode)
   - Existing `tsukinami` TTS files untouched (`git status` / `git diff`)

## Out-of-Scope / Protected
- Existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) MUST NOT be modified.
- `tests_e2e/` MUST NOT be weakened, skipped, xfailed, or altered to pass artificially.
