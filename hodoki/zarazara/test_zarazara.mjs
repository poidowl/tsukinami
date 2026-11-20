#!/usr/bin/env node
// hodoki/zarazara/test_zarazara.mjs — lab={} が草薙本体と同一波形か／対策が持続母音のシマーを下げるか
import { makeHitofude as M0, PRESETS as P0 } from "../../hitofude.mjs";
import { makeHitofude as M1, PRESETS as P1 } from "./hitofude_lab.mjs";
import { measure } from "./kurabe.mjs";
import { FIXES } from "./naoshi.mjs";
let ok = 0, ng = 0;
const check = (c, m) => { if (c) { ok++; console.log("ok  " + m); } else { ng++; console.log("NG  " + m); } };
for (const pr of ["hitofude", "ossan", "robot"]) {
  const a = M0("わたし、にほんご", P0[pr]).samples, b = M1("わたし、にほんご", { ...P1[pr], lab: {} }).samples;
  let d = a.length === b.length ? 0 : Infinity;
  for (let i = 0; i < Math.min(a.length, b.length); i++) d = Math.max(d, Math.abs(a[i] - b[i]));
  check(d === 0, `${pr}: lab={} は本体と同一 (maxdiff ${d})`);
}
const vow = (lab) => Float64Array.from(M1("ア", { ...P1.hitofude, lab, uta_hz: [350], vd_ms: [2000], vib_c: 0, sigh: 0 }).samples);
const b = measure(vow({}));
for (const [n, lab] of Object.entries(FIXES)) {
  const m = measure(vow(lab));
  check(m.shimmer_local_pct < b.shimmer_local_pct - 2, `${n}: 持続母音シマー ${b.shimmer_local_pct.toFixed(1)}% → ${m.shimmer_local_pct.toFixed(1)}%`);
  check(m.hnr_db > b.hnr_db + 3, `${n}: HNR ${b.hnr_db.toFixed(1)} → ${m.hnr_db.toFixed(1)} dB`);
}
console.log(`${ok}/${ok + ng}`); process.exit(ng ? 1 : 0);
