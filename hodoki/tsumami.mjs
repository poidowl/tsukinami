/**
 * hodoki/tsumami.mjs — 草薙のつまみ（makeHitofude の引数）を Hodoki の特徴から当てられるか
 *
 *   1) study   : つまみを乱数で振った合成音を作り、特徴 → つまみ を自前リッジ回帰（一個抜き交差検証 R²）で当てる
 *   2) fisher  : ある設定のまわりで、つまみを少し動かしたときの特徴の動き（ヤコビアン）と、seed だけ変えたときの
 *                特徴の揺れから、局所的な「当てられる幅」（Cramér–Rao 風の ±σ）と、つまみ同士の取り違え（相関）を出す
 *   3) invert  : 合成による分析。目標音の特徴に近づくよう、別 seed の草薙で Nelder–Mead（自前）をかけ、
 *                距離が「seed 違いの揺れ」以内に入ったつまみの集まりを幅として返す
 * 外部ライブラリなし。草薙本体（../hitofude.mjs）を呼ぶだけ。
 */
import { makeHitofude } from "../hitofude.mjs";
import { analyzeMichi, featureVector } from "./michi.mjs";

export const TEXT = "わたし、にほんご、ちょっとしゃべれます";
// 調べるつまみ（名前は makeHitofude の引数そのまま）。shin は 0/1 で別経路に切り替わるので 1.0 に固定。seed は毎回乱数（邪魔もの）
export const KNOBS = [
  { k: "hz", lo: 110, hi: 420, log: true },
  { k: "fscale", lo: 0.85, hi: 1.32 },
  { k: "rate", lo: 1.10, hi: 1.40 },
  { k: "g_vo", lo: 0.60, hi: 0.96 },
  { k: "tilt_w", lo: 3, hi: 8, int: true },
  { k: "sigh", lo: 0.0, hi: 0.9 },
  { k: "jitter", lo: 0.0, hi: 0.008 },
  { k: "wander_st", lo: 0.0, hi: 0.25 },
  { k: "damp", lo: 0.0, hi: 0.4 },
  { k: "level_k", lo: 0.3, hi: 1.0 },
];
export const FEATS = ["f0_med", "f0_p10", "f0_p90", "f0_span_st", "F1", "F2", "F3", "F4", "vtl", "vtl_disp", "h1h2", "h1h2c", "h1a1", "h1a3", "hnr",
  "jitter", "jitter_detr", "shimmer_db", "inharm", "ltas_lo_mid", "ltas_hi", "rate", "voiced_s", "dur", "voiced_frac"];

export function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const toU = (kn, v) => (kn.log ? Math.log(v / kn.lo) / Math.log(kn.hi / kn.lo) : (v - kn.lo) / (kn.hi - kn.lo));
const fromU = (kn, u) => { u = Math.max(0, Math.min(1, u)); let v = kn.log ? kn.lo * Math.pow(kn.hi / kn.lo, u) : kn.lo + u * (kn.hi - kn.lo); return kn.int ? Math.round(v) : v; };

export function features(knobs, seed, text = TEXT) {
  const out = makeHitofude(text, { ...knobs, seed, shin: 1.0 });
  const x = Float64Array.from(out.samples);
  const fv = featureVector(analyzeMichi(x, 44100));
  return FEATS.map((f) => fv[f]);
}

// ---------------------------------------------------------------- 線形代数（小さい密行列）
function solve(A, b) { // ガウス消去（部分ピボット）。A: n×n 配列の配列, b: n
  const n = A.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    const d = M[c][c] || 1e-12;
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / d; if (f) for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  return M.map((r, i) => r[n] / (M[i][i] || 1e-12));
}
function inv(A) { const n = A.length; return A.map((_, j) => solve(A, A.map((__, i) => (i === j ? 1 : 0)))).reduce((R, col, j) => { col.forEach((v, i) => { R[i][j] = v; }); return R; }, A.map(() => new Array(n).fill(0))); }
const colStats = (X, raw = false) => X[0].map((_, j) => { const v = X.map((r) => r[j]).filter(Number.isFinite); const m = v.reduce((a, b) => a + b, 0) / v.length; const s = Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, v.length - 1)); return { m, s: raw ? s : s || 1 }; });

/** リッジ回帰の一個抜き（LOO）予測。X: n×p（標準化済み、切片列なし）, y: n */
export function ridgeLoo(X, y, lambda) {
  const n = X.length, p = X[0].length;
  const ym = y.reduce((a, b) => a + b, 0) / n;
  const A = Array.from({ length: p }, (_, i) => Array.from({ length: p }, (__, j) => X.reduce((s, r) => s + r[i] * r[j], 0) + (i === j ? lambda : 0)));
  const Ai = inv(A);
  const beta = Ai.map((row) => X.reduce((s, r, k) => s + row.reduce((t, a, j) => t + a * r[j], 0) * (y[k] - ym), 0));
  const pred = X.map((r) => ym + r.reduce((s, v, j) => s + v * beta[j], 0));
  const loo = X.map((r, i) => { const h = 1 / n + r.reduce((s, v, a) => s + v * Ai[a].reduce((t, w, b) => t + w * r[b], 0), 0); return y[i] - (y[i] - pred[i]) / (1 - h); });
  return { beta, ym, loo };
}
function spearman(a, b) {
  const rank = (v) => { const idx = v.map((x, i) => [x, i]).sort((p, q) => p[0] - q[0]); const r = new Array(v.length); idx.forEach(([, i], k) => { r[i] = k; }); return r; };
  const ra = rank(a), rb = rank(b), n = a.length, ma = (n - 1) / 2;
  let num = 0, da = 0, db = 0; for (let i = 0; i < n; i++) { num += (ra[i] - ma) * (rb[i] - ma); da += (ra[i] - ma) ** 2; db += (rb[i] - ma) ** 2; }
  return num / Math.sqrt(da * db);
}

/** 1) study：N 本のランダム設定 → つまみごとの LOO R²・RMSE・最も効く単独特徴 */
export function study(N = 60, seed0 = 1, log = () => {}) {
  const r = rng(seed0), rows = [];
  for (let i = 0; i < N; i++) {
    const knobs = Object.fromEntries(KNOBS.map((kn) => [kn.k, fromU(kn, r())]));
    const sd = 1 + Math.floor(r() * 1e6);
    rows.push({ knobs, seed: sd, f: features(knobs, sd) });
    log(i + 1, N);
  }
  return { rows, ...fitStudy(rows) };
}
export function fitStudy(rows) {
  const ok = rows.filter((r) => r.f.every(Number.isFinite));
  const st = colStats(ok.map((r) => r.f));
  const X = ok.map((r) => r.f.map((v, j) => (v - st[j].m) / st[j].s));
  const res = {};
  for (const kn of KNOBS) {
    const y = ok.map((r) => (kn.log ? Math.log(r.knobs[kn.k]) : r.knobs[kn.k]));
    const vy = y.reduce((a, b) => a + (b - y.reduce((s, t) => s + t, 0) / y.length) ** 2, 0);
    let best = null;
    for (const lam of [0.3, 1, 3, 10, 30]) {
      const { loo } = ridgeLoo(X, y, lam);
      const sse = loo.reduce((s, v, i) => s + (v - y[i]) ** 2, 0);
      const r2 = 1 - sse / vy;
      if (!best || r2 > best.r2) best = { lam, r2, loo };
    }
    const back = (v) => (kn.log ? Math.exp(v) : v);
    const rmse = Math.sqrt(best.loo.reduce((s, v, i) => s + (back(v) - back(y[i])) ** 2, 0) / y.length);
    const sp = FEATS.map((f, j) => [f, spearman(ok.map((r) => r.f[j]), y)]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    res[kn.k] = { r2_loo: best.r2, lambda: best.lam, rmse, range: [kn.lo, kn.hi], top: sp.slice(0, 3).map(([f, c]) => [f, +c.toFixed(3)]) };
  }
  return { n: ok.length, featStats: st, recover: res };
}

/** seed だけ変えたときの特徴の揺れ（標準偏差） */
export function seedNoise(knobs, seeds) {
  const F = seeds.map((s) => features(knobs, s));
  const st = colStats(F, true);
  return { F, sd: st.map((s) => s.s), mean: st.map((s) => s.m) };
}

/** 2) fisher：中心 knobs のまわりの局所識別。sd: 特徴の seed 揺れ, scale: 特徴の床（study の特徴 SD×0.02） */
export function fisher(knobs, sd, floor, seeds = [11, 12, 13]) {
  const J = []; // J[f][k] = d feature_f / d u_k（u=0..1 正規化つまみ）
  const du = 0.06;
  const cols = [];
  for (const kn of KNOBS) {
    const u0 = toU(kn, knobs[kn.k]);
    let ua = Math.max(0, u0 - du), ub = Math.min(1, u0 + du);
    if (kn.int) { const v0 = knobs[kn.k]; const va = Math.max(kn.lo, v0 - 1), vb = Math.min(kn.hi, v0 + 1); ua = toU(kn, va); ub = toU(kn, vb); }
    const d = seeds.map((s) => { const fa = features({ ...knobs, [kn.k]: fromU(kn, ua) }, s), fb = features({ ...knobs, [kn.k]: fromU(kn, ub) }, s); return fa.map((v, j) => (fb[j] - v) / (ub - ua)); });
    cols.push(FEATS.map((_, j) => d.reduce((a, r) => a + r[j], 0) / d.length));
  }
  for (let j = 0; j < FEATS.length; j++) J.push(cols.map((c) => c[j]));
  const w = FEATS.map((_, j) => 1 / Math.max(sd[j], floor[j]) ** 2);
  const K = KNOBS.length;
  const Fm = Array.from({ length: K }, (_, a) => Array.from({ length: K }, (__, b) => J.reduce((s, row, j) => (Number.isFinite(row[a] * row[b]) ? s + w[j] * row[a] * row[b] : s), 0) + (a === b ? 1e-6 : 0)));
  const C = inv(Fm);
  const sig = C.map((r, i) => Math.sqrt(Math.max(0, r[i])));
  const corr = C.map((r, i) => r.map((v, j) => v / (sig[i] * sig[j] || 1)));
  return {
    sigma_u: sig, corr, J,
    sigma: KNOBS.map((kn, i) => { const u0 = toU(kn, knobs[kn.k]); return [fromU(kn, u0 - 2 * sig[i]), fromU(kn, u0 + 2 * sig[i])]; }),
  };
}

/** Nelder–Mead（最小化, u∈[0,1]^d に切り詰め） */
export function nelderMead(f, x0, { step = 0.15, maxEval = 120, onEval = () => {} } = {}) {
  const d = x0.length, clamp = (x) => x.map((v) => Math.max(0, Math.min(1, v)));
  let nE = 0; const ev = (x) => { const c = clamp(x); const v = f(c); nE++; onEval(c, v); return v; };
  let S = [clamp(x0)];
  for (let i = 0; i < d; i++) { const x = x0.slice(); x[i] = x[i] + (x[i] > 0.5 ? -step : step); S.push(clamp(x)); }
  let V = S.map(ev);
  while (nE < maxEval) {
    const o = V.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]).map(([, i]) => i);
    S = o.map((i) => S[i]); V = o.map((i) => V[i]);
    const c = S[0].map((_, j) => S.slice(0, d).reduce((s, x) => s + x[j], 0) / d);
    const xr = c.map((v, j) => v + (v - S[d][j])), fr = ev(xr);
    if (fr < V[0]) { const xe = c.map((v, j) => v + 2 * (v - S[d][j])), fe = ev(xe); if (fe < fr) { S[d] = clamp(xe); V[d] = fe; } else { S[d] = clamp(xr); V[d] = fr; } }
    else if (fr < V[d - 1]) { S[d] = clamp(xr); V[d] = fr; }
    else {
      const xc = c.map((v, j) => v + 0.5 * (S[d][j] - v)), fc = ev(xc);
      if (fc < V[d]) { S[d] = clamp(xc); V[d] = fc; }
      else { for (let i = 1; i <= d; i++) { S[i] = clamp(S[i].map((v, j) => S[0][j] + 0.5 * (v - S[0][j]))); V[i] = ev(S[i]); } }
    }
  }
  const bi = V.indexOf(Math.min(...V));
  return { x: S[bi], v: V[bi], nEval: nE };
}

/** 3) invert：目標特徴 ft（seed 不明）→ つまみの幅。start: 回帰の予測など */
export function invert(ft, sd, floor, start, { seed = 777, maxEval = 120, tolMul = 1, tol = null, log = () => {} } = {}) {
  const w = FEATS.map((_, j) => 1 / Math.max(sd[j], floor[j]) ** 2);
  const dist = (f) => { let s = 0, c = 0; f.forEach((v, j) => { if (Number.isFinite(v) && Number.isFinite(ft[j])) { s += w[j] * (v - ft[j]) ** 2; c++; } }); return s / c; };
  const hist = [];
  const obj = (u) => { const knobs = Object.fromEntries(KNOBS.map((kn, i) => [kn.k, fromU(kn, u[i])])); const v = dist(features(knobs, seed)); hist.push({ knobs, v }); log(hist.length, v); return v; };
  const nm = nelderMead(obj, KNOBS.map((kn) => toU(kn, start[kn.k])), { maxEval });
  const vmin = Math.min(...hist.map((h) => h.v));
  const thr = vmin + (tol ?? 1) * tolMul;
  const acc = hist.filter((h) => h.v <= thr);
  const ranges = Object.fromEntries(KNOBS.map((kn) => { const v = acc.map((h) => h.knobs[kn.k]); return [kn.k, [Math.min(...v), Math.max(...v)]]; }));
  const best = hist.find((h) => h.v === vmin).knobs;
  return { best, vmin, thr, accepted: acc.length, evals: hist.length, ranges, dist };
}

/** 回帰でつまみの初期値を予測（study の結果を使う） */
export function predictKnobs(rowsFit, f) {
  const ok = rowsFit.rows.filter((r) => r.f.every(Number.isFinite));
  const st = rowsFit.featStats;
  const X = ok.map((r) => r.f.map((v, j) => (v - st[j].m) / st[j].s));
  const x = f.map((v, j) => (Number.isFinite(v) ? (v - st[j].m) / st[j].s : 0));
  return Object.fromEntries(KNOBS.map((kn) => {
    const y = ok.map((r) => (kn.log ? Math.log(r.knobs[kn.k]) : r.knobs[kn.k]));
    const { beta, ym } = ridgeLoo(X, y, rowsFit.recover[kn.k].lambda);
    const v = ym + x.reduce((s, xv, j) => s + xv * beta[j], 0);
    return [kn.k, fromU(kn, toU(kn, kn.log ? Math.exp(v) : v))];
  }));
}
export { toU, fromU };

/**
 * 当てたつまみ best のまわりの幅：
 *   (a) Fisher ±2σ（特徴の seed 揺れを独立とみなした局所線形の幅）
 *   (b) seed 再当て：best を別 seed で鳴らした特徴から、ヤコビアン1歩（ガウス・ニュートン）で当て直した値の min–max
 *       （seed 由来の「特徴どうしが一緒に揺れる」分も入る）
 * 返す幅は (a) と (b) の和集合。ft: 目標の特徴, floor: 特徴の床
 */
export function rangesAround(best, ft, floor, seeds = [201, 202, 203, 204, 205, 206, 207, 208, 209, 210]) {
  const sn = seedNoise(best, seeds);
  const w = FEATS.map((_, j) => 1 / Math.max(sn.sd[j], floor[j]) ** 2);
  const fi = fisher(best, sn.sd, floor);
  const K = KNOBS.length, J = fi.J;
  const Fm = Array.from({ length: K }, (_, a) => Array.from({ length: K }, (__, b) => J.reduce((t, row, j) => (Number.isFinite(row[a] * row[b]) ? t + w[j] * row[a] * row[b] : t), 0) + (a === b ? 1e-6 : 0)));
  const Ci = inv(Fm);
  const refit = sn.F.map((fs) => {
    const g = KNOBS.map((_, a) => J.reduce((t, row, j) => (Number.isFinite(row[a]) && Number.isFinite(ft[j]) && Number.isFinite(fs[j]) ? t + w[j] * row[a] * (ft[j] - fs[j]) : t), 0));
    return KNOBS.map((kn, a) => fromU(kn, toU(kn, best[kn.k]) + Ci[a].reduce((t, v, b) => t + v * g[b], 0)));
  });
  const out = {};
  KNOBS.forEach((kn, i) => {
    const v = refit.map((r) => r[i]), f = fi.sigma[i];
    const lo = Math.min(f[0], ...v), hi = Math.max(f[1], ...v);
    out[kn.k] = {
      best: best[kn.k], fisher: f, refit: [Math.min(...v), Math.max(...v)], range: [lo, hi], width_u: toU(kn, hi) - toU(kn, lo),
      confounded: fi.corr[i].map((c, j) => [KNOBS[j].k, c]).filter(([k, c]) => k !== kn.k && Math.abs(c) > 0.5).map(([k, c]) => [k, +c.toFixed(2)]),
    };
  });
  return out;
}

/** 目標の特徴 ft → { best, ranges }。study: fitStudy の結果（rows 込み） */
export function decodeKnobs(ft, studyRes, { maxEval = 150, log = () => {} } = {}) {
  const floor = studyRes.featStats.map((s) => 0.02 * s.s);
  const start = predictKnobs(studyRes, ft);
  const sn0 = seedNoise(start, [101, 102, 103, 104, 105, 106]);
  const r = invert(ft, sn0.sd, floor, start, { seed: 777, maxEval, tol: 0, log });
  return { start, best: r.best, vmin: r.vmin, evals: r.evals, ranges: rangesAround(r.best, ft, floor) };
}
