"""JSONL manifest dataset, PyTorch batch collation, and Tier 3 real-audio manifest helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch.utils.data import Dataset

from asr.audio import load_wav
from asr.config import AudioConfig
from asr.features import extract_log_mel, spec_augment
from asr.tokenizer import Tokenizer

__all__ = [
    "load_manifest",
    "write_manifest",
    "ASRManifestDataset",
    "collate_asr_batch",
    "build_manifest_from_wav_dir",
]


def load_manifest(manifest_path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a UTF-8 JSONL ASR manifest file."""
    p = Path(manifest_path)
    if not p.exists():
        raise FileNotFoundError(f"Manifest not found: {p}")
    if p.is_dir():
        raise ValueError(f"Manifest path is a directory: {p}")

    records: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSONL at {p}:{line_no}: {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(
                    f"Expected JSON object at {p}:{line_no}, got {type(obj).__name__}"
                )
            audio_path = obj.get("audio_path")
            if not isinstance(audio_path, str) or not audio_path.strip():
                raise ValueError(
                    f"Missing or invalid 'audio_path' at {p}:{line_no}"
                )
            text = obj.get("text")
            if not isinstance(text, str):
                raise ValueError(
                    f"Missing or invalid 'text' at {p}:{line_no}"
                )
            records.append(obj)
    return records


def write_manifest(
    records: Sequence[Mapping[str, Any]],
    manifest_path: str | Path,
) -> Path:
    """Write ASR manifest records to a UTF-8 JSONL file."""
    out = Path(manifest_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(dict(rec), ensure_ascii=False) + "\n")
    return out


def _resolve_audio_path(raw_audio_path: str, manifest_dir: Path) -> Path:
    p = Path(raw_audio_path)
    if p.is_absolute():
        return p
    rel = manifest_dir / p
    if rel.exists():
        return rel.resolve()
    if p.exists():
        return p.resolve()
    return rel


class ASRManifestDataset(Dataset):
    """PyTorch Dataset that loads audio + transcripts from a JSONL manifest.

    Each item returns:
        - ``feats``: ``torch.float32`` tensor of shape ``[T, F]``
        - ``feat_length``: ``int`` (``T``)
        - ``targets``: ``torch.long`` tensor of shape ``[L]``
        - ``target_length``: ``int`` (``L``)
        - ``text``: ``str``
        - ``audio_path``: ``str``
    """

    def __init__(
        self,
        manifest_path: str | Path,
        audio_cfg: AudioConfig | None = None,
        tokenizer: Tokenizer | None = None,
        augment: bool = False,
        *,
        spec_augment_kwargs: Mapping[str, Any] | None = None,
        validate_files: bool = True,
        allow_empty_targets: bool = False,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.audio_cfg = audio_cfg if audio_cfg is not None else AudioConfig()
        self.tokenizer = tokenizer if tokenizer is not None else Tokenizer("kana")
        self.augment = bool(augment)
        self._spec_augment_kwargs: dict[str, Any] = (
            dict(spec_augment_kwargs) if spec_augment_kwargs is not None else {}
        )

        raw_records = load_manifest(self.manifest_path)
        if not raw_records:
            raise ValueError(f"Manifest contains no records: {self.manifest_path}")

        manifest_dir = self.manifest_path.parent
        items: list[dict[str, Any]] = []
        for idx, rec in enumerate(raw_records, start=1):
            resolved = _resolve_audio_path(rec["audio_path"], manifest_dir)
            if validate_files:
                if resolved.is_dir():
                    raise ValueError(f"Audio path is a directory: {resolved}")
                if not resolved.is_file():
                    raise FileNotFoundError(f"Audio file not found: {resolved}")

            text = rec["text"]
            target_ids = self.tokenizer.encode(text)
            if not allow_empty_targets and len(target_ids) == 0:
                raise ValueError(
                    f"Empty encoded target for text={text!r} "
                    f"(record {idx} in {self.manifest_path})"
                )

            items.append(
                {
                    "audio_path": resolved,
                    "text": text,
                    "target_ids": target_ids,
                    "duration": rec.get("duration"),
                    "speaker": rec.get("speaker", "unknown"),
                    "source": rec.get("source", "unknown"),
                    "moras": rec.get("moras", []),
                }
            )
        self._items = items

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, idx: int) -> dict[str, Any]:
        entry = self._items[idx]
        wav, _ = load_wav(entry["audio_path"], target_sr=self.audio_cfg.sample_rate)
        mel = extract_log_mel(wav, self.audio_cfg)
        if self.augment:
            mel = spec_augment(mel, **self._spec_augment_kwargs)

        feats = torch.from_numpy(np.ascontiguousarray(mel, dtype=np.float32))
        targets = torch.tensor(entry["target_ids"], dtype=torch.long)
        return {
            "feats": feats,
            "feat_length": int(feats.shape[0]),
            "targets": targets,
            "target_length": int(targets.shape[0]),
            "text": entry["text"],
            "audio_path": str(entry["audio_path"]),
        }


def collate_asr_batch(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pad variable-length ASR dataset items into a CTC-ready batch dictionary.

    Returns
    -------
    dict
        - ``feats``: ``torch.float32`` ``[B, T_max, F]`` (zero-padded)
        - ``feat_lengths``: ``torch.long`` ``[B]``
        - ``targets``: ``torch.long`` ``[B, L_max]`` (zero/blank-padded)
        - ``target_lengths``: ``torch.long`` ``[B]``
        - ``texts``: ``list[str]``
    """
    if len(items) == 0:
        raise ValueError("Cannot collate an empty batch")

    feat_list: list[torch.Tensor] = []
    target_list: list[torch.Tensor] = []
    texts: list[str] = []
    feat_dim: int | None = None

    for i, item in enumerate(items):
        feats = torch.as_tensor(item["feats"], dtype=torch.float32)
        if feats.ndim != 2:
            raise ValueError(
                f"Expected 2D feats [T, F] at batch index {i}, got shape {tuple(feats.shape)}"
            )
        if feat_dim is None:
            feat_dim = int(feats.shape[1])
        elif int(feats.shape[1]) != feat_dim:
            raise ValueError(
                f"Feature dimension mismatch at batch index {i}: "
                f"expected {feat_dim}, got {int(feats.shape[1])}"
            )

        targets = torch.as_tensor(item["targets"], dtype=torch.long)
        if targets.ndim != 1:
            raise ValueError(
                f"Expected 1D targets [L] at batch index {i}, got shape {tuple(targets.shape)}"
            )

        feat_list.append(feats)
        target_list.append(targets)
        texts.append(str(item["text"]))

    batch_size = len(items)
    feat_lens = [int(f.shape[0]) for f in feat_list]
    target_lens = [int(t.shape[0]) for t in target_list]
    t_max = max(feat_lens)
    l_max = max(target_lens)
    assert feat_dim is not None

    feats_padded = torch.zeros((batch_size, t_max, feat_dim), dtype=torch.float32)
    targets_padded = torch.zeros((batch_size, l_max), dtype=torch.long)

    for i, (f, t) in enumerate(zip(feat_list, target_list)):
        if f.shape[0] > 0:
            feats_padded[i, : f.shape[0], :] = f
        if t.shape[0] > 0:
            targets_padded[i, : t.shape[0]] = t

    return {
        "feats": feats_padded,
        "feat_lengths": torch.tensor(feat_lens, dtype=torch.long),
        "targets": targets_padded,
        "target_lengths": torch.tensor(target_lens, dtype=torch.long),
        "texts": texts,
    }


def _load_transcript_map(transcript_map: Mapping[str, str] | str | Path) -> dict[str, str]:
    if isinstance(transcript_map, Mapping):
        out: dict[str, str] = {}
        for k, v in transcript_map.items():
            if not isinstance(v, str):
                raise ValueError(
                    f"Transcript value for key {k!r} must be a string, got {type(v).__name__}"
                )
            out[str(k)] = v
        return out
    if not isinstance(transcript_map, (str, Path)):
        raise TypeError(
            "transcript_map must be a mapping or path to a JSON/TSV/TXT file, "
            f"got {type(transcript_map).__name__}"
        )

    p = Path(transcript_map)
    if not p.exists():
        raise FileNotFoundError(f"Transcript map file not found: {p}")
    if p.is_dir():
        raise ValueError(f"Transcript map path is a directory: {p}")

    if p.suffix.lower() == ".json":
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON transcript map {p}: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"Expected JSON object in {p}, got {type(obj).__name__}")
        out = {}
        for k, v in obj.items():
            if not isinstance(v, str):
                raise ValueError(
                    f"Transcript value for key {k!r} in {p} must be a string, got {type(v).__name__}"
                )
            out[str(k)] = v
        return out

    parsed: dict[str, str] = {}
    with p.open("r", encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            if "\t" in line:
                key, val = line.split("\t", 1)
            elif ":" in line and " " not in line.split(":", 1)[0]:
                # JSUT transcript_utf8.txt format: BASIC5000_0001:...
                key, val = line.split(":", 1)
            else:
                parts = line.split(None, 1)
                if len(parts) != 2:
                    raise ValueError(
                        f"Cannot parse transcript line {p}:{line_no}: {raw_line!r}"
                    )
                key, val = parts
            parsed[key.strip()] = val.strip()
    return parsed


def build_manifest_from_wav_dir(
    wav_dir: str | Path,
    transcript_map: Mapping[str, str] | str | Path,
    out_manifest_path: str | Path,
    *,
    speaker: str = "custom",
    source: str = "wav_dir",
    target_sr: int = 16000,
) -> Path:
    """Build a standard JSONL ASR manifest from a directory of WAV files and transcripts.

    Supports ``transcript_map`` as a Python mapping or a file path (``.json``,
    ``.tsv``, JSUT ``id:text``, or Kaldi ``id text``). Keys are matched in order:
    relative POSIX path, filename (with extension), then file stem.
    """
    wav_root = Path(wav_dir)
    if not wav_root.exists():
        raise FileNotFoundError(f"WAV directory not found: {wav_root}")
    if not wav_root.is_dir():
        raise ValueError(f"wav_dir is not a directory: {wav_root}")

    tmap = _load_transcript_map(transcript_map)
    out_path = Path(out_manifest_path)

    wav_files = sorted(
        (p for p in wav_root.rglob("*") if p.is_file() and p.suffix.lower() == ".wav"),
        key=lambda p: p.relative_to(wav_root).as_posix(),
    )

    records: list[dict[str, Any]] = []
    for wav_path in wav_files:
        rel_posix = wav_path.relative_to(wav_root).as_posix()
        raw_text: str | None = None
        for candidate_key in (rel_posix, wav_path.name, wav_path.stem):
            if candidate_key in tmap:
                raw_text = tmap[candidate_key]
                break
        if raw_text is None:
            continue

        text = raw_text.strip()
        if not text:
            raise ValueError(f"Empty transcript for {wav_path.name}")

        wav, sr = load_wav(wav_path, target_sr=target_sr)
        duration = round(float(wav.size) / float(sr), 4)

        stored_audio_path = str(wav_path.resolve())

        records.append(
            {
                "audio_path": stored_audio_path,
                "text": text,
                "duration": duration,
                "speaker": speaker,
                "source": source,
                "moras": [],
            }
        )

    if not records and (wav_files or tmap):
        raise ValueError(f"No matching WAV files found in {wav_root}")

    return write_manifest(records, out_path)
