#!/Users/p/mlx/bin/python
"""変態耳: 关亡婆（分析用モデル）に聞き間違いの要約を渡し、原因の順位と耳の育て方の提案を JSON で書かせる。
  ~/itako_mimi/itako_soudan.py digest.json out.json  （M6 で ~/mlx の venv の python。標準ライブラリだけ。耳そのものではなく相談の窓口） [--url http://127.0.0.1:8094/v1/chat/completions]"""
import json, sys, time, urllib.request, re
dig, outp = sys.argv[1], sys.argv[2]
url = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else "http://127.0.0.1:8094/v1/chat/completions"
D = json.load(open(dig))
SYS = ("あなたは音声認識の研究者。純JavaScript・ニューラル網なし・外部ライブラリなしの小さな耳（混合ガウス＋HMM）を育てている。"
       "データは合成音声 kusanagi の自分の声だけ。確認用（held-out）の台本は見せていない。"
       "渡す集計だけを根拠に、(a) 聞き間違いの原因を重い順に、(b) 耳の育て方の具体的な提案を、JSON だけで答える。")
USER = ("集計:\n" + json.dumps(D, ensure_ascii=False) + "\n\n"
        "次の形の JSON だけを出す（説明文やコードブロックは不要）:\n"
        '{"analysis":[{"rank":1,"cause":"...","evidence":"集計のどの数字か","share":"誤りのうちおよその割合"}],'
        '"proposals":[{"id":"P1","title":"...","change":"具体的に何をどう変えるか（特徴/状態の分け方/長さモデル/正解の作り方/復号の加減など）",'
        '"why":"...","expected_gain":"確認用かな正答で +何ポイントくらい","cost":"小/中/大","risk":"..."}]}\n'
        "提案は 3〜6 個、効きそうな順。正解（参照）側の問題と、耳側の問題を分けて考える。")
body = {"model": "default_model", "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": USER}],
        "max_tokens": 6000, "temperature": 0.6, "top_p": 0.95}
t0 = time.time()
req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=1800))
txt = r["choices"][0]["message"]["content"]
think = ""
m = re.search(r"<think>(.*?)</think>", txt, re.S)
if m: think = m.group(1).strip()
ans = txt.split("</think>")[-1].strip()
ans = re.sub(r"^```(json)?|```$", "", ans.strip(), flags=re.M).strip()
try: J = json.loads(ans[ans.index("{"): ans.rindex("}") + 1])
except Exception as e: J = {"parse_error": str(e), "raw": ans}
J["_meta"] = {"sec": round(time.time() - t0, 1), "usage": r.get("usage"), "think_chars": len(think), "model": r.get("model")}
json.dump(J, open(outp, "w"), ensure_ascii=False, indent=1)
open(outp.replace(".json", "_think.txt"), "w").write(think)
print(json.dumps(J["_meta"], ensure_ascii=False))
