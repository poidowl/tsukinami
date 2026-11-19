#!/usr/bin/env python3
"""tools/itako_asr_loop.py — イタコASRループ実行・採点ドライバ (tsukinami / hitofude)

hitofude.py の式には一切触れず、プリセット数値パラメータだけを動かして ASR のかな誤り率 (CER) を下げる。
- 元の文 (ref) は漢字かな混じりで保持し、ASR出力 (hyp) と同じかな変換に通してから CER を採点する。
  既定の変換は 关亡婆の ~/kana にある pyopenjtalk（正解も認識結果も同じ道具）。
- hakaru の値が、現行6プリセットの実測値から決めた枠の外に出た組は失格 (disqualified) にする。
- つまみ係 LLM (:8090 Qwen3-30B-A3B、model は必ず default_model) に渡す履歴は
  「最良5件・直近5件・パラメータの範囲」だけとし、確認用 (eval) の文・文字起こし・CER は一切見せない。
- 既定の ASR は、关亡婆で既に動いている 8091 (Qwen3-ASR-1.7B) と 8092 (parakeet-tdt_ctc-0.6b-ja)。
  点は2つの ASR のうち、文ごとに悪いほう（CER が高いほう）を使う。
  tools/itako_asr_server.py を 8091 で立てないこと（既存の Qwen3-ASR と衝突する）。

最初の一歩（関亡婆でループを回す。システムの python3 / git は使わない）:
  python tools/itako_asr_loop.py \
      --llm-url http://127.0.0.1:8090/v1 \
      --llm-model default_model \
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
sys.path.insert(0, HERE)

import itako_asr_lib as asrlib  # noqa: E402

import hitofude as H  # noqa: E402
import kotoba as K    # noqa: E402
import yomu as Y      # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9), name="JST")
FIXED_SEED = 2024

# 動かせるプリセット数値パラメータと許容範囲（範囲外の提案は端に丸める）
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

# --kana-backend pykakasi|fallback / mock テスト時の辞書（既定の本番は pyopenjtalk で ref/hyp 両方を同一変換）
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


def make_kana_normalizer(backend, openjtalk_python=None, allow_fallback=False):
    """Build the symmetric kana converter used for both ref and hyp."""
    if backend == "openjtalk":
        python_bin = openjtalk_python or asrlib.DEFAULT_OPENJTALK_PYTHON
        if not allow_fallback and not os.path.isfile(python_bin):
            raise SystemExit(
                f"ERROR: pyopenjtalk runner not found: {python_bin}\n"
                "かなCERは関亡婆の ~/kana/bin/python の pyopenjtalk で、正解も認識結果も同じ変換に通す。"
                "パスを --openjtalk-python で渡すか、テストなら --kana-backend fallback を使う。"
            )
        if not os.path.isfile(python_bin):
            backend = "fallback"
    if backend == "pykakasi":
        kk = _get_kakasi()
        if kk is None and not allow_fallback:
            raise SystemExit(
                "ERROR: --kana-backend pykakasi なのに pykakasi が入っていない。"
                " 既定は pyopenjtalk。テストなら --kana-backend fallback を使う。"
            )
        if kk is None:
            backend = "fallback"
            kk = None
        return asrlib.KanaNormalizer(
            backend=backend,
            openjtalk_python=openjtalk_python,
            kakasi=kk,
            fallback_lexicon=FALLBACK_KANJI_LEXICON,
        )
    return asrlib.KanaNormalizer(
        backend=backend,
        openjtalk_python=openjtalk_python,
        kakasi=None,
        fallback_lexicon=FALLBACK_KANJI_LEXICON,
    )


def normalize_kana_for_cer(text, normalizer=None):
    """Single-text wrapper (tests / debug). Production scoring uses batch conversion."""
    if normalizer is None:
        normalizer = asrlib.KanaNormalizer(backend="fallback", fallback_lexicon=FALLBACK_KANJI_LEXICON)
    return normalizer.batch([text])[0]


def levenshtein_distance(a, b):
    return asrlib.levenshtein_distance(a, b)


def compute_cer(ref_texts, hyp_texts, normalizer):
    """元の文(ref)とASR出力(hyp)の両方を同じかな変換に通してから CER を計算する。"""
    return asrlib.compute_cer(ref_texts, hyp_texts, normalizer)


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
def build_asr_runner(spec, timeout=asrlib.DEFAULT_HTTP_TIMEOUT_SEC, retry_budget=asrlib.DEFAULT_RETRY_BUDGET_SEC):
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
            return asrlib.run_http_asr(spec, wav_paths, timeout=timeout, retry_budget=retry_budget)

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


# つまみ係クライアント（イタコ :8090 Qwen3-30B-A3B / OpenAI互換 API）
# model は必ず "default_model"（他の名前を出すと 8090 が 30B を降ろして入れ替える）。
# ※ 渡す情報は「いちばん良かった5件・直近5件・パラメータの範囲」だけ。
#   確認用 (eval) の情報は引数にすら受け取らない。
# ==============================================================================
def validate_and_round_knob_dict(cand, active_knobs):
    """範囲外の値は許容範囲の端に丸め、桁も揃える。欠ける・非数値は (None, 理由)。"""
    return asrlib.clamp_and_round_knob_dict(cand, active_knobs, PARAM_BOUNDS)


def extract_json_object(raw_text):
    return asrlib.extract_json_object(raw_text)


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


def propose_from_qwen(
    llm_base_url,
    llm_model,
    active_knobs,
    tune_only_history,
    seen_keys,
    timeout=asrlib.DEFAULT_HTTP_TIMEOUT_SEC,
    retry_budget=asrlib.DEFAULT_RETRY_BUDGET_SEC,
):
    """最良5件・直近5件・パラメータ範囲だけを見せて次の組を1つ提案させる。

    範囲外の値は端に丸める。JSON が読めなければ同じ内容でもう1回だけ取り直す。
    接続拒否・切断は 1,2,4,8... 秒で、合計約 retry_budget 秒までやり直す。
    """
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
        "範囲を外れた値はこちらで端に丸めます。説明文は不要です。出力形式例: "
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

        parse_retry_hint = {"on": False}

        def _fetch_content(user_prompt=user_prompt, parse_retry_hint=parse_retry_hint, attempt=attempt):
            up = user_prompt
            if parse_retry_hint["on"]:
                up += "\n前回の出力はJSONとして読めませんでした。JSONオブジェクト1個だけを出力してください。\n"
            parse_retry_hint["on"] = True
            payload = {
                "model": llm_model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": up},
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
            raw, _code = asrlib.request_with_retry(req, timeout=timeout, retry_budget=retry_budget)
            body = json.loads(raw.decode("utf-8"))
            return body["choices"][0]["message"]["content"]

        try:
            parsed, n_fetch = asrlib.load_json_from_llm_response(_fetch_content)
            if n_fetch > 1:
                rejections.append("retried once after unparseable JSON")
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
        except (ValueError, json.JSONDecodeError) as e:
            rejections.append(f"unparseable JSON after 1 retry: {e}")
            break
        except Exception as e:
            err_s = f"parse/API error: {e}"
            rejections.append(err_s)
            if asrlib.is_connection_error(e):
                break
            feedback_msg = err_s

    # 欠損・重複が続いた、または JSON が2回読めなかった場合: 最良点近傍の決定論的微小摂動
    fallback = {}
    n_hist = len(tune_only_history)
    for ki, k in enumerate(active_knobs):
        lo, hi, ndig, _ = PARAM_BOUNDS[k]
        span = (hi - lo) * 0.06 * ((-1) ** (n_hist + ki))
        nv = min(hi, max(lo, anchor["knobs"][k] + span))
        fallback[k] = int(round(nv)) if ndig == 0 else round(nv, ndig)
    rejections.append("used bounded perturbation fallback after invalid proposals")
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
        help="ASR endpoint (repeatable). Default: 127.0.0.1:8091 and :8092 /v1/audio/transcriptions. "
             "Do not start tools/itako_asr_server.py on 8091 on 関亡婆.",
    )
    ap.add_argument("--llm-url", default=asrlib.DEFAULT_LLM_URL, help="OpenAI-compatible base URL (or 'mock')")
    ap.add_argument(
        "--llm-model",
        default=asrlib.DEFAULT_LLM_MODEL,
        help="Must be 'default_model' on 関亡婆 (any other name can unload the 30B)",
    )
    ap.add_argument("--preset", choices=tuple(Y.PRESETS.keys()), default="hitofude", help="Starting preset baseline")
    ap.add_argument("--knobs", default="hz,fscale,rate", help="Comma-separated tunable knob names (default: hz,fscale,rate)")
    ap.add_argument("--max-iters", type=int, default=10, help="Total iterations including iter 0 baseline (default: 10)")
    ap.add_argument("--synth", choices=("python", "node"), default="python", help="Synthesis engine (default: canonical python)")
    ap.add_argument("--skip-parity-check", action="store_true", help="Skip check_js_parity.py when --synth node is used")
    ap.add_argument("--remeasure-hakaru-gate", action="store_true", help="Recompute hakaru gate from current Y.PRESETS at startup")
    ap.add_argument(
        "--kana-backend",
        choices=("openjtalk", "pykakasi", "fallback"),
        default="openjtalk",
        help="Symmetric kana converter for ref and hyp (default: pyopenjtalk via ~/kana/bin/python)",
    )
    ap.add_argument(
        "--openjtalk-python",
        default=asrlib.DEFAULT_OPENJTALK_PYTHON,
        help="Python binary that has pyopenjtalk (default: ~/kana/bin/python)",
    )
    ap.add_argument(
        "--http-timeout",
        type=int,
        default=asrlib.DEFAULT_HTTP_TIMEOUT_SEC,
        help="Per-request HTTP timeout in seconds (default 120; do not go below 120 on 関亡婆)",
    )
    ap.add_argument(
        "--retry-budget",
        type=int,
        default=asrlib.DEFAULT_RETRY_BUDGET_SEC,
        help="Max total sleep seconds for connection retries (1,2,4,8... up to this budget, default 90)",
    )
    ap.add_argument("--allow-no-kakasi", action="store_true", help="Allow fallback lexicon when the kana backend is unavailable (tests)")
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

    asr_specs = args.asr or list(asrlib.DEFAULT_ASR_URLS)
    allow_fallback = bool(args.allow_no_kakasi or asr_specs == ["mock"])
    if args.llm_url != "mock" and args.http_timeout < 120:
        print(f"[warn] --http-timeout {args.http_timeout} < 120; raising to 120 so a cold model load can finish.", flush=True)
        args.http_timeout = 120

    kana_norm = make_kana_normalizer(
        args.kana_backend,
        openjtalk_python=args.openjtalk_python,
        allow_fallback=allow_fallback,
    )

    if args.synth == "node" and not args.skip_parity_check:
        engine_mjs = os.path.join(HERE, "hitofude_engine.mjs")
        print("[parity] Verifying tools/hitofude_engine.mjs against hitofude.py via tools/check_js_parity.py ...", flush=True)
        subprocess.check_call([sys.executable, os.path.join(HERE, "check_js_parity.py"), engine_mjs])

    if args.remeasure_hakaru_gate:
        hakaru_gate, _ = measure_hakaru_gate_from_presets(TUNE_ITEMS[0]["synth"])
    else:
        hakaru_gate = dict(DEFAULT_HAKARU_GATE_UTT0)

    asr_runners = [
        build_asr_runner(sp, timeout=args.http_timeout, retry_budget=args.retry_budget) for sp in asr_specs
    ]
    llm_model = args.llm_model or asrlib.DEFAULT_LLM_MODEL
    if llm_model == "auto":
        llm_model = asrlib.DEFAULT_LLM_MODEL
    if args.llm_url != "mock" and llm_model != asrlib.DEFAULT_LLM_MODEL:
        print(
            f"[warn] --llm-model={llm_model!r} is not 'default_model'. "
            "On 関亡婆 this can unload the 30B on port 8090.",
            flush=True,
        )

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
        f"knobs={active_knobs} | iters={args.max_iters} | asrs={asr_specs} | "
        f"llm_model={llm_model} | kana={kana_norm.backend} | score=worst_of_two_asrs_per_item ===",
        flush=True,
    )

    cur_knobs = {k: base_prm[k] for k in active_knobs}
    rejections = []

    for it in range(args.max_iters):
        if it > 0:
            cur_knobs, rejections = propose_from_qwen(
                args.llm_url,
                llm_model,
                active_knobs,
                tune_only_history,
                seen_keys,
                timeout=args.http_timeout,
                retry_budget=args.retry_budget,
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
                    "score_rule": "worst_of_two_asrs_per_item",
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
            tune_items_by_asr = {}
            eval_items_by_asr = {}
            transcriptions = {"tune": {}, "eval": {}}

            for runner in asr_runners:
                asr_name, tune_hyps = runner(tune_wavs, full_prm, tune_refs)
                _, eval_hyps = runner(eval_wavs, full_prm, eval_refs)

                t_cer, t_items = compute_cer(tune_refs, tune_hyps, kana_norm)
                e_cer, e_items = compute_cer(eval_refs, eval_hyps, kana_norm)

                tune_cer_by_asr[asr_name] = t_cer
                eval_cer_by_asr[asr_name] = e_cer
                tune_items_by_asr[asr_name] = t_items
                eval_items_by_asr[asr_name] = e_items
                transcriptions["tune"][asr_name] = [
                    {"ref": it_d["ref_raw"], "ref_kana": it_d["ref_kana"], "hyp": it_d["hyp_raw"], "hyp_kana": it_d["hyp_kana"], "cer": it_d["cer"]}
                    for it_d in t_items
                ]
                transcriptions["eval"][asr_name] = [
                    {"ref": it_d["ref_raw"], "ref_kana": it_d["ref_kana"], "hyp": it_d["hyp_raw"], "hyp_kana": it_d["hyp_kana"], "cer": it_d["cer"]}
                    for it_d in e_items
                ]

            # Official score: worse (higher) CER of the two ASRs, decided per item
            mean_tune_cer, _ = asrlib.worse_cer_per_item(tune_items_by_asr)
            mean_eval_cer, _ = asrlib.worse_cer_per_item(eval_items_by_asr)

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
            "score_rule": "worst_of_two_asrs_per_item",
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
