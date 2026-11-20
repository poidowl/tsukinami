/**
 * hodoki/michi.mjs — Hodoki 第2モジュール「声の道（michi）」＋ 話し手像カード
 *
 * import は同じ hodoki/ 内の soroi.mjs だけ（ブラウザでも Node でも動く）。外部ライブラリ・学習済み重みなし。
 *
 *   - 自前 LPC：2分の1間引き（44.1k→22.05k, 窓つき sinc FIR）→ プリエンファシス（固定 50 Hz＋窓ごとの適応1次）→ Hamming 窓 → 自己相関 → Levinson-Durbin（18 次）
 *   - 根の計算：Durand–Kerner 法で A(z) の根 → 周波数・帯域幅 → 帯域幅で選別して F1..F4
 *   - 高い声への手当て：「倍音包絡 LPC」（henv）。f0 の倍音ピークだけを拾って包絡を線形補間し、
 *     その包絡のパワースペクトルから自己相関を作って同じ Levinson にかける。既定は henv、通常 LPC（plain）も並べて出す。
 *   - 声道長：一様管 F_i = (2i−1)c/(4L) への原点通過最小二乗（主）と、分散法 ΔF=(F4−F1)/3, L=c/(2ΔF)（副）。c = 35000 cm/s
 *   - H1−H2（未補正）と H1*−H2*（Iseli & Alwan 2004 式で F1,F2 の影響を補正）、H1−A1, H1−A3（未補正）
 *   - 話し手像カード：発話内のフレーム推定を「中央値・四分位範囲・中央値のブートストラップ 90% 区間」の幅で集計
 */
import { analyze as soroiAnalyze, fft } from "./soroi.mjs";

export const C_CM_S = 35000;
const TAU = 2 * Math.PI;

// ---------------------------------------------------------------- 小道具
const nextPow2 = (n) => { let p = 1; while (p < n) p <<= 1; return p; };
function quantile(a, q) {
  const s = Float64Array.from(a.filter(Number.isFinite)).sort();
  if (!s.length) return NaN;
  const p = (s.length - 1) * q, i = Math.floor(p), f = p - i;
  return i + 1 < s.length ? s[i] * (1 - f) + s[i + 1] * f : s[i];
}
const median = (a) => quantile(a, 0.5);
function rngMulberry(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
/** 中央値・IQR・中央値のブートストラップ 90% 区間 */
export function rangeOf(vals, nBoot = 400, seed = 7) {
  const v = vals.filter(Number.isFinite);
  if (!v.length) return { n: 0, med: NaN, q1: NaN, q3: NaN, lo: NaN, hi: NaN };
  const r = rngMulberry(seed), meds = [];
  for (let b = 0; b < nBoot; b++) { const s = new Array(v.length); for (let i = 0; i < v.length; i++) s[i] = v[Math.floor(r() * v.length)]; meds.push(median(s)); }
  return { n: v.length, med: median(v), q1: quantile(v, 0.25), q3: quantile(v, 0.75), lo: quantile(meds, 0.05), hi: quantile(meds, 0.95) };
}
function parabola(ym1, y0, yp1) {
  const d = ym1 - 2 * y0 + yp1;
  if (d === 0) return { dx: 0, y: y0 };
  let dx = (0.5 * (ym1 - yp1)) / d; dx = Math.max(-0.5, Math.min(0.5, dx));
  return { dx, y: y0 - 0.25 * (ym1 - yp1) * dx };
}

// ---------------------------------------------------------------- 間引き
export function decimate(x, D) {
  const taps = 24 * D + 1, h = new Float64Array(taps), fc = 0.45 / D, mid = (taps - 1) / 2;
  let s = 0;
  for (let i = 0; i < taps; i++) {
    const k = i - mid, sinc = k === 0 ? 2 * fc : Math.sin(TAU * fc * k) / (Math.PI * k);
    h[i] = sinc * (0.42 - 0.5 * Math.cos((TAU * i) / (taps - 1)) + 0.08 * Math.cos((2 * TAU * i) / (taps - 1)));
    s += h[i];
  }
  for (let i = 0; i < taps; i++) h[i] /= s;
  const m = Math.floor(x.length / D), y = new Float64Array(m);
  for (let j = 0; j < m; j++) {
    const c = j * D; let acc = 0;
    for (let i = 0; i < taps; i++) { const n = c + i - mid; if (n >= 0 && n < x.length) acc += h[i] * x[n]; }
    y[j] = acc;
  }
  return y;
}

// ---------------------------------------------------------------- LPC
export function levinson(r, p) {
  const a = new Float64Array(p + 1); a[0] = 1;
  let e = r[0];
  if (!(e > 0)) return { a, e: 0 };
  const tmp = new Float64Array(p + 1);
  for (let i = 1; i <= p; i++) {
    let acc = r[i];
    for (let j = 1; j < i; j++) acc += a[j] * r[i - j];
    const k = -acc / e;
    tmp.set(a);
    for (let j = 1; j < i; j++) a[j] = tmp[j] + k * tmp[i - j];
    a[i] = k;
    e *= 1 - k * k;
    if (e <= 0) break;
  }
  return { a, e };
}
/** z^p + a1 z^{p-1} + ... + ap の根（Durand–Kerner） */
export function polyRoots(a) {
  const p = a.length - 1;
  const re = new Float64Array(p), im = new Float64Array(p);
  for (let k = 0; k < p; k++) { const ang = (TAU * k) / p + 0.4; re[k] = 0.9 * Math.cos(ang); im[k] = 0.9 * Math.sin(ang); }
  const evalP = (zr, zi) => { let vr = 1, vi = 0; for (let k = 1; k <= p; k++) { const nr = vr * zr - vi * zi + a[k], ni = vr * zi + vi * zr; vr = nr; vi = ni; } return [vr, vi]; };
  for (let it = 0; it < 800; it++) {
    let delta = 0;
    for (let k = 0; k < p; k++) {
      const [nr, ni] = evalP(re[k], im[k]);
      let dr = 1, di = 0;
      for (let j = 0; j < p; j++) if (j !== k) { const xr = re[k] - re[j], xi = im[k] - im[j]; const tr = dr * xr - di * xi; di = dr * xi + di * xr; dr = tr; }
      const den = dr * dr + di * di || 1e-30;
      const qr = (nr * dr + ni * di) / den, qi = (ni * dr - nr * di) / den;
      re[k] -= qr; im[k] -= qi;
      delta = Math.max(delta, Math.abs(qr) + Math.abs(qi));
    }
    if (delta < 1e-12) break;
  }
  return Array.from({ length: p }, (_, k) => [re[k], im[k]]);
}
/** LPC 係数 → 共鳴候補 {f, bw}（上半面の根のみ、周波数順） */
export function lpcResonances(a, fs) {
  return polyRoots(a)
    .filter(([, i]) => i > 0)
    .map(([r, i]) => { const mag = Math.hypot(r, i); return { f: (Math.atan2(i, r) * fs) / TAU, bw: (-Math.log(Math.max(mag, 1e-9)) * fs) / Math.PI }; })
    .sort((x, y) => x.f - y.f);
}
function pickFormants(cands, fs, o) {
  const ok = cands.filter((c) => c.f > o.fMin && c.f < fs / 2 - 150 && c.bw > 0 && c.bw < o.bwMax);
  return ok.slice(0, 4);
}

// ---------------------------------------------------------------- 倍音
function harmonicPeaks(db, binHz, f0, fMax) {
  const out = [];
  for (let h = 1; h * f0 < fMax; h++) {
    const lo = Math.max(1, Math.floor(((h - 0.25) * f0) / binHz)), hi = Math.min(db.length - 2, Math.ceil(((h + 0.25) * f0) / binHz));
    let kb = lo;
    for (let k = lo; k <= hi; k++) if (db[k] > db[kb]) kb = k;
    const p = parabola(db[kb - 1], db[kb], db[kb + 1]);
    out.push({ h, f: (kb + p.dx) * binHz, db: p.y });
  }
  return out;
}
/** Iseli & Alwan (2004)：周波数 f の倍音が共鳴 (F, B) で持ち上がる量 (dB)。f=0 で 0 dB */
export function formantBoostDb(f, F, B, fs) {
  const r = Math.exp((-Math.PI * B) / fs), wi = (TAU * F) / fs, w = (TAU * f) / fs;
  const num = Math.pow(r * r + 1 - 2 * r * Math.cos(wi), 2);
  const den = (r * r + 1 - 2 * r * Math.cos(w + wi)) * (r * r + 1 - 2 * r * Math.cos(w - wi));
  return 10 * Math.log10(num / den);
}

export const MICHI_DEFAULTS = {
  decim: 2, orders: [18], maxOrder: 18, adaptivePre: true, winMs: 25, preEmphHz: 50, fMin: 90, bwMax: 600,
  specWin: 2048, specPad: 4, henvNfft: 1024, method: "henv", autoHz: 250,
  minFormants: 4,
};

/**
 * x: Float64Array, sr: サンプルレート。soroi を内部で回して f0・有声・HNR を共有する。
 * 返り値 { frames: [{t, f0, plain:{F,B}, henv:{F,B}, use, vtl, vtlDisp, h1h2, h1h2c, h1a1, h1a3}], soroi, card, ltas }
 */
export function analyzeMichi(x, sr, opts = {}) {
  const o = { ...MICHI_DEFAULTS, ...opts };
  const so = soroiAnalyze(x, sr, opts.soroi || {});
  const fsD = sr / o.decim;
  const xd = decimate(x, o.decim);
  // プリエンファシス（1次差分, α = exp(−2π·preEmphHz/fs)）
  const al = Math.exp((-TAU * o.preEmphHz) / fsD);
  const xe = new Float64Array(xd.length);
  for (let i = 1; i < xd.length; i++) xe[i] = xd[i] - al * xd[i - 1];
  const W = Math.round((o.winMs / 1000) * fsD);
  const ham = new Float64Array(W);
  for (let i = 0; i < W; i++) ham[i] = 0.54 - 0.46 * Math.cos((TAU * i) / (W - 1));
  // 倍音スペクトル用（44.1k のまま）
  const SW = o.specWin, SN = SW * o.specPad, sbin = sr / SN;
  const hann = new Float64Array(SW);
  for (let i = 0; i < SW; i++) hann[i] = 0.5 - 0.5 * Math.cos((TAU * (i + 0.5)) / SW);
  const sre = new Float64Array(SN), sim = new Float64Array(SN), sdb = new Float64Array(SN / 2 + 1);
  const ltas = new Float64Array(SN / 2 + 1); let ltasN = 0;
  // henv 用
  const HN = o.henvNfft, hre = new Float64Array(HN), him = new Float64Array(HN);

  const frames = [];
  for (const f of so.frames) {
    if (!f.voiced || !(f.f0s > 0)) continue;
    const fr = { t: f.t, f0: f.f0s, hnr: f.hnr };
    // --- plain LPC
    const c = Math.round(f.t * fsD), s0 = c - (W >> 1);
    if (s0 < 1 || s0 + W >= xe.length) continue;
    // 適応プリエンファシス：固定 50 Hz の後に残る傾きを、その窓の 1 次 LPC 係数 k=r1/r0 でもう一度ならす
    let r0 = 0, r1 = 0;
    for (let i = 1; i < W; i++) { r0 += xe[s0 + i] * xe[s0 + i]; r1 += xe[s0 + i] * xe[s0 + i - 1]; }
    const ka = o.adaptivePre ? Math.max(0, Math.min(0.98, r1 / (r0 || 1))) : 0;
    const seg = new Float64Array(W);
    for (let i = 0; i < W; i++) seg[i] = (xe[s0 + i] - ka * xe[s0 + i - 1]) * ham[i];
    const rr = new Float64Array(o.maxOrder + 1);
    for (let k = 0; k <= o.maxOrder; k++) { let s = 0; for (let i = k; i < W; i++) s += seg[i] * seg[i - k]; rr[k] = s; }
    rr[0] *= 1 + 1e-9;
    fr.plainBy = {};
    for (const p of o.orders) {
      const pf = pickFormants(lpcResonances(levinson(rr, p).a, fsD), fsD, o);
      fr.plainBy[p] = { F: pf.map((q) => q.f), B: pf.map((q) => q.bw) };
    }
    // --- 倍音スペクトル（H1, H2, A1, A3 と henv）
    const cs = Math.round(f.t * sr) - SW / 2;
    if (cs >= 0 && cs + SW <= x.length) {
      sre.fill(0); sim.fill(0);
      for (let i = 0; i < SW; i++) sre[i] = x[cs + i] * hann[i];
      fft(sre, sim);
      for (let k = 0; k <= SN / 2; k++) { const pw = sre[k] * sre[k] + sim[k] * sim[k]; sdb[k] = 10 * Math.log10(pw + 1e-30); ltas[k] += pw; }
      ltasN++;
      const hp = harmonicPeaks(sdb, sbin, fr.f0, fsD / 2);
      fr.harm = hp;
      if (hp.length >= 2) {
        // 倍音包絡：倍音ピーク (dB) を周波数で線形補間 → パワー → プリエンファシス → 自己相関
        const kmax = HN / 2;
        for (let k = 0; k <= kmax; k++) {
          const fq = (k * fsD) / HN;
          let d;
          if (fq <= hp[0].f) d = hp[0].db;
          else if (fq >= hp[hp.length - 1].f) d = hp[hp.length - 1].db;
          else { let j = 0; while (hp[j + 1].f < fq) j++; const u = (fq - hp[j].f) / (hp[j + 1].f - hp[j].f); d = hp[j].db * (1 - u) + hp[j + 1].db * u; }
          const w = (TAU * fq) / fsD;
          const pe = 1 + al * al - 2 * al * Math.cos(w);
          hre[k] = Math.pow(10, d / 10) * pe; him[k] = 0;
          if (k > 0 && k < kmax) { hre[HN - k] = hre[k]; him[HN - k] = 0; }
        }
        fft(hre, him);
        const rh = new Float64Array(o.maxOrder + 2);
        for (let k = 0; k <= o.maxOrder + 1; k++) rh[k] = hre[k] / HN;
        // 適応プリエンファシス相当：1 次の傾きを Levinson 1 段で除いた残差の自己相関に置き換える
        if (o.adaptivePre) {
          const k1 = Math.max(0, Math.min(0.98, rh[1] / rh[0]));
          const r2 = new Float64Array(o.maxOrder + 2);
          for (let k = 0; k <= o.maxOrder; k++) r2[k] = (1 + k1 * k1) * rh[k] - k1 * (rh[Math.abs(k - 1)] + rh[k + 1]);
          rh.set(r2);
        }
        rh[0] *= 1 + 1e-6;
        fr.henvBy = {};
        for (const p of o.orders) {
          const hf = pickFormants(lpcResonances(levinson(rh, p).a, fsD), fsD, o);
          fr.henvBy[p] = { F: hf.map((q) => q.f), B: hf.map((q) => q.bw) };
        }
      }
    }
    frames.push(fr);
  }
  // --- 方式と次数の選択。方式：auto は f0 < autoHz なら plain、それ以上は henv。
  // 次数：発話全体で「4本そろったフレームの割合」×「F1..F4 の相対ばらつき（IQR/中央値）の小ささ」が最もよい次数を採る
  const methodOf = (fr) => (o.method === "auto" ? (fr.f0 < o.autoHz ? "plain" : "henv") : o.method);
  let bestP = o.orders[0], bestScore = -Infinity; const orderScores = {};
  for (const p of o.orders) {
    const got = frames.map((fr) => { const by = fr[methodOf(fr) + "By"]; return by && by[p] && by[p].F.length >= 4 ? by[p].F : null; });
    const okN = got.filter(Boolean).length;
    if (!okN) { orderScores[p] = 0; continue; }
    let spread = 0;
    for (let i = 0; i < 4; i++) { const v = got.filter(Boolean).map((F) => F[i]); spread += (quantile(v, 0.75) - quantile(v, 0.25)) / median(v); }
    const score = okN / frames.length - spread / 4;
    orderScores[p] = +score.toFixed(3);
    if (score > bestScore) { bestScore = score; bestP = p; }
  }
  for (const fr of frames) {
    const m = methodOf(fr);
    fr.method = m;
    fr.plain = fr.plainBy && fr.plainBy[bestP]; fr.henv = fr.henvBy && fr.henvBy[bestP];
    const use = fr[m] && fr[m].F.length >= o.minFormants ? fr[m] : null;
    if (use) {
      fr.F = use.F; fr.B = use.B;
      let num = 0, den = 0;
      for (let i = 0; i < 4; i++) { const k = 2 * i + 1; num += k * use.F[i]; den += k * k; }
      fr.vtl = (C_CM_S * den) / (4 * num);
      fr.vtlDisp = C_CM_S / (2 * ((use.F[3] - use.F[0]) / 3));
    }
    if (fr.harm && fr.harm.length >= 2) {
      const H1 = fr.harm[0].db, H2 = fr.harm[1].db;
      fr.h1h2 = H1 - H2;
      if (use) {
        let c1 = 0, c2 = 0;
        for (let i = 0; i < 2; i++) {
          const B = Math.max(40, Math.min(500, use.B[i]));
          c1 += formantBoostDb(fr.f0, use.F[i], B, sr);
          c2 += formantBoostDb(2 * fr.f0, use.F[i], B, sr);
        }
        fr.h1h2c = H1 - c1 - (H2 - c2);
        const near = (F) => { let best = null; for (const q of fr.harm) if (Math.abs(q.f - F) <= 0.2 * F && (!best || q.db > best.db)) best = q; return best; };
        const A1 = near(use.F[0]), A3 = near(use.F[2]);
        if (A1) fr.h1a1 = H1 - A1.db;
        if (A3) fr.h1a3 = H1 - A3.db;
      }
    }
    delete fr.harm; delete fr.plainBy; delete fr.henvBy;
  }
  // 長時間平均スペクトル（有声）の帯域比
  const band = (a, b) => { let s = 0; for (let k = Math.floor(a / sbin); k <= Math.min(ltas.length - 1, Math.ceil(b / sbin)); k++) s += ltas[k]; return s; };
  const lt = ltasN ? { lo_mid_db: 10 * Math.log10(band(50, 1000) / band(1000, 4000)), hi_db: 10 * Math.log10(band(4000, 8000) / band(50, 4000)) } : { lo_mid_db: NaN, hi_db: NaN };
  const rate = speechRate(x, sr, so);
  const card = speakerCard(frames, so, lt, rate);
  card.lpc_order = bestP; card.order_scores = orderScores;
  return { sr, n: x.length, options: o, soroi: so, frames, ltas: lt, rate, card };
}

/** 話速：有声フレーム上の強度ピーク（周囲より 2 dB 以上、間隔 ≥ 90 ms）＝音節核の数 / 発話区間 */
export function speechRate(x, sr, so) {
  const fr = so.frames;
  if (!fr.length) return { nuclei: 0, span_s: 0, per_s: NaN };
  const hopS = fr.length > 1 ? fr[1].t - fr[0].t : 0.01;
  const db = fr.map((f) => f.rmsDb);
  const sm = db.map((_, i) => { let s = 0, c = 0; for (let j = i - 2; j <= i + 2; j++) if (j >= 0 && j < db.length) { s += db[j]; c++; } return s / c; });
  const peaks = [];
  const minGap = Math.round(0.09 / hopS);
  for (let i = 1; i + 1 < sm.length; i++) {
    if (!fr[i].voiced || !(sm[i] >= sm[i - 1] && sm[i] > sm[i + 1])) continue;
    let lmin = sm[i], rmin = sm[i];
    for (let j = i - 1; j >= 0 && j >= i - 15; j--) { lmin = Math.min(lmin, sm[j]); if (sm[j] > sm[i]) break; }
    for (let j = i + 1; j < sm.length && j <= i + 15; j++) { rmin = Math.min(rmin, sm[j]); if (sm[j] > sm[i]) break; }
    if (sm[i] - Math.max(lmin, rmin) < 2) continue;
    if (peaks.length && i - peaks[peaks.length - 1] < minGap) { if (sm[i] > sm[peaks[peaks.length - 1]]) peaks[peaks.length - 1] = i; continue; }
    peaks.push(i);
  }
  const vi = fr.map((f, i) => (f.voiced ? i : -1)).filter((i) => i >= 0);
  const span = vi.length ? (vi[vi.length - 1] - vi[0] + 1) * hopS : 0;
  return { nuclei: peaks.length, span_s: span, per_s: span > 0 ? peaks.length / span : NaN, peaks_t: peaks.map((i) => fr[i].t) };
}

export function speakerCard(frames, so, lt, rate) {
  const g = (k) => frames.map((f) => f[k]);
  const F = (i) => frames.map((f) => (f.F ? f.F[i] : NaN));
  const f0 = g("f0");
  const st = (a, b) => 12 * Math.log2(b / a);
  const p10 = quantile(f0, 0.1), p90 = quantile(f0, 0.9);
  const S = so.summary;
  return {
    vtl_cm: rangeOf(g("vtl")),
    vtl_disp_cm: rangeOf(g("vtlDisp")),
    F1: rangeOf(F(0)), F2: rangeOf(F(1)), F3: rangeOf(F(2)), F4: rangeOf(F(3)),
    f0_hz: { ...rangeOf(f0), p10, p90, span_st: st(p10, p90) },
    h1h2_db: rangeOf(g("h1h2")),
    h1h2c_db: rangeOf(g("h1h2c")),
    h1a1_db: rangeOf(g("h1a1")),
    h1a3_db: rangeOf(g("h1a3")),
    hnr_db: rangeOf(frames.map((f) => f.hnr)),
    jitter_pct: S.jitter_local_pct, jitter_detrended_pct: S.jitter_detrended_pct,
    shimmer_db: S.shimmer_local_db, shimmer_pct: S.shimmer_local_pct, inharm_cents: S.inharm_cents,
    ltas_lo_mid_db: lt.lo_mid_db, ltas_hi_db: lt.hi_db,
    rate_nuclei_per_s: rate.per_s, nuclei: rate.nuclei, span_s: rate.span_s,
    voiced_s: S.voiced_s, duration_s: S.duration_s,
    frames_used: frames.filter((f) => Number.isFinite(f.vtl)).length, frames_voiced: frames.length,
    method_counts: frames.reduce((m, f) => ((m[f.method] = (m[f.method] || 0) + 1), m), {}),
    high_f0_flag: median(f0) >= 250,
  };
}

/** 逆算・相関調べ用の数値特徴（1発話 → 平坦なオブジェクト） */
export function featureVector(res) {
  const c = res.card;
  return {
    f0_med: c.f0_hz.med, f0_p10: c.f0_hz.p10, f0_p90: c.f0_hz.p90, f0_span_st: c.f0_hz.span_st,
    F1: c.F1.med, F2: c.F2.med, F3: c.F3.med, F4: c.F4.med, vtl: c.vtl_cm.med, vtl_disp: c.vtl_disp_cm.med,
    h1h2: c.h1h2_db.med, h1h2c: c.h1h2c_db.med, h1a1: c.h1a1_db.med, h1a3: c.h1a3_db.med, hnr: c.hnr_db.med,
    jitter: c.jitter_pct, jitter_detr: c.jitter_detrended_pct, shimmer_db: c.shimmer_db, inharm: c.inharm_cents,
    ltas_lo_mid: c.ltas_lo_mid_db, ltas_hi: c.ltas_hi_db, rate: c.rate_nuclei_per_s, voiced_s: c.voiced_s, dur: c.duration_s,
    voiced_frac: c.voiced_s / c.duration_s,
  };
}

// ---------------------------------------------------------------- HTML（話し手像カード＋声道レーン）
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
const fx = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : "—");
const rg = (r, d = 1, u = "") => `${fx(r.med, d)}${u}　IQR ${fx(r.q1, d)}–${fx(r.q3, d)}　中央値90%区間 ${fx(r.lo, d)}–${fx(r.hi, d)}　(n=${r.n})`;

export function renderMichiHtml(res, x, meta = {}, extra = "") {
  const c = res.card, sr = res.sr, dur = res.n / sr;
  // スペクトログラム（0–7 kHz）を Uint8 にして埋め込み、canvas で描く
  const hop = 0.01, NW = 1024, NB = 256, fMax = 7000;
  const cols = Math.floor(dur / hop), spec = new Uint8Array(cols * NB);
  const re = new Float64Array(NW), im = new Float64Array(NW);
  const win = new Float64Array(NW); for (let i = 0; i < NW; i++) win[i] = 0.5 - 0.5 * Math.cos((TAU * (i + 0.5)) / NW);
  let top = -Infinity; const tmp = new Float64Array(cols * NB);
  for (let cI = 0; cI < cols; cI++) {
    const s0 = Math.round(cI * hop * sr) - NW / 2;
    re.fill(0); im.fill(0);
    for (let i = 0; i < NW; i++) { const j = s0 + i; if (j >= 0 && j < x.length) re[i] = (x[j] - (j > 0 ? 0.95 * x[j - 1] : 0)) * win[i]; }
    fft(re, im);
    for (let b = 0; b < NB; b++) { const k = Math.round(((b + 0.5) / NB) * fMax / (sr / NW)); const v = 10 * Math.log10(re[k] * re[k] + im[k] * im[k] + 1e-20); tmp[cI * NB + b] = v; if (v > top) top = v; }
  }
  for (let i = 0; i < tmp.length; i++) spec[i] = Math.max(0, Math.min(255, Math.round(((tmp[i] - (top - 70)) / 70) * 255)));
  let b64 = ""; { let s = ""; for (let i = 0; i < spec.length; i++) s += String.fromCharCode(spec[i]); b64 = typeof btoa === "function" ? btoa(s) : Buffer.from(spec).toString("base64"); }
  const fr = res.frames.map((f) => [+f.t.toFixed(3), f.F ? f.F.map((v) => Math.round(v)) : null, f.plain && f.plain.F.length ? f.plain.F.map((v) => Math.round(v)) : null, +f.f0.toFixed(1), Number.isFinite(f.vtl) ? +f.vtl.toFixed(2) : null, Number.isFinite(f.h1h2) ? +f.h1h2.toFixed(2) : null, Number.isFinite(f.h1h2c) ? +f.h1h2c.toFixed(2) : null]);
  const rows = [
    ["声道長 VTL（一様管あてはめ）", rg(c.vtl_cm, 2, " cm")],
    ["声道長（分散法 ΔF）", rg(c.vtl_disp_cm, 2, " cm")],
    ["F1 / F2 / F3 / F4 中央値", `${fx(c.F1.med, 0)} / ${fx(c.F2.med, 0)} / ${fx(c.F3.med, 0)} / ${fx(c.F4.med, 0)} Hz`],
    ["f0 帯", `中央値 ${fx(c.f0_hz.med, 1)} Hz　10–90% ${fx(c.f0_hz.p10, 1)}–${fx(c.f0_hz.p90, 1)} Hz（幅 ${fx(c.f0_hz.span_st, 1)} 半音）`],
    ["H1−H2（未補正）", rg(c.h1h2_db, 2, " dB")],
    ["H1*−H2*（F1,F2 補正）", rg(c.h1h2c_db, 2, " dB")],
    ["H1−A1 / H1−A3（未補正）", `${fx(c.h1a1_db.med, 2)} / ${fx(c.h1a3_db.med, 2)} dB`],
    ["HNR（フレーム）", rg(c.hnr_db, 2, " dB")],
    ["揃い（soroi）", `ジッター ${fx(c.jitter_pct, 3)} %（傾き除去 ${fx(c.jitter_detrended_pct, 3)} %）／ シマー ${fx(c.shimmer_db, 3)} dB（${fx(c.shimmer_pct, 2)} %）／ 非整数倍度 ${fx(c.inharm_cents, 2)} cents`],
    ["長時間平均スペクトル", `0.05–1k / 1–4k = ${fx(c.ltas_lo_mid_db, 2)} dB　4–8k / 0–4k = ${fx(c.ltas_hi_db, 2)} dB`],
    ["話速（音節核）", `${fx(c.rate_nuclei_per_s, 2)} 個/s（${c.nuclei} 個 / ${fx(c.span_s, 2)} s）`],
    ["使ったフレーム", `${c.frames_used} / 有声 ${c.frames_voiced}　方式 ${JSON.stringify(c.method_counts)}`],
    ["高い声フラグ", c.high_f0_flag ? "f0 中央値 ≥ 250 Hz：フォルマント（特に F1）は倍音に引かれやすい。偏りの大きさは hodoki/test_michi.mjs の一様管表を参照" : "f0 中央値 < 250 Hz（通常 LPC）"],
  ];
  const metaRows = Object.entries(meta).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>Hodoki 話し手像 — ${esc(meta["入力"] || "")}</title>
<style>body{font-family:sans-serif;margin:18px;color:#222;max-width:1200px}table{border-collapse:collapse;margin:8px 0 14px}th,td{border:1px solid #ddd;padding:4px 10px;font-size:13px;text-align:left}th{background:#f3f3ee;font-weight:normal;color:#555}h1{font-size:18px;margin:0 0 6px}h2{font-size:15px;margin:14px 0 4px}p.n{font-size:12px;color:#666;line-height:1.6}canvas{display:block;margin:4px 0}</style></head><body>
<h1>Hodoki — 音声汎用デコーダー ／ 第2モジュール：声の道（michi）と話し手像カード</h1>
<table>${metaRows}</table>
<h2>話し手像カード（物理の手がかりだけ・すべて幅つき）</h2>
<table>${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td><b>${esc(v)}</b></td></tr>`).join("")}</table>
<h2>スペクトログラム＋フォルマント（●採用方式 / ×通常LPC）・f0</h2>
<canvas id="sp" width="1180" height="300"></canvas>
<canvas id="ln" width="1180" height="260"></canvas>
<script>
(function(){
const cols=${cols},NB=${NB},fMax=${fMax},dur=${dur.toFixed(4)},hop=${hop};
const raw=atob("${b64}");const fr=${JSON.stringify(fr)};
const cv=document.getElementById("sp"),g=cv.getContext("2d"),W=cv.width,H=cv.height,L=50,R=10,pw=W-L-R;
const X=t=>L+t/dur*pw, Yf=f=>H-20-(f/fMax)*(H-30);
const img=g.createImageData(pw,H-30);
for(let px=0;px<pw;px++){const c=Math.min(cols-1,Math.floor(px/pw*cols));for(let py=0;py<H-30;py++){const b=Math.min(NB-1,Math.floor((1-py/(H-30))*NB));const v=255-raw.charCodeAt(c*NB+b);const o=(py*pw+px)*4;img.data[o]=v;img.data[o+1]=v;img.data[o+2]=v;img.data[o+3]=255;}}
g.putImageData(img,L,10);
g.font="10px sans-serif";g.fillStyle="#555";for(let f=0;f<=fMax;f+=1000){g.fillText(f/1000+"k",8,Yf(f)+3);}
const col=["#e74c3c","#27ae60","#2980b9","#8e44ad"];
for(const r of fr){if(r[2])r[2].forEach((f,i)=>{g.strokeStyle=col[i];g.globalAlpha=0.5;const x=X(r[0]),y=Yf(f);g.beginPath();g.moveTo(x-2,y-2);g.lineTo(x+2,y+2);g.moveTo(x+2,y-2);g.lineTo(x-2,y+2);g.stroke();});
 g.globalAlpha=1;if(r[1])r[1].forEach((f,i)=>{g.fillStyle=col[i];g.beginPath();g.arc(X(r[0]),Yf(f),2.2,0,7);g.fill();});
 g.fillStyle="#f39c12";g.fillRect(X(r[0])-1,Yf(r[3])-1,2,2);}
g.fillStyle="#333";for(let t=0;t<=dur;t+=0.5)g.fillText(t.toFixed(1)+"s",X(t)-8,H-5);
const c2=document.getElementById("ln"),h=c2.getContext("2d"),H2=c2.height;
function lane(y0,hh,lo,hi,idx,color,label){h.fillStyle="#fbfbf8";h.fillRect(L,y0,pw,hh);h.strokeStyle="#ccc";h.strokeRect(L,y0,pw,hh);h.fillStyle="#333";h.font="bold 12px sans-serif";h.fillText(label,L+6,y0+14);h.font="10px sans-serif";h.fillStyle="#777";h.fillText(hi,10,y0+10);h.fillText(lo,10,y0+hh);
 for(const r of fr){const v=r[idx];if(v==null)continue;const y=y0+hh-(Math.max(lo,Math.min(hi,v))-lo)/(hi-lo)*hh;h.fillStyle=color;h.fillRect(X(r[0])-1.2,y-1.2,2.4,2.4);}}
lane(5,115,8,24,4,"#16a085","声道長 VTL（cm、フレームごと）");
lane(135,115,-15,25,5,"#c0392b","H1−H2（赤=未補正 / 紫=F1,F2補正, dB）");
for(const r of fr){const v=r[6];if(v==null)continue;const y=135+115-(Math.max(-15,Math.min(25,v))+15)/40*115;h.fillStyle="#8e44ad";h.fillRect(X(r[0])-1,y-1,2,2);}
})();
</script>
<p class="n">VTL＝一様管 F_i=(2i−1)c/(4L)（i=1..4, c=35000 cm/s）への原点通過最小二乗。分散法＝c/(2·(F4−F1)/3)。LPC＝44.1→22.05 kHz 間引き・50 Hz プリエンファシス＋窓ごとの適応1次プリエンファシス・25 ms Hamming・18 次・Levinson-Durbin・Durand–Kerner 根、帯域幅 &lt; 600 Hz の共鳴を下から4本。既定は全フレームで倍音包絡 LPC（46 ms 窓の倍音ピークを線形補間した包絡のパワーから自己相関）、× は同じ次数の通常 LPC。次数 18 は草薙の真値つき合成で選んだ値（README 参照）。H1*−H2* は Iseli &amp; Alwan (2004) の式で LPC の F1,F2（帯域幅 40–500 Hz に制限）による持ち上がりを差し引いた値、H1−A1/H1−A3 は未補正。幅は「中央値・四分位範囲・中央値のブートストラップ 90% 区間（400 回）」。これは物理量の推定で、聞き手が思い浮かべる性別・年齢などの判定ではありません。</p>
${extra}
</body></html>`;
}
