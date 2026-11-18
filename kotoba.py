# kotoba: kana -> formant tracks (F1..F3), per-bump gains, noise bands, loudness, voicing.  5 ms frames.
# Pure-Python standard-library tracks_from_kana; no numpy.
# Where the numbers come from:
#   VT (vowel formants, adult female), LE (F2 locus equations), place/manner rules, cue shapes: textbook / literature, alpha=1.15 / alpha3=1.3
#     scaling and consonant cues chosen by owner ear + ASR.
#   CDUR / VDUR / VL / CL / TAILT / HEAD0: rule-only textbook table (isochronous ~ mora, consonant class shares, r=25ms / w=55ms).
import math, bisect

FP = 5.0
K2V = {}
for row, cons in [("アイウエオ", ""), ("カキクケコ", "k"), ("サシスセソ", "s"), ("タチツテト", "t"), ("ナニヌネノ", "n"), ("ハヒフヘホ", "h"),
                  ("マミムメモ", "m"), ("ヤ・ユ・ヨ", "y"), ("ラリルレロ", "r"), ("ワ・・・ヲ", "w"), ("ガギグゲゴ", "g"), ("ザジズゼゾ", "z"),
                  ("ダヂヅデド", "d"), ("バビブベボ", "b"), ("パピプペポ", "p")]:
    for k, v in zip(row, "aiueo"):
        if k != "・": K2V[k] = (cons, v)
K2V.update({"シ": ("sh", "i"), "チ": ("ch", "i"), "ツ": ("ts", "u"), "ジ": ("j", "i"), "ヂ": ("j", "i"), "ヅ": ("z", "u"),
            "フ": ("f", "u"), "ヴ": ("b", "u"), "ヲ": ("", "o")})
SMALL = {"ャ": "a", "ュ": "u", "ョ": "o", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}
PALC = {"s": "sh", "z": "j", "t": "ch", "d": "j"}
PAUSE = set("、。，．,.!！?？… 　")

def to_kata(s):
    return ''.join(chr(ord(ch) + 0x60) if 'ぁ' <= ch <= 'ゖ' else ch for ch in s)

def split_moras(text):
    out = []
    for ch in to_kata(text):
        if ch in PAUSE:
            if out and out[-1] != '、': out.append('、')
        elif ch in SMALL and out and out[-1] not in ('、', 'ッ', 'ン', 'ー'): out[-1] += ch
        else: out.append(ch)
    while out and out[-1] == '、': out.pop()
    return out

def parse_kana(t, pv):
    if t == 'ー': return '', pv, False
    if len(t) == 2 and t[1] in SMALL:
        c, v0 = K2V.get(t[0], ('', pv)); v = SMALL[t[1]]
        if c in ('sh', 'ch', 'j'): return c, v, False
        if t[1] in 'ャュョ':
            if c in PALC: return PALC[c], v, False
            return c, v, True
        return (c or 'w'), v, False
    c, v = K2V.get(t, ('', pv)); return c, v, False

PLACE = {'p': 'lab', 'b': 'lab', 'm': 'lab', 'f': 'lab', 'w': 'lab', 't': 'alv', 'd': 'alv', 'n': 'alv', 's': 'alv', 'z': 'alv', 'ts': 'alv',
         'r': 'alv', 'sh': 'pal', 'ch': 'pal', 'j': 'pal', 'y': 'pal', 'k': 'vel', 'g': 'vel', 'h': 'glot', '': None}
MANNER = {'p': 'stop', 'b': 'stop', 't': 'stop', 'd': 'stop', 'k': 'stop', 'g': 'stop', 'm': 'nas', 'n': 'nas', 's': 'fric', 'z': 'fric',
          'sh': 'fric', 'j': 'fric', 'ch': 'affr', 'ts': 'affr', 'f': 'fric', 'h': 'h', 'r': 'tap', 'y': 'glide', 'w': 'glide', '': None}
VOICELESS = {'k', 's', 'sh', 't', 'ch', 'ts', 'h', 'f', 'p'}
VOICED_OBS = {'g', 'd', 'b', 'z', 'j'}

TEXTBOOK = dict(
    CDUR={'': 0, 'k': 70, 'g': 50, 's': 100, 'z': 70, 'sh': 100, 'j': 70, 't': 60, 'd': 40, 'ch': 80, 'ts': 80, 'n': 50, 'h': 70, 'f': 70,
          'm': 50, 'y': 60, 'r': 25, 'w': 55, 'b': 40, 'p': 70},
    VDUR={'a': 90, 'e': 90, 'i': 80, 'o': 90, 'u': 75},
    VL={'a': 0.0, 'e': -0.5, 'i': -0.8, 'o': -0.3, 'u': -0.8},
    CL={'k': (-12, -5), 't': (-12, -5), 'p': (-12, -5), 'ch': (-12, -4), 'ts': (-12, -4), 'g': (-4, -2), 'd': (-4, -2), 'b': (-4, -2),
        's': (-3, -3), 'sh': (-3, -3), 'z': (-3, -2), 'j': (-3, -2), 'h': (-5, -4), 'f': (-5, -4), 'm': (-1.5, -1.5), 'n': (-1.5, -1.5),
        'r': (-1.0, -1.0), 'w': (-0.5, -0.5), 'y': (-0.5, -0.5)},
    TAILT={'stop-vl': -6.0, 'Q': -6.0, 'fric-vl': -1.0, 'h-vl': -1.0, 'stop': -2.0},
    HEAD0={'h': -4.0, 'f': -4.0, 'r': -2.0, 'y': -1.0, 'w': -1.0})

DEF = dict(
    alpha=1.15, alpha3=1.3, T=30, Tvc=30, Tvv=40, Tpal=40, undershoot=80, f1on=280, f1drop=True, smooth=10,
    VT={'a': (850, 1400, 2800), 'i': (330, 2750, 3300), 'u': (380, 1600, 2700), 'e': (520, 2350, 3000), 'o': (530, 950, 2850)},
    LE={'lab': (0.75, 280), 'alv': (0.40, 1250), 'pal': (0.30, 1850), 'velF': (0.95, 300), 'velB': (1.05, 350)},
    gl={'y': (300, 2700, 3300), 'w': (360, 800, 2600)},
    fricT={'s': (2600, 4600, 6400), 'z': (2600, 4600, 6400), 'ts': (2600, 4600, 6400), 'sh': (1500, 3000, 4000), 'j': (1500, 3000, 4000), 'ch': (1500, 3000, 4000)},
    nasT={'m': (280, 1100, 2500), 'n': (280, 1600, 2700), 'N': (300, 1300, 2600)},
    vl_f1=1000, vl_on=0.85, vbar=350, alvF2=2350, alvF3=3000,
    cues=('fric', 'stop', 'nas', 'h', 'r'), sc=6000, ssd=1300, shc=3600, shsd=900, fg=2.2, fvg=0.15, ng2=0.15, ndl=-1.2, asp=3, bg=3.0,
    r3=2000, rdl=-1.5, rtrack=True, cue_dl=True,
    rate=1.0, fin=1.5, pau=0.35, qn=0.10,
    sil=-30.0, qlev=-18.0, decl=1.5, f0=220.0, devmax=0.045, Nlev=-1.0, fend=-6.0,
    **TEXTBOOK)

HUMAN = dict(TEXTBOOK)

def fi(s): return int(round(s * 1000 / FP))

# ---------------------------------------------------------------- small numpy stand-ins
def linspace(a, b, k):
    if k <= 0: return []
    if k == 1: return [float(a)]
    st = (b - a) / (k - 1); out = [a + i * st for i in range(k)]; out[-1] = float(b); return out

def _rng(n, a, b):
    return range(*slice(a, b).indices(n))

def setslice(L, a, b, vals):
    idx = _rng(len(L), a, b)
    if isinstance(vals, (int, float)):
        for i in idx: L[i] = vals
    else:
        if len(vals) != len(idx): raise ValueError('shape mismatch %d vs %d' % (len(vals), len(idx)))
        for i, v in zip(idx, vals): L[i] = v

def interp(x, xp, fp):
    if not xp: return [0.0] * len(x)
    out = []
    for v in x:
        if v < xp[0]: out.append(fp[0]); continue
        if v >= xp[-1]: out.append(fp[-1]); continue
        j = bisect.bisect_right(xp, v) - 1
        if v == xp[j]: out.append(fp[j]); continue
        sl = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]); out.append(sl * (v - xp[j]) + fp[j])
    return out

def smooth1(x, ms):
    k = max(1, int(ms / FP)); n = len(x)
    if k <= 1: return list(x)
    a = [x[0]] * k + list(x) + [x[-1]] * k; N = len(a); off = (k - 1) // 2; out = [0.0] * n
    for i in range(n):          # np.convolve(a, ones(k)/k, 'same')[k:-k]
        j = i + k + off; s = 0.0
        for m in range(k):
            q = j - m
            if 0 <= q < N: s += a[q] * (1.0 / k)
        out[i] = s
    return out

# ---------------------------------------------------------------- timing
def mora_info(moras):
    out = []; pv = 'a'
    for j, m in enumerate(moras):
        t = m['t']; fin = j + 1 == len(moras) or moras[j + 1]['t'] == '、'
        q = dict(t=t, cd=m.get('c', 0.0), vd=m.get('v', 0.0), p=m.get('p', 0.0), final=fin, dev=False)
        if t in ('、', 'ッ', 'ン'): q.update(kind={'、': 'pau', 'ッ': 'Q', 'ン': 'N'}[t], c='', v=None, pal=False)
        else:
            c, v, pal = parse_kana(t, pv); pv = v; q.update(kind='CV', c=c, v=v, pal=pal)
        out.append(q)
    for j, q in enumerate(out):
        if q['kind'] != 'CV': continue
        nx = out[j + 1] if j + 1 < len(out) else None
        nvl = nx is not None and ((nx['kind'] == 'CV' and nx['c'] in VOICELESS) or nx['kind'] == 'Q')
        q['dev'] = q['v'] in 'iu' and q['c'] in VOICELESS and (nvl or (q['final'] and q['c'] == 's'))
    return out

def rule_durations(ml, P):
    if P.get('uta_trance'):
        for q in ml:
            q['dev'] = False
    cd_s = P.get('cd_s', 0.75 if P.get('uta_trance') else 1.0)
    vd_s = P.get('vd_s', 1.12 if P.get('uta_trance') else 1.0)
    for q in ml:
        if q['kind'] == 'pau': q['cd'], q['vd'] = 0.0, P['pau']; continue
        if q['kind'] in ('Q', 'N'): q['cd'], q['vd'] = 0.0, P['qn'] * (1.3 if (q['final'] and q['kind'] == 'Q') else 1.0); continue
        c = P['CDUR'][q['c']] / 1000 * P['rate'] * cd_s; v = P['VDUR'][q['v']] / 1000 * P['rate'] * vd_s
        if q['dev']: v = min(v, P['devmax'])
        if q['final']: v *= P['fin']
        q['cd'], q['vd'] = c, v
    if P.get('vd_ms'):                  # 127 歌：拍ごとの母音（ッ・ンも）の長さ ms を上書き（間を除いた拍の順、None はそのまま）
        k = 0
        for q in ml:
            if q['kind'] == 'pau': continue
            if k < len(P['vd_ms']) and P['vd_ms'][k] is not None: q['vd'] = P['vd_ms'][k] / 1000
            k += 1
    return ml

def segments(ml, pre):
    seq = []; tt = pre
    for q in ml:
        a = tt; b = a + q['cd']; e = b + q['vd']; tt = e
        s = dict(q, a=a, b=b, e=e)
        if q['kind'] == 'Q': s['b'] = e
        if q['kind'] in ('N', 'pau'): s['b'] = a
        seq.append(s)
    return seq, tt

# ---------------------------------------------------------------- formant tracks
def build_tracks(seq, n, P):
    al, al3 = P['alpha'], P['alpha3']
    sc = lambda f: [f[0] * al, f[1] * al, f[2] * al3]
    vt = lambda s: sc(P['VT'][s['v']])
    def onset(c, V, v, pal):
        pl = PLACE[c]; mn = MANNER[c]
        if mn == 'glide': return sc(P['gl'][c])
        if pl is None: return list(V)
        f2 = V[1]
        if pl != 'glot': k, cc = P['LE'][pl if pl != 'vel' else ('velF' if v in 'ie' else 'velB')]; f2 = k * V[1] + cc * al
        f1 = V[0]
        if P['f1drop']:
            if c in ('p', 't', 'k', 'ch', 'ts'): f1 = P['vl_on'] * V[0]
            elif mn in ('stop', 'nas', 'tap'): f1 = min(V[0], P['f1on'] * al)
            elif mn == 'fric': f1 = min(V[0], (P['f1on'] + 100) * al)
        f3 = V[2]
        if pl == 'lab': f3 = V[2] - 250 * al3
        elif pl == 'vel': f3 = max(f2 + 400 * al, V[2] - 200 * al3) if v in 'ie' else min(V[2], f2 + 900 * al)
        elif pl == 'alv': f3 = 0.5 * V[2] + 0.5 * 2900 * al3
        elif pl == 'pal': f3 = max(V[2], 3300 * al3)
        O = [float(f1), float(f2), float(f3)]
        if pal: I = sc(P['VT']['i']); O = [0.5 * O[j] + 0.5 * I[j] for j in range(3)]
        return O
    def body(c, V, v, O):
        mn = MANNER[c]
        if c in P['fricT']: return [float(z) for z in P['fricT'][c]]
        if c == 'f': return O
        if mn == 'stop':
            B = list(O)
            if PLACE[c] == 'alv': B[1] = P['alvF2'] * al; B[2] = max(O[2], P['alvF3'] * al3)
            B[0] = P['vl_f1'] * al if c in ('p', 't', 'k') else P['vbar'] * al
            return B
        if mn == 'nas':
            B = sc(P['nasT'][c])
            if c == 'n' and v == 'i': B[1] = 2200 * al
            return B
        if mn == 'h': return [max(V[0], 1100 * al), V[1], V[2]]
        if c == 'r' and P['rtrack']: return [350.0 * al, 1500.0 * al, float(P['r3'])]
        return O
    kp = []; cur = sc(P['VT']['a']); first = True
    for j, s in enumerate(seq):
        if s['kind'] == 'pau': continue
        if s['kind'] in ('Q', 'N'):
            nx = next((q for q in seq[j + 1:] if q['kind'] == 'CV'), None)
            adj = nx is not None and seq[j + 1] is nx and nx['c']
            if s['kind'] == 'N':
                if adj:
                    pl = PLACE[nx['c']]; B = sc(P['nasT']['m' if pl == 'lab' else ('n' if pl in ('alv', 'pal') else 'N')])
                    if pl == 'vel': B[1] = onset(nx['c'], vt(nx), nx['v'], nx['pal'])[1]
                else: B = sc(P['nasT']['N'])
                kp += [(s['a'] + P['Tvc'] / 1000, *B), (s['e'], *B)]
            elif adj:
                V = vt(nx); B = body(nx['c'], V, nx['v'], onset(nx['c'], V, nx['v'], nx['pal']))
                kp += [(s['a'] + P['Tvc'] / 1000, *B), (s['e'], *B)]
            continue
        c, v = s['c'], s['v']; V = vt(s)
        if P['undershoot'] and s['e'] - s['b'] < P['undershoot'] / 1000:
            r = max(0.4, (s['e'] - s['b']) / (P['undershoot'] / 1000)); V = [cur[q] + (V[q] - cur[q]) * r for q in range(3)]
        if c:
            O = onset(c, V, v, s['pal']); B = body(c, V, v, O)
            fh = P.get('fric_hold') and (c in P['fricT'] or (P.get('vl_hold') and c in VOICELESS))   # 103h：vl_hold で声の無い子音ぜんぶ（k, t, p, h, f …）に広げる
            if not first and s['b'] > s['a'] and not fh: kp.append((s['a'], *B))
            kp.append((s['a'] + (min(P['fric_hold'] / 1000 + 0.01, (s['b'] - s['a']) * 0.4) if fh else min(P['Tvc'] / 1000, (s['b'] - s['a']) * 0.5)), *B))
            if fh:   # 103g：息の子音（s, sh …）の山の形は声の無い間だけ。声が始まる前に母音の形へ着いておく（山が滑る「わ」の音を出さん）
                kp.append((max(s['b'] - P['fric_hold'] / 1000 - 0.01, s['a']), *B))
                ho = P.get('hold_on')          # 123：声の頭で子音の出だしの的 O を通す（'pal'＝拗音だけ、'all'＝声の無い子音ぜんぶ）。F1 は母音より上から滑らせん（ほわんを戻さん）
                if ho == 'all' or (ho == 'pal' and s['pal']):
                    kp.append((max(s['b'] - P['fric_hold'] / 1000, s['a']), min(O[0], V[0]), O[1], O[2]))
                    kp.append((min(s['b'] + (P['T'] + (P['Tpal'] if s['pal'] else 0)) / 1000, s['e']), *V))
                else: kp.append((max(s['b'] - P['fric_hold'] / 1000, s['a']), *V))
            else:
                kp.append((max(s['b'] - 0.005, s['a']), *B))
                kp.append((s['b'], *O))
                Tt = (P['T'] + (P['Tpal'] if (s['pal'] or MANNER[c] == 'glide') else 0)) / 1000
                kp.append((min(s['b'] + Tt, s['e']), *V))
        else:
            kp.append((s['a'] + P['Tvv'] / 2000, *V))
        nxc = j + 1 < len(seq) and seq[j + 1]['kind'] == 'CV' and seq[j + 1]['c']
        if P.get('fric_hold') and nxc and (nxc in P['fricT'] or (P.get('vl_hold') and nxc in VOICELESS)): kp.append((s['e'] + P['fric_hold'] / 1000, *V))   # 103g：次が息の子音なら、声が止むまで母音の形のまま
        else: kp.append((s['e'] - (P['Tvc'] / 1000 if nxc else P['Tvv'] / 2000), *V))
        cur = list(V); first = False
    if not kp: return [[float(cur[j])] * n for j in range(3)]
    kp.sort(key=lambda q: q[0]); tfr = [i * FP / 1000 for i in range(n)]; xp = [float(q[0]) for q in kp]
    return [smooth1(interp(tfr, xp, [float(q[j + 1]) for q in kp]), (P.get('smooth_j') or [P['smooth']] * 3)[j]) for j in range(3)]   # 77a: per-formant track smoothing

# ---------------------------------------------------------------- consonant cues
def build_cues(seq, n, P):
    G = [[1.0] * n for _ in range(3)]; dl = [0.0] * n; bands = []; cues = set(P['cues'])
    def gset(a, b, vals):
        for j in range(3): setslice(G[j], a, b, vals[j])
    def gmul(a, b, f):
        for j in range(3):
            for i in _rng(n, a, b): G[j][i] *= f
    for s in seq:
        i0, ib, ie = fi(s['a']), fi(s['b']), fi(s['e'])
        if s['kind'] == 'Q':
            if 'stop' in cues: setslice(dl, i0, ie, -6)
            continue
        if s['kind'] == 'N':
            if 'nas' in cues: gset(i0, ie, (0.87, P['ng2'], 0.5)); setslice(dl, i0, ie, P['ndl'])
            continue
        if s['kind'] == 'CV' and P.get('VG') and s['v'] in P['VG']:   # 114：母音ごとの山の強さ（例 い の上の山を強く）。母音の区間だけ
            for j in range(3):
                for i in _rng(n, ib, ie): G[j][i] *= P['VG'][s['v']][j]
        if s['kind'] != 'CV' or ib <= i0: continue
        c, v = s['c'], s['v']; nc = ib - i0
        if 'nas' in cues and c in ('m', 'n'): gset(i0, ib, (0.87, P['ng2'], 0.5)); setslice(dl, i0, ib, P['ndl'])
        fp_ = (i0, ib) if c in ('s', 'z', 'sh', 'j') else ((i0 + nc // 2, ib) if c in ('ch', 'ts') else None)
        if 'fric' in cues and fp_:
            cen, sd = (P['sc'], P['ssd']) if c in ('s', 'z', 'ts') else (P['shc'], P['shsd'])
            bands.append((fp_[0], fp_[1], cen, sd, P['fg'] + cen / 2500.0)); gmul(fp_[0], fp_[1], 0.45 if c in VOICED_OBS else P['fvg'])
        if 'h' in cues and c in ('h', 'f'):
            setslice(G[0], i0, ib, 0.4); setslice(G[1], i0, ib, 0.9); setslice(G[2], i0, ib, 0.9)
            if v == 'i' and c == 'h': bands.append((i0, ib, 3500, 700, 1.0 + 3500 / 2500.))
        if 'stop' in cues and c in ('k', 'g', 't', 'd', 'p', 'b', 'ch', 'ts'):
            ce = i0 + (nc // 2 if c in ('ch', 'ts') else max(1, nc - P['asp']))
            if c in VOICED_OBS: gset(i0, ce, tuple(P.get('vcg', (0.8, 0.05, 0.05)))); setslice(dl, i0, ce, P.get('vdl', -1.2))
            else: setslice(dl, i0, ce, -6)
            cen, sd = ((3000 if v in 'ie' else 1900), 500) if c in ('k', 'g') else ((4500, 1000) if c in ('t', 'd', 'ch', 'ts') else (1200, 900))
            bg = P.get('vbg', P['bg']) if c in VOICED_OBS else P['bg']
            bn = P.get('vbn', 2) if c in VOICED_OBS else 2
            bands.append((ce, min(ce + bn, ib + 1), cen, sd, bg + cen / 2500.0))
            if c not in ('ch', 'ts'): gset(ce, ib, (0.4, 1, 1) if c not in VOICED_OBS else (1, 1, 1))
        if 'r' in cues and c == 'r':
            setslice(dl, i0, ib, P['rdl'])
            if P.get('rG'): gset(i0, ib, P['rG'])
    return [smooth1(g, 10) for g in G], smooth1(dl, 10), bands

# ---------------------------------------------------------------- loudness and source
def nxcls(nx):
    if nx is None or nx['kind'] == 'pau': return 'end'
    if nx['kind'] != 'CV': return nx['kind']
    if not nx['c']: return 'V'
    return MANNER[nx['c']] + ('-vl' if nx['c'] in VOICELESS else '')

def rule_loud(seq, n, P):
    L = [float(P['sil'])] * n
    for j, s in enumerate(seq):
        ia, ib, ie = fi(s['a']), fi(s['a'] + s['cd']), fi(s['e']); nx = seq[j + 1] if j + 1 < len(seq) else None
        if s['kind'] == 'pau': continue
        if s['kind'] == 'Q': setslice(L, ia, ie, P['qlev']); continue
        if s['kind'] == 'N': setslice(L, ia, ie, P['Nlev'])
        else:
            if s['c'] in P['CL'] and ib > ia:
                c1, c2 = P['CL'][s['c']]; im = ia + int(0.7 * (ib - ia)); setslice(L, ia, im, c1); setslice(L, im, ib, c2)
            lv = P['VL'][s['v']] + (-6 if s['dev'] else 0); setslice(L, ib, ie, lv)
            if s['c'] in P['HEAD0']:
                k = min(8, ie - ib); setslice(L, ib, ib + k, linspace(lv + P['HEAD0'][s['c']], lv, k))
            else:
                k = min(3, ie - ib)
                if k > 0: st = L[ib - 1] if ib > 0 else P['sil']; setslice(L, ib, ib + k, linspace(min(st, lv - 3), lv, k))
        c = nxcls(nx)
        if c == 'end':
            k = ie - ib if s['kind'] == 'CV' else ie - ia; h = int(k * P.get('fend_at', 0.5))   # 103e：語尾の消え始め（母音の何割目から）
            if k - h > 0: setslice(L, ie - k + h, ie, linspace(L[ie - k + h], P['fend'], k - h))
        elif c in P['TAILT']:
            lv = L[ie - 1]; k = min(12, ie - ib); setslice(L, ie - k, ie, linspace(lv, lv + P['TAILT'][c] * 1.5, k))
    dc = linspace(0, 1, n); L = [L[i] - P['decl'] * dc[i] for i in range(n)]; L = smooth1(L, 10); mx = max(L)
    return [v - mx for v in L]

def rule_source(seq, n, P):
    vo = [False] * n; kt = []; kv = []
    for s in seq:
        a, b, e = s['a'], s['a'] + s['cd'], s['e']
        if s['kind'] in ('pau', 'Q'): continue
        if s['kind'] == 'N' or s['c'] not in VOICELESS: setslice(vo, fi(a), fi(b), True)
        if not s['dev']: setslice(vo, fi(b), fi(e), True)
        if s.get('p', 0) > 0: kt.append((b + e) / 2); kv.append(math.exp(s['p']))
    tfr = [i * FP / 1000 for i in range(n)]
    c = interp(tfr, kt, kv) if kt else [P['f0'] * math.exp(v) for v in linspace(0.1, -0.15, n)]
    c = smooth1(c, 30)
    return [c[i] if vo[i] else 0.0 for i in range(n)], vo

def tracks_from_kana(text=None, moras=None, pre=0.1, post=0.1, timing='rule', n=None, params=None):
    P = dict(DEF); P.update(params or {})
    if moras is None:
        ms = split_moras(text)
        if P.get('ou_long'):            # 76: textbook phonology: オ段＋ウ (and エ段＋イ if ei_long) is a long vowel, said as ー
            pv = None
            for j, t in enumerate(ms):
                if t == 'ウ' and pv == 'o' or (P.get('ei_long') and t == 'イ' and pv == 'e'): ms[j] = 'ー'
                pv = None if t in ('、', 'ッ', 'ン') else parse_kana(ms[j], pv or 'a')[1]
        moras = [dict(t=t, c=0, v=0, p=0) for t in ms]
    ml = mora_info([dict(m) for m in moras])
    if timing == 'rule': ml = rule_durations(ml, P)
    seq, end = segments(ml, pre)
    n = n or fi(end + post) + 1
    Tr = build_tracks(seq, n, P); G, dl, bands = build_cues(seq, n, P)
    loud = rule_loud(seq, n, P); f0, vo = rule_source(seq, n, P)
    return dict(fp_ms=FP, n=n, F1=Tr[0], F2=Tr[1], F3=Tr[2], G1=G[0], G2=G[1], G3=G[2], dl=dl, loud=loud, f0=f0, voiced=vo,
                bands=[(a * FP / 1000, b * FP / 1000, c, d, g) for a, b, c, d, g in bands],
                moras=[{k: s[k] for k in ('t', 'kind', 'c', 'v', 'a', 'b', 'e')} for s in seq])

if __name__ == '__main__':
    import sys
    r = tracks_from_kana(sys.argv[1] if len(sys.argv) > 1 else 'きょうもいっしょにがんばろうね')
    print(r['n'], [(m['t'], round(m['a'], 3), round(m['e'], 3)) for m in r['moras']])
