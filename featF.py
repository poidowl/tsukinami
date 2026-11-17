# analysis only: 拍ごとの単位（子音の部分＋母音の部分）を全部のこまで持つ。上の形 96 帯（80〜8000Hz）は「こま全体の強さ」が基準
import sys, os, json, numpy as np, soundfile as sf, pyworld as pw, librosa, pickle, warnings; warnings.filterwarnings('ignore')
from multiprocessing import Pool
SID = os.environ.get('SID')
if not SID: raise SystemExit('SID required')
mf = f'meta{SID}.json' if os.path.exists(f'meta{SID}.json') else 'meta.json'
meta = [m for m in json.load(open(mf)) if str(m.get('sid', SID)) == str(SID)]
SR = 24000; fb = librosa.filters.mel(sr=SR, n_fft=1024, n_mels=96, fmin=80, fmax=8000)
def one(x):
    sid = x.get('sid', SID)
    w, sr = sf.read(f"wav/{sid}_{x['i']}.wav", always_2d=True); w = w.mean(1)
    if sr != SR:
        import scipy.signal as ss; w = ss.resample_poly(w, SR, sr); sr = SR
    w = (w / max(np.abs(w).max(), 1e-9) * 0.6).astype(np.float64)
    f0, t = pw.harvest(w, sr, f0_floor=150, f0_ceil=700, frame_period=5.0); sp = pw.cheaptrick(w, f0, t, sr)
    tot = 10 * np.log10(sp.mean(1) + 1e-20); U = (10 * np.log10(sp @ fb.T + 1e-20) - tot[:, None]).astype(np.float32); seq = []
    for ap in x['aps']:
        for m in ap['moras']: seq.append((m['c'] or '', m['v'], m['cl'], m['vl']))
        if ap.get('pause'): seq.append(('', 'pau', 0.0, ap['pause']))
    units = []; tt = x['pre']
    for j, (c, v, cl, vl) in enumerate(seq):
        a = tt; b = a + cl; e = b + vl; tt = e
        if v == 'pau': continue
        nc = seq[j + 1][0] if j + 1 < len(seq) else ''; nv = seq[j + 1][1] if j + 1 < len(seq) else 'pau'; pv = seq[j - 1][1] if j else 'pau'
        ia, ib, ie = int(round(a / .005)), int(round(b / .005)), min(int(round(e / .005)), len(f0))
        if ie - ib >= 2: units.append(dict(c=c, v=v, nc=nc, nv=nv, pv=pv, tx=x.get('text', ''), C=U[ia:ib].copy(), V=U[ib:ie].copy()))
    return units
if __name__ == '__main__':
    with Pool(4) as p: res = p.map(one, meta)
    units = [u for r in res for u in r]; pickle.dump(units, open(f'unitsF{SID}.pkl', 'wb')); print(len(units), sorted(set(u['v'] for u in units)))
