// xray/cat08_psycho.mjs — 変態解析ツール #71〜#80: 心理音響・聴覚モデル (Psychoacoustics & Perceptual)
import { fftRadix2, median, percentile } from "./core.mjs";

function hzToBark(f) {
  return 13.0 * Math.atan(0.00076 * f) + 3.5 * Math.atan(Math.pow(f / 7500.0, 2));
}

function bandPowerDb(freqs, mag, lo, hi) {
  let s = 0.0, n = 0;
  for (let b = 0; b < freqs.length; b++) {
    if (freqs[b] >= lo && freqs[b] <= hi) { s += mag[b] * mag[b]; n++; }
  }
  return 10.0 * Math.log10((s / (n || 1)) + 1e-18);
}

const U_STAR = Math.log(5.75 / 3.5) / 2.25;
const G_MAX = Math.exp(-3.5 * U_STAR) - Math.exp(-5.75 * U_STAR);

function erbHz(f) {
  return 24.7 * (0.00437 * f + 1.0);
}

function erbToHz(e) {
  return (Math.pow(10.0, e / 21.4) - 1.0) / 0.00437;
}

function plKernel(u) {
  return u > 0.01 && u <= 2.2 ? (Math.exp(-3.5 * u) - Math.exp(-5.75 * u)) / G_MAX : 0.0;
}

export function getPlompLeveltErb(d) {
  if (d._plRough) return d._plRough;

  // Component A: Voiced spectral pairwise Plomp-Levelt / Vassilakis roughness
  const frameVals = new Float64Array(d.nFrames);
  const specVals = [];
  const df = d.freqs.length > 1 ? (d.freqs[1] - d.freqs[0]) : (d.sr / d.nfft);
  for (let t = 0; t < d.nFrames; t++) {
    if (!d.f0Hz[t]) continue;
    const m = d.mag[t];
    const md = d.magDb[t];
    let pkMax = 0.0;
    for (let b = 2; b < d.nBins - 2; b++) {
      const f = d.freqs[b];
      if (f >= 120.0 && f <= 7500.0 && m[b] > pkMax) pkMax = m[b];
    }
    if (pkMax <= 1e-12) {
      specVals.push(0.0);
      continue;
    }
    const pks = [];
    const thr = 0.02 * pkMax;
    for (let b = 2; b < d.nBins - 2; b++) {
      const f = d.freqs[b];
      if (f < 120.0 || f > 7500.0) continue;
      if (m[b] >= thr && m[b] > m[b - 1] && m[b] >= m[b + 1]) {
        const yL = md[b - 1], y0 = md[b], yR = md[b + 1];
        const denom = yL - 2.0 * y0 + yR;
        const delta = Math.abs(denom) > 1e-9 ? Math.max(-0.5, Math.min(0.5, (0.5 * (yL - yR)) / denom)) : 0.0;
        pks.push({ f: f + delta * df, a: m[b] / pkMax });
      }
    }
    if (pks.length > 20) {
      pks.sort((u, v) => v.a - u.a);
      pks.length = 20;
    }
    let num = 0.0, den = 0.0;
    for (let i = 0; i < pks.length; i++) den += pks[i].a * pks[i].a;
    for (let i = 0; i < pks.length; i++) {
      const fi = pks[i].f, ai = pks[i].a;
      for (let j = i + 1; j < pks.length; j++) {
        const fj = pks[j].f, aj = pks[j].a;
        const fMin = fi < fj ? fi : fj;
        const u = Math.abs(fj - fi) / erbHz(fMin);
        const g = plKernel(u);
        if (g <= 0.0) continue;
        const aMin = ai < aj ? ai : aj;
        const modW = (2.0 * aMin) / (ai + aj + 1e-12);
        num += ai * aj * (modW * modW) * g;
      }
    }
    const rSpec = (100.0 * num) / (den + 1e-12);
    frameVals[t] = rSpec;
    specVals.push(rSpec);
  }
  const med = Number(median(specVals).toFixed(2));
  const p90 = Number(percentile(specVals, 90).toFixed(2));

  // Component B: 18-channel ERB bandpass (z=+-1 zeros) temporal modulation roughness
  let mod = 0.0;
  const sr = d.sr;
  const N = d.x.length;
  const step = Math.max(1, Math.round(sr / 1000.0));
  const nEnv = Math.floor(N / step);
  if (nEnv >= 32) {
    const fsEnv = sr / step;
    const voMask = new Uint8Array(nEnv);
    let voCnt = 0;
    for (let mIdx = 0; mIdx < nEnv; mIdx++) {
      const t = Math.max(0, Math.min(d.nFrames - 1, Math.round((mIdx * step - 0.5 * d.wl) / d.hop)));
      if (d.f0Hz[t] > 0) { voMask[mIdx] = 1; voCnt++; }
    }
    if (voCnt >= 32) {
      const WLEN = 128, WHOP = 64, NFFT = 256;
      const wins = [];
      for (let s = 0; s + WLEN <= nEnv; s += WHOP) {
        let vc = 0;
        for (let k = 0; k < WLEN; k++) vc += voMask[s + k];
        if (vc >= 96) wins.push({ start: s, len: WLEN });
      }
      if (!wins.length) {
        let s = 0;
        while (s < nEnv) {
          while (s < nEnv && !voMask[s]) s++;
          const a = s;
          while (s < nEnv && voMask[s]) s++;
          const len = s - a;
          if (len >= 32) wins.push({ start: a, len: Math.min(NFFT, len) });
        }
      }
      if (wins.length) {
        const chEnvs = [];
        const chBws = [];
        const alpha = 1.0 - Math.exp((-2.0 * Math.PI * 180.0) / sr);
        const x = d.x;
        for (let c = 0; c < 18; c++) {
          const ec = 6.5 + (24.0 * c) / 17.0;
          const fc = erbToHz(ec);
          if (fc >= 0.45 * sr) continue;
          const Bc = erbHz(fc);
          const r = Math.exp((-Math.PI * Bc) / sr);
          const wc = (2.0 * Math.PI * fc) / sr;
          const a1 = 2.0 * r * Math.cos(wc);
          const a2 = -r * r;
          const gbp = ((1.0 - r) * Math.sqrt(Math.max(1e-12, 1.0 - 2.0 * r * Math.cos(2.0 * wc) + r * r))) /
            Math.max(1e-6, 2.0 * Math.sin(wc));
          const env = new Float64Array(nEnv);
          let y1 = 0.0, y2 = 0.0, lp = 0.0;
          let x1 = 0.0, x2 = 0.0;
          let mIdx = 0;
          for (let n = 0; n < N; n++) {
            const x0 = x[n];
            const y0 = gbp * (x0 - x2) + a1 * y1 + a2 * y2;
            x2 = x1; x1 = x0;
            y2 = y1; y1 = y0;
            lp += alpha * (Math.abs(y0) - lp);
            if (n % step === 0 && mIdx < nEnv) env[mIdx++] = lp;
          }
          chEnvs.push(env);
          chBws.push(Bc);
        }

        const dfEnv = fsEnv / NFFT;
        const kLo = Math.max(1, Math.ceil(16.0 / dfEnv));
        const kHi = Math.min((NFFT >> 1) - 1, Math.floor(160.0 / dfEnv));
        const fftBuf = new Float64Array(NFFT);
        const winVals = [];
        const hannCache = new Map();

        for (const wObj of wins) {
          const { start, len } = wObj;
          let hObj = hannCache.get(len);
          if (!hObj) {
            const h = new Float64Array(len);
            let hSq = 0.0, kVar = 0.0;
            const kMid = 0.5 * (len - 1);
            for (let k = 0; k < len; k++) {
              h[k] = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * k) / Math.max(1, len - 1));
              hSq += h[k] * h[k];
              const dk = k - kMid;
              kVar += dk * dk;
            }
            hObj = { h, hSq, kMid, kVar: kVar || 1.0 };
            hannCache.set(len, hObj);
          }
          const { h, hSq, kMid, kVar } = hObj;
          let winNum = 0.0, winDen = 0.0;
          for (let ci = 0; ci < chEnvs.length; ci++) {
            const env = chEnvs[ci];
            const Bc = chBws[ci];
            let wMu = 0.0;
            for (let k = 0; k < len; k++) wMu += env[start + k];
            wMu /= len;
            if (wMu <= 1e-9) continue;
            let sNum = 0.0;
            for (let k = 0; k < len; k++) sNum += (k - kMid) * (env[start + k] - wMu);
            const slope = sNum / kVar;
            fftBuf.fill(0.0);
            for (let k = 0; k < len; k++) {
              fftBuf[k] = (env[start + k] - wMu - slope * (k - kMid)) * h[k];
            }
            const { re, im } = fftRadix2(fftBuf);
            let wPow = 0.0;
            for (let k = kLo; k <= kHi; k++) {
              const g = plKernel((k * dfEnv) / Bc);
              if (g > 0.0) wPow += g * (re[k] * re[k] + im[k] * im[k]);
            }
            const rc = 100.0 * Math.sqrt((2.0 * wPow) / (NFFT * hSq * wMu * wMu + 1e-18));
            const wCh = Math.pow(wMu, 0.6);
            winNum += wCh * rc;
            winDen += wCh;
          }
          if (winDen > 0.0) winVals.push(winNum / winDen);
        }
        mod = Number(median(winVals).toFixed(2));
      }
    }
  }

  const composite = Number((0.50 * med + 0.25 * p90 + 0.25 * mod).toFixed(2));
  d._plRough = { med, p90, mod, composite, frameVals };
  return d._plRough;
}

export const CAT08_TOOLS = [
  {
    id: 71, key: "brightness_db", name: "明るさスコア brightness (中高域 - 低域)", unit: "dB",
    run(d) {
      const b1 = Math.floor(d.nBins / 3), b2 = Math.floor((4 * d.nBins) / 5);
      let sum = 0.0;
      for (let t = 0; t < d.nFrames; t++) {
        const md = d.magDb[t];
        let lo = 0.0, hi = 0.0;
        for (let b = 0; b < b1; b++) lo += md[b];
        for (let b = b1; b < b2; b++) hi += md[b];
        sum += (hi / Math.max(1, b2 - b1)) - (lo / Math.max(1, b1));
      }
      return Number((sum / (d.nFrames || 1)).toFixed(2));
    },
  },
  {
    id: 72, key: "spec_centroid_hz", name: "有声スペクトル重心", unit: "Hz",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        let num = 0.0, den = 0.0;
        for (let b = 1; b < d.nBins; b++) {
          const p = d.mag[t][b] * d.mag[t][b];
          num += d.freqs[b] * p; den += p;
        }
        if (den > 0) vals.push(num / den);
      }
      return Math.round(median(vals));
    },
  },
  {
    id: 73, key: "spec_rolloff85_hz", name: "85%エネルギーロールオフ周波数", unit: "Hz",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        let tot = 0.0;
        for (let b = 1; b < d.nBins; b++) tot += d.mag[t][b] * d.mag[t][b];
        let acc = 0.0, f85 = d.freqs[d.nBins - 1];
        for (let b = 1; b < d.nBins; b++) {
          acc += d.mag[t][b] * d.mag[t][b];
          if (acc >= 0.85 * tot) { f85 = d.freqs[b]; break; }
        }
        vals.push(f85);
      }
      return Math.round(median(vals));
    },
  },
  {
    id: 74, key: "zwicker_sharpness", name: "Zwicker鋭さ (Bark重み付け acum近似)", unit: "acum",
    run(d) {
      const barks = Float64Array.from(d.freqs, hzToBark);
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        let num = 0.0, den = 0.0;
        for (let b = 1; b < d.nBins; b++) {
          const z = barks[b];
          const g = z <= 15.8 ? 1.0 : 0.066 * Math.exp(0.171 * z);
          const N_ = Math.pow(d.mag[t][b], 0.6); // specific loudness approx
          num += N_ * g * z;
          den += N_;
        }
        if (den > 0) vals.push(0.11 * (num / den));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 75, key: "sensory_roughness", name: "感覚的粗さ Roughness (Plomp-Levelt ERB統合)", unit: "idx",
    run: (d) => getPlompLeveltErb(d).composite,
  },
  {
    id: 76, key: "fluctuation_4hz", name: "聴覚変動強度 (4Hz変調ピーク)", unit: "vacil",
    run(d) {
      const dt = d.hop / d.sr;
      let m = 0.0;
      for (let t = 0; t < d.nFrames; t++) m += d.rmsFr[t];
      m /= d.nFrames || 1;
      let cr = 0.0, ci = 0.0;
      for (let t = 0; t < d.nFrames; t++) {
        const ang = 2.0 * Math.PI * 4.0 * t * dt;
        cr += (d.rmsFr[t] - m) * Math.cos(ang);
        ci += (d.rmsFr[t] - m) * Math.sin(ang);
      }
      return Number(((2.0 * Math.hypot(cr, ci)) / ((d.nFrames || 1) * (m || 1))).toFixed(3));
    },
  },
  {
    id: 77, key: "warmth_db", name: "温かみ指数 (200-600Hz - 2-5kHz)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        vals.push(bandPowerDb(d.freqs, d.mag[t], 200, 600) - bandPowerDb(d.freqs, d.mag[t], 2000, 5000));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 78, key: "intimacy_db", name: "耳元度・近接感 (低域温もり+高域空気)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const lo = bandPowerDb(d.freqs, d.mag[t], 200, 550);
        const mid = bandPowerDb(d.freqs, d.mag[t], 900, 2200);
        const air = bandPowerDb(d.freqs, d.mag[t], 4500, 7800);
        vals.push(0.5 * (lo + air) - mid);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 79, key: "ear_fatigue_db", name: "耳刺さり/聴き疲れ指数 (2.5-4.2kHz突出)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        let pk = -Infinity;
        for (let b = 0; b < d.nBins; b++) {
          if (d.freqs[b] >= 2500 && d.freqs[b] <= 4200 && d.magDb[t][b] > pk) pk = d.magDb[t][b];
        }
        const ref = bandPowerDb(d.freqs, d.mag[t], 400, 2000);
        if (Number.isFinite(pk)) vals.push(pk - ref);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 80, key: "erb_hi_mid_db", name: "ERB高帯域/中帯域バランス (3.2-7k / 0.8-2.8k)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        vals.push(bandPowerDb(d.freqs, d.mag[t], 3200, 7000) - bandPowerDb(d.freqs, d.mag[t], 800, 2800));
      }
      return Number(median(vals).toFixed(2));
    },
  },
];
