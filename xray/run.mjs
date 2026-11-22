#!/usr/bin/env node
// xray/run.mjs — カワイイクサナギ 変態解析ツール100選 CLIランナー（純JS・0依存）
// 使い方: node xray/run.mjs file1.wav file2.wav ...
import fs from "node:fs";
import path from "node:path";
import { decodeWav, extractBaseFrameData } from "./core.mjs";
import { CAT01_TOOLS } from "./cat01_glottal.mjs";
import { CAT02_TOOLS } from "./cat02_artifacts.mjs";
import { CAT03_TOOLS } from "./cat03_vocal_tract.mjs";
import { CAT04_TOOLS } from "./cat04_phase.mjs";
import { CAT05_TOOLS } from "./cat05_prosody.mjs";
import { CAT06_TOOLS } from "./cat06_breath.mjs";
import { CAT07_TOOLS } from "./cat07_consonants.mjs";
import { CAT08_TOOLS } from "./cat08_psycho.mjs";
import { CAT09_TOOLS } from "./cat09_composite.mjs";
import { buildHtmlReport, CAT10_TOOLS } from "./cat10_visual.mjs";

export const ALL_TOOLS = [
  ...CAT01_TOOLS,
  ...CAT02_TOOLS,
  ...CAT03_TOOLS,
  ...CAT04_TOOLS,
  ...CAT05_TOOLS,
  ...CAT06_TOOLS,
  ...CAT07_TOOLS,
  ...CAT08_TOOLS,
  ...CAT09_TOOLS,
  ...CAT10_TOOLS,
];

export function analyzeBuffer(bytes, ref = null, refMetrics = null) {
  const { sr, samples } = decodeWav(bytes);
  const d = extractBaseFrameData(sr, samples);
  const metrics = {};
  const visuals = {};
  for (const tool of ALL_TOOLS) metrics[tool.key] = tool.run(d, { metrics, visuals, ref, refMetrics });
  return { d, metrics, visuals };
}

function main() {
  const args = process.argv.slice(2);
  const asJson = args.includes("--json");
  let reportPath = null;
  const files = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--report" && args[i + 1]) { reportPath = args[++i]; }
    else if (!args[i].startsWith("--")) files.push(args[i]);
  }
  if (!files.length) {
    console.log(`Usage: node xray/run.mjs [--json] [--report out.html] <wav1> [wav2 ...]`);
    console.log(`Registered tools (${ALL_TOOLS.length}):`);
    for (const t of ALL_TOOLS) console.log(`  #${String(t.id).padStart(2, "0")} ${t.key.padEnd(22)} : ${t.name} [${t.unit}]`);
    return;
  }

  let refD = null, refMetrics = null;
  const results = files.map((f, idx) => {
    const label = path.basename(f, path.extname(f));
    const bytes = fs.readFileSync(f);
    const { d, metrics, visuals } = analyzeBuffer(bytes, refD, refMetrics);
    if (idx === 0) { refD = d; refMetrics = metrics; }
    return { label, file: f, metrics, visuals };
  });

  if (reportPath) {
    fs.writeFileSync(reportPath, buildHtmlReport(results, ALL_TOOLS));
    console.log(`[xray] Saved 100-Tool HTML Report -> ${reportPath}`);
  }

  if (asJson) {
    console.log(JSON.stringify(results.map(({ label, file, metrics }) => ({ label, file, metrics })), null, 2));
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

import { fileURLToPath } from "node:url";

if (path.resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main();
}
