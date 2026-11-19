# M1 Explorer 1 Handoff — Environment, Packaging, `.gitignore`, `asr/__init__.py`, and `asr/config.py`

## 1. Repository & Baseline Inspection

- **Repository root**: `/home/antigravity/poidowl/tsukinami`
- **Git status**: On branch `main` (ahead of `origin/main` by 23 commits). Clean working tree except untracked `.agents/`, `PROJECT.md`, and `__pycache__/`.
- **Existing `.gitignore`**: None present in repo root.
- **Existing TTS baseline**: `python3 yomu.py --help` exits cleanly with code `0` and displays the full Japanese CLI help (`--preset {default,ossan,robot,horror,whisper,chibi,utahime,choir}`, etc.).
- **Tracked audio/output files**: No `.wav` or `out/*` files are tracked in git.
- **Constraint**: Do not modify any existing TTS files (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `uta_hakaru.py`, `*.html`, `*.sh`, etc.).

---

## 2. Environment & Tooling Inventory

| Resource | Observed Value |
|---|---|
| `uv` | `/usr/local/bin/uv` — `uv 0.13.8 (x86_64-unknown-linux-gnu)` |
| System Python 3.11 | `/usr/bin/python3.11` (`Python 3.11.2`), also `/usr/bin/python3` → `python3.11` |
| `ffmpeg` | `/usr/bin/ffmpeg` — `ffmpeg version 5.1.9-0+deb12u1` (available for optional non-WAV fallback in `asr/audio.py`) |
| CPU | `2` vCPUs (`nproc` = 2) |
| RAM / Swap | `7.8 GiB` total (`6.9 GiB` available), `0B` swap |
| Disk (`/`) | `3.9G` total, `3.9G` available |
| Disk (`/tmp`) | `10G` overlay, `9.8G` available |
| Disk (`/home/antigravity`) | `20G` total, `20G` available (`516M` used, 3%) |
| `uv` cache dir | `/home/antigravity/.cache/uv` (already exists on the 20G persistent volume) |

---

## 3. Exact `.venv` & CPU-Only PyTorch Installation Commands

### Critical Finding (`uv` Index Priority Footgun)
We tested `uv pip compile` with `--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple`. In `uv`, `--extra-index-url` has **higher** resolution priority than `--index-url` (opposite of `pip`), which caused `uv` to resolve CUDA `torch==2.15.0` (52 packages) instead of `torch==2.15.0+cpu` (10 packages).

### Verified Reliable Two-Step Setup Commands
Run from `/home/antigravity/poidowl/tsukinami` with `UV_CACHE_DIR=/home/antigravity/.cache/uv` so `/` never fills up:

```bash
# 1. Create project-local Python 3.11 virtual environment using system Python 3.11.2
UV_CACHE_DIR=/home/antigravity/.cache/uv uv venv .venv --python /usr/bin/python3.11

# 2. Install CPU-only PyTorch exclusively from the PyTorch CPU index (resolves torch==2.15.0+cpu, 10 pkgs, 0 CUDA pkgs)
UV_CACHE_DIR=/home/antigravity/.cache/uv uv pip install --python .venv/bin/python \
  --index-url https://download.pytorch.org/whl/cpu \
  torch

# 3. Install remaining runtime and test dependencies from PyPI (does not touch torch)
UV_CACHE_DIR=/home/antigravity/.cache/uv uv pip install --python .venv/bin/python \
  numpy fastapi uvicorn python-multipart pytest httpx
```

### Post-Install Verification Command
```bash
.venv/bin/python -c "
import torch, numpy, fastapi, uvicorn, multipart, pytest, httpx
print('torch:', torch.__version__, 'cuda:', torch.cuda.is_available())
assert '+cpu' in torch.__version__ or not torch.cuda.is_available()
print('numpy:', numpy.__version__)
print('ALL IMPORTS OK')
"
```

Resolved versions verified via dry-run `uv pip compile`:
- `torch==2.15.0+cpu` (with `filelock`, `jinja2`, `networkx`, `sympy`, `typing-extensions`)
- `numpy==2.4.6`, `fastapi==0.165.0`, `uvicorn==0.54.0`, `python-multipart==0.0.34`, `pytest==9.2.0`, `httpx==0.28.1`

---

## 4. Exact File Designs

### 4.1 `.gitignore`

```gitignore
# Virtual environments
.venv/

# Python bytecode & caches
__pycache__/
*.py[cod]
*$py.class
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Packaging artifacts
build/
dist/
*.egg-info/

# ASR runtime outputs, generated datasets & checkpoints
checkpoints/
data/
out/
```

### 4.2 `pyproject.toml`

Include standard `[project]` metadata, `[project.optional-dependencies]`, `[tool.pytest.ini_options]` with `pythonpath = ["."]` (so `.venv/bin/pytest` imports `asr` and `kotoba` reliably without requiring an editable install), and `[[tool.uv.index]]` + `[tool.uv.sources]` pinning `torch` to the CPU index for anyone who uses `uv sync`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "tsukinami-asr"
version = "0.1.0"
description = "Transparent, interactive Japanese ASR playground built on top of Tsukinami TTS"
readme = "PROJECT.md"
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.26",
    "torch>=2.2",
    "fastapi>=0.110",
    "uvicorn>=0.27",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "httpx>=0.27",
]

[tool.setuptools.packages.find]
include = ["asr*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-q"

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cpu" }
```

### 4.3 `asr/config.py`

Design four `@dataclass` classes matching the exact signatures and defaults in `PROJECT.md` / `SCOPE.md`, backed by a small internal `_ConfigBase` mixin providing `.to_dict()` and `.from_dict(d)` with strict validation:

#### Exact Dataclass Signatures & Defaults
1. `AudioConfig`:
   - `sample_rate: int = 16000`
   - `n_fft: int = 512`
   - `win_length: int = 400`
   - `hop_length: int = 160`
   - `n_mels: int = 64`
   - `f_min: float = 80.0`
   - `f_max: float = 7600.0`
   - `preemphasis: float = 0.97`
   - `cmvn: bool = True`
2. `ModelConfig`:
   - `arch: str = "cnn_bigru"`
   - `n_mels: int = 64`
   - `hidden_size: int = 192`
   - `num_layers: int = 2`
   - `dropout: float = 0.1`
   - `num_heads: int = 4`
   - `conv_kernel_size: int = 15`
3. `TrainConfig`:
   - `epochs: int = 20`
   - `batch_size: int = 16`
   - `lr: float = 3e-3`
   - `weight_decay: float = 1e-4`
   - `grad_clip: float = 5.0`
   - `seed: int = 42`
   - `use_spec_augment: bool = True`
   - `checkpoint_dir: str = "checkpoints"`
4. `DecodeConfig`:
   - `method: str = "beam"`
   - `beam_width: int = 8`
   - `temperature: float = 1.0`
   - `blank_bias: float = 0.0`
   - `lm_weight: float = 0.0`
   - `insertion_bonus: float = 0.0`

#### Serialization Contract (`.to_dict()` & `.from_dict(d)`)
- `to_dict(self) -> dict[str, Any]`: returns `dataclasses.asdict(self)` (pure JSON-compatible Python primitives).
- `@classmethod def from_dict(cls: type[T], data: Mapping[str, Any]) -> T`:
  - If `not isinstance(data, Mapping)`: raise `TypeError(f"Expected mapping for {cls.__name__}.from_dict, got {type(data).__name__}")`.
  - Compute `valid_keys = {f.name for f in fields(cls)}`.
  - Compute `unknown = sorted(set(data.keys()) - valid_keys)`.
  - If `unknown`: raise `ValueError(f"Unknown {cls.__name__} field(s): {unknown}")`.
  - Return `cls(**dict(data))` (omitted fields receive dataclass defaults; `__post_init__` validates all values).

#### Validation Rules (`__post_init__`, raising `ValueError` on invalid values)
Helper validators:
- `_check_int(name, val, *, min_val=None)` — rejects `bool` (`isinstance(val, bool)`) and non-`int`, enforces `val >= min_val`.
- `_check_float(name, val, *, min_val=None, max_val=None, min_inclusive=True, max_inclusive=True)` — rejects `bool`, non-real, `NaN`, `±inf`, and range violations.
- `_check_bool(name, val)` — requires `isinstance(val, bool)`.

Per-config rules:
- **`AudioConfig`**:
  - `sample_rate >= 1`, `n_fft >= 1`, `win_length >= 1`, `win_length <= n_fft`, `hop_length >= 1`, `n_mels >= 1`
  - `0.0 <= f_min < f_max <= sample_rate / 2.0`
  - `0.0 <= preemphasis < 1.0`
  - `cmvn` is `bool`
- **`ModelConfig`**:
  - `arch in {"cnn_bigru", "conformer_lite"}`
  - `n_mels >= 1`, `hidden_size >= 1`, `num_layers >= 1`, `num_heads >= 1`
  - `0.0 <= dropout < 1.0`
  - `conv_kernel_size >= 1` and `conv_kernel_size % 2 == 1` (odd kernel for symmetric padding)
  - When `arch == "conformer_lite"`: `hidden_size % num_heads == 0`
- **`TrainConfig`**:
  - `epochs >= 1`, `batch_size >= 1`
  - `lr > 0.0`, `weight_decay >= 0.0`, `grad_clip >= 0.0`
  - `seed` is `int` (not `bool`)
  - `use_spec_augment` is `bool`
  - `checkpoint_dir` is non-empty `str` (`isinstance(..., str) and bool(checkpoint_dir.strip())`)
- **`DecodeConfig`**:
  - `method in {"greedy", "beam"}`
  - `beam_width >= 1`
  - `temperature > 0.0`
  - `blank_bias` finite float
  - `lm_weight >= 0.0` (finite)
  - `insertion_bonus` finite float

### 4.4 `asr/__init__.py`

Keep `asr/__init__.py` free of `import torch` so importing `asr` or DSP submodules remains fast (~20 ms). Export `__version__` and the M1 public symbols:

```python
"""Tsukinami ASR — Transparent, interactive Japanese speech recognition playground."""

from asr.audio import apply_corruption, detect_vad, load_wav, resample, save_wav
from asr.config import AudioConfig, DecodeConfig, ModelConfig, TrainConfig
from asr.features import extract_log_mel, extract_mfcc, spec_augment
from asr.tokenizer import Tokenizer

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AudioConfig",
    "ModelConfig",
    "TrainConfig",
    "DecodeConfig",
    "load_wav",
    "save_wav",
    "resample",
    "detect_vad",
    "apply_corruption",
    "extract_log_mel",
    "extract_mfcc",
    "spec_augment",
    "Tokenizer",
]
```

---

## 5. Recommended Unit Tests for Config & Environment (in `tests/test_asr_dsp.py`)

- Round-trip `.to_dict()` → `json.dumps` → `json.loads` → `.from_dict()` equality for all four configs (`AudioConfig`, `ModelConfig`, `TrainConfig`, `DecodeConfig`).
- Partial dict passed to `.from_dict()` fills remaining defaults cleanly.
- Unknown key in `.from_dict({"bogus": 1})` raises `ValueError` for every config class.
- Invalid field values raise `ValueError`:
  - `AudioConfig`: `f_min >= f_max`, `f_max > sample_rate / 2`, `win_length > n_fft`, `preemphasis = 1.0`, `n_mels = 0`, `sample_rate = -1`.
  - `ModelConfig`: `arch = "unknown"`, `dropout = 1.0`, `conv_kernel_size = 4` (even), `arch = "conformer_lite"` with `hidden_size = 190, num_heads = 4` (not divisible).
  - `TrainConfig`: `epochs = 0`, `lr = 0.0`, `grad_clip = -1.0`, `checkpoint_dir = "  "`.
  - `DecodeConfig`: `method = "invalid"`, `beam_width = 0`, `temperature = 0.0`, `lm_weight = -0.1`, `blank_bias = float("nan")`.
- Package import check: `import asr` exposes `__version__` and all M1 exports.
