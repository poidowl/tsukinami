// xray/suite.mjs — マルチ発話・マルチピッチ品質ゲート付きスイートランナー（純JS・0依存）
import fs from "node:fs";
import path from "node:path";
import { analyzeBuffer } from "./engine.mjs";

export const DEFAULT_SAFETY_GATES = Object.freeze({
  artifact_risk_100: ["<=", 12.0],
  cliff_all_ratio: ["<=", 55.0],
  max_sample_jump: ["<=", 6.0],
  pl_erb_rough_p90: ["<=", 14.0],
  intelligibility_guard_100: [">=", 85.0],
});

const VALID_OPS = new Set([">=", "<=", ">", "<"]);
const VSIB_TOKEN_RE = /(?:^|[\s_./-])(?:vsib|voiced[_-]sib(?:ilants?)?|z[_-]?row|dakuon[_-]z|ji)(?=$|[\s_./-])/i;
const AFFR_TOKEN_RE = /(?:^|[\s_./-])(?:affr(?:icates?)?|tsu|herutsu|ch[aiuo]?)(?=$|[\s_./-])/i;

function isPlainObject(v) {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

function validateRule(metric, rule) {
  if (!Array.isArray(rule) || rule.length !== 2) {
    throw new Error(`Malformed gate rule for metric '${metric}': expected [op, threshold]`);
  }
  const [op, threshold] = rule;
  if (!VALID_OPS.has(op)) {
    throw new Error(`Invalid gate operator '${op}' for metric '${metric}' (expected >=, <=, >, <)`);
  }
  if (typeof threshold !== "number" || !Number.isFinite(threshold)) {
    throw new Error(`Invalid gate threshold '${threshold}' for metric '${metric}' (must be finite number)`);
  }
  return { op, threshold };
}

function compareGate(actual, op, threshold) {
  if (op === ">=") return actual >= threshold;
  if (op === "<=") return actual <= threshold;
  if (op === ">") return actual > threshold;
  if (op === "<") return actual < threshold;
  return false;
}

export function evaluateItemGates(metrics, mergedGates) {
  let rules;
  if (mergedGates == null) {
    rules = [];
  } else if (Array.isArray(mergedGates)) {
    rules = mergedGates;
  } else if (isPlainObject(mergedGates)) {
    rules = [];
    for (const [metric, rule] of Object.entries(mergedGates)) {
      if (rule === null) continue;
      const { op, threshold } = validateRule(metric, rule);
      rules.push({ metric, op, threshold, source: "item" });
    }
  } else {
    throw new TypeError("Invalid gate specifications: expected plain object or rule array");
  }

  const results = [];
  for (const r of rules) {
    const { metric, op, threshold, source = "item" } = r;
    validateRule(metric, [op, threshold]);
    const hasKey = metrics != null && Object.prototype.hasOwnProperty.call(metrics, metric);
    const val = hasKey ? metrics[metric] : null;
    if (!hasKey || typeof val !== "number" || !Number.isFinite(val)) {
      results.push({ metric, op, threshold, actual: null, passed: false, source });
    } else {
      results.push({
        metric,
        op,
        threshold,
        actual: val,
        passed: compareGate(val, op, threshold),
        source,
      });
    }
  }
  return results;
}

function maxMetric(items, key) {
  let mx = -Infinity;
  for (const it of items) {
    const v = it.metrics?.[key];
    if (typeof v === "number" && Number.isFinite(v) && v > mx) mx = v;
  }
  return Number.isFinite(mx) ? mx : 0.0;
}

function minMetric(items, key) {
  let mn = Infinity;
  for (const it of items) {
    const v = it.metrics?.[key];
    if (typeof v === "number" && Number.isFinite(v) && v < mn) mn = v;
  }
  return Number.isFinite(mn) ? mn : 0.0;
}

export function computeSuiteRollups(items) {
  if (!Array.isArray(items) || !items.length) {
    return {
      worst_artifact_risk_100: 0.0,
      worst_cliff_all_ratio: 0.0,
      worst_pl_erb_rough_p90: 0.0,
      worst_max_sample_jump: 0.0,
      worst_post_pause_rise_ms: 0.0,
      min_vsib_coexist_pct: 0.0,
      min_affr_closure_depth_db: 0.0,
      min_intelligibility_guard_100: 0.0,
    };
  }

  const vsibItems = items.filter((it) =>
    (it.gateResults || []).some((g) => g.metric === "vsib_coexist_pct") ||
    VSIB_TOKEN_RE.test(`${it.category || ""} ${it.id || ""}`)
  );
  const affrItems = items.filter((it) =>
    (it.gateResults || []).some((g) => g.metric === "affr_closure_depth_db") ||
    AFFR_TOKEN_RE.test(`${it.category || ""} ${it.id || ""}`)
  );

  return {
    worst_artifact_risk_100: maxMetric(items, "artifact_risk_100"),
    worst_cliff_all_ratio: maxMetric(items, "cliff_all_ratio"),
    worst_pl_erb_rough_p90: maxMetric(items, "pl_erb_rough_p90"),
    worst_max_sample_jump: maxMetric(items, "max_sample_jump"),
    worst_post_pause_rise_ms: maxMetric(items, "post_pause_rise_ms"),
    min_vsib_coexist_pct: minMetric(vsibItems.length ? vsibItems : items, "vsib_coexist_pct"),
    min_affr_closure_depth_db: minMetric(affrItems.length ? affrItems : items, "affr_closure_depth_db"),
    min_intelligibility_guard_100: minMetric(items, "intelligibility_guard_100"),
  };
}

function resolveAudioPath(filePath, baseDir, label) {
  if (path.isAbsolute(filePath)) {
    if (!fs.existsSync(filePath)) throw new Error(`Missing WAV for suite item '${label}': ${filePath}`);
    return filePath;
  }
  const cand1 = path.resolve(baseDir || process.cwd(), filePath);
  if (fs.existsSync(cand1)) return cand1;
  if (baseDir && path.resolve(baseDir) !== path.resolve(process.cwd())) {
    const cand2 = path.resolve(process.cwd(), filePath);
    if (fs.existsSync(cand2)) return cand2;
  }
  throw new Error(`Missing WAV for suite item '${label}': ${cand1}`);
}

function buildMergedGates(entry, defaultGates, defaultEnabled, itemId) {
  const merged = new Map();
  const useDefault = entry.includeDefaultGates ?? defaultEnabled;
  if (useDefault && defaultGates) {
    for (const [metric, rule] of Object.entries(defaultGates)) {
      if (rule == null) continue;
      const { op, threshold } = validateRule(metric, rule);
      merged.set(metric, { metric, op, threshold, source: "default" });
    }
  }
  if (entry.gates !== undefined && entry.gates !== null) {
    if (!isPlainObject(entry.gates)) {
      throw new TypeError(`Invalid 'gates' for suite item '${itemId}': expected plain object`);
    }
    for (const [metric, rule] of Object.entries(entry.gates)) {
      if (rule === null) {
        merged.delete(metric);
      } else {
        const { op, threshold } = validateRule(metric, rule);
        merged.set(metric, { metric, op, threshold, source: "item" });
      }
    }
  }
  return Array.from(merged.values());
}

export function runSuite(manifestEntries, opts = {}) {
  if (!Array.isArray(manifestEntries)) {
    throw new TypeError("runSuite(manifestEntries, opts): manifestEntries must be an Array");
  }
  if (opts !== undefined && !isPlainObject(opts)) {
    throw new TypeError("runSuite(manifestEntries, opts): opts must be a plain object");
  }
  if (opts.defaultGates !== undefined && opts.defaultGates !== null && !isPlainObject(opts.defaultGates)) {
    throw new TypeError("Invalid 'defaultGates': expected plain object");
  }
  const baseDir = opts.baseDir || process.cwd();
  const defaultGates = opts.defaultGates === undefined ? DEFAULT_SAFETY_GATES : opts.defaultGates;
  const includeDefaultGates = opts.includeDefaultGates ?? true;
  const collectVisuals = Boolean(opts.collectVisuals);

  // Resolve suite-wide reference audio once upfront if supplied
  let suiteRef = null;
  if (opts.refObj) {
    suiteRef = opts.refObj;
  } else if (opts.refBytes) {
    suiteRef = analyzeBuffer(opts.refBytes);
  } else if (opts.refWav) {
    const refPath = resolveAudioPath(opts.refWav, baseDir, "__suite_ref__");
    suiteRef = analyzeBuffer(fs.readFileSync(refPath));
  }

  let fallbackRef = null;
  const items = [];
  const failures = [];
  const byItem = {};
  let totalGates = 0;
  let passedGates = 0;
  let itemsPassed = 0;
  let itemsFailed = 0;

  const explicitIds = new Set();
  const usedIds = new Set();
  for (let idx = 0; idx < manifestEntries.length; idx++) {
    const entry = manifestEntries[idx];
    if (!isPlainObject(entry)) {
      throw new TypeError(`Invalid suite manifest entry at index ${idx}: expected plain object`);
    }
    if (entry.id !== undefined && entry.id !== null) {
      if (typeof entry.id !== "string" || !entry.id.trim()) {
        throw new TypeError(`Invalid 'id' for suite item at index ${idx}: expected non-empty string`);
      }
      if (explicitIds.has(entry.id)) {
        throw new Error(`Duplicate suite item id: '${entry.id}'`);
      }
      explicitIds.add(entry.id);
      usedIds.add(entry.id);
    }
  }

  for (let idx = 0; idx < manifestEntries.length; idx++) {
    const entry = manifestEntries[idx];
    let id;
    if (entry.id !== undefined && entry.id !== null) {
      id = entry.id;
    } else {
      const baseId = entry.wav ? path.basename(entry.wav, path.extname(entry.wav)) : `item_${idx}`;
      id = baseId;
      if (usedIds.has(id)) {
        let n = 2;
        while (usedIds.has(`${baseId}#${n}`)) n++;
        id = `${baseId}#${n}`;
      }
      usedIds.add(id);
    }
    const category = entry.category || "general";
    const hz = entry.hz ?? null;
    const refText = entry.ref ?? null;

    let bytes = null;
    let resolvedWav = entry.wav || null;
    if (entry.wavBytes) {
      bytes = entry.wavBytes;
    } else if (entry.wav) {
      resolvedWav = resolveAudioPath(entry.wav, baseDir, id);
      bytes = fs.readFileSync(resolvedWav);
    } else {
      throw new Error(`Suite item '${id}' requires either 'wav' path or 'wavBytes'`);
    }

    let activeRef = suiteRef || fallbackRef;
    if (entry.refBytes) {
      activeRef = analyzeBuffer(entry.refBytes);
    } else if (entry.refWav) {
      const pRef = resolveAudioPath(entry.refWav, baseDir, `${id}:refWav`);
      activeRef = analyzeBuffer(fs.readFileSync(pRef));
    }

    const res = analyzeBuffer(bytes, activeRef ? activeRef.d : null, activeRef ? activeRef.metrics : null);
    if (!suiteRef && idx === 0) fallbackRef = res;

    const mergedGates = buildMergedGates(entry, defaultGates, includeDefaultGates, id);
    const gateResults = evaluateItemGates(res.metrics, mergedGates);
    const itemFailedGates = gateResults.filter((g) => !g.passed);
    const itemPassed = itemFailedGates.length === 0;

    totalGates += gateResults.length;
    passedGates += gateResults.length - itemFailedGates.length;
    if (itemPassed) itemsPassed++;
    else itemsFailed++;

    for (const fg of itemFailedGates) {
      failures.push({
        id,
        metric: fg.metric,
        op: fg.op,
        threshold: fg.threshold,
        actual: fg.actual,
        source: fg.source,
      });
    }
    byItem[id] = {
      passed: itemPassed,
      total: gateResults.length,
      failed: itemFailedGates.length,
      results: gateResults,
    };

    const itemObj = {
      id,
      category,
      hz,
      wav: resolvedWav,
      ref: refText,
      label: id,
      metrics: res.metrics,
      gateResults,
      passed: itemPassed,
    };
    if (collectVisuals) itemObj.visuals = res.visuals;
    items.push(itemObj);
  }

  const rollups = computeSuiteRollups(items);
  const failedGates = totalGates - passedGates;
  return {
    items,
    rollups,
    gates: {
      total: totalGates,
      passed: passedGates,
      failed: failedGates,
      itemsPassed,
      itemsFailed,
      byItem,
    },
    failures,
    passed: failures.length === 0,
  };
}

export function formatSuiteTable(suiteResult) {
  const { items, rollups, gates, failures, passed } = suiteResult;
  const lines = [];
  lines.push(
    `[xray-suite] ${items.length} items | ${gates.passed}/${gates.total} gates passed | VERDICT: ${passed ? "PASS" : "FAIL"}`
  );
  const hdr = [
    "ID".padEnd(18),
    "Category".padEnd(14),
    "Hz".padStart(4),
    "Kawaii".padStart(6),
    "Sweet".padStart(6),
    "Babaa".padStart(6),
    "ArtRsk".padStart(6),
    "ClfAll".padStart(6),
    "MaxJmp".padStart(6),
    "PLp90".padStart(6),
    "PostMs".padStart(6),
    "VSib%".padStart(6),
    "AffrDB".padStart(6),
    "Guard".padStart(6),
    "Gate".padStart(5),
  ].join(" ");
  lines.push(hdr);
  lines.push("-".repeat(hdr.length));
  for (const it of items) {
    const m = it.metrics;
    const fmt = (v, d = 1) => (typeof v === "number" && Number.isFinite(v) ? v.toFixed(d) : "-");
    lines.push([
      String(it.id).slice(0, 18).padEnd(18),
      String(it.category).slice(0, 14).padEnd(14),
      (it.hz != null ? String(it.hz) : "-").padStart(4),
      fmt(m.kawaii_overall_100, 1).padStart(6),
      fmt(m.sweet_voice_100, 1).padStart(6),
      fmt(m.bb_babaa_index_100, 1).padStart(6),
      fmt(m.artifact_risk_100, 1).padStart(6),
      fmt(m.cliff_all_ratio, 1).padStart(6),
      fmt(m.max_sample_jump, 2).padStart(6),
      fmt(m.pl_erb_rough_p90, 1).padStart(6),
      fmt(m.post_pause_rise_ms, 1).padStart(6),
      fmt(m.vsib_coexist_pct, 1).padStart(6),
      fmt(m.affr_closure_depth_db, 1).padStart(6),
      fmt(m.intelligibility_guard_100, 1).padStart(6),
      (it.passed ? "PASS" : "FAIL").padStart(5),
    ].join(" "));
  }
  lines.push("");
  lines.push("Canonical Rollups:");
  for (const [k, v] of Object.entries(rollups)) {
    lines.push(`  ${k.padEnd(30)} = ${v}`);
  }
  if (failures.length) {
    lines.push("");
    lines.push(`Gate Failures (${failures.length}):`);
    for (const f of failures) {
      lines.push(`  [FAIL] ${f.id}: ${f.metric} = ${f.actual} (expected ${f.op} ${f.threshold}, source=${f.source})`);
    }
  }
  return lines.join("\n");
}
