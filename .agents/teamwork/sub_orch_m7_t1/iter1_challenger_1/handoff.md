# Challenger 1 Handoff — M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`, Iteration 1)

## 1. Scope & Target Modules Audited
Isolated adversarial probes targeting the manifest & dataset pipeline after Iteration 1's absolute `audio_path` changes:
- `asr/synth_data.py` (`generate_dataset`)
- `asr/dataset.py` (`build_manifest_from_wav_dir`, `ASRManifestDataset`, `_resolve_audio_path`, `load_manifest`, `collate_asr_batch`)
- `asr/__main__.py` (`python -m asr generate`, `_resolve_manifest_audio_path`)

All scratch probes were staged inside an isolated temporary directory (`mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"`, resolved to `/tmp/teamwork_probe.yS4YYt`), executed with `/home/antigravity/poidowl/tsukinami/.venv/bin/python`, and completely removed (`rm -rf`) prior to reporting (`CLEANUP_CHECK: exists=no`). No working tree files were modified and `tests_e2e/` was not invoked.

---

## 2. Adversarial Probe Design Summary

1. **Probe 1 (`generate_dataset` with relative `out_dir` + CWD change)**:
   - Switched CWD to `<probe_dir>/probe1_cwd`, called `generate_dataset(Path("nested_rel/out_ds"), num_train=4, num_val=2, engine="fast", seed=77)`.
   - Verified returned `manifests["train"]` and `manifests["val"]` are absolute paths.
   - Switched CWD to a completely unrelated directory (`<probe_dir>/completely_unrelated_cwd`), loaded both manifests, asserted every `audio_path` is absolute and exists, verified `load_wav` and `ASRManifestDataset` + `collate_asr_batch`.
2. **Probe 1b (CLI `python -m asr generate` with relative `--out-dir`)**:
   - Invoked `.venv/bin/python -m asr generate --out-dir rel_cli_ds --num-train 2 --num-val 1 --seed 99` from `<probe_dir>/probe1b_cli_cwd`.
   - Verified exit code `0` and that all emitted `audio_path` entries in `train.jsonl` are absolute and exist on disk.
3. **Probe 2 (`generate_dataset` with spaces and Japanese Unicode characters)**:
   - Called `generate_dataset(Path("日本語 dir/テスト 音声　データ"), num_train=3, num_val=2, engine="fast", seed=55)` (containing ASCII space, full-width space `　`, and Japanese kanji/katakana).
   - Switched CWD to `OTHER_CWD`, verified all emitted `audio_path` entries are absolute, preserve the Unicode/space path, exist, and load cleanly through `load_wav` and `ASRManifestDataset`.
4. **Probe 3 (`build_manifest_from_wav_dir` with relative `wav_dir`, symlinks, nested subdirs, broken symlink, Unicode/spaces)**:
   - Built a directory tree under `rel_wavs/音声 dir` containing:
     - `root_utt.wav` (root level, matched by stem)
     - `nested/deep/sub_utt.wav` (nested subdir, matched by relative POSIX path)
     - `nested/linked_utt.wav` (symlink pointing outside `wav_dir` to `external_targets/real_external.wav`, matched by filename)
     - `broken.wav` (dangling symlink pointing to nonexistent file)
   - Called `build_manifest_from_wav_dir(Path("rel_wavs/音声 dir"), tmap, Path("manifests/custom.jsonl"))` from `probe3_cwd`, then switched to `OTHER_CWD`.
   - Verified broken symlink was skipped cleanly (3 valid records), all emitted `audio_path` entries are absolute and canonicalized (`not ap.is_symlink()`), the symlinked WAV resolved to `external_targets/real_external.wav`, and all 3 entries load cleanly via `load_wav` and `ASRManifestDataset`.
5. **Probe 4 (`ASRManifestDataset` & `asr/__main__._resolve_manifest_audio_path` backward compatibility with mixed manifests)**:
   - Hand-crafted `mixed.jsonl` containing both a manifest-relative path (`clips/a.wav`) and an absolute path (`/tmp/.../probe4_abs_clips/b.wav`).
   - Instantiated `ASRManifestDataset` across 3 CWD / manifest-path combinations (`CWD=manifest_dir` with relative manifest, `CWD=OTHER_CWD` with absolute manifest, `CWD=BASE` with relative manifest), then switched CWD to `OTHER_CWD` *after* `__init__` and *before* `__getitem__` to verify eager path resolution.
   - Also verified `asr.__main__._resolve_manifest_audio_path` resolves both entries identically.
6. **Probe 5 (Cross-directory determinism of `generate_dataset(..., seed=123)`)**:
   - Generated datasets for both `engine="fast"` and `engine="mixed"` (covering `kotoba_fast` and `tsukinami` TTS records) across two differently named directories (`det_<eng>_alpha` vs `det_<eng>_日本語 beta`).
   - Verified identical record counts, distinct absolute `audio_path` values, identical relative suffixes, identical non-path metadata (`text`, `duration`, `speaker`, `source`, `moras`), and byte-for-byte identical WAV files across all train & val utterances.

---

## 3. Exact Probe Execution Output

- **Exit Code**: `0`
- **Temp Dir Cleanup**: `CLEANUP_CHECK: exists=no`

```text
PROBE_DIR=/tmp/teamwork_probe.yS4YYt

=== PROBE 1: generate_dataset with relative out_dir + CWD change ===
  [PASS] returned train manifest path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/train.jsonl
  [PASS] returned val manifest path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/val.jsonl
  [PASS] train record count == 4
  [PASS] train[0] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/audio/train/train_00000.wav
  [PASS] train[0] audio_path exists from OTHER_CWD
  [PASS] train[0] load_wav ok (len=11040)
  [PASS] train[1] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/audio/train/train_00001.wav
  [PASS] train[1] audio_path exists from OTHER_CWD
  [PASS] train[1] load_wav ok (len=36160)
  [PASS] train[2] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/audio/train/train_00002.wav
  [PASS] train[2] audio_path exists from OTHER_CWD
  [PASS] train[2] load_wav ok (len=13120)
  [PASS] train[3] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/audio/train/train_00003.wav
  [PASS] train[3] audio_path exists from OTHER_CWD
  [PASS] train[3] load_wav ok (len=14080)
  [PASS] train ASRManifestDataset + collate ok from OTHER_CWD
  [PASS] val record count == 2
  [PASS] val[0] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/audio/val/val_00000.wav
  [PASS] val[0] audio_path exists from OTHER_CWD
  [PASS] val[0] load_wav ok (len=22080)
  [PASS] val[1] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe1_cwd/nested_rel/out_ds/audio/val/val_00001.wav
  [PASS] val[1] audio_path exists from OTHER_CWD
  [PASS] val[1] load_wav ok (len=14800)
  [PASS] val ASRManifestDataset + collate ok from OTHER_CWD

=== PROBE 1b: CLI `python -m asr generate` with relative --out-dir ===
  [PASS] CLI generate exit code == 0 (stderr='')
  [PASS] CLI train.jsonl exists at /tmp/teamwork_probe.yS4YYt/probe1b_cli_cwd/rel_cli_ds/train.jsonl
  [PASS] CLI emitted absolute existing audio_paths: ['/tmp/teamwork_probe.yS4YYt/probe1b_cli_cwd/rel_cli_ds/audio/train/train_00000.wav', '/tmp/teamwork_probe.yS4YYt/probe1b_cli_cwd/rel_cli_ds/audio/train/train_00001.wav']

=== PROBE 2: generate_dataset with spaces & Japanese Unicode dir ===
  [PASS] Unicode train[0] absolute & exists: /tmp/teamwork_probe.yS4YYt/probe2_cwd/日本語 dir/テスト 音声　データ/audio/train/train_00000.wav
  [PASS] Unicode train[0] preserves Japanese/space path
  [PASS] Unicode train[0] load_wav ok
  [PASS] Unicode train[1] absolute & exists: /tmp/teamwork_probe.yS4YYt/probe2_cwd/日本語 dir/テスト 音声　データ/audio/train/train_00001.wav
  [PASS] Unicode train[1] preserves Japanese/space path
  [PASS] Unicode train[1] load_wav ok
  [PASS] Unicode train[2] absolute & exists: /tmp/teamwork_probe.yS4YYt/probe2_cwd/日本語 dir/テスト 音声　データ/audio/train/train_00002.wav
  [PASS] Unicode train[2] preserves Japanese/space path
  [PASS] Unicode train[2] load_wav ok
  [PASS] Unicode train ASRManifestDataset[0] ok
  [PASS] Unicode val[0] absolute & exists: /tmp/teamwork_probe.yS4YYt/probe2_cwd/日本語 dir/テスト 音声　データ/audio/val/val_00000.wav
  [PASS] Unicode val[0] preserves Japanese/space path
  [PASS] Unicode val[0] load_wav ok
  [PASS] Unicode val[1] absolute & exists: /tmp/teamwork_probe.yS4YYt/probe2_cwd/日本語 dir/テスト 音声　データ/audio/val/val_00001.wav
  [PASS] Unicode val[1] preserves Japanese/space path
  [PASS] Unicode val[1] load_wav ok
  [PASS] Unicode val ASRManifestDataset[0] ok

=== PROBE 3: build_manifest_from_wav_dir (rel wav_dir, symlinks, nested subdirs) ===
  [PASS] matched 3 valid wavs (broken symlink skipped), got 3
  [PASS] texts match: {'コンニチハ', 'オハヨウ', 'アリガトウ'}
  [PASS] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe3_cwd/rel_wavs/音声 dir/nested/deep/sub_utt.wav
  [PASS] audio_path is resolved (not a symlink): /tmp/teamwork_probe.yS4YYt/probe3_cwd/rel_wavs/音声 dir/nested/deep/sub_utt.wav
  [PASS] audio_path exists from OTHER_CWD: /tmp/teamwork_probe.yS4YYt/probe3_cwd/rel_wavs/音声 dir/nested/deep/sub_utt.wav
  [PASS] load_wav ok for sub_utt.wav
  [PASS] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/external_targets/real_external.wav
  [PASS] audio_path is resolved (not a symlink): /tmp/teamwork_probe.yS4YYt/external_targets/real_external.wav
  [PASS] audio_path exists from OTHER_CWD: /tmp/teamwork_probe.yS4YYt/external_targets/real_external.wav
  [PASS] load_wav ok for real_external.wav
  [PASS] audio_path is absolute: /tmp/teamwork_probe.yS4YYt/probe3_cwd/rel_wavs/音声 dir/root_utt.wav
  [PASS] audio_path is resolved (not a symlink): /tmp/teamwork_probe.yS4YYt/probe3_cwd/rel_wavs/音声 dir/root_utt.wav
  [PASS] audio_path exists from OTHER_CWD: /tmp/teamwork_probe.yS4YYt/probe3_cwd/rel_wavs/音声 dir/root_utt.wav
  [PASS] load_wav ok for root_utt.wav
  [PASS] symlink resolved to canonical target: /tmp/teamwork_probe.yS4YYt/external_targets/real_external.wav == /tmp/teamwork_probe.yS4YYt/external_targets/real_external.wav
  [PASS] ASRManifestDataset loaded 3 items from OTHER_CWD
  [PASS] ASRManifestDataset[0] ok
  [PASS] ASRManifestDataset[1] ok
  [PASS] ASRManifestDataset[2] ok

=== PROBE 4: Mixed manifest-relative & absolute audio_path backward compat ===
  [PASS] [CWD=manifest_dir, rel manifest] len(ds) == 2
  [PASS] [CWD=manifest_dir, rel manifest] rel entry loaded & resolved: /tmp/teamwork_probe.yS4YYt/probe4_mixed/clips/a.wav
  [PASS] [CWD=manifest_dir, rel manifest] abs entry loaded & resolved: /tmp/teamwork_probe.yS4YYt/probe4_abs_clips/b.wav
  [PASS] [CWD=manifest_dir, rel manifest] __main__._resolve_manifest_audio_path handles both
  [PASS] [CWD=OTHER_CWD, abs manifest] len(ds) == 2
  [PASS] [CWD=OTHER_CWD, abs manifest] rel entry loaded & resolved: /tmp/teamwork_probe.yS4YYt/probe4_mixed/clips/a.wav
  [PASS] [CWD=OTHER_CWD, abs manifest] abs entry loaded & resolved: /tmp/teamwork_probe.yS4YYt/probe4_abs_clips/b.wav
  [PASS] [CWD=OTHER_CWD, abs manifest] __main__._resolve_manifest_audio_path handles both
  [PASS] [CWD=BASE, rel manifest] len(ds) == 2
  [PASS] [CWD=BASE, rel manifest] rel entry loaded & resolved: /tmp/teamwork_probe.yS4YYt/probe4_mixed/clips/a.wav
  [PASS] [CWD=BASE, rel manifest] abs entry loaded & resolved: /tmp/teamwork_probe.yS4YYt/probe4_abs_clips/b.wav
  [PASS] [CWD=BASE, rel manifest] __main__._resolve_manifest_audio_path handles both

=== PROBE 5: Cross-directory determinism (seed=123) ===
  [PASS] [fast/train] same record count (4)
  [PASS] [fast/train][0..3] both absolute, distinct paths, identical relative suffixes, identical metadata, byte-identical WAVs (92044, 24684, 33164, 73964 bytes)
  [PASS] [fast/val] same record count (2)
  [PASS] [fast/val][0..1] both absolute, distinct paths, identical relative suffixes, identical metadata, byte-identical WAVs (21164, 59084 bytes)
  [PASS] [mixed/train] same record count (4)
  [PASS] [mixed/train][0..3] both absolute, distinct paths, identical relative suffixes, identical metadata, byte-identical WAVs (76524, 22604, 53004, 59724 bytes)
  [PASS] [mixed/val] same record count (2)
  [PASS] [mixed/val][0..1] both absolute, distinct paths, identical relative suffixes, identical metadata, byte-identical WAVs (47404, 27244 bytes)

=== SUMMARY ===
TOTAL FAILURES: 0
ALL PROBES PASSED
CLEANUP_CHECK: exists=no
```

---

## 4. Findings & Verdict

No bugs, edge-case failures, or contract violations were found across any of the 5 adversarial probe suites (including CLI `generate`, Unicode/space paths, symlinks/broken symlinks, mixed relative+absolute backward compatibility across CWD shifts, and cross-directory `fast`/`mixed` determinism).

**Verdict: PASS**
