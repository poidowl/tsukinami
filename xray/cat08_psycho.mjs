// xray/cat08_psycho.mjs — 変態解析ツール #71〜#80: 心理音響・聴覚モデル (Psychoacoustics & Perceptual)
import { median } from "./core.mjs";

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
    id: 75, key: "sensory_roughness", name: "感覚的粗さ Roughness (30-150Hz うなり)", unit: "idx",
    run(d) {
      // Hilbert-like rectified envelope modulation in 30-150Hz on voiced segments
      const step = Math.max(1, Math.trunc(d.sr / 1000)); // 1kHz envelope rate
      const env = [];
      for (let i = 0; i < d.x.length; i += step) env.push(Math.abs(d.x[i]));
      const N = env.length;
      if (N < 64) return 0.0;
      const m = env.reduce((a, b) => a + b, 0) / N;
      let acc = 0.0, cnt = 0;
      for (let f = 40; f <= 140; f += 20) {
        let cr = 0.0, ci = 0.0;
        for (let i = 0; i < N; i++) {
          const ang = (2.0 * Math.PI * f * i) / 1000.0;
          cr += (env[i] - m) * Math.cos(ang);
          ci += (env[i] - m) * Math.sin(ang);
        }
        acc += Math.hypot(cr, ci) / N;
        cnt++;
      }
      return Number(((acc / (cnt || 1)) * 1000.0).toFixed(2));
    },
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
