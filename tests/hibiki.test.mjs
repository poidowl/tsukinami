import test from "node:test";
import assert from "node:assert/strict";
import { makeHitofude, PRESETS } from "../hitofude.mjs";

const phrase = "あさのひかり、ゆめのかけら";
const render = (p) => makeHitofude(phrase, p).samples;
const hashish = (a) => {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < a.length; i += 113) {
    const v = Math.round(a[i] * 32767);
    h = Math.imul(h ^ v, 16777619) >>> 0;
  }
  return h >>> 0;
};
test("hibiki variations render finite non-silent deterministic audio", () => {
  for (const key of ["hibiki", "hibiki_awa", "hibiki_kiba", "hibiki_katari", "hibiki_yorisoi", "hibiki_natsuku", "hibiki_ibuki"]) {
    const a = render(PRESETS[key]), b = render(PRESETS[key]);
    assert.equal(a.length, b.length);
    assert.ok(a.length > 44100);
    assert.ok(a.some((v) => Math.abs(v) > 0.01), key + " is silent");
    assert.ok(a.every(Number.isFinite), key + " contains NaN or Infinity");
    assert.equal(hashish(a), hashish(b), key + " is non-deterministic");
  }
});
test("character and edge change the rendered waveform", () => {
  const p = PRESETS.hibiki_kiba;
  const a = render(p);
  const b = render({ ...p, character: 0, edge: 0 });
  const c = render({ ...p, edge: 0 });
  assert.notEqual(hashish(a), hashish(b));
  assert.notEqual(hashish(a), hashish(c));
});
test("zero character and edge preserve legacy settings", () => {
  const p = PRESETS.alto;
  assert.equal(hashish(render(p)), hashish(render({ ...p, character: 0, edge: 0 })));
});

test("cadence responds to phonetic context, stays deterministic and is disabled in singing", () => {
  const p = PRESETS.hibiki_katari;
  const spoken = makeHitofude("あいあい、ああああ", p);
  const neutral = makeHitofude("あいあい、ああああ", { ...p, cadence: 0 });
  assert.notEqual(hashish(spoken.samples), hashish(neutral.samples));
  const repeat = makeHitofude("あいあい、ああああ", p);
  assert.equal(hashish(spoken.samples), hashish(repeat.samples));
  const sung = makeHitofude("あいうえお", { ...p, uta_hz: [300, 320, 340, 360, 380] });
  const sungNeutral = makeHitofude("あいうえお", { ...p, cadence: 0, uta_hz: [300, 320, 340, 360, 380] });
  assert.equal(hashish(sung.samples), hashish(sungNeutral.samples));
});
test("cadence zero is fully backward-compatible", () => {
  const p = PRESETS.hibiki;
  assert.equal(hashish(render(p)), hashish(render({ ...p, cadence: 0 })));
});

test("closeness changes voice but zero retains bit-identical audio", () => {
  const p = PRESETS.hibiki_yorisoi;
  assert.notEqual(hashish(render(p)), hashish(render({ ...p, closeness: 0 })));
  const base = PRESETS.hibiki_katari;
  assert.equal(hashish(render(base)), hashish(render({ ...base, closeness: 0 })));
});

test("signature changes contextual timbre and 0 preserves old voices", () => {
  const p = PRESETS.hibiki_natsuku;
  assert.notEqual(hashish(render(p)), hashish(render({ ...p, signature: 0 })));
  const b = PRESETS.hibiki_yorisoi;
  assert.equal(hashish(render(b)), hashish(render({ ...b, signature: 0 })));
});
test("single vowel and repeated-vowel utterances remain finite", () => {
  for (const txt of ["あ", "あああああ", "あ、い、う、え、お", "きゃきゅきょ、らりるれろ"]) {
    const samples = makeHitofude(txt, PRESETS.hibiki_natsuku).samples;
    assert.ok(samples.length > 0);
    assert.ok(samples.every(Number.isFinite), txt);
  }
});

test("gesture changes non-singing sound but never overrides sung notes", () => {
  const p = PRESETS.hibiki_ibuki;
  assert.notEqual(hashish(render(p)), hashish(render({ ...p, gesture: 0 })));
  const sung = { ...p, uta_hz: [290, 300, 310, 320, 330] };
  const a = makeHitofude("あいうえお", sung).samples;
  const b = makeHitofude("あいうえお", { ...sung, gesture: 0 }).samples;
  assert.equal(hashish(a), hashish(b));
});
test("old voice with gesture 0 is unchanged", () => {
  const p = PRESETS.hibiki_natsuku;
  assert.equal(hashish(render(p)), hashish(render({ ...p, gesture: 0 })));
});

test("B1 babble repeats deterministically and differs by seed", async () => {
  const { b1Babble, renderB1 } = await import("../b1_akambo.mjs");
  assert.equal(b1Babble(103, 8), b1Babble(103, 8));
  assert.notEqual(b1Babble(103, 8), b1Babble(104, 8));
  const a = renderB1({ seed: 103, phrases: 3 });
  const b = renderB1({ seed: 103, phrases: 3 });
  assert.equal(hashish(a.samples), hashish(b.samples));
  assert.ok(a.samples.every(Number.isFinite));
  assert.ok(a.samples.some(x => Math.abs(x) > 0.005));
});
test("B1 baby articulation is isolated from legacy V audio", async () => {
  const { renderB1 } = await import("../b1_akambo.mjs");
  const withBaby = renderB1({ text: "あー、うー、まま", baby: 0.78 });
  const noBaby = renderB1({ text: "あー、うー、まま", baby: 0 });
  assert.notEqual(hashish(withBaby.samples), hashish(noBaby.samples));
  const old = PRESETS.hibiki_ibuki;
  assert.equal(hashish(render(old)), hashish(render({ ...old, baby: 0 })));
});

test("B2 couples breath and vocal fold; legacy audio stays bit-identical", async () => {
  const { renderB2 } = await import("../b2_akambo.mjs");
  const opts = { seed: 44, text: "あー、うー、まま、ばぶ" };
  const wet = renderB2(opts), dry = renderB2({ ...opts, body: 0 });
  assert.ok(wet.samples.every(Number.isFinite));
  assert.ok(wet.samples.some(x => Math.abs(x) > 0.005));
  assert.notEqual(hashish(wet.samples), hashish(dry.samples));
  assert.equal(hashish(wet.samples), hashish(renderB2(opts).samples));
  const b1 = renderB2({ ...opts, body: 0 });
  assert.equal(hashish(dry.samples), hashish(b1.samples));
  const v = PRESETS.hibiki_ibuki;
  assert.equal(hashish(render(v)), hashish(render({ ...v, b2_body: 0 })));
});

test("B2 cooing differs from canonical babbling, stable and bounded", async () => {
  const { b2Coo, renderB2 } = await import("../b2_akambo.mjs");
  assert.equal(b2Coo(47, 5), b2Coo(47, 5));
  assert.notEqual(b2Coo(47, 5), b2Coo(48, 5));
  assert.ok(!/[バマパ]/.test(b2Coo(47, 8)));
  const coo = renderB2({ seed: 47, phrases: 3 });
  const babble = renderB2({ seed: 47, phrases: 3, mode: "babble" });
  assert.notEqual(coo.text, babble.text);
  assert.ok(coo.samples.every(Number.isFinite));
  const withBreaks = renderB2({ seed: 47, text: "アー、ウー、アウー" });
  const noBreaks = renderB2({ seed: 47, text: "アー、ウー、アウー", breaks: 0 });
  assert.notEqual(hashish(withBreaks.samples), hashish(noBreaks.samples));
  assert.equal(hashish(withBreaks.samples), hashish(renderB2({ seed: 47, text: "アー、ウー、アウー" }).samples));
  assert.throws(() => renderB2({ mode: "bad" }), RangeError);
  assert.throws(() => renderB2({ breaks: 1.1 }), RangeError);
  const v = PRESETS.hibiki_ibuki;
  assert.equal(hashish(render(v)), hashish(render({ ...v, b2_body: 0, b2_breaks: 0 })));
});

test("B2 reference-led clean preset remains reversible to B2 legacy", async () => {
  const { renderB2, B2_PRESET, B2_LEGACY } = await import("../b2_akambo.mjs");
  const opts = { seed: 42, text: "アー、ウー、ウアー" };
  const tuned = renderB2(opts), old = renderB2({ ...opts, profile: "legacy" });
  assert.notEqual(hashish(tuned.samples), hashish(old.samples));
  assert.equal(hashish(old.samples), hashish(makeHitofude(opts.text, { ...B2_LEGACY, seed: opts.seed }).samples));
  assert.equal(hashish(tuned.samples), hashish(renderB2(opts).samples));
  assert.ok(tuned.samples.every(Number.isFinite));
  assert.ok(B2_PRESET.hz < B2_LEGACY.hz);
  assert.ok(B2_PRESET.b2_breaks < B2_LEGACY.b2_breaks);
  assert.ok(B2_PRESET.b2_clean > 0);
  assert.throws(() => renderB2({ ...opts, clean: -0.1 }), RangeError);
  const v = PRESETS.hibiki_ibuki;
  assert.equal(hashish(render(v)), hashish(render({ ...v, b2_clean: 0 })));
});

test("B2 cycle levelling isolates shimmer without altering period timing", async () => {
  const { renderB2, B2_TUNED, B2_PRESET } = await import("../b2_akambo.mjs");
  const args = { seed: 42, text: "アー、ウー、ウアー" };
  const latest = renderB2(args);
  const reference = renderB2({ ...args, profile: "tuned" });
  const bypass = renderB2({ ...args, cycle: 0 });
  assert.notEqual(hashish(latest.samples), hashish(reference.samples));
  assert.equal(hashish(reference.samples), hashish(bypass.samples));
  assert.equal(hashish(reference.samples), hashish(makeHitofude(args.text, { ...B2_TUNED, seed: 42 }).samples));
  assert.equal(hashish(latest.samples), hashish(renderB2(args).samples));
  assert.ok(latest.samples.every(Number.isFinite));
  assert.ok(B2_PRESET.b2_cycle > 0);
  assert.throws(() => renderB2({ cycle: 1.01 }), RangeError);
  const v = PRESETS.hibiki_ibuki;
  assert.equal(hashish(render(v)), hashish(render({ ...v, b2_cycle: 0 })));
});

test("B3 soroe parameters modify only B3 and retain baby bend", async () => {
  const {renderB3,B3_BASE,B3_PRESET}=await import("../b3_akambo.mjs");
  const p={seed:42,text:"アー、ウー、ウアー"};
  const s1=renderB3({...p,profile:"soroe1"});
  const s2=renderB3({...p,profile:"soroe2"});
  const cur=renderB3(p);
  assert.ok(s1.samples.every(Number.isFinite));
  assert.ok(cur.samples.some(x=>Math.abs(x)>0.01));
  assert.notEqual(hashish(s1.samples),hashish(s2.samples));
  assert.equal(hashish(cur.samples),hashish(s1.samples));
  assert.equal(hashish(s1.samples),hashish(makeHitofude(p.text,{...B3_BASE,seed:p.seed}).samples));
  assert.equal(hashish(cur.samples),hashish(renderB3(p).samples));
  assert.notEqual(hashish(renderB3({...p,bend:0}).samples),hashish(cur.samples));
  assert.equal(B3_PRESET.b2_cycle,0);
  assert.throws(()=>renderB3({...p,combG:1.1}),RangeError);
  assert.throws(()=>renderB3({...p,jitter:-1}),RangeError);
  assert.equal(hashish(render(PRESETS.hibiki_ibuki)),
    hashish(render({...PRESETS.hibiki_ibuki,b3_combG:null,b3_rawAirMul:1})));
});

test("B3 default remains measured soroe1; kai is experimental opt-in",async()=>{
 const {renderB3,B3_PRESET,B3_JITTER_EXPERIMENT}=await import("../b3_akambo.mjs");
 const opts={seed:42,text:"アー、ウー、ウアー"};
 assert.notEqual(hashish(renderB3(opts).samples),hashish(renderB3({...opts,profile:"kai"}).samples));
 assert.equal(hashish(renderB3(opts).samples),hashish(renderB3({...opts,profile:"soroe1"}).samples));
 assert.notEqual(hashish(renderB3({...opts,profile:"candidate"}).samples),hashish(renderB3(opts).samples));
 assert.equal(B3_PRESET.jitter,0.018);
 assert.equal(B3_JITTER_EXPERIMENT.jitter,0.027);
});

test("B3-kai soft transitions, tilt and low-level gaps; soroe1 bit-identical",async()=>{
  const {renderB3}=await import("../b3_akambo.mjs");
  const opts={text:"アー、ウー、ウアー",seed:42};
  const base=renderB3({...opts,profile:"soroe1"});
  const kai=renderB3({...opts,profile:"kai"});
  const repeat=renderB3({...opts,profile:"kai"});
  assert.equal(hashish(kai.samples),hashish(repeat.samples));
  assert.notEqual(hashish(kai.samples),hashish(base.samples));
  assert.equal(kai.samples.length,base.samples.length);
  assert.ok(kai.samples.every(Number.isFinite));
  // silence is no longer digital zero, but remains low enough to avoid hissing over speech
  const pad=Math.min(10000,Math.floor(kai.samples.length/10));
  let gapEnergy=0;
  for(let i=0;i<pad;i++)gapEnergy+=kai.samples[i]*kai.samples[i];
  assert.ok(gapEnergy>0);
  assert.ok(Math.sqrt(gapEnergy/pad)<0.015);
  // setting the new stage's parameters must not alter the old soroe1 rendering.
  assert.equal(hashish(base.samples),hashish(renderB3({...opts,profile:"soroe1",
    attackMs:100,releaseMs:180,cutoffHz:700,airLevel:0.02}).samples));
  assert.throws(()=>renderB3({...opts,profile:"kai",cutoffHz:1}),RangeError);
});

test("B3 kai starts from exact soroe1 input, not higher-jitter candidate",async()=>{
  const {renderB3}=await import("../b3_akambo.mjs");
  const {b3KaiProcess,B3_KAI_SETTINGS}=await import("../b3_kai.mjs");
  const p={seed:42,text:"アー、ウー、ウアー"};
  const base=renderB3({...p,profile:"soroe1"});
  const kai=renderB3({...p,profile:"kai"});
  const expected=b3KaiProcess(base.samples,{seed:p.seed,...B3_KAI_SETTINGS});
  assert.equal(kai.samples.length,expected.length);
  for(let i=0;i<expected.length;i++)assert.equal(kai.samples[i],expected[i]);
  const wrong=b3KaiProcess(renderB3({...p,profile:"candidate"}).samples,{seed:p.seed,...B3_KAI_SETTINGS});
  assert.notEqual(hashish(kai.samples),hashish(wrong));
});

test("lab baseline retains B3 clean and budget 54 covers three pitch bands",async()=>{
 const {chooseCandidates,renderLabCandidate}=await import("../tools/infant_lab.mjs");
 const {B3_BASE}=await import("../b3_akambo.mjs");
 const candidates=chooseCandidates(54,350);
 assert.equal(candidates.length,54);
 assert.ok(candidates.every(x=>x.clean===B3_BASE.b2_clean));
 assert.equal(candidates[0].clean,0.74);
 const middle=350*.95;
 for(const hz of [middle*.88,middle,middle*1.10])
   assert.ok(candidates.some(x=>Math.abs(x.hz-hz)<1e-6),"pitch band missing "+hz);
 assert.ok(new Set(candidates.map(x=>x.combG)).size>1);
 assert.ok(new Set(candidates.map(x=>x.jitter)).size>1);
 assert.deepEqual(candidates,chooseCandidates(54,350));
 const actual=renderLabCandidate("アー、ウー、ウアー",42,candidates[0]);
 const expected=makeHitofude("アー、ウー、ウアー",{...B3_BASE,seed:42}).samples;
 assert.equal(hashish(actual),hashish(expected));
});

test("jitter sweep spans 0.018–0.05 without changing baseline",async()=>{
 const {chooseCandidates,renderLabCandidate}=await import("../tools/infant_lab.mjs");
 const {B3_BASE}=await import("../b3_akambo.mjs");
 const c=chooseCandidates(54,350,"jitter");
 assert.equal(c.length,54);
 for(const j of [.018,.022,.03,.04,.05])
   assert.ok(c.some(x=>x.jitter===j),"missing jitter "+j);
 assert.ok(c.every(x=>x.clean===B3_BASE.b2_clean));
 assert.equal(c[0].jitter,.018);
 const base=renderLabCandidate("アー、ウー、ウアー",42,c[0]);
 assert.equal(hashish(base),hashish(makeHitofude("アー、ウー、ウアー",{...B3_BASE,seed:42}).samples));
 assert.ok(new Set(c.map(x=>x.hz)).size>=2);
 assert.throws(()=>chooseCandidates(54,350,"invalid"),RangeError);
});

test("lab sweep removes duplicate waveforms and exposes correlated period timing",async()=>{
 const {chooseCandidates,renderLabCandidate}=await import("../tools/infant_lab.mjs");
 const makeKey=x=>JSON.stringify([x.hz,x.combG,x.rawAirMul,x.clean,x.jitter,
   x.jitterCorr??null,x.cutoffHz,x.tiltMix,x.airLevel]);
 for(const sweep of ["grid","jitter","correlated"]){
   const bank=chooseCandidates(54,368.9,sweep);
   assert.equal(new Set(bank.map(makeKey)).size,bank.length,
     "duplicate candidate in "+sweep);
   assert.equal(bank.length,54);
 }
 const c=chooseCandidates(54,368.9,"correlated");
 for(const rho of [0,.5,.85,.95])
   assert.ok(c.some(x=>x.jitterCorr===rho),"missing corr "+rho);
 for(const amp of [.018,.03,.05,.08,.12])
   assert.ok(c.some(x=>x.jitter===amp),"missing amplitude "+amp);
 assert.equal(c[0].jitterCorr,undefined);
 const x=renderLabCandidate("アー、ウー、ウアー",42,c.find(x=>x.jitterCorr===.95));
 const b=renderLabCandidate("アー、ウー、ウアー",42,c[0]);
 assert.ok(x.every(Number.isFinite));
 assert.notEqual(hashish(x),hashish(b));
});
