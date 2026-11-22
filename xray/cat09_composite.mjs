// xray/cat09_composite.mjs — 変態解析ツール #81〜#90: 総合スコア・不気味の谷・A/B差分距離 (Composite & Differential)

function clamp01(v) { return Math.max(0.0, Math.min(1.0, v)); }
function bandScore(v, lo, hi, margin) {
  if (v >= lo && v <= hi) return 1.0;
  const dist = v < lo ? (lo - v) : (v - hi);
  return clamp01(1.0 - dist / (margin || 1.0));
}

function ltas16(d) {
  if (d._ltas16) return d._ltas16;
  const bands = new Float64Array(16);
  const cnts = new Int32Array(16);
  for (let t = 0; t < d.nFrames; t++) {
    if (!d.f0Hz[t]) continue;
    const md = d.magDb[t];
    for (let b = 0; b < d.nBins; b++) {
      const bi = Math.min(15, Math.floor(d.freqs[b] / 500));
      bands[bi] += md[b]; cnts[bi]++;
    }
  }
  for (let i = 0; i < 16; i++) bands[i] = cnts[i] ? bands[i] / cnts[i] : -80.0;
  const ref0 = 0.5 * (bands[0] + bands[1]);
  for (let i = 0; i < 16; i++) bands[i] -= ref0;
  d._ltas16 = bands;
  return bands;
}

function envBins(d, nBins = 120) {
  const out = new Float64Array(nBins);
  for (let i = 0; i < nBins; i++) {
    const t = Math.min(d.nFrames - 1, Math.floor((i / nBins) * d.nFrames));
    out[i] = 20.0 * Math.log10(d.rmsFr[t] + 1e-6);
  }
  return out;
}

export const CAT09_TOOLS = [
  {
    id: 81, key: "kawaii_overall_100", name: "総合カワイイスコア (0-100)", unit: "pts",
    run(d, ctx) {
      const m = ctx?.metrics || {};
      const sPitch = bandScore(m.f0_mean_hz ?? 330, 300, 420, 120);
      const sRange = bandScore(m.f0_range_st ?? 10, 8, 16, 6);
      const sEpi = bandScore(m.epilaryngeal_3k_db ?? -12, -14, -7, 10);
      const sVbr = clamp01((m.voiced_breath_ratio ?? 0.5) / 0.85);
      const sSharp = bandScore(m.zwicker_sharpness ?? 1.5, 1.35, 1.75, 0.6);
      const sHnr = bandScore(m.hnr_mid_db ?? 30, 26, 40, 12);
      const sClean = 1.0 - clamp01(((m.fixed_whistle_db ?? 5) - 5.5) / 3.0);
      const score = 100.0 * (0.16 * sPitch + 0.14 * sRange + 0.20 * sEpi + 0.15 * sVbr + 0.15 * sSharp + 0.10 * sHnr + 0.10 * sClean);
      return Number(score.toFixed(1));
    },
  },
  {
    id: 82, key: "uncanny_synth_100", name: "シンセ臭/不気味の谷スコア (低いほど生人間!)", unit: "pts",
    run(d, ctx) {
      const m = ctx?.metrics || {};
      const lockPen = clamp01(((m.harm_phase_lock ?? 0.99) - 0.90) / 0.10);
      const cycPen = clamp01(((m.cycle_similarity ?? 0.98) - 0.92) / 0.08);
      const brickPen = clamp01(((m.fric_brick_slope ?? 3) - 3.0) / 5.0);
      const whistlePen = clamp01(((m.fixed_whistle_db ?? 5) - 5.2) / 3.0);
      const flatAirPen = 1.0 - bandScore(m.sfm_4_8k ?? 0.35, 0.30, 0.58, 0.25);
      const score = 100.0 * (0.30 * lockPen + 0.20 * cycPen + 0.15 * brickPen + 0.20 * whistlePen + 0.15 * flatAirPen);
      return Number(score.toFixed(1));
    },
  },
  {
    id: 83, key: "artifact_risk_100", name: "異音リスク総合警報 (0=完全無臭 / 100=危険)", unit: "pts",
    run(d, ctx) {
      const m = ctx?.metrics || {};
      const pWhistle = clamp01(((m.fixed_whistle_db ?? 5) - 5.2) / 2.5);
      const pFatigue = clamp01(((m.ear_fatigue_db ?? -11) - (-9.5)) / 7.5);
      const pSharp = clamp01(((m.close_sharpness ?? 3.0) - 3.15) / 0.8);
      const pPiercing = clamp01(((m.zwicker_sharpness ?? 1.5) - 1.75) / 0.6);
      const pRumble = clamp01(((m.sub_f0_rumble_db ?? -40) - (-32.0)) / 12.0);
      const score = 100.0 * (0.30 * pWhistle + 0.25 * pFatigue + 0.20 * pSharp + 0.15 * pPiercing + 0.10 * pRumble);
      return Number(score.toFixed(1));
    },
  },
  {
    id: 84, key: "anime_modern_100", name: "現代アニメヒロイン度 (Utsugi+/Ishi+ 2026)", unit: "pts",
    run(d, ctx) {
      const m = ctx?.metrics || {};
      const sTilt = bandScore(m.spec_tilt_dboct ?? -5.5, -6.5, -4.0, 3.0);
      const sNonM = bandScore(m.nonmodal_frame_pct ?? 20, 14, 30, 12);
      const sVbr = clamp01((m.voiced_breath_ratio ?? 0.8) / 0.85);
      const sEpi = bandScore(m.epilaryngeal_3k_db ?? -11, -14, -7, 8);
      const sInh = clamp01((m.voiced_inhale_cnt ?? 2) / 3.0);
      return Number((100.0 * (0.25 * sTilt + 0.20 * sNonM + 0.25 * sVbr + 0.20 * sEpi + 0.10 * sInh)).toFixed(1));
    },
  },
  {
    id: 85, key: "sweet_voice_100", name: "スイートボイス度 (Starr 2015)", unit: "pts",
    run(d, ctx) {
      const m = ctx?.metrics || {};
      const sOnset = bandScore(m.onset_rise_ms ?? 30, 22, 50, 20);
      const sScoop = clamp01(((m.final_scoop_st ?? 0.8) + 0.2) / 1.4);
      const sSmile = bandScore(m.smile_tract_index ?? 1.15, 1.05, 1.25, 0.25);
      const sWarm = bandScore(m.warmth_db ?? 24, 18, 28, 10);
      const sLeak = clamp01(((-14.0) - (m.fric_low_leak_db ?? -18)) / 6.0);
      return Number((100.0 * (0.20 * sOnset + 0.25 * sScoop + 0.20 * sSmile + 0.20 * sWarm + 0.15 * sLeak)).toFixed(1));
    },
  },
  {
    id: 86, key: "lsd_vs_first_db", name: "vs基準ファイル Log-Spectral Distance (LSD)", unit: "dB",
    run(d, ctx) {
      if (!ctx?.ref || ctx.ref === d) return 0.0;
      const a = ltas16(d), b = ltas16(ctx.ref);
      let sq = 0.0;
      for (let i = 0; i < 16; i++) { const diff = a[i] - b[i]; sq += diff * diff; }
      return Number(Math.sqrt(sq / 16.0).toFixed(2));
    },
  },
  {
    id: 87, key: "ltas_l1_vs_first", name: "vs基準ファイル 500Hz帯LTAS平均差 (L1)", unit: "dB",
    run(d, ctx) {
      if (!ctx?.ref || ctx.ref === d) return 0.0;
      const a = ltas16(d), b = ltas16(ctx.ref);
      let s = 0.0;
      for (let i = 0; i < 16; i++) s += Math.abs(a[i] - b[i]);
      return Number((s / 16.0).toFixed(2));
    },
  },
  {
    id: 88, key: "mcd_vs_first_db", name: "vs基準ファイル ケプストラム包絡距離 (MCD近似)", unit: "dB",
    run(d, ctx) {
      if (!ctx?.ref || ctx.ref === d) return 0.0;
      const avgEnv = (obj) => {
        const out = new Float64Array(32);
        let cnt = 0;
        for (let t = 0; t < obj.nFrames; t++) {
          const e = obj.envDb[t]; if (!e) continue;
          for (let k = 0; k < 32; k++) {
            const bi = Math.min(e.length - 1, Math.floor((k / 32) * e.length));
            out[k] += e[bi];
          }
          cnt++;
        }
        for (let k = 0; k < 32; k++) out[k] /= cnt || 1;
        return out;
      };
      const a = avgEnv(d), b = avgEnv(ctx.ref);
      let sq = 0.0;
      for (let k = 1; k < 32; k++) { const diff = a[k] - b[k]; sq += diff * diff; }
      return Number(Math.sqrt(sq / 31.0).toFixed(2));
    },
  },
  {
    id: 89, key: "env_corr_vs_first", name: "vs基準ファイル 時間包絡相関 r", unit: "r",
    run(d, ctx) {
      if (!ctx?.ref || ctx.ref === d) return 1.0;
      const a = envBins(d), b = envBins(ctx.ref);
      let ma = 0.0, mb = 0.0;
      for (let i = 0; i < a.length; i++) { ma += a[i]; mb += b[i]; }
      ma /= a.length; mb /= b.length;
      let num = 0.0, da = 0.0, db = 0.0;
      for (let i = 0; i < a.length; i++) {
        const xa = a[i] - ma, xb = b[i] - mb;
        num += xa * xb; da += xa * xa; db += xb * xb;
      }
      return Number((num / (Math.sqrt(da * db) || 1e-12)).toFixed(3));
    },
  },
  {
    id: 90, key: "artifact_delta", name: "vs基準ファイル 異音リスク改善デルタ (負=改善!)", unit: "pts",
    run(d, ctx) {
      if (!ctx?.refMetrics || ctx.ref === d) return 0.0;
      const cur = ctx.metrics.artifact_risk_100 ?? 0.0;
      const base = ctx.refMetrics.artifact_risk_100 ?? 0.0;
      return Number((cur - base).toFixed(1));
    },
  },
];
