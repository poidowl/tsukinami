# DONT SPEAKER 75 "ことば" (73 の削り出しに仮名の文を読ませる：kotoba.py の規則で山の道筋・強さ・息の帯・声のあり／なしを決める)
# 元: DONT SPEAKER 73 "声ありの耳" (72 に：句ごとに下がる高さをやめて平均 410Hz／母音の切り替えを素早く・子音からの入りなし／か・た・ぱは閉じ＋小さな破裂。silero 0.13→0.36：STK Exp 19)
# 元: DONT SPEAKER 72 "揺れを絞る" (70 の高さ 430Hz で、周期ごとの揺れ 6%→1%。耳の「合成音声」0.19→0.06・「子どもの声」0.03→0.14：STK Exp 18)
# 元: DONT SPEAKER 71 "高さ" (70 の高さだけを 4 段。耳のかわいい判定は声の高さがほぼ全部運ぶ：STK Exp 17)
# 元: DONT SPEAKER 70 "ニューニューラル" (69 に：4本くびれで偶数倍音も立てる／か・た・ぱの破裂をやめる／句を短く・拍の頭と尻をやわらかく／山を鋭く F2・F3 を控えめに。3つのニューラル耳で選んだ。STK Exp 16)
# 元: DONT SPEAKER 69 "山を残す" (母音の山 F1〜F3 だけ残して谷を引き算で削る。STK Exp 13/14)
# 元: DONT SPEAKER 68 "息を絞る" (67-3 の息の層を細くして澄ませる。粒も少し大きく)
# 元: DONT SPEAKER 67 "区切りの粒" (66-3 の元を、ノイズから削り出した一粒を周期ごとに置いた列に替える＝澄む。くびれの長さを周期ごとにずらす＝揺らぐ)
# 元: DONT SPEAKER 66 "カキン取り" (65-4 の母音のくびれが高い所で鳴る＝カキン。くびれの中で隣を均す m を増やして高い山を寝かせる)
# 元: DONT SPEAKER 65 "母音を分ける" (64-4 の線に、拍ごとに D を変える二本目・三本目のくびれを重ねて山の比をずらす。引き算だけ)
# white noise -> arakezuri / karuku / kubire(furafura) / sabun / kiridashi. No sin/cos, no oscillators.
import random, wave, struct, json, array, os, copy

SR = 44100
OUT = os.path.dirname(os.path.abspath(__file__))

# ---- chisels copied verbatim from the handoff ----
def arakezuri(x, w, p=1):            # 粗削り：幅 w の平均を p 回
    for _ in range(p):
        y = [0.0] * len(x); s = 0.0
        for i in range(len(x)):
            s += x[i]
            if i >= w: s -= x[i - w]
            y[i] = s / min(i + 1, w)
        x = y
    return x

def kubire(x, D, g, m):              # くびれ：D 個前の自分を引いて戻す
    n = len(x); y = [0.0] * n
    for i in range(n):
        d = D[i]; k = int(d); fr = d - k; acc = 0.0
        for j in range(m):
            a = i - k - j; b = a - 1
            if b >= 0: acc += y[a] * (1 - fr) + y[b] * fr
        y[i] = x[i] - g * acc / m
    return y

# ---- chisels written from the handoff's descriptions ----
def karuku(x, w):                    # 広い平均を引いて低い濁りを落とす
    a = arakezuri(x, w)
    return [x[i] - a[i] for i in range(len(x))]

def sabun(x, w1, w2, p=1):           # 細かい平均 − 粗い平均
    f = arakezuri(x, w1, p); c = arakezuri(x, w2, p)
    return [f[i] - c[i] for i in range(len(x))]

def furafura(n, rng, d0, haba, osoi):  # なだめた千鳥足の D 列
    v = 0.0; walk = [0.0] * n
    for i in range(n):
        v += rng.uniform(-1.0, 1.0)
        v *= 0.9995                   # 千鳥足が遠くへ行きすぎないように
        walk[i] = v
    sm = arakezuri(walk, max(1, int(osoi * SR)), 2)
    mean = sum(sm) / n
    sm = [s - mean for s in sm]
    pk = max(abs(s) for s in sm) or 1.0
    return [d0 + haba * s / pk for s in sm]

def kiridashi(x, a, b, atama, oshiri, magari):  # a..b だけ残し頭と尻を削る
    n = len(x); y = [0.0] * n
    for i in range(max(0, a), min(n, b)):
        t = 1.0
        if i - a < atama: t = ((i - a) / atama) ** magari
        if b - 1 - i < oshiri: t = min(t, ((b - 1 - i) / oshiri) ** magari)
        y[i] = x[i] * t
    return y

def fwd(x, D):                       # 73f：D 前の自分を引く（前向きのくびれ）→ 山は SR/(2D) の奇数倍
    return [x[i] - (x[i - D] if i >= D else 0.0) for i in range(len(x))]

def noise(rng, n):
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]

def rms(x):
    s = sum(v * v for v in x if v != 0.0); c = sum(1 for v in x if v != 0.0) or 1
    return (s / c) ** 0.5

def scale(x, k):
    return [v * k for v in x]


def kubire_t(x, D, G, m):            # くびれ。引く強さ G を時間で変える（手加減）
    n = len(x); y = [0.0] * n
    for i in range(n):
        d = D[i]; k = int(d); fr = d - k; acc = 0.0
        for j in range(m):
            a = i - k - j; b = a - 1
            if b >= 0: acc += y[a] * (1 - fr) + y[b] * fr
        y[i] = x[i] - G[i] * acc / m
    return y

def kubire_n(x, D, G, m, N):         # 70：くびれ N 本。周期 2D を N 等分した所の自分をぜんぶ引く → N の倍数番目以外の倍音が全部立つ（N=2 が今までのくびれ）
    n = len(x); y = [0.0] * n
    for i in range(n):
        P = 2 * D[i]; acc = 0.0
        for q in range(1, N):
            d = P * q / N; k = int(d); fr = d - k
            for j in range(m):
                a = i - k - j; b = a - 1
                if b >= 0: acc += y[a] * (1 - fr) + y[b] * fr
        y[i] = x[i] - G[i] * acc / m
    return y

def arakezuri_t(x, w, p, H):         # 粗削り。H=1 の所は粗さを削り残す（x から「x−平均」を引く量を 1−H に）
    s = arakezuri(x, w, p)
    return [x[i] - (1 - H[i]) * (x[i] - s[i]) for i in range(len(x))]

# 山削り: 母音の山を一つだけ残して谷を削る（引き算だけ）。標準ライブラリのみ。
def _comb(x, D, g):                  # くびれ（m=1）：D 前の自分を引く → 山は SR/(2D) の奇数倍
    n = len(x); y = [0.0] * n
    for i in range(n):
        d = D[i]; k = int(d); fr = d - k; a = i - k; b = a - 1
        acc = (y[a] * (1 - fr) + y[b] * fr) if b >= 0 else 0.0
        y[i] = x[i] - g * acc
    return y
def _ffbb(x, D, g):                  # 前から削って後ろからも削る＝ずれ無し
    y = _comb(x, D, g); y = _comb(y[::-1], D[::-1], g); return y[::-1]
def _kiri(x, D):                     # 前後 D の平均を引く → SR/D の倍数を消す（ずれ無し）
    n = len(x); y = [0.0] * n
    for i in range(n):
        d = D[i]; k = int(d); fr = d - k
        a = i - k; b = a - 1; c = i + k; e = c + 1
        p = (x[a] * (1 - fr) + x[b] * fr) if b >= 0 else 0.0
        q = (x[c] * (1 - fr) + x[e] * fr) if e < n else 0.0
        y[i] = x[i] - 0.5 * (p + q)
    return y
def _heikin(x, W):                   # 幅 W の中心平均（ずれ無し）、W は時間で変わってよい
    n = len(x); cs = [0.0] * (n + 1)
    for i in range(n): cs[i + 1] = cs[i] + x[i]
    y = [0.0] * n
    for i in range(n):
        h = max(1, int(W[i] / 2)); a = max(0, i - h); b = min(n, i + h + 1); y[i] = (cs[b] - cs[a]) / (b - a)
    return y
CFG = {"causal": False}
KIRI_GAIN = {3: 1.5, 5: 0.691, 7: 0.377}   # 1 - cos(2π/k)：山 F での残り具合（定数）
def yama_bp(x, F, g=0.7, p_low=3, p_high=2):
    """山一つだけ残す帯：くびれで F の奇数倍を立て、2F で消える平均を重ねて上を削り、F/2 で消える広い平均を引いて下を削る。"""
    F = [f / 0.95 for f in F]                          # 平均で山が 5% 下がる分の補正
    D_ = [SR / (2 * f) for f in F]
    bp = _comb(_comb(x, D_, g), D_, g) if CFG["causal"] else _ffbb(x, D_, g); norm = (1 - g) ** 2   # 114：causal＝前向きに二度削る（強さの形は同じ、尾は後ろだけ）
    for _ in range(p_low):
        bp = _heikin(bp, [SR / (2 * f) for f in F]); norm /= 0.6366
    for _ in range(p_high):
        w = _heikin(bp, [2 * SR / f for f in F]); bp = [bp[i] - w[i] for i in range(len(bp))]
    return [v * norm for v in bp]

YAMA = {"a": (850, 1350, 2900), "i": (330, 2800, 3400), "u": (370, 1600, 2700), "e": (530, 2300, 3000), "o": (500, 900, 2900)}  # 女の人の日本語の母音の山（Hz）
LOCUS = {"k": 2000, "t": 1800, "p": 900, "s": 1800, "sh": 2300, "m": 1000, "n": 1700}   # 子音から母音へ入るときの F2 の出どころ
def yama_tracks(spans, n, Y):
    T = [[0.0] * n for _ in range(3)]; tr = int(Y.get("locus_ms", 50) * SR / 1000)
    for k, (a, b, *_ ) in enumerate(spans):
        v = YAMA[VSEQ[k % len(VSEQ)]]; L = LOCUS.get(SEQ[k % len(SEQ)])
        for i in range(a, n):
            for j in range(3): T[j][i] = v[j]
        if L and Y.get("locus", True):
            for i in range(a, min(n, a + tr)):
                w = 1 - (i - a) / tr; T[1][i] = w * L + (1 - w) * v[1]; T[0][i] = w * 300 + (1 - w) * v[0]
    a0 = spans[0][0]
    for j in range(3):
        T[j][:a0] = [T[j][a0]] * a0
        T[j] = _heikin(T[j], [Y.get("glide_ms", 30) * SR / 1000] * n)
    return T

# ---- recipe ----
# STK Exp 7/9 (poidowl/stk RESULTS.md): 兄弟の好きな二人（つむぎ・花丸）に共通なのは声でなく節回し（プロソディ）。
#   速い 7.6-8.0 拍/秒 / 拍の長さに緩急 (CV ~0.39) / 高さの動き 9-11 半音 / 出だしが約5.6半音跳ねる / 語尾を約1.45倍伸ばす
# 58 は 2.5 拍/秒くらい、動き 4 半音、全部同じ形。ここを一つずつ変える。
SR_ = SR
BASE = {
    "seed": 1113, "length_s": 6.0,
    "line": {"D_center": 34.0, "D_haba": 6.0, "osoi_s": 0.07, "g": 0.993, "m": 3, "ara_w": 3, "ara_p": 2, "karuku_w": 60, "gain": 1.0},
    "breath": {"sabun_w1": 2, "sabun_w2": 7, "karuku_w": 40, "gain": 0.12, "tail_extra_ms": 40},
    "attack": {"burst_ms": 12, "keep_ms": 30, "D_from": 110.0, "D_to": 28.0, "sweep_ms": 20, "g": 0.95, "m": 2, "gain": 1.1},
    "pieces": {"phrases": [3, 4, 2, 5, 4], "dur_ms": [160, 520], "gap_ms": [60, 200], "phrase_gap_ms": [450, 900],
               "head_ms": 18, "tail_ms": 110, "magari": 1.6,
               "tempo": None, "kankyu": None, "gobi": 1.0},
    "tegagen": {"types": []},
    "fushi": {"mode": "58", "offsets": [-3.0, 3.5, -1.0, 4.5, 0.5, -2.0, 5.0, 2.0, -4.0],
              "haneru_st": 5.6, "kudari_st": 4.0, "sagari_st": 1.5, "owari_st": -2.5, "glide_ms": 30},
}
KANKYU = [1.35, 0.7, 1.0, 1.6, 0.65, 0.9, 1.25, 0.6, 1.1, 1.45, 0.75, 0.95]   # 拍の長さの緩急（手で並べた倍率）

def spans_of(rc, n, r):
    P = rc["pieces"]; out = []; t = int(0.06 * SR); k = 0
    for pi, q in enumerate(P["phrases"]):
        for j in range(q):
            if P["tempo"]:
                d = 1000.0 / P["tempo"] * (KANKYU[k % len(KANKYU)] if P["kankyu"] else 1.0); g_ = P.get("gap_t_ms", 8.0)
            else:
                d = r.uniform(*P["dur_ms"]); g_ = r.uniform(*P["gap_ms"])
            if j == q - 1: d *= P["gobi"]
            a = t; b = t + int(d * SR / 1000)
            if b > n - int(0.05 * SR): return out
            out.append((a, b, pi, j, q)); t = b + int(g_ * SR / 1000); k += 1
        t += int((r.uniform(*P["phrase_gap_ms"]) if not P["tempo"] else r.uniform(*P.get("ma_ms", [140, 260]))) * SR / 1000)
    return out

def st_of(rc, k, pi, j, q):          # その拍の高さ（半音、上が正）
    F = rc["fushi"]
    if F["mode"] == "58": return -F["offsets"][k % len(F["offsets"])] * 0.5      # 58 と同じ並び（D のずれ ≒ 半音の半分）
    base = -F["sagari_st"] * pi                                                  # 句ごとに少しずつ下がる
    if j == 0: return base                                                       # 句の頭は低く
    if j == q - 1: return base + F["owari_st"]                                    # 句の尻は下げて終わる
    return base + F["haneru_st"] - F["kudari_st"] * (j - 1) / max(1, q - 2)      # 2拍目で跳ね上がって下り坂

def make(rc):
    if rc.get("text"): return make_text(rc)          # 75：仮名の文を読む道
    n = int(rc["length_s"] * SR)
    r_line = random.Random(rc["seed"]); r_wander = random.Random(rc["seed"] + 1)
    r_breath = random.Random(rc["seed"] + 2); r_att = random.Random(rc["seed"] + 3); r_piece = random.Random(rc["seed"] + 4)
    P = rc["pieces"]; L = rc["line"]; B = rc["breath"]; A = rc["attack"]; F = rc["fushi"]
    spans = spans_of(rc, n, r_piece)
    T = rc.get("tegagen", {"types": []}); HA = [0.0] * n; HK = [0.0] * n; pre = [0] * len(spans)
    for k, (a, b, pi, j, q) in enumerate(spans):
        kind = SEQ[k % len(SEQ)]; cls = kind_class(kind)
        if cls not in T["types"]: continue
        if kind in rc.get("fric", {}).get("kinds", []) and not rc["fric"].get("overlay"): continue
        if cls == "masatsu":          # さ・しゃ・は：頭 70ms のくびれを緩め、さ・しゃは粗削りも緩める
            ln = int(T.get("nagasa", 0.07) * SR); pre[k] = ln // 2
            for i in range(max(0, a - ln // 2), min(n, a + ln // 2)):
                u = 1.0 - max(0.0, (i - a) / (ln / 2))     # 頭で 1、母音へ向けて 0
                HK[i] = max(HK[i], T.get("tsuyosa", 1.0) * min(1.0, u)); 
                if kind != "h": HA[i] = max(HA[i], T.get("tsuyosa", 1.0) * min(1.0, u))
        elif cls == "haretsu":        # か・た・ぱ：閉じ 30ms のあと 12ms だけ全部のノミを緩めた生ノイズを残す
            ln = int(T.get("nagasa", 0.07) / 6 * SR); pre[k] = 0
            for i in range(a, min(n, a + ln)):
                HK[i] = T.get("tsuyosa", 1.0); HA[i] = T.get("tsuyosa", 1.0) * (1.0 if kind != "p" else 0.3)
        elif cls == "hana":           # ま・な：頭 60ms は逆に粗削りを強める代わりに、くびれだけ少し緩める
            ln = int(0.06 * SR); pre[k] = 0
            for i in range(a, min(n, a + ln)): HK[i] = max(HK[i], 0.35)
    HA = arakezuri(HA, int(0.004 * SR)); HK = arakezuri(HK, int(0.004 * SR))
    wander = furafura(n, r_wander, 0.0, L["D_haba"] * (0.5 if F["mode"] != "58" else 1.0), L["osoi_s"])
    st = [0.0] * n
    for k, (a, b, pi, j, q) in enumerate(spans):
        v = st_of(rc, k, pi, j, q)
        for i in range(a, n): st[i] = v
    st = arakezuri(st, max(1, int(F["glide_ms"] * SR / 1000)))
    D = [L["D_center"] * 2 ** (-st[i] / 12) + wander[i] for i in range(n)]
    Z = rc.get("tadayoi", 0.0)
    if Z:                               # 69：高さを拍の中でも止めない。ノイズを 50ms で二度均した漂いで D を動かす（STK Exp 14）
        r_z = random.Random(rc["seed"] + 8); z = arakezuri(noise(r_z, n), int(0.05 * SR), 2)
        zm = sum(z) / n; zs = (sum((v - zm) ** 2 for v in z) / n) ** 0.5 or 1.0
        D = [D[i] * 2 ** (-Z * (z[i] - zm) / zs / 12) for i in range(n)]
    J = rc.get("yure_hayai", 0.0)
    if J:                               # 速い揺らぎ：周期ごとに D を少しだけデタラメにずらす（均さない）
        r_j = random.Random(rc["seed"] + 7); i = 0
        while i < n:
            f = 1 + r_j.uniform(-1, 1) * J; per = int(2 * D[i])
            for k in range(i, min(n, i + per)): D[k] *= f
            i += max(2, per)
    PER = [2 * d for d in D]
    x = karuku(arakezuri_t(noise(r_line, n), L["ara_w"], L["ara_p"], HA), L["karuku_w"])
    K = rc.get("kugiri", {"on": False})
    if K.get("tsubu"):                  # 同じ粒：ノイズから一粒だけ削り出し、周期ごとに置く（毎回同じ形＝澄む）
        r_k = random.Random(rc["seed"] + 6); G = K["tsubu"]
        grain = arakezuri(noise(r_k, G * 3), K["ara"], 3)[G:2 * G]
        gm = sum(grain) / G; grain = [v - gm for v in grain]
        grain = kiridashi(grain, 0, G, G // 4, G // 2, 1.5)
        y = [0.0] * n; i = 0
        while i < n:
            amp = 1 + r_k.uniform(-1, 1) * K.get("shimmer", 0.0)
            for j in range(G):
                if i + j < n: y[i + j] += grain[j] * amp
            i += max(2, int(PER[min(i, n - 1)] * (1 + r_k.uniform(-1, 1) * K["yure"])))
        if K.get("kurai"): y = arakezuri(y, K["kurai"], 2)
        pk = max(abs(v) for v in y) or 1.0; y = [v / pk for v in y]
        xr = rms(x) or 1.0; yr = rms(y) or 1.0
        x = [y[i] * xr / yr * (1 - HK[i]) + x[i] * HK[i] for i in range(n)]
    elif K["on"]:                         # 区切り：線の周期ごとに、ノイズを keep サンプルだけ残して他は削る（切り出しの細切れ）
        r_k = random.Random(rc["seed"] + 6); keep = K["keep"]; y = [0.0] * n; i = 0
        while i < n:
            for j in range(keep):
                if i + j < n: y[i + j] = x[i + j] * (1 - j / keep)
            per = PER[min(i, n - 1)] * (1 + r_k.uniform(-1, 1) * K["yure"])
            i += max(2, int(per))
        x = [y[i] * (1 - HK[i]) + x[i] * HK[i] for i in range(n)]   # 子音の手加減部分は削らずに残す
    if L.get("n", 2) > 2: line = kubire_n(x, D, [L["g"] * (1 - h) for h in HK], L["m"], L["n"])
    else: line = kubire_t(x, D, [L["g"] * (1 - h) for h in HK], L["m"])
    V = rc.get("boin", {"g": 0.0})
    if V["g"] > 0:                       # 拍ごとの母音：一つ目の山 F1 と二つ目の山 F2 を、それぞれ別のくびれで掘る（65〜68）
        d1 = [0.0] * n; d2 = [0.0] * n
        for k, (a, b, *_ ) in enumerate(spans):
            f1, f2 = BOIN[VSEQ[k % len(VSEQ)]]
            for i in range(max(0, a - int(0.03 * SR)), n): d1[i] = SR / (2 * f1); d2[i] = SR / (2 * f2)
        d1[:spans[0][0]] = [d1[spans[0][0]]] * spans[0][0]; d2[:spans[0][0]] = [d2[spans[0][0]]] * spans[0][0]
        d1 = arakezuri(d1, int(0.03 * SR)); d2 = arakezuri(d2, int(0.03 * SR))
        line = kubire(line, d1, V["g"], V.get("m", 1))             # 引く：山は F1, 3F1, 5F1…
        line = kubire(line, d2, V["g"] * 0.9, V.get("m", 1))
        line = karuku(line, L["karuku_w"])
    Y = rc.get("yama", {"on": False})
    if Y["on"]:                          # 69：母音の山を三つだけ残して、谷を削る（STK Exp 13/14：耳が声と聞く決め手）
        T = yama_tracks(spans, n, Y)
        bps = [yama_bp(line, T[j], Y["g"]) for j in range(3)]
        keep = [bps[0][i] + Y["f2"] * bps[1][i] + Y["f3"] * bps[2][i] for i in range(n)]
        sk = Y.get("shiin_nokosu", 0.0)    # 73：子音の頭（手加減の所）は谷を削り残す＝さ・しゃ・はの高い息が残る
        line = [line[i] - Y["fukasa"] * (1 - sk * HK[i]) * (line[i] - keep[i]) for i in range(n)]
    lc = [0.0] * n; env = [0.0] * n; ones = [1.0] * n
    for k, (a, b, *_ ) in enumerate(spans):
        a0 = max(0, a - pre[k])
        hd = min(int(P["head_ms"] * SR / 1000), (b - a) // 4); tl = min(int(P["tail_ms"] * SR / 1000), (b - a) // 2)
        if pre[k]: hd = max(hd, pre[k] // 2)
        FR = rc.get("fric", {}); kd = SEQ[k % len(SEQ)]
        if kd in FR.get("kinds", []) and kd not in ("m", "n") and not (FR.get("overlay") and kd in ("s", "sh", "h")):
            a0 = a + int((FR.get("vot_ms", 12) if kd in ("k", "t", "p") else FR.get("in_ms", 40)) * SR / 1000); hd = int(FR.get("line_head_ms", 20) * SR / 1000)
        seg = kiridashi(ones, a0, b, hd, tl, P["magari"])
        if kind_class(SEQ[k % len(SEQ)]) == "hana" and rc.get("hana_db"):   # 69：ま・なの頭 50ms を 5dB 下げて、母音へ上げる
            hn = int(0.05 * SR); lo = 10 ** (-rc["hana_db"] / 20)
            for i in range(a0, min(b, a0 + hn)): seg[i] *= lo + (1 - lo) * max(0.0, (i - a0 - hn * 0.6) / (hn * 0.4))
        for i in range(a0, b): env[i] += seg[i]
    FL = P.get("floor", 0.0)
    if FL > 0:
        ph = {}
        for a, b, pi, *_ in spans: ph.setdefault(pi, [a, b]); ph[pi][1] = b
        for pi, (a, b) in ph.items():
            pe = kiridashi(ones, a, b, int(P["head_ms"] * SR / 1000), int(P["tail_ms"] * SR / 1000), P["magari"])
            for i in range(a, b): env[i] = max(env[i], FL * pe[i])
    if P.get("env_ms"): env = _heikin(env, [P["env_ms"] * SR / 1000] * n)
    for i in range(n): lc[i] = line[i] * env[i]
    for k, (a, b, *_ ) in enumerate(spans):
        if kind_class(SEQ[k % len(SEQ)]) == "haretsu" and kind_class(SEQ[k % len(SEQ)]) in rc.get("tegagen", {"types": []})["types"]:
            for i in range(max(0, a - int(0.03 * SR)), a): lc[i] = 0.0     # 閉じ（削り切る）
            for i in range(a, min(n, a + int(0.012 * SR))): lc[i] = line[i] * 0.9   # 生ノイズの一瞬は切り出しも緩める
    lc = scale(lc, L["gain"] / (rms(lc) or 1.0))
    FR = rc.get("fric", {})
    if FR.get("kinds"):                 # 73f：さ・しゃ・は・か・たの頭を、別に削ったノイズの層で置く（引き算だけ）
        r_f = random.Random(rc["seed"] + 9)
        for k, (a, b, *_ ) in enumerate(spans):
            kd = SEQ[k % len(SEQ)]
            if kd not in FR["kinds"]: continue
            if kd in ("m", "n"):          # ま・な：拍の前を浅く沈める（閉じ）だけ
                cl = int(FR.get("nasal_ms", 25) * SR / 1000)
                for i in range(max(0, a - cl), a): lc[i] *= FR.get("nasal_keep", 0.3)
                continue
            if kd in ("k", "t", "p"):
                cl = int(FR.get("closure_ms", 25) * SR / 1000)
                for i in range(max(0, a - cl), a): lc[i] *= FR.get("closure_keep", 0.0)
                bl = int(FR.get("burst_ms", 12) * SR / 1000); fs = a
                x0 = noise(r_f, bl + 400)
                if kd == "k": y = yama_bp(x0, [FR.get("k_hz", 2000)] * len(x0), 0.7)[200:200 + bl]
                else: y = arakezuri(fwd(x0, FR.get("t_D", 3)), 2)[200:200 + bl]
                y = kiridashi(y, 0, bl, max(1, bl // 6), bl // 2, 1.5); g = FR.get("gain_" + kd, 0.3)
                for i in range(bl):
                    if fs + i < n: lc[fs + i] = lc[fs + i] * FR.get("burst_line", 0.0) + y[i] * g / (rms(y) or 1.0)
                continue
            pr = int(FR.get("pre_ms", 30) * SR / 1000); inn = int(FR.get("in_ms", 40) * SR / 1000); ln = pr + inn + int(FR.get("ov_ms", 20) * SR / 1000)
            fs = max(0, a - pr); x0 = noise(r_f, ln + 400)
            if kd == "s": y = arakezuri(fwd(x0, FR.get("s_D", 3)), FR.get("s_ma", 2))
            elif kd == "sh": y = arakezuri(fwd(x0, FR.get("sh_D", 6)), FR.get("sh_ma", 4))
            else:
                v = YAMA[VSEQ[k % len(VSEQ)]]; Y = rc["yama"]; bp = [yama_bp(x0, [f] * len(x0), Y["g"]) for f in v]
                y = [bp[0][i] + Y["f2"] * bp[1][i] + Y["f3"] * bp[2][i] for i in range(len(x0))]
            y = y[200:200 + ln]; y = [v_ / (rms(y) or 1.0) * FR.get("gain_" + kd, 0.3) for v_ in y]
            y = kiridashi(y, 0, ln, int(FR.get("f_head_ms", 25) * SR / 1000), int(FR.get("f_tail_ms", 30) * SR / 1000), 1.0)
            for i in range(ln):
                if fs + i < n:
                    if i < pr and not FR.get("overlay"): lc[fs + i] *= FR.get("prev_keep", 1.0) if i < pr // 2 else FR.get("prev_keep", 1.0) * (1 - (i - pr // 2) / max(1, pr - pr // 2))
                    lc[fs + i] += y[i]
    bx = karuku(sabun(noise(r_breath, n), B["sabun_w1"], B["sabun_w2"]), B["karuku_w"]); ex = int(B["tail_extra_ms"] * SR / 1000)
    bc = [0.0] * n
    for a, b, *_ in spans:
        hd = min(int(P["head_ms"] * SR / 1000), (b - a) // 4); tl = min(int(P["tail_ms"] * SR / 1000), (b - a) // 2)
        seg = kiridashi(bx, a, min(n, b + ex), hd * 2, tl + ex, P["magari"])
        for i in range(a, min(n, b + ex)): bc[i] += seg[i]
    bc = scale(bc, B["gain"] / (rms(bc) or 1.0))
    ac = [0.0] * n
    kn = int(A["keep_ms"] * SR / 1000); bn = int(A["burst_ms"] * SR / 1000); sw = int(A["sweep_ms"] * SR / 1000)
    for a, b, *_ in spans:
        burst = kiridashi(noise(r_att, kn), 0, bn, 8, bn // 2, 1.0)
        Da = [A["D_from"] + (A["D_to"] - A["D_from"]) * min(1.0, i / sw) for i in range(kn)]
        y = kiridashi(kubire(burst, Da, A["g"], A["m"]), 0, kn, 6, kn // 2, 1.5); r = rms(y) or 1.0
        for i in range(kn):
            if a + i < n: ac[a + i] += y[i] * A["gain"] / r
    mix = [lc[i] + bc[i] + ac[i] for i in range(n)]
    last = max(b for a, b, *_ in spans) + int(0.3 * SR); mix = mix[:min(n, last)]
    pk = max(abs(v) for v in mix) or 1.0
    return [v * 0.891 / pk for v in mix], spans

def write(path, x):
    a = array.array("h", [max(-32767, min(32767, int(round(v * 32767)))) for v in x])
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(a.tobytes())
    if LAST_CHOIR_PARTS and len(LAST_CHOIR_PARTS[0]["wav"]) == len(x) and path.endswith(".wav"):
        n_s = len(x)
        st_l = [0.0] * n_s
        st_r = [0.0] * n_s
        for p_info in LAST_CHOIR_PARTS:
            pw = p_info["wav"]
            pl, pr = p_info["pan"]
            for i in range(n_s):
                st_l[i] += pw[i] * pl
                st_r[i] += pw[i] * pr
        pk_st = max(max(abs(v) for v in st_l), max(abs(v) for v in st_r)) or 1.0
        sc_st = 0.891 / pk_st
        inter = array.array("h", [0] * (n_s * 2))
        for i in range(n_s):
            inter[2 * i] = max(-32767, min(32767, int(round(st_l[i] * sc_st * 32767))))
            inter[2 * i + 1] = max(-32767, min(32767, int(round(st_r[i] * sc_st * 32767))))
        st_path = path[:-4] + "_stereo4.wav"
        with wave.open(st_path, "wb") as w2:
            w2.setnchannels(2); w2.setsampwidth(2); w2.setframerate(SR); w2.writeframes(inter.tobytes())

def variant(changes):
    rc = json.loads(json.dumps(BASE)); changes = json.loads(json.dumps(changes))   # 73f：入れ子の辞書を共有しない（E73F の FRIC が書き換わっていた）
    for path, val in changes.items():
        d = rc; ks = path.split(".")
        for kk in ks[:-1]: d = d[kk]
        d[ks[-1]] = val
    return rc

SEQ = ["k", "a", "s", "t", "m", "h", "sh", "n", "p", "t", "a", "k", "s", "n", "h", "t", "m", "k"]
def kind_class(k): return {"t": "haretsu", "k": "haretsu", "p": "haretsu", "s": "masatsu", "sh": "masatsu", "h": "masatsu", "m": "hana", "n": "hana"}.get(k, "")
ALL61 = {"pieces.tempo": 7.8, "pieces.kankyu": True, "fushi.mode": "kawaii", "pieces.gobi": 1.45}
FILES = []
FILES.append(("1.wav", dict(ALL61), "61の5（手加減なし）"))
FILES.append(("2.wav", dict(ALL61, tegagen={"types": ["masatsu"]}), "さ・しゃ・は：頭のくびれ（と粗削り）を緩める"))
FILES.append(("3.wav", dict(ALL61, tegagen={"types": ["haretsu"]}), "か・た・ぱ：閉じのあと一瞬だけノミを全部緩める"))
FILES.append(("4.wav", dict(ALL61, tegagen={"types": ["hana"]}), "ま・な：頭のくびれを少しだけ緩める"))
FILES.append(("5.wav", dict(ALL61, tegagen={"types": ["masatsu", "haretsu", "hana"]}), "ぜんぶ"))

BOIN = {"a": (1000, 1400), "i": (300, 3200), "u": (350, 1300), "e": (550, 2600), "o": (500, 850)}   # 拍の母音の山（Hz）。母音どうしを大きく離した
VSEQ = ["a", "i", "u", "e", "o", "a", "i", "a", "u", "o", "e", "i", "a", "o", "u", "e", "a", "i"]
TG = {"types": ["masatsu", "haretsu"], "tsuyosa": 1.0, "nagasa": 0.11}
DK = {"line.ara_w": 8, "line.ara_p": 4}
D44 = {"line.D_center": 44.0}   # 線の高さ 約400Hz（STK の聞き比べ1で兄弟が選んだ11番の高さ）
BV = {"g": 0.9, "m": 3}
TB = {"on": True, "tsubu": 120, "ara": 16, "yure": 0.03, "shimmer": 0.1, "kurai": 8}
TB2 = dict(TB, shimmer=0.05)
FILES = [("1.wav", dict(ALL61, tegagen=TG, boin=BV, kugiri=TB, yure_hayai=0.04, **DK, **D44), "67の3"),
         ("2.wav", dict(ALL61, tegagen=TG, boin=BV, kugiri=TB2, yure_hayai=0.04, **{"breath.gain": 0.05}, **DK, **D44), "息を半分以下に"),
         ("3.wav", dict(ALL61, tegagen=TG, boin=BV, kugiri=dict(TB2, tsubu=160, ara=20), yure_hayai=0.04, **{"breath.gain": 0.02}, **DK, **D44), "息をほぼ無しに＋粒を大きく")]

YM = {"on": True, "g": 0.7, "fukasa": 0.95, "f2": 0.6, "f3": 0.37, "glide_ms": 30, "locus": True, "locus_ms": 50}
B68 = dict(ALL61, tegagen=TG, kugiri=dict(TB2, tsubu=160, ara=20), yure_hayai=0.04, **{"breath.gain": 0.02}, **DK, **D44)
FILES = [("1.wav", dict(B68, boin=BV), "68の3"),
         ("2.wav", dict(B68, yama=YM), "母音の山を三つだけ残して谷を削る（くびれの母音は外す）"),
         ("3.wav", dict(B68, yama=dict(YM, fukasa=0.99)), "谷をもっと深く"),
         ("4.wav", dict(B68, yama=dict(YM, locus=False)), "子音からの入り（F2の出どころ）なし"),
         ("5.wav", dict(B68, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0), yama=YM), "粒を細かく（元を明るく）＋山"),
         ("6.wav", dict(B68, kugiri=dict(TB2, tsubu=80, ara=6, kurai=0), yama=YM), "粒を中くらい＋山"),
         ("7.wav", dict(B68, kugiri={"on": False}, yama=YM), "粒なし（ノイズの線のまま）＋山"),
         ("8.wav", dict(B68, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0), yama=dict(YM, fukasa=0.995)), "粒を細かく＋谷を深く"),
         ("9.wav", dict(B68, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0), yama=dict(YM, fukasa=0.995), **{"attack.gain": 0.0}), "8＋拍頭のピュン無し"),
         ("10.wav", dict(B68, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0), yama=dict(YM, fukasa=0.995), **{"fushi.glide_ms": 90}), "8＋音程をなめらかに"),
         ("11.wav", dict(B68, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0), yama=dict(YM, fukasa=0.995), **{"attack.gain": 0.0, "fushi.glide_ms": 90}), "9＋10")]
E11 = dict(B68, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0), yama=dict(YM, fukasa=0.995), **{"attack.gain": 0.0, "fushi.glide_ms": 90})
FILES += [("12.wav", dict(E11, **{"breath.gain": 0.06}), "11＋息を少し戻す"),
          ("13.wav", dict(E11, **{"fushi.glide_ms": 150}), "11＋音程をもっとなめらかに"),
          ("14.wav", dict(E11, yama=dict(YM, fukasa=0.995, f3=0.6)), "11＋三つ目の山を強く"),
          ("15.wav", dict(E11, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0, yure=0.06)), "11＋周期の揺れを倍")]
E15 = dict(E11, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0, yure=0.06))
FILES += [("16.wav", dict(E15, **{"breath.gain": 0.06}), "15＋息を少し戻す"),
          ("17.wav", dict(E15, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0, yure=0.1)), "揺れを 0.1"),
          ("18.wav", dict(E15, kugiri=dict(TB2, tsubu=40, ara=3, kurai=0, yure=0.06, shimmer=0.2)), "15＋粒の大きさも揺らす"),
          ("19.wav", dict(E15, seed=2024), "15 を別の種で（たまたまでないか）")]
FILES = FILES[-4:]

E16 = dict(E15, **{"breath.gain": 0.06})
FILES = [("20.wav", dict(E16, tadayoi=1.3), "16＋高さの漂い"),
         ("21.wav", dict(E16, tadayoi=1.3, **{"fushi.glide_ms": 150}), "20＋段をもっとなめらかに"),
         ("22.wav", dict(E16, tadayoi=1.3, **{"pieces.ma_ms": [400, 600]}), "20＋句の間を長く"),
         ("23.wav", dict(E16, tadayoi=1.3, hana_db=5, **{"pieces.ma_ms": [400, 600]}), "22＋ま・なの頭を下げる"),
         ("24.wav", dict(E16, tadayoi=1.3, hana_db=5, seed=2024, **{"pieces.ma_ms": [400, 600]}), "23 を別の種で"),
         ("25.wav", dict(E16, tadayoi=1.3, hana_db=5, seed=7, **{"pieces.ma_ms": [400, 600]}), "23 をもう一つ別の種で")]

FILES = [("26.wav", dict(E16, tadayoi=1.3, seed=2024), "20 を別の種で"),
         ("27.wav", dict(E16, tadayoi=1.3, seed=7), "20 をもう一つ別の種で"),
         ("28.wav", dict(E16, seed=7), "16 を種7で（漂いの効き目を同じ種で比べる）")]

FILES = [("29.wav", dict(B68, boin=BV, seed=2024), "68の3 を種2024で"), ("30.wav", dict(B68, boin=BV, seed=7), "68の3 を種7で")]

E23 = dict(E16, tadayoi=1.3, hana_db=5, **{"pieces.ma_ms": [400, 600]})
FILES = [("1.wav", dict(E23), "69：母音の山を三つ残す＋高さの漂い＋句の間＋ま・なの頭"),
         ("2.wav", dict(E23, seed=2024), "1 を別の乱数で"),
         ("3.wav", dict(E23, seed=7), "1 をもう一つ別の乱数で")]

E70 = dict(E23, tegagen=dict(TG, types=["masatsu"]), yama=dict(YM, fukasa=0.999, g=0.82, f2=0.5, f3=0.25),
           **{"line.n": 4, "line.g": 0.6, "line.m": 1, "pieces.head_ms": 30, "pieces.tail_ms": 50, "pieces.magari": 1.0, "pieces.phrases": [2, 3, 2, 4, 3, 2, 3]})
FILES = [("1.wav", dict(E70), "70"), ("2.wav", dict(E70, seed=2024), "70 別の乱数"), ("3.wav", dict(E70, seed=7), "70 もう一つ別の乱数")]

E72 = dict(E70, kugiri=dict(E70["kugiri"], yure=0.01), yure_hayai=0.01, **{"line.D_center": 39.4})
FILES = [("1.wav", dict(E70, seed=2024, **{"line.D_center": 39.4}), "71の2（430Hz・揺れ6%）"),
         ("2.wav", dict(E72, seed=2024), "72：430Hz・揺れ1%"),
         ("3.wav", dict(E72, seed=2024, **{"line.D_center": 35.3}), "72 を 480Hz で"),
         ("4.wav", dict(E72, seed=7), "72 を別の乱数で")]
FRIC = {"kinds": ["s", "sh", "h"], "pre_ms": 30, "in_ms": 45, "ov_ms": 20, "line_head_ms": 20, "f_head_ms": 25, "f_tail_ms": 30,
        "gain_s": 0.35, "gain_sh": 0.35, "gain_h": 0.25, "s_D": 3, "s_ma": 2, "sh_D": 5, "sh_ma": 3, "prev_keep": 1.0,
        "closure_ms": 25, "closure_keep": 0.0, "burst_ms": 12, "vot_ms": 15, "burst_line": 0.0, "gain_k": 0.4, "gain_t": 0.4, "k_hz": 2000, "t_D": 3}
E73F = dict(E72, fric=FRIC)
# 73f の結論：さ・しゃ・は の別層は silero を下げた。効いたのは か・た・ぱ の閉じ（25ms 削り切る）＋形を付けた小さな破裂（VAD 0.13→0.22）
E73K = dict(E73F, fric=dict(FRIC, kinds=["k", "t", "p"], gain_k=0.2, gain_t=0.2, gain_p=0.3))

# combo: 4 searches stacked
S0 = {'fushi.sagari_st': 0.0, 'line.D_center': 50.6}
TL = {'yama.locus': False, 'yama.glide_ms': 3}
RT = {'pieces.tempo': 8.5, 'pieces.env_ms': 20}
E74 = dict(E73K, **TL, **{'fushi.sagari_st': 0.0, 'line.D_center': 53.1, 'pieces.env_ms': 20})   # ~410 Hz: VAD 0.36
E74L = dict(E73K, **TL, **{'fushi.sagari_st': 0.0, 'line.D_center': 60.4, 'pieces.env_ms': 20})  # ~360 Hz: VAD 0.48

# ---- 75：仮名の文を読む（kotoba.py の規則が出す山の道筋・山ごとの強さ・息の帯・声のあり／なし・大きさで削る） ----
# 材料は白いノイズだけ。ノミは今までと同じ（平均・自分を遅らせて引く・時間で変わる強さ・切り出し・別に削った層を混ぜる）。
# 層ごとの強さは「WORLD で鳴らしたときの、その層（山一つ／床／帯）のこまごとのエネルギー」に合わせる（時間で変わる強さ）。
import math, cmath, sys as _sys
_sys.path.insert(0, OUT); import kotoba
import accent

def _per_sample(fr, N, fp_ms=5.0):     # 5 ms のこまを線形に結んで一サンプルごとに
    n = len(fr); step = 1000.0 / (fp_ms * SR); out = [0.0] * N
    for i in range(N):
        t = i * step; k = int(t)
        if k >= n - 1: out[i] = fr[-1]
        else: u = t - k; out[i] = fr[k] * (1 - u) + fr[k + 1] * u
    return out

WG = (3.0, 2.5, 2.0); WW = (200.0, 300.0, 400.0)   # WORLD 診断器の山の高さ（ln 振幅）と幅（Hz）
def _world_energy(r, gk=1.0):
    """こまごとに、床・山1〜3・帯それぞれのエネルギー（WORLD 診断器のスペクトル包絡 exp(2(L+tilt)) を周波数で足したもの）"""
    n = r["n"]; fg = list(range(25, 11000, 50)); t2 = [math.exp(-2 * f / 2500.0) for f in fg]
    Ef = sum(t2); Ej = [[0.0] * n for _ in range(3)]; F = (r["F1"], r["F2"], r["F3"]); G = (r["G1"], r["G2"], r["G3"])
    for t in range(n):
        for j in range(3):
            c = F[j][t]; a = G[j][t] * WG[j] * gk; w = WW[j]; s = 0.0
            for q, f in enumerate(fg):
                if abs(f - c) < 4 * w: s += t2[q] * (math.exp(2 * a * math.exp(-0.5 * ((f - c) / w) ** 2)) - 1.0)
            Ej[j][t] = s
    Eb = []
    for (t0, t1, cen, sd, lev) in r["bands"]:
        a, b = int(round(t0 * 1000 / kotoba.FP)), int(round(t1 * 1000 / kotoba.FP)); e = [0.0] * n
        for t in range(max(0, a), min(n, b)):
            s = 0.0
            for q, f in enumerate(fg):
                Lb = lev * math.exp(-0.5 * ((f - cen) / sd) ** 2)
                Lv = sum(G[j][t] * WG[j] * gk * math.exp(-0.5 * ((f - F[j][t]) / WW[j]) ** 2) for j in range(3))
                if Lb > Lv: s += t2[q] * (math.exp(2 * Lb) - math.exp(2 * Lv))
            e[t] = s
        Eb.append(e)
    return Ef, Ej, Eb

def _agc(x, target, win, sm=0):       # 時間で変わる強さ：短い区間の大きさを target に合わせる（76：sm>0 なら強さ自体を幅 sm で均す）
    N = len(x); p = _heikin([v * v for v in x], [win] * N); eps = 1e-6 * (sum(p) / N) + 1e-30
    g = [target[i] / math.sqrt(p[i] + eps) for i in range(N)]
    if sm: g = _heikin(_heikin(g, [sm] * N), [sm] * N)
    return [x[i] * g[i] for i in range(N)]

def _band(rng, n, cen, sd, KT):        # 帯：新しいノイズから、中心 cen の山一つだけ削り出す（引き算だけ）
    x0 = noise(rng, n + 800)
    g = KT["band_g"] if not isinstance(KT["band_g"], dict) else KT["band_g"].get(int(cen), 0.5)
    y = yama_bp(x0, [cen] * len(x0), g, KT.get("band_plow", 1), KT.get("band_phigh", 2))[400:400 + n]
    r_ = rms(y) or 1.0; return [v / r_ for v in y]

def _phrase_st(rc, moras, N):          # 高さ：句ごとの上がり下がり（73 のかわいい節：2拍目で跳ねて下り坂、句の尻で下げる）
    F = rc["fushi"]; ph = []; cur = []
    for m in moras:
        if m["kind"] == "pau":
            if cur: ph.append(cur); cur = []
        else: cur.append(m)
    if cur: ph.append(cur)
    st = [0.0] * N; first = True
    for p in ph:
        q = len(p)
        for j, m in enumerate(p):
            if j == 0: v = 0.0
            elif j == q - 1: v = F["owari_st"]
            else: v = F["haneru_st"] - F["kudari_st"] * (j - 1) / max(1, q - 2)
            a = int(m["a"] * SR)
            if first: a = 0; first = False
            for i in range(a, N): st[i] = v
    return arakezuri(st, max(1, int(F["glide_ms"] * SR / 1000)), 2)

KTDEF = {"params": None, "g": [0.82, 0.82, 0.82], "floor": 1.0, "bump": [1.0, 1.0, 1.0], "band": 1.0, "band_g": 0.5,
         "xf_ms": 10, "hiss_ara": [2, 1], "agc_ms": 10, "use_dl": False, "gk": 1.0, "breath": 0.0, "line_g": None, "pre": 0.15, "post": 0.2}

def _ap_cascade(x, rng, KT):           # 81：位相だけ回す（振幅は変えない）二次の全域通過フィルタを n 段。中心は lo..hi に散らし、ゆっくり漂わせる
    n_sec = KT["ap_n"]; lo, hi = KT.get("ap_lo", 200.0), KT.get("ap_hi", 6000.0); bw = KT.get("ap_bw", 300.0)
    dr = KT.get("ap_drift", 0.0); H = 32; N = len(x); nb = N // H + 2
    r = math.exp(-math.pi * bw / SR); a2 = r * r
    for _ in range(n_sec):
        fc = lo + (hi - lo) * rng.random()
        if dr:                             # 漂い：ブロックごとのノイズを均した道（±dr の割合）
            w = arakezuri(noise(rng, nb), max(1, int(KT.get("ap_drift_ms", 80) * SR / 1000 / H)), 2)
            pk = max(abs(v) for v in w) or 1.0
            A1 = [-2 * r * math.cos(2 * math.pi * fc * (1 + dr * v / pk) / SR) for v in w]
        else: A1 = [-2 * r * math.cos(2 * math.pi * fc / SR)] * nb
        y = [0.0] * N; x1 = x2 = y1 = y2 = 0.0
        for i in range(N):
            a1 = A1[i // H]; v = x[i]
            o = a2 * v + a1 * x1 + x2 - a1 * y1 - a2 * y2
            x2 = x1; x1 = v; y2 = y1; y1 = o; y[i] = o
        x = y
    return x

# ---- 82b：exp35 henv（人の母音包絡の表を、声の所の 1 kHz より下だけに当てる）の標準ライブラリ版
#   carve の元（src）を、零位相の 2 次バターワース低域（前後二度がけ＝振幅 1/(1+(f/fc)^4)）の差で 1/3 オクターブの帯に分け、
#   帯ごとに 5 ms こまの強さ（表 − 元の長い平均の色）を掛けて足し戻す（強さが一定なら元にぴったり戻る）。
#   その 1 kHz より下を、carve 自身の混ぜの 1 kHz より下と大きさ（20 ms RMS）を合わせて入れ替える。音を作るものは無い：削りと混ぜだけ。
#   KT["henv"] = {"fc":1000,"sm_ms":10,"lev_ms":20,"allv":True}
_HENV_REF = None                         # 外から別の実装を差し込む口。既定は使わない
_HT = None
_HSEL = [None, True]
def _henv_tab():
    global _HT
    if _HSEL[0]:
        import henv_ref; return getattr(henv_ref, _HSEL[0])
    return _HT
def _interp(x, xp, fp):                  # np.interp（xp は増える列）
    if x <= xp[0]: return fp[0]
    if x >= xp[-1]: return fp[-1]
    lo, hi = 0, len(xp) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        if xp[m] <= x: lo = m
        else: hi = m
    u = (x - xp[lo]) / (xp[hi] - xp[lo]); return fp[lo] + u * (fp[hi] - fp[lo])
def _tmpl_db(v, fr, Ft, top, H_LO=300.0):  # exp35 henv._template_db（contrast 1）を周波数の列 fr で
    T = _henv_tab(); G = T["grid_hz"]; D = T["vowels"][v]["db"]; TF = T["vowels"][v]["F"]
    src_ = [0.0] + list(TF) + [12000.0, 24000.0]; dst = [0.0] + list(Ft) + [12000.0 * top, 24000.0 * top]
    if (not _HSEL[1]) or any(dst[i + 1] - dst[i] <= 0 for i in range(len(dst) - 1)): dst = [s_ * top for s_ in src_]   # warp False：表をそのままの周波数で（top 倍だけ）
    lG = [math.log(g) for g in G]; out = []
    for f in fr:
        g = _interp(f, dst, src_); o = _interp(math.log(max(g, 1.0)), lG, D)
        if g > G[-1]: o -= 12.0 * math.log2(g / G[-1])
        if f < H_LO: o -= 24.0 * math.log2(H_LO / max(f, 20.0))
        out.append(o)
    return out
def _gauss_fr(x, sd):                    # 短い列（こま）の正規ならし、端は端の値（mode nearest）
    if sd <= 0: return list(x)
    R = int(4 * sd + 0.5); ker = [math.exp(-0.5 * (k / sd) ** 2) for k in range(-R, R + 1)]; s = sum(ker); ker = [k / s for k in ker]
    n = len(x); return [sum(ker[k + R] * x[min(n - 1, max(0, i + k))] for k in range(-R, R + 1)) for i in range(n)]
def _box(x, W):                          # 幅 W（奇数）の中心平均、端は端の値
    n = len(x); h = W // 2; c = [0.0] * (n + 1); s = 0.0
    for i in range(n): s += x[i]; c[i + 1] = s
    out = [0.0] * n
    for i in range(n):
        a = i - h; b = i + h + 1; ex = 0.0
        if a < 0: ex += -a * x[0]; a = 0
        if b > n: ex += (b - n) * x[-1]; b = n
        out[i] = (c[b] - c[a] + ex) / W
    return out
def _gauss_s(x, sd):                     # 長い列（サンプル）の正規ならし ≈ 3 回の中心平均（分散 (W²-1)/4 = sd²）
    W = int(math.sqrt(4 * sd * sd + 1)) | 1
    for _ in range(3): x = _box(x, W)
    return x
def _lpz(x, fc, SR, order=2):            # バターワース低域を前と後ろから＝零位相、振幅 1/(1+(f/fc)^(2*order))（order 2 または 4）
    K = math.tan(math.pi * fc / SR); qs = [1 / math.sqrt(2)] if order == 2 else [0.5 / math.cos(math.pi / 8), 0.5 / math.cos(3 * math.pi / 8)]
    for rev, Q in [(r_, q_) for r_ in (False, True) for q_ in qs]:
        nm = 1.0 / (1 + K / Q + K * K); b0 = K * K * nm; a1 = 2 * (K * K - 1) * nm; a2 = (1 - K / Q + K * K) * nm
        y = [0.0] * len(x); x1 = x2 = y1 = y2 = 0.0
        rng_ = range(len(x) - 1, -1, -1) if rev else range(len(x))
        for i in rng_:
            v = x[i]; o = b0 * (v + 2 * x1 + x2) - a1 * y1 - a2 * y2; x2 = x1; x1 = v; y2 = y1; y1 = o; y[i] = o
        x = y
    return x
def _fft(a):                             # 基数 2 の FFT（複素数の列、長さ 2 の冪）
    n = len(a); a = list(a); j = 0
    for i in range(1, n):
        b = n >> 1
        while j & b: j ^= b; b >>= 1
        j |= b
        if i < j: a[i], a[j] = a[j], a[i]
    L = 2
    while L <= n:
        w = cmath.exp(-2j * math.pi / L); h = L // 2; tw = [w ** k for k in range(h)]
        for s in range(0, n, L):
            for k in range(h):
                u = a[s + k]; t = a[s + k + h] * tw[k]; a[s + k] = u + t; a[s + k + h] = u - t
        L <<= 1
    return a
def _henv_low(mix, src, r, KT, SR):
    H = dict(sm_ms=15.0, xf_ms=15.0, amt=1.0, vc=False, top=1.15, lev_ms=10.0, lo_gain=1.0, order=4)
    H.update(KT["henv"] if isinstance(KT["henv"], dict) else {})
    if not H.get("fc"): raise ValueError("henv (stdlib): only the band-split mode (fc) is ported")
    N = len(mix); n = r["n"]; fp = r["fp_ms"] / 1000.0; VOW = "aiueo"; fc = H["fc"]
    vid = [0] * n; w = [0.0] * n; lastv = "a"
    for m in r["moras"]:
        a, b, e = int(m["a"] / fp), int(m["b"] / fp), int(m["e"] / fp)
        if m["kind"] == "CV" and m.get("v"):
            lastv = m["v"]
            for t in range(a, min(e + 1, n)): vid[t] = VOW.index(m["v"])
            for t in range(b, min(e, n)): w[t] = 1.0 if r["voiced"][t] else 0.0
            if H["vc"] and m.get("c") in "mnryw":
                for t in range(a, min(b, n)): w[t] = 1.0
        else:
            for t in range(a, min(e + 1, n)): vid[t] = VOW.index(lastv)
    if H.get("allv"): w = [1.0 if v else 0.0 for v in r["voiced"]]
    w = [min(1.0, max(0.0, v * H["amt"])) for v in w]
    pr = _henv_prot(H, r)
    w = [w[t] * pr[t] for t in range(n)]
    # 帯：境 e_k（零位相低域の差）。最後の帯は境より上の残り全部
    ed = H.get("edges") or [150.0 * 2 ** (k / 3.0) for k in range(12)]
    cen = [ed[0] / 1.5] + [math.sqrt(ed[k] * ed[k + 1]) for k in range(len(ed) - 1)] + [ed[-1] * 1.4]
    # 元の長い平均の色（exp35：声の所の STFT の dB 平均を 30 係数のケプストラムで均したもの）を帯の真ん中で
    NF, HOP = 1024, 256; win = [0.5 - 0.5 * math.cos(2 * math.pi * k / NF) for k in range(NF)]
    xp = [src[0]] * 0 + [src[NF // 2 - k] for k in range(NF // 2)] + list(src) + [0.0] * NF   # boundary="even" 相当（頭は鏡）
    acc = [0.0] * (NF // 2 + 1); cnt = 0; nfr = (N + HOP - 1) // HOP + 1
    for j in range(0, nfr, H.get("base_stride", 1)):
        k = min(n - 1, int(round(j * HOP / SR / fp)))
        if w[k] <= 0.5: continue
        X = _fft([xp[j * HOP + q] * win[q] for q in range(NF)]) if j * HOP + NF <= len(xp) else None
        if X is None: continue
        for q in range(NF // 2 + 1): acc[q] += 10 * math.log10(abs(X[q]) ** 2 + 1e-12)
        cnt += 1
    Lb = [v / max(cnt, 1) for v in acc]; Lf = Lb + Lb[-2:0:-1]
    cq = [sum(Lf[q] * math.cos(2 * math.pi * q * c / NF) for q in range(NF)) / NF for c in range(30)]
    base = [cq[0] + 2 * sum(cq[c] * math.cos(2 * math.pi * f / SR * c) for c in range(1, 30)) for f in cen]
    # 表：こまごと（5 ms）に母音の重みを均して混ぜ、F1..F3 の道筋に合わせて伸び縮み
    sd = H["sm_ms"] / r["fp_ms"]; oh = [[1.0 if vid[t] == q else 0.0 for t in range(n)] for q in range(5)]
    oh = [_gauss_fr(o, sd) for o in oh]
    T = [[0.0] * n for _ in cen]
    for t in range(n):
        s_ = sum(oh[q][t] for q in range(5)) or 1.0
        Ft = [r["F1"][t], r["F2"][t] + 1, r["F3"][t] + 2]
        for i in (1, 2): Ft[i] = max(Ft[i], Ft[i - 1])
        for q in range(5):
            wq = oh[q][t] / s_
            if wq < 1e-3: continue
            d = _tmpl_db(VOW[q], cen, Ft, H["top"])
            for i in range(len(cen)): T[i][t] += wq * d[i]
    G = [[10 ** ((v - base[i]) / 20.0) for v in _gauss_fr(T[i], sd)] for i in range(len(cen))]
    # V = Σ 帯 × 強さ
    V = [0.0] * N; prev = None; step = 1.0 / (fp * SR)
    for i in range(len(cen)):
        cur = _lpz(src, ed[i], SR, H.get("order", 2)) if i < len(ed) else None
        if i == 0: band = cur
        elif cur is None: band = [src[s_] - prev[s_] for s_ in range(N)]
        else: band = [cur[s_] - prev[s_] for s_ in range(N)]
        gs = _per_sample(G[i], N, r["fp_ms"])
        for s_ in range(N): V[s_] += gs[s_] * band[s_]
        prev = cur
    xo = 4 if H.get("xp", 4) >= 8 else 2  # exp36a：分け目の次数 xp（4 → 2 次、8 → 4 次の零位相）
    vlo = _lpz(V, fc, SR, xo); mlo = _lpz(mix, fc, SR, xo)
    W20 = max(1, int(0.02 * SR)) | 1
    rm = [math.sqrt(max(v, 0.0)) for v in _box([v * v for v in mlo], W20)]
    rv = [math.sqrt(max(v, 0.0)) for v in _box([v * v for v in vlo], W20)]
    eps = 1e-4 * (max(rv) + 1e-12)
    g = _gauss_s([rm[i] / (rv[i] + eps) for i in range(N)], H["lev_ms"] / 1000.0 * SR / 2)
    ws = _gauss_s(_per_sample(w, N, r["fp_ms"]), H["xf_ms"] / 1000.0 * SR / 2.0)
    lg = H["lo_gain"]
    return [mix[i] + ws[i] * (lg * g[i] * vlo[i] - mlo[i]) for i in range(N)]

# ---- 82b/mdf：exp36 MDF の標準ライブラリ版。低い帯（上の _henv_low）＋上の帯（carve 自身の混ぜを表へ向けて削る面）＋1-4 kHz の揺れ取り
#   KT["henv"] = dict(on=1, fc=800, xp=8, sm_ms=10, lev_ms=50, allv=True, lo_gain=0.8,
#                     up=dict(depth=1.0, top=1.3, b23=6.0, sm_ms=30, lev_ms=30), df=dict(lo=1000, hi=4000, depth=1.0))
#   どれも削り（利得 <= 1、全体の最大で割る）と混ぜだけ。up / df にも cmute・cdil・von_ms（子音・出だしは carve のまま）を置ける（既定なし）
def _henv_prot(H, r):                    # 5 ms こまごとの「当ててよい」重み（1＝当てる、0＝carve のまま）
    n = r["n"]; pr = [1.0] * n
    if H.get("cmute"):                   # 82b：子音のまわり（cm_pad の印）は carve のまま（聞き取りを守る）。cdil ms だけ印を前後に広げる
        cmk = r["cm"]; dl = int(H.get("cdil", 0) / r["fp_ms"])
        if dl: cmk = [max(cmk[max(0, t - dl):t + dl + 1]) for t in range(n)]
        pr = [pr[t] * (1 - H["cmute"] * cmk[t]) for t in range(n)]
    if H.get("von_ms"):                  # 82b：声の出だし（無声・無音のあと）von_ms は carve のまま
        k_ = int(H["von_ms"] / r["fp_ms"]); vo_ = r["voiced"]; run = 0
        for t in range(n):
            run = run + 1 if vo_[t] else 0
            if 0 < run <= k_: pr[t] = 0.0
    return pr
_FFTT = {}
def _fftq(a, inv=False):                 # 基数 2 の FFT（表を覚えておく速い版）。inv：逆（1/n 込み）
    n = len(a)
    if n not in _FFTT:
        br = [0] * n; b = n.bit_length() - 1
        for i in range(n): br[i] = int(format(i, "0%db" % b)[::-1], 2) if b else 0
        _FFTT[n] = (br, [cmath.exp(-2j * math.pi * k / n) for k in range(n // 2)])
    br, tw = _FFTT[n]
    a = [a[i].conjugate() for i in br] if inv else [complex(a[i]) for i in br]
    L = 2
    while L <= n:
        h = L // 2; st = n // L
        if h <= st:                      # 帯の数が多い段：同じ回し因子をまとめて
            for k in range(h):
                wk = tw[k * st]; u = a[k::L]; v = [x * wk for x in a[k + h::L]]
                a[k::L] = [p + q for p, q in zip(u, v)]; a[k + h::L] = [p - q for p, q in zip(u, v)]
        else:
            ws = tw[::st]
            for s in range(0, n, L):
                u = a[s:s + h]; v = [x * w_ for x, w_ in zip(a[s + h:s + L], ws)]
                a[s:s + h] = [p + q for p, q in zip(u, v)]; a[s + h:s + L] = [p - q for p, q in zip(u, v)]
        L <<= 1
    if inv: a = [x.conjugate() / n for x in a]
    return a
def _stft_r(x, NF, HOP):                 # scipy stft(hann, boundary="even", padded=True) の枠（片側 NF/2+1 本、窓の和で割らない）
    N = len(x); h = NF // 2; win = [0.5 - 0.5 * math.cos(2 * math.pi * k / NF) for k in range(NF)]
    e = [x[h - k] for k in range(h)] + list(x) + [x[N - 2 - k] for k in range(h)]
    e += [0.0] * ((-(len(e) - NF) % HOP) % NF); nfr = (len(e) - NF) // HOP + 1; hb = h + 1; Z = []
    for j in range(0, nfr, 2):           # 二つの実の枠を一つの複素 FFT で
        a = e[j * HOP:j * HOP + NF]; b = e[(j + 1) * HOP:(j + 1) * HOP + NF] if j + 1 < nfr else [0.0] * NF
        c = _fftq([complex(a[q] * win[q], b[q] * win[q]) for q in range(NF)])
        cc = [c[0].conjugate()] + [c[NF - k].conjugate() for k in range(1, hb)]
        Z.append([(c[k] + cc[k]) * 0.5 for k in range(hb)])
        if j + 1 < nfr: Z.append([(c[k] - cc[k]) * -0.5j for k in range(hb)])
    return Z, win
def _istft_r(Y1, Y2, NF, HOP, win, N):   # 二つの片側スペクトル列 → 二つの実の信号（scipy istft(boundary=True) と同じ割り算）
    h = NF // 2; nfr = len(Y1); L = (nfr - 1) * HOP + NF; o1 = [0.0] * L; o2 = [0.0] * L; nm = [0.0] * L
    for j in range(nfr):
        a, b = Y1[j], Y2[j]
        full = [a[k] + 1j * b[k] for k in range(h + 1)] + [a[NF - k].conjugate() + 1j * b[NF - k].conjugate() for k in range(h + 1, NF)]
        z = _fftq(full, True); s = j * HOP
        for q in range(NF):
            wq = win[q]; o1[s + q] += wq * z[q].real; o2[s + q] += wq * z[q].imag; nm[s + q] += wq * wq
    y1 = [o1[i] / nm[i] if nm[i] > 1e-10 else o1[i] for i in range(h, h + N)]
    y2 = [o2[i] / nm[i] if nm[i] > 1e-10 else o2[i] for i in range(h, h + N)]
    return y1, y2
def _gauss_fast(x, sd):                  # scipy gaussian_filter1d(mode="nearest", truncate 4) と同じ
    if sd <= 0: return list(x)
    R = int(4 * sd + 0.5); ker = [math.exp(-0.5 * (k / sd) ** 2) for k in range(-R, R + 1)]; s = sum(ker); ker = [k / s for k in ker]
    p = [x[0]] * R + list(x) + [x[-1]] * R; L = 2 * R + 1; mul = float.__mul__
    return [sum(map(mul, ker, p[i:i + L])) for i in range(len(x))]
_OROW = {}
def _henv_up(mix, r, SR, U, fc, xp):     # exp36b up_delta：返すのは足す分 ws·(g·削った上 − carve の上)
    H = dict(depth=1.0, fhi=20000.0, top=1.3, b23=6.0, b23_sd=250.0, q=30, sm_ms=30.0, lev_ms=30.0, xf_ms=15.0); H.update(U)
    flo = H.get("flo", max(fc, 1000.0)); NF, HOP = 1024, 256; hb = NF // 2 + 1; VOW = "aiueo"
    N = len(mix); n = r["n"]; fp = r["fp_ms"] / 1000.0
    vid = [0] * n; lastv = "a"
    for m in r["moras"]:
        a, e = int(m["a"] / fp), int(m["e"] / fp)
        if m["kind"] == "CV" and m.get("v"): lastv = m["v"]
        for t in range(a, min(e + 1, n)): vid[t] = VOW.index(lastv)
    pr = _henv_prot(H, r); w = [(1.0 if (r["voiced"][t] or H.get("uv")) else 0.0) * pr[t] for t in range(n)]   # uv（145 の試し）：声のないこまも手本へ削る
    fr = [k * SR / NF for k in range(hb)]
    Z, win = _stft_r(mix, NF, HOP); nfr = len(Z); S2 = sum(win) ** 2
    kf = [min(n - 1, max(0, int(round(j * HOP / SR / fp)))) for j in range(nfr)]
    oh = [_gauss_fr([1.0 if vid[t] == q else 0.0 for t in range(n)], H["sm_ms"] / 5.0) for q in range(5)]
    T = []
    for j in range(nfr):
        k = kf[j]; s_ = sum(oh[q][k] for q in range(5)) or 1.0; row = [0.0] * hb
        if H.get("orow"):   # 142 測り専用：こまごとの手本の形（dB、5ms こま、同じ周波数の刻み）を表の代わりに使う。削りの作りが動く形を追えるかの確かめで、成果物には使わん
            if _OROW.get("n") != n:   # orow は道一つ、または道の並び（文ごと）。並びなら長さがこの文に一番近い物を使う
                import json as _j; ps_ = H["orow"] if isinstance(H["orow"], list) else [H["orow"]]; cs_ = [_j.load(open(p_)) for p_ in ps_]; _OROW.clear(); _OROW.update(min(cs_, key=lambda c_: abs(len(c_["db"]) - n))); _OROW["n"] = n
            o_ = _OROW["db"][min(len(_OROW["db"]) - 1, int(k * fp / 0.005 + 0.5))]; df_ = 12000.0 / (len(o_) - 1)   # 手本の刻みは 0〜12kHz
            row = [o_[min(len(o_) - 2, int(f / df_))] + (o_[min(len(o_) - 2, int(f / df_)) + 1] - o_[min(len(o_) - 2, int(f / df_))]) * min(1.0, f / df_ - min(len(o_) - 2, int(f / df_))) for f in fr]
        elif _HSEL[0]:
            Ft = [r["F1"][k], r["F2"][k] + 1, r["F3"][k] + 2]
            for i in (1, 2): Ft[i] = max(Ft[i], Ft[i - 1])
            for q in range(5):
                wq = oh[q][k] / s_
                if wq < 1e-3: continue
                d = _tmpl_db(VOW[q], fr, Ft, H["top"]); row = [x + wq * y for x, y in zip(row, d)]
        if H.get("ptilt") and r.get("st5"):   # 139 連動：高さが 1 半音上がるごとに上の形を持ち上げる [1.2〜2.5k, 2.5〜5k, 5k〜] dB/半音（つむぎ・花丸で測った傾き）。基準は声の所の高さの真ん中
            ds_ = r["st5"][k] - r["st5_med"]; p_ = H["ptilt"]
            row = [x + ds_ * (0.0 if f < 900 else p_[0] if f < 2500 else p_[1] if f < 5000 else p_[2]) for x, f in zip(row, fr)]
        if H["b23"]:
            for f_ in (r["F2"][k], r["F3"][k]):
                row = [x + H["b23"] * math.exp(-0.5 * ((f - f_) / H["b23_sd"]) ** 2) for x, f in zip(row, fr)]
        T.append(row)
    sg = H["sm_ms"] / (1000.0 * HOP / SR); q_ = H["q"]
    # 包絡 E：dB スペクトルを q 個のケプストラムで均す（irfft → 切る → rfft の実部）
    cosm = [[math.cos(2 * math.pi * k * c / NF) for k in range(NF)] for c in range(q_)]
    cosb = [[(1.0 if c == 0 else 2.0) * math.cos(2 * math.pi * k * c / NF) for c in range(q_)] for k in range(hb)]
    mul = float.__mul__; E = []; pkw = int(H.get("pk", 0))
    for j in range(nfr):
        P = [10 * math.log10((z.real * z.real + z.imag * z.imag) / S2 + 1e-12) for z in Z[j]]
        if pkw: P = [max(P[max(0, k - pkw):k + pkw + 1]) for k in range(hb)]   # envfit/templ 任意 pk：倍音の山をなぞる（±pk 本の最大）。谷の深さ（倍音のきれいさ）で包絡が沈むのを防ぐ
        Pf = P + P[-2:0:-1]; cq = [sum(map(mul, cm_, Pf)) / NF for cm_ in cosm]
        E.append([sum(map(mul, cb, cq)) for cb in cosb])
    Tt = [_gauss_fast([T[j][k] for j in range(nfr)], sg) for k in range(hb)]       # 時間方向に均す（帯ごと）
    Et = [_gauss_fast([E[j][k] for j in range(nfr)], sg) for k in range(hb)]
    W = [1.0 / (1.0 + (flo / max(f, 1.0)) ** 4) / (1.0 + (f / H["fhi"]) ** 4) for f in fr]
    band = [k for k in range(hb) if max(flo, 1000.0) <= fr[k] <= min(H["fhi"], 8000.0)]
    if H.get("ref"): band = [k for k in range(hb) if H["ref"][0] <= fr[k] <= H["ref"][1]]   # 137：表との差の基準を、削らん側の帯（例 500〜1200Hz）に取る → 上の帯まるごとの高さも表に合う（元は上の帯の中の平均を引いて、帯まるごとの高さを捨てとった）
    UVW = [1.0 / (1.0 + (H.get("uv_lo", 0.0) / max(f, 1.0)) ** 6) for f in fr]
    G = [[0.0] * hb for _ in range(nfr)]; gmax = -1e300
    for j in range(nfr):
        d = [Tt[k][j] - Et[k][j] for k in range(hb)]; mb = sum(d[k] for k in band) / len(band); row = G[j]; uvj = bool(H.get("uv_lo")) and not r["voiced"][kf[j]]   # 152 の後：声のないこまは uv_lo Hz より下を手本へ削らん（子音の所で下の帯の雑音が 13〜22dB 持ち上がって「ｼｬｯ」になった）
        for k in range(hb):
            v = H["depth"] * (d[k] - mb) * W[k] * (UVW[k] if uvj else 1.0); row[k] = v
            if v > gmax: gmax = v
    if H.get("gclip") is not None:   # 142 測り専用：利得の上の外れ値を切る（声のあるこまの上から gclip 番目の百分位）
        vs_ = sorted(G[j][k] for j in range(nfr) if w[kf[j]] > 0.5 for k in range(0, hb, 4)); gmax = vs_[int(len(vs_) * H["gclip"])] if vs_ else gmax
        G = [[min(v, gmax) for v in row] for row in G]
    Hm = [1.0 - 1.0 / (1.0 + (f / fc) ** xp) for f in fr]
    Y1 = [[Z[j][k] * (10 ** ((G[j][k] - gmax) / 20.0) * Hm[k]) for k in range(hb)] for j in range(nfr)]
    Y2 = [[Z[j][k] * Hm[k] for k in range(hb)] for j in range(nfr)]
    uhi, mhi = _istft_r(Y1, Y2, NF, HOP, win, N)
    W20 = max(1, int(0.02 * SR)) | 1
    rm = [math.sqrt(max(v, 0.0)) for v in _box([v * v for v in mhi], W20)]
    rv = [math.sqrt(max(v, 0.0)) for v in _box([v * v for v in uhi], W20)]
    eps = 1e-4 * (max(rv) + 1e-12)
    g = _gauss_s([rm[i] / (rv[i] + eps) for i in range(N)], H["lev_ms"] / 1000.0 * SR / 2)
    ws = _gauss_s(_per_sample(w, N, r["fp_ms"]), H["xf_ms"] / 1000.0 * SR / 2.0)
    return [ws[i] * (g[i] * uhi[i] - mhi[i]) for i in range(N)]
def _henv_df(x, r, SR, D):               # exp36c deflutter：lo-hi を bw ごとの帯に分け、帯の強さの速い山だけ削る（利得 = min(1, 遅い/速い)^depth）
    lo, hi = D.get("lo", 1000.0), D.get("hi", 4000.0); depth = D.get("depth", 1.0); bw = D.get("bw", 300.0); sd_ms = D.get("sd_ms", 8.0)
    NF, HOP = 256, 64; hb = NF // 2 + 1; N = len(x)
    Z, win = _stft_r(x, NF, HOP); nfr = len(Z); S2 = sum(win) ** 2
    f = [k * SR / NF for k in range(hb)]
    top = min(hi, SR / 2); ed = []; v = lo
    while v < top + 1: ed.append(v); v = lo + len(ed) * bw
    cen = []; gs = []
    for a, b in zip(ed[:-1], ed[1:]):
        ks = [k for k in range(hb) if a <= f[k] < b]
        En = [math.sqrt(sum((Z[j][k].real ** 2 + Z[j][k].imag ** 2) / S2 for k in ks) + 1e-12) for j in range(nfr)]
        Es = _gauss_fast(En, sd_ms / 1000 * SR / HOP); cen.append((a + b) / 2)
        gs.append([min(1.0, Es[j] / En[j]) ** depth for j in range(nfr)])
    pr = _henv_prot(D, r) if (D.get("cmute") or D.get("von_ms")) else None
    fp = r["fp_ms"] / 1000.0; n = r["n"]
    bk = [k for k in range(hb) if lo <= f[k] < hi]; Y = []; Y0 = [[0j] * hb for _ in range(nfr)]
    for j in range(nfr):
        row = [0j] * hb; gj = [gs[i][j] for i in range(len(cen))]
        pj = pr[min(n - 1, int(round(j * HOP / SR / fp)))] if pr else 1.0
        for k in bk: row[k] = Z[j][k] * ((_interp(f[k], cen, gj) - 1.0) * pj)
        Y.append(row)
    dlt, _ = _istft_r(Y, Y0, NF, HOP, win, N)
    return [x[i] + dlt[i] for i in range(N)]
def _iki_up(y, r, SR, K, rng):          # 147 の後：上の帯が純な倍音だけ（倍音の間の谷 20〜25dB、つむぎ は 2〜10dB）＝ハーモニカ。声のあるこまで、上の帯の力の一部を、同じ形に削った新しい白色雑音に入れ替える。pts＝[[Hz, 入れ替える割合]…]、w_hz＝形を取る幅
    NF, HOP = 1024, 256; hb = NF // 2 + 1; N = len(y); pts = K.get("pts", [[1200, 0.0], [2500, 0.1], [5000, 0.4], [8000, 0.7]]); hw = max(1, int(K.get("w_hz", 600) / (SR / NF) / 2))
    fr = [k * SR / NF for k in range(hb)]; lx = [math.log(p[0]) for p in pts]; A = [0.0 if f < pts[0][0] else _interp(math.log(min(f, pts[-1][0])), lx, [p[1] for p in pts]) for f in fr]
    FR = [max(0.0, min(1.0, (f - pts[0][0]) / 600.0)) for f in fr]
    Y, win = _stft_r(y, NF, HOP); Zn, _ = _stft_r(noise(rng, N), NF, HOP); n = r["n"]; fp = r["fp_ms"] / 1000.0; out = []
    wv = _gauss_fr([1.0 if (r["voiced"][t] or K.get("uv")) else 0.0 for t in range(n)], K.get("xf_fr", 2.0))
    for j in range(len(Y)):
        wj = wv[min(n - 1, int(j * HOP / SR / fp))]
        if wj < 1e-3: out.append(Y[j]); continue
        py = [abs(v) ** 2 for v in Y[j]]; pz = [abs(v) ** 2 for v in Zn[j]]; ey = _box(py, 2 * hw + 1); ez = _box(pz, 2 * hw + 1)
        gj = 10 ** (K.get("fl", 0.0) * rng.gauss(0, 1) / 20.0) if K.get("fl") else 1.0   # fl：上の帯まるごとの強さを こまごとに一緒に揺らす（dB、乱数。お手本は帯どうしが連れ立って揺れる）
        out.append([(Y[j][k] * math.sqrt(1 - A[k] * wj) + Zn[j][k] * math.sqrt(A[k] * wj * max(ey[k], 0.0) / (ez[k] + 1e-30))) * (1 + (gj - 1) * wj * FR[k]) for k in range(hb)])
    a, _b = _istft_r(out, out, NF, HOP, win, N); return a
def _henv(mix, src, r, KT, SR):          # 82b/mdf：exp36 merge36.apply と同じ順（低い帯 → ＋上の帯（元の mix から）→ 揺れ取り）
    H = KT["henv"] if isinstance(KT["henv"], dict) else {}
    _HSEL[0] = H.get("tab"); _HSEL[1] = H.get("warp", True)
    y = _henv_low(mix, src, r, KT, SR) if H.get("low", True) else list(mix)
    if H.get("up"):
        d = _henv_up(mix, r, SR, H["up"], float(H.get("fc", 1000.0)), H.get("xp", 4)); y = [a + b for a, b in zip(y, d)]
        for _ in range(int(H["up"].get("it", 1)) - 1):   # envfit/templ 任意 it：同じ削りをもう一度（均しのにじみで残った差を詰める）
            d = _henv_up(y, r, SR, H["up"], float(H.get("fc", 1000.0)), H.get("xp", 4)); y = [a + b for a, b in zip(y, d)]
    if H.get("up2"):   # 152：二度目の削り（別の帯・別の細かさ）。下の帯（〜1.2kHz）を、上とは別の粗さの包絡で手本へ
        d = _henv_up(y, r, SR, H["up2"], float(H.get("fc", 1000.0)), H.get("xp", 4)); y = [a + b for a, b in zip(y, d)]
    if H.get("df"): y = _henv_df(y, r, SR, H["df"])
    if H.get("keep_hi"):   # 153 の後：手本の無い高い帯（例 9kHz より上）は削る前の混ぜに戻す。上の形の削りの副作用で 12〜20kHz が 137-4 より 10〜15dB 持ち上がっとった
        ly = _lpz(y, float(H["keep_hi"]), SR, 4); lm = _lpz(mix, float(H["keep_hi"]), SR, 4); y = [ly[i] + mix[i] - lm[i] for i in range(len(y))]
    return y

def _vtrack(r, n, tab, k=None, sm_ms=30):   # 102: per-vowel correction track (5 ms frames): value of tab[vowel] over each mora (consonant part included), 1.0 elsewhere, smoothed
    out = [1.0] * n; fpz = kotoba.FP / 1000
    for m in r["moras"]:
        if m.get("kind") == "CV" and m.get("v") in tab:
            x = tab[m["v"]]; x = x if k is None else x[k]
            for t in range(max(0, int(m["a"] / fpz)), min(n, int(m["e"] / fpz) + 1)): out[t] = x
    return kotoba.smooth1(out, sm_ms)

def _onaji_kuukan(v_core, vo, N, SR, seed):
    """ソプラノ彫刻家の「澄み渡る空間の耳（脱・管共鳴）」：
    固定遅延のコムフィルタ（＝円筒管の共鳴）になるのを防ぐため、千鳥足(furafura)に自然なゆらぎ(12〜20サンプル)を持たせ、
    フィードバックも穏やか(-0.34〜-0.40)に抑えることで、管っぽさを一切出さずに開放空間の澄んだ空気だけを纏わせる。"""
    rng = random.Random(seed + 77)
    v_bright = karuku(v_core, 75)
    v_air = arakezuri(v_bright, 3, 2)

    # 1. ホール側壁の初期反射（37ms / 53ms：管共鳴にならぬよう 12/16 サンプルの緩やかな空気ゆらぎ＋穏やかな反射 -0.34/-0.32）
    d_w1 = furafura(N, rng, 0.037 * SR, 12.0, 0.32)
    d_w2 = furafura(N, rng, 0.053 * SR, 16.0, 0.36)
    w1 = kubire_t(v_air, d_w1, [-0.34] * N, 3)
    w2 = kubire_t(v_air, d_w2, [-0.32] * N, 4)
    wall = [0.55 * (w1[i] - v_air[i]) + 0.45 * (w2[i] - v_air[i]) for i in range(N)]

    # 2. 高い天井のシルキーな余韻（79ms / 115ms：m=5..6 で滑らかな絹の尾を作る）
    d_c1 = furafura(N, rng, 0.079 * SR, 18.0, 0.38)
    d_c2 = furafura(N, rng, 0.115 * SR, 22.0, 0.42)
    c1 = kubire_t(w1, d_c1, [-0.38] * N, 5)
    c2 = kubire_t(w2, d_c2, [-0.36] * N, 6)
    ceil = karuku(arakezuri([0.55 * (c1[i] - w1[i]) + 0.45 * (c2[i] - w2[i]) for i in range(N)], 4, 2), 65)

    out = [0.0] * N
    for i in range(N):
        tail_w = 0.06 + 0.22 * (1.0 - vo[i])
        out[i] = v_core[i] + tail_w * (0.55 * wall[i] + 0.45 * ceil[i])
    return out


def _scale_uta_spec(spec_list, mul):
    """第1層ヘルパー：単一Hz数値・メリスマ配列 [hz1, hz2, ...]・音符辞書 {"hz": ..., "tie": ...} のすべてに倍率 mul を適用する。"""
    out = []
    for item in spec_list:
        if isinstance(item, (list, tuple)):
            out.append([round(float(x) * mul, 2) for x in item])
        elif isinstance(item, dict):
            d = dict(item)
            if isinstance(d.get("hz"), (list, tuple)):
                d["hz"] = [round(float(x) * mul, 2) for x in d["hz"]]
            elif d.get("hz") is not None:
                d["hz"] = round(float(d["hz"]) * mul, 2)
            out.append(d)
        else:
            out.append(round(float(item) * mul, 2))
    return out


def _build_choir_parts(lead_hz):
    """『四声が4人じゃなくて1人に聞こえる＝オペラ歌手は1人で4人分歌っている』：
    別々の音程（3度下・4度下・5度下）でバラバラにハモらせるのではなく、
    4声すべてが同じ1つの旋律（1:1 ユニゾン＋メリスマ・音符イベント完全共有）を共有し、
    1人のオペラ歌手の「頭声・胸腔・頭蓋・聖堂オーラ」の4層として完全に一体化する。"""
    hz_v2 = _scale_uta_spec(lead_hz, 1.000)
    hz_v3 = _scale_uta_spec(lead_hz, 1.000)
    hz_pad = _scale_uta_spec(lead_hz, 1.000)
    return hz_v2, hz_v3, hz_pad


def _trance_singing_layers(r, n, KT, L, rc, SR):
    """チャッピィ提案の歌声合成3階層アーキテクチャ（--trance / --choir 専用、通常TTSには一切影響しない）：
    - 第1層（音符・演奏情報層）：モーラ1対1の制約を解き、同音連打（再アタック）とタイの区別、および明示指定時の1母音メリスマ `[hz1, hz2]` を音符イベント列へ展開。
    - 第2層（歌唱表現層）：
      ① 線形Hzの移動平均ではなく、セント（半音 log2）領域で「子音内の素早い遷移」と「母音間のS字最小躍度ポルタメント」を分離制御。
      ② 同音連打時（「ナ・マ」等）には自然な再アタックスクープとビブラート起点リセットを発動し、下降音程（「マ・エ〜」等）では余計なしゃくりや飾り気を排して真っ直ぐ澄み渡るロングトーンを響かせる。
      ③ 全母音一律の F1>=1.08*f0 ではなく、母音（i/u・e/o・a）と音高に応じたコペルトゥーラ（母音別フォルマント同調）を適用。"""
    fpz = kotoba.FP / 1000.0
    f_ref = SR / (2.0 * L["D_center"])
    sh_st = float(KT.get("uta_trance_shift_st", 3.0))
    sh_mul = 2.0 ** (sh_st / 12.0)
    raw_specs = _scale_uta_spec(KT["uta_hz"], sh_mul)

    # ---- 第1層：音符イベント列 (notes) の構築 ----
    # 各イベント: {a_fr, b_fr, e_fr, st, hz, tie, reattack, melisma, has_cons, vowel}
    notes = []
    k_ = 0
    prev_hz = None
    for m_idx, m_ in enumerate(r["moras"]):
        if m_.get("kind") == "pau":
            prev_hz = None
            continue
        spec = raw_specs[min(k_, len(raw_specs) - 1)]
        k_ += 1
        a_fr = max(0, min(n - 1, int(m_["a"] / fpz)))
        b_fr = max(a_fr, min(n - 1, int(m_["b"] / fpz)))
        e_fr = max(b_fr + 1, min(n, int(m_["e"] / fpz) + 1))
        has_cons = bool(m_.get("c"))
        v_ch = m_.get("v", "a")

        # 辞書指定・メリスマ配列・単一数値のすべてを正規化（勝手な自動こぶしは入れず、明示指定時のみメリスマ展開）
        explicit_tie = False
        port_override = None
        if isinstance(spec, dict):
            explicit_tie = bool(spec.get("tie", False))
            port_override = spec.get("port_ms")
            hz_val = spec.get("hz", 392.0)
        else:
            hz_val = spec

        if isinstance(hz_val, (list, tuple)) and len(hz_val) > 1:
            # メリスマ：1つのモーラの母音区間 [b_fr, e_fr] を複数音符（均等または重み付き比率）に分割
            pairs = []
            for item in hz_val:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    pairs.append(( float(item[0]), float(item[1]) ))
                else:
                    pairs.append(( float(item), 1.0 ))
            tot_w = sum(w for _, w in pairs) or 1.0
            span = max(1, e_fr - b_fr)
            acc_w = 0.0
            for idx, (h_sub, w_sub) in enumerate(pairs):
                h_f = max(60.0, h_sub)
                st_f = 12.0 * math.log2(h_f / f_ref)
                sub_a = a_fr if idx == 0 else b_fr + int(round(span * acc_w / tot_w))
                sub_b = b_fr if idx == 0 else sub_a
                acc_w += w_sub
                sub_e = e_fr if idx == len(pairs) - 1 else b_fr + int(round(span * acc_w / tot_w))
                is_same = (prev_hz is not None and abs(h_f - prev_hz) < 1e-3)
                notes.append({
                    "a_fr": sub_a, "b_fr": sub_b, "e_fr": max(sub_b + 1, sub_e),
                    "hz": h_f, "st": st_f,
                    "tie": explicit_tie if idx == 0 else False,
                    "reattack": (is_same and not explicit_tie) if idx == 0 else False,
                    "melisma": idx > 0,
                    "has_cons": has_cons if idx == 0 else False,
                    "port_ms": port_override,
                    "vowel": v_ch,
                })
                prev_hz = h_f
        else:
            h_f = max(60.0, float(hz_val[0] if isinstance(hz_val, (list, tuple)) else hz_val))
            st_f = 12.0 * math.log2(h_f / f_ref)
            is_same = (prev_hz is not None and abs(h_f - prev_hz) < 1e-3)
            # 促音(Q)・撥音(N)以外の通常モーラで同音が続く場合は「同音再アタック」として扱う（明示tieを除く）
            is_tie = explicit_tie or (is_same and m_.get("kind") in ("Q", "N"))
            notes.append({
                "a_fr": a_fr, "b_fr": b_fr, "e_fr": e_fr,
                "hz": h_f, "st": st_f,
                "tie": is_tie,
                "reattack": (is_same and not is_tie),
                "melisma": False,
                "has_cons": has_cons,
                "port_ms": port_override,
                "vowel": v_ch,
            })
            prev_hz = h_f

    if not notes:
        return [SR / (2.0 * L["D_center"])] * n

    # ---- 第2層①：セント（半音 st）領域での音程軌道構築（S字ポルタメント＆子音境界保護） ----
    st_track = [notes[0]["st"]] * n
    for idx, nt in enumerate(notes):
        for t_ in range(nt["a_fr"], n):
            st_track[t_] = nt["st"]

    # 音符間の遷移をセント領域の最小躍度S字曲線 (3u^2 - 2u^3, sin/cos不使用) で接続
    base_port_ms = float(KT.get("uta_sm", 38.0))
    for idx in range(1, len(notes)):
         prev_nt = notes[idx - 1]
         cur_nt = notes[idx]
         st0 = prev_nt["st"]
         st1 = cur_nt["st"]
         if abs(st1 - st0) < 1e-4 or cur_nt["tie"]:
             continue
         if cur_nt["melisma"]:
             p_ms = float(cur_nt["port_ms"] or 34.0)
             half_w = max(1, int(0.5 * p_ms / kotoba.FP))
             t_mid = cur_nt["b_fr"]
             t0 = max(prev_nt["b_fr"], t_mid - half_w)
             t1 = min(cur_nt["e_fr"], t_mid + half_w)
         elif cur_nt["has_cons"] and cur_nt["b_fr"] > cur_nt["a_fr"]:
             # 子音ありモーラ：子音区間 [a_fr, b_fr + 2] の中で素早く音高を切り替え、母音頭 b_fr が前後にボケないようにする
             p_ms = float(cur_nt["port_ms"] or min(26.0, base_port_ms * 0.6))
             t0 = cur_nt["a_fr"]
             t1 = min(cur_nt["e_fr"], max(cur_nt["b_fr"] + 2, t0 + max(2, int(p_ms / kotoba.FP))))
         else:
             # 母音連続（「マ・エ〜」「コ・エ〜」等）：30msのすっきりしたレガートで真っ直ぐターゲット音高へ着地させる
             p_ms = float(cur_nt["port_ms"] or min(30.0, base_port_ms))
             half_w = max(2, int(0.5 * p_ms / kotoba.FP))
             t_mid = cur_nt["b_fr"]
             t0 = max(prev_nt["b_fr"], t_mid - half_w)
             t1 = min(cur_nt["e_fr"], t_mid + half_w)
         span = max(1, t1 - t0)
         for t_ in range(t0, min(n, t1)):
             u = (t_ - t0) / span
             s_curve = u * u * (3.0 - 2.0 * u)
             st_track[t_] = st0 + (st1 - st0) * s_curve

    # ---- 第2層②：音の入りのしゃくり（同音連打「ナ・マ」は維持し、下降音程「マ・エ〜」では余計なしゃくりを入れず澄ませる） ----
    if KT.get("uta_scoop"):
        base_sc, base_sm = KT["uta_scoop"]
        for idx, nt in enumerate(notes):
            if nt["tie"] or nt["melisma"]:
                continue
            # 同音連打（reattack：「ナ・マ」等）は好評の自然な再アーティキュレーション（深さ0.42倍・時間0.65倍）
            if nt["reattack"]:
                sc_use = base_sc * 0.42
                sm_use = max(18.0, base_sm * 0.65)
            elif idx == 0 or (nt["st"] - notes[idx - 1]["st"]) > 1e-3:
                # 句頭または上昇音程のときだけ、控えめで品のある入り（最大0.85st・32ms）でスッと音芯へ乗せる
                sc_use = min(float(base_sc) * 0.65, 0.85)
                sm_use = min(float(base_sm), 32.0)
            else:
                # 下降音程（「マ(G4)→エ(D4)」「ノ(G4)→コ(E4)→エ(D4)」等）では下にしゃくり返さず、真っ直ぐ澄んだ音を響かせる！
                continue
            a_ = nt["b_fr"] if nt["has_cons"] else nt["a_fr"]
            end_sc = min(nt["e_fr"], min(n, a_ + int(4.5 * sm_use / kotoba.FP)))
            for t_ in range(a_, end_sc):
                st_track[t_] -= sc_use * math.exp(-(t_ - a_) * kotoba.FP / sm_use)

    # ---- 第2層③：天邪鬼ビブラート（乱数削り出し波＋16セント頭打ち解除＆倍音明滅のための軌道保持） ----
    raw_ = [0.0] * n
    if KT.get("uta_vib"):
        vr_, vd_, vl_, vu_ = KT["uta_vib"]
        # 16セント上限を解除し、伸ばし音（マエ〜・コエ〜）の後半で人間らしい豊かなビブラート（実効±15〜22セント）が乗るようにする
        vd_use = min(float(vd_) * 1.40, 44.0)
        vl_ = max(float(vl_), 180.0)
        vu_ = max(float(vu_), 240.0)
        wv_ = max(3, int(round(1000.0 / kotoba.FP / vr_ / 2.0)))
        vw_ = arakezuri(
            _comb(noise(random.Random(rc["seed"] + 33), n + 40 * wv_), [wv_] * (n + 40 * wv_), KT.get("uta_vib_g", 0.96)),
            max(2, wv_ // 2),
            2,
        )[40 * wv_:40 * wv_ + n]
        rm_ = (sum(v * v for v in vw_) / n) ** 0.5 or 1.0
        vw_ = [max(-1.5, min(1.5, v / rm_ / 1.414)) for v in vw_]

        t0_sec = notes[0]["b_fr"] * fpz
        for idx, nt in enumerate(notes):
            if idx == 0:
                t0_sec = nt["b_fr"] * fpz
            elif nt["tie"] or nt["melisma"]:
                pass
            elif nt["reattack"]:
                t0_sec = nt["b_fr"] * fpz - 0.45 * (vl_ / 1000.0)
            else:
                t0_sec = nt["b_fr"] * fpz
            for t_ in range(nt["a_fr"], min(n, nt["e_fr"])):
                el_ = t_ * fpz - t0_sec - vl_ / 1000.0
                if el_ > 0.0:
                    raw_[t_] = min(1.0, el_ / (vu_ / 1000.0)) * vw_[t_]
        for t_ in range(n):
            st_track[t_] += (vd_use / 100.0) * raw_[t_]
    r["vib_raw"] = raw_

    fr_ = [f_ref * (2.0 ** (s / 12.0)) for s in st_track]

    # ---- 第2層④：母音内部の調音ダイナミクス（固定された「エ〜」を、少しずつ動く生身の「エ〜」にする） ----
    # 1) 前後モーラとの調音結合（vl_hold で止められていた無声子音前の先行調音も復元）
    # 2) 長音内部での「口の開き（アーク）→ 母音固有の緩やかな収束（エ→エぃ、ア→アぉ等）」
    # 3) 舌・顎の緩やかな生体ゆらぎ（±1.6%）＋ ビブラートに同期したフォルマント微細揺れ（倍音明滅 Harmonic AM）
    cv_list = [m_ for m_ in r["moras"] if m_.get("kind") == "CV" and m_.get("v")]
    f_orig = [[ float(x) for x in r["F%d" % (j + 1)] ] for j in range(3)]
    r_art = random.Random(rc["seed"] + 41)
    art_drifts = []
    for j in range(3):
        dr = arakezuri(noise(r_art, n + 60), 18, 2)[30:30 + n]
        drm = sum(dr) / n
        drs = (sum((v - drm) ** 2 for v in dr) / n) ** 0.5 or 1.0
        art_drifts.append([(v - drm) / drs for v in dr])

    # 母音別の長音後半の自然な調音シフト率 (dF1, dF2, dF3)：前舌母音(e,i)はわずかに舌が上がり、奥・開母音(a,o,u)はわずかに丸まる
    V_LONG_DRIFT = {
        "e": (-0.065, +0.052, +0.025),
        "i": (-0.045, +0.038, +0.020),
        "a": (-0.058, -0.045, -0.018),
        "o": (-0.050, -0.048, -0.020),
        "u": (-0.045, -0.042, -0.018),
    }
    PLACE_LOCUS_F2 = {"lab": 950.0, "alv": 1850.0, "pal": 2350.0, "vel": 1650.0, "glot": None, None: None}

    for idx_m, m_ in enumerate(cv_list):
        b_fr = max(0, min(n - 1, int(round(m_["b"] / fpz))))
        e_fr = max(b_fr + 1, min(n, int(round(m_["e"] / fpz))))
        span_fr = max(1, e_fr - b_fr)
        dur_ms = span_fr * kotoba.FP
        v_c = m_["v"]
        tm_cur = min(n - 1, (b_fr + e_fr) // 2)
        F_cur = [f_orig[j][tm_cur] for j in range(3)]

        # 前の母音のフォルマント
        if idx_m > 0:
            pm = cv_list[idx_m - 1]
            tm_p = min(n - 1, int(round(0.5 * (pm["b"] + pm["e"]) / fpz)))
            F_prev = [f_orig[j][tm_p] for j in range(3)]
        else:
            F_prev = list(F_cur)

        # 次の子音・母音のターゲット（先行調音：次の子音の調音位置または次の母音へ向かって舌が準備を始める）
        if idx_m + 1 < len(cv_list):
            nm = cv_list[idx_m + 1]
            tm_n = min(n - 1, int(round(0.5 * (nm["b"] + nm["e"]) / fpz)))
            F_next = [f_orig[j][tm_n] for j in range(3)]
            nc = nm.get("c") or ""
            pl_n = kotoba.PLACE.get(nc)
            loc_f2 = PLACE_LOCUS_F2.get(pl_n)
            if loc_f2 is not None:
                F_next[1] = 0.55 * F_next[1] + 0.45 * loc_f2
                F_next[0] = min(F_next[0], F_cur[0] * 0.88)
        else:
            F_next = [F_cur[0] * 0.94, F_cur[1] * 0.97, F_cur[2] * 0.98]

        d1_long, d2_long, d3_long = V_LONG_DRIFT.get(v_c, (-0.05, 0.0, 0.0))
        long_scale = min(1.35, max(0.35, (dur_ms - 120.0) / 360.0))

        for t_ in range(b_fr, e_fr):
            u = (t_ - b_fr) / span_fr
            # (a) 前母音からのキャリーオーバー (u: 0 -> 0.38) と 次音への先行調音 (u: 0.52 -> 1.0)
            w_prev = 0.12 * ((1.0 - u / 0.38) ** 2) if u < 0.38 else 0.0
            w_next = 0.16 * (((u - 0.52) / 0.48) ** 2) if u > 0.52 else 0.0
            # (b) 長音の呼吸アーク（前半 u≈0.32 で口がわずかに開き、後半 u>0.40 で母音固有の方向へ緩やかに動く）
            arch = 4.0 * u * (1.0 - u)
            late = ((u - 0.35) / 0.65) if u > 0.35 else 0.0
            late_s = late * late * (3.0 - 2.0 * late)

            m1 = 1.0 + long_scale * (0.052 * arch + d1_long * late_s)
            m2 = 1.0 + long_scale * (0.018 * arch * (1.0 if v_c in ("e", "i") else -1.0) + d2_long * late_s)
            m3 = 1.0 + long_scale * (0.012 * arch + d3_long * late_s)
            m_tuple = (m1, m2, m3)

            for j in range(3):
                k_name = "F%d" % (j + 1)
                base_f = r[k_name][t_]
                coart_f = base_f + w_prev * (F_prev[j] - F_cur[j]) + w_next * (F_next[j] - F_cur[j])
                r[k_name][t_] = coart_f * m_tuple[j]

    # ---- 第2層⑤：母音別・音高別の高音フォルマント同調（コペルトゥーラ）＋ビブラート連動フォルマント揺れ ----
    v_map = ["a"] * n
    for m_ in r["moras"]:
        if m_.get("kind") == "CV" and m_.get("v"):
            for t_ in range(max(0, int(m_["a"] / fpz)), min(n, int(m_["e"] / fpz) + 1)):
                v_map[t_] = m_["v"]
    r["v_map"] = v_map

    COPERTURA = {
        "i": (420.0, 0.95, 0.65, 0.98),
        "u": (420.0, 0.96, 0.68, 0.97),
        "e": (440.0, 1.03, 0.78, 0.96),
        "o": (440.0, 1.04, 0.80, 0.98),
        "a": (500.0, 1.07, 0.85, 0.95),
    }
    vib_mod_scales = (+0.026, -0.022, +0.030)
    for t_ in range(n):
        if r["voiced"][t_] and fr_[t_] > 0.0:
            v_c = v_map[t_]
            f_start, f1_ratio, blend_k, f2_round = COPERTURA.get(v_c, (450.0, 1.04, 0.75, 0.97))
            f0_t = fr_[t_]
            target_f1 = f0_t * f1_ratio
            if target_f1 > r["F1"][t_] and f0_t > f_start * 0.85:
                w_tune = min(1.0, max(0.0, (f0_t - f_start * 0.85) / 180.0)) * blend_k
                r["F1"][t_] = r["F1"][t_] + w_tune * (target_f1 - r["F1"][t_])
            if f0_t > 440.0:
                w_cov = min(1.0, (f0_t - 440.0) / 320.0)
                r["F2"][t_] *= 1.0 - w_cov * (1.0 - f2_round)
            # 生体の微細調音ゆらぎ (±1.5%) ＋ ビブラート周期に同期した声道共鳴の揺れ（倍音明滅 Harmonic AM を生む）
            vw_t = raw_[t_]
            for j in range(3):
                k_name = "F%d" % (j + 1)
                r[k_name][t_] *= (1.0 + 0.015 * art_drifts[j][t_] + vib_mod_scales[j] * vw_t)

    return fr_


LAST_CHOIR_PARTS = []


def _make_choir(rc):
    """『オペラ歌手って4人分歌ってるようなもんなんやろう』——
    別音程の4人がバラバラに歌うのではなく、同じ1つの旋律（ユニゾン）を、
    1人のオペラ歌手の4つの共鳴腔（①頭声の芯 Testa・②深い胸腔 Petto・③高い頭蓋 Maschera・④聖堂の絹オーラ Duomo）として
    重ね合わせ、「1人の超人的なオペラ歌手」に結晶化させる。"""
    global LAST_CHOIR_PARTS
    base_rc = copy.deepcopy(rc)
    base_kt = dict(KTDEF)
    base_kt.update(base_rc.get("kotoba", {}))
    base_kt["uta_choir"] = False
    base_kt["uta_trance"] = True

    prm0 = base_kt["params"]
    prm0 = dict(getattr(kotoba, prm0) if isinstance(prm0, str) else prm0)
    prm0["uta_trance"] = True
    post_tr = max(float(base_kt.get("post", 0.35)), 1.10)
    r0 = kotoba.tracks_from_kana(base_rc["text"], pre=base_kt.get("pre", 0.6), post=post_tr, params=prm0)
    cv_moras = [m for m in r0["moras"] if m.get("kind") != "pau"]

    sh_st = float(base_kt.get("uta_trance_shift_st", 3.0))
    sh_mul = 2.0 ** (sh_st / 12.0)
    if base_kt.get("uta_hz"):
        lead_hz = _scale_uta_spec(base_kt["uta_hz"], sh_mul)
    else:
        f0_rule = accent.f0_rule(r0["moras"], r0["n"], None, **dict(accent.CUTE, reg=392.0, **(base_kt.get("accent_kw") or {})))
        fpz = kotoba.FP / 1000.0
        lead_hz = []
        for m in cv_moras:
            tm = int(0.5 * (m["b"] + m["e"]) / fpz)
            lead_hz.append(round(float(f0_rule[min(len(f0_rule) - 1, max(0, tm))]), 2))

    hz_v2, hz_v3, hz_pad = _build_choir_parts(lead_hz)
    vib_use = base_kt.get("uta_vib") or [5.4, 16, 180, 240]
    scoop_use = base_kt.get("uta_scoop") or [1.2, 35]

    singers = [
        {
            "name": "Testa", "hz_list": lead_hz,
            "fscale": [0.98, 0.95, 0.92], "tsubu": 46,
            "band": base_kt.get("band", 3.0),
            "vib": vib_use, "scoop": scoop_use, "gain": 1.00,
            "pan": (0.76, 0.74), "cavity": "testa",
        },
        {
            "name": "Petto", "hz_list": hz_v2,
            "fscale": [0.93, 0.90, 0.88], "tsubu": 46,
            "band": 0.0,
            "vib": vib_use, "scoop": scoop_use, "gain": 0.30,
            "pan": (0.68, 0.80), "cavity": "petto",
        },
        {
            "name": "Maschera", "hz_list": hz_v3,
            "fscale": [1.02, 0.99, 0.96], "tsubu": 46,
            "band": 0.0,
            "vib": vib_use, "scoop": scoop_use, "gain": 0.22,
            "pan": (0.80, 0.68), "cavity": "maschera",
        },
        {
            "name": "Duomo", "hz_list": hz_pad,
            "fscale": [0.96, 0.93, 0.90], "tsubu": 46,
            "band": 0.0,
            "vib": vib_use, "scoop": scoop_use, "gain": 0.24,
            "pan": (0.72, 0.78), "cavity": "duomo",
        },
    ]

    parts_wav = []
    moras_out = None
    max_len = 0
    base_seed = int(base_rc.get("seed", 2024))
    for sg in singers:
        s_rc = copy.deepcopy(base_rc)
        # 重要：4層すべてが「1人のオペラ歌手の同じ1対の声帯（同一seed・同一粒・同一ビブラート位相・同一子音タイミング）」を共有！
        s_rc["seed"] = base_seed
        s_rc["kugiri"] = dict(s_rc.get("kugiri", {}), tsubu=sg["tsubu"], ara=4, kurai=2)
        s_kt = copy.deepcopy(base_kt)
        s_kt["uta_choir"] = False
        s_kt["uta_trance"] = True
        s_kt["uta_trance_shift_st"] = 0.0
        s_kt["uta_hz"] = sg["hz_list"]
        s_kt["uta_vib"] = sg["vib"]
        s_kt["uta_scoop"] = sg["scoop"]
        s_kt["fscale"] = sg["fscale"]
        s_kt["band"] = sg["band"]
        s_kt["pre"] = base_kt.get("pre", 0.6)
        s_kt["post"] = post_tr
        s_kt["params"] = copy.deepcopy(prm0)
        s_rc["kotoba"] = s_kt
        wav_k, m_k = make_text(s_rc)
        n_w = len(wav_k)
        cav = sg.get("cavity")
        if cav == "petto":
            # 胸腔（固定遅延コム＝管共鳴を使わず、fscaleの深い声道＋柔らかいarakezuriで生身の温かい胴鳴りを作る）
            wav_k = arakezuri(wav_k, 4, 2)
        elif cav == "maschera":
            # 仮面（固定遅延コムを使わず、fscaleの明るい声道＋karukuで鼻腔・前頭洞の澄んだ輝きを取り出す）
            wav_k = karuku(arakezuri(wav_k, 2, 1), 50)
        elif cav == "duomo":
            # 聖堂4壁オーラ（固定管にならぬよう 18/26 サンプルの緩やかな空気ゆらぎ＋穏やかな反射 -0.35/-0.38）
            rng_d = random.Random(base_seed + 303)
            v_sm = karuku(arakezuri(wav_k, 5, 2), 180)
            D1 = furafura(n_w, rng_d, 0.0135 * SR, 18.0, 0.28)
            D2 = furafura(n_w, rng_d, 0.0390 * SR, 26.0, 0.34)
            s1 = kubire_t(v_sm, D1, [-0.35] * n_w, 4)
            s2 = kubire_t(v_sm, D2, [-0.38] * n_w, 5)
            wav_k = arakezuri([0.55 * (s1[i] - v_sm[i]) + 0.45 * (s2[i] - v_sm[i]) for i in range(n_w)], 3, 1)
        if moras_out is None:
            moras_out = m_k
        parts_wav.append((wav_k, sg["gain"], sg["pan"], sg["name"]))
        if len(wav_k) > max_len:
            max_len = len(wav_k)

    mix_all = [0.0] * max_len
    LAST_CHOIR_PARTS = []
    for wav_k, g_k, pan_k, name_k in parts_wav:
        rk = rms(wav_k) or 1.0
        norm_k = [(v / rk) * g_k for v in wav_k]
        if len(norm_k) < max_len:
            norm_k = norm_k + [0.0] * (max_len - len(norm_k))
        LAST_CHOIR_PARTS.append({"name": name_k, "wav": norm_k, "pan": pan_k})
        for i in range(max_len):
            mix_all[i] += norm_k[i]

    pk = max(abs(v) for v in mix_all) or 1.0
    scale_f = 0.891 / pk
    for p_info in LAST_CHOIR_PARTS:
        p_info["wav"] = [v * scale_f for v in p_info["wav"]]
    return [v * scale_f for v in mix_all], moras_out


def make_text(rc):
    global LAST_CHOIR_PARTS
    KT = dict(KTDEF); KT.update(rc.get("kotoba", {}))
    if KT.get("uta_choir"):
        return _make_choir(rc)
    LAST_CHOIR_PARTS = []
    is_trance = bool(KT.get("uta_trance"))
    prm = KT["params"]; prm = dict(getattr(kotoba, prm) if isinstance(prm, str) else prm)
    if is_trance:
        prm["uta_trance"] = True
        KT["post"] = max(float(KT.get("post", 0.35)), 1.10)
    r = kotoba.tracks_from_kana(rc["text"], pre=KT["pre"], post=KT["post"], params=prm)
    n = r["n"]; N = int(n * kotoba.FP / 1000 * SR)
    # 78b：子音のまわり（頭 a から声の始まり b まで、前後 cm_pad ms）を 1 とする印。F2/F3 の道筋・強さのならしをそこだけ短く、F4/F5 の山を消す
    cm = [0.0] * n
    if KT.get("cm_pad") is not None:
        pd = KT["cm_pad"] / 1000; fpz = kotoba.FP / 1000
        for m in r["moras"]:
            if m.get("c") or (KT.get("cm_q") and m.get("kind") in ("Q", "N")):
                for t in range(max(0, int((m["a"] - pd) / fpz)), min(n, int(((m["e"] if m.get("kind") in ("Q", "N") else m["b"]) + pd) / fpz) + 1)): cm[t] = 1.0
        cm = kotoba.smooth1(cm, KT.get("cm_sm", 10)) if hasattr(kotoba, "smooth1") else cm
        if KT.get("sj_c"):                 # 子音のまわりだけ短いならしの道筋に差し替える
            r2 = kotoba.tracks_from_kana(rc["text"], pre=KT["pre"], post=KT["post"], params=dict(prm, smooth_j=KT["sj_c"]))
            for j in range(3):
                k_ = "F%d" % (j + 1); r[k_] = [cm[t] * r2[k_][t] + (1 - cm[t]) * r[k_][t] for t in range(n)]
    cmS = _per_sample(cm, N)
    L = dict(rc["line"]); F = rc["fushi"]
    r_line = random.Random(rc["seed"]); r_wander = random.Random(rc["seed"] + 1); r_hiss = random.Random(rc["seed"] + 5)
    r_band = random.Random(rc["seed"] + 9); r_breath = random.Random(rc["seed"] + 2)
    # 高さ（73 と同じ：中心 D・千鳥足・漂い・周期ごとの速い揺れ）＋句の上がり下がり
    fs = KT.get("fscale", 1.0)             # 76k: formant tracks F1..F3 x fscale (shorter vocal tract = child)
    if is_trance and not isinstance(fs, (list, tuple)):
        # 重音テト(1.22)・管(1.09)・ピアニカ(0.86)のすべてを避け、透明感と肉声の温もりが両立するリリック・ソプラノの声道比率へ
        fs = [0.98, 0.95, 0.92]
    if fs != 1.0:
        fs = fs if isinstance(fs, (list, tuple)) else [fs] * 3
        for j in range(3): r["F%d" % (j + 1)] = [min(f * fs[j], 9000.0) for f in r["F%d" % (j + 1)]]
    if is_trance and not KT.get("uta_hz"):
        # 任意の読み上げ文でも --trance 指定時はソプラノのアリア節回し＋ビブラートへ昇華
        f0_tr = accent.f0_rule(r["moras"], n, None, **dict(accent.CUTE, reg=SR / (2 * L["D_center"]) * 1.12, **(KT.get("accent_kw") or {})))
        fpz_ = kotoba.FP / 1000
        uhz_ = []
        for m_ in r["moras"]:
            if m_.get("kind") == "pau": continue
            tm_ = int(0.5 * (m_["b"] + m_["e"]) / fpz_)
            uhz_.append(round(float(f0_tr[min(n - 1, max(0, tm_))]), 2))
        if uhz_:
            KT["uta_hz"] = uhz_
            KT.setdefault("uta_trance_shift_st", 0.0)
            KT.setdefault("uta_vib", [5.4, 16, 180, 240])
            KT.setdefault("uta_scoop", [1.2, 35])
    if KT.get("uta_hz"):                   # 127 歌：拍ごとの音の高さ（Hz、間を除いた拍の順）。段々の道筋を sm ms で均すだけ
        if is_trance:
            fr_ = _trance_singing_layers(r, n, KT, L, rc, SR)
        else:
            fr_ = [KT["uta_hz"][0]] * n; k_ = 0; fpz_ = kotoba.FP / 1000
            for m_ in r["moras"]:
                if m_.get("kind") == "pau": continue
                h_ = KT["uta_hz"][min(k_, len(KT["uta_hz"]) - 1)]; k_ += 1
                for t_ in range(max(0, int(m_["a"] / fpz_)), n): fr_[t_] = h_
            fr_ = kotoba.smooth1(fr_, KT.get("uta_sm", 40))
            if KT.get("uta_scoop"):        # 131：音の頭の弾み。[半音, ms]：音が変わる拍の頭で st 半音下から入って ms で的へ（指数で寄る）
                sc_, sm_ = KT["uta_scoop"]; k_ = 0; cur_ = None
                for m_ in r["moras"]:
                    if m_.get("kind") == "pau": cur_ = None; continue
                    h_ = KT["uta_hz"][min(k_, len(KT["uta_hz"]) - 1)]; k_ += 1
                    if h_ == cur_: continue
                    cur_ = h_; a_ = int(m_["a"] / fpz_)
                    for t_ in range(a_, min(n, a_ + int(5 * sm_ / 1000 / fpz_))):
                        fr_[t_] *= 2 ** (-sc_ * math.exp(-(t_ - a_) * fpz_ * 1000 / sm_) / 12)
            if KT.get("uta_vib"):          # 129：伸ばした音にだけ規則的な高さの波（道筋だけ）。[速さ Hz, 深さ セント, 入りの遅れ ms, 立ち上がり ms]。同じ高さが続く間を一つの音と数える
                vr_, vd_, vl_, vu_ = KT["uta_vib"]; t0_ = 0; raw_ = [0.0] * n; k_ = 0; cur_ = None
                wv_ = max(3, int(round(1000 / kotoba.FP / vr_ / 2)))      # 波は数式やなく、ノイズを削って作る（細かい平均 − 粗い平均 → 速さ vr のあたりだけ残る）
                vw_ = arakezuri(_comb(noise(random.Random(rc["seed"] + 33), n + 40 * wv_), [wv_] * (n + 40 * wv_), KT.get("uta_vib_g", 0.93)), max(2, wv_ // 2), 2)[40 * wv_:40 * wv_ + n]   # 声の線と同じくびれ：周期 2·wv こまの山だけ立てる
                rm_ = (sum(v * v for v in vw_) / n) ** 0.5 or 1.0; vw_ = [max(-1.5, min(1.5, v / rm_ / 1.414)) for v in vw_]
                for m_ in r["moras"]:
                    if m_.get("kind") == "pau": cur_ = None; continue
                    h_ = KT["uta_hz"][min(k_, len(KT["uta_hz"]) - 1)]; k_ += 1
                    if h_ != cur_: cur_ = h_; t0_ = m_["b"]
                    for t_ in range(max(0, int(m_["a"] / fpz_)), min(n, int(m_["e"] / fpz_) + 1)):
                        el_ = t_ * fpz_ - t0_ - vl_ / 1000
                        if el_ > 0: raw_[t_] = min(1.0, el_ / (vu_ / 1000)) * vw_[t_]
                fr_ = [f * 2 ** (vd_ * w_ / 1200) for f, w_ in zip(fr_, raw_)]
        st = _per_sample([12 * math.log2(f / (SR / (2 * L["D_center"]))) for f in fr_], N)
    elif KT.get("accent"):                   # 75：東京式アクセント規則（kw/it/accent/accent.py, 標準ライブラリ）で高さの道筋を作る（音そのものではなく道筋だけ）
        f0 = accent.f0_rule(r["moras"], n, None, **dict(accent.CUTE, reg=SR / (2 * L["D_center"]), **KT.get("accent_kw", {})))
        st = _per_sample([12 * math.log2(f / (SR / (2 * L["D_center"]))) for f in f0], N)
    else: st = _phrase_st(rc, r["moras"], N)
    wander = furafura(N, r_wander, 0.0, L["D_haba"] * (0.25 if is_trance else 0.5), L["osoi_s"])
    D = [L["D_center"] * 2 ** (-st[i] / 12) + wander[i] for i in range(N)]
    Z = rc.get("tadayoi", 0.0)
    if Z:
        r_z = random.Random(rc["seed"] + 8); z = arakezuri(noise(r_z, N), int(0.05 * SR), 2)
        zm = sum(z) / N; zs = (sum((v - zm) ** 2 for v in z) / N) ** 0.5 or 1.0
        D = [D[i] * 2 ** (-Z * (z[i] - zm) / zs / 12) for i in range(N)]
    J = 0.0012 if is_trance else rc.get("yure_hayai", 0.0)
    if J:
        r_j = random.Random(rc["seed"] + 7); i = 0
        while i < N:
            f = 1 + r_j.uniform(-1, 1) * J; per = int(2 * D[i])
            for k in range(i, min(N, i + per)): D[k] *= f
            i += max(2, per)
    PER = [2 * d for d in D]
    # 声の線
    K = dict(rc["kugiri"]); r_k = random.Random(rc["seed"] + 6); Gs = K["tsubu"]
    _sx = KT.get("seedx") or {}            # 103: optional, replace the random stream of the one grain (its fixed spectrum colours the whole voice)
    if "grain" in _sx: r_k = random.Random(_sx["grain"])
    if is_trance:
        # 脱・「ピアニカ（フリーリード感）」＆澄み渡る人間のソプラノ声門源：
        # 1) サブサンプル配置 (pos += PER) で周期切り捨ての白濁ノイズは防ぎつつ、
        #    1個の固定grainのスタンプ連打による低中域の「真空のような深すぎる谷」を防ぐため、
        #    第2の緩やかな声門粒 (grain2) との周期ごとの生体ブレンド＋微細ゆらぎ (yure=0.0028, shimmer=0.045) を与える！
        # 2) PER の強い再帰コムはリード楽器（ピアニカ）の倍音になるため、月並みTTS本線の「kurai丸め ＋ 半周期Dの6本くびれ(kubire_n)」を主軸に据える！
        Gs = max(46, int(K.get("tsubu", 46)))
        grain = arakezuri(noise(r_k, Gs * 3), 4, 3)[Gs:2 * Gs]; gm = sum(grain) / Gs; grain = [v - gm for v in grain]
        grain = kiridashi(grain, 0, Gs, Gs // 4, Gs // 2, 1.5)
        grain2 = arakezuri(noise(r_k, Gs * 3), 5, 3)[Gs:2 * Gs]; gm2 = sum(grain2) / Gs; grain2 = [v - gm2 for v in grain2]
        grain2 = kiridashi(grain2, 0, Gs, Gs // 4, Gs // 2, 1.5)
        g1_r = (sum(v * v for v in grain) / Gs) ** 0.5 or 1.0
        g2_r = (sum(v * v for v in grain2) / Gs) ** 0.5 or 1.0
        grain2 = [v * (g1_r / g2_r) for v in grain2]
        y = [0.0] * N; pos = 0.0
        r_pulse = random.Random(rc["seed"] + 16)
        yure_tr = min(float(K.get("yure", 0.0028)), 0.0032)
        shim_tr = min(float(K.get("shimmer", 0.045)), 0.050)
        g_mix = 0.0
        while int(pos) < N:
            idx = int(pos)
            frac = pos - idx
            g_mix = max(-0.28, min(0.28, 0.88 * g_mix + r_pulse.uniform(-0.11, 0.11)))
            amp_g = 1.0 + r_pulse.uniform(-1.0, 1.0) * shim_tr
            w0 = (1.0 - frac) * amp_g
            w1 = frac * amp_g
            for j in range(Gs):
                g_v = (1.0 - abs(g_mix)) * grain[j] + g_mix * grain2[j]
                if idx + j < N: y[idx + j] += g_v * w0
                if idx + j + 1 < N: y[idx + j + 1] += g_v * w1
            pos += max(2.0, PER[min(idx, N - 1)] * (1.0 + r_pulse.uniform(-1.0, 1.0) * yure_tr))
        y = arakezuri(y, 2, 2)
        line = kubire_n(y, D, [0.45] * N, L["m"], 6)
        line = kubire_t(line, PER, [-0.12] * N, 2)
        line = karuku(line, L["karuku_w"])
        line = [line[i] - 0.48 * (1.0 - cmS[i]) * line[i - 1] if i else line[i] for i in range(N)]
    else:
        grain = arakezuri(noise(r_k, Gs * 3), K["ara"], 3)[Gs:2 * Gs]; gm = sum(grain) / Gs; grain = [v - gm for v in grain]
        grain = kiridashi(grain, 0, Gs, Gs // 4, Gs // 2, 1.5)
        y = [0.0] * N; i = 0
        while i < N:
            amp = 1 + r_k.uniform(-1, 1) * K.get("shimmer", 0.0)
            for j in range(Gs):
                if i + j < N: y[i + j] += grain[j] * amp
            i += max(2, int(PER[min(i, N - 1)] * (1 + r_k.uniform(-1, 1) * K["yure"])))
        if K.get("kurai"): y = arakezuri(y, K["kurai"], 2)
        lg = KT["line_g"] if KT["line_g"] is not None else L["g"]
        line = kubire_n(y, D, [lg] * N, L["m"], L.get("n", 2)) if L.get("n", 2) > 2 else kubire_t(y, D, [lg] * N, L["m"])
        line = karuku(line, L["karuku_w"])
        # 77b：声の元の質（源の明るさ・息っぽさ）。すべて引き算の削り出しと、別に削った層の混ぜ合わせだけ
        if KT.get("emph"):                     # 前の一サンプルの自分を少し引く＝高い方を持ち上げる（傾きを緩く）
            e_ = KT["emph"]; ec = KT.get("emph_c", e_)
            line = [line[i] - (e_ + (ec - e_) * cmS[i]) * line[i - 1] if i else line[i] for i in range(N)]
    if KT.get("asp") and not is_trance:    # 声のある所にも高い息（ソプラノでは後段の _iki_up で高域倍音を絹の息へ置換する）
        r_a = random.Random(rc["seed"] + 11); aw = KT.get("asp_w", [1, 4])
        ah = karuku(sabun(noise(r_a, N), aw[0], aw[1]), L["karuku_w"]); ar_ = rms(ah) or 1.0; lr0 = rms(line) or 1.0
        pu = KT.get("asp_puls", 0.0)
        if pu:                             # 息を周期に合わせて脈打たせる（粒の列の大きさで窓をかける）
            ev = arakezuri([abs(v) for v in y], max(2, int(KT.get("asp_pw", 40))), 2); em = (sum(ev) / N) or 1.0
            ah = [ah[i] * ((1 - pu) + pu * ev[i] / em) for i in range(N)]; ar_ = rms(ah) or 1.0
        line = [line[i] + KT["asp"] * lr0 * ah[i] / ar_ for i in range(N)]
    # 声なしの元：くびれを通さない、軽く均しただけのノイズ
    ha = KT["hiss_ara"]; hiss = karuku(arakezuri(noise(r_hiss, N), ha[0], ha[1]), L["karuku_w"])
    lr = rms(line) or 1.0; hr = rms(hiss) or 1.0
    vo = _per_sample([1.0 if v else 0.0 for v in r["voiced"]], N)
    vo = _heikin(vo, [KT["xf_ms"] * SR / 1000] * N)
    src = [vo[i] * line[i] / lr + (1 - vo[i]) * hiss[i] / hr for i in range(N)]
    # こまごとの的（WORLD の包絡のエネルギー × 大きさ）
    Ef, Ej, Eb = _world_energy(r, KT["gk"])
    lo = [r["loud"][t] + (r["dl"][t] if KT["use_dl"] else 0.0) for t in range(n)]
    amp = [math.exp(v / 2) for v in lo]
    if is_trance:
        # 高音に向かって声量と輝きが自然に開くソプラノのブレス・アポッジョ ＋ ビブラート周期に同期した声門下圧の微細脈動
        vib_raw = r.get("vib_raw") or [0.0] * n
        for t_ in range(n):
            f_now = SR / PER[min(N - 1, int(t_ * N / n))]
            lift = max(0.92, min(1.36, (f_now / 310.0) ** 0.50))
            amp[t_] *= lift * (1.0 + 0.065 * vib_raw[t_])
        # 脱・ピアニカ＆生身の声道共鳴：
        # F1 の口腔土台 (bump[0]=2.85) をしっかり据えつつ、g=[0.74, 0.76, 0.77] でフォルマントの斜面を適度に立たせ、
        # ビブラートや調音ダイナミクスで倍音が斜面を登り降りしたときに「倍音の明滅（Harmonic AM）」がキラキラと生まれるようにする！
        KT["bump"] = [2.85, 1.58, 1.52]
        KT["g"] = [0.74, 0.76, 0.77]
        KT["p_low"] = [5, 4, 3]
        KT["h1"] = 1.05
        KT["hk"] = {"2": 1.75, "3": 0.90}
    win = KT["agc_ms"] * SR / 1000; sm = KT.get("gain_sm_ms", 0) * SR / 1000
    CFG["causal"] = False if is_trance else bool(KT.get("causal")); ser = KT.get("serial", 0.0); sacc = [0.0] * N
    mix = [0.0] * N
    VB = [_vtrack(r, n, KT["vbump"], j) for j in range(3)] if KT.get("vbump") else None      # 102: per-vowel level of each resonance layer
    VF = _vtrack(r, n, KT["vfloor"]) if KT.get("vfloor") else None                           # 102: per-vowel floor level
    V45 = [_vtrack(r, n, KT["vf45"], j) for j in range(len(KT.get("f45", [])))] if KT.get("vf45") else None   # 102: per-vowel F4/F5 level
    # 床：元そのまま（谷の底）。OO.txt の vfloor を活かしつつ母音の濁りを抑える 0.25 倍
    fsrc = arakezuri(src, KT["floor_ara"][0], KT["floor_ara"][1]) if KT.get("floor_ara") else src
    fl_scale = [0.25 if (is_trance and r["voiced"][t] and cm[t] < 0.3) else 1.0 for t in range(n)]
    fl = _agc(fsrc, _per_sample([KT["floor"] * fl_scale[t] * math.sqrt(Ef) * amp[t] * (VF[t] if VF else 1.0) for t in range(n)], N), KT.get("floor_agc", KT["agc_ms"]) * SR / 1000, KT.get("floor_sm", KT.get("gain_sm_ms", 0)) * SR / 1000)
    for i in range(N): mix[i] += fl[i]
    # 山三つ：道筋 F1..F3 で一つずつ削り出す（くびれ＋平均の引き算）
    for j in range(3):
        Fj = _per_sample(r["F%d" % (j + 1)], N)
        bp = yama_bp(src, Fj, KT["g"][j], p_low=KT["p_low"][j]) if KT.get("p_low") else yama_bp(src, Fj, KT["g"][j])
        tg = _per_sample([KT["bump"][j] * math.sqrt(Ej[j][t]) * amp[t] * (VB[j][t] if VB else 1.0) for t in range(n)], N)
        smj = (18 if is_trance else (KT["gain_sm_j"][j] if KT.get("gain_sm_j") else KT.get("gain_sm_ms", 0))) * SR / 1000
        winj = (14 if is_trance else (KT["agc_j"][j] if KT.get("agc_j") else KT["agc_ms"])) * SR / 1000
        if KT.get("gsm_c") and j > 0:
            bq = _agc(bp, tg, KT["gsm_c"][1] * SR / 1000, KT["gsm_c"][0] * SR / 1000); bp = _agc(bp, tg, winj, smj)
            bp = [cmS[i] * bq[i] + (1 - cmS[i]) * bp[i] for i in range(N)]
        else: bp = _agc(bp, tg, winj, smj)
        for i in range(N): mix[i] += bp[i]
    # 102：F1 の肩（OO.txt / R103 の母音別 vf1x を活かし、F1-F2 間の谷がピアニカのように痩せるのを防ぐ）
    f1x_tr = 0.65 if is_trance else 1.0
    for qx, (ratio, rel) in enumerate(KT.get("f1x", [])):
        VX = _vtrack(r, n, KT["vf1x"], qx) if KT.get("vf1x") else None
        bp = yama_bp(src, _per_sample([min(f * ratio, 9000.0) for f in r["F1"]], N), KT.get("f1x_g", 0.5))
        tg = _per_sample([f1x_tr * rel * KT["bump"][0] * math.sqrt(Ej[0][t]) * amp[t] * (VX[t] if VX else 1.0) * (1 - KT.get("f1x_cmute", 0.0) * cm[t]) for t in range(n)], N)
        bp = _agc(bp, tg, KT["agc_j"][0] * SR / 1000 if KT.get("agc_j") else win, KT["gain_sm_j"][0] * SR / 1000 if KT.get("gain_sm_j") else sm)
        for i in range(N): mix[i] += bp[i]
    if KT.get("h1"):                       # 103：声の高さそのもの（基音）の山をもう一つ（S.txt の h1_hz 規則もそのまま適用し、開母音でH1がリードのように鳴りっぱなしになるのを防ぐ！）
        bp = yama_bp(src, [SR / PER[i] for i in range(N)], 0.72 if is_trance else KT.get("h1_g", 0.7))
        hw = [1.0] * n
        if KT.get("h1_near"):
            lo_, hi_, mn_ = KT["h1_near"]
            for t in range(n):
                q = r["F1"][t] / (SR / PER[min(N - 1, int(t * N / n))])
                hw[t] = mn_ + (1 - mn_) * max(0.0, min(1.0, (q - lo_) / (hi_ - lo_)))
        if KT.get("h1_far"):
            lo_, hi_, mn_ = KT["h1_far"]
            for t in range(n):
                q = r["F1"][t] / (SR / PER[min(N - 1, int(t * N / n))])
                hw[t] *= 1 - (1 - mn_) * max(0.0, min(1.0, (q - lo_) / (hi_ - lo_)))
        if KT.get("h1_hz"):
            lo_, hi_, mn_ = KT["h1_hz"]
            for t in range(n): hw[t] *= 1 - (1 - mn_) * max(0.0, min(1.0, (r["F1"][t] - lo_) / (hi_ - lo_)))
        tg = _per_sample([KT["h1"] * hw[t] * math.sqrt(Ej[0][t]) * amp[t] for t in range(n)], N)
        bp = _agc(bp, tg, (22 if is_trance else KT.get("h1_agc", 20)) * SR / 1000, (24 if is_trance else KT.get("h1_sm", 20)) * SR / 1000)
        for i in range(N): mix[i] += vo[i] * bp[i]
    for kk, rel in sorted((KT.get("hk") or {}).items()):
        bp = yama_bp(src, [float(kk) * SR / PER[i] for i in range(N)], 0.72 if is_trance else KT.get("h1_g", 0.7))
        VK = _vtrack(r, n, {v: d.get(str(kk), 1.0) for v, d in KT["vhk"].items()}) if KT.get("vhk") else None
        tg = _per_sample([rel * (VK[t] if VK else 1.0) * math.sqrt(Ej[0][t]) * amp[t] for t in range(n)], N)
        bp = _agc(bp, tg, (22 if is_trance else KT.get("h1_agc", 20)) * SR / 1000, (24 if is_trance else KT.get("h1_sm", 20)) * SR / 1000)
        for i in range(N): mix[i] += vo[i] * bp[i]
    # 76：F4・F5（声道長・母音・F3に連動する高次フォルマント山）
    fs_hi = fs[2] if isinstance(fs, (list, tuple)) else float(fs)
    for q45, (fq, rel) in enumerate(KT.get("f45", [])):
        if is_trance:
            # 固定周波数ではなく、母音ごとに動く F3 と声道スケール fs_hi に連動して F4/F5 の山を動かす
            off_hz = (1040.0 if q45 == 0 else 2020.0) * fs_hi
            fq_ = _per_sample([min(f + off_hz, 8600.0) for f in r["F3"]], N)
        elif KT.get("f45_f3"):
            fq_ = _per_sample([min(f + fq, 9000.0) for f in r["F3"]], N)
        else:
            fq_ = [fq] * N
        bp = yama_bp(src, fq_, 0.76 if is_trance else KT["g"][2], p_low=4 if is_trance else 3)
        if is_trance:
            tg = _per_sample([rel * 0.62 * math.sqrt(Ej[2][t]) * amp[t] * (1 - 0.9 * cm[t]) for t in range(n)], N)
        else:
            tg = _per_sample([rel * math.sqrt(Ej[2][t]) * amp[t] * (1 - KT.get("f45_cmute", 0.0) * cm[t]) * (V45[q45][t] if V45 else 1.0) for t in range(n)], N)
        bp = _agc(bp, tg, KT.get("f45_agc", KT["agc_ms"]) * SR / 1000, KT.get("f45_sm", KT.get("gain_sm_ms", 0)) * SR / 1000)
        for i in range(N): mix[i] += bp[i]
    if is_trance:
        # 梨状陥凹（Piriform Fossa）の動的反共振ノッチ：
        # 固定周波数（4.5kHz一律）ではなく、女性歌手の声道スケール(fs_hi)・母音ごとの咽頭腔容積・音高(喉頭挙上)に応じて
        # 4.5〜5.5kHz の間で有機的に移動する反共振の谷を「引き算の削り出し」で刻み、3山楽器から「生身の喉の立体感」へ昇華させる！
        PIRI_BASE = {"o": 4720.0, "a": 4820.0, "u": 4980.0, "e": 5180.0, "i": 5320.0}
        v_map_tr = r.get("v_map") or ["a"] * n
        f_piri_tr = []
        for t_ in range(n):
            f_now = SR / PER[min(N - 1, int(t_ * N / n))]
            pb = PIRI_BASE.get(v_map_tr[t_], 4950.0) * fs_hi
            # 音高上昇に伴う喉頭位置の変化と F3 の動きを反映
            f_p = pb + 0.42 * max(0.0, f_now - 260.0) + 0.12 * (r["F3"][t_] - 2850.0)
            f_piri_tr.append(max(4100.0, min(6200.0, f_p)))
        bp_piri = yama_bp(mix, _per_sample(f_piri_tr, N), 0.80, p_low=4)
        for i in range(N):
            mix[i] -= 0.52 * vo[i] * (1.0 - cmS[i]) * bp_piri[i]
    # 帯：さ・しゃ・破裂などのノイズの帯を、新しいノイズから別に削り出して置く
    for k, (t0, t1, cen, sd, lev) in enumerate(r["bands"]):
        a = max(0, int((t0 - 0.01) * SR)); b = min(N, int((t1 + 0.01) * SR))
        if b <= a: continue
        z = _band(r_band, b - a, cen, sd, KT)
        tg = _per_sample([KT["band"] * math.sqrt(Eb[k][t]) * amp[t] for t in range(n)], N)
        for i in range(a, b): mix[i] += z[i - a] * tg[i]
    if KT["breath"]:                       # 73 の息の層（生身の声の空気感を残しつつ曇らせない 0.12 倍）
        B = rc["breath"]; bx = karuku(sabun(noise(r_breath, N), B["sabun_w1"], B["sabun_w2"]), B["karuku_w"]); br = rms(bx) or 1.0
        ea = _per_sample(amp, N); mr = rms(mix) or 1.0
        br_scale = 0.14 if is_trance else 1.0
        for i in range(N): mix[i] += KT["breath"] * br_scale * mr * ea[i] * bx[i] / br
    if KT.get("henv") and not is_trance:   # 82b：exp35 の人の母音包絡
        st5_ = [st[min(N - 1, int(t * N / n))] for t in range(n)]; sv_ = sorted(st5_[t] for t in range(n) if r["voiced"][t]) or [0.0]
        mix = (_HENV_REF or _henv)(mix, src, dict(r, cm=cm, st5=st5_, st5_med=sv_[len(sv_) // 2]), KT, SR)
    if is_trance:
        # 147 の核心＋低中域の谷の自然化：
        # 950Hz 以下の基音核は純倍音のまま保ち、1.2〜2.5kHz の中域にもわずかな息の湿り気 (5.5%〜14%) を織り込んで
        # 「真空に浮かぶ電子倍音（谷 24〜37dB）」から「生身の声の倍音の谷（16〜22dB）」へ自然に馴染ませる！
        iki_tr = {"pts": [[950, 0.0], [1600, 0.055], [2500, 0.14], [4800, 0.38], [8000, 0.60]], "w_hz": 520, "fl": 0.52}
        mix = _iki_up(mix, r, SR, iki_tr, random.Random(rc["seed"] + 31))
    elif KT.get("iki"):
        mix = _iki_up(mix, r, SR, KT["iki"], random.Random(rc["seed"] + 31))
    if KT.get("ap_n") and KT.get("ap_on") == "mix":
        # 81：40段の全域通過フィルタ (ap_n=40) をそのまま通し、ピアニカの金属リードのような位相の張り付きを人間の声道らしく柔らかく分散させる！
        mix = _ap_cascade(mix, random.Random(rc["seed"] + 21), KT)
    if KT.get("tilt") and not is_trance: mix = arakezuri(mix, KT["tilt"], 1)
    if is_trance:
        mix = _onaji_kuukan(mix, vo, N, SR, rc["seed"])
    pk = max(abs(v) for v in mix) or 1.0
    if KT.get("out_dbfs"):                 # 76：声のある所の RMS を out_dbfs に（人の録音は -25 dBFS 前後）
        fr_ = int(0.02 * SR); E_ = [sum(v * v for v in mix[i:i + fr_]) / fr_ for i in range(0, N - fr_, fr_)]; mx = max(E_) or 1.0
        act = [e for e in E_ if e > mx * 1e-3]; ar = math.sqrt(sum(act) / len(act)) or 1.0
        k_ = min(10 ** (KT["out_dbfs"] / 20) / ar, 0.891 / pk)
        return [v * k_ for v in mix], r["moras"]
    return [v * 0.891 / pk for v in mix], r["moras"]

T75 = dict(E74, **{"fushi.mode": "kawaii"})

FILES = [("1.wav", dict(E72, seed=2024), "72"), ("2.wav", dict(E74, seed=2024), "73"), ("3.wav", dict(E74, seed=7), "73 別の乱数"), ("4.wav", dict(E74, seed=42), "73 もう一つ別の乱数")]

# ---- 75 の一番：規則テーブル（kotoba.TEXTBOOK、話す速さだけ 1.15 倍ゆっくり）＋東京式アクセントの高さ（accent.py）
#      漂い 1.3→0.5・周期ごとの揺れ 1%→0.5%（ASR を下げていた）、床（谷の底）0.4、山 g 0.7、4本くびれ 0.3、帯 0.8、子音の閉じ（dl）あり
K75 = dict(floor=0.4, line_g=0.3, g=[0.7, 0.7, 0.7], use_dl=True, band=0.8, accent=True, params=dict(kotoba.TEXTBOOK, rate=1.15))
E75 = dict(T75, kotoba=K75, tadayoi=0.5, yure_hayai=0.005, **{"fushi.haneru_st": 3.0})
SENT75 = ["こんにちわ", "ありがとう", "きょうもいっしょにがんばろうね", "アノネ、チョットダケキイテホシイコトガアルノ", "モオ、シラナインダカラ", "ネエネエ、コレミテミテ、カワイイデショ"]
FILES = [(f"out/{k + 1}.wav", dict(E75, text=t, seed=2024), t) for k, t in enumerate(SENT75)]

# ---- 76：知らない短い文でも聞き取れるように（ASR の耳で、tune＝8文×3種＋20文×2種 で決めた）
#   1) 文の前の静けさ 0.15→0.6 秒（ASR が頭の拍を落とさない）
#   2) 濁った破裂（が・ば・だ）の閉じを深く（-1.2→-4）・破裂の帯を強く（3→4）：鼻の音（ま・な）に聞こえていた
#   3) ら行のはじき：短く（25 ms）・深く（-1.5→-4）：な・の に聞こえていた
#   4) オ段＋ウ は長い「オー」で言う（教科書の音韻規則。う の山に動かない）
K76P = dict(kotoba.TEXTBOOK, rate=1.15, ou_long=True, vdl=-4.0, vbg=4.0, rdl=-4.0, CDUR=dict(kotoba.TEXTBOOK["CDUR"], r=25))
E76 = dict(E75, kotoba=dict(K75, pre=0.6, params=K76P))
# ---- 76 の一番（合わせ）：E76（聞き取り）＋響き全体 ×1.15 と道筋 30ms ならし（声道を短く＝子ども）＋層の強さ 20ms ならし（ちらつき減）＋声の所 -20 dBFS
E76 = dict(E76, kotoba=dict(E76["kotoba"], fscale=1.15, gain_sm_ms=20, out_dbfs=-20, params=dict(E76["kotoba"]["params"], smooth=30)))
SENT76 = SENT75 + ["おやすみ", "だいすきだよ", "ごめんね", "またあそぼうね"]
FILES = [(f"out/{k + 1}.wav", dict(E76, text=t, seed=2024), t) for k, t in enumerate(SENT76)]

# ---- 77a：子どもらしさ（CED child）を上げる。E76 ＋ 包絡の形：
#   1) F2/F3 の層だけ強さをゆっくり均す（ならし 40 ms・AGC 窓 30 ms）、F1 は速いまま（20 / 10 ms）
#   2) F2/F3 の道筋だけ 50 ms ならし（F1 は 30 ms のまま）
#   3) F2/F3 の層 ×1.4、F4/F5 の決まった山（4600 Hz ×0.5、5800 Hz ×0.3：短い声道）
#   4) 話す速さ ×0.85（rate 1.15→1.353）
#   母音の的（VT）を子どもの値に替えるのは試したが、知らない文の ASR を下げたので入れない（E76 のまま）。
E77a = dict(E76, kotoba=dict(E76["kotoba"], gain_sm_j=[20, 40, 40], agc_j=[10, 30, 30], f45=[[4600, 0.5], [5800, 0.3]], bump=[1.0, 1.4, 1.4],
                             params=dict(E76["kotoba"]["params"], smooth_j=[30, 50, 50], rate=1.15 / 0.85)))
# ---- 77 の一番（合わせ）：77a（上の層をならす・4.6/5.8kHz の山・ゆっくり）＋77b（くし 6本・前の自分を 0.8 引いて高い方を持ち上げる・周期の揺れを減らす）
E77 = dict(E77a, kugiri=dict(E77a["kugiri"], yure=0.003), yure_hayai=0.002, **{"line.n": 6})
E77["kotoba"] = dict(E77a["kotoba"], line_g=0.5, emph=0.8)

# ---- 78：E77 ＋ 話す速さ ×0.8（0.85→0.8）＋ お の的 F1+120/F2+100 ＋ F4/F5 の山を F3 に付いて動かす（F3+1100 ×0.5、F3+2300 ×0.3）＋ 高さ +3%
E78 = dict(E77, **{"line.D_center": 53.1 / 1.03})
E78["kotoba"] = dict(E77["kotoba"], f45_f3=True, f45=[[1100, 0.5], [2300, 0.3]],
                     params=dict(E77["kotoba"]["params"], rate=1.15 / 0.8,
                                 VT={'a': (850, 1400, 2800), 'i': (330, 2750, 3300), 'u': (380, 1600, 2700), 'e': (520, 2350, 3000), 'o': (650, 1050, 2850)}))

# ---- 78 の一番（合わせ）：E78（ゆっくり×0.8・お を開く・高い山が F3 について動く・高さ+3%）
#   ＋78b（子音のまわり ±20ms と っ・ん だけ：高い山を消す・F2/F3 の強さのならし 10ms・前の自分引きをやめる）
E78M = dict(E78, kotoba=dict(E78["kotoba"], cm_pad=20, cm_sm=10, cm_q=True, f45_cmute=1.0, gsm_c=[10, 10], emph_c=0.0))
FILES = [(f"out/{k + 1}.wav", dict(E78M, text=t, seed=2024), t) for k, t in enumerate(SENT76)]

# ---- 79：E78M ＋ 話す速さ 1.30（×0.8→約×0.885）＋ 前の自分引き emph 0.8→0.5 ＋ 77a の F2/F3 だけのならし（道筋 50ms・強さ 40ms・AGC 30ms）をやめて F1 と同じに
#   ニューラル TTS らしさ（時間方向に滑らかすぎる：f0 の細かい揺れ・スペクトルの動きが小さい）を下げつつ、ASR・CED child・超耳を保つ（c79n で選んだ）
E79 = dict(E78M, kotoba=dict(E78M["kotoba"], emph=0.5, gain_sm_j=[20, 20, 20], agc_j=[10, 10, 10],
                             params=dict(E78M["kotoba"]["params"], rate=1.30, smooth_j=[30, 30, 30])))
FILES = [(f"out/{k + 1}.wav", dict(E79, text=t, seed=2024), t) for k, t in enumerate(SENT76)]

if __name__ == "__main__":
    out = {"base": BASE, "files": []}
    for name, ch, note in FILES:
        x, spans = make(variant(ch)); os.makedirs(os.path.dirname(os.path.join(OUT, name)), exist_ok=True); write(os.path.join(OUT, name), x)
        out["files"].append({"file": name, "changes": ch, "note": note, "pieces": len(spans)})
    with open(os.path.join(OUT, "out", "recipes.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
