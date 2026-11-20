#!/usr/bin/env node
/**
 * hodoki.mjs — Hodoki（ほどき）：声に重なった情報（高さ・声道・揃い不揃い・息・言葉）をほどいて読み出す音声汎用デコーダー
 * Node.js 標準ライブラリのみ。モジュールは hodoki/*.mjs に1本ずつ足していく（いまは soroi＝揃い／不揃い だけ）。
 *
 *   node hodoki.mjs [soroi] in.wav [-o out/hodoki_soroi_in.html] [--json out.json]
 *   node hodoki.mjs soroi --synth "わたし、にほんご、ちょっとしゃべれます" --preset hitofude [--set jitter=0 ...]
 *       （草薙エンジンで合成した wav をそのまま観察。wav も out/ に保存）
 *   node hodoki/test_soroi.mjs      # 物差し検定（合成テスト音で①〜④が仕込み量どおり動くか）
 */
import fs from "node:fs";
import path from "node:path";
import { parseArgs } from "node:util";
import { analyze, readWav, renderHtml } from "./hodoki/soroi.mjs";

const MODULES = ["soroi"];
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
    "min-f0": { type: "string" },
    "max-f0": { type: "string" },
    help: { type: "boolean", short: "h" },
  },
});
if (a.help || (!a.synth && positionals.length === 0)) {
  console.log(fs.readFileSync(new URL(import.meta.url)).toString().split("*/")[0]);
  process.exit(a.help ? 0 : 1);
}
fs.mkdirSync("out", { recursive: true });
let wavPath, meta = {};
if (a.synth) {
  const { synth, PRESETS } = await import("./yomu.mjs");
  const prm = { ...PRESETS[a.preset] };
  if (!PRESETS[a.preset]) throw new Error(`unknown preset ${a.preset}`);
  const over = {};
  for (const kv of a.set || []) { const [k, v] = kv.split("="); prm[k] = Number(v); over[k] = Number(v); }
  const { encodeWav } = await import("./hitofude.mjs");
  const r = synth(a.synth, prm);
  const tag = a.preset + Object.entries(over).map(([k, v]) => `_${k}${v}`).join("");
  wavPath = path.join("out", `hodoki_src_${tag}.wav`);
  fs.writeFileSync(wavPath, encodeWav(r.samples));
  meta = { 入力: `草薙合成 preset=${a.preset}${Object.keys(over).length ? " " + JSON.stringify(over) : ""}`, テキスト: a.synth, wav: wavPath };
} else {
  wavPath = positionals[0];
  meta = { 入力: wavPath };
}
const { sr, x, channels } = readWav(fs.readFileSync(wavPath));
meta["サンプルレート"] = `${sr} Hz${channels > 1 ? `（${channels}ch→平均）` : ""}`;
const opts = {};
if (a["min-f0"]) opts.minF0 = Number(a["min-f0"]);
if (a["max-f0"]) opts.maxF0 = Number(a["max-f0"]);
const t0 = Date.now();
const res = analyze(x, sr, opts);
res.x = x;
meta["解析時間"] = `${Date.now() - t0} ms`;
const out = a.out || path.join("out", `hodoki_${mod}_${path.basename(wavPath, path.extname(wavPath))}.html`);
fs.writeFileSync(out, renderHtml(res, meta));
if (a.json) fs.writeFileSync(a.json, JSON.stringify({ meta, summary: res.summary }, null, 2));
console.log(`[hodoki:${mod}] ${out}`);
console.log(JSON.stringify(res.summary));
