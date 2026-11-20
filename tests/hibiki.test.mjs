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
