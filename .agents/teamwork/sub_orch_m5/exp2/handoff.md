# Explorer 2 (`exp2`) Handoff — Decoding, Alignment, `<10 ms` Redecode & CLI Design (M5)

## 1. Inspected Modules & Verified Interface Signatures

### 1.1 `asr/decoding.py`
- **`CharNgramLM(order: int = 3, smoothing: float = 0.1)`**
  - `.fit(texts: Sequence[str]) -> CharNgramLM`
  - `.score_next(prefix: str, token: str) -> float`
  - `.to_dict() -> dict[str, Any]` / `CharNgramLM.from_dict(d: Mapping[str, Any]) -> CharNgramLM`
- **`greedy_decode(log_probs: np.ndarray, tokenizer: Tokenizer, *, temperature: float = 1.0, blank_bias: float = 0.0) -> dict[str, Any]`**
  - Validates `(T, V)` against `tokenizer.vocab_size`, handles `T == 0` by returning `{"text": "", "token_ids": [], "score": 0.0}`.
  - Internally calls `_prepare_log_probs(...)` which copies/scales `log_probs` without mutating the caller's array.
  - Returns: `{"text": str, "token_ids": list[int], "score": float}`.
- **`prefix_beam_search(log_probs: np.ndarray, tokenizer: Tokenizer, cfg: DecodeConfig, lm: CharNgramLM | None = None) -> list[dict[str, Any]]`**
  - Requires `isinstance(cfg, DecodeConfig)` (raises `TypeError` otherwise).
  - Handles `T == 0` by returning `[{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]`.
  - Internally calls `_prepare_log_probs(...)` without mutating caller's array.
  - Returns up to `cfg.beam_width` hypotheses sorted descending by `score`, tie-broken by `text`:
    `[{"text": str, "score": float, "acoustic_score": float, "lm_score": float}, ...]`.
  - **Important finding**: `prefix_beam_search` does **not** include `"token_ids"` in its returned hypothesis dicts.
- **`viterbi_align(log_probs: np.ndarray, token_ids: Sequence[int], tokenizer: Tokenizer, frame_stride_ms: float = 40.0) -> list[dict[str, Any]]`**
  - Returns `[]` immediately if `len(token_ids) == 0`.
  - Raises `ValueError` if:
    - `token_ids` contains `tokenizer.blank_id` (`0`) or out-of-range IDs.
    - `T < min_frames` where `min_frames = len(ids) + sum(1 for k in range(1, len(ids)) if ids[k] == ids[k-1])`.
    - All paths end in `-inf`.
  - Returns: `[{"token": str, "start_sec": float, "end_sec": float, "confidence": float}, ...]`.
  - Computes `confidence` as `mean(exp(clip(lp[start:end+1, tok_id], -700, 0)))` clipped to `[0, 1]`, so `log_probs` should be normalized log-probabilities (`log_softmax`), which the acoustic model already outputs.

### 1.2 `asr/metrics.py`
- **`compute_cer(refs: Sequence[str], hyps: Sequence[str], *, normalize_kana: bool = False) -> dict[str, Any]`**
  - Returns `{"cer": float, "substitutions": int, "deletions": int, "insertions": int, "ref_len": int}`.
- **`compute_mer(refs: Sequence[str], hyps: Sequence[str], *, ignore_pauses: bool = False) -> dict[str, Any]`**
  - Returns `{"mer": float, "substitutions": int, "deletions": int, "insertions": int, "ref_len": int}`.
- **`compute_wer(refs: Sequence[str], hyps: Sequence[str]) -> dict[str, Any]`**
  - Returns `{"wer": float, "substitutions": int, "deletions": int, "insertions": int, "ref_len": int}`.
- **`confusion_pairs(refs: Sequence[str], hyps: Sequence[str], top_k: int = 10, *, unit: str = "char") -> list[tuple[str, str, int]]`**
  - Returns `[(ref_tok, hyp_tok, count), ...]`.
- **`compute_rtf(elapsed_sec: float, audio_duration_sec: float) -> float`**
  - Returns `0.0` if `audio_duration_sec == 0.0`, else `elapsed_sec / audio_duration_sec`.
- **`alignment_boundary_error(gt_moras, pred_align) -> dict[str, Any]`**

### 1.3 `asr/synth_data.py` & `yomu.py`
- **`synthesize_fast_kotoba(text: str, *, sr: int = 16000, f0_scale: float = 1.0, fscale: float = 1.0, rate: float = 1.0, snr_db: float | None = None, seed: int | None = None) -> tuple[np.ndarray, list[dict[str, Any]]]`**
  - Returns `(wav_float32, moras)` where each mora is `{"t", "a", "e"}`.
- **`synthesize_tsukinami(text: str, *, preset: str = "default", sr: int = 16000, overrides: dict[str, Any] | None = None, cache_dir: str | Path | None = None) -> tuple[np.ndarray, list[dict[str, Any]]]`**
  - Available presets in `yomu.PRESETS` (8 total):
    `("default", "ossan", "robot", "horror", "whisper", "chibi", "utahime", "choir")`.
  - `DEFAULT_TSUKINAMI_PRESETS` (6 default dataset presets):
    `("default", "ossan", "robot", "horror", "whisper", "chibi")`.
  - Raises `ValueError` on unknown preset or non-speakable text.
- **`generate_dataset(out_dir: str | Path, *, num_train: int = 200, num_val: int = 40, engine: str = "fast", seed: int = 42, presets: Sequence[str] | None = None) -> dict[str, Path]`**
  - `VALID_ENGINES = ("fast", "tsukinami", "mixed")`.
  - Returns `{"train": Path(.../train.jsonl), "val": Path(.../val.jsonl)}`.

### 1.4 `asr/dataset.py` & `asr/train.py`
- **`load_manifest(manifest_path: str | Path) -> list[dict[str, Any]]`**: validates JSONL, requires `"audio_path"` and `"text"`.
- **Relative audio path resolution** (same logic as `asr/dataset.py:_resolve_audio_path`):
  1. If `Path(raw_audio_path).is_absolute()`: use as-is.
  2. Else if `(manifest_dir / p).exists()`: use `(manifest_dir / p).resolve()`.
  3. Else if `p.exists()`: use `p.resolve()`.
  4. Else return `manifest_dir / p` (which will raise `FileNotFoundError` in `load_wav`).
- **`train_asr(train_manifest, val_manifest, *, audio_cfg=None, model_cfg=None, train_cfg=None, tokenizer=None, resume_from=None) -> dict[str, Any]`**
  - Saves `best.pt` and `latest.pt` inside `train_cfg.checkpoint_dir`.
  - Returns `{"best_checkpoint": str, "latest_checkpoint": str, "best_val_cer": float, "final_train_loss": float, "final_val_loss": float, "final_val_cer": float, "epochs_completed": int, "history": list[dict]}`.
- **`load_checkpoint(path: str | Path, device: str = "cpu") -> dict[str, Any]`**
  - Validates existence, non-dir, non-corrupt, required keys (`model_state_dict`, `model_config`, `tokenizer`), and ensures both `audio_cfg` and `audio_config` aliases exist.
- **`asr/__init__.py`**: Not in M5 exclusive ownership; do **not** modify.

---

## 2. Concrete Design for Decoding, Alignment & `<10 ms` `redecode` in `asr/inference.py`

### 2.1 Shared Internal Helper: `_decode_and_align(log_probs, decode_cfg, frame_stride_ms)`
Centralize decoding + alignment into a single helper called by both `transcribe()` and `redecode()` so their output schemas are guaranteed identical:

```python
def _decode_and_align(
    self,
    log_probs: np.ndarray,
    decode_cfg: DecodeConfig,
    frame_stride_ms: float,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(decode_cfg, DecodeConfig):
        raise TypeError(f"decode_cfg must be a DecodeConfig, got {type(decode_cfg).__name__}")

    if log_probs.shape[0] == 0:
        empty_hyp = {
            "text": "",
            "score": 0.0,
            "acoustic_score": 0.0,
            "lm_score": 0.0,
        }
        return "", [empty_hyp], []

    if decode_cfg.method == "greedy":
        res = greedy_decode(
            log_probs,
            self.tokenizer,
            temperature=decode_cfg.temperature,
            blank_bias=decode_cfg.blank_bias,
        )
        text = res["text"]
        score = float(res["score"])
        token_ids: list[int] = res["token_ids"]
        hypotheses = [
            {
                "text": text,
                "score": score,
                "acoustic_score": score,
                "lm_score": 0.0,
            }
        ]
    else:  # decode_cfg.method == "beam"
        hypotheses = prefix_beam_search(
            log_probs,
            self.tokenizer,
            decode_cfg,
            lm=self.lm,
        )
        text = hypotheses[0]["text"] if hypotheses else ""
        token_ids = self.tokenizer.encode(text) if text else []

    if token_ids:
        try:
            alignment = viterbi_align(
                log_probs,
                token_ids,
                self.tokenizer,
                frame_stride_ms=frame_stride_ms,
            )
        except ValueError:
            alignment = []
    else:
        alignment = []

    return text, hypotheses, alignment
```

### 2.2 Key Design Points for `_decode_and_align`
1. **Normalized `hypotheses` schema**:
   - Both `"greedy"` and `"beam"` produce `list[dict]` with exact keys `{"text", "score", "acoustic_score", "lm_score"}` (all JSON-native `str` / `float`).
   - For `"greedy"`: single-element list with `acoustic_score == score` and `lm_score == 0.0`.
   - For `"beam"`: directly uses `prefix_beam_search` output (up to `decode_cfg.beam_width` items, sorted descending by `score`).
2. **Obtaining `token_ids` for `viterbi_align`**:
   - `"greedy"`: uses `greedy_decode(...)["token_ids"]` directly (zero re-encoding overhead).
   - `"beam"`: encodes `hypotheses[0]["text"]` via `self.tokenizer.encode(text)`. Verified that `Tokenizer.encode(Tokenizer.decode(ids))` round-trips cleanly for all 3 modes (`kana`, `phoneme`, `ascii`) and never emits `blank_id` (`0`).
   - Empty hypothesis (`text == ""` or `token_ids == []`): skips `viterbi_align` and returns `alignment = []`.
   - Defensive `try/except ValueError` around `viterbi_align` guarantees no crash on pathological edge cases (e.g., if `min_frames > T` or all `-inf` paths).
3. **Ensuring `<10 ms` `redecode(utterance_id, decode_cfg)`**:
   - Cache stores `OrderedDict[str, tuple[np.ndarray, float, float]]` mapping `utterance_id -> (log_probs_np, duration_sec, frame_stride_ms)`.
   - `log_probs_np` is a 2D `np.float32` array of shape `(T', V)` detached from PyTorch at `transcribe()` time.
   - `redecode()` executes **zero** PyTorch ops, **zero** STFT/Mel extraction, **zero** VAD:
     ```python
     def redecode(self, utterance_id: str, decode_cfg: DecodeConfig | None = None) -> dict[str, Any]:
         if utterance_id not in self._cache:
             raise KeyError(f"Unknown utterance_id: {utterance_id!r}")
         cfg = decode_cfg if decode_cfg is not None else DecodeConfig()
         if not isinstance(cfg, DecodeConfig):
             raise TypeError(f"decode_cfg must be a DecodeConfig, got {type(cfg).__name__}")
         self._cache.move_to_end(utterance_id)
         log_probs, duration_sec, frame_stride_ms = self._cache[utterance_id]
         t0 = time.perf_counter()
         text, hypotheses, alignment = self._decode_and_align(log_probs, cfg, frame_stride_ms)
         decode_ms = (time.perf_counter() - t0) * 1000.0
         return {
             "text": text,
             "hypotheses": hypotheses,
             "alignment": alignment,
             "utterance_id": utterance_id,
             "duration_sec": float(duration_sec),
             "decode_ms": float(decode_ms),
         }
     ```
   - Typical latency on CPU for 1–2 s audio (`T' ≈ 25–50`, `V = 86`, `beam_width = 8`): ~0.1 ms (greedy) to ~2–5 ms (beam + Viterbi), comfortably `<10 ms`.
   - Bounded LRU cache eviction: on insert in `transcribe()`, if `self.max_cache_size > 0`:
     ```python
     self._cache[utterance_id] = (log_probs, duration_sec, frame_stride_ms)
     self._cache.move_to_end(utterance_id)
     while len(self._cache) > self.max_cache_size:
         self._cache.popitem(last=False)
     ```

---

## 3. Concrete Design for CLI (`asr/__main__.py`)

### 3.1 Entry Point & Error Handling Pattern
- Implement `build_parser() -> argparse.ArgumentParser` and `main(argv: Sequence[str] | None = None) -> int`.
- `if __name__ == "__main__": sys.exit(main())`.
- Top-level `try ... except (FileNotFoundError, ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:` prints `f"Error: {exc}"` to `sys.stderr` and returns `1`.
- `argparse` validation errors naturally exit with code `2`.

### 3.2 Subcommands & Exact Integrations

| Subcommand | Flags & Defaults | Core Integration |
|---|---|---|
| `demo` | `--out-dir DIR` (default `"demo_out"`), `--epochs N` (default `8`), `--num-train N` (default `60`), `--num-val N` (default `12`), `--arch cnn_bigru\|conformer_lite` (default `"cnn_bigru"`), `--seed N` (default `42`) | 1) `generate_dataset(out_dir / "data", num_train=..., num_val=..., engine="fast", seed=...)`<br>2) `ModelConfig(arch=args.arch, n_mels=64, hidden_size=128, num_layers=2)` + `TrainConfig(epochs=args.epochs, batch_size=min(16, args.num_train), lr=3e-3, seed=args.seed, checkpoint_dir=str(out_dir))` + `Tokenizer("kana")`<br>3) `train_asr(...)` → saves `out_dir / "best.pt"` & `latest.pt`<br>4) `ASREngine.from_checkpoint(best_ckpt)`<br>5) Evaluate `val.jsonl` with `compute_cer`, `compute_mer`, `confusion_pairs(refs, hyps, top_k=5)`<br>6) Live TTS→ASR: `synthesize_fast_kotoba("オハヨウゴザイマス", sr=engine.audio_cfg.sample_rate, seed=args.seed)` → `engine.transcribe(...)` → print ref, hyp, CER, RTF, and `best.pt` path |
| `generate` | `--out-dir DIR` (required), `--num-train N` (default `200`), `--num-val N` (default `40`), `--engine fast\|tsukinami\|mixed` (default `"fast"`), `--seed N` (default `42`) | `generate_dataset(args.out_dir, num_train=args.num_train, num_val=args.num_val, engine=args.engine, seed=args.seed)` |
| `train` | `--train-manifest PATH` (required), `--val-manifest PATH` (required), `--out-dir DIR` (default `"checkpoints"`), `--arch cnn_bigru\|conformer_lite` (default `"cnn_bigru"`), `--epochs N` (default `20`), `--batch-size N` (default `16`), `--lr FLOAT` (default `3e-3`), `--seed N` (default `42`), `--resume PATH` (default `None`) | Builds `AudioConfig()`, `ModelConfig(arch=args.arch)`, `TrainConfig(epochs=..., batch_size=..., lr=..., seed=..., checkpoint_dir=args.out_dir)`, `Tokenizer("kana")` and calls `train_asr(..., resume_from=args.resume)` |
| `eval` | `--checkpoint PATH` (required), `--manifest PATH` (required), `--method greedy\|beam` (default `"beam"`), `--beam-width K` (default `8`), `--json` (flag) | Loads `ASREngine.from_checkpoint(args.checkpoint)` and `load_manifest(args.manifest)` (resolving relative `audio_path` against `manifest.parent`), validates non-empty manifest, runs `load_wav` + `engine.transcribe` per record, computes `compute_cer`, `compute_mer`, `confusion_pairs(refs, hyps, top_k=10)`, `compute_rtf(total_infer_sec, total_audio_sec)`. Outputs JSON if `--json`, else formatted summary. |
| `transcribe` | `--checkpoint PATH` (required), mutually exclusive required group: `--wav PATH` vs `--tts TEXT`, plus `--preset NAME` (default `"default"`), `--engine fast\|tsukinami` (default `"tsukinami"`), `--method greedy\|beam` (default `"beam"`), `--beam-width K` (default `8`), `--json` (flag) | Loads `ASREngine.from_checkpoint(args.checkpoint)`. For `--wav`: `load_wav(args.wav, target_sr=engine.audio_cfg.sample_rate)`. For `--tts`: `synthesize_tsukinami(args.tts, preset=args.preset, sr=engine.audio_cfg.sample_rate)` if `--engine tsukinami` else `synthesize_fast_kotoba(args.tts, sr=engine.audio_cfg.sample_rate)`. Calls `engine.transcribe(wav, sr=sr, decode_cfg=DecodeConfig(method=args.method, beam_width=args.beam_width))`. Outputs JSON (all `transcribe` fields, plus `tts_text`/`cer` when `--tts`) if `--json`, else formatted output. |
| `serve` | `--checkpoint PATH` (optional/default `None` or validated if given), `--host STR` (default `"127.0.0.1"`), `--port INT` (default `8000`) | Validates `--checkpoint` exists if provided. Lazily imports `from asr.server import create_app` and `import uvicorn` inside the `serve` handler so `python -m asr --help` and all other subcommands work cleanly before M6 creates `asr/server.py`. Calls `app = create_app(checkpoint_path=args.checkpoint)` and `uvicorn.run(app, host=args.host, port=args.port)`. |

### 3.3 `demo` CPU Speed Considerations
- Using `hidden_size=128` (divisible by `num_heads=4` for `conformer_lite`) and `engine="fast"` keeps default `demo` (`num_train=60, num_val=12, epochs=8`) well under ~15 seconds on 2 vCPUs.
- In automated tests (`tests/test_asr_cli.py`), running `python -m asr demo --out-dir <tmp> --epochs 1 --num-train 6 --num-val 2` will execute the entire end-to-end pipeline (generate → train → eval → live TTS→ASR → save `best.pt`) in ~1–2 seconds.
- Ensure `batch_size = min(16, max(1, args.num_train))` so tiny `--num-train` values never cause issues.
- Validate `--epochs >= 1`, `--num-train >= 1`, `--num-val >= 1` cleanly (raising `ValueError` → exit code `1`).

### 3.4 `transcribe --tts` Preset Note
- All 8 presets in `yomu.PRESETS` (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`) are supported by `synthesize_tsukinami`. Letting `synthesize_tsukinami` validate `preset` (or validating against `yomu.PRESETS`) avoids hardcoding a stale list and gives a helpful error listing all available presets on invalid input.

---

## 4. Recommended Test Matrix for `tests/test_asr_cli.py` (Decoding/Redecode/CLI Portion)
1. `ASREngine.transcribe`: both `greedy` and `beam` produce normalized `hypotheses` (`{text, score, acoustic_score, lm_score}`) and monotonic `alignment` (`{token, start_sec, end_sec, confidence}`).
2. `ASREngine.redecode`:
   - Re-decoding with different `DecodeConfig` (`greedy` vs `beam`, `blank_bias`, `temperature`, `lm_weight`) succeeds in `< 10 ms` (verified with `decode_ms` and wall-clock timer after warm-up).
   - Unknown `utterance_id` raises `KeyError`.
   - Evicted `utterance_id` (when `len > max_cache_size`) raises `KeyError`.
   - Empty/short audio produces empty `text=""`, `alignment=[]`, and valid cached `utterance_id` without crashing.
3. CLI integration via `subprocess.run([sys.executable, "-m", "asr", ...])`:
   - `--help` and `<subcommand> --help` (including `serve --help` without `asr/server.py`).
   - `generate` → creates `train.jsonl`, `val.jsonl`, WAVs.
   - `train` → creates `best.pt`, `latest.pt`.
   - `eval --json` → valid JSON with `cer`, `mer`, `confusion_pairs`, `rtf`.
   - `transcribe --wav ... --json` and `transcribe --tts オハヨウ --engine fast --json` and `transcribe --tts サクラ --preset chibi --json`.
   - `demo --out-dir <tmp> --epochs 1 --num-train 6 --num-val 2` → exits 0 and creates `<tmp>/best.pt`.
   - Error cases: missing checkpoint, missing WAV, corrupt WAV, unknown preset, missing manifest → non-zero exit code + helpful stderr.
