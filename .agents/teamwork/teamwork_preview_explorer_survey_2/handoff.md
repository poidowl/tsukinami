# Handoff Report — Environment & Runtime Survey (Survey Explorer 2)

**Summary**: `/home/antigravity/poidowl/tsukinami` runs in a **CPU-only, headless Debian 12 (x86_64) Linux sandbox** with **2 Intel Xeon Sapphire Rapids vCPUs (AVX-512 / AVX-VNNI / BF16)**, **7.8 GiB RAM (7.0 GiB available, no swap)**, and **20 GiB persistent disk** under `/home/antigravity`. It has **full outbound internet access** (via local proxy) to PyPI, HuggingFace, PyTorch CPU wheels, crates.io, and npm, plus `uv`, Python 3.11, Rust 1.100, Node 24, Go 1.27, GCC/Clang/CMake/Ninja, `ffmpeg` 5.1.9 (with built-in `libflite` TTS), and sandbox-permitted `sudo apt-get update` / `sudo apt-get install -y`. No ML/ASR Python libraries are pre-installed (only `numpy` and `fastapi`), and there are no hardware audio devices (`/dev/snd` absent).

---

## 1. Observation

### 1.1 Hardware & OS
Commands run: `uname -a`, `cat /etc/os-release`, `lscpu`, `free -h`, `df -h`, `nvidia-smi`, `rocminfo`, `ls -la /dev/nvidia* /dev/dri*`.

- **OS**: `Linux sandbox 6.12.105+ #1 SMP Sat Sep 19 19:37:41 UTC 2026 x86_64 GNU/Linux` — `Debian GNU/Linux 12 (bookworm)`
- **CPU**:
  - Architecture: `x86_64`
  - Cores: `2` (`1` socket, `2` cores/socket, `1` thread/core)
  - Model: `Intel(R) Xeon(R) Platinum 8481C`
  - Key SIMD flags: `avx`, `avx2`, `fma`, `f16c`, `avx512f`, `avx512dq`, `avx512bw`, `avx512vl`, `avx512_vnni`, `avx_vnni`, `avx512_bf16`, `avx512_fp16`
- **RAM**:
  - `Mem: 7.8Gi total, 790Mi used, 7.0Gi free, 7.0Gi available`
  - `Swap: 0B`
- **GPU**:
  - `nvidia-smi: command not found`
  - `rocminfo: command not found`
  - `/dev/nvidia*` and `/dev/dri*`: `No such file or directory`
- **Disk Space**:
  - `/home/antigravity` (and `/home/antigravity/poidowl/tsukinami`): `/dev/mapper/ace_vg-persist_lv` — `20G` total, `443M` used, `20G` available (`3%`)
  - `/tmp` and `/var`: `overlay` — `10G` total, `234M` used, `9.8G` available (`3%`)
  - `/`: `3.9G` total, `0` used, `3.9G` available (`0%`)

### 1.2 Installed Languages, Package Managers & Build Tools
Commands run: `command -v` + `--version` across toolchains, `uv python list --only-installed`, `ls -la /usr/lib/python3.11/EXTERNALLY-MANAGED`.

| Tool | Status | Path & Version |
|---|---|---|
| Python | Installed | `/usr/bin/python3` (`Python 3.11.2`), `/usr/bin/python -> python3` |
| `pip` / `pipx` | Installed | `/usr/bin/pip` (`pip 23.0.1`), `pipx 1.1.0` |
| `uv` | Installed | `/usr/local/bin/uv` (`uv 0.13.8 (x86_64-unknown-linux-gnu)`) |
| `python3-venv` | Installed | `3.11.2-1+b1` (`venv` and `ensurepip` importable) |
| `poetry` / `conda` / `mamba` / `virtualenv` | Not installed | — |
| Rust / Cargo | Installed | `/usr/local/bin/rustc` (`1.100.0`), `/usr/local/bin/cargo` (`1.100.0`) |
| Node / npm / npx | Installed | `/usr/local/bin/node` (`v24.22.3`), `npm` (`11.21.2`) (`pnpm`/`yarn` are Corepack shims; `bun` not installed) |
| Go | Installed | `/usr/local/bin/go` (`go1.27.4 linux/amd64`) |
| C / C++ | Installed | `gcc` / `g++` `12.2.0`, `clang` `14.0.6` |
| Build systems | Installed | `cmake` `3.25.1`, `make` `4.3`, `ninja` `1.11.1`, `pkg-config` `1.8.1` |
| `git` | Installed | `/usr/bin/git` (`2.39.5`) |
| `docker` | Not installed | — |

- **PEP 668 marker**: `/usr/lib/python3.11/EXTERNALLY-MANAGED` exists, so system-wide `pip install` is blocked by default; virtual environments (`uv venv` or `python3 -m venv`) should be used.

### 1.3 Installed ML & Audio Libraries / CLI Tools
Commands run: `python3 -m pip list`, Python import probe, CLI probe, `ffmpeg -version`, `ffmpeg -hide_banner -filters`, `ldconfig -p`.

- **Pre-installed Python packages (relevant subset)**:
  - `numpy` `1.24.2`
  - `fastapi` `0.92.0`, `uvicorn` `0.17.6`, `starlette` `0.26.1`, `pydantic` `1.10.4`, `wsproto` `1.2.0`
  - `Pillow` `9.4.0`, `PyYAML` `6.0`, `click` `8.1.3`
  - Stdlib: `wave`, `venv`, `ensurepip`, `sqlite3`, `ctypes`
- **NOT pre-installed Python packages**:
  - ML/ASR: `torch`, `torchaudio`, `onnxruntime`, `whisper`, `faster_whisper`, `vosk`, `transformers`, `datasets`, `webrtcvad`, `silero_vad`
  - Scientific/Audio: `scipy`, `librosa`, `soundfile`, `pyaudio`, `sounddevice`, `pydub`
  - TTS: `pyttsx3`, `gtts`, `edge_tts`
  - Web/Test: `gradio`, `streamlit`, `flask`, `pytest`
- **Pre-installed Audio CLI tools**:
  - `ffmpeg` (`/usr/bin/ffmpeg`, `5.1.9-0+deb12u1`) & `ffprobe` (`/usr/bin/ffprobe`)
  - Built-in `ffmpeg` codecs/filters of note: `--enable-libflite`, `--enable-pocketsphinx`, `--enable-libsoxr`, `--enable-libmp3lame`, `--enable-libopus`, `--enable-libvorbis`, `--enable-libspeex`, `--enable-libpulse`.
  - Confirmed filters via `ffmpeg -hide_banner -filters`: `flite` (`Synthesize voice from text using libflite`), `asr` (`Automatic Speech Recognition`), `sine`, `anoisesrc`.
- **NOT pre-installed Audio/Speech CLI tools**:
  - `sox`, `play`, `rec`, `aplay`, `arecord`, `pactl`, `pw-cli`, `espeak`, `espeak-ng`, `flite` (standalone CLI), `festival`, `pico2wave`, `open_jtalk`, `piper`, `whisper`, `vosk-transcriber`.
- **Pre-installed Shared Libraries (`ldconfig -p`)**:
  - `libsndfile.so.1`, `libavcodec.so.59`, `libasound.so.2`, `libpulse.so.0`, `libpulse-simple.so.0`, `libblas.so.3`, `liblapack.so.3`.

### 1.4 Network & Package Installation Capability
Commands run: `env` proxy check, `sudo -n true`, `curl -sI --max-time 5` against package registries, `apt-cache policy`.

- **Proxy configuration**:
  - `http_proxy` / `https_proxy` / `HTTP_PROXY` / `HTTPS_PROXY` = `http://127.0.0.1:33449`
  - `PIP_CERT=/etc/ssl/certs/ca-certificates.crt`
  - `NODE_USE_ENV_PROXY=1`
- **Registry reachability (read-only HEAD requests)**:
  - `https://pypi.org/simple/` -> `HTTP/2 200`
  - `https://huggingface.co/` -> `HTTP/2 200`
  - `https://download.pytorch.org/whl/cpu/` -> `HTTP/2 200`
  - `https://index.crates.io/config.json` -> `HTTP/2 200`
  - `https://registry.npmjs.org/` -> `HTTP/2 200`
  - `https://files.pythonhosted.org/` -> `HTTP 404` (expected on CDN root; TLS/proxy connection succeeded)
  - `https://cdn-lfs.hf.co/` -> `HTTP 403` (expected on CDN root without object path; TLS/proxy connection succeeded)
- **APT / `sudo` policy**:
  - `sudo -n true` returned verbatim:
    `exebox escape: remote error: "sudo -n true" not permitted by sandbox policy (not sudo apt-get or sudo apt); allowed: sudo apt-get update, sudo apt-get install -y <packages>`
  - `apt-get` (`apt 2.6.2 (amd64)`) is installed. `apt-cache policy` currently only shows installed packages (`python3-venv`), indicating `/var/lib/apt/lists` is unpopulated until `sudo apt-get update` is run.

### 1.5 Audio I/O & Synthetic Speech Capabilities
- **Hardware audio**: `/dev/snd` does not exist (`ls: cannot access '/dev/snd': No such file or directory`); no ALSA/PulseAudio/PipeWire user tools installed.
- **Headless audio/speech synthesis available out-of-the-box**:
  1. `ffmpeg` `flite` filter (`ffmpeg -f lavfi -i flite=text='...'`) for English synthetic speech WAV/PCM generation without installing anything.
  2. `ffmpeg` `sine` / `anoisesrc` filters and Python `numpy` + `wave` for synthetic tones, noise, silence, and programmatic WAV fixtures.
  3. Installable options for Japanese/multilingual synthetic speech (relevant to `ORIGINAL_REQUEST.md`: `"ASRをつくって遊びたい"`): `edge-tts` or `gTTS` via `uv`/`pip` (network-backed), or `open-jtalk` / `espeak-ng` via `sudo apt-get install -y`.

---

## 2. Logic Chain

1. **CPU-only + 7.0 GiB RAM + 0 swap -> Model size & backend selection is critical.**
   - Because there is no GPU (1.1), inference and any training/fine-tuning must run on 2 x86_64 CPU cores.
   - However, the CPU is an Intel Xeon Platinum 8481C with **AVX-512, AVX-VNNI, and BF16/FP16** (1.1), which accelerates quantized CPU inference (`int8`/`fp16` via CTranslate2/`faster-whisper`, `ggml`/`whisper.cpp`, or `onnxruntime`) dramatically compared to vanilla FP32 PyTorch.
   - With 7.0 GiB free RAM and **0 swap** (1.1), peak memory must stay well below ~5 GiB to avoid OOM kills. Lightweight models (e.g., Whisper `tiny`/`base`/`small` quantized, Sherpa-ONNX / SenseVoice / Zipformer / Vosk small models, or a small from-scratch CTC/Conformer/Transformer ASR trained on a toy/subset dataset) are very feasible; Whisper `large-v3` in FP32 or heavy multi-GB training runs are not.
2. **Online access + `uv` + full native toolchains -> Flexible implementation stack.**
   - PyPI, HuggingFace, PyTorch CPU wheels, crates.io, and npm are all reachable (1.4), and `sudo apt-get update && sudo apt-get install -y ...` is permitted (1.4).
   - Because `/usr/lib/python3.11/EXTERNALLY-MANAGED` is present (1.2) and `uv 0.13.8` is pre-installed (1.2), creating a project-local `.venv` under `/home/antigravity/poidowl/tsukinami` via `uv` is the cleanest and fastest Python setup.
   - Because GCC/G++/Clang/CMake/Ninja and Rust 1.100 are pre-installed (1.2), compiling `whisper.cpp`, `sherpa-onnx`, or custom Rust/C++ DSP/ASR code is also directly feasible (limit build parallelism to `-j2` to match 2 cores and avoid RAM spikes).
   - Disk space under `/home/antigravity` is 20 GiB (1.1), whereas `/` is only 3.9 GiB; therefore virtualenvs, downloaded model weights (`HF_HOME`), and build artifacts should stay under `/home/antigravity`.
3. **Headless VM (no `/dev/snd`) -> File/stream-based and browser-based ASR testing.**
   - Live local microphone capture (`pyaudio`/`sounddevice`/`arecord`) cannot work inside the VM (1.5).
   - Automated testing can rely on `ffmpeg` (`flite` filter for English speech, `sine`/`anoisesrc` for synthetic signals, format/resampling via `libsoxr`) and `numpy`+`wave` out-of-the-box (1.3, 1.5), plus installable TTS (`edge-tts`/`gTTS`/`open-jtalk`) or small downloaded audio samples for Japanese ASR tests.
   - For interactive "play around with ASR" UX (`ASRをつくって遊びたい`), a CLI tool (audio file / WAV input) and/or a lightweight web UI (e.g., FastAPI + browser MediaRecorder/WebAudio API, where mic capture happens in the user's browser and audio is uploaded/streamed to the backend) works cleanly in a headless server environment.

---

## 3. Caveats

- **Read-only verification only**: No packages were installed, no `uv venv` was created, and no `sudo apt-get update` was executed. While registry HEAD requests returned HTTP 200 and `sudo` policy explicitly stated `sudo apt-get update` and `sudo apt-get install -y <packages>` are allowed, actual wheel downloads and `apt-get` mirror connectivity were not exercised.
- **HuggingFace LFS / GitHub downloads**: `https://huggingface.co/` returned HTTP 200 and `https://cdn-lfs.hf.co/` responded over TLS (HTTP 403 on root path), strongly indicating model downloads will succeed, but an actual model file download was not tested.
- **`ffmpeg` `flite` voice data**: We confirmed `ffmpeg` is compiled with `--enable-libflite` and lists the `flite` filter, but did not execute `ffmpeg -f lavfi -i flite=text='test'` to write a WAV file (read-only survey).
- **Proxy behavior with Rust/Python tools**: `http_proxy`/`https_proxy` are set in the environment and `PIP_CERT` is configured; most standard tools (`uv`, `pip`, `cargo`, `npm`, `curl`, `huggingface_hub`) respect these variables, though some custom HTTP clients may require explicit proxy/CA handling.

---

## 4. Conclusion

### Feasibility Assessment for Building & Playing with ASR in `/home/antigravity/poidowl/tsukinami`
- **Highly Feasible (CPU-optimized ASR & interactive playground)**:
  1. **Python + `uv` + lightweight CPU ASR** (e.g., `faster-whisper` / CTranslate2 INT8, `onnxruntime` / `sherpa-onnx`, `vosk`, or a compact PyTorch CPU from-scratch/educational ASR) — leverages AVX-512/VNNI on Xeon 8481C, fits comfortably in 7.0 GiB RAM and 20 GiB disk.
  2. **Native C/C++ or Rust ASR** (e.g., `whisper.cpp`, custom DSP/MFCC/CTC decoder) — `gcc`/`clang`/`cmake`/`ninja` and `rustc`/`cargo` 1.100 are already installed.
  3. **Interactive Web/CLI Playground** — `fastapi`/`uvicorn` (or Node 24 frontend) can serve a browser-based mic recorder + file uploader + live transcript/spectrogram visualizer, bypassing the VM's lack of `/dev/snd`.
- **Key Operational Constraints to Respect**:
  - **No GPU**: CPU-only execution; prefer INT8/FP16 quantized inference or small models (`tiny`/`base`/`small`).
  - **7.0 GiB RAM, 0 swap**: Avoid large FP32 models and cap native build parallelism (`-j2`).
  - **Use `/home/antigravity` for venvs, caches, and models** (20 GiB available vs. 3.9 GiB on `/`).
  - **Use `uv` or `python3 -m venv`** due to PEP 668 (`EXTERNALLY-MANAGED`).
  - **Headless audio**: No `/dev/snd`; test via WAV files, `ffmpeg` (`flite`/`sine`/`anoisesrc`), or installable Japanese/English TTS (`gTTS`/`edge-tts`/`open-jtalk`).

---

## 5. Verification Method

Any agent can independently verify these findings with the following read-only commands from `/home/antigravity/poidowl/tsukinami`:

1. **Hardware & Disk**:
   ```bash
   uname -a && lscpu | grep -E 'Architecture|Model name|CPU\(s\)|Flags' && free -h && df -h / /tmp /home/antigravity
   ```
   - Invalidated if: GPU devices appear (`/dev/nvidia*`), RAM/CPU limits change, or disk free space drops significantly.
2. **Toolchains & Python environment**:
   ```bash
   python3 --version && uv --version && rustc --version && node --version && go version && gcc --version | head -n 1 && cmake --version | head -n 1
   python3 -m pip list
   ```
3. **Audio & `ffmpeg` capabilities**:
   ```bash
   ffmpeg -version | head -n 3 && ffmpeg -hide_banner -filters | grep -iE 'flite|asr|sine' && ls /dev/snd 2>&1
   ```
4. **Network & APT policy**:
   ```bash
   curl -sI --max-time 5 https://pypi.org/simple/ | head -n 3
   curl -sI --max-time 5 https://huggingface.co/ | head -n 3
   curl -sI --max-time 5 https://download.pytorch.org/whl/cpu/ | head -n 3
   ```
