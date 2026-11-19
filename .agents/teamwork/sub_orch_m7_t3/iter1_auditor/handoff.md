# Forensic Anti-Cheating Audit Report — M7 Phase 1 (Tier 3 E2E)

- **Audit Classification**: Intermediate Milestone Audit (M7 Phase 1 — Tier 3 E2E)
- **Verdict**: **`CLEAN`**
- **Audited Sub-Scope Paths**:
  - `asr/`
  - `tests/`
  - `tests_e2e/conftest.py`
  - `tests_e2e/test_tier1_features.py`
  - `tests_e2e/test_tier2_boundaries.py`
  - `tests_e2e/test_tier3_combinations.py`

---

## 1. Target-Scoped Unit Test Verification

Command:
```bash
.venv/bin/pytest tests/ -v
```

Output (exit code `0`):
```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.2.0, pluggy-1.7.0
rootdir: /home/antigravity/poidowl/tsukinami
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 154 items

tests/test_asr_cli.py ................                                   [ 10%]
tests/test_asr_data.py ....................                              [ 23%]
tests/test_asr_decoding.py ......................................        [ 48%]
tests/test_asr_dsp.py .............................................      [ 77%]
tests/test_asr_models.py .................                               [ 88%]
tests/test_asr_web.py ..................                                 [ 100%]

=============================== warnings summary ===============================
.venv/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

tests/test_asr_cli.py::test_corrupt_pickle_frame_checkpoint
  /home/antigravity/poidowl/tsukinami/.venv/lib/python3.11/site-packages/torch/_weights_only_unpickler.py:604: UserWarning: Detected pickle protocol 4 in the checkpoint, which was not the default pickle protocol used by `torch.load` (2). The weights_only Unpickler might not support all instructions implemented by this protocol, please file an issue for adding support if you encounter this.
    return Unpickler(file, encoding=encoding).load()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 154 passed, 2 warnings in 181.22s (0:03:01) ==================
```

- **Result**: **154/154 PASSED** (0 failed, 0 skipped, 0 xfailed).
- *(Note: `tests_e2e/` was NOT run by this auditor to avoid concurrent execution with Primary Reviewer, per audit rules.)*

---

## 2. Repository Integrity (`git status --short` & `git diff`)

Command:
```bash
git status --short && echo "---GIT DIFF---" && git diff && echo "---GIT DIFF STAT---" && git diff --stat
```

Output (exit code `0`):
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
---GIT DIFF---
---GIT DIFF STAT---
```

- **Finding**: **ZERO tracked files modified**. All existing `tsukinami` TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.) remain completely untouched.

---

## 3. E2E Test Suite Integrity Audit (`tests_e2e/`)

### 3.1 Skip / Xfail / Mock Scan
Command:
```bash
grep -rnE "pytest\.skip|pytest\.xfail|mark\.skip|mark\.xfail|unittest\.mock|MagicMock|monkeypatch|@patch|mock\.patch" tests_e2e/ || echo "ZERO matches in tests_e2e/"
```
Output:
```text
ZERO matches in tests_e2e/
```

### 3.2 AST Assertion Audit (Tiers 1–3)
Command:
```bash
.venv/bin/python -c '
import ast, pathlib
for p in sorted(pathlib.Path("tests_e2e").glob("test_tier[123]*.py")):
    tree = ast.parse(p.read_text(encoding="utf-8"))
    tests = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    no_assert = []
    assert_true = []
    for fn in tests:
        asserts = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
        raises = [n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr == "raises"]
        if not asserts and not raises:
            no_assert.append(fn.name)
        for a in asserts:
            if isinstance(a.test, ast.Constant) and a.test.value is True:
                assert_true.append(fn.name)
    print(f"{p}: {len(tests)} tests, no_assert={no_assert}, assert_true={assert_true}")
'
```
Output:
```text
tests_e2e/test_tier1_features.py: 103 tests, no_assert=[], assert_true=[]
tests_e2e/test_tier2_boundaries.py: 98 tests, no_assert=[], assert_true=[]
tests_e2e/test_tier3_combinations.py: 12 tests, no_assert=[], assert_true=[]
```

### 3.3 Manual Forensic Review of `tests_e2e/test_tier3_combinations.py` & `tests_e2e/conftest.py`
- `tests_e2e/conftest.py` (375 lines): Independent pure-stdlib/NumPy synthetic signal/WAV/log-prob helpers (`make_sine`, `make_speech_like`, `write_pcm_wav`, `write_corrupt_wav`, `make_synthetic_log_probs`) and session-scoped real fixtures (`tiny_fast_dataset`, `tiny_checkpoint`, `tiny_engine`, `api_client`, `run_cli`). Zero mocking, zero stubbing.
- `tests_e2e/test_tier3_combinations.py` (446 lines, 12 tests): Genuine opaque-box cross-feature tests covering DSP/corruption/VAD, speed/band-limit/gain/CMVN invariants, fast-kotoba + kana/phoneme tokenizers + dataset/collate + SpecAugment, authentic `tsukinami` preset synthesis + disk cache + WAV round-trip, `cnn_bigru` & `conformer_lite` training/checkpoint/resume/forward, Greedy/Beam/CharNgramLM/Viterbi alignment, mora boundary error + CER/MER/WER/confusion pairs, `ASREngine` visuals + cached `redecode`, full CLI subprocess pipeline (`generate` → `train` → `eval` → `transcribe --wav`/`--tts`), and FastAPI `/api/info` → `/api/tts-roundtrip` → `/api/redecode` → zero-CDN `/` HTML.

---

## 4. Implementation Integrity Audit (`asr/`)

### 4.1 Suspicious Marker / Hardcoding Scan
Command:
```bash
grep -rnE "NotImplementedError|TODO|FIXME|HACK|pytest|tests_e2e|test_t3_|test_t2_|test_t1_|ワタシ、ニホンコ|hello earth" asr/ || echo "ZERO suspicious markers in asr/"
```
Output:
```text
ZERO suspicious markers in asr/
```

### 4.2 Zero-CDN Web Playground Scan
Command:
```bash
grep -rnE "https?://|//cdn|unpkg|jsdelivr|cdnjs|googleapis" asr/web/index.html || echo "ZERO external CDN/URLs in asr/web/index.html"
```
Output:
```text
ZERO external CDN/URLs in asr/web/index.html
```

### 4.3 Source Inspection Summary
Directly inspected core `asr/` modules (total 8,428 lines across `asr/*.py`, `asr/models/*.py`, `asr/web/index.html`):
- **DSP & Features** (`asr/features.py`): Pure-NumPy pre-emphasis, Hann-windowed STFT (`np.fft.rfft`), Slaney Mel filterbank, Log-Mel with per-utterance CMVN, DCT-II MFCC + delta/delta-delta, and seeded SpecAugment.
- **Neural Acoustic Models** (`asr/models/cnn_bigru.py`, `asr/models/conformer.py`): Genuine PyTorch `Conv2dSubsampling` (4× stride), `CNNBiGRUCTC` with `pack_padded_sequence`/`pad_packed_sequence` + `LayerNorm` + `log_softmax`, and `ConformerLiteCTC` with non-persistent `SinusoidalPositionalEncoding`, Macaron FFN, masked `MultiheadAttention`, and depthwise-separable `_ConformerConvModule`.
- **Training & Checkpointing** (`asr/train.py`): Genuine `nn.CTCLoss`, `AdamW`, deterministic seeding, `_SeededSpecAugmentDataset`, atomic `.pt` checkpoint saving, validation CER computation via `greedy_decode`, and resume support.
- **CTC Decoding, LM, Alignment & Metrics** (`asr/decoding.py`, `asr/metrics.py`): Pure-NumPy/Python log-space `CharNgramLM` with add-k hierarchical backoff, `greedy_decode`, `prefix_beam_search`, `viterbi_align`, and dynamic-programming `levenshtein_align` backing `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`, and `alignment_boundary_error`.
- **Inference Engine & Server** (`asr/inference.py`, `asr/server.py`, `asr/synth_data.py`): Genuine `ASREngine` with real model forward pass, LRU cache for `<10 ms` `redecode`, visual payloads, FastAPI endpoints, and genuine `kotoba`/authentic `tsukinami` synthesis.

---

## 5. Final Verdict

**VERDICT: `CLEAN`**

- Zero cheating, zero hardcoded test outputs, zero dummy/facade implementations.
- Zero `pytest.skip`, zero `pytest.xfail`, zero weakened assertions, zero mocking in `tests_e2e/`.
- Zero existing `tsukinami` TTS files modified (`git diff` is empty).
- All 154/154 unit tests in `tests/` pass cleanly.
