#!/usr/bin/env node
/**
 * tools/test_sarasara.mjs — v10 既定（本命：子音・ハ行明瞭度 × 粘膜クッション）＆ combG / rawAirMul オプション回帰テスト
 *
 *   node tools/test_sarasara.mjs
 *
 * (a) 既定（オプションなし）が GOLDEN_V10 と全プリセット × 2文 × seed 2 つ ＋ 歌モードでバイト一致すること。
 * (b) {combG: null, rawAirMul: 1.0} の明示が既定（オプションなし）とバイト一致すること。
 * (c) サラサラ化オプション {combG: 0.985, rawAirMul: 0.6}（soroe2）を渡したとき、shin > 0 では有効に変化し（robot は不変）、有限・ピーク 1 以下を保つこと。
 */
import crypto from "node:crypto";
import { makeHitofude, PRESETS, encodeWav } from "../hitofude.mjs";

const GOLDEN_V10 = {
  "hitofude|t0|2024": "bb99a11d963aa2e2154ae492",
  "hitofude|t0|7": "d178e57ca5eaa8b5d4012e2e",
  "hitofude|t1|2024": "194d850e7ac782e5f3a41212",
  "hitofude|t1|7": "eb38c6a2e2b1f0b3aeaaba45",
  "hitofude|uta": "e05203c93d5a865332bf8873",
  "toiki|t0|2024": "d8eb9ca7433bfde9b57ec139",
  "toiki|t0|7": "1311b5fb3143999621b1f8de",
  "toiki|t1|2024": "dc62ce39d68b90e962ea9bb6",
  "toiki|t1|7": "65b8ab34783a18147badd614",
  "toiki|uta": "9617c1f2656d8352db3f2b74",
  "alto|t0|2024": "d064013636c8f8665598d9b8",
  "alto|t0|7": "5f85853b61c398099ed77cda",
  "alto|t1|2024": "2d9fd4d7a9be7008bd8063e5",
  "alto|t1|7": "1dc7847800a921a01e637e25",
  "alto|uta": "8f9f2f186e8293b1d95f2806",
  "sasayaki|t0|2024": "a5ca11f87a97d47edfd2a20e",
  "sasayaki|t0|7": "d4e18852715d3d766d291abc",
  "sasayaki|t1|2024": "0da200b4aa1bfd6080cd1a60",
  "sasayaki|t1|7": "d24df4dfe27fb2b0bbb5e543",
  "sasayaki|uta": "8aa40391ecfbafd7114bcec7",
  "chibi|t0|2024": "178e853ec8b37ded79dd89e7",
  "chibi|t0|7": "37724537ef22c2e8b64d819b",
  "chibi|t1|2024": "9ad32e3df312ef121dcf5726",
  "chibi|t1|7": "31f2d3f94a4ea23a1545863c",
  "chibi|uta": "e215812272e0c9ff0ee3320d",
  "ossan|t0|2024": "d8fea393e3af9f1d4ca02fd4",
  "ossan|t0|7": "4f2c99b0327348a78f7c6e76",
  "ossan|t1|2024": "1d81bf6625bbf6b6478fa8c8",
  "ossan|t1|7": "c4d55928405e34ca66f8d0cd",
  "ossan|uta": "71513583550c335e69bc85ac",
  "robot|t0|2024": "0ddc651fc278a1e537211ad5",
  "robot|t0|7": "800292b2336ed3b908aeab40",
  "robot|t1|2024": "1e5c831b45897aca2590be0e",
  "robot|t1|7": "9e6b9158ec48b48927f7e426",
  "robot|uta": "d37e9f58af7bcf4483551aae"
};
const DEF_EXPLICIT = { combG: null, rawAirMul: 1.0 }, SOROE2 = { combG: 0.985, rawAirMul: 0.6 };
const TEXTS = ["わたし、にほんご、ちょっとしゃべれます", "ヤマノウエニ、アオイソラガミエル?"];
const h = (s) => crypto.createHash("sha256").update(encodeWav(s)).digest("hex").slice(0, 24);
const n = { a: [0, 0], b: [0, 0], c: [0, 0] };
const check = (k, c, m) => { n[k][1]++; if (c) n[k][0]++; else console.log("NG  " + m); };

for (const [pn, p] of Object.entries(PRESETS)) {
  const cases = [];
  for (const [k, t] of TEXTS.entries()) for (const seed of [2024, 7]) cases.push([`${pn}|t${k}|${seed}`, t, { ...p, seed }]);
  cases.push([`${pn}|uta`, "ア", { ...p, uta_hz: [p.hz], vd_ms: [1200], vib_c: 0.0, sigh: 0.0 }]);
  for (const [key, t, o] of cases) {
    const def = makeHitofude(t, o).samples;
    const exp = makeHitofude(t, { ...o, ...DEF_EXPLICIT }).samples;
    const sor = makeHitofude(t, { ...o, ...SOROE2 }).samples;
    check("a", h(def) === GOLDEN_V10[key], `${key}: 既定が GOLDEN_V10 とバイト一致せん`);
    check("b", h(def) === h(exp), `${key}: {combG:null, rawAirMul:1.0} 明示が既定とバイト一致せん`);
    let fin = true, pk = 0, diff = 0;
    for (let i = 0; i < sor.length; i++) { if (!Number.isFinite(sor[i])) fin = false; pk = Math.max(pk, Math.abs(sor[i])); if (i < def.length) diff = Math.max(diff, Math.abs(sor[i] - def[i])); }
    const changed = p.shin > 0.0 ? diff > 1e-4 : diff === 0;
    check("c", fin && sor.length === def.length && pk <= 1.0 && changed, `${key}: 有限 ${fin} 長さ ${sor.length}/${def.length} ピーク ${pk.toFixed(3)} 既定との差 ${diff.toExponential(2)}`);
  }
}
console.log(`(a) v10 既定 = GOLDEN_V10 バイト一致: ${n.a[0]}/${n.a[1]}`);
console.log(`(b) v10 既定 = {combG:null, rawAirMul:1.0} 明示 バイト一致: ${n.b[0]}/${n.b[1]}`);
console.log(`(c) soroe2 オプション {combG:0.985, rawAirMul:0.6} 動作・有限・robot不変: ${n.c[0]}/${n.c[1]}`);
const ng = n.a[1] - n.a[0] + n.b[1] - n.b[0] + n.c[1] - n.c[0];
console.log(ng ? `NG ${ng}` : "ALL OK");
process.exit(ng ? 1 : 0);
