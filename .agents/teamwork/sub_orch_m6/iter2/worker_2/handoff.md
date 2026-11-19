# Milestone M6 Implementation Worker 2 (`worker_2`, Iteration 2) Handoff

## Summary of Changes

All four required Iteration 2 fixes were implemented cleanly within exclusively owned M6 files (`asr/web/index.html` and `tests/test_asr_web.py`; `asr/server.py` required no changes, and no M1–M5, TTS, or `tests_e2e/` files were touched):

1. **[BLOCKING — `chal_2` Defect 1] Fixed infinite click recursion on `#dropZone` / `#btnPickWav` / `#wavFileInput` (`asr/web/index.html`)**:
   - Added `el.wavFileInput.addEventListener("click", (e) => { e.stopPropagation(); });` so programmatic `.click()` on the nested `<input type="file" id="wavFileInput">` never bubbles back to `#dropZone`.
   - Stopped propagation in `el.btnPickWav`'s click handler (`e.stopPropagation(); el.wavFileInput.click();`).
   - Hardened `el.dropZone`'s click handler guard to `if (e.target !== el.btnPickWav && e.target !== el.wavFileInput && !el.btnPickWav.contains(e.target)) { el.wavFileInput.click(); }`.

2. **[UX Consistency — `chal_2` Defect 2] Aligned `normalizeKanaClient` with server-side `compute_cer(..., normalize_kana=True)` (`asr/web/index.html`)**:
   - Verified `asr/metrics.py` calls `kotoba.to_kata(s)`, which maps hiragana `U+3041..U+3096` to katakana (`+ 0x60`) without stripping punctuation such as `、` or `。`.
   - Updated `normalizeKanaClient(s)` to `return out;` instead of stripping `[\s、。,.!?！？・]+`, ensuring exact client/server CER parity when adjusting `/api/redecode` sliders after a TTS round-trip.

3. **[Minor Polish — `rev_1`/`rev_2`] Revoked prior object URL in `runTtsRoundtrip()` (`asr/web/index.html`)**:
   - Added `if (state.lastObjectUrl) { URL.revokeObjectURL(state.lastObjectUrl); state.lastObjectUrl = null; }` before assigning `el.audioPlayer.src = "data:audio/wav;base64," + data.audio_b64;`.

4. **[Regression Tests] Added two regression tests in `tests/test_asr_web.py`**:
   - `test_dropzone_click_no_infinite_recursion_regression`: checks both the static guard/`stopPropagation` code and runs a Node.js DOM event-bubbling harness against the extracted click handlers from `asr/web/index.html` (covering clicks on `#btnPickWav`, a child of `#btnPickWav`, `#dropZone`, a child of `#dropZone`, and `#wavFileInput` directly).
   - `test_client_cer_normalization_matches_server_compute_cer`: executes the extracted `normalizeKanaClient` + `computeClientCer` in Node.js and asserts exact equality (`ref_len`, `substitutions`, `deletions`, `insertions`, `cer`) against `asr.metrics.compute_cer(..., normalize_kana=True)` on Japanese strings with punctuation (including `"ワタシ、ニホンゴ。"` and `"ワタシ、ニホンゴ、チョットシャベレマス"`).
   - Confirmed zero external CDN references remain via `test_index_html_zero_cdn_and_self_contained` and JS syntax validity via `node --check` in `test_index_html_structure_and_js_syntax`.

---

## Verification Commands & Outputs

### 1. `.venv/bin/pytest tests/test_asr_web.py -v`
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
======================== 18 passed, 1 warning in 10.43s ========================
```

### 2. `.venv/bin/pytest tests/ -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 153 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ...................                               [ 22%]
tests/test_asr_decoding.py ......................................        [ 47%]
tests/test_asr_dsp.py .............................................      [ 77%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_web.py ..................                                 [100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 153 passed, 2 warnings in 78.14s (0:01:18) ==================
```

### 3. `git status --short && git diff --stat`
```text
?? .agents/
?? .gitignore
?? PROJECT.md
?? TEST_INFRA.md
?? TEST_READY.md
?? asr/
?? pyproject.toml
?? tests/
?? tests_e2e/
```
(No existing tracked TTS files were modified.)
