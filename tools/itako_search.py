#!/usr/bin/env python3
"""tools/itako_search.py — 草薙版イタコ探索：粗い LHS 探索 → 关亡婆 (8090) で詰め → 検証

- 1組の点 = 調整用の全文 × 複数 seed を node yomu.mjs で合成し、8091/8092 の2つで聞かせ、
  文ごと（seed ごと）に悪いほうの ASR を取って sum(edits)/sum(len) にした値（低いほど良い）。
- seed は yomu の乱数の種。同じ組・同じ seed なら同じ波形（決定論）なので、seed を複数にして
  「つまみの微小変化で ASR が揺れる」ぶれを平均でならす。
- 段階 A: 広い範囲でラテン超方格 (LHS) の点を撃つ。段階 B: 上位3点を关亡婆に渡し、
  序盤は範囲幅の10〜20%、終盤は5%以下の歩幅を明示して詰めさせる。段階 C: 既定値と最良値を
  調整用＋確認用で採点し、最良値はもう2回採点して安定を見る。hakaru の失格枠は守る。
- 確認用の文・文字起こし・CER は关亡婆には見せない。

例（关亡婆の上で。システムの python3 は使わない）:
  ITAKO_NODE=~/itako_kusanagi/node/bin/node python tools/itako_search.py \
      --items ../items3.json --out ../out/run3 --coarse 80 --refine 20
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import random
import shutil
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import itako_asr_lib as asrlib  # noqa: E402
import itako_asr_loop as loop   # noqa: E402
import kusanagi_yomu as KY      # noqa: E402

JST = datetime.timezone(datetime.timedelta(hours=9), name="JST")
DEFAULT_KNOBS = "hz,fscale,rate,g_vo,tilt_w,jitter,wander_st"


def now():
    return datetime.datetime.now(JST).isoformat(timespec="seconds")


def round_knobs(cand, knobs):
    out, err = loop.validate_and_round_knob_dict(cand, knobs)
    if err:
        raise ValueError(err)
    return out


def lhs_points(n, knobs, rng):
    """各つまみの範囲を n 等分し、区間ごとに1点ずつ（列ごとに独立に並べ替え）。"""
    cols = {}
    for k in knobs:
        lo, hi = loop.PARAM_BOUNDS[k][0], loop.PARAM_BOUNDS[k][1]
        vals = [lo + (hi - lo) * (i + rng.random()) / n for i in range(n)]
        rng.shuffle(vals)
        cols[k] = vals
    return [round_knobs({k: cols[k][i] for k in knobs}, knobs) for i in range(n)]


class Scorer:
    def __init__(self, items, seeds, asr_specs, kana_norm, gate, base_prm, timeout, retry_budget):
        self.items = items
        self.seeds = seeds
        self.asr_specs = asr_specs
        self.runners = [loop.build_asr_runner(s, timeout=timeout, retry_budget=retry_budget) for s in asr_specs]
        self.kana = kana_norm
        self.gate = gate
        self.base = base_prm
        refs = [it["ref"] for it in items]
        self.ref_kana = kana_norm.batch(refs)

    def score(self, knobs, keep_wav_dir=None):
        prm = dict(self.base, **knobs)
        synths = [it["synth"] for it in self.items]
        refs = [it["ref"] for it in self.items]
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="itako_s_") as td:
            wavs_by_seed = {}
            hk0 = None
            for si, seed in enumerate(self.seeds):
                p = dict(prm, seed=seed)
                paths = [os.path.join(td, f"s{seed}_utt_{i:02d}.wav") for i in range(len(synths))]
                hks = KY.synth_many(synths, p, paths, measure=(si == 0))
                if si == 0:
                    hk0 = hks[0]
                    viol = loop.check_hakaru_gate(hk0, self.gate) if self.gate else []
                    if viol:
                        return {"knobs": knobs, "disqualified": "; ".join(viol), "cer": None, "hakaru": hk0,
                                "sec": round(time.time() - t0, 1)}
                wavs_by_seed[seed] = paths
            all_wavs = [w for s in self.seeds for w in wavs_by_seed[s]]
            all_refs = refs * len(self.seeds)

            def _run(runner):
                return runner(all_wavs, prm, all_refs)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.runners)) as ex:
                outs = list(ex.map(_run, self.runners))
            hyp_flat = [h for _, hyps in outs for h in hyps]
            hyp_kana = self.kana.batch(hyp_flat) if hyp_flat else []
            items_by_asr = {}
            by_asr = {}
            off = 0
            for name, hyps in outs:
                hk = hyp_kana[off:off + len(hyps)]
                off += len(hyps)
                c, its = asrlib.compute_cer_from_kana(self.ref_kana * len(self.seeds), hk, ref_raws=all_refs, hyp_raws=hyps)
                items_by_asr[name] = its
                by_asr[name] = c
            cer, _ = asrlib.worse_cer_per_item(items_by_asr)
            n = len(self.items)
            per_sentence = []
            for i, it in enumerate(self.items):
                row = {"ref": it["ref"], "synth": it["synth"], "ref_kana": self.ref_kana[i], "by_asr": {}}
                worst = []
                for name, its in items_by_asr.items():
                    seeds_rows = [its[si * n + i] for si in range(len(self.seeds))]
                    row["by_asr"][name] = [{"seed": self.seeds[si], "hyp": r["hyp_raw"], "cer": r["cer"]}
                                           for si, r in enumerate(seeds_rows)]
                for si in range(len(self.seeds)):
                    worst.append(max(its[si * n + i]["cer"] for its in items_by_asr.values()))
                row["worse_cer_mean"] = round(sum(worst) / len(worst), 4)
                per_sentence.append(row)
            if keep_wav_dir:
                os.makedirs(keep_wav_dir, exist_ok=True)
                for seed, paths in wavs_by_seed.items():
                    for pth in paths:
                        shutil.copy(pth, os.path.join(keep_wav_dir, os.path.basename(pth)))
        return {"knobs": knobs, "disqualified": None, "cer": cer, "by_asr": by_asr, "per_sentence": per_sentence,
                "hakaru": hk0, "sec": round(time.time() - t0, 1)}


def ask_llm(url, model, knobs, history, anchors, step_frac, seen, timeout, retry_budget):
    bounds = {k: {"min": loop.PARAM_BOUNDS[k][0], "max": loop.PARAM_BOUNDS[k][1], "desc": loop.PARAM_BOUNDS[k][3]}
              for k in knobs}
    steps = {k: round((loop.PARAM_BOUNDS[k][1] - loop.PARAM_BOUNDS[k][0]) * step_frac, 4) for k in knobs}
    valid = [h for h in history if h.get("cer") is not None]
    best5 = [{"knobs": h["knobs"], "cer": h["cer"]} for h in sorted(valid, key=lambda h: h["cer"])[:5]]
    recent5 = [{"knobs": h["knobs"], "cer": h["cer"], "disqualified": bool(h.get("disqualified"))} for h in history[-5:]]
    sys_prompt = (
        "あなたは音声合成器のパラメータ調整係です。/no_think\n"
        "目的は日本語ASRの文字誤り率 cer（0〜1、低いほど良い）を下げることです。\n"
        "cer には測定のぶれがあるので、細かすぎる刻みは無意味です。"
        f"今回は、出発点（上位の点のどれか）から、各つまみを最大でおよそ範囲幅の{int(step_frac * 100)}%"
        f"（目安の歩幅: {json.dumps(steps)}）まで大胆に動かしてください。少なくとも2つのつまみを目安の半分以上動かすこと。\n"
        "disqualified の周辺は避け、範囲 [min, max] 内で未試行の組を JSON オブジェクト1個だけ出力。説明は不要。"
    )
    fb = ""
    for attempt in range(3):
        up = (f"範囲:\n{json.dumps(bounds, ensure_ascii=False)}\n\n出発点の候補（粗い探索の上位3点）:\n"
              f"{json.dumps(anchors, ensure_ascii=False)}\n\n最良5件:\n{json.dumps(best5, ensure_ascii=False)}\n\n"
              f"直近5件:\n{json.dumps(recent5, ensure_ascii=False)}\n")
        if fb:
            up += f"\n前回の出力は却下: {fb}\n"
        up += "\n次に試す組の JSON オブジェクトのみ:"
        payload = {"model": model, "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": up}],
                   "temperature": 0.5 + 0.2 * attempt, "max_tokens": 400}

        def _fetch(payload=payload):
            req = urllib.request.Request(f"{url.rstrip('/')}/chat/completions", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            raw, _ = asrlib.request_with_retry(req, timeout=timeout, retry_budget=retry_budget)
            return json.loads(raw.decode())["choices"][0]["message"]["content"]

        try:
            parsed, _n = asrlib.load_json_from_llm_response(_fetch)
            cand, err = loop.validate_and_round_knob_dict(parsed, knobs)
            if err:
                fb = err
                continue
            key = json.dumps(cand, sort_keys=True)
            if key in seen:
                fb = f"試行済み: {cand}"
                continue
            return cand, attempt
        except Exception as e:  # noqa: BLE001
            fb = f"error: {e}"
            if asrlib.is_connection_error(e):
                break
    return None, fb


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--items", required=True)
    ap.add_argument("--out", required=True, help="output dir (log.jsonl, summary.json, wavs_default/, wavs_best/)")
    ap.add_argument("--knobs", default=DEFAULT_KNOBS)
    ap.add_argument("--seeds", default="2024,7")
    ap.add_argument("--coarse", type=int, default=80)
    ap.add_argument("--refine", type=int, default=20)
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--min", action="append", default=[], help="tighter lower bound, e.g. --min hz=280 (female-range search)")
    ap.add_argument("--rng-seed", type=int, default=20261119)
    ap.add_argument("--llm-url", default=asrlib.DEFAULT_LLM_URL)
    ap.add_argument("--llm-model", default=asrlib.DEFAULT_LLM_MODEL)
    ap.add_argument("--asr", action="append", default=[])
    ap.add_argument("--kana-backend", default="openjtalk", choices=("openjtalk", "pykakasi", "fallback"))
    ap.add_argument("--openjtalk-python", default=asrlib.DEFAULT_OPENJTALK_PYTHON)
    ap.add_argument("--http-timeout", type=int, default=asrlib.DEFAULT_HTTP_TIMEOUT_SEC)
    ap.add_argument("--retry-budget", type=int, default=asrlib.DEFAULT_RETRY_BUDGET_SEC)
    args = ap.parse_args()

    knobs = [k.strip() for k in args.knobs.split(",") if k.strip()]
    for k in knobs:
        if k not in loop.PARAM_BOUNDS:
            raise SystemExit(f"unknown knob {k}")
    for spec in args.min:
        k, v = spec.split("=")
        lo, hi, nd, desc = loop.PARAM_BOUNDS[k]
        loop.PARAM_BOUNDS[k] = (max(lo, float(v)), hi, nd, desc)  # 粗い探索も关亡婆の提案もこの範囲に丸める
    seeds = [int(s) for s in args.seeds.split(",")]
    tune_items, check_items = loop.load_items(args.items)
    asr_specs = args.asr or list(asrlib.DEFAULT_ASR_URLS)
    kana = loop.make_kana_normalizer(args.kana_backend, openjtalk_python=args.openjtalk_python,
                                     allow_fallback=(asr_specs == ["mock"]))
    gate, _ = loop.measure_hakaru_gate_from_presets(tune_items[0]["synth"])
    base = {k: KY.presets()["hitofude"][k] for k in KY.knob_keys()}
    base.update({k: v[2] for k, v in KY.extra_knobs().items()})
    default_knobs = {k: base[k] for k in knobs}
    os.makedirs(args.out, exist_ok=True)
    log_path = os.path.join(args.out, "log.jsonl")
    # 失格枠は調整用1文目・最初の seed で測ったものなので、その文が先頭の採点器だけに掛ける
    mk = lambda items, g: Scorer(items, seeds, asr_specs, kana, g, base, args.http_timeout, args.retry_budget)  # noqa: E731
    tune_s, check_s, all_s = mk(tune_items, gate), mk(check_items, None), mk(tune_items + check_items, gate)

    def log(stage, res, **extra):
        res["stage"] = stage
        rec = dict({"time_jst": now()}, **res, **extra)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        c = "DQ " + res["disqualified"] if res.get("disqualified") else f"cer={res['cer']:.4f} {res.get('by_asr')}"
        print(f"[{stage}] {res['knobs']} -> {c} ({res['sec']}s)", flush=True)
        return res

    print(f"=== itako_search | git={loop.git_head_info()} | knobs={knobs} | seeds={seeds} | "
          f"tune={len(tune_items)} check={len(check_items)} | gate={gate} ===", flush=True)
    history = []
    seen = set()
    # 段階0: 既定値（決定論の確認に2回）
    d1 = log("default", tune_s.score(default_knobs))
    d2 = log("default_repeat", tune_s.score(default_knobs))
    deterministic = d1["cer"] == d2["cer"]
    print(f"[determinism] default twice: {d1['cer']} / {d2['cer']} -> {'same' if deterministic else 'DIFFERENT'}", flush=True)
    history.append(d1)
    seen.add(json.dumps(default_knobs, sort_keys=True))
    # 段階A: LHS
    rng = random.Random(args.rng_seed)
    for i, kn in enumerate(lhs_points(args.coarse, knobs, rng)):
        seen.add(json.dumps(kn, sort_keys=True))
        history.append(log(f"coarse_{i:03d}", tune_s.score(kn)))
    valid = sorted([h for h in history if h.get("cer") is not None], key=lambda h: h["cer"])
    anchors = [{"knobs": h["knobs"], "cer": h["cer"]} for h in valid[:args.top]]
    print(f"[top{args.top}] {anchors}", flush=True)
    # 段階B: 关亡婆
    for j in range(args.refine):
        frac = 0.20 if j < args.refine * 0.35 else (0.10 if j < args.refine * 0.7 else 0.05)
        t0 = time.time()
        cand, info = ask_llm(args.llm_url, args.llm_model, knobs, history, anchors, frac, seen,
                             args.http_timeout, args.retry_budget)
        llm_sec = round(time.time() - t0, 1)
        if cand is None:
            print(f"[refine_{j:02d}] LLM gave no usable proposal: {info}", flush=True)
            continue
        seen.add(json.dumps(cand, sort_keys=True))
        history.append(log(f"refine_{j:02d}", tune_s.score(cand), step_frac=frac, llm_sec=llm_sec))
    valid = sorted([h for h in history if h.get("cer") is not None], key=lambda h: h["cer"])
    best = valid[0]
    # 段階C: 検証
    v_def = log("validate_default_all", all_s.score(default_knobs, keep_wav_dir=os.path.join(args.out, "wavs_default")))
    v_best = [log("validate_best_all", all_s.score(best["knobs"], keep_wav_dir=os.path.join(args.out, "wavs_best")))]
    for r in range(2):
        v_best.append(log(f"validate_best_repeat{r + 1}", all_s.score(best["knobs"])))
    c_def = log("check_default", check_s.score(default_knobs))
    c_best = log("check_best", check_s.score(best["knobs"]))
    summary = {
        "time_jst": now(), "git": loop.git_head_info(), "knobs": knobs, "seeds": seeds, "deterministic": deterministic,
        "gate": gate, "n_scored": len(history), "default": default_knobs, "best": best["knobs"],
        "best_stage": best["stage"], "tune_default": d1["cer"], "tune_best": best["cer"],
        "tune_default_by_asr": d1["by_asr"], "tune_best_by_asr": best["by_asr"],
        "check_default": c_def["cer"], "check_best": c_best["cer"],
        "check_default_by_asr": c_def["by_asr"], "check_best_by_asr": c_best["by_asr"],
        "all_default": v_def["cer"], "all_best_runs": [v["cer"] for v in v_best],
        "top_coarse": anchors,
        "tune_cer_distribution": sorted(h["cer"] for h in history if h.get("cer") is not None),
        "per_sentence_default": [{"ref": r["ref"], "worse": r["worse_cer_mean"]} for r in v_def["per_sentence"]],
        "per_sentence_best": [{"ref": r["ref"], "worse": r["worse_cer_mean"]} for r in v_best[0]["per_sentence"]],
    }
    with open(os.path.join(args.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("=== summary ===\n" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
