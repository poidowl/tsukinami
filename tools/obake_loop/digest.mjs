// オバケ台帳（ループの行だけ）→ 关亡婆に渡す小さな集計。 node digest.mjs obake_daichou.jsonl OUTDIR → 書いたファイルの path を出す
import fs from "node:fs"; import path from "node:path";
import { moras, alignMoras } from "./repo_cd293c8/tools/kiku_eval.mjs";
const [ledger, outdir] = process.argv.slice(2);
const rows = fs.readFileSync(ledger, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)).filter((r) => (r.run || "").startsWith("loop-"));
if (!rows.length) process.exit(1);
// 声(kusanagi)や耳の版が変わったら混ぜて数えん: いちばん新しい行と同じ tts_commit・ear_commit の行だけ
const TTS = rows.at(-1).tts_commit || "cd293c8";
const EARC = rows.at(-1).ear_commit || "cd293c8";
rows.splice(0, rows.length, ...rows.filter((r) => (r.tts_commit || "cd293c8") === TTS && (r.ear_commit || "cd293c8") === EARC));
fs.mkdirSync(outdir, { recursive: true });
const prev = fs.readdirSync(outdir).filter((f) => /^digest_loop_\d+\.json$/.test(f)).sort();
const num = String(prev.length + 1).padStart(3, "0");
const lastAt = prev.length ? JSON.parse(fs.readFileSync(path.join(outdir, prev.at(-1)), "utf8")).rows_until : "";
const recent = rows.filter((r) => r.A_jikoku > lastAt);
function score(rs) {
  let e = 0, n = 0; const by = {};
  for (const r of rs) { const len = [...r.seikai].length, ce = r.I_kana_cer * len; e += ce; n += len; const b = (by[r.preset] ||= [0, 0]); b[0] += ce; b[1] += len; }
  const p = (a, b) => +(100 - (100 * a) / Math.max(1, b)).toFixed(1);
  return { kana_acc: p(e, n), n_utt: rs.length, by_preset: Object.fromEntries(Object.entries(by).sort().map(([k, [a, b]]) => [k, p(a, b)])) };
}
const conf = { cons: {}, vow: {}, del: {}, ins: {}, delctx: {} }, bump = (o, k) => (o[k] = (o[k] || 0) + 1);
for (const r of recent) {
  const T = moras(r.seikai), pairs = alignMoras(moras(r.kiku), T); let pv = "^";
  for (const [h, t] of pairs) {
    if (!h) { bump(conf.del, t.c + t.v); bump(conf.delctx, pv + "+" + t.c + t.v); }
    else if (!t) bump(conf.ins, h.c + h.v);
    else { if (h.c !== t.c) bump(conf.cons, `${t.c || "∅"}→${h.c || "∅"}`); if (h.v !== t.v) bump(conf.vow, `${t.v || "∅"}→${h.v || "∅"}`); }
    if (t) pv = t.v || t.c || pv;
  }
}
const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
const worst = [...recent].sort((a, b) => b.I_kana_cer - a.I_kana_cer).slice(0, 6).map((r) => ({ preset: r.preset, cer: r.I_kana_cer, ref: r.seikai, hyp: r.kiku }));
const D = {
  task: "关亡婆が書いた新しい台本（耳を育てるのに使ってない＝初見）を kusanagi が読み、耳 mimi（混合ガウス＋HMM、純JS。ear_commit が耳の版、tts_commit が声の版）が書き取った結果。正解＝kusanagi が実際に読んだかな。",
  ear: rows.at(-1).H_commit, tts_commit: TTS, ear_commit: rows.at(-1).ear_commit || "cd293c8", window: { from: recent[0]?.A_jikoku, to: recent.at(-1)?.A_jikoku, scripts: new Set(recent.map((r) => r.daihon_id)).size },
  score_recent: score(recent), score_all_loop: score(rows), prev_digest: prev.at(-1) || null,
  confusion_consonant: top(conf.cons, 10), confusion_vowel: top(conf.vow, 8), deletions: top(conf.del, 10), deletion_context_prevVowel_plus_mora: top(conf.delctx, 10), insertions: top(conf.ins, 6),
  worst_examples: worst, rows_until: rows.at(-1).A_jikoku,
};
const out = path.join(outdir, `digest_loop_${num}.json`);
fs.writeFileSync(out, JSON.stringify(D, null, 1));
console.log(out);
