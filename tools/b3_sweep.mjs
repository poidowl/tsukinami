#!/usr/bin/env node
// B3 parameter sweep, preserving the Hodoki soroi algorithm and baby bend.
// Usage: node tools/b3_sweep.mjs reference.wav
import fs from "node:fs";
import {analyze,readWav} from "./b3_soroi.mjs";
import {makeHitofude} from "../hitofude.mjs";
import {B3_BASE} from "../b3_akambo.mjs";
const ref=process.argv[2];if(!ref)throw Error("reference WAV argument required");
const wav=readWav(fs.readFileSync(ref));
if(wav.sr!==44100)throw Error("reference must be 44.1 kHz");
const metrics=(x,sr)=>{const m=analyze(x,sr).summary;
 return {f0:m.f0_median_hz,jitter:m.jitter_local_pct,shimmer:m.shimmer_local_pct,
  hnr:m.hnr_db,corr:m.period_corr_median}};
const target=metrics(wav.x,wav.sr),rows=[];
const text="アー、ウー、ウアー",seed=42;
for(const hz of [300,320,340,351]){
 for(const jitter of [0.018,0.027,0.04,0.055]){
  for(const combo of [{combG:0.99,rawAirMul:1},{combG:0.985,rawAirMul:0.6}]){
    // Sweep the glottal model without changing baby bend or the text.
    const samples=makeHitofude(text,{...B3_BASE,seed,hz,jitter,...{
      b3_combG:combo.combG,b3_rawAirMul:combo.rawAirMul
    }}).samples;
    const m=metrics(samples,44100);
    const score=Math.pow((m.f0-target.f0)/18,2)+Math.pow((m.jitter-target.jitter)/1.5,2)+
      Math.pow((m.shimmer-target.shimmer)/3,2)+Math.pow((m.hnr-target.hnr)/4,2)+
      Math.pow((m.corr-target.corr)/0.025,2);
    rows.push({hz,jitter,combG:combo.combG,rawAirMul:combo.rawAirMul,
      ...Object.fromEntries(Object.entries(m).map(([k,v])=>["measured_"+k,+v.toFixed(k==="corr"?4:2)])),
      score:+score.toFixed(3)});
  }
 }
}
rows.sort((a,b)=>a.score-b.score);
console.log("REFERENCE "+JSON.stringify(target));
for(const r of rows.slice(0,12))console.log("B3_CANDIDATE "+JSON.stringify(r));
