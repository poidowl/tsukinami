#!/usr/bin/env python3
"""tools/itako_asr_loop.py — イタコASRループ実行・採点ドライバ (tsukinami / hitofude)

hitofude.py の式には一切触れず、プリセット数値パラメータだけを動かして ASR のかな誤り率 (CER) を下げる。
- 元の文 (ref) は漢字かな混じりで保持し、ASR出力 (hyp) と同じかな変換・同じ揃え方に通してから CER を採点する。
- hakaru の値が、現行6プリセットの実測値から決めた枠の外に出た組は失格 (disqualified) にする。
- つまみ係 LLM (:8090 Qwen3-14B) に渡す履歴は「最良5件・直近5件・パラメータの範囲」だけとし、
  確認用 (eval) の文・文字起こし・CER は一切見せない。

最初の一歩（ASR 1つ・パラメータ3つ・10回）実行例:
  python3 tools/itako_asr_loop.py \
      --asr http://127.0.0.1:8091/transcribe \
      --llm-url http://127.0.0.1:8090/v1 \
      --knobs hz,fscale,rate \
      --max-iters 10

P の耳評価を JSONL に追記する例:
  python3 tools/itako_asr_loop.py --log out/itako_asr_log.jsonl \
      --rate-iter 3 --p-score 4 --p-note "パ行・カ行が明瞭、吐息も自然"
"""
import argparse
import concurrent.futures
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO_ROOT)

import hitofude as H  # noqa: E402
import kotoba as K    # noqa: E402
import yomu as Y      # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9), name="JST")
FIXED_SEED = 2024

# 動かせるプリセット数値パラメータと許容範囲（範囲外の提案はクランプせず弾く）
PARAM_BOUNDS = {
    "hz":        (120.0, 420.0, 1, "基本ピッチ F0 中央値 (Hz)"),
    "fscale":    (0.82,  1.36,  3, "声道長スケール（F1〜F3 倍率）"),
    "rate":      (0.80,  1.65,  3, "話速スケール（大きいほど1モーラが長い）"),
    "g_vo":      (0.50,  0.965, 3, "有声コムのくびれ深さ G"),
    "tilt_w":    (2.0,   9.0,   0, "高域粗削りの窓幅（整数サンプル）"),
    "sigh":      (0.0,   0.90,  2, "句末息抜き量"),
    "jitter":    (0.0,   0.005, 4, "周期ジッタ"),
    "wander_st": (0.0,   0.45,  3, "ピッチ緩徐漂い幅 (半音)"),
}

# 現行6プリセット (hitofude, toiki, sasayaki, chibi, ossan, robot) の utt_00 実測値から決めた失格枠:
#   utt_00 ("わたし、にほんご、ちょっとしゃべれます", seed=2024) 実測 [min, max]:
#     crest_db        : [15.3 (chibi),   16.8 (ossan)]    -> ±1.5 dB => [13.8, 18.3]
#     band_1k_2k6_db  : [-4.9 (ossan),   +0.4 (chibi)]    -> ±1.5 dB => [-6.4, +1.9]
#     band_2k6_5k6_db : [-8.0 (toiki),   -2.7 (robot)]    -> ±1.5 dB => [-9.5, -1.2]
#     tani_core_db    : [17.0 (ossan),   39.8 (toiki)]    -> ±2.5 dB => [14.5, 42.3]
#     tani_tail_db    : [15.3 (ossan),   39.9 (hitofude)] -> ±2.5 dB => [12.8, 42.4]
HAKARU_MARGINS_DB = {
    "crest_db": 1.5,
    "band_1k_2k6_db": 1.5,
    "band_2k6_5k6_db": 1.5,
    "tani_core_db": 2.5,
    "tani_tail_db": 2.5,
}
DEFAULT_HAKARU_GATE_UTT0 = {
    "crest_db":        (13.8, 18.3),
    "band_1k_2k6_db":  (-6.4,  1.9),
    "band_2k6_5k6_db": (-9.5, -1.2),
    "tani_core_db":    (14.5, 42.3),
    "tani_tail_db":    (12.8, 42.4),
}

# 調整用 8文: ref=漢字かな混じり正解文（ASR出力と同じ変換器でかな化する）、synth=hitofude合成用かな
TUNE_ITEMS = [
    {"ref": "私、日本語、ちょっと喋れます",       "synth": "わたし、にほんご、ちょっとしゃべれます"},
    {"ref": "パピプペポと、バビブベボを比べる",   "synth": "ぱぴぷぺぽと、ばびぶべぼをくらべる"},
    {"ref": "鍵と学校の、切符を探す",             "synth": "かぎとがっこうの、きっぷをさがす"},
    {"ref": "写真の、準備ができました",           "synth": "しゃしんの、じゅんびができました"},
    {"ref": "ラリルレロと、隣の窓を開ける",       "synth": "らりるれろと、となりのまどをあける"},
    {"ref": "冬の、静かな星空を見る",             "synth": "ふゆの、しずかなほしぞらをみる"},
    {"ref": "冷たい、水をコップに入れる",         "synth": "つめたい、みずをコップにいれる"},
    {"ref": "今日も、いいお天気ですね",           "synth": "きょうも、いいおてんきですね"},
]

# 確認用 8文（つまみ係には文・文字起こし・CER を一切見せない）
EVAL_ITEMS = [
    {"ref": "ノンアルコール　ウェットティッシュ", "synth": "ノンアルコール　ウェットティッシュ"},
    {"ref": "ポケットから、ピカピカのコインが出た", "synth": "ぽけっとから、ぴかぴかのコインがでた"},
    {"ref": "図書館で、歴史の本を借りる",         "synth": "としょかんで、れきしのほんをかりる"},
    {"ref": "小さな、茶色いリスが走る",           "synth": "ちいさな、ちゃいろいりすがはしる"},
    {"ref": "風が強くて、帽子が飛びそうだ",       "synth": "かぜがつよくて、ぼうしがとびそうだ"},
    {"ref": "涼しい、朝ご飯に味噌汁を飲む",       "synth": "すずしい、あさごはんにみそしるをのむ"},
    {"ref": "電車の、窓から海が見える",           "synth": "でんしゃの、まどからうみがみえる"},
    {"ref": "新しい、靴を履いて出かける",         "synth": "あたらしい、くつをはいてでかける"},
]

# --allow-no-kakasi / mock テスト時のみ使う最小フォールバック辞書（本番は pykakasi で ref/hyp 両方を同一変換）
FALLBACK_KANJI_LEXICON = [
    ("日本語", "ニホンゴ"), ("私", "ワタシ"), ("喋れ", "シャベレ"), ("喋", "シャベ"),
    ("比べ", "クラベ"), ("鍵", "カギ"), ("学校", "ガッコウ"), ("切符", "キップ"), ("探す", "サガス"),
    ("写真", "シャシン"), ("準備", "ジュンビ"), ("出来", "デキ"),
    ("隣", "トナリ"), ("窓", "マド"), ("開け", "アケ"),
    ("冬", "フユ"), ("静か", "シズカ"), ("星空", "ホシゾラ"), ("見る", "ミル"),
    ("冷たい", "ツメタイ"), ("水", "ミズ"), ("入れ", "イレ"),
    ("今日", "キョウ"), ("良い", "イイ"), ("お天気", "オテンキ"), ("天気", "テンキ"),
    ("図書館", "トショカン"), ("歴史", "レキシ"), ("本", "ホン"), ("借りる", "カリル"),
    ("小さな", "チイサナ"), ("茶色い", "チャイロイ"), ("茶色", "チャイロ"), ("栗鼠", "リス"), ("走る", "ハシル"),
    ("風", "カゼ"), ("強く", "ツヨク"), ("帽子", "ボウシ"), ("飛び", "トビ"),
    ("涼しい", "スズシイ"), ("朝ご飯", "アサゴハン"), ("朝食", "アサゴハン"), ("味噌汁", "ミソシル"), ("飲む", "ノム"),
    ("電車", "デンシャ"), ("海", "ウミ"), ("見える", "ミエル"),
    ("新しい", "アタラシイ"), ("靴", "クツ"), ("履い", "ハイ"), ("出かけ", "デカケ"), ("出た", "デタ"),
]

_KAKASI = None
_KAKASI_CHECKED = False


def _get_kakasi():
    global _KAKASI, _KAKASI_CHECKED
    if not _KAKASI_CHECKED:
        _KAKASI_CHECKED = True
        try:
            import pykakasi  # type: ignore
            _KAKASI = pykakasi.kakasi()
        except ImportError:
            _KAKASI = None
    return _KAKASI


A_HEADS = set("アカサタナハマヤラワガザダバパァャヮ")
I_HEADS = set("イキシチニヒミリヰギジヂビピィ")
U_HEADS = set("ウクスツヌフムユルグズヅブプゥュ")
E_HEADS = set("エケセテネヘメレヱゲゼデベペェ")
O_HEADS = set("オコソトノホモヨロヲゴゾドボポォョ")
SMALL_KANA = set("ァィゥェォャュョヮ")


def _trailing_vowel(ch):
    if ch in A_HEADS:
        return "a"
    if ch in I_HEADS:
        return "i"
    if ch in U_HEADS:
        return "u"
    if ch in E_HEADS:
        return "e"
    if ch in O_HEADS:
        return "o"
    return None


def normalize_kana_for_cer(text):
    """元の文(ref)とASR出力(hyp)を同じかな変換・同じ揃え方（句読点・空白除去、長音統一）にかける。"""
    s = unicodedata.normalize("NFKC", text or "")
    kk = _get_kakasi()
    if kk is not None:
        s = "".join(item.get("kana", item.get("orig", "")) for item in kk.convert(s))
    else:
        for kj, kn in FALLBACK_KANJI_LEXICON:
            s = s.replace(kj, kn)
    s = K.to_kata(s)
    # カタカナと長音符のみ残す（句読点・空白・記号をすべて除去）
    s = "".join(ch for ch in s if ("ァ" <= ch <= "ヶ") or ch == "ー")
    # 同音かな統一 (ヲ->オ, ヂ->ジ, ヅ->ズ, ヴ->ブ)
    s = s.replace("ヲ", "オ").replace("ヂ", "ジ").replace("ヅ", "ズ").replace("ヴ", "ブ")
    # 長音統一: 単独の母音連続 (オ段+ウ/オ, ウ段+ウ, ア段+ア, エ段+エ) を「ー」に揃え、連続「ーー」を1つに畳む
    # ※ 次文字が小書き母音/拗音 (ウェ, ウィ 等) の場合は子音グライドなので長音化しない
    out = []
    prev_v = None
    n = len(s)
    for idx, ch in enumerate(s):
        nxt = s[idx + 1] if idx + 1 < n else ""
        is_standalone_vowel = nxt not in SMALL_KANA
        if ch == "ー":
            if out and out[-1] != "ー":
                out.append("ー")
            continue
        if is_standalone_vowel and (
            (ch == "ウ" and prev_v in ("o", "u"))
            or (ch == "オ" and prev_v == "o")
            or (ch == "ア" and prev_v == "a")
            or (ch == "エ" and prev_v == "e")
        ):
            if out and out[-1] != "ー":
                out.append("ー")
            continue
        out.append(ch)
        prev_v = _trailing_vowel(ch)
    return "".join(out)


def levenshtein_distance(a, b):
    """純Python動的計画法による編集距離 (置換 + 削除 + 挿入)。"""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


def compute_cer(ref_texts, hyp_texts):
    """元の文(ref)とASR出力(hyp)の両方を normalize_kana_for_cer に通してから CER = sum(edits)/sum(len) を計算する。"""
    total_edits = 0
    total_chars = 0
    per_item = []
    for ref, hyp in zip(ref_texts, hyp_texts):
        rn = normalize_kana_for_cer(ref)
        hn = normalize_kana_for_cer(hyp)
        ed = levenshtein_distance(rn, hn)
        total_edits += ed
        total_chars += len(rn)
        per_item.append({
            "ref_raw": ref,
            "ref_kana": rn,
            "hyp_raw": hyp,
            "hyp_kana": hn,
            "edits": ed,
            "cer": round(ed / max(1, len(rn)), 4),
        })
    overall = total_edits / max(1, total_chars)
    return round(overall, 4), per_item


def measure_hakaru_gate_from_presets(ref_synth_text):
    """現行 Y.PRESETS 全6種の hakaru 実測値 [min, max] に HAKARU_MARGINS_DB を足して失格枠を算出する。"""
    per_preset = {}
    for pk, prm in Y.PRESETS.items():
        p_copy = {k: prm[k] for k in Y.KNOB_KEYS}
        p_copy["seed"] = FIXED_SEED
        r_info = {}
        sig, _ = Y.synth(ref_synth_text, p_copy, out_r=r_info)
        per_preset[pk] = H.hakaru(sig, r_info)
    gate = {}
    for metric, margin in HAKARU_MARGINS_DB.items():
        vals = [hk[metric] for hk in per_preset.values()]
        gate[metric] = (round(min(vals) - margin, 1), round(max(vals) + margin, 1))
    return gate, per_preset


def check_hakaru_gate(hk, gate):
    """hakaru 指標が枠外なら違反理由リストを返す（空リストなら合格）。"""
    if not hk:
        return ["hakaru missing"]
    violations = []
    for metric, (lo, hi) in gate.items():
        v = hk.get(metric)
        if v is None or not math.isfinite(v):
            violations.append(f"{metric}=invalid")
        elif v < lo or v > hi:
            violations.append(f"{metric}={v} outside [{lo}, {hi}]")
    return violations


def git_head_info():
    try:
        br = subprocess.check_output(["git", "-C", REPO_ROOT, "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        sha = subprocess.check_output(["git", "-C", REPO_ROOT, "rev-parse", "--short=7", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(
            ["git", "-C", REPO_ROOT, "status", "--porcelain", "--", "hitofude.py", "yomu.py", "kotoba.py", "accent.py"],
            text=True,
        ).strip()
        return f"{br}@{sha}{'+dirty' if dirty else ''}"
    except Exception:
        return "unknown"


# ==============================================================================
# 合成バックエンド（正本 Python または 高速 Node エンジン）
# ==============================================================================
def _synth_one_py(args_tuple):
    idx, text, prm, wav_path, measure_hakaru = args_tuple
    r_info = {} if measure_hakaru else None
    samples, _ = Y.synth(text, prm, out_r=r_info)
    H.write_wav(wav_path, samples)
    hk = H.hakaru(samples, r_info) if measure_hakaru else None
    return idx, hk


def synthesize_utt0_and_hakaru(utt0_synth_text, full_prm, wav0_path, backend="python"):
    """まず utt_00 を1文だけ合成して hakaru を測る（失格組で残り15文＋ASRを回さないため）。"""
    os.makedirs(os.path.dirname(os.path.abspath(wav0_path)), exist_ok=True)
    if backend == "python":
        _, hk0 = _synth_one_py((0, utt0_synth_text, full_prm, wav0_path, True))
        if hk0 and "sha256_16" in hk0:
            hk0 = {k: v for k, v in hk0.items() if k != "sha256_16"}
        return hk0

    if backend == "node":
        hs, wav_paths = synthesize_node_subset([utt0_synth_text], full_prm, [wav0_path], measure_first=True)
        return hs

    raise ValueError(f"Unknown synth backend: {backend}")


def synthesize_node_subset(synth_texts, full_prm, wav_paths, measure_first=False):
    engine_mjs = os.path.join(HERE, "hitofude_engine.mjs")
    if not os.path.exists(engine_mjs):
        raise RuntimeError(f"Missing {engine_mjs}; run with --synth python or restore tools/hitofude_engine.mjs")
    hk_out = wav_paths[0] + "._hk0.json" if measure_first else None
    job_spec = json.dumps(
        {"sentences": synth_texts, "prm": full_prm, "wav_paths": wav_paths, "hk_out": hk_out},
        ensure_ascii=False,
    )
    node_script = f"""
import fs from "fs";
import * as M from {json.dumps(engine_mjs)};
const job = {job_spec};
function pyRound(x) {{
  const f = Math.floor(x), d = x - f;
  if (Math.abs(d - 0.5) < 1e-12) return (Math.abs(f) % 2 === 0) ? f : f + 1;
  return d < 0.5 ? f : f + 1;
}}
function writeWav(filePath, samples) {{
  const n = samples.length;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(M.SR, 24); buf.writeUInt32LE(M.SR * 2, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {{
    const v = pyRound(Math.max(-1.0, Math.min(1.0, samples[i])) * 32767.0);
    buf.writeInt16LE(v, 44 + i * 2);
  }}
  fs.writeFileSync(filePath, buf);
}}
let hk0 = null;
for (let i = 0; i < job.sentences.length; i++) {{
  const res = M.makeHitofude(job.sentences[i], Object.assign({{}}, job.prm, {{ captureSteps: false }}));
  writeWav(job.wav_paths[i], res.samples);
  if (i === 0 && job.hk_out) hk0 = M.hakaru(res.samples, res.r);
}}
if (job.hk_out) fs.writeFileSync(job.hk_out, JSON.stringify(hk0));
"""
    subprocess.check_call(["node", "--input-type=module", "-e", node_script])
    hk0 = None
    if hk_out:
        with open(hk_out, "r", encoding="utf-8") as f:
            hk0 = json.load(f)
        os.remove(hk_out)
    return hk0, wav_paths


def synthesize_remaining(synth_texts, full_prm, wav_paths, backend="python"):
    if not synth_texts:
        return
    if backend == "python":
        tasks = [(i, s, full_prm, wav_paths[i], False) for i, s in enumerate(synth_texts)]
        with concurrent.futures.ProcessPoolExecutor() as ex:
            list(ex.map(_synth_one_py, tasks))
        return
    if backend == "node":
        synthesize_node_subset(synth_texts, full_prm, wav_paths, measure_first=False)
        return
    raise ValueError(f"Unknown synth backend: {backend}")


# ==============================================================================
# ASR クライアント（複数同時接続対応：HTTP サーバー / 直接 MLX / 直接 faster-whisper / ドライラン用 mock）
# ==============================================================================
def build_asr_runner(spec):
    if spec == "mock":
        # 通信なし環境でのハーネス単体テスト用：漢字かな混じり＋句読点付きの疑似認識文字列を返す
        def _mock_run(wav_paths, prm_hint, orig_ref_texts):
            dist = (
                abs(prm_hint.get("hz", 350.0) - 245.0) / 180.0
                + abs(prm_hint.get("fscale", 1.17) - 1.05) / 0.35
                + abs(prm_hint.get("rate", 1.26) - 1.32) / 0.60
            )
            keep_prob = max(0.35, min(0.98, 1.0 - 0.32 * dist))
            outs = []
            for idx, ref_txt in enumerate(orig_ref_texts):
                chars = list(ref_txt)
                for ci in range(len(chars)):
                    if chars[ci] in "、　 ":
                        continue
                    h = ((ci * 37 + idx * 13 + int(prm_hint.get("hz", 350))) % 100) / 100.0
                    if h > keep_prob:
                        chars[ci] = "タ"
                outs.append("".join(chars) + "。")
            return "mock-asr", outs

        return _mock_run

    if spec.startswith("http://") or spec.startswith("https://"):
        def _http_run(wav_paths, _prm_hint, _orig_ref_texts):
            req = urllib.request.Request(
                spec,
                data=json.dumps({"wav_paths": [os.path.abspath(p) for p in wav_paths]}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("name") or spec, data["texts"]

        return _http_run

    if spec.startswith("mlx:"):
        model_id = spec.split(":", 1)[1]
        import mlx_whisper  # type: ignore

        def _mlx_run(wav_paths, _prm_hint, _orig_ref_texts):
            outs = []
            for wp in wav_paths:
                r = mlx_whisper.transcribe(
                    wp, path_or_hf_repo=model_id, language="ja", temperature=0.0, condition_on_previous_text=False
                )
                outs.append((r.get("text") or "").strip())
            return f"mlx:{os.path.basename(model_id)}", outs

        return _mlx_run

    if spec.startswith("faster-whisper:"):
        model_id = spec.split(":", 1)[1]
        from faster_whisper import WhisperModel  # type: ignore

        model = WhisperModel(model_id, device="auto", compute_type="auto")

        def _fw_run(wav_paths, _prm_hint, _orig_ref_texts):
            outs = []
            for wp in wav_paths:
                segs, _ = model.transcribe(wp, language="ja", beam_size=5, temperature=0.0, condition_on_previous_text=False)
                outs.append("".join(s.text for s in segs).strip())
            return f"faster-whisper:{model_id}", outs

        return _fw_run

    raise ValueError(f"Unsupported --asr spec: {spec}")


# ==============================================================================
# つまみ係クライアント（イタコ :8090 Qwen3-14B / OpenAI互換 API）
# ※ 渡す情報は「いちばん良かった5件・直近5件・パラメータの範囲」だけ。
#   確認用 (eval) の情報は引数にすら受け取らない。
# ==============================================================================
def validate_and_round_knob_dict(cand, active_knobs):
    """範囲外の提案は厳格に弾く（クランプでごまかさず (None, 理由) を返す）。"""
    if not isinstance(cand, dict):
        return None, "proposal is not a JSON object"
    cleaned = {}
    for k in active_knobs:
        if k not in cand:
            return None, f"missing required knob '{k}'"
        try:
            v = float(cand[k])
        except (TypeError, ValueError):
            return None, f"non-numeric value for '{k}': {cand[k]!r}"
        if not math.isfinite(v):
            return None, f"non-finite value for '{k}'"
        lo, hi, ndig, _ = PARAM_BOUNDS[k]
        if v < lo or v > hi:
            return None, f"knob '{k}'={v} out of allowed range [{lo}, {hi}]"
        cleaned[k] = int(round(v)) if ndig == 0 else round(v, ndig)
    return cleaned, None


def extract_json_object(raw_text):
    # Qwen3 の <think>...</think> 思考ブロックを除去してから JSON オブジェクトを抽出
    s = re.sub(r"<think>[\s\S]*?</think>", "", raw_text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I).strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        raise ValueError(f"No JSON object found in LLM response: {s[:160]!r}")
    return json.loads(m.group(0))


def detect_llm_model(llm_base_url):
    try:
        req = urllib.request.Request(f"{llm_base_url.rstrip('/')}/models", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data") or []
        if items and items[0].get("id"):
            return items[0]["id"]
    except Exception:
        pass
    return "qwen3-14b"


def build_prompt_history_views(tune_only_history):
    """履歴から「いちばん良かった5件 (best_5)」と「直近5件 (recent_5)」だけを抽出する。"""
    valid = [h for h in tune_only_history if h.get("tune_cer") is not None and not h.get("disqualified")]
    best_sorted = sorted(valid, key=lambda h: (h["tune_cer"], h["iter"]))[:5]
    best_5 = [{"iter": h["iter"], "knobs": h["knobs"], "tune_cer": h["tune_cer"]} for h in best_sorted]

    recent_5 = []
    for h in tune_only_history[-5:]:
        if h.get("disqualified"):
            recent_5.append({
                "iter": h["iter"],
                "knobs": h["knobs"],
                "tune_cer": None,
                "disqualified": h["disqualified"],
            })
        else:
            recent_5.append({
                "iter": h["iter"],
                "knobs": h["knobs"],
                "tune_cer": h["tune_cer"],
            })
    return best_5, recent_5


def propose_from_qwen(llm_base_url, llm_model, active_knobs, tune_only_history, seen_keys):
    """最良5件・直近5件・パラメータ範囲だけを見せて次の組を1つ提案させる。範囲外・重複は弾いて再要求。"""
    valid_entries = [h for h in tune_only_history if h.get("tune_cer") is not None and not h.get("disqualified")]
    anchor = min(valid_entries, key=lambda h: h["tune_cer"]) if valid_entries else tune_only_history[0]

    if llm_base_url == "mock":
        step_idx = len(tune_only_history)
        cand = {}
        deltas = {
            "hz": [-45.0, -30.0, 25.0, -20.0, 15.0],
            "fscale": [-0.08, -0.04, 0.05, -0.02, 0.03],
            "rate": [0.08, -0.06, 0.04, 0.10, -0.04],
        }
        for ki, k in enumerate(active_knobs):
            lo, hi, ndig, _ = PARAM_BOUNDS[k]
            base_v = anchor["knobs"][k]
            d_list = deltas.get(k, [0.02 * (hi - lo), -0.02 * (hi - lo)])
            dv = d_list[(step_idx + ki) % len(d_list)] * (0.85 ** (step_idx // 3))
            nv = min(hi, max(lo, base_v + dv))
            cand[k] = int(round(nv)) if ndig == 0 else round(nv, ndig)
        return cand, []

    bounds_only = {
        k: {"min": PARAM_BOUNDS[k][0], "max": PARAM_BOUNDS[k][1], "desc": PARAM_BOUNDS[k][3]}
        for k in active_knobs
    }
    best_5, recent_5 = build_prompt_history_views(tune_only_history)

    sys_prompt = (
        "あなたは音声合成器 hitofude の音響パラメータ調整係です。/no_think\n"
        "目的は、日本語ASRの文字誤り率 tune_cer（0.0〜1.0、低いほど良い）を最小化することです。\n"
        "disqualified になった組の周辺は避け、指定された [min, max] 範囲内で未試行の組み合わせを JSON オブジェクト1個だけで出力してください。\n"
        "説明文は不要です。出力形式例: "
        + json.dumps({k: anchor["knobs"][k] for k in active_knobs})
    )

    rejections = []
    feedback_msg = ""
    for attempt in range(4):
        user_prompt = (
            f"パラメータの範囲:\n{json.dumps(bounds_only, ensure_ascii=False)}\n\n"
            f"いちばん良かった5件 (tune_cer 昇順):\n{json.dumps(best_5, ensure_ascii=False)}\n\n"
            f"直近5件:\n{json.dumps(recent_5, ensure_ascii=False)}\n"
        )
        if feedback_msg:
            user_prompt += f"\n前回の出力は以下の理由で却下されました。必ず修正してください: {feedback_msg}\n"
        user_prompt += "\n次に試すパラメータの JSON オブジェクトのみを出力してください:"

        payload = {
            "model": llm_model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.35 + 0.15 * attempt,
            "max_tokens": 512,
        }
        req = urllib.request.Request(
            f"{llm_base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            raw_content = body["choices"][0]["message"]["content"]
            parsed = extract_json_object(raw_content)
            cleaned, err = validate_and_round_knob_dict(parsed, active_knobs)
            if err:
                rejections.append(err)
                feedback_msg = err
                continue
            key = json.dumps(cleaned, sort_keys=True)
            if key in seen_keys:
                msg = f"already tested exact same knobs: {cleaned}"
                rejections.append(msg)
                feedback_msg = msg
                continue
            return cleaned, rejections
        except Exception as e:
            err_s = f"parse/API error: {e}"
            rejections.append(err_s)
            feedback_msg = err_s

    # 4回連続で範囲外・重複だった場合のみ、最良点近傍の決定論的微小摂動（範囲内保証）にフォールバック
    fallback = {}
    n_hist = len(tune_only_history)
    for ki, k in enumerate(active_knobs):
        lo, hi, ndig, _ = PARAM_BOUNDS[k]
        span = (hi - lo) * 0.06 * ((-1) ** (n_hist + ki))
        nv = min(hi, max(lo, anchor["knobs"][k] + span))
        fallback[k] = int(round(nv)) if ndig == 0 else round(nv, ndig)
    rejections.append("used bounded perturbation fallback after 4 invalid proposals")
    return fallback, rejections


def append_ear_rating(log_path, target_iter, score, note):
    """P の耳による聴感評価を JSONL に追記する。"""
    if not os.path.exists(log_path):
        raise SystemExit(f"Log file not found: {log_path}")
    rec = {
        "record_type": "p_ear_eval",
        "target_iter": target_iter,
        "timestamp_jst": datetime.datetime.now(JST).isoformat(timespec="seconds"),
        "p_score": score,
        "p_note": note,
        "git_commit": git_head_info(),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[p_eval] Appended ear rating for iter={target_iter} to {log_path}")


def main():
    ap = argparse.ArgumentParser(description="Itako ASR closed-loop parameter tuner for tsukinami/hitofude")
    ap.add_argument(
        "--asr",
        action="append",
        default=[],
        help="ASR endpoint/spec (repeatable for 2+ ASRs: e.g. http://127.0.0.1:8091/transcribe, mlx:..., mock)",
    )
    ap.add_argument("--llm-url", default="http://127.0.0.1:8090/v1", help="Qwen3-14B OpenAI-compatible base URL (or 'mock')")
    ap.add_argument("--llm-model", default="auto", help="Model name for /v1/chat/completions (default: auto-detect)")
    ap.add_argument("--preset", choices=tuple(Y.PRESETS.keys()), default="hitofude", help="Starting preset baseline")
    ap.add_argument("--knobs", default="hz,fscale,rate", help="Comma-separated tunable knob names (default: hz,fscale,rate)")
    ap.add_argument("--max-iters", type=int, default=10, help="Total iterations including iter 0 baseline (default: 10)")
    ap.add_argument("--synth", choices=("python", "node"), default="python", help="Synthesis engine (default: canonical python)")
    ap.add_argument("--skip-parity-check", action="store_true", help="Skip check_js_parity.py when --synth node is used")
    ap.add_argument("--remeasure-hakaru-gate", action="store_true", help="Recompute hakaru gate from current Y.PRESETS at startup")
    ap.add_argument("--allow-no-kakasi", action="store_true", help="Allow fallback lexicon when pykakasi is not installed")
    ap.add_argument("--log", default=os.path.join(REPO_ROOT, "out", "itako_asr_log.jsonl"), help="Output JSONL path")
    ap.add_argument("--wav-archive", default=os.path.join(REPO_ROOT, "out", "itako_wavs"), help="Directory to keep baseline & best WAVs for P's ear")
    ap.add_argument("--overfit-patience", type=int, default=3, help="Stop if tune improves over baseline while eval worsens N times")
    ap.add_argument("--overfit-margin", type=float, default=0.02, help="Eval CER worsening margin above best seen eval CER")

    # P の耳評価追記モード
    ap.add_argument("--rate-iter", type=int, default=None, help="Append P's ear evaluation for a finished iteration")
    ap.add_argument("--p-score", type=float, default=None, help="P's subjective ear score (e.g. 1..5)")
    ap.add_argument("--p-note", default="", help="P's listening note")
    args = ap.parse_args()

    if args.rate_iter is not None:
        append_ear_rating(args.log, args.rate_iter, args.p_score, args.p_note)
        return

    active_knobs = [k.strip() for k in args.knobs.split(",") if k.strip()]
    for k in active_knobs:
        if k not in PARAM_BOUNDS:
            raise SystemExit(f"Unknown knob '{k}'. Allowed: {', '.join(PARAM_BOUNDS.keys())}")

    asr_specs = args.asr or ["http://127.0.0.1:8091/transcribe"]
    if _get_kakasi() is None and asr_specs != ["mock"] and not args.allow_no_kakasi:
        raise SystemExit(
            "ERROR: 'pykakasi' is required so ASR output and Kanji-kana reference sentences share the exact same "
            "Kanji->Kana converter.\nInstall on Itako with: pip install pykakasi  (or pass --allow-no-kakasi for offline tests)"
        )

    if args.synth == "node" and not args.skip_parity_check:
        engine_mjs = os.path.join(HERE, "hitofude_engine.mjs")
        print("[parity] Verifying tools/hitofude_engine.mjs against hitofude.py via tools/check_js_parity.py ...", flush=True)
        subprocess.check_call([sys.executable, os.path.join(HERE, "check_js_parity.py"), engine_mjs])

    if args.remeasure_hakaru_gate:
        hakaru_gate, _ = measure_hakaru_gate_from_presets(TUNE_ITEMS[0]["synth"])
    else:
        hakaru_gate = dict(DEFAULT_HAKARU_GATE_UTT0)

    asr_runners = [build_asr_runner(sp) for sp in asr_specs]
    llm_model = args.llm_model
    if args.llm_url != "mock" and llm_model == "auto":
        llm_model = detect_llm_model(args.llm_url)

    os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
    os.makedirs(args.wav_archive, exist_ok=True)

    base_prm = {k: Y.PRESETS[args.preset][k] for k in Y.KNOB_KEYS}
    base_prm["seed"] = FIXED_SEED

    tune_refs = [it["ref"] for it in TUNE_ITEMS]
    eval_refs = [it["ref"] for it in EVAL_ITEMS]
    all_synths = [it["synth"] for it in TUNE_ITEMS] + [it["synth"] for it in EVAL_ITEMS]
    n_tune = len(TUNE_ITEMS)

    tune_only_history = []
    seen_keys = set()

    best_tune_cer = float("inf")
    min_eval_cer = float("inf")
    baseline_tune_cer = None
    overfit_streak = 0
    git_commit = git_head_info()

    print(
        f"=== Itako ASR Loop | git={git_commit} | synth={args.synth} | "
        f"knobs={active_knobs} | iters={args.max_iters} | asrs={len(asr_runners)} ===",
        flush=True,
    )

    cur_knobs = {k: base_prm[k] for k in active_knobs}
    rejections = []

    for it in range(args.max_iters):
        if it > 0:
            cur_knobs, rejections = propose_from_qwen(
                args.llm_url, llm_model, active_knobs, tune_only_history, seen_keys
            )

        seen_keys.add(json.dumps(cur_knobs, sort_keys=True))
        full_prm = dict(base_prm, **cur_knobs, seed=FIXED_SEED)

        with tempfile.TemporaryDirectory() as tmp_wav_dir:
            wav_paths = [os.path.join(tmp_wav_dir, f"utt_{i:02d}.wav") for i in range(len(all_synths))]
            hk0 = synthesize_utt0_and_hakaru(all_synths[0], full_prm, wav_paths[0], backend=args.synth)
            hk_violations = check_hakaru_gate(hk0, hakaru_gate)

            if hk_violations:
                disq_reason = "; ".join(hk_violations)
                stop_reason = "max_iters_reached" if (it + 1 == args.max_iters) else None
                record = {
                    "iter": it,
                    "timestamp_jst": datetime.datetime.now(JST).isoformat(timespec="seconds"),
                    "params": full_prm,
                    "active_knobs": cur_knobs,
                    "rejected_proposals": rejections,
                    "disqualified": True,
                    "disqualify_reason": disq_reason,
                    "tune_cer": None,
                    "eval_cer": None,
                    "tune_cer_by_asr": None,
                    "eval_cer_by_asr": None,
                    "hakaru": hk0,
                    "git_commit": git_commit,
                    "wav_dir": None,
                    "p_eval": None,
                    "stop_reason": stop_reason,
                    "transcriptions": None,
                }
                with open(args.log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"  [iter {it:02d}] knobs={cur_knobs} -> DISQUALIFIED ({disq_reason})", flush=True)
                tune_only_history.append({
                    "iter": it,
                    "knobs": cur_knobs,
                    "tune_cer": None,
                    "disqualified": disq_reason,
                })
                continue

            synthesize_remaining(all_synths[1:], full_prm, wav_paths[1:], backend=args.synth)
            tune_wavs = wav_paths[:n_tune]
            eval_wavs = wav_paths[n_tune:]

            tune_cer_by_asr = {}
            eval_cer_by_asr = {}
            transcriptions = {"tune": {}, "eval": {}}

            for runner in asr_runners:
                asr_name, tune_hyps = runner(tune_wavs, full_prm, tune_refs)
                _, eval_hyps = runner(eval_wavs, full_prm, eval_refs)

                t_cer, t_items = compute_cer(tune_refs, tune_hyps)
                e_cer, e_items = compute_cer(eval_refs, eval_hyps)

                tune_cer_by_asr[asr_name] = t_cer
                eval_cer_by_asr[asr_name] = e_cer
                transcriptions["tune"][asr_name] = [
                    {"ref": it_d["ref_raw"], "ref_kana": it_d["ref_kana"], "hyp": it_d["hyp_raw"], "hyp_kana": it_d["hyp_kana"], "cer": it_d["cer"]}
                    for it_d in t_items
                ]
                transcriptions["eval"][asr_name] = [
                    {"ref": it_d["ref_raw"], "ref_kana": it_d["ref_kana"], "hyp": it_d["hyp_raw"], "hyp_kana": it_d["hyp_kana"], "cer": it_d["cer"]}
                    for it_d in e_items
                ]

            mean_tune_cer = round(sum(tune_cer_by_asr.values()) / len(tune_cer_by_asr), 4)
            mean_eval_cer = round(sum(eval_cer_by_asr.values()) / len(eval_cer_by_asr), 4)

            if it == 0:
                baseline_tune_cer = mean_tune_cer

            # ベースラインおよび最良更新時の WAV を保存（P が耳で聴けるように残す）
            saved_wav_dir = None
            is_new_best = mean_tune_cer < best_tune_cer
            if it == 0 or is_new_best:
                tag = "baseline" if it == 0 else "best"
                saved_wav_dir = os.path.join(args.wav_archive, f"iter_{it:03d}_{tag}")
                if os.path.exists(saved_wav_dir):
                    shutil.rmtree(saved_wav_dir)
                shutil.copytree(tmp_wav_dir, saved_wav_dir)

        if is_new_best:
            best_tune_cer = mean_tune_cer
        if mean_eval_cer < min_eval_cer:
            min_eval_cer = mean_eval_cer

        # 過適合監視：調整用がベースラインより改善しているのに、確認用が最良確認用より悪化し続けたら停止
        if it > 0 and baseline_tune_cer is not None and mean_tune_cer < baseline_tune_cer:
            if mean_eval_cer > min_eval_cer + args.overfit_margin:
                overfit_streak += 1
            else:
                overfit_streak = 0
        else:
            overfit_streak = 0

        stop_reason = None
        if overfit_streak >= args.overfit_patience:
            stop_reason = f"overfit_detected(eval_cer={mean_eval_cer:.4f} > min_eval={min_eval_cer:.4f}+{args.overfit_margin})"
        elif it + 1 == args.max_iters:
            stop_reason = "max_iters_reached"

        record = {
            "iter": it,
            "timestamp_jst": datetime.datetime.now(JST).isoformat(timespec="seconds"),
            "params": full_prm,
            "active_knobs": cur_knobs,
            "rejected_proposals": rejections,
            "disqualified": False,
            "disqualify_reason": None,
            "tune_cer": mean_tune_cer,
            "eval_cer": mean_eval_cer,
            "tune_cer_by_asr": tune_cer_by_asr,
            "eval_cer_by_asr": eval_cer_by_asr,
            "hakaru": hk0,
            "git_commit": git_commit,
            "wav_dir": os.path.relpath(saved_wav_dir, REPO_ROOT) if saved_wav_dir else None,
            "p_eval": None,
            "stop_reason": stop_reason,
            "transcriptions": transcriptions,
        }
        with open(args.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(
            f"  [iter {it:02d}] knobs={cur_knobs} -> tune_cer={mean_tune_cer:.4f} | "
            f"eval_cer={mean_eval_cer:.4f} {'★BEST' if is_new_best else ''}",
            flush=True,
        )

        # つまみ係に渡す履歴元データ（eval 側の情報は一切入れない）
        tune_only_history.append({
            "iter": it,
            "knobs": cur_knobs,
            "tune_cer": mean_tune_cer,
            "disqualified": None,
        })

        if stop_reason and stop_reason.startswith("overfit_detected"):
            print(f"[STOP] Early stopping due to overfitting: {stop_reason}", flush=True)
            break

    valid_done = [h for h in tune_only_history if h.get("tune_cer") is not None]
    if valid_done:
        best_entry = min(valid_done, key=lambda h: h["tune_cer"])
        print(
            f"=== Done | best iter={best_entry['iter']} | best tune_cer={best_entry['tune_cer']:.4f} | "
            f"best knobs={best_entry['knobs']} | log={os.path.relpath(args.log, REPO_ROOT)} ===",
            flush=True,
        )
    else:
        print(f"=== Done | all iterations disqualified | log={os.path.relpath(args.log, REPO_ROOT)} ===", flush=True)


if __name__ == "__main__":
    main()
