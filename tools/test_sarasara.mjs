#!/usr/bin/env node
/**
 * tools/test_sarasara.mjs — v10.8 単一因果ループ統合＆サラサラ既定（v11.0 以降は {pau_iki: null} で読点の息を外して検証）（soroe2 = {combG: 0.985, rawAirMul: 0.6}）回帰テスト
 *
 *   node tools/test_sarasara.mjs
 *
 * (a) {combG: null, rawAirMul: 1.0}（非サラサラ明示）が GOLDEN_V10_8_NOSARA と全プリセット × 2文 × seed 2 つ ＋ 歌モードでバイト一致すること。
 * (b) 既定（{pau_iki: null} 以外オプションなし）が、soroe2 {combG: 0.985, rawAirMul: 0.6} を明示した音とバイト一致すること。
 * (c) 既定は非サラサラ音から有効に変化し（robot は shin=0 で扉バイパスのため不変）、有限・長さ同一・ピーク 1 以下であること。
 */
import crypto from "node:crypto";
import { makeHitofude, PRESETS, encodeWav } from "../hitofude.mjs";

const GOLDEN_V10_8_NOSARA = {
  "hitofude|t0|2024": "89363475069caadadd5f1c0a",
  "hitofude|t0|7": "b6d6169fdf7cf39bb62c7ac4",
  "hitofude|t1|2024": "dd972a520603049f814461a8",
  "hitofude|t1|7": "83e77c3e53e60ea3561ba103",
  "hitofude|uta": "c1c90338086e8cd814d8baf5",
  "toiki|t0|2024": "024e2dc52d5095d5c389a845",
  "toiki|t0|7": "b9320070ff9249a849aef40e",
  "toiki|t1|2024": "399f5ba34fb82eb2296ab77b",
  "toiki|t1|7": "8e890bd8599bed5536565c00",
  "toiki|uta": "92c9f86854f6107d69b0fd34",
  "alto|t0|2024": "1e70d54e16ded10eabd1cf9e",
  "alto|t0|7": "8a4c6d406573ee8fc62da5a7",
  "alto|t1|2024": "ca4dcd23a1c2552249e52cc9",
  "alto|t1|7": "ff32397278fd6e8fb2822fa7",
  "alto|uta": "8559b3eb29a1943b67f7b74f",
  "sasayaki|t0|2024": "46700d22b04986223a8b4614",
  "sasayaki|t0|7": "0a146e72cd4ef24fae530c43",
  "sasayaki|t1|2024": "6df92ef8d82d04148ebd4e9e",
  "sasayaki|t1|7": "a1640bb60c68406e9e8c8619",
  "sasayaki|uta": "78ef7b447e692658492b8eeb",
  "chibi|t0|2024": "138bd444732f66fca1b89107",
  "chibi|t0|7": "0dc1cfe1c62ab72e8ad292fd",
  "chibi|t1|2024": "89a36bd16836b10dd8e574c3",
  "chibi|t1|7": "6cc8914e205cb8d5ebc0141c",
  "chibi|uta": "0961bde3fbb44cad1ca63ac0",
  "ossan|t0|2024": "a4f08ed2cf791b6723c55e7c",
  "ossan|t0|7": "e91b5108a1e15833df00ad64",
  "ossan|t1|2024": "5931a1af1c02eefb2de6c72b",
  "ossan|t1|7": "5b146c0c77df550e392e4fa0",
  "ossan|uta": "ba923c36f0e90efcde31d05e",
  "robot|t0|2024": "52d0f0f15ed616269d74d4b8",
  "robot|t0|7": "af1db8783cc8ef74ad27c474",
  "robot|t1|2024": "7bcb6b030cf0dfb2ff7f0666",
  "robot|t1|7": "68c0f982d5f63f22cd826c74",
  "robot|uta": "87689dc897ea1d373f1fde97"
};
// v11.0 で読点の息の床 pau_iki=-30 が既定になったので、ここでは {pau_iki: null}（v10.8 の完全無音）に揃えてサラサラ化だけを検証する
const NOIKI = { pau_iki: null };
const NOSARA = { combG: null, rawAirMul: 1.0, ...NOIKI }, SOROE2 = { combG: 0.985, rawAirMul: 0.6, ...NOIKI };
const TEXTS = ["わたし、にほんご、ちょっとしゃべれます", "ヤマノウエニ、アオイソラガミエル?"];
const h = (s) => crypto.createHash("sha256").update(encodeWav(s)).digest("hex").slice(0, 24);
const n = { a: [0, 0], b: [0, 0], c: [0, 0] };
const check = (k, c, m) => { n[k][1]++; if (c) n[k][0]++; else console.log("NG  " + m); };

for (const [pn, p] of Object.entries(PRESETS)) {
  const cases = [];
  for (const [k, t] of TEXTS.entries()) for (const seed of [2024, 7]) cases.push([`${pn}|t${k}|${seed}`, t, { ...p, seed, ...NOIKI }]);
  cases.push([`${pn}|uta`, "ア", { ...p, uta_hz: [p.hz], vd_ms: [1200], vib_c: 0.0, sigh: 0.0, ...NOIKI }]);
  for (const [key, t, o] of cases) {
    const old = makeHitofude(t, { ...o, ...NOSARA }).samples;
    const def = makeHitofude(t, o).samples;
    check("a", h(old) === GOLDEN_V10_8_NOSARA[key], `${key}: {combG:null, rawAirMul:1.0} が GOLDEN_V10_8_NOSARA とバイト一致せん`);
    check("b", h(def) === h(makeHitofude(t, { ...o, ...SOROE2 }).samples), `${key}: 既定が soroe2 明示とバイト一致せん`);
    let fin = true, pk = 0, diff = 0;
    for (let i = 0; i < def.length; i++) { if (!Number.isFinite(def[i])) fin = false; pk = Math.max(pk, Math.abs(def[i])); if (i < old.length) diff = Math.max(diff, Math.abs(def[i] - old[i])); }
    const changed = p.shin > 0.0 ? diff > 1e-4 : diff === 0;
    check("c", fin && def.length === old.length && pk <= 1.0 && changed, `${key}: 有限 ${fin} 長さ ${def.length}/${old.length} ピーク ${pk.toFixed(3)} 非サラサラとの差 ${diff.toExponential(2)}`);
  }
}
console.log(`(a) 非サラサラ {combG:null, rawAirMul:1.0} = GOLDEN_V10_8 バイト一致: ${n.a[0]}/${n.a[1]}`);
console.log(`(b) v10.8 既定 = soroe2 明示 バイト一致: ${n.b[0]}/${n.b[1]}`);
console.log(`(c) v10.8 既定は非サラサラから変わる（robot は不変）・壊れん: ${n.c[0]}/${n.c[1]}`);
const ng = n.a[1] - n.a[0] + n.b[1] - n.b[0] + n.c[1] - n.c[0];
console.log(ng ? `NG ${ng}` : "ALL OK");
process.exit(ng ? 1 : 0);
