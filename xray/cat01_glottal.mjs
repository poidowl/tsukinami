// xray/cat01_glottal.mjs — 変態解析ツール #01〜#10: 声門・声帯ソース解析 (Glottal & Voice Quality)
import { fftRadix2 } from "../hitofude.mjs";
import { median } from "./core.mjs";

function peakDbNear(freqs, spDb, fc, bwFrac = 0.22) {
  let mx = -Infinity;
  const lo = fc * (1.0 - bwFrac), hi = fc * (1.0 + bwFrac);
  for (let k = 0; k < freqs.length; k++) {
    if (freqs[k] >= lo && freqs[k] <= hi && spDb[k] > mx) mx = spDb[k];
  }
  return mx;
}

function peakDbBand(freqs, spDb, lo, hi) {
  let mx = -Infinity;
  for (let k = 0; k < freqs.length; k++) {
    if (freqs[k] >= lo && freqs[k] <= hi && spDb[k] > mx) mx = spDb[k];
  }
  return mx;
}

export const CAT01_TOOLS = [
  {
    id: 1, key: "h1_h2_db", name: "H1-H2 (声門開大率/息っぽさ)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const h1 = peakDbNear(d.freqs, d.magDb[t], f0, 0.25);
        const h2 = peakDbNear(d.freqs, d.magDb[t], 2 * f0, 0.18);
        if (Number.isFinite(h1) && Number.isFinite(h2)) vals.push(h1 - h2);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 2, key: "h1_a1_db", name: "H1-A1 (F1帯の温かみ/鼻抜け)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const h1 = peakDbNear(d.freqs, d.magDb[t], f0, 0.25);
        const a1 = peakDbBand(d.freqs, d.magDb[t], Math.max(f0 * 1.3, 350), 1250);
        if (Number.isFinite(h1) && Number.isFinite(a1)) vals.push(h1 - a1);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 3, key: "h1_a3_db", name: "H1-A3 (声門閉鎖の鋭さ/傾斜)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const h1 = peakDbNear(d.freqs, d.magDb[t], f0, 0.25);
        const a3 = peakDbBand(d.freqs, d.magDb[t], 2400, 3800);
        if (Number.isFinite(h1) && Number.isFinite(a3)) vals.push(h1 - a3);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 4, key: "cpp_db", name: "CPP (ケプストラム明瞭度ピーク)", unit: "dB",
    run(d) {
      const vals = [];
      const nfft = d.nfft, half = (nfft >> 1) + 1;
      const qLo = Math.max(2, Math.trunc(d.sr / 560)), qHi = Math.min(half - 2, Math.trunc(d.sr / 150));
      const logBuf = new Float64Array(nfft);
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const m = d.mag[t];
        logBuf.fill(0.0);
        for (let k = 0; k < m.length; k++) {
          const lv = Math.log(m[k] + 1e-9);
          logBuf[k] = lv;
          if (k > 0 && k < nfft - k) logBuf[nfft - k] = lv;
        }
        const { re } = fftRadix2(logBuf);
        const seg = [];
        let mx = -Infinity;
        for (let q = qLo; q <= qHi; q++) {
          const v = re[q] / nfft;
          seg.push(v);
          if (v > mx) mx = v;
        }
        if (seg.length > 4) vals.push((mx - median(seg)) * 20.0);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 5, key: "spec_tilt_dboct", name: "高域スペクトル傾斜 (0.3-5kHz)", unit: "dB/oct",
    run(d) {
      const vals = [];
      const logF = [], kIdx = [];
      for (let k = 0; k < d.nBins; k++) {
        if (d.freqs[k] >= 300 && d.freqs[k] <= 5000) {
          logF.push(Math.log2(d.freqs[k]));
          kIdx.push(k);
        }
      }
      const mX = logF.reduce((a, b) => a + b, 0) / (logF.length || 1);
      let varX = 0.0;
      for (const lx of logF) varX += (lx - mX) * (lx - mX);
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const md = d.magDb[t];
        let mY = 0.0;
        for (const k of kIdx) mY += md[k];
        mY /= kIdx.length;
        let cov = 0.0;
        for (let i = 0; i < kIdx.length; i++) cov += (logF[i] - mX) * (md[kIdx[i]] - mY);
        vals.push(cov / (varX || 1.0));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 6, key: "close_sharpness", name: "声門閉鎖シャープネス (負微分尖度)", unit: "ratio",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const off = t * d.hop;
        let maxNeg = 0.0, sq = 0.0;
        for (let i = 1; i < d.wl; i++) {
          const dv = d.x[off + i] - d.x[off + i - 1];
          if (-dv > maxNeg) maxNeg = -dv;
          sq += dv * dv;
        }
        const rmsD = Math.sqrt(sq / d.wl) || 1e-9;
        vals.push(maxNeg / rmsD);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 7, key: "subharmonic_ratio", name: "サブハーモニクス比 SHR (エッジ/フライ)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0 || f0 < 220) continue;
        let sh = 0.0, hm = 0.0;
        for (let k = 1; k <= 4; k++) {
          sh += peakDbNear(d.freqs, d.magDb[t], (k - 0.5) * f0, 0.14);
          hm += peakDbNear(d.freqs, d.magDb[t], k * f0, 0.14);
        }
        if (Number.isFinite(sh) && Number.isFinite(hm)) vals.push((sh - hm) / 4.0);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 8, key: "open_quotient_est", name: "推定Open Quotient (声門開大率)", unit: "0..1",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const h1 = peakDbNear(d.freqs, d.magDb[t], f0, 0.25);
        const h2 = peakDbNear(d.freqs, d.magDb[t], 2 * f0, 0.18);
        if (Number.isFinite(h1) && Number.isFinite(h2)) {
          // Empirical Holmberg/Henrich mapping: OQ ≈ 0.50 + 0.018*(H1-H2) clamped [0.25, 0.92]
          vals.push(Math.min(0.92, Math.max(0.25, 0.50 + 0.018 * (h1 - h2))));
        }
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 9, key: "hrf_db", name: "HRF (倍音豊かさ H2..H8 / H1)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const h1 = peakDbNear(d.freqs, d.magDb[t], f0, 0.25);
        if (!Number.isFinite(h1)) continue;
        let sumP = 0.0;
        for (let k = 2; k <= 8; k++) {
          if (k * f0 > 7500) break;
          const hk = peakDbNear(d.freqs, d.magDb[t], k * f0, 0.14);
          if (Number.isFinite(hk)) sumP += Math.pow(10.0, hk / 10.0);
        }
        const h1P = Math.pow(10.0, h1 / 10.0);
        if (sumP > 0) vals.push(10.0 * Math.log10(sumP / (h1P + 1e-18)));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 10, key: "onset_rise_ms", name: "語頭立ち上がり時間 (柔らかさ)", unit: "ms",
    run(d) {
      const rises = [];
      let inVo = false;
      for (let t = 1; t < d.nFrames - 8; t++) {
        if (d.f0Hz[t] > 0 && !inVo) {
          inVo = true;
          // Measure frames from 15% to 85% of local voiced peak RMS
          let pk = 0.0;
          for (let k = t; k < Math.min(d.nFrames, t + 16); k++) if (d.rmsFr[k] > pk) pk = d.rmsFr[k];
          let t15 = t, t85 = t;
          while (t15 > 0 && d.rmsFr[t15] > 0.15 * pk) t15--;
          while (t85 < Math.min(d.nFrames - 1, t + 16) && d.rmsFr[t85] < 0.85 * pk) t85++;
          rises.push((t85 - t15) * 5.0);
        } else if (d.f0Hz[t] === 0 && d.f0Hz[Math.max(0, t - 1)] === 0) {
          inVo = false;
        }
      }
      return Number(median(rises).toFixed(1));
    },
  },
];
