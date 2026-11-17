# analysis only → 決まり（全帯）: 80〜8000Hz の 96 帯（こま全体の強さが基準）で、「的＋次の音へ寄る」作り。mijikaiF_{WHO}.npz
import pickle, os, numpy as np, scipy.fft as F
WHO = os.environ['WHO']; U_ = pickle.load(open(f'unitsF{WHO}.pkl', 'rb')); U = [u for u in U_ if u['v'] in 'aiueo' and len(u['V']) >= 2]
def rs(A, M): return A[np.round(np.linspace(0, len(A) - 1, M)).astype(int)]
Y = np.array([rs(u['V'], 10) for u in U]); NB = Y.shape[2]; vow = [u['v'] for u in U]; nx = [(u['nc'] if u['nc'] else u['nv'].lower()) for u in U]; hc = [j for j, u in enumerate(U) if len(u['C']) >= 2]; YC = np.array([rs(U[j]['C'], 5) for j in hc]); cc = [U[j]['c'] for j in hc]; cvw = [U[j]['v'] for j in hc]
names = sorted(set('aiueo') | set(nx) | set(cc)); ix = {k: j for j, k in enumerate(names)}; K = len(names); vi = np.array([ix[v] for v in vow]); ni = np.array([ix[x] for x in nx]); ci = np.array([ix[c] for c in cc]); cvi = np.array([ix[v] for v in cvw]); tv = ((Y - Y.mean((0, 1))) ** 2).sum()
w = np.linspace(0, .6, 10) ** 2; wc = np.linspace(.2, .8, 5)
for it in range(12):
    A = np.zeros((K, K)); B = np.zeros((K, NB))
    for t in range(10):
        for (a, ca), (b, cb) in (((vi, 1 - w[t]), (vi, 1 - w[t])), ((vi, 1 - w[t]), (ni, w[t])), ((ni, w[t]), (vi, 1 - w[t])), ((ni, w[t]), (ni, w[t]))): np.add.at(A, (a, b), ca * cb)
        np.add.at(B, vi, (1 - w[t]) * Y[:, t]); np.add.at(B, ni, w[t] * Y[:, t])
    for t in range(5):
        for (a, ca), (b, cb) in (((ci, 1 - wc[t]), (ci, 1 - wc[t])), ((ci, 1 - wc[t]), (cvi, wc[t])), ((cvi, wc[t]), (ci, 1 - wc[t])), ((cvi, wc[t]), (cvi, wc[t]))): np.add.at(A, (a, b), ca * cb)
        np.add.at(B, ci, (1 - wc[t]) * YC[:, t]); np.add.at(B, cvi, wc[t] * YC[:, t])
    M = np.linalg.solve(A + 1e-3 * np.eye(K), B); d = M[ni] - M[vi]; w = np.array([((Y[:, t] - M[vi]) * d).sum() / (d ** 2).sum() for t in range(10)]).clip(0, 1); d = M[cvi] - M[ci]; wc = np.array([((YC[:, t] - M[ci]) * d).sum() / (d ** 2).sum() for t in range(5)]).clip(0, 1)
def sc(M): P = (1 - w)[None, :, None] * M[vi][:, None] + w[None, :, None] * M[ni][:, None]; return 1 - ((Y - P) ** 2).sum() / tv
res = dict(a=M); print(WHO, '単位', len(U), '的', K, ' w', np.round(w, 2), ' 当てはまり 96 帯のまま', round(float(sc(M)), 2), end=' ')
for q in (24, 16, 12):
    C = F.dct(M, axis=1, norm='ortho'); C[:, q:] = 0; res[f'b{q}'] = F.idct(C, axis=1, norm='ortho'); print(f'成分 {q} 個 {sc(res[f"b{q}"]):.2f}', end=' ')
print(); np.savez(f'mijikaiF_{WHO}.npz', names=np.array(names), w=w, wc=wc, **res)
