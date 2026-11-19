# M2 Iteration 2 Secondary Reviewer Handoff (`iter2_rev2`)

## Summary

Audited the Iteration 2 changes in [`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py), [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py), and [`tests/test_asr_data.py`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_data.py) against `ORIGINAL_REQUEST.md`, `PROJECT.md`, `SCOPE.md`, and `iter2_worker/handoff.md`. All target-scoped unit tests pass (19/19), existing TTS files remain untouched, and all Iteration 2 fixes are clean and sound.

---

## Independent Verification

### 1. Target-Scoped Unit Tests
Command: `.venv/bin/pytest tests/test_asr_data.py -v` (Cwd: `/home/antigravity/poidowl/tsukinami`)
Exit code: `0`
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 19 items

tests/test_asr_data.py ...................                               [100%]

======================== 19 passed in 63.43s (0:01:03) =========================
```

### 2. Read-Only Behavior Probe (`_sanitize_whitespace`, `synthesize_fast_kotoba`, Kaldi `_load_transcript_map`)
Command: `.venv/bin/python -c "..."` (read-only probe, no workspace files created or modified)
Exit code: `0`
```text
'ワタシ、ニホンゴ、チョットシャベレマス' -> 'ワタシ、ニホンゴ、チョットシャベレマス' moras: ['ワ', 'タ', 'シ', '、', 'ニ', 'ホ', 'ン', 'ゴ', '、', 'チョ', 'ッ', 'ト', 'シャ', 'ベ', 'レ', 'マ', 'ス']
'わたし、にほんご' -> 'わたし、にほんご' moras: ['ワ', 'タ', 'シ', '、', 'ニ', 'ホ', 'ン', 'ゴ']
'ア\tイ\nウ\r\nエ\u3000オ' -> 'ア イ ウ エ オ' moras: ['ア', '、', 'イ', '、', 'ウ', '、', 'エ', '、', 'オ']
"アメ'ガ/フル|ヨ？" -> "アメ'ガ/フル|ヨ？" moras: ['ア', 'メ', "'", 'ガ', '/', 'フ', 'ル', '|', 'ヨ']
'   \t\n\u3000  ' -> '' moras: []
fast tab/nl: (20480,) float32 ['ア', '、', 'イ', '、', 'ウ']
kaldi: {'utt1': 'ワタシ ニホンゴ', 'utt2': 'サクラ'}
```

### 3. Working Tree Integrity
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
Zero tracked existing TTS files modified.

---

## Deep Audit Findings

1. **`_sanitize_whitespace` & Cache Keying ([`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L272-L274), [`L358-L389`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L358-L389), [`L544-L597`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L544-L597)) — PASS**
   - `" ".join(text.split())` normalizes control and Unicode whitespace (`\t`, `\n`, `\r`, `\u3000`) to single ASCII spaces without modifying valid katakana, hiragana, punctuation (`、`, `ー`, `ッ`), or accent marks (`'`, `’`, `0`, `/`, `|`, `?`, `？`).
   - `synthesize_fast_kotoba` returns `(np.zeros(0, dtype=np.float32), [])` on whitespace-only input (`"   \t\n  "`) and converts embedded control whitespace cleanly into pauses (`'、'`) rather than fake control-char moras.
   - `synthesize_tsukinami` rejects whitespace-only and pause/sokuon-only inputs (`"   \t\n  "`, `"ッ"`, `"、、、"`) with `ValueError` via `if not any(m not in ("ッ", "、") for m in ms):` (`L553-L554`).
   - `sanitized_text` is used consistently for both the SHA-256 cache key (`payload["text"]` at `L565`) and synthesis (`yomu.build_carve_rc(sanitized_text, prm)` at `L597`), so cache keys and synthesized outputs are strictly consistent.
   - Corpus literal cleanup verified at [`asr/synth_data.py#L172`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L172) (`"キップヲカッテ、デパチカヘイク"`).

2. **Cold-Write Reload & Atomic Cache Semantics ([`asr/synth_data.py`](file:///home/antigravity/poidowl/tsukinami/asr/synth_data.py#L612-L638)) — PASS**
   - Writes go to unique PID+UUID temporary files (`tmp_wav`, `tmp_meta`) and are published via `os.replace`, with cleanup of any temp files on exception (`L629-L635`).
   - After both files are atomically in place, `wav, _ = load_wav(wav_cache_path, target_sr=sr)` (`L636`) reloads the 16-bit PCM WAV at `sr` (zero resampling), guaranteeing bit-identical waveforms between cold writes and warm cache hits (`np.array_equal(wav1, wav2)` verified in [`tests/test_asr_data.py#L318`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_data.py#L318)).
   - *Minor non-blocking observation*: If an external cache evictor unlinks `wav_cache_path` in the window between `os.replace` (`L619`) and `load_wav` (`L636`), `load_wav` raises `FileNotFoundError` rather than falling back to the in-memory array; this is acceptable and preserves strict cache-read parity without leaving orphan temp files.

3. **`_load_transcript_map` Format Support & Type Validation ([`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py#L246-L303)) — PASS**
   - Preserves support for all 5 documented formats: Python `Mapping` (`dict`), `.json`, `.tsv`, JSUT `id:text`, and Kaldi `id text`.
   - Explicitly validates `isinstance(v, str)` for both `Mapping` (`L250-L253`) and `.json` (`L277-L280`), raising a clear `ValueError` on `None` / JSON `null` or other non-string values instead of silently stringifying them. Regression tests verified at [`tests/test_asr_data.py#L616-L622`](file:///home/antigravity/poidowl/tsukinami/tests/test_asr_data.py#L616-L622).

VERDICT: APPROVE
