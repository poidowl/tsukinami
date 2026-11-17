#!/usr/bin/env python3
"""
yomu.py — 月並みTTS (tsukinami) 「壊しても戻せる」クロスプラットフォーム実行・改造・比較・共有ドライバ
Play → Modify → Listen → Compare → Share (Windows / macOS / Linux 標準ライブラリのみ)

使い方:
  1) そのまま喋らせる (Play):
     python yomu.py "わたし、にほんご、ちょっとしゃべれます"

  2) 同梱の改造レシピで喋らせる (Preset):
     python yomu.py --preset ossan   "わたし、にほんご、ちょっとしゃべれます"   # 低いおっさん声
     python yomu.py --preset robot   "わたし、にほんご、ちょっとしゃべれます"   # 揺らぎゼロの冷凍ロボ声
     python yomu.py --preset horror  "うしろに、だれか、いますよ"               # ホラーゲームの不気味なNPC
     python yomu.py --preset whisper "ないしょの、おはなしですよ"               # 無声ささやき声

  3) 改造前（基準）と改造後を同時に書き出して比較する (Modify & Compare):
     python yomu.py --preset horror --compare "わたし、にほんご、ちょっとしゃべれます"
     python yomu.py --seed 7 --hz 150 --fscale 0.88 --compare "わたし、にほんご、ちょっとしゃべれます"

  4) 自分（やLLM）が作った改造レシピをJSONで保存・共有・再現する (Share):
     python yomu.py --seed 42 --hz 160 --fscale 0.90 --yure 0.015 --save-recipe my_voice.json "テストです"
     python yomu.py --recipe my_voice.json "わたし、にほんご、ちょっとしゃべれます"
"""
import argparse
import copy
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import accent as A
import carve as C

# 誰でもすぐ遊べる同梱プリセット（「改造の余白」サンプル）
PRESETS = {
    "default": {
        "description": "標準（月並みTTS 第1段デフォルト：明るい高め声）",
        "seed": 2024, "tsubu": 40, "hz": 330.0, "fscale": 1.22,
        "yure": 0.003, "shimmer": 0.05, "tadayoi": 0.5, "line_g": 0.5, "ap_n": 40, "rate": 1.30,
    },
    "ossan": {
        "description": "おっさん声（太い声道 fscale=0.86・低ピッチ 125Hz・大きめの粒 tsubu=64）",
        "seed": 2024, "tsubu": 64, "hz": 125.0, "fscale": 0.86,
        "yure": 0.006, "shimmer": 0.08, "tadayoi": 0.6, "line_g": 0.65, "ap_n": 40, "rate": 1.25,
    },
    "robot": {
        "description": "冷凍ロボット（周期揺らぎ・振幅揺らぎ・漂いすべてゼロ＋強い6本くびれ）",
        "seed": 2024, "tsubu": 32, "hz": 220.0, "fscale": 1.05,
        "yure": 0.0, "shimmer": 0.0, "tadayoi": 0.0, "line_g": 0.85, "ap_n": 0, "rate": 1.15,
    },
    "horror": {
        "description": "ホラーゲームのNPC（不安定な周期揺らぎ yure=0.045・うねり tadayoi=2.2・低い声道）",
        "seed": 13, "tsubu": 52, "hz": 165.0, "fscale": 0.92,
        "yure": 0.045, "shimmer": 0.25, "tadayoi": 2.2, "line_g": 0.75, "ap_n": 60, "rate": 1.55,
    },
    "whisper": {
        "description": "ささやき声（周期の揺らぎを大きく散らし、くびれを切って息成分を強調）",
        "seed": 2024, "tsubu": 24, "hz": 300.0, "fscale": 1.18,
        "yure": 0.35, "shimmer": 0.45, "tadayoi": 0.2, "line_g": 0.0, "ap_n": 40, "rate": 1.35,
    },
    "chibi": {
        "description": "超ちびっ子（短い声道 fscale=1.35・高ピッチ 400Hz・細かい粒 tsubu=32）",
        "seed": 2024, "tsubu": 32, "hz": 400.0, "fscale": 1.35,
        "yure": 0.004, "shimmer": 0.05, "tadayoi": 0.5, "line_g": 0.45, "ap_n": 40, "rate": 1.20,
    },
}


def resolve_params(args):
    prm = dict(PRESETS["default"])
    if args.preset:
        if args.preset not in PRESETS:
            raise SystemExit(f"未知のプリセット '{args.preset}' です。選択可能: {', '.join(PRESETS.keys())}")
        prm.update(PRESETS[args.preset])
    if args.recipe:
        with open(args.recipe, encoding="utf-8") as f:
            user_rc = json.load(f)
        prm.update(user_rc)
    for k in ("seed", "tsubu", "hz", "fscale", "yure", "shimmer", "tadayoi", "line_g", "ap_n", "rate"):
        val = getattr(args, k, None)
        if val is not None:
            prm[k] = val
    return prm


def build_carve_rc(text, prm):
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
    r["kotoba"].pop("hz", None)

    # Apply resolved recipe parameters
    hz = float(prm["hz"])
    r["line.D_center"] = C.E79["line.D_center"] * 436.6 / hz
    r["kotoba"]["fscale"] = float(prm["fscale"])
    r["kotoba"]["params"]["rate"] = float(prm["rate"])
    r["kugiri"] = dict(
        r["kugiri"],
        tsubu=int(prm["tsubu"]),
        yure=float(prm["yure"]),
        shimmer=float(prm["shimmer"]),
    )
    r["tadayoi"] = float(prm["tadayoi"])
    if float(prm["yure"]) == 0.0 and float(prm["tadayoi"]) == 0.0:
        r["yure_hayai"] = 0.0
        r["line"] = dict(r["line"], D_haba=0.0)
    r["kotoba"]["line_g"] = float(prm["line_g"])
    r["kotoba"]["ap_n"] = int(prm["ap_n"])

    has_marks = any(ch in text for ch in ("'", "’", "0", "/", "|", " ", "　", "?", "？"))
    if has_marks:
        clean_kana, phrases = A.annotate(text)
        q_flag = text.strip().endswith(("?", "？"))
        r["kotoba"]["accent_kw"] = dict(r["kotoba"].get("accent_kw") or {}, phrases=phrases, question=q_flag)
        target_text = clean_kana
    else:
        target_text = text

    return C.variant(dict(r, text=target_text, seed=int(prm["seed"])))


def compare_signals(ref, test):
    """Python標準ライブラリのみで波形相関係数 r と短時間フレームRMS差 (dB) を算出"""
    n = min(len(ref), len(test))
    if n == 0:
        return 0.0, 0.0
    ma = sum(ref[:n]) / n
    mb = sum(test[:n]) / n
    num = sum((ref[i] - ma) * (test[i] - mb) for i in range(n))
    da = math.sqrt(sum((ref[i] - ma) ** 2 for i in range(n))) or 1e-12
    db = math.sqrt(sum((test[i] - mb) ** 2 for i in range(n))) or 1e-12
    corr = num / (da * db)

    win = 882  # 20ms @ 44.1kHz
    diffs = []
    for i in range(0, n - win, win // 2):
        pa = sum(v * v for v in ref[i : i + win]) / win
        pb = sum(v * v for v in test[i : i + win]) / win
        if pa > 1e-5 or pb > 1e-5:
            diffs.append((10.0 * math.log10((pa + 1e-9) / (pb + 1e-9))) ** 2)
    env_db = math.sqrt(sum(diffs) / len(diffs)) if diffs else 0.0
    return corr, env_db


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
    p.add_argument(
        "--preset",
        choices=list(PRESETS.keys()),
        default=None,
        help="同梱キャラ声プリセット (default / ossan / robot / horror / whisper / chibi)",
    )
    p.add_argument("--list-presets", action="store_true", help="同梱プリセット一覧とパラメータを表示して終了")
    p.add_argument("--recipe", default=None, help="共有レシピJSONファイルを読み込んで合成")
    p.add_argument("--save-recipe", default=None, help="現在の改造パラメータをレシピJSONファイルに保存")
    p.add_argument("--compare", action="store_true", help="壊す前の基準音声 (out/yomu_base_*.wav) も同時出力して差分を表示")

    p.add_argument("--seed", type=int, default=None, help="[1.原料] 乱数シード（40サンプルgrainの声色DNAを変更, 既定: 2024）")
    p.add_argument("--tsubu", type=int, default=None, help="[1.原料] grainのサンプル長（既定: 40 ≒ 0.91ms）")
    p.add_argument("--hz", type=float, default=None, help="[2.骨格] 基準ピッチ高さ Hz（既定: 330）")
    p.add_argument("--yure", type=float, default=None, help="[2.骨格] 周期配置間隔の揺らぎ率（既定: 0.003）")
    p.add_argument("--shimmer", type=float, default=None, help="[2.骨格] 粒ごとの振幅揺らぎ率（既定: 0.05）")
    p.add_argument("--tadayoi", type=float, default=None, help="[2.骨格] ピッチのゆっくりした漂い（既定: 0.5）")
    p.add_argument("--line-g", dest="line_g", type=float, default=None, help="[3.整形] 音源6本くびれ kubire_n の係数 g（既定: 0.5, 0でOFF）")
    p.add_argument("--fscale", type=float, default=None, help="[4.共鳴] 声道フォルマント倍率（既定: 1.22=子ども声道, 1.0=大人標準, 0.86=おっさん）")
    p.add_argument("--rate", type=float, default=None, help="[4.共鳴] 話す速さの倍率（小さいほど速い、既定: 1.30）")
    p.add_argument("--ap-n", dest="ap_n", type=int, default=None, help="[5.位相] 仕上げの全域通過フィルタ段数（既定: 40, 0でOFF）")
    args = p.parse_args()

    if args.list_presets:
        print("=== 月並みTTS 同梱プリセット一覧 (--preset NAME) ===")
        for k, v in PRESETS.items():
            print(f"  {k:8s} : {v['description']}")
            params_str = ", ".join(f"{pk}={pv}" for pk, pv in v.items() if pk != "description")
            print(f"             ({params_str})")
        return

    prm = resolve_params(args)
    default_prm = PRESETS["default"]
    diff_keys = [
        f"{k}: {default_prm[k]} -> {prm[k]}"
        for k in ("seed", "tsubu", "hz", "fscale", "yure", "shimmer", "tadayoi", "line_g", "ap_n", "rate")
        if prm[k] != default_prm[k]
    ]

    if args.save_recipe:
        os.makedirs(os.path.dirname(os.path.abspath(args.save_recipe)), exist_ok=True)
        with open(args.save_recipe, "w", encoding="utf-8") as f:
            json.dump(prm, f, ensure_ascii=False, indent=2)
        print(f"[tsukinami] Saved shareable recipe JSON -> {args.save_recipe}")

    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)

    for idx, t in enumerate(args.texts):
        rc = build_carve_rc(t, prm)
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
        if diff_keys:
            print(f"  Modified magic numbers: {', '.join(diff_keys)}")

        if args.compare:
            base_rc = build_carve_rc(t, default_prm)
            base_samples, _ = C.make(base_rc)
            base_path = os.path.join(out_dir, f"yomu_base_{idx + 1}.wav")
            C.write(base_path, base_samples)
            corr, env_db = compare_signals(base_samples, samples)
            print(f"  [Compare vs Base] Base WAV: {base_path} | Waveform corr r={corr:+.4f} | Frame envelope diff={env_db:.2f} dB")


if __name__ == "__main__":
    main()
