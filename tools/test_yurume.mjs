#!/usr/bin/env node
/**
 * tools/test_yurume.mjs — 削りゆるめ任意ノブ（yurume_acc / yurume_toji / yurume_tani / yurume_bern）回帰テスト
 *
 *   node tools/test_yurume.mjs
 *
 * (a) ノブ未指定・0・null 明示が GOLDEN_ABB2DAE（abb2dae 既定音）と全プリセット × 2文 × seed 2 つでバイト一致すること。
 * (b) 各ノブ 1.0 は、効くはずのプリセットでだけ音を変え、効かないはずのプリセットではバイト一致のままであること
 *     （yurume_acc: sigh>=0.25 かつ hz>=200 のみ／yurume_toji・yurume_bern: 扉ありで hz>125（hiMix>0）のみ／yurume_tani: 扉あり shin>0 のみ）。
 * (c) 本命 R3b@2.0・比較用 R3c@1.5・各ノブ 1.0 で有限・長さ同一・ピーク 1 以下であること。
 * (d) yurume_tani: 1.0 は {combG: null} とバイト一致すること（g_vo 連動の帰還そのものに戻る）。
 */
import crypto from "node:crypto";
import { makeHitofude, PRESETS, encodeWav } from "../hitofude.mjs";

const GOLDEN_ABB2DAE = {
  "hitofude|t0|2024": "c2b95d6e1f7de627d51b55fd",
  "hitofude|t0|7": "d74d927a3ae2324bb376213f",
  "hitofude|t1|2024": "2e8b1ea03a2e4df937ab0acb",
  "hitofude|t1|7": "c72462f78758f1d8b2e6ff3d",
  "toiki|t0|2024": "9cf96d44aad6616d9c5c5ad9",
  "toiki|t0|7": "21da6d2f3b2d3e004905c6f5",
  "toiki|t1|2024": "03a069e4b967413bac1e27eb",
  "toiki|t1|7": "354add5651497833fb39c5f0",
  "alto|t0|2024": "2aeaf4886ae4a81f9beb4f83",
  "alto|t0|7": "38901d0fb75a7716c26948c9",
  "alto|t1|2024": "a1fe20fb5659a11d083a0c4d",
  "alto|t1|7": "935f9e16581f332f279341b5",
  "sasayaki|t0|2024": "3844bd580bfe79ba3af5d742",
  "sasayaki|t0|7": "fbc4b3d2f3547d32888b2016",
  "sasayaki|t1|2024": "761fbe01a8f7375ec2ddb265",
  "sasayaki|t1|7": "792ab76efd96393bb2ad1633",
  "chibi|t0|2024": "6154d9db4cd67b15fd935834",
  "chibi|t0|7": "46a4b9ea59434df966f49651",
  "chibi|t1|2024": "f88b844b6a8fbf337f0ec88e",
  "chibi|t1|7": "588c2cdcc56f76283715ab22",
  "ossan|t0|2024": "931258d84291742d5bc5650f",
  "ossan|t0|7": "6284697065dc6d4037af17ba",
  "ossan|t1|2024": "2732caa25bdec77f2d3038fa",
  "ossan|t1|7": "d819da4caa04560cec4f91f4",
  "robot|t0|2024": "ae5175c4ae8e7f1cfd796a7d",
  "robot|t0|7": "f28c8efe3896ebc2a06d0485",
  "robot|t1|2024": "ae4f9bf173bc49bb730e3a56",
  "robot|t1|7": "697f34c70a69ea8eeda46d3b",
};
const TEXTS = ["きょ'うは / あ'めが / ふ'ります", "わたし、にほんご、ちょっとしゃべれます"];
const REC_MAIN = { yurume_acc: 1.0, yurume_toji: 0.5, yurume_tani: 0.5, yurume_bern: 1.0, damp: 0.16, rawAirMul: 2.0 };
const REC_CMP = { yurume_acc: 1.0, yurume_toji: 1.0, yurume_tani: 0.5, yurume_bern: 1.0, damp: 0.16, rawAirMul: 1.5 };
const h = (s) => crypto.createHash("sha256").update(encodeWav(s)).digest("hex").slice(0, 24);
const n = { a: [0, 0], b: [0, 0], c: [0, 0], d: [0, 0] };
const check = (k, c, m) => { n[k][1]++; if (c) n[k][0]++; else console.log("NG  " + m); };
const sane = (s, len) => { if (s.length !== len) return false; for (const v of s) if (!Number.isFinite(v) || Math.abs(v) > 1.0) return false; return true; };
const hiMixOf = (p) => Math.min(1.0, Math.max(0.0, (Math.max(85.0, p.hz) - 125.0) / 85.0));
const applies = {
  yurume_acc: (p) => p.sigh >= 0.25 && p.hz >= 200.0,
  yurume_toji: (p) => p.shin > 0.0 && hiMixOf(p) > 0.0,
  yurume_tani: (p) => p.shin > 0.0,
  yurume_bern: (p) => p.shin > 0.0 && hiMixOf(p) > 0.0,
};

for (const [pn, p] of Object.entries(PRESETS)) {
  for (const [k, t] of TEXTS.entries()) for (const seed of [2024, 7]) {
    const key = `${pn}|t${k}|${seed}`, o = { ...p, seed };
    const base = makeHitofude(t, o).samples, hb = h(base);
    check("a", hb === GOLDEN_ABB2DAE[key], `${key}: ノブ未指定が GOLDEN_ABB2DAE とバイト一致せん`);
    check("a", h(makeHitofude(t, { ...o, yurume_acc: 0, yurume_toji: 0, yurume_tani: 0, yurume_bern: 0 }).samples) === hb, `${key}: ノブ 0 明示がバイト一致せん`);
    check("a", h(makeHitofude(t, { ...o, yurume_acc: null, yurume_toji: null, yurume_tani: null, yurume_bern: null }).samples) === hb, `${key}: ノブ null 明示がバイト一致せん`);
    for (const [knob, fn] of Object.entries(applies)) {
      const s = makeHitofude(t, { ...o, [knob]: 1.0 }).samples, changed = h(s) !== hb;
      check("b", changed === fn(p), `${key}: ${knob}=1.0 の効き方が想定と違う（changed=${changed}）`);
      check("c", sane(s, base.length), `${key}: ${knob}=1.0 が壊れとる`);
    }
    check("c", sane(makeHitofude(t, { ...o, ...REC_MAIN }).samples, base.length), `${key}: 本命 R3b@2.0 が壊れとる`);
    check("c", sane(makeHitofude(t, { ...o, ...REC_CMP }).samples, base.length), `${key}: 比較用 R3c@1.5 が壊れとる`);
    check("d", h(makeHitofude(t, { ...o, yurume_tani: 1.0 }).samples) === h(makeHitofude(t, { ...o, combG: null }).samples), `${key}: yurume_tani=1.0 が {combG:null} と一致せん`);
  }
}
const lab = { a: "ノブ未指定/0/null = GOLDEN_ABB2DAE バイト一致", b: "各ノブ 1.0 は効くプリセットでだけ変わる", c: "有限・長さ同一・ピーク 1 以下", d: "yurume_tani=1.0 = {combG:null}" };
let all = true;
for (const k of Object.keys(n)) { console.log(`(${k}) ${lab[k]}: ${n[k][0]}/${n[k][1]}`); if (n[k][0] !== n[k][1]) all = false; }
console.log(all ? "ALL OK" : "FAILED");
process.exit(all ? 0 : 1);
