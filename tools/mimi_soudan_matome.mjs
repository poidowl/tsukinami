#!/usr/bin/env node
// tools/mimi_soudan_matome.mjs — 変態耳: 关亡婆に渡す聞き間違いの要約を作る（調整用 tune の行だけ。確認用は渡さない）
//   node tools/mimi_soudan_matome.mjs <台帳.jsonl> <run の頭 例 mimi-r1@> <出力.json>
// 出力には台本の文（例）が入るので、リポジトリには置かず box / M6 だけに置く。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
import * as H from "../hitofude.mjs";
import { moras, alignMoras, truthOf, ed, isDev } from "./kiku_eval.mjs";
import { moraTimes } from "./mimi_sodate.mjs";
const L = fs.readFileSync(process.argv[2], "utf8").trim().split("\n").map(JSON.parse);
const R = L.filter((r) => r.run.startsWith(process.argv[3] || "mimi-r1@") && r.D_shurui === "調整用");
const hira = (s) => [...s].map((c) => (c >= "ァ" && c <= "ヶ" ? String.fromCharCode(c.charCodeAt(0) - 0x60) : c)).join("");
const bump = (o, k, n = 1) => (o[k] = (o[k] || 0) + n);
const per = {}, cons = {}, vow = {}, del = {}, ins = {}, delCtx = {}, pos = { head: [0, 0], mid: [0, 0], tail: [0, 0] };
let refMis = 0, refN = 0; const refEx = {};
const spoken = {};
for (const r of R) {
  const a = (per[r.preset] ||= [0, 0]); const n = [...r.seikai].length; a[0] += ed(r.kiku, r.seikai); a[1] += n;
  const T = moras(r.seikai), P = alignMoras(moras(r.kiku), T);
  let ti = 0;
  for (const [h, t] of P) {
    if (t) { const where = ti < 2 ? "head" : ti >= T.length - 2 ? "tail" : "mid"; pos[where][1]++; if (!h || h.c !== t.c || h.v !== t.v) pos[where][0]++; }
    if (!h) { bump(del, t.c + t.v); const prev = T[ti - 1]; bump(delCtx, `${prev ? prev.v || prev.c : "^"}+${t.c + t.v}`); }
    else if (!t) bump(ins, h.c + h.v);
    else { if (h.c !== t.c) bump(cons, `${t.c || "∅"}→${h.c || "∅"}`); if (h.v !== t.v) bump(vow, `${t.v || "∅"}→${h.v || "∅"}`); }
    if (t) ti++;
  }
  // kusanagi が実際に読んだモーラ（ou_long 等）と台本かなの食い違い
  const key = r.yomi + "|" + r.preset;
  if (!spoken[r.yomi]) {
    const ms = moraTimes(H, r.yomi, { ...H.PRESETS.hitofude, seed: 1 }).filter((m) => m.kind !== "pau");
    const said = ms.map((m) => (m.kind === "Q" ? "っ" : m.kind === "N" ? "ん" : m.t === "ー" ? "ー" : hira(m.t))).join("");
    spoken[r.yomi] = said;
    const t2 = truthOf(r.yomi); const d = ed(said.replace(/ー/g, "ー"), t2);
    refN += [...t2].length;
    if (said !== t2) { refMis++; if (Object.keys(refEx).length < 12) refEx[t2] = said; }
  }
}
const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
const ex = R.filter((r) => r.I_kana_cer > 0.08 && r.I_kana_cer < 0.4).filter((_, i) => i % 23 === 0).slice(0, 30).map((r) => ({ preset: r.preset, ref: r.seikai, hyp: r.kiku }));
const table = JSON.parse(fs.readFileSync(path.join(ROOT, "mimi_table.json"), "utf8"));
const out = {
  task: "kusanagi（決定的なフォルマント系の日本語音声合成）が読んだ声を、mimi（純JS、ニューラルなし）が書き取る。調整用の台本だけでの集計。",
  mimi: {
    features: "kiku.analyze の 10ms フレーム: F1 帯6本(260-1080Hz)・F2 帯7本(900-3600Hz)・高域3本の対数エネルギーから対数RMSを引き発話平均を引いたもの16、対数相対RMS、有声度vo(AMDF)、d1(差分率)、対数高域比、対数(f0/中央f0) の21次元 + ±2フレーム差21 = 42次元。全体で標準化。",
    model: `状態ごとの対角GMM K=${table.K}（状態: sil, Q, N, c:<子音>, v:<母音>; 計 ${Object.keys(table.gmm).length}）。単位=モーラ（${table.units.length}種、子音状態→母音状態の鎖）。各状態は最短 floor(平均長×${table.minf}) フレームの小部屋＋最後の部屋だけ自己ループ(幾何分布)。モーラ2-gram（加算0.5平滑化）×lmw=${table.dec.lmw}、挿入罰 pen=${table.dec.pen}。Viterbi。始まりと終わりは無音。`,
    durations_frames: Object.fromEntries(Object.entries(table.dur).map(([k, v]) => [k, v.mean])),
    truth: "正解=台本のカタカナを janome で読んだもの（ー→前の母音、、?除去）を、kusanagi の実際の読み（tracksFromKana のモーラ列）とは別に比べている。",
  },
  scores_tune_kana_acc: Object.fromEntries(Object.entries(per).map(([k, a]) => [k, +(100 - (100 * a[0]) / a[1]).toFixed(1)])),
  confusion_consonant: top(cons, 15), confusion_vowel: top(vow, 12), deletions: top(del, 15), deletion_context_prevVowel_plus_mora: top(delCtx, 20), insertions: top(ins, 10),
  error_rate_by_position: Object.fromEntries(Object.entries(pos).map(([k, a]) => [k, +(a[0] / a[1]).toFixed(3)])),
  reference_vs_kusanagi_spoken: { lines: Object.keys(spoken).length, lines_differ: refMis, examples_ref_to_spoken: refEx },
  examples: ex,
};
fs.writeFileSync(process.argv[4] || "digest.json", JSON.stringify(out, null, 1));
console.log(JSON.stringify(out).length, "bytes");
