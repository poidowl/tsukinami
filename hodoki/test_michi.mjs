#!/usr/bin/env node
/**
 * hodoki/test_michi.mjs — Hodoki「声の道（michi）」と「つまみ当て（tsumami）」の検定
 *   node hodoki/test_michi.mjs          # 全部（約1分）
 *   node hodoki/test_michi.mjs --quick  # つまみ当ての study を省く
 * データは JS で作るテスト音と草薙（../hitofude.mjs）の合成音だけ。
 */
import assert from "node:assert/strict";
import { analyzeMichi, C_CM_S } from "./michi.mjs";
import { makeHitofude, PRESETS } from "../hitofude.mjs";
import { study } from "./tsumami.mjs";

const SR = 44100, quick = process.argv.includes("--quick");
const results = [];
function check(name, fn) {
  try { fn(); results.push("ok"); console.log(`ok   ${name}`); }
  catch (e) { results.push("FAIL"); console.log(`FAIL ${name}\n     ${e.message}`); }
}
function res2(x, F, B) { const y = new Float64Array(x.length); let y1 = 0, y2 = 0; const r = Math.exp((-Math.PI * B) / SR), b = 2 * r * Math.cos((2 * Math.PI * F) / SR), c = -r * r; for (let i = 0; i < x.length; i++) { const o = (1 - b - c) * x[i] + b * y1 + c * y2; y2 = y1; y1 = o; y[i] = o; } return y; }
/** 倍音振幅 h^-alpha の定常音源（alpha=1 → H1−H2 = 6.02 dB, alpha=2 → 12.04 dB）を共鳴器の直列に通す */
function vowel(f0, Fs, Bs, alpha = 2, dur = 1.0) {
  const n = Math.round(dur * SR), H = Math.floor(7000 / f0); let x = new Float64Array(n);
  for (let i = 0; i < n; i++) { let v = 0; for (let h = 1; h <= H; h++) v += Math.sin((2 * Math.PI * h * f0 * i) / SR) * Math.pow(h, -alpha); x[i] = v; }
  for (let k = 0; k < Fs.length; k++) x = res2(x, Fs[k], Bs[k]);
  let pk = 0; for (const v of x) pk = Math.max(pk, Math.abs(v));
  return x.map((v) => (0.7 * v) / pk);
}
const tube = (L) => [1, 3, 5, 7, 9].map((k) => (k * C_CM_S) / (4 * L));
const pct = (a, b) => (100 * (a - b)) / b;

// ---- A. 一様管の共鳴器 × f0 100–450 Hz：声道長とフォルマントの偏り（plain と henv を並べて記録）
console.log("A. 一様管テスト（B=60/80/110/150/200 Hz, 音源 −12 dB/oct）  F誤差% は採用方式 henv、[ ] は通常 LPC");
const bias = [];
for (const L of [12, 14.5, 17.5]) {
  for (const f0 of [100, 150, 200, 250, 300, 350, 400, 450]) {
    const x = vowel(f0, tube(L), [60, 80, 110, 150, 200]);
    const c = analyzeMichi(x, SR).card, cp = analyzeMichi(x, SR, { method: "plain" }).card;
    const T = tube(L), e = [c.F1, c.F2, c.F3, c.F4].map((q, i) => pct(q.med, T[i])), ep = [cp.F1, cp.F2, cp.F3, cp.F4].map((q, i) => pct(q.med, T[i]));
    bias.push({ L, f0, vtl: c.vtl_cm.med, e, vtlP: cp.vtl_cm.med, ep, h1h2c: c.h1h2c_db.med, h1h2: c.h1h2_db.med });
    console.log(`  L=${String(L).padEnd(4)} f0=${String(f0).padEnd(3)} VTL ${c.vtl_cm.med.toFixed(2)} [${fx(cp.vtl_cm.med)}] cm  F1..F4 誤差 ${e.map((v) => v.toFixed(1)).join("/")} % [${ep.map((v) => fx(v, 1)).join("/")}]  H1*−H2* ${c.h1h2c_db.med.toFixed(2)} dB (未補正 ${c.h1h2_db.med.toFixed(2)})`);
  }
}
function fx(v, d = 2) { return Number.isFinite(v) ? v.toFixed(d) : "—"; }
check("一様管: 声道長が全 f0（100–450 Hz）・全長（12/14.5/17.5 cm）で ±3% 以内", () => { for (const b of bias) assert.ok(Math.abs(pct(b.vtl, b.L)) < 3, JSON.stringify(b)); });
check("一様管: F1 ±12%、F2–F4 ±8% 以内（henv）", () => { for (const b of bias) { assert.ok(Math.abs(b.e[0]) < 12, JSON.stringify(b)); for (let i = 1; i < 4; i++) assert.ok(Math.abs(b.e[i]) < 8, JSON.stringify(b)); } });
check("一様管: f0 ≤ 200 Hz では F1–F4 すべて ±4% 以内", () => { for (const b of bias.filter((q) => q.f0 <= 200)) for (const v of b.e) assert.ok(Math.abs(v) < 4, JSON.stringify(b)); });
{
  const hi = bias.filter((b) => b.f0 >= 300), lo = bias.filter((b) => b.f0 <= 200);
  const m = (a) => a.reduce((s, v) => s + Math.abs(v), 0) / a.length;
  console.log(`  F1 の平均|誤差|: f0≤200 henv ${m(lo.map((b) => b.e[0])).toFixed(1)}% / plain ${m(lo.map((b) => b.ep[0]).filter(Number.isFinite)).toFixed(1)}%   f0≥300 henv ${m(hi.map((b) => b.e[0])).toFixed(1)}% / plain ${m(hi.map((b) => b.ep[0]).filter(Number.isFinite)).toFixed(1)}%`);
}

// ---- B. H1−H2
console.log("B. H1−H2");
for (const alpha of [1, 2]) for (const f0 of [100, 200, 350, 450]) {
  const c = analyzeMichi(vowel(f0, [], [], alpha), SR).card;
  check(`音源だけ（−${6 * alpha} dB/oct）f0=${f0}: H1−H2 = ${(6.02 * alpha).toFixed(2)}±0.5 dB（実測 ${c.h1h2_db.med.toFixed(2)}）`, () => assert.ok(Math.abs(c.h1h2_db.med - 6.02 * alpha) < 0.5));
}
check("一様管つき: 補正 H1*−H2* が真値 12.04 dB の ±2.5 dB（f0 ≤ 250）/ ±3.5 dB（f0 > 250）", () => { for (const b of bias) assert.ok(Math.abs(b.h1h2c - 12.04) < (b.f0 <= 250 ? 2.5 : 3.5), JSON.stringify(b)); });
check("一様管つき: 未補正 H1−H2 は f0 によって真値から 10 dB 以上外れることがある（補正が要る証拠）", () => assert.ok(bias.some((b) => Math.abs(b.h1h2 - 12.04) > 10)));

// ---- C. 草薙：合成に使ったフォルマント軌道（真値）と比べる
console.log("C. 草薙の真値フォルマント軌道との比較");
const T0 = "わたし、にほんご、ちょっとしゃべれます";
function kusanagiTruth(p) {
  const out = makeHitofude(T0, p), r = out.r, fs = p.fscale, vt = [];
  const tr = (i) => { const F1 = Math.max(r.F1[i] * fs, 1.04 * r.f0_tr[i]), F2 = Math.min(Math.max(r.F2[i] * fs, F1 + 280), 8500), F3 = Math.min(Math.max(r.F3[i] * fs, F2 + 350), 9000), F4 = Math.min(8600, F3 + 1150 * fs); return [F1, F2, F3, F4]; };
  for (let i = 0; i < r.voiced.length; i++) if (r.voiced[i]) { const F = tr(i); vt.push((C_CM_S * 84) / (4 * (F[0] + 3 * F[1] + 5 * F[2] + 7 * F[3]))); }
  vt.sort((a, b) => a - b);
  return { x: Float64Array.from(out.samples), vtlTrue: vt[vt.length >> 1], tr, r };
}
for (const [name, over] of [["hitofude", {}], ["alto", {}], ["ossan", {}], ["chibi", {}], ["sasayaki", {}], ["hitofude", { fscale: 0.9 }], ["hitofude", { hz: 150 }]]) {
  const p = { ...PRESETS[name], ...over }, k = kusanagiTruth(p), res = analyzeMichi(k.x, SR), c = res.card;
  const err = [[], [], [], []];
  for (const f of res.frames) { const i = Math.round(f.t / 0.005); if (!f.F || !k.r.voiced[i]) continue; k.tr(i).forEach((v, j) => err[j].push(Math.abs(pct(f.F[j], v)))); }
  const md = (a) => { const s = [...a].sort((x, y) => x - y); return s[s.length >> 1]; };
  const tag = name + (Object.keys(over).length ? JSON.stringify(over) : "");
  console.log(`  ${tag.padEnd(24)} f0 ${c.f0_hz.med.toFixed(0)} Hz  VTL ${c.vtl_cm.med.toFixed(2)} cm (IQR ${c.vtl_cm.q1.toFixed(2)}–${c.vtl_cm.q3.toFixed(2)})  真値 ${k.vtlTrue.toFixed(2)} cm  F1..F4 |誤差|中央値 ${err.map((e) => md(e).toFixed(1)).join("/")} %  使用 ${c.frames_used}/${c.frames_voiced}`);
  check(`草薙 ${tag}: 声道長が真値の ±8% 以内`, () => assert.ok(Math.abs(pct(c.vtl_cm.med, k.vtlTrue)) < 8));
}
{
  const v = [0.9, 1.0, 1.1, 1.2, 1.3].map((fs) => analyzeMichi(kusanagiTruth({ ...PRESETS.hitofude, fscale: fs, seed: 5 }).x, SR).card.vtl_cm.med);
  console.log(`  fscale 0.9→1.3 の VTL: ${v.map((q) => q.toFixed(2)).join(" → ")} cm`);
  check("草薙: fscale を上げると推定声道長が単調に短くなる", () => { for (let i = 1; i < v.length; i++) assert.ok(v[i] < v[i - 1]); });
}

// ---- D. つまみ当て（乱数 60 本・seed も毎回違う → リッジ回帰の一個抜き R²）
if (!quick) {
  console.log("D. つまみ当て（60 本、seed も乱数）");
  const s = study(60, 3);
  for (const [k, v] of Object.entries(s.recover)) console.log(`  ${k.padEnd(10)} R²(LOO) ${v.r2_loo.toFixed(3)}  RMSE ${v.rmse.toPrecision(3)}  効く特徴 ${v.top.map(([f, c]) => `${f}(${c})`).join(" ")}`);
  const want = { hz: 0.95, fscale: 0.93, rate: 0.98, g_vo: 0.85 };
  for (const [k, th] of Object.entries(want)) check(`つまみ ${k}: R²(LOO) > ${th}`, () => assert.ok(s.recover[k].r2_loo > th, s.recover[k].r2_loo.toFixed(3)));
}

const nf = results.filter((r) => r !== "ok").length;
console.log(`\n${results.length - nf}/${results.length} passed`);
process.exit(nf ? 1 : 0);
