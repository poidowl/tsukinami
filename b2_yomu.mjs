#!/usr/bin/env node
// node b2_yomu.mjs [--seed N] [--phrases N] [--mode coo|babble] [--profile cycle|tuned|legacy] [--body 0..1] [--breaks 0..1] [--clean 0..1] [--cycle 0..1] [--out path] [--text カナ]
import fs from "node:fs";
import { resolve } from "node:path";
import { parseArgs } from "node:util";
import { renderB2, encodeWav, SR } from "./b2_akambo.mjs";
const { values } = parseArgs({ options: {
  seed: { type: "string", default: "20261120" },
  phrases: { type: "string", default: "4" },
  body: { type: "string" },
  breaks: { type: "string" },
  clean: { type: "string" },
  cycle: { type: "string" },
  profile: { type: "string", default: "cycle" },
  mode: { type: "string", default: "coo" },
  out: { type: "string", default: "b2_akambo.wav" },
  text: { type: "string" },
}});
const seed = Number(values.seed), phrases = Number(values.phrases);
const body = values.body === undefined ? undefined : Number(values.body);
const breaks = values.breaks === undefined ? undefined : Number(values.breaks);
const clean = values.clean === undefined ? undefined : Number(values.clean);
const cycle = values.cycle === undefined ? undefined : Number(values.cycle);
if (!Number.isFinite(seed) || !Number.isInteger(phrases) || (body !== undefined && !Number.isFinite(body)) || (breaks !== undefined && !Number.isFinite(breaks)) || (clean !== undefined && !Number.isFinite(clean)) || (cycle !== undefined && !Number.isFinite(cycle))) throw new RangeError("invalid numeric option");
const result = renderB2({ seed, phrases, mode: values.mode, profile: values.profile, body, breaks, clean, cycle, text: values.text });
const target = resolve(values.out);
fs.writeFileSync(target, encodeWav(result.samples));
console.log(JSON.stringify({ series: "B2", kana: result.text, seconds: +(result.samples.length / SR).toFixed(2), path: target }));
