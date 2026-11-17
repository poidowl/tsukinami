# 切り分け／決まり探し: 拍ごとに、鍵（子音・母音・前の母音・次の子音・次の母音）が近い単位を N 個とって、こまごとに「まとめた形」を作る。
# MODE=mean: 帯の高さをそのまま平均。MODE=peak: 5 つの帯域ごとの山の場所と高さ・谷の場所と高さを平均してから形に戻す。
import sys, os, json, numpy as np, soundfile as sf, scipy.signal as ss, scipy.ndimage as nd, pyworld as pw, librosa, warnings; warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
SWAP = os.environ.get('SWAP', os.path.join(HERE, 'swap')); os.makedirs(SWAP, exist_ok=True)
tag, text, base, mof = sys.argv[1:5]; N = int(os.environ.get('N', 8)); MODE = os.environ.get('MODE', 'peak'); SR = 24000
SKIP = [k for k in os.environ.get('SKIP', '').split(',') if k]; NOC = [int(k) for k in os.environ.get('NOC', '').split(',') if k]; W = [float(v) for v in os.environ.get('W', '3,3,3').split(',')]
x, sr = sf.read(base, dtype='float64', always_2d=True); x = x.mean(1); x = ss.resample_poly(x, SR, sr) if sr != SR else x
f0, tt = pw.harvest(x, SR, f0_floor=150, f0_ceil=700, frame_period=5); sp = pw.cheaptrick(x, f0, tt, SR); ap = pw.d4c(x, f0, tt, SR); n = len(f0)
mo = json.load(open(mof)); MJ = np.load(os.environ['MJ']); NM = list(MJ['names']); MT = MJ[os.environ.get('VAR', 'a')]; Ww = MJ['w']; Wc = MJ['wc']
def cid(m):
    c = m.get('c') or ''
    if any(k in m['t'] for k in 'ャュョ') and c in ('k', 'g', 'n', 'h', 'b', 'p', 'm', 'r'): c += 'y'
    return c
def vof(m): return 'N' if m['kind'] == 'N' else 'cl' if m['kind'] == 'Q' else m.get('v') or 'pau'
fq = np.arange(513) * SR / 1024; cf = librosa.mel_frequencies(n_mels=98, fmin=80, fmax=8000)[1:-1]; fb = librosa.filters.mel(sr=SR, n_fft=1024, n_mels=96, fmin=80, fmax=8000); bw = 10 * np.log10(fb.sum(1)); XO = float(os.environ.get('XO', 0)); w = 1 / (1 + (XO / np.maximum(fq, 1)) ** 6) if XO > 0 else np.ones(513); w = (1 - 1 / (1 + (1200 / np.maximum(fq, 1)) ** 6)) if os.environ.get('LOW') else w; lf = np.log(cf)
ED = [float(v) for v in os.environ.get('ED', '1200,2000,3000,4200,5800,8000').split(',')]; RG = [np.where((cf >= a) & (cf < b))[0] for a, b in zip(ED[:-1], ED[1:])]; RG[-1] = np.where(cf >= ED[-2])[0]
def enc(u):
    pk = [r[int(np.argmax(u[r]))] for r in RG]; vl = [a + int(np.argmin(u[a:b + 1])) for a, b in zip(pk[:-1], pk[1:])]
    return np.r_[u[0], [lf[i] for i in pk], [u[i] for i in pk], [lf[i] for i in vl], [u[i] for i in vl], u[-1]]
R = len(RG)
def dec(p):
    xs = [lf[0] - 1e-3]; ys = [p[0]]; px, py = p[1:1 + R], p[1 + R:1 + 2 * R]
    vx = p[1 + 2 * R:1 + 2 * R + R - 1]; vy = p[1 + 2 * R + R - 1:1 + 2 * R + 2 * (R - 1)]
    for r in range(R):
        xs.append(px[r]); ys.append(py[r])
        if r < R - 1: xs.append(vx[r]); ys.append(vy[r])
    xs.append(lf[-1] + 1e-3); ys.append(p[-1]); xs = np.maximum.accumulate(np.array(xs) + np.arange(len(xs)) * 1e-6); ys = np.array(ys)
    t_ = np.interp(lf, xs, np.arange(len(xs))); k0 = np.floor(t_).astype(int).clip(0, len(xs) - 2); sm = (1 - np.cos(np.pi * (t_ - k0))) / 2; return ys[k0] * (1 - sm) + ys[k0 + 1] * sm
def rs(A, M_):
    p = np.linspace(0, len(A) - 1, M_); a = np.floor(p).astype(int); b = np.minimum(a + 1, len(A) - 1); f = (p - a)[:, None]; return A[a] * (1 - f) + A[b] * f
def matome(Ls, M_):
    Ls = [rs(A, M_) for A in Ls if len(A) >= 1]
    if not Ls: return None
    if MODE == 'mean':
        R_ = np.mean(Ls, 0); GA, GB = [float(v) for v in os.environ.get('GV', '1,1').split(',')]; tm = R_.mean(0); R_ = tm + GA * (R_ - tm); ax = np.arange(R_.shape[1])
        return np.array([np.polyval(np.polyfit(ax, r, 1), ax) + GB * (r - np.polyval(np.polyfit(ax, r, 1), ax)) for r in R_])
    if MODE == 'one': return nd.uniform_filter1d(Ls[0], int(os.environ.get('SM', 1)), axis=0, mode='nearest')
    P = np.mean([[enc(u) for u in A] for A in Ls], 0)
    if MODE == 'one_peak': P = np.array([enc(u) for u in Ls[0]])
    return np.array([dec(p) for p in P])
D = 10 * np.log10(sp + 1e-30); tot = 10 * np.log10(sp.mean(1) + 1e-20); T = D.copy(); done = np.zeros(n)
import scipy.fft as FF
FL = float(os.environ.get('FL', 0))
if FL and os.path.exists('yure_stat.json'):
    YS = json.load(open('yure_stat.json')); _sd = np.array(YS['sd']); _r = np.clip(np.array(YS['r1']), 0, .95); _rng = np.random.default_rng(int(os.environ.get('SEED', 1))); _z = np.zeros((n, 64)); _z[0] = _rng.standard_normal(64) * _sd
    for i in range(1, n): _z[i] = _r * _z[i - 1] + np.sqrt(1 - _r ** 2) * _rng.standard_normal(64) * _sd
    YURE = FF.idct(_z, axis=1, norm='ortho')
else:
    FL = 0.0; YURE = None
def put(i0, i1, Us):
    if Us is None: return
    if FL and YURE is not None: Us = Us + FL * YURE[i0:i1]
    for q, i in enumerate(range(i0, i1)): T[i] = w * np.interp(fq, cf, Us[q] + tot[i] - bw) + (1 - w) * D[i]; done[i] = 1
for j, m in enumerate(mo):
    v = vof(m)
    if v in ('cl', 'pau'): continue
    c = cid(m); nc = cid(mo[j + 1]) if j + 1 < len(mo) else ''; nv = vof(mo[j + 1]) if j + 1 < len(mo) else 'pau'; pv = vof(mo[j - 1]) if j else 'pau'; ia, ib, ie = [min(n, int(round((m[k] + .5) / .005))) for k in ('a', 'b', 'e')]
    if v == 'N': ib = ia
    if v not in NM: continue
    nxn = nc if nc else nv; tv_ = MT[NM.index(v)]; tn_ = MT[NM.index(nxn)] if nxn in NM else tv_; Vp = (1 - Ww)[:, None] * tv_ + Ww[:, None] * tn_
    if j not in NOC and ib - ia >= 1 and c in NM and not (os.environ.get('NOUV') and c in ('k', 'ky', 's', 'sh', 't', 'ts', 'ch', 'h', 'hy', 'f', 'p', 'py')): put(ia, ib, matome([(1 - Wc)[:, None] * MT[NM.index(c)] + Wc[:, None] * tv_], ib - ia))
    TV = float(os.environ.get('TV', 0))
    if TV and (ie - ib) * 5 > TV:
        nq = ie - ib; ps = np.clip(1 - (nq - 1 - np.arange(nq)) * 5 / TV, 0, 1) * 9; a_ = np.floor(ps).astype(int).clip(0, 8); f_ = (ps - a_)[:, None]; Vp = Vp[a_] * (1 - f_) + Vp[a_ + 1] * f_
    if ie - ib >= 1: put(ib, ie, matome([Vp], ie - ib))
vm = nd.uniform_filter1d(done, 3)[:, None]; T = vm * T + (1 - vm) * D; s2 = 10 ** (T / 10); s2 *= (sp.mean(1) / (s2.mean(1) + 1e-30))[:, None]
if os.environ.get('OROW'): json.dump(dict(db=[[round(float(v), 2) for v in r] for r in 10 * np.log10(s2 + 1e-30)], lead=0), open(f'{SWAP}/orow_{tag}.json', 'w'))
y = pw.synthesize(f0, np.ascontiguousarray(s2), ap, SR, 5); sf.write(f'{SWAP}/{tag}.wav', y / max(1, np.abs(y).max() / 0.9), SR); print(tag, MODE, 'N', N, '貼ったこま', int(done.sum()), '/', n)
