#!/usr/bin/env node
// B3 - sample-fidelity development CLI; no third-party dependencies.
import fs from "node:fs";
import {resolve} from "node:path";
import {parseArgs} from "node:util";
import {renderB3, encodeWav, SR} from "./b3_akambo.mjs";
const {values:v}=parseArgs({options:{
  seed:{type:"string",default:"20261120"},phrases:{type:"string",default:"4"},
  text:{type:"string"},mode:{type:"string",default:"coo"},
  profile:{type:"string",default:"soroe1"},
  jitter:{type:"string"},combG:{type:"string"},rawAirMul:{type:"string"},bend:{type:"string"},
  out:{type:"string",default:"b3_akambo.wav"},
}});
const opts={seed:Number(v.seed),phrases:Number(v.phrases),text:v.text,
  mode:v.mode,profile:v.profile};
for(const name of ["jitter","combG","rawAirMul","bend"]){
 if(v[name]!==undefined)opts[name]=Number(v[name]);
}
if(!Number.isInteger(opts.phrases)||opts.phrases<1||opts.phrases>32)throw new RangeError("phrases: 1..32");
const res=renderB3(opts), file=resolve(v.out);
fs.writeFileSync(file,encodeWav(res.samples));
console.log(JSON.stringify({series:"B3",profile:opts.profile,text:res.text,seconds:+(res.samples.length/SR).toFixed(2),file}));
