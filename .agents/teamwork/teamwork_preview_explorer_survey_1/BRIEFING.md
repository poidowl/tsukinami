# BRIEFING — 2026-11-19T02:58:30Z

## Mission
Survey the codebase and repository structure of `/home/antigravity/poidowl/tsukinami` (read-only) and produce a self-contained `handoff.md`.

## 🔒 My Identity
- Archetype: Explorer (Survey Explorer 1)
- Roles: Read-only investigation, synthesis
- Working directory: /home/antigravity/poidowl/tsukinami
- State folder: /home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_1
- Original parent: dae8e1c02ad3da5e30ef373936de6d57
- Milestone: Initial Repository Survey

## 🔒 Key Constraints
- Read-only investigation — do NOT modify any source files or write code
- Write reports only to own state folder under `.agents/teamwork/teamwork_preview_explorer_survey_1/`
- Read `ORIGINAL_REQUEST.md` first

## Current Parent
- Conversation ID: dae8e1c02ad3da5e30ef373936de6d57
- Updated: 2026-11-19T02:58:30Z

## Investigation State
- **Explored paths**:
  - `.agents/teamwork/ORIGINAL_REQUEST.md`
  - Repo root (`30` files, `assets/` with 3 images, `.git/`, `.agents/`)
  - `README.md`, `README_EN.md`, `LICENSE`
  - Core Stage 1 Python: `carve.py`, `kotoba.py`, `accent.py`, `yomu.py`, `mkt.py`, `mcp_server.py`, `S.txt`, `OO.txt`
  - Stage 2 / analysis Python: `uta_hakaru.py`, `erabu_mijikaiF.py`, `featF.py`, `mijikai_full.py`, `suki3.py`, `tani.py`
  - Shell scripts: `yomu2.sh`, `tehon.sh`, `nagauta.sh`, `jikoshoukai_uta.sh`
  - HTML demos: `index.html` (== `toybox.html`), `demo.html`, `ablation.html`, `watashi_demo.html`, `hitofude.html`/`hitofude_player.html`, `kusanagi.html`/`kusanagi_player.html`
  - Git metadata (48 commits, `main` ahead of `origin/main` by 23 commits, no tags) and runtime toolchain (Python 3.11.2, numpy 1.24.2, node/npm/cargo; no pytest/scipy/torch/whisper/etc.)
- **Key findings**:
  - `tsukinami` is a mature, flat-layout, zero-dependency (Stage 1) pure-Python Japanese TTS & singing synthesizer ("月並みTTS / 天邪鬼TTS") with self-contained single-file HTML/WebAudio interactive demos.
  - Zero build/packaging configs (`pyproject.toml`, `setup.py`, `requirements.txt`, `package.json`, `.gitignore` do not exist); no formal test suite (only `uta_hakaru.py --f12` regression hash checks).
  - User's request is `"ASRをつくって遊びたい"` — building a playful ASR that aligns naturally with `tsukinami`'s ethos (transparent DSP/phonetics, zero-or-minimal dependencies, interactive "play/break/inspect" UX, and direct TTS↔ASR closed-loop testing against `kotoba.py`/`carve.py`!).
- **Unexplored areas**: Full internal implementation details of `carve.py` (lines 46–1781) and JS players (`hitofude_player.html`, `kusanagi_player.html`) — out of scope for repo survey.

## Key Decisions Made
- Completed full inventory and documented layout, philosophy, dependencies, and ASR integration opportunities in `handoff.md`.

## Artifact Index
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_1/DISPATCH.md` — Dispatch message log
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_1/BRIEFING.md` — Persistent working memory
- `/home/antigravity/poidowl/tsukinami/.agents/teamwork/teamwork_preview_explorer_survey_1/handoff.md` — Final 5-component survey handoff report
