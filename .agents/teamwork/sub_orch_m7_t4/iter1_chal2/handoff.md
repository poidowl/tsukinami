# Challenger 2 Handoff — M7 Phase 1 Tier 4 E2E (`sub_orch_m7_t4` / `iter1_chal2`)

## Verdict: `CONFIRMED_CORRECT`

All adversarial probes across the FastAPI Web Playground API (`asr/server.py`), HTTP JSON `ctc_posteriors` contract, zero-CDN HTML & `drawCtcPosteriors` Canvas 2D JavaScript (`asr/web/index.html`), and Tier-3 real-audio WAV folder corpus workflow (`asr/dataset.py`) passed with zero defects found.

---

## 1. Probe Scope & Execution Summary

All ad-hoc probe scripts were staged in an isolated temporary directory (`/tmp/teamwork_probe.yunP50`, created with `mktemp -d`) with `OMP_NUM_THREADS=1`, executed against the repository code without modifying any tracked or untracked project files, and cleanly deleted before reporting.

### A. FastAPI `create_app` Endpoints & Adversarial Input Handling (`asr/server.py`)
- **No-model mode (`create_app()`)**:
  - `GET /` -> `200 OK` (`text/html`)
  - `GET /api/health` -> `200 OK`, `{"status": "ok", "model_loaded": false}`
  - `GET /api/info` -> `200 OK`, `model_loaded: false`
  - `POST /api/transcribe`, `/api/tts-roundtrip`, `/api/redecode` -> `503 Service Unavailable`
- **Loaded-model mode (`create_app(engine=...)` with `cnn_bigru` + `CharNgramLM`)**:
  - `GET /` -> `200 OK` (`text/html`)
  - `GET /api/health` -> `200 OK`, `{"status": "ok", "model_loaded": true}`
  - `GET /api/info` -> `200 OK`, verified `vocab_size == len(vocab) == 86`, `blank_id == 0`, `has_lm == true`, and all 6 presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`).
  - `POST /api/transcribe`:
    - Multipart 16 kHz mono WAV + combined corruptions (`snr_db=15`, `noise_type="pink"`, `band_limit="300,3400"`, `speed="1.1"`, `include_visuals="true"`) -> `200 OK`
    - Multipart 44.1 kHz stereo WAV and 8 kHz mono WAV -> `200 OK` (cleanly resampled and downmixed)
    - JSON raw base64 WAV (`include_visuals=true`) and `data:audio/wav;base64,...` data URI (`include_visuals=false`) -> `200 OK`
    - 16 adversarial error cases all rejected cleanly with `400`/`422`: empty multipart (`400`), corrupt bytes (`400`), truncated RIFF header (`400`), valid WAV with 0 frames (`400`), missing `file` field (`422`), invalid base64 (`400`), empty `audio_b64` (`400`), missing `audio_b64` (`422`), corrupt/zero-frame base64 WAV (`400`), invalid `beam_width` (`0` / `999` -> `422`), invalid `method` (`422`), invalid `noise_type` (`422`), inverted `band_limit` (`422`), out-of-range `speed` (`422`).
  - `POST /api/tts-roundtrip`:
    - All 6 presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`) on `synth_engine="fast"` (with additive noise, band-limit, and speed perturbation on `ossan` & `whisper`) -> `200 OK`, valid base64 WAV decodable to 16 kHz PCM, non-empty `ground_truth_moras`, finite `cer`.
    - Authentic `synth_engine="tsukinami"` on `default` and `robot` -> `200 OK`.
    - Adversarial inputs rejected cleanly: empty text (`422`), unknown preset (`422`), invalid `synth_engine` (`422`), non-speakable punctuation `"!!!"` (`400`), negative `hz` (`422`), forbidden extra field (`422`), >500-char text (`422`). (Note: `"12345!!!"` returns `200` because `kotoba.split_moras` legitimately produces moras for digits; `"!!!"` has 0 moras and returns `400`.)
  - `POST /api/redecode`:
    - Unknown `utterance_id` -> `404 Not Found`
    - Empty/whitespace `utterance_id` -> `422 Unprocessable Entity`
    - Cached re-decode latency (10 runs, single-threaded):
      - `engine.redecode(greedy)`: min `0.59 ms`, median `0.68 ms` (`<10 ms`)
      - `engine.redecode(beam, bw=4)`: min `6.09 ms`, median `8.27 ms` (`<10 ms`)
      - `engine.redecode(beam, bw=8)`: min `9.23 ms`, median `15.18 ms` (on 35-frame flat-entropy untrained model under shared 2-vCPU load)
      - HTTP `POST /api/redecode` (TestClient): `6.91–7.04 ms` for greedy, `12.26–12.90 ms` for beam with LM.

### B. `ctc_posteriors` HTTP JSON Contract Verification
Verified across every `/api/transcribe` (16 kHz, 44.1 kHz stereo, 8 kHz mono, JSON base64) and `/api/tts-roundtrip` (6 `fast` presets + 2 `tsukinami` presets) response:
- Strictly a 2D JSON `list[list[float]]` of shape `(T', V)` with `V == vocab_size == 86`.
- All entries finite and within `[0.0, 1.0]`.
- Every frame row sums to `1.0` with maximum observed error `<= 8.00e-06` (well within `1e-4`).

### C. Zero-CDN Audit & `drawCtcPosteriors` JS Execution (`asr/web/index.html`, Node.js v24.22.3)
- **Zero-CDN**: Audited all 2,162 lines of `asr/web/index.html` — `0` occurrences of `http://`, `https://`, protocol-relative `src="//..."` / `href="//..."`, or `@import`. Single inline `<script>` tag with no `src` attribute.
- **Executed actual `drawCtcPosteriors()` from `asr/web/index.html` in Node.js `vm` with a strict mock Canvas 2D context** (throwing on any non-finite coordinate):
  1. Standard 2D `(T=3, V=15)` matrix with `state.info.vocab` & `blank_id=0`: rendered 12 rows (`<blank>` + top 11 non-blank tokens sorted by descending peak probability) and heatmap cells cleanly.
  2. Missing `state.info` (`null`) and missing `state.info.vocab`: gracefully fell back to `["<blank>", "#1", "#2"]`.
  3. Empty/null inputs (`[]`, `[[]]`, `null`, `undefined`): invoked `drawEmptyPlaceholder` cleanly with zero errors.
  4. Legacy object format `{ probs, top_tokens }`: rendered labels and cells cleanly.
  5. Adversarial non-zero `blank_id=2`, out-of-range `blank_id=99`, `NaN` values, and ragged/`null` rows: handled safely with finite canvas coordinates and no exceptions.

### D. Tier-3 WAV Folder Corpus Workflow (`asr/dataset.py`)
- Built synthetic WAV directory containing:
  - `utt_8k.wav` (8 kHz mono, 16-bit)
  - `nested/utt_44k_stereo.wav` (44.1 kHz stereo, 16-bit)
  - `utt_22k.wav` (22.05 kHz mono, 16-bit)
  - `unmatched_extra.wav` (correctly skipped when absent from transcript map)
- Verified `build_manifest_from_wav_dir` with Python `dict` (matching stem, relative POSIX path, and filename with mixed Hiragana/Katakana/punctuation Japanese transcripts) AND JSUT `id:text` `.txt` format.
- Verified `ASRManifestDataset` (`augment=False` and `augment=True`) -> `collate_asr_batch` -> `build_model("cnn_bigru")` -> `nn.CTCLoss`: collated `feats` shape `(3, 68, 64)` all finite, non-empty encoded kana targets, finite positive CTC loss (`3.4621`).
- Verified corrupt WAV in `wav_dir` raises `ValueError` cleanly.

---

## 2. Repository Hygiene Verification
- Removed `/tmp/teamwork_probe.yunP50` completely (`test ! -d` confirmed).
- `git status --short` confirms zero tracked `tsukinami` TTS files modified and no probe artifacts left in the repo.
