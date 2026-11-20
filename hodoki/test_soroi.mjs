#!/usr/bin/env node
/**
 * hodoki/test_soroi.mjs — Hodoki「揃い」モジュールの物差し検定（合成テスト音のみ・外部データなし）
 *   node hodoki/test_soroi.mjs
 * 既知の揺れを仕込んだテスト音を JS で作り、①〜④が仕込んだ量に沿って動くかを assert する。
 */
import assert from "node:assert/strict";
import { analyze } from "./soroi.mjs";

const SR = 44100;
function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const gauss = (r) => Math.sqrt(-2 * Math.log(r() + 1e-12)) * Math.cos(2 * Math.PI * r());

/**
 * 周期ごとに長さ T[i]・強さ A[i] を変えられる帯域制限パルス列（1/h 振幅の倍音和、位相連続）。
 * jit: 周期長を一様 ±jit 倍で独立に揺らす / shim: 振幅を一様 ±shim 倍で揺らす
 * snrDb: 白色ノイズを「倍音パワー/ノイズパワー = snrDb」で加算 / cents: h 次倍音を (−1)^h·cents ずらす
 */
function tone({ f0 = 220, dur = 1.5, jit = 0, shim = 0, snrDb = Infinity, cents = 0, seed = 1 } = {}) {
  const r = rng(seed), n = Math.round(dur * SR), H = Math.floor(6000 / f0);
  const x = new Float64Array(n);
  let ph = 0, T = SR / f0, A = 1;
  const ratio = Array.from({ length: H + 1 }, (_, h) => h * Math.pow(2, ((h % 2 ? -1 : 1) * (h > 1 ? cents : 0)) / 1200));
  const phs = new Float64Array(H + 1);
  for (let i = 0; i < n; i++) {
    let v = 0;
    for (let h = 1; h <= H; h++) v += Math.sin(phs[h]) / h;
    x[i] = A * v;
    const inc = 1 / T;
    ph += inc;
    for (let h = 1; h <= H; h++) phs[h] += 2 * Math.PI * ratio[h] * inc;
    // 長さは位相 0 で、強さは位相 0.5（鋸波が 0 を横切り、山と谷のどちらからも遠い点）で引き直す
    if (ph >= 0.5 && ph - inc < 0.5) A = 1 + shim * (2 * r() - 1);
    if (ph >= 1) { ph -= 1; T = (SR / f0) * (1 + jit * (2 * r() - 1)); }
  }
  if (Number.isFinite(snrDb)) {
    let p = 0; for (let i = 0; i < n; i++) p += x[i] * x[i]; p /= n;
    const s = Math.sqrt(p / Math.pow(10, snrDb / 10));
    for (let i = 0; i < n; i++) x[i] += s * gauss(r);
  }
  let pk = 0; for (const v of x) pk = Math.max(pk, Math.abs(v));
  for (let i = 0; i < n; i++) x[i] *= 0.8 / pk;
  return x;
}

function glide() { const n = Math.round(1.5 * SR), x = new Float64Array(n); let ph = 0; for (let i = 0; i < n; i++) { const f = 220 - (40 * i) / n; let v = 0; for (let h = 1; h <= 25; h++) v += Math.sin(h * ph) / h; x[i] = 0.4 * v; ph += (2 * Math.PI * f) / SR; } return x; }
const results = [];
function check(name, fn) {
  try { fn(); results.push([name, "ok"]); console.log(`ok   ${name}`); }
  catch (e) { results.push([name, "FAIL"]); console.log(`FAIL ${name}\n     ${e.message}`); }
}
const S = (p) => analyze(tone(p), SR).summary;
const show = (s) => `jit=${s.jitter_local_pct.toFixed(3)}% shim=${s.shimmer_local_pct.toFixed(2)}%/${s.shimmer_local_db.toFixed(3)}dB hnr=${s.hnr_db.toFixed(1)}dB inh=${s.inharm_cents.toFixed(2)}c f0=${s.f0_median_hz.toFixed(1)}`;

const clean = S({});
console.log("clean      ", show(clean));
check("完全周期: ジッター < 0.05%", () => assert.ok(clean.jitter_local_pct < 0.05, show(clean)));
check("完全周期: シマー < 0.05 dB", () => assert.ok(clean.shimmer_local_db < 0.05, show(clean)));
check("完全周期: HNR > 30 dB", () => assert.ok(clean.hnr_db > 30, show(clean)));
check("完全周期: 非整数倍度 < 1 cent", () => assert.ok(clean.inharm_cents < 1, show(clean)));
check("完全周期: 傾き除去ジッター < 0.05%", () => assert.ok(clean.jitter_detrended_pct < 0.05, show(clean)));
// 滑らかな高さの下降（220→180 Hz を 1.5 秒で）だけでは傾き除去ジッターは上がらない
check("滑らかな f0 下降: 傾き除去ジッター < 0.05%", () => { const s = analyze(glide(), SR).summary; console.log("glide      ", show(s), "detr=" + s.jitter_detrended_pct.toFixed(3) + "%"); assert.ok(s.jitter_detrended_pct < 0.05, show(s)); });
check("完全周期: f0 = 220 Hz ±1%", () => assert.ok(Math.abs(clean.f0_median_hz - 220) < 2.2, show(clean)));

// 一様 ±j の独立揺れ → 期待 local jitter = E|U1-U2| = 2j/3
const jits = [0.003, 0.015, 0.03].map((j) => [j, S({ jit: j })]);
for (const [j, s] of jits) {
  console.log(`jit ±${(100 * j).toFixed(1)}%  `, show(s));
  const want = (200 * j) / 3;
  check(`ジッター ±${(100 * j).toFixed(1)}%: 実測が期待 ${want.toFixed(2)}% の ±35% 以内`, () => assert.ok(Math.abs(s.jitter_local_pct - want) < 0.35 * want, show(s)));
}
check("ジッター: 仕込み量に対して単調増加", () => assert.ok(jits[0][1].jitter_local_pct < jits[1][1].jitter_local_pct && jits[1][1].jitter_local_pct < jits[2][1].jitter_local_pct));

const shims = [0.01, 0.05, 0.10].map((m) => [m, S({ shim: m })]);
for (const [m, s] of shims) {
  console.log(`shim ±${(100 * m).toFixed(0)}%  `, show(s));
  const want = (200 * m) / 3;
  check(`シマー ±${(100 * m).toFixed(0)}%: 実測が期待 ${want.toFixed(2)}% の ±35% 以内`, () => assert.ok(Math.abs(s.shimmer_local_pct - want) < 0.35 * want, show(s)));
  check(`シマー ±${(100 * m).toFixed(0)}%: ジッターは 0.1% 未満のまま（混線しない）`, () => assert.ok(s.jitter_local_pct < 0.1, show(s)));
}

const noisy = [30, 20, 10].map((d) => [d, S({ snrDb: d })]);
for (const [d, s] of noisy) {
  console.log(`snr ${d}dB    `, show(s));
  check(`ノイズ SNR ${d} dB: HNR が ${d}±3 dB`, () => assert.ok(Math.abs(s.hnr_db - d) < 3, show(s)));
}
check("ノイズ: HNR が単調減少、ジッター/シマーは単調増加", () => {
  assert.ok(noisy[0][1].hnr_db > noisy[1][1].hnr_db && noisy[1][1].hnr_db > noisy[2][1].hnr_db);
  assert.ok(noisy[0][1].jitter_local_pct < noisy[2][1].jitter_local_pct);
  assert.ok(noisy[0][1].shimmer_local_db < noisy[2][1].shimmer_local_db);
});

// 期待値：仕込んだ真の倍音周波数に、装置と同じ「振幅(1/h)重み付き最小二乗 f0*」を当てたときの重み付き平均|ずれ|
function expectInh(f0, c) {
  const H = Math.min(16, Math.floor(5000 / f0));
  const q = Array.from({ length: H }, (_, i) => { const h = i + 1; return { h, w: 1 / h, f: h * f0 * Math.pow(2, ((h % 2 ? -1 : 1) * (h > 1 ? c : 0)) / 1200) }; });
  let num = 0, den = 0; for (const v of q) { num += v.w * v.h * v.f; den += v.w * v.h * v.h; }
  const fs = num / den; let sw = 0, sd = 0;
  for (const v of q) { sw += v.w; sd += v.w * Math.abs(1200 * Math.log2(v.f / (v.h * fs))); }
  return sd / sw;
}
const inh = [5, 15].map((c) => [c, S({ cents: c })]);
for (const [c, s] of inh) {
  console.log(`inharm ±${c}c  `, show(s));
  const want = expectInh(220, c);
  check(`非整数倍度 ±${c} cents 仕込み: 実測が期待 ${want.toFixed(2)} cents の ±20% 以内`, () => assert.ok(Math.abs(s.inharm_cents - want) < 0.2 * want, show(s)));
}
check("非整数倍度: 仕込み量に対して単調増加（完全周期 < 5c < 15c）", () => assert.ok(clean.inharm_cents < inh[0][1].inharm_cents && inh[0][1].inharm_cents < inh[1][1].inharm_cents));

// 高い声（草薙の帯域 350 Hz 付近）でも完全周期が揃って見えるか
const hi = S({ f0: 350 });
console.log("clean 350Hz", show(hi));
check("完全周期 350 Hz: f0 = 350±1%・ジッター < 0.05%・HNR > 30 dB", () => assert.ok(Math.abs(hi.f0_median_hz - 350) < 3.5 && hi.jitter_local_pct < 0.05 && hi.hnr_db > 30, show(hi)));

const nf = results.filter((r) => r[1] !== "ok").length;
console.log(`\n${results.length - nf}/${results.length} passed`);
process.exit(nf ? 1 : 0);
