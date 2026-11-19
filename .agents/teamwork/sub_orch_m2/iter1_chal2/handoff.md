# Challenger 2 Handoff — Adversarial Audit of `asr/dataset.py`

## Scope
Adversarial verification of [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py) against `PROJECT.md` and `SCOPE.md` contracts using isolated probe scripts executed in a temporary directory (`/tmp/teamwork_probe.*`, removed after execution) via `.venv/bin/python`.

## Probe Results

| # | Adversarial Category | Checks Executed | Result |
|---|---|---|---|
| 1 | **CWD Independence & Path Resolution** | Generated dataset in `dir_A`, `os.chdir(dir_B)`, loaded `ASRManifestDataset(dir_A / "train.jsonl")`; initialized `ASRManifestDataset(Path("train.jsonl"))` in `dir_A` then `os.chdir(dir_B)` before `__getitem__`; tested absolute `audio_path` entries from an unrelated CWD | **PASS** |
| 2a | **Variable-Length Collation (`B=1`, `B=7`)** | Wildly varying utterance lengths (1 mora to ~20 moras); verified exact keys (`feats`, `feat_lengths`, `targets`, `target_lengths`, `texts`), exact dtypes (`torch.float32`, `torch.long`), exact preservation of valid slices, and exact `0.0` / blank `0` padding in padded regions | **PASS** |
| 2b | **PyTorch `DataLoader` + `nn.CTCLoss`** | Verified `DataLoader(..., collate_fn=collate_asr_batch)` with `num_workers=0` (`shuffle=True`) and `num_workers=2`; ran `Linear -> log_softmax -> nn.CTCLoss(blank=0, zero_infinity=True)` forward + backward + optimizer step with finite loss and gradients | **PASS** |
| 2c | **Augmentation & Determinism** | Verified `augment=False` is bit-exact across repeated `__getitem__` calls; `augment=True` modifies features while preserving shape/dtype/finiteness and varies across calls & `num_workers=2` workers; verified very short 480-sample (30 ms) audio under `augment=True` does not crash; verified `spec_augment_kwargs={"seed": 42}` forwarding | **PASS** |
| 2d | **`collate_asr_batch` Boundary Cases** | Empty batch `[]` (`ValueError`), 1D/3D `feats` (`ValueError`), mismatched feature dim (`ValueError`), 2D `targets` (`ValueError`), `L=0` empty targets (`targets.shape == (2, 0)`), and NumPy array inputs | **PASS** |
| 3 | **Hostile Manifest Inputs (15 cases)** | Missing file (`FileNotFoundError`), directory path (`ValueError`), 0-byte file (`ValueError`), whitespace-only file (`ValueError`), malformed JSON (`ValueError`), non-dict JSON (`ValueError`), missing/blank/non-string `audio_path` (`ValueError`), missing/null `text` (`ValueError`), missing WAV (`FileNotFoundError`), directory `audio_path` (`ValueError`), empty text (`ValueError`), OOV-only text `"🎉🔥"` encoding to `[]` (`ValueError`), corrupt WAV failing cleanly with `ValueError` on `__getitem__` | **PASS** |
| 4a | **`build_manifest_from_wav_dir` Core & Round-Trip** | Dict keyed by filename, stem, and nested relative POSIX path (`sub1/dup.wav`, `sub2/dup.wav`); uppercase `.WAV`; non-WAV files and `fake.wav/` directory ignored; unmatched WAVs and unmatched corrupt WAVs skipped; sibling output manifest dir (absolute path fallback) round-tripped into `ASRManifestDataset` from another CWD; parent output manifest dir stores relative POSIX paths | **PASS** |
| 4b | **`build_manifest_from_wav_dir` Formats & Unicode** | `.json`, `.tsv` (CRLF), JSUT `id:text`, Kaldi `id text` (with colon inside text); 44.1 kHz stereo WAV resampling + Unicode/space filename (`音声/日本語 ファイル.wav`); `kana`, `phoneme`, and `ascii` tokenizers | **PASS** |
| 4c | **`build_manifest_from_wav_dir` Error Cases** | Missing `wav_dir` (`FileNotFoundError`), file as `wav_dir` (`ValueError`), no matching WAVs (`ValueError`), empty transcript (`ValueError`), corrupt matched WAV (`ValueError`), missing/malformed transcript file (`FileNotFoundError`/`ValueError`), invalid `transcript_map` type (`TypeError`) | **PASS** |

## Minor Non-Blocking Observation
- In [`_load_transcript_map`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py#L246-L268), mapping/JSON values are coerced with `str(v)`, so a hostile JSON entry like `{"good": null}` (or Python `{"good": None}`) silently becomes the literal text `"None"` rather than raising `ValueError`. This does not violate the `Mapping[str, str]` contract and is non-blocking, but rejecting non-`str` values would be slightly stricter.

## Cleanup Verification
- Temporary probe directory `/tmp/teamwork_probe.rLeMk4` removed (`rm -rf`).
- Working tree untouched (`git diff --stat` empty).

VERDICT: CONFIRMED
