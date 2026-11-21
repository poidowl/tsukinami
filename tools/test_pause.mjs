#!/usr/bin/env node
/**
 * tools/test_pause.mjs — v11.0 読点の息の床（pau_iki 既定 -30）＆間の長さ（pau_s）回帰テスト
 *
 *   node tools/test_pause.mjs
 *
 * (a) オプトアウト {pau_iki: null} が GOLDEN_V10_8 (b9b5eb8 既定音) と全プリセット × 2文 × seed 3 つ ＋ 歌モードでバイト一致すること。
 * (b) {pau_iki: null, pau_s: null}／{pau_iki: null, pau_s: 0.35} 明示もバイト一致し、読点の無い歌モードは既定のままでも一致すること。
 * (c) 既定は {pau_iki: -30} 明示とバイト一致し（chibi はプリセットで pau_iki:null＝既定のまま GOLDEN 一致）、v10.8 から読点の間だけが変わり（間の外はスケール比で一致）、有限・長さ同一・ピーク 1 以下・間の RMS が無音より上がること。
 * (d) pau_s を詰めると全長が (0.35 - pau_s) × 読点数 ぶん短くなり、壊れんこと。
 */
import crypto from "node:crypto";
import { makeHitofude, PRESETS, encodeWav, SR } from "../hitofude.mjs";

const GOLDEN_V10_8 = {
  "hitofude|t0|2024": "6ee63e1efca8a7a56a9cdef5",
  "hitofude|t0|7": "bfdbaced5931d2385103b32f",
  "hitofude|t0|99": "5430574a8c8e0edc70719c72",
  "hitofude|t1|2024": "a016130c1e0580fd3d0607ae",
  "hitofude|t1|7": "ab5b6d208a9658f196170395",
  "hitofude|t1|99": "3772f7b75b97e47d2b6c6b56",
  "hitofude|uta": "4d6a88db93b65bc36b401ec6",
  "toiki|t0|2024": "24bdadf49fac566aee75a923",
  "toiki|t0|7": "eb9a94590758528db58bfee2",
  "toiki|t0|99": "fae4bad067a3e42f2ad67634",
  "toiki|t1|2024": "fc00d6b03102921fa1c0e8b6",
  "toiki|t1|7": "ed05cbc9e98b264838d2f9d7",
  "toiki|t1|99": "8222f7cda74d1189f97f87cd",
  "toiki|uta": "df7c74c0f50d0a9c0057c05e",
  "alto|t0|2024": "38a96c29275be75075d051eb",
  "alto|t0|7": "6becbae0b82352f88f2b77bd",
  "alto|t0|99": "7ade4a4ea769baf753a29acf",
  "alto|t1|2024": "49e8a7f63797be2120ecd5f9",
  "alto|t1|7": "651376d212a11be7edf7a89b",
  "alto|t1|99": "6c534986fb4a34da8d0b5604",
  "alto|uta": "57b3ebc3dbd5619b1b605105",
  "sasayaki|t0|2024": "45df5121f722474cf0aae657",
  "sasayaki|t0|7": "cf60630fa545ee5ad36271de",
  "sasayaki|t0|99": "35fd744110429865bc893b43",
  "sasayaki|t1|2024": "dd48bcdb7b1ef43fb145d306",
  "sasayaki|t1|7": "d29e91fdfac8682739c4be1f",
  "sasayaki|t1|99": "44a1fb190e149d1524fd46c5",
  "sasayaki|uta": "99e5f03f855b9fa8da93f8d4",
  "chibi|t0|2024": "f88b844b6a8fbf337f0ec88e",
  "chibi|t0|7": "588c2cdcc56f76283715ab22",
  "chibi|t0|99": "755f58b6ffd77cefa071cbc5",
  "chibi|t1|2024": "4c56898fd8b4a3257329188c",
  "chibi|t1|7": "6c27581426996e75885704b4",
  "chibi|t1|99": "33fde6e63de9f7e56b4184e2",
  "chibi|uta": "9af70d5f79f92aa9a9416af0",
  "ossan|t0|2024": "472811eeeb9ab4e7c52ee0d5",
  "ossan|t0|7": "40c99edb270ed565f0eb26ad",
  "ossan|t0|99": "b97107a4800db9f3756bb6b3",
  "ossan|t1|2024": "66759acedd5300f76ef267f3",
  "ossan|t1|7": "cc2a28034ab014e9d9dfde75",
  "ossan|t1|99": "f50580b0597bbdfbc3e56fbf",
  "ossan|uta": "8555515e23c2c80ae9bd5cf9",
  "robot|t0|2024": "52d0f0f15ed616269d74d4b8",
  "robot|t0|7": "af1db8783cc8ef74ad27c474",
  "robot|t0|99": "4493b74992aaa215b125e1ab",
  "robot|t1|2024": "7bcb6b030cf0dfb2ff7f0666",
  "robot|t1|7": "68c0f982d5f63f22cd826c74",
  "robot|t1|99": "3e2251ed7011b59ccd744645",
  "robot|uta": "87689dc897ea1d373f1fde97",
};
const TEXTS = ["わたし、にほんご、ちょっとしゃべれます", "ヤマノウエニ、アオイソラガミエル?"];
const OFF = { pau_iki: null };
const h = (s) => crypto.createHash("sha256").update(encodeWav(s)).digest("hex").slice(0, 24);
const n = { a: [0, 0], b: [0, 0], c: [0, 0], d: [0, 0] };
const check = (k, c, m) => { n[k][1]++; if (c) n[k][0]++; else console.log("NG  " + m); };
const rms = (x, a, b) => { let s = 0; for (let i = a; i < b; i++) s += x[i] * x[i]; return Math.sqrt(s / Math.max(1, b - a)); };

for (const [pn, p] of Object.entries(PRESETS)) {
  for (const [k, t] of TEXTS.entries()) for (const seed of [2024, 7, 99]) {
    const key = `${pn}|t${k}|${seed}`, o = { ...p, seed };
    const R = makeHitofude(t, { ...o, ...OFF }), old = R.samples, ho = h(old);
    check("a", ho === GOLDEN_V10_8[key], `${key}: {pau_iki:null} が GOLDEN_V10_8 とバイト一致せん`);
    check("b", h(makeHitofude(t, { ...o, ...OFF, pau_s: null }).samples) === ho && h(makeHitofude(t, { ...o, ...OFF, pau_s: 0.35 }).samples) === ho, `${key}: {pau_iki:null, pau_s:null/0.35} が GOLDEN とバイト一致せん`);
    const def = makeHitofude(t, o).samples;
    const pz = R.moras.filter((m) => m.kind === "pau").map((m) => [Math.trunc(m.a * SR), Math.trunc(m.e * SR)]);
    if (p.pau_iki === null) { // chibi など既定で息を外したプリセットは、既定のまま v10.8 とバイト一致
      check("c", h(def) === ho, `${key}: プリセットで pau_iki:null やのに既定が GOLDEN とバイト一致せん`);
    } else {
      const same30 = h(def) === h(makeHitofude(t, { ...o, pau_iki: -30 }).samples);
      const inP = (i) => pz.some(([a, b]) => i >= a && i < b);
      let fin = true, pk = 0, ratio = null, outOk = true;
      for (let i = 0; i < def.length; i++) {
        if (!Number.isFinite(def[i])) fin = false; pk = Math.max(pk, Math.abs(def[i]));
        if (!inP(i) && Math.abs(old[i]) > 1e-3) { const q = def[i] / old[i]; if (ratio === null) ratio = q; else if (Math.abs(q - ratio) > 1e-3) outOk = false; }
    }
    const up = pz.length > 0 && pz.every(([a, b]) => rms(def, a, b) > 3 * rms(old, a, b) + 1e-6);
    check("c", same30 && fin && def.length === old.length && pk <= 1.0 && outOk && up, `${key}: -30明示一致 ${same30} 有限 ${fin} 長さ ${def.length}/${old.length} ピーク ${pk.toFixed(3)} 間の外一致 ${outOk} 間が上がる ${up}`);
    }
    const sh = makeHitofude(t, { ...o, pau_s: 0.2 }).samples;
    const dN = def.length - sh.length, want = Math.round(0.15 * pz.length * SR);
    let fin2 = true, pk2 = 0;
    for (let i = 0; i < sh.length; i++) { if (!Number.isFinite(sh[i])) fin2 = false; pk2 = Math.max(pk2, Math.abs(sh[i])); }
    check("d", fin2 && pk2 <= 1.0 && Math.abs(dN - want) <= Math.round(0.006 * SR), `${key}: 短縮 ${dN} 標本（期待 ~${want}）有限 ${fin2} ピーク ${pk2.toFixed(3)}`);
  }
  const key = `${pn}|uta`, uo = { ...p, uta_hz: [p.hz], vd_ms: [1200], vib_c: 0.0, sigh: 0.0 };
  check("a", h(makeHitofude("ア", { ...uo, ...OFF }).samples) === GOLDEN_V10_8[key], `${key}: 歌モード {pau_iki:null} が GOLDEN_V10_8 とバイト一致せん`);
  check("b", h(makeHitofude("ア", uo).samples) === GOLDEN_V10_8[key], `${key}: 読点なし歌モードの既定が GOLDEN_V10_8 とバイト一致せん`);
}
console.log(`(a) {pau_iki:null} = GOLDEN_V10_8 (b9b5eb8) バイト一致: ${n.a[0]}/${n.a[1]}`);
console.log(`(b) pau_s null/0.35 明示・読点なし歌の既定 = GOLDEN バイト一致: ${n.b[0]}/${n.b[1]}`);
console.log(`(c) v11.0 既定 = pau_iki -30、読点の間だけ変わる・壊れん: ${n.c[0]}/${n.c[1]}`);
console.log(`(d) pau_s=0.2 で正しく詰まる・壊れん: ${n.d[0]}/${n.d[1]}`);
const ng = Object.values(n).reduce((s, [a, b]) => s + b - a, 0);
console.log(ng ? `NG ${ng}` : "ALL OK");
process.exit(ng ? 1 : 0);
