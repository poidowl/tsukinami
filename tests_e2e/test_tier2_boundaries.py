"""Tier 2 E2E Tests: Boundary, Corner-Case & Negative Coverage across all 18 features.

Every feature area (#1-#18) has >= 5 genuine boundary, edge-case, or negative
tests verifying graceful error handling, numerical stability, and edge-input
correctness against PROJECT.md § Interface Contracts.
"""

from __future__ import annotations

import math
from html.parser import HTMLParser
from pathlib import Path

import pytest


# ===========================================================================
# Feature 1: Config Boundaries
# ===========================================================================


class TestTier2Feature01ConfigBoundaries:
    def test_model_config_invalid_arch_rejected(self):
        from asr.config import DecodeConfig, ModelConfig

        with pytest.raises(ValueError):
            ModelConfig(arch="invalid_arch_xyz")
        with pytest.raises(ValueError):
            DecodeConfig(method="invalid_method")

    def test_decode_config_boundary_numeric_values(self):
        from asr.config import DecodeConfig

        cfg = DecodeConfig(
            method="greedy",
            beam_width=1,
            temperature=0.05,
            blank_bias=-5.0,
            lm_weight=0.0,
            insertion_bonus=-1.0,
        )
        assert DecodeConfig.from_dict(cfg.to_dict()) == cfg

    def test_config_from_dict_empty_or_partial_handled_cleanly(self):
        from asr.config import AudioConfig, DecodeConfig, ModelConfig, TrainConfig

        for cls in (AudioConfig, ModelConfig, TrainConfig, DecodeConfig):
            try:
                inst = cls.from_dict({})
                assert isinstance(inst, cls)
            except (KeyError, TypeError, ValueError):
                pass

    def test_audio_config_extreme_nyquist_values(self):
        from asr.config import AudioConfig

        cfg = AudioConfig(
            sample_rate=8000,
            n_fft=256,
            win_length=200,
            hop_length=80,
            n_mels=32,
            f_min=0.0,
            f_max=4000.0,
            preemphasis=0.0,
            cmvn=False,
        )
        assert AudioConfig.from_dict(cfg.to_dict()) == cfg

    def test_train_config_minimal_boundary_values(self):
        from asr.config import TrainConfig

        cfg = TrainConfig(
            epochs=1,
            batch_size=1,
            lr=1e-6,
            weight_decay=0.0,
            grad_clip=0.0,
            seed=0,
            use_spec_augment=False,
            checkpoint_dir=".",
        )
        assert TrainConfig.from_dict(cfg.to_dict()) == cfg


# ===========================================================================
# Feature 2: WAV/PCM I/O & Resampling Boundaries
# ===========================================================================


class TestTier2Feature02AudioIOBoundaries:
    def test_load_wav_missing_file_raises_file_not_found(self, tmp_path: Path):
        from asr.audio import load_wav

        with pytest.raises(FileNotFoundError):
            load_wav(tmp_path / "does_not_exist.wav")

    def test_load_wav_corrupt_garbage_raises_value_error(self, tmp_path: Path, helpers):
        from asr.audio import load_wav

        p = helpers.write_corrupt_wav(tmp_path / "garbage.wav", "garbage")
        with pytest.raises(ValueError):
            load_wav(p)

    def test_load_wav_empty_file_raises_value_error(self, tmp_path: Path, helpers):
        from asr.audio import load_wav

        p = helpers.write_corrupt_wav(tmp_path / "empty.wav", "empty")
        with pytest.raises(ValueError):
            load_wav(p)

    def test_load_wav_truncated_header_raises_value_error(self, tmp_path: Path, helpers):
        from asr.audio import load_wav

        p = helpers.write_corrupt_wav(tmp_path / "truncated.wav", "truncated")
        with pytest.raises(ValueError):
            load_wav(p)

    def test_save_wav_clips_out_of_range_values(self, tmp_path: Path, helpers):
        import numpy as np
        from asr.audio import load_wav, save_wav

        clipped = helpers.make_clipped(duration=0.3, sr=16000, amp=3.0)
        p = tmp_path / "clipped.wav"
        save_wav(p, clipped, sr=16000)
        loaded, sr = load_wav(p, target_sr=16000)
        assert sr == 16000
        assert np.isfinite(loaded).all()
        assert float(np.min(loaded)) >= -1.0 and float(np.max(loaded)) <= 1.0
        # Positive peaks in clipped signal must remain positive (no int16 wrap-around)
        pos_mask = clipped > 1.5
        assert float(np.mean(loaded[pos_mask])) > 0.8

    def test_resample_identity_empty_and_invalid_sr(self, helpers):
        import numpy as np
        from asr.audio import resample

        wav = helpers.make_sine(440.0, 0.25, 16000)
        same = resample(wav, 16000, 16000)
        assert len(same) == len(wav)
        assert np.allclose(same, wav, atol=1e-4)

        empty = resample(np.zeros(0, dtype=np.float32), 16000, 8000)
        assert empty.dtype == np.float32 and len(empty) == 0

        with pytest.raises(ValueError):
            resample(wav, 0, 16000)
        with pytest.raises(ValueError):
            resample(wav, 16000, -8000)


# ===========================================================================
# Feature 3: Feature Extraction Boundaries
# ===========================================================================


class TestTier2Feature03FeaturesBoundaries:
    def test_extract_log_mel_pure_silence_is_finite(self, helpers):
        import numpy as np
        from asr.features import extract_log_mel

        mel = extract_log_mel(helpers.make_silence(0.5, 16000))
        assert mel.dtype == np.float32
        assert mel.ndim == 2 and mel.shape[1] == 64
        assert np.isfinite(mel).all()

    def test_extract_log_mel_very_short_audio_shorter_than_win_length(self):
        import numpy as np
        from asr.features import extract_log_mel

        short = np.linspace(-0.2, 0.2, 100, dtype=np.float32)
        mel = extract_log_mel(short)
        assert mel.dtype == np.float32
        assert mel.ndim == 2 and mel.shape[0] >= 1 and mel.shape[1] == 64
        assert np.isfinite(mel).all()

    def test_extract_log_mel_constant_dc_signal_finite(self):
        import numpy as np
        from asr.features import extract_log_mel

        dc = np.full(1600, 0.5, dtype=np.float32)
        mel = extract_log_mel(dc)
        assert mel.dtype == np.float32
        assert mel.ndim == 2 and mel.shape[1] == 64
        assert np.isfinite(mel).all()

    def test_extract_mfcc_silence_and_deltas_short_audio(self, helpers):
        import numpy as np
        from asr.features import extract_mfcc

        mfcc = extract_mfcc(helpers.make_silence(0.05, 16000), n_mfcc=13, include_deltas=True)
        assert mfcc.dtype == np.float32
        assert mfcc.ndim == 2 and mfcc.shape[1] == 39
        assert np.isfinite(mfcc).all()

    def test_extract_log_mel_preemphasis_zero_vs_high(self, helpers):
        import numpy as np
        from asr.config import AudioConfig
        from asr.features import extract_log_mel

        wav = helpers.make_speech_like(0.6, 16000)
        m0 = extract_log_mel(wav, AudioConfig(preemphasis=0.0))
        m99 = extract_log_mel(wav, AudioConfig(preemphasis=0.99))
        assert m0.shape == m99.shape
        assert np.isfinite(m0).all() and np.isfinite(m99).all()


# ===========================================================================
# Feature 4: Energy VAD Boundaries
# ===========================================================================


class TestTier2Feature04VADBoundaries:
    def test_detect_vad_pure_silence_returns_empty(self, helpers):
        from asr.audio import detect_vad

        assert detect_vad(helpers.make_silence(1.0, 16000), sr=16000) == []

    def test_detect_vad_empty_array_returns_empty(self):
        import numpy as np
        from asr.audio import detect_vad

        assert detect_vad(np.zeros(0, dtype=np.float32), sr=16000) == []

    def test_detect_vad_continuous_loud_signal_single_span(self, helpers):
        from asr.audio import detect_vad

        segs = detect_vad(helpers.make_sine(440.0, 1.0, 16000, amp=0.8), sr=16000)
        assert len(segs) == 1
        assert segs[0][0] <= 0.05 and segs[0][1] >= 0.95

    def test_detect_vad_very_short_sub_frame_audio(self, helpers):
        from asr.audio import detect_vad

        short = helpers.make_sine(440.0, 50 / 16000.0, 16000, amp=0.5)
        segs = detect_vad(short, sr=16000, frame_ms=20.0)
        assert isinstance(segs, list)

    def test_detect_vad_zero_hangover_and_extreme_thresholds(self, helpers):
        from asr.audio import detect_vad

        wav = helpers.make_sine(440.0, 0.5, 16000, amp=0.1)
        segs_zero_ho = detect_vad(wav, sr=16000, hangover_ms=0.0)
        assert isinstance(segs_zero_ho, list)
        assert detect_vad(wav, sr=16000, threshold_db=0.0) == []
        assert len(detect_vad(wav, sr=16000, threshold_db=-120.0)) >= 1


# ===========================================================================
# Feature 5: SpecAugment & Corruption Boundaries
# ===========================================================================


class TestTier2Feature05AugmentBoundaries:
    def test_spec_augment_zero_masks_returns_unchanged(self, helpers):
        import numpy as np
        from asr.features import extract_log_mel, spec_augment

        mel = extract_log_mel(helpers.make_speech_like(0.8, 16000))
        out = spec_augment(mel, freq_mask_param=8, time_mask_param=20, num_freq_masks=0, num_time_masks=0, seed=0)
        assert np.array_equal(out, mel)

    def test_spec_augment_mask_larger_than_dimensions(self):
        import numpy as np
        from asr.features import spec_augment

        tiny_mel = np.ones((5, 16), dtype=np.float32)
        out = spec_augment(tiny_mel, freq_mask_param=200, time_mask_param=500, num_freq_masks=2, num_time_masks=2, seed=1)
        assert out.shape == (5, 16)
        assert np.isfinite(out).all()

    def test_apply_corruption_noop_defaults(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        wav = helpers.make_sine(440.0, 0.5, 16000, amp=0.5)
        out = apply_corruption(wav, 16000)
        assert out.dtype == np.float32
        assert len(out) == len(wav)
        assert np.allclose(out, wav, atol=1e-4)

    def test_apply_corruption_invalid_noise_type_raises(self, helpers):
        from asr.audio import apply_corruption

        wav = helpers.make_sine(440.0, 0.3, 16000)
        with pytest.raises(ValueError):
            apply_corruption(wav, 16000, snr_db=10.0, noise_type="brown")

    def test_apply_corruption_extreme_snr_values(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        wav = helpers.make_sine(440.0, 0.5, 16000, amp=0.4)
        heavy = apply_corruption(wav, 16000, snr_db=-10.0, noise_type="white", seed=0)
        light = apply_corruption(wav, 16000, snr_db=60.0, noise_type="white", seed=0)
        assert heavy.shape == wav.shape and np.isfinite(heavy).all()
        assert light.shape == wav.shape and np.isfinite(light).all()

    def test_apply_corruption_silence_input_with_noise(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        sil = helpers.make_silence(0.4, 16000)
        out = apply_corruption(sil, 16000, snr_db=10.0, noise_type="white", seed=0)
        assert out.dtype == np.float32
        assert len(out) == len(sil)
        assert np.isfinite(out).all()


# ===========================================================================
# Feature 6: Tokenizer Boundaries
# ===========================================================================


class TestTier2Feature06TokenizerBoundaries:
    def test_tokenizer_invalid_mode_raises_value_error(self):
        from asr.tokenizer import Tokenizer

        with pytest.raises(ValueError):
            Tokenizer(mode="invalid_mode_xyz")

    def test_tokenizer_empty_string_encode_and_empty_decode(self):
        from asr.tokenizer import Tokenizer

        for mode in ("kana", "phoneme", "ascii"):
            tok = Tokenizer(mode=mode)
            assert tok.encode("") == []
            assert tok.decode([]) == ""

    def test_tokenizer_decode_all_blanks_returns_empty(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        assert tok.decode([0, 0, 0, 0], collapse_ctc=True) == ""
        assert tok.decode([0, 0], collapse_ctc=False) == ""

    def test_tokenizer_unknown_characters_do_not_crash(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        ids = tok.encode("🎵🚀123XYZ漢字")
        assert isinstance(ids, list)
        assert all(isinstance(i, int) and 0 <= i < tok.vocab_size for i in ids)

    def test_tokenizer_punctuation_and_small_kana_mora_handling(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        ids = tok.encode("きゃ、きゅ、きょ！っんー")
        assert len(ids) > 0
        decoded = tok.decode(ids, collapse_ctc=False)
        assert isinstance(decoded, str) and len(decoded) > 0

    def test_tokenizer_ascii_case_and_spaces(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="ascii")
        ids = tok.encode("Hello   WORLD")
        assert isinstance(ids, list) and len(ids) > 0
        assert isinstance(tok.decode(ids), str)


# ===========================================================================
# Feature 7: Fast Kotoba Synth Boundaries
# ===========================================================================


class TestTier2Feature07FastSynthBoundaries:
    def test_fast_kotoba_single_mora(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        wav, moras = synthesize_fast_kotoba("ア", sr=16000, seed=1)
        assert wav.dtype == np.float32 and len(wav) > 0 and np.isfinite(wav).all()
        assert len(moras) >= 1

    def test_fast_kotoba_special_moras_sokuon_hatuon_chouon(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        wav, moras = synthesize_fast_kotoba("カッパ、アンパン、カー", sr=16000, seed=2)
        assert wav.dtype == np.float32 and len(wav) > 1000 and np.isfinite(wav).all()
        assert len(moras) >= 5

    def test_fast_kotoba_extreme_f0_and_fscale(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        w_low, _ = synthesize_fast_kotoba("アイウ", sr=16000, f0_scale=0.5, fscale=0.7, seed=3)
        w_high, _ = synthesize_fast_kotoba("アイウ", sr=16000, f0_scale=1.8, fscale=1.4, seed=3)
        assert np.isfinite(w_low).all() and len(w_low) > 0
        assert np.isfinite(w_high).all() and len(w_high) > 0

    def test_fast_kotoba_empty_or_punctuation_only_text(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        for txt in ("", "、、、"):
            try:
                wav, moras = synthesize_fast_kotoba(txt, sr=16000, seed=4)
                assert wav.dtype == np.float32 and np.isfinite(wav).all()
                assert isinstance(moras, list)
            except ValueError:
                pass

    def test_fast_kotoba_low_snr_heavy_noise(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        wav, _ = synthesize_fast_kotoba("アイウ", sr=16000, snr_db=-5.0, seed=9)
        assert wav.dtype == np.float32 and len(wav) > 0 and np.isfinite(wav).all()


# ===========================================================================
# Feature 8: Tsukinami TTS Boundaries
# ===========================================================================


class TestTier2Feature08TsukinamiTTSBoundaries:
    def test_tsukinami_invalid_preset_raises(self):
        from asr.synth_data import synthesize_tsukinami

        with pytest.raises((ValueError, KeyError)):
            synthesize_tsukinami("あい", preset="nonexistent_preset_xyz", sr=16000)

    def test_tsukinami_single_mora(self, tsukinami_cache_dir: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        wav, moras = synthesize_tsukinami("あ", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)
        assert wav.dtype == np.float32 and len(wav) > 0 and np.isfinite(wav).all()
        assert len(moras) >= 1

    def test_tsukinami_hiragana_vs_katakana_equivalence(self, tsukinami_cache_dir: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        w_h, m_h = synthesize_tsukinami("あい", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)
        w_k, m_k = synthesize_tsukinami("アイ", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)
        assert np.isfinite(w_h).all() and np.isfinite(w_k).all()
        assert len(m_h) == len(m_k)

    def test_tsukinami_whisper_and_chibi_presets(self, tsukinami_cache_dir: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        for preset in ("whisper", "chibi"):
            wav, _ = synthesize_tsukinami("あ", preset=preset, sr=16000, cache_dir=tsukinami_cache_dir)
            assert wav.dtype == np.float32 and len(wav) > 0 and np.isfinite(wav).all()

    def test_tsukinami_cache_dir_none_works(self):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        wav, moras = synthesize_tsukinami("あ", preset="default", sr=16000, cache_dir=None)
        assert wav.dtype == np.float32 and len(wav) > 0 and np.isfinite(wav).all()
        assert isinstance(moras, list)


# ===========================================================================
# Feature 9: Manifest & DataLoader Boundaries
# ===========================================================================


class TestTier2Feature09DatasetBoundaries:
    def test_dataset_missing_manifest_raises_file_not_found(self, tmp_path: Path):
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset
        from asr.tokenizer import Tokenizer

        with pytest.raises(FileNotFoundError):
            ASRManifestDataset(tmp_path / "missing.jsonl", AudioConfig(), Tokenizer("kana"))

    def test_collate_single_item_batch(self, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset, collate_asr_batch
        from asr.tokenizer import Tokenizer

        ds = ASRManifestDataset(tiny_fast_dataset["train"], AudioConfig(), Tokenizer("kana"))
        batch = collate_asr_batch([ds[0]])
        assert batch["feats"].shape[0] == 1 and batch["feats"].shape[2] == 64
        assert batch["targets"].shape[0] == 1
        assert len(batch["texts"]) == 1

    def test_collate_highly_variable_lengths(self, tmp_path: Path):
        import torch
        from asr.audio import save_wav
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset, build_manifest_from_wav_dir, collate_asr_batch
        from asr.synth_data import synthesize_fast_kotoba
        from asr.tokenizer import Tokenizer

        wdir = tmp_path / "var_wavs"
        w_short, _ = synthesize_fast_kotoba("ア", sr=16000, seed=1)
        w_long, _ = synthesize_fast_kotoba("アイウエオカキクケコ", sr=16000, seed=2)
        save_wav(wdir / "short.wav", w_short, sr=16000)
        save_wav(wdir / "long.wav", w_long, sr=16000)

        mpath = build_manifest_from_wav_dir(wdir, {"short.wav": "ア", "long.wav": "アイウエオカキクケコ"}, tmp_path / "var.jsonl")
        ds = ASRManifestDataset(mpath, AudioConfig(), Tokenizer("kana"))
        batch = collate_asr_batch([ds[0], ds[1]])
        lens = batch["feat_lengths"].tolist()
        tlens = batch["target_lengths"].tolist()
        assert min(lens) < max(lens)
        assert min(tlens) < max(tlens)
        assert batch["feats"].shape[1] == max(lens)
        assert torch.isfinite(batch["feats"]).all()

    def test_build_manifest_from_wav_dir_empty_dir(self, tmp_path: Path):
        from asr.dataset import build_manifest_from_wav_dir

        empty_dir = tmp_path / "empty_wavs"
        empty_dir.mkdir()
        out = build_manifest_from_wav_dir(empty_dir, {}, tmp_path / "empty.jsonl")
        assert Path(out).is_file()
        lines = [ln for ln in Path(out).read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 0

    def test_generate_dataset_invalid_engine_raises(self, tmp_path: Path):
        from asr.synth_data import generate_dataset

        with pytest.raises(ValueError):
            generate_dataset(tmp_path / "bad_eng", num_train=2, num_val=1, engine="unknown_engine_xyz")


# ===========================================================================
# Feature 10: Acoustic Model Boundaries
# ===========================================================================


class TestTier2Feature10ModelsBoundaries:
    def test_build_model_invalid_arch_raises_value_error(self):
        from asr.config import ModelConfig
        from asr.models import build_model

        with pytest.raises(ValueError):
            build_model(ModelConfig(arch="resnet_999"), vocab_size=50)

    def test_model_batch_size_one_and_minimum_valid_frames(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        for arch in ("cnn_bigru", "conformer_lite"):
            cfg = ModelConfig(arch=arch, n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)
            model = build_model(cfg, vocab_size=30)
            lp, out_len = model(torch.randn(1, 16, 64), torch.tensor([16]))
            assert lp.shape[0] == 1 and lp.shape[2] == 30
            assert int(out_len[0]) >= 1
            assert torch.isfinite(lp).all()

    def test_model_extreme_length_disparity_in_batch(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        for arch in ("cnn_bigru", "conformer_lite"):
            cfg = ModelConfig(arch=arch, n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)
            model = build_model(cfg, vocab_size=30)
            lp, out_len = model(torch.randn(2, 120, 64), torch.tensor([120, 16]))
            assert int(out_len[0]) > int(out_len[1]) >= 1
            assert torch.isfinite(lp).all()

    def test_model_custom_n_mels_80(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        cfg = ModelConfig(arch="cnn_bigru", n_mels=80, hidden_size=32, num_layers=1)
        model = build_model(cfg, vocab_size=35)
        lp, out_len = model(torch.randn(2, 32, 80), torch.tensor([32, 24]))
        assert lp.shape[0] == 2 and lp.shape[2] == 35
        assert torch.isfinite(lp).all()

    def test_model_dropout_zero_train_vs_eval_consistency(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        model = build_model(ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0), vocab_size=30)
        x = torch.randn(1, 32, 64)
        lens = torch.tensor([32])
        model.train()
        with torch.no_grad():
            lp_tr, len_tr = model(x, lens)
        model.eval()
        with torch.no_grad():
            lp_ev, len_ev = model(x, lens)
        assert lp_tr.shape == lp_ev.shape
        assert torch.equal(len_tr, len_ev)
        assert torch.isfinite(lp_tr).all() and torch.isfinite(lp_ev).all()


# ===========================================================================
# Feature 11: Training & Checkpointing Boundaries
# ===========================================================================


class TestTier2Feature11TrainingBoundaries:
    def test_load_checkpoint_missing_path_raises_file_not_found(self, tmp_path: Path):
        from asr.train import load_checkpoint

        with pytest.raises(FileNotFoundError):
            load_checkpoint(tmp_path / "no_such_ckpt.pt")

    def test_train_asr_missing_manifest_raises_file_not_found(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import train_asr

        with pytest.raises(FileNotFoundError):
            train_asr(
                tmp_path / "missing_train.jsonl",
                tiny_fast_dataset["val"],
                audio_cfg=AudioConfig(),
                model_cfg=ModelConfig(hidden_size=32, num_layers=1),
                train_cfg=TrainConfig(epochs=1, batch_size=2, checkpoint_dir=str(tmp_path / "c")),
                tokenizer=Tokenizer("kana"),
            )

    def test_train_asr_missing_resume_path_raises_file_not_found(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import train_asr

        with pytest.raises(FileNotFoundError):
            train_asr(
                tiny_fast_dataset["train"],
                tiny_fast_dataset["val"],
                audio_cfg=AudioConfig(),
                model_cfg=ModelConfig(hidden_size=32, num_layers=1),
                train_cfg=TrainConfig(epochs=1, batch_size=2, checkpoint_dir=str(tmp_path / "c")),
                tokenizer=Tokenizer("kana"),
                resume_from=tmp_path / "missing_resume.pt",
            )

    def test_train_asr_batch_size_larger_than_dataset(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import train_asr

        cdir = tmp_path / "big_bs"
        summary = train_asr(
            tiny_fast_dataset["val"],  # only 4 utterances
            tiny_fast_dataset["val"],
            audio_cfg=AudioConfig(),
            model_cfg=ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0),
            train_cfg=TrainConfig(epochs=1, batch_size=64, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
            tokenizer=Tokenizer("kana"),
        )
        assert isinstance(summary, dict)
        assert (cdir / "best.pt").is_file()

    def test_train_asr_single_utterance_train_and_val(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import train_asr

        first_line = tiny_fast_dataset["train"].read_text(encoding="utf-8").splitlines()[0]
        one_m = tmp_path / "one.jsonl"
        one_m.write_text(first_line + "\n", encoding="utf-8")

        cdir = tmp_path / "one_ckpt"
        summary = train_asr(
            one_m,
            one_m,
            audio_cfg=AudioConfig(),
            model_cfg=ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0),
            train_cfg=TrainConfig(epochs=1, batch_size=1, seed=42, use_spec_augment=False, checkpoint_dir=str(cdir)),
            tokenizer=Tokenizer("kana"),
        )
        assert isinstance(summary, dict)
        assert (cdir / "best.pt").is_file()


# ===========================================================================
# Feature 12: CTC Decoding Boundaries
# ===========================================================================


class TestTier2Feature12DecodingBoundaries:
    def test_beam_width_one(self, helpers):
        import numpy as np
        from asr.config import DecodeConfig
        from asr.decoding import greedy_decode, prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a, t_i = tok.encode("アイ")
        lp = helpers.make_synthetic_log_probs([0, t_a, t_a, 0, t_i, 0], tok.vocab_size)
        g = greedy_decode(lp, tok)
        hyps = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=1))
        assert len(hyps) == 1
        assert hyps[0]["text"] == g["text"]
        assert np.isfinite(hyps[0]["score"])

    def test_extreme_temperatures(self, helpers):
        import numpy as np
        from asr.config import DecodeConfig
        from asr.decoding import greedy_decode, prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([0, t_a, t_a, 0], tok.vocab_size)
        for temp in (0.1, 5.0):
            g = greedy_decode(lp, tok, temperature=temp)
            b = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4, temperature=temp))
            assert np.isfinite(g["score"]) and isinstance(g["text"], str)
            assert len(b) >= 1 and np.isfinite(b[0]["score"])

    def test_extreme_blank_bias(self, helpers):
        import numpy as np
        from asr.config import DecodeConfig
        from asr.decoding import greedy_decode, prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([0, t_a, 0], tok.vocab_size, peak_logit=3.0)
        g_sup = greedy_decode(lp, tok, blank_bias=10.0)
        assert g_sup["text"] == ""
        b_enc = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4, blank_bias=-5.0))
        assert len(b_enc) >= 1 and np.isfinite(b_enc[0]["score"])

    def test_all_blank_log_probs(self, helpers):
        import numpy as np
        from asr.config import DecodeConfig
        from asr.decoding import greedy_decode, prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        lp = helpers.make_synthetic_log_probs([0] * 10, tok.vocab_size, peak_logit=10.0)
        g = greedy_decode(lp, tok)
        assert g["text"] == "" and g["token_ids"] == [] and np.isfinite(g["score"])
        b = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4))
        assert len(b) >= 1 and b[0]["text"] == "" and np.isfinite(b[0]["score"])

    def test_single_frame_log_probs(self, helpers):
        from asr.config import DecodeConfig
        from asr.decoding import greedy_decode, prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([t_a], tok.vocab_size)
        assert greedy_decode(lp, tok)["text"] == "ア"
        assert prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=3))[0]["text"] == "ア"

    def test_lm_empty_corpus_and_unseen_prefix(self):
        import numpy as np
        from asr.decoding import CharNgramLM

        for corpus in ([], [""]):
            lm = CharNgramLM(order=3, smoothing=0.1)
            lm.fit(corpus)
            assert np.isfinite(lm.score_next("", "ア"))
            assert np.isfinite(lm.score_next("XYZ", "ア"))

    def test_insertion_bonus_effect(self, helpers):
        import numpy as np
        from asr.config import DecodeConfig
        from asr.decoding import prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([0, t_a, t_a, 0], tok.vocab_size)
        h0 = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4, insertion_bonus=0.0))
        h2 = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4, insertion_bonus=2.0))
        assert np.isfinite(h0[0]["score"]) and np.isfinite(h2[0]["score"])
        assert h2[0]["score"] >= h0[0]["score"] - 1e-6


# ===========================================================================
# Feature 13: Viterbi Forced Alignment Boundaries
# ===========================================================================


class TestTier2Feature13AlignmentBoundaries:
    def test_viterbi_align_empty_token_ids(self, helpers):
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        lp = helpers.make_synthetic_log_probs([0, 0, 0], tok.vocab_size)
        assert viterbi_align(lp, [], tok, frame_stride_ms=40.0) == []

    def test_viterbi_align_single_token_single_frame(self, helpers):
        import numpy as np
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([t_a], tok.vocab_size)
        align = viterbi_align(lp, [t_a], tok, frame_stride_ms=40.0)
        assert len(align) == 1
        assert align[0]["token"] == "ア"
        assert 0.0 <= align[0]["start_sec"] <= align[0]["end_sec"] <= 0.04 + 1e-6
        assert np.isfinite(align[0]["confidence"])

    def test_viterbi_align_uniform_log_probs(self):
        import numpy as np
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        ids = tok.encode("アイウ")
        lp = np.full((12, tok.vocab_size), -math.log(tok.vocab_size), dtype=np.float32)
        align = viterbi_align(lp, ids, tok, frame_stride_ms=40.0)
        assert len(align) == 3
        for i, item in enumerate(align):
            assert np.isfinite(item["start_sec"]) and np.isfinite(item["end_sec"]) and np.isfinite(item["confidence"])
            if i > 0:
                assert align[i - 1]["start_sec"] <= item["start_sec"] + 1e-6

    def test_viterbi_align_tokens_exceed_frames(self, helpers):
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        ids = tok.encode("アイウアイ")
        lp = helpers.make_synthetic_log_probs([0, 0], tok.vocab_size)
        try:
            res = viterbi_align(lp, ids, tok, frame_stride_ms=40.0)
            assert isinstance(res, list)
        except ValueError:
            pass

    def test_viterbi_align_empty_log_probs(self):
        import numpy as np
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = np.empty((0, tok.vocab_size), dtype=np.float32)
        try:
            res = viterbi_align(lp, [t_a], tok, frame_stride_ms=40.0)
            assert res == []
        except ValueError:
            pass


# ===========================================================================
# Feature 14: ASR Evaluation Metrics Boundaries
# ===========================================================================


class TestTier2Feature14MetricsBoundaries:
    def test_metrics_empty_lists(self):
        from asr.metrics import compute_cer, compute_mer, compute_wer

        cer = compute_cer([], [])
        assert cer["cer"] == pytest.approx(0.0) and cer["ref_len"] == 0
        assert compute_mer([], [])["mer"] == pytest.approx(0.0)
        assert compute_wer([], [])["wer"] == pytest.approx(0.0)

    def test_metrics_empty_ref_and_empty_hyp_strings(self):
        import numpy as np
        from asr.metrics import compute_cer

        assert compute_cer([""], [""])["cer"] == pytest.approx(0.0)
        d = compute_cer(["アイウ"], [""])
        assert d["deletions"] == 3 and d["cer"] == pytest.approx(1.0)
        ins = compute_cer([""], ["アイ"])
        assert ins["insertions"] == 2 and np.isfinite(ins["cer"]) and ins["cer"] >= 0.0

    def test_metrics_mismatched_lengths_raises(self):
        from asr.metrics import compute_cer, compute_mer, compute_wer

        with pytest.raises(ValueError):
            compute_cer(["ア"], ["ア", "イ"])
        with pytest.raises(ValueError):
            compute_mer(["ア"], ["ア", "イ"])
        with pytest.raises(ValueError):
            compute_wer(["a"], ["a", "b"])

    def test_confusion_pairs_no_substitutions_and_top_k_zero(self):
        from asr.metrics import confusion_pairs

        assert confusion_pairs(["アイウ"], ["アイウ"]) == []
        assert confusion_pairs(["アイウ"], ["ア"]) == []
        assert confusion_pairs(["カ"], ["ガ"], top_k=0) == []
        assert confusion_pairs([], []) == []

    def test_alignment_boundary_error_empty_inputs(self):
        import numpy as np
        from asr.metrics import alignment_boundary_error

        gt = [{"t": "ア", "a": 0.0, "e": 0.2}]
        pred = [{"token": "ア", "start_sec": 0.0, "end_sec": 0.2, "confidence": 0.9}]
        for a, b in (([], []), (gt, []), ([], pred)):
            res = alignment_boundary_error(a, b)
            assert isinstance(res, dict)
            for v in res.values():
                if isinstance(v, (int, float)):
                    assert np.isfinite(v)

    def test_compute_cer_exceeds_one_on_heavy_insertions(self):
        from asr.metrics import compute_cer

        res = compute_cer(["ア"], ["アイウエオ"])
        assert res["insertions"] == 4
        assert res["ref_len"] == 1
        assert res["cer"] == pytest.approx(4.0)


# ===========================================================================
# Feature 15: High-Level Inference Engine Boundaries
# ===========================================================================


class TestTier2Feature15EngineBoundaries:
    def test_from_checkpoint_missing_file_raises(self, tmp_path: Path):
        from asr.inference import ASREngine

        with pytest.raises((FileNotFoundError, OSError)):
            ASREngine.from_checkpoint(tmp_path / "does_not_exist.pt")

    def test_redecode_unknown_utterance_id_raises(self, tiny_engine):
        from asr.config import DecodeConfig

        with pytest.raises((KeyError, ValueError)):
            tiny_engine.redecode("unknown-utt-id-99999", DecodeConfig())

    def test_transcribe_pure_silence(self, tiny_engine, helpers):
        import numpy as np

        res = tiny_engine.transcribe(helpers.make_silence(1.0, 16000), sr=16000)
        assert float(res["duration_sec"]) == pytest.approx(1.0, abs=0.05)
        assert np.isfinite(res["rtf"]) and isinstance(res["text"], str)

    def test_transcribe_empty_audio(self, tiny_engine):
        import numpy as np

        empty = np.array([], dtype=np.float32)
        try:
            res = tiny_engine.transcribe(empty, sr=16000)
            assert res["text"] == ""
            assert float(res["duration_sec"]) == pytest.approx(0.0, abs=1e-4)
        except ValueError:
            pass

    def test_redecode_extreme_decode_params(self, tiny_engine, helpers):
        from asr.config import DecodeConfig

        res = tiny_engine.transcribe(helpers.make_speech_like(0.5, 16000), sr=16000)
        utt_id = res["utterance_id"]
        for cfg in (
            DecodeConfig(method="beam", beam_width=1, temperature=0.1, blank_bias=-5.0),
            DecodeConfig(method="beam", beam_width=1, temperature=5.0, blank_bias=5.0),
        ):
            r = tiny_engine.redecode(utt_id, cfg)
            assert isinstance(r["text"], str) and isinstance(r["hypotheses"], list)


# ===========================================================================
# Feature 16: Full CLI Boundaries
# ===========================================================================


class TestTier2Feature16CLIBoundaries:
    def test_cli_unknown_subcommand(self, run_cli):
        proc = run_cli(["totally_unknown_cmd"], timeout=30)
        assert proc.returncode != 0
        assert len(proc.stderr.strip()) > 0
        assert "Traceback" not in proc.stderr

    def test_cli_generate_missing_out_dir(self, run_cli):
        proc = run_cli(["generate"], timeout=30)
        assert proc.returncode != 0
        assert len(proc.stderr.strip()) > 0
        assert "Traceback" not in proc.stderr

    def test_cli_transcribe_missing_checkpoint(self, run_cli, tmp_path: Path):
        proc = run_cli(["transcribe", "--checkpoint", str(tmp_path / "missing.pt"), "--tts", "アイ"], timeout=30)
        assert proc.returncode != 0
        assert len(proc.stderr.strip()) > 0

    def test_cli_transcribe_missing_wav(self, run_cli, tmp_path: Path, tiny_checkpoint: dict):
        proc = run_cli(
            ["transcribe", "--checkpoint", str(tiny_checkpoint["best_pt"]), "--wav", str(tmp_path / "missing.wav")],
            timeout=30,
        )
        assert proc.returncode != 0
        assert len(proc.stderr.strip()) > 0

    def test_cli_train_invalid_arch(self, run_cli, tiny_fast_dataset: dict[str, Path]):
        proc = run_cli(
            [
                "train",
                "--train-manifest", str(tiny_fast_dataset["train"]),
                "--val-manifest", str(tiny_fast_dataset["val"]),
                "--arch", "bogus_arch_xyz",
            ],
            timeout=30,
        )
        assert proc.returncode != 0
        assert len(proc.stderr.strip()) > 0
        assert "Traceback" not in proc.stderr

    def test_cli_transcribe_missing_input_source(self, run_cli, tiny_checkpoint: dict):
        proc = run_cli(["transcribe", "--checkpoint", str(tiny_checkpoint["best_pt"])], timeout=30)
        assert proc.returncode != 0
        assert len(proc.stderr.strip()) > 0


# ===========================================================================
# Feature 17: FastAPI Backend Boundaries
# ===========================================================================


class TestTier2Feature17APIBoundaries:
    def test_api_redecode_unknown_utterance_404(self, api_client):
        resp = api_client.post(
            "/api/redecode",
            json={"utterance_id": "nonexistent-id-000", "decode_cfg": {"method": "greedy"}},
        )
        assert resp.status_code == 404

    def test_api_transcribe_corrupt_wav_400_or_422(self, api_client):
        resp = api_client.post(
            "/api/transcribe",
            files={"file": ("bad.wav", b"NOT_A_WAV_FILE_12345", "audio/wav")},
        )
        assert resp.status_code in (400, 422)

    def test_api_transcribe_empty_file_400_or_422(self, api_client):
        resp = api_client.post(
            "/api/transcribe",
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        assert resp.status_code in (400, 422)

    def test_api_tts_roundtrip_missing_text_422_or_400(self, api_client):
        resp = api_client.post("/api/tts-roundtrip", json={})
        assert resp.status_code in (400, 422)

    def test_api_redecode_malformed_payload_422(self, api_client):
        resp = api_client.post("/api/redecode", json={})
        assert resp.status_code in (400, 422)

    def test_api_health_without_model_loaded(self, api_client_no_model, helpers):
        h = api_client_no_model.get("/api/health")
        assert h.status_code == 200
        assert h.json() == {"status": "ok", "model_loaded": False}

        wav_bytes = helpers.wav_to_bytes(helpers.make_silence(0.2, 16000), sr=16000)
        tr = api_client_no_model.post("/api/transcribe", files={"file": ("s.wav", wav_bytes, "audio/wav")})
        assert tr.status_code in (400, 503)


# ===========================================================================
# Feature 18: Web Playground Boundaries
# ===========================================================================


class _TagCounter(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.open_counts: dict[str, int] = {}
        self.close_counts: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs) -> None:
        t = tag.lower()
        self.open_counts[t] = self.open_counts.get(t, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        self.close_counts[t] = self.close_counts.get(t, 0) + 1


class TestTier2Feature18WebBoundaries:
    def test_web_html_well_formed_script_and_style_tags(self, api_client):
        body = api_client.get("/").text
        counter = _TagCounter()
        counter.feed(body)
        assert counter.open_counts.get("script", 0) == counter.close_counts.get("script", 0)
        assert counter.open_counts.get("style", 0) == counter.close_counts.get("style", 0)

    def test_web_no_common_cdn_hosts(self, api_client):
        body = api_client.get("/").text.lower()
        for host in (
            "cdn.jsdelivr.net",
            "unpkg.com",
            "cdnjs.cloudflare.com",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
        ):
            assert host not in body, f"Disallowed CDN host found: {host}"

    def test_web_utf8_charset_declared(self, api_client):
        resp = api_client.get("/")
        raw = resp.content.decode("utf-8")
        assert "utf-8" in raw.lower()

    def test_web_unknown_route_returns_404(self, api_client):
        resp = api_client.get("/nonexistent-route-xyz")
        assert resp.status_code == 404

    def test_web_disallowed_method_on_root_returns_405(self, api_client):
        resp = api_client.delete("/")
        assert resp.status_code == 405
