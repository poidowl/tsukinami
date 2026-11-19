# Explorer 3 Handoff: `asr/train.py` & `tests/test_asr_models.py` Design

## 1. Existing Module Interfaces & Verified Runtime Facts

### Environment (Verified via `.venv/bin/python`)
- **PyTorch**: `2.15.0+cpu`, **NumPy**: `2.4.6`
- **CPU**: `os.cpu_count() == 2`, default `torch.get_num_threads() == 2`, `torch.get_num_interop_threads() == 2`
- **Verified PyTorch 2.15 behaviors**:
  1. `nn.CTCLoss(blank=0, reduction="mean", zero_infinity=True)` accepts **2D padded targets `(B, L_max)`** directly alongside `log_probs.transpose(0, 1)` `(T', B, V)`, `out_lengths` `(B,)`, and `target_lengths` `(B,)`. When `out_lengths[i] < target_lengths[i]` (or repeated tokens exceed available frames), `zero_infinity=True` zeros both the invalid item's loss and its gradients without producing `NaN`/`inf`.
  2. `torch.load(path, map_location=device, weights_only=True)` succeeds cleanly on checkpoints containing `model_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, and plain JSON-like Python dicts/lists/primitives (no custom dataclass or `Path` instances).

### Exact Signatures of Consumed M1/M2/M4 Modules
- **`asr/config.py`**:
  - `AudioConfig(sample_rate=16000, n_fft=512, win_length=400, hop_length=160, n_mels=64, ...)` — `.to_dict()` / `.from_dict(d)`
  - `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=192, num_layers=2, dropout=0.1, num_heads=4, conv_kernel_size=15)` — `.to_dict()` / `.from_dict(d)`
  - `TrainConfig(epochs=20, batch_size=16, lr=3e-3, weight_decay=1e-4, grad_clip=5.0, seed=42, use_spec_augment=True, checkpoint_dir="checkpoints")` — `.to_dict()` / `.from_dict(d)`
- **`asr/tokenizer.py`**:
  - `Tokenizer(mode="kana", vocab=None)` — `.blank_id == 0`, `.vocab_size`, `.to_dict()`, `Tokenizer.from_dict(d)`
- **`asr/dataset.py`**:
  - `ASRManifestDataset(manifest_path, audio_cfg=None, tokenizer=None, augment=False)` — returns dict with `feats [T, F]`, `feat_length`, `targets [L]`, `target_length`, `text`, `audio_path` (defaults to `allow_empty_targets=False`).
  - `collate_asr_batch(items)` — returns:
    - `feats`: `torch.float32 [B, T_max, F]` (zero-padded)
    - `feat_lengths`: `torch.long [B]`
    - `targets`: `torch.long [B, L_max]` (zero-padded)
    - `target_lengths`: `torch.long [B]`
    - `texts`: `list[str]`
- **`asr/decoding.py`**:
  - `greedy_decode(log_probs: np.ndarray, tokenizer: Tokenizer, *, temperature=1.0, blank_bias=0.0) -> dict` returning `{"text", "token_ids", "score"}`. Expects 2D `(T_valid, V)` NumPy array.
- **`asr/metrics.py`**:
  - `compute_cer(refs: Sequence[str], hyps: Sequence[str], *, normalize_kana: bool = False) -> dict` returning `{"cer", "substitutions", "deletions", "insertions", "ref_len"}`.
- **`asr/synth_data.py`**:
  - `synthesize_fast_kotoba(text, *, sr=16000, f0_scale=1.0, fscale=1.0, rate=1.0, snr_db=None, seed=None) -> tuple[np.ndarray, list[dict]]`
  - `generate_dataset(out_dir, *, num_train=200, num_val=40, engine="fast", seed=42, presets=None) -> dict[str, Path]` returning `{"train": Path, "val": Path}`.

---

## 2. Detailed Design for `asr/train.py`

### Public Exports (`__all__`)
- `train_asr`
- `load_checkpoint`

### Function Signatures
```python
def load_checkpoint(path: str | Path, device: str = "cpu") -> dict[str, Any]: ...

def train_asr(
    train_manifest: str | Path,
    val_manifest: str | Path,
    *,
    audio_cfg: AudioConfig | None = None,
    model_cfg: ModelConfig | None = None,
    train_cfg: TrainConfig | None = None,
    tokenizer: Tokenizer | None = None,
    resume_from: str | Path | None = None,
) -> dict[str, Any]: ...
```

### Key Implementation Details

1. **CPU Threading & Determinism**:
   - `_seed_everything(train_cfg.seed)`: seeds `random.seed`, `np.random.seed`, and `torch.manual_seed`.
   - CPU threads: call `torch.set_num_threads(min(2, os.cpu_count() or 1))`.
   - **Important**: Do **NOT** call `torch.set_num_interop_threads(...)` inside `train_asr` — PyTorch raises `RuntimeError` if called more than once in a process (which breaks multi-test pytest runs).

2. **Config Validation & `DataLoader` Setup**:
   - Resolve defaults (`AudioConfig()`, `ModelConfig()`, `TrainConfig()`, `Tokenizer("kana")`).
   - Validate `audio_cfg.n_mels == model_cfg.n_mels` (raise `ValueError` on mismatch).
   - Build datasets:
     - `train_ds = ASRManifestDataset(train_manifest, audio_cfg=audio_cfg, tokenizer=tokenizer, augment=train_cfg.use_spec_augment)`
     - `val_ds = ASRManifestDataset(val_manifest, audio_cfg=audio_cfg, tokenizer=tokenizer, augment=False)`
   - Build `DataLoader`s:
     - `gen = torch.Generator(); gen.manual_seed(train_cfg.seed)`
     - `train_loader = DataLoader(train_ds, batch_size=train_cfg.batch_size, shuffle=True, num_workers=0, collate_fn=collate_asr_batch, generator=gen, drop_last=False)`
     - `val_loader = DataLoader(val_ds, batch_size=train_cfg.batch_size, shuffle=False, num_workers=0, collate_fn=collate_asr_batch, drop_last=False)`
     - `num_workers=0` prevents fork overhead and thread oversubscription on 2 vCPUs and ensures deterministic iteration.
     - `drop_last=False` ensures tiny datasets (e.g., 4 utterances with `batch_size=16`) still produce batches.

3. **CTC Loss Invocation**:
   - `criterion = nn.CTCLoss(blank=tokenizer.blank_id, reduction="mean", zero_infinity=True)`
   - Per batch:
     ```python
     log_probs, out_lengths = model(feats, feat_lengths)   # (B, T', V), (B,)
     loss = criterion(log_probs.transpose(0, 1), targets, out_lengths, target_lengths)
     ```
   - Guard: `if not torch.isfinite(loss): continue` (belt-and-suspenders alongside `zero_infinity=True`).
   - Accumulate epoch loss weighted by batch size (`loss_sum += float(loss.item()) * bsz`, `sample_count += bsz`).

4. **Optimizer, LR Scheduler, & Gradient Clipping**:
   - `optimizer = torch.optim.AdamW(model.parameters(), lr=train_cfg.lr, weight_decay=train_cfg.weight_decay)`
   - `scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, train_cfg.epochs), eta_min=train_cfg.lr * 0.01)`
   - **Why `CosineAnnealingLR` (per-epoch) over `OneCycleLR`**: `OneCycleLR` raises `ValueError` if resumed with a higher `train_cfg.epochs` than originally configured. `CosineAnnealingLR` stepped once per epoch resumes cleanly across arbitrary new `train_cfg.epochs` by updating `scheduler.T_max = max(1, train_cfg.epochs)`.
   - Per step:
     ```python
     optimizer.zero_grad(set_to_none=True)
     loss.backward()
     if train_cfg.grad_clip > 0.0:
         torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=train_cfg.grad_clip)
     optimizer.step()
     ```
   - Record `epoch_lr = float(optimizer.param_groups[0]["lr"])` before calling `scheduler.step()` at the end of each epoch.

5. **Validation Loop (CTC Loss + Greedy CER)**:
   - `model.eval()` inside `with torch.no_grad():`
   - For each batch:
     - Forward pass -> compute batch CTC loss (weighted average by batch size).
     - Convert `lp_np = log_probs.detach().cpu().numpy()`, `out_lens = out_lengths.detach().cpu().tolist()`.
     - For `i, ref_text in enumerate(batch["texts"])`:
       - **Crucial slicing**: `lp_i = lp_np[i, : out_lens[i]]` (never pass padded trailing frames to `greedy_decode`).
       - `hyp_text = greedy_decode(lp_i, tokenizer)["text"]`
       - Collect `(all_refs, all_hyps)`.
   - `val_cer = float(compute_cer(all_refs, all_hyps)["cer"])`.
   - History entry per epoch:
     ```python
     {
         "epoch": int(epoch),
         "train_loss": float(train_loss),
         "val_loss": float(val_loss),
         "val_cer": float(val_cer),
         "lr": float(epoch_lr),
     }
     ```

6. **Checkpoint Schema & Atomic Save**:
   - Store **only** PyTorch tensors and plain Python dicts/lists/primitives (no `Path` or dataclass instances) so `weights_only=True` always succeeds:
     ```python
     ckpt = {
         "epoch": int(epoch),
         "best_val_cer": float(best_val_cer),
         "model_state_dict": model.state_dict(),
         "optimizer_state_dict": optimizer.state_dict(),
         "scheduler_state_dict": scheduler.state_dict(),
         "model_config": model_cfg.to_dict(),
         "audio_config": audio_cfg.to_dict(),
         "audio_cfg": audio_cfg.to_dict(),   # alias for PROJECT.md line 166 compatibility
         "train_config": train_cfg.to_dict(),
         "tokenizer": tokenizer.to_dict(),
         "history": list(history),
     }
     ```
   - **Atomic write**: save to `path.with_suffix(".pt.tmp")` then `os.replace(tmp_path, path)` so interrupted writes never corrupt `best.pt` or `latest.pt`.
   - **`best.pt` selection rule**: Track `best_val_cer` and `best_val_loss` (tie-breaker when CER is equal, e.g., both 1.0 in early epochs). Update and save `best.pt` whenever `(val_cer < best_val_cer) or (val_cer == best_val_cer and val_loss < best_val_loss) or (not best_path.exists())`.
   - Always save `latest.pt` at the end of every epoch.

7. **`load_checkpoint(path, device="cpu")`**:
   - Validate `p = Path(path)` exists (`FileNotFoundError`) and is not a directory (`ValueError`).
   - Load via `torch.load(p, map_location=device, weights_only=True)` (fallback to `weights_only=False` only on `pickle.UnpicklingError`/`RuntimeError` if loading an external legacy checkpoint).
   - Validate result is a `dict` containing required keys (`model_state_dict`, `model_config`, `tokenizer`).
   - Normalize `audio_config` / `audio_cfg` alias if only one is present.

8. **`resume_from` Behavior**:
   - Load checkpoint with `load_checkpoint(resume_from, device="cpu")`.
   - Validate `model_cfg.to_dict() == ckpt["model_config"]` and `tokenizer.vocab_size == len(ckpt["tokenizer"]["vocab"])` (raise `ValueError` on incompatible resume).
   - Load `model.load_state_dict(ckpt["model_state_dict"])`, `optimizer.load_state_dict(ckpt["optimizer_state_dict"])`, and `scheduler.load_state_dict(ckpt["scheduler_state_dict"])` (if present); update `scheduler.T_max = max(1, train_cfg.epochs)`.
   - Restore `history = list(ckpt.get("history", []))`, `best_val_cer = float(ckpt.get("best_val_cer", float("inf")))`, `best_val_loss` (min `val_loss` among history entries matching `best_val_cer`, or `float("inf")`).
   - `start_epoch = int(ckpt["epoch"]) + 1`.
   - **Case `start_epoch <= train_cfg.epochs`** (e.g., `ckpt["epoch"] == 3`, `train_cfg.epochs == 5`): run epochs `4..5`, appending to `history` (final epochs `[1, 2, 3, 4, 5]`).
   - **Case `train_cfg.epochs <= ckpt["epoch"]`**: loop runs 0 epochs without error; ensure `latest.pt` and `best.pt` exist in `checkpoint_dir` (save resumed snapshot if missing) and return summary dict.

9. **Summary Dict Returned by `train_asr`**:
   ```python
   {
       "best_checkpoint": str(best_path),
       "latest_checkpoint": str(latest_path),
       "best_val_cer": float(best_val_cer),
       "final_train_loss": float(history[-1]["train_loss"]) if history else 0.0,
       "final_val_loss": float(history[-1]["val_loss"]) if history else 0.0,
       "final_val_cer": float(history[-1]["val_cer"]) if history else 1.0,
       "epochs_completed": int(history[-1]["epoch"]) if history else 0,
       "history": history,
   }
   ```

---

## 3. Detailed Design for `tests/test_asr_models.py`

Target total runtime: **~5–10 seconds** on 2 vCPUs.

1. **`test_build_model_factory_and_metadata`**:
   - Parametrized over `("cnn_bigru", "conformer_lite")`:
     - Builds model via `build_model(cfg, vocab_size=tok.vocab_size)`.
     - Asserts `model.subsampling_factor == 4`.
     - Asserts `model.output_frame_stride_ms(AudioConfig()) == pytest.approx(40.0)` and scales with `hop_length=80` (`20.0`).
   - Unknown arch (via `SimpleNamespace(arch="unknown", ...)` or mutated config) raises `ValueError`.
   - `vocab_size <= 0` raises `ValueError`.

2. **`test_model_forward_shapes_and_log_probs`** (parametrized over both archs):
   - Random `(B=3, T=101, F=64)` with `feat_lengths = tensor([101, 73, 40])`.
   - Verifies `log_probs.shape == (3, T', V)`, `out_lengths.dtype == torch.long`, `out_lengths.max().item() == T'`, `out_lengths` monotonic with `feat_lengths`, all finite, and `log_probs.exp().sum(dim=-1)` is `1.0` (`atol=1e-5`).
   - Short input edge case (`T=8`, `feat_lengths=tensor([8, 6])`): runs cleanly with `out_lengths >= 1`.

3. **`test_padding_mask_invariance`** (parametrized over both archs):
   - Model in `.eval()` mode.
   - `feats1` `(B=2, T=80, F=64)`, `feat_lengths = tensor([80, 40])`.
   - `feats2 = feats1.clone()`; mutate padded region `feats2[1, 40:, :] = 99.0`.
   - **Note for model implementers**: `Conv2dSubsampling` MUST zero-mask padded input frames (`t >= feat_lengths[i]`) before the 2D convolutions (and/or mask after convs) so the 3×3 conv receptive field does not bleed padded values into the last valid frame!
   - Assert `torch.allclose(lp1[1, :out_lens1[1]], lp2[1, :out_lens2[1]], atol=1e-5)` and `torch.equal(out_lens1, out_lens2)`.

4. **`test_gradient_flow_with_ctc_loss`** (parametrized over both archs):
   - Forward -> `nn.CTCLoss(blank=0, zero_infinity=True)` -> `loss.backward()`.
   - Assert `torch.isfinite(loss)` and `loss.item() > 0`.
   - Assert every trainable parameter has `p.grad is not None`, all finite, and total grad norm > 0.

5. **`test_train_asr_overfit_sanity_cpu`**:
   - Synthesize 4 distinct short Japanese utterances (`["アオ", "イヌ", "ウミ", "エキ"]` or `["オハヨウ", "コンニチハ", "アリガトウ", "サヨウナラ"]`) via `synthesize_fast_kotoba(..., snr_db=None, seed=100+i)` -> save WAVs + `train.jsonl` (and reuse as `val.jsonl` for pure overfit verification).
   - Config: `ModelConfig(arch="cnn_bigru", hidden_size=96, num_layers=2, dropout=0.0)`, `TrainConfig(epochs=35, batch_size=4, lr=5e-3, use_spec_augment=False, seed=42, checkpoint_dir=str(tmp_path / "ckpt"))`.
   - Runs in ~2–3 s on 2 vCPUs.
   - Assertions:
     - `final_train_loss < 0.5 * history[0]["train_loss"]` (>50% CTC loss reduction).
     - `best_val_cer < 0.5` and `best_val_cer < history[0]["val_cer"]` (significant greedy CER drop).
     - `Path(result["best_checkpoint"]).is_file()` and `Path(result["latest_checkpoint"]).is_file()`.

6. **`test_checkpoint_exact_logit_reproduction_and_resume`**:
   - Train 2 epochs (`epochs=2`, small `hidden_size=48`) on the 4-utterance dataset.
   - Load `best.pt` via `load_checkpoint(..., device="cpu")`, verify all required keys (`model_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, `model_config`, `audio_config`, `tokenizer`, `history`, `epoch`, `best_val_cer`).
   - Reconstruct model, run `.eval()` forward on fixed input, save directly and reload -> verify `torch.allclose(lp_a, lp_b, atol=1e-5)` (exact logit reproduction).
   - Also verify deterministic `load_checkpoint` reproduction against a fresh model initialized with the loaded `model_state_dict`.
   - Resume from `latest.pt` with `epochs=4`:
     - Verify `[h["epoch"] for h in resumed["history"]] == [1, 2, 3, 4]`.
     - Verify `resumed["history"][:2] == initial["history"]`.
     - Verify `resumed["best_val_cer"] <= initial["best_val_cer"]`.
   - Resume with `epochs=2` (<= `ckpt["epoch"] == 4`): succeeds cleanly without extra epochs, `epochs_completed == 4`.
   - `load_checkpoint(tmp_path / "missing.pt")` raises `FileNotFoundError`.

7. **`test_train_asr_conformer_lite_smoke`**:
   - Train 2 epochs with `ModelConfig(arch="conformer_lite", hidden_size=64, num_layers=1, num_heads=4, conv_kernel_size=7, dropout=0.0)` on the tiny 4-utterance dataset; verify finite loss and valid `best.pt` loadable via `load_checkpoint`.
