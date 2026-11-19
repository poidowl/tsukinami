"""Tier 1 E2E Tests: Isolated Feature Coverage across all 18 Tsukinami ASR features.

Every feature area (#1-#18 in PROJECT.md § Feature Inventory) has >= 5 isolated
happy-path tests adhering to progressive testability (earlier features do not
depend on later features) and strict opaque-box contract verification.
"""

from __future__ import annotations

import base64
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest


# ===========================================================================
# Feature 1: Project Environment, Packaging & Config (asr/config.py)
# ===========================================================================


class TestTier1Feature01ConfigEnv:
    def test_packaging_files_and_asr_import(self, repo_root: Path):
        import asr

        pyproject = repo_root / "pyproject.toml"
        gitignore = repo_root / ".gitignore"
        assert pyproject.is_file(), "pyproject.toml must exist at repo root"
        assert gitignore.is_file(), ".gitignore must exist at repo root"
        gitignore_text = gitignore.read_text(encoding="utf-8")
        assert ".venv" in gitignore_text
        assert asr is not None

    def test_audio_config_defaults_and_roundtrip(self):
        from asr.config import AudioConfig

        cfg = AudioConfig()
        assert cfg.sample_rate == 16000
        assert cfg.n_fft == 512
        assert cfg.win_length == 400
        assert cfg.hop_length == 160
        assert cfg.n_mels == 64
        assert cfg.f_min == pytest.approx(80.0)
        assert cfg.f_max == pytest.approx(7600.0)
        assert cfg.preemphasis == pytest.approx(0.97)
        assert cfg.cmvn is True

        raw = cfg.to_dict()
        assert isinstance(raw, dict)
        json_str = json.dumps(raw)
        restored = AudioConfig.from_dict(json.loads(json_str))
        assert restored == cfg

    def test_model_config_defaults_and_roundtrip(self):
        from asr.config import ModelConfig

        cfg = ModelConfig()
        assert cfg.arch == "cnn_bigru"
        assert cfg.n_mels == 64
        assert cfg.hidden_size == 192
        assert cfg.num_layers == 2
        assert cfg.dropout == pytest.approx(0.1)
        assert cfg.num_heads == 4
        assert cfg.conv_kernel_size == 15
        assert ModelConfig.from_dict(cfg.to_dict()) == cfg

        conf = ModelConfig(arch="conformer_lite", hidden_size=128, num_layers=3)
        assert ModelConfig.from_dict(conf.to_dict()) == conf

    def test_train_config_defaults_and_roundtrip(self):
        from asr.config import TrainConfig

        cfg = TrainConfig()
        assert cfg.epochs == 20
        assert cfg.batch_size == 16
        assert cfg.lr == pytest.approx(3e-3)
        assert cfg.weight_decay == pytest.approx(1e-4)
        assert cfg.grad_clip == pytest.approx(5.0)
        assert cfg.seed == 42
        assert cfg.use_spec_augment is True
        assert cfg.checkpoint_dir == "checkpoints"
        assert TrainConfig.from_dict(cfg.to_dict()) == cfg

    def test_decode_config_defaults_and_roundtrip(self):
        from asr.config import DecodeConfig

        cfg = DecodeConfig()
        assert cfg.method == "beam"
        assert cfg.beam_width == 8
        assert cfg.temperature == pytest.approx(1.0)
        assert cfg.blank_bias == pytest.approx(0.0)
        assert cfg.lm_weight == pytest.approx(0.0)
        assert cfg.insertion_bonus == pytest.approx(0.0)
        assert DecodeConfig.from_dict(cfg.to_dict()) == cfg

        greedy = DecodeConfig(method="greedy", beam_width=1, blank_bias=-0.5)
        assert DecodeConfig.from_dict(greedy.to_dict()) == greedy

    def test_custom_config_override_serialization(self):
        from asr.config import AudioConfig, DecodeConfig, ModelConfig, TrainConfig

        a = AudioConfig(sample_rate=8000, n_fft=256, win_length=200, hop_length=80, n_mels=40, f_min=50.0, f_max=3800.0, preemphasis=0.95, cmvn=False)
        m = ModelConfig(arch="conformer_lite", n_mels=40, hidden_size=64, num_layers=1, dropout=0.2, num_heads=2, conv_kernel_size=7)
        t = TrainConfig(epochs=5, batch_size=8, lr=1e-3, weight_decay=1e-5, grad_clip=1.0, seed=7, use_spec_augment=False, checkpoint_dir="tmp_ckpt")
        d = DecodeConfig(method="beam", beam_width=4, temperature=1.2, blank_bias=0.3, lm_weight=0.4, insertion_bonus=0.1)

        blob = json.loads(json.dumps({"a": a.to_dict(), "m": m.to_dict(), "t": t.to_dict(), "d": d.to_dict()}))
        assert AudioConfig.from_dict(blob["a"]) == a
        assert ModelConfig.from_dict(blob["m"]) == m
        assert TrainConfig.from_dict(blob["t"]) == t
        assert DecodeConfig.from_dict(blob["d"]) == d


# ===========================================================================
# Feature 2: WAV/PCM I/O & Resampling (asr/audio.py)
# ===========================================================================


class TestTier1Feature02AudioIO:
    def test_save_and_load_wav_16k_mono_roundtrip(self, tmp_path: Path, helpers):
        import numpy as np
        from asr.audio import load_wav, save_wav

        wav = helpers.make_sine(freq=440.0, duration=0.5, sr=16000, amp=0.5)
        out_path = tmp_path / "roundtrip.wav"
        save_wav(out_path, wav, sr=16000)
        assert out_path.is_file()

        loaded, sr = load_wav(out_path, target_sr=16000)
        assert sr == 16000
        assert loaded.ndim == 1
        assert loaded.dtype == np.float32
        assert len(loaded) == len(wav)
        assert float(np.min(loaded)) >= -1.0 and float(np.max(loaded)) <= 1.0
        assert float(np.mean(np.abs(loaded - wav))) < 1e-3

    def test_load_wav_independent_16bit_pcm_file(self, tmp_path: Path, helpers):
        import numpy as np
        from asr.audio import load_wav

        wav = helpers.make_sine(freq=300.0, duration=0.4, sr=16000, amp=0.6)
        wav_path = helpers.write_pcm_wav(tmp_path / "indep16.wav", wav, sr=16000, channels=1, sampwidth=2)
        loaded, sr = load_wav(wav_path, target_sr=16000)
        assert sr == 16000
        assert loaded.ndim == 1
        assert loaded.dtype == np.float32
        assert len(loaded) == len(wav)
        assert float(np.max(np.abs(loaded))) <= 1.0

    def test_load_wav_resamples_from_44100_to_16000(self, tmp_path: Path, helpers):
        import numpy as np
        from asr.audio import load_wav

        wav_44k = helpers.make_sine(freq=440.0, duration=1.0, sr=44100, amp=0.5)
        wav_path = helpers.write_pcm_wav(tmp_path / "sr44k.wav", wav_44k, sr=44100, channels=1, sampwidth=2)
        loaded, sr = load_wav(wav_path, target_sr=16000)
        assert sr == 16000
        assert loaded.ndim == 1
        assert loaded.dtype == np.float32
        assert abs(len(loaded) - 16000) <= 320
        assert np.isfinite(loaded).all()

    def test_load_wav_stereo_mixdown_to_mono(self, tmp_path: Path, helpers):
        import numpy as np
        from asr.audio import load_wav

        wav = helpers.make_sine(freq=520.0, duration=0.5, sr=16000, amp=0.5)
        wav_path = helpers.write_pcm_wav(tmp_path / "stereo.wav", wav, sr=16000, channels=2, sampwidth=2)
        loaded, sr = load_wav(wav_path, target_sr=16000)
        assert sr == 16000
        assert loaded.ndim == 1
        assert loaded.dtype == np.float32
        assert np.isfinite(loaded).all()
        assert float(np.sqrt(np.mean(loaded ** 2))) > 0.05

    def test_resample_downsample_and_upsample(self, helpers):
        import numpy as np
        from asr.audio import resample

        wav_44k = helpers.make_sine(freq=440.0, duration=1.0, sr=44100, amp=0.5)
        down = resample(wav_44k, 44100, 16000)
        assert down.ndim == 1 and down.dtype == np.float32
        assert abs(len(down) / 16000.0 - 1.0) < 0.02

        wav_8k = helpers.make_sine(freq=440.0, duration=1.0, sr=8000, amp=0.5)
        up = resample(wav_8k, 8000, 16000)
        assert up.ndim == 1 and up.dtype == np.float32
        assert abs(len(up) / 16000.0 - 1.0) < 0.02


# ===========================================================================
# Feature 3: Pure-NumPy STFT, Log-Mel & MFCC (asr/features.py)
# ===========================================================================


class TestTier1Feature03Features:
    def test_extract_log_mel_default_shape_and_dtype(self, helpers):
        import numpy as np
        from asr.features import extract_log_mel

        wav = helpers.make_speech_like(duration=1.0, sr=16000)
        mel = extract_log_mel(wav)
        assert mel.ndim == 2
        assert mel.dtype == np.float32
        assert mel.shape[1] == 64
        assert 90 <= mel.shape[0] <= 105
        assert np.isfinite(mel).all()

    def test_extract_log_mel_custom_80_mels(self, helpers):
        import numpy as np
        from asr.config import AudioConfig
        from asr.features import extract_log_mel

        wav = helpers.make_speech_like(duration=1.0, sr=16000)
        mel = extract_log_mel(wav, AudioConfig(n_mels=80))
        assert mel.ndim == 2
        assert mel.dtype == np.float32
        assert mel.shape[1] == 80
        assert np.isfinite(mel).all()

    def test_extract_log_mel_cmvn_normalizes_mean_and_std(self, helpers):
        import numpy as np
        from asr.config import AudioConfig
        from asr.features import extract_log_mel

        wav = helpers.make_speech_like(duration=1.2, sr=16000)
        mel_norm = extract_log_mel(wav, AudioConfig(cmvn=True))
        mel_raw = extract_log_mel(wav, AudioConfig(cmvn=False))
        assert mel_norm.shape == mel_raw.shape
        assert abs(float(np.mean(mel_norm))) < 0.15
        assert 0.5 < float(np.std(mel_norm)) < 1.5

    def test_extract_mfcc_basic_13_coeffs(self, helpers):
        import numpy as np
        from asr.config import AudioConfig
        from asr.features import extract_log_mel, extract_mfcc

        wav = helpers.make_speech_like(duration=1.0, sr=16000)
        cfg = AudioConfig()
        mel = extract_log_mel(wav, cfg)
        mfcc = extract_mfcc(wav, cfg, n_mfcc=13, include_deltas=False)
        assert mfcc.dtype == np.float32
        assert mfcc.shape == (mel.shape[0], 13)
        assert np.isfinite(mfcc).all()

    def test_extract_mfcc_with_deltas_39_coeffs(self, helpers):
        import numpy as np
        from asr.config import AudioConfig
        from asr.features import extract_mfcc

        wav = helpers.make_speech_like(duration=1.0, sr=16000)
        cfg = AudioConfig()
        mfcc_static = extract_mfcc(wav, cfg, n_mfcc=13, include_deltas=False)
        mfcc_delta = extract_mfcc(wav, cfg, n_mfcc=13, include_deltas=True)
        assert mfcc_delta.dtype == np.float32
        assert mfcc_delta.shape == (mfcc_static.shape[0], 39)
        assert np.isfinite(mfcc_delta).all()
        assert np.allclose(mfcc_delta[:, :13], mfcc_static, atol=1e-4)


# ===========================================================================
# Feature 4: Energy VAD & Silence Trimming (asr/audio.py)
# ===========================================================================


class TestTier1Feature04VAD:
    def test_detect_vad_finds_single_speech_segment(self, helpers):
        import numpy as np
        from asr.audio import detect_vad

        wav = np.concatenate([
            helpers.make_silence(0.4, 16000),
            helpers.make_sine(300.0, 0.6, 16000, amp=0.5),
            helpers.make_silence(0.4, 16000),
        ])
        segs = detect_vad(wav, sr=16000)
        assert isinstance(segs, list) and len(segs) >= 1
        for start, end in segs:
            assert 0.0 <= start < end <= 1.45
        # Detected speech must overlap active [0.4, 1.0]
        assert any(s < 1.0 and e > 0.4 for s, e in segs)

    def test_detect_vad_finds_multiple_separated_segments(self, helpers):
        import numpy as np
        from asr.audio import detect_vad

        wav = np.concatenate([
            helpers.make_silence(0.3, 16000),
            helpers.make_sine(350.0, 0.4, 16000, amp=0.5),
            helpers.make_silence(0.5, 16000),
            helpers.make_sine(450.0, 0.4, 16000, amp=0.5),
            helpers.make_silence(0.3, 16000),
        ])
        segs = detect_vad(wav, sr=16000, hangover_ms=100.0)
        assert len(segs) == 2
        assert segs[0][0] < segs[0][1] < segs[1][0] < segs[1][1]

    def test_detect_vad_hangover_extends_segment_tail(self, helpers):
        import numpy as np
        from asr.audio import detect_vad

        wav = np.concatenate([
            helpers.make_silence(0.3, 16000),
            helpers.make_sine(400.0, 0.4, 16000, amp=0.5),
            helpers.make_silence(0.5, 16000),
        ])
        short_ho = detect_vad(wav, sr=16000, hangover_ms=20.0)
        long_ho = detect_vad(wav, sr=16000, hangover_ms=200.0)
        assert len(short_ho) >= 1 and len(long_ho) >= 1
        assert long_ho[-1][1] >= short_ho[-1][1]

    def test_detect_vad_threshold_db_sensitivity(self, helpers):
        from asr.audio import detect_vad

        # ~ -30 dB sine wave (amplitude ~ 0.03)
        quiet = helpers.make_sine(440.0, 0.6, 16000, amp=0.03)
        lenient = detect_vad(quiet, sr=16000, threshold_db=-45.0)
        strict = detect_vad(quiet, sr=16000, threshold_db=-10.0)
        assert len(lenient) >= 1
        assert len(strict) == 0

    def test_detect_vad_custom_frame_ms(self, helpers):
        from asr.audio import detect_vad

        wav = helpers.make_speech_like(duration=1.0, sr=16000, pad_sec=0.2)
        for frame_ms in (10.0, 30.0):
            segs = detect_vad(wav, sr=16000, frame_ms=frame_ms)
            assert isinstance(segs, list) and len(segs) >= 1
            for s, e in segs:
                assert 0.0 <= s < e <= 1.05


# ===========================================================================
# Feature 5: SpecAugment & Waveform Corruptions (asr/features.py, asr/audio.py)
# ===========================================================================


class TestTier1Feature05Augment:
    def test_spec_augment_preserves_shape_and_masks_values(self, helpers):
        import numpy as np
        from asr.features import extract_log_mel, spec_augment

        wav = helpers.make_speech_like(duration=1.2, sr=16000)
        mel = extract_log_mel(wav)
        mel_copy = mel.copy()
        aug = spec_augment(mel, freq_mask_param=8, time_mask_param=15, num_freq_masks=2, num_time_masks=2, seed=42)
        assert aug.shape == mel.shape
        assert aug.dtype == np.float32
        assert np.isfinite(aug).all()
        assert np.array_equal(mel, mel_copy), "spec_augment must not mutate input in-place"
        assert not np.array_equal(aug, mel)

    def test_spec_augment_reproducible_with_seed(self, helpers):
        import numpy as np
        from asr.features import extract_log_mel, spec_augment

        mel = extract_log_mel(helpers.make_speech_like(duration=1.0, sr=16000))
        a = spec_augment(mel, freq_mask_param=8, time_mask_param=15, num_freq_masks=2, num_time_masks=2, seed=123)
        b = spec_augment(mel, freq_mask_param=8, time_mask_param=15, num_freq_masks=2, num_time_masks=2, seed=123)
        assert np.array_equal(a, b)

    def test_apply_corruption_white_noise_snr(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        wav = helpers.make_sine(440.0, duration=1.0, sr=16000, amp=0.5)
        noisy = apply_corruption(wav, 16000, snr_db=10.0, noise_type="white", seed=7)
        assert noisy.shape == wav.shape
        assert noisy.dtype == np.float32
        assert np.isfinite(noisy).all()
        noise = noisy - wav
        sig_pow = float(np.mean(wav ** 2))
        noise_pow = float(np.mean(noise ** 2))
        assert noise_pow > 0.0
        est_snr = 10.0 * np.log10(sig_pow / noise_pow)
        assert 5.0 < est_snr < 15.0

    def test_apply_corruption_pink_noise(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        wav = helpers.make_sine(440.0, duration=1.0, sr=16000, amp=0.5)
        noisy = apply_corruption(wav, 16000, snr_db=10.0, noise_type="pink", seed=7)
        assert noisy.shape == wav.shape
        assert noisy.dtype == np.float32
        assert np.isfinite(noisy).all()
        assert float(np.mean(np.abs(noisy - wav))) > 1e-3

    def test_apply_corruption_band_limit_telephone(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        sr = 16000
        sig = (
            helpers.make_sine(100.0, 1.0, sr, amp=0.3)
            + helpers.make_sine(1000.0, 1.0, sr, amp=0.3)
            + helpers.make_sine(6000.0, 1.0, sr, amp=0.3)
        ).astype(np.float32)
        filtered = apply_corruption(sig, sr, band_limit=(300.0, 3400.0))
        assert filtered.dtype == np.float32
        assert np.isfinite(filtered).all()

        freqs = np.fft.rfftfreq(len(filtered), d=1.0 / sr)
        spec = np.abs(np.fft.rfft(filtered))
        e_100 = float(spec[np.argmin(np.abs(freqs - 100.0))])
        e_1000 = float(spec[np.argmin(np.abs(freqs - 1000.0))])
        e_6000 = float(spec[np.argmin(np.abs(freqs - 6000.0))])
        assert e_1000 > e_100 * 2.0
        assert e_1000 > e_6000 * 2.0

    def test_apply_corruption_speed_and_gain_db(self, helpers):
        import numpy as np
        from asr.audio import apply_corruption

        wav = helpers.make_sine(440.0, duration=1.0, sr=16000, amp=0.25)
        fast = apply_corruption(wav, 16000, speed=1.25)
        slow = apply_corruption(wav, 16000, speed=0.8)
        assert len(fast) < len(wav) < len(slow)

        louder = apply_corruption(wav, 16000, gain_db=6.0)
        quieter = apply_corruption(wav, 16000, gain_db=-6.0)
        rms_orig = float(np.sqrt(np.mean(wav ** 2)))
        rms_loud = float(np.sqrt(np.mean(louder ** 2)))
        rms_quiet = float(np.sqrt(np.mean(quieter ** 2)))
        assert rms_loud > rms_orig * 1.5
        assert rms_quiet < rms_orig * 0.7


# ===========================================================================
# Feature 6: CTC Tokenizer (asr/tokenizer.py)
# ===========================================================================


class TestTier1Feature06Tokenizer:
    def test_kana_mode_blank_id_and_roundtrip(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        assert tok.blank_id == 0
        assert tok.vocab_size > 40
        ids = tok.encode("ワタシ、ニホンゴ")
        assert len(ids) > 0
        assert all(0 < idx < tok.vocab_size for idx in ids)
        assert tok.decode(ids, collapse_ctc=False) == "ワタシ、ニホンゴ"

    def test_kana_mode_hiragana_normalizes_to_katakana(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        assert tok.encode("わたし、にほんご") == tok.encode("ワタシ、ニホンゴ")

    def test_decode_collapse_ctc_semantics(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        a = tok.encode("ア")[0]
        b = tok.encode("イ")[0]
        assert a != b and a != 0 and b != 0
        seq = [0, a, a, 0, a, b, b, 0]
        assert tok.decode(seq, collapse_ctc=True) == tok.decode([a, a, b], collapse_ctc=False)

    def test_phoneme_and_ascii_modes(self):
        from asr.tokenizer import Tokenizer

        tok_ph = Tokenizer(mode="phoneme")
        assert tok_ph.blank_id == 0 and tok_ph.vocab_size > 10
        ph_ids = tok_ph.encode("こんにちは")
        assert len(ph_ids) > 0
        assert len(tok_ph.decode(ph_ids)) > 0

        tok_asc = Tokenizer(mode="ascii")
        assert tok_asc.blank_id == 0 and tok_asc.vocab_size > 20
        asc_ids = tok_asc.encode("hello world")
        assert len(asc_ids) > 0
        assert "hello" in tok_asc.decode(asc_ids).lower()

    def test_tokenizer_to_dict_from_dict_roundtrip(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana")
        d = json.loads(json.dumps(tok.to_dict()))
        tok2 = Tokenizer.from_dict(d)
        assert tok2.vocab_size == tok.vocab_size
        assert tok2.blank_id == tok.blank_id == 0
        assert tok2.encode("おはよう") == tok.encode("おはよう")
        assert tok2.decode(tok2.encode("おはよう")) == tok.decode(tok.encode("おはよう"))

    def test_custom_vocab_override(self):
        from asr.tokenizer import Tokenizer

        tok = Tokenizer(mode="kana", vocab=["ア", "イ", "ウ"])
        assert tok.blank_id == 0
        ids = tok.encode("アイウ")
        assert len(ids) == 3
        assert all(idx != 0 for idx in ids)
        assert tok.decode(ids) == "アイウ"


# ===========================================================================
# Feature 7: Tier 1 Fast kotoba Formant-Track Synth (asr/synth_data.py)
# ===========================================================================


class TestTier1Feature07FastSynth:
    def test_synthesize_fast_kotoba_basic_output(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        wav, moras = synthesize_fast_kotoba("おはよう", sr=16000, seed=42)
        assert wav.ndim == 1
        assert wav.dtype == np.float32
        assert len(wav) > 0
        assert np.isfinite(wav).all()
        assert float(np.sqrt(np.mean(wav ** 2))) > 1e-3
        assert isinstance(moras, list) and len(moras) >= 3

    def test_synthesize_fast_kotoba_mora_timestamps_schema(self):
        from asr.synth_data import synthesize_fast_kotoba

        wav, moras = synthesize_fast_kotoba("ワタシ、ニホンゴ", sr=16000, seed=42)
        dur = len(wav) / 16000.0
        prev_a = -1e-6
        for m in moras:
            assert {"t", "a", "e"} <= set(m.keys())
            assert 0.0 <= float(m["a"]) <= float(m["e"]) + 1e-6
            assert float(m["a"]) >= prev_a - 1e-6
            prev_a = float(m["a"])
        assert float(moras[-1]["e"]) <= dur + 0.25

    def test_synthesize_fast_kotoba_rate_changes_duration(self):
        from asr.synth_data import synthesize_fast_kotoba

        w_slow, _ = synthesize_fast_kotoba("こんにちは", sr=16000, rate=0.75, seed=1)
        w_fast, _ = synthesize_fast_kotoba("こんにちは", sr=16000, rate=1.4, seed=1)
        assert len(w_slow) > 0 and len(w_fast) > 0
        assert abs(len(w_slow) - len(w_fast)) > 500

    def test_synthesize_fast_kotoba_speaker_variation_and_seed(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        w1, _ = synthesize_fast_kotoba("あいう", sr=16000, f0_scale=0.8, fscale=0.9, seed=7)
        w2, _ = synthesize_fast_kotoba("あいう", sr=16000, f0_scale=1.3, fscale=1.2, seed=7)
        w1_rep, _ = synthesize_fast_kotoba("あいう", sr=16000, f0_scale=0.8, fscale=0.9, seed=7)
        assert np.array_equal(w1, w1_rep)
        min_len = min(len(w1), len(w2))
        assert float(np.mean(np.abs(w1[:min_len] - w2[:min_len]))) > 1e-3

    def test_synthesize_fast_kotoba_with_snr_noise(self):
        import numpy as np
        from asr.synth_data import synthesize_fast_kotoba

        clean, _ = synthesize_fast_kotoba("テスト", sr=16000, snr_db=None, seed=1)
        noisy, _ = synthesize_fast_kotoba("テスト", sr=16000, snr_db=15.0, seed=1)
        assert noisy.shape == clean.shape
        assert noisy.dtype == np.float32
        assert np.isfinite(noisy).all()
        assert float(np.mean(np.abs(noisy - clean))) > 1e-4


# ===========================================================================
# Feature 8: Tier 2 Authentic tsukinami TTS (asr/synth_data.py)
# ===========================================================================


class TestTier1Feature08TsukinamiTTS:
    def test_synthesize_tsukinami_default_preset(self, tsukinami_cache_dir: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        wav, moras = synthesize_tsukinami("あい", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)
        assert wav.ndim == 1
        assert wav.dtype == np.float32
        assert len(wav) > 1000
        assert np.isfinite(wav).all()
        assert float(np.sqrt(np.mean(wav ** 2))) > 1e-3
        assert isinstance(moras, list) and len(moras) >= 1
        assert all({"t", "a", "e"} <= set(m.keys()) for m in moras)

    def test_synthesize_tsukinami_alternate_presets(self, tsukinami_cache_dir: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        w_ossan, _ = synthesize_tsukinami("あい", preset="ossan", sr=16000, cache_dir=tsukinami_cache_dir)
        w_robot, _ = synthesize_tsukinami("あい", preset="robot", sr=16000, cache_dir=tsukinami_cache_dir)
        assert w_ossan.dtype == np.float32 and w_robot.dtype == np.float32
        assert np.isfinite(w_ossan).all() and np.isfinite(w_robot).all()
        n = min(len(w_ossan), len(w_robot))
        assert float(np.mean(np.abs(w_ossan[:n] - w_robot[:n]))) > 1e-3

    def test_synthesize_tsukinami_overrides_applied(self, tsukinami_cache_dir: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        w_base, _ = synthesize_tsukinami("あい", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)
        w_mod, _ = synthesize_tsukinami(
            "あい",
            preset="default",
            sr=16000,
            overrides={"hz": 160.0, "fscale": 0.9},
            cache_dir=tsukinami_cache_dir,
        )
        assert w_mod.dtype == np.float32 and np.isfinite(w_mod).all()
        n = min(len(w_base), len(w_mod))
        assert float(np.mean(np.abs(w_base[:n] - w_mod[:n]))) > 1e-3

    def test_synthesize_tsukinami_disk_cache_hit(self, tmp_path: Path):
        import numpy as np
        from asr.synth_data import synthesize_tsukinami

        cache_dir = tmp_path / "cache"
        t0 = time.perf_counter()
        w1, m1 = synthesize_tsukinami("あ", preset="default", sr=16000, cache_dir=cache_dir)
        dt1 = time.perf_counter() - t0

        assert any(cache_dir.rglob("*")), "cache_dir must contain cached artifact files"

        t1 = time.perf_counter()
        w2, m2 = synthesize_tsukinami("あ", preset="default", sr=16000, cache_dir=cache_dir)
        dt2 = time.perf_counter() - t1

        assert np.allclose(w1, w2, atol=1e-4)
        assert len(m1) == len(m2)
        assert dt2 < dt1

    def test_synthesize_tsukinami_custom_sr_resampling(self, tsukinami_cache_dir: Path):
        from asr.synth_data import synthesize_tsukinami

        w16, _ = synthesize_tsukinami("あい", preset="default", sr=16000, cache_dir=tsukinami_cache_dir)
        w8, _ = synthesize_tsukinami("あい", preset="default", sr=8000, cache_dir=tsukinami_cache_dir)
        dur16 = len(w16) / 16000.0
        dur8 = len(w8) / 8000.0
        assert abs(dur16 - dur8) / max(dur16, 1e-6) < 0.05


# ===========================================================================
# Feature 9: Tier 3 Unified Manifest & Corpus DataLoader (asr/dataset.py)
# ===========================================================================


class TestTier1Feature09Dataset:
    def test_generate_dataset_fast_creates_manifests_and_wavs(self, tmp_path: Path):
        from asr.synth_data import generate_dataset

        paths = generate_dataset(tmp_path, num_train=6, num_val=2, engine="fast", seed=42)
        assert {"train", "val"} <= set(paths.keys())
        train_lines = [ln for ln in Path(paths["train"]).read_text(encoding="utf-8").splitlines() if ln.strip()]
        val_lines = [ln for ln in Path(paths["val"]).read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(train_lines) == 6
        assert len(val_lines) == 2
        for ln in train_lines + val_lines:
            row = json.loads(ln)
            assert Path(row["audio_path"]).is_file()

    def test_manifest_jsonl_schema_compliance(self, tiny_fast_dataset: dict[str, Path]):
        lines = [ln for ln in tiny_fast_dataset["train"].read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 12
        for ln in lines:
            row = json.loads(ln)
            assert {"audio_path", "text", "duration", "speaker", "source", "moras"} <= set(row.keys())
            assert float(row["duration"]) > 0.0
            assert isinstance(row["moras"], list) and len(row["moras"]) > 0
            assert all({"t", "a", "e"} <= set(m.keys()) for m in row["moras"])

    def test_asr_manifest_dataset_len_and_getitem(self, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset
        from asr.tokenizer import Tokenizer

        ds = ASRManifestDataset(tiny_fast_dataset["train"], AudioConfig(), Tokenizer("kana"), augment=False)
        assert len(ds) == 12
        item = ds[0]
        assert item is not None

    def test_collate_asr_batch_padding_and_shapes(self, tiny_fast_dataset: dict[str, Path]):
        import torch
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset, collate_asr_batch
        from asr.tokenizer import Tokenizer

        ds = ASRManifestDataset(tiny_fast_dataset["train"], AudioConfig(), Tokenizer("kana"), augment=False)
        batch = collate_asr_batch([ds[0], ds[1], ds[2]])
        assert {"feats", "feat_lengths", "targets", "target_lengths", "texts"} <= set(batch.keys())
        assert isinstance(batch["feats"], torch.Tensor)
        assert batch["feats"].ndim == 3 and batch["feats"].shape[0] == 3 and batch["feats"].shape[2] == 64
        assert batch["feat_lengths"].shape == (3,)
        assert batch["feats"].shape[1] == int(batch["feat_lengths"].max())
        assert batch["targets"].ndim == 2 and batch["targets"].shape[0] == 3
        assert batch["target_lengths"].shape == (3,)
        assert isinstance(batch["texts"], list) and len(batch["texts"]) == 3

    def test_asr_manifest_dataset_augment_flag(self, tiny_fast_dataset: dict[str, Path]):
        import torch
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset, collate_asr_batch
        from asr.tokenizer import Tokenizer

        ds = ASRManifestDataset(tiny_fast_dataset["train"], AudioConfig(), Tokenizer("kana"), augment=True)
        b1 = collate_asr_batch([ds[0]])
        b2 = collate_asr_batch([ds[0]])
        assert b1["feats"].shape == b2["feats"].shape
        assert torch.isfinite(b1["feats"]).all()
        assert torch.isfinite(b2["feats"]).all()

    def test_build_manifest_from_wav_dir_tier3(self, tmp_path: Path, helpers):
        from asr.config import AudioConfig
        from asr.dataset import ASRManifestDataset, build_manifest_from_wav_dir
        from asr.tokenizer import Tokenizer

        wav_dir = tmp_path / "wavs"
        for name, freq in [("u1.wav", 300.0), ("u2.wav", 400.0), ("u3.wav", 500.0)]:
            helpers.write_pcm_wav(wav_dir / name, helpers.make_sine(freq, 0.5, 16000), sr=16000)

        out_manifest = tmp_path / "custom.jsonl"
        ret = build_manifest_from_wav_dir(wav_dir, {"u1.wav": "ア", "u2.wav": "イ", "u3.wav": "ウ"}, out_manifest)
        assert Path(ret).is_file()
        ds = ASRManifestDataset(ret, AudioConfig(), Tokenizer("kana"), augment=False)
        assert len(ds) == 3


# ===========================================================================
# Feature 10: Selectable End-to-End CTC Acoustic Models (asr/models/)
# ===========================================================================


class TestTier1Feature10Models:
    def test_build_model_cnn_bigru_forward_and_log_softmax(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        cfg = ModelConfig(arch="cnn_bigru", n_mels=64, hidden_size=32, num_layers=1, dropout=0.0)
        model = build_model(cfg, vocab_size=50)
        feats = torch.randn(2, 40, 64)
        lengths = torch.tensor([40, 28], dtype=torch.long)
        log_probs, out_lengths = model(feats, lengths)

        assert log_probs.ndim == 3 and log_probs.shape[0] == 2 and log_probs.shape[2] == 50
        assert out_lengths.shape == (2,)
        assert int(out_lengths[0]) > int(out_lengths[1]) > 0
        assert torch.isfinite(log_probs).all()
        probs_sum = torch.exp(log_probs).sum(dim=-1)
        assert torch.allclose(probs_sum, torch.ones_like(probs_sum), atol=1e-4)

    def test_build_model_conformer_lite_forward_and_log_softmax(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        cfg = ModelConfig(arch="conformer_lite", n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7, dropout=0.0)
        model = build_model(cfg, vocab_size=50)
        feats = torch.randn(2, 40, 64)
        lengths = torch.tensor([40, 28], dtype=torch.long)
        log_probs, out_lengths = model(feats, lengths)

        assert log_probs.ndim == 3 and log_probs.shape[0] == 2 and log_probs.shape[2] == 50
        assert out_lengths.shape == (2,)
        assert int(out_lengths[0]) > int(out_lengths[1]) > 0
        assert torch.isfinite(log_probs).all()
        probs_sum = torch.exp(log_probs).sum(dim=-1)
        assert torch.allclose(probs_sum, torch.ones_like(probs_sum), atol=1e-4)

    def test_model_subsampling_factor_and_frame_stride(self):
        from asr.config import AudioConfig, ModelConfig
        from asr.models import build_model

        for arch in ("cnn_bigru", "conformer_lite"):
            cfg = ModelConfig(arch=arch, n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)
            model = build_model(cfg, vocab_size=40)
            assert model.subsampling_factor == 4
            assert model.output_frame_stride_ms(AudioConfig()) == pytest.approx(40.0)
            assert model.output_frame_stride_ms(AudioConfig(hop_length=320)) == pytest.approx(80.0)

    def test_default_model_config_cpu_forward_both_archs(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        for arch in ("cnn_bigru", "conformer_lite"):
            model = build_model(ModelConfig(arch=arch), vocab_size=60)
            model.eval()
            with torch.no_grad():
                lp, out_len = model(torch.randn(1, 32, 64), torch.tensor([32]))
            assert lp.shape[0] == 1 and lp.shape[2] == 60
            assert int(out_len[0]) >= 1
            assert torch.isfinite(lp).all()

    def test_ctc_loss_backward_gradient_flow_both_archs(self):
        import torch
        import torch.nn as nn
        from asr.config import ModelConfig
        from asr.models import build_model

        ctc = nn.CTCLoss(blank=0, zero_infinity=True)
        for arch in ("cnn_bigru", "conformer_lite"):
            cfg = ModelConfig(arch=arch, n_mels=64, hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7)
            model = build_model(cfg, vocab_size=40)
            feats = torch.randn(2, 48, 64)
            lengths = torch.tensor([48, 40])
            log_probs, out_lengths = model(feats, lengths)
            targets = torch.tensor([[1, 2, 3], [4, 5, 0]], dtype=torch.long)
            target_lengths = torch.tensor([3, 2], dtype=torch.long)
            loss = ctc(log_probs.transpose(0, 1), targets, out_lengths, target_lengths)
            assert torch.isfinite(loss)
            loss.backward()
            grad_norms = [float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None]
            assert len(grad_norms) > 0 and sum(grad_norms) > 0.0

    def test_eval_mode_deterministic_inference(self):
        import torch
        from asr.config import ModelConfig
        from asr.models import build_model

        model = build_model(ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.2), vocab_size=40)
        model.eval()
        x = torch.randn(1, 36, 64)
        lens = torch.tensor([36])
        with torch.no_grad():
            lp1, _ = model(x, lens)
            lp2, _ = model(x, lens)
        assert torch.equal(lp1, lp2)


# ===========================================================================
# Feature 11: Training Engine & Checkpointing (asr/train.py)
# ===========================================================================


class TestTier1Feature11Training:
    def test_train_asr_creates_best_and_latest_checkpoints(self, tiny_checkpoint: dict):
        assert isinstance(tiny_checkpoint["summary"], dict) and len(tiny_checkpoint["summary"]) > 0
        assert tiny_checkpoint["best_pt"].is_file()
        assert tiny_checkpoint["latest_pt"].is_file()

    def test_load_checkpoint_contract_keys(self, tiny_checkpoint: dict):
        from asr.train import load_checkpoint

        ckpt = load_checkpoint(tiny_checkpoint["best_pt"], device="cpu")
        required = {"model_state_dict", "model_config", "audio_cfg", "tokenizer", "history", "epoch", "best_val_cer"}
        assert required <= set(ckpt.keys())
        assert isinstance(ckpt["model_state_dict"], dict)
        assert int(ckpt["epoch"]) >= 1

    def test_train_asr_resume_from_checkpoint(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import load_checkpoint, train_asr

        ckpt_dir = tmp_path / "resume_ckpt"
        audio_cfg = AudioConfig()
        model_cfg = ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0)
        tok = Tokenizer("kana")

        train_asr(
            tiny_fast_dataset["train"],
            tiny_fast_dataset["val"],
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=TrainConfig(epochs=1, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(ckpt_dir)),
            tokenizer=tok,
        )
        latest = ckpt_dir / "latest.pt"
        assert latest.is_file()

        train_asr(
            tiny_fast_dataset["train"],
            tiny_fast_dataset["val"],
            audio_cfg=audio_cfg,
            model_cfg=model_cfg,
            train_cfg=TrainConfig(epochs=2, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(ckpt_dir)),
            tokenizer=tok,
            resume_from=latest,
        )
        ckpt2 = load_checkpoint(latest, device="cpu")
        assert int(ckpt2["epoch"]) >= 2

    def test_train_asr_conformer_lite_architecture(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import load_checkpoint, train_asr

        ckpt_dir = tmp_path / "conf_ckpt"
        summary = train_asr(
            tiny_fast_dataset["train"],
            tiny_fast_dataset["val"],
            audio_cfg=AudioConfig(),
            model_cfg=ModelConfig(arch="conformer_lite", hidden_size=32, num_layers=1, num_heads=4, conv_kernel_size=7, dropout=0.0),
            train_cfg=TrainConfig(epochs=1, batch_size=4, seed=42, use_spec_augment=False, checkpoint_dir=str(ckpt_dir)),
            tokenizer=Tokenizer("kana"),
        )
        assert isinstance(summary, dict)
        assert (ckpt_dir / "best.pt").is_file()
        ckpt = load_checkpoint(ckpt_dir / "best.pt", device="cpu")
        assert "model_state_dict" in ckpt

    def test_train_asr_deterministic_seed(self, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        from asr.config import AudioConfig, ModelConfig, TrainConfig
        from asr.tokenizer import Tokenizer
        from asr.train import load_checkpoint, train_asr

        results = []
        for idx in range(2):
            cdir = tmp_path / f"det_{idx}"
            train_asr(
                tiny_fast_dataset["train"],
                tiny_fast_dataset["val"],
                audio_cfg=AudioConfig(),
                model_cfg=ModelConfig(arch="cnn_bigru", hidden_size=32, num_layers=1, dropout=0.0),
                train_cfg=TrainConfig(epochs=1, batch_size=4, seed=99, use_spec_augment=False, checkpoint_dir=str(cdir)),
                tokenizer=Tokenizer("kana"),
            )
            results.append(load_checkpoint(cdir / "latest.pt", device="cpu"))

        assert float(results[0]["best_val_cer"]) == pytest.approx(float(results[1]["best_val_cer"]), abs=1e-4)


# ===========================================================================
# Feature 12: CTC Decoding — Greedy, Prefix Beam Search & CharNgramLM
# ===========================================================================


class TestTier1Feature12Decoding:
    def test_greedy_decode_exact_ctc_collapse(self, helpers):
        import numpy as np
        from asr.decoding import greedy_decode
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a, t_i, t_u = tok.encode("アイウ")
        lp = helpers.make_synthetic_log_probs([0, t_a, t_a, 0, t_i, t_i, t_i, 0, t_u, 0], tok.vocab_size)
        res = greedy_decode(lp, tok)
        assert res["text"] == "アイウ"
        assert res["token_ids"] == [t_a, t_i, t_u]
        assert isinstance(res["score"], float) and np.isfinite(res["score"])

    def test_greedy_decode_repeated_char_separated_by_blank(self, helpers):
        from asr.decoding import greedy_decode
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([t_a, t_a, 0, t_a], tok.vocab_size)
        res = greedy_decode(lp, tok)
        assert res["text"] == "アア"
        assert res["token_ids"] == [t_a, t_a]

    def test_prefix_beam_search_matches_greedy_on_peaky_input(self, helpers):
        from asr.config import DecodeConfig
        from asr.decoding import prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        ids = tok.encode("サクラ")
        frames = [0, ids[0], ids[0], 0, ids[1], 0, ids[2], ids[2], 0]
        lp = helpers.make_synthetic_log_probs(frames, tok.vocab_size)
        hyps = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=4))
        assert isinstance(hyps, list) and 1 <= len(hyps) <= 4
        for h in hyps:
            assert {"text", "score", "acoustic_score", "lm_score"} <= set(h.keys())
        assert hyps[0]["text"] == "サクラ"
        for i in range(len(hyps) - 1):
            assert hyps[i]["score"] >= hyps[i + 1]["score"] - 1e-6

    def test_prefix_beam_search_merges_equivalent_ctc_paths(self, helpers):
        from asr.config import DecodeConfig
        from asr.decoding import prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        t_i = tok.encode("イ")[0]
        # Multiple paths emit "ア": (t_a, 0), (0, t_a), (t_a, t_a)
        # Only one narrower path strongly emits "イ"
        lp = helpers.make_weighted_log_probs(
            [
                {0: 2.0, t_a: 2.0, t_i: -5.0},
                {0: 2.0, t_a: 2.0, t_i: 2.05},
            ],
            tok.vocab_size,
        )
        hyps = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=6))
        texts = [h["text"] for h in hyps]
        assert "ア" in texts
        if "イ" in texts:
            assert texts.index("ア") < texts.index("イ")

    def test_char_ngram_lm_fit_and_score_next(self):
        import numpy as np
        from asr.decoding import CharNgramLM

        lm = CharNgramLM(order=3, smoothing=0.1)
        lm.fit(["ニホンゴ"] * 20 + ["サクラ"] * 5)
        s_good = lm.score_next("ニホ", "ン")
        s_bad = lm.score_next("ニホ", "ア")
        assert np.isfinite(s_good) and np.isfinite(s_bad)
        assert s_good <= 0.0 and s_bad <= 0.0
        assert s_good > s_bad

    def test_char_ngram_lm_serialization_roundtrip(self):
        from asr.decoding import CharNgramLM

        lm = CharNgramLM(order=3, smoothing=0.1)
        lm.fit(["ニホンゴ"] * 15 + ["オハヨウ"] * 10)
        d = json.loads(json.dumps(lm.to_dict()))
        lm2 = CharNgramLM.from_dict(d)
        assert lm2.score_next("ニホ", "ン") == pytest.approx(lm.score_next("ニホ", "ン"))
        assert lm2.score_next("オハ", "ヨ") == pytest.approx(lm.score_next("オハ", "ヨ"))

    def test_prefix_beam_search_with_lm_rescoring(self, helpers):
        from asr.config import DecodeConfig
        from asr.decoding import CharNgramLM, prefix_beam_search
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a, t_i, t_u = tok.encode("アイウ")
        lm = CharNgramLM(order=3, smoothing=0.1)
        lm.fit(["アイ"] * 50)

        lp = helpers.make_weighted_log_probs(
            [
                {t_a: 8.0},
                {0: 8.0},
                {t_i: 5.0, t_u: 5.05},
            ],
            tok.vocab_size,
        )
        hyps = prefix_beam_search(lp, tok, DecodeConfig(method="beam", beam_width=6, lm_weight=1.5), lm=lm)
        assert hyps[0]["text"] == "アイ"
        assert hyps[0]["lm_score"] != 0.0


# ===========================================================================
# Feature 13: Viterbi Forced Alignment (asr/decoding.py)
# ===========================================================================


class TestTier1Feature13Alignment:
    def test_viterbi_align_exact_segments(self, helpers):
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a, t_i, t_u = tok.encode("アイウ")
        frames = [t_a] * 4 + [0, 0] + [t_i] * 4 + [0, 0] + [t_u] * 4
        lp = helpers.make_synthetic_log_probs(frames, tok.vocab_size)
        align = viterbi_align(lp, [t_a, t_i, t_u], tok, frame_stride_ms=40.0)
        assert len(align) == 3
        for item in align:
            assert {"token", "start_sec", "end_sec", "confidence"} <= set(item.keys())
        assert [item["token"] for item in align] == ["ア", "イ", "ウ"]
        assert align[0]["start_sec"] <= 0.08
        assert align[1]["start_sec"] >= 0.20
        assert align[2]["start_sec"] >= 0.44

    def test_viterbi_align_monotonic_timestamps_and_bounds(self, helpers):
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        ids = tok.encode("オハヨウ")
        frames = [0, ids[0], ids[0], 0, ids[1], ids[1], 0, ids[2], ids[2], 0, ids[3], ids[3]]
        lp = helpers.make_synthetic_log_probs(frames, tok.vocab_size)
        align = viterbi_align(lp, ids, tok, frame_stride_ms=40.0)
        dur = len(frames) * 0.04
        assert len(align) == len(ids)
        for i, item in enumerate(align):
            assert 0.0 <= item["start_sec"] <= item["end_sec"] <= dur + 1e-6
            if i > 0:
                assert align[i - 1]["start_sec"] <= item["start_sec"] + 1e-6

    def test_viterbi_align_frame_stride_scaling(self, helpers):
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        ids = tok.encode("アイ")
        lp = helpers.make_synthetic_log_probs([0, ids[0], ids[0], 0, ids[1], ids[1]], tok.vocab_size)
        a40 = viterbi_align(lp, ids, tok, frame_stride_ms=40.0)
        a20 = viterbi_align(lp, ids, tok, frame_stride_ms=20.0)
        assert len(a40) == len(a20) == 2
        for x40, x20 in zip(a40, a20):
            assert x20["start_sec"] == pytest.approx(0.5 * x40["start_sec"], abs=1e-6)
            assert x20["end_sec"] == pytest.approx(0.5 * x40["end_sec"], abs=1e-6)

    def test_viterbi_align_confidence_reflects_posterior_strength(self, helpers):
        import numpy as np
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        ids = tok.encode("アイ")
        frames = [ids[0], ids[0], 0, ids[1], ids[1]]
        lp_peaky = helpers.make_synthetic_log_probs(frames, tok.vocab_size, peak_logit=8.0)
        lp_unif = helpers.make_synthetic_log_probs(frames, tok.vocab_size, peak_logit=0.0)
        a_peaky = viterbi_align(lp_peaky, ids, tok, frame_stride_ms=40.0)
        a_unif = viterbi_align(lp_unif, ids, tok, frame_stride_ms=40.0)

        for item in a_peaky + a_unif:
            assert 0.0 <= float(item["confidence"]) <= 1.0 + 1e-6
        mean_peaky = float(np.mean([x["confidence"] for x in a_peaky]))
        mean_unif = float(np.mean([x["confidence"] for x in a_unif]))
        assert mean_peaky > mean_unif

    def test_viterbi_align_repeated_identical_tokens(self, helpers):
        from asr.decoding import viterbi_align
        from asr.tokenizer import Tokenizer

        tok = Tokenizer("kana")
        t_a = tok.encode("ア")[0]
        lp = helpers.make_synthetic_log_probs([t_a, t_a, 0, 0, t_a, t_a], tok.vocab_size)
        align = viterbi_align(lp, [t_a, t_a], tok, frame_stride_ms=40.0)
        assert len(align) == 2
        assert [x["token"] for x in align] == ["ア", "ア"]
        assert align[0]["end_sec"] <= align[1]["start_sec"] + 1e-6


# ===========================================================================
# Feature 14: ASR Evaluation Metrics (asr/metrics.py)
# ===========================================================================


class TestTier1Feature14Metrics:
    def test_compute_cer_exact_match(self):
        from asr.metrics import compute_cer

        res = compute_cer(["アイウエオ"], ["アイウエオ"])
        assert res["cer"] == pytest.approx(0.0)
        assert res["substitutions"] == 0
        assert res["deletions"] == 0
        assert res["insertions"] == 0
        assert res["ref_len"] == 5

    def test_compute_cer_s_d_i_breakdown(self):
        from asr.metrics import compute_cer

        sub = compute_cer(["アイウ"], ["アエウ"])
        assert (sub["substitutions"], sub["deletions"], sub["insertions"], sub["ref_len"]) == (1, 0, 0, 3)
        assert sub["cer"] == pytest.approx(1.0 / 3.0)

        dele = compute_cer(["アイウエ"], ["アイ"])
        assert (dele["substitutions"], dele["deletions"], dele["insertions"], dele["ref_len"]) == (0, 2, 0, 4)
        assert dele["cer"] == pytest.approx(0.5)

        ins = compute_cer(["アイ"], ["アイウエ"])
        assert (ins["substitutions"], ins["deletions"], ins["insertions"], ins["ref_len"]) == (0, 0, 2, 2)
        assert ins["cer"] == pytest.approx(1.0)

    def test_compute_cer_corpus_aggregation(self):
        from asr.metrics import compute_cer

        res = compute_cer(["アイウ", "カキクケ"], ["アエウ", "カキ"])
        assert res["substitutions"] == 1
        assert res["deletions"] == 2
        assert res["insertions"] == 0
        assert res["ref_len"] == 7
        assert res["cer"] == pytest.approx(3.0 / 7.0)

    def test_compute_mer_mora_level(self):
        from asr.metrics import compute_mer

        exact = compute_mer(["シャシン"], ["シャシン"])
        assert exact["mer"] == pytest.approx(0.0)
        diff = compute_mer(["キャ"], ["カ"])
        assert diff["mer"] == pytest.approx(1.0)

    def test_compute_wer_word_level(self):
        from asr.metrics import compute_wer

        exact = compute_wer(["hello world foo bar"], ["hello world foo bar"])
        assert exact["wer"] == pytest.approx(0.0)
        one_wrong = compute_wer(["hello world foo bar"], ["hello mars foo bar"])
        assert one_wrong["wer"] == pytest.approx(0.25)

    def test_confusion_pairs_ranking_and_top_k(self):
        from asr.metrics import confusion_pairs

        pairs = confusion_pairs(["カカカタ"], ["ガガガダ"], top_k=10)
        assert pairs == [("カ", "ガ", 3), ("タ", "ダ", 1)]
        top1 = confusion_pairs(["カカカタ"], ["ガガガダ"], top_k=1)
        assert top1 == [("カ", "ガ", 3)]

    def test_alignment_boundary_error_exact_vs_shifted(self):
        import numpy as np
        from asr.metrics import alignment_boundary_error

        gt = [{"t": "ア", "a": 0.0, "e": 0.2}, {"t": "イ", "a": 0.2, "e": 0.4}]
        exact = [
            {"token": "ア", "start_sec": 0.0, "end_sec": 0.2, "confidence": 0.9},
            {"token": "イ", "start_sec": 0.2, "end_sec": 0.4, "confidence": 0.9},
        ]
        shifted = [
            {"token": "ア", "start_sec": 0.1, "end_sec": 0.3, "confidence": 0.9},
            {"token": "イ", "start_sec": 0.3, "end_sec": 0.5, "confidence": 0.9},
        ]
        r_exact = alignment_boundary_error(gt, exact)
        r_shift = alignment_boundary_error(gt, shifted)
        assert isinstance(r_exact, dict) and len(r_exact) > 0
        assert isinstance(r_shift, dict) and len(r_shift) > 0
        for k, v in r_exact.items():
            if isinstance(v, (int, float)):
                assert np.isfinite(v)
                if "iou" in k.lower() and isinstance(r_shift.get(k), (int, float)):
                    assert v >= r_shift[k] - 1e-6
                if any(w in k.lower() for w in ("error", "offset", "mae")) and isinstance(r_shift.get(k), (int, float)):
                    assert v <= r_shift[k] + 1e-6


# ===========================================================================
# Feature 15: High-Level Inference Engine (asr/inference.py)
# ===========================================================================


class TestTier1Feature15Engine:
    def test_engine_from_checkpoint_loads_with_and_without_lm(self, tiny_checkpoint: dict):
        from asr.decoding import CharNgramLM
        from asr.inference import ASREngine

        eng1 = ASREngine.from_checkpoint(tiny_checkpoint["best_pt"])
        assert eng1 is not None

        lm = CharNgramLM(order=3, smoothing=0.1)
        lm.fit(["アイウ", "オハヨウ"])
        eng2 = ASREngine.from_checkpoint(tiny_checkpoint["best_pt"], lm=lm)
        assert eng2 is not None

    def test_engine_transcribe_contract_keys(self, tiny_engine):
        from asr.synth_data import synthesize_fast_kotoba

        wav, _ = synthesize_fast_kotoba("アイウ", sr=16000, seed=1)
        res = tiny_engine.transcribe(wav, sr=16000)
        assert {"text", "hypotheses", "alignment", "rtf", "duration_sec", "utterance_id"} <= set(res.keys())
        assert isinstance(res["text"], str)
        assert isinstance(res["hypotheses"], list)
        assert isinstance(res["alignment"], list)
        assert float(res["rtf"]) >= 0.0
        assert float(res["duration_sec"]) == pytest.approx(len(wav) / 16000.0, rel=0.05)
        assert isinstance(res["utterance_id"], str) and len(res["utterance_id"]) > 0

    def test_engine_transcribe_include_visuals(self, tiny_engine):
        from asr.synth_data import synthesize_fast_kotoba

        wav, _ = synthesize_fast_kotoba("アイウ", sr=16000, seed=2)
        res = tiny_engine.transcribe(wav, sr=16000, include_visuals=True)
        for key in ("waveform", "log_mel", "ctc_posteriors", "vad_segments"):
            assert key in res and res[key] is not None

    def test_engine_transcribe_greedy_and_beam_configs(self, tiny_engine):
        from asr.config import DecodeConfig
        from asr.synth_data import synthesize_fast_kotoba

        wav, _ = synthesize_fast_kotoba("おはよう", sr=16000, seed=3)
        g = tiny_engine.transcribe(wav, sr=16000, decode_cfg=DecodeConfig(method="greedy"))
        b = tiny_engine.transcribe(wav, sr=16000, decode_cfg=DecodeConfig(method="beam", beam_width=4))
        assert isinstance(g["text"], str) and isinstance(g["hypotheses"], list)
        assert isinstance(b["text"], str) and isinstance(b["hypotheses"], list)

    def test_engine_redecode_uses_cache_and_applies_config(self, tiny_engine):
        from asr.config import DecodeConfig
        from asr.synth_data import synthesize_fast_kotoba

        wav, _ = synthesize_fast_kotoba("アイウ", sr=16000, seed=4)
        res1 = tiny_engine.transcribe(wav, sr=16000)
        utt_id = res1["utterance_id"]

        t0 = time.perf_counter()
        res2 = tiny_engine.redecode(utt_id, DecodeConfig(method="beam", beam_width=4, blank_bias=0.0))
        elapsed = time.perf_counter() - t0
        assert "text" in res2 and "hypotheses" in res2
        assert elapsed < 0.25

        res_blank = tiny_engine.redecode(utt_id, DecodeConfig(method="greedy", blank_bias=50.0))
        assert res_blank["text"] == ""

    def test_engine_transcribe_non_16khz_resamples(self, tiny_engine, helpers):
        wav_22k = helpers.make_speech_like(duration=0.5, sr=22050)
        res = tiny_engine.transcribe(wav_22k, sr=22050)
        assert float(res["duration_sec"]) == pytest.approx(0.5, abs=0.05)


# ===========================================================================
# Feature 16: Full CLI (asr/__main__.py)
# ===========================================================================


class TestTier1Feature16CLI:
    def test_cli_help_lists_all_subcommands(self, run_cli):
        proc = run_cli(["--help"], timeout=60)
        assert proc.returncode == 0, proc.stderr
        for sub in ("demo", "generate", "train", "eval", "transcribe", "serve"):
            assert sub in proc.stdout

    def test_cli_generate_fast(self, run_cli, tmp_path: Path):
        out = tmp_path / "gen"
        proc = run_cli(["generate", "--out-dir", str(out), "--num-train", "3", "--num-val", "2", "--engine", "fast"], timeout=60)
        assert proc.returncode == 0, proc.stderr
        train_lines = [ln for ln in (out / "train.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        val_lines = [ln for ln in (out / "val.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(train_lines) == 3
        assert len(val_lines) == 2

    def test_cli_train_creates_checkpoints(self, run_cli, tmp_path: Path, tiny_fast_dataset: dict[str, Path]):
        out = tmp_path / "cli_ckpt"
        proc = run_cli(
            [
                "train",
                "--train-manifest", str(tiny_fast_dataset["train"]),
                "--val-manifest", str(tiny_fast_dataset["val"]),
                "--out-dir", str(out),
                "--arch", "cnn_bigru",
                "--epochs", "1",
            ],
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert (out / "best.pt").is_file()
        assert (out / "latest.pt").is_file()

    def test_cli_eval_runs_on_manifest(self, run_cli, tiny_checkpoint: dict):
        proc = run_cli(
            [
                "eval",
                "--checkpoint", str(tiny_checkpoint["best_pt"]),
                "--manifest", str(tiny_checkpoint["val_manifest"]),
                "--method", "greedy",
            ],
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        combined = (proc.stdout + proc.stderr).lower()
        assert "cer" in combined

    def test_cli_transcribe_wav_json(self, run_cli, tmp_path: Path, tiny_checkpoint: dict, helpers):
        wav_path = helpers.write_pcm_wav(tmp_path / "sample.wav", helpers.make_speech_like(0.6, 16000), sr=16000)
        proc = run_cli(
            [
                "transcribe",
                "--checkpoint", str(tiny_checkpoint["best_pt"]),
                "--wav", str(wav_path),
                "--method", "greedy",
                "--json",
            ],
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert "text" in payload

    def test_cli_transcribe_tts_json(self, run_cli, tiny_checkpoint: dict):
        proc = run_cli(
            [
                "transcribe",
                "--checkpoint", str(tiny_checkpoint["best_pt"]),
                "--tts", "あか",
                "--preset", "default",
                "--method", "beam",
                "--json",
            ],
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert "text" in payload

    def test_cli_serve_help_flags(self, run_cli):
        proc = run_cli(["serve", "--help"], timeout=60)
        assert proc.returncode == 0, proc.stderr
        for flag in ("--checkpoint", "--host", "--port"):
            assert flag in proc.stdout


# ===========================================================================
# Feature 17: FastAPI Backend (asr/server.py)
# ===========================================================================


class TestTier1Feature17API:
    def test_api_health_loaded(self, api_client):
        resp = api_client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "model_loaded": True}

    def test_api_info_metadata(self, api_client):
        resp = api_client.get("/api/info")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict) and len(data) > 0
        keys_joined = " ".join(k.lower() for k in data.keys())
        assert "vocab" in keys_joined or "tokenizer" in keys_joined
        assert "preset" in keys_joined

    def test_api_transcribe_multipart_wav(self, api_client, helpers):
        wav_bytes = helpers.wav_to_bytes(helpers.make_speech_like(0.6, 16000), sr=16000)
        resp = api_client.post("/api/transcribe", files={"file": ("test.wav", wav_bytes, "audio/wav")})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        for key in ("text", "hypotheses", "alignment", "utterance_id", "duration_sec", "rtf"):
            assert key in data
        for vkey in ("waveform", "log_mel", "ctc_posteriors", "vad_segments"):
            assert vkey in data

    def test_api_tts_roundtrip_fast(self, api_client, helpers):
        resp = api_client.post(
            "/api/tts-roundtrip",
            json={"text": "アイウ", "preset": "default", "synth_engine": "fast"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "audio_b64" in data and isinstance(data["audio_b64"], str)
        raw_wav = base64.b64decode(data["audio_b64"])
        assert raw_wav[:4] == b"RIFF"
        assert "ground_truth_moras" in data and isinstance(data["ground_truth_moras"], list) and len(data["ground_truth_moras"]) > 0
        assert "cer" in data
        tr = helpers.extract_transcribe_payload(data)
        assert "text" in tr

    def test_api_redecode_cached_utterance(self, api_client, helpers):
        wav_bytes = helpers.wav_to_bytes(helpers.make_speech_like(0.5, 16000), sr=16000)
        r1 = api_client.post("/api/transcribe", files={"file": ("u.wav", wav_bytes, "audio/wav")})
        assert r1.status_code == 200
        utt_id = r1.json()["utterance_id"]

        r2 = api_client.post(
            "/api/redecode",
            json={
                "utterance_id": utt_id,
                "decode_cfg": {"method": "beam", "beam_width": 4, "temperature": 1.0, "blank_bias": 0.0},
            },
        )
        assert r2.status_code == 200, r2.text
        data2 = r2.json()
        assert "text" in data2 and "hypotheses" in data2

    def test_create_app_from_checkpoint_path(self, tiny_checkpoint: dict, api_client_factory):
        client = api_client_factory(checkpoint_path=tiny_checkpoint["best_pt"])
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "model_loaded": True}


# ===========================================================================
# Feature 18: Zero-CDN Interactive Web Playground (asr/web/index.html)
# ===========================================================================


class _ExternalAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.external_urls: list[str] = []
        self.canvas_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if t == "canvas":
            self.canvas_count += 1
        if t == "script":
            src = attr_map.get("src", "").strip()
            if src.startswith(("http://", "https://", "//")):
                self.external_urls.append(src)
        if t == "link":
            href = attr_map.get("href", "").strip()
            if href.startswith(("http://", "https://", "//")):
                self.external_urls.append(href)


class TestTier1Feature18WebPlayground:
    def test_web_root_serves_html(self, api_client):
        resp = api_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "").lower()
        body = resp.text
        assert "<html" in body.lower() and "</html>" in body.lower()
        assert len(body) > 1000

    def test_web_zero_cdn_assets(self, api_client):
        body = api_client.get("/").text
        parser = _ExternalAssetParser()
        parser.feed(body)
        assert parser.external_urls == [], f"Found external CDN URLs: {parser.external_urls}"
        assert not re.search(r"@import\s+url\s*\(\s*['\"]?(?:https?:)?//", body, re.IGNORECASE)

    def test_web_has_canvas_visualizers(self, api_client):
        body = api_client.get("/").text
        parser = _ExternalAssetParser()
        parser.feed(body)
        assert parser.canvas_count >= 2
        assert "getcontext('2d')" in body.lower() or 'getcontext("2d")' in body.lower()

    def test_web_has_interactive_audio_and_slider_controls(self, api_client):
        body = api_client.get("/").text
        low = body.lower()
        assert 'type="file"' in low or "type='file'" in low
        assert 'type="range"' in low or "type='range'" in low
        assert any(tok in body for tok in ("AudioContext", "webkitAudioContext", "MediaRecorder", "getUserMedia"))

    def test_web_wires_all_backend_api_endpoints(self, api_client):
        body = api_client.get("/").text
        for route in ("/api/info", "/api/transcribe", "/api/tts-roundtrip", "/api/redecode"):
            assert route in body, f"Playground UI must wire {route}"
