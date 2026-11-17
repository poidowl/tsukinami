# mkt.py：文を env TEXTS（JSON の並び）から取り、ノイズ削りの土台音声を合成する（標準ライブラリのみ）。
# MO=1 で拍の時刻（頭の 0.5 秒を引いた物）も swap/mo_{tag}_{j}.json に書く。
import sys, os, copy, json
W = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, W); os.chdir(W)
import carve as C
tag = sys.argv[1]
OUT = os.environ.get('OUT', os.path.join(W, 'out')); os.makedirs(OUT, exist_ok=True)
SWAP = os.environ.get('SWAP', os.path.join(W, 'swap')); os.makedirs(SWAP, exist_ok=True)
BASE = {"bump":[3,1.4,1.4],"g":[0.7,0.7,0.7],"floor":1.0,"ap_on":"mix","ap_n":40,"ap_lo":300,"ap_hi":8000,"ap_bw":150,"band":3.0}
R103 = json.loads(r"""{"p_low": [5, 4, 3], "vfloor": {"a": 0.6, "o": 0.3}, "f1x_cmute": 1.0, "f45": [[1400, 0.75], [2300, 0.3]], "vbump": {"a": [1, 1.2, 1], "e": [0.7, 1.3, 0.7], "o": [1, 1, 0.3], "i": [0.7, 0.6, 0.7]}, "f1x": [[2.0, 0.35], [0.45, 0.25], [2.8, 0.35]], "vf1x": {"a": [0.15, 0, 0], "i": [0.3, 0, 0.3], "u": [0.3, 0, 0.3], "e": [0.5, 1, 0], "o": [0.1, 1, 0]}, "henv": null}""")
kw = dict(R103); kw.update({"P.fend_at":0.15,"P.fric_hold":20,"P.vl_hold":True,"P.vdl":-2.0,"P.vbg":1.5}); kw.update(json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
r = copy.deepcopy(C.E79); r['line.D_center'] = C.E79['line.D_center'] * 436.6 / 360
K = dict(fscale=1.22); K.update(BASE); P = {}
for k, v in kw.items():
    if k.startswith('line.') or k.startswith('kugiri.'): r[k] = v
    elif k.startswith('P.'): P[k[2:]] = v
    elif k.startswith('rc.'): r[k[3:]] = v
    else: K[k] = v
r['kotoba'] = dict(r['kotoba'], **K); r['kotoba']['params'] = dict(r['kotoba']['params'], **P)
A2 = r['kotoba'].pop('acc2', None); HZ = r['kotoba'].pop('hz', None)
if HZ: r['line.D_center'] = C.E79['line.D_center'] * 436.6 / HZ
for j, t in enumerate(json.loads(os.environ['TEXTS'])):
    rr = copy.deepcopy(r)
    if j == 1 and A2: rr['kotoba']['accent_kw'] = dict(rr['kotoba'].get('accent_kw') or {}, **A2)
    x, m = C.make(C.variant(dict(rr, text=t, seed=2024))); C.write(f'{OUT}/{tag}_{j+1}.wav', x)
    if os.environ.get('MO'):
        mm = m['moras'] if isinstance(m, dict) else m; mm = [dict(q) for q in mm]
        for q in mm:
            for k in 'abe': q[k] -= .5
        json.dump(mm, open(f'{SWAP}/mo_{tag}_{j+1}.json', 'w'), default=str)
