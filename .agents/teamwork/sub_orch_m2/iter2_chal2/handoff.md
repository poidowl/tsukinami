# M2 Iteration 2 Challenger 2 Handoff (`asr/dataset.py`)

## Scope & Method
Ran isolated adversarial probes against [`asr/dataset.py`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py) using `.venv/bin/python` from temporary directories created with `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` (cleaned up via `trap 'rm -rf "$PROBE_DIR"' EXIT` and verified removed). The working tree was not modified.

## Checks Executed

1. **`_load_transcript_map` strict non-`str` rejection & format support** — **PASS**
   - Python `dict` and `MappingProxyType` with non-`str` values (`None`, `123`, `3.14`, `True`, `False`, `["a"]`, `{"a": 1}`, `b"bytes"`, `(1, 2)`), including mixed valid/invalid mappings, all raise `ValueError`.
   - `.json` (and uppercase `.JSON`) files with non-`str` values (`null`, `123`, `1.5`, `true`, `false`, `["a"]`, `{"a": 1}`), non-object top-level JSON (`list`, `str`, `null`), and malformed JSON all raise `ValueError`.
   - Valid `dict`, `MappingProxyType`, `.json`/`.JSON`, `.tsv` (with blank lines, spaces, and colons in text), JSUT `id:text` (with colons and spaces in text), and Kaldi `id text` (with multiple spaces and colons in text) all parse cleanly both directly and end-to-end through [`build_manifest_from_wav_dir`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py#L306-L374).
   - Invalid input types (`123`, `None`) raise `TypeError`; missing file raises `FileNotFoundError`; directory or unparseable single-token line raises `ValueError`.

2. **CWD independence & `build_manifest_from_wav_dir` key resolution** — **PASS**
   - Verified key priority (`rel_posix` > `filename` > `stem`) and uppercase `.WAV` discovery.
   - Verified relative `audio_path` storage when manifest is inside `wav_dir` and absolute `audio_path` storage when manifest is outside `wav_dir`.
   - Verified loading both manifests after `os.chdir("/tmp")`, as well as constructing [`ASRManifestDataset`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py#L89-L174) from a relative manifest path and then `os.chdir("/tmp")` before calling `__getitem__` (audio paths are eagerly resolved to absolute paths in `__init__`).

3. **`ASRManifestDataset` (`augment=True/False`), `collate_asr_batch`, `DataLoader` + `nn.CTCLoss`** — **PASS**
   - `augment=False` is deterministic (`torch.equal` across repeated reads); `augment=True` modifies features while preserving `[T, F]` `float32` finite tensors, and supports deterministic `spec_augment_kwargs={"seed": ...}`.
   - [`collate_asr_batch`](file:///home/antigravity/poidowl/tsukinami/asr/dataset.py#L177-L243) produces `feats` (`float32 [B, T_max, F]`), `feat_lengths` (`int64 [B]`), `targets` (`int64 [B, L_max]`), `target_lengths` (`int64 [B]`), and `texts` (`list[str]`), with exact zero-padding beyond true lengths.
   - Verified `DataLoader` with both `num_workers=0` (`Tokenizer("kana")`, `n_mels=64`) and `num_workers=2` (`Tokenizer("phoneme")`, `n_mels=80`) feeding `nn.Linear` + `nn.CTCLoss(blank=0, zero_infinity=True)` forward & `.backward()` with finite loss and non-zero finite gradients.
   - Verified hostile `collate_asr_batch` inputs (empty batch, 1D/3D feats, feature-dim mismatch, 2D targets) all raise `ValueError`.

4. **Hostile manifest & WAV error handling** — **PASS**
   - Verified `load_manifest` / `ASRManifestDataset` / `build_manifest_from_wav_dir` error handling for: missing files (`FileNotFoundError`), directories (`ValueError`), empty/whitespace-only manifests (`ValueError` in `ASRManifestDataset`), malformed JSONL, non-dict JSONL lines, invalid/empty `audio_path` and non-string `text`, non-UTF-8 manifest bytes (`UnicodeDecodeError` / `ValueError`), missing or directory `audio_path` with `validate_files=True`, corrupt WAV bytes (`ValueError` in `__getitem__` and `build_manifest_from_wav_dir`), and empty encoded targets (`""`, `"12345"` raise `ValueError` when `allow_empty_targets=False` and succeed when `allow_empty_targets=True`).

VERDICT: CONFIRMED
