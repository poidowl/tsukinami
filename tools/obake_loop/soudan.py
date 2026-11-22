"""digest_loop_NNN.json → 关亡婆（8090、細切れ問い合わせ）に原因の順位と耳の育て方の提案を書かせる → teian_loop_NNN.json
提案だけ。耳(mimi_table.json)は変えん。採るかどうかはナグリが決める。"""
import json, sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kotodama import probe, gen
dig = sys.argv[1]
outp = dig.replace("digest_loop_", "teian_loop_")
p0 = probe()
if p0 is None or p0 > 1.5: print(json.dumps({"skip": "8090 busy", "probe": p0})); sys.exit(3)
D = json.load(open(dig))
SYS = ("あなたは音声認識の研究者。純JavaScript・ニューラル網なし・外部ライブラリなしの小さな耳 mimi（16帯の断面→42次元特徴、状態ごとの対角GMM、モーラ2-gram、Viterbi）を育てている。"
       "データは合成音声 kusanagi の声だけ。渡す集計だけを根拠に答える。耳を直接いじる権限はない。提案だけを書く。")
USER = ("集計（初見の台本での聞き間違い）:\n" + json.dumps(D, ensure_ascii=False, separators=(",", ":")) + "\n\n"
        "次の形の JSON だけを出す（説明文やコードブロックは不要、全体で 1200 字以内）:\n"
        '{"analysis":[{"rank":1,"pattern":"聞き間違いの型","evidence":"集計のどの数字か","share":"およその割合"}],'
        '"proposals":[{"id":"P1","title":"…","change":"具体的に何をどう変えるか（特徴/状態/長さモデル/2-gram/復号の加減/台本の足し方など）","why":"…","expected_gain":"かな正答 +何ポイント","cost":"小/中/大","risk":"…"}]}\n'
        "analysis は 3〜5 個、proposals は 3〜5 個、効きそうな順。正解側（読みの作り方）の問題と耳側の問題を分ける。")
txt, meta = gen(SYS, USER, max_total=1600, temperature=0.4)
ans = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
def loads_lenient(t):
    """LLM の JSON を甘めに読む：そのまま → 変な \\ エスケープ（\\6 や \\` など）の \\ を落とす → 制御文字も許す。"""
    t = t[t.index("{"): t.rindex("}") + 1]
    errs = []
    for f in (lambda x: x, lambda x: re.sub(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})?', lambda m: m.group(0) if m.group(1) else "", x)):
        for strict in (True, False):
            try: return json.loads(f(t), strict=strict), errs
            except Exception as e: errs.append(str(e))
    raise ValueError(" / ".join(errs))
try:
    J, errs = loads_lenient(ans)
    if errs: J["_parse_fixed"] = errs[0]
except Exception as e: J = {"parse_error": str(e), "raw": ans}
J["_meta"] = {**meta, "digest": os.path.basename(dig), "score_recent": D.get("score_recent"), "note": "提案だけ。耳は変えていない。採否はナグリ。"}
json.dump(J, open(outp, "w"), ensure_ascii=False, indent=1)
print(json.dumps({"out": outp, **{k: meta[k] for k in ("sec", "requests", "req_max_sec", "probe_during")}}, ensure_ascii=False))
