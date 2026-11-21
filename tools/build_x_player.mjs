// build_x_player.mjs — Builds kusanagi_player.html + kusanagi.html directly from ../hitofude.mjs
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = process.argv[2] ? path.resolve(process.argv[2]) : path.join(HERE, "..", "out");
fs.mkdirSync(OUT_DIR, { recursive: true });

let engineSrc = fs.readFileSync(path.join(HERE, "..", "hitofude.mjs"), "utf8");
// Strip ES module 'export ' keywords for self-contained inline IIFE execution
engineSrc = engineSrc.replace(/^export\s+(const|function)\s+/gm, "$1 ");

// Light whitespace/comment compaction for the inline engine (keeps readable structure, trims verbose comments)
const compactEngine = engineSrc
  .split("\n")
  .map((line) => line.replace(/\s+$/, ""))
  .filter((line) => {
    const t = line.trim();
    return t !== "" && !t.startsWith("//");
  })
  .join("\n");

const PAGES_BASE = "https://poidowl.github.io/tsukinami";

const playerHtml = `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="robots" content="noindex">
<link rel="canonical" href="${PAGES_BASE}/kusanagi.html">
<title>草薙 kusanagi — Pure JS Single-Wire Subtractive TTS Player</title>
<style>
  :root {
    --bg: #0b111b;
    --panel: #121b29;
    --panel-hi: #182436;
    --border: #253449;
    --text: #f3efe6;
    --muted: #8fa0b5;
    --amber: #f59e0b;
    --amber-hi: #fbbf24;
    --emerald: #26cc9b;
    --emerald-dim: rgba(38, 204, 155, 0.16);
    --amber-dim: rgba(245, 158, 11, 0.16);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    width: 100%;
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", sans-serif;
    font-size: 13px;
    line-height: 1.35;
    overflow-x: hidden;
    overflow-y: auto;
    -webkit-font-smoothing: antialiased;
  }
  .app {
    max-width: 520px;
    min-height: 100%;
    margin: 0 auto;
    padding: 9px 10px 10px;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    flex-wrap: wrap;
  }
  .brand {
    display: flex;
    align-items: baseline;
    gap: 6px;
    min-width: 0;
  }
  .brand h1 {
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.02em;
    color: var(--text);
    white-space: nowrap;
  }
  .brand .sub {
    font-size: 11px;
    color: var(--amber);
    font-weight: 600;
    white-space: nowrap;
  }
  .top-links {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
  }
  .pill-stat {
    padding: 2px 7px;
    border-radius: 999px;
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .gh-link {
    color: var(--emerald);
    text-decoration: none;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 6px;
    border: 1px solid rgba(38, 204, 155, 0.35);
    white-space: nowrap;
  }
  .gh-link:hover { background: var(--emerald-dim); }

  /* Input + Main Play CTA */
  .input-row {
    display: flex;
    gap: 6px;
    align-items: stretch;
  }
  .kana-input {
    flex: 1 1 140px;
    min-width: 0;
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 9px;
    font-size: 13px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.15s;
  }
  .kana-input:focus { border-color: var(--emerald); }
  .play-btn {
    flex: 0 0 auto;
    background: var(--amber);
    color: #0b111b;
    border: none;
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 800;
    font-family: inherit;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    white-space: nowrap;
    transition: transform 0.08s, background 0.15s;
  }
  .play-btn:hover { background: var(--amber-hi); }
  .play-btn:active { transform: scale(0.97); }
  .play-btn.playing {
    background: var(--emerald);
    color: #07120f;
  }

  /* 5-Step Subtractive Selector */
  .steps-box {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 6px 7px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .steps-row {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr)) auto;
    gap: 4px;
    align-items: center;
  }
  .step-btn {
    background: var(--bg);
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 3px;
    font-size: 11.5px;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transition: background 0.12s, color 0.12s, border-color 0.12s;
  }
  .step-btn:hover { color: var(--text); border-color: #3a5070; }
  .step-btn.active {
    background: var(--emerald-dim);
    color: var(--emerald);
    border-color: var(--emerald);
  }
  .tour-btn {
    background: var(--amber-dim);
    color: var(--amber-hi);
    border: 1px solid rgba(245, 158, 11, 0.45);
    border-radius: 6px;
    padding: 5px 7px;
    font-size: 11px;
    font-weight: 800;
    font-family: inherit;
    cursor: pointer;
    white-space: nowrap;
  }
  .tour-btn:hover { background: rgba(245, 158, 11, 0.26); }
  .tour-btn.running {
    background: var(--amber);
    color: #0b111b;
  }
  .step-desc {
    font-size: 11px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    gap: 6px;
    align-items: center;
    min-height: 16px;
  }
  .step-desc strong { color: var(--text); font-weight: 700; }

  /* Dual Waveform + FFT Canvas */
  .scope-wrap {
    position: relative;
    background: #080d15;
    border: 1px solid var(--border);
    border-radius: 9px;
    height: 108px;
    overflow: hidden;
  }
  #scope {
    width: 100%;
    height: 100%;
    display: block;
    cursor: pointer;
  }
  .scope-labels {
    position: absolute;
    top: 5px;
    left: 8px;
    right: 8px;
    display: flex;
    justify-content: space-between;
    pointer-events: none;
    font-size: 10px;
    color: rgba(143, 160, 181, 0.85);
    font-variant-numeric: tabular-nums;
  }

  /* Presets */
  .presets-row {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .preset-btn {
    flex: 1 1 auto;
    background: var(--panel);
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 6px;
    font-size: 11.5px;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    white-space: nowrap;
    text-align: center;
  }
  .preset-btn:hover { color: var(--text); border-color: #3a5070; }
  .preset-btn.active {
    background: var(--panel-hi);
    color: var(--amber-hi);
    border-color: var(--amber);
  }

  /* 3 Orthogonal Knobs */
  .knobs {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 9px;
    padding: 6px 9px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .knob-row {
    display: grid;
    grid-template-columns: 88px 1fr 48px;
    align-items: center;
    gap: 7px;
    font-size: 11.5px;
  }
  .knob-label {
    color: var(--muted);
    white-space: nowrap;
    font-weight: 600;
  }
  .knob-val {
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--text);
    font-weight: 700;
    font-size: 11.5px;
  }
  input[type="range"] {
    width: 100%;
    height: 16px;
    accent-color: var(--emerald);
    cursor: pointer;
    background: transparent;
  }

  /* Footer: hakaru telemetry + re-seed */
  .footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    flex-wrap: wrap;
    font-size: 10.5px;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
  .seed-btn {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 7px;
    font-size: 10.5px;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    white-space: nowrap;
  }
  .seed-btn:hover { border-color: var(--emerald); color: var(--emerald); }

  /* Narrow X column / mobile card down to 245px */
  @media (max-width: 350px) {
    .app { padding: 7px; gap: 6px; }
    .brand .sub { display: none; }
    .input-row { flex-direction: column; }
    .play-btn { justify-content: center; width: 100%; padding: 7px; }
    .steps-row { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .scope-wrap { height: 88px; }
    .knob-row { grid-template-columns: 72px 1fr 42px; gap: 4px; font-size: 11px; }
  }
</style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <div class="brand">
      <h1>草薙 kusanagi</h1>
      <span class="sub">純JS・1本の乱数から4手で声を彫る</span>
    </div>
    <div class="top-links">
      <span class="pill-stat" id="perfBadge">録音 0B · 準備中</span>
      <a class="gh-link" href="https://github.com/poidowl/tsukinami/tree/kusanagi" target="_blank" rel="noopener noreferrer">GitHub ↗</a>
    </div>
  </header>

  <div class="input-row">
    <input id="kanaInput" class="kana-input" type="text" maxlength="48" spellcheck="false" autocomplete="off"
      value="わたし、にほんご、ちょっとしゃべれます" aria-label="読み上げるかなテキスト">
    <button id="playBtn" class="play-btn" type="button">▶ 彫って鳴らす</button>
  </div>

  <section class="steps-box" aria-label="4段階の引き算ステップ">
    <div class="steps-row">
      <button class="step-btn" type="button" data-step="0">0 原石</button>
      <button class="step-btn" type="button" data-step="1">① 谷</button>
      <button class="step-btn" type="button" data-step="2">② 角</button>
      <button class="step-btn" type="button" data-step="3">③ 山</button>
      <button class="step-btn active" type="button" data-step="4">④ 完成</button>
      <button id="tourBtn" class="tour-btn" type="button" title="0原石→①→②→③→④完成を順に聴き比べ">0→④順聴</button>
    </div>
    <div class="step-desc" id="stepDesc">
      <span><strong>④ 完成：</strong>整音＋時間包絡（句末で同じ1本線の吐息へほどける）</span>
    </div>
  </section>

  <div class="scope-wrap" id="scopeWrap" title="クリックで現在のステップを再生">
    <canvas id="scope"></canvas>
    <div class="scope-labels">
      <span id="waveLabel">波形 (1本のノイズ線 x)</span>
      <span id="specLabel">スペクトル 0–5.5kHz</span>
    </div>
  </div>

  <div class="presets-row" id="presetsRow">
    <button class="preset-btn active" type="button" data-preset="toiki">吐息</button>
    <button class="preset-btn" type="button" data-preset="hitofude">澄み</button>
    <button class="preset-btn" type="button" data-preset="alto">アルト</button>
    <button class="preset-btn" type="button" data-preset="sasayaki">囁き</button>
    <button class="preset-btn" type="button" data-preset="chibi">ちびっ子</button>
    <button class="preset-btn" type="button" data-preset="ossan">おっさん</button>
    <button class="preset-btn" type="button" data-preset="robot">ロボ</button>
    <button class="preset-btn" type="button" data-preset="uta">♪歌</button>
  </div>

  <section class="knobs" aria-label="音響パラメータ">
    <div class="knob-row">
      <span class="knob-label">高さ hz</span>
      <input id="slHz" type="range" min="85" max="450" step="1" value="292">
      <span class="knob-val" id="valHz">292Hz</span>
    </div>
    <div class="knob-row">
      <span class="knob-label">くびれ g_vo</span>
      <input id="slGvo" type="range" min="0" max="0.96" step="0.01" value="0.89">
      <span class="knob-val" id="valGvo">0.89</span>
    </div>
    <div class="knob-row">
      <span class="knob-label">句末吐息 sigh</span>
      <input id="slSigh" type="range" min="0" max="1" step="0.02" value="0.42">
      <span class="knob-val" id="valSigh">0.42</span>
    </div>
  </section>

  <footer class="footer">
    <span id="hakaruLine">計測待機中…</span>
    <button id="seedBtn" class="seed-btn" type="button">🎲 別原石 (seed: 2024)</button>
  </footer>
</div>

<script>
(() => {
"use strict";
${compactEngine}

const STEP_META = [
  ["0 原石：", "uniform(-1, 1) の生ホワイトノイズ1本（揺らぎもジッタもこの1本から）"],
  ["① 倍音の谷：", "2段コムで倍音の隙間の谷を引く（冷凍ロボ用の片道 shin=0）"],
  ["② 角落とし：", "低域DC濁りと高域の角を引く（子音は鋭く残す）"],
  ["③ 声道の山：", "F1–F4 因果直列カスケード＋唇放射で母音、因果2極バンドパスで子音の山を残す"],
  ["④ 完成：", "1スカラー整音＋包絡"],
];
const STEP_META_COUPLED = [
  ["0 原石：", "uniform(-1, 1) の生ホワイトノイズ1本（呼気圧もジッタもこの1本から）"],
  ["① 声帯波：", "声道からの帰還圧を受けながら2段コム＋高域dampで揺れる滑らかな声帯組織波"],
  ["② 非対称扉：", "上唇は丸く開き、下唇はベルヌーイ吸い寄せ×粘膜ソフトクッションでフランジャーなく呼気流を刻む"],
  ["③ 5極声道：", "扉と再帰結合した F1–F5 粘膜声道＋唇微分放射と、明瞭な子音・ハ行帯の響き"],
  ["④ 完成：", "1スカラー整音＋包絡（句末で扉を緩め、元のノイズの吐息へ戻す）"],
];

const DEFAULT_TEXT = "わたし、にほんご、ちょっとしゃべれます";
const OSSAN_TEXT = "こんばんは、いいよるですね";
const UTA_TEXT = "わたしのなまえは、つきなみです";
const BUILTIN_TEXTS = new Set([DEFAULT_TEXT, OSSAN_TEXT, UTA_TEXT]);

const UTA_MELODY = [294, 330, 349, 392, 440, 392, 330, 294, 330, 349, 392, 349, 330, 294];

const elInput = document.getElementById("kanaInput");
const elPlay = document.getElementById("playBtn");
const elTour = document.getElementById("tourBtn");
const elDesc = document.getElementById("stepDesc");
const elPerf = document.getElementById("perfBadge");
const elHakaru = document.getElementById("hakaruLine");
const elSeed = document.getElementById("seedBtn");
const elScope = document.getElementById("scope");
const elWaveLbl = document.getElementById("waveLabel");
const slHz = document.getElementById("slHz");
const slGvo = document.getElementById("slGvo");
const slSigh = document.getElementById("slSigh");
const valHz = document.getElementById("valHz");
const valGvo = document.getElementById("valGvo");
const valSigh = document.getElementById("valSigh");
const stepBtns = Array.from(document.querySelectorAll(".step-btn"));
const presetBtns = Array.from(document.querySelectorAll(".preset-btn"));

let curPreset = "toiki";
let curStep = 4;
let curSeed = 2024;
let isUta = false;
let cachedKey = "";
let cachedRes = null;
let cachedSpecDb = [null, null, null, null, null];

let audioCtx = null;
let analyser = null;
let activeNodes = [];
let tourTimers = [];
let isTouring = false;
let playStartCtxTime = 0;
let playDurSec = 0;
let playRangeStart = 0;
let playRangeSpan = 1;
let rafId = 0;

function getOpts() {
  const base = PRESETS[curPreset] || PRESETS.toiki;
  const hz = Number(slHz.value);
  const g_vo = Number(slGvo.value);
  const sigh = Number(slSigh.value);
  return {
    seed: curSeed,
    hz,
    fscale: base.fscale,
    rate: base.rate,
    g_vo,
    tilt_w: base.tilt_w,
    sigh: isUta ? 0.0 : sigh,
    jitter: base.jitter,
    wander_st: base.wander_st,
    damp: base.damp ?? 0.30,
    shin: base.shin ?? 1.0,
    ...("pau_iki" in base ? { pau_iki: base.pau_iki } : {}),
    uta_hz: isUta ? UTA_MELODY : null,
    captureSteps: true,
  };
}

function updateKnobLabels() {
  valHz.textContent = slHz.value + "Hz";
  valGvo.textContent = Number(slGvo.value).toFixed(2);
  valSigh.textContent = isUta ? "歌OFF" : Number(slSigh.value).toFixed(2);
}

function computeStaticSpec(samples, rInfo) {
  const N = samples.length, nf = 2048, hb = (nf >> 1) + 1;
  const fpz = FP / 1000.0;
  const voiced = rInfo.voiced || [];
  const win = new Float64Array(nf);
  for (let k = 0; k < nf; k++) win[k] = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * k) / nf);
  const acc = new Float64Array(hb);
  let frames = 0;
  for (let s0 = 0; s0 <= N - nf; s0 += nf) {
    const tc = Math.trunc(((s0 + (nf >> 1)) / SR) / fpz);
    if (!voiced.length || (tc >= 0 && tc < voiced.length && voiced[tc])) {
      const buf = new Float64Array(nf);
      for (let k = 0; k < nf; k++) buf[k] = samples[s0 + k] * win[k];
      const { re, im } = fftRadix2(buf);
      for (let k = 0; k < hb; k++) acc[k] += re[k] * re[k] + im[k] * im[k];
      frames++;
    }
  }
  if (!frames && N > 0) {
    const buf = new Float64Array(nf);
    const end = Math.min(nf, N);
    for (let k = 0; k < end; k++) buf[k] = samples[k] * win[k];
    const { re, im } = fftRadix2(buf);
    for (let k = 0; k < hb; k++) acc[k] += re[k] * re[k] + im[k] * im[k];
    frames = 1;
  }
  const db = new Float32Array(hb);
  let mx = -120;
  for (let k = 1; k < hb; k++) {
    db[k] = 10 * Math.log10((acc[k] / (frames || 1)) + 1e-18);
    if (db[k] > mx) mx = db[k];
  }
  for (let k = 1; k < hb; k++) db[k] -= mx; // 0 dB peak normalized
  db[0] = -60;
  return db;
}

function ensureCarved() {
  const rawText = (elInput.value || "").trim().slice(0, 48) || "あ";
  const opts = getOpts();
  const key = JSON.stringify([rawText, opts]);
  if (key === cachedKey && cachedRes) return cachedRes;

  const t0 = performance.now();
  const res = makeHitofude(rawText, opts);
  const dt = Math.round(performance.now() - t0);
  const hk = hakaru(res.samples, res.r);
  cachedRes = res;
  cachedKey = key;
  cachedSpecDb = [null, null, null, null, null];

  elPerf.textContent = "合成 " + dt + "ms · " + hk.dur_s.toFixed(2) + "s";
  elHakaru.textContent =
    "谷(核→末): " + hk.tani_core_db.toFixed(1) + "→" + hk.tani_tail_db.toFixed(1) +
    "dB · 1–2.6k: " + hk.band_1k_2k6_db.toFixed(1) + "dB";
  return res;
}

function setStepUI(stepIdx) {
  curStep = stepIdx;
  stepBtns.forEach((b, i) => b.classList.toggle("active", i === stepIdx));
  const isCoupled = ((PRESETS[curPreset] && PRESETS[curPreset].shin) ?? 1.0) > 0;
  const [title, body] = (isCoupled ? STEP_META_COUPLED : STEP_META)[stepIdx];
  elDesc.innerHTML = "<span><strong>" + title + "</strong>" + body + "</span>";
  const shortNames = isCoupled
    ? ["0 原石ノイズ", "① 声帯組織波", "② 非対称2唇扉", "③ 5極声道", "④ 完成波形"]
    : ["0 原石ノイズ", "① 倍音の谷", "② 角落とし", "③ 声道の山", "④ 完成波形"];
  elWaveLbl.textContent = shortNames[stepIdx];
  drawScope(-1);
}

function stopPlayback() {
  while (tourTimers.length) clearTimeout(tourTimers.pop());
  isTouring = false;
  elTour.classList.remove("running");
  elTour.textContent = "0→④順聴";
  while (activeNodes.length) {
    const src = activeNodes.pop();
    try { src.onended = null; src.stop(); src.disconnect(); } catch (_) {}
  }
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
  elPlay.classList.remove("playing");
  elPlay.textContent = "▶ 彫って鳴らす";
  playDurSec = 0;
  drawScope(-1);
}

async function ensureAudio() {
  if (!audioCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx({ sampleRate: SR });
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.65;
    analyser.connect(audioCtx.destination);
  }
  if (audioCtx.state !== "running") {
    try { await audioCtx.resume(); } catch (_) {}
  }
}

function spokenSampleBounds(res) {
  const N = res.samples.length;
  const ms = res.r && res.r.moras ? res.r.moras : [];
  if (!ms.length) return [0, N];
  const s0 = Math.max(0, Math.min(N - 1, Math.trunc(Math.max(0, ms[0].a - 0.05) * SR)));
  const s1 = Math.max(s0 + 1, Math.min(N, Math.trunc((ms[ms.length - 1].e + 0.08) * SR)));
  return [s0, s1];
}

async function playCurrentStep(stepIdx) {
  stopPlayback();
  setStepUI(stepIdx);
  await ensureAudio();
  const res = ensureCarved();
  const arr = res.steps ? res.steps[stepIdx] : res.samples;
  if (!arr || !arr.length) return;

  const [s0] = spokenSampleBounds(res);
  const offSec = s0 / SR;

  const buf = audioCtx.createBuffer(1, arr.length, SR);
  buf.getChannelData(0).set(arr);
  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(analyser);
  activeNodes.push(src);

  playStartCtxTime = audioCtx.currentTime;
  playDurSec = Math.max(0.01, (arr.length - s0) / SR);
  playRangeStart = s0 / arr.length;
  playRangeSpan = 1 - playRangeStart;
  elPlay.classList.add("playing");
  elPlay.textContent = "■ 停止";

  src.onended = () => {
    if (activeNodes.includes(src)) {
      stopPlayback();
    }
  };
  src.start(0, offSec);
  startAnimLoop();
}

async function playStepTour() {
  if (isTouring) { stopPlayback(); return; }
  stopPlayback();
  await ensureAudio();
  const res = ensureCarved();
  if (!res.steps || !res.samples.length) return;

  isTouring = true;
  elTour.classList.add("running");
  elTour.textContent = "■ 順聴中";
  elPlay.classList.add("playing");
  elPlay.textContent = "■ 停止";

  // Play the full spoken span [first mora .. last mora] across all 5 steps (0 -> ① -> ② -> ③ -> ④)
  const N = res.samples.length;
  const [sStart, sEnd] = spokenSampleBounds(res);
  const sLen = sEnd - sStart;
  const fade = Math.min(530, Math.floor(sLen / 8));

  let offsetSec = 0.02;
  const now = audioCtx.currentTime;

  for (let st = 0; st < 5; st++) {
    const full = res.steps[st];
    const seg = full.slice(sStart, sEnd);
    if (st < 4 && fade > 1) {
      for (let i = 0; i < fade; i++) {
        const w = i / fade;
        seg[i] *= w;
        seg[seg.length - 1 - i] *= w;
      }
    }
    const dur = seg.length / SR;
    const buf = audioCtx.createBuffer(1, seg.length, SR);
    buf.getChannelData(0).set(seg);
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(analyser);
    activeNodes.push(src);
    src.start(now + offsetSec);

    const fireMs = Math.max(0, Math.round(offsetSec * 1000));
    const stepCopy = st;
    const durCopy = dur;
    tourTimers.push(setTimeout(() => {
      if (!isTouring) return;
      playStartCtxTime = audioCtx.currentTime;
      playDurSec = durCopy;
      playRangeStart = sStart / N;
      playRangeSpan = sLen / N;
      setStepUI(stepCopy);
    }, fireMs));

    if (st === 4) {
      src.onended = () => { if (isTouring) stopPlayback(); };
    }
    offsetSec += dur + 0.14;
  }
  startAnimLoop();
}

function startAnimLoop() {
  if (rafId) cancelAnimationFrame(rafId);
  const tick = () => {
    if (!audioCtx || !playDurSec) { rafId = 0; return; }
    const localProg = Math.min(1, Math.max(0, (audioCtx.currentTime - playStartCtxTime) / playDurSec));
    drawScope(playRangeStart + localProg * playRangeSpan);
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}

const liveFreqBuf = new Float32Array(1024);

function drawScope(progress) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = elScope.clientWidth || 460;
  const h = elScope.clientHeight || 108;
  if (elScope.width !== Math.round(w * dpr) || elScope.height !== Math.round(h * dpr)) {
    elScope.width = Math.round(w * dpr);
    elScope.height = Math.round(h * dpr);
  }
  const ctx = elScope.getContext("2d");
  ctx.save();
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const midX = Math.floor(w * 0.50);
  // Subtle divider
  ctx.strokeStyle = "#1d2a3d";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(midX, 0);
  ctx.lineTo(midX, h);
  ctx.stroke();

  if (!cachedRes) { ctx.restore(); return; }
  const arr = cachedRes.steps ? cachedRes.steps[curStep] : cachedRes.samples;
  const N = arr.length;

  // Left half: Waveform envelope
  const padTop = 18, padBot = 8;
  const cy = padTop + (h - padTop - padBot) * 0.5;
  const amp = (h - padTop - padBot) * 0.48;
  const cols = Math.max(20, midX - 12);
  const x0 = 6;

  ctx.strokeStyle = curStep === 0 ? "#8fa0b5" : (curStep < 4 ? "#38bdf8" : "#26cc9b");
  ctx.lineWidth = 1.15;
  ctx.beginPath();
  for (let c = 0; c < cols; c++) {
    const a = Math.trunc((c * N) / cols);
    const b = Math.max(a + 1, Math.trunc(((c + 1) * N) / cols));
    let mn = 0, mx = 0;
    const stride = Math.max(1, Math.trunc((b - a) / 24));
    for (let i = a; i < b; i += stride) {
      const v = arr[i];
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    }
    ctx.moveTo(x0 + c + 0.5, cy - mx * amp);
    ctx.lineTo(x0 + c + 0.5, cy - mn * amp);
  }
  ctx.stroke();

  if (progress >= 0 && progress <= 1) {
    const px = x0 + progress * cols;
    ctx.strokeStyle = "#f59e0b";
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(px, padTop - 2);
    ctx.lineTo(px, h - 4);
    ctx.stroke();
  }

  // Right half: Spectrum 0 - 5500 Hz (live AnalyserNode while playing, or precomputed voiced FFT)
  const sx0 = midX + 8;
  const sw = Math.max(20, w - sx0 - 8);
  const syTop = 20, syBot = h - 14;
  const sh = Math.max(20, syBot - syTop);
  const maxBin = Math.min(1024, Math.round((5500 / SR) * 2048));

  let useLive = false;
  if (progress >= 0 && analyser && activeNodes.length) {
    analyser.getFloatFrequencyData(liveFreqBuf);
    let pk = -120;
    for (let k = 2; k < maxBin; k++) if (liveFreqBuf[k] > pk) pk = liveFreqBuf[k];
    if (pk > -95) {
      useLive = true;
      ctx.beginPath();
      for (let c = 0; c < sw; c++) {
        const k = Math.max(1, Math.min(maxBin - 1, Math.round((c / sw) * maxBin)));
        const rel = Math.max(-52, Math.min(0, liveFreqBuf[k] - pk));
        const yy = syTop + ((-rel) / 52) * sh;
        if (c === 0) ctx.moveTo(sx0 + c, yy);
        else ctx.lineTo(sx0 + c, yy);
      }
    }
  }

  if (!useLive) {
    if (!cachedSpecDb[curStep]) {
      cachedSpecDb[curStep] = computeStaticSpec(arr, cachedRes.r);
    }
    const sdb = cachedSpecDb[curStep];
    ctx.beginPath();
    for (let c = 0; c < sw; c++) {
      const k = Math.max(1, Math.min(maxBin - 1, Math.round((c / sw) * maxBin)));
      const rel = Math.max(-52, Math.min(0, sdb[k]));
      const yy = syTop + ((-rel) / 52) * sh;
      if (c === 0) ctx.moveTo(sx0 + c, yy);
      else ctx.lineTo(sx0 + c, yy);
    }
  }

  ctx.strokeStyle = curStep === 0 ? "#94a3b8" : "#f59e0b";
  ctx.lineWidth = 1.3;
  ctx.stroke();
  ctx.lineTo(sx0 + sw, syBot);
  ctx.lineTo(sx0, syBot);
  ctx.closePath();
  ctx.fillStyle = curStep === 0 ? "rgba(148, 163, 184, 0.12)" : "rgba(245, 158, 11, 0.14)";
  ctx.fill();

  // Frequency axis ticks (1k, 2.5k, 5k)
  ctx.fillStyle = "#64748b";
  ctx.font = "9.5px sans-serif";
  for (const [hzTick, lbl] of [[1000, "1k"], [2600, "2.6k"], [5000, "5k"]]) {
    const tx = sx0 + (hzTick / 5500) * sw;
    if (tx < sx0 + sw - 12) ctx.fillText(lbl, tx - 5, h - 3);
  }

  ctx.restore();
}

// Event Wiring (stateless, sandbox-safe)
elPlay.addEventListener("click", () => {
  if (activeNodes.length || isTouring) {
    stopPlayback();
  } else {
    playCurrentStep(curStep);
  }
});

elInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();
    playCurrentStep(curStep);
  }
});

stepBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const idx = Number(btn.dataset.step);
    playCurrentStep(idx);
  });
});

elTour.addEventListener("click", () => {
  playStepTour();
});

elScope.addEventListener("click", () => {
  playCurrentStep(curStep);
});

presetBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const pk = btn.dataset.preset;
    presetBtns.forEach((b) => b.classList.toggle("active", b === btn));
    const curVal = elInput.value.trim();
    if (pk === "uta") {
      isUta = true;
      curPreset = "hitofude";
      slHz.value = "326";
      slGvo.value = "0.90";
      if (BUILTIN_TEXTS.has(curVal)) elInput.value = UTA_TEXT;
    } else {
      isUta = false;
      curPreset = pk;
      const p = PRESETS[pk];
      slHz.value = String(Math.round(p.hz));
      slGvo.value = p.g_vo.toFixed(2);
      slSigh.value = p.sigh.toFixed(2);
      if (BUILTIN_TEXTS.has(curVal)) {
        elInput.value = (pk === "ossan" || pk === "alto") ? OSSAN_TEXT : DEFAULT_TEXT;
      }
    }
    updateKnobLabels();
    playCurrentStep(curStep);
  });
});

for (const sl of [slHz, slGvo, slSigh]) {
  sl.addEventListener("input", updateKnobLabels);
  sl.addEventListener("change", () => playCurrentStep(curStep));
}

elSeed.addEventListener("click", () => {
  curSeed = curSeed >= 2039 ? 2024 : curSeed + 1;
  elSeed.textContent = "🎲 別原石 (seed: " + curSeed + ")";
  playCurrentStep(curStep);
});

window.addEventListener("resize", () => drawScope(-1));

// Initial boot: render frame immediately, then pre-carve default phrase on next frame
updateKnobLabels();
requestAnimationFrame(() => {
  setTimeout(() => {
    ensureCarved();
    setStepUI(4);
    // If loaded with ?autoplay=1 inside a frame that inherited user activation, attempt polite start
    if (/[?&](autoplay=1|auto_play=true)/.test(window.location.search)) {
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (Ctx) {
          audioCtx = new Ctx({ sampleRate: SR });
          analyser = audioCtx.createAnalyser();
          analyser.fftSize = 2048;
          analyser.smoothingTimeConstant = 0.65;
          analyser.connect(audioCtx.destination);
          if (audioCtx.state === "running") {
            playCurrentStep(4);
          }
        }
      } catch (_) {}
    }
  }, 16);
});
})();
</script>
</body>
</html>
`;

const PLAYER_VER = "10.8";
const ENGINE_KB = Math.round(Buffer.byteLength(engineSrc, "utf8") / 1000);

const shareHtml = `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="twitter:card" content="player">
<meta name="twitter:title" content="草薙 kusanagi — Pythonゼロ・純JSで1本の乱数から声を彫る">
<meta name="twitter:description" content="Pythonゼロ・録音0 Byte・学習モデルなし。1本のホワイトノイズと非対称ベルヌーイ2唇扉×5極声道の再帰だけで女声・大人アルト・低音おっさん・歌まで彫る純JSシンセ（0原石→④完成をその場で聴き比べ）">
<meta name="twitter:image" content="${PAGES_BASE}/assets/kusanagi_square.jpg">
<meta name="twitter:player" content="${PAGES_BASE}/kusanagi_player.html?v=${PLAYER_VER}">
<meta name="twitter:player:width" content="480">
<meta name="twitter:player:height" content="480">
<meta property="og:type" content="website">
<meta property="og:url" content="${PAGES_BASE}/kusanagi.html">
<meta property="og:title" content="草薙 kusanagi — Pythonゼロ・純JSで1本の乱数から声を彫る">
<meta property="og:description" content="Pythonゼロ・録音0 Byte・学習モデルなし。1本のホワイトノイズと非対称ベルヌーイ2唇扉×声道再帰だけで日本語の声と吐息を彫る純JSシンセ。">
<meta property="og:image" content="${PAGES_BASE}/assets/kusanagi_square.jpg">
<meta property="og:image:width" content="1024">
<meta property="og:image:height" content="1024">
<title>草薙 kusanagi — Pythonゼロ・純JSで1本の乱数から声を彫る | poidowl/tsukinami</title>
<style>
  :root {
    --bg: #080d15;
    --panel: #111a28;
    --border: #243347;
    --text: #f3efe6;
    --muted: #94a3b8;
    --amber: #f59e0b;
    --emerald: #26cc9b;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 20px 14px 40px;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Meiryo", sans-serif;
    line-height: 1.55;
  }
  .wrap {
    max-width: 560px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .hero {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    flex-wrap: wrap;
  }
  .hero h1 {
    margin: 0;
    font-size: 1.3rem;
    letter-spacing: 0.02em;
  }
  .hero p {
    margin: 4px 0 0;
    font-size: 0.86rem;
    color: var(--muted);
  }
  .frame-shell {
    width: 100%;
    max-width: 480px;
    height: 480px;
    margin: 0 auto;
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid var(--border);
    background: #0b111b;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.45);
  }
  .frame-shell iframe {
    width: 100%;
    height: 100%;
    border: 0;
    display: block;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    font-size: 0.86rem;
  }
  .card h2 {
    margin: 0 0 8px;
    font-size: 0.96rem;
    color: var(--amber);
  }
  .steps-list {
    margin: 0;
    padding-left: 18px;
    color: var(--muted);
  }
  .steps-list li { margin-bottom: 4px; }
  .steps-list strong { color: var(--text); }
  .share-bar {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
    margin-top: 10px;
  }
  .btn {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 0.82rem;
    font-weight: 700;
    text-decoration: none;
    cursor: pointer;
    font-family: inherit;
  }
  .btn:hover { border-color: var(--emerald); color: var(--emerald); }
  .btn.primary {
    background: var(--emerald);
    color: #07120f;
    border-color: var(--emerald);
  }
  @media (max-width: 500px) {
    body { padding: 12px 8px 28px; }
    .frame-shell { height: 500px; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div>
      <h1>草薙 kusanagi</h1>
      <p>Pythonゼロ・録音 0 Byte・正弦波オシレータ不使用。たった1本のホワイトノイズから非対称ベルヌーイ粘膜扉と声道再帰だけで日本語を彫る純JSシンセ。</p>
    </div>
  </header>

  <div class="frame-shell">
    <iframe src="./kusanagi_player.html?v=${PLAYER_VER}" title="草薙 kusanagi インタラクティブシンセ"
      sandbox="allow-popups allow-same-origin allow-scripts allow-presentation"></iframe>
  </div>

  <section class="card">
    <h2>1本のノイズ線から声になる仕組み</h2>
    <ol class="steps-list">
      <li><strong>0 原石：</strong>軽量PRNG（<code>Mulberry32</code>）で <code>[-1, 1]</code> のホワイトノイズを1本だけ用意する（漂い・ジッタ・ビブラート・呼気圧もすべてこの1本から作る）。</li>
      <li><strong>① 声帯組織波：</strong>声道からの帰還圧を受けながら2段コム＋高域 <code>damp</code> で揺れる声帯波を立てる（冷凍ロボのみ片道コム <code>shin=0</code>）。</li>
      <li><strong>② 非対称2唇扉：</strong>上唇は丸くめくれて開き、下唇はベルヌーイ吸い寄せ×粘膜ソフトクッションでフランジャー櫛を立てずに呼気流を刻む。</li>
      <li><strong>③ 5極粘膜声道：</strong>扉と1サンプル再帰結合した F1–F5 粘膜声道＋真の唇微分放射（<code>+6dB/oct</code>）で1本の管として響かせ、子音・ハ行帯を明瞭に添える。</li>
      <li><strong>④ 完成：</strong>1スカラー整音と時間包絡をかけ、句末は同じ1本線の扉を緩めて元の吐息へ戻す。</li>
    </ol>
    <div class="share-bar">
      <button id="copyUrlBtn" class="btn primary" type="button">X投稿用URLをコピー</button>
      <a class="btn" href="./kusanagi_choir.html">🎶 1→128人ライブ大合唱へ</a>
      <a class="btn" href="./index.html">🎛️ 月並みTTS オモチャ箱へ</a>
      <a class="btn" href="https://github.com/poidowl/tsukinami/tree/kusanagi" target="_blank" rel="noopener noreferrer">純JSソース (${ENGINE_KB}KB・kusanagi branch) ↗</a>
    </div>
  </section>

  <section class="card">
    <h2>改変履歴（kusanagi エンジン）</h2>
    <ul class="steps-list">
      <li><strong>v11.0：</strong><strong>読点の息の床（<code>pau_iki: -30</code> 既定）</strong> — 読点「、」の 0.35 秒を完全無音に彫り切らず、同じ原石ノイズが無声のまま5極声道＋唇放射を通った吐息を、有声部 RMS 比 −30 dB でうっすら残す（両端は余弦窓）。ReazonSpeech k2 が読点を文末と取り違えて「ちょっとしゃべれます」を落とす本数が、大人6声×3 seed で 6/18 → 2/18。<code>{pau_iki: null}</code> で v10.8 (<code>b9b5eb8</code>) とバイト一致。ちびっ子は崩れが出たため従来の無音のまま。間の長さノブ <code>pau_s</code>（既定 0.35 秒）も追加。</li>
      <li><strong>v10.8 (<a href="https://github.com/poidowl/tsukinami/commit/b9b5eb8" target="_blank" rel="noopener noreferrer"><code>b9b5eb8</code></a>)：</strong><strong>ノイズ削りコード自体の断捨離＆単一因果ループ統合（計 -306行 / -8.9KB）</strong> — 旧並列時代の非因果往復コム <code>yamaBp/ffbb/combHalf</code> をピーク利得一定の因果2極ゼロDCバンドパスへ置換して全段を完全因果1パス化し、重複していた <code>xSeed</code>・後段 <code>karuku</code>・ロボ専用別エンジン <code>combPeriod/resonator2Pole</code>・死蔵 <code>G2/G3</code> 軌道を全撤去して全7プリセット＋歌を単一ループへ統合。</li>
      <li><strong>v10.1 (<a href="https://github.com/poidowl/tsukinami/commit/a084abe" target="_blank" rel="noopener noreferrer"><code>a084abe</code></a>)：</strong>v10 の子音・ハ行明瞭度×粘膜ソフトクッションに、<strong>v9 サラサラ化（<code>combG: 0.985, rawAirMul: 0.6</code> / soroe2）を既定合流</strong>（持続母音シマー <code>5.5% → 1.8%</code>、<code>{combG: null, rawAirMul: 1.0}</code> で <code>90f0c44</code> の音とバイト一致）。</li>
      <li><strong>v10 (<a href="https://github.com/poidowl/tsukinami/commit/90f0c44" target="_blank" rel="noopener noreferrer"><code>90f0c44</code></a>)：</strong>聴き取りと自然さの二軸両立アップデート — <strong>子音明瞭度（<code>/s/, /t/, /k/</code>）とハ行気息（後続母音 F2 同調 <code>h</code> / 両唇 <code>f</code>）の完全復元</strong>、<code>ei</code> 長音同化、および<strong>高域コム減衰＋粘膜ソフトクッション＋等身大声道倍率</strong>による女声・歌唱時のエフェクター（フランジャー・ワウ）感の解消。</li>
      <li><strong>v9 サラサラ化 (<a href="https://github.com/poidowl/tsukinami/commit/2859fff" target="_blank" rel="noopener noreferrer"><code>2859fff</code></a>・11-20)：</strong>有声のあいだ粘膜コム帰還を <code>combG×有声度</code>（既定 <code>0.985</code>）に固定し、扉を通る生ノイズ <code>rawAir</code> を <code>0.6</code> 倍に（<strong>soroe2</strong>）。毎周期まじる新しいノイズによるザラザラ（シマー）を減らす。</li>
      <li><strong>v8 (<a href="https://github.com/poidowl/tsukinami/commit/7f09d18" target="_blank" rel="noopener noreferrer"><code>7f09d18</code></a>)：</strong>2唇粘膜扉×5極声道の再帰結合を <strong>非対称ベルヌーイ閉鎖（上唇は丸く開き・下唇は気流吸い寄せで急閉鎖）＋真の唇微分放射</strong>へ進化させ、女声・歌・新設 <code>アルト</code> まで全人間プリセットへ統合（旧並列時代の <code>fricT</code>/<code>vl_f1</code> 子音F1ワープも撤去）。</li>
      <li><strong>v7 (<a href="https://github.com/poidowl/tsukinami/commit/755c7a8" target="_blank" rel="noopener noreferrer"><code>755c7a8</code></a>)：</strong>低音男声（<code>ossan</code>）を片道コムから <strong>声門2唇粘膜扉×5極声道（F1–F5）の1サンプル再帰結合系</strong>へ刷新し、低音の位相ボコーダー感を排した太い「轟」を実現。</li>
      <li><strong><a href="https://github.com/poidowl/tsukinami/commit/b114684" target="_blank" rel="noopener noreferrer"><code>b114684</code></a>：</strong>ピッチ漂い・周期ジッタ・歌唱ビブラート用の別シード乱数を全廃し、Step 0 のホワイトノイズ <code>x</code> 1本だけから削り出す真の単一乱数化を達成。</li>
      <li><strong>v6 (<a href="https://github.com/poidowl/tsukinami/commit/1498df1" target="_blank" rel="noopener noreferrer"><code>1498df1</code></a>)：</strong>有声破裂（<code>g/d/b</code>）への高域ノイズ帯域 <code>rawBands</code> 付与を廃止し、ダ行・ガ行・バ行で乗っていた高域クリックノイズを解消。</li>
      <li><strong>v5 (<a href="https://github.com/poidowl/tsukinami/commit/3026d36" target="_blank" rel="noopener noreferrer"><code>3026d36</code></a>)：</strong>歌モード（<code>uta_hz</code>）時に話し声用の母音無声化と <code>ou</code> 長音同化を無効化し、歌唱時の音抜け（ち・つ・し・す・ぴ・ぷ等）を解消。</li>
      <li><strong>v4 (<a href="https://github.com/poidowl/tsukinami/commit/8e95bfa" target="_blank" rel="noopener noreferrer"><code>8e95bfa</code></a>)：</strong>無声子音中の母音声道ゲート <code>G1S</code> を復活させ <code>bpc</code> 係数を <code>0.40</code> へ再調整（大合唱時の「しゅー」過多を解消・発話子音の輪郭改善）。</li>
      <li><strong>v3 (<a href="https://github.com/poidowl/tsukinami/commit/a79bb1b" target="_blank" rel="noopener noreferrer"><code>a79bb1b</code></a>)：</strong>高音時の笛・スパイク化を抑えるため <code>resonator2Pole</code> に Q 上限つきの周波数連動 <code>bw</code> と F1/F2/F3 衝突ガードを追加。</li>
      <li><strong>v2 (<a href="https://github.com/poidowl/tsukinami/commit/24d4965" target="_blank" rel="noopener noreferrer"><code>24d4965</code></a>)：</strong>Step ③ の母音声道を並列 <code>yamaBp</code>×4 から <strong>F1→F2→F3→F4 因果直列カスケード＋唇放射</strong>へ刷新（ボコーダー感低減・高速化）。</li>
      <li><strong><a href="https://github.com/poidowl/tsukinami/commit/c2b67c4" target="_blank" rel="noopener noreferrer"><code>c2b67c4</code></a>：</strong>母音 <code>/u/</code> の F2・音長・音量を修正し、無声破裂音前での「う」脱落を解消。</li>
      <li><strong><a href="https://github.com/poidowl/tsukinami/commit/d81cca0" target="_blank" rel="noopener noreferrer"><code>d81cca0</code></a>：</strong><code>combPeriod</code> に高域減衰 <code>damp</code> をオプション追加。</li>
      <li><strong>v1 (<a href="https://github.com/poidowl/tsukinami/commit/24d3049" target="_blank" rel="noopener noreferrer"><code>24d3049</code></a>)：</strong>初版公開＋読み上げ修正（並列 <code>yamaBp</code> 5本構成）。</li>
    </ul>
  </section>
</div>
<script>
document.getElementById("copyUrlBtn").addEventListener("click", function () {
  const url = "${PAGES_BASE}/kusanagi.html";
  const btn = this;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(() => {
      btn.textContent = "✓ コピーしました: " + url;
      setTimeout(() => { btn.textContent = "X投稿用URLをコピー"; }, 2400);
    });
  }
});
</script>
</body>
</html>
`;

fs.writeFileSync(path.join(OUT_DIR, "kusanagi_player.html"), playerHtml, "utf8");
fs.writeFileSync(path.join(OUT_DIR, "kusanagi.html"), shareHtml, "utf8");

console.log("compactEngine bytes:", Buffer.byteLength(compactEngine, "utf8"));
console.log("kusanagi_player.html bytes:", Buffer.byteLength(playerHtml, "utf8"));
console.log("kusanagi.html bytes:", Buffer.byteLength(shareHtml, "utf8"));
