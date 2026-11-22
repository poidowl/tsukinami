"""关亡婆（8090）に新しい台本を 1 本書かせ、janome でかなにして、kiku_eval の corpus 形（split=loop）で出す。
  venv/bin/python daihon_gen.py OUT_corpus.json  → 標準出力に 1 行 JSON（id, 行数, 8090 の返り）"""
import json, sys, time, random, re, unicodedata, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kotodama import probe, gen
from janome.tokenizer import Tokenizer
T = Tokenizer()
KATA = re.compile(r'^[ァ-ヴー]+$')
def kana(text):   # itako_kana.py（box）と同じ下ごしらえ
    out = []
    for tk in T.tokenize(text):
        s = tk.surface; pos = tk.part_of_speech.split(',')
        if s in ('、', '，', ',', '。', '．', '！', '!', '…', '「', '」', '・', '　', ' ', '？', '?'):
            if s in ('？', '?'): out.append('?')
            elif s not in ('「', '」', '・'): out.append('、')
            continue
        r = tk.reading if tk.reading and tk.reading != '*' else None
        if r is None:
            r = ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in s)
        if pos[0] == '助詞' and s == 'は': r = 'ワ'
        elif pos[0] == '助詞' and s == 'へ': r = 'エ'
        elif pos[0] == '助詞' and s == 'を': r = 'オ'
        if not KATA.match(r): return None
        out.append(r)
    s = ''.join(out)
    s = re.sub(r'、+', '、', s).strip('、')
    s = re.sub(r'、\?', '?', s)
    return s if len(s.replace('、', '').replace('?', '')) >= 4 else None

TOPICS = ["こたつ", "雨の音", "猫のしっぽ", "冬の朝", "湯たんぽ", "星空", "駅のホーム", "味噌汁", "古い時計", "雪の日", "図書館", "金魚",
          "夜の散歩", "風邪の日", "洗濯もの", "月見", "お茶の時間", "毛布", "焼き芋", "電車の窓", "郵便受け", "夕焼け", "ストーブ", "ラジオ",
          "朝ごはん", "坂道", "傘", "お風呂", "まくら", "商店街", "川の流れ", "紅葉", "手紙", "おでん", "みかん", "とうふ屋", "神社", "灯台"]
WEAK = ["長い「う」「お」（ゆう、こう、そう、きゅう、しょう など）", "「ん」と「に」「の」が続くところ", "拗音（きゃ、きゅ、ちょ、りょ、ひょ など）",
        "促音「っ」", "「る」「り」「ろ」が続くところ", "母音が二つ並ぶところ（あい、おう、いい）"]

def main():
    outp = sys.argv[1]
    p0 = probe()
    if p0 is None or p0 > 1.5:
        print(json.dumps({"skip": "8090 busy or down", "probe": p0}, ensure_ascii=False)); sys.exit(3)
    rnd = random.Random()
    topic = rnd.choice(TOPICS); weak = rnd.sample(WEAK, 2)
    SYS = "あなたは关亡婆。ぬくみTVのやさしい語り手として、短い日本語の台本を書く。"
    USER = (f"お題「{topic}」で、ゆったり語る台本を 8 行書いて。\n"
            "決まり: 1 行は 10〜28 字、ふつうの漢字かな交じり文。数字・英字・記号・絵文字・カタカナ語の長い外来語は使わない。"
            "話し手名や説明はつけない。語尾はばらばらに（です・のだ・だよ・ね など）。\n"
            f"耳の試験用なので、{weak[0]}と、{weak[1]}を含む言葉を自然に多めに入れて。\n"
            '次の JSON だけを出す: {"title":"…","lines":["…", "…"]}')
    txt, meta = gen(SYS, USER, max_total=450, temperature=0.9)
    txt = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.M).strip()
    J = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    sid = "atsume_" + time.strftime("%Y%m%d_%H%M%S")
    lines = []
    for t in J.get("lines", [])[:10]:
        t = unicodedata.normalize("NFKC", str(t)).strip().replace("?", "？").replace("!", "！")
        k = kana(t)
        if k: lines.append({"text": t, "kana": k})
    if len(lines) < 3:
        print(json.dumps({"skip": "too few readable lines", "raw": txt[:300]}, ensure_ascii=False)); sys.exit(4)
    sc = {"id": sid, "title": J.get("title", topic), "split": "atsume", "topic": topic, "weak": weak, "lines": lines, "gen": meta}
    json.dump({"source": "关亡婆（8090 Qwen3-30B-A3B）がオバケ台帳ループで書いた台本。読みは janome。助詞は/へ/を は ワ/エ/オ", "scripts": [sc]},
              open(outp, "w"), ensure_ascii=False, indent=1)
    with open(os.path.expanduser("~/itako_mimi/atsume/daihon/daihon_all.jsonl"), "a") as f: f.write(json.dumps(sc, ensure_ascii=False) + "\n")
    print(json.dumps({"id": sid, "topic": topic, "lines": len(lines), "probe_before": p0, **meta}, ensure_ascii=False))

main()
