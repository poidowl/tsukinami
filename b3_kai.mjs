// B3改: acoustic-envelope and spectral-shaping experiment.
// Independent post-stage, opt-in only. Doesn't touch the glottal comb, PER, or baby bend.
// No original recording is used in synthesis.
import { SR, makeRng } from "./hitofude.mjs";

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
export const B3_KAI_SETTINGS = Object.freeze({
  attackMs: 46, releaseMs: 105, cutoffHz: 2300,
  tiltMix: 0.72, airLevel: 0.0028, airHpHz: 110,
});

export function b3KaiProcess(samples, { seed = 20261120,
  attackMs = B3_KAI_SETTINGS.attackMs,
  releaseMs = B3_KAI_SETTINGS.releaseMs,
  cutoffHz = B3_KAI_SETTINGS.cutoffHz,
  tiltMix = B3_KAI_SETTINGS.tiltMix,
  airLevel = B3_KAI_SETTINGS.airLevel,
  airHpHz = B3_KAI_SETTINGS.airHpHz } = {}) {
  for (const n of [seed, attackMs, releaseMs, cutoffHz, tiltMix, airLevel, airHpHz])
    if (!Number.isFinite(n)) throw new RangeError("B3 kai parameters must be finite");
  if (attackMs < 0 || attackMs > 500 || releaseMs < 0 || releaseMs > 800 ||
      cutoffHz < 100 || cutoffHz > 15000 || tiltMix < 0 || tiltMix > 1 ||
      airLevel < 0 || airLevel > 0.03 || airHpHz < 5 || airHpHz > 4000)
    throw new RangeError("B3 kai parameter out of range");
  const n = samples.length, dst = new Float32Array(n);
  if (!n) return dst;
  // Quantify the activity in small frames: threshold is relative to the recording's
  // own 96th-percentile envelope; no absolute voice-level assumption.
  const hop = Math.max(1, Math.round(0.005 * SR));
  const count = Math.ceil(n / hop), energy = new Float64Array(count);
  let maxE = 0;
  for (let k = 0; k < count; k++) {
    const a = k * hop, b = Math.min(n, a + hop);
    let sum = 0;
    for (let i = a; i < b; i++) sum += samples[i] * samples[i];
    const e = Math.sqrt(sum / Math.max(1, b - a));
    energy[k] = e;
    if (e > maxE) maxE = e;
  }
  // Only real voiced material creates an activity gate; ambient audio is created separately.
  const gate = new Float64Array(count);
  const threshold = maxE * 0.035;
  let activity = 0;
  const aAtk = attackMs === 0 ? 0 : Math.exp(-hop / (attackMs * 0.001 * SR));
  const aRel = releaseMs === 0 ? 0 : Math.exp(-hop / (releaseMs * 0.001 * SR));
  for (let k = 0; k < count; k++) {
    const active = energy[k] > threshold ? 1 : 0;
    const coeff = active > activity ? aAtk : aRel;
    activity = coeff * activity + (1 - coeff) * active;
    gate[k] = activity;
  }
  const alpha = 1 - Math.exp(-2 * Math.PI * cutoffHz / SR);
  const airAlpha = 1 - Math.exp(-2 * Math.PI * airHpHz / SR);
  const rng = makeRng(seed + 103);
  let lp = 0, airLp = 0;
  for (let i = 0; i < n; i++) {
    lp += alpha * (samples[i] - lp);
    const timbre = (1 - tiltMix) * samples[i] + tiltMix * lp;
    const frame = Math.min(count - 1, Math.floor(i / hop));
    // interpolate across frame boundaries; ensure gate changes remain smooth
    const frac = (i % hop) / hop;
    const g = gate[frame] * (1 - frac) + gate[Math.min(count - 1, frame + 1)] * frac;
    const white = rng.uniform(-1, 1);
    airLp += airAlpha * (white - airLp);
    const air = white - airLp; // gentle high-pass: remove infrasonic drift
    const amb = airLevel * air * (0.35 + 0.65 * (1 - g));
    dst[i] = clamp(timbre * g + amb, -0.98, 0.98);
  }
  return dst;
}
