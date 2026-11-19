# M2 Iteration 2 Primary Review Report

## Scope & Context Audited
- `ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- `PROJECT.md` (Section 4 Interface Contracts: `asr/synth_data.py`, `asr/dataset.py`)
- `.agents/teamwork/sub_orch_m2/SCOPE.md`
- `.agents/teamwork/sub_orch_m2/iter2_worker/handoff.md`
- Owned M2 files:
  - [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py)
  - [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py)
  - [`tests/test_asr_data.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_data.py)

## Independent Verification Results

### 1. M1 + M2 Unit Test Suite
Command: `.venv/bin/pytest tests/test_asr_dsp.py tests/test_asr_data.py -v`
Exit code: `0`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 64 items

tests/test_asr_dsp.py .............................................      [ 70%]
tests/test_asr_data.py ...................                               [100%]

======================== 64 passed in 60.93s (0:01:00) =========================
```

### 2. Git Working Tree Integrity Check
Command: `git status --short && git diff --stat`
Exit code: `0`
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
Confirmed zero tracked existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, etc.) were modified.

## Iteration 2 Fixes Audit

1. **`_sanitize_whitespace()` in `synthesize_fast_kotoba` and `synthesize_tsukinami`** — **PASS**
   - Defined in `asr/synth_data.py:272-274` (`" ".join(text.split())`).
   - Applied before `kotoba.split_moras()` / `kotoba.tracks_from_kana()` in `synthesize_fast_kotoba` (`asr/synth_data.py:358-360, 362, 389`).
   - Applied consistently in `synthesize_tsukinami` (`asr/synth_data.py:544-546`) and reused for `accent.annotate()`, disk cache key payload (`:565`), `yomu.build_carve_rc()` (`:597`), and cached metadata (`:622`).

2. **Sokuon-only (`"ッ"`) and control-whitespace (`"   \t\n  "`) guards** — **PASS**
   - `synthesize_fast_kotoba`: returns `(np.zeros(0, dtype=np.float32), [])` on `"   \t\n  "` (`asr/synth_data.py:358-360`), and returns silent `np.float32` audio with valid `{"t", "a", "e"}` mora metadata on `"ッ"` (`asr/synth_data.py:367-378`).
   - `synthesize_tsukinami`: raises `ValueError` on `"   \t\n  "` (`asr/synth_data.py:545-546`) and on sokuon/pause-only strings such as `"ッ"` or `"、、、"` via `if not any(m not in ("ッ", "、") for m in ms): raise ValueError(...)` (`asr/synth_data.py:553-554`).

3. **Cold-vs-warm disk cache bit-identical waveform return in `synthesize_tsukinami`** — **PASS**
   - After atomic `save_wav` + `os.replace` and metadata write (`asr/synth_data.py:612-635`), reloads `wav, _ = load_wav(wav_cache_path, target_sr=sr)` (`asr/synth_data.py:636`), matching the warm cache hit path (`asr/synth_data.py:577`) so 16-bit PCM quantization is identical across cold and warm calls (`np.array_equal(wav1, wav2) == True`).

4. **Non-`str` rejection in `_load_transcript_map`** — **PASS**
   - Both `Mapping` (`asr/dataset.py:247-255`) and `.json` (`asr/dataset.py:275-282`) paths validate `isinstance(v, str)` and raise a clear `ValueError` instead of coercing non-strings (such as `None` / JSON `null`) via `str(v)`.

5. **Minor cleanup (`TRAIN_CORPUS` literal)** — **PASS**
   - `asr/synth_data.py:172` uses the direct katakana literal `"キップヲカッテ、デパチカヘイク"`.

6. **Regression tests in `tests/test_asr_data.py`** — **PASS**
   - `synthesize_fast_kotoba("   \t\n  ")` and `synthesize_fast_kotoba("ッ")` (`tests/test_asr_data.py:210-215`).
   - `synthesize_tsukinami("   \t\n  ")` and `synthesize_tsukinami("ッ")` raising `ValueError` (`tests/test_asr_data.py:291-294`).
   - `synthesize_tsukinami(..., cache_dir=...)` cold vs warm bit-identical check via `np.array_equal(wav1, wav2)` (`tests/test_asr_data.py:315-318`).
   - `build_manifest_from_wav_dir` rejecting `{"good": None}` and JSON `{"good": null}` (`tests/test_asr_data.py:616-622`).

7. **Interface Contracts (`PROJECT.md` & `SCOPE.md`)** — **PASS**
   - All function signatures, return types, JSONL schema (`audio_path`, `text`, `duration`, `speaker`, `source`, `moras`), PyTorch `Dataset` / `collate_asr_batch` batch keys & tensor dtypes, and Tier 3 WAV directory manifest helper match the contracts exactly.

## Blocking Issues
None.

VERDICT: APPROVE
