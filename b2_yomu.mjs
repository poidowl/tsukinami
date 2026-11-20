#!/usr/bin/env node
// node b2_yomu.mjs [--seed N] [--phrases N] [--mode coo|babble] [--body 0..1] [--breaks 0..1] [--out path] [--text カナ]
import fs from "node:fs";
import { resolve } from "node:path";
import { parseArgs } from "node:util";
import { renderB2, encodeWav, SR } from "./b2_akambo.mjs";
const { values } = parseArgs({ options: {
  seed: { type: "string", default: "20261120" },
  phrases: { type: "string", default: "4" },
  body: { type: "string", default: "0.88" },
  breaks: { type: "string", default: "0.72" },
  mode: { type: "string", default: "coo" },
  out: { type: "string", default: "b2_akambo.wav" },
  text: { type: "string" },
}});
const seed = Number(values.seed), phrases = Number(values.phrases), body = Number(values.body), breaks = Number(values.breaks);
if (!Number.isFinite(seed) || !Number.isInteger(phrases) || !Number.isFinite(body) || !Number.isFinite(breaks)) throw new RangeError("invalid numeric option");
const result = renderB2({ seed, phrases, mode: values.mode, body, breaks, text: values.text });
const target = resolve(values.out);
fs.writeFileSync(target, encodeWav(result.samples));
console.log(JSON.stringify({ series: "B2", kana: result.text, seconds: +(result.samples.length / SR).toFixed(2), path: target }));
