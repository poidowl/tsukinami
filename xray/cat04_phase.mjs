// xray/cat04_phase.mjs — 変態解析ツール #31〜#40: 位相・分散・時間微細構造 (Phase & Micro-Timing)
import { median } from "./core.mjs";

function unwrap1D(arr) {
  const out = new Float64Array(arr.length);
  if (!arr.length) return out;
  out[0] = arr[0];
  let offset = 0.0;
  for (let i = 1; i < arr.length; i++) {
    let d = arr[i] - arr[i - 1];
    if (d > Math.PI) offset -= 2.0 * Math.PI;
    else if (d < -Math.PI) offset += 2.0 * Math.PI;
    out[i] = arr[i] + offset;
  }
  return out;
}

function stdOf(vals) {
  if (vals.length < 2) return 0.0;
  let m = 0.0;
  for (let i = 0; i < vals.length; i++) m += vals[i];
  m /= vals.length;
  let v = 0.0;
  for (let i = 0; i < vals.length; i++) { const d = vals[i] - m; v += d * d; }
  return Math.sqrt(v / vals.length);
}

function phaseDiffStd(d, fLo, fHi) {
  const diffs = [];
  for (let b = 0; b < d.nBins; b++) {
    if (d.freqs[b] < fLo || d.freqs[b] > fHi) continue;
    const col = new Float64Array(d.nFrames);
    for (let t = 0; t < d.nFrames; t++) col[t] = d.phase[t][b];
    const uw = unwrap1D(col);
    for (let t = 1; t < d.nFrames; t++) diffs.push(uw[t] - uw[t - 1]);
  }
  return stdOf(diffs);
}

export const CAT04_TOOLS = [
  {
    id: 31, key: "phase_stability", name: "瞬時位相安定度 (-std dφ/dt)", unit: "-rad",
    run: (d) => Number((-phaseDiffStd(d, 0, 8000)).toFixed(3)),
  },
  {
    id: 32, key: "phase_stability_hi", name: "高域(3-7kHz)位相安定度", unit: "-rad",
    run: (d) => Number((-phaseDiffStd(d, 3000, 7000)).toFixed(3)),
  },
  {
    id: 33, key: "group_delay_std", name: "群遅延ゆらぎ (周波数方向位相微分std)", unit: "rad",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const uw = unwrap1D(d.phase[t]);
        const gd = [];
        for (let b = 1; b < d.nBins; b++) {
          if (d.freqs[b] >= 300 && d.freqs[b] <= 5500) gd.push(uw[b] - uw[b - 1]);
        }
        vals.push(stdOf(gd));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 34, key: "harm_phase_lock", name: "倍音位相ロック度 (1=完全周期/0=ノイズ)", unit: "0..1",
    run(d) {
      const df = d.freqs[1] - d.freqs[0] || 20.0;
      const locks = [];
      for (let t = 2; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t];
        if (!f0 || !d.f0Hz[t - 1] || !d.f0Hz[t - 2]) continue;
        let cSum = 0.0, sSum = 0.0, cnt = 0;
        for (let k = 1; k <= 8; k++) {
          const b = Math.round((k * f0) / df);
          if (b >= d.nBins) break;
          const d2 = d.phase[t][b] - 2.0 * d.phase[t - 1][b] + d.phase[t - 2][b];
          cSum += Math.cos(d2); sSum += Math.sin(d2); cnt++;
        }
        if (cnt) locks.push(Math.hypot(cSum, sSum) / cnt);
      }
      return Number(median(locks).toFixed(3));
    },
  },
  {
    id: 35, key: "inst_freq_jitter_hz", name: "H1瞬時周波数ジッタ", unit: "Hz",
    run(d) {
      const df = d.freqs[1] - d.freqs[0] || 20.0;
      const dt = d.hop / d.sr;
      const jits = [];
      let prevIf = NaN;
      for (let t = 1; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t];
        if (!f0 || !d.f0Hz[t - 1]) { prevIf = NaN; continue; }
        const b = Math.min(d.nBins - 1, Math.round(f0 / df));
        let dphi = d.phase[t][b] - d.phase[t - 1][b];
        while (dphi > Math.PI) dphi -= 2.0 * Math.PI;
        while (dphi < -Math.PI) dphi += 2.0 * Math.PI;
        const instF = d.freqs[b] + dphi / (2.0 * Math.PI * dt);
        if (Number.isFinite(prevIf)) jits.push(Math.abs(instF - prevIf));
        prevIf = instF;
      }
      return Number(median(jits).toFixed(2));
    },
  },
  {
    id: 36, key: "phase_disp_ratio", name: "高域/低域の位相分散比 (軟組織分散)", unit: "ratio",
    run(d) {
      const lo = phaseDiffStd(d, 200, 1500) || 1e-6;
      const hi = phaseDiffStd(d, 3000, 7000);
      return Number((hi / lo).toFixed(3));
    },
  },
  {
    id: 37, key: "waveform_skewness", name: "有声波形の非対称度 (Skewness)", unit: "skew",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const off = t * d.hop;
        let m2 = 0.0, m3 = 0.0;
        for (let i = 0; i < d.wl && off + i < d.x.length; i++) {
          const v = d.x[off + i];
          m2 += v * v; m3 += v * v * v;
        }
        const s = Math.sqrt(m2 / d.wl) || 1e-9;
        vals.push((m3 / d.wl) / (s * s * s));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 38, key: "waveform_kurtosis", name: "有声波形の尖度 (Kurtosis: 3=正規)", unit: "kurt",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const off = t * d.hop;
        let m2 = 0.0, m4 = 0.0;
        for (let i = 0; i < d.wl && off + i < d.x.length; i++) {
          const v = d.x[off + i], v2 = v * v;
          m2 += v2; m4 += v2 * v2;
        }
        const v2m = (m2 / d.wl) || 1e-12;
        vals.push((m4 / d.wl) / (v2m * v2m));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 39, key: "cycle_similarity", name: "ピッチ周期再現率 R(T0) (ロボ度/自然度)", unit: "0..1",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const lag = Math.round(d.sr / f0);
        const off = t * d.hop;
        let num = 0.0, d1 = 0.0, d2 = 0.0;
        for (let i = 0; i < d.wl - lag && off + i + lag < d.x.length; i++) {
          const a = d.x[off + i], b = d.x[off + i + lag];
          num += a * b; d1 += a * a; d2 += b * b;
        }
        vals.push(num / (Math.sqrt(d1 * d2) || 1e-12));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 40, key: "zcr_regularity", name: "有声ゼロ交差安定度 (-std ZCR)", unit: "-rate",
    run(d) {
      const zcrs = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const off = t * d.hop;
        let zc = 0;
        for (let i = 1; i < d.wl && off + i < d.x.length; i++) {
          if ((d.x[off + i] >= 0) !== (d.x[off + i - 1] >= 0)) zc++;
        }
        zcrs.push(zc / d.wl);
      }
      return Number((-stdOf(zcrs)).toFixed(4));
    },
  },
];
