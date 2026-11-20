#!/usr/bin/env node
/**
 * hodoki.mjs — Hodoki（ほどき）：声に重なった情報（高さ・声道・揃い不揃い・息・言葉）をほどいて読み出す音声汎用デコーダー
 * Node.js 標準ライブラリのみ。モジュールは hodoki/*.mjs に1本ずつ足していく。
 *   soroi   … 揃い／不揃い（ジッター・シマー・非整数倍度・HNR）
 *   michi   … 声の道（自前 LPC フォルマント・声道長・H1−H2）＋ 話し手像カード（幅つき）
 *   tsumami … 草薙のつまみを特徴から当てられるかの調べ（乱数合成 → 回帰の一個抜き R²）
 *
 *   node hodoki.mjs [soroi] in.wav [-o out/hodoki_soroi_in.html] [--json out.json]
 *   node hodoki.mjs soroi --synth "わたし、にほんご、ちょっとしゃべれます" --preset hitofude [--set jitter=0 ...]
 *   node hodoki.mjs michi in.wav                         # 話し手像カード
 *   node hodoki.mjs michi --synth "…" --preset hitofude --decode [--study-json out/hodoki_tsumami_study.json]
 *       （--decode：合成による分析で草薙のつまみを幅つきで当て、表をレポートに足す。study が無ければ 120 本作る）
 *   node hodoki.mjs tsumami [--study-n 200] [--json out/hodoki_tsumami_study.json]
 *   node hodoki/test_soroi.mjs ; node hodoki/test_michi.mjs   # 物差し検定
 */
import fs from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import { analyze, readWav, renderHtml } from "./hodoki/soroi.mjs";

const MODULES = ["soroi", "michi", "tsumami"];
const argv = process.argv.slice(2);
const mod = MODULES.includes(argv[0]) ? argv.shift() : "soroi";

const { values: a, positionals } = parseArgs({
  args: argv,
  allowPositionals: true,
  options: {
    out: { type: "string", short: "o" },
    json: { type: "string" },
    synth: { type: "string" },
    preset: { type: "string", default: "hitofude" },
    set: { type: "string", multiple: true }, // --set jitter=0 など、プリセットのノブを上書き
    seed: { type: "string" },
    "min-f0": { type: "string" },
    "max-f0": { type: "string" },
    decode: { type: "boolean" },
    "study-json": { type: "string" },
    "study-n": { type: "string" },
    help: { type: "boolean", short: "h" },
  },
});
const usage = () => console.log(fs.readFileSync(new URL(import.meta.url)).toString().split("*/")[0]);
if (a.help) { usage(); process.exit(0); }
fs.mkdirSync("out", { recursive: true });

if (mod === "tsumami") {
  const { study } = await import("./hodoki/tsumami.mjs");
  const N = Number(a["study-n"] || 200), t0 = Date.now();
  const s = study(N, 1, (i, n) => { if (i % 20 === 0) console.error(`  ${i}/${n}`); });
  const out = a.json || path.join("out", "hodoki_tsumami_study.json");
  fs.writeFileSync(out, JSON.stringify(s));
  for (const [k, v] of Object.entries(s.recover)) console.log(`${k.padEnd(10)} R²(LOO) ${v.r2_loo.toFixed(3)}  RMSE ${v.rmse.toPrecision(3)}  効く特徴 ${v.top.map(([f, c]) => `${f}(${c})`).join(" ")}`);
  console.log(`[hodoki:tsumami] ${out}  (${N} 本, ${((Date.now() - t0) / 1000).toFixed(0)} s)`);
  process.exit(0);
}

if (!a.synth && positionals.length === 0) { usage(); process.exit(1); }
let wavPath, meta = {}, x, sr, knobsTrue = null;
if (a.synth) {
  const { makeHitofude, PRESETS, encodeWav } = await import("./hitofude.mjs");
  if (!PRESETS[a.preset]) throw new Error(`unknown preset ${a.preset}`);
  const prm = { ...PRESETS[a.preset] };
  const over = {};
  for (const kv of a.set || []) { const [k, v] = kv.split("="); prm[k] = Number(v); over[k] = Number(v); }
  if (a.seed) prm.seed = Number(a.seed);
  const r = makeHitofude(a.synth, prm);
  knobsTrue = prm;
  const tag = a.preset + Object.entries(over).map(([k, v]) => `_${k}${v}`).join("");
  wavPath = path.join("out", `hodoki_src_${tag}.wav`);
  fs.writeFileSync(wavPath, encodeWav(r.samples));
  meta = { 入力: `草薙合成 preset=${a.preset}${Object.keys(over).length ? " " + JSON.stringify(over) : ""}`, テキスト: a.synth, wav: wavPath };
}
if (!a.synth) { wavPath = positionals[0]; meta = { 入力: wavPath }; }
({ sr, x } = (() => { const w = readWav(fs.readFileSync(wavPath)); meta["サンプルレート"] = `${w.sr} Hz${w.channels > 1 ? `（${w.channels}ch→平均）` : ""}`; return w; })());
const opts = {};
if (a["min-f0"]) opts.minF0 = Number(a["min-f0"]);
if (a["max-f0"]) opts.maxF0 = Number(a["max-f0"]);
const t0 = Date.now();
const base = path.basename(wavPath, path.extname(wavPath));

if (mod === "soroi") {
  const res = analyze(x, sr, opts);
  res.x = x;
  meta["解析時間"] = `${Date.now() - t0} ms`;
  const out = a.out || path.join("out", `hodoki_soroi_${base}.html`);
  fs.writeFileSync(out, renderHtml(res, meta));
  if (a.json) fs.writeFileSync(a.json, JSON.stringify({ meta, summary: res.summary }, null, 2));
  console.log(`[hodoki:soroi] ${out}`);
  console.log(JSON.stringify(res.summary));
} else if (mod === "michi") {
  const { analyzeMichi, renderMichiHtml, featureVector } = await import("./hodoki/michi.mjs");
  const res = analyzeMichi(x, sr, { soroi: opts });
  meta["解析時間"] = `${Date.now() - t0} ms`;
  let extra = "", decoded = null;
  if (a.decode) {
    const T = await import("./hodoki/tsumami.mjs");
    if (sr !== 44100) throw new Error("--decode は 44.1 kHz の音だけ（草薙と同じ）");
    let S;
    if (a["study-json"] && fs.existsSync(a["study-json"])) S = JSON.parse(fs.readFileSync(a["study-json"]));
    else { console.error("  study を作ります（120 本）…"); S = T.study(120, 1); fs.writeFileSync(path.join("out", "hodoki_tsumami_study.json"), JSON.stringify(S)); }
    const fv = featureVector(res), ft = T.FEATS.map((f) => fv[f]);
    const t1 = Date.now();
    decoded = T.decodeKnobs(ft, S, { log: (i) => { if (i % 30 === 0) console.error(`  逆算 ${i} 回`); } });
    meta["つまみ逆算"] = `Nelder–Mead ${decoded.evals} 回＋幅 ${((Date.now() - t1) / 1000).toFixed(0)} s（study ${S.n} 本）`;
    extra = knobTable(T, S, decoded, knobsTrue);
  }
  const out = a.out || path.join("out", `hodoki_michi_${base}.html`);
  fs.writeFileSync(out, renderMichiHtml(res, x, meta, extra));
  const card = { ...res.card };
  if (a.json) fs.writeFileSync(a.json, JSON.stringify({ meta, card, decoded }, null, 2));
  console.log(`[hodoki:michi] ${out}`);
  console.log(JSON.stringify({ vtl_cm: card.vtl_cm, f0_hz: card.f0_hz, h1h2c_db: card.h1h2c_db, hnr_db: card.hnr_db }));
  if (decoded) for (const [k, v] of Object.entries(decoded.ranges)) console.log(`  ${k.padEnd(10)} 当て ${fmt(v.best)}  幅 ${fmt(v.range[0])}–${fmt(v.range[1])}${knobsTrue ? `  真値 ${fmt(knobsTrue[k] ?? (k === "damp" ? 0.08 : k === "level_k" ? 0.65 : NaN))}` : ""}`);
}

function fmt(v) { return Number.isFinite(v) ? (+v.toPrecision(4)).toString() : "—"; }
function knobTable(T, S, dec, truth) {
  const verdict = (r2) => (r2 >= 0.9 ? "当てられる" : r2 >= 0.3 ? "幅つき（部分的）" : "当てられない");
  const tv = (k) => (truth ? (truth[k] ?? (k === "damp" ? 0.08 : k === "level_k" ? 0.65 : NaN)) : NaN);
  const rows = T.KNOBS.map((kn) => {
    const s = S.recover[kn.k], d = dec.ranges[kn.k];
    return `<tr><th>${kn.k}</th><td>${kn.lo}–${kn.hi}</td><td>${s.r2_loo.toFixed(3)}</td><td>${fmt(s.rmse)}</td><td><b>${fmt(d.best)}</b></td><td>${fmt(d.range[0])}–${fmt(d.range[1])}（全域の ${(100 * d.width_u).toFixed(0)}%）</td>${truth ? `<td>${fmt(tv(kn.k))}${Number.isFinite(tv(kn.k)) ? (tv(kn.k) >= d.range[0] - 1e-9 && tv(kn.k) <= d.range[1] + 1e-9 ? " ✓" : " ✗") : ""}</td>` : ""}<td>${d.confounded.map(([k, c]) => `${k}(${c})`).join(" ") || "—"}</td><td>${verdict(s.r2_loo)}</td></tr>`;
  }).join("");
  return `<h2>草薙のつまみ逆算（合成による分析）</h2>
<table><tr><th>つまみ</th><th>調べた範囲</th><th>回帰 R²（一個抜き）</th><th>回帰 RMSE</th><th>当てた値</th><th>幅（Fisher ±2σ ∪ seed 再当て）</th>${truth ? "<th>真値</th>" : ""}<th>取り違え相手（|相関|&gt;0.5）</th><th>判定（R² で）</th></tr>${rows}</table>
<p class="n">study＝つまみと seed を一様乱数で振った草薙合成 ${S.n} 本（同じ文）。回帰＝特徴 ${T.FEATS.length} 個を標準化した自前リッジ回帰の一個抜き交差検証。逆算＝回帰の予測から始め、seed 777 の草薙で Nelder–Mead（${dec.evals} 回）して目標の特徴との重みつき距離（重み＝seed 揺れの分散の逆数）を最小化。幅＝最良点のまわりの Fisher ±2σ（特徴の揺れを独立とみなす）と、最良点を seed 10 通りで鳴らしてヤコビアン1歩で当て直した値の min–max の和集合。判定は R² ≥ 0.9＝当てられる、0.3–0.9＝幅つき、&lt; 0.3＝当てられない。shin は 1.0 に固定。文が1つだけなので、話速 rate は「長さ」でほぼ決まる（別の文には一般化しない）。</p>`;
}
