#!/usr/bin/env node
/**
 * B-series reference lab: generate, measure, rank, and package reproducible variants.
 * node tools/infant_lab.mjs --manifest samples/reference/manifest.json --reference stephan_2m --out out/infant_lab --budget 18
 * Add local WAV or OGG recordings to the manifest; never use a recording as a synthesis source.
 * ffmpeg is required for OGG or for WAV with non-44.1kHz sample rate.
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import {spawnSync} from "node:child_process";
import {parseArgs} from "node:util";
import {makeHitofude,encodeWav,SR} from "../hitofude.mjs";
import {B3_BASE} from "../b3_akambo.mjs";
import {B3_KAI_SETTINGS,b3KaiProcess} from "../b3_kai.mjs";
import {analyze,readWav} from "./b3_soroi.mjs";
const FIELDS=["f0_median_hz","jitter_local_pct","shimmer_local_pct","hnr_db","period_corr_median"];
const WEIGHTS={f0_median_hz:18,jitter_local_pct:1.25,shimmer_local_pct:3.5,hnr_db:5,period_corr_median:0.02};
const metrics=(x,sr)=>{const s=analyze(x,sr).summary;return Object.fromEntries(FIELDS.map(k=>[k,s[k]]));};
const finite=(m)=>FIELDS.every(k=>Number.isFinite(m[k]));
const cut=(m)=>Object.fromEntries(FIELDS.map(k=>[k,Number.isFinite(m[k])?+m[k].toFixed(k==="period_corr_median"?5:2):null]));
const score=(x,y)=>FIELDS.reduce((acc,k)=>acc+Math.pow((x[k]-y[k])/WEIGHTS[k],2),0);
export function loadReference(entry,root){
  if(typeof entry.file!=="string" || !entry.file.trim())throw Error("reference file path missing");
  const full=path.resolve(root,entry.file);
  if(!fs.existsSync(full))throw Error("reference missing: "+full);
  const start=entry.start_s??0,end=entry.end_s??null;
  if(!Number.isFinite(start)||start<0||end!==null&&(!Number.isFinite(end)||end<=start))throw Error("invalid reference selection");
  const bytes=fs.readFileSync(full);
  const sourceHash=crypto.createHash("sha256").update(bytes).digest("hex");
  let wav;
  if(path.extname(full).toLowerCase()===".wav"){
    const got=readWav(bytes);
    if(got.sr===SR)return {x:got.x.subarray(Math.round(start*SR),end==null?got.x.length:Math.round(end*SR)),sourceHash};
  }
  const args=["-nostdin","-hide_banner","-loglevel","error","-i",full,"-vn","-ac","1","-ar",String(SR),"-f","wav","-acodec","pcm_s16le","pipe:1"];
  // ffmpeg cannot be assumed available: report how to install it rather than fabricate a measurement.
  const res=spawnSync("ffmpeg",args,{maxBuffer:64*1024*1024,encoding:null});
  if(res.error)throw Error("ffmpeg required for OGG or non-44.1kHz WAV: "+res.error.message);
  if(res.status!==0)throw Error("ffmpeg failed: "+String(res.stderr));
  wav=readWav(res.stdout);
  return {x:wav.x.subarray(Math.round(start*SR),end==null?wav.x.length:Math.round(end*SR)),sourceHash};
}
function uniqueCandidates(items,budget){
  const seen=new Set(),output=[];
  for(const p of items){
    // Only waveform-affecting knobs are compared; duplicate combinations
    // with different labels still consume exactly one synthesis budget slot.
    const key=JSON.stringify([p.hz,p.combG,p.rawAirMul,p.clean,p.jitter,
      p.jitterCorr??null,p.cutoffHz,p.tiltMix,p.airLevel]);
    if(seen.has(key))continue;
    seen.add(key);
    output.push({...p,id:"v"+String(output.length).padStart(3,"0")});
    if(output.length>=budget)break;
  }
  return output;
}
export function chooseCandidates(budget=24, referenceF0=350, sweep="grid"){
  if(!Number.isInteger(budget)||budget<1||budget>512)throw RangeError("budget must be 1..512");
  if(!["grid","jitter","correlated"].includes(sweep))throw RangeError("sweep must be grid, jitter or correlated");
  // Deterministic anchors, then round-robin stratified sweeps across pitch bands.
  const targetHz = Math.max(200,Math.min(700,referenceF0*0.95));
  const presets=[
   {hz:351,combG:.99,rawAirMul:1,clean:B3_BASE.b2_clean,jitter:.018,cutoffHz:2300,tiltMix:0,airLevel:0},
   {hz:351,combG:.99,rawAirMul:1,clean:B3_BASE.b2_clean,jitter:.018,cutoffHz:2300,tiltMix:.72,airLevel:.0028},
   {hz:targetHz,combG:.99,rawAirMul:1,clean:B3_BASE.b2_clean,jitter:.018,cutoffHz:2300,tiltMix:0,airLevel:0},
   {hz:targetHz,combG:.99,rawAirMul:1,clean:B3_BASE.b2_clean,jitter:.018,cutoffHz:2300,tiltMix:.72,airLevel:.0028},
  ];
  if(sweep==="correlated"){
    // Compare the SAME underlying soroe1 source with independently controlled
    // jitter amplitude and correlation, including the unmodified legacy anchor.
    const levels=[.018,.03,.05,.08,.12];
    const correlations=[0,.5,.85,.95];
    // Interleave timing magnitude and correlation from the start.
    for(const tiltMix of [0,.72])
      for(const hz of [351,targetHz])
        for(const jitter of levels)
          for(const corr of correlations)
            presets.push({hz,combG:.99,rawAirMul:1,clean:B3_BASE.b2_clean,
              jitter,jitterCorr:corr,cutoffHz:2300,tiltMix,airLevel:tiltMix?.0028:0});
    return uniqueCandidates(presets,budget);
  }
  if(sweep==="jitter"){
    // Cross jitter with a fixed, small set of source/timbre knobs. Alternate jitter
    // levels early, rather than exhausting one jitter value before trying the next.
    const levels=[.018,.022,.03,.04,.05];
    const banks=levels.map(jitter=>{
      const variants=[];
      for(const hz of [351,targetHz])
        for(const combG of [.99,.985])
          for(const rawAirMul of [1,.4])
            for(const tiltMix of [0,.72])
              variants.push({hz,combG,rawAirMul,clean:B3_BASE.b2_clean,jitter,
                cutoffHz:2300,tiltMix,airLevel:tiltMix?.0028:0});
      return variants;
    });
    for(let i=0;i<banks[0].length;i++)
      for(let j=0;j<banks.length;j++)
        presets.push(banks[j][(i+j*3)%banks[j].length]);
    return uniqueCandidates(presets,budget);
  }
  const bands=[targetHz*0.88,targetHz,targetHz*1.10];
  const buckets=bands.map(hz=>{
    const bucket=[];
    for(const combG of [.985,.99,.995])
      for(const rawAirMul of [.4,.6,1])
        for(const jitter of [.014,.018,.022])
          for(const tiltMix of [0,.55])
            bucket.push({hz,combG,rawAirMul,clean:B3_BASE.b2_clean,jitter,
              cutoffHz:2400,tiltMix,airLevel:tiltMix?.0015:0});
    return bucket;
  });
  // Interleave pitch bands and vary initial positions in the other dimensions.
  const stride=17; // coprime to each 54-entry band
  for(let i=0;i<buckets[0].length;i++)
    for(let k=0;k<buckets.length;k++)
      presets.push(buckets[k][(i+k*stride)%buckets[k].length]);
  return uniqueCandidates(presets,budget);
}
export function renderLabCandidate(text,seed,opts){
  const base=makeHitofude(text,{...B3_BASE,seed,hz:opts.hz,jitter:opts.jitter,
    b3_combG:opts.combG,b3_rawAirMul:opts.rawAirMul,b2_clean:opts.clean,
    b3_jitter_corr:opts.jitterCorr??null});
  if(opts.tiltMix===0 && opts.airLevel===0)return base.samples;
  return b3KaiProcess(base.samples,{...B3_KAI_SETTINGS,seed,tiltMix:opts.tiltMix,
    cutoffHz:opts.cutoffHz,airLevel:opts.airLevel});
}
export function evaluate(manifest,referenceId,{out="out/infant_lab",budget=24,seed=20261120,text="アー、ウー、ウアー",root=process.cwd(),sweep="grid"}={}){
  const reference=manifest.references?.find(r=>r.id===referenceId);
  if(!reference)throw Error("reference id not found: "+referenceId);
  if(!Number.isFinite(seed)||!Number.isInteger(seed))throw Error("seed must be an integer");
  if(!text||typeof text!=="string")throw Error("text must be nonempty");
  const src=loadReference(reference,root);
  if(src.x.length<SR/4)throw Error("reference selection too short");
  const target=metrics(src.x,SR);
  if(!finite(target))throw Error("no reliable voiced cycles in reference window; choose a vocal segment");
  fs.mkdirSync(out,{recursive:true});
  const rows=[];
  for(const opts of chooseCandidates(budget,target.f0_median_hz,sweep)){
    const samples=renderLabCandidate(text,seed,opts), m=metrics(samples,SR);
    const item={id:opts.id,params:opts,metrics:cut(m),
      score:finite(m)?+score(m,target).toFixed(4):null,
      wav:opts.id+".wav"};
    if(!finite(m))item.warning="Hodoki could not find reliable cycles";
    fs.writeFileSync(path.join(out,item.wav),encodeWav(samples));
    rows.push(item);
  }
  rows.sort((a,b)=>(a.score??Infinity)-(b.score??Infinity));
  const report={schema:1,reference:{id:reference.id,file:reference.file,
      sha256:src.sourceHash,start_s:reference.start_s??0,end_s:reference.end_s??null,metrics:cut(target)},
    settings:{seed,text,budget,sweep,candidates:rows.length,scoring:"weighted squared distance; screen only, not perceptual proof",weights:WEIGHTS},
    ranked:rows};
  fs.writeFileSync(path.join(out,"results.json"),JSON.stringify(report,null,2)+"\n");
  let txt="# B-series reference-fit report\n\n";
  txt+="Reference: `"+reference.id+"` (SHA256 `"+src.sourceHash+"`).\n\n";
  txt+="Target: `"+JSON.stringify(cut(target))+"`.\n\n";
  txt+="| Rank | WAV | score | F0 | jitter | shimmer | HNR | corr |\n|---:|---|---:|---:|---:|---:|---:|---:|\n";
  for(let i=0;i<Math.min(20,rows.length);i++){const e=rows[i],m=e.metrics;
    txt+=`| ${i+1} | \`${e.wav}\` | ${e.score??"n/a"} | ${m.f0_median_hz} | ${m.jitter_local_pct} | ${m.shimmer_local_pct} | ${m.hnr_db} | ${m.period_corr_median} |\n`;
  }
  txt+="\n## Feedback to kusanagi (proposal only)\n\n";
  if(rows.length&&rows[0].score!==null){
    const best=rows[0];
    txt+="Best measured candidate: `"+best.id+"` — `"+JSON.stringify(best.params)+"`.\n\n";
    txt+="Promote only after A/B listening, at least three seeds, and voiced onset/high-harmonic checks.\n\n";
  }
  txt+="Potential portable engine knobs: `combG` and `rawAirMul`; these are opt-in in hibiki.\n";
  txt+="Do NOT copy baby pitch bend, infant fscale, ambient noise, or postprocessing into kusanagi by default.\n";
  txt+="This file does not change kusanagi. Different words and reference lengths are confounders.\n";
  fs.writeFileSync(path.join(out,"PROMOTION.md"),txt);
  return report;
}
if(import.meta.url===`file://${process.argv[1]}`){
 const {values:v}=parseArgs({options:{manifest:{type:"string",default:"samples/reference/manifest.json"},
  reference:{type:"string",default:"stephan_2m"},out:{type:"string",default:"out/infant_lab"},
  budget:{type:"string",default:"24"},sweep:{type:"string",default:"grid"},seed:{type:"string",default:"20261120"},
  text:{type:"string",default:"アー、ウー、ウアー"}}});
 const file=path.resolve(v.manifest),manifest=JSON.parse(fs.readFileSync(file,"utf8"));
 const result=evaluate(manifest,v.reference,{out:path.resolve(v.out),root:process.cwd(),
    budget:Number(v.budget),sweep:v.sweep,seed:Number(v.seed),text:v.text});
 console.log(JSON.stringify({reference:result.reference.id,metrics:result.reference.metrics,
   best:result.ranked.slice(0,3).map(x=>({id:x.id,score:x.score,metrics:x.metrics,params:x.params})),
   output:path.resolve(v.out)}));
}
