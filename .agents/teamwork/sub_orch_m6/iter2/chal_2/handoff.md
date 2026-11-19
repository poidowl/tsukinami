# Milestone M6 Adversarial Challenger 2 (`chal_2`, Iteration 2) Handoff

## Verdict: **PASS**

All Iteration 2 frontend fixes in `asr/web/index.html` (and regression coverage in `tests/test_asr_web.py`) passed every adversarial probe with zero defects found. All temporary probe scripts were staged in `mktemp -d` under `/tmp/teamwork_probe.XXXXXX` and cleaned up on exit; no repository files were modified.

---

## Adversarial Probes & Exact Results

### Probe 1: Extract ALL `<script>` blocks from `asr/web/index.html` and run `node --check`
- **Method**: Parsed all `<script>...</script>` blocks from `asr/web/index.html` into a temp dir and executed `node --check` on each.
- **Output**:
  ```text
  Found 1 <script> block(s).
    block[0]: len=44469 chars, exit=0
  PROBE 1: PASS
  ```
- **Result**: **PASS**

---

### Probe 2: Node.js DOM-Event-Bubbling Harness on `#dropZone` / `#btnPickWav` / `#wavFileInput`
- **Method**: Executed the full `<script>` IIFE from `asr/web/index.html` inside a Node.js mock DOM implementing realistic ancestor bubbling (`dispatchEvent`, `stopPropagation`, `contains`, `click()` with recursion guard > 50) matching the real DOM nesting (`#dropZone` -> `<p>`, `#wavFileInput`, `#btnPickWav` -> `<span>`).
- **Simulated interactions & exact outputs**:
  ```text
    [OK] click #btnPickWav -> wavFileInput.clickCallCount=1 (expected 1)
    [OK] click child <span> inside #btnPickWav -> wavFileInput.clickCallCount=1 (expected 1)
    [OK] click #dropZone directly -> wavFileInput.clickCallCount=1 (expected 1)
    [OK] click child <p> inside #dropZone -> wavFileInput.clickCallCount=1 (expected 1)
    [OK] click #wavFileInput directly -> wavFileInput.clickCallCount=1 (expected 1)
  PROBE 2: PASS
  ```
- **Result**: **PASS** (Iteration 1 Defect 1 — infinite click recursion / `RangeError` — is completely resolved, with zero double-triggering.)

---

### Probe 3: `normalizeKanaClient` + `computeClientCer` vs `asr.metrics.compute_cer(..., normalize_kana=True)`
- **Method**: Extracted `normalizeKanaClient` and `computeClientCer` verbatim from `asr/web/index.html`, ran them in Node.js across 19 tricky Japanese string pairs (hiragana/katakana, punctuation `、。！？・`, spaces, small kana `ぁぃぅぇぉっゃゅょゎゕゖ`, `ゔ` -> `ヴ`, prolonged sound mark `ー`, empty strings `""`, tie-breaking edit distances, ASCII, and emoji surrogate pairs), and compared `ref_len`, `substitutions`, `deletions`, `insertions`, and `cer` against Python `asr.metrics.compute_cer(..., normalize_kana=True)`.
- **Output**:
  ```text
  Checked 19 tricky Japanese string pairs -> mismatches=0
  PROBE 3: PASS
  ```
- **Result**: **PASS** (Iteration 1 Defect 2 — punctuation-stripping divergence from `kotoba.to_kata` / server `compute_cer` — is completely resolved.)

---

### Probe 4: DOM ID Integrity & Exhaustive Zero-CDN Compliance
- **Method**: Parsed `asr/web/index.html` via `html.parser.HTMLParser` to collect all `id` attributes and `<label for=...>` references; extracted all `$("...")` / `document.getElementById("...")` calls and `el.<prop>` references from `<script>`; ran exhaustive regex scans for external/CDN references.
- **Output**:
  ```text
  Total HTML id attributes: 76 (unique: 76, duplicates: [])
  JS DOM ID refs: 67, missing from HTML: []
  <label for=...> refs: 12, missing from HTML: []
  el.<prop> keys defined: 67, used: 67, missing: []
    Zero-CDN check [http://]: 0 hit(s)
    Zero-CDN check [https://]: 0 hit(s)
    Zero-CDN check [raw //]: 0 hit(s)
    Zero-CDN check [<link]: 0 hit(s)
    Zero-CDN check [<script src=]: 0 hit(s)
    Zero-CDN check [@import]: 0 hit(s)
    Zero-CDN check [CSS url()]: 0 hit(s)
    Zero-CDN check [known CDN domains]: 0 hit(s)
  ```
- **Result**: **PASS**

---

### Probe 5 (Bonus Regression Check): `URL.revokeObjectURL` Cleanup on Upload -> TTS Round-Trip
- **Method**: Executed the real `<script>` in the Node.js harness, triggered `wavFileInput` `change` (creating a blob object URL via `setAudioSourceBlob`), then triggered `btnRoundtrip` `click` (`runTtsRoundtrip()`).
- **Output**:
  ```text
    [OK] Object URL created on upload (blob:mock-1) and revoked on TTS roundtrip (blob:mock-1)
  PROBE 4 & EXTRA PROBE 5: PASS
  ```
- **Result**: **PASS**

---

## Defects Discovered

None. All Iteration 2 fixes are verified clean.
