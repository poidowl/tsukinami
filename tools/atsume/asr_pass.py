"""atsume の wav を 8092(parakeet)・8091(Qwen3-ASR) に聞かせて、書き取り＋かな＋CER(対 spoken ラベル) を asr.jsonl に足す。
~/kana/bin/python asr_pass.py K   … まだの行を新しい順に最大 K 本。1 本でも 3 秒を超えたらその周は打ち切り（8090 を守る）。"""
import json, sys, os, re, time, urllib.request, pyopenjtalk
H = os.path.dirname(os.path.abspath(__file__)); K = int(sys.argv[1]) if len(sys.argv) > 1 else 30
done = set()
if os.path.exists(f"{H}/asr.jsonl"):
    for l in open(f"{H}/asr.jsonl"):
        try: done.add(json.loads(l)["id"])
        except Exception: pass
rows = []
for l in open(f"{H}/ledger.jsonl"):
    try: r = json.loads(l)
    except Exception: continue
    if r["id"] not in done and os.path.exists(f"{H}/{r['rel']}"): rows.append(r)
rows = rows[::-1][:K]
def ed(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        p, d[0] = d[0], i
        for j in range(1, len(b) + 1): p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (a[i - 1] != b[j - 1]))
    return d[len(b)]
def post(port, p):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/audio/transcriptions", data=json.dumps({"path": p}).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))["text"]
out = open(f"{H}/asr.jsonl", "a"); n = 0; slow = None; t0 = time.time()
for r in rows:
    rec = {"id": r["id"], "at": time.strftime("%FT%T%z")}
    for name, port in (("parakeet", 8092), ("qwen3", 8091)):
        s = time.time()
        try: txt = post(port, f"{H}/{r['rel']}")
        except Exception as e: txt = None; rec[name + "_err"] = str(e)[:120]
        sec = round(time.time() - s, 2)
        if txt is not None:
            k = re.sub(r"[^ァ-ヴー]", "", pyopenjtalk.g2p(txt, kana=True)).replace("ヲ", "オ"); ref = r["spoken"].replace("ヲ", "オ")
            rec[name] = {"text": txt, "kana": k, "cer": round(100 * ed(ref, k) / max(1, len(ref)), 1), "sec": sec}
        if sec > 3: slow = f"{name} {sec}s"
    out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush(); n += 1
    if slow: break
    time.sleep(0.5)
print(json.dumps({"asr": n, "left": len(rows) - n, "slow": slow, "sec": round(time.time() - t0, 1)}))
