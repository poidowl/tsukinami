/**
 * hodoki/soroi.mjs — Hodoki（音声汎用デコーダー）第1モジュール「揃い／不揃い」観察（観察のみ・フィルターなし）
 *
 * import ゼロの純粋 ES Module（ブラウザでも Node でも動く）。外部ライブラリ・学習済み重みなし。
 * ファイル入出力は CLI 側 (hodoki.mjs) に置く。
 *
 * 4本の線を時間に沿って測る：
 *   ① ジッター   … 隣り合う周期の「長さ」の揺れ   |T[i+1]-T[i]| / mean(T)   (%)
 *   ② シマー     … 隣り合う周期の「強さ」の揺れ   |20log10(A[i+1]/A[i])| (dB) と |ΔA|/mean(A) (%)
 *   ③ 非整数倍度 … 実測した倍音ピークが f0 の整数倍からどれだけずれているか (cents)
 *   ④ HNR        … 倍音とノイズのパワー比（Boersma 1993 の窓補正つき正規化自己相関）(dB)
 *
 * 周期の切り出し（エポック打ち）：
 *   フレーム自己相関で f0 の目安を出し、有声区間ごとに「いまの1周期」と「1周期先」を
 *   波形照合（正規化相互相関＋放物線補間）して次の周期頭へ1歩ずつ進む。
 */

// ---------------------------------------------------------------------------
// WAV 読み込み（PCM 16/24/32bit・float32、複数chは平均してモノラル化）
// ---------------------------------------------------------------------------
export function readWav(bytes) {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  const tag = (o) => String.fromCharCode(u8[o], u8[o + 1], u8[o + 2], u8[o + 3]);
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") throw new Error("not a RIFF/WAVE file");
  let off = 12, fmt = null, data = null;
  while (off + 8 <= u8.length) {
    const id = tag(off), sz = dv.getUint32(off + 4, true);
    if (id === "fmt ") {
      fmt = {
        format: dv.getUint16(off + 8, true), ch: dv.getUint16(off + 10, true),
        sr: dv.getUint32(off + 12, true), bits: dv.getUint16(off + 22, true),
      };
      if (fmt.format === 0xfffe && sz >= 40) fmt.format = dv.getUint16(off + 32, true);
    } else if (id === "data") {
      data = { off: off + 8, len: Math.min(sz, u8.length - off - 8) };
    }
    off += 8 + sz + (sz & 1);
  }
  if (!fmt || !data) throw new Error("missing fmt/data chunk");
  const bps = fmt.bits / 8, n = Math.floor(data.len / (bps * fmt.ch));
  const x = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let c = 0; c < fmt.ch; c++) {
      const o = data.off + (i * fmt.ch + c) * bps;
      let v;
      if (fmt.format === 3 && fmt.bits === 32) v = dv.getFloat32(o, true);
      else if (fmt.bits === 16) v = dv.getInt16(o, true) / 32768;
      else if (fmt.bits === 24) { let t = u8[o] | (u8[o + 1] << 8) | (u8[o + 2] << 16); if (t & 0x800000) t -= 0x1000000; v = t / 8388608; }
      else if (fmt.bits === 32) v = dv.getInt32(o, true) / 2147483648;
      else if (fmt.bits === 8) v = (u8[o] - 128) / 128;
      else throw new Error(`unsupported bits ${fmt.bits}`);
      s += v;
    }
    x[i] = s / fmt.ch;
  }
  return { sr: fmt.sr, x, channels: fmt.ch };
}

// ---------------------------------------------------------------------------
// 自前 FFT（radix-2, in-place, 複素）
// ---------------------------------------------------------------------------
const PLAN = new Map();
function plan(n) {
  let p = PLAN.get(n);
  if (p) return p;
  const bits = Math.round(Math.log2(n));
  if (1 << bits !== n) throw new Error("FFT size must be power of 2");
  const rev = new Uint32Array(n);
  for (let i = 0; i < n; i++) { let r = 0, v = i; for (let b = 0; b < bits; b++) { r = (r << 1) | (v & 1); v >>= 1; } rev[i] = r; }
  const cos = new Float64Array(n / 2), sin = new Float64Array(n / 2);
  for (let k = 0; k < n / 2; k++) { cos[k] = Math.cos((2 * Math.PI * k) / n); sin[k] = -Math.sin((2 * Math.PI * k) / n); }
  p = { rev, cos, sin };
  PLAN.set(n, p);
  return p;
}
export function fft(re, im) {
  const n = re.length, { rev, cos, sin } = plan(n);
  for (let i = 0; i < n; i++) {
    const j = rev[i];
    if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
  }
  for (let size = 2; size <= n; size <<= 1) {
    const half = size >> 1, step = n / size;
    for (let s = 0; s < n; s += size) {
      for (let k = 0; k < half; k++) {
        const wr = cos[k * step], wi = sin[k * step];
        const a = s + k, b = a + half;
        const vr = re[b] * wr - im[b] * wi, vi = re[b] * wi + im[b] * wr;
        re[b] = re[a] - vr; im[b] = im[a] - vi;
        re[a] += vr; im[a] += vi;
      }
    }
  }
}

const hann = (n) => { const w = new Float64Array(n); for (let i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * (i + 0.5)) / n); return w; };
const nextPow2 = (n) => { let p = 1; while (p < n) p <<= 1; return p; };
function parabola(ym1, y0, yp1) {
  const d = ym1 - 2 * y0 + yp1;
  if (d === 0) return { dx: 0, y: y0 };
  let dx = (0.5 * (ym1 - yp1)) / d;
  if (dx > 0.5) dx = 0.5; else if (dx < -0.5) dx = -0.5;
  return { dx, y: y0 - 0.25 * (ym1 - yp1) * dx };
}
function median(a) {
  if (!a.length) return NaN;
  const s = Float64Array.from(a).sort();
  const m = s.length >> 1;
  return s.length & 1 ? s[m] : 0.5 * (s[m - 1] + s[m]);
}
const mean = (a) => (a.length ? a.reduce((s, v) => s + v, 0) / a.length : NaN);

// ---------------------------------------------------------------------------
// ① フレーム解析：f0 ＋ HNR（窓補正つき正規化自己相関 r' → HNR = 10log10(r'/(1-r'))）
// ---------------------------------------------------------------------------
function frameTrack(x, sr, o) {
  const W = Math.round((o.periodsPerWindow / o.minF0) * sr);
  const nfft = nextPow2(2 * W);
  const win = hann(W);
  // 窓そのものの自己相関（補正用）
  const wr = new Float64Array(nfft), wi = new Float64Array(nfft);
  for (let i = 0; i < W; i++) wr[i] = win[i];
  fft(wr, wi);
  for (let k = 0; k < nfft; k++) { wr[k] = wr[k] * wr[k] + wi[k] * wi[k]; wi[k] = 0; }
  fft(wr, wi);
  const rw = new Float64Array(W);
  for (let t = 0; t < W; t++) rw[t] = wr[t] / wr[0];

  let gmax = 0;
  for (let i = 0; i < x.length; i++) gmax = Math.max(gmax, Math.abs(x[i]));
  const hop = Math.round(o.hopMs * 1e-3 * sr);
  const minLag = Math.floor(sr / o.maxF0), maxLag = Math.min(Math.ceil(sr / o.minF0), Math.floor(W / 2));
  const frames = [];
  const re = new Float64Array(nfft), im = new Float64Array(nfft);
  for (let c = Math.floor(W / 2); c + Math.ceil(W / 2) <= x.length; c += hop) {
    const s0 = c - Math.floor(W / 2);
    let m = 0, peak = 0;
    for (let i = 0; i < W; i++) { m += x[s0 + i]; peak = Math.max(peak, Math.abs(x[s0 + i])); }
    m /= W;
    re.fill(0); im.fill(0);
    let e = 0;
    for (let i = 0; i < W; i++) { const v = (x[s0 + i] - m) * win[i]; re[i] = v; e += v * v; }
    const fr = { t: c / sr, f0: 0, r: 0, hnr: NaN, voiced: false, rmsDb: 10 * Math.log10(e / W + 1e-20) };
    if (e > 0 && peak > gmax * o.silenceRel) {
      fft(re, im);
      for (let k = 0; k < nfft; k++) { re[k] = re[k] * re[k] + im[k] * im[k]; im[k] = 0; }
      fft(re, im);
      const r0 = re[0];
      const rn = (t) => (re[t] / r0) / rw[t];
      // 局所最大を全部拾い、最大値の 0.9 倍以上ある中で最も短い遅れを採る（オクターブ下の取り違え防止）
      const peaks = [];
      let gR = -1;
      for (let t = minLag + 1; t < maxLag; t++) {
        const v = rn(t);
        if (v > rn(t - 1) && v >= rn(t + 1)) { peaks.push(t); if (v > gR) gR = v; }
      }
      let best = -1;
      for (const t of peaks) if (rn(t) >= 0.9 * gR) { best = t; break; }
      // 後段の「連なり中央値への寄せ直し」用に候補（遅れ・高さ・f0）を残す
      fr.cands = peaks.filter((t) => rn(t) >= 0.5 * gR).map((t) => { const q = parabola(rn(t - 1), rn(t), rn(t + 1)); return { f0: sr / (t + q.dx), r: Math.min(q.y, 0.999999) }; });
      if (best > 0) {
        const p = parabola(rn(best - 1), rn(best), rn(best + 1));
        const r = Math.min(p.y, 0.999999);
        fr.r = r;
        fr.f0 = sr / (best + p.dx);
        if (r >= o.voicingThreshold) {
          fr.voiced = true;
          fr.hnr = 10 * Math.log10(Math.max(r, 1e-6) / (1 - r));
        }
      }
    }
    frames.push(fr);
  }
  // 有声の連なりごとに f0 中央値を取り、そこから 1.6 倍以上外れたフレームは中央値に一番近い候補へ寄せ直す（跳び跳ね防止）
  for (let i = 0; i < frames.length;) {
    if (!frames[i].voiced) { i++; continue; }
    let j = i;
    while (j < frames.length && frames[j].voiced) j++;
    const md = median(frames.slice(i, j).map((f) => f.f0));
    for (let k = i; k < j; k++) {
      const f = frames[k];
      if (Math.abs(Math.log(f.f0 / md)) > Math.log(1.6) && f.cands && f.cands.length) {
        let c = f.cands[0];
        for (const q of f.cands) if (Math.abs(Math.log(q.f0 / md)) < Math.abs(Math.log(c.f0 / md))) c = q;
        if (Math.abs(Math.log(c.f0 / md)) < Math.log(1.6)) { f.f0 = c.f0; f.r = c.r; f.hnr = 10 * Math.log10(Math.max(c.r, 1e-6) / (1 - c.r)); }
      }
    }
    i = j;
  }
  frames.forEach((f) => { delete f.cands; });
  // 5点メディアンで f0 を滑らかに（有声フレームのみ）
  const f0m = frames.map((f, i) => {
    if (!f.voiced) return 0;
    const nb = [];
    for (let j = i - 2; j <= i + 2; j++) if (frames[j] && frames[j].voiced) nb.push(frames[j].f0);
    return median(nb);
  });
  frames.forEach((f, i) => { f.f0s = f0m[i]; });
  // 2フレーム未満の孤立有声は捨てる
  for (let i = 0; i < frames.length; i++) {
    if (frames[i].voiced && !(frames[i - 1] && frames[i - 1].voiced) && !(frames[i + 1] && frames[i + 1].voiced)) {
      frames[i].voiced = false; frames[i].hnr = NaN; frames[i].f0s = 0;
    }
  }
  return { frames, W, hop };
}

// ---------------------------------------------------------------------------
// ② エポック打ち：波形照合で1周期ずつ進み、周期長 T[i] と強さ A[i]（周期内ピーク間振幅）を取る
// ---------------------------------------------------------------------------
function markPeriods(x, sr, frames, hop, o) {
  const f0At = (s) => {
    const i = Math.round((s / sr - frames[0].t) / (hop / sr));
    const f = frames[Math.max(0, Math.min(frames.length - 1, i))];
    return f && f.voiced ? f.f0s : 0;
  };
  const ncc = (a, b, L) => {
    let sab = 0, saa = 0, sbb = 0;
    for (let i = 0; i < L; i++) { const u = x[a + i], v = x[b + i]; sab += u * v; saa += u * u; sbb += v * v; }
    return saa > 0 && sbb > 0 ? sab / Math.sqrt(saa * sbb) : 0;
  };
  const periods = []; // {t0, T, A, cc, run}
  let run = 0, s = 0;
  while (s < x.length) {
    const f0 = f0At(s);
    if (!f0) { s += Math.round(sr * 0.002); continue; }
    // 有声の入口：最初の1周期のなかで絶対値最大の点を周期頭にそろえる
    let T0 = sr / f0;
    let st = s, mx = 0;
    for (let i = s; i < Math.min(x.length, s + T0); i++) if (Math.abs(x[i]) > mx) { mx = Math.abs(x[i]); st = i; }
    let t = st;
    run++;
    let chain = 0;
    while (true) {
      const f = f0At(t);
      if (!f) break;
      T0 = sr / f;
      const L = Math.round(T0);
      const lo = Math.floor(T0 * (1 - o.maxPeriodDev)), hi = Math.ceil(T0 * (1 + o.maxPeriodDev));
      const ti = Math.round(t);
      if (ti + hi + L + 1 >= x.length) break;
      let best = -1, bestC = -2;
      const cs = new Float64Array(hi - lo + 3);
      for (let lag = lo - 1; lag <= hi + 1; lag++) {
        const c = ncc(ti, ti + lag, L);
        cs[lag - lo + 1] = c;
      }
      for (let lag = lo; lag <= hi; lag++) {
        const c = cs[lag - lo + 1];
        if (c > bestC && c >= cs[lag - lo] && c >= cs[lag - lo + 2]) { bestC = c; best = lag; }
      }
      if (best < 0 || bestC < o.minPeriodCorr) break;
      const p = parabola(cs[best - lo], cs[best - lo + 1], cs[best - lo + 2]);
      const T = best + p.dx;
      // 強さ A：周期頭（＝最大振幅点にそろえた位置）を中央にした1周期窓のピーク間振幅（放物線補間で格子ずれを消す）
      const a0 = Math.max(1, Math.round(t - T / 2)), a1 = Math.min(x.length - 2, Math.round(t + T / 2));
      let imax = a0, imin = a0;
      for (let i = a0; i < a1; i++) { if (x[i] > x[imax]) imax = i; if (x[i] < x[imin]) imin = i; }
      const A = parabola(x[imax - 1], x[imax], x[imax + 1]).y - parabola(x[imin - 1], x[imin], x[imin + 1]).y;
      periods.push({ t0: t / sr, T: T / sr, A, cc: bestC, run });
      t += T;
      chain++;
    }
    s = Math.max(Math.round(t) + 1, s + 1);
    // 途切れた後は少し先から入り直す
    if (chain === 0) s += Math.round(T0);
  }
  return periods;
}

// 隣接ペア（同じ連なり・長さ比 ≤ maxPeriodFactor）のジッター/シマー
function pairMetrics(periods, o) {
  const pairs = [];
  for (let i = 0; i + 1 < periods.length; i++) {
    const a = periods[i], b = periods[i + 1];
    if (a.run !== b.run) continue;
    const ratio = Math.max(a.T, b.T) / Math.min(a.T, b.T);
    if (ratio > o.maxPeriodFactor) continue;
    if (!(a.A > 0 && b.A > 0)) continue;
    pairs.push({
      t: b.t0,
      dT: Math.abs(b.T - a.T), Tm: 0.5 * (a.T + b.T),
      dA: Math.abs(b.A - a.A), Am: 0.5 * (a.A + b.A),
      dDb: Math.abs(20 * Math.log10(b.A / a.A)),
    });
  }
  return pairs;
}

// ---------------------------------------------------------------------------
// ③ 非整数倍度：倍音ピークの実測周波数と「最もよく合う f0*」の整数倍とのずれ
// ---------------------------------------------------------------------------
function inharmonicity(x, sr, frames, o) {
  const W = nextPow2(Math.round(o.inhWinMs * 1e-3 * sr));
  const nfft = W * o.inhZeroPad;
  const win = hann(W);
  const re = new Float64Array(nfft), im = new Float64Array(nfft);
  const db = new Float64Array(nfft / 2 + 1);
  const binHz = sr / nfft;
  for (const f of frames) {
    f.inh = NaN; f.harm = null;
    if (!f.voiced || !f.f0s) continue;
    const c = Math.round(f.t * sr), s0 = c - W / 2;
    if (s0 < 0 || s0 + W > x.length) continue;
    re.fill(0); im.fill(0);
    for (let i = 0; i < W; i++) re[i] = x[s0 + i] * win[i];
    fft(re, im);
    let top = -Infinity;
    for (let k = 0; k <= nfft / 2; k++) { db[k] = 10 * Math.log10(re[k] * re[k] + im[k] * im[k] + 1e-30); if (db[k] > top) top = db[k]; }
    const f0 = f.f0s;
    const K = Math.min(o.inhMaxHarm, Math.floor(o.inhMaxHz / f0));
    const hs = [];
    for (let h = 1; h <= K; h++) {
      const lo = Math.max(1, Math.floor(((h - o.inhSearch) * f0) / binHz)), hi = Math.min(nfft / 2 - 1, Math.ceil(((h + o.inhSearch) * f0) / binHz));
      let kb = lo;
      for (let k = lo; k <= hi; k++) if (db[k] > db[kb]) kb = k;
      if (kb === lo || kb === hi) continue; // 窓の端＝はっきりした山ではない
      // 山の際立ち：倍音間の谷（(h±0.5)f0 付近の中央値）より何 dB 上か
      const vlo = Math.max(1, Math.floor(((h - 0.5) * f0) / binHz)), vhi = Math.min(nfft / 2, Math.ceil(((h + 0.5) * f0) / binHz));
      const band = [];
      for (let k = vlo; k <= vhi; k++) band.push(db[k]);
      const floor = median(band);
      if (db[kb] - floor < o.inhMinProm || db[kb] < top - o.inhMinRel) continue;
      const p = parabola(db[kb - 1], db[kb], db[kb + 1]);
      hs.push({ h, f: (kb + p.dx) * binHz, w: Math.pow(10, p.y / 20) });
    }
    if (hs.length < o.inhMinHarm) continue;
    // 重み付き最小二乗で f0* = Σ w h f / Σ w h²
    let num = 0, den = 0;
    for (const q of hs) { num += q.w * q.h * q.f; den += q.w * q.h * q.h; }
    const f0s = num / den;
    let sw = 0, sd = 0;
    for (const q of hs) {
      q.cents = 1200 * Math.log2(q.f / (q.h * f0s));
      sw += q.w; sd += q.w * Math.abs(q.cents);
    }
    f.inh = sd / sw;
    f.harm = hs.map((q) => [q.h, +q.cents.toFixed(2)]);
  }
}

export const DEFAULTS = {
  minF0: 75, maxF0: 800, periodsPerWindow: 3, hopMs: 10,
  voicingThreshold: 0.45, silenceRel: 0.03,
  maxPeriodDev: 0.25, minPeriodCorr: 0.5, maxPeriodFactor: 1.3,
  inhWinMs: 46, inhZeroPad: 8, inhMaxHarm: 16, inhMaxHz: 5000, inhSearch: 0.2,
  inhMinProm: 6, inhMinRel: 60, inhMinHarm: 3,
};

export function analyze(x, sr, opts = {}) {
  const o = { ...DEFAULTS, ...opts };
  const { frames, hop } = frameTrack(x, sr, o);
  const periods = markPeriods(x, sr, frames, hop, o);
  const pairs = pairMetrics(periods, o);
  inharmonicity(x, sr, frames, o);
  const vf = frames.filter((f) => f.voiced);
  const summary = {
    duration_s: x.length / sr,
    voiced_s: (vf.length * hop) / sr,
    f0_median_hz: median(vf.map((f) => f.f0s)),
    periods: periods.length,
    pairs: pairs.length,
    jitter_local_pct: pairs.length ? (100 * mean(pairs.map((p) => p.dT))) / mean(periods.map((p) => p.T)) : NaN,
    // 滑らかな高さの動き（イントネーションの下降など）を差し引いたジッター：|T[i] − (T[i−1]+T[i+1])/2| / 平均周期
    jitter_detrended_pct: (() => { const d = []; for (let i = 1; i + 1 < periods.length; i++) { const a = periods[i - 1], b = periods[i], c = periods[i + 1]; if (a.run !== b.run || b.run !== c.run) continue; const mx = Math.max(a.T, b.T, c.T), mn = Math.min(a.T, b.T, c.T); if (mx / mn > o.maxPeriodFactor) continue; d.push(Math.abs(b.T - 0.5 * (a.T + c.T))); } return d.length ? (100 * mean(d)) / mean(periods.map((p) => p.T)) : NaN; })(),
    jitter_abs_us: pairs.length ? 1e6 * mean(pairs.map((p) => p.dT)) : NaN,
    shimmer_local_pct: pairs.length ? (100 * mean(pairs.map((p) => p.dA))) / mean(periods.map((p) => p.A)) : NaN,
    shimmer_local_db: pairs.length ? mean(pairs.map((p) => p.dDb)) : NaN,
    hnr_db: mean(vf.map((f) => f.hnr).filter(Number.isFinite)),
    inharm_cents: mean(frames.map((f) => f.inh).filter(Number.isFinite)),
    inharm_frames: frames.filter((f) => Number.isFinite(f.inh)).length,
    period_corr_median: median(periods.map((p) => p.cc)),
  };
  return { sr, n: x.length, options: o, frames, periods, pairs, summary };
}

// ---------------------------------------------------------------------------
// HTML レポート（インライン SVG・自己完結）
// ---------------------------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fx = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : "—");

function movingMedian(ts, vs, tGrid, halfWin) {
  const out = [];
  let a = 0, b = 0;
  for (const t of tGrid) {
    while (a < ts.length && ts[a] < t - halfWin) a++;
    while (b < ts.length && ts[b] <= t + halfWin) b++;
    out.push(b - a >= 3 ? median(vs.slice(a, b)) : NaN);
  }
  return out;
}

export function renderHtml(res, meta = {}) {
  const Wpx = 1180, padL = 70, padR = 20, plotW = Wpx - padL - padR;
  const dur = res.n / res.sr;
  const X = (t) => padL + (t / dur) * plotW;
  const S = res.summary;
  const lanes = [];
  let y = 0;
  const lane = (title, unit, h, lo, hi, body, ticks) => {
    const Y = (v) => y + h - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * h;
    let g = `<g><rect x="${padL}" y="${y}" width="${plotW}" height="${h}" fill="#fbfbf8" stroke="#ccc"/>`;
    for (const tv of ticks || [lo, hi]) g += `<line x1="${padL}" x2="${padL + plotW}" y1="${Y(tv).toFixed(1)}" y2="${Y(tv).toFixed(1)}" stroke="#e6e6e0"/><text x="${padL - 6}" y="${(Y(tv) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#777">${tv}</text>`;
    g += `<text x="${padL + 6}" y="${y + 14}" font-size="12" font-weight="bold" fill="#333">${esc(title)} <tspan font-weight="normal" fill="#888">(${esc(unit)})</tspan></text>`;
    g += body(Y);
    g += `</g>`;
    lanes.push(g);
    y += h + 14;
  };
  const voicedSpans = (hh) => {
    let s = "", st = null;
    const fr = res.frames, hopS = fr.length > 1 ? fr[1].t - fr[0].t : 0.01;
    fr.forEach((f, i) => {
      if (f.voiced && st === null) st = f.t - hopS / 2;
      if ((!f.voiced || i === fr.length - 1) && st !== null) {
        s += `<rect x="${X(st).toFixed(1)}" y="0" width="${(X(f.t) - X(st)).toFixed(1)}" height="${hh}" fill="#f5b041" opacity="0.10"/>`;
        st = null;
      }
    });
    return s;
  };
  const poly = (pts, color, w = 1.4) => {
    let d = "", pen = false;
    for (const [t, v] of pts) {
      if (!Number.isFinite(v)) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(t).toFixed(1)},${v.toFixed(1)}`;
      pen = true;
    }
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${w}"/>`;
  };
  const dots = (pts, color, r = 1.3) => pts.filter(([, v]) => Number.isFinite(v)).map(([t, v]) => `<circle cx="${X(t).toFixed(1)}" cy="${v.toFixed(1)}" r="${r}" fill="${color}" opacity="0.45"/>`).join("");
  const grid = Array.from({ length: 600 }, (_, i) => ((i + 0.5) / 600) * dur);

  // 波形（ピクセルごとの min/max）
  lane("波形", "振幅", 90, -1, 1, (Y) => {
    const cols = plotW, per = res.n / cols;
    let d = "";
    for (let c = 0; c < cols; c++) {
      let mn = 0, mx = 0;
      for (let i = Math.floor(c * per); i < Math.floor((c + 1) * per); i++) { const v = res.x[i]; if (v < mn) mn = v; if (v > mx) mx = v; }
      d += `M${padL + c + 0.5},${Y(mx).toFixed(1)}V${Y(mn).toFixed(1)}`;
    }
    return `<path d="${d}" stroke="#4a6fa5" stroke-width="1"/>`;
  }, [-1, 0, 1]);
  const vf = res.frames.filter((f) => f.voiced);
  const f0s = vf.map((f) => f.f0s);
  const f0lo = Math.max(0, Math.floor((Math.min(...f0s, 1e9) * 0.85) / 50) * 50), f0hi = Math.ceil((Math.max(...f0s, 0) * 1.1) / 50) * 50 || 500;
  lane("f0（基本周波数）", "Hz", 90, f0lo, f0hi, (Y) => poly(res.frames.map((f) => [f.t, f.voiced ? Y(f.f0s) : NaN]), "#2a7a2a", 1.6), [f0lo, Math.round((f0lo + f0hi) / 2), f0hi]);

  const pt = res.pairs.map((p) => p.t);
  const jit = res.pairs.map((p) => (100 * p.dT) / p.Tm);
  const jhi = Math.max(1, Math.ceil(Math.min(20, (median(jit) || 0.5) * 4)));
  lane("① ジッター：隣の周期との長さのずれ", "%  点=1周期, 線=±25ms中央値", 110, 0, jhi, (Y) =>
    dots(pt.map((t, i) => [t, Y(jit[i])]), "#c0392b") + poly(grid.map((t, i) => [t, ((v) => (Number.isFinite(v) ? Y(v) : NaN))(movingMedian(pt, jit, grid, 0.025)[i])]), "#7b1d12", 1.8),
    [0, +(jhi / 2).toFixed(2), jhi]);
  const shm = res.pairs.map((p) => p.dDb);
  const shi = Math.max(0.5, Math.ceil(Math.min(10, (median(shm) || 0.2) * 4) * 2) / 2);
  lane("② シマー：隣の周期との強さのずれ", "dB  点=1周期, 線=±25ms中央値", 110, 0, shi, (Y) =>
    dots(pt.map((t, i) => [t, Y(shm[i])]), "#8e44ad") + poly(grid.map((t, i) => [t, ((v) => (Number.isFinite(v) ? Y(v) : NaN))(movingMedian(pt, shm, grid, 0.025)[i])]), "#4a1d5e", 1.8),
    [0, +(shi / 2).toFixed(2), shi]);
  const inhs = res.frames.map((f) => f.inh).filter(Number.isFinite);
  const ihi = Math.max(5, Math.ceil((Math.max(...inhs, 0) * 1.05) / 5) * 5);
  lane("③ 非整数倍度：倍音が f0 の整数倍からずれる量", "cents（振幅重み付き平均|ずれ|）", 100, 0, ihi, (Y) =>
    poly(res.frames.map((f) => [f.t, Number.isFinite(f.inh) ? Y(f.inh) : NaN]), "#d35400", 1.6), [0, ihi / 2, ihi]);
  // 倍音ごとのずれ（符号つき）のヒートマップ
  const Kmax = Math.max(1, ...res.frames.filter((f) => f.harm).map((f) => Math.max(...f.harm.map((h) => h[0]))));
  lane("③' 倍音ごとのずれ（青=低い / 赤=高い）", `下から 1..${Kmax} 次, ±25 cents で色飽和`, Math.max(60, Kmax * 6), 0.5, Kmax + 0.5, (Y) => {
    let s = "";
    const hopS = res.frames.length > 1 ? res.frames[1].t - res.frames[0].t : 0.01;
    const wpx = Math.max(1, (hopS / dur) * plotW);
    for (const f of res.frames) {
      if (!f.harm) continue;
      for (const [h, c] of f.harm) {
        const a = Math.max(-1, Math.min(1, c / 25));
        const col = a >= 0 ? `rgb(255,${Math.round(255 * (1 - a))},${Math.round(255 * (1 - a))})` : `rgb(${Math.round(255 * (1 + a))},${Math.round(255 * (1 + a))},255)`;
        s += `<rect x="${(X(f.t) - wpx / 2).toFixed(1)}" y="${(Y(h + 0.5)).toFixed(1)}" width="${wpx.toFixed(1)}" height="${(Y(h - 0.5) - Y(h + 0.5)).toFixed(1)}" fill="${col}"/>`;
      }
    }
    return s;
  }, [1, Kmax]);
  lane("④ HNR：倍音とノイズの比", "dB（高いほど揃い）", 100, -5, 40, (Y) =>
    poly(res.frames.map((f) => [f.t, Number.isFinite(f.hnr) ? Y(f.hnr) : NaN]), "#16a085", 1.6), [0, 10, 20, 30, 40]);

  // 時間軸
  let axis = "";
  const step = dur > 6 ? 1 : dur > 2 ? 0.5 : 0.1;
  for (let t = 0; t <= dur + 1e-9; t += step) axis += `<line x1="${X(t).toFixed(1)}" x2="${X(t).toFixed(1)}" y1="0" y2="${y - 14}" stroke="#000" stroke-opacity="0.06"/><text x="${X(t).toFixed(1)}" y="${y + 2}" text-anchor="middle" font-size="10" fill="#666">${t.toFixed(1)}s</text>`;
  const H = y + 16;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${Wpx}" height="${H}" viewBox="0 0 ${Wpx} ${H}" font-family="sans-serif">${lanes.join("")}<g pointer-events="none">${voicedSpans(H - 16)}</g>${axis}</svg>`;

  const rows = [
    ["有声時間 / 全長", `${fx(S.voiced_s)} s / ${fx(S.duration_s)} s`],
    ["f0 中央値", `${fx(S.f0_median_hz, 1)} Hz`],
    ["切り出した周期 / 隣接ペア", `${S.periods} / ${S.pairs}`],
    ["① ジッター (local)", `${fx(S.jitter_local_pct, 3)} %  （絶対 ${fx(S.jitter_abs_us, 1)} µs）`],
    ["① ジッター（高さの滑らかな動きを除く）", `${fx(S.jitter_detrended_pct, 3)} %  （|T[i]−(T[i−1]+T[i+1])/2|）`],
    ["② シマー (local)", `${fx(S.shimmer_local_pct, 2)} %  /  ${fx(S.shimmer_local_db, 3)} dB`],
    ["③ 非整数倍度", `${fx(S.inharm_cents, 2)} cents  （${S.inharm_frames} フレーム）`],
    ["④ HNR 平均", `${fx(S.hnr_db, 2)} dB`],
    ["周期照合の相関（中央値）", fx(S.period_corr_median, 3)],
  ];
  const metaRows = Object.entries(meta).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("");
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>Hodoki 揃い観察 — ${esc(meta["入力"] || "")}</title>
<style>body{font-family:sans-serif;margin:18px;color:#222;max-width:1200px}table{border-collapse:collapse;margin:8px 0 14px}th,td{border:1px solid #ddd;padding:4px 10px;font-size:13px;text-align:left}th{background:#f3f3ee;font-weight:normal;color:#555}h1{font-size:18px;margin:0 0 6px}p.n{font-size:12px;color:#666;line-height:1.6}</style></head><body>
<h1>Hodoki — 音声汎用デコーダー ／ 第1モジュール：揃い・不揃い（soroi）</h1>
<table>${metaRows}</table>
<table>${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td><b>${esc(v)}</b></td></tr>`).join("")}</table>
${svg}
<p class="n">黄色の帯＝有声と判定したフレーム。① ジッター＝|T[i+1]−T[i]|／平均周期、② シマー＝|20·log10(A[i+1]/A[i])|（A＝周期内のピーク間振幅）。周期は波形照合（正規化相互相関＋放物線補間）で1周期ずつ切り出し、長さ比が ${res.options.maxPeriodFactor} を超えるペアは除外。③ 非整数倍度＝各フレーム（${res.options.inhWinMs} ms Hann, ×${res.options.inhZeroPad} ゼロ詰め）の倍音ピーク周波数を放物線補間で出し、重み付き最小二乗で最もよく合う f0* を求め、h·f0* からのずれを cents で振幅重み付き平均。④ HNR＝Boersma (1993) 式の窓補正つき正規化自己相関 r から 10·log10(r/(1−r))。ニューラル重み・外部ライブラリなし。</p>
</body></html>`;
}
