# Challenger 2 Handoff — M7 Phase 1: Tier 1 E2E (`sub_orch_m7_t1`, Iteration 1)

## Verdict: PASS

All 4 isolated adversarial probe suites across Tier 1 core contracts and cross-module handoffs confirmed correctness with zero implementation bugs, contract violations, or regressions. All temporary probe directories were staged via `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and removed via `trap 'rm -rf "$PROBE_DIR"' EXIT` (verified non-existent after execution). The repository working tree was not modified.

---

## Probe Script Summary & Coverage

1. **Probe 1 — End-to-End Mini-Pipeline from Temp Dir**
   - Invoked `generate_dataset` with **relative** `out_dir` for both `engine="fast"` and `engine="mixed"` from `work_a`, then `os.chdir(work_b)`.
   - Verified every manifest row in `train.jsonl` and `val.jsonl` emits an **absolute** `audio_path` and loads directly via `load_wav(row["audio_path"])` from `work_b` without joining `manifest.parent`.
   - Verified `build_manifest_from_wav_dir` with relative `wav_dir` emits absolute `audio_path` loadable directly by `load_wav()` from `work_b`.
   - Verified backward compatibility: a hand-crafted manifest with relative `audio_path` (`audio/a.wav`) still loads via `ASRManifestDataset` from another CWD.
   - Ran `ASRManifestDataset` -> `collate_asr_batch` -> `build_model("cnn_bigru")` and `build_model("conformer_lite")` forward passes -> `greedy_decode`, `prefix_beam_search` (with & without `CharNgramLM`), and `viterbi_align`. Verified shapes, `exp(log_probs).sum(-1) == 1`, `subsampling_factor == 4`, `output_frame_stride_ms == 40.0`, monotonic alignment timestamps, and valid `[0, 1]` confidences.

2. **Probe 2 — CLI `asr eval` & `asr transcribe` from a Different Working Directory**
   - Trained a 1-epoch tiny `cnn_bigru` checkpoint via `train_asr` in the temp dir.
   - From a completely separate working directory (`completely_different_cwd`), ran subprocess invocations:
     - `.venv/bin/python -m asr eval --checkpoint <ckpt> --manifest <val.jsonl> --method greedy --json`
     - `.venv/bin/python -m asr eval --checkpoint <ckpt> --manifest <val.jsonl> --method beam --beam-width 4 --json`
     - `.venv/bin/python -m asr transcribe --checkpoint <ckpt> --wav <row["audio_path"]> --method greedy --json`
     - `.venv/bin/python -m asr transcribe --checkpoint <ckpt> --tts コンニチハ --method greedy --json`
   - All exited `0` with valid JSON matching expected schema.

3. **Probe 3 — Tricky Inputs across DSP, VAD, Corruptions, Tokenizer, LM, Metrics**
   - `extract_log_mel` and `extract_mfcc` (with & without deltas): 1-sample, 10-sample, 160-sample, 399-sample, 400-sample clips, 1s pure silence, and constant DC offset (`0.5`) — all returned finite `float32` tensors with expected shapes.
   - `detect_vad`: pure silence (`[]`), 3-sample clip, and speech burst surrounded by silence (`[(0.24, 0.92)]`).
   - `apply_corruption`: white & pink noise on pure silence (no NaN/Inf), plus combined noise + band-limit `(300, 3400)` + speed `1.15` + gain `-3 dB` determinism with `seed=42`.
   - `Tokenizer` (`kana`, `phoneme`, `ascii`): `blank_id == 0`, `to_dict()`/`from_dict()` round-trip, repeated moras (`アア`, `カカカ`), small kana (`キャ`, `キャキュキョ`, `シャチュリョ`), hiragana normalization (`こんにちは`), empty string `""`, and CTC collapse (`[1, 1] -> "ア"` vs `[1, 0, 1] -> "アア"`).
   - `CharNgramLM`: finite non-positive log-probs on seen, unseen, and empty prefixes, plus exact `to_dict()`/`from_dict()` round-trip.
   - `compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`, `alignment_boundary_error`: verified repeated mora deletion (`アア` vs `ア` -> `cer=0.5`), char-vs-mora distinction on small kana (`キャ` vs `キ` -> `cer=0.5`, `mer=1.0`), empty edge cases, confusion pairs, and boundary error metrics.

4. **Probe 4 — FastAPI `create_app` Routes**
   - Unloaded app (`checkpoint_path=None`): `GET /` (200 HTML, `<canvas>`, zero external CDN), `GET /api/health` (`{"status": "ok", "model_loaded": false}`), `GET /api/info` (200, `model_loaded: false`, `tsukinami_presets` populated with 8 presets), `POST /api/redecode` (503 cleanly when no model loaded).
   - Loaded app (`checkpoint_path=best.pt`): `GET /`, `GET /api/health` (`model_loaded: true`), `GET /api/info` (`model_loaded: true`, `vocab`, `tsukinami_presets`, `history`, etc.), `POST /api/redecode` with unknown `utterance_id` -> `404`, `POST /api/transcribe` valid WAV -> `200` + cached `POST /api/redecode` hit in `3.20 ms` (`< 10 ms`), `POST /api/transcribe` corrupt bytes -> `400`, `POST /api/tts-roundtrip` -> `200`.

---

## Exact Probe Outputs

### Run 1 (Full 4-Probe Suite)
```text
PROBE_DIR=/tmp/teamwork_probe.Bc5PDO
=== PROBE 1: End-to-End Mini-Pipeline from Temp Dir ===
[PASS] P1.fast.train.nonempty (n=4)
[PASS] P1.fast.train.audio_path_is_absolute (sample=/tmp/teamwork_probe.Bc5PDO/work_a/ds_fast/audio/train/train_00000.wav)
[PASS] P1.fast.train.direct_load_wav_from_other_cwd
[PASS] P1.fast.val.nonempty (n=2)
[PASS] P1.fast.val.audio_path_is_absolute (sample=/tmp/teamwork_probe.Bc5PDO/work_a/ds_fast/audio/val/val_00000.wav)
[PASS] P1.fast.val.direct_load_wav_from_other_cwd
[PASS] P1.mixed.train.nonempty (n=4)
[PASS] P1.mixed.train.audio_path_is_absolute (sample=/tmp/teamwork_probe.Bc5PDO/work_a/ds_mixed/audio/train/train_00000.wav)
[PASS] P1.mixed.train.direct_load_wav_from_other_cwd
[PASS] P1.mixed.val.nonempty (n=2)
[PASS] P1.mixed.val.audio_path_is_absolute (sample=/tmp/teamwork_probe.Bc5PDO/work_a/ds_mixed/audio/val/val_00000.wav)
[PASS] P1.mixed.val.direct_load_wav_from_other_cwd
[PASS] P1.build_manifest_from_wav_dir.absolute_path (/tmp/teamwork_probe.Bc5PDO/work_a/raw_wavs/utt1.wav)
[PASS] P1.build_manifest_from_wav_dir.direct_load_wav_other_cwd
[PASS] P1.relative_manifest_backward_compat
[PASS] P1.collate_asr_batch.shapes (feats=(4, 286, 64), targets=(4, 15))
[PASS] P1.model.cnn_bigru.forward (log_probs=(4, 72, 86), out_lengths=[72, 19, 26, 58])
[PASS] P1.model.cnn_bigru.greedy_decode
[PASS] P1.model.cnn_bigru.prefix_beam_search (top_no_lm='サォセコセノォノセォセコセォヤォサォフベセォセォセヤセォセォセヤセォヤシ', top_lm='サコラサコラコ')
[PASS] P1.model.cnn_bigru.viterbi_align (n_seg=15)
[PASS] P1.model.conformer_lite.forward (log_probs=(4, 72, 86), out_lengths=[72, 19, 26, 58])
[PASS] P1.model.conformer_lite.greedy_decode
[PASS] P1.model.conformer_lite.prefix_beam_search (top_no_lm='ガアケレケレダケャッギルクギタルタルポッナッナッダッィポギポギダジ', top_lm='ガギケコギタナッギ')
[PASS] P1.model.conformer_lite.viterbi_align (n_seg=15)

=== PROBE 2: CLI eval & transcribe from a Different Working Directory ===
[PASS] P2.train_asr.checkpoint_exists (/tmp/teamwork_probe.Bc5PDO/ckpt/best.pt)
[PASS] P2.cli_eval.greedy.other_cwd (rc=0, cer=1.0, stderr=)
[PASS] P2.cli_eval.beam.other_cwd (rc=0, cer=1.0, stderr=)
[PASS] P2.cli_transcribe_wav.other_cwd (rc=0, text='', stderr=)
[PASS] P2.cli_transcribe_tts.other_cwd (rc=0, cer=1.0, stderr=)

=== PROBE 3: Tricky Inputs (DSP, VAD, Corruptions, Tokenizer, LM, Metrics) ===
[PASS] P3.features.len_1 (mel=(1, 64), mfcc_d=(1, 39))
[PASS] P3.features.len_10 (mel=(1, 64), mfcc_d=(1, 39))
[PASS] P3.features.len_160 (mel=(1, 64), mfcc_d=(1, 39))
[PASS] P3.features.len_399 (mel=(1, 64), mfcc_d=(1, 39))
[PASS] P3.features.len_400 (mel=(1, 64), mfcc_d=(1, 39))
[PASS] P3.features.silence_1s (mel=(98, 64), mfcc_d=(98, 39))
[PASS] P3.features.dc_const (mel=(48, 64), mfcc_d=(48, 39))
[PASS] P3.vad.silence (got=[])
[PASS] P3.vad.very_short (got=[(0.0, 0.0001875)])
[PASS] P3.vad.burst (got=[(0.24, 0.92)])
[PASS] P3.corruption.silence_white
[PASS] P3.corruption.silence_pink
[PASS] P3.corruption.combo_deterministic
[PASS] P3.tokenizer.kana.blank_and_roundtrip
[PASS] P3.tokenizer.kana.tricky_encode_decode
[PASS] P3.tokenizer.phoneme.blank_and_roundtrip
[PASS] P3.tokenizer.phoneme.tricky_encode_decode
[PASS] P3.tokenizer.ascii.blank_and_roundtrip
[PASS] P3.tokenizer.ascii.tricky_encode_decode
[PASS] P3.tokenizer.kana.ctc_repeated_mora (ids_aa=[1, 1], same='ア', blank_sep='アア')
[PASS] P3.tokenizer.kana.small_kana_kya (ids_kya=[7, 75], dec='キャ')
[PASS] P3.lm.scores_and_roundtrip (seen=-0.0711, unseen=-2.3716, empty=-1.3867)
[PASS] P3.metrics.cer_repeated_mora
[PASS] P3.metrics.cer_vs_mer_small_kana (cer_kya={'cer': 0.5, 'substitutions': 0, 'deletions': 1, 'insertions': 0, 'ref_len': 2}, mer_kya={'mer': 1.0, 'substitutions': 1, 'deletions': 0, 'insertions': 0, 'ref_len': 1})
[PASS] P3.metrics.wer
[PASS] P3.metrics.empty_edge_cases (empty={'cer': 0.0, 'substitutions': 0, 'deletions': 0, 'insertions': 0, 'ref_len': 0}, empty_ref={'cer': 1.0, 'substitutions': 0, 'deletions': 0, 'insertions': 1, 'ref_len': 0})
[PASS] P3.metrics.confusion_pairs (cp=[('カ', 'ガ', 1), ('ク', 'グ', 1)])
[PASS] P3.metrics.alignment_boundary_error (abe={'onset_mae_sec': 0.01, 'offset_mae_sec': 0.010000000000000009, 'mean_start_error_ms': 10.0, 'mean_end_error_ms': 10.000000000000009, 'mean_boundary_error_ms': 10.000000000000004, 'mean_iou': 0.8999999999999999, 'matched': 2, 'gt_count': 2, 'pred_count': 2})

=== PROBE 4: FastAPI create_app Routes ===
[PASS] P4.empty.GET_root
[PASS] P4.empty.zero_cdn
[PASS] P4.empty.GET_health ({'status': 'ok', 'model_loaded': False})
[PASS] P4.empty.GET_info
[PASS] P4.loaded.GET_root
[PASS] P4.loaded.GET_health ({'status': 'ok', 'model_loaded': True})
[NOTE] P4.loaded.GET_info returned keys=['arch', 'audio_config', 'best_val_cer', 'blank_id', 'cache_size', 'checkpoint', 'checkpoint_path', 'epoch', 'frame_stride_ms', 'has_lm', 'history', 'max_cache_size', 'model_config', 'model_loaded', 'num_parameters', 'param_count', 'preset_details', 'subsampling_factor', 'tokenizer', 'tokenizer_mode', 'tsukinami_presets', 'vocab', 'vocab_size'] (probe initially checked 'presets' instead of 'tsukinami_presets'; confirmed in Run 2 below).
[PASS] P4.loaded.POST_redecode_404 (status=404, body={"detail":"Unknown or evicted utterance_id: 'nonexistent_id_12345'"})
[PASS] P4.loaded.POST_transcribe_valid (status=200)
[PASS] P4.loaded.POST_redecode_hit (status=200, elapsed_ms=3.20)
[PASS] P4.loaded.POST_transcribe_corrupt (status=400)
[PASS] P4.loaded.POST_tts_roundtrip (status=200, cer=1.4)
```

### Run 2 (Cleanup Verification & `/api/info` + Unloaded `/api/redecode` Confirmation)
```text
CLEANUP_VERIFIED=1
empty_info_presets= ['default', 'ossan', 'robot', 'horror', 'whisper', 'chibi', 'utahime', 'choir']
empty_redecode_status= 503 {'detail': 'No ASR model loaded. Launch server with --checkpoint PATH.'}
```

---

## Final Verdict

**PASS** — All Tier 1 core contracts, absolute manifest path fixes, cross-CWD CLI handoffs, tricky DSP/tokenizer/LM/metrics edge cases, and FastAPI routes behave cleanly and accurately.
