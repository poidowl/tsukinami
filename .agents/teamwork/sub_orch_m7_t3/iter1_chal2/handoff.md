# Challenger 2 Handoff — Decoding, Alignment, Metrics, Engine & Web API Cross-Feature Probes

## Verdict
**`CONFIRMED_CORRECT`**

No Tier 3 or contract defects were found across `asr/decoding.py`, `asr/metrics.py`, `asr/inference.py`, or `asr/server.py`. All 166 adversarial cross-feature assertions passed cleanly after resolving one probe-script assumption about existing read-only `kotoba.split_moras("hello world")` behavior. Working tree is untouched (`git diff --stat` empty), and all temporary probe directories under `/tmp/teamwork_probe.*` were removed before reporting.

---

## Probe Execution Environment & Hygiene
- **Python**: `.venv/bin/python` with `PYTHONPATH=. OMP_NUM_THREADS=1`
- **Concurrency**: Did NOT invoke `tests_e2e/` concurrently with Primary Reviewer.
- **Staging & Cleanup**: All scripts and temporary `.pt` checkpoints were staged in `mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX"` and deleted via `rm -rf` immediately after execution (verified `NO_LEFTOVER_PROBE_DIRS`).
- **Repository Cleanliness**: `git diff --stat` returned empty output; zero source or test files were modified.

---

## Probe Suites Executed & Results

### Suite A: Core Cross-Feature Probes (`probe_all.py`)
Command pattern:
```bash
PROBE_DIR=$(mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX")
# wrote probe_all.py into $PROBE_DIR
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python "$PROBE_DIR/probe_all.py"
rm -rf "$PROBE_DIR"
```

1. **Probe 1 — `greedy_decode`, `prefix_beam_search`, `CharNgramLM` → `viterbi_align`** (all checks PASSED):
   - `CharNgramLM` (`order` in `{1, 2, 3, 4}`, `smoothing=0.05`) JSON `to_dict()` / `from_dict()` roundtrip: exact equality and identical `score_next()` values across empty prefix, kana, small kana (`キ`→`ョ`), sokuon (`ガ`→`ッ`), chouonpu (`ラ`→`ー`), unseen tokens (`ヴ`), and `<eos>`. Empty/unfitted LM roundtrips cleanly and returns `0.0`.
   - Synthetic CTC collapse `[ア, ア, <blank>, ア, カ, カ]` → `"アアカ"` in both `greedy_decode` and `prefix_beam_search`.
   - `blank_bias=+25.0` forces empty decode; `blank_bias=-25.0` forces non-empty decode; `lm_weight=0.0` with LM matches `lm=None` identically; `lm_weight=0.7, insertion_bonus=0.5` produces finite, descending-sorted hypotheses; extreme temperatures (`0.05`, `1.0`, `5.0`) produce finite scores.
   - Boundary & error guards: `T=0` and `T=1` handled cleanly; partial `-inf` entries handled cleanly; all-`-inf` frame raises `ValueError` in both `greedy_decode` and `prefix_beam_search`; invalid `temperature` (`0.0`, `-1.0`, `NaN`, `True`) and `blank_bias=inf` raise `ValueError`.
   - `viterbi_align`: repeated tokens `[ア, ア, カ]` enforce mandatory blank gap (`end_sec=0.08 < start_sec=0.12`), monotonic non-overlapping spans within `[0, T * stride]`, finite confidences in `[0, 1]`. Empty `token_ids=[]` returns `[]` even for `T=0`. Guards raise `ValueError` for `[A, A]` with `T=2 < min_frames=3`, `len(ids) > T`, `blank_id` in `token_ids`, out-of-range IDs, `bool` IDs, and impossible `-inf` token columns.
   - Cross-tokenizer chain: `Tokenizer("phoneme")` + `CharNgramLM` → `prefix_beam_search` → `tokenizer.encode(text)` → `viterbi_align` produced 6 aligned phoneme spans for `'o h a y o u'`.

2. **Probe 2 — Metrics (`compute_cer`, `compute_mer`, `compute_wer`, `confusion_pairs`, `alignment_boundary_error`)** (all checks PASSED):
   - Hiragana vs. Katakana with small kana, sokuon, chouonpu (`"きょう、がっこう、らーめん"` vs `"キョウ、ガッコウ、ラーメン"`): `compute_cer(normalize_kana=False)` > 0, `normalize_kana=True` == `0.0`; `compute_mer` == `0.0` (`ref_len=12`); `ignore_pauses=False` records 1 deletion vs `ignore_pauses=True` == `0.0`.
   - Small-kana mora substitution: `compute_mer(["キャッチャー"], ["カッチャー"])` → `ref_len=4, substitutions=1, mer=0.25`.
   - Empty inputs: `[""]` vs `[""]` → `0.0` across CER/MER/WER; `[""]` vs `["ア"]` → `1.0` (`insertions=1`); `["ア"]` vs `[""]` → `1.0` (`deletions=1`); `[]` vs `[]` → `0.0`; pause-only `["、"]` vs `[""]` with `ignore_pauses=True` → `0.0`; mismatched sequence lengths raise `ValueError`.
   - `confusion_pairs(unit="mora")` on small kana returned `[('キョ', 'コ', 1), ('シャ', 'サ', 1)]`; `top_k=0` → `[]`; `top_k=-1` and invalid `unit` raise `ValueError`.
   - `alignment_boundary_error`: correctly merged `キ` + `ョ` → `キョ` while NOT merging `ャ` onto non-mergeable `ッ` (`matched=4, gt_count=4, pred_count=4, mean_iou=1.0, onset_mae_sec=0.0`). Empty `([], [])` returns finite zeros; zero-duration exact match returns `mean_iou=1.0`.

3. **Probe 3 — `ASREngine` (`transcribe`, visuals, edge audio, LRU `redecode` & latency)** (all checks PASSED):
   - `include_visuals=True` includes all 10 keys (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`, `waveform`, `log_mel`, `ctc_posteriors`, `vad_segments`) with `ctc_posteriors["top_tokens"][0] == "<blank>"`; `include_visuals=False` omits all 4 visual keys.
   - Edge audio inputs: `sr=44100` resampled cleanly; stereo `(2, N)` and `(N, 2)` yielded identical durations; `NaN`/`+inf`/`-inf` samples sanitized to finite waveform outputs; empty `float32[]` returned `text=""`, `duration_sec=0.0`, `waveform=[]`.
   - LRU cache (`max_cache_size=3`): transcribing `u1, u2, u3`, refreshing `u1` via `redecode`, then transcribing `u4` evicted `u2` (`KeyError`) while keeping `u1, u3, u4` cached. Unknown `utterance_id` raised `KeyError`; non-`DecodeConfig` raised `TypeError`.
   - Extreme `blank_bias=-10.0` in `redecode` completed safely without crashing on Viterbi length constraints.
   - **Cached `redecode` median latency** (~1.1 s utterance, 5 trials):
     - `greedy`: **0.59 ms** (< 10 ms target)
     - `beam (beam_width=8)`: **3.28 ms** (< 10 ms target)
     - `beam + LM (beam_width=8, lm_weight=0.5)`: **4.55 ms** (< 10 ms target)

4. **Probe 4 — FastAPI `create_app` Endpoints** (all contract checks PASSED):
   - **No-model mode** (`create_app()`): `GET /` → `200 text/html` with **0 external CDN `<script>`/`<link>` tags**; `GET /api/health` → `200 {"status": "ok", "model_loaded": false}`; `GET /api/info` → `200`; `POST /api/transcribe`, `/api/tts-roundtrip`, `/api/redecode` → `503`.
   - **Loaded-model mode**: `GET /api/health` → `model_loaded: true`; `GET /api/info` → valid model/vocab/preset metadata.
   - **`POST /api/transcribe` invalid inputs**: empty multipart WAV → `400`, corrupt non-WAV bytes → `400`, missing `file` → `422`, empty JSON → `400`, malformed JSON → `400`, missing `audio_b64` → `422`, invalid base64 → `400`, base64 junk → `400`, `temperature=-0.5` → `422`, `beam_width=999` → `422`.
   - **`POST /api/transcribe` valid inputs**: multipart WAV with pink noise corruption (`snr_db=15`) + `include_visuals=true` → `200` with visuals & `utterance_id`; JSON `data:audio/wav;base64,...` URI with `include_visuals=false` → `200` without visuals.
   - **`POST /api/tts-roundtrip` + `/api/redecode` chained flow**:
     - Validation guards: blank text → `422`, unknown preset → `422`, unknown `synth_engine` → `422`, extra Pydantic field → `422`, `hz=-50` → `422`.
     - Valid chained request (`text="きょう、がっこう"`, `preset="ossan"`, `synth_engine="fast"`, `corruption={"snr_db": 15.0, "speed": 1.25, "band_limit": [300.0, 3400.0]}`) → `200`, valid RIFF WAV in `audio_b64`, speed-scaled `ground_truth_moras` (`max_end=0.932s <= duration=1.020s`), chained `/api/redecode` (nested `decode_cfg`: `0.56 ms`; top-level overrides: `3.15 ms`) → `200`.
     - Unknown `utterance_id` → `404`; whitespace `utterance_id` → `422`; `temperature=0.0` → `422`.
   - *Note on Probe 4 initial check*: Passing `"hello world"` to `/api/tts-roundtrip` returned `200` because read-only `kotoba.split_moras("hello world")` intentionally preserves non-kana characters as fallback moras (`['h', 'e', ..., 'd']`), which in turn evicted the earlier `/api/transcribe` entry from the `max_cache_size=3` test engine. Verified in Suite B below that punctuation-only `"!!!"` (which produces 0 moras) cleanly returns `400`, and `/api/transcribe` → `/api/redecode` succeeds cleanly with default cache size.

---

### Suite B: Checkpoint + Embedded LM + Authentic Tsukinami API Probes (`probe_extra.py`)
Command pattern:
```bash
PROBE_DIR=$(mktemp -d -- "${TMPDIR:-/tmp}/teamwork_probe.XXXXXX")
# wrote probe_extra.py into $PROBE_DIR
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python "$PROBE_DIR/probe_extra.py" "$PROBE_DIR"
rm -rf "$PROBE_DIR"
```
Result: **9/9 PASSED (`EXIT_CODE=0`)**:
- `create_app(checkpoint_path=...)` loaded a saved `conformer_lite` `.pt` checkpoint with an embedded `CharNgramLM` dict and exposed `has_lm=True`, `epoch=3`, `best_val_cer=0.42`, and `history` via `GET /api/info`.
- `POST /api/tts-roundtrip` with punctuation-only `"!!!"` returned `400` (`No speakable Japanese kana moras produced`).
- `POST /api/tts-roundtrip` with authentic `synth_engine="tsukinami"` (`text="あか"`, `preset="default"`) returned `200` with 2 moras, and chained `POST /api/redecode` returned `200` (`decode_ms=4.07 ms`).
- Chained `POST /api/transcribe` → `POST /api/redecode` returned `200` (`decode_ms=1.48 ms`).
- `ASREngine.from_checkpoint` on a corrupt `.pt` file raised `ValueError` cleanly.
