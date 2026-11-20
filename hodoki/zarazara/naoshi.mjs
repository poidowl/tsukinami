#!/usr/bin/env node
/**
 * hodoki/zarazara/naoshi.mjs — ザラザラ対策（opt-in）の前後比較
 *
 *   node hodoki/zarazara/naoshi.mjs [--out /workspace/hodoki/zarazara] [--presets hitofude,ossan] [--seeds 2024,7,99] [--wav]
 *
 * 対策は hitofude_lab.mjs の opts.lab で入れる（草薙本体の既定は変えない）：
 *   soroe1 = { combG: 0.99 }                    有声のあいだコム帰還を 0.99 に（毎周期まじる新しいノイズを減らす）
 *   soroe2 = { combG: 0.985, rawAirMul: 0.6 }   ＋扉を通る生ノイズ rawAir を 0.6 倍
 * どちらも「一本のノイズ x をコムと共鳴で引き算して削る」は変えていない（別の音源は足していない）。
 */
import fs from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import { makeHitofude, PRESETS, encodeWav, SR } from "./hitofude_lab.mjs";
import { TEXT, measure } from "./kurabe.mjs";
import { yomeru } from "./yomeru.mjs";

export const FIXES = { soroe1: { combG: 0.99 }, soroe2: { combG: 0.985, rawAirMul: 0.6 } };

const synth = (preset, seed, lab, vowel) => {
  const p = { ...PRESETS[preset], seed, lab };
  return Float64Array.from(vowel ? makeHitofude("ア", { ...p, uta_hz: [p.hz], vd_ms: [2000], vib_c: 0.0, sigh: 0.0 }).samples : makeHitofude(TEXT, p).samples);
};

if (import.meta.url === `file://${process.argv[1]}`) {
  const { values: a } = parseArgs({ options: { out: { type: "string", default: "/workspace/hodoki/zarazara" }, presets: { type: "string", default: "hitofude,ossan" }, seeds: { type: "string", default: "2024,7,99" }, wav: { type: "boolean" } } });
  const seeds = a.seeds.split(",").map(Number), res = {};
  fs.mkdirSync(a.out, { recursive: true });
  for (const pr of a.presets.split(",")) {
    res[pr] = {};
    const base = seeds.map((s) => synth(pr, s, {}, false));
    const baseV = seeds.map((s) => synth(pr, s, {}, true));
    for (const [name, lab] of [["base", {}], ...Object.entries(FIXES)]) {
      const S = name === "base" ? base : seeds.map((s) => synth(pr, s, lab, false));
      const V = name === "base" ? baseV : seeds.map((s) => synth(pr, s, lab, true));
      if (a.wav) { fs.writeFileSync(path.join(a.out, `fix_${pr}_${name}_bun.wav`), encodeWav(S[0])); fs.writeFileSync(path.join(a.out, `fix_${pr}_${name}_a.wav`), encodeWav(V[0])); }
      const ms = S.map(measure), mv = V.map(measure);
      // 読める代理：同じ seed の base と比べる。base 行は seed 違いどうし（物差し）
      const yo = name === "base" ? seeds.slice(1).map((s, k) => yomeru(base[0], base[k + 1], SR)) : S.map((x, k) => yomeru(base[k], x, SR));
      const avg = (arr, f) => arr.reduce((s, r) => s + f(r), 0) / arr.length;
      const sum = (m) => ({ shimmer_pct: avg(m, (r) => r.shimmer_local_pct), shimmer_db: avg(m, (r) => r.shimmer_local_db), steady_pct: avg(m, (r) => r.steady.pct), edge_pct: avg(m, (r) => r.edge.pct), hnr_db: avg(m, (r) => r.hnr_db), corr: avg(m, (r) => r.period_corr_median), jitter_pct: avg(m, (r) => r.jitter_local_pct) });
      res[pr][name] = { bun: sum(ms), a: sum(mv), yomeru: { env_db: avg(yo, (r) => r.env_db), dF1: avg(yo, (r) => r.formant.F1), dF2: avg(yo, (r) => r.formant.F2), dF3: avg(yo, (r) => r.formant.F3), note: name === "base" ? "seed違いの base どうし（物差し）" : "同 seed の base との差" } };
      const r = res[pr][name], f = (m) => `シマー ${m.shimmer_pct.toFixed(1)}% (${m.shimmer_db.toFixed(2)}dB) 定常 ${m.steady_pct.toFixed(1)} 端 ${m.edge_pct.toFixed(1)} HNR ${m.hnr_db.toFixed(1)} 相関 ${m.corr.toFixed(3)} ジッター ${m.jitter_pct.toFixed(2)}`;
      console.log(`${pr}/${name}\n  文: ${f(r.bun)}\n  ア: ${f(r.a)}\n  読める代理: 包絡距離 ${r.yomeru.env_db.toFixed(2)} dB  |ΔF1| ${r.yomeru.dF1.toFixed(0)} |ΔF2| ${r.yomeru.dF2.toFixed(0)} |ΔF3| ${r.yomeru.dF3.toFixed(0)} Hz  (${r.yomeru.note})`);
    }
  }
  fs.writeFileSync(path.join(a.out, "naoshi.json"), JSON.stringify(res, null, 1));
}
