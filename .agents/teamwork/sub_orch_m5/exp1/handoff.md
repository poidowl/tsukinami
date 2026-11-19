# Explorer 1 (`exp1`) Handoff — `asr/inference.py` (`ASREngine`) Design

## 1. Exact Checkpoint Schema (`asr/train.py`)

### Keys Written by `_build_ckpt()` (`asr/train.py:321-335`)
Every `best.pt` and `latest.pt` saved by `train_asr` contains:
- `"epoch"`: `int` (1-indexed epoch number)
- `"best_val_cer"`: `float` (may be `float("inf")` if initialized/unimproved — sanitize before JSON!)
- `"model_state_dict"`: `OrderedDict[str, torch.Tensor]`
- `"optimizer_state_dict"`: `dict`
- `"scheduler_state_dict"`: `dict`
- `"model_config"`: `dict[str, Any]` (`ModelConfig.to_dict()`)
- `"audio_config"`: `dict[str, Any]` (`AudioConfig.to_dict()`)
- `"audio_cfg"`: `dict[str, Any]` (copy of `AudioConfig.to_dict()`)
- `"train_config"`: `dict[str, Any]` (`TrainConfig.to_dict()`)
- `"tokenizer"`: `dict[str, Any]` (`Tokenizer.to_dict()` -> `{"mode", "vocab", "blank_token"}`)
- `"history"`: `list[dict[str, Any]]` where each element is `{"epoch": int, "train_loss": float, "val_loss": float, "val_cer": float, "lr": float}`

### Behavior of `load_checkpoint(path, device="cpu")` (`asr/train.py:86-125`)
- Validates file existence (`FileNotFoundError`) and non-directory (`ValueError`).
- Loads with `weights_only=True`, falling back to `weights_only=False` on `(pickle.UnpicklingError, RuntimeError)`; wraps corrupt file errors (`EOFError`, `UnpicklingError`, `BadZipFile`, `RuntimeError`, `OSError`) into `ValueError`.
- Validates `isinstance(ckpt, dict)` and `_REQUIRED_CKPT_KEYS = ("model_state_dict", "model_config", "tokenizer")`.
- Aliases `"audio_config"` ↔ `"audio_cfg"` if only one is present. Note that neither key is in `_REQUIRED_CKPT_KEYS`.

### `ASREngine.from_checkpoint(path, lm=None, *, device="cpu", max_cache_size=32)` Loading Rules
1. Call `ckpt = load_checkpoint(path, device=device)`.
2. Parse `model_cfg`:
   - If `isinstance(ckpt["model_config"], ModelConfig)` use directly; else `ModelConfig.from_dict(ckpt["model_config"])`.
3. Parse `audio_cfg`:
   - Look up `raw_audio = ckpt.get("audio_config") or ckpt.get("audio_cfg")`.
   - If `isinstance(raw_audio, AudioConfig)` use directly; elif `raw_audio is not None`: `AudioConfig.from_dict(raw_audio)`; else fallback `AudioConfig(n_mels=model_cfg.n_mels)`.
4. Parse `tokenizer`:
   - If `isinstance(ckpt["tokenizer"], Tokenizer)` use directly; else `Tokenizer.from_dict(ckpt["tokenizer"])`.
5. Optional LM:
   - If `lm is None` and `"lm"` in `ckpt` and `ckpt["lm"] is not None`: `lm = CharNgramLM.from_dict(ckpt["lm"])` (if dict) or use directly.
6. Build and load model:
   - `model = build_model(model_cfg, vocab_size=tokenizer.vocab_size)`
   - `model.load_state_dict(ckpt["model_state_dict"])`
   - `model.to(device)` and `model.eval()`
7. Extract `checkpoint_meta`:
   ```python
   checkpoint_meta = {
       "checkpoint_path": str(Path(path)),
       "epoch": ckpt.get("epoch"),
       "best_val_cer": ckpt.get("best_val_cer"),
       "train_config": ckpt.get("train_config"),
       "history": [dict(entry) for entry in ckpt.get("history", [])],
   }
   ```
8. Return `cls(model, audio_cfg, model_cfg, tokenizer, lm=lm, checkpoint_meta=checkpoint_meta, max_cache_size=max_cache_size)`.

---

## 2. Edge-Case Audit (Audio, Features, Models, Decoding)

| Edge Case | Upstream Module Behavior | Required `ASREngine` Handling |
|---|---|---|
| **Empty audio (`len == 0`)** | `resample` returns empty `(0,)`; `detect_vad` returns `[]`; `extract_log_mel` zero-pads to `win_length=400` and returns `(1, n_mels)` of zeros (which would run the NN and could emit spurious tokens!). | **Short-circuit before NN**: set `duration_sec = 0.0`, `log_probs = np.empty((0, vocab_size), dtype=np.float32)`, cache it under `utterance_id`, decode (returns `""` / `[{"text": "", "score": 0.0, "acoustic_score": 0.0, "lm_score": 0.0}]`), `alignment = []`, `rtf = 0.0`. If `include_visuals=True`, return `waveform=[]`, `log_mel=[]`, `ctc_posteriors={"times_sec": [], "top_tokens": [], "probs": []}`, `vad_segments=[]`. |
| **Very short audio (e.g. 1–399 samples)** | `stft_power` (`asr/features.py:63-67`) zero-pads to `win_length=400`, producing `T = 1` frame `(1, n_mels)`. `Conv2dSubsampling` (`asr/models/subsampling.py:54-129`) uses `k=3, s=2, p=1`, so `T=1 -> T1=1 -> T2=1` (`out_lengths=[1]`). Both `CNNBiGRUCTC` (`pack_padded_sequence`) and `ConformerLiteCTC` (frame-wise `LayerNorm`, explicitly designed for `(B=1, T'=1)`) succeed cleanly and return `(1, 1, V)`. | Works out of the box once `feats` has `T >= 1`. Always slice `log_probs = lp_tensor[0, :valid_len].cpu().numpy()` where `valid_len = int(out_lengths[0].item())`. |
| **Non-16kHz sample rates** | `resample(wav, orig_sr, target_sr)` (`asr/audio.py:60-74`) validates `orig_sr > 0`, `target_sr > 0` (rejects `bool`/`<=0`), and FFT-resamples to `max(1, round(n * target_sr / orig_sr))`. | Validate `sr` (`not isinstance(sr, bool) and isinstance(sr, int) and sr > 0`, else `ValueError`). If `sr != self.audio_cfg.sample_rate`, call `resample(mono, sr, self.audio_cfg.sample_rate)`. Compute `duration_sec = float(wav_res.size) / float(self.audio_cfg.sample_rate)`. |
| **Multi-channel / non-float32 / list inputs** | `_to_mono_float32` (`asr/audio.py:23-31`) converts `np.asarray(wav, dtype=np.float32)`, averages 2D `(N, C)` across `axis=-1` (`C > 0`), raises `ValueError` on `C == 0`, 0D, or `ndim >= 3`. | Add `_prepare_waveform(wav)` helper using the same rules: accept 1D array-like or 2D `(N, C)` with `C > 0`, cast to `float32`, mix to mono; raise `ValueError` on 0D, `>=3D`, or 0-channel arrays. |
| **NaN / +Inf / -Inf in `wav`** | **CRITICAL GAP in M1**: Neither `resample`, `detect_vad`, nor `extract_log_mel` sanitizes NaN/Inf! A single NaN poisons FFT resampling, produces NaN `log_mel` -> NaN `log_probs`, and causes `asr/decoding.py:62` to raise `ValueError("log_probs must not contain NaN or +inf")`. | In `_prepare_waveform(wav)`, **before** resampling/VAD/features: if `not np.all(np.isfinite(mono))`, replace via `np.nan_to_num(mono, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32, copy=False)`. |
| **Greedy vs Beam return schema** | `greedy_decode` returns `{"text", "token_ids", "score"}`. `prefix_beam_search` returns `list[{"text", "score", "acoustic_score", "lm_score"}]` (no `token_ids`). | Unify in a private `_decode_and_align(log_probs, decode_cfg, frame_stride_ms)` helper: for `greedy`, wrap into `hypotheses = [{"text": res["text"], "score": float(res["score"]), "acoustic_score": float(res["score"]), "lm_score": 0.0}]` and use `res["token_ids"]`; for `beam`, call `prefix_beam_search` and get `token_ids = self.tokenizer.encode(top_text)` if `top_text` else `[]`. Wrap `viterbi_align` in `try ... except ValueError: alignment = []` as a safety net for degenerate/unalignable edge cases. |
| **Model training mode / grad** | `model.eval()` and `torch.no_grad()` needed to disable dropout and autograd overhead. | Call `self.model.eval()` in `__init__` and wrap forward pass in `with torch.no_grad():`. |

---

## 3. Visual Payload Specification (`include_visuals=True`)

All values must be **pure Python JSON-serializable** (`list`, `dict`, `float`, `str`, `int` — no NumPy scalars/arrays, no `NaN`/`Inf`) and **bounded in size** for M6 Canvas 2D rendering:

1. **`waveform`**: `list[float]`
   - Downsample `wav_16k` to at most `MAX_WAVEFORM_POINTS = 2000` points using evenly spaced indices `np.linspace(0, n - 1, MAX_WAVEFORM_POINTS, dtype=np.int64)` when `n > MAX_WAVEFORM_POINTS`.
   - Round to 5 decimal places: `[round(float(x), 5) for x in ds]` (or `np.round(ds, 5).tolist()`).
   - Empty audio -> `[]`.

2. **`log_mel`**: `list[list[float]]`
   - Extracted `mel` has shape `(T, audio_cfg.n_mels)`.
   - Preserve `n_mels` (64) strictly; bound time axis to `MAX_MEL_FRAMES = 600` (covers up to 6.0s at 10ms hop without downsampling; for longer audio, evenly sample `T` indices via `np.linspace(0, T - 1, MAX_MEL_FRAMES, dtype=np.int64)`).
   - Convert via `np.round(mel_vis, 4).tolist()` -> shape `(T_vis, n_mels)`.
   - Empty audio -> `[]`.

3. **`ctc_posteriors`**: `dict[str, Any]` with keys:
   - `"times_sec"`: `list[float]` of length `T'_vis` (bound to `MAX_POSTERIOR_FRAMES = 400`, which covers 16s at 40ms stride without downsampling). Values: `round(float(idx * stride_s), 4)`.
   - `"top_tokens"`: `list[str]` of length `K = min(top_k_tokens, vocab_size)` (default `top_k_tokens = 12`). Always include `tokenizer.blank_token` (`"<blank>"`, id `0`) first, then select the top `K - 1` non-blank token IDs ranked by `max_t probs[t, id]` descending (tie-broken by token ID ascending for determinism).
   - `"probs"`: `list[list[float]]` of shape `(T'_vis, K)` where each entry is `round(float(exp(log_probs[t, tok_id])), 4)` clipped to `[0.0, 1.0]`.
   - Empty audio (`T' == 0`) -> `{"times_sec": [], "top_tokens": [], "probs": []}`.

4. **`vad_segments`**: `list[list[float]]`
   - From `detect_vad(wav_16k, sr=self.audio_cfg.sample_rate)`.
   - Convert tuples to lists: `[[round(float(s), 4), round(float(e), 4)] for s, e in segs]`.
   - Empty audio -> `[]`.

---

## 4. `ASREngine.info()` Schema

Pure-Python JSON-serializable dictionary covering checkpoint metadata, model/audio config, tokenizer/vocab, LM status, cache state, and training history (directly consumable by M6 `GET /api/info`):

```python
{
    "arch": self.model_cfg.arch,                       # "cnn_bigru" | "conformer_lite"
    "num_parameters": int(sum(p.numel() for p in self.model.parameters())),
    "subsampling_factor": int(getattr(self.model, "subsampling_factor", 4)),
    "frame_stride_ms": float(self.frame_stride_ms),    # e.g. 40.0
    "model_config": self.model_cfg.to_dict(),
    "audio_config": self.audio_cfg.to_dict(),
    "tokenizer": {
        "mode": self.tokenizer.mode,
        "vocab_size": self.tokenizer.vocab_size,
        "blank_id": self.tokenizer.blank_id,
        "vocab": list(self.tokenizer.vocab),
    },
    "has_lm": self.lm is not None,
    "cache_size": len(self._cache),
    "max_cache_size": self.max_cache_size,
    "checkpoint": {
        "path": meta.get("checkpoint_path"),           # str | None
        "epoch": meta.get("epoch"),                    # int | None
        "best_val_cer": _finite_float_or_none(meta.get("best_val_cer")),
        "train_config": meta.get("train_config"),      # dict | None
    },
    "history": list(meta.get("history", [])),          # list[{"epoch", "train_loss", "val_loss", "val_cer", "lr"}]
}
```

---

## 5. `ASREngine` Class & Caching Architecture

- Constructor:
  ```python
  class ASREngine:
      def __init__(
          self,
          model: nn.Module,
          audio_cfg: AudioConfig,
          model_cfg: ModelConfig,
          tokenizer: Tokenizer,
          *,
          lm: CharNgramLM | None = None,
          checkpoint_meta: dict[str, Any] | None = None,
          max_cache_size: int = 32,
          device: str = "cpu",
      ) -> None:
  ```
  - Validate `max_cache_size` (`int`, not `bool`, `>= 1`).
  - Set `self.model.to(self.device)` and `self.model.eval()`.
  - Compute `self.frame_stride_ms = float(model.output_frame_stride_ms(audio_cfg))` if method exists else `4.0 * 1000.0 * audio_cfg.hop_length / audio_cfg.sample_rate`.
  - Initialize `self._cache: OrderedDict[str, _CachedUtterance] = OrderedDict()` where `_CachedUtterance` is a lightweight `@dataclass(slots=True)` storing `(log_probs: np.ndarray, duration_sec: float, frame_stride_ms: float)`.
- `transcribe(wav, sr=16000, decode_cfg=None, *, include_visuals=False) -> dict`:
  - Default `decode_cfg = DecodeConfig()` if `None`.
  - Validate `decode_cfg` is a `DecodeConfig`.
  - Start timer `t0 = time.perf_counter()`.
  - Prepare & sanitize waveform, resample if `sr != audio_cfg.sample_rate`.
  - Compute `log_probs` (short-circuit on empty audio; otherwise `extract_log_mel` -> tensor `(1, T, F)` -> `torch.no_grad()` -> `model(feats, feat_lengths)` -> slice `lp[0, :out_len].cpu().numpy()`).
  - Cache under `utterance_id = uuid.uuid4().hex[:16]`, evicting oldest with `popitem(last=False)` when `len(self._cache) > self.max_cache_size`.
  - Decode & align via `_decode_and_align`.
  - Compute `rtf = (time.perf_counter() - t0) / duration_sec if duration_sec > 0.0 else 0.0`.
  - Return base dict (`text`, `hypotheses`, `alignment`, `rtf`, `duration_sec`, `utterance_id`), plus visual keys if `include_visuals=True`.
- `redecode(utterance_id: str, decode_cfg: DecodeConfig) -> dict`:
  - Validate `decode_cfg` is a `DecodeConfig`.
  - Lookup `utterance_id` in `self._cache`; raise `KeyError` if missing.
  - `self._cache.move_to_end(utterance_id)` for true LRU semantics.
  - Time decode + align (`decode_ms = (time.perf_counter() - t0) * 1000.0`).
  - Return `{"text", "hypotheses", "alignment", "utterance_id", "duration_sec", "decode_ms"}`.
