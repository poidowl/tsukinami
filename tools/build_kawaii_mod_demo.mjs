#!/usr/bin/env node
/**
 * tools/build_kawaii_mod_demo.mjs
 *
 * Original kusanagi (v13.2) と Kawaii MOD (kawaii-kusanagi V8-Egao) を
 * 1枚の完全オフライン・自己完結HTMLでリアルタイム聴き比べできるデモを生成する。
 *
 * Usage:
 *   node tools/build_kawaii_mod_demo.mjs [out.html]
 */
import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const outPath = process.argv[2] ? path.resolve(process.argv[2]) : path.join(ROOT, "demo_kawaii_mod.html");

const origSrc = execSync("git show kusanagi:hitofude.mjs", { cwd: ROOT, encoding: "utf8" });
const modSrc = fs.readFileSync(path.join(ROOT, "hitofude.mjs"), "utf8");

function wrapIife(src, globalName) {
  const safe = src
    .replace(/^export\s+/gm, "")
    .replace(/<\/script>/gi, "<\\/script>");
  return `const ${globalName} = (() => {\n${safe}\nreturn { makeHitofude, encodeWav, PRESETS, SR };\n})();`;
}

const origKb = (Buffer.byteLength(origSrc, "utf8") / 1024).toFixed(1);
const modKb = (Buffer.byteLength(modSrc, "utf8") / 1024).toFixed(1);

const html = `<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tsukinami — kusanagi v13.2 vs カワイイMOD (V8-Egao) リアルタイム聴き比べ</title>
<style>
  :root {
    color-scheme: dark;
    --bg: #070b14;
    --bg2: #0d1424;
    --panel: rgba(16, 24, 41, 0.92);
    --border: #23324f;
    --fg: #f1f5f9;
    --muted: #94a3b8;
    --cyan: #38bdf8;
    --cyan-g: linear-gradient(135deg, #0284c7, #6366f1);
    --pink: #f472b6;
    --pink-g: linear-gradient(135deg, #ec4899, #8b5cf6);
    --gold: #fbbf24;
    --gold-g: linear-gradient(135deg, #f59e0b, #ec4899);
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 16px;
    font-family: system-ui, -apple-system, "Segoe UI", "Hiragino Sans", sans-serif;
    background:
      radial-gradient(900px 420px at 15% -10%, rgba(56, 189, 248, 0.14), transparent 60%),
      radial-gradient(900px 420px at 85% -10%, rgba(244, 114, 182, 0.16), transparent 60%),
      var(--bg);
    color: var(--fg);
    min-height: 100vh;
  }
  .wrap { max-width: 980px; margin: 0 auto; display: grid; gap: 12px; }
  header {
    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px;
    padding: 12px 16px; border-radius: 14px;
    background: var(--panel); border: 1px solid var(--border);
  }
  .brand { display: flex; flex-direction: column; gap: 2px; }
  h1 { margin: 0; font-size: 1.08rem; letter-spacing: 0.01em; color: #fff; }
  .sub { font-size: 0.75rem; color: var(--muted); }
  .badges { display: flex; flex-wrap: wrap; gap: 6px; }
  .badge {
    font-size: 0.69rem; font-weight: 700; padding: 3px 9px; border-radius: 999px;
    border: 1px solid var(--border); background: rgba(255,255,255,0.04); color: #cbd5e1;
  }
  .badge.pink { border-color: rgba(244,114,182,0.45); color: #fbcfe8; background: rgba(244,114,182,0.10); }
  .badge.cyan { border-color: rgba(56,189,248,0.45); color: #bae6fd; background: rgba(56,189,248,0.10); }

  .input-box {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 12px 14px; display: grid; gap: 9px;
  }
  .input-row { display: flex; gap: 8px; flex-wrap: wrap; }
  #textInput {
    flex: 1 1 280px;
    padding: 10px 13px; border-radius: 10px;
    border: 1px solid #33476b; background: #0a1020; color: #fff;
    font-size: 0.95rem; font-weight: 600; outline: none;
  }
  #textInput:focus { border-color: var(--pink); box-shadow: 0 0 0 3px rgba(244,114,182,0.18); }
  .btn-ab {
    border: none; border-radius: 10px; padding: 10px 16px;
    font-size: 0.86rem; font-weight: 800; color: #fff; cursor: pointer;
    background: var(--gold-g); white-space: nowrap;
    box-shadow: 0 4px 16px rgba(236,72,153,0.28);
    transition: transform 0.1s ease, filter 0.15s ease;
  }
  .btn-ab:hover { filter: brightness(1.08); }
  .btn-ab:active { transform: scale(0.98); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    border: 1px solid #2b3c5c; background: rgba(255,255,255,0.03); color: #cbd5e1;
    border-radius: 999px; padding: 4px 10px; font-size: 0.72rem; cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .chip:hover { border-color: var(--pink); background: rgba(244,114,182,0.12); color: #fff; }

  .arena { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  @media (max-width: 720px) { .arena { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
    padding: 14px; display: flex; flex-direction: column; gap: 10px;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .card.orig { border-top: 3px solid var(--cyan); }
  .card.mod  { border-top: 3px solid var(--pink); background: linear-gradient(180deg, rgba(244,114,182,0.07), rgba(16,24,41,0.94) 40%); }
  .card.playing { border-color: var(--gold); box-shadow: 0 0 20px rgba(251,191,36,0.22); }

  .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
  .card-title { font-weight: 800; font-size: 0.94rem; color: #fff; }
  .card-tag { font-size: 0.70rem; color: var(--muted); margin-top: 2px; }
  .size-pill { font-size: 0.68rem; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: rgba(255,255,255,0.06); color: #cbd5e1; white-space: nowrap; }

  .ctrl-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  select {
    flex: 1 1 140px; padding: 7px 10px; border-radius: 9px;
    border: 1px solid #33476b; background: #0a1020; color: #fff;
    font-size: 0.82rem; font-weight: 600;
  }
  .btn-play {
    border: none; border-radius: 9px; padding: 8px 15px;
    font-size: 0.83rem; font-weight: 800; color: #fff; cursor: pointer; white-space: nowrap;
  }
  .btn-play.orig { background: var(--cyan-g); }
  .btn-play.mod  { background: var(--pink-g); }
  .btn-dl {
    border: 1px solid #33476b; background: rgba(255,255,255,0.04); color: #cbd5e1;
    border-radius: 9px; padding: 7px 10px; font-size: 0.76rem; font-weight: 700; cursor: pointer;
  }
  .btn-dl:hover { border-color: #64748b; color: #fff; }
  .btn-dl:disabled { opacity: 0.4; cursor: default; }

  canvas.wave {
    width: 100%; height: 64px; border-radius: 9px;
    background: #080d1a; border: 1px solid #1c2942; display: block;
  }
  audio { width: 100%; height: 32px; }
  .meta { font-size: 0.71rem; color: var(--muted); display: flex; justify-content: space-between; gap: 8px; }

  details.knobs {
    border-top: 1px solid #22304b; padding-top: 8px; font-size: 0.76rem;
  }
  details.knobs summary {
    cursor: pointer; font-weight: 700; color: #fbcfe8; user-select: none;
  }
  .knob-grid {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 12px; margin-top: 8px;
  }
  .knob { display: flex; flex-direction: column; gap: 3px; }
  .knob label { display: flex; justify-content: space-between; color: #cbd5e1; font-size: 0.71rem; }
  .knob input[type="range"] { width: 100%; accent-color: var(--pink); }
  .reset-row { margin-top: 6px; display: flex; justify-content: flex-end; }
  .btn-mini {
    border: 1px solid #33476b; background: transparent; color: var(--muted);
    border-radius: 7px; padding: 3px 9px; font-size: 0.70rem; cursor: pointer;
  }
  .btn-mini:hover { color: #fff; border-color: var(--pink); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="brand">
      <h1>🎙️ tsukinami — kusanagi v13.2 vs カワイイMOD (V8-Egao)</h1>
      <div class="sub">学習済みモデル 0 バイト・純粋物理JSだけで動く、その場リアルタイム合成＆聴き比べデモ</div>
    </div>
    <div class="badges">
      <span class="badge cyan">Original kusanagi: ${origKb} KB</span>
      <span class="badge pink">Kawaii MOD V8-Egao: ${modKb} KB</span>
      <span class="badge">0-Byte Weights / CC0 / 100% Offline</span>
    </div>
  </header>

  <section class="input-box">
    <div class="input-row">
      <input id="textInput" type="text" value="あのね、きょうもいっしょに、あそぼうね" placeholder="ひらがな・カタカナで入力（例：わたし、にほんご、ちょっとしゃべれます）">
      <button class="btn-ab" id="btnAB">⚔️ A → B 連続聴き比べ</button>
    </div>
    <div class="chips" id="chips">
      <button class="chip" data-t="あのね、きょうもいっしょに、あそぼうね">あのね、きょうもいっしょに、あそぼうね</button>
      <button class="chip" data-t="わたし、にほんご、ちょっとしゃべれます">わたし、にほんご、ちょっとしゃべれます</button>
      <button class="chip" data-t="ねえねえ、こっちむいて、おねがい">ねえねえ、こっちむいて、おねがい</button>
      <button class="chip" data-t="やったあ、きょうもげんきに、いってみよう">やったあ、きょうもげんきに、いってみよう</button>
      <button class="chip" data-t="ひみつだよ、だれにも、いわないでね">ひみつだよ、だれにも、いわないでね</button>
      <button class="chip" data-t="こんにちは、くさなぎの、かわいいもっどです">こんにちは、くさなぎの、かわいいもっどです</button>
    </div>
  </section>

  <section class="arena">
    <!-- Left: Original kusanagi v13.2 -->
    <div class="card orig" id="cardOrig">
      <div class="card-head">
        <div>
          <div class="card-title">A. Original kusanagi (v13.2)</div>
          <div class="card-tag">オリジナルの草薙エンジン（オッサン・ロボット・アルト等も収録）</div>
        </div>
        <span class="size-pill">${origKb} KB</span>
      </div>
      <div class="ctrl-row">
        <select id="selOrig"></select>
        <button class="btn-play orig" id="btnOrig">▶ 合成して再生</button>
        <button class="btn-dl" id="dlOrig" disabled>WAV</button>
      </div>
      <canvas class="wave" id="waveOrig" width="440" height="64"></canvas>
      <audio id="audioOrig" controls></audio>
      <div class="meta">
        <span id="metaOrig">待機中（ボタンを押すとブラウザ内で即合成します）</span>
        <span id="timeOrig"></span>
      </div>
    </div>

    <!-- Right: Kawaii MOD V8-Egao -->
    <div class="card mod" id="cardMod">
      <div class="card-head">
        <div>
          <div class="card-title">B. Kawaii MOD (V8-Egao)</div>
          <div class="card-tag">肉厚H2–A1声帯・CF0摂動・生理的ジッター・笑顔気息（全6プリセット異音0.0）</div>
        </div>
        <span class="size-pill">${modKb} KB</span>
      </div>
      <div class="ctrl-row">
        <select id="selMod"></select>
        <button class="btn-play mod" id="btnMod">▶ 合成して再生</button>
        <button class="btn-dl" id="dlMod" disabled>WAV</button>
      </div>
      <canvas class="wave" id="waveMod" width="440" height="64"></canvas>
      <audio id="audioMod" controls></audio>
      <div class="meta">
        <span id="metaMod">待機中（ボタンを押すとブラウザ内で即合成します）</span>
        <span id="timeMod"></span>
      </div>

      <details class="knobs">
        <summary>🎛️ カワイイMOD リアルタイム物理ノブ（声帯・声道を変形）</summary>
        <div class="knob-grid">
          <div class="knob">
            <label><span>ピッチ hz</span><span id="vHz">335</span></label>
            <input type="range" id="kHz" min="240" max="460" step="1" value="335">
          </div>
          <div class="knob">
            <label><span>声道サイズ fs</span><span id="vFs">1.18</span></label>
            <input type="range" id="kFs" min="0.95" max="1.45" step="0.01" value="1.18">
          </div>
          <div class="knob">
            <label><span>笑顔度 smile</span><span id="vSmile">0.70</span></label>
            <input type="range" id="kSmile" min="0.00" max="1.20" step="0.02" value="0.70">
          </div>
          <div class="knob">
            <label><span>有声の息 asp</span><span id="vAsp">0.18</span></label>
            <input type="range" id="kAsp" min="0.00" max="0.50" step="0.01" value="0.18">
          </div>
        </div>
        <div class="reset-row">
          <button class="btn-mini" id="btnResetKnobs">プリセット既定値に戻す</button>
        </div>
      </details>
    </div>
  </section>
</div>

<script>
${wrapIife(origSrc, "KusanagiOrig")}
${wrapIife(modSrc, "KawaiiMod")}

const ORIG_LABELS = {
  hitofude: "hitofude（標準）",
  toiki:    "toiki（吐息）",
  alto:     "alto（アルト）",
  sasayaki: "sasayaki（ささやき）",
  chibi:    "chibi（ちび）",
  ossan:    "ossan（オッサン）",
  robot:    "robot（ロボット）",
};
const MOD_LABELS = {
  kawaii:   "🌸 kawaii（王道笑顔）",
  amae:     "🎀 amae（とろ甘）",
  genki:    "⚡ genki（元気）",
  tenshi:   "👼 tenshi（天使）",
  chibi:    "🐥 chibi（ちび）",
  sasayaki: "🌙 sasayaki（ささやき）",
};

const selOrig = document.getElementById("selOrig");
const selMod  = document.getElementById("selMod");
for (const k of Object.keys(KusanagiOrig.PRESETS)) {
  const o = document.createElement("option");
  o.value = k; o.textContent = ORIG_LABELS[k] || k;
  selOrig.appendChild(o);
}
for (const k of Object.keys(KawaiiMod.PRESETS)) {
  const o = document.createElement("option");
  o.value = k; o.textContent = MOD_LABELS[k] || k;
  selMod.appendChild(o);
}

const kHz = document.getElementById("kHz");
const kFs = document.getElementById("kFs");
const kSmile = document.getElementById("kSmile");
const kAsp = document.getElementById("kAsp");
function syncKnobsFromPreset() {
  const p = KawaiiMod.PRESETS[selMod.value] || KawaiiMod.PRESETS.kawaii;
  kHz.value = p.hz ?? 335;
  kFs.value = p.fs ?? 1.18;
  kSmile.value = p.smile ?? 0.70;
  kAsp.value = p.asp ?? 0.18;
  updateKnobLabels();
}
function updateKnobLabels() {
  document.getElementById("vHz").textContent = Number(kHz.value).toFixed(0) + " Hz";
  document.getElementById("vFs").textContent = Number(kFs.value).toFixed(2);
  document.getElementById("vSmile").textContent = Number(kSmile.value).toFixed(2);
  document.getElementById("vAsp").textContent = Number(kAsp.value).toFixed(2);
}
selMod.addEventListener("change", syncKnobsFromPreset);
[kHz, kFs, kSmile, kAsp].forEach(el => el.addEventListener("input", updateKnobLabels));
document.getElementById("btnResetKnobs").addEventListener("click", syncKnobsFromPreset);
syncKnobsFromPreset();

const state = {
  orig: { url: null, samples: null },
  mod:  { url: null, samples: null },
};

function drawWave(canvas, samples, color) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#1c2942";
  ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
  if (!samples || !samples.length) return;
  const step = Math.max(1, Math.floor(samples.length / w));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  for (let x = 0; x < w; x++) {
    let mn = 1, mx = -1;
    const i0 = x * step, i1 = Math.min(samples.length, i0 + step);
    for (let i = i0; i < i1; i++) {
      const v = samples[i];
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    }
    const y1 = (1 - mx) * 0.5 * (h - 6) + 3;
    const y2 = (1 - mn) * 0.5 * (h - 6) + 3;
    ctx.moveTo(x + 0.5, y1);
    ctx.lineTo(x + 0.5, y2);
  }
  ctx.stroke();
}

function synthSide(side, autoPlay = true) {
  const text = document.getElementById("textInput").value.trim() || "あのね、きょうもいっしょに、あそぼうね";
  const isOrig = side === "orig";
  const engine = isOrig ? KusanagiOrig : KawaiiMod;
  const presetKey = isOrig ? selOrig.value : selMod.value;
  const basePrm = engine.PRESETS[presetKey];
  const prm = isOrig
    ? { ...basePrm, seed: Math.trunc(Number(basePrm.seed)), tilt_w: Math.round(Number(basePrm.tilt_w)) }
    : {
        ...basePrm,
        hz: Number(kHz.value),
        fs: Number(kFs.value),
        smile: Number(kSmile.value),
        asp: Number(kAsp.value),
        seed: Math.trunc(Number(basePrm.seed)),
        tilt_w: Math.round(Number(basePrm.tilt_w)),
      };

  const t0 = performance.now();
  const res = engine.makeHitofude(text, prm);
  const wavBytes = engine.encodeWav(res.samples, engine.SR);
  const dt = (performance.now() - t0).toFixed(0);
  const dur = (res.samples.length / engine.SR).toFixed(2);

  if (state[side].url) URL.revokeObjectURL(state[side].url);
  const blob = new Blob([wavBytes], { type: "audio/wav" });
  const url = URL.createObjectURL(blob);
  state[side].url = url;
  state[side].samples = res.samples;

  const audio = document.getElementById(isOrig ? "audioOrig" : "audioMod");
  const canvas = document.getElementById(isOrig ? "waveOrig" : "waveMod");
  const meta = document.getElementById(isOrig ? "metaOrig" : "metaMod");
  const timeEl = document.getElementById(isOrig ? "timeOrig" : "timeMod");
  const dlBtn = document.getElementById(isOrig ? "dlOrig" : "dlMod");

  drawWave(canvas, res.samples, isOrig ? "#38bdf8" : "#f472b6");
  audio.src = url;
  meta.textContent = (isOrig ? "kusanagi" : "Kawaii MOD") + " [" + presetKey + "] / " + dur + "秒";
  timeEl.textContent = "合成 " + dt + " ms";
  dlBtn.disabled = false;

  if (autoPlay) {
    const other = document.getElementById(isOrig ? "audioMod" : "audioOrig");
    if (!other.paused) other.pause();
    audio.currentTime = 0;
    audio.play();
  }
  return audio;
}

["Orig", "Mod"].forEach((S) => {
  const audio = document.getElementById("audio" + S);
  const card = document.getElementById("card" + S);
  audio.addEventListener("play", () => card.classList.add("playing"));
  audio.addEventListener("pause", () => card.classList.remove("playing"));
  audio.addEventListener("ended", () => card.classList.remove("playing"));
});

document.getElementById("btnOrig").addEventListener("click", () => synthSide("orig", true));
document.getElementById("btnMod").addEventListener("click", () => synthSide("mod", true));

document.getElementById("btnAB").addEventListener("click", () => {
  const aOrig = synthSide("orig", false);
  const aMod = synthSide("mod", false);
  aMod.pause(); aMod.currentTime = 0;
  aOrig.onended = () => {
    aOrig.onended = null;
    setTimeout(() => { aMod.currentTime = 0; aMod.play(); }, 220);
  };
  aOrig.currentTime = 0;
  aOrig.play();
});

document.getElementById("dlOrig").addEventListener("click", () => {
  if (!state.orig.url) return;
  const a = document.createElement("a");
  a.href = state.orig.url; a.download = "kusanagi_" + selOrig.value + ".wav"; a.click();
});
document.getElementById("dlMod").addEventListener("click", () => {
  if (!state.mod.url) return;
  const a = document.createElement("a");
  a.href = state.mod.url; a.download = "kawaii_mod_" + selMod.value + ".wav"; a.click();
});

document.getElementById("chips").addEventListener("click", (e) => {
  const btn = e.target.closest(".chip");
  if (!btn) return;
  document.getElementById("textInput").value = btn.dataset.t;
});
</script>
</body>
</html>
`;

fs.writeFileSync(outPath, html);
console.log(`[build_kawaii_mod_demo] Wrote ${outPath} (${(Buffer.byteLength(html, "utf8") / 1024).toFixed(1)} KB)`);
