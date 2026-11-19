"""Tests for Milestone M6: FastAPI backend (asr/server.py) and zero-CDN web UI."""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import torch
from fastapi.testclient import TestClient

import yomu
from asr.audio import load_wav_bytes
from asr.config import AudioConfig, ModelConfig, TrainConfig
from asr.decoding import CharNgramLM
from asr.inference import ASREngine
from asr.metrics import compute_cer
from asr.models import build_model
from asr.server import create_app
from asr.synth_data import synthesize_fast_kotoba
from asr.tokenizer import Tokenizer

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "asr" / "web" / "index.html"


@dataclass
class _WebBundle:
    ckpt_path: Path
    mono_16k_wav_bytes: bytes
    stereo_44k_wav_bytes: bytes


def _encode_pcm16_wav(samples: np.ndarray, sr: int, channels: int = 1) -> bytes:
    arr = np.asarray(samples, dtype=np.float32)
    pcm = np.round(np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


@pytest.fixture(scope="module")
def web_bundle(tmp_path_factory: pytest.TempPathFactory) -> _WebBundle:
    tmp_dir = tmp_path_factory.mktemp("asr_web_ckpt")
    torch.manual_seed(1234)

    audio_cfg = AudioConfig(sample_rate=16000, n_mels=64)
    model_cfg = ModelConfig(
        arch="cnn_bigru",
        n_mels=64,
        hidden_size=32,
        num_layers=1,
        dropout=0.0,
    )
    tokenizer = Tokenizer(mode="kana")
    model = build_model(model_cfg, tokenizer.vocab_size)

    ckpt_path = tmp_dir / "tiny_web.pt"
    ckpt = {
        "model_state_dict": model.state_dict(),
        "model_config": model_cfg.to_dict(),
        "audio_config": audio_cfg.to_dict(),
        "audio_cfg": audio_cfg.to_dict(),
        "tokenizer": tokenizer.to_dict(),
        "epoch": 3,
        "best_val_cer": 0.42,
        "train_config": TrainConfig(epochs=3, batch_size=4).to_dict(),
        "history": [
            {"epoch": 1, "train_loss": 3.5, "val_loss": 3.1, "val_cer": 0.85, "lr": 3e-3},
            {"epoch": 2, "train_loss": 2.4, "val_loss": 2.2, "val_cer": 0.60, "lr": 2e-3},
            {"epoch": 3, "train_loss": 1.8, "val_loss": 1.7, "val_cer": 0.42, "lr": 1e-3},
        ],
    }
    torch.save(ckpt, ckpt_path)

    wav_16k, _ = synthesize_fast_kotoba("オハヨウ", sr=16000, seed=7)
    mono_bytes = _encode_pcm16_wav(wav_16k, sr=16000, channels=1)

    t = np.arange(int(44100 * 0.5), dtype=np.float32) / 44100.0
    left = 0.25 * np.sin(2.0 * np.pi * 440.0 * t)
    right = 0.25 * np.sin(2.0 * np.pi * 660.0 * t)
    stereo = np.stack([left, right], axis=-1).reshape(-1)
    stereo_bytes = _encode_pcm16_wav(stereo, sr=44100, channels=2)

    return _WebBundle(
        ckpt_path=ckpt_path,
        mono_16k_wav_bytes=mono_bytes,
        stereo_44k_wav_bytes=stereo_bytes,
    )


@pytest.fixture(scope="module")
def client(web_bundle: _WebBundle) -> TestClient:
    app = create_app(checkpoint_path=web_bundle.ckpt_path)
    return TestClient(app)


@pytest.fixture(scope="module")
def client_no_model() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture(scope="module")
def client_engine_with_lm(web_bundle: _WebBundle) -> TestClient:
    lm = CharNgramLM(order=2, smoothing=0.1).fit(["オハヨウ", "コンニチハ", "サクラ"])
    engine = ASREngine.from_checkpoint(web_bundle.ckpt_path, lm=lm)
    app = create_app(engine=engine)
    return TestClient(app)


# ---------------------------------------------------------------------------
# A. App Creation, Root HTML, Health & Info
# ---------------------------------------------------------------------------


def test_get_root_html(client: TestClient, client_no_model: TestClient) -> None:
    for c in (client, client_no_model):
        res = c.get("/")
        assert res.status_code == 200
        assert res.headers["content-type"].lower().startswith("text/html")
        body = res.text
        assert len(body) > 1000
        for marker in (
            "<canvas",
            "/api/info",
            "/api/transcribe",
            "/api/tts-roundtrip",
            "/api/redecode",
        ):
            assert marker in body


def test_health_loaded_and_unloaded(
    client: TestClient, client_no_model: TestClient
) -> None:
    res_ok = client.get("/api/health")
    assert res_ok.status_code == 200
    assert res_ok.json() == {"status": "ok", "model_loaded": True}

    res_no = client_no_model.get("/api/health")
    assert res_no.status_code == 200
    assert res_no.json() == {"status": "ok", "model_loaded": False}


def test_info_loaded_and_unloaded(
    client: TestClient, client_no_model: TestClient
) -> None:
    res = client.get("/api/info")
    assert res.status_code == 200
    data = res.json()
    json.dumps(data, allow_nan=False)

    assert data["model_loaded"] is True
    assert data["arch"] == "cnn_bigru"
    assert data["vocab_size"] > 0
    assert isinstance(data["vocab"], list)
    assert len(data["vocab"]) == data["vocab_size"]
    assert set(data["tsukinami_presets"]) == set(yomu.PRESETS.keys())
    assert isinstance(data["history"], list)
    assert len(data["history"]) == 3

    res_no = client_no_model.get("/api/info")
    assert res_no.status_code == 200
    data_no = res_no.json()
    json.dumps(data_no, allow_nan=False)
    assert data_no["model_loaded"] is False
    assert "default" in data_no["tsukinami_presets"]
    assert data_no["history"] == []


def test_create_app_precedence_and_missing_checkpoint(
    web_bundle: _WebBundle, tmp_path: Path
) -> None:
    missing = tmp_path / "does_not_exist.pt"
    with pytest.raises(FileNotFoundError):
        create_app(checkpoint_path=missing)

    engine = ASREngine.from_checkpoint(web_bundle.ckpt_path)
    app = create_app(checkpoint_path=missing, engine=engine)
    c = TestClient(app)
    assert c.get("/api/health").json() == {"status": "ok", "model_loaded": True}


# ---------------------------------------------------------------------------
# B. POST /api/transcribe
# ---------------------------------------------------------------------------


def test_transcribe_multipart_with_and_without_visuals(
    client: TestClient, web_bundle: _WebBundle
) -> None:
    res = client.post(
        "/api/transcribe",
        files={"file": ("sample.wav", web_bundle.mono_16k_wav_bytes, "audio/wav")},
        data={
            "method": "beam",
            "beam_width": "4",
            "temperature": "1.0",
            "blank_bias": "0.0",
            "snr_db": "20",
            "noise_type": "pink",
            "band_limit_low": "300",
            "band_limit_high": "3400",
            "speed": "1.1",
            "include_visuals": "true",
        },
    )
    assert res.status_code == 200
    data = res.json()
    json.dumps(data, allow_nan=False)

    for key in (
        "text",
        "hypotheses",
        "alignment",
        "rtf",
        "duration_sec",
        "utterance_id",
        "waveform",
        "log_mel",
        "ctc_posteriors",
        "vad_segments",
    ):
        assert key in data
    assert isinstance(data["utterance_id"], str) and len(data["utterance_id"]) > 0
    info_vocab_size = client.get("/api/info").json()["vocab_size"]
    post = data["ctc_posteriors"]
    assert isinstance(post, list) and len(post) > 0
    post_arr = np.asarray(post, dtype=np.float64)
    assert post_arr.ndim == 2
    assert post_arr.shape[0] > 0
    assert post_arr.shape[1] == info_vocab_size
    assert np.isfinite(post_arr).all()
    assert float(np.min(post_arr)) >= 0.0
    assert float(np.max(post_arr)) <= 1.0
    assert np.allclose(post_arr.sum(axis=-1), np.ones(post_arr.shape[0]), atol=1e-4)

    # include_visuals="false" must genuinely omit visual payloads
    res_no_vis = client.post(
        "/api/transcribe",
        files={"file": ("sample.wav", web_bundle.mono_16k_wav_bytes, "audio/wav")},
        data={
            "method": "greedy",
            "snr_db": "",
            "band_limit_low": "",
            "band_limit_high": "",
            "include_visuals": "false",
        },
    )
    assert res_no_vis.status_code == 200
    data_nv = res_no_vis.json()
    for vis_key in ("waveform", "log_mel", "ctc_posteriors", "vad_segments"):
        assert vis_key not in data_nv


def test_transcribe_json_base64(client: TestClient, web_bundle: _WebBundle) -> None:
    b64 = base64.b64encode(web_bundle.mono_16k_wav_bytes).decode("ascii")
    res = client.post(
        "/api/transcribe",
        json={
            "audio_b64": b64,
            "decode_cfg": {
                "method": "beam",
                "beam_width": 4,
                "temperature": 0.9,
                "blank_bias": -0.2,
            },
            "corruption": {
                "snr_db": 15.0,
                "noise_type": "white",
                "band_limit": [300.0, 3400.0],
                "speed": 0.95,
            },
            "include_visuals": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["utterance_id"]
    assert "waveform" in data
    assert "log_mel" in data

    # Data URI prefix + include_visuals=False
    res_uri = client.post(
        "/api/transcribe",
        json={
            "audio_b64": f"data:audio/wav;base64,{b64}",
            "include_visuals": False,
        },
    )
    assert res_uri.status_code == 200
    assert "waveform" not in res_uri.json()


def test_transcribe_stereo_44k_resampling(
    client: TestClient, web_bundle: _WebBundle
) -> None:
    res = client.post(
        "/api/transcribe",
        files={"file": ("stereo.wav", web_bundle.stereo_44k_wav_bytes, "audio/wav")},
    )
    assert res.status_code == 200
    data = res.json()
    json.dumps(data, allow_nan=False)
    assert data["duration_sec"] == pytest.approx(0.5, abs=0.05)


def test_transcribe_invalid_inputs_return_4xx_never_500(
    client: TestClient, web_bundle: _WebBundle
) -> None:
    b64 = base64.b64encode(web_bundle.mono_16k_wav_bytes).decode("ascii")

    # Empty file
    r = client.post(
        "/api/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert r.status_code in (400, 422)

    # Corrupt WAV header
    r = client.post(
        "/api/transcribe",
        files={"file": ("bad.wav", b"RIFF0000WAVEcorrupt", "audio/wav")},
    )
    assert r.status_code in (400, 422)

    # Non-WAV garbage
    r = client.post(
        "/api/transcribe",
        files={"file": ("junk.wav", b"not audio at all", "audio/wav")},
    )
    assert r.status_code in (400, 422)

    # Missing file field in multipart
    r = client.post("/api/transcribe", data={"method": "greedy"})
    assert r.status_code in (400, 422)

    # Invalid base64
    r = client.post("/api/transcribe", json={"audio_b64": "!!!not-base64!!!"})
    assert r.status_code in (400, 422)

    # Missing audio_b64
    r = client.post("/api/transcribe", json={})
    assert r.status_code in (400, 422)

    # Malformed JSON body
    r = client.post(
        "/api/transcribe",
        content=b"{broken",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 422)

    # Invalid decode_cfg values
    for bad_dec in (
        {"method": "invalid"},
        {"beam_width": 0},
        {"temperature": 0.0},
        {"lm_weight": -1.0},
    ):
        r = client.post(
            "/api/transcribe",
            json={"audio_b64": b64, "decode_cfg": bad_dec},
        )
        assert r.status_code in (400, 422), f"Expected 4xx for {bad_dec}, got {r.status_code}"

    # Invalid corruption values
    for bad_corr in (
        {"noise_type": "brown"},
        {"speed": 0.0},
        {"band_limit": [3400.0, 300.0]},
        {"band_limit_low": 300.0},
    ):
        r = client.post(
            "/api/transcribe",
            json={"audio_b64": b64, "corruption": bad_corr},
        )
        assert r.status_code in (400, 422), f"Expected 4xx for {bad_corr}, got {r.status_code}"


def test_transcribe_no_model_returns_503(
    client_no_model: TestClient, web_bundle: _WebBundle
) -> None:
    r1 = client_no_model.post(
        "/api/transcribe",
        files={"file": ("sample.wav", web_bundle.mono_16k_wav_bytes, "audio/wav")},
    )
    assert r1.status_code == 503

    b64 = base64.b64encode(web_bundle.mono_16k_wav_bytes).decode("ascii")
    r2 = client_no_model.post("/api/transcribe", json={"audio_b64": b64})
    assert r2.status_code == 503


# ---------------------------------------------------------------------------
# C. POST /api/tts-roundtrip
# ---------------------------------------------------------------------------


def test_tts_roundtrip_fast_engine_and_corruption(client: TestClient) -> None:
    res = client.post(
        "/api/tts-roundtrip",
        json={
            "text": "オハヨウ",
            "synth_engine": "fast",
            "preset": "default",
            "hz": 260.0,
            "fscale": 1.05,
            "rate": 1.1,
            "corruption": {
                "snr_db": 18.0,
                "noise_type": "white",
                "band_limit": [300.0, 3400.0],
                "speed": 1.1,
            },
            "decode_cfg": {"method": "beam", "beam_width": 4},
            "include_visuals": True,
        },
    )
    assert res.status_code == 200
    data = res.json()
    json.dumps(data, allow_nan=False)

    for key in (
        "audio_b64",
        "ground_truth_moras",
        "cer",
        "cer_details",
        "text",
        "hypotheses",
        "alignment",
        "rtf",
        "duration_sec",
        "utterance_id",
        "waveform",
        "log_mel",
        "ctc_posteriors",
        "vad_segments",
    ):
        assert key in data

    raw_wav = base64.b64decode(data["audio_b64"])
    wav, sr = load_wav_bytes(raw_wav, target_sr=16000)
    assert wav.size > 0
    assert sr == 16000

    moras = data["ground_truth_moras"]
    assert isinstance(moras, list) and len(moras) > 0
    assert set(moras[0].keys()) == {"t", "a", "e"}
    assert isinstance(data["cer"], float) and data["cer"] >= 0.0
    assert {"cer", "substitutions", "deletions", "insertions", "ref_len"} <= set(
        data["cer_details"].keys()
    )


def test_tts_roundtrip_tsukinami_presets_and_overrides(client: TestClient) -> None:
    res_def = client.post(
        "/api/tts-roundtrip",
        json={"text": "アイ", "synth_engine": "tsukinami", "preset": "default"},
    )
    assert res_def.status_code == 200
    d1 = res_def.json()
    wav1, sr1 = load_wav_bytes(base64.b64decode(d1["audio_b64"]), target_sr=16000)
    assert wav1.size > 0 and sr1 == 16000
    assert len(d1["ground_truth_moras"]) > 0

    res_robot = client.post(
        "/api/tts-roundtrip",
        json={
            "text": "アイ",
            "synth_engine": "tsukinami",
            "preset": "robot",
            "hz": 200.0,
            "fscale": 1.0,
            "yure": 0.0,
            "rate": 1.1,
        },
    )
    assert res_robot.status_code == 200
    d2 = res_robot.json()
    wav2, _ = load_wav_bytes(base64.b64decode(d2["audio_b64"]), target_sr=16000)
    assert wav2.size > 0

    # Hiragana input normalization
    res_hira = client.post(
        "/api/tts-roundtrip",
        json={"text": "あい", "synth_engine": "fast"},
    )
    assert res_hira.status_code == 200


def test_tts_roundtrip_invalid_inputs_and_no_model(
    client: TestClient, client_no_model: TestClient
) -> None:
    bad_payloads = [
        {"text": ""},
        {"text": "   "},
        {"text": "!!!", "synth_engine": "fast"},
        {"text": "!!!", "synth_engine": "tsukinami"},
        {"text": "アイ", "preset": "nonexistent_preset"},
        {"text": "アイ", "synth_engine": "espeak"},
        {"text": "アイ", "hz": 0.0},
        {"text": "アイ", "hz": -10.0},
        {"text": "アイ", "fscale": 0.0},
        {"text": "アイ", "rate": -1.0},
        {"text": "アイ", "yure": -0.5},
        {"text": "アイ", "decode_cfg": {"method": "bad"}},
        {"text": "アイ", "corruption": {"speed": 0.0}},
    ]
    for payload in bad_payloads:
        r = client.post("/api/tts-roundtrip", json=payload)
        assert r.status_code in (400, 422), f"Expected 4xx for {payload}, got {r.status_code}"

    r_no = client_no_model.post("/api/tts-roundtrip", json={"text": "アイ"})
    assert r_no.status_code == 503


# ---------------------------------------------------------------------------
# D. POST /api/redecode
# ---------------------------------------------------------------------------


def test_redecode_from_transcribe_and_roundtrip_fast(
    client_engine_with_lm: TestClient, web_bundle: _WebBundle
) -> None:
    r1 = client_engine_with_lm.post(
        "/api/transcribe",
        files={"file": ("sample.wav", web_bundle.mono_16k_wav_bytes, "audio/wav")},
    )
    assert r1.status_code == 200
    utt_id_1 = r1.json()["utterance_id"]

    r2 = client_engine_with_lm.post(
        "/api/tts-roundtrip",
        json={"text": "オハヨウ", "synth_engine": "fast"},
    )
    assert r2.status_code == 200
    utt_id_2 = r2.json()["utterance_id"]

    # Warm-up redecode
    _ = client_engine_with_lm.post(
        "/api/redecode",
        json={"utterance_id": utt_id_1, "decode_cfg": {"method": "greedy"}},
    )

    t0 = time.perf_counter()
    rd_greedy = client_engine_with_lm.post(
        "/api/redecode",
        json={
            "utterance_id": utt_id_1,
            "decode_cfg": {"method": "greedy", "temperature": 0.7, "blank_bias": -0.5},
        },
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0
    assert rd_greedy.status_code == 200
    dg = rd_greedy.json()
    assert dg["utterance_id"] == utt_id_1
    for k in ("text", "hypotheses", "alignment", "utterance_id", "duration_sec", "decode_ms"):
        assert k in dg
    assert dg["decode_ms"] < 50.0
    assert wall_ms < 200.0

    rd_beam = client_engine_with_lm.post(
        "/api/redecode",
        json={
            "utterance_id": utt_id_1,
            "decode_cfg": {
                "method": "beam",
                "beam_width": 6,
                "temperature": 1.2,
                "blank_bias": 0.3,
                "lm_weight": 0.3,
                "insertion_bonus": 0.1,
            },
        },
    )
    assert rd_beam.status_code == 200
    assert rd_beam.json()["decode_ms"] < 50.0

    rd_rt = client_engine_with_lm.post(
        "/api/redecode",
        json={"utterance_id": utt_id_2, "decode_cfg": {"method": "greedy"}},
    )
    assert rd_rt.status_code == 200
    assert rd_rt.json()["utterance_id"] == utt_id_2


def test_redecode_unknown_id_invalid_cfg_and_no_model(
    client: TestClient, client_no_model: TestClient
) -> None:
    r_404 = client.post(
        "/api/redecode",
        json={"utterance_id": "does-not-exist", "decode_cfg": {"method": "greedy"}},
    )
    assert r_404.status_code == 404

    r_422 = client.post(
        "/api/redecode",
        json={"utterance_id": "any", "decode_cfg": {"temperature": 0.0}},
    )
    assert r_422.status_code in (400, 422)

    r_503 = client_no_model.post(
        "/api/redecode",
        json={"utterance_id": "any", "decode_cfg": {"method": "greedy"}},
    )
    assert r_503.status_code == 503


# ---------------------------------------------------------------------------
# E. Static Zero-CDN & HTML/JS Structural Checks on asr/web/index.html
# ---------------------------------------------------------------------------


def test_index_html_zero_cdn_and_self_contained() -> None:
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    forbidden_patterns = [
        r"https?://",
        r"""src\s*=\s*["']//""",
        r"""href\s*=\s*["']//""",
        r"""url\(\s*["']?(?:https?:|//)""",
        r"""@import\s+["']?(?:https?:|//)""",
        r"(?:cdn\.|unpkg\.com|jsdelivr\.net|googleapis\.com|gstatic\.com|cdnjs\.cloudflare\.com)",
    ]
    for pat in forbidden_patterns:
        matches = re.findall(pat, html, flags=re.IGNORECASE)
        assert not matches, f"Forbidden external/CDN reference matched {pat!r}: {matches}"


def test_index_html_structure_and_js_syntax(tmp_path: Path) -> None:
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    assert "<!DOCTYPE html>" in html
    assert "<html" in html and "</html>" in html
    assert "<head>" in html and "</head>" in html
    assert "<body>" in html and "</body>" in html
    assert html.count("<script>") == html.count("</script>")
    assert html.count("<style>") == html.count("</style>")

    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
    assert len(scripts) >= 1
    combined_js = "\n".join(scripts).strip()
    assert len(combined_js) > 500

    for token in (
        "/api/info",
        "/api/transcribe",
        "/api/tts-roundtrip",
        "/api/redecode",
        'getContext("2d")',
    ):
        assert token in combined_js

    node_bin = shutil.which("node")
    if node_bin:
        for i, block in enumerate(scripts):
            js_file = tmp_path / f"inline_script_{i}.js"
            js_file.write_text(block, encoding="utf-8")
            proc = subprocess.run(
                [node_bin, "--check", str(js_file)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"node --check failed on script {i}: {proc.stderr}"


def test_dropzone_click_no_infinite_recursion_regression(tmp_path: Path) -> None:
    """Regression test for chal_2 Defect 1: clicking #btnPickWav or #dropZone must not recurse."""
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
    combined_js = "\n".join(scripts)

    # Static guard checks
    assert 'el.wavFileInput.addEventListener("click"' in combined_js
    assert "e.stopPropagation()" in combined_js
    assert "e.target !== el.wavFileInput" in combined_js

    # Runtime DOM event-bubbling harness via Node.js using the actual handler snippet
    node_bin = shutil.which("node")
    assert node_bin is not None, "node is required to execute the DOM bubbling regression harness"

    # Extract the three click-handler registrations from the script
    m = re.search(
        r'(el\.wavFileInput\.addEventListener\("click".*?el\.wavFileInput\.addEventListener\("change")',
        combined_js,
        flags=re.DOTALL,
    )
    assert m is not None, "Could not locate WAV upload click handlers in index.html"
    handler_snippet = m.group(1).rsplit('el.wavFileInput.addEventListener("change"', 1)[0]

    harness = tmp_path / "dropzone_bubbling_test.js"
    harness.write_text(
        """
class MockElement {
  constructor(id, parent = null) {
    this.id = id;
    this.parent = parent;
    this.children = [];
    this.listeners = {};
    this.clickCount = 0;
    if (parent) parent.children.push(this);
  }
  addEventListener(type, fn) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn);
  }
  contains(node) {
    let cur = node;
    while (cur) {
      if (cur === this) return true;
      cur = cur.parent;
    }
    return false;
  }
  click() {
    this.clickCount += 1;
    if (this.clickCount > 50) {
      throw new Error("Infinite click recursion detected on #" + this.id);
    }
    let stopped = false;
    const event = {
      target: this,
      stopPropagation() { stopped = true; },
    };
    let cur = this;
    while (cur && !stopped) {
      for (const fn of (cur.listeners.click || [])) {
        fn(event);
      }
      cur = cur.parent;
    }
  }
}

const dropZone = new MockElement("dropZone");
const dropText = new MockElement("dropText", dropZone);
const wavFileInput = new MockElement("wavFileInput", dropZone);
const btnPickWav = new MockElement("btnPickWav", dropZone);
const btnInnerSpan = new MockElement("btnInnerSpan", btnPickWav);

const el = { dropZone, wavFileInput, btnPickWav };
"""
        + handler_snippet
        + """
// 1. Clicking #btnPickWav opens file picker exactly once
btnPickWav.click();
if (wavFileInput.clickCount !== 1) {
  throw new Error("Expected 1 wavFileInput click after #btnPickWav click, got " + wavFileInput.clickCount);
}

// 2. Clicking a child inside #btnPickWav opens file picker exactly once
btnInnerSpan.click();
if (wavFileInput.clickCount !== 2) {
  throw new Error("Expected 2 wavFileInput clicks after child of #btnPickWav click, got " + wavFileInput.clickCount);
}

// 3. Clicking #dropZone directly opens file picker exactly once
dropZone.click();
if (wavFileInput.clickCount !== 3) {
  throw new Error("Expected 3 wavFileInput clicks after #dropZone click, got " + wavFileInput.clickCount);
}

// 4. Clicking text inside #dropZone opens file picker exactly once
dropText.click();
if (wavFileInput.clickCount !== 4) {
  throw new Error("Expected 4 wavFileInput clicks after #dropText click, got " + wavFileInput.clickCount);
}

// 5. Clicking #wavFileInput directly does not re-trigger itself
wavFileInput.click();
if (wavFileInput.clickCount !== 5) {
  throw new Error("Expected 5 wavFileInput clicks after direct click, got " + wavFileInput.clickCount);
}
console.log("OK");
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [node_bin, str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"DOM bubbling harness failed: {proc.stderr}\n{proc.stdout}"
    assert proc.stdout.strip() == "OK"


def test_client_cer_normalization_matches_server_compute_cer(tmp_path: Path) -> None:
    """Regression test for chal_2 Defect 2: normalizeKanaClient matches compute_cer(normalize_kana=True)."""
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE)
    combined_js = "\n".join(scripts)

    m = re.search(
        r"(function normalizeKanaClient\(s\).*?function computeClientCer\(refStr, hypStr\).*?return \{ cer, substitutions: s, deletions: d, insertions: ins, ref_len: m \};\s*\})",
        combined_js,
        flags=re.DOTALL,
    )
    assert m is not None, "Could not extract normalizeKanaClient and computeClientCer from index.html"
    fn_block = m.group(1)

    pairs = [
        ("ワタシ、ニホンゴ。", "ワタシニホンゴ"),
        ("わたし、にほんご。", "ワタシ、ニホンゴ。"),
        ("ワタシ、ニホンゴ、チョットシャベレマス", "ワタシニホンゴチョットシャベレマス"),
        ("ワタシ、ニホンゴ、チョットシャベレマス", "ワタシ、ニホンゴ、チョットシャベレマス"),
        ("おはようございます", "オハヨウゴザイマス"),
        ("", "ア"),
        ("", ""),
    ]

    node_bin = shutil.which("node")
    assert node_bin is not None, "node is required to execute the CER parity test"

    harness = tmp_path / "cer_parity_test.js"
    harness.write_text(
        fn_block
        + "\nconst pairs = "
        + json.dumps(pairs, ensure_ascii=False)
        + ";\nconst results = pairs.map(([r, h]) => computeClientCer(r, h));\n"
        + "console.log(JSON.stringify(results));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [node_bin, str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"JS CER harness failed: {proc.stderr}"
    js_results = json.loads(proc.stdout)

    for (ref, hyp), js_res in zip(pairs, js_results):
        py_res = compute_cer([ref], [hyp], normalize_kana=True)
        assert js_res["ref_len"] == py_res["ref_len"], f"ref_len mismatch for ({ref!r}, {hyp!r})"
        assert js_res["substitutions"] == py_res["substitutions"], f"sub mismatch for ({ref!r}, {hyp!r})"
        assert js_res["deletions"] == py_res["deletions"], f"del mismatch for ({ref!r}, {hyp!r})"
        assert js_res["insertions"] == py_res["insertions"], f"ins mismatch for ({ref!r}, {hyp!r})"
        assert js_res["cer"] == pytest.approx(py_res["cer"], abs=1e-12), (
            f"CER mismatch for ({ref!r}, {hyp!r}): JS={js_res} vs PY={py_res}"
        )

