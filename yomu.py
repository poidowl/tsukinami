#!/usr/bin/env python3
"""
yomu.py — 月並みTTS (tsukinami) クロスプラットフォーム1ファイル実行＆改造ドライバ
Windows / macOS / Linux すべてで Python 3 標準ライブラリだけで動作します。

使い方:
  1) そのまま喋らせる:
     python yomu.py "わたし、にほんご、ちょっとしゃべれます"

  2) アクセント核 (')・平板 (0)・句切れ (空白 or /)・疑問 (?) を指定して喋らせる:
     python yomu.py "わたし0、にほんご0、ちょ'っと しゃべれま'す？" -o out/watashi_q.wav

  3) 5つの設計ブロック（原料・骨格・倍音整形・共鳴・位相分散）をコマンドラインから改造して実験する:
     python yomu.py "わたし、にほんご、ちょっとしゃべれます" --seed 7 --hz 280 --fscale 1.05 --line-g 0.0 --ap-n 0 -o out/hack.wav
"""
import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import accent as A
import carve as C


def build_recipe(text, args):
    # S.txt + OO.txt + mkt.py の第1段標準プリセットを読み込む
    with open(os.path.join(HERE, "S.txt"), encoding="utf-8") as f:
        s_txt = f.read().strip()
    with open(os.path.join(HERE, "OO.txt"), encoding="utf-8") as f:
        oo_txt = f.read().strip()

    base_kt = {
        "bump": [3, 1.4, 1.4],
        "g": [0.7, 0.7, 0.7],
        "floor": 1.0,
        "ap_on": "mix",
        "ap_n": 40,
        "ap_lo": 300,
        "ap_hi": 8000,
        "ap_bw": 150,
        "band": 3.0,
    }
    r103 = {
        "p_low": [5, 4, 3],
        "vfloor": {"a": 0.6, "o": 0.3},
        "f1x_cmute": 1.0,
        "f45": [[1400, 0.75], [2300, 0.3]],
        "vbump": {"a": [1, 1.2, 1], "e": [0.7, 1.3, 0.7], "o": [1, 1, 0.3], "i": [0.7, 0.6, 0.7]},
        "f1x": [[2.0, 0.35], [0.45, 0.25], [2.8, 0.35]],
        "vf1x": {"a": [0.15, 0, 0], "i": [0.3, 0, 0.3], "u": [0.3, 0, 0.3], "e": [0.5, 1, 0], "o": [0.1, 1, 0]},
        "henv": None,
    }
    v0 = '"vbump":{"a":[1,1.2,1],"e":[0.7,1.3,0.7],"o":[1,1.3,0.8],"i":[0.25,3.0,3.0]}'

    kw = dict(r103)
    kw.update({"P.fend_at": 0.15, "P.fric_hold": 20, "P.vl_hold": True, "P.vdl": -2.0, "P.vbg": 1.5})
    kw.update(json.loads("{" + f"{s_txt},{v0},{oo_txt}" + "}"))

    r = copy.deepcopy(C.E79)
    r["line.D_center"] = C.E79["line.D_center"] * 436.6 / 360.0
    K = dict(fscale=1.22)
    K.update(base_kt)
    P = {}
    for k, v in kw.items():
        if k.startswith("line.") or k.startswith("kugiri."):
            r[k] = v
        elif k.startswith("P."):
            P[k[2:]] = v
        elif k.startswith("rc."):
            r[k[3:]] = v
        else:
            K[k] = v

    r["kotoba"] = dict(r["kotoba"], **K)
    r["kotoba"]["params"] = dict(r["kotoba"]["params"], **P)
    r["kotoba"].pop("acc2", None)
    hz = r["kotoba"].pop("hz", 330.0)

    # ---- コマンドライン引数によるハック（5つの設計ブロックを直接上書き） ----
    if args.hz is not None:
        hz = args.hz
    if hz:
        r["line.D_center"] = C.E79["line.D_center"] * 436.6 / float(hz)

    if args.fscale is not None:
        r["kotoba"]["fscale"] = args.fscale
    if args.rate is not None:
        r["kotoba"]["params"]["rate"] = args.rate
    if args.tsubu is not None:
        r["kugiri"] = dict(r["kugiri"], tsubu=args.tsubu)
    if args.yure is not None:
        r["kugiri"] = dict(r["kugiri"], yure=args.yure)
    if args.shimmer is not None:
        r["kugiri"] = dict(r["kugiri"], shimmer=args.shimmer)
    if args.line_g is not None:
        r["kotoba"]["line_g"] = args.line_g
    if args.ap_n is not None:
        r["kotoba"]["ap_n"] = args.ap_n

    # アクセント記号 (' / 0 / 空白 / ?) が含まれている場合は accent.annotate で分解
    has_marks = any(ch in text for ch in ("'", "’", "0", "/", "|", " ", "　", "?", "？"))
    if has_marks:
        clean_kana, phrases = A.annotate(text)
        q_flag = text.strip().endswith(("?", "？"))
        r["kotoba"]["accent_kw"] = dict(r["kotoba"].get("accent_kw") or {}, phrases=phrases, question=q_flag)
        target_text = clean_kana
    else:
        target_text = text

    return C.variant(dict(r, text=target_text, seed=args.seed))


def main():
    p = argparse.ArgumentParser(
        description="日本語かな・カナを読む。その仕組みを、Pythonで読む。 — 月並みTTS (tsukinami)"
    )
    p.add_argument(
        "texts",
        nargs="*",
        default=["わたし、にほんご、ちょっとしゃべれます"],
        help="読み上げるひらがな・カタカナ文（' でアクセント核、0 で平板、空白で句切れ、? で疑問上昇も指定可）",
    )
    p.add_argument("-o", "--out", default=None, help="出力WAVファイルパス（省略時は out/yomu_1.wav ...）")
    p.add_argument("--seed", type=int, default=2024, help="[1.原料] 乱数シード（40サンプルgrainの声色DNAを変更, 既定: 2024）")
    p.add_argument("--tsubu", type=int, default=None, help="[1.原料] grainのサンプル長（既定: 40 ≒ 0.91ms）")
    p.add_argument("--hz", type=float, default=None, help="[2.骨格] 基準ピッチ高さ Hz（既定: 330）")
    p.add_argument("--yure", type=float, default=None, help="[2.骨格] 周期配置間隔の揺らぎ率（既定: 0.003）")
    p.add_argument("--shimmer", type=float, default=None, help="[2.骨格] 粒ごとの振幅揺らぎ率（既定: 0.05）")
    p.add_argument("--line-g", type=float, default=None, help="[3.整形] 音源6本くびれ kubire_n のフィードバック係数 g（既定: 0.5, 0でOFF）")
    p.add_argument("--fscale", type=float, default=None, help="[4.共鳴] 声道フォルマント倍率（既定: 1.22=子ども声道, 1.0=大人標準）")
    p.add_argument("--rate", type=float, default=None, help="[4.共鳴] 話す速さの倍率（小さいほど速い、既定: 1.30）")
    p.add_argument("--ap-n", type=int, default=None, help="[5.位相] 仕上げの全域通過フィルタ段数（既定: 40, 0でOFF）")
    args = p.parse_args()

    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)

    for idx, t in enumerate(args.texts):
        rc = build_recipe(t, args)
        samples, moras = C.make(rc)
        if args.out and len(args.texts) == 1:
            out_path = args.out
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        else:
            out_path = os.path.join(out_dir, f"yomu_{idx + 1}.wav")
        C.write(out_path, samples)
        dur = len(samples) / C.SR
        m_list = [m.get("t", "") for m in (moras["moras"] if isinstance(moras, dict) else moras)]
        print(f"[tsukinami] Saved: {out_path} ({dur:.2f}s, {len(m_list)} moras: {''.join(m_list)})")


if __name__ == "__main__":
    main()
