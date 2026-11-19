#!/usr/bin/env python3
"""kusanagi_yomu.py — イタコASRループ用の薄い橋（草薙版: 純JS hitofude.mjs + CLI yomu.mjs）

Python の合成器は使わず、合成はすべて `node yomu.mjs --recipe <json> --measure -o <wav> -- <texts...>` で行う。
- PRESETS / KNOB_KEYS は hitofude.mjs から node で読み出す（数値の二重管理をしない）。
- つまみ値は node に渡す前に有限値・範囲を自前で確かめる（yomu.mjs 側の検査に頼り切らない）。
- node は環境変数 ITAKO_NODE、なければ PATH の node を使う。
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
YOMU_MJS = os.path.join(REPO_ROOT, "yomu.mjs")
HITOFUDE_MJS = os.path.join(REPO_ROOT, "hitofude.mjs")
NODE_TIMEOUT_SEC = 300

_MEASURE_RE = re.compile(r"^\s*\[Measure\]\s*(\{.*\})\s*$")
_cache = {}


def node_bin():
    nb = os.environ.get("ITAKO_NODE") or shutil.which("node")
    if not nb:
        raise RuntimeError("node が見つからない。ITAKO_NODE=/path/to/node を設定する。")
    return nb


def _load():
    if "presets" not in _cache:
        js = (
            "const M = await import(process.argv[1]);"
            "console.log(JSON.stringify({PRESETS: M.PRESETS, KNOB_KEYS: M.KNOB_KEYS}));"
        )
        url = "file://" + HITOFUDE_MJS
        out = subprocess.check_output(
            [node_bin(), "--input-type=module", "-e", js, url], text=True, timeout=NODE_TIMEOUT_SEC
        )
        d = json.loads(out.strip().splitlines()[-1])
        _cache["presets"] = d["PRESETS"]
        _cache["knob_keys"] = list(d["KNOB_KEYS"])
    return _cache["presets"], _cache["knob_keys"]


def presets():
    return _load()[0]


def knob_keys():
    return _load()[1]


def validate_prm(prm):
    """yomu.mjs と同じ条件を Python 側でも先に見る。NG なら ValueError。"""
    keys = knob_keys()
    clean = {}
    for k in keys:
        if k not in prm:
            raise ValueError(f"missing knob '{k}'")
        v = float(prm[k])
        if not math.isfinite(v):
            raise ValueError(f"'{k}' must be finite, got {prm[k]!r}")
        clean[k] = v
    if clean["hz"] <= 0 or clean["fscale"] <= 0 or clean["rate"] <= 0:
        raise ValueError("hz / fscale / rate must be > 0")
    if not (0.0 <= clean["g_vo"] < 1.0):
        raise ValueError(f"g_vo must be in [0, 1), got {clean['g_vo']}")
    clean["tilt_w"] = int(round(clean["tilt_w"]))
    if clean["tilt_w"] < 1:
        raise ValueError(f"tilt_w must be >= 1, got {clean['tilt_w']}")
    clean["seed"] = int(clean["seed"])
    return clean


def synth_many(texts, prm, wav_paths, measure=False):
    """texts を1回の `node yomu.mjs` で合成し wav_paths に置く。measure=True なら hakaru 辞書のリストを返す。"""
    if len(texts) != len(wav_paths):
        raise ValueError("texts and wav_paths length mismatch")
    if not texts:
        return []
    clean = validate_prm(prm)
    with tempfile.TemporaryDirectory(prefix="itako_yomu_") as td:
        recipe = os.path.join(td, "recipe.json")
        with open(recipe, "w", encoding="utf-8") as f:
            json.dump(clean, f)
        out = os.path.join(td, "u.wav")
        cmd = [node_bin(), YOMU_MJS, "--recipe", recipe, "-o", out]
        if measure:
            cmd.append("--measure")
        cmd += ["--", *texts]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=NODE_TIMEOUT_SEC, cwd=td)
        if res.returncode != 0:
            raise RuntimeError(f"yomu.mjs failed (exit {res.returncode}): {res.stderr.strip()[:500]}")
        produced = [out] if len(texts) == 1 else [os.path.join(td, f"u_{i + 1}.wav") for i in range(len(texts))]
        for src, dst in zip(produced, wav_paths):
            os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
            shutil.move(src, dst)
        if not measure:
            return None
        hks = []
        for line in res.stdout.splitlines():
            m = _MEASURE_RE.match(line)
            if m:
                hk = json.loads(m.group(1))
                hk.pop("sha256_16", None)
                hks.append(hk)
        if len(hks) != len(texts):
            raise RuntimeError(f"expected {len(texts)} [Measure] lines, got {len(hks)}")
        return hks
