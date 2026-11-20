#!/usr/bin/env node
// node b1_yomu.mjs [--seed N] [--phrases N] [--baby 0..1] [--out path] [--text カナ]
import fs from "node:fs";
import { parseArgs } from "node:util";
import { resolve } from "node:path";
import { renderB1, encodeWav, SR } from "./b1_akambo.mjs";

const { values } = parseArgs({ options: {
  seed: { type: "string", default: "20261120" },
  phrases: { type: "string", default: "4" },
  baby: { type: "string", default: "0.78" },
  out: { type: "string", default: "b1_akambo.wav" },
  text: { type: "string" },
}});
const seed = Number(values.seed), phrases = Number(values.phrases), baby = Number(values.baby);
if (!Number.isFinite(seed) || !Number.isInteger(phrases) || !Number.isFinite(baby)) {
  throw new RangeError("seed / phrases / baby must be finite numbers");
}
const r = renderB1({ seed, phrases, baby, text: values.text });
const path = resolve(values.out);
fs.writeFileSync(path, encodeWav(r.samples));
console.log(JSON.stringify({ series: "B1", kana: r.text, seconds: +(r.samples.length / SR).toFixed(2), path }));
