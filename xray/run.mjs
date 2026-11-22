#!/usr/bin/env node
// xray/run.mjs — カワイイクサナギ 変態解析ツール100選 CLIランナー（純JS・0依存）
// 使い方: node xray/run.mjs file1.wav file2.wav ...
import fs from "node:fs";
import path from "node:path";
import { decodeWav, extractBaseFrameData } from "./core.mjs";
import { CAT01_TOOLS } from "./cat01_glottal.mjs";

export const ALL_TOOLS = [
  ...CAT01_TOOLS,
];

export function analyzeBuffer(bytes) {
  const { sr, samples } = decodeWav(bytes);
  const d = extractBaseFrameData(sr, samples);
  const out = {};
  for (const tool of ALL_TOOLS) out[tool.key] = tool.run(d);
  return out;
}

function main() {
  const args = process.argv.slice(2);
  const asJson = args.includes("--json");
  const files = args.filter((a) => !a.startsWith("--"));
  if (!files.length) {
    console.log(`Usage: node xray/run.mjs [--json] <wav1> [wav2 ...]`);
    console.log(`Registered tools (${ALL_TOOLS.length}):`);
    for (const t of ALL_TOOLS) console.log(`  #${String(t.id).padStart(2, "0")} ${t.key.padEnd(20)} : ${t.name} [${t.unit}]`);
    return;
  }

  const results = files.map((f) => {
    const label = path.basename(f, path.extname(f));
    const bytes = fs.readFileSync(f);
    return { label, file: f, metrics: analyzeBuffer(bytes) };
  });

  if (asJson) {
    console.log(JSON.stringify(results, null, 2));
    return;
  }

  const colW = 14;
  const header = `${"#".padEnd(3)} ${"Tool".padEnd(22)} ${"Unit".padEnd(7)} | ` + results.map((r) => r.label.slice(0, colW).padStart(colW)).join(" | ");
  console.log(header);
  console.log("-".repeat(header.length));
  for (const t of ALL_TOOLS) {
    const row = `${String(t.id).padStart(2, "0")}  ${t.key.padEnd(22)} ${t.unit.padEnd(7)} | ` +
      results.map((r) => String(r.metrics[t.key]).padStart(colW)).join(" | ");
    console.log(row);
  }
}

main();
