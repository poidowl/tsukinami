# analysis only: 歌の音一本から「歌い回しの数字」を測って表に積む（歌詞は要らん、高さの線と強さだけ）。
# python uta_hakaru.py 名前=a.wav ...  → 一行ずつ uta_hyou.jsonl に足す（env HYOU で置き場、NOADD=1 で足さん）
import sys, os, json, numpy as np, warnings; warnings.filterwarnings('ignore')
HOP = 5.0
def med(x, k):
    k |= 1; p = np.pad(x, k // 2, mode='edge'); return np.median(np.lib.stride_tricks.sliding_window_view(p, k), 1)
def mav(x, k):
    k |= 1; p = np.pad(x, k // 2, mode='edge'); return np.convolve(p, np.ones(k) / k, 'valid')
def hakaru(fn):
    import soundfile as sf, pyworld as pw
    x, sr = sf.read(fn, dtype='float64', always_2d=True); x = x.mean(1)
    f0, t = pw.harvest(x, sr, f0_floor=100, f0_ceil=900, frame_period=HOP); n = len(f0); v = f0 > 0
    c = np.where(v, 1200 * np.log2(np.maximum(f0, 1) / 440) + 6900, np.nan)
    w = int(sr * 0.02); lev = np.array([10 * np.log10(np.mean(x[max(0, int(i * sr * HOP / 1000) - w):int(i * sr * HOP / 1000) + w] ** 2) + 1e-12) for i in range(n)])
    runs = []; i = 0                                   # 声のある続き（40ms までの切れ目は繋ぐ）
    while i < n:
        if v[i]:
            j = i
            while j < n and (v[j] or (j + 8 < n and v[j:j + 8].any())): j += 1
            if j - i >= 20: runs.append((i, j))
            i = j
        else: i += 1
    notes = []                                         # 音符：150ms の中央値の線が 60 セント動いたら次の音
    for a, b in runs:
        cc = c[a:b].copy(); ok = ~np.isnan(cc); cc[~ok] = np.interp(np.flatnonzero(~ok), np.flatnonzero(ok), cc[ok]); m = med(cc, 31)
        s = 0; ref = m[min(10, len(m) - 1)]
        for k in range(len(m)):
            if abs(m[k] - ref) > 60 and k + 12 < len(m) and abs(m[k + 12] - ref) > 60:
                if k - s >= 16: notes.append((a + s, a + k, a, b))
                s = k; ref = m[min(k + 12, len(m) - 1)]
        if len(m) - s >= 16: notes.append((a + s, b, a, b))
    ci = np.where(np.isnan(c), np.interp(np.arange(n), np.flatnonzero(v), c[v]), c)
    N = [];
    for a, b, ra, rb in notes:
        core = ci[a + min(20, (b - a) // 3):b - min(6, (b - a) // 6)]; N.append(dict(a=a, b=b, ra=ra, rb=rb, c=float(np.median(core)), ms=(b - a) * HOP, lev=float(np.mean(lev[a:b]))))
    cs = np.array([q['c'] for q in N]); off = np.angle(np.mean(np.exp(2j * np.pi * cs / 100))) / (2 * np.pi) * 100; dev = (cs - off + 50) % 100 - 50   # 調子笛とのずれを抜いた、半音の升目からの外れ
    vib = []; scoop = []; watari = []; over = []; drift = []; fine = []
    for k, q in enumerate(N):
        a, b = q['a'], q['b']; seg = ci[a:b]
        if q['ms'] >= 450:                              # 伸ばした音：ビブラート
            d = seg - mav(seg, 61); d = d[10:-4]; e = np.abs(np.fft.rfft((d - d.mean()) * np.hanning(len(d)), 4096)); fr = np.fft.rfftfreq(4096, HOP / 1000); band = (fr >= 3.5) & (fr <= 9)
            tail = d[len(d) // 2:]; e = np.abs(np.fft.rfft((tail - tail.mean()) * np.hanning(len(tail)), 4096)); rate = float(fr[band][np.argmax(e[band])]); depth = float(np.sqrt(2) * np.std(tail)); env = np.sqrt(2 * mav(d ** 2, 41)); i0 = int(np.argmin(env[:max(1, min(80, len(env) // 2))])); on = i0 + np.flatnonzero(env[i0:] >= 0.5 * depth)
            ratio = float(e[band].max() / (np.median(e[(fr > 1) & (fr < 20)]) + 1e-9))
            vib.append((rate if q['ms'] >= 700 else np.nan, depth if q['ms'] >= 700 else np.nan, float(on[0] + 10) * HOP if len(on) else np.nan, ratio)); drift.append(float(np.std(mav(seg, 61)[20:-6]))); fine.append(float(np.std(seg[10:-4] - mav(seg, 7)[10:-4])))
        if a == q['ra'] and q['ms'] >= 200:             # 息つぎのあとの頭：しゃくり
            h = seg[:40] - q['c']; scoop.append((float(np.median(h[1:7])), float(np.argmax(np.abs(h) < 20) * HOP)))
        if k and N[k - 1]['b'] == a and abs(q['c'] - N[k - 1]['c']) > 80:   # 音から音への渡り
            p0, p1 = N[k - 1]['c'], q['c']; w0 = max(a - 40, N[k - 1]['a']); w1 = min(a + 40, b); z = (ci[w0:w1] - p0) / (p1 - p0)
            i10 = np.argmax(z > 0.1); i90 = np.argmax(z > 0.9) if (z > 0.9).any() else len(z) - 1; watari.append(float((i90 - i10) * HOP)); over.append(float((z.max() - 1) * abs(p1 - p0)))
    ln = np.array([q['lev'] for q in N]); long_ = np.array([q['ms'] >= 200 for q in N])
    tsure = float(np.polyfit(cs[long_] / 100, ln[long_], 1)[0]) if long_.sum() > 3 else np.nan; tsure_r = float(np.corrcoef(cs[long_], ln[long_])[0, 1]) if long_.sum() > 3 else np.nan
    V = np.array(vib) if vib else np.zeros((0, 4)); g = lambda z: None if len(z) == 0 or np.all(np.isnan(z)) else round(float(np.nanmedian(z)), 2)
    return dict(onpu=len(N), nobashi=len(vib), hazure_heikin=g(np.abs(dev)), hazure_max=round(float(np.abs(dev).max()), 1), choushi=round(float(off), 1),
                vib_hz=g(V[:, 0]), vib_cent=g(V[:, 1]), vib_iri_ms=g(V[:, 2]), vib_tsuyosa=g(V[:, 3]), tadayoi_cent=g(np.array(drift)), komakai_cent=g(np.array(fine)),
                shakuri_cent=g(np.array([s[0] for s in scoop])), shakuri_ms=g(np.array([s[1] for s in scoop])), watari_ms=g(np.array(watari)), yukisugi_cent=g(np.array(over)),
                tsure_db_per_hanon=None if np.isnan(tsure) else round(tsure, 2), tsure_r=None if np.isnan(tsure_r) else round(tsure_r, 2), hirosa_hanon=round(float(cs.max() - cs.min()) / 100, 1))
def hakaru_f12():
    import carve, kotoba, copy, math, hashlib
    fpz = kotoba.FP / 1000.0; sr = carve.SR; nf42 = int(round(0.042 * sr)); wn42 = np.hanning(nf42); fq42 = np.fft.rfftfreq(nf42, 1.0 / sr)
    def wav_hash(x):
        return hashlib.sha256(b"".join(int(max(-32768, min(32767, round(v * 32767)))).to_bytes(2, "little", signed=True) for v in x)).hexdigest()[:16]
    def wav_f12(x, t_sec):
        s0 = max(0, min(len(x) - nf42, int(round(t_sec * sr)) - nf42 // 2)); sp = np.abs(np.fft.rfft(x[s0:s0 + nf42] * wn42)) ** 2
        m1, m2 = (fq42 >= 280) & (fq42 <= 1150), (fq42 >= 1150) & (fq42 <= 3500)
        return float(np.sum(fq42[m1] * sp[m1]) / (np.sum(sp[m1]) + 1e-24)), float(np.sum(fq42[m2] * sp[m2]) / (np.sum(sp[m2]) + 1e-24))
    def synth_item(txt, hzs, vd_ms, c_conv=True, eff_conv=True, mode=None):
        rc = copy.deepcopy(carve.E79); rc["kotoba"] = dict(rc["kotoba"], pre=0.2, post=0.3, uta_trance=True, uta_hz=hzs, uta_trance_shift_st=0.0,
                                                           uta_vib=[5.5, 22, 220, 280], uta_scoop=[1.5, 45], tr_sub_cut=True, tr_f_shift=True,
                                                           tr_c_conv=c_conv, tr_eff_conv=eff_conv, tr_mode=mode, params=dict(rc["kotoba"]["params"], vd_ms=vd_ms))
        r = {}; v_rc = carve.variant(dict(rc, text=txt, seed=2024)); v_rc["_out_r"] = r
        x, _ = carve.make(v_rc); return np.array(x, dtype=np.float64), r
    print("=== [0] 回帰ハッシュ検証（E79通常読み上げ / 40b3d25互換 / 3f7cffb色気OFF / 現行 --trance電子色気 / 現行 --choir電子色気） ===")
    exp_hashes = {"E79(通常TTS)": "35dc9e825bf993d8", "40b3d25(--trance)": "bbb09b4d6f55d61b", "3f7cffb(色気OFF)": "2986205c88116f25"}
    for nm, kw in [("E79(通常TTS)", {}), ("40b3d25(--trance)", {"uta_trance": True, "tr_mode": "40b3d25"}),
                   ("3f7cffb(色気OFF)", {"uta_trance": True, "tr_iroke": False}),
                   ("現行(--trance)", {"uta_trance": True}), ("現行(--choir)", {"uta_choir": True})]:
        rc = copy.deepcopy(carve.E79); rc["kotoba"] = dict(rc["kotoba"], **kw); x, _ = carve.make(carve.variant(dict(rc, text="こんにちわ", seed=2024)))
        h_ = wav_hash(x); ok_ = "" if nm not in exp_hashes else (" [OK]" if h_ == exp_hashes[nm] else f" [NG: expected {exp_hashes[nm]}]")
        print(f"  {nm:18s}: SHA256={h_} (samples={len(x)}){ok_}")
    print("\n=== [1] 5ms 内部制御軌道 & 出力WAV実音響スペクトル重心テスト（ア→イ / イ→ア / ア、イ / アンイ / 高音イ・ウ） ===")
    for lbl, txt, hzs in [("ア→イ", "アイ", [440, 440]), ("イ→ア", "イア", [440, 440]), ("ア、イ(休止跨ぎ)", "ア、イ", [440, 440]), ("アンイ(撥音跨ぎ)", "アンイ", [440, 440, 440])]:
        x, r = synth_item(txt, hzs, [300] * len(hzs)); m0 = r["moras"][0]; cv = [m for m in r["moras"] if m.get("kind") == "CV"]
        tb, tm, te = int(m0["b"] / fpz), int(0.5 * (m0["b"] + m0["e"]) / fpz), int((m0["e"] - 0.010) / fpz)
        f1, f2 = r["F1"], r["F2"]; wf1_m, wf2_m = wav_f12(x, tm * fpz); wf1_e, wf2_e = wav_f12(x, te * fpz)
        print(f"  {lbl:16s}: 制御F1({f1[tb]:5.1f}→{f1[tm]:5.1f}→{f1[te]:5.1f}Hz, 予兆{f1[te]-f1[tm]:+6.1f}Hz) | 制御F2({f2[tb]:6.1f}→{f2[tm]:6.1f}→{f2[te]:6.1f}Hz, 予兆{f2[te]-f2[tm]:+6.1f}Hz) | WAV実音Δ(F1={wf1_e-wf1_m:+5.1f}Hz, F2={wf2_e-wf2_m:+6.1f}Hz)")
        if txt == "アイ":
            m_last = cv[-1]; t_lm, t_le = int(0.5 * (m_last["b"] + m_last["e"]) / fpz), int(m_last["e"] / fpz)
            print(f"    └ 句末final保持[イ末尾]: F2_base(mid)={r['F2_base'][t_lm]:.1f}Hz == F2_base(e)={r['F2_base'][t_le]:.1f}Hz (差={r['F2_base'][t_le]-r['F2_base'][t_lm]:+.1f}Hz)")
        if txt == "アンイ":
            tN = int(0.5 * (r["moras"][1]["a"] + r["moras"][1]["e"]) / fpz)
            print(f"    └ 撥音[ン]中央: v_map={r['v_map'][tN]}, F1={f1[tN]:.1f}Hz (F1_base={r['F1_base'][tN]:.1f}Hz), F2={f2[tN]:.1f}Hz")
    for lbl, txt in [("高音イ(523Hz)", "イ"), ("高音ウ(523Hz)", "ウ")]:
        x, r = synth_item(txt, [523.25], [360]); m0 = r["moras"][0]; tb, tm = int((m0["b"] + 0.015) / fpz), int(0.5 * (m0["b"] + m0["e"]) / fpz)
        wf1_b, wf2_b = wav_f12(x, tb * fpz); wf1_m, wf2_m = wav_f12(x, tm * fpz)
        print(f"  {lbl:16s}: 制御[頭(b+15ms) F1={r['F1'][tb]:5.1f}, F2={r['F2'][tb]:6.1f} → 収束(mid) F1={r['F1'][tm]:5.1f}, F2={r['F2'][tm]:6.1f}Hz (ΔF1={r['F1'][tm]-r['F1'][tb]:+5.1f}Hz)] | WAV重心[mid F1={wf1_m:5.1f}, F2={wf2_m:6.1f}Hz]")
    print("\n=== [2] 無声音子音区間（アサ / カタ / シタ）での古いフォルマントロック残留チェック ===")
    for txt in ("アサ", "カタ", "シタ"):
        _, r = synth_item(txt, [440, 440], [280, 280]); m0, m1 = r["moras"][0], r["moras"][1]
        tm0, tc1, tm1 = int(0.5 * (m0["b"] + m0["e"]) / fpz), int(0.5 * (m1["a"] + m1["b"]) / fpz), int(0.5 * (m1["b"] + m1["e"]) / fpz)
        d1, d2 = r["df1_lock"], r["df2_lock"]
        print(f"  {txt} (子音={m1['c']:2s}): 1拍目母音中央 lock=({d1[tm0]:+5.1f}, {d2[tm0]:+6.1f}Hz) → 無声子音中央 lock=({d1[tc1]:+5.1f}, {d2[tc1]:+6.1f}Hz) → 2拍目母音中央 lock=({d1[tm1]:+5.1f}, {d2[tm1]:+6.1f}Hz)")
    print("\n=== [3] 独立分離実験（本物の40b3d25 / 条件A / 条件B / 条件C / 条件D[電子色気]）チェックポイント検証 ===")
    T0 = "ワタシノナマエツキナミノコエ"; VD = [260, 260, 260, 260, 260, 260, 560, 260, 260, 260, 260, 260, 260, 820]
    M0 = [60, 62, 64, 67, 67, 64, 62, 64, 65, 67, 69, 67, 64, 62]; HZ0 = [round(440 * 2 ** ((k - 69) / 12)) for k in M0]
    W = os.path.dirname(os.path.abspath(__file__))
    S0 = open(os.path.join(W, "S.txt")).read().strip(); OO = open(os.path.join(W, "OO.txt")).read().strip()
    V0 = '"vbump":{"a":[1,1.2,1],"e":[0.7,1.3,0.7],"o":[1,1.3,0.8],"i":[0.25,3.0,3.0]}'
    R103 = {"p_low": [5, 4, 3], "vfloor": {"a": 0.6, "o": 0.3}, "f1x_cmute": 1.0, "f45": [[1400, 0.75], [2300, 0.3]], "vbump": {"a": [1, 1.2, 1], "e": [0.7, 1.3, 0.7], "o": [1, 1, 0.3], "i": [0.7, 0.6, 0.7]}, "f1x": [[2.0, 0.35], [0.45, 0.25], [2.8, 0.35]], "vf1x": {"a": [0.15, 0, 0], "i": [0.3, 0, 0.3], "u": [0.3, 0, 0.3], "e": [0.5, 1, 0], "o": [0.1, 1, 0]}, "henv": None}
    def build_song_rc(extra_kw):
        kw = dict(R103, **{"P.fend_at": 0.15, "P.fric_hold": 20, "P.vl_hold": True, "P.vdl": -2.0, "P.vbg": 1.5})
        kw.update(json.loads("{" + f"{S0},{V0},{OO}" + "}"))
        kw.update({"P.vd_ms": VD, "rc.tadayoi": 0.0, "line.D_haba": 0, "uta_vib": [5.5, 22, 220, 280], "uta_scoop": [1.5, 45], "uta_hz": HZ0, "rc.yure_hayai": 0.02, "uta_trance": True})
        kw.update(extra_kw)
        rc = copy.deepcopy(carve.E79); rc["line.D_center"] = carve.E79["line.D_center"] * 436.6 / 360
        K = dict(fscale=1.22, bump=[3, 1.4, 1.4], g=[0.7, 0.7, 0.7], floor=1.0, ap_on="mix", ap_n=40, ap_lo=300, ap_hi=8000, ap_bw=150, band=3.0); P = {}
        for k, v in kw.items():
            if k.startswith("line.") or k.startswith("kugiri."): rc[k] = v
            elif k.startswith("P."): P[k[2:]] = v
            elif k.startswith("rc."): rc[k[3:]] = v
            else: K[k] = v
        rc["kotoba"] = dict(rc["kotoba"], **K); rc["kotoba"]["params"] = dict(rc["kotoba"]["params"], **P)
        rc["kotoba"].pop("acc2", None); hz_b = rc["kotoba"].pop("hz", None)
        if hz_b: rc["line.D_center"] = carve.E79["line.D_center"] * 436.6 / hz_b
        return rc
    conds = [
        ("0: 本物の40b3d25 (旧コード完全一致)", {"tr_c_conv": False, "tr_eff_conv": False, "tr_mode": "40b3d25", "tr_iroke": False}),
        ("A: 移動=即時 / ゲイン=固定 / 鼻音=同一", {"tr_c_conv": False, "tr_eff_conv": False, "tr_iroke": False}),
        ("B: 移動=c_conv / ゲイン=固定 / 鼻音=同一", {"tr_c_conv": True, "tr_eff_conv": False, "tr_iroke": False}),
        ("C: 移動=c_conv / ゲイン=連動 / 色気OFF", {"tr_c_conv": True, "tr_eff_conv": True, "tr_iroke": False}),
        ("D: 電子色気ブレンド (--trance既定: P1+P2+P3+P4)", {"tr_c_conv": True, "tr_eff_conv": True, "tr_iroke": True}),
    ]
    for tag, ekw in conds:
        rc = build_song_rc(ekw); r = {}; v_rc = carve.variant(dict(rc, text=T0, seed=2024)); v_rc["_out_r"] = r
        x, _ = carve.make(v_rc); x = np.array(x, dtype=np.float64); cv = [m for m in r["moras"] if m.get("kind") == "CV"]
        hi_df1, hi_res = [], []
        for i in (2, 7, 8, 10):
            tb, tm = int((cv[i]["b"] + 0.030) / fpz), int(0.5 * (cv[i]["b"] + cv[i]["e"]) / fpz); tgt = r["f0_tr"][tm] * 1.03
            hi_df1.append(r["F1"][tm] - r["F1"][tb]); hi_res.append(abs(r["F1"][tb] - tgt) - abs(r["F1"][tm] - tgt))
        mi_b, mi_m = int((cv[10]["b"] + 0.015) / fpz), int(0.5 * (cv[10]["b"] + cv[10]["e"]) / fpz)
        sub240 = []
        for i in (3, 4, 5, 9, 10, 11):
            s0 = int(cv[i]["a"] * sr); seg = x[s0:s0 + nf42]
            if len(seg) == nf42:
                sp = np.abs(np.fft.rfft(seg * wn42)) ** 2; sub240.append(10 * np.log10((np.sum(sp[(fq42 >= 50) & (fq42 < 240)]) + 1e-24) / (np.sum(sp[(fq42 >= 60) & (fq42 <= 8000)]) + 1e-24)))
        reed_on, reed_mid, f2_e, f2_o = [], [], [], []
        for i in (3, 6, 11, 12, 13):
            for s_pos, acc in [(int(cv[i]["b"] * sr), reed_on), (int(0.5 * (cv[i]["b"] + cv[i]["e"]) * sr) - nf42 // 2, reed_mid)]:
                seg = x[max(0, s_pos):max(0, s_pos) + nf42]
                if len(seg) == nf42:
                    sp = np.abs(np.fft.rfft(seg * wn42)) ** 2
                    acc.append(10 * np.log10((np.sum(sp[(fq42 >= 1600) & (fq42 <= 3400)]) + 1e-24) / (np.sum(sp[(fq42 >= 300) & (fq42 <= 1100)]) + 1e-24)))
                    if acc is reed_mid:
                        mb = (fq42 >= 800) & (fq42 <= 2800); cf2 = float(np.sum(fq42[mb] * sp[mb]) / (np.sum(sp[mb]) + 1e-24))
                        (f2_e if cv[i]["v"] == "e" else f2_o).append(cf2)
        df1_jmp, df2_jmp, coart_mv = [], [], []
        for i0, i1 in [(5, 6), (6, 7), (10, 11), (11, 12), (12, 13)]:
            ta = int(cv[i1]["a"] / fpz); w_r = range(max(1, ta - 6), min(r["n"], ta + 6))
            df1_jmp.append(max(abs(r["F1"][t] - r["F1"][t - 1]) for t in w_r))
            df2_jmp.append(max(abs(r["F2"][t] - r["F2"][t - 1]) for t in w_r))
            tm0 = int(0.5 * (cv[i0]["b"] + cv[i0]["e"]) / fpz); te0 = int((cv[i0]["e"] - 0.005) / fpz)
            coart_mv.append(math.hypot(r["F1"][te0] - r["F1"][tm0], r["F2"][te0] - r["F2"][tm0]))
        print(f"  [{tag}]\n"
              f"    ① 立ち上がり運動: 高母音符号付ΔF1(b+30ms→mid)={np.mean(hi_df1):+5.1f}Hz(目標接近{np.mean(hi_res):+5.1f}Hz), ミ10 F1(b+15ms→mid: {r['F1'][mi_b]:.1f}→{r['F1'][mi_m]:.1f}Hz, {r['F1'][mi_m]-r['F1'][mi_b]:+.1f}Hz) [吹かれ<240Hz={np.mean(sub240):+6.2f}dB]\n"
              f"    ② 高音エ/オ伸ばし: 頭42.0msリード比={np.mean(reed_on):+6.2f}dB, 定常中央リード比={np.mean(reed_mid):+6.2f}dB, F2重心(エ={np.mean(f2_e):.0f}/オ={np.mean(f2_o):.0f}Hz, 差={np.mean(f2_e)-np.mean(f2_o):+.0f}Hz)\n"
              f"    ③ 高→低下降遷移: 音節末予兆移動量={np.mean(coart_mv):5.1f}Hz, 境界5ms最大跳躍 max|ΔF1|={np.mean(df1_jmp):4.1f}Hz/5ms, max|ΔF2|={np.mean(df2_jmp):4.1f}Hz/5ms")
    print("\n=== [4] 電子色気 4柱直交分離検証（P1 粘性グライド / P2 液状パルス&硝子尾溶解 / P3 直交リサージュ / P4 濡れ絹位相分散） ===")
    nf2k = 2048; wn2k = np.hanning(nf2k); fq2k = np.fft.rfftfreq(nf2k, 1.0 / sr)
    ir_cases = [
        ("0: 旧--trance (色気OFF)", {"tr_iroke": False}),
        ("1: +P1 粘性グライド&語尾吐息", {"tr_iroke": False, "tr_ir_glide": True}),
        ("2: +P2 液状パルス&硝子尾溶解", {"tr_iroke": False, "tr_ir_pulse": True}),
        ("3: +P3 直交リサージュ&F3鎖", {"tr_iroke": False, "tr_ir_liss": True}),
        ("4: +P4 濡れ絹位相分散", {"tr_iroke": False, "tr_ir_silk": True}),
        ("5: 新--trance (電子色気Full)", {"tr_iroke": True}),
    ]
    for lbl, ikw in ir_cases:
        rc = build_song_rc(ikw); r = {}; v_rc = carve.variant(dict(rc, text=T0, seed=2024)); v_rc["_out_r"] = r
        x, _ = carve.make(v_rc); x = np.array(x, dtype=np.float64); cv = [m for m in r["moras"] if m.get("kind") == "CV"]
        rccs, h_vals, h12_on, h12_core, h12_tail = [], [], [], [], []
        def h12_at(t_pos):
            fl = r["f0_tr"][min(r["n"] - 1, max(0, int(t_pos / fpz)))]; sc = max(0, min(len(x) - nf2k, int(t_pos * sr) - nf2k // 2))
            sp_ = np.abs(np.fft.rfft(x[sc:sc + nf2k] * wn2k)) ** 2; i1, i2 = np.argmin(np.abs(fq2k - fl)), np.argmin(np.abs(fq2k - 2 * fl))
            return 10 * np.log10((np.max(sp_[max(0, i1 - 2):i1 + 3]) + 1e-24) / (np.max(sp_[max(0, i2 - 2):i2 + 3]) + 1e-24))
        for idx_m, m in enumerate(cv):
            if m["e"] - m["b"] < 0.18: continue
            tm = 0.5 * (m["b"] + m["e"]); f0 = r["f0_tr"][int(tm / fpz)]; per = int(round(sr / f0)); sm = int(tm * sr)
            seg = x[sm - per * 4:sm + per * 4]; s1, s2 = seg[:-per], seg[per:]
            rccs.append(float(np.dot(s1, s2) / (np.linalg.norm(s1) * np.linalg.norm(s2) + 1e-24)))
            sp = np.abs(np.fft.rfft(x[sm - nf2k // 2:sm + nf2k // 2] * wn2k)) ** 2
            hp = [np.max(sp[max(0, np.argmin(np.abs(fq2k - k * f0)) - 1):np.argmin(np.abs(fq2k - k * f0)) + 2]) for k in range(1, 9)]
            vp = [np.min(sp[max(0, np.argmin(np.abs(fq2k - (k + 0.5) * f0)) - 1):np.argmin(np.abs(fq2k - (k + 0.5) * f0)) + 2]) for k in range(1, 9)]
            h_vals.append(10 * np.log10((np.mean(hp) + 1e-24) / (np.mean(vp) + 1e-24)))
            h12_on.append(h12_at(m["b"] + 0.025)); h12_core.append(h12_at(tm))
            if idx_m == 13: h12_tail.append(h12_at(m["e"] - 0.065))
        ml = cv[-1]; ts, te = int((ml["b"] + 0.24) / fpz), int((ml["e"] - 0.18) / fpz)
        p_tr = [1200 * math.log2(r["f0_tr"][t_] / 392.0) for t_ in range(ts, te)]
        br_tr = [10 * np.log10((np.sum((np.abs(np.fft.rfft(x[int(t_ * fpz * sr) - 1024:int(t_ * fpz * sr) + 1024] * wn2k)) ** 2)[(fq2k >= 2400) & (fq2k <= 4200)]) + 1e-24) /
                               (np.sum((np.abs(np.fft.rfft(x[int(t_ * fpz * sr) - 1024:int(t_ * fpz * sr) + 1024] * wn2k)) ** 2)[(fq2k >= 280) & (fq2k <= 1200)]) + 1e-24)) for t_ in range(ts, te)]
        pa = np.array(p_tr) - np.mean(p_tr); ba = np.array(br_tr) - np.mean(br_tr)
        pn, bn = pa / (np.std(pa) + 1e-9), ba / (np.std(ba) + 1e-9)
        liss = float(0.5 * np.abs(np.sum(pn[:-1] * bn[1:] - pn[1:] * bn[:-1])) / max(1, len(pn) - 1))
        desc_c = [1200 * math.log2(r["f0_tr"][int(cv[im]["b"] / fpz)] / r["f0_tr"][int(0.5 * (cv[im]["b"] + cv[im]["e"]) / fpz)]) for im in (5, 6, 10, 11, 12, 13) if M0[im] < M0[im - 1]]
        tfa, tfb = int((ml["b"] + 0.12) / fpz), int((ml["b"] + 0.36) / fpz)
        tail_c = 1200 * math.log2(r["f0_tr"][int((ml["e"] - 0.015) / fpz)] / float(np.median(r["f0_tr"][tfa:tfb])))
        hop_s = 220; phs = []
        for kh in (5, 7, 9):
            fh = kh * r["f0_tr"][(tfa + tfb) // 2]
            if fh > 5500: continue
            ih = int(round(fh * nf2k / sr)); s_pts = range(int((ml["b"] + 0.20) * sr), int((ml["e"] - 0.20) * sr), hop_s)
            angs = [np.angle(np.fft.rfft(x[sp_:sp_ + nf2k] * wn2k)[ih]) for sp_ in s_pts]
            inst_hz = np.diff(np.unwrap(angs)) * (sr / hop_s) / (2 * np.pi)
            f0_rs = np.array([kh * r["f0_tr"][int((sp_ + nf2k // 2) / sr / fpz)] for sp_ in s_pts][:-1])
            phs.append(float(np.std(inst_hz - f0_rs)))
        print(f"  [{lbl:26s}] rcc={np.mean(rccs):.4f} | 谷差={np.mean(h_vals):+5.2f}dB | 下降余韻={np.mean(desc_c):+5.1f}c | 語尾吐息={tail_c:+5.1f}c | "
              f"H1-H2[入={np.mean(h12_on):+5.2f}→核={np.mean(h12_core):+5.2f}→尾={np.mean(h12_tail):+5.2f}dB] | リサージュ={liss:.4f}(幅={np.percentile(br_tr,95)-np.percentile(br_tr,5):.2f}dB) | 位相ゆらぎ={np.mean(phs):.2f}Hz")


if __name__ == '__main__':
    if '--f12' in sys.argv: hakaru_f12(); sys.exit(0)
    H = os.environ.get('HYOU', 'uta_hyou.jsonl')
    for a in sys.argv[1:]:
        nm, fn = a.split('=', 1); r = hakaru(fn); print(nm, json.dumps(r, ensure_ascii=False))
        if not os.environ.get('NOADD'): open(H, 'a').write(json.dumps(dict(uta=nm, **r), ensure_ascii=False) + '\n')

