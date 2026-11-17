# analysis only: 声 SID の見本 WAV（wav/{sid}_*.wav）の倍音の間の谷の深さ → iki の pts（較正表から帯ごとに内挿）。tani_{SID}.json
import sys, os, glob, json, numpy as np, soundfile as sf, pyworld as pw, warnings; warnings.filterwarnings('ignore')
sid = sys.argv[1]; out = [[], [], []]; f0s = []
wav_dir = os.environ.get('WAV_DIR', 'wav')
for fn in sorted(glob.glob(f'{wav_dir}/{sid}_*.wav')):
    x, SR = sf.read(fn, always_2d=True); x = x.mean(1); f0, t = pw.harvest(x, SR, f0_floor=120, f0_ceil=700, frame_period=5); N = int(SR * .016); NF = 4096; f0s += list(f0[f0 > 0])
    for i in range(1, len(f0) - 1):
        if min(f0[i - 1:i + 2]) <= 0 or abs(12 * np.log2(f0[i + 1] / f0[i - 1])) > 0.3: continue
        c = int(t[i] * SR); seg = x[c - N // 2:c + N // 2]
        if len(seg) < N: continue
        s = 20 * np.log10(np.abs(np.fft.rfft(seg * np.hanning(N), NF)) + 1e-9); f = f0[i]; h = np.arange(1, int(8000 / f)) * f
        for b, (lo, hi) in enumerate(((1200, 2500), (2500, 5000), (5000, 8000))):
            hh = h[(h >= lo) & (h < hi - f)]
            if len(hh): out[b].append(np.mean([(s[int(round(q * NF / SR))] + s[int(round((q + f) * NF / SR))]) / 2 - s[int(round((q + f / 2) * NF / SR))] for q in hh]))
d = [float(np.median(o)) for o in out]
CAL = (([25, 20.4, 17.6, 16.3, 13.4], [0, .03, .07, .1, .2]), ([25, 14.8, 12.3, 9.9, 7.0], [0, .15, .25, .4, .6]), ([20, 7.8, 6.2, 4.3, 1.7], [0, .5, .62, .7, .9]))
sh = [round(float(np.interp(-d[b], [-v for v in CAL[b][0]], CAL[b][1])), 3) for b in range(3)]
json.dump(dict(tani=d, f0=float(np.median(f0s)), pts=[[1200, 0], [2500, sh[0]], [5000, sh[1]], [8000, sh[2]], [9000, sh[2]], [11000, 0]]), open(f'tani_{sid}.json', 'w')); print(sid, '谷', np.round(d, 1), '高さ', round(float(np.median(f0s))), 'iki', sh)
