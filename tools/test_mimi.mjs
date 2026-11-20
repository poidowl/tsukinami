#!/usr/bin/env node
/** tools/test_mimi.mjs — 変態耳（mimi）と測り台（kiku_eval）の確かめ。外部ライブラリ 0。 node tools/test_mimi.mjs */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as H from "../hitofude.mjs";
import * as K from "../kiku.mjs";
import * as M from "../mimi.mjs";
import { moraTimes, unitOf } from "./mimi_sodate.mjs";
import { truthOf, ed, moras, isDev } from "./kiku_eval.mjs";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
let ok = 0, ng = 0;
const check = (name, cond, extra = "") => { if (cond) ok++; else { ng++; console.log("NG", name, extra); } };

// 1) 正解の下ごしらえ
check("truthOf", truthOf("ソレワ、ハコー?") === "それわはこお", truthOf("ソレワ、ハコー?"));
check("ed", ed("あいう", "あう") === 1 && ed("", "あい") === 2);
check("moras", JSON.stringify(moras("きゃっと")) === JSON.stringify([{ c: "ky", v: "a" }, { c: "Q", v: "" }, { c: "t", v: "o" }]));
// 2) 時刻表は makeHitofude と同じ（音を作らずに正解だけ作れる）
for (const p of Object.keys(H.PRESETS)) {
  const prm = { ...H.PRESETS[p], seed: 7 }, k = "ネコガハコニハイルトキ、メオホソメマス";
  check("moraTimes " + p, JSON.stringify(moraTimes(H, k, prm)) === JSON.stringify(H.makeHitofude(k, prm).moras));
}
// 3) フレームの札
const lab = M.frameLabels([{ kind: "pau", a: 0, e: 0.1 }, { kind: "CV", c: "k", v: "a", a: 0.1, b: 0.15, e: 0.25 }, { kind: "N", a: 0.25, e: 0.3 }], [0.05, 0.12, 0.2, 0.27, 0.4]);
check("frameLabels", lab.join(",") === "sil,c:k,v:a,N,sil", lab.join(","));
check("unitOf", unitOf({ kind: "CV", t: "キャ", c: "ky", v: "a" }).states.join() === "c:ky,v:a" && unitOf({ kind: "Q" }).kana === "っ");
check("isDev 決まった割り振り", isDev("itako_20261120_01") === isDev("itako_20261120_01"));
// 4) wav を通しても通さんでも同じ特徴
const s = H.makeHitofude("ソレワハコナノダ", { ...H.PRESETS.hitofude, seed: 2024 }).samples;
const w = K.decodeWavBytes(H.encodeWav(s));
const fa = M.features(s, H.SR), fb = M.features(w.samples, w.sr);
let md = 0; for (let t = 0; t < fa.T; t++) for (let d = 0; d < 42; d++) md = Math.max(md, Math.abs(fa.X[t][d] - fb.X[t][d]));
check("features wav 往復", fa.T === fb.T && md < 0.05, "maxdiff " + md);
// 5) 表で書き取る（表は tools/mimi_sodate.mjs が調整用の台本だけで作ったもの）
const table = JSON.parse(fs.readFileSync(path.join(ROOT, "mimi_table.json"), "utf8"));
check("表の形", table.kind === "mimi-table v1" && table.units.length > 40 && table.lm.length === table.units.length + 1 && table.from.split.startsWith("tune"));
let e = 0, n = 0, eh = 0;
for (const [k, p, seed] of [["ソレワハコナノダ", "hitofude", 2024], ["キョウワサムイノダ", "alto", 555], ["アシタモアソボウ", "ossan", 31]]) {
  const x = H.makeHitofude(k, { ...H.PRESETS[p], seed }).samples;
  const tr = truthOf(k);
  const hyp = M.decodeMimi(x, H.SR, table).text.replace(/、/g, "");
  const hand = K.decode(K.analyze(x, H.SR)).text.replace(/、/g, "");
  e += ed(hyp, tr); eh += ed(hand, tr); n += [...tr].length;
  console.log(`  ${p}/${seed} 正:${tr} 耳:${hyp} 手:${hand}`);
}
check("耳のかな正答 >= 60%", 1 - e / n >= 0.6, `${(100 - (100 * e) / n).toFixed(1)}%`);
check("手の耳（元の kiku）も動く", eh <= n * 2);
console.log(ng ? `NG ${ng} / OK ${ok}` : `ALL OK (${ok})`);
process.exit(ng ? 1 : 0);
