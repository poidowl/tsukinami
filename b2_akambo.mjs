// B2 — ナマの喃語: 呼吸・声帯・声道の結合実験。
// VシリーズとB1を変更しない。録音・ライブラリ・新規ノイズ線は使わない。
import { makeHitofude, makeRng, encodeWav, SR } from "./hitofude.mjs";
import { b1Babble, B1_PRESET } from "./b1_akambo.mjs";

export const B2_PRESET = Object.freeze({
  ...B1_PRESET,
  hz: 390, fscale: 1.31, rate: 1.62, g_vo: 0.83, damp: 0.23,
  tilt_w: 6, sigh: 0.64, jitter: 0.018, wander_st: 0.36,
  baby: 0.68, b2_body: 0.88, b2_breaks: 0.72,
});
// 生後2か月前後の「クーイング」を狙う: 正規のCV音節より、母音の探りを重視。
// バババ期の喃語は --mode babble で別途生成できる。
const COO_NUCLEI = ["アー", "ウー", "ウアー", "アウー", "オー", "エー", "アアー", "ウエー"];
export function b2Coo(seed = B2_PRESET.seed, phrases = 4) {
  if (!Number.isInteger(phrases) || phrases < 1 || phrases > 32) throw new RangeError("phrases must be 1..32");
  const rng = makeRng(seed);
  const result = [];
  for (let i = 0; i < phrases; i++) {
    const count = rng.random() < 0.66 ? 1 : 2;
    let phrase = "";
    for (let j = 0; j < count; j++) phrase += COO_NUCLEI[Math.floor(rng.random() * COO_NUCLEI.length)];
    result.push(phrase);
  }
  return result.join("、");
}
export function renderB2({ seed = B2_PRESET.seed, phrases = 4, text = null,
  mode = "coo", body = B2_PRESET.b2_body, breaks = B2_PRESET.b2_breaks } = {}) {
  if (!Number.isFinite(seed) || !Number.isFinite(body) || body < 0 || body > 1 ||
      !Number.isFinite(breaks) || breaks < 0 || breaks > 1)
    throw new RangeError("invalid B2 seed/body/breaks");
  if (mode !== "coo" && mode !== "babble") throw new RangeError("mode must be coo or babble");
  const kana = text == null ? (mode === "coo" ? b2Coo(seed, phrases) : b1Babble(seed, phrases)) : String(text);
  return { text: kana, ...makeHitofude(kana, { ...B2_PRESET, seed, b2_body: body, b2_breaks: breaks }) };
}
export { encodeWav, SR };
