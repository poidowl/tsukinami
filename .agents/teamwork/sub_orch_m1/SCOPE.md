# Milestone M1 Scope

## Exclusive File Ownership
1. `.venv/` — Project-local Python 3.11 virtual environment (`uv venv .venv --python 3.11`) with CPU-only `torch` (`https://download.pytorch.org/whl/cpu`), `numpy`, `fastapi`, `uvicorn`, `python-multipart`, `pytest`, `httpx`.
2. `pyproject.toml` — Project metadata, dependencies, pytest config.
3. `.gitignore` — Ignore `.venv/`, `__pycache__/`, `*.pyc`, `checkpoints/`, `data/`, `.pytest_cache/`.
4. `asr/__init__.py` — Package exports & version.
5. `asr/config.py` — `AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig` with `.to_dict()` / `.from_dict()`.
6. `asr/audio.py` — `load_wav`, `save_wav`, `resample`, `detect_vad`, `apply_corruption` (white/pink noise at target SNR dB, telephone/arbitrary band-pass filter, speed perturbation, gain, deterministic seeding; clean `FileNotFoundError`/`ValueError` on invalid inputs; optional `ffmpeg` fallback for non-WAV formats).
7. `asr/features.py` — Pure-NumPy pre-emphasis, Hann STFT, Slaney Mel filterbank, `extract_log_mel`, `extract_mfcc` (with optional deltas), per-utterance CMVN, `spec_augment` (freq/time masking).
8. `asr/tokenizer.py` — `Tokenizer(mode="kana"|"phoneme"|"ascii")` built on `kotoba.to_kata` & `kotoba.split_moras`, `<blank>=0`, `encode`, `decode(collapse_ctc=...)`, `to_dict`/`from_dict`.
9. `tests/test_asr_dsp.py` — Thorough unit tests run via `.venv/bin/pytest tests/test_asr_dsp.py`.

## Forbidden Paths
- All existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `index.html`, `toybox.html`, etc.).
- `tests_e2e/`.

## Exact Interface Contracts (from PROJECT.md)
- `AudioConfig(sample_rate=16000, n_fft=512, win_length=400, hop_length=160, n_mels=64, f_min=80.0, f_max=7600.0, preemphasis=0.97, cmvn=True)`
- `ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=192, num_layers=2, dropout=0.1, num_heads=4, conv_kernel_size=15)`
- `TrainConfig(epochs=20, batch_size=16, lr=3e-3, weight_decay=1e-4, grad_clip=5.0, seed=42, use_spec_augment=True, checkpoint_dir="checkpoints")`
- `DecodeConfig(method="beam", beam_width=8, temperature=1.0, blank_bias=0.0, lm_weight=0.0, insertion_bonus=0.0)`
- `load_wav(path: str | Path, target_sr: int = 16000) -> tuple[np.ndarray, int]`
- `save_wav(path: str | Path, wav: np.ndarray, sr: int = 16000) -> None`
- `resample(wav: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray`
- `detect_vad(wav: np.ndarray, sr: int = 16000, frame_ms: float = 20.0, threshold_db: float = -35.0, hangover_ms: float = 150.0) -> list[tuple[float, float]]`
- `apply_corruption(wav: np.ndarray, sr: int, *, snr_db: float | None = None, noise_type: str = "white", band_limit: tuple[float, float] | None = None, speed: float = 1.0, gain_db: float = 0.0, seed: int | None = None) -> np.ndarray`
- `extract_log_mel(wav: np.ndarray, cfg: AudioConfig | None = None) -> np.ndarray`
- `extract_mfcc(wav: np.ndarray, cfg: AudioConfig | None = None, n_mfcc: int = 13, include_deltas: bool = False) -> np.ndarray`
- `spec_augment(mel: np.ndarray, freq_mask_param: int = 8, time_mask_param: int = 20, num_freq_masks: int = 2, num_time_masks: int = 2, seed: int | None = None) -> np.ndarray`
- `Tokenizer(mode: str = "kana", vocab: list[str] | None = None)` with `blank_id == 0`, `vocab_size: int`, `encode(text: str) -> list[int]`, `decode(ids: Sequence[int], collapse_ctc: bool = False) -> str`, `to_dict() -> dict`, `Tokenizer.from_dict(d: dict) -> Tokenizer`.
