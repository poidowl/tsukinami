# M2 Iteration 2 Worker Handoff

## Summary of Changes

Modified **only** the 3 owned files:
1. [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py)
   - Added `_sanitize_whitespace(text: str) -> str` (`" ".join(text.split())`) to normalize control/Unicode whitespace (`\t`, `\n`, `\r`, etc.) cleanly before `kotoba.split_moras()` / `kotoba.tracks_from_kana()` / `accent.annotate()` / `yomu.build_carve_rc()`.
   - **Issue 1 (`synthesize_tsukinami`)**: Updated the speakable-mora guard to `if not any(m not in ("ッ", "、") for m in ms): raise ValueError(...)`, preventing unhandled `IndexError` on `"ッ"` and ensuring whitespace-only inputs like `"   \t\n  "` raise `ValueError`.
   - **Issue 2 (`synthesize_fast_kotoba`)**: Sanitized whitespace before `kotoba.split_moras()` / `kotoba.tracks_from_kana()` and returned `(np.zeros(0, dtype=np.float32), [])` when `cleaned_text` is empty, preventing audible output and fake `'\t'`/`'\n'` moras on `"   \t\n  "`.
   - **Issue 3 (`synthesize_tsukinami` cache consistency)**: After atomically writing `wav_cache_path` and `meta_cache_path`, reloaded `wav, _ = load_wav(wav_cache_path, target_sr=sr)` before returning so cold writes and warm cache hits return bit-identical waveforms (`np.array_equal(w1, w2) == True`).
   - **Minor cleanup**: Replaced `"キップヲカッテ、デパ地下ヘイク".replace("地下", "チカ")` with the direct literal `"キップヲカッテ、デパチカヘイク"`.
2. [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py)
   - **Minor cleanup (`_load_transcript_map`)**: Validated that transcript values in both `Mapping` and `.json` inputs are `str`, raising a clear `ValueError` on non-string values (e.g., `None` / JSON `null`) instead of coercing via `str(v)`.
3. [`tests/test_asr_data.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_data.py)
   - Added regression assertions for:
     - `synthesize_fast_kotoba("   \t\n  ")` returning empty `float32` waveform and `[]` moras.
     - `synthesize_tsukinami("   \t\n  ")` and `synthesize_tsukinami("ッ")` raising `ValueError`.
     - `synthesize_tsukinami(..., cache_dir=...)` cold call vs warm cache hit returning bit-identical waveforms (`np.array_equal(wav1, wav2)`).
     - `build_manifest_from_wav_dir` rejecting non-string (`None` in dict and JSON `null`) transcript values with `ValueError`.

## Verification Commands & Exact Outputs

### 1. `.venv/bin/pytest tests/test_asr_data.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 19 items

tests/test_asr_data.py ...................                               [100%]

============================= 19 passed in 41.36s ==============================
```
Exit code: `0`

### 2. `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 64 items

tests/test_asr_dsp.py .............................................      [ 70%]
tests/test_asr_data.py ...................                               [100%]

============================= 64 passed in 41.70s ==============================
```
Exit code: `0`

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
Exit code: `0` (zero tracked existing TTS files modified; only the 3 owned M2 files were edited).
