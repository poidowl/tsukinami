# Challenger 2 (`chal2`) Adversarial CLI Probe Report — Milestone M5 (Iteration 1)

## Verdict: `FAIL`

51 of 52 adversarial CLI checks passed, but **1 genuine bug** was discovered on corrupt checkpoint error handling: passing random/corrupt checkpoint bytes that trigger a pickle `FRAME` length overflow leaks an uncaught `OverflowError` with a full chained Python traceback to stderr instead of a clean `Error: ...` message.

---

## Failing Check & Deterministic Reproducer

### Failure: Corrupt checkpoint triggers uncaught `OverflowError` traceback (Check 4.7)
- **Observed**: When running `python -m asr eval` (or `transcribe`) with a corrupt `.pt` file containing random bytes (specifically any byte stream interpreted by legacy `torch.load` / `pickle.load` as a protocol-4 `FRAME` opcode `0x95` with an out-of-range 64-bit length), `asr/train.py:load_checkpoint` does not catch `OverflowError` (nor do `ASREngine.from_checkpoint` in `asr/inference.py` or `main()` in `asr/__main__.py`). The CLI crashes with a full chained Python traceback on stderr.
- **Deterministic Reproducer**:
  ```bash
  TMP=$(mktemp -d)
  python3 -c 'import pathlib, sys; pathlib.Path(sys.argv[1]).write_bytes(b"\x80\x04\x95\xff\xff\xff\xff\xff\xff\xff\xff" + b"\x00"*32)' "$TMP/bad.pt"
  printf '{"audio_path": "x.wav", "text": "ア"}\n' > "$TMP/m.jsonl"
  .venv/bin/python -m asr eval --checkpoint "$TMP/bad.pt" --manifest "$TMP/m.jsonl"
  rm -rf "$TMP"
  ```
- **Observed Output**:
  - Exit code: `1`
  - Stderr: Full chained `Traceback (most recent call last):` ending in `OverflowError: FRAME length exceeds system's maximum of 9223372036854775807 bytes`.
- **Root Cause**:
  1. `asr/inference.py` (`ASREngine.from_checkpoint`, line 229) calls `load_checkpoint(ckpt_path, device=device)` directly without catching non-`ValueError` unpickling/deserialization errors (such as `OverflowError`, `EOFError`, `IndexError`, `UnicodeDecodeError`, `pickle.PickleError`, `zipfile.BadZipFile`, `struct.error`) and normalizing them into `ValueError(f"Corrupt or invalid checkpoint ...")`.
  2. `asr/__main__.py` (`main()`, lines 506–516) catches `(FileNotFoundError, ValueError, TypeError, KeyError, RuntimeError, OSError, ImportError)` but not `OverflowError` (or `EOFError` / `pickle.PickleError` / `zipfile.BadZipFile` / `IndexError`). Note that `train --resume` also calls `load_checkpoint` via `train_asr`, so hardening both `ASREngine.from_checkpoint` and `asr/__main__.py:main()` covers all CLI subcommands (`eval`, `transcribe`, `train --resume`) without needing to touch M3's `asr/train.py`.

---

## Full Probe Results Summary (51/52 Passed)

### 1. `--help` & `<subcmd> --help` (7/7 PASS)
- `python -m asr --help`: PASS (`rc=0`, lists all 6 subcommands: `demo`, `generate`, `train`, `eval`, `transcribe`, `serve`).
- `demo --help`, `generate --help`, `train --help`, `eval --help`, `transcribe --help`, `serve --help`: PASS (`rc=0`, `serve --help` succeeds even though `asr/server.py` does not exist yet).

### 2. End-to-End Subprocess Flow & Pure `--json` Output (7/7 PASS)
- `generate --num-train 6 --num-val 2 --engine fast --seed 42`: PASS (`train.jsonl`, `val.jsonl`, WAVs created).
- `train --epochs 1 --batch-size 4 --hidden-size 32 --num-layers 1`: PASS (`best.pt`, `latest.pt` saved).
- `train --epochs 2 --resume <latest.pt>`: PASS (`Training complete (2 epochs)`).
- `eval --method beam --beam-width 4 --json`: PASS (stdout parses as a single pure JSON object via `json.loads`, keys include `cer`, `mer`, `wer`, `mean_rtf`, `confusion_pairs`, `samples`, `num_utterances=2`).
- `transcribe --wav <val.wav> --method greedy --json`: PASS (single pure JSON object, `source="wav"`, `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`).
- `transcribe --tts オハヨウ --engine fast --method beam --beam-width 4 --json`: PASS (single pure JSON object, `source="tts"`, `tts_engine="fast"`, `cer`, `text`).
- `transcribe --tts コンニチハ --engine tsukinami --preset robot --method greedy --json`: PASS (single pure JSON object, `source="tts"`, `tts_engine="tsukinami"`, `preset="robot"`, `cer`, `text`).

### 3. `demo` Subcommand (2/2 PASS)
- `demo --out-dir <tmp>/demo_out --epochs 2 --num-train 6 --num-val 2 --arch cnn_bigru --seed 7`: PASS (`rc=0`, `best.pt` saved in `--out-dir`, Val CER/MER and Live TTS→ASR output printed, no traceback).
- `ASREngine.from_checkpoint(<demo_out>/best.pt)` + `.transcribe(...)`: PASS (loads cleanly, `arch=cnn_bigru`, `vocab=86`).

### 4. Error Paths & Clean Non-Zero Exit Codes (35/36 PASS, 1 FAIL)
- Missing WAV, corrupt WAV (random bytes, truncated header, 0-byte): 4/4 PASS (`rc=1`, clean `Error: ...`, no traceback).
- Missing checkpoint (`eval`, `transcribe`, `serve`), 0-byte checkpoint, pickle non-dict, pickle missing keys, directory as checkpoint: 6/6 PASS.
- **Corrupt checkpoint (random bytes / pickle FRAME overflow)**: **FAIL** (`rc=1`, **uncaught `OverflowError` traceback**).
- Missing manifest (`eval`, `train`), empty manifest, corrupt JSONL manifest, manifest referencing missing WAV: 5/5 PASS.
- Mutually exclusive `--wav` & `--tts` (both provided, neither provided): 2/2 PASS (`rc=2`, argparse error).
- Invalid `--arch` (`train`, `demo`), invalid `--method` (`eval`, `transcribe`), invalid `--engine` (`generate`, `transcribe`), invalid `--preset` (`transcribe tsukinami`): 7/7 PASS.
- Out-of-bounds numerics (`--epochs 0`, `--epochs -3`, `--beam-width 0`, `--beam-width -2`, `--num-train 0`, `--lr -0.01`, `--lr nan`, `--port 0`): 8/8 PASS.
- `serve` with missing `asr.server` (both with valid `--checkpoint` and without `--checkpoint`): 2/2 PASS (`rc=1`, clean `Error: Web server module \`asr.server\` is not available: No module named 'asr.server'`, no traceback).

## Cleanup Verification
- Temporary probe directory removed (`NO_TEMP_PROBE_DIRS`).
- Repository working tree untouched.
