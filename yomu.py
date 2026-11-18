#!/usr/bin/env python3
"""yomu.py — 一筆彫りTTS (tsukinami / hitofude branch) 実行・改造・自己計測ドライバ（標準ライブラリのみ）

使い方:
  python3 yomu.py "わたし、にほんご、ちょっとしゃべれます"
  python3 yomu.py --preset toiki --measure "わたし、にほんご、ちょっとしゃべれます"
  python3 yomu.py --preset sasayaki --compare "ないしょの、おはなしですよ"
  python3 yomu.py --uta 294,330,349,392,440,392,330,294 --measure "ワタシノナマエハ"
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import accent as A
import hitofude as H

PRESETS = {
    "hitofude": {
        "description": "澄み（標準：1本のホワイトノイズから4手で彫る透明女声）",
        "seed": 2024, "hz": 350.0, "fscale": 1.17, "rate": 1.26,
        "g_vo": 0.92, "tilt_w": 5, "sigh": 0.0, "jitter": 0.0013, "wander_st": 0.18,
    },
    "toiki": {
        "description": "吐息（句末でくびれGを緩め、声が同じ1本のノイズ線の吐息へほどけて戻る女声）",
        "seed": 2024, "hz": 312.0, "fscale": 1.15, "rate": 1.30,
        "g_vo": 0.895, "tilt_w": 6, "sigh": 0.78, "jitter": 0.0013, "wander_st": 0.18,
    },
    "sasayaki": {
        "description": "半有声囁き（浅いくびれG=0.58で倍音の谷に元のノイズの風を残す耳元ささやき）",
        "seed": 2024, "hz": 305.0, "fscale": 1.15, "rate": 1.30,
        "g_vo": 0.58, "tilt_w": 6, "sigh": 0.85, "jitter": 0.0018, "wander_st": 0.15,
    },
    "chibi": {
        "description": "ちびっ子（短い声道 fscale=1.32・高ピッチ 400Hz・明るい粗削り tilt_w=4）",
        "seed": 2024, "hz": 400.0, "fscale": 1.32, "rate": 1.20,
        "g_vo": 0.92, "tilt_w": 4, "sigh": 0.0, "jitter": 0.0015, "wander_st": 0.22,
    },
    "ossan": {
        "description": "おっさん（長い声道 fscale=0.88・低音 148Hz）",
        "seed": 2024, "hz": 148.0, "fscale": 0.88, "rate": 1.22,
        "g_vo": 0.93, "tilt_w": 5, "sigh": 0.0, "jitter": 0.0016, "wander_st": 0.14,
    },
    "robot": {
        "description": "冷凍ロボット（周期ジッタ0・漂い0・強いくびれG=0.96）",
        "seed": 2024, "hz": 220.0, "fscale": 1.06, "rate": 1.15,
        "g_vo": 0.96, "tilt_w": 4, "sigh": 0.0, "jitter": 0.0, "wander_st": 0.0,
    },
}

KNOB_KEYS = ("seed", "hz", "fscale", "rate", "g_vo", "tilt_w", "sigh", "jitter", "wander_st")


def synth(text, prm, uta_hz=None, out_r=None):
    # 手動韻律記号: "'" 核, "0" 平板, "/" または半角空白 " " = 句切れ(無音なし), "、" または全角空白 "　" = ポーズ(無音あり), "?" 疑問上昇
    has_marks = any(ch in text for ch in ("'", "’", "0", "/", "|", " ", "　", "?", "？"))
    if has_marks and not uta_hz:
        clean_kana, phrases = A.annotate(text)
        accent_kw = dict(phrases=phrases, question=text.strip().endswith(("?", "？")))
        target_text = clean_kana
    else:
        accent_kw = None
        target_text = text
    return H.make_hitofude(
        target_text,
        seed=int(prm["seed"]),
        hz=float(prm["hz"]),
        fscale=float(prm["fscale"]),
        rate=float(prm["rate"]),
        g_vo=float(prm["g_vo"]),
        tilt_w=int(prm["tilt_w"]),
        sigh=float(prm["sigh"]),
        jitter=float(prm["jitter"]),
        wander_st=float(prm["wander_st"]),
        uta_hz=uta_hz,
        accent_kw=accent_kw,
        out_r=out_r,
    )


def _env_db_curve(sig, bins=160):
    n = len(sig)
    if n == 0:
        return [-90.0] * bins
    win = max(1, int(0.020 * H.SR))
    out = []
    for b in range(bins):
        c = int((b + 0.5) / bins * n)
        i0 = max(0, min(max(0, n - win), c - win // 2))
        seg = sig[i0 : i0 + win]
        p = sum(v * v for v in seg) / max(1, len(seg))
        out.append(10.0 * math.log10(p + 1e-9))
    return out


def compare_acoustic(base_sig, base_r, test_sig, test_r):
    """位相非同期・話速差があっても破綻しない比較：正規化時間包絡の相関・dB差 ＋ hakaru 指標差分。"""
    ea, eb = _env_db_curve(base_sig), _env_db_curve(test_sig)
    ma, mb = sum(ea) / len(ea), sum(eb) / len(eb)
    num = sum((a - ma) * (b - mb) for a, b in zip(ea, eb))
    da = math.sqrt(sum((a - ma) ** 2 for a in ea)) or 1e-12
    db = math.sqrt(sum((b - mb) ** 2 for b in eb)) or 1e-12
    act = [(a - b) ** 2 for a, b in zip(ea, eb) if a > -50.0 or b > -50.0]
    env_diff = math.sqrt(sum(act) / len(act)) if act else 0.0
    mb_m = H.hakaru(base_sig, base_r)
    mt_m = H.hakaru(test_sig, test_r)
    return {
        "env_r": round(num / (da * db), 3),
        "env_diff_db": round(env_diff, 2),
        "d_dur_s": round(mt_m["dur_s"] - mb_m["dur_s"], 2),
        "d_band_1k_2k6_db": round(mt_m["band_1k_2k6_db"] - mb_m["band_1k_2k6_db"], 1),
        "d_band_2k6_5k6_db": round(mt_m["band_2k6_5k6_db"] - mb_m["band_2k6_5k6_db"], 1),
        "d_tani_core_db": round(mt_m["tani_core_db"] - mb_m["tani_core_db"], 1),
        "d_tani_tail_db": round(mt_m["tani_tail_db"] - mb_m["tani_tail_db"], 1),
    }


def _resolve_out_path(args_out, n_texts, idx, out_dir, preset):
    if args_out:
        if n_texts == 1:
            return args_out
        stem, ext = os.path.splitext(args_out)
        return f"{stem}_{idx + 1}{ext or '.wav'}"
    seq = 1
    while True:
        cand = os.path.join(out_dir, f"yomu_{seq:03d}_{preset}.wav")
        if not os.path.exists(cand):
            return cand
        seq += 1


def main():
    p = argparse.ArgumentParser(description="一筆彫りTTS (hitofude) — 1本のホワイトノイズから4手で彫る日本語音声合成")
    p.add_argument("texts", nargs="*", default=["わたし、にほんご、ちょっとしゃべれます"])
    p.add_argument("-o", "--out", default=None, help="出力WAVパス（複数テキスト時は _1, _2 連番、省略時は out/yomu_NNN_<preset>.wav）")
    p.add_argument("--preset", choices=list(PRESETS.keys()), default="hitofude", help="プリセット名")
    p.add_argument("--list-presets", action="store_true", help="プリセット一覧を表示して終了")
    p.add_argument("--measure", action="store_true", help="合成波形の実測音響指標JSONを表示（LLM自己検証用・標準ライブラリのみ）")
    p.add_argument("--compare", action="store_true", help="基準プリセット (hitofude) との音響指標・包絡差分JSONを同時出力")
    p.add_argument("--uta", default=None, help="歌モード：カンマ区切り周波数Hz列（例: 294,330,349,392）")
    p.add_argument("--recipe", default=None, help="レシピJSONを読み込む")
    p.add_argument("--save-recipe", default=None, help="現在のパラメータをレシピJSONへ保存")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--hz", type=float, default=None)
    p.add_argument("--fscale", type=float, default=None)
    p.add_argument("--rate", type=float, default=None)
    p.add_argument("--g-vo", dest="g_vo", type=float, default=None)
    p.add_argument("--tilt", dest="tilt_w", type=int, default=None)
    p.add_argument("--sigh", type=float, default=None)
    p.add_argument("--jitter", type=float, default=None)
    p.add_argument("--wander", dest="wander_st", type=float, default=None)
    args = p.parse_args()

    if args.list_presets:
        for k, v in PRESETS.items():
            knobs = ", ".join(f"{ pk }={ pv }" for pk, pv in v.items() if pk != "description")
            print(f"  {k:9s} : {v['description']}\n              ({knobs})")
        return

    prm = dict(PRESETS[args.preset])
    if args.recipe:
        with open(args.recipe, encoding="utf-8") as f:
            prm.update(json.load(f))
    for k in KNOB_KEYS:
        val = getattr(args, k, None)
        if val is not None:
            prm[k] = val

    if args.save_recipe:
        os.makedirs(os.path.dirname(os.path.abspath(args.save_recipe)), exist_ok=True)
        with open(args.save_recipe, "w", encoding="utf-8") as f:
            json.dump(prm, f, ensure_ascii=False, indent=2)
        print(f"[hitofude] Saved recipe -> {args.save_recipe}")

    uta_hz = [float(v) for v in args.uta.split(",") if v.strip()] if args.uta else None
    out_dir = os.path.join(HERE, "out")
    os.makedirs(out_dir, exist_ok=True)

    for idx, t in enumerate(args.texts):
        r_info = {}
        samples, moras = synth(t, prm, uta_hz=uta_hz, out_r=r_info)
        out_path = _resolve_out_path(args.out, len(args.texts), idx, out_dir, args.preset)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        H.write_wav(out_path, samples)
        m_str = "".join(m.get("t", "") for m in moras)
        print(f"[hitofude] Saved: {out_path} ({len(samples)/H.SR:.2f}s, {len(moras)} moras: {m_str})")
        if args.measure:
            print("  [Measure]", json.dumps(H.hakaru(samples, r_info), ensure_ascii=False))
        if args.compare:
            base_r = {}
            base_samples, _ = synth(t, PRESETS["hitofude"], uta_hz=uta_hz, out_r=base_r)
            stem, ext = os.path.splitext(out_path)
            base_path = f"{stem}_base{ext or '.wav'}"
            H.write_wav(base_path, base_samples)
            cmp_info = dict(base=base_path, **compare_acoustic(base_samples, base_r, samples, r_info))
            print("  [Compare vs hitofude]", json.dumps(cmp_info, ensure_ascii=False))


if __name__ == "__main__":
    main()
