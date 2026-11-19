#!/usr/bin/env node
/**
 * kiku.mjs — 草薙ASR（聴く）
 * 外部ライブラリ 0 Byte・学習重み 0 Byte・FFT / sin / cos 不使用。
 * hitofude.mjs (kusanagi) の式をそのまま鏡写しにした「引き算と移動平均のノミ」だけで
 * 日本語の母音・子音を読み取る極小純JS ASR（Node.js / ブラウザ両対応）。
 *
 * 使い方 (Node.js):
 *   node kiku.mjs --say "アイウエオ"                      # hitofude.mjs の声を直接聴く
 *   node kiku.mjs --say "アイウエオ" --preset ossan       # おっさん声で試す
 *   node kiku.mjs --say "アイウエオ" --scope              # フレーム断面スコープ表示
 *   node kiku.mjs sample.wav [--scope]                   # WAVファイルを聴く
 */

// hitofude.mjs L103 の 5母音基準 VT (F1, F2) @ fscale=1.0 をそのまま逆引き（手調整なし）
export const KUSANAGI_VT = {
  a: [850.0, 1400.0],
  i: [330.0, 2750.0],
  u: [380.0, 1300.0],
  e: [520.0, 2350.0],
  o: [650.0, 1050.0],
};

// プローブ帯域：F1 (6本) + F2 (7本) + 高域摩擦 (3本) = 計 16 本
export const F1_BANDS = [260, 360, 480, 640, 850, 1080];
export const F2_BANDS = [900, 1150, 1450, 1850, 2350, 2950, 3600];
export const HI_BANDS = [3800, 4900, 6100];

const KANA = {
  ",a": "あ", ",i": "い", ",u": "う", ",e": "え", ",o": "お",
  "k,a": "か", "k,i": "き", "k,u": "く", "k,e": "け", "k,o": "こ",
  "s,a": "さ", "s,i": "し", "s,u": "す", "s,e": "せ", "s,o": "そ",
  "sh,a": "しゃ", "sh,i": "し", "sh,u": "しゅ", "sh,e": "しぇ", "sh,o": "しょ",
  "t,a": "た", "t,i": "ち", "t,u": "つ", "t,e": "て", "t,o": "と",
  "ch,a": "ちゃ", "ch,i": "ち", "ch,u": "ちゅ", "ch,e": "ちぇ", "ch,o": "ちょ",
  "ts,a": "つぁ", "ts,i": "つぃ", "ts,u": "つ", "ts,e": "つぇ", "ts,o": "つぉ",
  "n,a": "な", "n,i": "に", "n,u": "ぬ", "n,e": "ね", "n,o": "の",
  "h,a": "は", "h,i": "ひ", "h,u": "ふ", "h,e": "へ", "h,o": "ほ",
  "m,a": "ま", "m,i": "み", "m,u": "む", "m,e": "め", "m,o": "も",
  "y,a": "や", "y,i": "い", "y,u": "ゆ", "y,e": "え", "y,o": "よ",
  "r,a": "ら", "r,i": "り", "r,u": "る", "r,e": "れ", "r,o": "ろ",
  "w,a": "わ", "w,i": "い", "w,u": "う", "w,e": "え", "w,o": "お",
  "p,a": "ぱ", "p,i": "ぴ", "p,u": "ぷ", "p,e": "ぺ", "p,o": "ぽ",
};

// ---- 1. hitofude.mjs の鏡写しノミ群（引き算と移動平均だけ・sin/cos ゼロ） ----

/** 幅 w の移動平均（累積和 O(N)）。 */
export function heikin(x, w) {
  if (w <= 1) return x;
  const n = x.length;
  const cs = new Float64Array(n + 1);
  let s = 0.0;
  for (let i = 0; i < n; i++) {
    s += x[i];
    cs[i + 1] = s;
  }
  const h = w >> 1;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let a = i - h;
    let b = a + w;
    if (a < 0) a = 0;
    if (b > n) b = n;
    out[i] = (cs[b] - cs[a]) / (b - a);
  }
  return out;
}

/** 固定遅延 d のくびれ：y[i] = x[i] - g * y[i - d]（F = sr/(2d) の奇数倍を立てる）。 */
export function combC(x, d, g) {
  const n = x.length;
  const y = new Float64Array(n);
  const k = Math.trunc(d);
  const fr = d - k;
  const c0 = 1.0 - fr;
  const c1 = fr;
  for (let i = 0; i < n; i++) {
    const a = i - k;
    if (a >= 1) y[i] = x[i] - g * (y[a] * c0 + y[a - 1] * c1);
    else if (a === 0) y[i] = x[i] - g * y[0] * c0;
    else y[i] = x[i];
  }
  return y;
}

/** 定数帯域プローブ：2段くびれ ＋ 3F/5F 奇数倍音 exact-null 平均 ＋ 低域引き算。 */
export function yamaProbe(x, sr, freq, g = 0.70) {
  const f = freq / 0.95;
  const d = sr / (2.0 * f);
  let y = combC(combC(x, d, g), d, g);
  const w3 = Math.max(1, Math.round(sr / (3.0 * f)));
  const w5 = Math.max(1, Math.round(sr / (5.0 * f)));
  y = heikin(y, w3);
  y = heikin(y, w3);
  if (w5 >= 2) y = heikin(y, w5);
  const wHi = Math.max(2, Math.round((2.0 * sr) / f));
  for (let p = 0; p < 2; p++) {
    const lo = heikin(y, wHi);
    const next = new Float64Array(y.length);
    for (let i = 0; i < y.length; i++) next[i] = y[i] - lo[i];
    y = next;
  }
  const scale = ((1.0 - g) * (1.0 - g)) / 0.65;
  for (let i = 0; i < y.length; i++) y[i] *= scale;
  return y;
}

/** hitofude.mjs L1300 の唇放射 (yc[i] - 0.70*yc[i-1]) を打ち消す 1次リーキー積分。 */
export function deemph(x, a = 0.70) {
  const n = x.length;
  const y = new Float64Array(n);
  let s = 0.0;
  for (let i = 0; i < n; i++) {
    s = x[i] + a * s;
    y[i] = s;
  }
  return y;
}

/** 逆コム (AMDF)：|x[i] - x[i + D]| の最小の凹みから有声度と f0 を測る。 */
export function amdfVoicing(x, start, win, sr) {
  const dMin = Math.max(4, Math.trunc(sr / 520));
  const dMax = Math.min(win >> 1, Math.trunc(sr / 85));
  if (dMax <= dMin) return [0.0, 0.0];
  let meanAbs = 0.0;
  for (let i = 0; i < win; i++) meanAbs += Math.abs(x[start + i]);
  meanAbs /= win;
  if (meanAbs < 1e-6) return [0.0, 0.0];
  let bestD = dMin;
  let bestV = 1e9;
  for (let d = dMin; d <= dMax; d++) {
    let s = 0.0;
    const m = win - d;
    for (let i = 0; i < m; i++) {
      const diff = x[start + i] - x[start + i + d];
      s += diff >= 0.0 ? diff : -diff;
    }
    const val = s / (m * meanAbs);
    if (val < bestV) {
      bestV = val;
      bestD = d;
    }
  }
  const voicing = Math.max(0.0, Math.min(1.0, (1.15 - bestV) / 0.75));
  return [voicing, sr / bestD];
}

/** 帯域エネルギーの p 乗重み付き対数周波数重心。 */
export function bandPeak(freqs, energies, p = 4.0) {
  let s = 0.0;
  let mx = 0.0;
  let logSum = 0.0;
  for (let i = 0; i < freqs.length; i++) {
    const e = energies[i];
    if (e > mx) mx = e;
    const w = Math.pow(e, p);
    s += w;
    logSum += Math.log(freqs[i]) * w;
  }
  if (s <= 1e-18) return [freqs[freqs.length >> 1], 0.0];
  return [Math.exp(logSum / s), mx];
}

/** 整数比の粗削り平均ダウンサンプル（44100 -> 22050 = 2点平均）。 */
export function downsample(samples, sr, targetSr = 22050) {
  const step = Math.max(1, Math.round(sr / targetSr));
  if (step <= 1) return [Float64Array.from(samples), sr];
  const m = Math.floor(samples.length / step);
  const out = new Float64Array(m);
  for (let i = 0; i < m; i++) {
    let s = 0.0;
    const base = i * step;
    for (let k = 0; k < step; k++) s += samples[base + k];
    out[i] = s / step;
  }
  return [out, sr / step];
}

// ---- 2. フレーム解析 ----

export function analyze(samples, sr, opts = {}) {
  const hopMs = opts.hopMs ?? 10.0;
  const winMs = opts.winMs ?? 25.0;
  const [xs, sr2] = downsample(samples, sr, 22050);
  const n = xs.length;

  // DC除去（30ms移動平均の引き算）
  const dc = heikin(xs, Math.max(16, Math.trunc(sr2 * 0.03)));
  const x = new Float64Array(n);
  for (let i = 0; i < n; i++) x[i] = xs[i] - dc[i];

  // F1用: 唇放射を打ち消して低域F1を立てる（1次リーキー積分）
  const x1 = deemph(x, 0.85);
  // F2・高域用: 1サンプル引き算プリエンファシス
  const xp = new Float64Array(n);
  for (let i = 1; i < n; i++) xp[i] = x[i] - 0.95 * x[i - 1];

  const probed1 = F1_BANDS.map((f) => yamaProbe(x1, sr2, f));
  const probed2 = F2_BANDS.map((f) => yamaProbe(xp, sr2, f));
  const probedHi = HI_BANDS.map((f) => yamaProbe(xp, sr2, f));

  // 1サンプル引き算（高域のザラつき指標）
  const diff1 = new Float64Array(n);
  for (let i = 1; i < n; i++) diff1[i] = Math.abs(x[i] - x[i - 1]);

  const hop = Math.max(1, Math.round((sr2 * hopMs) / 1000.0));
  const win = Math.max(hop, Math.round((sr2 * winMs) / 1000.0));
  const frames = [];

  for (let start = 0; start + win <= n; start += hop) {
    let sq = 0.0, absSum = 0.0, d1Sum = 0.0;
    for (let i = 0; i < win; i++) {
      const v = x[start + i];
      sq += v * v;
      absSum += Math.abs(v);
      d1Sum += diff1[start + i];
    }
    const rms = Math.sqrt(sq / win);
    const d1 = d1Sum / (absSum + 1e-9);
    const [vo, f0] = rms > 1e-4 ? amdfVoicing(x, start, win, sr2) : [0.0, 0.0];

    const bandRms = (arr) => {
      let s = 0.0;
      for (let i = 0; i < win; i++) {
        const v = arr[start + i];
        s += v * v;
      }
      return Math.sqrt(s / win);
    };
    const e1Vec = probed1.map(bandRms);
    const e2Vec = probed2.map(bandRms);
    const eHi = probedHi.map(bandRms);
    const [f1, e1] = bandPeak(F1_BANDS, e1Vec);
    const [f2, e2] = bandPeak(F2_BANDS, e2Vec);
    const hiRatio = ((eHi[0] + eHi[1] + eHi[2]) / 3.0) / (e1 + e2 + 1e-9);

    frames.push({
      t: start / sr2, rms, d1, vo, f0,
      f1, f2, e1, e2, e1Vec, e2Vec, eHi, hiRatio,
    });
  }
  return frames;
}

// ---- 3. デコード（hitofude.mjs の VT & F1/F2 式をそのまま逆引き） ----

function med5(arr) {
  const n = arr.length;
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, i - 2);
    const b = Math.min(n, i + 3);
    const w = arr.slice(a, b).sort((u, v) => u - v);
    out[i] = w[w.length >> 1];
  }
  return out;
}

export function decode(frames, vtTable = KUSANAGI_VT) {
  if (!frames.length) return { text: "", trace: [], fscale: 1.0, medF0: 0.0 };
  let peakRms = 0.0;
  for (const f of frames) if (f.rms > peakRms) peakRms = f.rms;
  if (peakRms <= 0.0) peakRms = 1.0;
  const silTh = peakRms * 0.06;

  // 有声フレームのピッチ f0 中央値から声道スケール fscale を推定
  // hitofude.mjs PRESETS: ossan(148Hz->0.88), robot(220Hz->1.06), hitofude(350Hz->1.17), chibi(400Hz->1.32)
  const vF0 = frames
    .filter((f) => f.rms > silTh * 2.0 && f.vo > 0.45 && f.hiRatio < 0.5 && f.f0 >= 85 && f.f0 <= 500)
    .map((f) => f.f0)
    .sort((a, b) => a - b);
  const medF0 = vF0.length ? vF0[vF0.length >> 1] : 0.0;
  const fscale = medF0 > 0 ? Math.max(0.82, Math.min(1.36, Math.pow(medF0 / 215.0, 0.35))) : 1.0;

  // F1 は <= 950 * fscale（あ の F1 上限）でガードし、お の低 F2 の侵入を防ぐ
  // F2 は F1 自身の漏れ (> f1 + 150) と F3 の侵入 (<= 3150 * fscale) をガードして読む
  const f1Ceil = 950.0 * fscale;
  const f2Ceil = 3150.0 * fscale;
  for (const f of frames) {
    const e1m = F1_BANDS.map((freq, idx) => (freq <= f1Ceil ? f.e1Vec[idx] : 0.0));
    const [nf1, ne1] = bandPeak(F1_BANDS, e1m);
    if (ne1 > 1e-12) { f.f1 = nf1; f.e1 = ne1; }
    const e2m = F2_BANDS.map((freq, idx) => (freq >= f.f1 + 150.0 && freq <= f2Ceil ? f.e2Vec[idx] : 0.0));
    const [nf2, ne2] = bandPeak(F2_BANDS, e2m);
    if (ne2 > 1e-12) { f.f2 = nf2; f.e2 = ne2; }
  }

  const sf1 = med5(frames.map((f) => f.f1));
  const sf2 = med5(frames.map((f) => f.f2));
  const sf0 = med5(frames.map((f) => f.f0));
  const vowelKeys = Object.keys(vtTable);

  const closureTh = peakRms * 0.022;
  const vowelTh = peakRms * 0.085;

  const labels = frames.map((f, i) => {
    if (f.rms < closureTh) return "_";
    // 高域摩擦・歯茎破裂 (hitofude.mjs: S=6000Hz, T=4500Hz, SH=3600Hz)
    if (f.hiRatio >= 0.45 && f.eHi[2] >= f.eHi[0] * 1.15 && f.eHi[2] >= f.eHi[1] * 0.72 && (f.vo < 0.45 || f.d1 > 0.50)) {
      return "S";
    }
    if (f.hiRatio >= 0.30 && f.eHi[1] > f.eHi[0] && f.eHi[1] > f.eHi[2] * 1.25 && f.vo < 0.35) {
      return "T";
    }
    if (f.hiRatio >= 0.30 && f.eHi[0] > f.eHi[2] * 1.35 && f.eHi[0] >= f.eHi[1] * 1.05 && f.rms >= peakRms * 0.06 && (f.vo < 0.45 || f.d1 > 0.50)) {
      return "SH";
    }
    // 弱振幅帯 (closureTh <= rms < vowelTh): 有声なら弾き音 R、無声なら破裂/息 B
    if (f.rms < vowelTh) {
      if (f.vo >= 0.40 && f.hiRatio < 0.35) return "R";
      return "B";
    }
    // 強めの無声息・破裂 (H / 強い K)
    if (f.vo < 0.25 && f.d1 > 0.40) return "B";
    // 鼻音は低F1かつ低F2（い のような高F2母音を誤爆しない）かつ高域減衰が大きい
    if (sf1[i] < 360 * fscale && sf2[i] < 1700 * fscale && f.e2 < f.e1 * 0.08 && f.rms < peakRms * 0.35) return "N";

    // hitofude.mjs L1216-1217 の実効フォルマント式をそのまま逆引き:
    //   t1 = max(VT[v][0] * fscale, 1.04 * f0)
    //   t2 = max(VT[v][1] * fscale, t1 + 280)
    const lf1 = Math.log(Math.max(100.0, sf1[i]));
    const lf2 = Math.log(Math.max(300.0, sf2[i]));
    const f0Now = sf0[i] >= 85 ? sf0[i] : medF0;
    let bestV = "a", bestD = 1e9;
    for (const v of vowelKeys) {
      const [v1, v2] = vtTable[v];
      const t1 = Math.max(v1 * fscale, 1.04 * f0Now);
      const t2 = Math.max(v2 * fscale, t1 + 280.0);
      const d1 = lf1 - Math.log(t1);
      const d2 = lf2 - Math.log(t2);
      const d = d1 * d1 * 1.2 + d2 * d2 * 1.4;
      if (d < bestD) { bestD = d; bestV = v; }
    }
    return bestV;
  });

  // 3フレーム多数決で孤立スパイク除去
  const sm = labels.slice();
  for (let i = 1; i < labels.length - 1; i++) {
    if (labels[i - 1] === labels[i + 1] && labels[i] !== labels[i - 1]) sm[i] = labels[i - 1];
  }

  // ランレングス圧縮
  const runs = [];
  for (let i = 0; i < sm.length; i++) {
    const lab = sm[i];
    if (!runs.length || runs[runs.length - 1][0] !== lab) runs.push([lab, i, i + 1]);
    else runs[runs.length - 1][2] = i + 1;
  }

  const runStats = (a, b) => {
    let hi = 0, f2s = 0, e0 = 0, e2 = 0;
    const n = Math.max(1, b - a);
    for (let i = a; i < b; i++) {
      hi += frames[i].hiRatio;
      f2s += sf2[i];
      e0 += frames[i].eHi[0];
      e2 += frames[i].eHi[2];
    }
    return { hiR: hi / n, f2: f2s / n, e2over0: e2 / Math.max(1e-12, e0), dur: b - a };
  };

  // 無声化母音 (シ・ス・チ・ツ・キ・ク・ピ・プ・ヒ・フ) のフラッシュ
  const flushDevoiced = (c, meta) => {
    if (!c || !meta) return null;
    if (c === "sh" && meta.dur >= 3) return "し";
    if (c === "ch" && meta.dur >= 3) return "ち";
    if (c === "s" && meta.dur >= 3) return "す";
    if (c === "ts" && meta.dur >= 3) return "つ";
    if (c === "k" && meta.dur >= 2) return meta.f2 / fscale >= 1950 ? "き" : "く";
    if (c === "p" && meta.dur >= 2) return meta.f2 / fscale >= 2200 ? "ぴ" : "ぷ";
    if (c === "h" && meta.dur >= 4) return (meta.hiR >= 0.22 || meta.f2 / fscale >= 2000) ? "ひ" : "ふ";
    if (c === "t" && meta.dur >= 2) return meta.f2 / fscale >= 2000 ? "ち" : "つ";
    return null;
  };

  // かな組み立て
  const out = [];
  let pendingC = "";
  let pendingMeta = null;
  let silLen = 0;
  for (let idx = 0; idx < runs.length; idx++) {
    const [lab, a, b] = runs[idx];
    const dur = b - a;
    if (lab === "_") {
      if (dur >= 15) {
        if (pendingC === "s" || pendingC === "sh" || pendingC === "h") {
          const dv = flushDevoiced(pendingC, pendingMeta);
          if (dv) out.push(dv);
        }
        pendingC = "";
        pendingMeta = null;
        if (out.length && out[out.length - 1] !== "、") out.push("、");
      }
      silLen = dur;
      continue;
    }
    if (lab === "S" || lab === "SH" || lab === "T" || lab === "B") {
      if (dur < 2) continue;
      const st = runStats(a, b);
      const isClosure = silLen >= 3 && silLen <= 14;
      const isAffClosure = silLen >= 4 && silLen <= 14;
      let nextC = "";
      if (lab === "S") nextC = isAffClosure ? "ts" : "s";
      else if (lab === "SH") nextC = isAffClosure ? "ch" : (st.hiR >= 0.40 ? "sh" : "h");
      else if (lab === "T") nextC = "t";
      else {
        // B: 息 H (長め) vs 破裂 K (1900/3000Hz: hiR>=0.13 または高域傾斜 eHi[2]/eHi[0]>=1.5) vs P (1200Hz)
        if ((dur >= 5 && !isClosure) || dur >= 7) nextC = "h";
        else if (st.hiR >= 0.13 || st.e2over0 >= 1.5) nextC = "k";
        else nextC = "p";
      }
      // 前の無声子音が母音なしで次子音にぶつかったら、無声化母音として確定
      if (pendingC && pendingC !== "r" && pendingC !== "n") {
        // 破裂直後の同一調音摩擦 (例: T/B -> S/SH) は破擦音に統合
        if ((pendingC === "t" || pendingC === "k" || pendingC === "p") && silLen === 0 && (lab === "S" || lab === "SH")) {
          nextC = lab === "SH" ? "ch" : "ts";
        } else {
          const dv = flushDevoiced(pendingC, pendingMeta);
          if (dv) out.push(dv);
        }
      }
      pendingC = nextC;
      pendingMeta = st;
      silLen = 0;
      continue;
    }
    if (lab === "R") {
      const nxt = idx + 1 < runs.length ? runs[idx + 1][0] : "_";
      if (!pendingC && dur >= 2 && dur <= 6 && vtTable[nxt]) {
        pendingC = "r";
        pendingMeta = null;
      }
      silLen = 0;
      continue;
    }
    if (lab === "N") {
      if (dur >= 3) {
        const nxt = idx + 1 < runs.length ? runs[idx + 1][0] : "_";
        if (vtTable[nxt]) { pendingC = "n"; pendingMeta = null; }
        else { out.push("ん"); pendingC = ""; pendingMeta = null; }
      }
      silLen = 0;
      continue;
    }
    if (dur < (pendingC ? 4 : 5)) continue;
    let c = pendingC;
    pendingC = "";
    pendingMeta = null;
    if (!c && silLen >= 3 && silLen <= 12 && out.length && out[out.length - 1] !== "、") {
      const f2On = sf2[a] / fscale;
      if (f2On < 1200) c = "p";
      else if (f2On < 1950) c = "t";
      else c = "k";
    }
    out.push(KANA[`${c},${lab}`] ?? KANA[`,${lab}`]);
    silLen = 0;
  }
  if (pendingC === "s" || pendingC === "sh") {
    const dv = flushDevoiced(pendingC, pendingMeta);
    if (dv) out.push(dv);
  }
  while (out.length && out[out.length - 1] === "、") out.pop();

  return {
    text: out.join(""),
    trace: frames.map((f, i) => ({ ...f, sf1: sf1[i], sf2: sf2[i], lab: sm[i] })),
    fscale,
    medF0,
  };
}

/** 16-bit / 8-bit PCM WAV デコーダ（標準JSのみ・外部依存ゼロ）。 */
export function decodeWavBytes(buf) {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  let off = 12, ch = 1, sr = 44100, bits = 16, dataOff = 0, dataLen = 0;
  while (off + 8 <= buf.byteLength) {
    const id = String.fromCharCode(dv.getUint8(off), dv.getUint8(off + 1), dv.getUint8(off + 2), dv.getUint8(off + 3));
    const sz = dv.getUint32(off + 4, true);
    if (id === "fmt ") {
      ch = dv.getUint16(off + 10, true);
      sr = dv.getUint32(off + 12, true);
      bits = dv.getUint16(off + 22, true);
    } else if (id === "data") {
      dataOff = off + 8;
      dataLen = sz;
      break;
    }
    off += 8 + sz + (sz & 1);
  }
  const bytesPerSample = bits >> 3;
  const nFrames = Math.floor(dataLen / (ch * bytesPerSample));
  const out = new Float32Array(nFrames);
  for (let i = 0; i < nFrames; i++) {
    let s = 0.0;
    for (let c = 0; c < ch; c++) {
      const p = dataOff + (i * ch + c) * bytesPerSample;
      s += bits === 16 ? dv.getInt16(p, true) / 32768.0 : (dv.getUint8(p) - 128) / 128.0;
    }
    out[i] = s / ch;
  }
  return { samples: out, sr };
}

// ---- 4. Node.js CLI（直接実行時のみ起動） ----
const isNodeCli = typeof process !== "undefined" && process.argv?.[1] &&
  import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/"));

if (isNodeCli) {
  const fs = await import("node:fs");
  const args = process.argv.slice(2);
  if (!args.length) {
    console.log("使い方: node kiku.mjs --say <カナ> [--preset hitofude|ossan|chibi|robot|toiki] [--scope]");
    console.log("       node kiku.mjs <wav_path> [--scope]");
    process.exit(1);
  }
  const scope = args.includes("--scope");
  const sayIdx = args.indexOf("--say");
  const preIdx = args.indexOf("--preset");
  const presetName = preIdx >= 0 ? args[preIdx + 1] : "hitofude";

  const printResult = (label, res) => {
    console.log(`[${label}] -> ${res.text}  (f0=${res.medF0.toFixed(0)}Hz, fscale=${res.fscale.toFixed(2)})`);
    if (scope) {
      const pk = res.trace.reduce((m, f) => Math.max(m, f.rms), 0) || 1.0;
      for (const f of res.trace) {
        const bar = "#".repeat(Math.min(20, Math.trunc((20 * f.rms) / pk))).padEnd(20, " ");
        console.log(`${f.t.toFixed(2).padStart(5)}s ${f.lab.padEnd(2)} |${bar}| vo=${f.vo.toFixed(2)} f0=${f.f0.toFixed(0).padStart(3)} F1=${f.sf1.toFixed(0).padStart(4)} F2=${f.sf2.toFixed(0).padStart(4)} hi=${f.hiRatio.toFixed(2)}`);
      }
    }
  };

  if (sayIdx >= 0) {
    const { makeHitofude, PRESETS, SR } = await import("./hitofude.mjs");
    const text = args[sayIdx + 1];
    const prm = PRESETS[presetName] || PRESETS.hitofude;
    const { samples } = makeHitofude(text, prm);
    const res = decode(analyze(samples, SR));
    printResult(`${presetName}:${text}`, res);
  } else {
    const paths = args.filter((a, i) => a !== "--scope" && a !== "--preset" && (preIdx < 0 || i !== preIdx + 1));
    for (const p of paths) {
      const raw = fs.readFileSync(p);
      const { samples, sr } = decodeWavBytes(raw);
      printResult(p, decode(analyze(samples, sr)));
    }
  }
}
