# Explorer 3 Handoff: Test Strategy & Edge Cases (`tests/test_asr_web.py`)

## 1. Existing Test Conventions & Environment Findings

Verified directly from the repository and `.venv`:

- **Pytest config** (`pyproject.toml`):
  - `pythonpath = ["."]`, `testpaths = ["tests"]`, `addopts = "-q"`.
  - Canonical test runner: `.venv/bin/pytest tests/test_asr_web.py -v` and `.venv/bin/pytest tests/ -v`.
- **Installed packages in `.venv`**:
  - `fastapi==0.165.0`, `httpx==0.28.1`, `python-multipart`, `uvicorn`, `torch` (CPU), `numpy`, `pytest`.
  - `/usr/local/bin/node` is available on PATH, so `<script>` JS syntax in `asr/web/index.html` can be verified directly with `node --check` (with graceful fallback to pure-Python structural checks if `node` were ever absent).
- **Existing M5 fixture pattern (`tests/test_asr_cli.py`)**:
  - Uses `@pytest.fixture(scope="module")` with `tmp_path_factory` to build a tiny checkpoint once per module.
  - **Even faster deterministic fixture for `tests/test_asr_web.py`**: Instead of running `train_asr` (~2–3 s), construct a tiny deterministic `cnn_bigru` (`hidden_size=32, num_layers=1, dropout=0.0`) checkpoint directly via `torch.save(...)` in ~30 ms with realistic `history` entries matching `asr/train.py`'s exact schema:
    ```python
    {
        "model_state_dict": model.state_dict(),
        "model_config": model_cfg.to_dict(),
        "audio_config": audio_cfg.to_dict(),
        "audio_cfg": audio_cfg.to_dict(),
        "tokenizer": tokenizer.to_dict(),
        "epoch": 3,
        "best_val_cer": 0.42,
        "train_config": TrainConfig(epochs=3, batch_size=4).to_dict(),
        "history": [
            {"epoch": 1, "train_loss": 3.5, "val_loss": 3.1, "val_cer": 0.85, "lr": 3e-3},
            {"epoch": 2, "train_loss": 2.4, "val_loss": 2.2, "val_cer": 0.60, "lr": 2e-3},
            {"epoch": 3, "train_loss": 1.8, "val_loss": 1.7, "val_cer": 0.42, "lr": 1e-3},
        ],
    }
    ```
  - This tests `create_app(checkpoint_path=ckpt_path)` through real `ASREngine.from_checkpoint`, AND we can also create:
    - `client_with_lm`: `create_app(engine=ASREngine.from_checkpoint(ckpt_path, lm=CharNgramLM(order=2).fit(["オハヨウ", "コンニチハ", "サクラ"])))` to test `lm_weight` & `insertion_bonus`.
    - `client_no_model`: `create_app()` (no checkpoint, no engine) to test no-model mode & `503` responses.
- **Exact module contracts verified**:
  - `yomu.PRESETS` has 8 keys: `default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`. (Core 6 in `DEFAULT_TSUKINAMI_PRESETS` are a strict subset of `yomu.PRESETS`.)
  - `ASREngine.transcribe(...)` returns keys: `text`, `hypotheses` (`[{text, score, acoustic_score, lm_score}]`), `alignment` (`[{token, start_sec, end_sec, confidence}]`), `rtf`, `duration_sec`, `utterance_id`, plus when `include_visuals=True`: `waveform`, `log_mel`, `ctc_posteriors` (`{times_sec, top_tokens, probs}`), `vad_segments` (`[[s, e], ...]`).
  - `ASREngine.redecode(utterance_id, decode_cfg)` returns keys: `text`, `hypotheses`, `alignment`, `utterance_id`, `duration_sec`, `decode_ms`. Raises `KeyError` on unknown ID, `TypeError` on invalid `decode_cfg`.
  - `asr.audio.load_wav_bytes(data, target_sr=16000)` handles mono/stereo, 8/16/24/32-bit PCM & IEEE float WAV, resampling, and raises `ValueError` on empty/corrupt WAV bytes.
  - `asr.audio.apply_corruption(wav, sr, *, snr_db=None, noise_type="white", band_limit=None, speed=1.0, gain_db=0.0, seed=None)` raises `ValueError` on invalid `noise_type`, non-positive/non-finite `speed`, non-finite `snr_db`/`gain_db`, or invalid `band_limit`.
  - `asr.metrics.compute_cer(refs, hyps, normalize_kana=True)` returns `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`.

---

## 2. Detailed Test Plan for `tests/test_asr_web.py`

Target runtime: **< 5 seconds total**, 100% deterministic, zero network calls.

### Fixtures (module-scoped)
1. `web_bundle` (`scope="module"`):
   - Creates tiny `cnn_bigru` checkpoint (`ckpt_path`) with 3-epoch `history`.
   - Synthesizes a deterministic 16 kHz mono WAV (`"オハヨウ"`, `seed=7`) in memory (`mono_16k_wav_bytes`).
   - Creates a 44.1 kHz stereo 16-bit PCM WAV in memory (`stereo_44k_wav_bytes`, 0.5 s) using `io.BytesIO` + `wave`.
2. `client` (`scope="module"`): `TestClient(create_app(checkpoint_path=web_bundle.ckpt_path))`.
3. `client_no_model` (`scope="module"`): `TestClient(create_app())`.
4. `client_engine_with_lm` (`scope="module"`): `TestClient(create_app(engine=ASREngine.from_checkpoint(web_bundle.ckpt_path, lm=...)))`.

### Test Cases

#### A. App Creation, Static Root, Health & Info
1. `test_get_root_html(client, client_no_model)`:
   - Both loaded and no-model apps return `200`, `content-type` starts with `text/html`, non-empty body.
   - Contains key UI markers: `<canvas`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`, `/api/info`.
2. `test_health_loaded_and_unloaded(client, client_no_model)`:
   - `GET /api/health` on `client` -> `200`, `{"status": "ok", "model_loaded": True}`.
   - `GET /api/health` on `client_no_model` -> `200`, `{"status": "ok", "model_loaded": False}`.
3. `test_info_loaded_and_unloaded(client, client_no_model)`:
   - Loaded: `200`, `model_loaded is True`, `arch == "cnn_bigru"`, `vocab_size > 0`, `isinstance(vocab, list)`, `len(vocab) == vocab_size`, `tsukinami_presets` contains all of `{"default", "ossan", "robot", "horror", "whisper", "chibi"}` (and matches `list(yomu.PRESETS.keys())`), `isinstance(history, list)` with `len(history) == 3`, strictly JSON-serializable (`json.dumps(data, allow_nan=False)`).
   - Unloaded: `200`, `model_loaded is False`, `tsukinami_presets` still non-empty and includes `"default"`, `history == []`, strictly JSON-serializable.
4. `test_create_app_precedence_and_missing_checkpoint(web_bundle, tmp_path)`:
   - `create_app(checkpoint_path=tmp_path / "missing.pt")` raises `FileNotFoundError`.
   - `create_app(checkpoint_path=tmp_path / "missing.pt", engine=engine)` uses `engine` without error (explicit `engine` takes precedence).

#### B. `POST /api/transcribe`
5. `test_transcribe_multipart_with_and_without_visuals(client, web_bundle)`:
   - Multipart upload `files={"file": ("sample.wav", web_bundle.mono_16k_wav_bytes, "audio/wav")}` with `data={"method": "beam", "beam_width": "4", "temperature": "1.0", "blank_bias": "0.0", "snr_db": "20", "noise_type": "pink", "band_limit_low": "300", "band_limit_high": "3400", "speed": "1.1", "include_visuals": "true"}`.
   - Assert `200`, required keys `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, plus visuals `waveform`, `log_mel`, `ctc_posteriors` (`times_sec`, `top_tokens`, `probs`), `vad_segments`.
   - Repeat with `data={"method": "greedy", "include_visuals": "false"}` -> assert `200` and `"waveform" not in data`, `"log_mel" not in data`, `"ctc_posteriors" not in data`, `"vad_segments" not in data` (catches the Python `bool("false") == True` bug!).
   - Also test empty-string optional form fields (`snr_db=""`, `band_limit_low=""`, `band_limit_high=""`) -> `200` (not 400/500).
6. `test_transcribe_json_base64(client, web_bundle)`:
   - JSON body `{"audio_b64": b64_str, "decode_cfg": {"method": "beam", "beam_width": 4, "temperature": 0.9, "blank_bias": -0.2}, "corruption": {"snr_db": 15.0, "noise_type": "white", "band_limit": [300.0, 3400.0], "speed": 0.95}, "include_visuals": True}`.
   - Assert `200`, valid schema, visuals present, `utterance_id` non-empty.
   - Also test `audio_b64` with `data:audio/wav;base64,` prefix if supported (or plain base64) and `include_visuals: False`.
7. `test_transcribe_stereo_44k_resampling(client, web_bundle)`:
   - Upload `web_bundle.stereo_44k_wav_bytes` (0.5 s, 44.1 kHz, 2-channel) -> `200`, `duration_sec == pytest.approx(0.5, abs=0.05)`, strictly finite JSON.
8. `test_transcribe_invalid_inputs_return_4xx_never_500(client, web_bundle)`:
   - Empty multipart file (`b""`) -> `status_code in (400, 422)`.
   - Corrupt WAV header (`b"RIFF0000WAVEcorrupt"`) -> `400/422`.
   - Non-WAV garbage bytes (`b"not audio at all"`) -> `400/422`.
   - JSON with invalid base64 (`"!!!not-base64!!!"`) -> `400/422`.
   - JSON with missing `audio_b64` (`{}`) -> `400/422`.
   - Multipart with missing `file` field -> `400/422`.
   - Invalid `decode_cfg` (`method="invalid"`, `beam_width=0`, `temperature=0.0`, `lm_weight=-1.0`) -> `400/422`.
   - Invalid `corruption` (`noise_type="brown"`, `speed=0.0`, `band_limit=[3400, 300]`, partial `band_limit_low=300` without high) -> `400/422`.
   - Malformed JSON body (`content=b"{broken"`, `headers={"Content-Type": "application/json"}`) -> `400/422`.
9. `test_transcribe_no_model_returns_503(client_no_model, web_bundle)`:
   - Multipart upload & JSON upload both return `503`.

#### C. `POST /api/tts-roundtrip`
10. `test_tts_roundtrip_fast_engine_and_corruption(client, web_bundle)`:
    - JSON `{"text": "オハヨウ", "synth_engine": "fast", "preset": "default", "hz": 260.0, "fscale": 1.05, "rate": 1.1, "corruption": {"snr_db": 18.0, "noise_type": "white", "speed": 1.0}, "decode_cfg": {"method": "beam", "beam_width": 4}, "include_visuals": True}`.
    - Assert `200`, keys present: `audio_b64`, `ground_truth_moras`, `cer`, `cer_details`, `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`.
    - Decode `base64.b64decode(data["audio_b64"])` and verify `load_wav_bytes(...)` succeeds with `wav.size > 0` and `sr == 16000`.
    - Verify `ground_truth_moras` is a non-empty list of dicts with keys `{"t", "a", "e"}`.
    - Verify `isinstance(data["cer"], float)` and `0.0 <= data["cer"]`, and `cer_details` has `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`.
11. `test_tts_roundtrip_tsukinami_presets_and_overrides(client)`:
    - Short 2-mora phrase `"アイ"` for speed (~0.5 s each):
      - `synth_engine="tsukinami"`, `preset="default"` -> `200`, valid `audio_b64` WAV, non-empty `ground_truth_moras`.
      - `synth_engine="tsukinami"`, `preset="robot"`, `hz=200.0`, `fscale=1.0`, `yure=0.0`, `rate=1.1` -> `200`, valid `audio_b64` WAV.
    - Hiragana input `"あい"` with `synth_engine="fast"` -> `200` (kana normalization works cleanly).
12. `test_tts_roundtrip_invalid_inputs_and_no_model(client, client_no_model)`:
    - Empty text `""` and whitespace-only `"   "` -> `400/422`.
    - Unspeakable non-kana text `"12345"` -> `400/422`.
    - Unknown preset `"nonexistent_preset"` -> `400/422`.
    - Unknown `synth_engine` `"espeak"` -> `400/422`.
    - Invalid overrides (`hz=-10`, `fscale=0`, `rate=-1`, `yure=-0.5`) -> `400/422`.
    - Invalid `decode_cfg` or `corruption` -> `400/422`.
    - `client_no_model` -> `503`.

#### D. `POST /api/redecode`
13. `test_redecode_from_transcribe_and_roundtrip_fast(client_engine_with_lm, web_bundle)`:
    - Step 1: Call `POST /api/transcribe` (JSON or multipart) -> capture `utt_id_1`.
    - Step 2: Call `POST /api/tts-roundtrip` (`synth_engine="fast"`, `"オハヨウ"`) -> capture `utt_id_2`.
    - Step 3: Warm up once, then call `POST /api/redecode` on `utt_id_1` with:
      - `{"method": "greedy", "temperature": 0.7, "blank_bias": -0.5}` -> `200`, assert `decode_ms < 50.0` (and wall time `< 100.0 ms`), `utterance_id == utt_id_1`, keys `{text, hypotheses, alignment, utterance_id, duration_sec, decode_ms}`.
      - `{"method": "beam", "beam_width": 6, "temperature": 1.2, "blank_bias": 0.3, "lm_weight": 0.3, "insertion_bonus": 0.1}` -> `200`, `decode_ms < 50.0`.
    - Step 4: Call `POST /api/redecode` on `utt_id_2` -> `200`, `utterance_id == utt_id_2`.
14. `test_redecode_unknown_id_invalid_cfg_and_no_model(client, client_no_model)`:
    - Unknown `utterance_id: "does-not-exist"` -> `404`.
    - Invalid `decode_cfg` (e.g., `temperature=0.0` or `method="bad"`) -> `400/422`.
    - `client_no_model` -> `503`.

#### E. Static & Structural Checks on `asr/web/index.html`
15. `test_index_html_zero_cdn_and_self_contained()`:
    - Read `asr/web/index.html` as UTF-8.
    - Regex scan for any external URLs in HTML/CSS/JS resource attributes:
      - `src=["'](https?:|//)`
      - `href=["'](https?:|//)`
      - `url\(\s*["']?(https?:|//)`
      - `@import\s+["']?(https?:|//)`
      - No `cdn.`, `unpkg.com`, `jsdelivr.net`, `googleapis.com`, `gstatic.com`, `cdnjs.cloudflare.com`.
    - Assert zero matches!
16. `test_index_html_structure_and_js_syntax()`:
    - Verify balanced core HTML structure (`<!DOCTYPE html>`, `<html`, `</html>`, `<head`, `</head>`, `<body`, `</body>`, equal count of `<script` and `</script>`, `<style` and `</style>`).
    - Extract all `<script>...</script>` blocks with regex. Assert at least one non-empty inline `<script>` block exists.
    - If `shutil.which("node")` is found (confirmed `/usr/local/bin/node` in this VM), write each script block to `tmp_path / f"script_{i}.js"` and run `subprocess.run(["node", "--check", str(js_file)], capture_output=True, text=True)` -> assert `returncode == 0` (catches any JS syntax error!).
    - Also run pure-Python sanity check (non-empty script, references `/api/info`, `/api/transcribe`, `/api/tts-roundtrip`, `/api/redecode`, `getContext('2d')` / `getContext("2d")`).

---

## 3. Tricky Edge Cases for Server (`asr/server.py`) & UI (`asr/web/index.html`)

Implementers MUST account for these to prevent 500s, subtle bugs, or UI breakage:

1. **Multipart boolean/optional string parsing (`POST /api/transcribe`)**:
   - Form fields arrive as strings. `bool("false")` is `True` in Python! Must parse `"true"/"1"/"yes"/"on"` vs `"false"/"0"/"no"/"off"` explicitly (and reject invalid boolean strings with `400/422`).
   - Empty string `""` for optional form fields (`snr_db`, `band_limit_low`, `band_limit_high`, `speed`, `beam_width`, etc.) must be treated as `None` (use default), NOT fail float/int conversion.
2. **Dual Content-Type (`multipart/form-data` vs `application/json`) on `POST /api/transcribe`**:
   - Use `request: Request` and branch on `request.headers.get("content-type", "").lower()` so FastAPI doesn't reject one format with 422 before the handler runs.
   - Catch `json.JSONDecodeError`, `UnicodeDecodeError`, `binascii.Error`, `ValueError`, `TypeError` and map them cleanly to `HTTPException(status_code=400/422)` — **never 500**.
   - Support optional `data:audio/...;base64,` prefix stripping on `audio_b64`.
   - Enforce a reasonable payload size limit (e.g., 25 MB) to prevent OOM on the 7.8 GiB RAM VM.
3. **Corruption & Decode parameter bounds**:
   - Cap `beam_width` (e.g. `1..64`) and `speed` (e.g. `0.25..4.0`) so adversarial/accidental extreme values cannot hang the CPU or allocate gigabytes during FFT resampling.
   - Reject `NaN` / `Inf` in all numeric inputs (JSON or form).
   - Reject partial `band_limit` (only `band_limit_low` without `band_limit_high`, or vice versa) with `400/422`.
4. **Unspeakable / non-kana text in `POST /api/tts-roundtrip`**:
   - `synthesize_fast_kotoba("12345")` returns an empty array `(np.zeros(0), [])`, while `synthesize_tsukinami("12345")` raises `ValueError`.
   - Server should treat empty synthesized audio (`wav.size == 0`) or `ValueError` from synth as `400/422` consistently across both engines.
   - Use `compute_cer([text], [result["text"]], normalize_kana=True)` so hiragana user input (`"おはよう"`) compares fairly against katakana model output (`"オハヨウ"`).
   - Validate `preset` against `yomu.PRESETS` and validate `hz`, `fscale`, `rate` (> 0, finite) and `yure` (>= 0, finite) before invoking `carve.make` or `synthesize_fast_kotoba`.
   - Encode the **post-corruption** waveform into `audio_b64` (16-bit PCM WAV) so audio playback matches what ASR actually transcribed.
5. **Thread-safety & LRU cache**:
   - Protect `engine.transcribe` and `engine.redecode` with a `threading.Lock` (or serialize access) since `ASREngine._cache` is a plain `OrderedDict` and PyTorch CPU inference isn't intended for concurrent mutation.
6. **UI (`asr/web/index.html`) defensive handling**:
   - **No-model state**: When `/api/info` returns `model_loaded: false`, display a clear status banner and keep the page functional without throwing uncaught exceptions.
   - **Empty visual arrays**: All 4 Canvas 2D renderers (Waveform+VAD, Log-Mel, CTC Posteriors, Alignment) must guard against empty arrays (`length === 0`) and draw a clean placeholder instead of `NaN` coordinates.
   - **Redecode race & debounce**: Debounce slider `input` events (~30–50 ms), no-op if `currentUtteranceId` is null, and use a monotonic request ID so out-of-order responses never clobber newer slider values.
   - **Web Audio / Mic fallback**: Guard `navigator.mediaDevices && navigator.mediaDevices.getUserMedia` for headless/non-HTTPS contexts, and resume `AudioContext` on user gesture.
   - **Strict zero-CDN**: No external `http://`, `https://`, or `//` URLs anywhere in HTML/CSS/JS.
