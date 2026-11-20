// B1 — アカンボシミュレータ / 乳児喃語の独立実験シリーズ。
// 録音・別ノイズ・外部ライブラリなし。Vシリーズのパラメータは変更しない。
import { makeHitofude, makeRng, encodeWav, SR } from "./hitofude.mjs";

export const B1_PRESET = Object.freeze({
  seed: 20261120, hz: 440, fscale: 1.38, rate: 1.52,
  g_vo: 0.79, damp: 0.19, shin: 1.0, tilt_w: 5,
  sigh: 0.57, jitter: 0.013, wander_st: 0.42,
  baby: 0.78, character: 0, cadence: 0, gesture: 0,
});

const SYLLABLES = ["ア", "ウ", "エ", "オ", "マ", "バ", "パ", "ム", "ブ", "ナ", "ワ", "ヤ"];
const STARTERS = ["ア", "ウ", "マ", "バ", "ン"];
export function b1Babble(seed = B1_PRESET.seed, phrases = 4) {
  if (!Number.isInteger(phrases) || phrases < 1 || phrases > 32) throw new RangeError("phrases must be an integer 1..32");
  const rng = makeRng(seed);
  const out = [];
  for (let p = 0; p < phrases; p++) {
    const count = 2 + Math.floor(rng.random() * 4);
    let phrase = STARTERS[Math.floor(rng.random() * STARTERS.length)];
    for (let i = 1; i < count; i++) {
      // 同じ音節の反復を許す。「ババ」「ママ」は偶然の試行として起きる。
      const syllable = rng.random() < 0.34 ? phrase.slice(-1) : SYLLABLES[Math.floor(rng.random() * SYLLABLES.length)];
      phrase += syllable;
    }
    out.push(phrase);
  }
  return out.join("、");
}

export function renderB1({ seed = B1_PRESET.seed, phrases = 4, text = null, baby = B1_PRESET.baby } = {}) {
  if (!Number.isFinite(seed) || !Number.isFinite(baby) || baby < 0 || baby > 1) throw new RangeError("invalid seed or baby intensity");
  const kana = text == null ? b1Babble(seed, phrases) : String(text);
  const result = makeHitofude(kana, { ...B1_PRESET, seed, baby });
  return { text: kana, ...result };
}

export { encodeWav, SR };
