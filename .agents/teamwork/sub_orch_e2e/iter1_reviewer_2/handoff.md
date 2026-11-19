# Secondary Reviewer Handoff — Iteration 1 (`sub_orch_e2e`)

## Verdict: APPROVE

`tests_e2e/conftest.py`, `tests_e2e/test_tier3_combinations.py`, and `tests_e2e/test_tier4_scenarios.py` meet all requirements in `PROJECT.md` and `SCOPE.md`, collect cleanly without top-level `asr.*`/ML imports, strictly match `PROJECT.md § Interface Contracts`, and pass independent execution of the existing `tsukinami` TTS non-regression test.

---

## Independent Verification Outputs

Executed from `/home/antigravity/poidowl/tsukinami` without modifying the working tree:

### 1. Bytecode Compilation (`py_compile`)
Command:
```bash
python3 -m py_compile tests_e2e/conftest.py tests_e2e/test_tier3_combinations.py tests_e2e/test_tier4_scenarios.py && echo "PY_COMPILE_OK"
```
Output (exit code `0`):
```text
PY_COMPILE_OK
```

### 2. Pytest Collection Check (Tier 3 & Tier 4)
Command:
```bash
.venv/bin/pytest --collect-only tests_e2e/test_tier3_combinations.py tests_e2e/test_tier4_scenarios.py -q
```
Output (exit code `0`):
```text
tests_e2e/test_tier3_combinations.py: 12
tests_e2e/test_tier4_scenarios.py: 9
```

### 3. Existing `tsukinami` TTS Non-Regression Execution (Tier 4 Scenario 9)
Command:
```bash
.venv/bin/pytest tests_e2e/test_tier4_scenarios.py -k test_t4_scenario9_existing_tsukinami_tts_non_regression -v
```
Output (exit code `0`):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 9 items / 8 deselected / 1 selected

tests_e2e/test_tier4_scenarios.py .                                      [100%]

======================= 1 passed, 8 deselected in 2.77s ========================
```

---

## Detailed Review Findings

### 1. `tests_e2e/conftest.py`
- **Lazy Imports & Collection Hygiene**: Only stdlib modules and `pytest` are imported at top level; all `numpy`, `torch`, `fastapi`, and `asr.*` imports live inside helper/fixture bodies.
- **Independent Test Helpers**: Pure stdlib/NumPy signal, WAV, corrupt-WAV, base64, and synthetic log-prob helpers are decoupled from `asr.*`. `extract_transcribe_payload` gracefully handles both flat and nested `/api/tts-roundtrip` JSON shapes.
- **CPU/RAM Guardrails**: Session-scoped fixtures (`tiny_fast_dataset`: 12 train / 4 val; `tiny_checkpoint`: `cnn_bigru`, `hidden_size=32`, `num_layers=1`, `epochs=2`, `batch_size=4`, `torch.set_num_threads(2)`) and `run_cli` (`OMP_NUM_THREADS=2`, `MKL_NUM_THREADS=2`) keep resource usage well within the 2-vCPU / 7.8 GiB RAM budget.
- **Minor non-blocking nit**: `math` and `struct` imports on lines 14 and 16 are unused.

### 2. `tests_e2e/test_tier3_combinations.py` (12 Tests)
- **Genuine Pairwise Cross-Feature Coverage**: All 18 product features participate in meaningful cross-module combinations:
  - F2/F3/F4/F5/F7: fast synth + white/pink noise + Log-Mel / MFCC+deltas + VAD (`test_t3_corruption_noise_features_and_vad`), speed / telephone band-limit / gain + Log-Mel CMVN (`test_t3_corruption_speed_bandlimit_gain_features`).
  - F2/F3/F5/F6/F7/F9: fast synth + `kana` & `phoneme` tokenizers + `ASRManifestDataset` + `collate_asr_batch` + `spec_augment`.
  - F2/F3/F8: `tsukinami` presets (`default` vs `ossan`) + disk cache hit + WAV roundtrip + Log-Mel divergence.
  - F1/F10/F11: `cnn_bigru` training + checkpoint save/reload + resume (`epoch >= 2`) + `subsampling_factor == 4` / `output_frame_stride_ms == 40.0`; `conformer_lite` training + checkpoint load + `log_softmax` probability sum invariant.
  - F7/F10/F12/F13/F14: model log-probs → greedy, beam, beam + `CharNgramLM` (`to_dict`/`from_dict`), `viterbi_align`, `alignment_boundary_error`, `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`.
  - F5/F12/F15: `ASREngine` clean & noisy `transcribe(include_visuals=True)` + cached `redecode`.
  - F1/F7/F9/F11/F15/F16: full CLI subprocess pipeline (`generate -> train -> eval -> transcribe --wav / --tts`).
  - F5/F8/F12/F15/F17/F18: FastAPI `/api/info` -> `/api/tts-roundtrip` (with corruption) -> `/api/redecode` -> `/` zero-CDN HTML check.
- **Contract Alignment**: All function names, kwargs, CLI flags, HTTP routes, and return dictionary keys match `PROJECT.md § Interface Contracts` verbatim.

### 3. `tests_e2e/test_tier4_scenarios.py` (9 Scenarios)
All 9 required real-world scenarios are present, substantive, and flake-resistant:
1. `test_t4_scenario1_one_command_cpu_quickstart_demo`: Full `python -m asr demo` subprocess run (`--epochs 2 --num-train 16 --arch cnn_bigru`), verifying manifests, checkpoint reload via `ASREngine`, transcription, and CER output without brittle accuracy thresholds.
2. `test_t4_scenario2_multi_preset_tsukinami_roundtrip_and_alignment`: 5 presets (`default`, `ossan`, `robot`, `whisper`, `chibi`) on `"あか"` with disk caching, verifying waveform invariants, CER/MER/RTF/alignment boundary error, and pairwise acoustic distinctness.
3. `test_t4_scenario3_noisy_and_telephone_degradation_experiment`: Clean vs white 5 dB vs pink 10 dB vs telephone (300–3400 Hz) verifying spectral divergence and high-frequency Mel attenuation.
4. `test_t4_scenario4_interactive_web_playground_full_session`: End-to-end HTTP session (`/`, `/api/health`, `/api/info`, `/api/tts-roundtrip`, 4-config `/api/redecode` sweep, multipart `/api/transcribe` with visuals).
5. `test_t4_scenario5_custom_wav_folder_tier3_corpus_workflow`: Custom WAV folder including 22.05 kHz resampling -> `build_manifest_from_wav_dir` -> train -> `ASREngine` -> CER/WER.
6. `test_t4_scenario6_architecture_comparison_and_checkpoint_resume`: `cnn_bigru` vs `conformer_lite` train + resume (`epoch >= 2`) + `ASREngine` inference.
7. `test_t4_scenario7_decoding_strategy_and_ngram_lm_study`: `CharNgramLM` fit/roundtrip + Greedy vs Beam vs Beam+LM evaluation with CER/MER/WER/confusion_pairs.
8. `test_t4_scenario8_live_engine_visuals_and_fast_redecode_sweep`: Visual payload invariants (including CTC posterior simplex sum-to-1) + warmed-up median `<10 ms` greedy redecode sweep and `<50 ms` beam sweep.
9. `test_t4_scenario9_existing_tsukinami_tts_non_regression`: Verified live (`PASSED in 2.77s`) against `kotoba`, `accent`, `yomu`, `carve` (44.1 kHz WAV output).

---

## Summary
No blocking issues found. Zero skips, zero dummy passes, strict contract fidelity, and sensible CPU/RAM budgets. **Verdict: APPROVE.**
