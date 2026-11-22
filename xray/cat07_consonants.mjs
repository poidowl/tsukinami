// xray/cat07_consonants.mjs — 変態解析ツール #61〜#70: 子音・共調音・レガート解析 (Consonants, Coarticulation & Flow)
import { median, percentile } from "./core.mjs";

function modSpectrum(d) {
  if (d._modSpec) return d._modSpec;
  const env = new Float64Array(d.nFrames);
  let mean = 0.0;
  for (let t = 0; t < d.nFrames; t++) {
    const v = 20.0 * Math.log10(d.rmsFr[t] + 1e-6);
    env[t] = v; mean += v;
  }
  mean /= d.nFrames || 1;
  const dt = d.hop / d.sr;
  const freqs = [];
  const amps = [];
  for (let f = 1.0; f <= 25.0; f += 0.5) {
    let cr = 0.0, ci = 0.0;
    for (let t = 0; t < d.nFrames; t++) {
      const w = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * t) / Math.max(1, d.nFrames - 1));
      const ang = 2.0 * Math.PI * f * t * dt;
      const val = (env[t] - mean) * w;
      cr += val * Math.cos(ang);
      ci += val * Math.sin(ang);
    }
    freqs.push(f);
    amps.push(Math.hypot(cr, ci) / (d.nFrames || 1));
  }
  d._modSpec = { freqs, amps };
  return d._modSpec;
}

function frameFluxes(d) {
  if (d._fluxes) return d._fluxes;
  const out = [];
  for (let t = 1; t < d.nFrames; t++) {
    let s = 0.0;
    const a = d.magDb[t], b = d.magDb[t - 1];
    for (let k = 0; k < d.nBins; k++) s += Math.abs(a[k] - b[k]);
    out.push(s / (d.nBins || 1));
  }
  d._fluxes = out;
  return out;
}

function isFricFrame(d, t) {
  if (d.f0Hz[t] > 0 || d.rmsFr[t] < 0.012) return false;
  let hi = 0.0, lo = 0.0;
  for (let b = 0; b < d.nBins; b++) {
    const p = d.mag[t][b] * d.mag[t][b];
    if (d.freqs[b] >= 3000) hi += p;
    else if (d.freqs[b] >= 200 && d.freqs[b] < 2000) lo += p;
  }
  return hi > lo * 1.5;
}

export const CAT07_TOOLS = [
  {
    id: 61, key: "fric_brick_slope", name: "摩擦音レンガ壁スコア (無声高域の立ち上がり急峻度)", unit: "dB/5ms",
    run(d) {
      const jumps = [];
      for (let t = 1; t < d.nFrames; t++) {
        if (isFricFrame(d, t) && !isFricFrame(d, t - 1)) {
          const j = 20.0 * Math.log10((d.rmsFr[t] + 1e-6) / (d.rmsFr[t - 1] + 1e-6));
          if (j > 0) jumps.push(j);
        }
      }
      return Number(median(jumps).toFixed(2));
    },
  },
  {
    id: 62, key: "fric_low_leak_db", name: "摩擦音の低域漏れ (<2.5kHz / 3-8kHz)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!isFricFrame(d, t)) continue;
        let lo = 0.0, hi = 0.0;
        for (let b = 0; b < d.nBins; b++) {
          const p = d.mag[t][b] * d.mag[t][b];
          if (d.freqs[b] >= 400 && d.freqs[b] < 2500) lo += p;
          else if (d.freqs[b] >= 3000 && d.freqs[b] <= 8000) hi += p;
        }
        vals.push(10.0 * Math.log10((lo + 1e-18) / (hi + 1e-18)));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 63, key: "flux_p50_db", name: "スペクトルフラックス中央値", unit: "dB/fr",
    run: (d) => Number(percentile(frameFluxes(d), 50).toFixed(2)),
  },
  {
    id: 64, key: "flux_p95_db", name: "スペクトルフラックス p95 (子音破裂の鋭さ)", unit: "dB/fr",
    run: (d) => Number(percentile(frameFluxes(d), 95).toFixed(2)),
  },
  {
    id: 65, key: "spec_smoothness", name: "時間方向スペクトル滑らかさ (-mean|Δmag|)", unit: "-dB/fr",
    run(d) {
      const fl = frameFluxes(d);
      const m = fl.reduce((a, b) => a + b, 0) / (fl.length || 1);
      return Number((-m).toFixed(3));
    },
  },
  {
    id: 66, key: "mod_3_8hz", name: "変調スペクトル 3-8Hz (音節レガート度)", unit: "dB-mod",
    run(d) {
      const { freqs, amps } = modSpectrum(d);
      let s = 0.0, n = 0;
      for (let i = 0; i < freqs.length; i++) if (freqs[i] >= 3.0 && freqs[i] <= 8.0) { s += amps[i]; n++; }
      return Number((s / (n || 1)).toFixed(3));
    },
  },
  {
    id: 67, key: "mod_10_22hz", name: "変調スペクトル 10-22Hz (微細ブツ切り度)", unit: "dB-mod",
    run(d) {
      const { freqs, amps } = modSpectrum(d);
      let s = 0.0, n = 0;
      for (let i = 0; i < freqs.length; i++) if (freqs[i] >= 10.0 && freqs[i] <= 22.0) { s += amps[i]; n++; }
      return Number((s / (n || 1)).toFixed(3));
    },
  },
  {
    id: 68, key: "cv_attack_ms", name: "子音->母音 遷移時間 (共調音幅)", unit: "ms",
    run(d) {
      const durs = [];
      for (let t = 1; t < d.nFrames; t++) {
        if (isFricFrame(d, t) && !isFricFrame(d, t - 1)) {
          let k = t;
          while (k < d.nFrames && d.f0Hz[k] === 0 && (k - t) < 40) k++;
          if (k < d.nFrames && d.f0Hz[k] > 0) durs.push((k - t) * 5.0);
        }
      }
      return Number(median(durs).toFixed(1));
    },
  },
  {
    id: 69, key: "voiced_duty_pct", name: "有声デューティ比 (発話の密度)", unit: "%",
    run(d) {
      let vo = 0;
      for (let t = 0; t < d.nFrames; t++) if (d.f0Hz[t] > 0) vo++;
      return Number(((100.0 * vo) / (d.nFrames || 1)).toFixed(1));
    },
  },
  {
    id: 70, key: "syllable_rate_hz", name: "推定音節レート (変調ピーク周波数)", unit: "Hz",
    run(d) {
      const { freqs, amps } = modSpectrum(d);
      let bestF = 4.0, bestA = -1.0;
      for (let i = 0; i < freqs.length; i++) {
        if (freqs[i] >= 2.0 && freqs[i] <= 9.0 && amps[i] > bestA) { bestA = amps[i]; bestF = freqs[i]; }
      }
      return Number(bestF.toFixed(1));
    },
  },
];
