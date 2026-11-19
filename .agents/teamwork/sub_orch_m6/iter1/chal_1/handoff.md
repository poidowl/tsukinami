# Milestone M6 Adversarial Challenger 1 (`chal_1`) Handoff

**Verdict: `PASS`**

All adversarial API & backend robustness probes against `asr/server.py` succeeded with **zero unhandled HTTP 500 errors**, **zero non-standard NaN/Infinity JSON serialization errors**, clean `400`/`422`/`404`/`503` responses on malformed/invalid/no-model requests, and sub-10 ms cached `/api/redecode` latency under sequential and multi-threaded stress.

---

## Probe Execution Summary

All ad-hoc probe scripts were staged in `/tmp/teamwork_probe.slQBdy` (created via `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`) and removed before reporting (`rm -rf /tmp/teamwork_probe.slQBdy`). Zero repository working-tree files were created, modified, or deleted.

### 1. Fuzz `POST /api/transcribe` (56 probes — PASS)
Executed via `.venv/bin/python /tmp/teamwork_probe.slQBdy/probe_server.py` and `.venv/bin/python /tmp/teamwork_probe.slQBdy/probe_extra.py` against FastAPI `TestClient(..., raise_server_exceptions=False)` with strict JSON validation (`json.loads(..., parse_constant=reject)`):

- **Multipart boolean & empty numeric fields**:
  - `include_visuals="false"` + empty `""` for all optional numeric/string fields → `HTTP 200` (visuals omitted: `keys=['alignment', 'duration_sec', 'hypotheses', 'rtf', 'text', 'utterance_id']`).
  - `include_visuals="0"` → `HTTP 200` (`has_waveform=False`).
  - `include_visuals=""` → `HTTP 200` (`has_waveform=True`, default).
  - `include_visuals="maybe"` → `HTTP 422`.
- **Query params + multipart upload**:
  - `?method=greedy&include_visuals=false&snr_db=15&noise_type=pink&speed=1.1` + multipart WAV → `HTTP 200` (visuals omitted).
  - Form fields override query params (`?include_visuals=false&method=invalid_method` overridden by `data={"method": "greedy", "include_visuals": "true"}`) → `HTTP 200` (visuals included).
- **Malformed bodies & Content-Types**:
  - Malformed JSON (`{bad json`) → `HTTP 400`.
  - Unknown Content-Type (`text/plain`, `application/octet-stream` empty body) → `HTTP 400`.
  - JSON array `[1, 2, 3]` → `HTTP 422`.
  - Malformed multipart (missing boundary, or `file` as plain text) → `HTTP 400`.
  - Malformed JSON inside multipart `decode_cfg`/`corruption` fields (`"{bad"`, `"[1,2]"`) → `HTTP 422`.
- **Audio & base64 edge cases**:
  - Empty file (0 bytes) → `HTTP 400`.
  - Truncated WAV header (`RIFF$...WAVEfmt `) → `HTTP 400`.
  - Garbage bytes (`0xdeadbeef * 100`) → `HTTP 400`.
  - 0-sample WAV (both multipart and JSON base64) → `HTTP 400`.
  - Ultra-short WAVs (1, 10, 100, 399, 400 samples) → `HTTP 200` (no subsampling crash).
  - Stereo 44.1 kHz WAV and mono 8 kHz WAV → `HTTP 200` (clean mixdown + resampling).
  - Invalid base64 (`"!!!not_base64!!!"`), empty `audio_b64`, empty data-URI (`"data:audio/wav;base64,"`), non-string `audio_b64` → `HTTP 400`; missing `audio_b64` → `HTTP 422`.
  - Valid data-URI prefixed base64 (`data:audio/wav;base64,...`) → `HTTP 200`.
  - MIME base64 with embedded `\n` → `HTTP 400` (`validate=True` rejects newlines cleanly, non-500).
- **Extreme corruption params**:
  - `snr_db=-50`, `snr_db=-1000`, `gain_db=1000`, `band_limit=[300, 50000]` → `HTTP 200` with strict JSON (no NaN/Inf).
  - `speed=0`, `speed=-1`, `band_limit=[5000, 100]`, `noise_type="brown"`, partial `band_limit_low="300"` without `band_limit_high`, `band_limit="bad"`, `band_limit="[300]"`, `snr_db="nan"`, `speed="inf"` → `HTTP 422`.
  - `band_limit="300,3400"` and `band_limit="[300, 3400]"` in multipart → `HTTP 200`.
- **Extreme decode params**:
  - `beam_width=0`, `beam_width=-5`, `beam_width=9999`, `temperature=0`, `temperature=-1`, `method="viterbi_magic"`, raw JSON `NaN` in `decode_cfg.temperature` → `HTTP 422`.
  - Extreme finite values (`temperature=1e-300` beam/greedy, `blank_bias=1e300`) → `HTTP 200` with strict JSON.

### 2. Fuzz `POST /api/tts-roundtrip` (35 probes — PASS)
- **Non-kana / empty / whitespace text**:
  - `""`, `"   "`, `"\u3000"` (full-width space) → `HTTP 422` (both `fast` and `tsukinami`).
  - `"!!!"` (punctuation yielding 0 moras) → `HTTP 400` (both `fast` and `tsukinami`).
  - `"12345"`, `"hello"`, `"東京"` → `HTTP 200` (clean non-500; underlying unmodified `kotoba.split_moras` emits fallback mora entries for non-punctuation characters, so `len(moras) > 0` and valid WAV + strict JSON are returned).
  - `text` length 501 (> 500 cap) → `HTTP 422`.
- **Hiragana vs Katakana CER normalization**:
  - `compute_cer(["こんにちは"], ["コンニチハ"], normalize_kana=True)` returns `cer=0.0, ref_len=5`.
  - Deterministic `tsukinami` engine with `"こんにちは"` vs `"コンニチハ"` produced identical `text`, identical `cer=4.2`, and identical `cer_details` (`ref_len=5`). (Note: `fast` engine uses unseeded aspiration noise so two separate calls differ slightly in waveform, while CER normalization itself is verified identical.)
- **Invalid voice & engine params**:
  - `hz=0`, `hz=-100`, `hz=10000`, `fscale=0`, `fscale=-0.5`, `fscale=10.0`, `yure=-1`, `yure=2.0`, `rate=0`, `rate=-1`, `rate=10.0`, `preset="super_alien"`, `synth_engine="wavenet"`, extra unknown JSON key → `HTTP 422`.
  - Valid boundary `yure=0.0` → `HTTP 200`.
  - Extreme short synthesis (`text="ア"`, `rate=5.0`, `corruption={"speed": 4.0}`) → `HTTP 200`.
- **Combined corruption & WAV/mora integrity**:
  - `text="ワタシ、ニホンゴ"`, `corruption={"snr_db": 10, "band_limit": [300, 3400], "speed": 1.25}` on both `fast` (`moras=8, wav_frames=21120`) and `tsukinami` (`moras=8, wav_frames=32512`) → `HTTP 200`; `audio_b64` decodes to valid 16-bit mono 16 kHz PCM WAV; `ground_truth_moras` timestamps (`a`, `e`) verified scaled by `1 / 1.25` (`0.615 -> 0.492`).

### 3. Stress `POST /api/redecode` (10 functional probes + 130 stress calls — PASS)
- Unknown `utterance_id` → `HTTP 404`.
- Whitespace `utterance_id` → `HTTP 422`.
- Invalid `decode_cfg` (`beam_width=0`, `beam_width=9999`, `temperature=0`, `temperature=-1`, `method="bogus"`, raw `NaN` temperature, extra unknown field) → `HTTP 422`.
- Top-level parameter overrides (`{"utterance_id": ..., "method": "greedy", "beam_width": 4}`) → `HTTP 200`.
- **Sequential latency & consistency (50 calls, `beam_width=8`, `lm_weight=0.2`)**:
  ```text
  Sequential redecode (50x): median=6.88ms, p95=7.32ms, max=7.92ms, unique_texts=1
  ```
  All 50 calls succeeded (`< 10 ms` including FastAPI/TestClient overhead) with 100% deterministic output.
- **Concurrent stress (80 calls across 8 threads, mixed greedy & beam)**:
  ```text
  Concurrent redecode (80x across 8 threads): errors=0, greedy_unique=1, beam_unique=1
  ```
  Zero lock/cache races, zero errors, 100% consistent outputs per decode config.

### 4. No-Model Mode (`create_app()`) & Checkpoint Loading (8 probes — PASS)
- `create_app()` (no model):
  - `GET /api/health` → `HTTP 200`, `{"status": "ok", "model_loaded": false}`
  - `GET /api/info` → `HTTP 200`, `model_loaded: false`, `tsukinami_presets` populated
  - `POST /api/transcribe` → `HTTP 503`
  - `POST /api/tts-roundtrip` → `HTTP 503`
  - `POST /api/redecode` → `HTTP 503`
- `create_app(checkpoint_path=...)` (loaded from temp `.pt` checkpoint):
  - `GET /` → `HTTP 200`, `text/html; charset=utf-8` (`len=68087`)
  - `GET /api/health` → `HTTP 200`, `{"status": "ok", "model_loaded": true}`
  - `GET /api/info` → `HTTP 200`, `model_loaded: true`, `arch: "cnn_bigru"`, 6 `tsukinami_presets`

---

## Minor Non-Blocking Observations (Informational)
1. `base64.b64decode(b64_str, validate=True)` in `POST /api/transcribe` rejects MIME-wrapped base64 containing newlines (`\n`) with `HTTP 400`. This is safe and clean (not a 500), though stripping whitespace before decoding could be a nice ergonomic touch if ever needed.
2. Extreme `snr_db=-1000` / `gain_db=1000` triggers numpy `RuntimeWarning` in `asr/audio.py` (M1 code) during float32 cast, which `ASREngine` and `_sanitize_json` safely recover from with `HTTP 200` and valid strict JSON.

## Defects Found
None. **Verdict: `PASS`**.
