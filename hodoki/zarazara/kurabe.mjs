#!/usr/bin/env node
/**
 * hodoki/zarazara/kurabe.mjs — 草薙 v8 のザラザラ（シマー高・HNR低・周期類似の低さ）の出どころ調べ
 *
 *   node hodoki/zarazara/kurabe.mjs [--out /workspace/hodoki/zarazara] [--only name,name] [--wav]
 *
 * 実験用コピー hitofude_lab.mjs の opts.lab で段を1つずつ切る／理想化し、Hodoki soroi で測る。
 * 文（わたし、にほんご、ちょっとしゃべれます）と、持続母音（歌モードで「ア」を 2 秒・350 Hz・ビブラート 0）の両方。
 * シマーは「有声区間の端から 60 ms 以内」と「それより内側（定常）」にも分けて出す。
 */
import fs from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import { makeHitofude, PRESETS, encodeWav, SR } from "./hitofude_lab.mjs";
import { analyze } from "../soroi.mjs";

export const TEXT = "わたし、にほんご、ちょっとしゃべれます";
export const CONDITIONS = [
  ["base", "hitofude そのまま", {}, {}],
  ["no_jit_wander", "jitter=0・wander_st=0", { jitter: 0, wander_st: 0 }, {}],
  ["no_level", "整音 level_k=0", { level_k: 0 }, {}],
  ["no_env_wander", "漂いによる音量ゆれ(×(1+0.24w))を切る", {}, { noEnvWander: true }],
  ["no_lung", "肺圧の漂い pLungWalk を一定に", {}, { noLungWalk: true }],
  ["no_rawair", "扉を通る生ノイズ rawAir·x を 0", {}, { noRawAir: true }],
  ["no_tanh", "コム帰還の tanh を外す", {}, { noTanh: true }],
  ["no_doorbw", "扉で声道帯域幅を広げるのを切る", {}, { doorBwOff: true }],
  ["no_load", "声道→扉の負荷帰還(pLoad)を切る", {}, { noLoad: true }],
  ["comb_g995", "コム帰還を 0.995（毎周期の新しいノイズを減らす）", {}, { combG: 0.995 }],
  ["comb_lock", "コム入力を位相固定ノイズ（同じ x を周期位相で読む）", {}, { combLock: 1.0 }],
  ["ideal_door", "扉を位相だけで決まる理想パルスに", {}, { idealDoor: true }],
  ["ideal_door_no_rawair", "理想扉＋rawAir=0", {}, { idealDoor: true, noRawAir: true }],
  ["comb_lock_no_rawair", "位相固定コム＋rawAir=0", {}, { combLock: 1.0, noRawAir: true }],
  ["all_ideal", "理想扉＋rawAir=0＋肺圧一定＋jitter/wander=0", { jitter: 0, wander_st: 0 }, { idealDoor: true, noRawAir: true, noLungWalk: true }],
];

export function synthBoth(knobOver, lab, seed = 2024) {
  const p = { ...PRESETS.hitofude, ...knobOver, seed, lab };
  const sent = makeHitofude(TEXT, p).samples;
  const vow = makeHitofude("ア", { ...p, uta_hz: [p.hz], vd_ms: [2000], vib_c: 0.0, sigh: 0.0 }).samples;
  return { sent: Float64Array.from(sent), vow: Float64Array.from(vow) };
}

/** soroi の要約＋端/定常に分けたシマー */
export function measure(x) {
  const r = analyze(x, SR);
  const fr = r.frames, hop = fr.length > 1 ? fr[1].t - fr[0].t : 0.01;
  const edges = [];
  for (let i = 0; i < fr.length; i++) {
    const v = fr[i].voiced, pv = i > 0 && fr[i - 1].voiced;
    if (v && !pv) edges.push(fr[i].t - hop / 2);
    if (!v && pv) edges.push(fr[i].t - hop / 2);
  }
  const nearEdge = (t) => edges.some((e) => Math.abs(t - e) < 0.06);
  const pe = r.pairs.filter((p) => nearEdge(p.t)), ps = r.pairs.filter((p) => !nearEdge(p.t));
  const sh = (ps_) => {
    if (!ps_.length) return { pct: NaN, db: NaN, n: 0 };
    const dA = ps_.reduce((s, p) => s + p.dA, 0) / ps_.length, Am = ps_.reduce((s, p) => s + p.Am, 0) / ps_.length;
    return { pct: (100 * dA) / Am, db: ps_.reduce((s, p) => s + p.dDb, 0) / ps_.length, n: ps_.length };
  };
  return { ...r.summary, edge: sh(pe), steady: sh(ps) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { values: a } = parseArgs({ options: { out: { type: "string", default: "/workspace/hodoki/zarazara" }, only: { type: "string" }, wav: { type: "boolean" }, seed: { type: "string" } } });
  fs.mkdirSync(a.out, { recursive: true });
  const only = a.only ? new Set(a.only.split(",")) : null;
  const rows = [];
  for (const [name, desc, kn, lab] of CONDITIONS) {
    if (only && !only.has(name)) continue;
    const s = synthBoth(kn, lab, a.seed ? Number(a.seed) : 2024);
    const ms = measure(s.sent), mv = measure(s.vow);
    rows.push({ name, desc, sent: ms, vow: mv });
    if (a.wav) { fs.writeFileSync(path.join(a.out, `abl_${name}_bun.wav`), encodeWav(s.sent)); fs.writeFileSync(path.join(a.out, `abl_${name}_a.wav`), encodeWav(s.vow)); }
    const f = (m) => `シマー ${m.shimmer_local_pct.toFixed(1)}% (${m.shimmer_local_db.toFixed(2)}dB) 端 ${m.edge.pct.toFixed(1)}% 定常 ${m.steady.pct.toFixed(1)}%  HNR ${m.hnr_db.toFixed(1)}  相関 ${m.period_corr_median.toFixed(3)}  ジッター ${m.jitter_local_pct.toFixed(2)}%`;
    console.log(`${name.padEnd(22)} 文: ${f(ms)}\n${"".padEnd(22)} ア: ${f(mv)}`);
  }
  fs.writeFileSync(path.join(a.out, "kurabe.json"), JSON.stringify(rows, null, 1));
}
