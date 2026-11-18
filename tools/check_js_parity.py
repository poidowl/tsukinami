#!/usr/bin/env python3
"""tools/check_js_parity.py — hitofude ブランチ (Python) と main ブランチ (hitofude_player.html 内蔵JS) の突き合わせ検証

使い方:
  python3 tools/check_js_parity.py                            # デフォルト: origin/main (なければ main) の hitofude_player.html と照合
  python3 tools/check_js_parity.py --ref main                 # 指定ブランチ/コミットの hitofude_player.html と照合
  python3 tools/check_js_parity.py path/to/hitofude_player.html
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..")) if not os.path.exists(os.path.join(HERE, "hitofude.py")) else HERE
sys.path.insert(0, REPO_ROOT)

import hitofude as H  # noqa: E402
import yomu as Y      # noqa: E402

CORE_PY_FILES = ("hitofude.py", "yomu.py", "kotoba.py", "accent.py")

SENTENCES = [
    "わたし、にほんご、ちょっとしゃべれます",
    "ワタシノ'ナマエハ 0ツキナミ?",
    "ノンアルコール　ウェットティッシュ",
]
UTA_CASE = ("ワタシノナマエハ", [294.0, 330.0, 349.0, 392.0, 440.0, 392.0, 330.0, 294.0])
EDGE_CASES = ["", "、", "ッ", "ス", "ン"]

FORBIDDEN_TOKENS = (
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "alert(",
    "confirm(",
    "prompt(",
    "<form",
)


def _git(args):
    return subprocess.check_output(["git", "-C", REPO_ROOT, *args], text=True, stderr=subprocess.DEVNULL).strip()


def describe_python_side():
    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"])
        sha = _git(["rev-parse", "--short=7", "HEAD"])
        dirty = bool(_git(["status", "--porcelain", "--", *CORE_PY_FILES]))
        return f"{branch}@{sha}{'+dirty' if dirty else ''}"
    except Exception:
        return "local-python(no-git)"


def load_player_html(path_arg, ref_arg):
    if path_arg:
        with open(path_arg, "r", encoding="utf-8") as f:
            html = f.read()
        h8 = hashlib.sha256(html.encode("utf-8")).hexdigest()[:8]
        return html, f"file:{path_arg} (sha256:{h8})"

    candidates = [ref_arg] if ref_arg else ["origin/main", "main"]
    last_err = None
    for ref in candidates:
        try:
            commit_sha = _git(["rev-parse", "--short=7", ref])
            blob_sha = _git(["rev-parse", "--short=7", f"{ref}:hitofude_player.html"])
            html = subprocess.check_output(
                ["git", "-C", REPO_ROOT, "show", f"{ref}:hitofude_player.html"],
                text=True,
            )
            return html, f"{ref}@{commit_sha}:hitofude_player.html (blob:{blob_sha})"
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not read hitofude_player.html from git refs {candidates}: {last_err}")


def extract_engine_js(html):
    m = re.search(r"<script>([\s\S]*?)</script>", html)
    if not m:
        raise RuntimeError("<script> block not found in hitofude_player.html")
    script = m.group(1)
    i0 = script.find('"use strict";')
    i1 = script.find("const STEP_META =")
    if i0 < 0 or i1 < 0 or i1 <= i0:
        raise RuntimeError("Could not locate engine boundaries inside <script>")
    return script[i0 + len('"use strict";') : i1]


def audit_sandbox_html(html):
    errs = []
    for tok in FORBIDDEN_TOKENS:
        if tok in html:
            errs.append(f"forbidden token in player HTML: {tok}")
    for tag in re.findall(r"<(?:script|link|img|audio|font)\b[^>]*>", html, flags=re.I):
        if 'rel="canonical"' in tag or "rel='canonical'" in tag:
            continue
        if re.search(r"(?:src|href)\s*=\s*['\"]https?://", tag, flags=re.I):
            errs.append(f"external resource tag in player HTML: {tag}")
    return errs


def _run_py_job(j):
    r_py = {}
    if j["edge"]:
        s_py, _ = H.make_hitofude(j["text"], pre=0.0, post=0.0, out_r=r_py, **j["prm"])
    else:
        s_py, _ = Y.synth(j["text"], j["prm"], uta_hz=j["uta_hz"], out_r=r_py)
    return s_py, H.hakaru(s_py, r_py)


def main():
    ap = argparse.ArgumentParser(description="Verify Python hitofude.py vs JS hitofude_player.html parity")
    ap.add_argument("player_html", nargs="?", default=None, help="Local path to hitofude_player.html (overrides --ref)")
    ap.add_argument("--ref", default=None, help="Git ref hosting hitofude_player.html (default: origin/main -> main)")
    ap.add_argument("--tol", type=float, default=1e-6, help="Max allowed sample abs diff (default: 1e-6, ~1/30 of 16-bit LSB)")
    args = ap.parse_args()

    py_desc = describe_python_side()
    html, js_desc = load_player_html(args.player_html, args.ref)

    print("=== hitofude Python <-> JS Parity Check ===")
    print(f"  Python side : {py_desc}")
    print(f"  JS side     : {js_desc} ({len(html.encode('utf-8')):,} bytes)")

    print("[1/3] Auditing X sandbox constraints...")
    sb_errs = audit_sandbox_html(html)
    if sb_errs:
        for e in sb_errs:
            print("  FAIL:", e)
        sys.exit(1)
    print("  OK: zero forbidden sandbox APIs or external asset requests.")

    engine_js = extract_engine_js(html)

    jobs = []
    for text in SENTENCES:
        for pk, prm in Y.PRESETS.items():
            jobs.append({"id": f"{pk}:{text[:10]}", "text": text, "prm": {k: prm[k] for k in Y.KNOB_KEYS}, "uta_hz": None, "edge": False})
    jobs.append({
        "id": f"uta:{UTA_CASE[0]}",
        "text": UTA_CASE[0],
        "prm": {k: Y.PRESETS["hitofude"][k] for k in Y.KNOB_KEYS},
        "uta_hz": UTA_CASE[1],
        "edge": False,
    })
    for ed in EDGE_CASES:
        jobs.append({
            "id": f"edge:{repr(ed)}",
            "text": ed,
            "prm": {k: Y.PRESETS["hitofude"][k] for k in Y.KNOB_KEYS},
            "uta_hz": None,
            "edge": True,
        })

    print(f"[2/3] Synthesizing {len(jobs)} cases in Node.js...")
    with tempfile.TemporaryDirectory() as tmp:
        f32_path = os.path.join(tmp, "js_samples.f32")
        meta_path = os.path.join(tmp, "js_meta.json")
        runner_path = os.path.join(tmp, "runner.js")
        jobs_json = json.dumps(jobs, ensure_ascii=False)

        runner_code = f"""
"use strict";
const fs = require("fs");
{engine_js}
const jobs = {jobs_json};
const metas = [];
const chunks = [];
makeHitofude("わたし、にほんご、ちょっとしゃべれます", Object.assign({{}}, PRESETS.toiki, {{ captureSteps: false }}));
const t0 = performance.now();
for (const j of jobs) {{
  const opts = Object.assign({{}}, j.prm, {{
    uta_hz: j.uta_hz,
    pre: j.edge ? 0.0 : 0.6,
    post: j.edge ? 0.0 : 0.1,
    captureSteps: true,
  }});
  const ts = performance.now();
  const res = makeHitofude(j.text, opts);
  const ms = performance.now() - ts;
  const hk = hakaru(res.samples, res.r);
  let stepFinite = true;
  for (const st of (res.steps || [])) {{
    for (let i = 0; i < st.length; i++) {{
      if (!Number.isFinite(st[i])) {{ stepFinite = false; break; }}
    }}
  }}
  metas.push({{ id: j.id, n: res.samples.length, ms, hk, stepFinite }});
  chunks.push(Buffer.from(res.samples.buffer, res.samples.byteOffset, res.samples.byteLength));
}}
const totalMs = performance.now() - t0;
fs.writeFileSync({json.dumps(f32_path)}, Buffer.concat(chunks));
fs.writeFileSync({json.dumps(meta_path)}, JSON.stringify({{ totalMs, metas }}));
"""
        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(runner_code)
        subprocess.check_call(["node", runner_path])

        with open(meta_path, "r", encoding="utf-8") as f:
            js_info = json.load(f)
        with open(f32_path, "rb") as f:
            raw_bytes = f.read()

    print(f"[3/3] Comparing against Python ({py_desc}) across all {len(jobs)} cases...")
    with concurrent.futures.ProcessPoolExecutor() as ex:
        py_results = list(ex.map(_run_py_job, jobs))

    offset = 0
    worst_diff = 0.0
    worst_id = ""
    worst_hk_diff = 0.0
    failures = []

    for j, jm, (s_py, hk_py) in zip(jobs, js_info["metas"], py_results):
        n_py = len(s_py)
        n_js = jm["n"]
        if n_py != n_js:
            failures.append(f"{j['id']}: length mismatch py={n_py} vs js={n_js}")
            offset += n_js * 4
            continue

        s_js = struct.unpack(f"<{n_js}f", raw_bytes[offset : offset + n_js * 4])
        offset += n_js * 4

        if not jm["stepFinite"]:
            failures.append(f"{j['id']}: NaN/Inf detected in JS step buffers")

        max_d = 0.0
        for a, b in zip(s_py, s_js):
            d = abs(a - b)
            if d > max_d:
                max_d = d
        if max_d > worst_diff:
            worst_diff = max_d
            worst_id = j["id"]
        if max_d > args.tol:
            failures.append(f"{j['id']}: max_abs_diff={max_d:.3e} exceeds tol={args.tol:.3e}")

        for k in ("dur_s", "crest_db", "band_1k_2k6_db", "band_2k6_5k6_db", "tani_core_db", "tani_tail_db"):
            hd = abs(hk_py[k] - jm["hk"][k])
            if hd > worst_hk_diff:
                worst_hk_diff = hd
            if hd > 0.15:
                failures.append(f"{j['id']}: hakaru[{k}] py={hk_py[k]} vs js={jm['hk'][k]}")

    print(
        f"  Summary: {len(jobs)}/{len(jobs)} cases | "
        f"worst Float64-vs-Float32 diff = {worst_diff:.3e} ({worst_id or 'exact 0'}) | "
        f"worst hakaru diff = {worst_hk_diff:.2f} dB | "
        f"JS 24-case time = {js_info['totalMs']:.0f} ms"
    )
    if failures:
        for fl in failures:
            print("  FAIL:", fl)
        sys.exit(1)
    print(f"PASS [{py_desc} <-> {js_desc}]")


if __name__ == "__main__":
    main()
