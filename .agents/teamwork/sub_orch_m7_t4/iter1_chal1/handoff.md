# Challenger 1 Handoff — M7 Phase 1 Tier 4 E2E (`sub_orch_m7_t4` / `iter1_chal1`)

## Verdict
**`CONFIRMED_CORRECT`**

All isolated adversarial probes covering `_build_ctc_posteriors`, `ASREngine.transcribe(..., include_visuals=True)`, Corruption Lab extremes, 6-preset `tsukinami` round-trip + Viterbi alignment, and `python -m asr` CLI end-to-end & error-handling contracts passed with **0 failures**.

---

## Probe Execution Environment & Hygiene
- **Python**: `/home/antigravity/poidowl/tsukinami/.venv/bin/python` with `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `torch.set_num_threads(1)`.
- **Staging**: Executed in an isolated temp directory created with `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and removed automatically via `trap 'rm -rf "$PROBE_DIR"' EXIT`.
- **Cleanup verified**: `ls -d "${TMPDIR:-/tmp}"/teamwork_probe.*` returned no leftover directories; `git status --short` confirmed zero repository modifications.

---

## Adversarial Probe Results

### 1. Direct `_build_ctc_posteriors` Edge Cases
- **Empty / degenerate shapes**: `(0, 10)`, `(5, 0)`, and 1D `(10,)` all returned `[]`.
- **Non-finite & extreme log-probs**: all `-inf`, all `NaN`, all `+inf`, mixed `[NaN, -inf, +inf, -1.0, -2.0]`, and extreme `[1e10, -1e10, 0.0, -5.0]` all produced finite probabilities in `[0.0, 1.0]`, passed `json.dumps(..., allow_nan=False)`, and summed to `1.0` with max error `<= 2.22e-16`.
- **Frame downsampling & wide vocab**: `(500, 80)` downsampled cleanly to exact length `400` (`max |row_sum - 1.0| = 1.00e-05`); `(3, 500)` uniform log-probs preserved width `500` (`max |row_sum - 1.0| = 4.44e-16`).

### 2. `ASREngine.transcribe(..., include_visuals=True)` Edge Cases (`cnn_bigru` & `conformer_lite`)
- **Empty audio** (`0` samples): returned `text == ""`, `ctc_posteriors == []`, `waveform == []`, `log_mel == []`, `vad_segments == []`, and valid strict JSON.
- **1-sample & ultra-short audio** (`1, 10, 160, 399, 400, 800` samples): both `cnn_bigru` and `conformer_lite` succeeded without crash, produced valid `(1, 86)` posteriors (`max |row_sum - 1.0| <= 4.00e-06`), passed strict JSON serialization, and supported cached `engine.redecode(...)`.
- **Non-finite audio** (`[NaN, +inf, -inf, 0.1, ...]`): sanitized cleanly with finite `(3, 86)` posteriors (`max |row_sum - 1.0| <= 5.00e-06`) and strict JSON compliance.
- **Very long audio** (`18s` / `288,000` samples -> `>400` output frames): downsampled cleanly to `len(ctc_posteriors) == 400`, `len(waveform) == 2000 <= 2000`, `len(log_mel) == 600 <= 600`, `max |row_sum - 1.0| = 8.00e-06`, and strict JSON (`1,178,319` bytes).

### 3. Corruption Lab Extremes (`apply_corruption` + `ASREngine`)
Tested `snr_db=-5.0` (`white` and `pink`), `band_limit=(300.0, 3400.0)`, `speed=0.8`, `speed=1.25`, and all combined (`snr_db=-5.0, noise_type="pink", band_limit=(300.0, 3400.0), speed=0.8, gain_db=6.0`):
- All outputs were finite 1D `float32` waveforms.
- All `transcribe(..., method="beam", beam_width=4, include_visuals=True)` calls produced valid `(T_vis, 86)` posteriors (`max |row_sum - 1.0| <= 8.00e-06`) and passed `json.dumps(..., allow_nan=False)`.

### 4. Multi-Preset `tsukinami` Round-Trip & Viterbi Alignment
Verified all 6 presets (`default`, `ossan`, `robot`, `whisper`, `chibi`, `horror`) present in `DEFAULT_TSUKINAMI_PRESETS`:
- Every preset synthesized finite, non-empty 1D `float32` waveforms and non-empty ground-truth moras.
- Both `greedy` and `beam` decoding produced valid `(T_vis, 86)` posteriors (`max |row_sum - 1.0| <= 8.00e-06`), passed strict JSON serialization, and produced valid monotonic Viterbi alignment segments (`0.0 <= start_sec <= end_sec`, `0.0 <= confidence <= 1.0`, all finite).

### 5. CLI `python -m asr` End-to-End & Error Handling
- **`demo`**: `python -m asr demo --out-dir <tmp>/demo_run --epochs 1 --num-train 4 --num-val 2 --seed 42` exited `0`, creating `best.pt` and `data/val.jsonl`.
- **`transcribe --tts --json`**: `--tts オハヨウ --preset robot --engine tsukinami --json` exited `0` and emitted a single strict JSON object containing all required keys (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, `source`, `tts_engine`, `preset`, `reference_text`, `tts_text`, `cer`).
- **`transcribe --wav --json`** and **`eval --json`**: both exited `0` with valid JSON matching their contracts.
- **Error-handling probes** (12 cases: missing/corrupt/directory checkpoint, missing/corrupt WAV, unknown preset, empty `--tts ""`, `--beam-width 0`, `--epochs 0`, `--port 99999`, both `--wav` & `--tts`, neither `--wav` nor `--tts`): all returned non-zero exit codes (`1` or `2`) with concise error/usage messages on `stderr` and **zero Python tracebacks**.
