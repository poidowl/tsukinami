#!/usr/bin/env node
// B3 reproducible Hodoki soroi measurement. Input WAVs must have same sample rate;
// the GitHub workflow converts the OGG original to 44100 Hz mono before calling this.
import fs from "node:fs";
import {readWav, analyze} from "./b3_soroi.mjs";

const paths=process.argv.slice(2);
if(paths.length===0)throw new Error("usage: node tools/b3_measure.mjs reference.wav output.wav ...");
const target={f0_median_hz:349,jitter_local_pct:2.18,shimmer_local_pct:5.70,hnr_db:16.16,period_corr_median:0.991};
let ref=null;
for(const p of paths){
  const {sr,x}=readWav(fs.readFileSync(p));
  const s=analyze(x,sr).summary;
  const picked=Object.fromEntries(Object.keys(target).map(k=>[k,Number.isFinite(s[k])?+s[k].toFixed(k==="period_corr_median"?4:2):null]));
  if(!ref)ref=picked;
  const diffs=Object.fromEntries(Object.keys(target).map(k=>[k,picked[k]===null||ref[k]===null?null:+(picked[k]-ref[k]).toFixed(3)]));
  console.log(JSON.stringify({file:p,sample_rate:sr,voiced_s:+s.voiced_s.toFixed(2),periods:s.periods,metrics:picked,diff_vs_ref:diffs}));
}
