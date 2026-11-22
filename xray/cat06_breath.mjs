// xray/cat06_breath.mjs — 変態解析ツール #51〜#60: 息・吐息・有声息吸い (Breath, Sigh & Voiced Inhalation)
import { median, percentile } from "./core.mjs";

function frameSfm(freqs, mag, fLo, fHi) {
  let logSum = 0.0, linSum = 0.0, n = 0;
  for (let b = 0; b < freqs.length; b++) {
    if (freqs[b] >= fLo && freqs[b] <= fHi) {
      const v = mag[b] + 1e-12;
      logSum += Math.log(v);
      linSum += v;
      n++;
    }
  }
  return n ? Math.exp(logSum / n) / (linSum / n + 1e-12) : 0.0;
}

function frameLocalHnr(freqs, magDb, f0, fLo = 200, fHi = 3000) {
  const k0 = Math.max(1, Math.ceil(fLo / f0)), k1 = Math.floor(fHi / f0);
  const diffs = [];
  for (let k = k0; k < k1; k++) {
    let pMax = -Infinity, vMin = Infinity, hp = false, hv = false;
    const pLo = (k - 0.2) * f0, pHi = (k + 0.2) * f0;
    const vLo = (k + 0.3) * f0, vHi = (k + 0.7) * f0;
    for (let b = 0; b < freqs.length; b++) {
      const f = freqs[b];
      if (f >= pLo && f <= pHi) { if (magDb[b] > pMax) pMax = magDb[b]; hp = true; }
      if (f >= vLo && f <= vHi) { if (magDb[b] < vMin) vMin = magDb[b]; hv = true; }
    }
    if (hp && hv) diffs.push(pMax - vMin);
  }
  return diffs.length ? diffs.reduce((a, b) => a + b, 0) / diffs.length : 0.0;
}

export const CAT06_TOOLS = [
  {
    id: 51, key: "voiced_inhale_cnt", name: "有声の息吸い検知 (Ishi+ 2026 発話前ブレス)", unit: "cnt",
    run(d) {
      // Detect soft breath-in energy (-38..-14dB of voiced RMS) in the 20..120ms window right before voiced phrase starts
      let vSum = 0.0, vCnt = 0;
      for (let t = 0; t < d.nFrames; t++) if (d.f0Hz[t] > 0) { vSum += d.rmsFr[t]; vCnt++; }
      const vRms = vSum / (vCnt || 1);
      let cnt = 0;
      for (let t = 18; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0 && d.f0Hz[t - 1] === 0 && d.f0Hz[t - 2] === 0 && d.f0Hz[t - 3] === 0) {
          let prePk = 0.0, hasAir = false;
          for (let k = t - 18; k < t - 2; k++) {
            if (d.rmsFr[k] > prePk) prePk = d.rmsFr[k];
            if (d.rmsFr[k] > vRms * 0.012 && frameSfm(d.freqs, d.mag[k], 2500, 7000) > 0.35) hasAir = true;
          }
          if (hasAir && prePk >= vRms * 0.012 && prePk <= vRms * 0.25) cnt++;
        }
      }
      return cnt;
    },
  },
  {
    id: 52, key: "nonmodal_frame_pct", name: "局所的非モーダル声質率 (Ishi+ 2026)", unit: "%",
    run(d) {
      const hnrs = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0) hnrs.push(frameLocalHnr(d.freqs, d.magDb[t], d.f0Hz[t], 200, 3000));
      }
      if (!hnrs.length) return 0.0;
      const med = median(hnrs);
      const nonModal = hnrs.filter((v) => v < med - 6.0).length;
      return Number(((100.0 * nonModal) / hnrs.length).toFixed(1));
    },
  },
  {
    id: 53, key: "tail_sigh_decay_db", name: "句末吐息の谷浅化 (コアHNR - 語尾HNR)", unit: "dB",
    run(d) {
      const decays = [];
      let seg = [];
      const evalSeg = (s) => {
        if (s.length < 12) return;
        const core = s.slice(2, Math.floor(s.length * 0.55));
        const tail = s.slice(Math.floor(s.length * 0.70));
        if (core.length && tail.length) decays.push(median(core) - median(tail));
      };
      for (let t = 0; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0) seg.push(frameLocalHnr(d.freqs, d.magDb[t], d.f0Hz[t], 200, 3500));
        else { evalSeg(seg); seg = []; }
      }
      evalSeg(seg);
      return Number(median(decays).toFixed(2));
    },
  },
  {
    id: 54, key: "pause_breath_db", name: "ポーズ息床レベル (有声RMS比)", unit: "dB",
    run(d) {
      const vR = [], pR = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0) vR.push(d.rmsFr[t]);
        else if (d.rmsFr[t] < 0.02) pR.push(d.rmsFr[t]);
      }
      if (!vR.length || !pR.length) return -60.0;
      return Number((20.0 * Math.log10((median(pR) + 1e-6) / (median(vR) + 1e-6))).toFixed(1));
    },
  },
  {
    id: 55, key: "sfm_4_8k", name: "4-8kHz スペクトル平坦度 (0=純倍音/1=息)", unit: "0..1",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0) vals.push(frameSfm(d.freqs, d.mag[t], 4000, 8000));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 56, key: "asp_to_harm_db", name: "有声気息対倍音比 (3.5-7.5k / 0.3-2.5k)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const m = d.mag[t];
        let loP = 0.0, hiP = 0.0;
        for (let b = 0; b < d.nBins; b++) {
          const f = d.freqs[b], p = m[b] * m[b];
          if (f >= 300 && f <= 2500) loP += p;
          else if (f >= 3500 && f <= 7500) hiP += p;
        }
        vals.push(10.0 * Math.log10((hiP + 1e-18) / (loP + 1e-18)));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 57, key: "voiced_breath_ratio", name: "有声気息キープ率 (息帯で声帯が鳴ってる割合)", unit: "0..1",
    run(d) {
      let airTot = 0, airVo = 0;
      for (let t = 0; t < d.nFrames; t++) {
        if (d.rmsFr[t] < 0.015) continue;
        const sfm = frameSfm(d.freqs, d.mag[t], 3500, 7500);
        if (sfm > 0.45) {
          airTot++;
          if (d.f0Hz[t] > 0) airVo++;
        }
      }
      return airTot ? Number((airVo / airTot).toFixed(3)) : 0.0;
    },
  },
  {
    id: 58, key: "breath_centroid_hz", name: "高域気息の重心周波数 (2.5-8kHz)", unit: "Hz",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        const m = d.mag[t];
        let num = 0.0, den = 0.0;
        for (let b = 0; b < d.nBins; b++) {
          if (d.freqs[b] >= 2500 && d.freqs[b] <= 8000) {
            num += d.freqs[b] * m[b];
            den += m[b];
          }
        }
        if (den > 0) vals.push(num / den);
      }
      return Math.round(median(vals));
    },
  },
  {
    id: 59, key: "offset_tail_ms", name: "語尾フェード長 (80%->15%減衰時間)", unit: "ms",
    run(d) {
      const fades = [];
      for (let t = 4; t < d.nFrames - 1; t++) {
        if (d.f0Hz[t] > 0 && d.f0Hz[t + 1] === 0) {
          let pk = 0.0;
          for (let k = Math.max(0, t - 12); k <= t; k++) if (d.rmsFr[k] > pk) pk = d.rmsFr[k];
          let t80 = t, t15 = t;
          while (t80 > Math.max(0, t - 12) && d.rmsFr[t80] < 0.80 * pk) t80--;
          while (t15 < Math.min(d.nFrames - 1, t + 18) && d.rmsFr[t15] > 0.15 * pk) t15++;
          fades.push((t15 - t80) * 5.0);
        }
      }
      return Number(median(fades).toFixed(1));
    },
  },
  {
    id: 60, key: "breath_dynamics_db", name: "息ダイナミクス幅 (4-8kHz p90-p10)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        let hiP = 0.0;
        for (let b = 0; b < d.nBins; b++) if (d.freqs[b] >= 4000 && d.freqs[b] <= 8000) hiP += d.mag[t][b] * d.mag[t][b];
        vals.push(10.0 * Math.log10(hiP + 1e-18));
      }
      if (vals.length < 4) return 0.0;
      return Number((percentile(vals, 90) - percentile(vals, 10)).toFixed(2));
    },
  },
];
