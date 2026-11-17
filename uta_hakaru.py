# analysis only: 歌の音一本から「歌い回しの数字」を測って表に積む（歌詞は要らん、高さの線と強さだけ）。
# python uta_hakaru.py 名前=a.wav ...  → 一行ずつ uta_hyou.jsonl に足す（env HYOU で置き場、NOADD=1 で足さん）
import sys, os, json, numpy as np, soundfile as sf, warnings; warnings.filterwarnings('ignore')
import pyworld as pw
HOP = 5.0
def med(x, k):
    k |= 1; p = np.pad(x, k // 2, mode='edge'); return np.median(np.lib.stride_tricks.sliding_window_view(p, k), 1)
def mav(x, k):
    k |= 1; p = np.pad(x, k // 2, mode='edge'); return np.convolve(p, np.ones(k) / k, 'valid')
def hakaru(fn):
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
if __name__ == '__main__':
    H = os.environ.get('HYOU', 'uta_hyou.jsonl')
    for a in sys.argv[1:]:
        nm, fn = a.split('=', 1); r = hakaru(fn); print(nm, json.dumps(r, ensure_ascii=False))
        if not os.environ.get('NOADD'): open(H, 'a').write(json.dumps(dict(uta=nm, **r), ensure_ascii=False) + '\n')
