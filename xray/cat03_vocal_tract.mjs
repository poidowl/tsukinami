// xray/cat03_vocal_tract.mjs — 変態解析ツール #21〜#30: 声道・フォルマント・零点X線 (Cepstral Vocal-Tract Envelope)
import { median, percentile } from "./core.mjs";

function extractFormantTracks(d) {
  if (d._formants) return d._formants;
  const f1s = [], f2s = [], f3s = [], f2Seq = [];
  for (let t = 0; t < d.nFrames; t++) {
    const e = d.envDb[t];
    if (!e) { f2Seq.push(NaN); continue; }
    // Local peaks on smooth cepstral vocal-tract envelope
    const pks = [];
    for (let b = 2; b < d.nBins - 2; b++) {
      if (d.freqs[b] >= 280 && d.freqs[b] <= 4600 && e[b] > e[b - 1] && e[b] >= e[b + 1]) {
        pks.push({ f: d.freqs[b], v: e[b] });
      }
    }
    const c1 = pks.filter((p) => p.f >= 280 && p.f <= 1250);
    const f1 = c1.length ? c1.reduce((a, b) => (b.v > a.v ? b : a)).f : 550;
    const c2 = pks.filter((p) => p.f >= f1 + 320 && p.f <= 3100);
    const f2 = c2.length ? c2.reduce((a, b) => (b.v > a.v ? b : a)).f : 1650;
    const c3 = pks.filter((p) => p.f >= f2 + 350 && p.f <= 4400);
    const f3 = c3.length ? c3.reduce((a, b) => (b.v > a.v ? b : a)).f : 3100;
    f1s.push(f1); f2s.push(f2); f3s.push(f3); f2Seq.push(f2);
  }
  d._formants = { f1s, f2s, f3s, f2Seq };
  return d._formants;
}

function meanEnvBand(freqs, env, lo, hi) {
  let s = 0.0, n = 0;
  for (let b = 0; b < freqs.length; b++) {
    if (freqs[b] >= lo && freqs[b] <= hi) { s += env[b]; n++; }
  }
  return n ? s / n : 0.0;
}

export const CAT03_TOOLS = [
  {
    id: 21, key: "f1_median_hz", name: "F1中央値 (口の開き・ケプストラム包絡)", unit: "Hz",
    run: (d) => Math.round(median(extractFormantTracks(d).f1s)),
  },
  {
    id: 22, key: "f2_median_hz", name: "F2中央値 (舌の前後・笑顔声道)", unit: "Hz",
    run: (d) => Math.round(median(extractFormantTracks(d).f2s)),
  },
  {
    id: 23, key: "f3_median_hz", name: "F3中央値 (唇丸め/笑顔の明るさ)", unit: "Hz",
    run: (d) => Math.round(median(extractFormantTracks(d).f3s)),
  },
  {
    id: 24, key: "vtl_est_cm", name: "推定声道長 VTL (短いほど幼く可愛い)", unit: "cm",
    run(d) {
      const { f1s, f2s, f3s } = extractFormantTracks(d);
      const f1 = median(f1s), f2 = median(f2s), f3 = median(f3s);
      const df = 0.5 * ((f2 - f1) + (f3 - f2));
      return Number((35000.0 / (2.0 * Math.max(600.0, df))).toFixed(2));
    },
  },
  {
    id: 25, key: "vowel_space_span_hz", name: "母音空間広がり IQR(F1+F2) [IDS指標]", unit: "Hz",
    run(d) {
      const { f1s, f2s } = extractFormantTracks(d);
      const span = (percentile(f1s, 75) - percentile(f1s, 25)) + (percentile(f2s, 75) - percentile(f2s, 25));
      return Math.round(span);
    },
  },
  {
    id: 26, key: "smile_tract_index", name: "笑顔声道指数 (F2/F3口角リフト)", unit: "idx",
    run(d) {
      const { f2s, f3s } = extractFormantTracks(d);
      const idx = 0.6 * (median(f2s) / 1600.0) + 0.4 * (median(f3s) / 2900.0);
      return Number(idx.toFixed(3));
    },
  },
  {
    id: 27, key: "boxy_1k3_db", name: "1.1-1.5kHz 箱っぽさ/鼻づまり指数", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const e = d.envDb[t]; if (!e) continue;
        vals.push(meanEnvBand(d.freqs, e, 1100, 1500) - meanEnvBand(d.freqs, e, 500, 900));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 28, key: "epilaryngeal_3k_db", name: "3kHz 喉頭管キラキラ比 (2.6-3.7kHz)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const e = d.envDb[t]; if (!e) continue;
        vals.push(meanEnvBand(d.freqs, e, 2600, 3700) - meanEnvBand(d.freqs, e, 500, 1500));
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 29, key: "piriform_notch_db", name: "4.3kHz 梨状窩ノッチ深さ (倍音除去済)", unit: "dB",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t++) {
        const e = d.envDb[t]; if (!e) continue;
        const shL = meanEnvBand(d.freqs, e, 3100, 3700);
        const shR = meanEnvBand(d.freqs, e, 5000, 5600);
        const pit = meanEnvBand(d.freqs, e, 4100, 4700);
        vals.push(0.5 * (shL + shR) - pit);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 30, key: "formant_smoothness", name: "F2軌道なめらかさ (-median|ΔF2|)", unit: "Hz/fr",
    run(d) {
      const { f2Seq } = extractFormantTracks(d);
      const diffs = [];
      for (let t = 1; t < f2Seq.length; t++) {
        if (Number.isFinite(f2Seq[t]) && Number.isFinite(f2Seq[t - 1])) {
          diffs.push(Math.abs(f2Seq[t] - f2Seq[t - 1]));
        }
      }
      return Number((-median(diffs)).toFixed(1));
    },
  },
];
