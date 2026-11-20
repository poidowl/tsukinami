#!/usr/bin/env node
/**
 * tools/test_sarasara.mjs — サラサラ化（11-20 から既定 soroe2 = {combG: 0.985, rawAirMul: 0.6}）の回帰テスト
 *
 *   node tools/test_sarasara.mjs
 *
 * (a) 旧い既定 {combG: null, rawAirMul: 1.0} を明示すると、出力 WAV が草薙 7f09d18（この変更の前）とバイト一致すること。
 *     全プリセット × 2文 × seed 2 つ ＋ 歌モード持続母音。GOLDEN は 7f09d18 の hitofude.mjs で encodeWav した sha256 の先頭 24 桁。
 * (b) 新しい既定（オプションなし）が、soroe2 を明示した音とバイト一致すること（同じ範囲）。
 * (c) 新しい既定は旧い音から変わっとる（robot は shin=0 でコムを使わんので変わらんのが正しい）。有限・長さ同じ・ピーク 1 以下。
 * 外部ライブラリなし（node:crypto のみ）。
 */
import crypto from "node:crypto";
import { makeHitofude, PRESETS, encodeWav } from "../hitofude.mjs";

const GOLDEN_7f09d18 = {
  "hitofude|t0|2024": "ff427d94224499c00e485e64",
  "hitofude|t0|7": "47719b7d1ed152fa1217c025",
  "hitofude|t1|2024": "fb07960e88579bca6767ce33",
  "hitofude|t1|7": "5885050218f71fec84c7a3e0",
  "hitofude|uta": "c4a01f90eae2dbb8d15d65ab",
  "toiki|t0|2024": "1457af568c4c06e3e0d500bb",
  "toiki|t0|7": "97c4141366f222d86dc51eea",
  "toiki|t1|2024": "a4fd53d6de30b03b9e9f18e0",
  "toiki|t1|7": "643e9d1a018359505066c311",
  "toiki|uta": "e9c150f86eb692d3bc687027",
  "alto|t0|2024": "53fb5f69dcd18f5682b65c81",
  "alto|t0|7": "87e5fbdecf6932100b239394",
  "alto|t1|2024": "c1929ba3edf966bd68e8ad04",
  "alto|t1|7": "f4ddaec861a0c4112b25b1f9",
  "alto|uta": "2dd648103ad69c5c71e49207",
  "sasayaki|t0|2024": "5e96b652973df503e3ff5f8d",
  "sasayaki|t0|7": "fefe7b9d6c0c7339fd0e9000",
  "sasayaki|t1|2024": "7f9a69c38e3d72f6ecb60d33",
  "sasayaki|t1|7": "ab0f4d5f9fa84e15513779f4",
  "sasayaki|uta": "8eb8e93af3f035a26ffeeea9",
  "chibi|t0|2024": "1c0676a031447dbd10589cb4",
  "chibi|t0|7": "b3af131dfdbd0e200069a91b",
  "chibi|t1|2024": "2ea8004a20417f5a232bc481",
  "chibi|t1|7": "92316514d96f86d967994108",
  "chibi|uta": "6b057d9839f5201991864a07",
  "ossan|t0|2024": "25cfd414f0b61eb4befcc27c",
  "ossan|t0|7": "eb18b4f5998e37bfe3055229",
  "ossan|t1|2024": "25d9195ea0303c12a634abdd",
  "ossan|t1|7": "344010a89a38a0bf97cdbc35",
  "ossan|uta": "87f69757f8a3296cacc38fcc",
  "robot|t0|2024": "52799d6d680d4d6d9422c3e2",
  "robot|t0|7": "86ad8e53809c6f1cef9a0205",
  "robot|t1|2024": "1e5c831b45897aca2590be0e",
  "robot|t1|7": "9e6b9158ec48b48927f7e426",
  "robot|uta": "d37e9f58af7bcf4483551aae"
};
const OLD = { combG: null, rawAirMul: 1.0 }, SOROE2 = { combG: 0.985, rawAirMul: 0.6 };
const TEXTS = ["わたし、にほんご、ちょっとしゃべれます", "ヤマノウエニ、アオイソラガミエル?"];
const h = (s) => crypto.createHash("sha256").update(encodeWav(s)).digest("hex").slice(0, 24);
const n = { a: [0, 0], b: [0, 0], c: [0, 0] };
const check = (k, c, m) => { n[k][1]++; if (c) n[k][0]++; else console.log("NG  " + m); };

for (const [pn, p] of Object.entries(PRESETS)) {
  const cases = [];
  for (const [k, t] of TEXTS.entries()) for (const seed of [2024, 7]) cases.push([`${pn}|t${k}|${seed}`, t, { ...p, seed }]);
  cases.push([`${pn}|uta`, "ア", { ...p, uta_hz: [p.hz], vd_ms: [1200], vib_c: 0.0, sigh: 0.0 }]);
  for (const [key, t, o] of cases) {
    const old = makeHitofude(t, { ...o, ...OLD }).samples, def = makeHitofude(t, o).samples;
    check("a", h(old) === GOLDEN_7f09d18[key], `${key}: 旧い既定の明示が 7f09d18 とバイト一致せん`);
    check("b", h(def) === h(makeHitofude(t, { ...o, ...SOROE2 }).samples), `${key}: 新しい既定が soroe2 明示とバイト一致せん`);
    let fin = true, pk = 0, diff = 0;
    for (let i = 0; i < def.length; i++) { if (!Number.isFinite(def[i])) fin = false; pk = Math.max(pk, Math.abs(def[i])); if (i < old.length) diff = Math.max(diff, Math.abs(def[i] - old[i])); }
    const changed = p.shin > 0.0 ? diff > 1e-4 : diff === 0;
    check("c", fin && def.length === old.length && pk <= 1.0 && changed, `${key}: 有限 ${fin} 長さ ${def.length}/${old.length} ピーク ${pk.toFixed(3)} 旧い音との差 ${diff.toExponential(2)}`);
  }
}
console.log(`(a) 旧い既定 {combG:null, rawAirMul:1.0} = 7f09d18 バイト一致: ${n.a[0]}/${n.a[1]}`);
console.log(`(b) 新しい既定 = soroe2 明示 バイト一致: ${n.b[0]}/${n.b[1]}`);
console.log(`(c) 新しい既定は旧い音から変わる（robot は不変）・壊れん: ${n.c[0]}/${n.c[1]}`);
const ng = n.a[1] - n.a[0] + n.b[1] - n.b[0] + n.c[1] - n.c[0];
console.log(ng ? `NG ${ng}` : "ALL OK");
process.exit(ng ? 1 : 0);
