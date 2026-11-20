// B3 — Infant fidelity experiment. Hodoki soroe corrections applied to B2 tuned.
// Completely separate from V, B1 and B2. No restrictions on future implementation.
import { makeHitofude, encodeWav, SR } from "./hitofude.mjs";
import { B2_TUNED, b2Coo } from "./b2_akambo.mjs";
import { b1Babble } from "./b1_akambo.mjs";
import { b3KaiProcess, B3_KAI_SETTINGS } from "./b3_kai.mjs";

export const B3_BASE = Object.freeze({
  ...B2_TUNED, b2_cycle: 0,
  // Measured B2 tuned + soroe1: f0 348 Hz, jitter 1.36%, shimmer 8.1%, HNR 14.4 dB, corr .983.
  b3_combG: 0.99, b3_rawAirMul: 1,
});
// The extra jitter is an experimental hypothesis; exact impact must be measured.
export const B3_PRESET = Object.freeze({ ...B3_BASE });
export const B3_JITTER_EXPERIMENT = Object.freeze({ ...B3_BASE, jitter: 0.027 });
export const B3_SOROE2 = Object.freeze({ ...B3_BASE, b3_combG: 0.985, b3_rawAirMul: 0.6 });
export const B3_KAI = Object.freeze({ ...B3_PRESET, ...B3_KAI_SETTINGS });

export function renderB3({ seed = B3_PRESET.seed, phrases = 4, text = null,
  mode = "coo", profile = "soroe1", jitter = undefined,
  combG = undefined, rawAirMul = undefined, bend = undefined,
  attackMs = undefined, releaseMs = undefined, cutoffHz = undefined,
  tiltMix = undefined, airLevel = undefined } = {}) {
  if (!["kai", "candidate", "soroe1", "soroe2"].includes(profile)) throw new RangeError("invalid B3 profile");
  if (!["coo", "babble"].includes(mode)) throw new RangeError("invalid B3 mode");
  const preset = profile === "soroe1" ? B3_PRESET : profile === "soroe2" ? B3_SOROE2 : B3_JITTER_EXPERIMENT;
  const j = jitter ?? preset.jitter;
  const comb = combG ?? preset.b3_combG, air = rawAirMul ?? preset.b3_rawAirMul;
  const bendAmount = bend ?? preset.baby;
  if (![seed,j,comb,air,bendAmount].every(Number.isFinite) || j<0 || j>0.2 ||
    comb<0 || comb>0.9995 || air<0 || air>2 || bendAmount<0 || bendAmount>1)
    throw new RangeError("B3 synthesis parameter out of range");
  const kana = text == null ? (mode === "coo" ? b2Coo(seed,phrases) : b1Babble(seed,phrases)) : String(text);
  const source = makeHitofude(kana,{
    ...preset, seed, jitter:j, b3_combG:comb, b3_rawAirMul:air, baby:bendAmount,
  });
  if (profile !== "kai") return {text:kana, ...source};
  const samples = b3KaiProcess(source.samples, {
    seed, attackMs:attackMs ?? B3_KAI_SETTINGS.attackMs,
    releaseMs:releaseMs ?? B3_KAI_SETTINGS.releaseMs,
    cutoffHz:cutoffHz ?? B3_KAI_SETTINGS.cutoffHz,
    tiltMix:tiltMix ?? B3_KAI_SETTINGS.tiltMix,
    airLevel:airLevel ?? B3_KAI_SETTINGS.airLevel,
  });
  return {text:kana, ...source, samples};
}
export {encodeWav,SR};
