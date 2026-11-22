#!/usr/bin/env node
/**
 * tools/test_pause.mjs — v12 (VDP自励声帯) 決定論・読点息床 (pau_iki)・間長 (pau_s)・CLI 整合テスト
 *
 *   node tools/test_pause.mjs
 */
import crypto from "node:crypto";
import { makeHitofude, PRESETS, encodeWav, SR } from "../hitofude.mjs";
import { synth } from "../yomu.mjs";

const TEXTS = ["わたし、にほんご、ちょっとしゃべれます", "ヤマノウエニ、アオイソラガミエル?"];
const OFF = { pau_iki: null };
const h = (s) => crypto.createHash("sha256").update(encodeWav(s)).digest("hex").slice(0, 24);
const n = { a: [0, 0], b: [0, 0], c: [0, 0], d: [0, 0], e: [0, 0] };
const check = (k, c, m) => { n[k][1]++; if (c) n[k][0]++; else console.log("NG  " + m); };
const rms = (x, a, b) => { let s = 0; for (let i = a; i < b; i++) s += x[i] * x[i]; return Math.sqrt(s / Math.max(1, b - a)); };

for (const [pn, p] of Object.entries(PRESETS)) {
  for (const [k, t] of TEXTS.entries()) for (const seed of [2024, 7, 99]) {
    const key = `${pn}|t${k}|${seed}`, o = { ...p, seed };
    const R = makeHitofude(t, { ...o, ...OFF }), old = R.samples, ho = h(old);
    check("a", ho === h(makeHitofude(t, { ...o, ...OFF }).samples), `${key}: 決定論再現せん`);
    check("b", h(makeHitofude(t, { ...o, ...OFF, pau_s: null }).samples) === ho && h(makeHitofude(t, { ...o, ...OFF, pau_s: 0.35 }).samples) === ho, `${key}: pau_s null/0.35 が不一致`);
    const def = makeHitofude(t, o).samples;
    const pz = R.moras.filter((m) => m.kind === "pau").map((m) => [Math.trunc(m.a * SR), Math.trunc(m.e * SR)]);
    if (p.pau_iki === null) {
      check("c", h(def) === ho, `${key}: プリセット pau_iki:null なのに既定と不一致`);
    } else {
      const same30 = h(def) === h(makeHitofude(t, { ...o, pau_iki: -30 }).samples);
      const inP = (i) => pz.some(([a, b]) => i >= a && i < b);
      let fin = true, pk = 0, ratio = null, outOk = true;
      for (let i = 0; i < def.length; i++) {
        if (!Number.isFinite(def[i])) fin = false; pk = Math.max(pk, Math.abs(def[i]));
        if (!inP(i) && Math.abs(old[i]) > 1e-3) { const q = def[i] / old[i]; if (ratio === null) ratio = q; else if (Math.abs(q - ratio) > 1e-3) outOk = false; }
      }
      const up = pz.length > 0 && pz.every(([a, b]) => rms(def, a, b) > 3 * rms(old, a, b) + 1e-6);
      check("c", same30 && fin && def.length === old.length && pk <= 1.0 && outOk && up, `${key}: -30一致 ${same30} 有限 ${fin} 長さ ${def.length}/${old.length} ピーク ${pk.toFixed(3)} 間の外一致 ${outOk} 間上がる ${up}`);
    }
    const sh = makeHitofude(t, { ...o, pau_s: 0.2 }).samples;
    const dN = def.length - sh.length, want = Math.round(0.15 * pz.length * SR);
    let fin2 = true, pk2 = 0;
    for (let i = 0; i < sh.length; i++) { if (!Number.isFinite(sh[i])) fin2 = false; pk2 = Math.max(pk2, Math.abs(sh[i])); }
    check("d", fin2 && pk2 <= 1.0 && Math.abs(dN - want) <= Math.round(0.006 * SR), `${key}: 短縮 ${dN} 標本（期待 ~${want}）有限 ${fin2} ピーク ${pk2.toFixed(3)}`);
    check("e", h(synth(t, o).samples) === h(def), `${key}: synth() が makeHitofude 直呼びと不一致`);
  }
  const custom = { ...p, seed: 2024, pau_iki: -24, pau_s: 0.22, rawAirMul: 1.0 };
  check("e", h(synth("あ、あ", custom).samples) === h(makeHitofude("あ、あ", custom).samples), `${pn}|custom: synth() でオプション落ち`);
  const uo = { ...p, uta_hz: [p.hz], vd_ms: [1200], vib_c: 0.0, sigh: 0.0 };
  const hu = h(makeHitofude("ア", { ...uo, ...OFF }).samples);
  check("a", hu === h(makeHitofude("ア", { ...uo, ...OFF }).samples), `${pn}|uta: 歌モード決定論`);
  check("b", h(makeHitofude("ア", uo).samples) === hu, `${pn}|uta: 読点なし歌モードの既定一致`);
}
console.log(`(a) 全7プリセット決定論バイト一致: ${n.a[0]}/${n.a[1]}`);
console.log(`(b) pau_s null/0.35・読点なし歌の既定一致: ${n.b[0]}/${n.b[1]}`);
console.log(`(c) 既定 pau_iki=-30、読点の間だけ変わる・壊れん: ${n.c[0]}/${n.c[1]}`);
console.log(`(d) pau_s=0.2 で正しく詰まる・壊れん: ${n.d[0]}/${n.d[1]}`);
console.log(`(e) CLI synth() 経由 = makeHitofude 直呼び バイト一致: ${n.e[0]}/${n.e[1]}`);
const ng = Object.values(n).reduce((s, [a, b]) => s + b - a, 0);
console.log(ng ? `NG ${ng}` : "ALL OK");
process.exit(ng ? 1 : 0);
