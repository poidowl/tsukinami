// B2 — ナマの喃語: 呼吸・声帯・声道の結合実験。
// VシリーズとB1を変更しない。録音・ライブラリ・新規ノイズ線は使わない。
import { makeHitofude, encodeWav, SR } from "./hitofude.mjs";
import { b1Babble, B1_PRESET } from "./b1_akambo.mjs";

export const B2_PRESET = Object.freeze({
  ...B1_PRESET,
  hz: 390, fscale: 1.31, rate: 1.62, g_vo: 0.83, damp: 0.23,
  tilt_w: 6, sigh: 0.64, jitter: 0.018, wander_st: 0.36,
  baby: 0.68, b2_body: 0.88,
});
export function renderB2({ seed = B2_PRESET.seed, phrases = 4, text = null, body = B2_PRESET.b2_body } = {}) {
  if (!Number.isFinite(seed) || !Number.isFinite(body) || body < 0 || body > 1)
    throw new RangeError("invalid B2 seed/body");
  const kana = text == null ? b1Babble(seed, phrases) : String(text);
  return { text: kana, ...makeHitofude(kana, { ...B2_PRESET, seed, b2_body: body }) };
}
export { encodeWav, SR };
