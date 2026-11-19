"""CTC Tokenizer supporting Japanese kana, kotoba phonemes, and lowercase ASCII."""

from __future__ import annotations

import numbers
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    import kotoba
except ImportError:  # pragma: no cover - fallback when invoked outside repo root
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    import kotoba


_DEFAULT_KANA_TOKENS: list[str] = [
    # 71 full-size Katakana characters from kotoba.K2V in gojuon order
    "ア", "イ", "ウ", "エ", "オ",
    "カ", "キ", "ク", "ケ", "コ",
    "サ", "シ", "ス", "セ", "ソ",
    "タ", "チ", "ツ", "テ", "ト",
    "ナ", "ニ", "ヌ", "ネ", "ノ",
    "ハ", "ヒ", "フ", "ヘ", "ホ",
    "マ", "ミ", "ム", "メ", "モ",
    "ヤ", "ユ", "ヨ",
    "ラ", "リ", "ル", "レ", "ロ",
    "ワ", "ヲ",
    "ガ", "ギ", "グ", "ゲ", "ゴ",
    "ザ", "ジ", "ズ", "ゼ", "ゾ",
    "ダ", "ヂ", "ヅ", "デ", "ド",
    "バ", "ビ", "ブ", "ベ", "ボ",
    "パ", "ピ", "プ", "ペ", "ポ",
    "ヴ",
    # Special moras
    "ン", "ッ", "ー",
    # Small kana (kotoba.SMALL)
    "ャ", "ュ", "ョ", "ァ", "ィ", "ゥ", "ェ", "ォ",
    # Punctuation & space
    "、", "。", " ",
]

_DEFAULT_PHONEME_TOKENS: list[str] = [
    # Vowels (5)
    "a", "i", "u", "e", "o",
    # Consonants (19, matching non-empty keys of kotoba.PLACE)
    "k", "g", "s", "z", "sh", "j", "t", "d", "ch", "ts",
    "n", "h", "f", "m", "y", "r", "w", "b", "p",
    # Special moras & pause (4)
    "N", "Q", ":", "pau",
]

_DEFAULT_ASCII_TOKENS: list[str] = (
    [" "]
    + [chr(c) for c in range(ord("a"), ord("z") + 1)]
    + [chr(c) for c in range(ord("0"), ord("9") + 1)]
    + ["'", "-", ",", "."]
)


def _default_vocab_for_mode(mode: str) -> list[str]:
    if mode == "kana":
        return [Tokenizer.BLANK_TOKEN, *_DEFAULT_KANA_TOKENS]
    if mode == "phoneme":
        return [Tokenizer.BLANK_TOKEN, *_DEFAULT_PHONEME_TOKENS]
    if mode == "ascii":
        return [Tokenizer.BLANK_TOKEN, *_DEFAULT_ASCII_TOKENS]
    raise ValueError(
        f"Invalid tokenizer mode {mode!r}; expected one of {Tokenizer.VALID_MODES}"
    )


class Tokenizer:
    """CTC-compatible tokenizer with ``<blank>`` fixed at index ``0``."""

    BLANK_TOKEN = "<blank>"
    VALID_MODES = ("kana", "phoneme", "ascii")

    def __init__(self, mode: str = "kana", vocab: list[str] | None = None) -> None:
        if mode not in self.VALID_MODES:
            raise ValueError(
                f"Invalid tokenizer mode {mode!r}; expected one of {self.VALID_MODES}"
            )
        self.mode: str = mode
        self.blank_token: str = self.BLANK_TOKEN

        if vocab is None:
            resolved_vocab = _default_vocab_for_mode(mode)
        else:
            resolved_vocab = list(vocab)
            if not resolved_vocab:
                resolved_vocab = [self.BLANK_TOKEN]
            elif resolved_vocab[0] != self.BLANK_TOKEN:
                if self.BLANK_TOKEN in resolved_vocab:
                    raise ValueError(
                        f"{self.BLANK_TOKEN!r} must be at index 0 when provided in vocab"
                    )
                resolved_vocab = [self.BLANK_TOKEN, *resolved_vocab]

        for tok in resolved_vocab:
            if not isinstance(tok, str):
                raise ValueError(
                    f"Tokenizer vocab entries must be strings, got {type(tok).__name__}: {tok!r}"
                )
        if len(set(resolved_vocab)) != len(resolved_vocab):
            raise ValueError("Tokenizer vocab contains duplicate tokens")

        self.vocab: list[str] = resolved_vocab
        self.token_to_id: dict[str, int] = {tok: i for i, tok in enumerate(self.vocab)}
        self.id_to_token: dict[int, str] = {i: tok for i, tok in enumerate(self.vocab)}
        self._has_multichar_kana: bool = (
            self.mode == "kana"
            and any(len(tok) > 1 for tok in self.vocab[1:])
        )

    @property
    def blank_id(self) -> int:
        return 0

    @property
    def vocab_size(self) -> int:
        return len(self.vocab)

    def _encode_kana(self, text: str) -> list[int]:
        kata = kotoba.to_kata(text).replace("\u3000", " ")
        ids: list[int] = []
        if self._has_multichar_kana:
            for mora in kotoba.split_moras(kata):
                if mora in self.token_to_id and mora != self.blank_token:
                    ids.append(self.token_to_id[mora])
                else:
                    for ch in mora:
                        idx = self.token_to_id.get(ch)
                        if idx is not None and idx != 0:
                            ids.append(idx)
            return ids

        for ch in kata:
            idx = self.token_to_id.get(ch)
            if idx is not None and idx != 0:
                ids.append(idx)
        return ids

    def _encode_phoneme(self, text: str) -> list[int]:
        stripped = text.strip()
        if not stripped:
            return []

        parts = stripped.split()
        if parts and all(
            p in self.token_to_id and p != self.blank_token for p in parts
        ):
            return [self.token_to_id[p] for p in parts]

        moras = kotoba.split_moras(stripped)
        tokens: list[str] = []
        pv = "a"
        for m in moras:
            if m == "、":
                tokens.append("pau")
            elif m == "ッ":
                tokens.append("Q")
            elif m == "ン":
                tokens.append("N")
            elif m == "ー":
                tokens.append(":")
            elif m in kotoba.K2V or (
                len(m) == 2 and m[0] in kotoba.K2V and m[1] in kotoba.SMALL
            ):
                c, v, pal = kotoba.parse_kana(m, pv)
                if c:
                    tokens.append(c)
                if pal:
                    tokens.append("y")
                if v:
                    tokens.append(v)
                    pv = v
            # Unknown tokens (kanji, ASCII, symbols) are skipped deterministically

        return [
            self.token_to_id[t]
            for t in tokens
            if t in self.token_to_id and t != self.blank_token
        ]

    def _encode_ascii(self, text: str) -> list[int]:
        ids: list[int] = []
        for ch in text.lower():
            idx = self.token_to_id.get(ch)
            if idx is not None and idx != 0:
                ids.append(idx)
        return ids

    def encode(self, text: str) -> list[int]:
        """Encode input text into a list of non-blank token IDs."""
        if not text:
            return []
        if self.mode == "kana":
            return self._encode_kana(text)
        if self.mode == "phoneme":
            return self._encode_phoneme(text)
        return self._encode_ascii(text)

    def decode_tokens(
        self, ids: Sequence[int], collapse_ctc: bool = False
    ) -> list[str]:
        """Decode token IDs into a list of token strings, optionally applying CTC collapse."""
        int_ids: list[int] = []
        for raw_id in ids:
            if isinstance(raw_id, bool) or not isinstance(raw_id, numbers.Integral):
                raise ValueError(
                    f"Token ID must be an integer, got {type(raw_id).__name__}: {raw_id!r}"
                )
            idx = int(raw_id)
            if idx < 0 or idx >= self.vocab_size:
                raise ValueError(
                    f"Token ID {idx} out of range [0, {self.vocab_size - 1}]"
                )
            int_ids.append(idx)

        if collapse_ctc:
            collapsed: list[int] = []
            prev: int | None = None
            for idx in int_ids:
                if idx != prev:
                    collapsed.append(idx)
                    prev = idx
            filtered = [idx for idx in collapsed if idx != self.blank_id]
        else:
            filtered = [idx for idx in int_ids if idx != self.blank_id]

        return [self.vocab[idx] for idx in filtered]

    def decode(self, ids: Sequence[int], collapse_ctc: bool = False) -> str:
        """Decode token IDs into a string, optionally applying CTC collapse."""
        tokens = self.decode_tokens(ids, collapse_ctc=collapse_ctc)
        sep = " " if self.mode == "phoneme" else ""
        return sep.join(tokens)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "vocab": list(self.vocab),
            "blank_token": self.blank_token,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Tokenizer:
        if not isinstance(d, Mapping):
            raise TypeError(
                f"Expected mapping for Tokenizer.from_dict, got {type(d).__name__}"
            )
        if "mode" not in d or "vocab" not in d:
            raise ValueError("Tokenizer dict must contain 'mode' and 'vocab'")
        vocab = d["vocab"]
        if not isinstance(vocab, (list, tuple)):
            raise ValueError(
                f"Tokenizer 'vocab' must be a list or tuple, got {type(vocab).__name__}"
            )
        return cls(mode=str(d["mode"]), vocab=list(vocab))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tokenizer):
            return NotImplemented
        return self.mode == other.mode and self.vocab == other.vocab

    def __repr__(self) -> str:
        return f"Tokenizer(mode={self.mode!r}, vocab_size={self.vocab_size})"
