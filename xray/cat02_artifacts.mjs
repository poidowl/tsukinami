// xray/cat02_artifacts.mjs — 変態解析ツール #11〜#20: 異音・アーティファクト自動ハンター (Artifact & Anomaly Hunter)
import { median, percentile } from "./core.mjs";

function bandHnr(d, fLo, fHi) {
  const vals = [];
  for (let t = 0; t < d.nFrames; t++) {
    const f0 = d.f0Hz[t]; if (!f0) continue;
    const md = d.magDb[t];
    const k0 = Math.max(1, Math.ceil(fLo / f0)), k1 = Math.floor(fHi / f0);
    const diffs = [];
    for (let k = k0; k < k1; k++) {
      let pMax = -Infinity, vMin = Infinity, hp = false, hv = false;
      const pLo = (k - 0.20) * f0, pHi = (k + 0.20) * f0;
      const vLo = (k + 0.30) * f0, vHi = (k + 0.70) * f0;
      for (let b = 0; b < d.nBins; b++) {
        const f = d.freqs[b];
        if (f >= pLo && f <= pHi) { if (md[b] > pMax) pMax = md[b]; hp = true; }
        if (f >= vLo && f <= vHi) { if (md[b] < vMin) vMin = md[b]; hv = true; }
      }
      if (hp && hv) diffs.push(pMax - vMin);
    }
    if (diffs.length) vals.push(diffs.reduce((a, b) => a + b, 0) / diffs.length);
  }
  return Number(median(vals).toFixed(2));
}

export const CAT02_TOOLS = [
  { id: 11, key: "hnr_low_db", name: "帯域別HNR 0.2-1.5kHz (声の芯)", unit: "dB", run: (d) => bandHnr(d, 200, 1500) },
  { id: 12, key: "hnr_mid_db", name: "帯域別HNR 1.5-3.0kHz (明瞭帯)", unit: "dB", run: (d) => bandHnr(d, 1500, 3000) },
  { id: 13, key: "hnr_hi_db", name: "帯域別HNR 3.0-5.0kHz (キラ帯)", unit: "dB", run: (d) => bandHnr(d, 3000, 5000) },
  { id: 14, key: "hnr_air_db", name: "帯域別HNR 5.0-8.0kHz (空気帯)", unit: "dB", run: (d) => bandHnr(d, 5000, 8000) },
  {
    id: 15, key: "fixed_whistle_db", name: "固定周波数ピー音/金属笛検知 (非倍音成分 2-7kHz)", unit: "dB",
    run(d) {
      // Mask out normal harmonics k*f0 (±0.18*f0) in each voiced frame so flat-pitch speech never false-alarms,
      // while a true stationary non-harmonic whistle / metallic ring sticks out sharply above its ±450Hz neighborhood!
      const avg = new Float64Array(d.nBins);
      const cnt = new Int32Array(d.nBins);
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const md = d.magDb[t];
        for (let b = 0; b < d.nBins; b++) {
          const f = d.freqs[b];
          if (f < 1500 || f > 7500) continue;
          const harmDist = Math.abs(f / f0 - Math.round(f / f0));
          if (harmDist < 0.18) continue; // skip true pitch harmonics
          avg[b] += md[b]; cnt[b]++;
        }
      }
      for (let b = 0; b < d.nBins; b++) avg[b] = cnt[b] ? avg[b] / cnt[b] : -80.0;
      const df = d.freqs[1] - d.freqs[0] || 20.0;
      const winB = Math.max(3, Math.round(450 / df));
      let maxProm = 0.0;
      for (let b = 0; b < d.nBins; b++) {
        if (d.freqs[b] < 2000 || d.freqs[b] > 7000 || cnt[b] < 3) continue;
        let sum = 0.0, n = 0;
        for (let k = Math.max(0, b - winB); k <= Math.min(d.nBins - 1, b + winB); k++) {
          if (Math.abs(k - b) < 2 || cnt[k] < 3) continue;
          sum += avg[k]; n++;
        }
        const prom = avg[b] - sum / (n || 1);
        if (prom > maxProm) maxProm = prom;
      }
      return Number(maxProm.toFixed(2));
    },
  },
  {
    id: 16, key: "cliff_impulse_ratio", name: "1サンプル崖/クリック検知 (2階微分p99.98+孤立クリック/中央値)", unit: "ratio",
    run(d) {
      // Center-aligned active-frame baseline over voiced + unvoiced frames + all-sample isolated-impulse promotion
      // (catches edge clicks in leading/trailing silent margins attenuated by Hann win[0]=win[wl-1]=0).
      const x = d.x;
      const N = x.length;
      const d2Full = new Float64Array(N);
      const diffs = [];
      let maxD2 = 0.0;
      for (let i = 2; i < N; i++) {
        const v2 = Math.abs(x[i] - 2.0 * x[i - 1] + x[i - 2]);
        d2Full[i] = v2;
        if (v2 > maxD2) maxD2 = v2;
        const t = Math.max(0, Math.min(d.nFrames - 1, Math.round((i - 0.5 * d.wl) / d.hop)));
        if (d.rmsFr[t] > 0.012) {
          diffs.push(v2);
        }
      }
      if (diffs.length < 16) return 0.0;
      const med = median(diffs);
      if (med <= 1e-12) return maxD2 > 1e-9 ? 999.0 : 0.0;
      const pVal = percentile(diffs, 99.98);
      let bestD2 = pVal;
      const R = Math.max(16, Math.round(0.0015 * d.sr));
      const nb = [];
      for (let idx = 2; idx < N; idx++) {
        const v2 = d2Full[idx];
        const isLeftEdge = idx === 2 && Math.abs(x[0] - x[1]) >= 2.0 * Math.abs(x[1] - x[2]);
        const isRightEdge = idx === N - 1 && Math.abs(x[N - 1] - x[N - 2]) >= 2.0 * Math.abs(x[N - 2] - x[N - 3]);
        const effV2 = (isLeftEdge || isRightEdge) ? 2.0 * v2 : v2;
        if (effV2 <= pVal) continue;
        nb.length = 0;
        const lo = Math.max(2, idx - R);
        const hi = Math.min(N - 1, idx + R);
        for (let j = lo; j <= hi; j++) {
          if (Math.abs(j - idx) <= 2) continue;
          nb.push(d2Full[j]);
        }
        if (nb.length < 4) continue;
        nb.sort((a, b) => a - b);
        const nbP80 = nb[Math.min(nb.length - 1, Math.floor(0.80 * (nb.length - 1)))];
        if (v2 / Math.max(nbP80, 1e-12) >= 5.0 && effV2 > bestD2) bestD2 = effV2;
      }
      return Number(Math.min(999.0, bestD2 / med).toFixed(2));
    },
  },
  {
    id: 17, key: "phaser_notch_depth", name: "並列フェイザー/声道ノッチ深さ (ケプストラム包絡)", unit: "dB",
    run(d) {
      // Measures sharp dips on F0-stripped cepstral vocal-tract envelope (immune to normal F0 inter-harmonic valleys!)
      const df = d.freqs[1] - d.freqs[0] || 20.0;
      const span = Math.max(3, Math.round(450 / df));
      const frameMaxDips = [];
      for (let t = 0; t < d.nFrames; t++) {
        const e = d.envDb[t]; if (!e) continue;
        let mxDip = 0.0;
        for (let b = span; b < d.nBins - span; b++) {
          if (d.freqs[b] < 1500 || d.freqs[b] > 5500) continue;
          const shoulders = 0.5 * (e[b - span] + e[b + span]);
          const dip = shoulders - e[b];
          if (dip > mxDip) mxDip = dip;
        }
        frameMaxDips.push(mxDip);
      }
      return Number(median(frameMaxDips).toFixed(2));
    },
  },
  {
    id: 18, key: "interharm_grit_db", name: "倍音間ザラつき床 (2-5.5kHz半整数倍音)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const m = d.mag[t];
        let gritP = 0.0, harmP = 0.0;
        const k0 = Math.max(2, Math.ceil(2000 / f0)), k1 = Math.floor(5500 / f0);
        for (let k = k0; k < k1; k++) {
          const bH = Math.min(d.nBins - 1, Math.round((k * f0) / (d.freqs[1] || 20)));
          const bG = Math.min(d.nBins - 1, Math.round(((k + 0.5) * f0) / (d.freqs[1] || 20)));
          harmP += m[bH] * m[bH];
          gritP += m[bG] * m[bG];
        }
        if (harmP > 0) vals.push(10.0 * Math.log10((gritP + 1e-18) / (harmP + 1e-18)));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 19, key: "sub_f0_rumble_db", name: "F0以下超低域濁り (<0.75*F0)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const m = d.mag[t];
        let subP = 0.0, mainP = 0.0;
        for (let b = 1; b < d.nBins; b++) {
          const f = d.freqs[b], p = m[b] * m[b];
          if (f < 0.75 * f0) subP += p;
          else if (f >= 0.85 * f0 && f <= 2000) mainP += p;
        }
        if (mainP > 0) vals.push(10.0 * Math.log10((subP + 1e-18) / (mainP + 1e-18)));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 20, key: "buzzy_crest_db", name: "有声部クレスト比 (ジリジリ/潰れ検知)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const off = t * d.hop;
        let pk = 0.0, sq = 0.0;
        for (let i = 0; i < d.wl && off + i < d.x.length; i++) {
          const v = d.x[off + i], av = Math.abs(v);
          if (av > pk) pk = av;
          sq += v * v;
        }
        const rms = Math.sqrt(sq / d.wl) || 1e-9;
        if (pk > 0) vals.push(20.0 * Math.log10(pk / rms));
      }
      return Number(median(vals).toFixed(2));
    },
  },
];
