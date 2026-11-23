// xray/engine.mjs — カワイイクサナギ変態音響X線スイート 150ツール統合エンジン（純JS・0依存・無循環）
import { decodeWav, extractBaseFrameData } from "./core.mjs";
import { CAT01_TOOLS } from "./cat01_glottal.mjs";
import { CAT02_TOOLS } from "./cat02_artifacts.mjs";
import { CAT03_TOOLS } from "./cat03_vocal_tract.mjs";
import { CAT04_TOOLS } from "./cat04_phase.mjs";
import { CAT05_TOOLS } from "./cat05_prosody.mjs";
import { CAT06_TOOLS } from "./cat06_breath.mjs";
import { CAT07_TOOLS } from "./cat07_consonants.mjs";
import { CAT08_TOOLS } from "./cat08_psycho.mjs";
import { CAT09_TOOLS } from "./cat09_composite.mjs";
import { CAT10_TOOLS } from "./cat10_visual.mjs";
import { CAT11_TOOLS } from "./cat11_felony.mjs";
import { CAT12_TOOLS } from "./cat12_babaa.mjs";
import { CAT13_TOOLS } from "./cat13_audit.mjs";

export const ALL_TOOLS = [
  ...CAT01_TOOLS,
  ...CAT02_TOOLS,
  ...CAT03_TOOLS,
  ...CAT04_TOOLS,
  ...CAT05_TOOLS,
  ...CAT06_TOOLS,
  ...CAT07_TOOLS,
  ...CAT08_TOOLS,
  ...CAT09_TOOLS,
  ...CAT10_TOOLS,
  ...CAT11_TOOLS,
  ...CAT12_TOOLS,
  ...CAT13_TOOLS,
];

export function analyzeBuffer(bytes, ref = null, refMetrics = null) {
  const { sr, samples } = decodeWav(bytes);
  const d = extractBaseFrameData(sr, samples);
  const metrics = {};
  const visuals = {};
  const ctx = { metrics, visuals, ref, refMetrics, totalTools: ALL_TOOLS.length };
  for (const tool of ALL_TOOLS) metrics[tool.key] = tool.run(d, ctx);
  return { d, metrics, visuals };
}
