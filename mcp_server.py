#!/usr/bin/env python3
"""mcp_server.py — 月並みTTS (tsukinami) 標準ライブラリのみ・ゼロ依存 MCP (Model Context Protocol) サーバー。

Claude Desktop / Cursor / Antigravity 等の MCP クライアントに登録すると、
LLM がチャットから直接 `tsukinami_speak` を呼び出して WAV 生成・スピーカー再生・1クリック共有URL生成を行えます。

設定例 (claude_desktop_config.json 等):
{
  "mcpServers": {
    "tsukinami": {
      "command": "python3",
      "args": ["/path/to/tsukinami/mcp_server.py"]
    }
  }
}
"""
import os
import sys
import json
import shutil
import urllib.parse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import yomu
import carve as C


def play_wav_locally(wav_path):
    """OS標準のオーディオプレイヤーがあれば非同期でスピーカー再生する。"""
    if sys.platform == "darwin" and shutil.which("afplay"):
        subprocess.Popen(["afplay", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "afplay"
    if sys.platform.startswith("linux"):
        for cmd in (["aplay", "-q"], ["paplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd + [wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return cmd[0]
    if sys.platform == "win32":
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", f"(New-Object Media.SoundPlayer '{wav_path}').PlaySync()"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return "SoundPlayer"
    return None


def build_share_url(text, preset, prm):
    base_prm = yomu.PRESETS["default"]
    qp = {}
    if preset and preset != "default":
        qp["preset"] = preset
    for k in ("seed", "tsubu", "hz", "fscale", "yure", "shimmer", "tadayoi", "line_g", "ap_n", "rate"):
        if k in prm and abs(float(prm[k]) - float(base_prm[k])) > 1e-6:
            qp[k] = prm[k]
    if text:
        qp["text"] = text
    qstr = urllib.parse.urlencode(qp)
    return f"https://poidowl.github.io/tsukinami/toybox.html?{qstr}" if qstr else "https://poidowl.github.io/tsukinami/toybox.html"


TOOLS = [
    {
        "name": "tsukinami_speak",
        "description": "月並みTTS (carve.py) で日本語かな・カナテキストから音声(WAV)を合成し、ローカル再生と1クリック試聴URL・JSONレシピを返します。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "読み上げる日本語かな・カナ（例：わたし、にほんご、ちょっとしゃべれます）"},
                "preset": {"type": "string", "enum": list(yomu.PRESETS.keys()), "default": "default"},
                "seed": {"type": "integer", "description": "固定乱数粒（芋判）のシード（標準 2024）"},
                "tsubu": {"type": "integer", "description": "乱数粒のサンプル長（標準 40）"},
                "hz": {"type": "number", "description": "基本ピッチ Hz（標準 200.0、男声 125、子供・美少女 280〜310）"},
                "fscale": {"type": "number", "description": "声道フォルマント倍率（標準 1.0、太い声 0.82、可愛い声 1.18〜1.24）"},
                "yure": {"type": "number", "description": "周期ジッタ（標準 0.003、ロボ声 0.0）"},
                "shimmer": {"type": "number", "description": "振幅シマー（標準 0.05）"},
                "tadayoi": {"type": "number", "description": "ピッチの漂い（標準 0.02）"},
                "line_g": {"type": "number", "description": "N=6コムフィルタ強度（標準 0.5）"},
                "ap_n": {"type": "integer", "description": "オールパス段数（標準 40）"},
                "rate": {"type": "number", "description": "話速スケール（標準 1.30）"},
                "play_audio": {"type": "boolean", "default": True, "description": "合成後にPCのスピーカーで再生するか"},
            },
            "required": ["text"],
        },
    }
]


def handle_call_tool(params):
    name = params.get("name")
    args = params.get("arguments") or {}
    if name != "tsukinami_speak":
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    text = args.get("text", "わたし、にほんご、ちょっとしゃべれます")
    preset = args.get("preset", "default")
    prm = dict(yomu.PRESETS.get(preset, yomu.PRESETS["default"]))
    for k in ("seed", "tsubu", "hz", "fscale", "yure", "shimmer", "tadayoi", "line_g", "ap_n", "rate"):
        if k in args and args[k] is not None:
            prm[k] = int(args[k]) if k in ("seed", "tsubu", "ap_n") else float(args[k])

    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)
    out_wav = os.path.join(out_dir, "mcp_out.wav")
    rc = yomu.build_carve_rc(text, prm)
    samples, moras = C.make(rc)
    C.write(out_wav, samples)
    dur = len(samples) / C.SR

    player = play_wav_locally(out_wav) if args.get("play_audio", True) else None
    share_url = build_share_url(text, preset, prm)
    recipe_json = json.dumps({"name": preset, "engine": "tsukinami-carve-E79", "text": text, "params": prm}, ensure_ascii=False)

    msg = (
        f"✅ 合成完了: {out_wav} ({dur:.2f}秒)\n"
        f"🔊 ローカル再生: {player or 'スキップ（またはブラウザURLから再生可能）'}\n"
        f"🔗 1クリック試聴URL: {share_url}\n"
        f"🧪 レシピJSON: {recipe_json}"
    )
    return {"content": [{"type": "text", "text": msg}]}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        req_id = req.get("id")
        if method == "initialize":
            res = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tsukinami-tts", "version": "1.0.0"},
            }
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            res = handle_call_tool(req.get("params") or {})
        elif req_id is None:
            continue
        else:
            res = {}
        if req_id is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": res}, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
