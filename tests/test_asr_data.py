"""Unit tests for M2 speech data synthesis and dataset pipeline (asr/synth_data.py, asr/dataset.py)."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader

import carve
import kotoba
import yomu
from asr.audio import detect_vad, load_wav, save_wav
from asr.config import AudioConfig
from asr.dataset import (
    ASRManifestDataset,
    build_manifest_from_wav_dir,
    collate_asr_batch,
    load_manifest,
    write_manifest,
)
from asr.features import extract_log_mel
from asr.synth_data import (
    BUILTIN_CORPUS,
    DEFAULT_TSUKINAMI_PRESETS,
    TRAIN_CORPUS,
    VAL_CORPUS,
    generate_dataset,
    synthesize_fast_kotoba,
    synthesize_tsukinami,
)
from asr.tokenizer import Tokenizer


# ===========================================================================
# 1. Built-in Japanese Kana Corpus
# ===========================================================================


def test_builtin_corpus_diversity_and_kana_validity() -> None:
    tok = Tokenizer("kana")
    assert len(TRAIN_CORPUS) >= 100
    assert len(VAL_CORPUS) >= 20
    assert len(BUILTIN_CORPUS) == len(TRAIN_CORPUS) + len(VAL_CORPUS)
    assert len(set(BUILTIN_CORPUS)) == len(BUILTIN_CORPUS)
    assert set(TRAIN_CORPUS).isdisjoint(set(VAL_CORPUS))

    train_chars = set("".join(TRAIN_CORPUS))
    val_chars = set("".join(VAL_CORPUS))
    assert val_chars.issubset(train_chars), f"Unseen val chars: {val_chars - train_chars}"

    # Verify special moras and palatalized kana are present
    all_text = "".join(BUILTIN_CORPUS)
    for required_char in ("ン", "ッ", "ー", "ャ", "ュ", "ョ", "、"):
        assert required_char in all_text

    # Every utterance round-trips losslessly through Tokenizer("kana") and kotoba
    for text in BUILTIN_CORPUS:
        ids = tok.encode(text)
        assert len(ids) >= 1
        assert tok.decode(ids) == text
        ms = kotoba.split_moras(text)
        assert len(ms) >= 1
        tr = kotoba.tracks_from_kana(text)
        assert tr["n"] > 0 and len(tr["moras"]) >= 1


# ===========================================================================
# 2. Tier 1: synthesize_fast_kotoba
# ===========================================================================


def test_fast_kotoba_basic_schema_vad_and_determinism() -> None:
    wav1, moras1 = synthesize_fast_kotoba("ワタシ、ニホンゴ", sr=16000, seed=123)
    wav2, moras2 = synthesize_fast_kotoba("ワタシ、ニホンゴ", sr=16000, seed=123)
    wav_hira, moras_hira = synthesize_fast_kotoba("わたし、にほんご", sr=16000, seed=123)

    assert wav1.dtype == np.float32
    assert wav1.ndim == 1
    assert wav1.size > 0
    assert np.all(np.isfinite(wav1))
    assert float(np.min(wav1)) >= -1.0 and float(np.max(wav1)) <= 1.0
    assert float(np.sqrt(np.mean(wav1**2))) > 0.02

    # Bit-exact determinism and hiragana == katakana equivalence
    assert np.array_equal(wav1, wav2)
    assert moras1 == moras2
    assert np.array_equal(wav1, wav_hira)
    assert moras1 == moras_hira

    # Mora boundary schema & monotonicity
    assert len(moras1) >= 7
    dur = wav1.size / 16000.0
    prev_e = 0.0
    for m in moras1:
        assert set(m.keys()) == {"t", "a", "e"}
        assert isinstance(m["t"], str) and len(m["t"]) >= 1
        assert isinstance(m["a"], float) and isinstance(m["e"], float)
        assert 0.0 <= m["a"] < m["e"]
        assert m["a"] >= prev_e - 1e-4
        prev_e = m["e"]
    assert moras1[-1]["e"] <= dur + 0.05

    # VAD cleanly detects speech (silence padding stays below threshold)
    vad_segs = detect_vad(wav1, sr=16000)
    assert len(vad_segs) >= 1
    assert vad_segs[0][0] > 0.02


def test_fast_kotoba_phonetic_vowel_and_fricative_distinctiveness() -> None:
    cfg = AudioConfig(sample_rate=16000, cmvn=False)
    vowels = ("アアア", "イイイ", "ウウウ", "エエエ", "オオオ")
    mean_mels: dict[str, np.ndarray] = {}
    spectra: dict[str, np.ndarray] = {}

    for v in vowels:
        wav, _ = synthesize_fast_kotoba(v, sr=16000, seed=7)
        mel = extract_log_mel(wav, cfg)
        # Use middle 50% frames to avoid pre/post silence
        t0, t1 = mel.shape[0] // 4, (3 * mel.shape[0]) // 4
        mean_mels[v] = mel[t0:t1].mean(axis=0)

        s0, s1 = wav.size // 4, (3 * wav.size) // 4
        seg = wav[s0:s1] * np.hanning(s1 - s0)
        mag = np.abs(np.fft.rfft(seg, n=4096)) ** 2
        spectra[v] = mag / (mag.sum() + 1e-12)

    freqs = np.fft.rfftfreq(4096, d=1.0 / 16000.0)

    # All 5 vowels have pairwise distinct Log-Mel profiles
    for i, v1 in enumerate(vowels):
        for v2 in vowels[i + 1 :]:
            l2 = float(np.linalg.norm(mean_mels[v1] - mean_mels[v2]))
            assert l2 > 2.0, f"Vowels {v1} and {v2} too similar (L2={l2:.2f})"

    # /a/ has stronger F1 low-mid band (600-1300 Hz) than /i/
    f1_a_mask = (freqs >= 600.0) & (freqs <= 1300.0)
    assert spectra["アアア"][f1_a_mask].sum() > spectra["イイイ"][f1_a_mask].sum() * 1.5

    # /i/ has stronger high F2 band (2200-3600 Hz) than /o/
    f2_i_mask = (freqs >= 2200.0) & (freqs <= 3600.0)
    assert spectra["イイイ"][f2_i_mask].sum() > spectra["オオオ"][f2_i_mask].sum() * 1.5

    # Fricative /sh/ ("シシシ") has much higher >3 kHz energy ratio than vowel /a/ ("アアア")
    wav_sh, _ = synthesize_fast_kotoba("シシシ", sr=16000, seed=7)
    wav_a, _ = synthesize_fast_kotoba("アアア", sr=16000, seed=7)

    def _hf_ratio(w: np.ndarray) -> float:
        spec = np.abs(np.fft.rfft(w)) ** 2
        f = np.fft.rfftfreq(w.size, d=1.0 / 16000.0)
        hi = spec[f >= 3000.0].sum()
        lo = spec[(f >= 100.0) & (f <= 1200.0)].sum() + 1e-12
        return float(hi / lo)

    assert _hf_ratio(wav_sh) > _hf_ratio(wav_a) * 2.0


def test_fast_kotoba_speaker_params_and_edge_cases() -> None:
    def _centroid(w: np.ndarray, sr: int = 16000) -> float:
        mag = np.abs(np.fft.rfft(w))
        f = np.fft.rfftfreq(w.size, d=1.0 / sr)
        return float(np.sum(f * mag) / (np.sum(mag) + 1e-12))

    # fscale shifts spectral centroid upward
    w_low_f, _ = synthesize_fast_kotoba("アイウエオ", fscale=0.8, seed=1)
    w_hi_f, _ = synthesize_fast_kotoba("アイウエオ", fscale=1.25, seed=1)
    assert _centroid(w_hi_f) > _centroid(w_low_f) * 1.15

    # f0_scale changes fundamental frequency (autocorrelation peak)
    def _est_f0(w: np.ndarray, sr: int = 16000) -> float:
        mid = w[w.size // 3 : (2 * w.size) // 3].astype(np.float64)
        mid -= mid.mean()
        ac = np.correlate(mid, mid, mode="full")[mid.size - 1 :]
        lo_lag, hi_lag = sr // 450, sr // 80
        lag = lo_lag + int(np.argmax(ac[lo_lag:hi_lag]))
        return sr / float(lag)

    w_low_p, _ = synthesize_fast_kotoba("アアア", f0_scale=0.7, seed=1)
    w_hi_p, _ = synthesize_fast_kotoba("アアア", f0_scale=1.5, seed=1)
    assert _est_f0(w_hi_p) > _est_f0(w_low_p) * 1.6

    # rate scales both audio duration and mora spans
    w_fast, m_fast = synthesize_fast_kotoba("キョウモイッショ", rate=0.75, seed=1)
    w_slow, m_slow = synthesize_fast_kotoba("キョウモイッショ", rate=1.4, seed=1)
    assert w_slow.size > w_fast.size * 1.5
    assert (m_slow[-1]["e"] - m_slow[0]["a"]) > (m_fast[-1]["e"] - m_fast[0]["a"]) * 1.5

    # snr_db raises noise floor in pre-silence region and varies with seed
    w_clean, _ = synthesize_fast_kotoba("アイウ", snr_db=None, seed=10)
    w_noisy1, _ = synthesize_fast_kotoba("アイウ", snr_db=8.0, seed=10)
    w_noisy2, _ = synthesize_fast_kotoba("アイウ", snr_db=8.0, seed=11)
    assert float(np.sqrt(np.mean(w_noisy1[:800] ** 2))) > float(np.sqrt(np.mean(w_clean[:800] ** 2))) * 10.0
    assert not np.allclose(w_noisy1, w_noisy2)
    assert float(np.max(np.abs(w_noisy1))) <= 1.0

    # Custom sample rate
    w_8k, _ = synthesize_fast_kotoba("アイウ", sr=8000, seed=1)
    assert abs((w_8k.size / 8000.0) - (w_clean.size / 16000.0)) < 0.03

    # Edge cases: empty / punctuation / sokuon-only do not crash
    w_empty, m_empty = synthesize_fast_kotoba("")
    assert w_empty.dtype == np.float32 and w_empty.size == 0 and m_empty == []
    w_ws, m_ws = synthesize_fast_kotoba("   ")
    assert w_ws.size == 0 and m_ws == []
    w_ctrl, m_ctrl = synthesize_fast_kotoba("   \t\n  ")
    assert w_ctrl.dtype == np.float32 and w_ctrl.size == 0 and m_ctrl == []
    w_pau, m_pau = synthesize_fast_kotoba("、、、")
    assert w_pau.size == 0 and m_pau == []
    w_q, m_q = synthesize_fast_kotoba("ッ")
    assert w_q.dtype == np.float32 and w_q.size > 0 and len(m_q) == 1 and m_q[0]["t"] == "ッ"

    # Special moras N / prolonged vowel / sokuon inside words
    for s in ("ン", "ラーメン", "キット"):
        ws, ms = synthesize_fast_kotoba(s, seed=3)
        assert ws.dtype == np.float32 and ws.size > 0 and len(ms) >= 1

    # Invalid parameter validation
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", sr=0)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", f0_scale=-1.0)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", fscale=0.0)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", rate=-0.5)
    with pytest.raises(ValueError):
        synthesize_fast_kotoba("ア", snr_db=float("nan"))


def test_fast_kotoba_speed_benchmark() -> None:
    phrases = BUILTIN_CORPUS[:100]
    assert len(phrases) == 100
    t0 = time.perf_counter()
    total_samples = 0
    for i, phrase in enumerate(phrases):
        wav, moras = synthesize_fast_kotoba(phrase, sr=16000, seed=i)
        total_samples += wav.size
        assert len(moras) >= 1
    elapsed = time.perf_counter() - t0
    assert total_samples > 100 * 4000
    assert elapsed < 5.0, f"100 utterances took {elapsed:.2f}s (must be < 5.0s)"


# ===========================================================================
# 3. Tier 2: synthesize_tsukinami
# ===========================================================================


@pytest.mark.parametrize("preset", DEFAULT_TSUKINAMI_PRESETS)
def test_tsukinami_core_presets(preset: str) -> None:
    before_presets = copy.deepcopy(yomu.PRESETS)
    wav, moras = synthesize_tsukinami("ア", preset=preset, sr=16000)

    assert wav.dtype == np.float32
    assert wav.ndim == 1
    assert wav.size > 4000
    assert np.all(np.isfinite(wav))
    assert float(np.min(wav)) >= -1.0 and float(np.max(wav)) <= 1.0
    assert float(np.sqrt(np.mean(wav**2))) > 0.005

    assert len(moras) == 1
    assert set(moras[0].keys()) == {"t", "a", "e"}
    assert moras[0]["t"] == "ア"
    assert 0.0 <= moras[0]["a"] < moras[0]["e"] <= (wav.size / 16000.0) + 0.05

    # Global presets must never be mutated
    assert yomu.PRESETS == before_presets


def test_tsukinami_overrides_resampling_and_errors() -> None:
    overrides = {"hz": 165.0, "fscale": 0.85, "seed": 7}
    overrides_copy = copy.deepcopy(overrides)

    w_def, _ = synthesize_tsukinami("ア", preset="default", sr=16000)
    w_ovr, _ = synthesize_tsukinami("ア", preset="default", sr=16000, overrides=overrides)
    w_8k, _ = synthesize_tsukinami("ア", preset="default", sr=8000, overrides=overrides)

    assert overrides == overrides_copy
    assert not np.allclose(w_def[: min(w_def.size, w_ovr.size)], w_ovr[: min(w_def.size, w_ovr.size)])
    assert abs(w_8k.size - (w_ovr.size / 2.0)) <= 4

    with pytest.raises(ValueError):
        synthesize_tsukinami("ア", preset="nonexistent_preset")
    with pytest.raises(ValueError):
        synthesize_tsukinami("")
    with pytest.raises(ValueError):
        synthesize_tsukinami("   \t\n  ")
    with pytest.raises(ValueError):
        synthesize_tsukinami("ッ")
    with pytest.raises(ValueError):
        synthesize_tsukinami("、、、")
    with pytest.raises(ValueError):
        synthesize_tsukinami("ア", sr=0)


def test_tsukinami_disk_cache_hit_and_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "tts_cache"
    wav1, moras1 = synthesize_tsukinami("ア", preset="default", sr=16000, cache_dir=cache_dir)
    assert len(list(cache_dir.glob("*.wav"))) == 1
    assert len(list(cache_dir.glob("*.json"))) == 1

    def _boom(*_args, **_kwargs):
        raise AssertionError("carve.make should not be called on cache hit")

    monkeypatch.setattr(carve, "make", _boom)

    # Identical call hits disk cache cleanly and returns bit-identical audio
    wav2, moras2 = synthesize_tsukinami("ア", preset="default", sr=16000, cache_dir=cache_dir)
    assert moras1 == moras2
    assert wav1.shape == wav2.shape
    assert np.array_equal(wav1, wav2)

    # Different preset / overrides misses cache and invokes carve.make
    with pytest.raises(AssertionError, match="cache hit"):
        synthesize_tsukinami("ア", preset="robot", sr=16000, cache_dir=cache_dir)
    with pytest.raises(AssertionError, match="cache hit"):
        synthesize_tsukinami("ア", preset="default", sr=16000, overrides={"hz": 190.0}, cache_dir=cache_dir)


# ===========================================================================
# 4. generate_dataset
# ===========================================================================


def test_generate_dataset_fast_and_determinism(tmp_path: Path) -> None:
    out1 = generate_dataset(tmp_path / "ds1", num_train=10, num_val=4, engine="fast", seed=42)
    out2 = generate_dataset(tmp_path / "ds2", num_train=10, num_val=4, engine="fast", seed=42)

    assert set(out1.keys()) == {"train", "val"}
    assert out1["train"].is_file() and out1["val"].is_file()

    train_recs1 = load_manifest(out1["train"])
    val_recs1 = load_manifest(out1["val"])
    assert len(train_recs1) == 10
    assert len(val_recs1) == 4

    # Train/val texts come from disjoint corpus splits
    assert {r["text"] for r in train_recs1}.isdisjoint({r["text"] for r in val_recs1})

    required_keys = {"audio_path", "text", "duration", "speaker", "source", "moras"}
    for rec in train_recs1 + val_recs1:
        assert set(rec.keys()) == required_keys
        assert rec["source"] == "kotoba_fast"
        assert rec["duration"] > 0.0
        assert len(rec["moras"]) >= 1
        assert set(rec["moras"][0].keys()) == {"t", "a", "e"}
        wav_path = Path(rec["audio_path"])
        assert wav_path.is_absolute()
        assert wav_path.is_file()
        wav, sr = load_wav(wav_path, target_sr=16000)
        assert sr == 16000
        assert abs(rec["duration"] - (wav.size / 16000.0)) < 0.01

    # Determinism across runs with same seed (normalize audio_path relative to each dataset root)
    train_recs2 = load_manifest(out2["train"])
    val_recs2 = load_manifest(out2["val"])

    def _normalize(recs: list[dict], base: Path) -> list[dict]:
        base_resolved = base.resolve()
        return [
            {**r, "audio_path": Path(r["audio_path"]).relative_to(base_resolved).as_posix()}
            for r in recs
        ]

    assert _normalize(train_recs1, tmp_path / "ds1") == _normalize(train_recs2, tmp_path / "ds2")
    assert _normalize(val_recs1, tmp_path / "ds1") == _normalize(val_recs2, tmp_path / "ds2")
    assert train_recs1[0]["audio_path"] != train_recs2[0]["audio_path"]
    wav1_bytes = Path(train_recs1[0]["audio_path"]).read_bytes()
    wav2_bytes = Path(train_recs2[0]["audio_path"]).read_bytes()
    assert wav1_bytes == wav2_bytes


def test_generate_dataset_tsukinami_mixed_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Use short 1-2 mora corpus subsets for fast tsukinami/mixed integration tests
    monkeypatch.setattr("asr.synth_data.TRAIN_CORPUS", ("ア", "イ", "ウ", "エ"))
    monkeypatch.setattr("asr.synth_data.VAL_CORPUS", ("オ", "カ"))

    tsuki_out = generate_dataset(
        tmp_path / "ds_tsuki",
        num_train=2,
        num_val=1,
        engine="tsukinami",
        seed=7,
        presets=("default", "ossan"),
    )
    tsuki_train = load_manifest(tsuki_out["train"])
    assert len(tsuki_train) == 2
    assert all(r["source"] == "tsukinami" for r in tsuki_train)
    assert {r["speaker"] for r in tsuki_train} == {"default", "ossan"}

    mixed_out = generate_dataset(
        tmp_path / "ds_mixed",
        num_train=4,
        num_val=2,
        engine="mixed",
        seed=7,
        presets=("default",),
    )
    mixed_train = load_manifest(mixed_out["train"])
    sources = {r["source"] for r in mixed_train}
    assert sources == {"kotoba_fast", "tsukinami"}

    with pytest.raises(ValueError):
        generate_dataset(tmp_path / "bad1", engine="bogus")
    with pytest.raises(ValueError):
        generate_dataset(tmp_path / "bad2", num_train=0, num_val=1)
    with pytest.raises(ValueError):
        generate_dataset(tmp_path / "bad3", num_train=1, num_val=-1)
    with pytest.raises(ValueError):
        generate_dataset(tmp_path / "bad4", presets=())
    with pytest.raises(ValueError):
        generate_dataset(tmp_path / "bad5", presets=("not_a_preset",))


# ===========================================================================
# 5. ASRManifestDataset, collate_asr_batch & PyTorch DataLoader + CTCLoss
# ===========================================================================


def test_dataset_collate_dataloader_and_ctc_loss(tmp_path: Path) -> None:
    paths = generate_dataset(tmp_path / "ds", num_train=6, num_val=2, engine="fast", seed=9)
    audio_cfg = AudioConfig(sample_rate=16000, n_mels=64)
    tok = Tokenizer("kana")

    ds_clean = ASRManifestDataset(paths["train"], audio_cfg, tok, augment=False)
    ds_aug = ASRManifestDataset(paths["train"], audio_cfg, tok, augment=True)
    assert len(ds_clean) == 6

    item0 = ds_clean[0]
    item0_again = ds_clean[0]
    item_last = ds_clean[-1]
    assert item0["feats"].dtype == torch.float32
    assert item0["feats"].ndim == 2 and item0["feats"].shape[1] == 64
    assert item0["targets"].dtype == torch.long and item0["targets"].ndim == 1
    assert item0["feat_length"] == item0["feats"].shape[0]
    assert item0["target_length"] == item0["targets"].shape[0]
    assert torch.equal(item0["feats"], item0_again["feats"])
    assert isinstance(item_last["text"], str) and len(item_last["text"]) > 0

    # SpecAugment introduces stochastic masking when augment=True
    aug_diffs = [not torch.equal(ds_clean[i]["feats"], ds_aug[i]["feats"]) for i in range(len(ds_clean))]
    assert any(aug_diffs)

    # Phoneme tokenizer compatibility
    ds_ph = ASRManifestDataset(paths["val"], audio_cfg, Tokenizer("phoneme"), augment=False)
    assert ds_ph[0]["targets"].numel() >= 1

    # DataLoader + collate_asr_batch + nn.CTCLoss integration
    loader = DataLoader(ds_clean, batch_size=4, shuffle=False, collate_fn=collate_asr_batch)
    batches = list(loader)
    assert len(batches) == 2

    batch = batches[0]
    assert set(batch.keys()) == {"feats", "feat_lengths", "targets", "target_lengths", "texts"}
    assert batch["feats"].dtype == torch.float32
    assert batch["feat_lengths"].dtype == torch.long
    assert batch["targets"].dtype == torch.long
    assert batch["target_lengths"].dtype == torch.long
    assert isinstance(batch["texts"], list) and len(batch["texts"]) == 4

    b, t_max, f_dim = batch["feats"].shape
    l_max = batch["targets"].shape[1]
    assert (b, f_dim) == (4, 64)
    assert int(batch["feat_lengths"].max()) == t_max
    assert int(batch["target_lengths"].max()) == l_max

    # Verify zero/blank padding beyond sequence lengths
    for i in range(b):
        fl = int(batch["feat_lengths"][i])
        tl = int(batch["target_lengths"][i])
        if fl < t_max:
            assert torch.all(batch["feats"][i, fl:, :] == 0.0)
        if tl < l_max:
            assert torch.all(batch["targets"][i, tl:] == tok.blank_id)

    # Real torch.nn.CTCLoss compatibility check
    log_probs = torch.log_softmax(torch.randn(t_max, b, tok.vocab_size), dim=-1)
    ctc_loss = torch.nn.CTCLoss(blank=tok.blank_id, zero_infinity=True)
    loss = ctc_loss(log_probs, batch["targets"], batch["feat_lengths"], batch["target_lengths"])
    assert torch.isfinite(loss) and float(loss.item()) >= 0.0


def test_dataset_path_resolution_and_error_handling(tmp_path: Path) -> None:
    wav, _ = synthesize_fast_kotoba("サクラ", sr=16000, seed=1)
    abs_wav = tmp_path / "abs_sample.wav"
    save_wav(abs_wav, wav, sr=16000)

    # Absolute path in manifest
    abs_manifest = write_manifest(
        [{"audio_path": str(abs_wav), "text": "サクラ"}],
        tmp_path / "abs.jsonl",
    )
    ds = ASRManifestDataset(abs_manifest, AudioConfig(), Tokenizer("kana"))
    assert len(ds) == 1 and ds[0]["text"] == "サクラ"

    # Error cases
    with pytest.raises(FileNotFoundError):
        ASRManifestDataset(tmp_path / "missing.jsonl")

    bad_json = tmp_path / "bad.jsonl"
    bad_json.write_text("{not valid json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ASRManifestDataset(bad_json)

    missing_key = tmp_path / "missing_key.jsonl"
    missing_key.write_text(json.dumps({"audio_path": str(abs_wav)}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ASRManifestDataset(missing_key)

    empty_manifest = tmp_path / "empty.jsonl"
    empty_manifest.write_text("\n   \n", encoding="utf-8")
    with pytest.raises(ValueError):
        ASRManifestDataset(empty_manifest)

    missing_wav_manifest = write_manifest(
        [{"audio_path": "does_not_exist.wav", "text": "サクラ"}],
        tmp_path / "missing_wav.jsonl",
    )
    with pytest.raises(FileNotFoundError):
        ASRManifestDataset(missing_wav_manifest)

    empty_target_manifest = write_manifest(
        [{"audio_path": str(abs_wav), "text": "12345"}],  # not in kana vocab
        tmp_path / "empty_target.jsonl",
    )
    with pytest.raises(ValueError):
        ASRManifestDataset(empty_target_manifest, AudioConfig(), Tokenizer("kana"))

    with pytest.raises(ValueError):
        collate_asr_batch([])

    with pytest.raises(ValueError):
        collate_asr_batch(
            [
                {"feats": torch.zeros(10, 64), "targets": torch.tensor([1]), "text": "ア"},
                {"feats": torch.zeros(12, 80), "targets": torch.tensor([2]), "text": "イ"},
            ]
        )


# ===========================================================================
# 6. Tier 3: build_manifest_from_wav_dir
# ===========================================================================


def test_build_manifest_from_wav_dir_dict_and_files(tmp_path: Path) -> None:
    wav_dir = tmp_path / "wavs"
    sub_dir = wav_dir / "sub"
    sub_dir.mkdir(parents=True)

    for rel, text in (
        ("a.wav", "サクラ"),
        ("b.wav", "ツキナミ"),
        ("sub/c.wav", "オハヨウ"),
        ("ignored.wav", "ネコ"),
    ):
        w, _ = synthesize_fast_kotoba(text, sr=16000, seed=1)
        save_wav(wav_dir / rel, w, sr=16000)

    # 1. Dict map keyed by filename, stem, and relative POSIX path
    out_dict = build_manifest_from_wav_dir(
        wav_dir,
        {"a.wav": "サクラ", "b": "ツキナミ", "sub/c.wav": "オハヨウ"},
        tmp_path / "manifest_dict.jsonl",
        speaker="user_mic",
        source="real_wav",
    )
    assert out_dict.is_file()
    recs = load_manifest(out_dict)
    assert len(recs) == 3
    assert [r["text"] for r in recs] == ["サクラ", "ツキナミ", "オハヨウ"]
    assert all(r["speaker"] == "user_mic" and r["source"] == "real_wav" for r in recs)
    assert all(r["duration"] > 0.0 and r["moras"] == [] for r in recs)
    assert all(Path(r["audio_path"]).is_absolute() and Path(r["audio_path"]).is_file() for r in recs)

    # Load generated manifest directly into ASRManifestDataset + DataLoader
    ds = ASRManifestDataset(out_dict, AudioConfig(), Tokenizer("kana"))
    batch = next(iter(DataLoader(ds, batch_size=3, collate_fn=collate_asr_batch)))
    assert batch["texts"] == ["サクラ", "ツキナミ", "オハヨウ"]

    # 2. TSV file
    tsv_path = tmp_path / "transcripts.tsv"
    tsv_path.write_text("a\tサクラ\nb\tツキナミ\n", encoding="utf-8")
    out_tsv = build_manifest_from_wav_dir(wav_dir, tsv_path, tmp_path / "manifest_tsv.jsonl")
    assert len(load_manifest(out_tsv)) == 2

    # 3. JSUT id:text format
    jsut_path = tmp_path / "transcript_utf8.txt"
    jsut_path.write_text("a:サクラ\nsub/c.wav:オハヨウ\n", encoding="utf-8")
    out_jsut = build_manifest_from_wav_dir(wav_dir, jsut_path, tmp_path / "manifest_jsut.jsonl")
    assert [r["text"] for r in load_manifest(out_jsut)] == ["サクラ", "オハヨウ"]

    # 4. JSON file
    json_path = tmp_path / "transcripts.json"
    json_path.write_text(json.dumps({"a.wav": "サクラ"}, ensure_ascii=False), encoding="utf-8")
    out_json = build_manifest_from_wav_dir(wav_dir, json_path, tmp_path / "manifest_json.jsonl")
    assert [r["text"] for r in load_manifest(out_json)] == ["サクラ"]


def test_build_manifest_from_wav_dir_errors(tmp_path: Path) -> None:
    wav_dir = tmp_path / "wavs"
    wav_dir.mkdir()
    w, _ = synthesize_fast_kotoba("ア", sr=16000, seed=1)
    save_wav(wav_dir / "good.wav", w, sr=16000)
    (wav_dir / "corrupt.wav").write_bytes(b"NOT_A_WAV")

    with pytest.raises(FileNotFoundError):
        build_manifest_from_wav_dir(tmp_path / "no_such_dir", {"a": "ア"}, tmp_path / "m.jsonl")

    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(not_a_dir, {"a": "ア"}, tmp_path / "m.jsonl")

    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(wav_dir, {"unmatched": "ア"}, tmp_path / "m.jsonl")

    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(wav_dir, {"good": "   "}, tmp_path / "m.jsonl")

    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(wav_dir, {"good": None}, tmp_path / "m.jsonl")  # type: ignore[dict-item]

    null_json = tmp_path / "null_transcript.json"
    null_json.write_text(json.dumps({"good": None}), encoding="utf-8")
    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(wav_dir, null_json, tmp_path / "m.jsonl")

    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(wav_dir, {"corrupt": "ア"}, tmp_path / "m.jsonl")


def test_build_manifest_from_wav_dir_empty_and_unmatched(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_wavs"
    empty_dir.mkdir()

    # Empty wav_dir + empty transcript_map -> writes empty JSONL manifest and returns Path
    out_empty = build_manifest_from_wav_dir(empty_dir, {}, tmp_path / "empty.jsonl")
    assert isinstance(out_empty, Path)
    assert out_empty.is_file()
    assert load_manifest(out_empty) == []

    # Empty wav_dir + non-empty transcript_map -> raises ValueError
    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(empty_dir, {"a.wav": "ア"}, tmp_path / "empty_unmatched.jsonl")

    # Non-empty wav_dir + empty or unmatched transcript_map -> raises ValueError
    non_empty_dir = tmp_path / "non_empty_wavs"
    non_empty_dir.mkdir()
    w, _ = synthesize_fast_kotoba("ア", sr=16000, seed=2)
    save_wav(non_empty_dir / "a.wav", w, sr=16000)

    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(non_empty_dir, {}, tmp_path / "non_empty_empty_map.jsonl")

    with pytest.raises(ValueError):
        build_manifest_from_wav_dir(
            non_empty_dir, {"unmatched": "ア"}, tmp_path / "non_empty_unmatched.jsonl"
        )

