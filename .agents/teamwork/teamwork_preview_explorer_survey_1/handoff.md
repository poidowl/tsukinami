# Repository Survey Handoff — `/home/antigravity/poidowl/tsukinami`

**Summary**: `tsukinami` ("月並みTTS / 天邪鬼TTS") is an existing, actively developed, flat-layout **pure-Python Japanese speech & singing synthesizer** (48 commits, 30 root files, 12,356 total lines) accompanied by self-contained single-file HTML/WebAudio interactive playgrounds. It has no packaging/build/linter/test-runner configs, runs Stage 1 strictly on the Python 3 standard library (`SR=44100`, 5 ms frames, ~765 transparent phonetic/DSP numbers), and offers a natural foundation for building a playful, transparent, TTS↔ASR closed-loop Japanese ASR in response to the user's request (`"ASRをつくって遊びたい"`).

---

## 1. Observation

### 1.1 Original User Request
- File: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` (lines 1–5):
  ```
  ## Initial Request — 2026-11-19T02:55:22Z
  ASRをつくって遊びたい
  ```

### 1.2 Git Repository State
Command: `git status -sb`, `git branch -a`, `git remote -v`, `git tag -l`, `git rev-list --count HEAD`, `git log`
- Branch: `main` (`## main...origin/main [ahead 23]`), working tree clean except untracked `.agents/`.
- Remote: `origin https://github.com/poidowl/tsukinami.git` (fetch/push).
- Tags: none.
- Commit count: `48` commits.
- Earliest commit: `6aab453 Initial release: 月並みTTS (tsukinami) 純Python乱数削り出し音声・歌声合成器 + 可視化デモ`.
- Most recent commits:
  - `d2ab3ce Merge pull request #4 from poidowl/kusanagi-sync-24d3049`
  - `c0ecb97 Sync kusanagi_player.html with kusanagi @24d3049 reading fixes`
  - `16fbde6 Merge pull request #3 from poidowl/kusanagi-x-card`
  - `3858e11 Merge pull request #2 from poidowl/fix-tour-full-span`
  - `84ec019 Merge pull request #1 from poidowl/hitofude-x-card`
  - Prior to PRs #1–#4: intensive `--trance` / `--choir` singing DSP & `uta_hakaru.py --f12` regression checks (`50375da`, `7ba3a34`, `70a8739`, `3f7cffb`, `7914898`).

### 1.3 Complete Directory & File Inventory
Root directory `/home/antigravity/poidowl/tsukinami` contains **3 subdirectories** (`.git/`, `.agents/`, `assets/`) and **30 root files** (flat layout, no `src/`, `tests/`, `.github/`, `.gitignore`, `pyproject.toml`, `requirements.txt`, `package.json`, or notebooks).

| Category | File | Size / Lines | Role & Key Details |
|---|---|---:|---|
| **Docs / License** | `README.md` | 26,742 B / 236 L | Japanese main README: architecture, ablation table, CLI quickstart, "765 numbers" design, prior art vs original |
| | `README_EN.md` | 14,216 B / 133 L | English mirror of README |
| | `LICENSE` | 1,064 B / 22 L | MIT License (Copyright 2026 poidowl) |
| **Core Stage 1 TTS (stdlib only)** | `carve.py` | 131,827 B / 1,781 L | Core time-domain noise-carving synthesizer (`SR = 44100`, `make(rc)`, `write(path, x)`, `variant(changes)`, `make_text(rc)`). Imports: `random, wave, struct, json, array, os, copy, math, cmath, sys, accent` |
| | `kotoba.py` | 20,844 B / 365 L | Pure-Python kana → 5 ms (`FP = 5.0`) formant tracks (`F1..F3`), gains (`G1..G3`), noise bands, loudness, voicing, and exact mora timestamps (`tracks_from_kana()`). Imports: `math, bisect` |
| | `accent.py` | 12,784 B / 252 L | Pure-Python rule-based Tokyo pitch accent & intonation → 5 ms `f0` contour (`annotate()`, `f0_rule()`). Imports: `math` |
| | `yomu.py` | 16,108 B / 329 L | Cross-platform CLI driver ("Play → Modify → Listen → Compare → Share") with 8 presets (`default`, `ossan`, `robot`, `horror`, `whisper`, `chibi`, `utahime`, `choir`), `--compare`, `--recipe`/`--save-recipe`. Stdlib + `accent`, `carve` |
| | `mkt.py` | 2,330 B / 30 L | Batch driver reading `TEXTS` env JSON, invoking `carve.py`, writing `out/{tag}_{j+1}.wav` and optional `swap/mo_{tag}_{j+1}.json` mora timings (`MO=1`). Stdlib + `carve` |
| | `mcp_server.py` | 6,793 B / 157 L | Zero-dependency MCP server exposing `tsukinami_speak` tool (synthesizes WAV, optional local playback, generates `toybox.html` share URL). Stdlib + `yomu`, `carve` |
| | `S.txt`, `OO.txt` | 341 B, 113 B (1 L each) | JSON fragment parameter presets injected by `yomu2.sh` |
| **Stage 2 / Acoustic Analysis** | `uta_hakaru.py` | 22,524 B / 236 L | Singing analysis (`hakaru`, uses `numpy`, `soundfile`, `pyworld`) + regression hash & F1/F2 spectral verification (`hakaru_f12`, uses `numpy`, `carve`, `kotoba`) |
| | `erabu_mijikaiF.py` | 6,451 B / 69 L | Stage 2 96-band spectral target trajectory builder (`numpy`, `soundfile`, `scipy`, `pyworld`, `librosa`) |
| | `featF.py` | 2,112 B / 30 L | Mora-level 96-band feature extractor (`numpy`, `soundfile`, `pyworld`, `librosa`, `pickle`, `multiprocessing`) |
| | `mijikai_full.py` | 2,571 B / 21 L | Builds `mijikaiF_{WHO}.npz` coarticulation/target stats (`numpy`, `scipy.fft`, `pickle`) |
| | `suki3.py` | 975 B / 10 L | Merges multiple speaker `mijikaiF_*.npz` models (`numpy`) |
| | `tani.py` | 1,811 B / 18 L | Measures inter-harmonic valley depth (`iki` calibration) (`numpy`, `soundfile`, `pyworld`) |
| **Shell Drivers** | `yomu2.sh` | 1,988 B / 30 L | 1-stage (`mkt.py`) or 2-stage (`mkt.py` + `erabu_mijikaiF.py`) synthesis wrapper |
| | `tehon.sh` | 1,019 B / 26 L | Reference-voice analysis pipeline (`hanashi` / `uta`) |
| | `nagauta.sh` | 1,296 B / 17 L | 4-phrase singing demo script |
| | `jikoshoukai_uta.sh` | 1,729 B / 47 L | Self-introduction song demo (`--trance` / `--choir`) |
| **Interactive HTML Demos (GitHub Pages)** | `index.html` & `toybox.html` | 797,681 B / 980 L each | Byte-identical (`cmp -s index.html toybox.html` = equal). Interactive Toybox with 6 presets, A/B compare, 10 sliders, URL query & Recipe JSON |
| | `watashi_demo.html` | 1,831,374 B / 707 L | 6-stage carving & 17-mora microscope + 7-track ablation (embedded real audio) |
| | `ablation.html` | 1,033,607 B / 152 L | 7-track ablation listening jury & metric definitions |
| | `demo.html` | 30,205 B / 849 L | Free-kana live WebAudio playground |
| | `hitofude.html`, `hitofude_player.html` | 6,317 B / 174 L; 79,955 B / 2,246 L | "一筆彫り hitofude" pure-JS 4-step noise-carving WebAudio synth + X Player Card |
| | `kusanagi.html`, `kusanagi_player.html` | 6,348 B / 174 L; 83,127 B / 2,305 L | "草薙 kusanagi" pure-JS noise-carving WebAudio synth + X Player Card |
| **Assets** | `assets/` | 3 files | `social_preview.png` (857 KB), `hitofude_square.jpg` (624 KB), `kusanagi_square.jpg` (35 KB) |

### 1.4 Language, Build, Package, Linter, Test & Runtime Environment
- **Languages in repo**: Python 3 (core TTS + analysis), Bash (4 shell wrappers), single-file HTML/CSS/JS (WebAudio demos, zero CDN/npm dependencies).
- **Build tools / package managers / linters / test configs in repo**: **None** (no `pyproject.toml`, `setup.py`, `requirements.txt`, `package.json`, `Cargo.toml`, `Makefile`, `pytest.ini`, `.flake8`, `.ruff.toml`, `.gitignore`).
- **Existing verification mechanism**: `uta_hakaru.py` implements `hakaru_f12()` with SHA-256 WAV regression hashes (`exp_hashes` at `uta_hakaru.py:73`) and F1/F2 spectral checks.
- **Installed environment tools observed**:
  - `Python 3.11.2`
  - `numpy 1.24.2`
  - `node`, `npm`, `cargo` available on PATH (`/usr/local/bin/...`)
  - **Not installed** in Python environment: `scipy`, `soundfile`, `librosa`, `pyworld`, `torch`, `torchaudio`, `whisper`, `faster_whisper`, `pytest`.

### 1.5 Domain Context, Naming Conventions & Design Ethos
- **Japanese-rooted, poetic, playful naming**: `tsukinami` (月並み), `carve.py` (削り出し: `arakezuri`, `kubire`, `karuku`, `sabun`, `yama_bp`), `kotoba.py`, `yomu.py`, `uta_hakaru.py`, `hitofude` (一筆彫り), `kusanagi` (草薙), `toybox.html` (オモチャ箱).
- **Core philosophy** (`README.md:7-25`, `README_EN.md:7-26`):
  - **"Read how it works, in Python"** — transparent, inspectable, hackable code over black-box weights.
  - **Zero-dependency Stage 1** — pure Python standard library (and zero-CDN single-file HTML/JS for browser demos).
  - **Acoustic cues over brute-force modeling** — `kotoba.py` already defines Japanese kana/mora phonology (`K2V`, `SMALL`, `PALC`, `PLACE`, `MANNER`, `VOICELESS`, `VOICED_OBS`), 5-vowel formant targets (`VT`: `a/i/u/e/o` F1–F3), F2 locus equations (`LE`), consonant durations (`CDUR`), fricative bands (`fricT`), nasal formants (`nasT`), and exact 5 ms frame-aligned ground-truth mora boundaries (`tracks_from_kana()` returns `moras=[{t, kind, c, v, a, b, e}]`).
  - **"Breakable & Reversible" UX** — interactive sliders, A/B comparison, ablation/inspection views, CLI + browser parity.
  - **TTS ↔ ASR connection already hinted in repo**: `kotoba.py:5` and `README.md:93,100,120` explicitly note that `tsukinami`'s phonetic cues were tuned using `"owner ear + ASR"`.

---

## 2. Logic Chain

1. **Repo is NOT greenfield**: Observation 1.2–1.3 shows an active 48-commit TTS repository with a flat file layout, GitHub Pages HTML demos (`index.html == toybox.html`), and established Python modules (`kotoba.py`, `accent.py`, `carve.py`, `yomu.py`). Therefore, any new ASR work must coexist cleanly without breaking existing TTS files, `index.html`, or regression hashes in `uta_hakaru.py`.
2. **Zero/minimal-dependency constraint in this environment**: Observation 1.4 shows only Python 3.11.2 stdlib + `numpy 1.24.2` are installed (no `torch`, `whisper`, `scipy`, `librosa`, `pytest`). Additionally, Observation 1.5 shows the repo's signature identity is pure-Python stdlib (or stdlib + optional `numpy`) and zero-CDN single-file HTML/JS. Designing an ASR that runs with stdlib (or stdlib + `numpy`) and/or pure-JS WebAudio/mic input directly fits both the environment and `tsukinami`'s ethos.
3. **Built-in synthetic dataset & ground-truth oracle**: Observation 1.3 (`kotoba.py:342-360`, `carve.py:14,206,378`, `yomu.py`) shows `tsukinami` can synthesize arbitrary Japanese kana utterances at 44.1 kHz with exact ground-truth mora labels, consonant/vowel classes, formant trajectories, and timestamps (`a`, `b`, `e`). This gives an ASR project an immediate, infinite, reproducible test bench (including multi-speaker/style presets like `default`, `ossan`, `chibi`, `robot`, `whisper`, noise/speed perturbations) for closed-loop TTS→ASR evaluation.
4. **Layout & testing implications**: Because there is no `pyproject.toml`, `src/`, or `pytest` installed, new code should either follow the repo's flat root convention (or a clean self-contained directory like `asr/` if multi-module, keeping root uncluttered) and provide runnable verification via `python3 -m unittest` (stdlib) or a standalone check script (mirroring `uta_hakaru.py`).

---

## 3. Caveats

- **Deep internals not read**: Only headers/signatures of `carve.py` (lines 1–45), `uta_hakaru.py` (lines 1–80), `yomu.py` (lines 1–80), `mcp_server.py` (lines 1–100), and the HTML/JS player bodies (`hitofude_player.html`, `kusanagi_player.html`, `toybox.html`) were inspected; full line-by-line reading was unnecessary for a structural survey.
- **Ambiguity in user request**: `"ASRをつくって遊びたい"` does not specify whether the user wants:
  - a pure-Python/NumPy transparent DSP/acoustic-phonetic/HMM/CTC/DTW ASR (in `tsukinami`'s "no pretrained weights, read how it works" spirit),
  - an interactive browser/microphone ASR playground (like `toybox.html` / `demo.html`),
  - a TTS↔ASR round-trip game/benchmark using `tsukinami` itself, or
  - a neural ASR trained from scratch on `tsukinami`-generated speech.
  Architectural decisions should be scoped by the orchestrator/planner.
- **Git state**: `main` is ahead of `origin/main` by 23 commits; no network/remote inspection was performed.

---

## 4. Conclusion

`/home/antigravity/poidowl/tsukinami` is a well-crafted, flat-structured pure-Python Japanese TTS & singing synthesis repository with zero-dependency Stage 1 DSP (`carve.py`, `kotoba.py`, `accent.py`, `yomu.py`), optional Stage 2 analysis scripts, and zero-CDN interactive HTML/WebAudio playgrounds.

**Actionable recommendations for building ASR in this repo**:
1. **Preserve existing TTS untouched**: Do not alter `carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `index.html`, or existing regression hashes (`uta_hakaru.py`).
2. **Match `tsukinami`'s ethos & runtime**: Favor pure Python 3.11 stdlib (and/or `numpy 1.24.2`, already installed) with zero external ML downloads required to run out of the box, plus optional zero-CDN HTML/WebAudio interactive demo (microphone + WAV upload + live spectrum/formant/mora decoding visualizer).
3. **Leverage `kotoba.py` & `carve.py` as a built-in oracle**: Reuse `kotoba.py`'s kana/mora phonology (`K2V`, `split_moras`, `VT`, `PLACE`, `MANNER`, `tracks_from_kana`) and `carve.py`/`yomu.py` to generate reproducible labeled test utterances across presets (`default`, `ossan`, `chibi`, etc.) for automated accuracy/CER/mora-alignment verification.
4. **Use stdlib `unittest` for automated tests**: Since `pytest` is not installed, `python3 -m unittest` guarantees zero-setup verification.
5. **Mind layout**: Either place a compact, cohesive ASR module (e.g., `kiku.py` / `asr.py` + `asr_demo.html`, matching Japanese verb naming like `yomu.py` = read → `kiku.py` = listen) at root or in a dedicated `asr/` package, and keep `.agents/teamwork/` strictly metadata-only.

---

## 5. Verification Method

All observations can be independently verified from `/home/antigravity/poidowl/tsukinami`:
1. **File inventory & line counts**:
   ```bash
   ls -la /home/antigravity/poidowl/tsukinami
   wc -l *.py *.sh *.txt *.md *.html
   cmp -s index.html toybox.html && echo "IDENTICAL"
   ```
2. **Git state**:
   ```bash
   git status -sb && git branch -a && git remote -v && git rev-list --count HEAD
   ```
3. **Python imports & runtime dependencies**:
   ```bash
   grep -rn '^import \|^from ' *.py
   python3 --version && python3 -c "import numpy; print(numpy.__version__)"
   ```
4. **TTS smoke check (read-only/in-memory)**:
   ```bash
   python3 -c "import kotoba; r = kotoba.tracks_from_kana('わたし'); print(r['n'], len(r['moras']), r['moras'][0])"
   ```
5. **Invalidation conditions**: Any new commits, newly installed Python packages/virtualenvs, or added build configs (`pyproject.toml`, `requirements.txt`, etc.) would update Sections 1.2–1.4.
