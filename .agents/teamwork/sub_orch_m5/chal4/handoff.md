# Challenger 4 (`chal4`) Handoff — Milestone M5 (Iteration 2)

## Verdict: **CONFIRMED**

All **51 / 51** adversarial CLI subprocess probes against `.venv/bin/python -m asr` passed with zero failures, zero uncaught tracebacks, and clean error reporting. The Iteration 2 corrupt-checkpoint fix in `asr/inference.py` (`ASREngine.from_checkpoint`) and `asr/__main__.py` (`main`) is verified across all CLI subcommands.

---

## Probe Environment & Hygiene
- **Command under test**: `/home/antigravity/poidowl/tsukinami/.venv/bin/python -m asr <subcommand>` (subprocess, `cwd=/home/antigravity/poidowl/tsukinami`)
- **Staging**: Temporary directory created with `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and removed automatically on exit (`NO_STRAY_PROBE_DIRS` verified).
- **Working tree**: Read-only — zero source, test, or repo files modified.

---

## Detailed Probe Results (51 / 51 Passed)

### 1. Corrupt Pickle-FRAME Checkpoint Regression (`3 / 3` PASS)
Payload: `b"\x80\x04\x95\xff\xff\xff\xff\xff\xff\xff\xff" + b"\x00" * 32`
- `eval --checkpoint <corrupt> --manifest <val>` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `transcribe --checkpoint <corrupt> --wav <wav>` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `train --resume <corrupt>` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)

### 2. Additional Corrupt / Invalid Checkpoint Payloads (`30 / 30` PASS)
Each payload tested against `eval`, `transcribe --wav`, and `train --resume` (asserting `rc=1`, `Error:` in stderr, and zero `Traceback`):
| Payload | `eval` | `transcribe --wav` | `train --resume` |
|---|---|---|---|
| `empty_0b` (0-byte file) | PASS | PASS | PASS |
| `random_bytes` (256 random bytes) | PASS | PASS | PASS |
| `truncated_zip` (`PK\x03\x04...` truncated) | PASS | PASS | PASS |
| `bad_zip_data_pkl` (valid ZIP with corrupt `archive/data.pkl`) | PASS | PASS | PASS |
| `non_dict_pickle` (`pickle.dumps([1, 2, 3, "not_a_dict"])`) | PASS | PASS | PASS |
| `empty_dict_pickle` (`pickle.dumps({})`) | PASS | PASS | PASS |
| `invalid_utf8_pickle` (`b"\x80\x04\x8c\x04\xff\xfe\xfd\xfc."`) | PASS | PASS | PASS |
| `empty_stack_pickle` (`b"\x80\x020."`) | PASS | PASS | PASS |
| `dir_as_ckpt` (directory passed as checkpoint path) | PASS | PASS | PASS |
| `missing_ckpt` (non-existent path) | PASS | PASS | PASS |

### 3. Additional Error-Handling Probes (`3 / 3` PASS)
- `transcribe --checkpoint <valid> --wav <corrupt_wav>` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `eval --beam-width 0` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `train --lr -0.01` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)

### 4. Subprocess Smoke Checks (`15 / 15` PASS)
- `--help` → **PASS** (`rc=0`, lists `demo`, `generate`, `train`, `eval`, `transcribe`, `serve`)
- `serve --help` → **PASS** (`rc=0`, works cleanly without `asr.server`)
- `generate --num-train 6 --num-val 3 --engine fast` → **PASS** (`rc=0`, writes `train.jsonl` & `val.jsonl`)
- `train --epochs 1 --batch-size 4 --hidden-size 32 --num-layers 1` → **PASS** (`rc=0`, writes `best.pt` & `latest.pt`)
- `train --epochs 2 --resume <latest.pt>` → **PASS** (`rc=0`)
- `eval --method beam --beam-width 4 --json` → **PASS** (`rc=0`, valid JSON with `manifest`, `num_utterances=3`, `cer`, `mer`, `wer`, `mean_rtf`, `samples`, `checkpoint`)
- `eval --method greedy` (human-readable text) → **PASS** (`rc=0`, prints `CER:` and `MER:`)
- `transcribe --wav <wav> --method greedy --json` → **PASS** (`rc=0`, valid JSON with `source="wav"`, `text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`)
- `transcribe --tts オハヨウ --engine fast --method beam --beam-width 4 --json` → **PASS** (`rc=0`, valid JSON with `source="tts"`, `tts_engine="fast"`, `cer`, `reference_text`)
- `transcribe --tts コンニチハ --engine tsukinami --preset default --method greedy --json` → **PASS** (`rc=0`, valid JSON with `source="tts"`, `tts_engine="tsukinami"`, `cer`)
- `demo --epochs 1 --num-train 6 --num-val 2` → **PASS** (`rc=0`, creates `best.pt` and outputs `[1/4]`–`[4/4]`)
- `serve` (missing `asr.server` in M5) → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `serve --checkpoint <best.pt>` (missing `asr.server`) → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `serve --port 0` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
- `serve --checkpoint <missing>` → **PASS** (`rc=1`, `Error:` on stderr, no `Traceback`)
