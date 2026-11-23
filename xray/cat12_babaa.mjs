/**
 * xray/cat12_babaa.mjs — Category 12: ババア検知20連センサー (#111–#130)
 *
 * 「若い声を当てる」のではなく「加齢声帯 (Presbyphonia)・喉頭下垂・大御所貫禄・
 *  乾燥カスレの20個の地雷」に引っかからない声を『若い』と定義する反証型センサー群。
 *
 * 各センサーは 0..100 のババア危険度 (0=完全10代クリア / 50+=警報点灯 / 100=紫綬褒章) を返す。
 * #130 は #111..#129 の19センサーの平均ババア度 (0..100) と警報発火数を集約する。
 */
import { median } from "./core.mjs";

const clamp = (v, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, v));
// Linear risk ramp: <= ok -> 0, >= bad -> 100
const rampUp = (v, ok, bad) => Number(clamp(((v - ok) / (bad - ok)) * 100).toFixed(1));
const rampDn = (v, ok, bad) => Number(clamp(((ok - v) / (ok - bad)) * 100).toFixed(1));

function voicedBandDb(d, fLo, fHi) {
  let sum = 0, cnt = 0;
  for (let t = 0; t < d.nFrames; t++) {
    if (!d.f0Hz[t]) continue;
    let p = 0, n = 0;
    for (let k = 0; k < d.nBins; k++) {
      if (d.freqs[k] >= fLo && d.freqs[k] < fHi) {
        p += Math.pow(10, d.magDb[t][k] / 10);
        n++;
      }
    }
    if (n) { sum += 10 * Math.log10(p / n + 1e-12); cnt++; }
  }
  return cnt ? sum / cnt : -90;
}

// 2-4Hz slow tremor (vocal aging / presbyphonia tremor vs youthful 5-7Hz vibrato)
function tremor2to4Hz(d) {
  const env = [];
  for (let t = 0; t < d.nFrames; t++) {
    if (!d.f0Hz[t]) continue;
    env.push(d.rmsFr[t]);
  }
  if (env.length < 64) return 0.0; // require >= 320ms voiced speech
  const N = env.length;
  const mean = env.reduce((a, b) => a + b, 0) / N || 1e-9;
  const wNorm = new Float64Array(N);
  let wSum = 0.0, wSq = 0.0, acSq = 0.0;
  for (let i = 0; i < N; i++) {
    const w = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * i) / (N - 1));
    const v = (env[i] - mean) / mean;
    wNorm[i] = v * w;
    wSum += w;
    wSq += w * w;
    acSq += v * v * w * w;
  }
  const acRms = Math.sqrt(acSq / (wSq || 1.0) + 1e-12);
  const fps = d.sr / d.hop;
  let maxDepth = 0.0;
  for (let f = 2.0; f <= 4.0; f += 0.25) {
    let re = 0.0, im = 0.0;
    for (let i = 0; i < N; i++) {
      const ang = (2.0 * Math.PI * f * i) / fps;
      re += wNorm[i] * Math.cos(ang);
      im -= wNorm[i] * Math.sin(ang);
    }
    const depth = (2.0 * Math.hypot(re, im)) / (wSum || 1.0);
    if (depth > maxDepth) maxDepth = depth;
  }
  const purity = Math.min(1.0, (maxDepth / Math.SQRT2) / (acRms + 1e-9));
  return maxDepth * purity * purity;
}

const INDIVIDUAL_SENSORS = [
  // === 群A: 声道・骨格の加齢 (喉頭下垂・低域の重さ・高域くすみ) ===
  {
    id: 111, key: "bb_low_heavy", name: "[ババア01] 200-600Hz低域の重さ (貫禄/胸声)", unit: "risk",
    run(d, { metrics: m }) { return rampUp(m.warmth_db ?? 22, 24.5, 36.0); },
  },
  {
    id: 112, key: "bb_hi_dim", name: "[ババア02] 高域くすみ/ギラつき逸脱 (光の矢バランス)", unit: "risk",
    run(d, { metrics: m }) {
      const dim = rampDn(m.erb_hi_mid_db ?? -18, -20.5, -27.0);
      const glare = rampUp(m.brightness_db ?? -7.5, -5.0, -1.5);
      return Number(Math.max(dim, glare).toFixed(1));
    },
  },
  {
    id: 113, key: "bb_dull_sharp", name: "[ババア03] Zwicker鋭さ不足 (ハリ喪失)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.zwicker_sharpness ?? 1.7, 1.60, 1.15); },
  },
  {
    id: 114, key: "bb_adult_f3", name: "[ババア04] 喉頭下垂・大人F3 (<3500Hz)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.f3_median_hz ?? 3800, 3650, 2950); },
  },
  {
    id: 115, key: "bb_closed_f1", name: "[ババア05] 口閉じ落ち着きF1 (<575Hz)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.f1_median_hz ?? 620, 580, 480); },
  },
  {
    id: 116, key: "bb_nasal_2k", name: "[ババア06] 1.8-2.6kHz 電話/舞台鼻声山", unit: "risk",
    run(d) {
      const b2k = voicedBandDb(d, 1800, 2600);
      const b5k = voicedBandDb(d, 4500, 6000);
      // Young voices have 2kHz recessed relative to 4.5-6kHz (diff <= +1dB); nasal/veteran voices protrude (+6..+15dB)
      return rampUp(b2k - b5k, 1.5, 13.0);
    },
  },
  {
    id: 117, key: "bb_katsuo_exag", name: "[ババア07] 昭和誇張・カツオ化 (母音大げさ/6-8Hz過剰脈動)", unit: "risk",
    run(d, { metrics: m }) {
      const exagVowel = rampUp(m.vowel_space_span_hz ?? 1000, 1220, 1650);
      const exagPulse = rampUp(m.smile_pulse_6_8hz ?? 1.8, 2.7, 4.5);
      return Number(Math.max(exagVowel, exagPulse).toFixed(1));
    },
  },

  // === 群B: 声帯粘膜の加齢 (Presbyphonia: トレモロ・乾き・押し声・カスレ) ===
  {
    id: 118, key: "bb_tremor_2_4hz", name: "[ババア08] 2-4Hz 老人性トレモロ (遅い震え)", unit: "risk",
    run(d) { return rampUp(tremor2to4Hz(d), 0.16, 0.36); },
  },
  {
    id: 119, key: "bb_dry_hiss", name: "[ババア09] 4-8kHz 乾いたカスレ/微風ノイズ", unit: "risk",
    run(d, { metrics: m }) {
      // High SFM (flat white noise) combined with low HNR_air = dry husky hiss
      const sfmRisk = rampUp(m.sfm_4_8k ?? 0.52, 0.56, 0.78);
      const hnrRisk = rampDn(m.hnr_air_db ?? 14, 11.5, 4.0);
      return Number(clamp(0.5 * sfmRisk + 0.5 * hnrRisk).toFixed(1));
    },
  },
  {
    id: 120, key: "bb_pressed_h2", name: "[ババア10] 押し声・力みH2過多 (H1-H2<+1.5dB)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.h1_h2_db ?? 3.5, 2.2, -1.5); },
  },
  {
    id: 121, key: "bb_hoarse_cpp", name: "[ババア11] 粘膜ツルツル喪失 (低CPPカスレ)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.cpp_db ?? 5.0, 4.5, 2.2); },
  },
  {
    id: 122, key: "bb_synth_bicoh", name: "[ババア12] 人工倍音結合・波形非対称逆転 (バイコヒ/Skew)", unit: "risk",
    run(d, { metrics: m }) {
      const bic = rampUp(m.bicoherence_idx ?? 0.36, 0.44, 0.65);
      const skw = rampUp(m.waveform_skewness ?? -0.15, -0.04, 0.10);
      return Number(clamp(0.6 * bic + 0.4 * skw).toFixed(1));
    },
  },
  {
    id: 123, key: "bb_stiff_crest", name: "[ババア13] 波形潰れ・硬直声帯 (低クレスト)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.buzzy_crest_db ?? 8.8, 8.2, 6.8); },
  },

  // === 群C: 話し方・貫禄・大御所コントロール (紫綬褒章センサー) ===
  {
    id: 124, key: "bb_slow_pitch", name: "[ババア14] ノロいピッチ速度 (大御所抑揚)", unit: "risk",
    run(d, { metrics: m }) { return rampDn(m.pitch_vel_st_s ?? 22, 18.5, 8.5); },
  },
  {
    id: 125, key: "bb_sticky_vo", name: "[ババア15] ベタ付き有声率 (抜けのなさ)", unit: "risk",
    run(d, { metrics: m }) { return rampUp(m.voiced_duty_pct ?? 48, 53.5, 64.0); },
  },
  {
    id: 126, key: "bb_slow_mod", name: "[ババア16] 音節モタつき (3-8Hz過大変調)", unit: "risk",
    run(d, { metrics: m }) { return rampUp(m.mod_3_8hz ?? 0.9, 1.25, 2.40); },
  },
  {
    id: 127, key: "bb_overcontrol", name: "[ババア17] 過制御・無防備さ欠如 (位相ロック)", unit: "risk",
    run(d, { metrics: m }) { return rampUp(m.harm_phase_lock ?? 0.98, 0.988, 0.999); },
  },
  {
    id: 128, key: "bb_stiff_fric", name: "[ババア18] 硬直した摩擦音エッジ", unit: "risk",
    run(d, { metrics: m }) { return rampUp(m.fric_brick_slope ?? 1.0, 1.5, 4.2); },
  },
  {
    id: 129, key: "bb_stagnant_lam", name: "[ババア19] 声門停滞・一本調子 (RQA LAM)", unit: "risk",
    run(d, { metrics: m }) { return rampUp(m.rqa_laminarity_pct ?? 3.0, 6.0, 24.0); },
  },
];

export const CAT12_TOOLS = [
  ...INDIVIDUAL_SENSORS,
  {
    id: 130, key: "bb_babaa_index_100", name: "[総合] ババア度指数 (0=完全10代 / 100=紫綬褒章)", unit: "pts",
    run(d, { metrics: m }) {
      let sum = 0, n = 0;
      for (const s of INDIVIDUAL_SENSORS) {
        const v = m[s.key];
        if (typeof v === "number" && Number.isFinite(v)) { sum += v; n++; }
      }
      return Number((n ? sum / n : 0).toFixed(1));
    },
  },
];
