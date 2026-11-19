# Milestone M1 Challenger 2 Handoff (`iter1_chal2`)

**VERDICT: PASS**

Focus area: `asr/config.py`, `asr/tokenizer.py`, and environment/packaging (`.venv`, `pyproject.toml`, `.gitignore`, `asr/__init__.py`, TTS non-regression).

All adversarial probe scripts were staged inside a temporary directory (`mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`) and removed on exit. No working-tree files were modified.

---

## 1. `asr/config.py` Probes — PASS

- **Default values match `PROJECT.md` contracts**: Verified all defaults for `AudioConfig`, `ModelConfig`, `TrainConfig`, and `DecodeConfig`.
- **`.to_dict()` / `.from_dict()` round-trip (JSON-serialized)**:
  - Passed for all 4 config classes with both default and custom values (`AudioConfig`, `ModelConfig` with `arch="conformer_lite"`, `TrainConfig`, `DecodeConfig` with `method="greedy"`).
  - Passed empty dict `cls.from_dict({}) == cls()`.
- **Strict deserialization**:
  - Unknown keys in `.from_dict()` raise `ValueError` for all 4 classes.
  - Non-mapping inputs to `.from_dict()` raise `TypeError` for all 4 classes.
- **Invalid value rejection (`__post_init__`)**:
  - `AudioConfig`: `sample_rate <= 0`, `sample_rate=True` (bool), `n_fft=0`, `win_length > n_fft`, `hop_length=0`, `n_mels=0`, `f_min == f_max`, `f_min > f_max`, `f_min < 0`, `f_max > sample_rate / 2`, `NaN`/`Inf`, `preemphasis < 0`, `preemphasis >= 1.0`, `cmvn=1` (non-bool) — all raise `ValueError`.
  - `ModelConfig`: `arch="invalid"`, `dropout < 0`, `dropout >= 1.0`, `dropout=NaN`, even/zero `conv_kernel_size`, `conformer_lite` with `hidden_size % num_heads != 0`, `num_layers=0` — all raise `ValueError`.
  - `TrainConfig`: `epochs=0`, `batch_size=0`, `lr <= 0`, `lr=Inf`, `weight_decay < 0`, `grad_clip < 0`, blank `checkpoint_dir`, `use_spec_augment=1` — all raise `ValueError`.
  - `DecodeConfig`: `method="invalid"`, `beam_width < 1`, `temperature <= 0`, `temperature=NaN`, `lm_weight < 0`, `blank_bias=Inf` — all raise `ValueError`.

---

## 2. `asr/tokenizer.py` Probes — PASS

- **Modes & invariants**:
  - All 3 modes (`kana`, `phoneme`, `ascii`) initialize with `blank_id == 0`, `vocab[0] == "<blank>"`, and `vocab_size == len(vocab)`.
  - Invalid mode (`mode="bpe"`) raises `ValueError`.
  - Empty string encodes to `[]` and decodes to `""` in all 3 modes.
- **`kana` mode**:
  - Hiragana ↔ katakana equivalence verified: `encode("わたし") == encode("ワタシ")` (length 3), `decode(encode("わたし")) == "ワタシ"`.
  - Palatalized moras (`シャ`, `キュ`, `チョ`, `ティ`, `ヴァ`, `ゔぁ`), sokuon (`ッ`), chouon (`ー`), moraic nasal (`ン`), punctuation (`、`, `。`, ASCII space, fullwidth space `\u3000`) all round-trip cleanly with no blank IDs emitted.
  - Unknown characters (kanji, emoji, ASCII) mixed with Japanese (`"私😀helloワタシ123世界！"`) cleanly strip unknowns and return `"ワタシ"`; unknown-only input returns `[]`.
- **`phoneme` mode**:
  - Palatalized moras (`シャ -> sh a`, `キュ -> k y u`, `チョ -> ch o`, `ティ -> t i`, `ヴァ -> b a`), `ッ -> Q`, `ー -> :`, `ン -> N`, `、 -> pau`, and hiragana (`わたし -> w a t a sh i`) all encode as expected.
  - Space-separated phoneme string round-trip verified for all test cases (`encode(decode(ids)) == ids`).
  - Verified `kotoba.parse_kana` fallback quirk does **not** inject bogus vowels: unknown chars (`"漢字😀@#"`, `"ABC123"`) return `[]`, and mixed input (`"漢字😀ワタシABC"`) returns `"w a t a sh i"`.
  - *Minor note (non-blocking)*: Characters in `kotoba.PAUSE` (e.g. `!` or spaces) followed by unknown non-kana characters can emit a `pau` token because `kotoba.split_moras` converts pause punctuation to `、` and only strips trailing `、`. No bogus vowels are emitted.
- **`ascii` mode**:
  - Uppercase/lowercase normalization, digits, spaces, and punctuation (`'`, `-`, `,`, `.`) round-trip accurately; non-ASCII / unsupported punctuation are stripped cleanly.
- **CTC collapse & decoding edge cases** (verified across all 3 modes):
  - `[1, 1, 0, 1]` with `collapse_ctc=True` → two tokens (`[v1, v1]`), NOT one.
  - `[0, 0, 0]` and `[]` → `""`.
  - `[0, 1, 1, 2, 2, 0, 2, 0, 3]` with `collapse_ctc=True` → `[v1, v2, v2, v3]`.
  - `collapse_ctc=False` preserves `[1, 1]` and drops `0`.
  - `np.ndarray` (`np.int64`) input works cleanly.
  - Out-of-range IDs (`-1`, `vocab_size`, `9999`) raise `ValueError`.
- **Serialization & custom `vocab`**:
  - `to_dict()` / `Tokenizer.from_dict()` JSON round-trip matches exactly for all 3 default modes and custom vocabs.
  - Custom `vocab` with `<blank>` at index 0 (including multi-char mora `"シャ"`), without `<blank>` (auto-prepends `<blank>` at index 0), and empty `vocab=[]` (`["<blank>"]`) all work as expected.
  - `<blank>` at index != 0 and duplicate vocab tokens raise `ValueError`.
  - `Tokenizer.from_dict()` rejects non-mappings (`TypeError`) and missing required keys (`ValueError`).

---

## 3. Environment & Packaging Probes — PASS

- **Lazy `torch` import**: `import asr` completed in `79.2 ms` and `'torch' not in sys.modules`.
- **CPU-only PyTorch**: `.venv/bin/python` reports `torch.__version__ == '2.15.0+cpu'`, `torch.version.cuda is None`, `torch.cuda.is_available() == False`.
- **Existing TTS non-regression**: `python3 yomu.py --help` exited `0`; `git diff --stat` shows zero modifications to tracked TTS files.
- **`.gitignore` verification**: `git check-ignore -q` confirmed all required patterns are ignored: `.venv/`, `__pycache__/`, `foo.pyc`, `checkpoints/`, `data/`, `.pytest_cache/`.
