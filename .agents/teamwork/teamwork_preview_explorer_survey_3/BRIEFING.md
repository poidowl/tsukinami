# BRIEFING — 2026-11-19T02:59:00Z

## Mission
Survey `/home/antigravity/poidowl/tsukinami` and design the feature inventory, genuine end-to-end ASR architecture, milestone decomposition (3-7 milestones), interface contracts, and playability/E2E verification requirements for "ASRをつくって遊びたい".

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: /home/antigravity/poidowl/tsukinami
- State folder: /home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_3
- Original parent: dae8e1c02ad3da5e30ef373936de6d57
- Milestone: Survey & Architecture Design

## 🔒 Key Constraints
- Read-only exploration and design analysis — do NOT write source code or modify project files
- Write `handoff.md` in state folder only
- Must propose a genuine, trainable/runnable end-to-end ASR (no black-box API wrapper, no hardcoded dummy)
- Must work out-of-the-box without huge manual downloads while supporting real audio and optional real datasets

## Current Parent
- Conversation ID: dae8e1c02ad3da5e30ef373936de6d57
- Updated: 2026-11-19T02:59:00Z

## Investigation State
- **Explored paths**:
  - `.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
  - `README.md`, `README_EN.md`, `yomu.py`, `kotoba.py`, `featF.py`, `mcp_server.py`
  - Git history (`git log -n 10`) and runtime environment (Python 3.11.2, numpy 1.24.2, fastapi 0.92.0, uvicorn 0.17.6, ffmpeg, uv, pip, node, npm; 2 CPU cores, 7.8 GiB RAM, no GPU)
- **Key findings**:
  - `tsukinami` is a pure-Python Japanese kana TTS synthesizer (`yomu.py`, `carve.py`, `kotoba.py`, `accent.py`) with interactive zero-CDN HTML playgrounds (`toybox.html`, `ablation.html`, `watashi_demo.html`, `demo.html`).
  - `yomu.build_carve_rc()` + `carve.make()` synthesizes genuine Japanese speech at 44.1 kHz (RTF ~2.8 on 2-core CPU) and returns exact ground-truth mora boundaries (`t`, `kind`, `c`, `v`, `a`, `b`, `e`).
  - `kotoba.tracks_from_kana()` produces 5ms formant/voicing/noise tracks + mora alignments in <1 ms, enabling ultra-fast NumPy formant-track synthesis for bulk CPU training in seconds alongside authentic `carve.make` synthesis for TTS→ASR round-trip play.
  - `numpy`, `fastapi`, `uvicorn`, `ffmpeg`, `uv`, `pip` are pre-installed; `torch` and `pytest` are not yet installed (can be installed via `uv`/`pip` or an optional pure-NumPy backend can be chosen).
- **Unexplored areas**:
  - None blocking for architectural design; `carve.py` internals (131 KB) not read in full because `yomu.py` provides the stable high-level synthesis contract.

## Key Decisions Made
- Propose a dedicated `asr/` package + `tests/` so existing `tsukinami` TTS files remain untouched.
- Propose a hybrid transparent architecture: Pure-NumPy DSP/Mel/SpecAugment/CTC-Decoding/Metrics + compact PyTorch CPU Acoustic Models (`cnn_bigru` default, `conformer_lite` optional) with Pure-NumPy TDNN-CTC documented as Architecture Option 2.
- Decompose into 6 clean milestones (M1–M6) with explicit interface contracts and E2E playability/verification criteria.

## Artifact Index
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_3/DISPATCH.md` — Dispatch log
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_3/BRIEFING.md` — Situational awareness
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_3/handoff.md` — Final survey & architecture design report (pending write)
