# analysis only: 手本の決まりを統合する。手本が 1 人のときはそのまま、複数人のときは平均の色＋平均の的＋k×（先頭 2 声の共通ずれ）。mijikaiF_m{k}.npz（鍵 a＝96 帯）
import numpy as np, os
sids = os.environ.get('SIDS', '').split()
if not sids: raise SystemExit('SIDS required')
Z = {s: np.load(f'mijikaiF_{s}.npz') for s in sids}; names = sorted(set.intersection(*[set(Z[s]['names']) for s in sids]))
M = np.array([[Z[s]['a'][list(Z[s]['names']).index(k)] for k in names] for s in sids]); col = M.mean(1, keepdims=True); R = M - col; com = R.mean(0)
S = ((R[0] + R[1]) / 2 - com) if len(sids) >= 2 else np.zeros_like(com)
W = np.array([Z[s]['w'] for s in sids]).mean(0); WC = np.array([Z[s]['wc'] for s in sids]).mean(0)
for k in (0, 1, 2, -1): np.savez(f'mijikaiF_m{k}.npz', names=np.array(names), w=W, wc=WC, a=col.mean(0) + com + k * S)
print('ずれの大きさ rms dB', round(float(np.sqrt((S ** 2).mean())), 1))
