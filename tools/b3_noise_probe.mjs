#!/usr/bin/env node
/**
 * B3 noise-contamination probe: Does additive room noise bias Hodoki jitter?
 * The source voice stays exactly identical across all noise conditions.
 * CLI: node tools/b3_noise_probe.mjs --reference stephan_2m --out out/noise_probe
 * Optional: --bed-start 0 --bed-end 1 (only if auditioned as a no-voice reference span).
 */
import fs from "node:fs";
import path from "node:path";
import {parseArgs} from "node:util";
import {encodeWav,SR,makeRng} from "../hitofude.mjs";
import {B3_BASE} from "../b3_akambo.mjs";
import {renderLabCandidate,loadReference} from "./infant_lab.mjs";
import {analyze} from "./b3_soroi.mjs";

const KEYS=["f0_median_hz","jitter_local_pct","shimmer_local_pct","hnr_db","period_corr_median"];
const summary=x=>{
  const s=analyze(x,SR).summary;
  return Object.fromEntries(KEYS.map(k=>[k,Number.isFinite(s[k])?+s[k].toFixed(k==="period_corr_median"?5:2):null]));
};
const rms=x=>Math.sqrt(x.reduce((v,t)=>v+t*t,0)/Math.max(1,x.length));
export function addNoise(voice,{snrDb=Infinity,kind="white",seed=20261120,bed=null}={}){
  if(!["white","low","recorded"].includes(kind))throw new RangeError("noise kind");
  if(!Number.isFinite(seed)||!Number.isInteger(seed))throw new RangeError("seed");
  if(snrDb!==Infinity&&(!Number.isFinite(snrDb)||snrDb<0||snrDb>100))throw new RangeError("SNR");
  // No noise bypass must be bit-identical for a strict control.
  if(snrDb===Infinity)return Float32Array.from(voice);
  if(kind==="recorded"&&(!bed||bed.length<SR/10))throw new RangeError("recorded bed requires >=100ms manually verified no-voice span");
  const rng=makeRng(seed);
  const raw=new Float64Array(voice.length);
  let pole=0;
  for(let i=0;i<raw.length;i++){
    if(kind==="recorded"){
      // Wrap noise sample: potential loop artifacts are an acknowledged limitation.
      raw[i]=bed[i%bed.length];
    }else{
      const white=rng.uniform(-1,1);
      pole+=0.035*(white-pole);
      raw[i]=kind==="low"?pole:white;
    }
  }
  // Use RMS on original synthesized full waveform to keep a reproducible
  // nominal SNR; voice pauses are NOT excluded, so voiced-only SNR is higher.
  const voiceRms=rms(voice),noiseRms=rms(raw);
  if(noiseRms===0)throw new Error("zero-energy noise bed");
  const factor=voiceRms*Math.pow(10,-snrDb/20)/noiseRms;
  const out=new Float32Array(voice.length);
  for(let i=0;i<out.length;i++)out[i]=voice[i]+factor*raw[i];
  return out;
}
export function probe({reference,root=process.cwd(),out="out/b3_noise_probe",
  seed=20261120,text="アー、ウー、ウアー",bedStart=null,bedEnd=null,
  snrs=[Infinity,40,30,25,20,15,10],kinds=["white","low"]}){
  if(!reference||!reference.file)throw Error("reference entry required");
  const ref=loadReference(reference,root);
  const target=summary(ref.x);
  let bed=null;
  if(bedStart!==null||bedEnd!==null){
    if(!Number.isFinite(bedStart)||!Number.isFinite(bedEnd)||bedStart<0||bedEnd<=bedStart)
      throw new RangeError("explicit noise bed requires --bed-start and --bed-end in seconds");
    const full=loadReference({...reference,start_s:bedStart,end_s:bedEnd},root);
    bed=full.x;
    if(bed.length<SR/10)throw Error("too short noise bed");
    kinds=[...kinds,"recorded"];
  }
  fs.mkdirSync(out,{recursive:true});
  const source=renderLabCandidate(text,seed,{
    hz:B3_BASE.hz,combG:.99,rawAirMul:1,clean:B3_BASE.b2_clean,
    jitter:B3_BASE.jitter,cutoffHz:2300,tiltMix:0,airLevel:0
  });
  const clean=summary(source),rows=[];
  fs.writeFileSync(path.join(out,"clean.wav"),encodeWav(source));
  for(const kind of kinds){
    for(const db of snrs){
      if(db===Infinity && kind!=="white")continue;
      const sound=addNoise(source,{snrDb:db,kind,seed:seed+37,bed});
      const metrics=summary(sound);
      const file=db===Infinity?"clean.wav":kind+"_snr"+String(db)+".wav";
      if(db!==Infinity)fs.writeFileSync(path.join(out,file),encodeWav(sound));
      rows.push({kind:db===Infinity?"none":kind,snrDb:db===Infinity?null:db,metrics,
        deltaFromClean:Object.fromEntries(KEYS.map(k=>[k,metrics[k]===null||clean[k]===null?null:+(metrics[k]-clean[k]).toFixed(4)])),
        wav:file});
    }
  }
  const result={schema:1,reference:{id:reference.id,sha256:ref.sourceHash,
    start_s:reference.start_s,end_s:reference.end_s,metrics:target},
    source:{profile:"soroe1",seed,text,metrics:clean,base_jitter:B3_BASE.jitter},
    noiseBed:bed?{start_s:bedStart,end_s:bedEnd,warning:"No-voice segment must be verified by ear"}:null,
    notes:"Nominal SNR is measured across the whole rendered file, including pauses. Measured jitter may change because of Hodoki epoch detection, not actual source cycle timing.",
    rows};
  fs.writeFileSync(path.join(out,"results.json"),JSON.stringify(result,null,2)+"\n");
  console.log(JSON.stringify({reference:result.reference,source:result.source,rows}));
  return result;
}
if(import.meta.url===`file://${process.argv[1]}`){
  const {values:v}=parseArgs({options:{
    manifest:{type:"string",default:"samples/reference/manifest.json"},
    reference:{type:"string",default:"stephan_2m"},
    out:{type:"string",default:"out/b3_noise_probe"},
    seed:{type:"string",default:"20261120"},text:{type:"string",default:"アー、ウー、ウアー"},
    "bed-start":{type:"string"},"bed-end":{type:"string"}
  }});
  const manifest=JSON.parse(fs.readFileSync(v.manifest,"utf8"));
  const entry=manifest.references?.find(x=>x.id===v.reference);
  if(!entry)throw Error("reference id unknown");
  probe({reference:entry,out:v.out,seed:Number(v.seed),text:v.text,
    bedStart:v["bed-start"]===undefined?null:Number(v["bed-start"]),
    bedEnd:v["bed-end"]===undefined?null:Number(v["bed-end"])});
}
