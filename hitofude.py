# hitofude.py — 一筆彫り (Single-Wire Subtractive Speech & Singing Synthesis)
# 標準ライブラリのみ (Python 3, 外部パッケージ・外部データファイル一切不要)。
#
# 【LLM向け設計原則】
#   音になる信号線は最初から最後まで「たった1本のホワイトノイズ x」のみを4段階で削って声と吐息にする。
#   - 固定波形の粒スタンプ (grain) なし → 40段オールパス位相散らし不要
#   - 有声/無声・子音帯・息の音声信号はすべて同じ1本のノイズ線 x から彫る（ピッチ漂い・ジッタ・ビブラートの制御揺らぎのみ別シード乱数）
#   - 帯域ごとの自動利得制御 (_agc) なし → 各ノブはほぼ直交に効く（g_vo 変化時の帯域比揺れも ±2 dB 以内）
#   - STFT 往復なし → 時間領域の1パス直列処理のみ
import array
import cmath
import hashlib
import math
import random
import sys
import wave

import accent
import kotoba

SR = 44100

# kotoba.tracks_from_kana に渡す日本語音韻・調音パラメータ（旧 carve.py E79 相当の確定値）
KOTOBA_PRM = dict(
    kotoba.TEXTBOOK,
    ou_long=True,       # オ段＋ウを長音「オー」として発音
    vdl=-4.0,           # 有声破裂音 (g, d, b) の閉鎖減衰
    vbg=4.0,            # 有声破裂音のバースト強度
    rdl=-4.0,           # ラ行弾き音の閉鎖減衰
    smooth=30,          # フォルマント軌道の平滑化窓 (ms)
    smooth_j=[30, 30, 30],
    fric_hold=20,       # 無声子音区間でのフォルマント保持 (ms)
    vl_hold=True,
    CDUR=dict(kotoba.TEXTBOOK["CDUR"], r=25),
    VT={
        "a": (850, 1400, 2800),
        "i": (330, 2750, 3300),
        "u": (380, 1600, 2700),
        "e": (520, 2350, 3000),
        "o": (650, 1050, 2850),
    },
)


# ==============================================================================
# 基礎ノミ（時間領域の引き算・移動平均プリミティブ：正弦波オシレータ不使用）
# ==============================================================================
def noise(rng, n):
    """原石：[-1, +1] 一様ホワイトノイズを1本生成する。"""
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def rms(x):
    s = sum(v * v for v in x if v != 0.0)
    c = sum(1 for v in x if v != 0.0) or 1
    return (s / c) ** 0.5


def _per_sample(fr, N, fp_ms=5.0):
    """5ms フレーム列 fr をサンプル単位 (N 点) に線形補間する。"""
    n = len(fr)
    step = 1000.0 / (fp_ms * SR)
    out = [0.0] * N
    for i in range(N):
        t = i * step
        k = int(t)
        if k >= n - 1:
            out[i] = fr[-1]
        else:
            u = t - k
            out[i] = fr[k] * (1.0 - u) + fr[k + 1] * u
    return out


def arakezuri(x, w, p=1):
    """粗削り（ローパス）：幅 w サンプルの移動平均を p 回かける。最初の零点は SR / w Hz。"""
    for _ in range(p):
        y = [0.0] * len(x)
        s = 0.0
        for i in range(len(x)):
            s += x[i]
            if i >= w:
                s -= x[i - w]
            y[i] = s / min(i + 1, w)
        x = y
    return x


def arakezuri_t(x, w, p, H):
    """時間可変の粗削り：H[i]=1 の区間（破裂・摩擦子音など）は高域の鋭さを削り残す。"""
    s = arakezuri(x, w, p)
    return [x[i] - (1.0 - H[i]) * (x[i] - s[i]) for i in range(len(x))]


def karuku(x, w):
    """軽くする（ハイパス）：幅 w の移動平均を引いて DC〜低域の濁りを落とす。"""
    a = arakezuri(x, w)
    return [x[i] - a[i] for i in range(len(x))]


def furafura(n, rng, d0, haba, osoi):
    """ピッチのゆっくりした自然な漂い（平滑化ランダムウォーク、単位は呼び出し側）。"""
    if haba == 0.0:
        return [d0] * n
    v = 0.0
    walk = [0.0] * n
    for i in range(n):
        v += rng.uniform(-1.0, 1.0)
        v *= 0.9995
        walk[i] = v
    sm = arakezuri(walk, max(1, int(osoi * SR)), 2)
    mean = sum(sm) / n
    sm = [s - mean for s in sm]
    pk = max(abs(s) for s in sm) or 1.0
    return [d0 + haba * s / pk for s in sm]


def _heikin(x, W):
    """前後に位相ずれのない中心移動平均（窓幅 W[i] はサンプルごとに可変、累積和で O(N)）。"""
    n = len(x)
    cs = [0.0] * (n + 1)
    for i in range(n):
        cs[i + 1] = cs[i] + x[i]
    y = [0.0] * n
    for i in range(n):
        h = max(1, int(W[i] / 2))
        a = max(0, i - h)
        b = min(n, i + h + 1)
        y[i] = (cs[b] - cs[a]) / (b - a)
    return y


def _comb(x, D, g):
    """半周期 D 前の自分を反転フィードバックして奇数倍音 (SR / 2D) を立てる。"""
    n = len(x)
    y = [0.0] * n
    for i in range(n):
        d = D[i]
        k = int(d)
        fr = d - k
        a = i - k
        b = a - 1
        acc = (y[a] * (1.0 - fr) + y[b] * fr) if b >= 0 else 0.0
        y[i] = x[i] - g * acc
    return y


def _ffbb(x, D, g):
    """前後双方向コムフィルタ（ゼロ位相共振）。"""
    y = _comb(x, D, g)
    y = _comb(y[::-1], D[::-1], g)
    return y[::-1]


def yama_bp(x, F, g=0.7, p_low=3, p_high=2):
    """受動フォルマント帯域通過：周波数 F[i] Hz の山1つだけを残し、上下の裾を引き算で削る。"""
    F_c = [f / 0.95 for f in F]
    D_ = [SR / (2.0 * f) for f in F_c]
    bp = _ffbb(x, D_, g)
    norm = (1.0 - g) ** 2
    for _ in range(p_low):
        bp = _heikin(bp, [SR / (2.0 * f) for f in F_c])
        norm /= 0.6366
    for _ in range(p_high):
        w = _heikin(bp, [2.0 * SR / f for f in F_c])
        bp = [bp[i] - w[i] for i in range(len(bp))]
    return [v * norm for v in bp]


def _comb_period(x, PER, G):
    """引き算①（音源くびれ）：周期 PER[i] と食い違う倍音間の谷を削る。
    入力に sqrt(1 - g^2) を掛けるためエネルギーが発散せず、G[i]=0 では同じノイズ線を素通しする。"""
    n = len(x)
    y = [0.0] * n
    _sqrt = math.sqrt
    for i in range(n):
        g = G[i]
        if g <= 1e-4:
            y[i] = x[i]
            continue
        c_in = _sqrt(1.0 - g * g)
        p = PER[i]
        k = int(p)
        u = p - k
        i0 = i - k
        if i0 - 2 >= 0 and i0 + 1 < i:
            ym1, y0, y1, y2 = y[i0 + 1], y[i0], y[i0 - 1], y[i0 - 2]
            fb = (
                (-u * (u - 1.0) * (u - 2.0) / 6.0) * ym1
                + ((u + 1.0) * (u - 1.0) * (u - 2.0) / 2.0) * y0
                - ((u + 1.0) * u * (u - 2.0) / 2.0) * y1
                + ((u + 1.0) * u * (u - 1.0) / 6.0) * y2
            )
        elif i0 - 1 >= 0:
            fb = y[i0] * (1.0 - u) + y[i0 - 1] * u
        else:
            fb = 0.0
        y[i] = c_in * x[i] + g * fb
    return y


# ==============================================================================
# 本体：1本のホワイトノイズから4手で彫る音声・歌声合成
# ==============================================================================
def make_hitofude(
    text,
    seed=2024,
    hz=350.0,         # 基準ピッチ高さ (Hz)。女声 300〜360、子ども 400、男声 130〜165
    fscale=1.17,      # 声道長逆スケール（フォルマント倍率）。1.15〜1.22=女声/少女、0.88=太い男声
    rate=1.26,        # 話速倍率（小さいほど速い、1.0=標準教科書速度、1.25〜1.30=聞き取りやすい会話）
    g_vo=0.92,        # 有声時の倍音くびれ深さ G (0.0〜0.97)。2段直列の谷深さ ≒ 40*log10((1+G)/(1-G)) dB
    tilt_w=5,         # 高域粗削り幅 w (整数 >=1)。w=4〜5 で明るい女声、w=6 で柔らかい吐息、w>=8 で暗い声
    sigh=0.0,         # 句末の息抜き量 (0.0〜1.0)。句末母音後半で G を緩め、声を同じノイズ線の吐息へ戻す
    jitter=0.0013,    # 1周期ごとの微細周期揺らぎ率 (0.0 で完全周期ロボ、標準 0.0013)
    wander_st=0.18,   # ピッチの緩やかな自然漂い幅 (半音単位、0.0 で冷凍固定)
    level_k=0.65,     # 母音定常部の1スカラー音量整音強度 (0.0〜1.0、瞬間スペクトル傾斜変化は 0.00 dB)
    pre=0.6,          # 発話前の無音長 (秒)
    post=0.1,         # 発話後の無音長 (秒)
    uta_hz=None,      # 歌モード：モーラごとの目標周波数リスト [Hz, ...]（None なら話し声アクセント）
    vd_ms=None,       # 歌モード：モーラごとの母音長リスト [ms, ...]
    vib_c=6.0,        # 歌モード：長音ビブラート深さ (cent)
    accent_kw=None,   # 話し声アクセント指定辞書 (accent.annotate の phrases / question 等)
    out_r=None,       # 診断用：内部5ms軌道辞書を書き戻す出力先 dict
):
    fpz = kotoba.FP / 1000.0
    fend_at = 0.45 if sigh > 0.0 else 0.16
    prm = dict(KOTOBA_PRM, rate=float(rate), fend_at=fend_at)
    if vd_ms is not None:
        prm["vd_ms"] = vd_ms
    r = kotoba.tracks_from_kana(text, pre=pre, post=post, params=prm)
    n = r["n"]
    N = int(n * fpz * SR)
    if not any(r["voiced"]) and not r["bands"]:
        if out_r is not None:
            out_r.update(r, f0_tr=[0.0] * n)
        return [0.0] * N, r["moras"]

    # ピッチ軌道 f0_fr (Hz, 5ms フレーム)
    if uta_hz:
        f0_fr = [float(uta_hz[0])] * n
        k_ = 0
        for m_ in r["moras"]:
            if m_.get("kind") == "pau":
                continue
            h_ = float(uta_hz[min(k_, len(uta_hz) - 1)])
            k_ += 1
            for t_ in range(max(0, int(m_["a"] / fpz)), n):
                f0_fr[t_] = h_
        f0_fr = kotoba.smooth1(f0_fr, 34)
        if vib_c > 0.0:
            wv = max(3, int(round(1000.0 / kotoba.FP / 5.2 / 2.0)))
            vw = arakezuri(_comb(noise(random.Random(int(seed) + 33), n + 30 * wv), [wv] * (n + 30 * wv), 0.94), max(2, wv // 2), 2)[30 * wv : 30 * wv + n]
            vrm = (sum(v * v for v in vw) / n) ** 0.5 or 1.0
            t0_s = 0.0
            cur_h = None
            k_ = 0
            for m_ in r["moras"]:
                if m_.get("kind") == "pau":
                    cur_h = None
                    continue
                h_ = float(uta_hz[min(k_, len(uta_hz) - 1)])
                k_ += 1
                if h_ != cur_h:
                    cur_h = h_
                    t0_s = m_["b"]
                for t_ in range(max(0, int(m_["b"] / fpz)), min(n, int(m_["e"] / fpz))):
                    el = t_ * fpz - t0_s - 0.28
                    if el > 0.0:
                        f0_fr[t_] *= 2.0 ** ((vib_c * min(1.0, el / 0.26) * (vw[t_] / vrm / 1.414)) / 1200.0)
    else:
        acc = dict(accent.NORMAL, rng=6.2, jump=2.8, fall=3.8, sag=0.9, decl=1.4, fin=2.6) if sigh >= 0.25 else accent.CUTE
        f0_fr = accent.f0_rule(r["moras"], n, None, **dict(acc, reg=float(hz), **(accent_kw or {})))

    # 句末息抜きプロファイル (sigh_fr)：F1 下限計算より先に f0_fr の微低下も確定させる
    sigh_fr = [0.0] * n
    if sigh > 0.0:
        for idx_m, m_ in enumerate(r["moras"]):
            ib, ie = max(0, int(m_["b"] / fpz)), min(n, int(m_["e"] / fpz))
            if m_.get("kind") != "CV" or (ie - ib) < 7 or not any(r["voiced"][ib:ie]):
                continue
            rem = []
            for m2 in r["moras"][idx_m + 1 :]:
                if m2.get("kind") == "pau":
                    break
                rem.append(m2)
            is_end = not any(any(r["voiced"][max(0, int(m2["b"] / fpz)) : min(n, int(m2["e"] / fpz))]) for m2 in rem)
            if is_end:
                sp_ = max(1, ie - ib)
                for t_ in range(ib, ie):
                    u = (t_ - ib) / sp_
                    if u > 0.30:
                        s_v = min(1.0, sigh) * (((u - 0.30) / 0.70) ** 1.10)
                        sigh_fr[t_] = s_v
                        f0_fr[t_] *= 2.0 ** (-0.18 * s_v / 12.0)

    fs = float(fscale)
    F1 = [max(r["F1"][t] * fs, 1.04 * f0_fr[t] if r["voiced"][t] else 180.0) for t in range(n)]
    F2 = [min(r["F2"][t] * fs, 8500.0) for t in range(n)]
    F3 = [min(r["F3"][t] * fs, 9000.0) for t in range(n)]

    # 子音破裂・摩擦帯域 (r["bands"])
    f_cons_cen = [2500.0] * n
    f_cons_w = [0.0] * n
    cons_sharp = [0.0] * n
    last_cen = 2500.0
    for (t0, t1, cen, _sd, lev) in sorted(r["bands"], key=lambda b: b[0]):
        ia, ib = max(0, int(round(t0 / fpz))), min(n, int(round(t1 / fpz)) + 1)
        last_cen = float(cen)
        for t_ in range(max(0, ia - 2), min(n, ib + 2)):
            f_cons_cen[t_] = last_cen
        for t_ in range(ia, ib):
            f_cons_w[t_] = max(f_cons_w[t_], min(3.4, 0.58 * float(lev)))
            cons_sharp[t_] = 1.0
    for t_ in range(1, n):
        if f_cons_w[t_] == 0.0 and cons_sharp[t_] == 0.0:
            f_cons_cen[t_] = f_cons_cen[t_ - 1]

    vo_sm = kotoba.smooth1([1.0 if v else 0.0 for v in r["voiced"]], 10)
    sigh_sm = kotoba.smooth1(sigh_fr, 14)
    g_fr = [vo_sm[t] * float(g_vo) * (1.0 - 0.88 * sigh_sm[t]) for t in range(n)]

    rng = random.Random(int(seed))
    f0S = _per_sample(f0_fr, N)
    wander = furafura(N, random.Random(int(seed) + 1), 0.0, float(wander_st), 0.09)
    PER = [SR / max(60.0, f0S[i] * (2.0 ** (wander[i] / 12.0))) for i in range(N)]
    if jitter > 0.0:
        rng_j = random.Random(int(seed) + 7)
        jit = float(jitter)
        idx_p = 0
        while idx_p < N:
            pl = max(2, int(PER[idx_p]))
            jf = 1.0 + rng_j.uniform(-jit, jit)
            for k in range(idx_p, min(N, idx_p + pl)):
                PER[k] *= jf
            idx_p += pl

    # === 原石：最初から最後までたった1本のホワイトノイズ ===
    x = noise(rng, N)

    # 【引き算①】倍音の隙間の谷を引く（2段直列）
    GS = _per_sample(g_fr, N)
    x = _comb_period(x, PER, GS)
    x = _comb_period(x, PER, GS)

    # 【引き算②】f0未満の濁りと高域の角を引く（子音破裂・摩擦だけは H=1 で鋭さを残す）
    x = karuku(x, 115 if hz >= 200.0 else 220)
    tw = max(1, int(round(tilt_w)))
    x = arakezuri_t(x, tw, 2, _per_sample(cons_sharp, N))
    if sigh > 0.0:
        x = arakezuri_t(x, tw + 3, 2, _per_sample([1.0 - 0.85 * sigh_sm[t] for t in range(n)], N))

    # 【引き算③】声道の山以外の谷を引く（帯域ごと _agc ゼロの受動声道）
    bp1 = yama_bp(x, _per_sample(F1, N), g=0.56, p_low=3, p_high=1)
    bp2 = yama_bp(x, _per_sample(F2, N), g=0.73, p_low=3, p_high=2)
    bp3 = yama_bp(x, _per_sample(F3, N), g=0.75, p_low=3, p_high=2)
    bp4 = yama_bp(x, _per_sample([min(8600.0, F3[t] + 1150.0 * fs) for t in range(n)], N), g=0.72, p_low=3, p_high=2)
    bpc = yama_bp(x, _per_sample(f_cons_cen, N), g=0.50, p_low=1, p_high=2)

    uv_lift = [1.0 + 1.15 * (1.0 - vo_sm[t] + 0.55 * sigh_sm[t]) for t in range(n)]
    G1S = _per_sample(r["G1"], N)
    G2S = _per_sample([r["G2"][t] * uv_lift[t] for t in range(n)], N)
    G3S = _per_sample([r["G3"][t] * uv_lift[t] for t in range(n)], N)
    W4S = _per_sample([0.34 * (1.0 - 0.45 * sigh_sm[t]) * (1.0 - cons_sharp[t]) for t in range(n)], N)
    FCW = _per_sample(kotoba.smooth1(f_cons_w, 6), N)
    y = [
        0.025 * x[i]
        + 1.35 * G1S[i] * bp1[i]
        + 0.72 * G2S[i] * bp2[i]
        + 0.56 * G3S[i] * bp3[i]
        + W4S[i] * G3S[i] * bp4[i]
        + 0.90 * FCW[i] * bpc[i]
        for i in range(N)
    ]

    # 【引き算④】スペクトル傾斜を 0.00 dB も変えない1本のスカラー整音 ＋ 時間包絡切り出し
    if level_k > 0.0:
        w_sc = int(0.028 * SR)
        p_loc = _heikin([v * v for v in y], [w_sc] * N)
        v_pows = [p_loc[int((t + 0.5) * fpz * SR)] for t in range(n) if r["voiced"][t] and sigh_sm[t] < 0.1 and cons_sharp[t] < 0.1]
        ref_rms = math.sqrt(sorted(v_pows)[len(v_pows) // 2]) if v_pows else (rms(y) or 1.0)
        eps = (0.12 * ref_rms) ** 2 + 1e-24
        w_lv = _per_sample(kotoba.smooth1([float(level_k) * vo_sm[t] * (1.0 - sigh_sm[t]) * (1.0 - cons_sharp[t]) for t in range(n)], 14), N)
        g_lv = _heikin([1.0 + w_lv[i] * (min(2.2, max(0.45, ref_rms / math.sqrt(p_loc[i] + eps))) - 1.0) for i in range(N)], [int(0.018 * SR)] * N)
        y = [y[i] * g_lv[i] for i in range(N)]

    lo_fr = [r["loud"][t] + r["dl"][t] - (0.45 * sigh_sm[t] if sigh > 0.0 else 0.0) for t in range(n)]
    env = _per_sample([math.exp(v / 2.0) for v in lo_fr], N)
    out = [y[i] * env[i] for i in range(N)]
    pk = max(abs(v) for v in out) or 1.0
    if out_r is not None:
        out_r.update(r, f0_tr=f0_fr)
    return [v * 0.891 / pk for v in out], r["moras"]


def _pcm16_bytes(samples):
    """[-1, +1] float 列を 16-bit signed little-endian PCM バイト列へ変換する。"""
    pcm = array.array("h", [max(-32768, min(32767, int(round(v * 32767)))) for v in samples])
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def write_wav(path, samples):
    """[-1, +1] float 列を 16-bit mono PCM WAV として書き出す。"""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(_pcm16_bytes(samples))


# ==============================================================================
# LLM用「耳の代わり」：標準ライブラリのみの自己音響計測 (numpy/scipy 一切不要)
# ==============================================================================
_FFT_CACHE = {}


def _fft_radix2(a):
    n = len(a)
    if n <= 1:
        return list(a)
    plan = _FFT_CACHE.get(n)
    if plan is None:
        bits = (n - 1).bit_length()
        bitrev = [int(format(i, f"0{bits}b")[::-1], 2) for i in range(n)]
        tws = []
        step = 2
        while step <= n:
            half = step // 2
            tws.append((step, half, [cmath.exp(-2j * math.pi * k / step) for k in range(half)]))
            step <<= 1
        plan = (bitrev, tws)
        _FFT_CACHE[n] = plan
    bitrev, tws = plan
    out = [complex(a[j]) for j in bitrev]
    for step, half, tw in tws:
        for s in range(0, n, step):
            for k in range(half):
                u = out[s + k]
                v = out[s + k + half] * tw[k]
                out[s + k] = u + v
                out[s + k + half] = u - v
    return out


def hakaru(samples, r_info):
    """合成波形と out_r から、LLMが音色を数値検証するための実測指標辞書を返す（標準ライブラリのみ）。"""
    N = len(samples)
    fpz = kotoba.FP / 1000.0
    voiced = r_info.get("voiced") or []
    moras = r_info.get("moras") or []
    f0_tr = r_info.get("f0_tr") or [0.0]
    pk = max((abs(v) for v in samples), default=0.0)
    v_sq, v_cnt = 0.0, 0
    for t, vo in enumerate(voiced):
        if vo:
            a, b = int(t * fpz * SR), min(N, int((t + 1) * fpz * SR))
            for i in range(a, b):
                v_sq += samples[i] * samples[i]
            v_cnt += max(0, b - a)
    rms_v = math.sqrt(v_sq / v_cnt) if v_cnt > 0 else rms(samples)
    crest_db = 20.0 * math.log10(pk / (rms_v + 1e-12)) if pk > 0.0 and rms_v > 0.0 else 0.0

    nf = 2048
    hb = nf // 2 + 1
    win = [0.5 - 0.5 * math.cos(2.0 * math.pi * k / nf) for k in range(nf)]
    fq = [k * SR / nf for k in range(hb)]

    def _win_spec(s0):
        seg = samples[s0 : s0 + nf]
        if len(seg) < nf:
            seg = list(seg) + [0.0] * (nf - len(seg))
        return _fft_radix2([seg[k] * win[k] for k in range(nf)])

    sp_acc = [0.0] * hb
    if 0 < N < nf and any(voiced):
        spec = _win_spec(0)
        for k in range(hb):
            sp_acc[k] += spec[k].real ** 2 + spec[k].imag ** 2
    for s0 in range(0, N - nf + 1, nf):
        tc = int(((s0 + nf // 2) / SR) / fpz)
        if 0 <= tc < len(voiced) and voiced[tc]:
            spec = _win_spec(s0)
            for k in range(hb):
                sp_acc[k] += spec[k].real ** 2 + spec[k].imag ** 2
    has_sp = any(v > 0.0 for v in sp_acc)
    b0 = sum(sp_acc[k] for k in range(hb) if 120.0 <= fq[k] < 1000.0) + 1e-24
    b1 = 10.0 * math.log10((sum(sp_acc[k] for k in range(hb) if 1000.0 <= fq[k] < 2600.0) + 1e-24) / b0) if has_sp else 0.0
    b2 = 10.0 * math.log10((sum(sp_acc[k] for k in range(hb) if 2600.0 <= fq[k] < 5600.0) + 1e-24) / b0) if has_sp else 0.0

    def _tani_at(ts):
        if N == 0:
            return 0.0
        s0 = max(0, min(max(0, N - nf), int(ts * SR) - nf // 2))
        spec = _win_spec(s0)
        sp_db = [10.0 * math.log10(spec[k].real ** 2 + spec[k].imag ** 2 + 1e-24) for k in range(hb)]
        f0 = max(80.0, f0_tr[min(len(f0_tr) - 1, max(0, int(ts / fpz)))])
        diffs = []
        for h_idx in range(1, 7):
            ps = [sp_db[k] for k in range(hb) if (h_idx - 0.18) * f0 <= fq[k] <= (h_idx + 0.18) * f0]
            vs = [sp_db[k] for k in range(hb) if (h_idx + 0.32) * f0 <= fq[k] <= (h_idx + 0.68) * f0]
            if ps and vs:
                diffs.append(max(ps) - min(vs))
        return sum(diffs) / len(diffs) if diffs else 0.0

    cvs = [m for m in moras if m.get("kind") == "CV" and any(voiced[int(m["b"] / fpz) : int(m["e"] / fpz)])]
    ml = cvs[-1] if cvs else (moras[0] if moras else None)
    if ml is not None and has_sp:
        t_core = _tani_at(ml["b"] + 0.18 * (ml["e"] - ml["b"]))
        t_tail = _tani_at(ml["b"] + 0.85 * (ml["e"] - ml["b"]))
    else:
        t_core, t_tail = 0.0, 0.0

    wav_sha = hashlib.sha256(_pcm16_bytes(samples)).hexdigest()[:16]
    return {
        "sha256_16": wav_sha,
        "dur_s": round(N / SR, 2),
        "crest_db": round(crest_db, 1),
        "band_1k_2k6_db": round(b1, 1),
        "band_2k6_5k6_db": round(b2, 1),
        "tani_core_db": round(t_core, 1),
        "tani_tail_db": round(t_tail, 1),
    }
