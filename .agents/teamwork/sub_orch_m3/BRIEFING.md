# Milestone M3 Briefing (`sub_orch_m3`)

- **Original Request**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/ORIGINAL_REQUEST.md` ("ASRをつくって遊びたい")
- **Project Spec**: `/home/antigravity/poidowl/tsukinami/PROJECT.md`
- **Working Directory**: `/home/antigravity/poidowl/tsukinami`
- **State Folder**: `/home/antigravity/poidowl/tsukinami/.agents/teamwork/sub_orch_m3`
- **Parent Conversation ID**: `dae8e1c02ad3da5e30ef373936de6d57`

## Objective
Implement Milestone M3: Acoustic Models & Training Engine for Tsukinami ASR.
Milestones M1, M2, and M4 are already complete (`asr/config.py`, `asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`, `asr/synth_data.py`, `asr/dataset.py`, `asr/decoding.py`, `asr/metrics.py`).

## Exclusive File Ownership
1. `asr/models/__init__.py`
2. `asr/models/subsampling.py`
3. `asr/models/cnn_bigru.py`
4. `asr/models/conformer.py`
5. `asr/train.py`
6. `tests/test_asr_models.py`

Do NOT modify M1/M2/M4 files, existing TTS files, or `tests_e2e/`.
