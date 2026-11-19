# Explorer 3 (`exp3`) Handoff — M5 Downstream Compatibility, CLI Ergonomics & Test Plan

## 1. Downstream Compatibility with M6 (`asr/server.py`)

Inspected `PROJECT.md § Interface Contracts #7 & #8`, `asr/train.py`, `asr/config.py`, `asr/decoding.py`, `asr/metrics.py`, `asr/audio.py`, `asr/features.py`, and `asr/synth_data.py`.

### 1.1 Endpoint-to-`ASREngine` Mapping

| M6 Endpoint | `ASREngine` Call | Required Behavior & Contract |
|---|---|---|
| `GET /api/health` | Engine presence check | `{"status": "ok", "model_loaded": bool}` |
| `GET /api/info` | `engine.info()` | Must return a strictly JSON-serializable `dict` containing: `model_config` (dict from `ModelConfig.to_dict()`), `audio_config` (dict from `AudioConfig.to_dict()`), `vocab_size` (`int`), `vocab` (`list[str]`), `blank_id` (`int`), `tokenizer_mode` (`str`), `param_count` (`int`), `tsukinami_presets` (`list[str]` from `DEFAULT_TSUKINAMI_PRESETS`), `checkpoint_path` (`str \| None`), `epoch` (`int \| None`), `best_val_cer` (`float \| None`), `history` (`list[dict]`). |
| `POST /api/transcribe` | `engine.transcribe(wav, sr=sr, decode_cfg=cfg, include_visuals=True)` | Returns strictly JSON-serializable `dict` (no `np.ndarray`, `np.float32`, `Path`, `NaN`, or `Inf`). Raises `ValueError` on invalid input so FastAPI maps it cleanly to HTTP `400`/`422`. |
| `POST /api/tts-roundtrip` | `engine.transcribe(wav, sr=16000, decode_cfg=cfg, include_visuals=True)` | `result["alignment"]` entries `{"token", "start_sec", "end_sec", "confidence"}` plug directly into `asr.metrics.alignment_boundary_error(gt_moras, result["alignment"])`. `result["text"]` plugs directly into `asr.metrics.compute_cer([ref], [result["text"]], normalize_kana=True)`. |
| `POST /api/redecode` | `engine.redecode(utterance_id, decode_cfg)` | Re-decodes cached `log_probs` in `<10 ms` without re-running STFT or PyTorch. Raises `KeyError` when `utterance_id` is unknown or evicted so FastAPI maps it cleanly to HTTP `404`. |

### 1.2 JSON Serializability & Schema Details

All dicts returned by `engine.info()`, `engine.transcribe(...)`, and `engine.redecode(...)` MUST pass `json.dumps(obj, allow_nan=False)`:

- **`best_val_cer` sanitization**: In `asr/train.py`, `best_val_cer` is initialized to `float("inf")` before epoch 1. `engine.info()` must convert non-finite `best_val_cer` to `None` (or finite `float`) so `json.dumps(..., allow_nan=False)` never fails.
- **`hypotheses` normalization**:
  - `prefix_beam_search` returns `[{"text": str, "score": float, "acoustic_score": float, "lm_score": float}]`.
  - `greedy_decode` returns `{"text": str, "token_ids": list[int], "score": float}`.
  - `ASREngine` must normalize greedy output into the exact same list schema: `[{"text": str, "score": float, "acoustic_score": float, "lm_score": 0.0}]`.
- **Visual payload (`include_visuals=True`)**:
  - `waveform`: `list[float]` downsampled to a bounded length (e.g. `<= 1200` points via uniform striding or min/max envelope) for fast Canvas 2D rendering; `[]` for empty audio.
  - `log_mel`: `list[list[float]]` of shape `(T_vis, n_mels)` preserving `n_mels` exactly (e.g., `64`), with optional time downsampling only if `T` is very large (e.g. `> 500` frames); `[]` for empty audio.
  - `ctc_posteriors`: `{"times_sec": list[float], "top_tokens": list[str], "probs": list[list[float]]}` where `len(times_sec) == T'`, `len(probs) == T'`, `len(probs[t]) == len(top_tokens)`, all probabilities are finite Python `float`s in `[0.0, 1.0]`. Select `<blank>` plus top-K non-blank tokens by peak posterior probability (e.g., `K <= 16`) so the Canvas heatmap stays legible and JSON stays compact.
  - `vad_segments`: `list[list[float]]` (`[[float(s), float(e)], ...]`) converted from `detect_vad(wav, sr=self.audio_cfg.sample_rate)`.

### 1.3 `utterance_id` LRU Cache Semantics

- Backed by `collections.OrderedDict[str, _CachedUtterance]` with `max_cache_size: int = 32` (validate `max_cache_size >= 1`).
- Generate unique `utterance_id` via `uuid.uuid4().hex[:12]` (or `uuid.uuid4().hex`).
- Cache entry stores: `log_probs: np.ndarray` (2D `float32`/`float64` shape `(T', V)`), `duration_sec: float`, `frame_stride_ms: float`.
- On `transcribe`: insert `self._cache[utterance_id] = entry`; if `len(self._cache) > self.max_cache_size`, evict oldest with `self._cache.popitem(last=False)`.
- On `redecode`: if `utterance_id not in self._cache`, raise `KeyError(f"Unknown utterance_id: {utterance_id!r}")`. Otherwise call `self._cache.move_to_end(utterance_id)` (true LRU promotion) before decoding.
- Note: Even for empty/short audio (`len(wav) == 0`), cache an entry (e.g. `log_probs` with shape `(0, vocab_size)`) under `utterance_id` so a subsequent `redecode(utterance_id, ...)` succeeds cleanly instead of raising `KeyError`.

### 1.4 Edge Cases & Error Types

- **Empty / very short audio**:
  - `len(wav) == 0`: `duration_sec = 0.0`, `rtf = 0.0`, `text = ""`, `hypotheses = [{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]`, `alignment = []`, visuals empty (`waveform=[]`, `log_mel=[]`, `ctc_posteriors={"times_sec": [], "top_tokens": [], "probs": []}`, `vad_segments=[]`).
  - `0 < len(wav) < win_length`: `asr.features.extract_log_mel` zero-pads to `win_length` (returning `(1, n_mels)`), and both `cnn_bigru` and `conformer_lite` handle `T=1` cleanly (`T'=1`).
- **`viterbi_align` safety guard**:
  - For `beam` decoding, obtain `token_ids = self.tokenizer.encode(top_text)`.
  - If `len(token_ids) == 0` or `log_probs.shape[0] == 0`: `alignment = []`.
  - If `viterbi_align` raises `ValueError` (e.g., degenerate very short audio where `T' < min_frames` for predicted tokens), catch `ValueError` and fall back to `alignment = []` rather than crashing inference/redecode.
- **Invalid inputs** (raise explicit exceptions for M6 & CLI):
  - `from_checkpoint(path)`: propagates `FileNotFoundError` (missing file) and `ValueError` (corrupt/empty/directory/missing-keys checkpoint from `asr.train.load_checkpoint`).
  - `transcribe(wav, sr=...)`: raises `ValueError` if `sr <= 0` or `isinstance(sr, bool)`, or if `wav.ndim not in (1, 2)` or `wav` has 0 channels; raises `TypeError` if `decode_cfg` is not `None | DecodeConfig`.
  - `redecode(utterance_id, decode_cfg)`: raises `KeyError` on unknown/evicted ID; `TypeError` if `decode_cfg` is not `DecodeConfig`.

---

## 2. CLI Ergonomics, JSON Output Formats & Error Handling (`asr/__main__.py`)

### 2.1 Architecture & Entrypoint
- Expose `build_parser() -> argparse.ArgumentParser` and `main(argv: Sequence[str] | None = None) -> int`.
- `if __name__ == "__main__": raise SystemExit(main())`.
- Returning an `int` exit code from `main(argv)` allows fast in-process CLI tests without spawning a new PyTorch process for every single flag/error combination, while still keeping `python -m asr ...` 100% standard.

### 2.2 Subcommand Specification

1. **`demo`**:
   `python -m asr demo [--out-dir DIR] [--epochs N] [--num-train N] [--num-val N] [--arch cnn_bigru|conformer_lite] [--seed N]`
   - CPU-friendly defaults: `--out-dir demo_out`, `--epochs 6`, `--num-train 60`, `--num-val 12`, `--arch cnn_bigru`, `--seed 42`.
   - Workflow:
     1. Generate synthetic dataset under `<out-dir>/data` via `generate_dataset(..., engine="fast")`.
     2. Train model via `train_asr(...)` saving `best.pt` and `latest.pt` under `<out-dir>/checkpoints`.
     3. Load `ASREngine.from_checkpoint(<out-dir>/checkpoints/best.pt)` and evaluate on `val.jsonl` (CER, MER, top confusion pairs, mean RTF).
     4. Synthesize a sample Japanese phrase (e.g., `"ワタシ、ニホンゴ"`) and run live transcription, printing reference vs prediction and path to `best.pt`.
2. **`generate`**:
   `python -m asr generate --out-dir DIR [--num-train N] [--num-val N] [--engine fast|tsukinami|mixed] [--seed N]`
   - Calls `asr.synth_data.generate_dataset(...)` and prints summary (train/val manifest paths & counts).
3. **`train`**:
   `python -m asr train --train-manifest PATH --val-manifest PATH [--out-dir DIR] [--arch cnn_bigru|conformer_lite] [--epochs N] [--batch-size N] [--lr FLOAT] [--seed N] [--resume PATH] [--hidden-size N] [--num-layers N] [--no-spec-augment]`
   - Default `--out-dir checkpoints`, `--arch cnn_bigru`, `--epochs 20`, `--batch-size 16`, `--lr 3e-3`, `--seed 42`.
   - Optional `--hidden-size`, `--num-layers`, `--no-spec-augment` default to `ModelConfig`/`TrainConfig` defaults while enabling fast CPU smoke runs and tests.
4. **`eval`**:
   `python -m asr eval --checkpoint PATH --manifest PATH [--method greedy|beam] [--beam-width K] [--json]`
   - Loads `ASREngine.from_checkpoint`, reads `load_manifest(manifest_path)`, resolves relative `audio_path` against `manifest_path.parent` (matching `asr/dataset.py`), loads each WAV via `load_wav(path, target_sr=engine.audio_cfg.sample_rate)`, transcribes, and computes `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`, and mean RTF.
   - **Text output**: human-readable table/summary with CER, MER, WER, S/D/I counts, mean RTF, top confusion pairs.
   - **`--json` output**: prints **only** a single JSON object to `stdout` (`ensure_ascii=False`, `allow_nan=False`), with no banner/log lines polluting `stdout`:
     ```json
     {
       "checkpoint": "path/to/best.pt",
       "manifest": "path/to/val.jsonl",
       "num_utterances": 4,
       "decode_config": {"method": "beam", "beam_width": 8, ...},
       "cer": 0.25,
       "mer": 0.25,
       "wer": 0.5,
       "cer_details": {"cer": 0.25, "substitutions": 1, "deletions": 0, "insertions": 0, "ref_len": 4},
       "mer_details": {"mer": 0.25, "substitutions": 1, "deletions": 0, "insertions": 0, "ref_len": 4},
       "wer_details": {"wer": 0.5, "substitutions": 1, "deletions": 0, "insertions": 0, "ref_len": 2},
       "mean_rtf": 0.04,
       "total_audio_sec": 3.5,
       "confusion_pairs": [["ア", "オ", 1]],
       "samples": [{"audio_path": "...", "ref": "...", "hyp": "...", "rtf": 0.04}]
     }
     ```
5. **`transcribe`**:
   `python -m asr transcribe --checkpoint PATH (--wav PATH | --tts TEXT [--preset NAME] [--engine fast|tsukinami]) [--method greedy|beam] [--beam-width K] [--json]`
   - `--wav` and `--tts` are a **required mutually exclusive group** (`parser.add_mutually_exclusive_group(required=True)`).
   - `--preset` defaults to `"default"`, `--engine` defaults to `"tsukinami"` when `--preset` is used or `"fast"` by default (explicitly supporting both `--engine fast` and `--engine tsukinami`; validate `--preset` against `yomu.PRESETS` when `--engine tsukinami`).
   - **`--json` output**: prints **only** a single JSON object to `stdout`:
     ```json
     {
       "text": "ワタシ",
       "hypotheses": [{"text": "ワタシ", "score": -1.2, "acoustic_score": -1.2, "lm_score": 0.0}],
       "alignment": [{"token": "ワ", "start_sec": 0.04, "end_sec": 0.16, "confidence": 0.91}],
       "rtf": 0.03,
       "duration_sec": 1.15,
       "utterance_id": "a1b2c3d4e5f6",
       "source": "wav"
     }
     ```
     When `--tts` is used, also include `"reference_text": str` and `"cer": float` (computed with `normalize_kana=True`).
6. **`serve`**:
   `python -m asr serve --checkpoint PATH [--host 127.0.0.1] [--port 8000]`
   - **Lazy import**: import `asr.server` and `uvicorn` inside `_cmd_serve()`, NOT at module top level. This guarantees `python -m asr --help` and `python -m asr serve --help` succeed cleanly before M6 creates `asr/server.py`.
   - Validate `--port` in `1..65535` and checkpoint file existence before calling `uvicorn.run`. If `asr.server` is missing (`ModuleNotFoundError`/`ImportError`), emit a clear message to `stderr` and return exit code `1`.

### 2.3 Error Handling & Exit Codes
- `argparse` errors (unknown subcommand, missing required args, both `--wav` and `--tts` supplied, neither supplied, invalid `--arch`/`--method`/`--engine`) → exit code `2` with usage message on `stderr`.
- Application/validation errors (`FileNotFoundError`, `ValueError`, `KeyError`, `OSError`, `ImportError`) → caught in `main()`, print `Error: <concise message>` to `sys.stderr`, return exit code `1` (no uncaught Python tracebacks).
- Reject empty manifests in `eval` cleanly (either exit code `1` with clear message or valid 0-utterance summary — recommend explicit `ValueError("Manifest contains no utterances")` → exit code `1` or 0-utterance JSON; wait: returning `num_utterances=0` with `cer=0.0` vs error — let's ensure corrupt JSONL raises `ValueError` → exit code `1`).
- Corrupt WAV (`load_wav` raises `ValueError`), missing WAV (`FileNotFoundError`), corrupt/empty checkpoint (`load_checkpoint` raises `ValueError`), missing checkpoint (`FileNotFoundError`), invalid numeric args (`--epochs 0`, `--beam-width 0`, `--num-train 0`) → all return non-zero exit code with helpful `stderr` message.

---

## 3. Comprehensive, Fast Test Plan (`tests/test_asr_cli.py`)

### 3.1 Runtime Budget Strategy (2-vCPU CPU-Only Environment)
- **Shared module-scoped fixture (`tiny_bundle`)**:
  - Uses `tmp_path_factory.mktemp("asr_cli_m5")` once per module.
  - Synthesizes 6 tiny utterances (`["アオ", "イヌ", "ウミ", "エキ", "オト", "カサ"]`) with `synthesize_fast_kotoba` (~0.1s).
  - Trains one tiny `cnn_bigru` (`hidden_size=32, num_layers=1, epochs=2, batch_size=6, use_spec_augment=False`) saving `best.pt` (~1–1.5s).
  - All `ASREngine` unit tests and `eval`/`transcribe` CLI tests reuse this checkpoint.
- **In-process `main(argv)` + targeted subprocess smoke tests**:
  - Run detailed flag/JSON/error matrix via in-process `main(argv)` + `capsys` (sub-second, zero interpreter startup overhead).
  - Run 4–5 real `subprocess.run([sys.executable, "-m", "asr", ...], capture_output=True, text=True)` tests to verify `__main__.py` wiring, exit codes, and clean stdout/stderr separation.
  - Expected total runtime for `tests/test_asr_cli.py`: **~10–15 seconds** on 2 vCPUs.

### 3.2 `ASREngine` Unit Test Cases
1. **`test_engine_from_checkpoint_and_info`**:
   - Loads `tiny_bundle.checkpoint_path` via `ASREngine.from_checkpoint`.
   - Verifies `info()` keys (`model_config`, `audio_config`, `vocab_size`, `vocab`, `blank_id`, `param_count`, `tsukinami_presets`, `epoch`, `best_val_cer`, `history`).
   - Verifies `json.dumps(engine.info(), allow_nan=False)` succeeds.
   - Verifies `from_checkpoint` raises `FileNotFoundError` on missing file and `ValueError` on corrupt/empty file.
2. **`test_engine_transcribe_greedy_and_beam`**:
   - Transcribes synthetic Japanese audio with `DecodeConfig(method="greedy")` and `DecodeConfig(method="beam", beam_width=4)`.
   - Checks all required keys (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`), types, finite values, non-negative `rtf`/`duration_sec`, alignment monotonicity (`start_sec <= end_sec`), and `json.dumps(..., allow_nan=False)`.
   - Also tests beam search with a fitted `CharNgramLM` (`lm_weight=0.3`).
3. **`test_engine_transcribe_include_visuals`**:
   - Calls `transcribe(..., include_visuals=True)`.
   - Checks `waveform` (non-empty `list[float]`), `log_mel` (2D `list[list[float]]` with width `audio_cfg.n_mels`), `ctc_posteriors` (`times_sec`, `top_tokens`, `probs` shapes & probability bounds `[0.0, 1.0]`), `vad_segments` (list of `[start, end]` pairs).
   - Verifies `json.dumps(res, allow_nan=False)` succeeds.
   - Verifies default `include_visuals=False` omits the 4 visual keys.
4. **`test_engine_redecode_speed_and_unknown_id`**:
   - Calls `transcribe(...)` to obtain `utterance_id`.
   - Calls `redecode(utterance_id, DecodeConfig(method="greedy", blank_bias=-1.0))` and `redecode(utterance_id, DecodeConfig(method="beam", beam_width=4, temperature=0.8))`.
   - Asserts `redecode` returns `text`, `hypotheses`, `alignment`, `utterance_id`, `duration_sec`, `decode_ms`.
   - Measures wall-clock latency over greedy redecode (after warmup or single short utterance) and asserts `< 10 ms` (or `< 20 ms` wall clock with `decode_ms < 10.0` on tiny clip; note: with `hidden_size=32`, 1s audio has `T' ≈ 25` frames, so pure-NumPy greedy/beam redecode takes ~0.5–3 ms!).
   - Asserts `redecode("nonexistent-id", DecodeConfig())` raises `KeyError`.
5. **`test_engine_lru_cache_eviction`**:
   - Instantiate `ASREngine(..., max_cache_size=2)`.
   - Transcribe utt1 → utt2; touch utt1 via `redecode(utt1, ...)` (promotes utt1 to MRU); transcribe utt3.
   - Assert utt2 is evicted (`KeyError` on `redecode(utt2, ...)`), while utt1 and utt3 remain cached and succeed!
6. **`test_engine_resampling_and_stereo`**:
   - Pass 44.1 kHz audio (`sr=44100`) and stereo 2D array `(N, 2)` to `transcribe`.
   - Verify `duration_sec` matches `len(wav) / 44100.0` closely and no crash occurs.
7. **`test_engine_empty_and_very_short_audio`**:
   - Pass `np.zeros(0, dtype=np.float32)` (empty), `np.zeros(10, dtype=np.float32)` (10 samples < `win_length`), and `np.zeros(1600, dtype=np.float32)` (silence) with both `include_visuals=False` and `include_visuals=True`.
   - Assert clean return dicts, `json.dumps(..., allow_nan=False)`, and cached `utterance_id` works in `redecode`.
   - Assert invalid `sr=0` or 3D array raises `ValueError`.

### 3.3 CLI Integration Test Cases
1. **Help & lazy `serve` import (subprocess)**:
   - `python -m asr --help` → exit 0, mentions `demo`, `generate`, `train`, `eval`, `transcribe`, `serve`.
   - `python -m asr serve --help` → exit 0, mentions `--checkpoint`, `--host`, `--port` (verifies lazy import of `asr.server`).
2. **`generate` (in-process + subprocess)**:
   - `generate --out-dir <tmp> --num-train 4 --num-val 2 --engine fast --seed 7` → exit 0, creates `train.jsonl` (4 lines), `val.jsonl` (2 lines), and WAV files.
3. **`train` (in-process)**:
   - `train --train-manifest ... --val-manifest ... --out-dir <tmp> --arch cnn_bigru --epochs 1 --batch-size 4 --hidden-size 32 --num-layers 1 --no-spec-augment` → exit 0, creates `best.pt` and `latest.pt`.
4. **`eval` text + `--json` (in-process)**:
   - `eval --checkpoint <ckpt> --manifest <val.jsonl> --method greedy` → exit 0, prints CER/MER.
   - `eval --checkpoint <ckpt> --manifest <val.jsonl> --method beam --beam-width 4 --json` → exit 0, `json.loads(stdout)` succeeds with `cer`, `mer`, `wer`, `num_utterances`, `mean_rtf`, `confusion_pairs`.
5. **`transcribe --wav` text + `--json` (in-process + subprocess)**:
   - `transcribe --checkpoint <ckpt> --wav <wav> --method greedy` → exit 0.
   - `transcribe --checkpoint <ckpt> --wav <wav> --method beam --beam-width 4 --json` (subprocess) → exit 0, valid JSON with `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`.
6. **`transcribe --tts` fast + tsukinami (in-process)**:
   - `transcribe --checkpoint <ckpt> --tts アイウ --engine fast --json` → exit 0, valid JSON with `reference_text`.
   - `transcribe --checkpoint <ckpt> --tts アイ --engine tsukinami --preset default --json` → exit 0, valid JSON (short 2-mora phrase keeps `carve.make` fast ~0.3s).
7. **`demo` end-to-end (subprocess)**:
   - `python -m asr demo --out-dir <tmp> --epochs 1 --num-train 4 --num-val 2 --arch cnn_bigru --seed 42` → exit 0, creates `<tmp>/data/train.jsonl`, `<tmp>/checkpoints/best.pt`, prints evaluation and live transcription output.
8. **Error cases & non-zero exit codes (in-process + subprocess)**:
   - Missing checkpoint file → exit != 0, message on `stderr`.
   - Corrupt checkpoint file (`b"not a checkpoint"`) → exit != 0, message on `stderr`.
   - Missing WAV file → exit != 0, message on `stderr`.
   - Corrupt WAV file (`b"RIFF....WAVEbad"`) → exit != 0, message on `stderr`.
   - Both `--wav` and `--tts` supplied (mutually exclusive) → exit code 2, message on `stderr`.
   - Neither `--wav` nor `--tts` supplied → exit code 2, message on `stderr`.
   - Invalid subcommand / invalid `--arch` / invalid `--epochs 0` → exit != 0, message on `stderr`.
