#!/usr/bin/env node
/**
 * yomu.mjs — 一筆彫りTTS 草薙版 (tsukinami / kusanagi branch) CLI・自己計測ドライバ（Node.js 標準ライブラリのみ）
 *
 * 使い方:
 *   node yomu.mjs "わたし、にほんご、ちょっとしゃべれます"
 *   node yomu.mjs --preset toiki --measure "わたし、にほんご、ちょっとしゃべれます"
 *   node yomu.mjs --preset sasayaki --compare "ないしょの、おはなしですよ"
 *   node yomu.mjs --uta 294,330,349,392,440,392,330,294 --measure "ワタシノナマエハ"
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { encodeWav, hakaru, KNOB_KEYS, makeHitofude, PRESETS, SR } from "./hitofude.mjs";

export { KNOB_KEYS, PRESETS };

const HERE = path.dirname(fileURLToPath(import.meta.url));

export function synth(text, prm, utaHz = null) {
  return makeHitofude(text, {
    seed: Math.trunc(Number(prm.seed)),
    hz: Number(prm.hz),
    fscale: Number(prm.fscale),
    rate: Number(prm.rate),
    g_vo: Number(prm.g_vo),
    tilt_w: Math.round(Number(prm.tilt_w)),
    sigh: Number(prm.sigh),
    jitter: Number(prm.jitter),
    wander_st: Number(prm.wander_st),
    damp: prm.damp === undefined ? 0.08 : Number(prm.damp),
    shin: prm.shin === undefined ? 1.0 : Number(prm.shin),
    character: prm.character === undefined ? 0.0 : Number(prm.character),
    edge: prm.edge === undefined ? 0.0 : Number(prm.edge),
    cadence: prm.cadence === undefined ? 0.0 : Number(prm.cadence),
    closeness: prm.closeness === undefined ? 0.0 : Number(prm.closeness),
    uta_hz: utaHz,
  });
}

function envDbCurve(sig, bins = 160) {
  const n = sig.length;
  if (n === 0) return new Float64Array(bins).fill(-90.0);
  const win = Math.max(1, Math.trunc(0.020 * SR));
  const out = new Float64Array(bins);
  for (let b = 0; b < bins; b++) {
    const c = Math.trunc(((b + 0.5) / bins) * n);
    const i0 = Math.max(0, Math.min(Math.max(0, n - win), c - Math.floor(win / 2)));
    const i1 = Math.min(n, i0 + win);
    let sq = 0.0;
    for (let i = i0; i < i1; i++) sq += sig[i] * sig[i];
    const p = sq / Math.max(1, i1 - i0);
    out[b] = 10.0 * Math.log10(p + 1e-9);
  }
  return out;
}

export function compareAcoustic(baseSig, baseR, testSig, testR) {
  const ea = envDbCurve(baseSig);
  const eb = envDbCurve(testSig);
  let sa = 0.0, sb = 0.0;
  for (let i = 0; i < ea.length; i++) { sa += ea[i]; sb += eb[i]; }
  const ma = sa / ea.length, mb = sb / eb.length;
  let num = 0.0, da2 = 0.0, db2 = 0.0, actSum = 0.0, actCnt = 0;
  for (let i = 0; i < ea.length; i++) {
    const xa = ea[i] - ma, xb = eb[i] - mb;
    num += xa * xb;
    da2 += xa * xa;
    db2 += xb * xb;
    if (ea[i] > -50.0 || eb[i] > -50.0) {
      const d = ea[i] - eb[i];
      actSum += d * d;
      actCnt++;
    }
  }
  const da = Math.sqrt(da2) || 1e-12;
  const db = Math.sqrt(db2) || 1e-12;
  const envDiff = actCnt ? Math.sqrt(actSum / actCnt) : 0.0;
  const mbM = hakaru(baseSig, baseR);
  const mtM = hakaru(testSig, testR);
  return {
    env_r: Number((num / (da * db)).toFixed(3)),
    env_diff_db: Number(envDiff.toFixed(2)),
    d_dur_s: Number((mtM.dur_s - mbM.dur_s).toFixed(2)),
    d_band_1k_2k6_db: Number((mtM.band_1k_2k6_db - mbM.band_1k_2k6_db).toFixed(1)),
    d_band_2k6_5k6_db: Number((mtM.band_2k6_5k6_db - mbM.band_2k6_5k6_db).toFixed(1)),
    d_tani_core_db: Number((mtM.tani_core_db - mbM.tani_core_db).toFixed(1)),
    d_tani_tail_db: Number((mtM.tani_tail_db - mbM.tani_tail_db).toFixed(1)),
  };
}

function splitStemAndExt(filePath) {
  const rawExt = path.extname(filePath);
  const ext = rawExt || ".wav";
  const stem = rawExt ? filePath.slice(0, -rawExt.length) : filePath;
  return { stem, ext };
}

function resolveOutPath(argsOut, nTexts, idx, outDir, preset) {
  if (argsOut) {
    if (nTexts === 1) return argsOut;
    const { stem, ext } = splitStemAndExt(argsOut);
    return `${stem}_${idx + 1}${ext}`;
  }
  let seq = 1;
  while (true) {
    const cand = path.join(outDir, `yomu_${String(seq).padStart(3, "0")}_${preset}.wav`);
    if (!fs.existsSync(cand)) return cand;
    seq++;
  }
}

function measureWithHash(samples, rInfo, wavBytes) {
  const sha256_16 = crypto.createHash("sha256").update(wavBytes.subarray(44)).digest("hex").slice(0, 16);
  return Object.assign({ sha256_16 }, hakaru(samples, rInfo));
}

function printHelp() {
  console.log(`Usage: node yomu.mjs [options] [texts...]

一筆彫りTTS 草薙版 (kusanagi) — 1本のホワイトノイズから4手で彫る純JS日本語音声合成

Options:
  -o, --out <path>         出力WAVパス（省略時は out/yomu_NNN_<preset>.wav）
  --preset <name>          プリセット名 (${Object.keys(PRESETS).join(", ")}) [既定: hitofude]
  --list-presets           プリセット一覧を表示して終了
  --measure                合成波形の実測音響指標JSONを表示（LLM自己検証用）
  --compare                基準プリセット (hitofude) との音響指標・包絡差分JSONを同時出力
  --uta <hz,hz,...>        歌モード：カンマ区切り周波数Hz列
  --recipe <json>          レシピJSONを読み込む
  --save-recipe <json>     現在のパラメータをレシピJSONへ保存
  --seed <int>             乱数シード
  --hz <float>             基準ピッチ高さ Hz
  --fscale <float>         フォルマント周波数倍率
  --rate <float>           話速倍率
  --g-vo <float>           有声くびれ深さ G (0.0..0.97)
  --tilt <int>             高域粗削り移動平均幅 w
  --sigh <float>           句末の息抜き量 (0.0..1.0)
  --jitter <float>         周期ジッタ率
  --wander <float>         ピッチ緩徐漂い幅 (半音)
  --damp <float>           コム帰還路の高域減衰 (0.0..0.95、高域に元の息を残す)
  --shin <float>           声門扉と声道の再帰結合度 (0.0=片道4段、0.0<..1.0=2唇粘膜扉×5極声道の再帰低音)
  --character <float>      響の声色・モーラ訛り (0.0..1.0、既存音声は0)
  --edge <float>           響の拍頭アタック (0.0..1.0、既存音声は0)
  --cadence <float>        響の文脈に反応する節回し (0.0..1.0、既存音声は0)
  --closeness <float>      響の句内の存在感 (0.0..1.0、既存音声は0)
  -h, --help               このヘルプを表示`);
}

function dieParam(msg) {
  console.error(`[kusanagi] Invalid parameter: ${msg}`);
  process.exit(2);
}

function main() {
  const { values, positionals } = parseArgs({
    options: {
      out: { type: "string", short: "o" },
      preset: { type: "string", default: "hitofude" },
      "list-presets": { type: "boolean", default: false },
      measure: { type: "boolean", default: false },
      compare: { type: "boolean", default: false },
      uta: { type: "string" },
      recipe: { type: "string" },
      "save-recipe": { type: "string" },
      seed: { type: "string" },
      hz: { type: "string" },
      fscale: { type: "string" },
      rate: { type: "string" },
      "g-vo": { type: "string" },
      tilt: { type: "string" },
      sigh: { type: "string" },
      jitter: { type: "string" },
      wander: { type: "string" },
      damp: { type: "string" },
      shin: { type: "string" },
      character: { type: "string" },
      edge: { type: "string" },
      cadence: { type: "string" },
      closeness: { type: "string" },
      help: { type: "boolean", short: "h", default: false },
    },
    allowPositionals: true,
  });

  if (values.help) {
    printHelp();
    return;
  }

  if (values["list-presets"]) {
    for (const [k, v] of Object.entries(PRESETS)) {
      const knobs = KNOB_KEYS.map((nk) => `${nk}=${v[nk]}`).join(", ");
      console.log(`  ${k.padEnd(9)} : ${v.description}\n              (${knobs})`);
    }
    return;
  }

  if (!PRESETS[values.preset]) {
    console.error(`Unknown --preset '${values.preset}'. Choose from: ${Object.keys(PRESETS).join(", ")}`);
    process.exit(2);
  }

  const prm = Object.assign({}, PRESETS[values.preset]);
  if (values.recipe) {
    Object.assign(prm, JSON.parse(fs.readFileSync(values.recipe, "utf8")));
  }
  const flagMap = {
    seed: "seed", hz: "hz", fscale: "fscale", rate: "rate",
    "g-vo": "g_vo", tilt: "tilt_w", sigh: "sigh", jitter: "jitter", wander: "wander_st",
    damp: "damp", shin: "shin", character: "character", edge: "edge", cadence: "cadence", closeness: "closeness",
  };
  for (const [flag, key] of Object.entries(flagMap)) {
    if (values[flag] !== undefined) {
      const raw = values[flag].trim();
      const num = Number(raw);
      if (!raw || !Number.isFinite(num)) dieParam(`--${flag} expects a finite number, got '${values[flag]}'`);
      prm[key] = num;
    }
  }
  for (const key of KNOB_KEYS) {
    if (!Number.isFinite(Number(prm[key]))) dieParam(`'${key}' must be a finite number, got '${prm[key]}'`);
  }
  if (prm.hz <= 0) dieParam(`hz must be > 0, got ${prm.hz}`);
  if (prm.fscale <= 0) dieParam(`fscale must be > 0, got ${prm.fscale}`);
  if (prm.rate <= 0) dieParam(`rate must be > 0, got ${prm.rate}`);
  if (prm.g_vo < 0 || prm.g_vo >= 1) dieParam(`g_vo must be in [0, 1), got ${prm.g_vo}`);
  if (Math.round(prm.tilt_w) < 1) dieParam(`tilt_w must be >= 1, got ${prm.tilt_w}`);
  if (prm.damp !== undefined && (!Number.isFinite(Number(prm.damp)) || Number(prm.damp) < 0 || Number(prm.damp) >= 1)) {
    dieParam(`damp must be in [0, 1), got ${prm.damp}`);
  }
  if (prm.shin !== undefined && (!Number.isFinite(Number(prm.shin)) || Number(prm.shin) < 0 || Number(prm.shin) > 1)) {
    dieParam(`shin must be in [0, 1], got ${prm.shin}`);
  }

  if (prm.character !== undefined && (!Number.isFinite(Number(prm.character)) || Number(prm.character) < 0 || Number(prm.character) > 1)) {
    dieParam(`character must be in [0, 1], got ${prm.character}`);
  }

  if (prm.edge !== undefined && (!Number.isFinite(Number(prm.edge)) || Number(prm.edge) < 0 || Number(prm.edge) > 1)) {
    dieParam(`edge must be in [0, 1], got ${prm.edge}`);
  }

  if (prm.cadence !== undefined && (!Number.isFinite(Number(prm.cadence)) || Number(prm.cadence) < 0 || Number(prm.cadence) > 1)) {
    dieParam(`cadence must be in [0, 1], got ${prm.cadence}`);
  }

  if (prm.closeness !== undefined && (!Number.isFinite(Number(prm.closeness)) || Number(prm.closeness) < 0 || Number(prm.closeness) > 1)) {
    dieParam(`closeness must be in [0, 1], got ${prm.closeness}`);
  }

  if (values["save-recipe"]) {
    const dst = path.resolve(values["save-recipe"]);
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.writeFileSync(dst, JSON.stringify(prm, null, 2) + "\n");
    console.log(`[kusanagi] Saved recipe -> ${values["save-recipe"]}`);
  }

  let utaHz = null;
  if (values.uta !== undefined) {
    const parts = values.uta.split(",").map((s) => s.trim());
    if (!parts.length || parts.some((s) => !s || !Number.isFinite(Number(s)) || Number(s) <= 0)) {
      dieParam(`--uta expects comma-separated positive numbers, got '${values.uta}'`);
    }
    utaHz = parts.map(Number);
  }
  const texts = positionals.length ? positionals : ["わたし、にほんご、ちょっとしゃべれます"];
  const outDir = path.join(HERE, "out");
  fs.mkdirSync(outDir, { recursive: true });

  for (let idx = 0; idx < texts.length; idx++) {
    const t = texts[idx];
    const t0 = performance.now();
    const { samples, r, moras } = synth(t, prm, utaHz);
    const ms = performance.now() - t0;
    const outPath = resolveOutPath(values.out, texts.length, idx, outDir, values.preset);
    fs.mkdirSync(path.dirname(path.resolve(outPath)), { recursive: true });
    const wavBytes = encodeWav(samples);
    fs.writeFileSync(outPath, wavBytes);
    const mStr = moras.map((m) => m.t || "").join("");
    console.log(`[kusanagi] Saved: ${outPath} (${(samples.length / SR).toFixed(2)}s in ${ms.toFixed(0)}ms, ${moras.length} moras: ${mStr})`);

    if (values.measure) {
      console.log("  [Measure]", JSON.stringify(measureWithHash(samples, r, wavBytes)));
    }
    if (values.compare) {
      const baseRes = synth(t, PRESETS.hitofude, utaHz);
      const { stem, ext } = splitStemAndExt(outPath);
      const basePath = `${stem}_base${ext}`;
      fs.writeFileSync(basePath, encodeWav(baseRes.samples));
      const cmp = Object.assign({ base: basePath }, compareAcoustic(baseRes.samples, baseRes.r, samples, r));
      console.log("  [Compare vs hitofude]", JSON.stringify(cmp));
    }
  }
}

if (path.resolve(process.argv[1] || "") === fileURLToPath(import.meta.url)) {
  main();
}
