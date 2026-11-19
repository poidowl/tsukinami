# Milestone M6 Adversarial Challenger 2 (`chal_2`) Handoff

## Verdict: **FAIL**

All static checks, `node --check` JS syntax verification, DOM ID integrity, pure-JS WAV encoding (`encodeWav16BitPCM` + `linearResample`), Zero-CDN compliance, and CLI/`create_app(checkpoint_path=...)` integration **PASSED**, **except** a real browser runtime bug discovered in `asr/web/index.html` (`#dropZone` / `#btnPickWav` click event bubbling infinite recursion) plus a minor client/server CER normalization mismatch.

---

## Defects Discovered

### Defect 1 (HIGH — Blocking): Infinite Click Recursion on WAV Upload (`#dropZone` / `#btnPickWav`)
- **Location**: `asr/web/index.html` lines 624–629 and 2026–2029.
- **Root Cause**: `<input type="file" id="wavFileInput">` is nested inside `<div id="dropZone">`. The event wiring is:
  ```js
  el.btnPickWav.addEventListener("click", () => el.wavFileInput.click());
  el.dropZone.addEventListener("click", (e) => {
    if (e.target !== el.btnPickWav) el.wavFileInput.click();
  });
  ```
  When a user clicks `#btnPickWav` or `#dropZone`, `el.wavFileInput.click()` synchronously dispatches a bubbling `click` event with `e.target === el.wavFileInput`. That event bubbles up to `#dropZone`, where `e.target !== el.btnPickWav` evaluates to `true`, calling `el.wavFileInput.click()` again in an unbounded synchronous recursion (`RangeError: Maximum call stack size exceeded`).
- **Probe Reproduction Output**:
  ```text
  wavFileInput inside #dropZone: true
  REPRODUCED on #btnPickWav click: RangeError: Maximum call stack size exceeded
  ```
- **Recommended Fix**: Guard against `el.wavFileInput` in the `#dropZone` handler (and/or stop propagation on `el.wavFileInput`):
  ```js
  el.dropZone.addEventListener("click", (e) => {
    if (e.target !== el.btnPickWav && e.target !== el.wavFileInput) {
      el.wavFileInput.click();
    }
  });
  ```

### Defect 2 (LOW — Non-blocking UX inconsistency): Client vs. Server CER Normalization Mismatch on Punctuation
- **Location**: `asr/web/index.html` line 984 (`normalizeKanaClient`) vs. `asr/metrics.py` (`compute_cer(..., normalize_kana=True)`).
- **Details**: `normalizeKanaClient` strips `[\s、。,.!?！？・]+`, whereas server-side `compute_cer(..., normalize_kana=True)` preserves `、` (which is in the default TTS input `"ワタシ、ニホンゴ、チョットシャベレマス"`). Moving a `/api/redecode` slider after a TTS round-trip causes the displayed CER badge to jump even if the decoded hypothesis text is unchanged.
- **Probe Output**:
  ```text
  MISMATCH ref='ワタシ、ニホンゴ。' hyp='ワタシニホンゴ':
    JS={'cer': 0, 'substitutions': 0, 'deletions': 0, 'insertions': 0, 'ref_len': 7}
    PY={'cer': 0.2222222222222222, 'substitutions': 0, 'deletions': 2, 'insertions': 0, 'ref_len': 9}
  ```

---

## Detailed Probe Results

### Probe 1: Extract & Syntax-Check All `<script>` Blocks (`node --check`) — PASS
- Node version: `v24.22.3`
- Output:
  ```text
  Found 1 <script> block(s).
    script_0.js (44137 chars): node --check OK
  ```

### Probe 2: Pure JS Helper Harness, DOM ID Integrity & WAV Cross-Verification — PARTIAL (Defect 1 & 2 above; WAV & DOM IDs PASS)
- **DOM ID Integrity**:
  ```text
  Total unique HTML id attributes: 76, duplicates: 0
  Total JS getElementById/$() refs: 67, missing in HTML: 0
  Missing <label for="..."> targets: 0
  ```
- **Pure JS Helpers (`escapeHtml`, `formatParams`, `linearResample`, `encodeWav16BitPCM`)**:
  ```text
  escapeHtml: OK
  formatParams: OK
  encodeWav16BitPCM(16kHz 1s sine): 32044 bytes (expected 32044)
  linearResample(48k->16k) + encodeWav: len=16000, bytes=32044
  encodeWav16BitPCM(edge/clip/NaN): 64 bytes
  encodeWav16BitPCM(empty): 44 bytes
  ```
- **Python `wave` + `asr.audio.load_wav_bytes` Verification of JS-Encoded WAVs**:
  ```text
  js_sine_16k.wav: wave OK, load_wav_bytes OK, max_err vs 440Hz sine = 0.000046
  js_resampled_16k.wav: wave OK, load_wav_bytes OK, max_err vs 440Hz sine = 0.000046
  js_edge.wav: wave OK, load_wav_bytes OK, samples=[-1.0, -1.0, -0.5, 0.0, 0.5, 1.0, 1.0, 0.0, 1.0, -1.0]
  js_empty.wav: wave OK (0 frames), load_wav_bytes cleanly raised ValueError: Corrupt WAV payload: WAV file contains no audio frames
  ```

### Probe 3: Exhaustive Zero-CDN / External Reference Scan (`asr/web/index.html`) — PASS
```text
http://: 0 match(es)
https://: 0 match(es)
ws:// or wss://: 0 match(es)
protocol-relative // in HTML attrs/CSS: 0 match(es)
cdn keyword: 1 match(es) -> ["CDN"]   # literal subtitle text "(Zero-CDN)" on line 511
google fonts: 0 match(es)
@import: 0 match(es)
url(http: 0 match(es)
<link tag: 0 match(es)
<script src=: 0 match(es)
<img src=http: 0 match(es)
fetch(http: 0 match(es)
```

### Probe 4: CLI Integration & Real Disk Checkpoint (`create_app(checkpoint_path=...)`) — PASS
- **CLI `serve` subcommand validation**:
  ```text
  build_parser(['serve', ...]): OK
  CLI missing checkpoint -> exit 1, stderr: Error: Checkpoint not found: /tmp/teamwork_probe.W2hS7t/does_not_exist.pt
  CLI directory checkpoint -> exit 1, stderr: Error: Checkpoint path is a directory: /tmp/teamwork_probe.W2hS7t
  CLI invalid port 70000 -> exit 1, stderr: Error: --port must be in 1..65535, got 70000
  CLI `python -m asr serve --help` -> exit 0 OK
  ```
- **Real Tiny `cnn_bigru` Checkpoint Trained on Disk -> `create_app(checkpoint_path=best.pt)`**:
  ```text
  Trained tiny checkpoint on disk: best.pt (427019 bytes)
  GET /: 200 OK, content-type='text/html; charset=utf-8', 70160 bytes, UTF-8 Japanese intact
  GET /api/health: {'status': 'ok', 'model_loaded': True}
  GET /api/info: arch=cnn_bigru, vocab=86, presets=8, history_len=1
  POST /api/transcribe (JS-encoded WAV): 200 OK, duration=1.00s, utt_id=b0568e8d...
  POST /api/redecode: 200 OK, decode_ms=0.57ms
  POST /api/tts-roundtrip: 200 OK, audio_samples=22000, cer=1.667, moras=9
  ```

---

## Hygiene Confirmation
- All probe scripts and temporary checkpoints were staged in `/tmp/teamwork_probe.XXXXXX` and removed upon exit.
- Repository working tree was not modified (only this `handoff.md` was written).
