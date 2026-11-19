# Adversarial Challenger 1 (`chal_1`, Iteration 2) Handoff

## Verdict: PASS

No blocking or non-blocking defects were discovered in `asr/server.py` (or its integration with `asr/inference.py` and `asr/web/index.html`). All endpoints, validation rules, error status codes, strict JSON sanitization, `<10 ms` cached `/api/redecode` latency, LRU cache eviction, and multi-threaded concurrency checks passed.

---

## Probe Summary & Results

All probe scripts were staged under `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and removed immediately after execution. No repository working-tree files were modified.

### 1. Core Endpoints (`GET /`, `GET /api/health`, `GET /api/info`)
- `GET /`: `200 OK`, `content-type: text/html; charset=utf-8`, `68419` chars (works in both model-loaded and no-model modes).
- `GET /api/health`: `200 OK`, `{"status": "ok", "model_loaded": true}` (loaded) and `{"status": "ok", "model_loaded": false}` (no-model).
- `GET /api/info`: `200 OK`, returns architecture (`cnn_bigru`), `vocab_size=86`, `tsukinami_presets` (8 presets), `preset_details`, and `history` in loaded mode; gracefully returns `model_loaded: false` with `tsukinami_presets` in no-model mode.

### 2. `POST /api/transcribe`
- **Valid multipart upload** (`files={"file": ...}` + form decode/corruption params): `200 OK`, returns `utterance_id`, `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`.
- **Valid JSON base64** (including `data:audio/wav;base64,...` data URI, `decode_cfg`, `corruption`, `include_visuals: false`): `200 OK`, omits visual keys when `include_visuals: false`.
- **Edge-case audio** (0.5 s all-zero silence, 0.5 s DC offset `+1.0`, 1-sample WAV, 10-sample WAV, 160-sample WAV): all returned `200 OK` with strictly valid JSON (no `NaN`/`Inf`).
- **Invalid/empty/corrupt payloads -> `400`/`422`**:
  - Multipart empty bytes (`400`), corrupt bytes (`400`), truncated RIFF header (`400`), 0-sample WAV (`400`), missing `file` field (`422`).
  - Multipart invalid params: `method="bogus"` (`422`), `beam_width=0` (`422`), `beam_width=999` (`422`), inverted `band_limit` (`422`), `speed=0.05` (`422`).
  - JSON empty body (`400`), malformed JSON (`400`), JSON array (`422`), missing `audio_b64` (`422`), empty `audio_b64` (`400`), invalid base64 (`400`), corrupt WAV inside base64 (`400`), raw JSON `NaN` temperature (`422`), raw JSON `Infinity` `snr_db` (`422`).
- **No-model mode**: returns `503 Service Unavailable`.

### 3. `POST /api/tts-roundtrip`
- **`synth_engine="fast"`** with preset `ossan` + pink noise + band-pass `[300, 3400]` + `speed=1.2` + beam decoding: `200 OK`, `audio_b64` decodes to valid 16 kHz mono PCM WAV, returns `cer`, `cer_details`, `ground_truth_moras`, `utterance_id`.
- **`synth_engine="tsukinami"`** with preset `robot` + overrides (`hz=180`, `fscale=1.0`, `yure=0.1`, `rate=1.0`) + greedy decoding: `200 OK`, valid `audio_b64`, `ground_truth_moras`, `cer`, `utterance_id`.
- **Speed scaling**: `speed=2.0` scaled `ground_truth_moras` end timestamp from `0.82s` to `0.41s` (exact `0.5x`).
- **Invalid params -> `400`/`422`**:
  - Empty text (`422`), whitespace text (`422`), >500 chars (`422`), unspeakable punctuation `"。。。！！！"` on both `fast` (`400`) and `tsukinami` (`400`), unknown preset (`422`), unknown `synth_engine` (`422`), `hz=-50` (`422`), `rate=0` (`422`), `yure=2.5` (`422`), extra unknown field (`422`), invalid `noise_type="brown"` (`422`), invalid `decode_cfg.method="viterbi"` (`422`), raw JSON `NaN` `hz` (`422`), raw JSON `Infinity` `rate` (`422`).
- **No-model mode**: returns `503 Service Unavailable`.

### 4. `POST /api/redecode`
- **Cached latency (`<10 ms`)**:
  - FastAPI `TestClient` (25 calls, alternating greedy & beam): `min=2.41 ms`, `median=3.37 ms`, `p95=4.41 ms`.
  - Live `uvicorn` TCP localhost (30 calls, beam width 4): `min=2.05 ms`, `median=2.20 ms`, `p95=2.83 ms`.
- **Unknown / evicted ID -> `404`**:
  - Unknown `utterance_id`: `404 Not Found`.
  - LRU eviction (`max_cache_size=2`, 3 utterances transcribed): oldest `utterance_id` -> `404`, two recent IDs -> `200`.
- **Invalid params -> `422`**: empty/whitespace `utterance_id` (`422`), `temperature=0` (`422`), `temperature=-1` (`422`), raw JSON `NaN` `blank_bias` (`422`), `beam_width=65` (`422`), extra unknown field (`422`).
- **No-model mode**: returns `503 Service Unavailable`.

### 5. Strict JSON Serialization & Thread Safety
- **Strict JSON (no `NaN`/`Inf`)**:
  - Every response across all probes was parsed with `json.loads(..., parse_constant=_reject)` — 0 violations.
  - Injecting `float("nan")`, `float("inf")`, and `float("-inf")` into `engine.checkpoint_meta["history"]` produced valid JSON with `null` values in `GET /api/info`.
- **Concurrent thread safety**:
  - `TestClient` (`ThreadPoolExecutor(max_workers=12)`, 80 concurrent `/api/redecode` requests alternating greedy/beam): 80/80 succeeded with deterministic outputs (`unique_even=1`, `unique_odd=1`).
  - Live `uvicorn` server (`ThreadPoolExecutor(max_workers=16)`, 100 concurrent mixed `/api/redecode` + `/api/info` requests over real localhost sockets): `100/100` passed with strict JSON validation and zero errors.

---

## Working Tree Verification

- `git status --short && git diff --stat` confirmed zero modifications to tracked files and zero stray files created outside `.agents/teamwork/sub_orch_m6/iter2/chal_1/handoff.md`.
- All `/tmp/teamwork_probe.*` temp directories were removed.
