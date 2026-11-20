#!/usr/bin/env node
// 響: 匿名試聴パック生成。外部パッケージ不要、手動で答え合わせする方式。
// Usage: node tools/hibiki_listen.mjs [output-directory]
// 出力先が既存なら失敗する（WAVや採点結果を上書きしない）。
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { encodeWav, makeHitofude, makeRng, PRESETS } from "../hitofude.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(process.argv[2] || path.join(root, "out", "hibiki_blind"));
const voices = ["hibiki", "hibiki_katari", "hibiki_awa", "hibiki_kiba"];
const lines = [
  "あさのひかり、ゆめのかけら",
  "あのひとのこえが、まだみみにのこっている",
  "ねえ、きょうはなにをはなそうか？",
];
const rng = makeRng(20261120);
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.mkdirSync(out); // EEXIST: 意図せぬ上書きを拒否
const entries = [];
for (let j = 0; j < lines.length; j++) {
  const order = voices.slice();
  for (let i = order.length - 1; i > 0; i--) {
    const k = Math.floor(rng.random() * (i + 1));
    [order[i], order[k]] = [order[k], order[i]];
  }
  for (let i = 0; i < order.length; i++) {
    const preset = order[i];
    const name = `line${j + 1}_${String.fromCharCode(65 + i)}.wav`;
    const { samples } = makeHitofude(lines[j], PRESETS[preset]);
    fs.writeFileSync(path.join(out, name), encodeWav(samples));
    entries.push({ file: name, line: j + 1, preset });
  }
}
const guide = [
  "# 響：匿名試聴",
  "音声は line1_A → line1_D、続いて line2, line3 の順に聴く。",
  "採点時には answer_key.json を開かない。",
  "各WAVについて、以下を1〜5で採点（1=低い、5=高い）。",
  "可読性 / 耳の快適さ / 記憶に残る度合い / 続きを聴きたい度合い",
  "自由記述：魅力的な癖、不快な瞬間、言葉の聞き違い。",
  "",
  "line1: " + lines[0],
  "line2: " + lines[1],
  "line3: " + lines[2],
  "",
  "音の好みと個人差があるため、これは評価手段であり改善の証拠ではない。",
].join("\n");
fs.writeFileSync(path.join(out, "LISTEN_FIRST.txt"), guide + "\n");
fs.writeFileSync(path.join(out, "answer_key.json"), JSON.stringify({ lines, entries }, null, 2) + "\n");
console.log(`[hibiki] ${entries.length} WAV + listening guide + answer key -> ${out}`);
