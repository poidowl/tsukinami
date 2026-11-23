#!/usr/bin/env node
// xray/run.mjs — カワイイクサナギ 変態解析ツール150選 CLIランナー & スイートゲート実行器（純JS・0依存）
// 使い方:
//   node xray/run.mjs [--json] [--report out.html] <wav1> [wav2 ...]
//   node xray/run.mjs --suite <manifest.json> [--ref-wav <ref.wav>] [--gate-strict] [--no-default-gates] [--json] [--report out.html]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ALL_TOOLS, analyzeBuffer } from "./engine.mjs";
import { runSuite, DEFAULT_SAFETY_GATES, formatSuiteTable } from "./suite.mjs";
import { buildHtmlReport } from "./cat10_visual.mjs";

export { ALL_TOOLS, analyzeBuffer, runSuite, DEFAULT_SAFETY_GATES };

function requireArg(args, i, flag) {
  const val = args[i + 1];
  if (i + 1 >= args.length || typeof val !== "string" || !val.trim() || val.startsWith("--")) {
    throw new Error(`Missing required argument for ${flag}`);
  }
  return val;
}

function main() {
  const args = process.argv.slice(2);
  let asJson = false;
  let reportPath = null;
  let suitePath = null;
  let refWavPath = null;
  let gateStrict = false;
  let noDefaultGates = false;
  const files = [];

  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--json") { asJson = true; }
    else if (a === "--gate-strict") { gateStrict = true; }
    else if (a === "--no-default-gates") { noDefaultGates = true; }
    else if (a === "--report") { reportPath = requireArg(args, i, "--report"); i++; }
    else if (a === "--suite") { suitePath = requireArg(args, i, "--suite"); i++; }
    else if (a === "--ref-wav") { refWavPath = requireArg(args, i, "--ref-wav"); i++; }
    else if (a.startsWith("-")) { throw new Error(`Unknown option: ${a}`); }
    else if (!a.trim()) { throw new Error("Empty WAV file path argument"); }
    else { files.push(a); }
  }

  if (!suitePath) {
    if (refWavPath !== null) throw new Error("Option --ref-wav requires --suite <manifest.json>");
    if (gateStrict) throw new Error("Option --gate-strict requires --suite <manifest.json>");
    if (noDefaultGates) throw new Error("Option --no-default-gates requires --suite <manifest.json>");
  } else if (files.length) {
    throw new Error(`Unexpected positional arguments with --suite: ${files.join(", ")}`);
  }

  if (suitePath) {
    const absManifest = path.resolve(suitePath);
    if (!fs.existsSync(absManifest)) {
      throw new Error(`Suite manifest not found: ${absManifest}`);
    }
    const raw = fs.readFileSync(absManifest, "utf8");
    let manifestEntries;
    try {
      manifestEntries = JSON.parse(raw);
    } catch (err) {
      throw new Error(`Invalid JSON in suite manifest '${absManifest}': ${err.message}`);
    }
    if (!Array.isArray(manifestEntries)) {
      throw new Error(`Suite manifest '${absManifest}' must be a JSON Array`);
    }
    const suiteResult = runSuite(manifestEntries, {
      refWav: refWavPath ? path.resolve(refWavPath) : null,
      baseDir: path.dirname(absManifest),
      includeDefaultGates: !noDefaultGates,
      collectVisuals: Boolean(reportPath),
    });

    if (reportPath) {
      fs.writeFileSync(reportPath, buildHtmlReport(suiteResult.items, ALL_TOOLS, suiteResult));
      const msg = `[xray] Saved ${ALL_TOOLS.length}-Tool Suite HTML Report -> ${reportPath}`;
      if (asJson) console.error(msg);
      else console.log(msg);
    }

    if (asJson) {
      const cleanItems = suiteResult.items.map(({ visuals, ...rest }) => rest);
      const out = {
        items: cleanItems,
        rollups: suiteResult.rollups,
        gates: suiteResult.gates,
        failures: suiteResult.failures,
        passed: suiteResult.passed,
      };
      console.log(JSON.stringify(out, null, 2));
    } else {
      console.log(formatSuiteTable(suiteResult));
    }

    if (gateStrict && !suiteResult.passed) process.exitCode = 1;
    return;
  }

  if (!files.length) {
    if (asJson || reportPath !== null) {
      throw new Error("Missing WAV file argument(s) (or use --suite <manifest.json>)");
    }
    console.log("Usage:");
    console.log("  node xray/run.mjs [--json] [--report out.html] <wav1> [wav2 ...]");
    console.log("  node xray/run.mjs --suite <manifest.json> [--ref-wav <ref.wav>] [--gate-strict] [--no-default-gates] [--json] [--report out.html]");
    console.log(`Registered tools (${ALL_TOOLS.length}):`);
    for (const t of ALL_TOOLS) {
      console.log(`  #${String(t.id).padStart(3, "0")} ${t.key.padEnd(26)} : ${t.name} [${t.unit}]`);
    }
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
    const msg = `[xray] Saved ${ALL_TOOLS.length}-Tool HTML Report -> ${reportPath}`;
    if (asJson) console.error(msg);
    else console.log(msg);
  }

  if (asJson) {
    console.log(JSON.stringify(results.map(({ label, file, metrics }) => ({ label, file, metrics })), null, 2));
    return;
  }

  const colW = 14;
  const header = `${"#".padEnd(4)} ${"Tool".padEnd(26)} ${"Unit".padEnd(7)} | ` +
    results.map((r) => r.label.slice(0, colW).padStart(colW)).join(" | ");
  console.log(header);
  console.log("-".repeat(header.length));
  for (const t of ALL_TOOLS) {
    const row = `${String(t.id).padStart(3, "0")}  ${t.key.padEnd(26)} ${t.unit.padEnd(7)} | ` +
      results.map((r) => String(r.metrics[t.key]).padStart(colW)).join(" | ");
    console.log(row);
  }
}

function isMainEntry() {
  if (!process.argv[1]) return false;
  const selfPath = fileURLToPath(import.meta.url);
  const argPath = path.resolve(process.argv[1]);
  if (argPath === selfPath) return true;
  try {
    return fs.realpathSync(argPath) === fs.realpathSync(selfPath);
  } catch {
    return false;
  }
}

if (isMainEntry()) {
  try {
    main();
  } catch (err) {
    console.error(`[xray] Error: ${err?.message || err}`);
    process.exitCode = 1;
  }
}
