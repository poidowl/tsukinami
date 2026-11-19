# Milestone M6 Secondary Review (`rev_2`, Iteration 2) Handoff

## Verdict: **APPROVE**

All four Iteration 2 changes in `asr/web/index.html` and `tests/test_asr_web.py` are verified, cleanly implemented, and covered by genuine runtime regression tests. Zero defects found.

---

## Verification Results

### 1. Target-Scoped Test Suite
Command:
```bash
.venv/bin/pytest tests/test_asr_web.py -v
```
Output (exit code `0`):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 18 items

tests/test_asr_web.py ..................                                 [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 18 passed, 1 warning in 9.42s =========================
```

### 2. Audit of Iteration 2 Changes

1. **`#dropZone` / `#btnPickWav` / `#wavFileInput` click handling (`asr/web/index.html:2030-2045`) — PASS**
   - `el.wavFileInput` registers a click listener calling `e.stopPropagation()`, preventing programmatic `.click()` from bubbling back to `#dropZone`.
   - `el.btnPickWav` calls `e.stopPropagation()` before invoking `el.wavFileInput.click()`.
   - `el.dropZone` guards with `e.target !== el.btnPickWav && e.target !== el.wavFileInput && !el.btnPickWav.contains(e.target)`.
   - Zero recursion risk across all click targets (`#btnPickWav`, children of `#btnPickWav`, `#dropZone`, children of `#dropZone`, and `#wavFileInput` directly).

2. **`normalizeKanaClient` parity with `asr.metrics.compute_cer(..., normalize_kana=True)` (`asr/web/index.html:973-1025`) — PASS**
   - Verified `kotoba.to_kata(s)` maps `0x3041..0x3096` (`ぁ..ゖ`) to `+ 0x60` without stripping punctuation or whitespace.
   - `normalizeKanaClient(s)` uses the exact same `0x3041..0x3096` -> `+ 0x60` range and returns `out` unmodified.
   - `computeClientCer(refStr, hypStr)` uses `Array.from(...)` (code-point safe), identical Levenshtein tie-breaking (`sub <= del && sub <= ins`, `del <= ins`), and identical empty-reference handling (`m > 0 ? ... : (n > 0 ? 1.0 : 0.0)`), giving exact 1:1 parity with `asr.metrics.compute_cer(..., normalize_kana=True)`.

3. **`state.lastObjectUrl` revocation in `runTtsRoundtrip()` (`asr/web/index.html:1773-1779`) — PASS**
   - Revokes and nulls `state.lastObjectUrl` via `URL.revokeObjectURL(state.lastObjectUrl)` before assigning `el.audioPlayer.src = "data:audio/wav;base64," + data.audio_b64;`, preventing blob URL leaks when switching from Mic/WAV upload to TTS round-trip.

4. **Zero-CDN invariant (`asr/web/index.html`) — PASS**
   - Confirmed via `test_index_html_zero_cdn_and_self_contained` and full-file inspection: zero external `http://`, `https://`, protocol-relative `//`, `@import`, `url(http...)`, or CDN references exist in `asr/web/index.html`.
   - `node --check` passes cleanly on the inline script block via `test_index_html_structure_and_js_syntax`.

5. **Regression tests (`tests/test_asr_web.py:675-850`) — PASS**
   - `test_dropzone_click_no_infinite_recursion_regression`: extracts the real click-handler registrations from `asr/web/index.html` and executes them in Node.js with a DOM event-bubbling `MockElement` harness across all 5 click paths, verifying exact single-trigger behavior and guarding against recursion.
   - `test_client_cer_normalization_matches_server_compute_cer`: extracts the real `normalizeKanaClient` and `computeClientCer` functions from `asr/web/index.html`, runs them in Node.js over 7 test pairs (including punctuation `、` and `。`, hiragana, and empty strings), and asserts exact equality on `ref_len`, `substitutions`, `deletions`, `insertions`, and `cer` against `asr.metrics.compute_cer(..., normalize_kana=True)`.

### 3. Working Tree Integrity
`git status --short && git diff --stat` confirms zero tracked TTS files were modified and no repository files were touched during review.
