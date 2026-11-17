# key: accent.  Rule-based Tokyo-Japanese pitch accent + intonation -> 5 ms f0 frames for combo/rules.py.
# Pure Python (standard library only).  No dictionary required; optional hand marking of accents/phrases.
#
#   import accent as A
#   kana, phr = A.annotate("おはよう、きょ'うも いっしょに がんばろ'うね")   # optional marks: ' after accent nucleus, space = phrase break
#   r = rules.tracks_from_kana(kana)                                          # any timing
#   f0 = A.f0_rule(r['moras'], r['n'], r['voiced'], phrases=phr, **A.CUTE)    # list of n floats (Hz, 0 = unvoiced)
#
# Model (textbook Tokyo accent, Pierrehumbert & Beckman / Fujisaki-style, in semitones):
#   accent phrase (AP): initial %L on mora 1 (weak if mora 2 is ン/ッ/ー or first mora accented), H plateau up to the
#   nucleus, fall after it (accent 0 = heiban: no fall, particles stay high); post-nucleus morae continue to sag.
#   downstep: an accented AP lowers the H of the following APs (catathesis); pause = new intonation phrase, partial reset.
#   declination over time; utterance-final fall (or question rise if text ends in ?/？).
#   No dictionary: APs = pause chunks split after particle-like morae; accent guess = heiban (default) or antepenultimate.
import math

SPECIAL = ('ン', 'ッ', 'ー')
VL_C = {'k', 's', 'sh', 't', 'ch', 'ts', 'h', 'f', 'p'}
VD_OBS = {'g', 'd', 'b', 'z', 'j'}
PART = set('モニガヲデヘテ')          # particle-like / te-form endings that usually close a bunsetsu
PAUSE = set("、。，．,.!！?？… 　")

NORMAL = dict(reg=340.0, rng=8.0, jump=4.0, fall=5.0, sag=1.0, lag=1.0, rlag=0.5, ds=2.0, ds_h=0.5, reset=0.6, decl=1.2, fin=3.0, qrise=5.0, sm=35.0)
CUTE = dict(reg=410.0, rng=10.0, jump=5.6, fall=6.0, sag=1.2, lag=1.0, rlag=0.5, ds=2.0, ds_h=0.4, reset=0.7, decl=1.0, fin=2.0, qrise=6.0, sm=30.0)
# rules.py params for owner-favoured timing: ~7.8 morae/s and phrase-final lengthening 1.45 (set in ev script by measurement)
CUTE_TIMING = dict(fin=1.45)   # rules.py params; with the default rate this gives ~7.8 morae/s


def to_kata(s):
    return ''.join(chr(ord(ch) + 0x60) if 'ぁ' <= ch <= 'ゖ' else ch for ch in s)


SMALL = set("ャュョァィゥェォ")


def split_marked(text):
    """kana with marks -> list of tokens: mora strings, "'" accent mark, '/' phrase break, '、' pause (same mora rules as rules.split_moras)"""
    out = []
    for ch in to_kata(text):
        if ch in ("'", "’"): out.append("'")
        elif ch in (' ', '/', '|'):
            if out and out[-1] not in ('/', '、'): out.append('/')
        elif ch in '?？':
            if out and out[-1] in ('/', '、'): out[-1] = '?'
            elif out: out.append('?')
        elif ch in PAUSE:
            if out and out[-1] == '/': out[-1] = '、'
            elif out and out[-1] not in ('、', '?'): out.append('、')
        elif ch in SMALL and out and out[-1] not in ('、', 'ッ', 'ン', 'ー', "'", '/'): out[-1] += ch
        else: out.append(ch)
    while out and out[-1] in ('、', '/'): out.pop()
    return out


def annotate(text):
    """marked kana -> (clean kana for rules.tracks_from_kana, phrases).  phrases = list of [start, length, accent] over the
    non-pause morae (accent = 1-based nucleus mora within the AP, 0 = heiban, None = guess).  An AP with no ' mark gets None
    unless it is followed by a 0 digit ("おはよう0" = explicitly heiban)."""
    toks = split_marked(text.replace('0', '#'))
    clean, phr, cur, k = [], [], None, 0
    for i, t in enumerate(toks):
        if t in ('、', '/', '?'):
            if t == '?' and cur is not None: cur[3] = 1
            if t == '、' or (t == '?' and i + 1 < len(toks)): clean.append('、')
            cur = None; continue
        if t == '#':
            if cur is not None and cur[2] is None: cur[2] = 0
            continue
        if t == "'":
            if cur is not None: cur[2] = k - cur[0]
            continue
        if cur is None: cur = [k, 0, None, 0]; phr.append(cur)
        cur[1] += 1; clean.append(t); k += 1
    return ''.join(clean), phr


def guess_phrases(moras, accent='ante', split=False, minlen=3):
    """no-dictionary AP segmentation + accent guess.  moras: kana text (may contain ?), list of mora strings
    ('、' = pause, '?' = question pause) or rules.py mora dicts."""
    ts = split_marked(moras) if isinstance(moras, str) else [m['t'] if isinstance(m, dict) else m for m in moras]
    ts = [t for t in ts if t not in ("'", '/')]
    chunks, cur, qs = [], [], []
    for t in ts:
        if t in ('、', '?'):
            if cur: chunks.append(cur); qs.append(t == '?'); cur = []
            elif t == '?' and qs: qs[-1] = True
        else: cur.append(t)
    if cur: chunks.append(cur); qs.append(False)
    phr, k = [], 0
    for ch, isq in zip(chunks, qs):
        cuts, s = [], 0
        if split:
            for j in range(len(ch)):
                if ch[j] in PART and j + 1 - s >= minlen and len(ch) - (j + 1) >= minlen and (j + 1 >= len(ch) or ch[j + 1] not in SPECIAL):
                    cuts.append(j + 1); s = j + 1
        bounds = [0] + cuts + [len(ch)]
        for a, b in zip(bounds[:-1], bounds[1:]):
            L = b - a; seg = ch[a:b]
            ended_by_particle = b in cuts or (seg[-1] in PART and L > 2)
            if accent == 'heiban': acc = 0
            elif accent == 'ante':           # antepenultimate mora of the word (particle stripped), never on a special mora
                W = L - (1 if ended_by_particle else 0)
                acc = max(1, W - 2) if W >= 3 else 1
                while acc > 1 and seg[acc - 1] in SPECIAL: acc -= 1
            elif accent == 'mixed':          # short exclamation-like chunks (<=2 morae) accent 1, otherwise heiban
                acc = 1 if L <= 2 else 0
            else: acc = 0
            phr.append([k + a, L, acc, int(isq and b == len(ch))])
        k += len(ch)
    return phr


def _targets(ml, phrases, P, question):
    """per non-pause mora: (level_st_start, level_st_end) relative to the H line of the utterance"""
    idx = [j for j, m in enumerate(ml) if m['kind'] != 'pau']
    lv = [None] * len(ml)
    top = 0.0
    for pi, (s, L, acc, *_q) in enumerate(phrases):
        if pi > 0:
            ps, pL, pacc = phrases[pi - 1][:3]
            prev_end = idx[ps + pL - 1]; this_start = idx[s]
            drop = P['ds'] if pacc else P['ds_h']
            top -= drop
            if any(ml[j]['kind'] == 'pau' for j in range(prev_end + 1, this_start)): top *= (1 - P['reset'])   # partial reset at a pause
        H = top; Lo = top - P['jump']
        weak = L > 1 and _heavy(ml[idx[s]], ml[idx[s + 1]])
        for q in range(L):
            j = idx[s + q]; pos = q + 1
            lag, rl = P.get('lag', 0.0), P.get('rlag', 0.0)
            if acc == 1 and pos == 1: a = b = H
            elif acc and pos > acc:      # post-nucleus: fall starts at the nucleus end, completes over the next mora (lag)
                d = P['fall'] + P['sag'] * (pos - acc - 1); a = b = H - d
                if pos == acc + 1: a = H - P['fall'] * (1 - lag)
            elif pos == 1:
                a = b = (H - P['jump'] * 0.45) if weak else Lo
                if L == 1: a = b = H - 1.0
            else:
                a = b = H
                if pos == 2 and not weak: a = H - P['jump'] * rl     # gradual initial rise
            lv[j] = [a, b]
        if _q and _q[0]:                    # question: rise on the last mora of this AP
            j = idx[s + L - 1]; lv[j][1] = lv[j][0] + P['qrise']
    # utterance-final fall / question rise on the last mora (spread over the last two morae for the fall)
    last = idx[-1]
    if question: lv[last][1] = lv[last][0] + P['qrise']
    elif not (phrases[-1][3:] and phrases[-1][3]):
        lv[last][1] = lv[last][0] - P['fin']
        if len(idx) > 1: lv[idx[-2]][1] -= P['fin'] * 0.25
    return lv


def f0_rule(moras, n, voiced=None, phrases=None, accent='ante', question=False, reg=340.0, rng=8.0, jump=4.0, fall=5.0,
            sag=1.0, lag=1.0, rlag=0.5, ds=2.0, ds_h=0.5, reset=0.6, decl=1.2, fin=2.5, qrise=5.0, sm=35.0, fp_ms=5.0, fit_range=True, micro=0.0):
    """moras: rules.tracks_from_kana(...)['moras'] (dicts with t, kind, a, b, e in s).  n: number of 5 ms frames.
    voiced: per-frame bools (f0 forced to 0 where False; None = all voiced).  phrases: [[start, len, accent], ...] over
    non-pause morae (from annotate), or None -> guess_phrases(accent=...).  reg = mean f0 (Hz) of voiced frames,
    rng = target 5-95 % range in semitones (scales the contour if fit_range).  micro (st) adds micro-prosody: a +micro st
    onset bump after voiceless consonants (decays in ~40 ms), -0.5*micro dip in voiced obstruents, and a slow
    deterministic drift of +-0.25*micro st.  Returns list of n floats (Hz)."""
    P = dict(jump=jump, fall=fall, sag=sag, ds=ds, ds_h=ds_h, reset=reset, fin=fin, qrise=qrise, lag=lag, rlag=rlag)
    ml = list(moras)
    if phrases is None: phrases = guess_phrases(ml, accent)
    else:
        phrases = [list(p) if p[2] is not None else [p[0], p[1], _guess1(ml, p, accent)] + list(p[3:]) for p in phrases]
    lv = _targets(ml, phrases, P, question)
    # keypoints (t, st): plateau over the vowel, consonant interval interpolates
    kt, kv = [], []
    for m, l in zip(ml, lv):
        if l is None: continue
        b, e = m['b'], m['e']
        if e - b < 0.02: b = m['a']
        kt += [b, e]; kv += [l[0], l[1]]
    if not kt: return [0.0] * n
    t0 = kt[0]
    kv = [v - decl * (t - t0) for t, v in zip(kt, kv)]
    fp = fp_ms / 1000.0
    st = []
    j = 0
    for i in range(n):
        t = i * fp
        if t <= kt[0]: st.append(kv[0]); continue
        if t >= kt[-1]: st.append(kv[-1]); continue
        while kt[j + 1] < t: j += 1
        a, b = kt[j], kt[j + 1]
        w = 0.0 if b <= a else (t - a) / (b - a)
        st.append(kv[j] + w * (kv[j + 1] - kv[j]))
    st = _smooth(st, max(1, int(sm / fp_ms)))
    vo = [True] * n if voiced is None else [bool(v) for v in voiced]
    vs = sorted(s for s, v in zip(st, vo) if v) or sorted(st)
    if fit_range and rng:
        lo, hi = vs[int(0.05 * (len(vs) - 1))], vs[int(0.95 * (len(vs) - 1))]
        k = rng / (hi - lo) if hi - lo > 1e-6 else 1.0
        st = [s * k for s in st]; vs = [s * k for s in vs]
    if micro:
        for m in ml:
            c = m.get('c') or ''; ib = int(round(m['b'] / fp))
            if m.get('kind') != 'CV' or not c: continue
            if c in VL_C:
                for q in range(10):
                    if 0 <= ib + q < n: st[ib + q] += micro * math.exp(-q / 3.0)
            elif c in VD_OBS:
                for q in range(int(round(m['a'] / fp)), ib + 2):
                    if 0 <= q < n: st[q] -= 0.5 * micro
        st = [s + 0.25 * micro * (math.sin(2 * math.pi * 1.7 * i * fp + 0.3) + 0.6 * math.sin(2 * math.pi * 4.3 * i * fp + 1.1)) for i, s in enumerate(st)]
    # mean in log domain -> reg Hz
    mu = sum(vs) / len(vs)
    return [reg * 2 ** ((s - mu) / 12.0) if v else 0.0 for s, v in zip(st, vo)]


LONGV = {'a': 'ア', 'i': 'イ', 'u': 'ウ', 'e': 'エイ', 'o': 'オウ'}
def _heavy(m1, m2):
    """first syllable heavy (CVN, CVQ, long vowel, diphthong-ish CVi): Tokyo initial lowering is weak/absent"""
    t = m2['t']
    if t in SPECIAL: return True
    v = m1.get('v')
    return v is not None and t in LONGV.get(v, '')


def _guess1(ml, p, accent):
    ts = [m['t'] for m in ml if m['kind'] != 'pau'][p[0]:p[0] + p[1]]
    return guess_phrases(ts, accent, split=False)[0][2]


def _smooth(x, k):
    """moving average (edge padded), applied twice (triangular kernel)"""
    if k <= 1: return list(x)
    for _ in range(2):
        h = k // 2; n = len(x); pad = [x[0]] * h + list(x) + [x[-1]] * h
        c = [0.0]
        for v in pad: c.append(c[-1] + v)
        x = [(c[i + k] - c[i]) / k for i in range(n)] if len(pad) >= k + n - 1 else x
    return x


def mora_levels(moras, phrases=None, accent='heiban', question=False, **kw):
    """analysis helper: per non-pause mora mean target level (st, before range fit), for validation against reference pitch"""
    P = dict(NORMAL); P.update(kw)
    ml = list(moras)
    if phrases is None: phrases = guess_phrases(ml, accent)
    lv = _targets(ml, phrases, P, question)
    return [(l[0] + l[1]) / 2 for l in lv if l is not None]


if __name__ == '__main__':
    import sys, kotoba as R
    txt = sys.argv[1] if len(sys.argv) > 1 else "おはよう0、きょ'うも いっしょに0 がんばろ'うね"
    kana, phr = annotate(txt)
    r = R.tracks_from_kana(kana)
    f0 = f0_rule(r['moras'], r['n'], r['voiced'], phrases=phr, **CUTE)
    print(kana, phr)
    for m in r['moras']:
        i = int((m['b'] + m['e']) / 2 * 200); print(m['t'], round(f0[i]))
