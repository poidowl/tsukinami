#!/usr/bin/env node
// xray/test_xray.mjs — 変態解析ツール100選 自己検証テスト（合成正解信号＋V7.1音声で全100本の正常性＆感度を検証）
import assert from "node:assert/strict";
import { encodeWav, makeHitofude, PRESETS, SR } from "../hitofude.mjs";
import { ALL_TOOLS, analyzeBuffer } from "./run.mjs";

function makeSine(hz, durS = 1.0, extraFn = null) {
  const N = Math.trunc(SR * durS);
  const s = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    let v = 0.5 * Math.sin((2.0 * Math.PI * hz * i) / SR) + 0.2 * Math.sin((2.0 * Math.PI * 2 * hz * i) / SR);
    if (extraFn) v += extraFn(i);
    s[i] = Math.max(-1.0, Math.min(1.0, v));
  }
  return encodeWav(s);
}

function makeNoise(durS = 1.0) {
  const N = Math.trunc(SR * durS);
  const s = new Float32Array(N);
  let seed = 12345;
  for (let i = 0; i < N; i++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    s[i] = ((seed / 4294967296.0) * 2.0 - 1.0) * 0.35;
  }
  return encodeWav(s);
}

assert.equal(ALL_TOOLS.length, 130, `Expected 130 tools, got ${ALL_TOOLS.length}`);
const ids = new Set(ALL_TOOLS.map((t) => t.id));
assert.equal(ids.size, 130, "Tool IDs must be unique 1..130");

const cases = {
  sine350: makeSine(350.0, 0.8),
  whistle4100: makeSine(350.0, 0.8, (i) => 0.12 * Math.sin((2.0 * Math.PI * 4100.0 * i) / SR)),
  clickImpulse: makeSine(350.0, 0.8, (i) => (i % 4410 === 100 ? 0.6 : 0.0)),
  whiteNoise: makeNoise(0.8),
  kawaiiV71: encodeWav(makeHitofude("わたし、にほんご、ちょっとしゃべれます", PRESETS.kawaii).samples),
};

const res = {};
let refD = null, refM = null;
for (const [name, wav] of Object.entries(cases)) {
  const r = analyzeBuffer(wav, refD, refM);
  if (!refD) { refD = r.d; refM = r.metrics; }
  res[name] = r.metrics;
  for (const t of ALL_TOOLS) {
    const val = r.metrics[t.key];
    assert.ok(typeof val === "number" && Number.isFinite(val), `[${name}] Tool #${t.id} (${t.key}) returned non-finite: ${val}`);
  }
}

// Ground-truth physics sensitivity assertions
assert.ok(Math.abs(res.sine350.f0_mean_hz - 350.0) < 3.0, `F0 tracker failed on 350Hz sine: ${res.sine350.f0_mean_hz}`);
assert.ok(res.whistle4100.fixed_whistle_db > res.sine350.fixed_whistle_db + 10.0,
  `#15 fixed_whistle_db failed to catch 4.1kHz whistle: whistle=${res.whistle4100.fixed_whistle_db} vs sine=${res.sine350.fixed_whistle_db}`);
assert.ok(res.clickImpulse.cliff_impulse_ratio > res.sine350.cliff_impulse_ratio * 2.0,
  `#16 cliff_impulse_ratio failed to catch 1-sample click: click=${res.clickImpulse.cliff_impulse_ratio} vs sine=${res.sine350.cliff_impulse_ratio}`);
assert.ok(res.kawaiiV71.phaser_notch_depth < 12.0,
  `#17 phaser_notch_depth should not trigger on F0 valleys: ${res.kawaiiV71.phaser_notch_depth}`);
assert.ok(res.kawaiiV71.voiced_breath_ratio > 0.5,
  `#57 voiced_breath_ratio should detect V7.1 voiced breath: ${res.kawaiiV71.voiced_breath_ratio}`);
assert.equal(res.kawaiiV71.vis_100_report_ready, 100, "#100 report count must equal 100");

console.log(`ALL 100 X-RAY TOOLS PASSED! (0 NaN/Inf, all ground-truth physics sensors verified)`);
console.log(`  sine350 F0=${res.sine350.f0_mean_hz}Hz | #15 whistle=${res.whistle4100.fixed_whistle_db}dB (vs sine ${res.sine350.fixed_whistle_db}dB)`);
console.log(`  #16 click=${res.clickImpulse.cliff_impulse_ratio} (vs sine ${res.sine350.cliff_impulse_ratio}) | #17 V7.1 phaser=${res.kawaiiV71.phaser_notch_depth}dB`);
console.log(`  V7.1 kawaii_overall=${res.kawaiiV71.kawaii_overall_100} | artifact_risk=${res.kawaiiV71.artifact_risk_100} | radar=${res.kawaiiV71.vis_kawaii_radar}%`);
