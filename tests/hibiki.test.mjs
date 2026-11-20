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
  for (const key of ["hibiki", "hibiki_awa", "hibiki_kiba"]) {
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
