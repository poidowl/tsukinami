#!/usr/bin/env python3
"""tools/itako_rescore.py — 決めた組を、調整用／確認用それぞれ指定の seed で採点し直す（新しい seed での検証用）。

  ITAKO_NODE=... python tools/itako_rescore.py --items tools/itako_items_run3.json \
      --params '{"hz":148.1,"fscale":0.973}' --name run3_best --seeds 11,42 --seeds 99,123 --out ../out/run4/rescore.jsonl
省略したつまみは hitofude プリセット（追加つまみは既定0）。失格枠はかけない（採点だけ）。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import itako_asr_lib as L  # noqa: E402
import itako_asr_loop as loop  # noqa: E402
import itako_search as S  # noqa: E402
import kusanagi_yomu as KY  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--params", default="{}", help="JSON object of knob overrides")
    ap.add_argument("--name", default="params")
    ap.add_argument("--seeds", action="append", default=[], help="comma list; repeatable (one score per group)")
    ap.add_argument("--out", default=None, help="append JSONL here")
    ap.add_argument("--keep-wavs", default=None, help="copy wavs of the first seed group here")
    ap.add_argument("--openjtalk-python", default=L.DEFAULT_OPENJTALK_PYTHON)
    args = ap.parse_args()
    tune, chk = loop.load_items(args.items)
    kana = loop.make_kana_normalizer("openjtalk", openjtalk_python=args.openjtalk_python)
    base = {k: KY.presets()["hitofude"][k] for k in KY.knob_keys()}
    base.update({k: v[2] for k, v in KY.extra_knobs().items()})
    knobs = json.loads(args.params)
    for gi, grp in enumerate(args.seeds or ["2024,7"]):
        seeds = [int(x) for x in grp.split(",")]
        for label, items in (("tune", tune), ("check", chk)):
            sc = S.Scorer(items, seeds, list(L.DEFAULT_ASR_URLS), kana, None, base, 120, 90)
            keep = os.path.join(args.keep_wavs, label) if (args.keep_wavs and gi == 0) else None
            r = sc.score(knobs, keep_wav_dir=keep)
            rec = {"name": args.name, "seeds": seeds, "set": label, "knobs": knobs, "cer": r["cer"],
                   "by_asr": {k.split("/")[-1]: v for k, v in r["by_asr"].items()},
                   "per_sentence": [{"ref": p["ref"], "worse": p["worse_cer_mean"],
                                     "hyps": {n.split("/")[-1][:8]: [x["hyp"] for x in v] for n, v in p["by_asr"].items()}}
                                    for p in r["per_sentence"]]}
            print(json.dumps({k: rec[k] for k in ("name", "seeds", "set", "cer", "by_asr")}, ensure_ascii=False), flush=True)
            if args.out:
                os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
                with open(args.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
