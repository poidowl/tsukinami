# Milestone M5 Handoff — High-Level Inference Engine, CLI & Demo Workflow

## Status: **PASS** (Iteration 2 Gate Passed — Unanimous Approval & Auditor CLEAN)

## Deliverables (Exclusive File Ownership Strictly Respected)
1. **`asr/inference.py` (`ASREngine`)**:
   - `ASREngine(model, audio_cfg, model_cfg, tokenizer, *, lm=None, checkpoint_meta=None, max_cache_size=32, device="cpu")`
   - `ASREngine.from_checkpoint(path, lm=None) -> ASREngine`: loads checkpoints via `asr.train.load_checkpoint`, reconstructs `ModelConfig`, `AudioConfig`, `Tokenizer`, optional `CharNgramLM`, and PyTorch model in `eval()` mode; preserves `FileNotFoundError`/`IsADirectoryError` and normalizes corrupt-checkpoint deserialization exceptions (`OverflowError`, `EOFError`, `IndexError`, `UnicodeDecodeError`, `pickle.PickleError`, `zipfile.BadZipFile`, `struct.error`, `RuntimeError`) into `ValueError`.
   - `engine.transcribe(wav, sr=16000, decode_cfg=None, *, include_visuals=False) -> dict`:
     - Handles 1D, samples-first `(N, C)`, and channels-first `(C, N)` audio; normalizes signed/unsigned integer PCM (`int16`, `int32`, `uint8`) to `[-1.0, 1.0]`; sanitizes `NaN`/`±Inf`; resamples when `sr != audio_cfg.sample_rate`; handles empty (`len == 0`) and very short audio cleanly.
     - Runs `extract_log_mel` + acoustic model under `torch.no_grad()` + `eval()`, caches `(log_probs, duration_sec, frame_stride_ms)` in a bounded `OrderedDict` LRU cache (`max_cache_size`), and runs Greedy or Prefix Beam Search + `viterbi_align`.
     - Returns strictly JSON-serializable (`allow_nan=False`) dict with `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, plus optional bounded `waveform`, `log_mel`, `ctc_posteriors` (`{times_sec, top_tokens, probs}`), and `vad_segments` when `include_visuals=True`.
   - `engine.redecode(utterance_id, decode_cfg) -> dict`: promotes LRU entry, raises `KeyError` on unknown/evicted IDs, re-runs CTC decoding + Viterbi alignment without touching PyTorch in `<10 ms` (verified median `3.12 ms`, max `7.15 ms`).
   - `engine.info() -> dict`: strictly JSON-serializable metadata (sanitizing non-finite floats like `inf` to `None`) including `arch`, `num_parameters`, `subsampling_factor`, `frame_stride_ms`, `model_config`, `audio_config`, `tokenizer` & vocab fields, `tsukinami_presets`, `has_lm`, cache stats, checkpoint metadata, and training history.
2. **`asr/__main__.py` (CLI: `.venv/bin/python -m asr <subcommand>`)**:
   - Subcommands matching `PROJECT.md § Interface Contracts #7`: `demo`, `generate`, `train`, `eval`, `transcribe` (`--wav` | `--tts`), and `serve` (lazily importing `asr.server.create_app` and `uvicorn` so `--help` and `serve --help` work cleanly before M6).
   - `--json` on `eval` and `transcribe` emits a single pure JSON object to stdout.
   - Clean non-zero exit codes (`1` for runtime/IO/validation/corrupt-file errors with `Error: ...` on stderr and zero uncaught tracebacks; `2` for argparse errors).
3. **`tests/test_asr_cli.py`**:
   - 16 thorough unit and CLI integration tests (including subprocess smoke & error tests and Iteration 2 regression tests for `(2, N)` stereo, `int16`/`uint8` PCM normalization, and corrupt pickle-FRAME checkpoints).

## Verification Summary (Iteration 2)
- **Forensic Auditor (`aud2`)**: **CLEAN** — 16/16 `tests/test_asr_cli.py` passed; exclusive file ownership confirmed (M1–M4 files, existing TTS files, and `tests_e2e/` untouched); 100% genuine implementation and tests.
- **Primary Reviewer (`rev3`)**: **APPROVE** — Full M1–M5 unit test suite `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py tests/test_asr_decoding.py tests/test_asr_models.py tests/test_asr_cli.py -v` passed **135/135** in 76.35s.
- **Secondary Reviewer (`rev4`)**: **APPROVE** — `.venv/bin/pytest tests/test_asr_cli.py -v` passed **16/16** in 20.58s; M6 downstream contracts verified.
- **Challenger 3 (`chal3`)**: **CONFIRMED** — 22/22 adversarial `ASREngine` probes passed (including `<10 ms` `redecode` without `model.forward`, LRU eviction/promotion, integer PCM/VAD parity, stereo `(2, N)`/`(N, 2)`, corrupt checkpoints, strict JSON).
- **Challenger 4 (`chal4`)**: **CONFIRMED** — 51/51 adversarial CLI subprocess probes passed (including 33/33 corrupt/invalid checkpoint tests across `eval`, `transcribe`, `train --resume` with zero tracebacks).

## Key State Artifacts
- Gate record: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m5/GATE_STATUS.md`
- Auditor report: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m5/aud2/handoff.md`
- Primary review: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m5/rev3/handoff.md`
