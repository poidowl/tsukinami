#!/usr/bin/env node
// xray/test_xray.mjs — 変態解析ツール150選 自己検証テスト（完全スタンドアロン・15グループ検証）
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { fftRadix2, decodeWav } from "./core.mjs";
import { evaluateItemGates } from "./suite.mjs";
import { ALL_TOOLS, analyzeBuffer, runSuite, DEFAULT_SAFETY_GATES } from "./run.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SR = 24000;

function makePrng(seed = 123456789) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296.0;
  };
}

function encodeWav(samples, sr = SR) {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const ws = (off, str) => { for (let i = 0; i < str.length; i++) v.setUint8(off + i, str.charCodeAt(i)); };
  ws(0, "RIFF");
  v.setUint32(4, 36 + n * 2, true);
  ws(8, "WAVE");
  ws(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, sr, true);
  v.setUint32(28, sr * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  ws(36, "data");
  v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const c = Math.max(-1.0, Math.min(1.0, samples[i]));
    v.setInt16(44 + i * 2, Math.round(c * 32767.0), true);
  }
  return new Uint8Array(buf);
}

function biquadBandpass(x, sr, fc, Q) {
  const w0 = (2.0 * Math.PI * fc) / sr;
  const alpha = Math.sin(w0) / (2.0 * Q);
  const b0 = alpha, b1 = 0.0, b2 = -alpha;
  const a0 = 1.0 + alpha, a1 = -2.0 * Math.cos(w0), a2 = 1.0 - alpha;
  const nb0 = b0 / a0, nb1 = b1 / a0, nb2 = b2 / a0, na1 = a1 / a0, na2 = a2 / a0;
  const y = new Float64Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < x.length; i++) {
    const x0 = x[i];
    const y0 = nb0 * x0 + nb1 * x1 + nb2 * x2 - na1 * y1 - na2 * y2;
    x2 = x1; x1 = x0; y2 = y1; y1 = y0;
    y[i] = y0;
  }
  return y;
}

function applyFormants(src, sr, formants, gains = [1.0, -0.65, 0.35, -0.25]) {
  const out = new Float64Array(src.length);
  for (let idx = 0; idx < formants.length; idx++) {
    const [fc, bw] = formants[idx];
    const r = Math.exp((-Math.PI * bw) / sr);
    const w0 = (2.0 * Math.PI * fc) / sr;
    const a1 = 2.0 * r * Math.cos(w0);
    const a2 = -r * r;
    const g = (1.0 - r) * Math.sin(w0);
    const wG = gains[idx] ?? 0.2;
    let y1 = 0.0, y2 = 0.0;
    for (let i = 0; i < src.length; i++) {
      const v = g * src[i] + a1 * y1 + a2 * y2;
      y2 = y1; y1 = v;
      out[i] += wG * v;
    }
  }
  return out;
}

function applyFormantsCascade(src, sr, formants) {
  let cur = Float64Array.from(src);
  for (let idx = 0; idx < formants.length; idx++) {
    const [fc, bw] = formants[idx];
    const r = Math.exp((-Math.PI * bw) / sr);
    const w0 = (2.0 * Math.PI * fc) / sr;
    const a1 = 2.0 * r * Math.cos(w0);
    const a2 = -r * r;
    const g = 1.0 - a1 - a2;
    const next = new Float64Array(cur.length);
    let y1 = 0.0, y2 = 0.0;
    for (let i = 0; i < cur.length; i++) {
      const v = g * cur[i] + a1 * y1 + a2 * y2;
      y2 = y1; y1 = v;
      next[i] = v;
    }
    cur = next;
  }
  return cur;
}

function makeCascadeVowel(f0, durS, formants, opts = {}) {
  const sr = opts.sr || SR;
  const N = Math.trunc(sr * durS);
  const src = new Float64Array(N);
  const nHarm = Math.min(48, Math.floor((0.46 * sr) / f0));
  for (let i = 0; i < N; i++) {
    let v = 0.0;
    for (let k = 1; k <= nHarm; k++) {
      v += (1.0 / Math.pow(k, opts.rolloff ?? 1.0)) * Math.sin((2.0 * Math.PI * k * f0 * i) / sr + 0.11 * k);
    }
    src[i] = v;
  }
  const filt = applyFormantsCascade(src, sr, formants);
  const rad = new Float64Array(N);
  for (let i = 1; i < N; i++) rad[i] = filt[i] - 0.96 * filt[i - 1];
  const fade = Math.min(Math.trunc(0.015 * sr), N >> 2);
  for (let i = 0; i < fade; i++) {
    const w = i / Math.max(1, fade);
    rad[i] *= w;
    rad[N - 1 - i] *= w;
  }
  return normalizePeak(rad, 0.7);
}

function normalizePeak(arr, peak = 0.65) {
  let mx = 0.0;
  for (let i = 0; i < arr.length; i++) { const a = Math.abs(arr[i]); if (a > mx) mx = a; }
  const g = mx > 1e-9 ? peak / mx : 1.0;
  const out = new Float32Array(arr.length);
  for (let i = 0; i < arr.length; i++) out[i] = Math.max(-1.0, Math.min(1.0, arr[i] * g));
  return out;
}

function makeSine(hz, durS = 0.8, extraFn = null, sr = SR) {
  const N = Math.trunc(sr * durS);
  const s = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    let v = 0.5 * Math.sin((2.0 * Math.PI * hz * i) / sr) + 0.2 * Math.sin((2.0 * Math.PI * 2 * hz * i) / sr);
    if (extraFn) v += extraFn(i, sr);
    s[i] = Math.max(-1.0, Math.min(1.0, v));
  }
  return encodeWav(s, sr);
}

function makeNoise(durS = 0.8, amp = 0.35, seed = 12345, sr = SR) {
  const rng = makePrng(seed);
  const N = Math.trunc(sr * durS);
  const s = new Float32Array(N);
  for (let i = 0; i < N; i++) s[i] = (rng() * 2.0 - 1.0) * amp;
  return encodeWav(s, sr);
}

function makeHarmonicVowel(f0, durS, formants, opts = {}) {
  const sr = opts.sr || SR;
  const N = Math.trunc(sr * durS);
  const src = new Float64Array(N);
  const nHarm = Math.min(36, Math.floor((0.46 * sr) / f0));
  const rng = makePrng(opts.seed || 777);
  for (let i = 0; i < N; i++) {
    let v = 0.0;
    for (let k = 1; k <= nHarm; k++) {
      v += (1.0 / Math.pow(k, opts.rolloff ?? 0.55)) * Math.sin((2.0 * Math.PI * k * f0 * i) / sr + 0.13 * k);
    }
    if (opts.breathAmp) v += (rng() * 2.0 - 1.0) * opts.breathAmp;
    src[i] = v;
  }
  const filt = applyFormants(src, sr, formants);
  const fade = Math.min(Math.trunc(0.015 * sr), N >> 2);
  for (let i = 0; i < fade; i++) {
    const w = i / Math.max(1, fade);
    filt[i] *= w;
    filt[N - 1 - i] *= w;
  }
  return normalizePeak(filt, 0.7);
}

function makeKawaiiSynth(baseF0 = 340.0, seed = 4242) {
  // Multi-syllable cute breathy 4-formant speech-like synthetic signal (0 external engine deps)
  const rng = makePrng(seed);
  const durS = 1.1;
  const N = Math.trunc(SR * durS);
  const src = new Float64Array(N);
  const breathRaw = new Float64Array(N);
  let phase = 0.0;
  for (let i = 0; i < N; i++) {
    const t = i / SR;
    const f0 = baseF0 + 35.0 * Math.sin(2.0 * Math.PI * 1.8 * t) + 12.0 * Math.sin(2.0 * Math.PI * 5.2 * t);
    phase += (2.0 * Math.PI * f0) / SR;
    let glot = 0.0;
    for (let k = 1; k <= 16; k++) glot += Math.sin(k * phase + 0.07 * k) / Math.pow(k, 1.5);
    const syl = 0.55 + 0.45 * Math.sin(2.0 * Math.PI * 3.5 * t);
    src[i] = glot * syl;
    breathRaw[i] = (rng() * 2.0 - 1.0) * syl;
  }
  const vocal = normalizePeak(applyFormants(src, SR, [[760, 90], [1520, 120], [3150, 200], [4500, 260]], [1.0, -0.55, 0.18, -0.12]), 0.7);
  const air = normalizePeak(biquadBandpass(breathRaw, SR, 5200, 1.2), 0.7);
  const mix = new Float64Array(N);
  for (let i = 0; i < N; i++) mix[i] = vocal[i] + 0.18 * air[i];
  const fade = Math.trunc(0.02 * SR);
  for (let i = 0; i < fade; i++) {
    const w = i / fade;
    mix[i] *= w;
    mix[N - 1 - i] *= w;
  }
  return encodeWav(normalizePeak(mix, 0.7));
}

function assertAllFinite(metrics, label) {
  for (const t of ALL_TOOLS) {
    const val = metrics[t.key];
    assert.ok(
      typeof val === "number" && Number.isFinite(val),
      `[${label}] Tool #${t.id} (${t.key}) returned non-finite: ${val}`
    );
  }
}

// =========================================================================
// Group 0: Registry & Standalone Contract
// =========================================================================
assert.equal(ALL_TOOLS.length, 150, `Expected 150 tools, got ${ALL_TOOLS.length}`);
const idSet = new Set();
const keySet = new Set();
for (let i = 0; i < ALL_TOOLS.length; i++) {
  const t = ALL_TOOLS[i];
  assert.equal(t.id, i + 1, `Tool index ${i} must have id ${i + 1}, got ${t.id}`);
  assert.equal(typeof t.key, "string");
  assert.equal(typeof t.name, "string");
  assert.equal(typeof t.unit, "string");
  assert.equal(typeof t.run, "function");
  idSet.add(t.id);
  keySet.add(t.key);
}
assert.equal(idSet.size, 150, "Tool IDs must be unique 1..150");
assert.equal(keySet.size, 150, "Tool keys must be unique");

const EXPECTED_CAT13_KEYS = [
  "pl_erb_rough_med", "pl_erb_rough_p90", "erb_mod_rough",
  "cliff_all_ratio", "max_sample_jump", "c2_jerk_p999",
  "post_pause_rise_ms", "onset_toe_ratio",
  "vsib_coexist_pct", "vsib_centroid_hz",
  "affr_closure_depth_db", "affr_burst_jump_db",
  "f4_median_hz", "f3f4_bright_lift_hz", "f1f2_drift_pct",
  "tail_rqa_lam_pct", "tail_hopf_dissolve",
  "f0_pink_beta", "f1_f0_margin_hz", "intelligibility_guard_100",
];
for (let j = 0; j < EXPECTED_CAT13_KEYS.length; j++) {
  const tool = ALL_TOOLS[130 + j];
  assert.equal(tool.id, 131 + j);
  assert.equal(tool.key, EXPECTED_CAT13_KEYS[j], `Cat 13 #${131 + j} key mismatch`);
}

// Verify all external consumer keys are preserved
const CONSUMER_KEYS = [
  "h1_h2_db", "cpp_db", "spec_tilt_dboct", "epilaryngeal_3k_db", "f0_mean_hz", "f0_range_st",
  "final_scoop_st", "fric_brick_slope", "fric_low_leak_db", "kawaii_overall_100",
  "uncanny_synth_100", "artifact_risk_100", "anime_modern_100", "sweet_voice_100",
  "lsd_vs_first_db", "rqa_laminarity_pct", "bb_low_heavy", "bb_hi_dim", "bb_closed_f1",
  "bb_nasal_2k", "bb_overcontrol", "bb_stiff_fric", "bb_stagnant_lam", "bb_babaa_index_100",
  "vis_100_report_ready",
];
for (const k of CONSUMER_KEYS) assert.ok(keySet.has(k), `Missing preserved consumer key: ${k}`);

// Verify zero parent-directory imports across all .mjs modules in xray/
const mjsFiles = fs.readdirSync(__dirname).filter((f) => f.endsWith(".mjs"));
for (const f of mjsFiles) {
  const txt = fs.readFileSync(path.join(__dirname, f), "utf8");
  assert.ok(!/from\s+["']\.\.\//.test(txt), `Forbidden parent import found in xray/${f}`);
}
console.log("[PASS] Group 0: Registry (150 tools, canonical #131-#150, 0 parent imports)");

// =========================================================================
// Group 1: Edge-Case 0-NaN / 0-Crash Sweep + Legacy Physics Assertions
// =========================================================================
const edgeCases = {
  empty0: encodeWav(new Float32Array(0), SR),
  silence500: encodeWav(new Float32Array(SR * 0.5), SR),
  dc500: encodeWav(new Float32Array(SR * 0.5).fill(0.4), SR),
  short15ms24k: makeSine(350.0, 0.015, null, 24000),
  short30ms24k: makeSine(350.0, 0.030, null, 24000),
  short30ms44k: makeSine(350.0, 0.030, null, 44100),
  whiteNoise: makeNoise(0.8),
  sine350: makeSine(350.0, 0.8),
  whistle4100: makeSine(350.0, 0.8, (i, sr) => 0.12 * Math.sin((2.0 * Math.PI * 4100.0 * i) / sr)),
  clickImpulse: makeSine(350.0, 0.8, (i) => (i % 2400 === 100 ? 0.6 : 0.0)),
  clippedSine: encodeWav(Float32Array.from({ length: SR * 0.6 }, (_, i) => Math.max(-1, Math.min(1, 4.0 * Math.sin((2 * Math.PI * 350 * i) / SR)))), SR),
  kawaiiSynth: makeKawaiiSynth(),
};

const edgeRes = {};
let refD1 = null, refM1 = null;
for (const [name, wav] of Object.entries(edgeCases)) {
  const r = analyzeBuffer(wav, refD1, refM1);
  if (name === "sine350") { refD1 = r.d; refM1 = r.metrics; }
  edgeRes[name] = r.metrics;
  assertAllFinite(r.metrics, name);
}
assert.ok(Math.abs(edgeRes.sine350.f0_mean_hz - 350.0) < 3.0, `F0 tracker failed: ${edgeRes.sine350.f0_mean_hz}`);
assert.ok(edgeRes.whistle4100.fixed_whistle_db > edgeRes.sine350.fixed_whistle_db + 10.0, "#15 whistle failed");
assert.ok(edgeRes.clickImpulse.cliff_impulse_ratio > edgeRes.sine350.cliff_impulse_ratio * 2.0, "#16 click failed");
assert.ok(edgeRes.kawaiiSynth.phaser_notch_depth < 12.0, `#17 phaser too high: ${edgeRes.kawaiiSynth.phaser_notch_depth}`);
assert.ok(edgeRes.kawaiiSynth.voiced_breath_ratio > 0.5, `#57 voiced_breath_ratio too low: ${edgeRes.kawaiiSynth.voiced_breath_ratio}`);
assert.equal(edgeRes.kawaiiSynth.vis_100_report_ready, 150, "#100 vis_100_report_ready must equal 150");
assert.equal(edgeRes.silence500.artifact_risk_100, 0.0, `Silence artifact_risk must be 0, got ${edgeRes.silence500.artifact_risk_100}`);
assert.equal(edgeRes.whiteNoise.artifact_risk_100, 0.0, `Clean whiteNoise artifact_risk must be 0, got ${edgeRes.whiteNoise.artifact_risk_100}`);
console.log("[PASS] Group 1: Edge-case 0-NaN/0-crash sweep (12 signals x 150 tools) + legacy assertions");

// =========================================================================
// Group 2: Standalone fftRadix2 & Adaptive High-F0 qCut @ 440 Hz
// =========================================================================
{
  const N = 256;
  const cosIn = new Float64Array(N);
  for (let i = 0; i < N; i++) cosIn[i] = Math.cos((2.0 * Math.PI * 8 * i) / N);
  const copy = Float64Array.from(cosIn);
  const { re, im } = fftRadix2(cosIn);
  for (let i = 0; i < N; i++) assert.equal(cosIn[i], copy[i], "fftRadix2 must not mutate input");
  assert.ok(Math.abs(re[8] - N / 2) < 1e-6 && Math.abs(im[8]) < 1e-6, `fftRadix2 cos(8) bin mismatch: (${re[8]}, ${im[8]})`);
  assert.ok(Math.abs(re[0]) < 1e-6 && Math.abs(re[16]) < 1e-6, "fftRadix2 leakage at non-signal bins");

  const v440 = encodeWav(makeHarmonicVowel(440.0, 0.7, [[800, 90], [1500, 120], [3000, 170], [4200, 220]]));
  const m440 = analyzeBuffer(v440).metrics;
  assertAllFinite(m440, "vowel440");
  assert.ok(Math.abs(m440.f0_mean_hz - 440.0) < 5.0, `440Hz F0 mismatch: ${m440.f0_mean_hz}`);
  assert.ok(m440.phaser_notch_depth < 10.0, `440Hz phaser_notch_depth too high (F0 ripple leak): ${m440.phaser_notch_depth}`);
  assert.ok(m440.f1_median_hz >= 600 && m440.f1_median_hz <= 1050, `440Hz F1 out of range: ${m440.f1_median_hz}`);
}
console.log("[PASS] Group 2: Standalone fftRadix2 + adaptive high-F0 qCut @ 440 Hz");

// =========================================================================
// Group 3: #10 onset_rise_ms Capped Lookback
// =========================================================================
{
  const makeTwoSyl = (riseMs2) => {
    const N = Math.trunc(SR * 1.1);
    const s = new Float32Array(N);
    const tGap0 = Math.trunc(0.45 * SR), tGap1 = Math.trunc(0.49 * SR); // 40ms shallow dip/unvoiced gap
    const tRise2 = Math.trunc((riseMs2 / 1000) * SR);
    for (let i = 0; i < N; i++) {
      let env = 0.0;
      if (i < Math.trunc(0.03 * SR)) env = 0.0;
      else if (i < Math.trunc(0.045 * SR)) env = (i - 0.03 * SR) / (0.015 * SR);
      else if (i < tGap0) env = 1.0;
      else if (i < tGap1) env = 0.01; // quiet gap breaking voicing
      else if (i < tGap1 + tRise2) env = (i - tGap1) / Math.max(1, tRise2);
      else if (i < N - Math.trunc(0.03 * SR)) env = 1.0;
      s[i] = env * 0.55 * Math.sin((2.0 * Math.PI * 330.0 * i) / SR);
    }
    return encodeWav(s);
  };
  const mCrisp = analyzeBuffer(makeTwoSyl(15)).metrics;
  const mSlug = analyzeBuffer(makeTwoSyl(65)).metrics;
  assert.ok(mCrisp.onset_rise_ms <= 85.0, `Capped lookback violated: ${mCrisp.onset_rise_ms}`);
  assert.ok(mSlug.onset_rise_ms <= 160.0, `Sluggish lookback exceeded cap: ${mSlug.onset_rise_ms}`);
  assert.ok(mSlug.onset_rise_ms > mCrisp.onset_rise_ms + 15.0,
    `#10 onset_rise_ms failed to separate sluggish (${mSlug.onset_rise_ms}) vs crisp (${mCrisp.onset_rise_ms})`);
}
console.log("[PASS] Group 3: #10 onset_rise_ms capped lookback & sluggish vs crisp separation");

// =========================================================================
// Group 4: All-Sample Cliff, C^2 Jerk, Onset/Offset Symmetry, Single-Click & #83 Wiring
// =========================================================================
{
  // 4a. Exact 5ms hop = 120 samples @ 24kHz -> n = 2400, 4800, 7200 are exact hop boundaries (i = 0)
  const rng = makePrng(9911);
  const N = Math.trunc(SR * 0.8);
  const unvBase = new Float32Array(N);
  const unvClick = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const v = (rng() * 2.0 - 1.0) * 0.12;
    unvBase[i] = v;
    unvClick[i] = (i === 2400 || i === 4800 || i === 7200) ? 0.92 : v;
  }
  const mUnvBase = analyzeBuffer(encodeWav(unvBase)).metrics;
  const mUnvClick = analyzeBuffer(encodeWav(unvClick)).metrics;
  assert.ok(mUnvClick.cliff_impulse_ratio > mUnvBase.cliff_impulse_ratio * 2.5,
    `#16 unvoiced hop click missed: ${mUnvClick.cliff_impulse_ratio} vs ${mUnvBase.cliff_impulse_ratio}`);
  assert.ok(mUnvClick.cliff_all_ratio > mUnvBase.cliff_all_ratio * 2.5,
    `#134 unvoiced hop click missed: ${mUnvClick.cliff_all_ratio} vs ${mUnvBase.cliff_all_ratio}`);
  assert.ok(mUnvClick.max_sample_jump > mUnvBase.max_sample_jump * 1.5,
    `#135 max_sample_jump missed unvoiced click: ${mUnvClick.max_sample_jump} vs ${mUnvBase.max_sample_jump}`);
  assert.ok(mUnvClick.artifact_risk_100 > mUnvBase.artifact_risk_100 + 8.0,
    `#83 failed to spike on unvoiced click: ${mUnvClick.artifact_risk_100} vs ${mUnvBase.artifact_risk_100}`);

  const voHopClick = makeSine(350.0, 0.8, (i) => (i === 2400 || i === 4800 || i === 7200 ? 0.65 : 0.0));
  const mVoHop = analyzeBuffer(voHopClick).metrics;
  assert.ok(mVoHop.cliff_impulse_ratio > edgeRes.sine350.cliff_impulse_ratio * 3.0,
    `#16 voiced hop click missed: ${mVoHop.cliff_impulse_ratio}`);
  assert.ok(mVoHop.cliff_all_ratio > edgeRes.sine350.cliff_all_ratio * 3.0,
    `#134 voiced hop click missed: ${mVoHop.cliff_all_ratio}`);
  assert.ok(mVoHop.artifact_risk_100 > edgeRes.sine350.artifact_risk_100 + 8.0,
    `#83 failed to spike on voiced hop click: ${mVoHop.artifact_risk_100} vs ${edgeRes.sine350.artifact_risk_100}`);

  // 4b. Direct non-disjunctive #136 c2_jerk_p999 test: C^0 boxcar vs C^2 minimum-jerk (10u^3-15u^4+6u^5)
  {
    const seg = Math.trunc(0.016 * SR); // 16ms segments -> 50 steps -> 200 d3 spikes (>0.1% of N)
    const box = new Float32Array(N);
    const mj = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const sIdx = Math.floor(i / seg);
      const u = (i - sIdx * seg) / seg;
      const lo = (sIdx & 1) ? 0.35 : 0.95;
      const hi = (sIdx & 1) ? 0.95 : 0.35;
      const car = 0.5 * Math.sin((2.0 * Math.PI * 330.0 * i) / SR) + 0.2 * Math.sin((2.0 * Math.PI * 660.0 * i) / SR);
      box[i] = lo * car;
      mj[i] = (lo + (hi - lo) * (u * u * u * (10.0 - 15.0 * u + 6.0 * u * u))) * car;
    }
    const mBox = analyzeBuffer(encodeWav(box)).metrics;
    const mMj = analyzeBuffer(encodeWav(mj)).metrics;
    assert.ok(mBox.c2_jerk_p999 > mMj.c2_jerk_p999 * 10.0,
      `#136 c2_jerk failed C0 vs C2 separation: box=${mBox.c2_jerk_p999} vs minJerk=${mMj.c2_jerk_p999}`);
    assert.ok(mBox.c2_jerk_p999 > 50.0, `#136 boxcar jerk too low: ${mBox.c2_jerk_p999}`);
    assert.ok(mMj.c2_jerk_p999 < 10.0, `#136 minJerk jerk too high: ${mMj.c2_jerk_p999}`);
  }

  // 4c. Center-aligned symmetry: 10 abrupt syllable offset cuts vs 10 abrupt onset cuts (#16/#134/#136/#83/#98)
  {
    const silN = Math.trunc(0.06 * SR), sylN = Math.trunc(0.08 * SR), rampN = Math.trunc(0.03 * SR);
    const segs = [new Float32Array(silN)];
    for (let s = 0; s < 10; s++) {
      const syl = new Float32Array(sylN);
      for (let i = 0; i < sylN; i++) {
        const e = i > sylN - rampN ? 0.5 * (1.0 + Math.cos((Math.PI * (i - (sylN - rampN))) / rampN)) : 1.0;
        syl[i] = e * (0.45 * Math.cos((2.0 * Math.PI * 330.0 * i) / SR) + 0.15 * Math.cos((2.0 * Math.PI * 660.0 * i) / SR));
      }
      segs.push(syl, new Float32Array(silN));
    }
    const tot = segs.reduce((a, b) => a + b.length, 0);
    const xOn = new Float32Array(tot), xOff = new Float32Array(tot);
    let off = 0;
    for (const sg of segs) { xOn.set(sg, off); off += sg.length; }
    for (let i = 0; i < tot; i++) xOff[i] = xOn[tot - 1 - i];
    const mOn = analyzeBuffer(encodeWav(xOn)).metrics;
    const mOff = analyzeBuffer(encodeWav(xOff)).metrics;
    assert.ok(mOff.cliff_impulse_ratio > 100.0, `Offset cuts #16 missed: ${mOff.cliff_impulse_ratio}`);
    assert.ok(mOff.cliff_all_ratio > 100.0, `Offset cuts #134 missed: ${mOff.cliff_all_ratio}`);
    assert.ok(mOff.c2_jerk_p999 > 100.0, `Offset cuts #136 missed: ${mOff.c2_jerk_p999}`);
    assert.ok(mOff.artifact_risk_100 >= 38.0, `Offset cuts #83 missed: ${mOff.artifact_risk_100}`);
    assert.ok(Math.abs(mOff.cliff_all_ratio - mOn.cliff_all_ratio) / Math.max(1.0, mOn.cliff_all_ratio) < 0.10,
      `Onset/offset cliff asymmetry: on=${mOn.cliff_all_ratio} vs off=${mOff.cliff_all_ratio}`);
    assert.ok(mOff.vis_artifact_flags >= 10, `#98 missed offset cliff flags: ${mOff.vis_artifact_flags}`);
  }

  // 4d. Single 1-sample click in 1.0s audio @ 24kHz & 44.1kHz (i=0, mid, N-1) + zero-median square/DC
  {
    for (const srTest of [24000, 44100]) {
      const nLen = srTest;
      const base = new Float32Array(nLen);
      for (let i = 0; i < nLen; i++) {
        base[i] = 0.45 * Math.sin((2.0 * Math.PI * 350.0 * i) / srTest) + 0.18 * Math.sin((2.0 * Math.PI * 700.0 * i) / srTest);
      }
      for (const [label, pos] of [["i=0", 0], ["mid", nLen >> 1], ["N-1", nLen - 1]]) {
        const clicked = Float32Array.from(base);
        clicked[pos] = -0.95;
        const mc = analyzeBuffer(encodeWav(clicked, srTest)).metrics;
        assert.ok(mc.cliff_impulse_ratio > 55.0,
          `Single click #16 missed @ ${srTest}Hz ${label}: ${mc.cliff_impulse_ratio}`);
        assert.ok(mc.cliff_all_ratio > 55.0,
          `Single click #134 missed @ ${srTest}Hz ${label}: ${mc.cliff_all_ratio}`);
        assert.ok(mc.artifact_risk_100 >= 38.0,
          `#83 missed single click @ ${srTest}Hz ${label}: art=${mc.artifact_risk_100}`);
      }
    }
    // Zero-median square wave -> 999.0; pure DC -> 0.0
    const sq = new Float32Array(SR);
    for (let i = 0; i < SR; i++) sq[i] = Math.sin((2.0 * Math.PI * 300.0 * i) / SR) >= 0 ? 1.0 : -1.0;
    const mSq = analyzeBuffer(encodeWav(sq)).metrics;
    assert.equal(mSq.cliff_impulse_ratio, 999.0, `Square #16 expected 999, got ${mSq.cliff_impulse_ratio}`);
    assert.equal(mSq.cliff_all_ratio, 999.0, `Square #134 expected 999, got ${mSq.cliff_all_ratio}`);
    assert.equal(mSq.c2_jerk_p999, 999.0, `Square #136 expected 999, got ${mSq.c2_jerk_p999}`);
    const dc = new Float32Array(SR).fill(0.5);
    const mDc = analyzeBuffer(encodeWav(dc)).metrics;
    assert.equal(mDc.cliff_impulse_ratio, 0.0, `DC #16 expected 0, got ${mDc.cliff_impulse_ratio}`);
    assert.equal(mDc.cliff_all_ratio, 0.0, `DC #134 expected 0, got ${mDc.cliff_all_ratio}`);
    assert.equal(mDc.c2_jerk_p999, 0.0, `DC #136 expected 0, got ${mDc.c2_jerk_p999}`);
  }
}
console.log("[PASS] Group 4: All-sample cliff, C^2 jerk, onset/offset symmetry, 1-click & zero-median");

// =========================================================================
// Group 5: Plomp-Levelt ERB Roughness (#75, #131-#133)
// =========================================================================
{
  const beat350_370 = encodeWav(Float32Array.from({ length: SR }, (_, i) =>
    0.4 * Math.sin((2 * Math.PI * 350 * i) / SR) + 0.4 * Math.sin((2 * Math.PI * 370 * i) / SR)
  ));
  const rough4100_4200 = encodeWav(Float32Array.from({ length: SR }, (_, i) =>
    0.45 * Math.sin((2 * Math.PI * 350 * i) / SR) +
    0.22 * Math.sin((2 * Math.PI * 4100 * i) / SR) +
    0.22 * Math.sin((2 * Math.PI * 4200 * i) / SR)
  ));
  const mBeat = analyzeBuffer(beat350_370).metrics;
  const mRough = analyzeBuffer(rough4100_4200).metrics;
  const mSine = edgeRes.sine350;
  assert.ok(mSine.pl_erb_rough_med < 1.0, `Pure sine PL rough should be < 1.0, got ${mSine.pl_erb_rough_med}`);
  assert.ok(mBeat.erb_mod_rough > Math.max(20.0, mSine.erb_mod_rough * 2.5),
    `#133 erb_mod_rough failed on 350+370Hz beat: ${mBeat.erb_mod_rough} vs sine ${mSine.erb_mod_rough}`);
  assert.ok(mBeat.sensory_roughness > mSine.sensory_roughness * 1.5,
    `#75 sensory_roughness failed on beat: ${mBeat.sensory_roughness} vs sine ${mSine.sensory_roughness}`);
  assert.ok(mRough.pl_erb_rough_med > mSine.pl_erb_rough_med + 4.0,
    `#131 pl_erb_rough_med failed on 4100+4200Hz: ${mRough.pl_erb_rough_med}`);
  assert.ok(mRough.pl_erb_rough_p90 > mSine.pl_erb_rough_p90 + 4.0,
    `#132 pl_erb_rough_p90 failed on 4100+4200Hz: ${mRough.pl_erb_rough_p90}`);
}
console.log("[PASS] Group 5: Plomp-Levelt ERB roughness (#75, #131-#133)");

// =========================================================================
// Group 6: Multi-Slice RQA (#103/#104) & #118 bb_tremor_2_4hz Fix
// =========================================================================
{
  const shortSteady = makeSine(350.0, 0.25);
  const longSteady = makeSine(350.0, 1.2);
  const tremor3Hz = encodeWav(Float32Array.from({ length: Math.trunc(SR * 1.5) }, (_, i) =>
    (1.0 + 0.35 * Math.sin((2.0 * Math.PI * 3.0 * i) / SR)) * 0.45 * Math.sin((2.0 * Math.PI * 350.0 * i) / SR)
  ));
  const vib6Hz = encodeWav(Float32Array.from({ length: Math.trunc(SR * 1.5) }, (_, i) =>
    (1.0 + 0.35 * Math.sin((2.0 * Math.PI * 6.0 * i) / SR)) * 0.45 * Math.sin((2.0 * Math.PI * 350.0 * i) / SR)
  ));
  const mShort = analyzeBuffer(shortSteady).metrics;
  const mLongA = analyzeBuffer(longSteady).metrics;
  const mLongB = analyzeBuffer(longSteady).metrics;
  const mTrem = analyzeBuffer(tremor3Hz).metrics;
  const mVib = analyzeBuffer(vib6Hz).metrics;
  assert.equal(mShort.bb_tremor_2_4hz, 0.0, `Short steady must have 0 tremor, got ${mShort.bb_tremor_2_4hz}`);
  assert.ok(mLongA.bb_tremor_2_4hz < 10.0, `Steady tone tremor must be < 10, got ${mLongA.bb_tremor_2_4hz}`);
  assert.ok(mVib.bb_tremor_2_4hz < 10.0, `6Hz vibrato must not trigger 2-4Hz tremor, got ${mVib.bb_tremor_2_4hz}`);
  assert.ok(mTrem.bb_tremor_2_4hz > 40.0, `3Hz +-35% AM tremor must be > 40, got ${mTrem.bb_tremor_2_4hz}`);
  assert.equal(mLongA.rqa_diag_entropy, mLongB.rqa_diag_entropy, "RQA ENTR must be deterministic");
  assert.equal(mLongA.rqa_laminarity_pct, mLongB.rqa_laminarity_pct, "RQA LAM must be deterministic");
  assert.ok(mLongA.rqa_diag_entropy > 0.0, `RQA ENTR should be positive on steady voiced tone, got ${mLongA.rqa_diag_entropy}`);
  assert.ok(mLongA.rqa_laminarity_pct >= 0.0 && mLongA.rqa_laminarity_pct <= 100.0);
}
console.log("[PASS] Group 6: Multi-slice RQA (#103/#104) & #118 bb_tremor_2_4hz fix");

// =========================================================================
// Group 7: #137 post_pause_rise_ms & #138 onset_toe_ratio (paired worst-onset + initial)
// =========================================================================
{
  const makeMultiOnset = (profiles, srTest = SR) => {
    const segs = [];
    const silLen = Math.trunc(0.130 * srTest);
    const sylLen = Math.trunc(0.220 * srTest);
    for (let p = 0; p < profiles.length; p++) {
      segs.push(new Float32Array(silLen));
      const { ms, mode } = profiles[p];
      const rN = Math.trunc((ms / 1000.0) * srTest);
      const syl = new Float32Array(sylLen);
      for (let i = 0; i < sylLen; i++) {
        let env = 1.0;
        if (i < rN) {
          const u = i / Math.max(1, rN);
          if (mode === "sq") env = u * u;
          else if (mode === "t3") env = u * u * u;
          else if (mode === "sqrt") env = Math.sqrt(u);
          else if (mode === "rcos") env = 0.5 - 0.5 * Math.cos(Math.PI * u);
          else env = u;
        } else if (i > sylLen - Math.trunc(0.02 * srTest)) {
          env = (sylLen - i) / Math.trunc(0.02 * srTest);
        }
        syl[i] = env * (0.45 * Math.sin((2 * Math.PI * 340 * i) / srTest) + 0.18 * Math.sin((2 * Math.PI * 680 * i) / srTest));
      }
      segs.push(syl);
    }
    segs.push(new Float32Array(silLen));
    const tot = segs.reduce((a, b) => a + b.length, 0);
    const out = new Float32Array(tot);
    let off = 0;
    for (const seg of segs) { out.set(seg, off); off += seg.length; }
    return encodeWav(out, srTest);
  };
  const crispMulti = makeMultiOnset([
    { ms: 12, mode: "lin" }, { ms: 12, mode: "rcos" }, { ms: 12, mode: "lin" }, { ms: 12, mode: "rcos" },
  ]);
  const badToeMulti = makeMultiOnset([
    { ms: 12, mode: "lin" }, { ms: 12, mode: "rcos" }, { ms: 38, mode: "sq" }, { ms: 12, mode: "rcos" },
  ]);
  const mCrisp = analyzeBuffer(crispMulti).metrics;
  const mBad = analyzeBuffer(badToeMulti).metrics;
  assert.ok(mBad.post_pause_rise_ms > mCrisp.post_pause_rise_ms + 8.0,
    `#137 failed to catch 1 bad onset among 4: bad=${mBad.post_pause_rise_ms} vs crisp=${mCrisp.post_pause_rise_ms}`);
  assert.ok(mBad.onset_toe_ratio > mCrisp.onset_toe_ratio + 0.08,
    `#138 failed to catch concave t^2 toe: bad=${mBad.onset_toe_ratio} vs crisp=${mCrisp.onset_toe_ratio}`);

  // 1-bad-among-5-good (t^2 & t^3) + 1-bad-initial + 5-good post-pause regression @ 44.1kHz
  const goodProf = { ms: 12, mode: "sqrt" };
  const mAllGood6 = analyzeBuffer(makeMultiOnset(
    [goodProf, goodProf, goodProf, goodProf, goodProf, goodProf, goodProf], 44100
  )).metrics;
  const mBadT2In6 = analyzeBuffer(makeMultiOnset(
    [goodProf, goodProf, goodProf, { ms: 35, mode: "sq" }, goodProf, goodProf, goodProf], 44100
  )).metrics;
  const mBadT3In6 = analyzeBuffer(makeMultiOnset(
    [goodProf, goodProf, goodProf, { ms: 35, mode: "t3" }, goodProf, goodProf, goodProf], 44100
  )).metrics;
  const mBadT3Init = analyzeBuffer(makeMultiOnset(
    [{ ms: 35, mode: "t3" }, goodProf, goodProf, goodProf, goodProf, goodProf], 44100
  )).metrics;

  assert.ok(mAllGood6.onset_toe_ratio < 0.50, `All-good6 toe too high: ${mAllGood6.onset_toe_ratio}`);
  assert.ok(mAllGood6.post_pause_rise_ms < 14.0, `All-good6 rise too high: ${mAllGood6.post_pause_rise_ms}`);

  assert.ok(mBadT2In6.onset_toe_ratio > 0.60, `5good+1bad(t^2) #138 diluted: ${mBadT2In6.onset_toe_ratio}`);
  assert.ok(mBadT2In6.post_pause_rise_ms >= 18.0, `5good+1bad(t^2) #137 diluted: ${mBadT2In6.post_pause_rise_ms}`);
  assert.ok(mBadT2In6.sweet_voice_100 < mAllGood6.sweet_voice_100 - 1.5,
    `5good+1bad(t^2) #85 missed penalty: ${mBadT2In6.sweet_voice_100} vs ${mAllGood6.sweet_voice_100}`);
  assert.ok(mBadT2In6.intelligibility_guard_100 < mAllGood6.intelligibility_guard_100 - 3.0,
    `5good+1bad(t^2) #150 missed penalty: ${mBadT2In6.intelligibility_guard_100} vs ${mAllGood6.intelligibility_guard_100}`);

  assert.ok(mBadT3In6.onset_toe_ratio > 0.60, `5good+1bad(t^3) #138 diluted: ${mBadT3In6.onset_toe_ratio}`);
  assert.ok(mBadT3In6.post_pause_rise_ms >= 16.0, `5good+1bad(t^3) #137 diluted: ${mBadT3In6.post_pause_rise_ms}`);
  assert.ok(mBadT3In6.sweet_voice_100 < mAllGood6.sweet_voice_100 - 1.5,
    `5good+1bad(t^3) #85 missed penalty: ${mBadT3In6.sweet_voice_100} vs ${mAllGood6.sweet_voice_100}`);
  assert.ok(mBadT3In6.intelligibility_guard_100 < mAllGood6.intelligibility_guard_100 - 3.0,
    `5good+1bad(t^3) #150 missed penalty: ${mBadT3In6.intelligibility_guard_100} vs ${mAllGood6.intelligibility_guard_100}`);

  assert.ok(mBadT3Init.onset_toe_ratio > 0.60, `1bad-init(t^3)+5good #138 missed: ${mBadT3Init.onset_toe_ratio}`);
  assert.ok(mBadT3Init.post_pause_rise_ms >= 16.0, `1bad-init(t^3)+5good #137 missed: ${mBadT3Init.post_pause_rise_ms}`);
  assert.ok(mBadT3Init.sweet_voice_100 < mAllGood6.sweet_voice_100 - 1.5,
    `1bad-init(t^3)+5good #85 missed penalty: ${mBadT3Init.sweet_voice_100} vs ${mAllGood6.sweet_voice_100}`);
  assert.ok(mBadT3Init.intelligibility_guard_100 < mAllGood6.intelligibility_guard_100 - 3.0,
    `1bad-init(t^3)+5good #150 missed penalty: ${mBadT3Init.intelligibility_guard_100} vs ${mAllGood6.intelligibility_guard_100}`);
}
console.log("[PASS] Group 7: #137/#138 paired worst-onset + 1-bad-in-6 + initial bare-vowel regression");

// =========================================================================
// Group 8: #139 vsib_coexist_pct & #140 vsib_centroid_hz
// =========================================================================
{
  const makeSib = (voiced, fc, seed) => {
    const rng = makePrng(seed);
    const N = Math.trunc(SR * 0.6);
    const raw = new Float64Array(N);
    for (let i = 0; i < N; i++) raw[i] = rng() * 2.0 - 1.0;
    const fric = biquadBandpass(raw, SR, fc, 2.2);
    const out = new Float64Array(N);
    for (let i = 0; i < N; i++) {
      const vo = voiced ? (0.35 * Math.sin((2 * Math.PI * 300 * i) / SR) + 0.12 * Math.sin((2 * Math.PI * 600 * i) / SR)) : 0.0;
      out[i] = vo + 0.45 * fric[i];
    }
    return encodeWav(normalizePeak(out, 0.7));
  };
  const mUnv = analyzeBuffer(makeSib(false, 4800, 101)).metrics;
  const mPal = analyzeBuffer(makeSib(true, 3800, 102)).metrics;
  const mAlv = analyzeBuffer(makeSib(true, 6000, 103)).metrics;
  assert.ok(mPal.vsib_coexist_pct > mUnv.vsib_coexist_pct + 40.0,
    `#139 vsib_coexist_pct failed: voiced=${mPal.vsib_coexist_pct} vs unvoiced=${mUnv.vsib_coexist_pct}`);
  assert.ok(mPal.vsib_coexist_pct > 50.0 && mUnv.vsib_coexist_pct < 20.0);
  assert.ok(mAlv.vsib_centroid_hz > mPal.vsib_centroid_hz + 800,
    `#140 vsib_centroid_hz failed: alv=${mAlv.vsib_centroid_hz} vs pal=${mPal.vsib_centroid_hz}`);
}
console.log("[PASS] Group 8: #139 vsib_coexist_pct & #140 vsib_centroid_hz");

// =========================================================================
// Group 9: #141/#142 Affricate Closure/Burst Sweep, #85 Exemption & Negative Controls
// =========================================================================
{
  const makeVcv = (withClosure) => {
    const rng = makePrng(3030);
    const v1 = makeHarmonicVowel(340, 0.22, [[720, 80], [1400, 110], [2900, 160], [4200, 220]], { seed: 11 });
    const v2 = makeHarmonicVowel(340, 0.22, [[720, 80], [1400, 110], [2900, 160], [4200, 220]], { seed: 12 });
    const sibN = Math.trunc(0.085 * SR);
    const sibRaw = new Float64Array(sibN);
    for (let i = 0; i < sibN; i++) sibRaw[i] = rng() * 2.0 - 1.0;
    const sib = normalizePeak(biquadBandpass(sibRaw, SR, 5600, 2.0), 0.25);

    const parts = [v1];
    if (withClosure) {
      parts.push(new Float32Array(Math.trunc(0.032 * SR))); // 32ms stop closure silence
      const bN = Math.trunc(0.015 * SR);
      const bRaw = new Float64Array(bN);
      for (let i = 0; i < bN; i++) bRaw[i] = (rng() * 2.0 - 1.0) * Math.exp(-3.0 * (i / bN));
      parts.push(normalizePeak(biquadBandpass(bRaw, SR, 2600, 0.9), 0.35)); // 15ms 1-4kHz burst
    }
    parts.push(sib, v2);
    const tot = parts.reduce((a, b) => a + b.length, 0);
    const out = new Float32Array(tot);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return encodeWav(out);
  };
  const mAffr = analyzeBuffer(makeVcv(true)).metrics;
  const mFric = analyzeBuffer(makeVcv(false)).metrics;
  assert.ok(mAffr.affr_closure_depth_db > mFric.affr_closure_depth_db + 12.0,
    `#141 affr_closure_depth_db failed: affr=${mAffr.affr_closure_depth_db} vs fric=${mFric.affr_closure_depth_db}`);
  assert.ok(mAffr.affr_closure_depth_db > 20.0,
    `#141 affr_closure_depth_db too low: ${mAffr.affr_closure_depth_db}`);
  assert.ok(mAffr.affr_burst_jump_db > mFric.affr_burst_jump_db + 6.0,
    `#142 affr_burst_jump_db failed: affr=${mAffr.affr_burst_jump_db} vs fric=${mFric.affr_burst_jump_db}`);
  assert.ok(mAffr.sweet_voice_100 >= mFric.sweet_voice_100 - 5.0,
    `#85 sweet_voice_100 affricate exemption failed: affr=${mAffr.sweet_voice_100} vs fric=${mFric.sweet_voice_100}`);

  const makeAffrSynth = (srTest, closureMs, floorDb = null, opts = {}) => {
    const rng = makePrng(4040 + srTest + closureMs);
    const v1 = makeHarmonicVowel(340, 0.25, [[750, 80], [1400, 110], [2900, 160], [4200, 220]], { sr: srTest, seed: 21 });
    const v2 = makeHarmonicVowel(340, 0.25, [[750, 80], [1400, 110], [2900, 160], [4200, 220]], { sr: srTest, seed: 22 });
    const parts = [v1];
    if (closureMs > 0) {
      const clN = Math.trunc((closureMs / 1000.0) * srTest);
      const cl = new Float32Array(clN);
      if (floorDb !== null) {
        const amp = Math.pow(10.0, floorDb / 20.0) * 0.7;
        for (let i = 0; i < clN; i++) cl[i] = (rng() * 2.0 - 1.0) * amp;
      }
      parts.push(cl);
    }
    if (closureMs > 0 && !opts.noBurst) {
      const bN = Math.trunc(0.006 * srTest);
      const bRaw = new Float64Array(bN);
      for (let i = 0; i < bN; i++) bRaw[i] = (rng() * 2.0 - 1.0) * Math.exp(-2.5 * (i / bN));
      parts.push(normalizePeak(biquadBandpass(bRaw, srTest, 4500, 1.4), 0.35));
    }
    if (!opts.noSib) {
      const sibN = Math.trunc(0.085 * srTest);
      const sibRaw = new Float64Array(sibN);
      for (let i = 0; i < sibN; i++) sibRaw[i] = rng() * 2.0 - 1.0;
      const hiSib = normalizePeak(biquadBandpass(sibRaw, srTest, 6000, 1.8), 0.25);
      if (opts.leakySib) {
        const leakRaw = new Float64Array(sibN);
        for (let i = 0; i < sibN; i++) leakRaw[i] = rng() * 2.0 - 1.0;
        const loLeak = normalizePeak(biquadBandpass(leakRaw, srTest, 1600, 1.5), 0.14);
        const mix = new Float32Array(sibN);
        for (let i = 0; i < sibN; i++) mix[i] = hiSib[i] + loLeak[i];
        parts.push(mix);
      } else {
        parts.push(hiSib);
      }
    }
    parts.push(v2);
    const tot = parts.reduce((a, b) => a + b.length, 0);
    const out = new Float32Array(tot);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return encodeWav(out, srTest);
  };

  // Multi-SR × duration × floor affricate sweep (16, 30, 50, 75 ms × {0, -55 dB} × {16k, 24k, 44.1k, 48k})
  for (const srTest of [16000, 24000, 44100, 48000]) {
    for (const clMs of [16, 30, 50, 75]) {
      for (const flDb of [null, -55]) {
        const m = analyzeBuffer(makeAffrSynth(srTest, clMs, flDb)).metrics;
        assert.ok(m.affr_closure_depth_db > 25.0,
          `Affricate sweep #141 failed @ sr=${srTest}, cl=${clMs}ms, floor=${flDb}: ${m.affr_closure_depth_db}`);
        assert.ok(m.affr_burst_jump_db > 15.0,
          `Affricate sweep #142 failed @ sr=${srTest}, cl=${clMs}ms, floor=${flDb}: ${m.affr_burst_jump_db}`);
      }
    }
  }

  // Direct #85 sweet_voice_100 exemption on leaky /s/ (44.1kHz, 30ms closure vs 0ms plain fricative)
  const mLeakyAffr = analyzeBuffer(makeAffrSynth(44100, 30, null, { leakySib: true })).metrics;
  const mLeakyFric = analyzeBuffer(makeAffrSynth(44100, 0, null, { leakySib: true })).metrics;
  assert.ok(mLeakyAffr.affr_closure_depth_db > 25.0,
    `Leaky affricate #141 missed: ${mLeakyAffr.affr_closure_depth_db}`);
  assert.equal(mLeakyFric.affr_closure_depth_db, 0.0,
    `Leaky fricative #141 false alarm: ${mLeakyFric.affr_closure_depth_db}`);
  assert.ok(mLeakyAffr.sweet_voice_100 > mLeakyFric.sweet_voice_100 + 5.0,
    `#85 leaky /s/ exemption failed: affr=${mLeakyAffr.sweet_voice_100} vs fric=${mLeakyFric.sweet_voice_100}`);

  // Negative controls: /asa/, /ata/, and 90ms/120ms comma pauses (zero & -35 dB floor) MUST be 0.0
  for (const [label, wav] of [
    ["asa_0ms", makeAffrSynth(44100, 0, null)],
    ["ata_30ms_nosib", makeAffrSynth(44100, 30, null, { noSib: true })],
    ["comma_90ms_zero", makeAffrSynth(44100, 90, null)],
    ["comma_120ms_zero", makeAffrSynth(44100, 120, null)],
    ["comma_90ms_n35", makeAffrSynth(44100, 90, -35)],
    ["comma_120ms_n35", makeAffrSynth(44100, 120, -35)],
  ]) {
    const mn = analyzeBuffer(wav).metrics;
    assert.equal(mn.affr_closure_depth_db, 0.0, `Neg control ${label} #141 false alarm: ${mn.affr_closure_depth_db}`);
    assert.equal(mn.affr_burst_jump_db, 0.0, `Neg control ${label} #142 false alarm: ${mn.affr_burst_jump_db}`);
  }
}
console.log("[PASS] Group 9: #141/#142 multi-SR/duration affricate sweep, #85 exemption & negative controls");

// =========================================================================
// Group 10: #143-#145 Sturm-Liouville F4 Lift vs F1/F2 Drift (incl. High-F0 Parallel & Cascade)
// =========================================================================
{
  const wBase = encodeWav(makeHarmonicVowel(300.0, 0.7, [[750, 80], [1450, 110], [2850, 150], [3850, 190]]));
  const wLift = encodeWav(makeHarmonicVowel(300.0, 0.7, [[750, 80], [1450, 110], [3100, 150], [4350, 190]]));
  const rBase = analyzeBuffer(wBase);
  const rLiftNoRef = analyzeBuffer(wLift);
  const rLift = analyzeBuffer(wLift, rBase.d, rBase.metrics);
  assert.equal(rLiftNoRef.metrics.f3f4_bright_lift_hz, 0.0, "Without ref, f3f4_bright_lift_hz must be 0");
  assert.equal(rLiftNoRef.metrics.f1f2_drift_pct, 0.0, "Without ref, f1f2_drift_pct must be 0");
  assert.ok(rLift.metrics.f4_median_hz > rBase.metrics.f4_median_hz + 200,
    `#143 f4_median_hz lift failed: lifted=${rLift.metrics.f4_median_hz} vs base=${rBase.metrics.f4_median_hz}`);
  assert.ok(rLift.metrics.f3f4_bright_lift_hz > 150.0,
    `#144 f3f4_bright_lift_hz failed: ${rLift.metrics.f3f4_bright_lift_hz}`);
  assert.ok(rLift.metrics.f1f2_drift_pct < 4.0,
    `#145 f1f2_drift_pct too large: ${rLift.metrics.f1f2_drift_pct}`);

  // Parallel /a/ @ F0 = 520 Hz, sr = 44.1 kHz (LIFT & SHIFT)
  const wBase520 = encodeWav(makeHarmonicVowel(520.0, 0.7, [[800, 90], [1400, 120], [2900, 160], [4150, 210]], { sr: 44100 }), 44100);
  const wLift520 = encodeWav(makeHarmonicVowel(520.0, 0.7, [[800, 90], [1400, 120], [3150, 160], [4600, 210]], { sr: 44100 }), 44100);
  const wShift520 = encodeWav(makeHarmonicVowel(520.0, 0.7, [[620, 90], [1850, 120], [2900, 160], [4150, 210]], { sr: 44100 }), 44100);
  const rBase520 = analyzeBuffer(wBase520);
  const rLift520 = analyzeBuffer(wLift520, rBase520.d, rBase520.metrics);
  const rShift520 = analyzeBuffer(wShift520, rBase520.d, rBase520.metrics);
  assert.ok(rBase520.metrics.f4_median_hz > 3800 && rBase520.metrics.f4_median_hz < 4500,
    `Parallel /a/ 520Hz F4 out of range: ${rBase520.metrics.f4_median_hz}`);
  assert.ok(rBase520.metrics.f1_f0_margin_hz > 200.0,
    `Parallel /a/ 520Hz #149 margin too low: ${rBase520.metrics.f1_f0_margin_hz}`);
  assert.ok(rLift520.metrics.f3f4_bright_lift_hz > 200.0,
    `Parallel /a/ 520Hz LIFT #144 failed: ${rLift520.metrics.f3f4_bright_lift_hz}`);
  assert.ok(rLift520.metrics.f1f2_drift_pct < 3.0,
    `Parallel /a/ 520Hz LIFT #145 drift too high: ${rLift520.metrics.f1f2_drift_pct}`);
  assert.ok(rShift520.metrics.f1f2_drift_pct > 10.0,
    `Parallel /a/ 520Hz SHIFT #145 missed drift: ${rShift520.metrics.f1f2_drift_pct}`);

  // Cascade /e/ & /a/ across F0 = 260, 380, 460, 520 Hz @ 44.1 kHz
  const cascSpecs = [
    ["casc_e", [[550, 80], [1950, 120], [2900, 160], [4150, 210]], [[550, 80], [1950, 120], [3150, 160], [4600, 210]]],
    ["casc_a", [[800, 90], [1300, 110], [2900, 160], [4100, 210]], [[800, 90], [1300, 110], [3150, 160], [4550, 210]]],
  ];
  for (const [vName, fBase, fLift] of cascSpecs) {
    for (const f0 of [260.0, 380.0, 460.0, 520.0]) {
      const rb = analyzeBuffer(encodeWav(makeCascadeVowel(f0, 0.7, fBase, { sr: 44100 }), 44100));
      const rl = analyzeBuffer(encodeWav(makeCascadeVowel(f0, 0.7, fLift, { sr: 44100 }), 44100), rb.d, rb.metrics);
      assert.ok(rl.metrics.f3f4_bright_lift_hz > 150.0,
        `${vName} @ ${f0}Hz #144 lift failed: ${rl.metrics.f3f4_bright_lift_hz}`);
      assert.ok(rl.metrics.f1f2_drift_pct < 5.0,
        `${vName} @ ${f0}Hz #145 drift too high: ${rl.metrics.f1f2_drift_pct}`);
    }
  }

  // 5-formant vowel (F5 guard): F4 must stay near 4200 Hz rather than skipping to F5 (5400 Hz)
  const w5 = encodeWav(makeHarmonicVowel(300.0, 0.7, [[700, 80], [1400, 110], [2950, 160], [4200, 200], [5400, 240]]));
  const m5 = analyzeBuffer(w5).metrics;
  assert.ok(Math.abs(m5.f4_median_hz - 4200) < 120, `5-formant F4 skipped to F5: got ${m5.f4_median_hz}`);
}
console.log("[PASS] Group 10: #143-#145 Sturm-Liouville F4 lift, high-F0 parallel/cascade & 5-formant guard");

// =========================================================================
// Group 11: #146-#147 Tail RQA & Hopf Dissolution
// =========================================================================
{
  const makeTail = (hopf) => {
    const rng = makePrng(5151);
    const durS = 0.65;
    const N = Math.trunc(SR * durS);
    const tTail0 = Math.trunc((durS - 0.14) * SR);
    const rawNoise = new Float64Array(N);
    for (let i = 0; i < N; i++) rawNoise[i] = rng() * 2.0 - 1.0;
    const hiBreath = biquadBandpass(rawNoise, SR, 5000, 1.0);
    const out = new Float64Array(N);
    let ph = 0.0;
    for (let i = 0; i < N; i++) {
      let f0 = 330.0;
      let amp = 1.0;
      let br = 0.0;
      if (i >= tTail0) {
        const u = (i - tTail0) / (N - tTail0);
        if (hopf) {
          // Organic supercritical Hopf dissolution: gradual harmonic decay + rising breath + micro-wander
          amp = Math.pow(1.0 - 0.85 * u, 1.3);
          br = 0.35 * Math.pow(u, 0.9);
          f0 = 330.0 + 18.0 * Math.sin(2.0 * Math.PI * 11.0 * (i / SR)) * u + 8.0 * (rng() - 0.5) * u;
        } else {
          // Frozen periodic mechanical fade
          amp = 1.0 - 0.5 * u;
          br = 0.0;
        }
      }
      ph += (2.0 * Math.PI * f0) / SR;
      let gl = 0.0;
      for (let k = 1; k <= 10; k++) gl += Math.sin(k * ph) / Math.pow(k, 1.2);
      out[i] = amp * gl + br * hiBreath[i];
    }
    return encodeWav(normalizePeak(out, 0.7));
  };
  const mFrozen = analyzeBuffer(makeTail(false)).metrics;
  const mHopf = analyzeBuffer(makeTail(true)).metrics;
  assert.ok(mHopf.tail_hopf_dissolve > mFrozen.tail_hopf_dissolve + 0.3,
    `#147 tail_hopf_dissolve failed: hopf=${mHopf.tail_hopf_dissolve} vs frozen=${mFrozen.tail_hopf_dissolve}`);
  assert.ok(mHopf.tail_rqa_lam_pct < mFrozen.tail_rqa_lam_pct - 5.0,
    `#146 tail_rqa_lam_pct failed: hopf=${mHopf.tail_rqa_lam_pct} vs frozen=${mFrozen.tail_rqa_lam_pct}`);
}
console.log("[PASS] Group 11: #146-#147 Tail RQA & Hopf dissolution");

// =========================================================================
// Group 12: #148 f0_pink_beta (Spectral 1/f^beta Pink vs White F0)
// =========================================================================
{
  const makeSpectralF0 = (targetBeta, seed) => {
    const rng = makePrng(seed);
    const durS = 2.6;
    const N = Math.trunc(SR * durS);
    // Multi-mode spectral synthesis of f0(t) over 1.0..25.0 Hz with exact 1/f^(beta/2) amplitude law
    const nModes = 90;
    const freqs = [], amps = [], phases = [];
    let pSum = 0.0;
    for (let m = 0; m < nModes; m++) {
      const f = 1.0 + (24.0 * m) / (nModes - 1);
      const a = 1.0 / Math.pow(f, targetBeta / 2.0);
      freqs.push(f); amps.push(a); phases.push(rng() * 2.0 * Math.PI);
      pSum += 0.5 * a * a;
    }
    const scaleSt = 0.35 / Math.sqrt(pSum);
    const out = new Float32Array(N);
    let ph = 0.0;
    for (let i = 0; i < N; i++) {
      const t = i / SR;
      let st = -0.5 * (t / durS); // natural macro declination stripped by linear detrend
      for (let m = 0; m < nModes; m++) st += scaleSt * amps[m] * Math.sin(2.0 * Math.PI * freqs[m] * t + phases[m]);
      const f0 = 330.0 * Math.pow(2.0, st / 12.0);
      ph += (2.0 * Math.PI * f0) / SR;
      out[i] = 0.5 * Math.sin(ph) + 0.2 * Math.sin(2.0 * ph);
    }
    return encodeWav(out);
  };
  const mPink = analyzeBuffer(makeSpectralF0(1.2, 6060)).metrics;
  const mWhite = analyzeBuffer(makeSpectralF0(0.0, 6061)).metrics;
  assert.ok(mPink.f0_pink_beta > mWhite.f0_pink_beta + 0.45,
    `#148 f0_pink_beta separation failed: pink=${mPink.f0_pink_beta} vs white=${mWhite.f0_pink_beta}`);
  assert.ok(mPink.f0_pink_beta >= 0.5 && mPink.f0_pink_beta <= 2.4,
    `#148 pink beta out of range: ${mPink.f0_pink_beta}`);
  assert.ok(mWhite.f0_pink_beta < 0.5,
    `#148 white beta too high: ${mWhite.f0_pink_beta}`);
}
console.log("[PASS] Group 12: #148 f0_pink_beta (1/f pink vs white F0)");

// =========================================================================
// Group 13: #149 f1_f0_margin_hz & #150 intelligibility_guard_100
// =========================================================================
{
  const wTight = encodeWav(makeHarmonicVowel(400.0, 0.7, [[440, 70], [1800, 120], [3000, 170], [4300, 220]]));
  const wOpen = encodeWav(makeHarmonicVowel(400.0, 0.7, [[780, 90], [1600, 120], [3000, 170], [4300, 220]]));
  const mTight = analyzeBuffer(wTight).metrics;
  const mOpen = analyzeBuffer(wOpen).metrics;
  assert.ok(mOpen.f1_f0_margin_hz > mTight.f1_f0_margin_hz + 150.0,
    `#149 f1_f0_margin_hz failed: open=${mOpen.f1_f0_margin_hz} vs tight=${mTight.f1_f0_margin_hz}`);
  assert.ok(mOpen.intelligibility_guard_100 >= 0.0 && mOpen.intelligibility_guard_100 <= 100.0);
  assert.equal(edgeRes.silence500.intelligibility_guard_100, 0.0, "Silence intelligibility_guard must be 0");

  // Direct #150 sensitivity: clean kawaiiSynth >= 95 vs rough+whistle AND single-click drop > 12 pts
  const { samples: kRaw } = decodeWav(edgeCases.kawaiiSynth);
  const kRough = Float32Array.from(kRaw, (v, i) =>
    Math.max(-1.0, Math.min(1.0, v + 0.20 * Math.sin((2.0 * Math.PI * 4100.0 * i) / SR) + 0.20 * Math.sin((2.0 * Math.PI * 4200.0 * i) / SR)))
  );
  const kOneClk = Float32Array.from(kRaw);
  const kMid = kOneClk.length >> 1;
  kOneClk[kMid] = kOneClk[kMid] >= 0.0 ? -0.95 : 0.95;
  const mKClean = edgeRes.kawaiiSynth;
  const mKRough = analyzeBuffer(encodeWav(kRough)).metrics;
  const mKClk = analyzeBuffer(encodeWav(kOneClk)).metrics;
  assert.ok(mKClean.intelligibility_guard_100 >= 95.0,
    `Clean kawaiiSynth #150 too low: ${mKClean.intelligibility_guard_100}`);
  assert.ok(mKRough.intelligibility_guard_100 < mKClean.intelligibility_guard_100 - 12.0,
    `#150 failed to drop on rough+whistle: clean=${mKClean.intelligibility_guard_100} vs rough=${mKRough.intelligibility_guard_100}`);
  assert.ok(mKClk.intelligibility_guard_100 < mKClean.intelligibility_guard_100 - 12.0,
    `#150 failed to drop on 1-sample click: clean=${mKClean.intelligibility_guard_100} vs click=${mKClk.intelligibility_guard_100}`);
}
console.log("[PASS] Group 13: #149 f1_f0_margin_hz & #150 intelligibility_guard_100 (clean vs rough/click)");

// =========================================================================
// Group 14: runSuite API & CLI (--suite, --ref-wav, --gate-strict, --json, --report, legacy CLI)
// =========================================================================
{
  const kawaiiAlt = makeKawaiiSynth(320.0, 4243);
  const sPass = runSuite([
    { id: "kawaii_340", category: "general", hz: 340, wavBytes: edgeCases.kawaiiSynth },
    { id: "kawaii_320", category: "general", hz: 320, wavBytes: kawaiiAlt },
  ]);
  assert.equal(sPass.passed, true, `In-memory clean suite should pass, failures: ${JSON.stringify(sPass.failures)}`);
  assert.equal(sPass.failures.length, 0);
  const EXPECTED_ROLLUPS = [
    "worst_artifact_risk_100", "worst_cliff_all_ratio", "worst_pl_erb_rough_p90",
    "worst_max_sample_jump", "worst_post_pause_rise_ms", "min_vsib_coexist_pct",
    "min_affr_closure_depth_db", "min_intelligibility_guard_100",
  ];
  for (const rk of EXPECTED_ROLLUPS) {
    assert.ok(typeof sPass.rollups[rk] === "number" && Number.isFinite(sPass.rollups[rk]), `Non-finite rollup ${rk}`);
  }

  const sFail = runSuite([
    { id: "click_bad", category: "general", hz: 350, wavBytes: edgeCases.clickImpulse },
  ]);
  assert.equal(sFail.passed, false, "Clicked signal must fail default safety gates");
  assert.ok(sFail.failures.length > 0);

  // Verify unknown-metric typo gate fails (never silently passes) and null disables default gate
  const sTypo = runSuite([
    { id: "typo_item", category: "general", wavBytes: edgeCases.kawaiiSynth, gates: { nonexistent_metric_xyz: [">=", 0] } },
  ]);
  assert.equal(sTypo.passed, false, "Typo metric gate must FAIL");
  assert.equal(sTypo.failures[0].actual, null);

  const sOverride = runSuite([
    {
      id: "click_exempt",
      category: "general",
      wavBytes: edgeCases.clickImpulse,
      gates: {
        artifact_risk_100: null,
        cliff_all_ratio: null,
        max_sample_jump: null,
        pl_erb_rough_p90: null,
        intelligibility_guard_100: null,
      },
    },
  ]);
  assert.equal(sOverride.passed, true, "Null gate overrides must disable default gates");

  // 14a. Strict decodeWav() validation: 10 valid WAV variants + high-SR 96kHz + 18 invalid rejections
  {
    const buildRawWav = (chunks, riffTag = "RIFF", waveTag = "WAVE") => {
      let bodySz = 4;
      for (const [, data] of chunks) bodySz += 8 + data.byteLength + (data.byteLength & 1);
      const buf = new Uint8Array(8 + bodySz);
      const dv = new DataView(buf.buffer);
      const w4 = (o, s) => { for (let i = 0; i < 4; i++) buf[o + i] = s.charCodeAt(i); };
      w4(0, riffTag);
      dv.setUint32(4, bodySz, true);
      w4(8, waveTag);
      let off = 12;
      for (const [id, data] of chunks) {
        w4(off, id);
        dv.setUint32(off + 4, data.byteLength, true);
        buf.set(data, off + 8);
        off += 8 + data.byteLength + (data.byteLength & 1);
      }
      return buf;
    };
    const makeFmt = (audioFmt, ch, sr, bits) => {
      const b = new Uint8Array(16);
      const dv = new DataView(b.buffer);
      dv.setUint16(0, audioFmt, true);
      dv.setUint16(2, ch, true);
      dv.setUint32(4, sr, true);
      dv.setUint32(8, sr * ch * Math.max(1, bits >> 3), true);
      dv.setUint16(12, ch * Math.max(1, bits >> 3), true);
      dv.setUint16(14, bits, true);
      return b;
    };
    const makeExtFmt = (subFmt, ch, sr, bits) => {
      const b = new Uint8Array(40);
      const dv = new DataView(b.buffer);
      dv.setUint16(0, 0xFFFE, true);
      dv.setUint16(2, ch, true);
      dv.setUint32(4, sr, true);
      dv.setUint32(8, sr * ch * (bits >> 3), true);
      dv.setUint16(12, ch * (bits >> 3), true);
      dv.setUint16(14, bits, true);
      dv.setUint16(16, 22, true);
      dv.setUint16(18, bits, true);
      dv.setUint32(20, 0, true);
      dv.setUint16(24, subFmt, true);
      dv.setUint16(26, 0x0000, true);
      dv.setUint16(28, 0x0000, true);
      dv.setUint16(30, 0x0010, true);
      b.set([0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71], 32);
      return b;
    };

    // Valid 1: 44-byte 0-sample PCM16
    const vEmpty = decodeWav(edgeCases.empty0);
    assert.equal(vEmpty.sr, SR);
    assert.equal(vEmpty.samples.length, 0);

    // Valid 2: 8-bit unsigned stereo PCM
    const d8 = new Uint8Array([192, 64, 128, 128]);
    const v8 = decodeWav(buildRawWav([["fmt ", makeFmt(1, 2, 16000, 8)], ["data", d8]]));
    assert.equal(v8.sr, 16000);
    assert.equal(v8.samples.length, 2);
    assert.ok(Math.abs(v8.samples[0]) < 1e-9 && Math.abs(v8.samples[1]) < 1e-9);

    // Valid 3: 24-bit signed PCM (+0.5, -0.5, -1/8388608)
    const d24 = new Uint8Array([0x00, 0x00, 0x40, 0x00, 0x00, 0xC0, 0xFF, 0xFF, 0xFF]);
    const v24 = decodeWav(buildRawWav([["fmt ", makeFmt(1, 1, 24000, 24)], ["data", d24]]));
    assert.ok(Math.abs(v24.samples[0] - 0.5) < 1e-9);
    assert.ok(Math.abs(v24.samples[1] + 0.5) < 1e-9);
    assert.ok(Math.abs(v24.samples[2] + 1.0 / 8388608.0) < 1e-12);

    // Valid 4: 32-bit signed integer PCM (audioFmt=1, bits=32)
    const d32i = new Uint8Array(8);
    new DataView(d32i.buffer).setInt32(0, 1073741824, true);
    new DataView(d32i.buffer).setInt32(4, -1073741824, true);
    const v32i = decodeWav(buildRawWav([["fmt ", makeFmt(1, 1, 44100, 32)], ["data", d32i]]));
    assert.ok(Math.abs(v32i.samples[0] - 0.5) < 1e-9 && Math.abs(v32i.samples[1] + 0.5) < 1e-9);

    // Valid 5: 32-bit IEEE float
    const d32f = new Uint8Array(8);
    new DataView(d32f.buffer).setFloat32(0, 0.25, true);
    new DataView(d32f.buffer).setFloat32(4, -0.75, true);
    const v32f = decodeWav(buildRawWav([["fmt ", makeFmt(3, 1, 48000, 32)], ["data", d32f]]));
    assert.ok(Math.abs(v32f.samples[0] - 0.25) < 1e-6 && Math.abs(v32f.samples[1] + 0.75) < 1e-6);

    // Valid 6: 64-bit IEEE float
    const d64f = new Uint8Array(16);
    new DataView(d64f.buffer).setFloat64(0, 0.125, true);
    new DataView(d64f.buffer).setFloat64(8, -0.625, true);
    const v64f = decodeWav(buildRawWav([["fmt ", makeFmt(3, 1, 48000, 64)], ["data", d64f]]));
    assert.ok(Math.abs(v64f.samples[0] - 0.125) < 1e-12 && Math.abs(v64f.samples[1] + 0.625) < 1e-12);

    // Valid 7: WAVE_FORMAT_EXTENSIBLE (0xFFFE) wrapping 24-bit PCM
    const vExt = decodeWav(buildRawWav([["fmt ", makeExtFmt(1, 1, 48000, 24)], ["data", d24]]));
    assert.equal(vExt.sr, 48000);
    assert.ok(Math.abs(vExt.samples[0] - 0.5) < 1e-9);

    // Valid 8: Extra odd-sized JUNK (5B) + fact (4B) + LIST (3B) before data
    const d16 = new Uint8Array(4);
    new DataView(d16.buffer).setInt16(0, 16384, true);
    new DataView(d16.buffer).setInt16(2, -16384, true);
    const vJunk = decodeWav(buildRawWav([
      ["JUNK", new Uint8Array([1, 2, 3, 4, 5])],
      ["fmt ", makeFmt(1, 1, 22050, 16)],
      ["fact", new Uint8Array(4)],
      ["LIST", new Uint8Array([9, 8, 7])],
      ["data", d16],
    ]));
    assert.equal(vJunk.sr, 22050);
    assert.ok(Math.abs(vJunk.samples[0] - 0.5) < 1e-9);

    // Valid 9: data chunk BEFORE fmt chunk
    const vOrder = decodeWav(buildRawWav([["data", d16], ["fmt ", makeFmt(1, 1, 32000, 16)]]));
    assert.equal(vOrder.sr, 32000);
    assert.ok(Math.abs(vOrder.samples[1] + 0.5) < 1e-9);

    // Valid 10: Uint8Array subarray with byteOffset = 19 inside dirty buffer + 96kHz high-SR nfft check
    const rawOk = buildRawWav([["fmt ", makeFmt(1, 1, 24000, 16)], ["data", d16]]);
    const outer = new Uint8Array(rawOk.byteLength + 37).fill(0xAA);
    outer.set(rawOk, 19);
    const vSub = decodeWav(outer.subarray(19, 19 + rawOk.byteLength));
    assert.equal(vSub.sr, 24000);
    assert.ok(Math.abs(vSub.samples[0] - 0.5) < 1e-9);

    const r96k = analyzeBuffer(makeSine(350.0, 0.2, null, 96000));
    assertAllFinite(r96k.metrics, "sr96k");
    assert.ok(r96k.d.nfft >= r96k.d.wl, `96kHz nfft (${r96k.d.nfft}) must be >= wl (${r96k.d.wl})`);

    // Invalid (18 cases) — ALL must throw
    const pngBytes = new Uint8Array(1032);
    pngBytes.set([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A], 0);
    const nanF32 = new Uint8Array(4);
    new DataView(nanF32.buffer).setFloat32(0, Number.NaN, true);
    const invalidInputs = [
      ["null", null],
      ["string", "RIFF....WAVE"],
      ["empty0bytes", new Uint8Array(0)],
      ["short43bytes", new Uint8Array(43)],
      ["png", pngBytes],
      ["plaintext", new TextEncoder().encode("hello world this is definitely not a wav file at all!")],
      ["noFmt", buildRawWav([["data", d16]])],
      ["noData", buildRawWav([["fmt ", makeFmt(1, 1, 24000, 16)]])],
      ["truncFmt10", buildRawWav([["fmt ", new Uint8Array(10)], ["data", d16]])],
      ["sr0", buildRawWav([["fmt ", makeFmt(1, 1, 0, 16)], ["data", d16]])],
      ["sr500k", buildRawWav([["fmt ", makeFmt(1, 1, 500000, 16)], ["data", d16]])],
      ["ch0", buildRawWav([["fmt ", makeFmt(1, 0, 24000, 16)], ["data", d16]])],
      ["ch32", buildRawWav([["fmt ", makeFmt(1, 32, 24000, 16)], ["data", d16]])],
      ["bits0", buildRawWav([["fmt ", makeFmt(1, 1, 24000, 0)], ["data", d16]])],
      ["bits12", buildRawWav([["fmt ", makeFmt(1, 1, 24000, 12)], ["data", d16]])],
      ["adpcm", buildRawWav([["fmt ", makeFmt(2, 1, 24000, 4)], ["data", d16]])],
      ["float16", buildRawWav([["fmt ", makeFmt(3, 1, 24000, 16)], ["data", d16]])],
      ["float32NaN", buildRawWav([["fmt ", makeFmt(3, 1, 24000, 32)], ["data", nanF32]])],
    ];
    for (const [label, badIn] of invalidInputs) {
      assert.throws(() => decodeWav(badIn), `decodeWav should reject invalid input: ${label}`);
    }
  }

  // 14b. Category-filtered rollups: regex trap protection & positive token matching
  {
    const rngMix = makePrng(7171);
    const sibRawM = new Float64Array(Math.trunc(SR * 0.5));
    for (let i = 0; i < sibRawM.length; i++) sibRawM[i] = rngMix() * 2.0 - 1.0;
    const sibFiltM = biquadBandpass(sibRawM, SR, 5500, 2.0);
    const vsibWavM = encodeWav(normalizePeak(Float64Array.from(sibFiltM, (v, i) => 0.35 * Math.sin((2 * Math.PI * 300 * i) / SR) + 0.45 * v), 0.7));

    // Real affricate WAV for rollup check
    const vA = makeHarmonicVowel(340, 0.22, [[750, 80], [1400, 110], [2900, 160], [4200, 220]], { seed: 91 });
    const vB = makeHarmonicVowel(340, 0.22, [[750, 80], [1400, 110], [2900, 160], [4200, 220]], { seed: 92 });
    const bN = Math.trunc(0.006 * SR), sN = Math.trunc(0.085 * SR);
    const bR = new Float64Array(bN), sR = new Float64Array(sN);
    for (let i = 0; i < bN; i++) bR[i] = (rngMix() * 2.0 - 1.0) * Math.exp(-2.5 * (i / bN));
    for (let i = 0; i < sN; i++) sR[i] = rngMix() * 2.0 - 1.0;
    const affrParts = [vA, new Float32Array(Math.trunc(0.032 * SR)), normalizePeak(biquadBandpass(bR, SR, 4500, 1.4), 0.35), normalizePeak(biquadBandpass(sR, SR, 6000, 1.8), 0.25), vB];
    const affrBuf = new Float32Array(affrParts.reduce((a, b) => a + b.length, 0));
    let aOff = 0; for (const p of affrParts) { affrBuf.set(p, aOff); aOff += p.length; }
    const affrWavM = encodeWav(affrBuf);

    const sTrap = runSuite([
      { id: "zrow_302", category: "dakuon_z", wavBytes: vsibWavM },
      { id: "herutsu_380", category: "affricate", wavBytes: affrWavM },
      // Affricate traps (must NOT match AFFR_TOKEN_RE)
      { id: "pitch_380", category: "pitch_sweep", wavBytes: edgeCases.kawaiiSynth },
      { id: "high_pitch_hanamaru", category: "high_pitch", wavBytes: edgeCases.kawaiiSynth },
      { id: "bench_01", category: "speech_01", wavBytes: edgeCases.kawaiiSynth },
      { id: "branch_nama", category: "match_01", wavBytes: edgeCases.kawaiiSynth },
      { id: "tsukinami_ref", category: "general", wavBytes: edgeCases.kawaiiSynth },
      { id: "herusu_380", category: "general", wavBytes: edgeCases.kawaiiSynth },
      { id: "ch1_mono", category: "general", wavBytes: edgeCases.kawaiiSynth },
      // Voiced-sibilant traps (must NOT match VSIB_TOKEN_RE)
      { id: "romaji_01", category: "romaji_test", wavBytes: edgeCases.kawaiiSynth },
      { id: "kanji_01", category: "emoji_1", wavBytes: edgeCases.kawaiiSynth },
      { id: "bare_aji_400", category: "bare_onset", wavBytes: edgeCases.kawaiiSynth },
      { id: "jitter_01", category: "general", wavBytes: edgeCases.kawaiiSynth },
    ], { includeDefaultGates: false });
    assert.ok(sTrap.rollups.min_vsib_coexist_pct > 50.0,
      `Trap labels polluted min_vsib_coexist_pct: ${sTrap.rollups.min_vsib_coexist_pct}`);
    assert.ok(sTrap.rollups.min_affr_closure_depth_db > 20.0,
      `Trap labels polluted min_affr_closure_depth_db: ${sTrap.rollups.min_affr_closure_depth_db}`);

    // Positive token matching check: each canonical token MUST be selected into its respective rollup
    for (const [id, cat] of [["ji_400", "general"], ["high_pitch_ji_bare", "general"], ["voiced_sibilant_hi", "general"]]) {
      const sp = runSuite([
        { id: "zrow_good", category: "dakuon_z", wavBytes: vsibWavM },
        { id, category: cat, wavBytes: edgeCases.kawaiiSynth },
      ], { includeDefaultGates: false });
      assert.equal(sp.rollups.min_vsib_coexist_pct, 0.0,
        `Positive vsib token '${id}' was NOT selected by VSIB_TOKEN_RE: got ${sp.rollups.min_vsib_coexist_pct}`);
    }
    for (const [id, cat] of [["ch_380", "general"], ["chi_400", "general"], ["tsu_380", "general"]]) {
      const sp = runSuite([
        { id: "affr_good", category: "affricate", wavBytes: affrWavM },
        { id, category: cat, wavBytes: edgeCases.kawaiiSynth },
      ], { includeDefaultGates: false });
      assert.equal(sp.rollups.min_affr_closure_depth_db, 0.0,
        `Positive affr token '${id}' was NOT selected by AFFR_TOKEN_RE: got ${sp.rollups.min_affr_closure_depth_db}`);
    }
  }

  // 14c. Malformed entry.gates / opts.defaultGates / evaluateItemGates null-skip & duplicate ID contract
  {
    for (const badGates of ["kawaii_overall_100 >= 99", "", 123, true, [[">=", 80]], []]) {
      assert.throws(
        () => runSuite([{ id: "bad_g", wavBytes: edgeCases.kawaiiSynth, gates: badGates }]),
        TypeError,
        `entry.gates=${JSON.stringify(badGates)} must throw TypeError`
      );
    }
    for (const badDef of ["bad", [], 42]) {
      assert.throws(
        () => runSuite([{ id: "ok", wavBytes: edgeCases.kawaiiSynth }], { defaultGates: badDef }),
        TypeError,
        `opts.defaultGates=${JSON.stringify(badDef)} must throw TypeError`
      );
    }
    assert.throws(() => runSuite([{ id: "ok", wavBytes: edgeCases.kawaiiSynth }], "badOpts"), TypeError);
    assert.throws(() => runSuite([[]]), TypeError);

    const evalNullSkip = evaluateItemGates(edgeRes.kawaiiSynth, {
      artifact_risk_100: null,
      kawaii_overall_100: [">=", 0],
    });
    assert.equal(evalNullSkip.length, 1);
    assert.equal(evalNullSkip[0].passed, true);
    assert.throws(() => evaluateItemGates(edgeRes.kawaiiSynth, "bad"), TypeError);

    // Explicit duplicate id MUST throw
    assert.throws(
      () => runSuite([
        { id: "dup", wavBytes: edgeCases.kawaiiSynth },
        { id: "dup", wavBytes: kawaiiAlt },
      ]),
      /Duplicate suite item id/
    );
  }

  // 14d. Subprocess CLI tests + auto-derived basename duplicate + symlinked CLI in isolated mktemp
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "xray_test_cli_"));
  try {
    const runJs = path.join(__dirname, "run.mjs");
    const wClean = path.join(tmpDir, "clean320.wav");
    const wKawaii = path.join(tmpDir, "kawaii340.wav");
    const wBad = path.join(tmpDir, "bad.wav");
    fs.writeFileSync(wClean, kawaiiAlt);
    fs.writeFileSync(wKawaii, edgeCases.kawaiiSynth);
    fs.writeFileSync(wBad, edgeCases.clickImpulse);

    // Auto-derived basename duplicate: dirA/sample.wav (FAIL) + dirB/sample.wav (PASS) -> sample & sample#2
    const dirA = path.join(tmpDir, "dirA");
    const dirB = path.join(tmpDir, "dirB");
    fs.mkdirSync(dirA);
    fs.mkdirSync(dirB);
    fs.writeFileSync(path.join(dirA, "sample.wav"), edgeCases.clickImpulse);
    fs.writeFileSync(path.join(dirB, "sample.wav"), edgeCases.kawaiiSynth);
    const sAutoDup = runSuite([
      { wav: "dirA/sample.wav" },
      { wav: "dirB/sample.wav" },
    ], { baseDir: tmpDir });
    assert.deepEqual(sAutoDup.items.map((x) => x.id), ["sample", "sample#2"]);
    assert.equal(Object.keys(sAutoDup.gates.byItem).length, 2);
    assert.equal(sAutoDup.gates.byItem["sample"].passed, false, "Auto-dup item 0 failure must NOT be overwritten");
    assert.equal(sAutoDup.gates.byItem["sample#2"].passed, true);
    assert.equal(sAutoDup.passed, false);

    // Pre-reserved explicit id colliding with omitted id -> auto item shifts to sample#2
    const sMixDup = runSuite([
      { wav: "dirA/sample.wav" },
      { id: "sample", wav: "dirB/sample.wav" },
    ], { baseDir: tmpDir });
    assert.deepEqual(sMixDup.items.map((x) => x.id), ["sample#2", "sample"]);
    assert.equal(sMixDup.gates.byItem["sample#2"].passed, false);
    assert.equal(sMixDup.gates.byItem["sample"].passed, true);

    const passManifest = path.join(tmpDir, "pass.json");
    const failManifest = path.join(tmpDir, "fail.json");
    const badGatesManifest = path.join(tmpDir, "bad_gates.json");
    const htmlOut = path.join(tmpDir, "suite_report.html");
    fs.writeFileSync(passManifest, JSON.stringify([
      { id: "clean320", category: "general", hz: 320, wav: "clean320.wav" },
      { id: "kawaii340", category: "general", hz: 340, wav: "kawaii340.wav" },
    ]));
    fs.writeFileSync(failManifest, JSON.stringify([
      { id: "bad", category: "general", hz: 350, wav: "bad.wav" },
    ]));
    fs.writeFileSync(badGatesManifest, JSON.stringify([
      { id: "badg", category: "general", wav: "clean320.wav", gates: "kawaii_overall_100 >= 99" },
    ]));

    // Fake PNG & sr=0 WAV for CLI rejection
    const fakePng = path.join(tmpDir, "fake.png");
    const pngBuf = new Uint8Array(128);
    pngBuf.set([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A], 0);
    fs.writeFileSync(fakePng, pngBuf);
    const badSr0 = path.join(tmpDir, "bad_sr0.wav");
    const sr0Buf = Uint8Array.from(edgeCases.empty0);
    new DataView(sr0Buf.buffer).setUint32(24, 0, true);
    fs.writeFileSync(badSr0, sr0Buf);

    // PASS --suite --ref-wav --gate-strict --json --report (stdout MUST be pure JSON!)
    const pPass = spawnSync("node", [runJs, "--suite", passManifest, "--ref-wav", wClean, "--gate-strict", "--json", "--report", htmlOut], { encoding: "utf8" });
    assert.equal(pPass.status, 0, `PASS suite CLI exited ${pPass.status}: ${pPass.stderr}`);
    const jPass = JSON.parse(pPass.stdout);
    assert.equal(jPass.passed, true);
    assert.equal(jPass.items.length, 2);
    assert.equal(Object.keys(jPass.items[0].metrics).length, 150);
    assert.ok(!("visuals" in jPass.items[0]), "--json output must strip visuals");
    const htmlTxt = fs.readFileSync(htmlOut, "utf8");
    assert.ok(htmlTxt.includes("150") && htmlTxt.includes("Cat 13") && htmlTxt.includes("Suite Verdict"), "HTML report missing 150/Cat 13/Suite panel");

    // FAIL --suite --gate-strict --json -> exit 1
    const pFail = spawnSync("node", [runJs, "--suite", failManifest, "--gate-strict", "--json"], { encoding: "utf8" });
    assert.equal(pFail.status, 1, `FAIL suite CLI must exit 1 under --gate-strict, got ${pFail.status}`);
    const jFail = JSON.parse(pFail.stdout);
    assert.equal(jFail.passed, false);
    assert.ok(jFail.failures.length > 0);

    // Legacy CLI --json <w1> <w2>
    const pLeg = spawnSync("node", [runJs, "--json", wClean, wKawaii], { encoding: "utf8" });
    assert.equal(pLeg.status, 0, `Legacy CLI failed: ${pLeg.stderr}`);
    const jLeg = JSON.parse(pLeg.stdout);
    assert.ok(Array.isArray(jLeg) && jLeg.length === 2);
    assert.equal(Object.keys(jLeg[0].metrics).length, 150);
    assert.equal(Object.keys(jLeg[1].metrics).length, 150);

    // Hardened CLI error cases — ALL must exit 1 with [xray] Error: on stderr
    const cliFailCases = [
      ["empty --suite", ["--suite", ""]],
      ["ws --suite", ["--suite", "   "]],
      ["empty --ref-wav", ["--suite", passManifest, "--ref-wav", ""]],
      ["empty --report", ["--report", "", wClean]],
      ["--ref-wav without --suite", ["--ref-wav", wClean, "--json", wKawaii]],
      ["--gate-strict without --suite", ["--gate-strict", wClean]],
      ["--no-default-gates without --suite", ["--no-default-gates", wClean]],
      ["stray positional with --suite", ["--suite", passManifest, wClean]],
      ["--json with 0 WAVs", ["--json"]],
      ["empty positional", [""]],
      ["unknown short flag -x", ["-x", wClean]],
      ["fake PNG input", ["--json", fakePng]],
      ["sr=0 WAV input", ["--json", badSr0]],
      ["malformed string gates manifest", ["--suite", badGatesManifest, "--gate-strict"]],
    ];
    for (const [label, cliArgs] of cliFailCases) {
      const pr = spawnSync("node", [runJs, ...cliArgs], { encoding: "utf8" });
      assert.equal(pr.status, 1, `CLI case '${label}' expected exit 1, got ${pr.status} (stdout=${pr.stdout})`);
      assert.ok(pr.stderr.includes("[xray] Error:"), `CLI case '${label}' missing [xray] Error on stderr: ${pr.stderr}`);
    }

    // Symlinked CLI invocation MUST still execute main() via realpathSync
    const linkPath = path.join(tmpDir, "xray_link.mjs");
    fs.symlinkSync(runJs, linkPath);
    const pSym = spawnSync("node", [linkPath, "--json", wClean], { encoding: "utf8" });
    assert.equal(pSym.status, 0, `Symlinked CLI failed: ${pSym.stderr}`);
    const jSym = JSON.parse(pSym.stdout);
    assert.ok(Array.isArray(jSym) && jSym.length === 1);
    assert.equal(Object.keys(jSym[0].metrics).length, 150);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}
console.log("[PASS] Group 14: decodeWav validation, suite hardening, duplicate IDs, CLI guards & symlink");

// =========================================================================
// Group 15: Real Human Calibration (hanamaru*.wav PASS) & Frozen tokiko f21ac7b Regression (zrow_302 FAIL)
// =========================================================================
{
  const SCR = "/home/antigravity/.gemini/jetski/brain/v1/default/jetski_remote_agents_3p/7b3b6152-ce00-42db-990f-839b65a1a74a/scratch";
  const han1 = path.join(SCR, "hanamaru.wav");
  const han2 = path.join(SCR, "hanamaru_flat_ok.wav");
  if (fs.existsSync(han1) && fs.existsSync(han2)) {
    const sHum = runSuite([
      { id: "hanamaru", category: "human_ref", wav: han1 },
      { id: "hanamaru_flat_ok", category: "human_ref", wav: han2 },
    ]);
    assert.equal(sHum.passed, true, `Human reference WAVs MUST PASS default gates: ${JSON.stringify(sHum.failures)}`);
    assert.equal(sHum.gates.passed, 10, `Expected 10/10 default gates passed on human refs, got ${sHum.gates.passed}/${sHum.gates.total}`);
    for (const it of sHum.items) {
      assertAllFinite(it.metrics, it.id);
      assert.ok(it.metrics.artifact_risk_100 < 12.0, `${it.id} artifact_risk_100=${it.metrics.artifact_risk_100} >= 12`);
      assert.ok(it.metrics.intelligibility_guard_100 >= 95.0, `${it.id} guard=${it.metrics.intelligibility_guard_100} < 95`);
      assert.ok(it.metrics.cliff_all_ratio < 55.0, `${it.id} cliff_all_ratio=${it.metrics.cliff_all_ratio} >= 55`);
    }

    // Inject 1 single-sample audible click (+0.30 at midpoint) into hanamaru.wav -> MUST FAIL default gates
    const { sr: hanSr, samples: hanRaw } = decodeWav(fs.readFileSync(han1));
    const hanClk = Float32Array.from(hanRaw);
    const midIdx = hanClk.length >> 1;
    hanClk[midIdx] = Math.max(-1.0, Math.min(1.0, hanClk[midIdx] + 0.30));
    const hanClkWav = encodeWav(hanClk, hanSr);
    const sHanClk = runSuite([{ id: "hanamaru_1clk", category: "human_ref", wavBytes: hanClkWav }]);
    const mHanClk = sHanClk.items[0].metrics;
    assert.ok(mHanClk.cliff_impulse_ratio > 55.0, `hanamaru+1clk #16 missed: ${mHanClk.cliff_impulse_ratio}`);
    assert.ok(mHanClk.cliff_all_ratio > 55.0, `hanamaru+1clk #134 missed: ${mHanClk.cliff_all_ratio}`);
    assert.ok(mHanClk.artifact_risk_100 > 12.0, `hanamaru+1clk #83 missed: ${mHanClk.artifact_risk_100}`);
    assert.equal(sHanClk.passed, false, "hanamaru.wav + 1 audible click MUST FAIL default gates");

    console.log(
      `[PASS] Group 15a: Human refs PASS 5/5 (` +
      `hanamaru art=${sHum.items[0].metrics.artifact_risk_100} kaw=${sHum.items[0].metrics.kawaii_overall_100} grd=${sHum.items[0].metrics.intelligibility_guard_100}, ` +
      `hanamaru_flat art=${sHum.items[1].metrics.artifact_risk_100} kaw=${sHum.items[1].metrics.kawaii_overall_100} grd=${sHum.items[1].metrics.intelligibility_guard_100}; ` +
      `hanamaru+1clk FAIL: cliff=${mHanClk.cliff_all_ratio}, art=${mHanClk.artifact_risk_100})`
    );
  } else {
    console.log("[SKIP] Group 15a: Local human reference WAVs not found");
  }

  const tokikoDir = "/home/antigravity/poidowl/tokiko";
  if (fs.existsSync(path.join(tokikoDir, ".git"))) {
    const tmpTok = fs.mkdtempSync(path.join(os.tmpdir(), "xray_tokiko_f21_"));
    try {
      const src = execFileSync("git", ["-C", tokikoDir, "show", "f21ac7b:kuda.mjs"], { encoding: "utf8" });
      const modPath = path.join(tmpTok, "kuda_f21.mjs");
      fs.writeFileSync(modPath, src);
      const { synthKuda, encodeWav: encodeTok } = await import(pathToFileURL(modPath).href);
      const zrowWav = encodeTok(synthKuda("ざ、じ、ず、ぜ、ぞ", { preset: "kawaii", hz: 302, srOut: 24000 }).samples, 24000);
      const herutsuWav = encodeTok(synthKuda("よんひゃくへるつ、さんびゃくへるつ", { preset: "kawaii", hz: 380, srOut: 24000 }).samples, 24000);
      const herusuWav = encodeTok(synthKuda("よんひゃくへるす、さんびゃくへるす", { preset: "kawaii", hz: 380, srOut: 24000 }).samples, 24000);

      const sZ = runSuite([
        { id: "f21_zrow_302", category: "voiced_sibilant", hz: 302, wavBytes: zrowWav },
      ]);
      const mz = sZ.items[0].metrics;
      assertAllFinite(mz, "f21_zrow_302");
      assert.equal(sZ.passed, false, "Frozen tokiko f21ac7b zrow_302 MUST FAIL default safety gates");
      assert.equal(sZ.gates.passed, 0, `zrow_302 expected 0/5 default gates passed, got ${sZ.gates.passed}/${sZ.gates.total}`);
      assert.ok(mz.artifact_risk_100 >= 25.0, `zrow_302 artifact_risk_100=${mz.artifact_risk_100} < 25`);
      assert.ok(mz.cliff_all_ratio > 55.0, `zrow_302 cliff_all_ratio=${mz.cliff_all_ratio} <= 55`);
      assert.ok(mz.max_sample_jump > 6.0, `zrow_302 max_sample_jump=${mz.max_sample_jump} <= 6`);
      assert.ok(mz.pl_erb_rough_p90 > 14.0, `zrow_302 pl_erb_rough_p90=${mz.pl_erb_rough_p90} <= 14`);
      assert.ok(mz.kawaii_overall_100 < 85.0, `zrow_302 kawaii_overall_100=${mz.kawaii_overall_100} >= 85`);
      assert.ok(mz.intelligibility_guard_100 < 85.0, `zrow_302 guard=${mz.intelligibility_guard_100} >= 85`);

      const mTsu = analyzeBuffer(herutsuWav).metrics;
      const mSu = analyzeBuffer(herusuWav).metrics;
      assert.ok(mTsu.affr_closure_depth_db > 35.0,
        `f21 herutsu_380 affricate closure too low: depth=${mTsu.affr_closure_depth_db}`);
      assert.ok(mTsu.affr_burst_jump_db > 20.0,
        `f21 herutsu_380 affricate burst jump too low: jump=${mTsu.affr_burst_jump_db}`);
      assert.equal(mSu.affr_closure_depth_db, 0.0,
        `f21 herusu_380 should not false-alarm affricate closure: ${mSu.affr_closure_depth_db}`);

      console.log(
        `[PASS] Group 15b: Frozen tokiko f21ac7b regression verified ` +
        `(zrow_302 FAIL 0/5: art=${mz.artifact_risk_100}, cliff=${mz.cliff_all_ratio}, jmp=${mz.max_sample_jump}, ` +
        `pl90=${mz.pl_erb_rough_p90}, kaw=${mz.kawaii_overall_100}, guard=${mz.intelligibility_guard_100}; ` +
        `herutsu=${mTsu.affr_closure_depth_db}/${mTsu.affr_burst_jump_db}dB vs herusu=${mSu.affr_closure_depth_db}dB)`
      );
    } finally {
      fs.rmSync(tmpTok, { recursive: true, force: true });
    }
  } else {
    console.log("[SKIP] Group 15b: Local tokiko git repo not found");
  }
}

console.log(`ALL 150 X-RAY TOOLS & 15 TEST GROUPS PASSED! (0 NaN/Inf, ${Object.keys(DEFAULT_SAFETY_GATES).length} default safety gates verified)`);
