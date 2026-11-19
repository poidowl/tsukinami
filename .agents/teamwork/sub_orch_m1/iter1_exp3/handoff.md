# Explorer 3 Handoff — `kotoba.py` Analysis, `asr/tokenizer.py` Design & `tests/test_asr_dsp.py` Plan

## 1. `kotoba.py` Deep-Dive Findings

File inspected: `/home/antigravity/poidowl/tsukinami/kotoba.py` (366 lines, pure stdlib, DO NOT MODIFY).

### Tables & Functions
- **`K2V` (71 entries)**: Maps 71 standard full-size Katakana characters to `(consonant, vowel)`:
  - Vowels (5): `ア イ ウ エ オ` → `("", v)`
  - 13 full rows + Y (3: `ヤ ユ ヨ`) + W (2: `ワ ヲ`) + `ヴ` (1) = 71 chars.
  - Special mappings: `シ→("sh","i")`, `チ→("ch","i")`, `ツ→("ts","u")`, `ジ→("j","i")`, `ヂ→("j","i")`, `ヅ→("z","u")`, `フ→("f","u")`, `ヴ→("b","u")`, `ヲ→("","o")`.
  - Consonants in `PLACE` (19 non-empty): `k, g, s, z, sh, j, t, d, ch, ts, n, h, f, m, y, r, w, b, p`.
  - Vowels (5): `a, i, u, e, o`.
- **`SMALL` (8 entries)**: `ャ:a, ュ:u, ョ:o, ァ:a, ィ:i, ゥ:u, ェ:e, ォ:o`.
  - Note: `ッ` is NOT in `SMALL`; it is a special mora (`kind='Q'`).
- **Special moras**: `ッ` (`kind='Q'`), `ン` (`kind='N'`), `ー` (repeats previous vowel `pv` in `parse_kana`), `、` (`kind='pau'`).
- **`PAUSE` (13 chars)**: `set("、。，．,.!！?？… 　")`.
- **`to_kata(s)`**: Converts Hiragana `ぁ` (U+3041) .. `ゖ` (U+3096) (including `ゔ` → `ヴ`) to Katakana `ァ`..`ヶ` via `+0x60`; leaves all other chars unchanged.
- **`split_moras(text)`**: Calls `to_kata(text)`, merges `SMALL` onto preceding mora (unless preceding is `、`, `ッ`, `ン`, `ー`, or empty), normalizes all `PAUSE` chars to `、`, collapses consecutive pauses, and **strips leading and trailing pauses**.
- **`parse_kana(t, pv)`**: Returns `(c, v, pal)` where `pal=True` for palatalized `ャ/ュ/ョ` moras whose consonant is not already palatal (`sh/ch/j`) and not in `PALC` (`s→sh, z→j, t→ch, d→j`).

### Quirks & Edge Cases to Handle in `asr/tokenizer.py`
1. **`parse_kana` silent fallback on unknown chars**: Line 44 does `K2V.get(t, ('', pv))`, so unknown tokens (ASCII, kanji, etc.) silently return `('', pv, False)` (a spurious vowel!). In `phoneme` mode, we MUST validate that `t` is in `{"、", "ッ", "ン", "ー"}`, or in `K2V`, or a 2-char `K2V + SMALL` pair before calling `parse_kana`; skip unknown tokens otherwise.
2. **`split_moras` strips trailing/leading pauses & normalizes `。`/` ` to `、`**: For `kana` mode, using `to_kata(text)` directly (char-level) preserves `、`, `。`, and `" "` faithfully, whereas `phoneme` mode benefits from `split_moras` to correctly parse palatalized moras (`キョ`, `シャ`, `ファ`, etc.).
3. **Import safety**: `kotoba.py` sits at repo root. `asr/tokenizer.py` should do `try: import kotoba` with a fallback that adds `Path(__file__).resolve().parent.parent` to `sys.path` if needed.

---

## 2. `asr/tokenizer.py` Design Specification

### Public API & Contract
```python
class Tokenizer:
    BLANK_TOKEN = "<blank>"
    VALID_MODES = ("kana", "phoneme", "ascii")

    def __init__(self, mode: str = "kana", vocab: list[str] | None = None) -> None: ...
    @property
    def blank_id(self) -> int: return 0
    @property
    def vocab_size(self) -> int: return len(self.vocab)

    def encode(self, text: str) -> list[int]: ...
    def decode_tokens(self, ids: Sequence[int], collapse_ctc: bool = False) -> list[str]: ...
    def decode(self, ids: Sequence[int], collapse_ctc: bool = False) -> str: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Tokenizer": ...
```

Attributes to expose for downstream milestones (M2, M3, M4, M5, M6):
- `self.mode: str`
- `self.vocab: list[str]` (`self.vocab[0] == "<blank>"`)
- `self.blank_token: str` (`"<blank>"`)
- `self.blank_id: int` (`0`)
- `self.vocab_size: int` (`len(self.vocab)`)
- `self.token_to_id: dict[str, int]`
- `self.id_to_token: dict[int, str]`
- `__eq__`, `__repr__`

### Default Vocabularies

#### 1. `mode="kana"` — Character-Level Katakana (**86 tokens**)
Why char-level instead of mora-level by default:
- Compact output space (86 vs 120+): trains cleanly on small CPU datasets (200 utterances) and compositionally generalizes to all palatalized moras (`キャ`/`キュ`/`キョ`/`ファ`/`ティ` etc.).
- Exact round-trip for `encode`/`decode`, preserves `、`, `。`, and `" "`.
- Pairs directly with M4 `CharNgramLM` and `compute_cer` (while `compute_mer` uses `kotoba.split_moras`).
- With 40 ms CTC frames (4× subsampling), a ~150 ms palatalized mora has ~3.75 frames — plenty for 2 distinct chars.

Exact token order (index 0 = `"<blank>"`):
- `[0]`: `"<blank>"`
- `[1..71]`: All 71 chars from `kotoba.K2V` in canonical gojūon order:
  - `ア イ ウ エ オ`
  - `カ キ ク ケ コ`
  - `サ シ ス セ ソ`
  - `タ チ ツ テ ト`
  - `ナ ニ ヌ ネ ノ`
  - `ハ ヒ フ ヘ ホ`
  - `マ ミ ム メ モ`
  - `ヤ ユ ヨ`
  - `ラ リ ル レ ロ`
  - `ワ ヲ`
  - `ガ ギ グ ゲ ゴ`
  - `ザ ジ ズ ゼ ゾ`
  - `ダ ヂ ヅ デ ド`
  - `バ ビ ブ ベ ボ`
  - `パ ピ プ ペ ポ`
  - `ヴ`
- `[72..74]`: Special moras: `ン`, `ッ`, `ー`
- `[75..82]`: Small kana (`kotoba.SMALL`): `ャ`, `ュ`, `ョ`, `ァ`, `ィ`, `ゥ`, `ェ`, `ォ`
- `[83..85]`: Punctuation & space: `、`, `。`, `" "`
- Total: `1 + 71 + 3 + 8 + 3 = 86` pairwise-disjoint tokens.

Encoding in `kana` mode:
- Convert Hiragana → Katakana via `kotoba.to_kata(text)`.
- Normalize fullwidth space `"\u3000"` → `" "`.
- If custom `vocab` contains multi-char tokens (e.g. user-supplied mora vocab), split via `kotoba.split_moras` and match multi-char tokens first with char-level fallback.
- Otherwise (default char-level): iterate char-by-char and append `token_to_id[ch]` if `ch in token_to_id` (skipping unknown chars deterministically).
- Decoding joins tokens with `""`.

#### 2. `mode="phoneme"` — Kotoba Phoneme Set (**29 tokens**)
Exact token order:
- `[0]`: `"<blank>"`
- `[1..5]`: Vowels: `"a", "i", "u", "e", "o"`
- `[6..24]`: Consonants (19, all non-empty keys of `kotoba.PLACE`): `"k", "g", "s", "z", "sh", "j", "t", "d", "ch", "ts", "n", "h", "f", "m", "y", "r", "w", "b", "p"`
- `[25..28]`: Special moras & pause: `"N", "Q", ":", "pau"`
- Total: **29 tokens**.

Encoding in `phoneme` mode:
- If `text.strip()` is empty → `[]`.
- Round-trip support: if all whitespace-separated parts of `text.strip().split()` are valid non-blank tokens in `self.token_to_id` (e.g. `"k y o u"`), encode them directly!
- Otherwise, parse Japanese kana via `kotoba.split_moras(text)` with `pv = "a"`:
  - `"、"` → `["pau"]`
  - `"ッ"` → `["Q"]`
  - `"ン"` → `["N"]`
  - `"ー"` → `[":"]` (distinct long-vowel token avoids repeated-vowel CTC blank overhead)
  - Valid kana (`m in kotoba.K2V` or `len(m) == 2 and m[0] in kotoba.K2V and m[1] in kotoba.SMALL`):
    - `c, v, pal = kotoba.parse_kana(m, pv)`
    - Emit `c` (if non-empty), `"y"` (if `pal`), `v`; update `pv = v`.
  - Any other token → skip deterministically.
- Decoding joins tokens with `" "` (space-separated, unambiguous for multi-char phonemes `sh`, `ch`, `ts`, `pau`).

#### 3. `mode="ascii"` — Lowercase ASCII (**42 tokens**)
Exact token order:
- `[0]`: `"<blank>"`
- `[1]`: `" "`
- `[2..27]`: `"a"` .. `"z"` (26)
- `[28..37]`: `"0"` .. `"9"` (10)
- `[38..41]`: `"'"`, `"-"`, `","`, `"."` (4)
- Total: **42 tokens**.
- Encoding: `text.lower()`, char-by-char lookup in `token_to_id`, skip unknown chars.
- Decoding: join with `""`.

### Custom `vocab` & Validation Rules
- `mode not in VALID_MODES` → raise `ValueError`.
- If `vocab is not None`:
  - Convert to `list(vocab)`.
  - If empty or `vocab[0] != "<blank>"`:
    - If `"<blank>"` is present at index > 0 → raise `ValueError`.
    - Otherwise prepend `"<blank>"` so `blank_id == 0` is always enforced.
  - If duplicates exist (`len(set(vocab)) != len(vocab)`) → raise `ValueError`.

### CTC Collapse Rules (`decode_tokens` / `decode`)
- Convert each element via `int(i)` (supports Python `int`, `np.int64`, 0-d `torch.Tensor`).
- Validate `0 <= idx < self.vocab_size` (raise `ValueError` if out of range).
- **When `collapse_ctc=True`**:
  1. Collapse consecutive duplicate IDs FIRST (`prev = None`; keep `idx` only if `idx != prev`; update `prev = idx`).
  2. THEN drop `idx == self.blank_id` (0).
  - Example: `[1, 1, 0, 1]` → after step 1: `[1, 0, 1]` → after step 2: `[1, 1]` (NOT `[1]`).
- **When `collapse_ctc=False`**:
  1. Drop `idx == self.blank_id` (0) without collapsing consecutive duplicates.
  - Example: `[1, 1, 0, 1]` → `[1, 1, 1]`.
- Map remaining IDs to `self.vocab[idx]` and join (`" "` for `phoneme`, `""` for `kana`/`ascii`).

### Serialization (`to_dict` / `from_dict`)
- `to_dict()` returns `{"mode": self.mode, "vocab": list(self.vocab), "blank_token": self.blank_token}` (pure JSON-compatible types).
- `Tokenizer.from_dict(d)` reconstructs `cls(mode=d["mode"], vocab=list(d["vocab"]))`.

---

## 3. Comprehensive Unit Test Plan (`tests/test_asr_dsp.py`)

Run command: `.venv/bin/pytest tests/test_asr_dsp.py -v`

1. **Package & Config (`asr/__init__.py`, `asr/config.py`)**:
   - `asr.__version__` present.
   - Exact default field values for `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig`.
   - JSON + `.to_dict()` / `.from_dict()` exact round-trip for default & custom configs.
   - Invalid config values (e.g. unknown `arch` or `method`) raise `ValueError`.
2. **Audio I/O & Resampling (`asr/audio.py`)**:
   - `save_wav` → `load_wav` 16 kHz mono round-trip (`float32`, 1D, `[-1, 1]`, max abs error < `1e-3`).
   - Stereo WAV mixdown to mono 1D `float32`.
   - 44.1 kHz → 16 kHz resampling via `load_wav(..., target_sr=16000)` and `resample()` preserves dominant FFT frequency (440 Hz ± 5 Hz) and expected length.
   - Upsampling 8 kHz → 16 kHz and identity `orig_sr == target_sr`.
   - Error handling: missing file → `FileNotFoundError`; corrupt bytes / 0-byte file → `ValueError`; `orig_sr <= 0` → `ValueError`.
3. **Energy VAD (`asr/audio.py` → `detect_vad`)**:
   - All-zero silence → `[]`; empty array → `[]`.
   - Full speech tone → 1 segment covering utterance.
   - Silence–speech–silence → 1 segment with accurate start/end bounds (accounting for hangover).
   - Two speech bursts separated by long silence → 2 ordered non-overlapping segments.
   - Two bursts separated by gap < `hangover_ms` → merged into 1 segment.
4. **Waveform Corruptions (`asr/audio.py` → `apply_corruption`)**:
   - No-op preserves signal; output always `float32`, 1D, finite.
   - White noise at `snr_db=10.0`: measured SNR within ±1.0 dB; deterministic with `seed`.
   - Pink noise at `snr_db=10.0`: measured SNR within ±1.5 dB; stronger low-freq vs high-freq energy tilt than white noise.
   - Band-pass filter `(300.0, 3400.0)` on multi-tone (100 Hz + 1000 Hz + 6000 Hz): 1000 Hz preserved, 100 Hz and 6000 Hz attenuated (>10 dB).
   - Speed perturbation (`1.25`, `0.8`): output length ≈ `len / speed`.
   - Gain (`+6 dB`, `-6 dB`): RMS scales by `10^(gain_db / 20)`.
   - Invalid `noise_type` or `speed <= 0` → `ValueError`.
5. **Features (`asr/features.py`)**:
   - `extract_log_mel`: shape `(T, n_mels)`, `float32`, finite (including on all-zeros silence and very short audio < `win_length`).
   - CMVN `True`: per-bin mean ≈ 0, std ≈ 1; CMVN `False`: louder signal has higher mean energy.
   - Frequency selectivity: 440 Hz sine peaks at lower mel bin than 3000 Hz sine.
   - Custom `AudioConfig(n_mels=80)` → `(T, 80)`.
   - `extract_mfcc`: `(T, 13)` when `include_deltas=False`, `(T, 39)` when `include_deltas=True`, base 13 dims match.
   - `spec_augment`: preserves shape/dtype, does NOT mutate input in-place, deterministic with `seed`, masks non-constant mel, handles `0` masks and small `T < time_mask_param` without crashing.
6. **Tokenizer (`asr/tokenizer.py`)**:
   - `kana` mode: `blank_id == 0`, `vocab_size == 86`, hiragana→katakana equivalence (`わたし、にほんご` == `ワタシ、ニホンゴ`), round-trip with small kana (`ョ`, `ァ`), `ッ`, `ン`, `ー`, `ヴ`, `ヂ`, `ヅ`, `ヲ`, `、`, `。`, space; empty string; unknown chars skipped cleanly.
   - `phoneme` mode: `blank_id == 0`, `vocab_size == 29`, `きょう→"k y o u"`, `しゃしん→"sh a sh i N"`, `いっしょ→"i Q sh o"`, `こーひー→"k o : h i :"`, `わたし、にほんご→"w a t a sh i pau n i h o N g o"`, phoneme-string round-trip, unknown chars do NOT emit spurious vowel.
   - `ascii` mode: `blank_id == 0`, `vocab_size == 42`, lowercase normalization, digits & apostrophe round-trip.
   - CTC collapse: `[a, a, 0, a]` with `collapse_ctc=True` → `"アア"` (NOT `"ア"`), with `collapse_ctc=False` → `"アアア"`; all-blanks → `""`; works with `np.int64` arrays.
   - `to_dict()` / `from_dict()` JSON round-trip for all 3 modes and custom vocab.
   - Custom vocab auto-prepends `<blank>` at index 0; duplicate vocab or invalid mode raises `ValueError`.
7. **Existing TTS Non-Regression**:
   - `subprocess.run([sys.executable, "yomu.py", "--help"], ...)` exits 0 and outputs expected help text.
   - `kotoba.split_moras("きょう")` == `["キョ", "ウ"]`.
