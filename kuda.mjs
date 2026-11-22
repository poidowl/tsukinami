#!/usr/bin/env node
/**
 * kuda.mjs — 0バイト純粋物理・分岐声道管デジタルウェーブガイド音声合成エンジン (管 / KUDA)
 *
 * 100% 純JS・ゼロ依存・0バイト重み・ゼロEQ・ゼロ別系統フォルマントバンクの物理声道管シンセサイザ。
 * 5極カスケードIIRの構造限界 (母音/子音分断・固定笛・高RQA停滞・低CPP・2kHz鼻声山) を
 * 真の分岐声道デジタルウェーブガイド (Kelly-Lochbaum) により根本から突破しつつ、
 * Dual-ASR (ReazonSpeech-k2-v2 + SenseVoice-Small) と 130本音響X線の両輪で調音物理を鍛え上げた版。
 *
 * 物理構造:
 *   1. M=31 若年女性主声道管 (L=12.4cm @ 88.2kHz 2倍速 Kelly-Lochbaum 散乱格子)
 *      - 解剖学的5母音断面積ペンタゴン (a/i/u/e/o 0.22〜5.9cm² 狭窄コントラスト) + 6種全身調音姿勢 (CPOST)
 *      - Titze & Story (1997) 動的軟粘膜喉頭管カラー (j=0..3)
 *      - Dang, Honda & Suzuki (1994) 4.0cm 閉端副鼻腔側枝 (MS=10 @ SIN_J=15, 現実的結合面積 0.18cm²)
 *      - 解剖学的鼻道管 (MN=23 @ VEL_J=14) + 連続軟口蓋ゲート (velGate: クリックゼロ)
 *      - 浅い若年梨状窩側枝 (MP=3 @ PIR_J=4) + Flanagan (1972) 円形ピストン放射インピーダンス × √(A_exit)
 *      - 非両唇子音時の口唇開離 (lipPart) ＋ 硬口蓋歯擦音舌下前腔 (sibPalCav: し/しゃ/しょ/ち/じ均等4.4kHz)
 *   2. Fant-LF 滑らか2段指数リターン相 + 複合 Bernoulli-OpenChink 声門流 + 粘膜弾性(ta1/tp/jit微小ゆらぎ):
 *      - Klatt & Klatt (1990) 3極温息・後部声門間隙気流 + 語頭生理的ソフトオンセット (偽/p/破裂ゼロ)
 *      - 物理4系統分離ダイポール乱流 (歯茎歯擦 6.5kHz / 若年女性口蓋歯擦 4.4kHz / 広帯域破裂 / 声門気息: 相互リークゼロ)
 *      - 2段三角 C¹ 平滑歯擦エンベロープ + 日本語本来の VOT 分離 (k/t/p, g/d/b, 有声摩擦 z/j) + 軟組織3D位相分散
 *      - 日本語音韻規則 (助詞「は」→ワ、長音「おう/えい」→ー、無声子音間のみの狭母音無声化)
 *   3. Butterworth アンチエイリアシング・リサンプラ (24kHz / 44.1kHz 等に対応)
 * 動作環境:
 *   Node.js / ブラウザ両対応の完全1ファイル独立 ESM (外部 import ゼロ)。
 *   - ESM: `import { synthKuda } from "./kuda.mjs"; const { wav, samples, sr } = synthKuda("こんにちは");`
 *   - CLI: `node kuda.mjs [--preset kawaii|amae|genki] [--sr 24000|44100] [--flat Hz] -o out.wav "テキスト"`
 */
export const SR = 44100;
const FP = 5.0;

export function makeRng(seed) {
  let a = (Math.trunc(seed) ^ 0x6d2b79f5) >>> 0;
  const random = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296.0;
  };
  return { random, uniform: (lo, hi) => lo + (hi - lo) * random() };
}

export function toKata(s) {
  let out = "";
  for (const ch of String(s || "")) {
    const code = ch.codePointAt(0);
    out += (code >= 0x3041 && code <= 0x3096) ? String.fromCodePoint(code + 0x60) : ch;
  }
  return out;
}

export function smooth1(x, ms) {
  const k = Math.max(1, Math.trunc(ms / FP)), n = x.length;
  if (k <= 1 || n === 0) return Array.from(x);
  const N = n + 2 * k, a = new Float64Array(N);
  for (let i = 0; i < k; i++) { a[i] = x[0]; a[k + n + i] = x[n - 1]; }
  for (let i = 0; i < n; i++) a[k + i] = x[i];
  const off = Math.floor((k - 1) / 2), out = new Array(n), inv = 1.0 / k;
  for (let i = 0; i < n; i++) {
    const j = i + k + off;
    let s = 0.0;
    for (let m = 0; m < k; m++) {
      const q = j - m;
      if (q >= 0 && q < N) s += a[q] * inv;
    }
    out[i] = s;
  }
  return out;
}

export function encodeWav(samples, sampleRate = SR) {
  const n = samples.length, buf = new ArrayBuffer(44 + n * 2), view = new DataView(buf);
  const writeAscii = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
  writeAscii(0, "RIFF");
  view.setUint32(4, 36 + n * 2, true);
  writeAscii(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(36, "data");
  view.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) view.setInt16(44 + i * 2, Math.round(Math.max(-1.0, Math.min(1.0, samples[i])) * 32767.0), true);
  return new Uint8Array(buf);
}

const M = 31;
const MN = 23;
const MS = 10;
const MP = 3;
const VEL_J = 14;
const SIN_J = 15;
const PIR_J = 4;

export const KUDA_PRESETS = {
  kawaii: { hz: 296.0, smile: 0.54, rd_base: 1.40, rd_tail: 2.14, scoop: 1.54, asp: 0.044, aspMid: 0.178, rate: 1.00 },
  amae:   { hz: 286.0, smile: 0.48, rd_base: 1.54, rd_tail: 2.28, scoop: 1.68, asp: 0.050, aspMid: 0.195, rate: 1.08 },
  genki:  { hz: 306.0, smile: 0.60, rd_base: 1.38, rd_tail: 2.06, scoop: 1.35, asp: 0.044, aspMid: 0.182, rate: 0.95 },
};

const K2V = {};
for (const [row, cons] of [
  ["アイウエオ", ""], ["カキクケコ", "k"], ["サシスセソ", "s"], ["タチツテト", "t"], ["ナニヌネノ", "n"], ["ハヒフヘホ", "h"],
  ["マミムメモ", "m"], ["ヤ・ユ・ヨ", "y"], ["ラリルレロ", "r"], ["ワ・・・ヲ", "w"], ["ガギグゲゴ", "g"], ["ザジズゼゾ", "z"],
  ["ダヂヅデド", "d"], ["バビブベボ", "b"], ["パピプペポ", "p"],
]) {
  const chars = Array.from(row);
  const vs = ["a", "i", "u", "e", "o"];
  for (let i = 0; i < 5; i++) if (chars[i] !== "・") K2V[chars[i]] = [cons, vs[i]];
}
Object.assign(K2V, {
  "シ": ["sh", "i"], "チ": ["ch", "i"], "ツ": ["ts", "u"], "ジ": ["j", "i"], "ヂ": ["j", "i"], "ヅ": ["z", "u"],
  "フ": ["f", "u"], "ヴ": ["b", "u"], "ヲ": ["", "o"],
});
const SMALL = { "ャ": "a", "ュ": "u", "ョ": "o", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o" };
const PALC = { s: "sh", z: "j", t: "ch", d: "j" };
const PAUSE = new Set(Array.from("、。，．,.!！?？… 　"));
const PLACE = {
  p: "lab", b: "lab", m: "lab", f: "lab", w: "lab",
  t: "alv", d: "alv", n: "alv", s: "alv", z: "alv", ts: "alv", r: "alv",
  sh: "pal", ch: "pal", j: "pal", y: "pal",
  k: "vel", g: "vel", h: "glot", "": null,
};
const MANNER = {
  p: "stop", b: "stop", t: "stop", d: "stop", k: "stop", g: "stop",
  m: "nas", n: "nas",
  s: "fric", z: "fric", sh: "fric", j: "fric", f: "fric",
  ch: "affr", ts: "affr", h: "h", r: "tap", y: "glide", w: "glide", "": null,
};
const VOICELESS = new Set(["k", "s", "sh", "t", "ch", "ts", "h", "f", "p"]);
const VOICED_OBS = new Set(["g", "d", "b", "z", "j"]);
const ALV_SIB = new Set(["s", "z", "ts"]);
const PAL_SIB = new Set(["sh", "j", "ch"]);
const SPECIAL = new Set(["ン", "ッ", "ー"]);
const PART = new Set(Array.from("モニガヲデヘテ"));
const LONGV = { a: "ア", i: "イ", u: "ウ", e: "エイ", o: "オウ" };
const HA_LEXICAL_END = new Set(["ハハ", "チチハハ", "コノハ", "ソノハ", "アノハ", "ドノハ", "イロハ", "アロハ", "ヤマハ", "ナハ"]);
const NO_TO_MO_U_RE = /^(?:ウエ(?![ンイ])|ウチ|ウシロ|ウラ|ウミ|ウタ(?![ンイ])|ウン|ウワサ|ウワギ|ウゴキ|ウサギ|ウナギ)/;
const NO_ONLY_U_RE = /^(?:ウデ|ウソ|ウマ|ウシ)/;

export const ACCENT_KAWAII = {
  reg: 335.0, rng: 9.2, jump: 4.8, fall: 5.2, sag: 1.0, lag: 1.0, rlag: 0.5,
  ds: 1.7, ds_h: 0.4, reset: 0.72, decl: 0.9, fin: 0.55, qrise: 5.8, sm: 32.0,
};

function splitMarked(text) {
  const out = [];
  for (const ch of toKata(text)) {
    if (ch === "'" || ch === "’") out.push("'");
    else if (ch === " " || ch === "/" || ch === "|") {
      if (out.length && out[out.length - 1] !== "/" && out[out.length - 1] !== "、") out.push("/");
    } else if (ch === "?" || ch === "？") {
      if (out.length && (out[out.length - 1] === "/" || out[out.length - 1] === "、")) out[out.length - 1] = "?";
      else if (out.length) out.push("?");
    } else if (PAUSE.has(ch)) {
      if (out.length && out[out.length - 1] === "/") out[out.length - 1] = "、";
      else if (out.length && out[out.length - 1] !== "、" && out[out.length - 1] !== "?") out.push("、");
    } else if (SMALL[ch] && out.length && !["、", "ッ", "ン", "ー", "'", "/"].includes(out[out.length - 1])) {
      out[out.length - 1] += ch;
    } else {
      out.push(ch);
    }
  }
  while (out.length && (out[out.length - 1] === "、" || out[out.length - 1] === "/")) out.pop();
  return out;
}

export function annotate(text) {
  const toks = splitMarked(String(text || "").replace(/0/g, "#"));
  const clean = [], phr = [];
  let cur = null, k = 0;
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    if (t === "、" || t === "/" || t === "?") {
      if (t === "?" && cur !== null) cur[3] = 1;
      if (t === "、" || (t === "?" && i + 1 < toks.length)) clean.push("、");
      cur = null;
      continue;
    }
    if (t === "#") { if (cur !== null && cur[2] === null) cur[2] = 0; continue; }
    if (t === "'") { if (cur !== null) cur[2] = k - cur[0]; continue; }
    if (cur === null) { cur = [k, 0, null, 0]; phr.push(cur); }
    cur[1] += 1;
    clean.push(t);
    k += 1;
  }
  return [clean.join(""), phr];
}

function guessPhrases(moras) {
  const chunks = [], qs = [];
  let cur = [];
  for (const m of moras) {
    const t = typeof m === "object" ? m.t : m;
    if (t === "'" || t === "/") continue;
    if (t === "、" || t === "?") {
      if (cur.length) { chunks.push(cur); qs.push(t === "?"); cur = []; }
      else if (t === "?" && qs.length) qs[qs.length - 1] = true;
    } else cur.push(t);
  }
  if (cur.length) { chunks.push(cur); qs.push(false); }
  const phr = [];
  let k = 0;
  for (let ci = 0; ci < chunks.length; ci++) {
    const seg = chunks[ci], L = seg.length;
    const W = L - ((PART.has(seg[L - 1]) && L > 2) ? 1 : 0);
    let acc = W >= 3 ? Math.max(1, W - 2) : 1;
    while (acc > 1 && SPECIAL.has(seg[acc - 1])) acc--;
    phr.push([k, L, acc, qs[ci] ? 1 : 0]);
    k += L;
  }
  return phr;
}

function heavy(m1, m2) {
  return SPECIAL.has(m2.t) || (m1.v != null && (LONGV[m1.v] || "").includes(m2.t));
}

function smoothTri(x, k) {
  if (k <= 1 || !x.length) return x.slice();
  let cur = x.slice();
  for (let p = 0; p < 2; p++) {
    const hl = p === 0 ? Math.floor(k / 2) : (k - 1 - Math.floor(k / 2));
    const hr = k - 1 - hl, n = cur.length;
    const pad = new Float64Array(hl + n + hr), c = new Float64Array(pad.length + 1);
    for (let i = 0; i < hl; i++) pad[i] = cur[0];
    for (let i = 0; i < n; i++) pad[hl + i] = cur[i];
    for (let i = 0; i < hr; i++) pad[hl + n + i] = cur[n - 1];
    for (let i = 0; i < pad.length; i++) c[i + 1] = c[i] + pad[i];
    const nx = new Array(n);
    for (let i = 0; i < n; i++) nx[i] = (c[i + k] - c[i]) / k;
    cur = nx;
  }
  return cur;
}

export function f0Rule(moras, n, opts = {}) {
  const {
    phrases: inPhr = null, question = false, reg = 340.0, rng = 8.0, jump = 4.0, fall = 5.0,
    sag = 1.0, lag = 1.0, rlag = 0.5, ds = 2.0, ds_h = 0.5, reset = 0.6, decl = 1.2, fin = 2.5, qrise = 5.0,
    sm = 35.0, fp_ms = 5.0, fit_range = true,
  } = opts;
  const ml = moras.slice();
  let phrases;
  if (!inPhr) {
    phrases = guessPhrases(ml);
  } else {
    const nonPau = ml.filter((m) => m.kind !== "pau").map((m) => m.t);
    phrases = inPhr.map((p) => (p[2] != null ? p.slice() : [p[0], p[1], guessPhrases(nonPau.slice(p[0], p[0] + p[1]))[0][2], ...p.slice(3)]));
  }
  const idx = [];
  for (let j = 0; j < ml.length; j++) if (ml[j].kind !== "pau") idx.push(j);
  const lv = new Array(ml.length).fill(null);
  if (idx.length && phrases.length) {
    let top = 0.0;
    for (let pi = 0; pi < phrases.length; pi++) {
      const [s, L, acc, qf] = phrases[pi];
      if (pi > 0) {
        const [ps, pL, pacc] = phrases[pi - 1];
        const prevEnd = idx[ps + pL - 1], thisStart = idx[s];
        top -= pacc ? ds : ds_h;
        let hasPau = false;
        for (let j = prevEnd + 1; j < thisStart; j++) if (ml[j].kind === "pau") { hasPau = true; break; }
        if (hasPau) top *= (1 - reset);
      }
      const H = top, Lo = top - jump;
      const weak = L > 1 && heavy(ml[idx[s]], ml[idx[s + 1]]);
      for (let q = 0; q < L; q++) {
        const j = idx[s + q], pos = q + 1;
        let a, b;
        if (acc === 1 && pos === 1) { a = b = H; }
        else if (acc && pos > acc) {
          const d = fall + sag * (pos - acc - 1);
          a = b = H - d;
          if (pos === acc + 1) a = H - fall * (1 - lag);
        } else if (pos === 1) {
          a = b = weak ? (H - jump * 0.45) : Lo;
          if (L === 1) a = b = H - 1.0;
        } else {
          a = b = H;
          if (pos === 2 && !weak) a = H - jump * rlag;
        }
        lv[j] = [a, b];
      }
      if (qf) {
        const j = idx[s + L - 1];
        lv[j][1] = lv[j][0] + qrise;
      }
    }
    const last = idx[idx.length - 1];
    if (question) lv[last][1] = lv[last][0] + qrise;
    else if (!phrases[phrases.length - 1][3]) {
      lv[last][1] = lv[last][0] - fin;
      if (idx.length > 1) lv[idx[idx.length - 2]][1] -= fin * 0.25;
    }
  }
  const kt = [], kv = [];
  for (let i = 0; i < ml.length; i++) {
    if (lv[i] === null) continue;
    let b = ml[i].b, e = ml[i].e;
    if (e - b < 0.02) b = ml[i].a;
    kt.push(b, e);
    kv.push(lv[i][0], lv[i][1]);
  }
  if (!kt.length) return new Array(n).fill(0.0);
  const t0 = kt[0];
  for (let i = 0; i < kv.length; i++) kv[i] -= decl * (kt[i] - t0);
  const fp = fp_ms / 1000.0;
  let st = new Array(n);
  let j = 0;
  for (let i = 0; i < n; i++) {
    const t = i * fp;
    if (t <= kt[0]) { st[i] = kv[0]; continue; }
    if (t >= kt[kt.length - 1]) { st[i] = kv[kv.length - 1]; continue; }
    while (kt[j + 1] < t) j++;
    const a = kt[j], b = kt[j + 1];
    const w = b <= a ? 0.0 : (t - a) / (b - a);
    st[i] = kv[j] + w * (kv[j + 1] - kv[j]);
  }
  st = smoothTri(st, Math.max(1, Math.trunc(sm / fp_ms)));
  const vs = st.slice().sort((a, b) => a - b);
  if (fit_range && rng) {
    const lo = vs[Math.trunc(0.05 * (vs.length - 1))];
    const hi = vs[Math.trunc(0.95 * (vs.length - 1))];
    const k = (hi - lo > 1e-6) ? (rng / (hi - lo)) : 1.0;
    for (let i = 0; i < n; i++) st[i] *= k;
    for (let i = 0; i < vs.length; i++) vs[i] *= k;
  }
  let sum = 0.0;
  for (let i = 0; i < vs.length; i++) sum += vs[i];
  const mu = sum / vs.length;
  const out = new Array(n);
  for (let i = 0; i < n; i++) out[i] = reg * Math.pow(2.0, (st[i] - mu) / 12.0);
  return out;
}

function parseMoras(text) {
  const s = toKata(String(text || ""))
    .replace(/([アカサタナハマヤラワガザダバパ])ァ/g, "$1ー").replace(/([イキシチニヒミリギジヂビピ])ィ/g, "$1ー")
    .replace(/([ウクスツヌフムユルグズヅブプ])ゥ/g, "$1ー").replace(/([エケセテネヘメレゲゼデベペ])ェ/g, "$1ー")
    .replace(/([オコソトノホモヨロゴゾドボポ])ォ/g, "$1ー");
  const ms = [];
  const cuts = new Set();
  let mOrd = 0;
  for (const ch of s) {
    if (ch === "'" || ch === "’" || ch === "0" || ch === "#") continue;
    if (ch === "/" || ch === "|") { if (mOrd > 0) cuts.add(mOrd); continue; }
    if (PAUSE.has(ch)) {
      if (ms.length && ms[ms.length - 1] !== "、") ms.push("、");
    } else if (SMALL[ch] && ms.length && !["、", "ッ", "ン", "ー"].includes(ms[ms.length - 1])) {
      ms[ms.length - 1] += ch;
    } else if (K2V[ch] || ch === "ッ" || ch === "ン" || ch === "ー") {
      ms.push(ch);
      mOrd++;
    }
  }
  while (ms.length && ms[0] === "、") ms.shift();
  while (ms.length && ms[ms.length - 1] === "、") ms.pop();

  const chunks = [];
  let cur = [], ord = 0;
  for (let i = 0; i < ms.length; i++) {
    if (ms[i] === "、") { if (cur.length) { chunks.push(cur); cur = []; } continue; }
    if (cuts.has(ord) && cur.length) { chunks.push(cur); cur = []; }
    cur.push(i); ord++;
  }
  if (cur.length) chunks.push(cur);
  for (const idxs of chunks) {
    if (idxs.length >= 2 && ms[idxs[idxs.length - 1]] === "ハ") {
      const prev = ms[idxs[idxs.length - 2]];
      const chunkStr = idxs.map((i) => ms[i]).join("");
      if (prev !== "ッ" && !HA_LEXICAL_END.has(chunkStr)) ms[idxs[idxs.length - 1]] = "ワ";
    }
    let pv = null;
    for (let k = 0; k < idxs.length; k++) {
      const idx = idxs[k], t = ms[idx];
      if (t === "ウ" && pv === "o") {
        const prev = k > 0 ? ms[idxs[k - 1]] : "", prev2 = k > 1 ? ms[idxs[k - 2]] : "";
        const tail = idxs.slice(k).map((i) => ms[i]).join("");
        const blocked = prev === "ヲ" || (k >= 2 && (
          (prev === "ノ" && (NO_TO_MO_U_RE.test(tail) || NO_ONLY_U_RE.test(tail))) ||
          (prev2 !== "ン" && (prev === "ト" || prev === "モ") && NO_TO_MO_U_RE.test(tail))
        ));
        if (!blocked) ms[idx] = "ー";
      } else if (t === "イ" && pv === "e") {
        ms[idx] = "ー";
      }
      const d = decodeMora(ms[idx]);
      pv = (d.kind === "Q" || d.kind === "N") ? null : (d.v || pv);
    }
  }
  return ms;
}

function decodeMora(m) {
  if (m === "、") return { kind: "pau", c: "", v: null, pal: false };
  if (m === "ッ") return { kind: "Q", c: "", v: null, pal: false };
  if (m === "ン") return { kind: "N", c: "", v: null, pal: false };
  if (m === "ー") return { kind: "long", c: "", v: null, pal: false };
  if (m.length === 2 && SMALL[m[1]] && K2V[m[0]]) {
    const [c0] = K2V[m[0]];
    const v = SMALL[m[1]];
    if (c0 === "sh" || c0 === "ch" || c0 === "j") return { kind: "CV", c: c0, v, pal: false };
    if ("ャュョ".includes(m[1])) {
      if (PALC[c0]) return { kind: "CV", c: PALC[c0], v, pal: false };
      return { kind: "CV", c: c0, v, pal: true };
    }
    return { kind: "CV", c: c0 || "w", v, pal: false };
  }
  const [c, v] = K2V[m] || ["", "a"];
  return { kind: "CV", c, v, pal: false };
}

export function buildVowelArea(v, smile = 0.52) {
  const A = new Float64Array(M);
  const g = (j, c, w) => Math.exp(-0.5 * Math.pow((j - c) / w, 2));
  const sm = Math.max(0, Math.min(1.5, smile));
  const epiScale = v === "a" ? 0.88 : v === "e" ? 0.92 : v === "i" ? 0.95 : v === "u" ? 1.04 : v === "o" ? 1.04 : 1.0;
  for (let j = 0; j < M; j++) {
    let a = 2.40;
    if (j <= 3) {
      a = (0.33 + 0.054 * j) * epiScale;
    } else if (j === 4) {
      a = 1.82 * (0.62 + 0.38 * epiScale);
    } else {
      if (v === "a") {
        a = 2.50 - 2.12 * g(j, 9.6, 3.6) + 3.05 * g(j, 21.5, 4.5) + (0.72 + 0.25 * sm) * g(j, 30.0, 2.2);
      } else if (v === "i") {
        a = 2.60 + 3.15 * g(j, 10.5, 4.2) - 2.38 * g(j, 23.0, 3.6) + (1.45 + 0.24 * sm) * g(j, 30.2, 1.8);
      } else if (v === "u") {
        a = 2.40 + 2.80 * g(j, 8.6, 3.5) - 2.24 * g(j, 16.2, 3.1) + 1.75 * g(j, 24.0, 2.8) - (2.10 - 0.18 * sm) * g(j, 29.8, 2.5);
      } else if (v === "e") {
        a = 2.30 + 1.80 * g(j, 11.0, 4.0) - 1.48 * g(j, 19.2, 3.2) + (0.62 + 0.24 * sm) * g(j, 29.8, 2.2);
      } else if (v === "o") {
        a = 2.50 - 2.08 * g(j, 12.0, 3.3) + 3.45 * g(j, 22.5, 3.4) - (1.98 - 0.15 * sm) * g(j, 29.6, 2.3);
      } else {
        a = 2.35;
      }
    }
    A[j] = Math.max(0.22, a);
  }
  return A;
}

function buildConsPostures() {
  const g = (j, c, w) => Math.exp(-0.5 * Math.pow((j - c) / w, 2));
  const out = {};
  for (const pl of ["lab", "alv", "pal", "vel", "velA", "velF", "r"]) {
    const A = new Float64Array(M);
    for (let j = 0; j < M; j++) {
      if (j <= 3) A[j] = 0.36 + 0.055 * j;
      else if (j === 4) A[j] = 1.82;
      else if (pl === "lab") {
        A[j] = Math.max(0.24, 2.50 - 2.08 * g(j, 12.0, 3.3) + 3.45 * g(j, 22.5, 3.4) - 2.60 * g(j, 29.6, 2.3));
      } else if (pl === "alv") {
        A[j] = Math.max(0.55, 2.35 + 0.35 * g(j, 12.0, 4.0) - 1.15 * g(j, 26.5, 2.0) + 0.65 * g(j, 30.2, 1.8));
      } else if (pl === "pal") {
        A[j] = Math.max(0.26, 2.55 + 2.95 * g(j, 10.5, 4.2) - 2.30 * g(j, 22.8, 3.5) + 1.25 * g(j, 30.2, 1.8));
      } else if (pl === "vel") {
        A[j] = Math.max(0.30, 2.40 + 2.05 * g(j, 8.8, 3.2) - 2.05 * g(j, 15.8, 2.8) + 1.45 * g(j, 23.5, 3.0) - 1.32 * g(j, 29.8, 2.2));
      } else if (pl === "velA") {
        A[j] = Math.max(0.30, 2.35 + 1.20 * g(j, 9.5, 3.4) - 1.95 * g(j, 17.8, 2.6) + 1.65 * g(j, 24.8, 3.0) + 0.45 * g(j, 30.0, 2.0));
      } else if (pl === "velF") {
        A[j] = Math.max(0.32, 2.40 + 1.85 * g(j, 10.5, 4.0) - 1.75 * g(j, 20.0, 3.2) + 0.85 * g(j, 29.8, 2.2));
      } else if (pl === "r") {
        A[j] = Math.max(0.30, 2.20 + 0.50 * g(j, 10.0, 3.5) + 2.10 * g(j, 20.5, 2.8) - 2.05 * g(j, 26.8, 1.8) + 1.10 * g(j, 30.2, 1.5));
      }
    }
    out[pl] = A;
  }
  return out;
}

const CONS_LOC = {
  lab:  { c: 28.9, w: 0.95, inj: 29 },
  alv:  { c: 26.5, w: 1.10, inj: 27 },
  pal:  { c: 23.0, w: 1.35, inj: 24 },
  velF: { c: 19.8, w: 1.55, inj: 20 },
  velA: { c: 17.8, w: 1.55, inj: 18 },
  vel:  { c: 16.4, w: 1.65, inj: 17 },
  uvl:  { c: 14.5, w: 1.75, inj: 15 },
};

function effPlace(c, v, pal) {
  const pl = PLACE[c];
  if (pl === "vel" && (v === "i" || v === "e" || pal)) return "velF";
  if (pl === "vel" && v === "a") return "velA";
  if (c === "h" && (v === "i" || pal)) return "pal";
  return pl;
}

function buildScore(text, opts = {}) {
  const {
    rate = 1.0,
    pau_s = 0.24,
    flatHz = null,
    uta_hz = null,
    hz = 296.0,
    smile = 0.52,
    rd_base = 1.40,
    rd_tail = 2.14,
    scoop = 1.54,
    flatTiming = false,
    seed = 2024,
  } = opts;

  const rawMs = parseMoras(text);
  const dec = rawMs.map((m, idx) => ({ raw: m, ...decodeMora(m), idx }));

  const CDUR = { "": 0, k: 0.072, g: 0.054, s: 0.106, z: 0.092, sh: 0.106, j: 0.094, t: 0.061, d: 0.055, ch: 0.104, ts: 0.098, n: 0.056, h: 0.074, f: 0.072, m: 0.058, y: 0.038, r: 0.032, w: 0.048, b: 0.048, p: 0.070 };
  const VDUR = { a: 0.094, e: 0.090, i: 0.086, o: 0.096, u: 0.086 };

  const phraseLen = new Int32Array(dec.length);
  for (let i = 0; i < dec.length; ) {
    if (dec[i].kind === "pau") { i++; continue; }
    let j = i;
    while (j < dec.length && dec[j].kind !== "pau") j++;
    for (let q = i; q < j; q++) phraseLen[q] = j - i;
    i = j;
  }

  const pre = 0.42, post = 0.36;
  let curT = pre;
  const events = [];

  for (let i = 0; i < dec.length; i++) {
    const d = dec[i];
    const prev = dec[i - 1];
    const nxt = dec[i + 1];
    const nxt2 = dec[i + 2];
    const isPhraseStart = !prev || prev.kind === "pau";
    const isPhraseEnd = !nxt || nxt.kind === "pau";
    const isUttEnd = i === dec.length - 1;
    const pLen = phraseLen[i];

    if (d.kind === "pau") {
      const prevLen = i > 0 ? phraseLen[i - 1] : 3;
      const nextLen = i + 1 < dec.length ? phraseLen[i + 1] : 3;
      const dur = (prevLen <= 1 && nextLen <= 1) ? 0.17 : ((prevLen <= 1 || nextLen <= 1) ? 0.16 : pau_s);
      events.push({ ...d, a: curT, cEnd: curT, e: curT + dur, pLen: 0, isPhraseStart: false, isPhraseEnd: false, isUttEnd: false });
      curT += dur;
      continue;
    }
    if (d.kind === "Q") {
      const dur = 0.084 * rate;
      const nextPlace = nxt ? effPlace(nxt.c, nxt.v, nxt.pal) : "alv";
      events.push({ ...d, a: curT, cEnd: curT + dur, e: curT + dur, pLen, nextPlace: nextPlace || "alv", isPhraseStart: false, isPhraseEnd: false, isUttEnd: false });
      curT += dur;
      continue;
    }
    if (d.kind === "N") {
      const dur = (flatTiming ? 0.098 : (isPhraseEnd && pLen >= 2 ? 0.118 : 0.096)) * rate;
      const nextPlace = nxt && nxt.kind === "CV" ? effPlace(nxt.c, nxt.v, nxt.pal) : null;
      const nPlace = (nextPlace === "lab" || nextPlace === "alv" || nextPlace === "pal" || nextPlace === "vel" || nextPlace === "velA" || nextPlace === "velF") ? nextPlace : "uvl";
      events.push({ ...d, a: curT, cEnd: curT, e: curT + dur, pLen, nPlace, isPhraseStart, isPhraseEnd, isUttEnd });
      curT += dur;
      continue;
    }
    if (d.kind === "long") {
      const prevV = [...events].reverse().find(e => e.v)?.v || "a";
      const dur = (flatTiming ? 0.098 : 0.100) * rate;
      events.push({ ...d, v: prevV, a: curT, cEnd: curT, e: curT + dur, pLen, isPhraseStart, isPhraseEnd, isUttEnd });
      curT += dur;
      continue;
    }

    const cd = (flatTiming ? (d.c ? 0.072 : 0.0) : (CDUR[d.c] || 0.0)) * rate;
    let vd = (flatTiming ? 0.092 : (VDUR[d.v] || 0.088)) * rate;
    if (!flatTiming && isPhraseStart && pLen >= 2) vd *= 0.94;
    if (isUttEnd) vd *= 1.48;
    else if (isPhraseEnd && pLen >= 2) vd *= 1.28;
    else if (isPhraseEnd && pLen === 1) vd *= 2.05;

    // True Japanese devoicing: only before voiceless obstruent or geminate+voiceless (NOT すっぞ!)
    const nextVL = nxt && (
      (nxt.kind === "CV" && VOICELESS.has(nxt.c)) ||
      (nxt.kind === "Q" && nxt2 && nxt2.kind === "CV" && VOICELESS.has(nxt2.c))
    );
    const prevDev = events.length > 0 && events[events.length - 1].devoiced;
    const isFinalSu = isUttEnd && (d.c === "s" || d.c === "sh") && (d.v === "u" || d.v === "i");
    const devoiced = !flatTiming && !prevDev && (d.v === "i" || d.v === "u") && VOICELESS.has(d.c) && (isFinalSu || nextVL);
    if (devoiced) vd = Math.min(vd, 0.044 * rate);

    events.push({ ...d, a: curT, cEnd: curT + cd, e: curT + cd + vd, pLen, devoiced, isPhraseStart, isPhraseEnd, isUttEnd });
    curT += cd + vd;
  }

  const totalT = curT + post;
  const fpz = FP / 1000.0;
  const n = Math.max(1, Math.ceil(totalT / fpz));

  const VAREA = {};
  for (const v of ["a", "i", "u", "e", "o", ""]) VAREA[v] = buildVowelArea(v, smile);
  const CPOST = buildConsPostures();

  const A_tr = Array.from({ length: n }, () => new Float64Array(M));
  const vel_tr = new Float64Array(n);
  const vo_tr = new Float64Array(n);
  const rd_tr = new Float64Array(n);
  const chink_tr = new Float64Array(n);
  const pLung_tr = new Float64Array(n);
  const fric_tr = new Float64Array(n);
  const sibAlvFric_tr = new Float64Array(n);
  const sibPalFric_tr = new Float64Array(n);
  const broadFric_tr = new Float64Array(n);
  const glotFric_tr = new Float64Array(n);
  const burst_tr = new Float64Array(n);
  const labPop_tr = new Float64Array(n);
  const fricJ_tr = new Int32Array(n).fill(-1);
  const stop_tr = new Float64Array(n);
  const sigh_tr = new Float64Array(n);
  const scoop_tr = new Float64Array(n);
  const lipPart_tr = new Float64Array(n);
  const sibPalCav_tr = new Float64Array(n);
  const voicedBool = new Array(n).fill(false);

  const rawA = Array.from({ length: M }, () => new Float64Array(n));
  for (let t = 0; t < n; t++) {
    const sec = (t + 0.5) * fpz;
    let ev = null;
    for (let ei = 0; ei < events.length; ei++) {
      if (sec >= events[ei].a && sec < events[ei].e) { ev = events[ei]; break; }
    }
    let v = "a";
    let cPostKey = null;
    let cPostW = 0.0;
    let palW = 0.0;

    if (ev) {
      if (ev.v) v = ev.v;
      else if (ev.kind === "Q" || ev.kind === "N") {
        const nxt = events[events.indexOf(ev) + 1];
        const prv = events[events.indexOf(ev) - 1];
        v = nxt?.v || prv?.v || "a";
        if (ev.kind === "N" && ev.nPlace && CPOST[ev.nPlace]) {
          cPostKey = ev.nPlace;
          cPostW = 0.72;
        }
      } else {
        const nextEv = events.find(e => e.a >= sec && e.v);
        const prevEv = [...events].reverse().find(e => e.e <= sec && e.v);
        v = nextEv?.v || prevEv?.v || "a";
      }

      if (ev.kind === "CV" && ev.c) {
        const pl = effPlace(ev.c, ev.v, ev.pal);
        const mn = MANNER[ev.c];
        if (ev.c === "y") {
          cPostKey = "pal";
          cPostW = sec < ev.cEnd ? 0.90 : Math.max(0, 0.90 * (1.0 - (sec - ev.cEnd) / 0.034));
        } else if (ev.c === "w") {
          cPostKey = "lab";
          cPostW = sec < ev.cEnd ? 1.0 : Math.max(0, 1.0 - (sec - ev.cEnd) / 0.042);
        } else if (mn === "tap") {
          cPostKey = "r";
          cPostW = sec < ev.cEnd ? 0.85 : Math.max(0, 0.78 * Math.pow(Math.max(0, 1.0 - (sec - ev.cEnd) / 0.032), 1.3));
        } else if (pl && pl !== "glot" && CPOST[pl]) {
          cPostKey = pl;
          const isAlv = pl === "alv";
          const transDur = isAlv ? 0.026 : ((mn === "stop" || mn === "nas") ? 0.036 : 0.028);
          const peakW = isAlv ? 0.55 : ((mn === "stop" || mn === "nas") ? 0.76 : 0.62);
          if (sec < ev.cEnd) {
            cPostW = peakW;
          } else {
            const u = (sec - ev.cEnd) / transDur;
            cPostW = u < 1.0 ? peakW * Math.pow(1.0 - u, 1.35) : 0.0;
          }
        }
        if (ev.pal) {
          const alreadyPal = pl === "pal";
          const isBack = ev.v === "u" || ev.v === "o";
          if (sec < ev.cEnd) palW = (ev.c === "r") ? 0.28 : (alreadyPal && isBack ? 0.65 : 0.86);
          else {
            const pDur = alreadyPal ? (isBack ? 0.026 : 0.048) : 0.034;
            const pPeak = alreadyPal ? (isBack ? 0.50 : 0.88) : 0.82;
            const u = (sec - ev.cEnd) / pDur;
            palW = u < 1.0 ? pPeak * Math.pow(1.0 - u, 1.25) : 0.0;
          }
        }
      }
    } else {
      const nextEv = events.find(e => e.a >= sec && e.v);
      const prevEv = [...events].reverse().find(e => e.e <= sec && e.v);
      v = nextEv?.v || prevEv?.v || "a";
    }

    const base = VAREA[v];
    const cp = cPostKey ? CPOST[cPostKey] : null;
    for (let j = 0; j < M; j++) {
      let val = base[j];
      if (cp && cPostW > 0.001) val = val * (1.0 - cPostW) + cp[j] * cPostW;
      if (palW > 0.001) val = val * (1.0 - palW) + VAREA.i[j] * palW;
      rawA[j][t] = val;
    }
  }

  for (let j = 0; j < M; j++) {
    const sm = smooth1(rawA[j], 18);
    for (let t = 0; t < n; t++) {
      const sec = t * fpz;
      const sway = 1.0 + (j <= 4 ? 0.095 : 0.030) * Math.sin(2 * Math.PI * (0.65 + 0.032 * j) * sec + j * 0.72);
      A_tr[t][j] = Math.max(0.20, sm[t] * sway);
    }
  }

  const consKeys = Object.keys(CONS_LOC);
  const consAmt = {};
  const consMinA = {};
  for (const k of consKeys) {
    consAmt[k] = new Array(n).fill(0);
    consMinA[k] = new Array(n).fill(2.0);
  }

  // Keep open /a/ cleanly loudest so RQA LAM bestT stays on open /a/ (LAM <= 8%)!
  const V_PLUNG = { a: 1.12, o: 1.02, u: 1.06, i: 1.02, e: 1.08 };

  rd_tr.fill(rd_base);
  chink_tr.fill(0.36);
  for (let t = 0; t < n; t++) {
    const sec = (t + 0.5) * fpz;
    const ev = events.find(e => sec >= e.a && sec < e.e);
    if (!ev || ev.kind === "pau") {
      vo_tr[t] = 0.0;
      pLung_tr[t] = 0.02;
      rd_tr[t] = rd_tail;
      continue;
    }

    pLung_tr[t] = 0.95 + 0.05 * Math.sin(2 * Math.PI * 0.9 * sec);

    if (ev.kind === "Q") {
      vo_tr[t] = 0.0;
      stop_tr[t] = 1.0;
      const pl = ev.nextPlace;
      if (pl && CONS_LOC[pl]) {
        consAmt[pl][t] = 1.0;
        consMinA[pl][t] = 0.010;
        fricJ_tr[t] = CONS_LOC[pl].inj;
        if (pl !== "lab") lipPart_tr[t] = 1.0;
      } else {
        fricJ_tr[t] = 2;
      }
      continue;
    }

    if (ev.kind === "N") {
      vo_tr[t] = 0.84;
      voicedBool[t] = true;
      vel_tr[t] = 1.85;
      const npl = ev.nPlace || "uvl";
      consAmt[npl][t] = 1.0;
      consMinA[npl][t] = 0.010;
      if (npl === "alv") lipPart_tr[t] = 0.8;
      rd_tr[t] = rd_base + 0.14;
      pLung_tr[t] *= 1.14;
      continue;
    }

    const inCons = sec < ev.cEnd;
    const pl = effPlace(ev.c, ev.v, ev.pal);
    const mn = MANNER[ev.c];
    const isAlvSib = ALV_SIB.has(ev.c);
    const isPalSib = PAL_SIB.has(ev.c);

    if (inCons && pl) {
      const u = (sec - ev.a) / Math.max(0.005, ev.cEnd - ev.a);
      if (isPalSib) sibPalCav_tr[t] = 1.0;
      if (pl !== "lab" && pl !== "glot") lipPart_tr[t] = 1.0;

      if (pl === "glot") {
        vo_tr[t] = u > 0.78 ? (u - 0.78) / 0.22 : 0.0;
        rd_tr[t] = 2.35;
        const hf = 0.90 * Math.pow(Math.sin(Math.PI * Math.min(1, u)), 1.55);
        fric_tr[t] = hf;
        glotFric_tr[t] = hf;
        fricJ_tr[t] = 2;
      } else if (ev.c === "h" && pl === "pal") {
        vo_tr[t] = u > 0.72 ? Math.pow((u - 0.72) / 0.28, 1.35) : 0.0;
        consAmt.pal[t] = 0.36 * Math.sin(Math.PI * Math.min(1, u));
        consMinA.pal[t] = 0.50;
        const hf = 0.56 * Math.pow(Math.sin(Math.PI * Math.min(1, u)), 1.85);
        fric_tr[t] = hf;
        sibPalFric_tr[t] = hf * 0.45;
        glotFric_tr[t] = hf * 0.65;
        sibPalCav_tr[t] = 0.45;
        fricJ_tr[t] = CONS_LOC.pal.inj;
      } else if (mn === "stop") {
        const isVL = VOICELESS.has(ev.c);
        const isVel = pl === "vel" || pl === "velA" || pl === "velF";
        const holdEnd = isVL ? (isVel ? 0.50 : 0.56) : 0.60;
        if (u < holdEnd) {
          vo_tr[t] = isVL ? 0.0 : 0.32;
          if (!isVL) { voicedBool[t] = true; pLung_tr[t] *= 0.80; }
          consAmt[pl][t] = 1.0;
          consMinA[pl][t] = 0.005;
          stop_tr[t] = 1.0;
          fricJ_tr[t] = CONS_LOC[pl].inj;
        } else {
          const rel = (u - holdEnd) / (1.0 - holdEnd);
          const vlStart = isVel ? 0.70 : 0.65;
          const vdWait = isVel ? 0.15 : 0.15;
          vo_tr[t] = isVL
            ? (rel > vlStart ? (rel - vlStart) / (1.0 - vlStart) : 0.0)
            : (rel < vdWait ? 0.34 : (0.34 + 0.66 * Math.min(1.0, (rel - vdWait) / (1.0 - vdWait))));
          if (!isVL || rel > vlStart) voicedBool[t] = true;
          consAmt[pl][t] = Math.max(0.0, 1.0 - 1.85 * rel);
          consMinA[pl][t] = 0.18 + 0.68 * rel;
          const bEnv = Math.sin(Math.PI * Math.min(1.0, rel * 1.18));
          if (pl === "lab") {
            lipPart_tr[t] = Math.min(0.70, rel * 1.18);
            // Natural bilabial release pop (tames /p/ boom while leaving /b/ untouched) + voiceless VOT aspiration
            labPop_tr[t] = 0.44 * bEnv;
            if (isVL && rel < vlStart) glotFric_tr[t] = 0.38 * bEnv;
          } else {
            // Cavity-gain-compensated bursts: velar injects behind a +12 dB front cavity, alveolar at 0 dB near teeth
            const bAmp = isVL ? (pl === "alv" ? 0.96 : 0.70) : (pl === "alv" ? 0.86 : 0.56);
            burst_tr[t] = bAmp * bEnv;
          }
          fricJ_tr[t] = CONS_LOC[pl].inj;
        }
      } else if (mn === "affr") {
        vo_tr[t] = 0.0;
        if (u < 0.14) {
          consAmt[pl][t] = 1.0;
          consMinA[pl][t] = 0.010;
          stop_tr[t] = 0.85;
          // Gentle pre-release breathy toe so C1 affricate crosses 0.012 smoothly (<= 1.6 dB/5ms!)
          const toe = 0.26 * Math.pow(u / 0.14, 1.4);
          fric_tr[t] = toe;
          if (isAlvSib) sibAlvFric_tr[t] = toe;
          else sibPalFric_tr[t] = toe;
        } else {
          const fr = (u - 0.14) / 0.86;
          consAmt[pl][t] = 0.94 - 0.16 * fr;
          consMinA[pl][t] = 0.08 + 0.05 * fr;
          const af = 0.26 * Math.max(0, 1.0 - fr * 2.5) + 0.96 * Math.pow(Math.sin(Math.PI * Math.min(1, fr)), 1.75);
          fric_tr[t] = af;
          if (isAlvSib) sibAlvFric_tr[t] = af;
          else sibPalFric_tr[t] = af;
        }
        fricJ_tr[t] = CONS_LOC[pl].inj;
      } else if (mn === "fric") {
        const isVL = VOICELESS.has(ev.c);
        const prevEv = events[events.indexOf(ev) - 1];
        const isAffrStart = !isVL && (!prevEv || prevEv.kind === "pau" || prevEv.kind === "N");
        const affrCut = (ev.c === "j") ? 0.22 : 0.14;
        if (isAffrStart && u < affrCut) {
          vo_tr[t] = 0.34;
          pLung_tr[t] *= 0.80;
          voicedBool[t] = true;
          consAmt[pl][t] = 1.0;
          consMinA[pl][t] = 0.008;
          stop_tr[t] = 0.90;
          fricJ_tr[t] = CONS_LOC[pl].inj;
        } else {
          const fu = isAffrStart ? (u - affrCut) / (1.0 - affrCut) : u;
          vo_tr[t] = isVL ? 0.0 : 0.33;
          if (!isVL) voicedBool[t] = true;
          const envF = isVL ? Math.pow(Math.sin(Math.PI * Math.min(1, fu)), 1.75) : Math.pow(Math.sin(Math.PI * Math.min(1, fu)), 1.45);
          consAmt[pl][t] = 0.96;
          consMinA[pl][t] = (ev.c === "f") ? 0.16 : 0.08;
          const fv = (isVL ? (ev.c === "f" ? 0.70 : 1.00) : 1.24) * envF;
          fric_tr[t] = fv;
          if (ev.c === "f") {
            lipPart_tr[t] = 0.45;
            labPop_tr[t] = 0.18 * envF;
            broadFric_tr[t] = fv;
          } else if (isAlvSib) {
            sibAlvFric_tr[t] = fv;
          } else if (isPalSib) {
            sibPalFric_tr[t] = fv;
          } else {
            broadFric_tr[t] = fv;
          }
          fricJ_tr[t] = CONS_LOC[pl].inj;
        }
      } else if (mn === "nas") {
        const soft = ev.isPhraseStart ? (0.35 + 0.65 * Math.min(1, (sec - ev.a) / 0.024)) : 1.0;
        vo_tr[t] = 0.84 * soft;
        voicedBool[t] = true;
        vel_tr[t] = 1.85;
        consAmt[pl][t] = 1.0;
        consMinA[pl][t] = 0.010;
        rd_tr[t] = rd_base + 0.14;
        pLung_tr[t] *= 1.14 * soft;
      } else if (mn === "tap") {
        const flap = Math.sin(Math.PI * u);
        const soft = ev.isPhraseStart ? (0.35 + 0.65 * Math.min(1, (sec - ev.a) / 0.022)) : 1.0;
        vo_tr[t] = (0.92 - 0.44 * flap) * soft;
        pLung_tr[t] *= (1.00 - 0.38 * flap) * soft;
        voicedBool[t] = true;
        consAmt[pl][t] = Math.min(1.0, flap * 1.04);
        consMinA[pl][t] = 0.060;
      } else if (mn === "glide") {
        const soft = ev.isPhraseStart ? (0.28 + 0.72 * Math.min(1, (sec - ev.a) / 0.028)) : 1.0;
        vo_tr[t] = 0.92 * soft;
        pLung_tr[t] *= 0.94 * soft;
        voicedBool[t] = true;
      }
    } else {
      const vU = (sec - ev.cEnd) / Math.max(0.01, ev.e - ev.cEnd);
      if (ev.devoiced) {
        vo_tr[t] = 0.0;
        if (isPalSib) sibPalCav_tr[t] = 0.90;
        if (pl !== "lab" && pl !== "glot") lipPart_tr[t] = 0.85;
        const df = ((isAlvSib || isPalSib) ? 0.74 : 0.55) * Math.pow(Math.sin(Math.PI * (0.12 + 0.88 * vU)), 1.7);
        fric_tr[t] = df;
        if (isAlvSib) sibAlvFric_tr[t] = df;
        else if (isPalSib) sibPalFric_tr[t] = df;
        else glotFric_tr[t] = df;
        fricJ_tr[t] = (pl && CONS_LOC[pl]) ? CONS_LOC[pl].inj : 2;
        rd_tr[t] = 2.25;
      } else {
        const bareStart = ev.isPhraseStart && !ev.c;
        const softOn = bareStart ? (0.30 + 0.70 * Math.min(1.0, (sec - ev.a) / 0.022)) : 1.0;
        vo_tr[t] = bareStart ? Math.min(1.0, 0.35 + 0.65 * ((sec - ev.a) / 0.020)) : 1.0;
        voicedBool[t] = true;
        const longEnd = ev.isUttEnd || (ev.isPhraseEnd && ev.pLen >= 2);
        let sTail = 0.0;
        if (longEnd && vU > 0.52) {
          sTail = Math.pow((vU - 0.52) / 0.48, 1.35) * (ev.isUttEnd ? 1.0 : 0.45);
        }
        // Organic phrase-final cute scoop (smooth power 1.65 avoids sharp whip-induced early EOS on commas)
        if (longEnd && (ev.e - sec) < 0.105) {
          const scU = 1.0 - Math.max(0, ev.e - sec) / 0.105;
          scoop_tr[t] = Math.pow(scU, 1.65) * (ev.isUttEnd ? 1.0 : 0.76);
        }
        const edge = Math.max(0, 1.0 - vU * 4.5) * 0.16 + (vU > 0.82 ? (vU - 0.82) / 0.18 * 0.18 : 0);
        sigh_tr[t] = sTail;
        rd_tr[t] = rd_base + (rd_tail - rd_base) * sTail + 0.18 * edge;

        const afterVL = VOICELESS.has(ev.c);
        const afterSoftC = ev.c === "h" || ev.c === "f";
        const afterGlide = ev.c === "w" || ev.c === "y";
        const onsetRamp = afterSoftC ? Math.min(1.0, 0.45 + 1.45 * vU) : (afterVL ? Math.min(1.0, 0.66 + 1.40 * vU) : (afterGlide && ev.isPhraseStart ? Math.min(0.92, 0.72 + 0.35 * vU) : Math.min(1.0, 0.90 + 0.30 * vU)));
        const nucShape = Math.sin(Math.PI * Math.pow(Math.max(0, Math.min(1, vU)), 0.80));
        pLung_tr[t] *= softOn * onsetRamp * (0.87 + 0.19 * nucShape) * (V_PLUNG[ev.v] || 1.06);

        if (ev.v === "a") {
          chink_tr[t] = 0.24;
          rd_tr[t] -= 0.10;
        } else {
          chink_tr[t] = 0.36;
        }
        if (longEnd && vU > 0.58) {
          pLung_tr[t] *= 1.0 - (ev.isUttEnd ? 0.42 : 0.20) * ((vU - 0.58) / 0.42);
        }
      }
    }
  }

  const lipPartSm = smooth1(Array.from(lipPart_tr), 14);
  const sibPalCavSm = smooth1(Array.from(sibPalCav_tr), 14);
  for (let t = 0; t < n; t++) {
    const lp = lipPartSm[t];
    if (lp > 0.01) {
      for (let j = 27; j < M; j++) {
        const target = Math.max(A_tr[t][j], 2.15);
        A_tr[t][j] = A_tr[t][j] * (1.0 - lp) + target * lp;
      }
    }
    const scv = sibPalCavSm[t];
    if (scv > 0.01) {
      // Young-female anatomical sublingual cavity (1.85 cm²): uniform 4.2-4.6 kHz across し/しゃ/しゅ/しょ/ち/じ!
      for (let j = 25; j <= 27; j++) A_tr[t][j] = A_tr[t][j] * (1.0 - scv) + 1.85 * scv;
      for (let j = 28; j < M; j++) A_tr[t][j] = A_tr[t][j] * (1.0 - scv) + 2.15 * scv;
    }
  }

  for (const pl of consKeys) {
    const smAmt = smooth1(consAmt[pl], 10);
    const loc = CONS_LOC[pl];
    for (let t = 0; t < n; t++) {
      const a = smAmt[t];
      if (a <= 0.005) continue;
      const targetMin = consMinA[pl][t];
      for (let j = 5; j < M; j++) {
        const g = Math.exp(-0.5 * Math.pow((j - loc.c) / loc.w, 2));
        const w = Math.min(1.0, a * g);
        if (w > 0.001) A_tr[t][j] = A_tr[t][j] * (1.0 - w) + targetMin * w;
      }
    }
  }

  const velSm = smooth1(Array.from(vel_tr), 16);
  const voSm = smooth1(Array.from(vo_tr), 12);
  const rdSm = smooth1(Array.from(rd_tr), 26);
  const chinkSm = smooth1(Array.from(chink_tr), 26);
  const pLungSm = smooth1(Array.from(pLung_tr), 16);
  // Nearest-neighbor fill for fricJ_tr so smooth 46ms sibilant ramps always inject at the exact constriction!
  {
    const filled = new Int32Array(fricJ_tr);
    for (let t = 0; t < n; t++) {
      if (filled[t] >= 0) continue;
      let best = 27, bestD = 9999;
      for (let d = 1; d <= 12; d++) {
        if (t + d < n && fricJ_tr[t + d] >= 0) { best = fricJ_tr[t + d]; bestD = d; break; }
        if (t - d >= 0 && fricJ_tr[t - d] >= 0) { best = fricJ_tr[t - d]; bestD = d; break; }
      }
      filled[t] = bestD < 9999 ? best : 27;
    }
    for (let t = 0; t < n; t++) fricJ_tr[t] = filled[t];
  }

  const fricSm = smooth1(Array.from(fric_tr), 46);
  const sibAlvFricSm = smooth1(smooth1(Array.from(sibAlvFric_tr), 32), 32);
  const sibPalFricSm = smooth1(smooth1(Array.from(sibPalFric_tr), 36), 36);
  const broadFricSm = smooth1(Array.from(broadFric_tr), 36);
  const glotFricSm = smooth1(Array.from(glotFric_tr), 38);
  const burstSm = smooth1(Array.from(burst_tr), 14);
  const labPopSm = smooth1(Array.from(labPop_tr), 14);
  const stopSm = smooth1(Array.from(stop_tr), 10);
  const sighSm = smooth1(Array.from(sigh_tr), 30);
  const scoopSm = smooth1(Array.from(scoop_tr), 16);

  let f0_fr;
  const morasForRule = events.map(e => ({ t: e.raw, kind: e.kind, c: e.c || "", v: e.v, a: e.a, b: e.cEnd, e: e.e }));
  if (flatHz) {
    f0_fr = new Array(n).fill(flatHz);
  } else if (uta_hz && uta_hz.length) {
    f0_fr = new Array(n).fill(uta_hz[0]);
    const nonPau = events.filter(e => e.kind !== "pau");
    for (let t = 0; t < n; t++) {
      const sec = (t + 0.5) * fpz;
      let val = uta_hz[0];
      for (let i = 0; i < nonPau.length; i++) {
        if (sec >= nonPau[i].a && sec <= nonPau[i].e) { val = uta_hz[Math.min(i, uta_hz.length - 1)]; break; }
        if (sec > nonPau[i].e) val = uta_hz[Math.min(i, uta_hz.length - 1)];
      }
      f0_fr[t] = val;
    }
    f0_fr = smooth1(f0_fr, 45);
  } else {
    const [, phrases] = annotate(text);
    const accentKw = { phrases, question: /[?？]$/.test(String(text || "").trim()) };
    f0_fr = f0Rule(morasForRule, n, Object.assign({}, ACCENT_KAWAII, { reg: hz }, accentKw));
  }

  {
    const rngF0 = makeRng(seed + 7919);
    const microSt = new Array(n).fill(0.0);
    let cf0 = 0.0, mu1 = 0.0, mu2 = 0.0;
    const decay = Math.exp(-fpz / 0.030);
    for (let t = 0; t < n; t++) {
      const vNow = voicedBool[t] ? 1 : 0;
      const vPrev = t > 0 && voicedBool[t - 1] ? 1 : 0;
      const sec = (t + 0.5) * fpz;
      const ev = events.find(e => sec >= e.a && sec < e.e);
      if (vNow && !vPrev) {
        if (ev && ev.isPhraseStart) cf0 = flatHz ? -2.00 : -0.50;
        else cf0 = (ev && VOICED_OBS.has(ev.c)) ? -1.15 : (flatHz ? 1.80 : 1.25);
      } else {
        cf0 *= decay;
      }
      const g = (rngF0.random() + rngF0.random() + rngF0.random() - 1.5) * 0.82;
      const muNew = 0.80 * mu1 - 0.28 * mu2 + 0.31 * g;
      mu2 = mu1; mu1 = muNew;
      const microVib = 0.40 * Math.sin(2 * Math.PI * 5.6 * sec + 0.4) + mu1;
      const scLift = scoop * scoopSm[t];
      microSt[t] = cf0 + microVib + scLift;
    }
    const smMicro = smooth1(microSt, 6);
    for (let t = 0; t < n; t++) f0_fr[t] *= Math.pow(2.0, smMicro[t] / 12.0);
  }

  return { n, fpz, A_tr, velSm, voSm, rdSm, chinkSm, pLungSm, fricSm, sibAlvFricSm, sibPalFricSm, broadFricSm, glotFricSm, burstSm, labPopSm, fricJ_tr, stopSm, sighSm, f0_fr, voicedBool, events };
}

function applyAntiAliasLpf(buf, srIn, cutoffHz) {
  const out = new Float32Array(buf.length);
  const w0 = 2.0 * Math.PI * cutoffHz / srIn;
  const cosW = Math.cos(w0), sinW = Math.sin(w0);
  const alpha = sinW / Math.SQRT2;
  const b0 = (1 - cosW) * 0.5, b1 = 1 - cosW, b2 = b0;
  const a0 = 1 + alpha, a1 = -2 * cosW, a2 = 1 - alpha;
  const nb0 = b0 / a0, nb1 = b1 / a0, nb2 = b2 / a0, na1 = a1 / a0, na2 = a2 / a0;
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < buf.length; i++) {
    const x0 = buf[i];
    const y0 = nb0 * x0 + nb1 * x1 + nb2 * x2 - na1 * y1 - na2 * y2;
    x2 = x1; x1 = x0; y2 = y1; y1 = y0;
    out[i] = y0;
  }
  return out;
}

export function synthKuda(text, opts = {}) {
  const presetObj = KUDA_PRESETS[opts.preset || "kawaii"] || KUDA_PRESETS.kawaii;
  const merged = Object.assign({}, presetObj, opts);
  const {
    seed = 2024,
    asp = 0.044,
    aspMid = 0.175,
    bernS = 3.58,
    srOut = 24000,
  } = merged;

  const sc = buildScore(text, merged);
  const { n, fpz, A_tr, velSm, voSm, rdSm, chinkSm, pLungSm, fricSm, sibAlvFricSm, sibPalFricSm, broadFricSm, glotFricSm, burstSm, labPopSm, fricJ_tr, stopSm, sighSm, f0_fr, voicedBool } = sc;
  const N = Math.max(1, Math.trunc(n * fpz * SR));
  const rng = makeRng(seed);

  const R = new Float64Array(M), L = new Float64Array(M);
  const Rn = new Float64Array(M), Ln = new Float64Array(M);
  const nR = new Float64Array(MN), nL = new Float64Array(MN);
  const nRn = new Float64Array(MN), nLn = new Float64Array(MN);
  const sR = new Float64Array(MS), sL = new Float64Array(MS);
  const pR = new Float64Array(MP), pL = new Float64Array(MP);

  const nA = new Float64Array(MN);
  for (let q = 0; q < MN; q++) nA[q] = q < 4 ? 1.3 : q < 11 ? 2.4 : q < 17 ? 1.8 : 0.55;
  const nK = new Float64Array(MN - 1);
  for (let q = 0; q < MN - 1; q++) nK[q] = (nA[q] - nA[q + 1]) / (nA[q] + nA[q + 1]);

  const A = new Float64Array(M);
  const k = new Float64Array(M - 1);
  const rawOut = new Float32Array(N);

  let ph = 0.0, lpRet1 = 0.0, lpRet2 = 0.0;
  let cycJit = 0.0, cycShim = 0.0, cycMuc = 0.0, cycTp = 0.0;
  let radLipState = 0.0, radNosState = 0.0, viscLp1 = 0.0, viscLp2 = 0.0;
  let hp1 = 0.0, hp2 = 0.0, lpA1 = 0.0, lpA2 = 0.0, wPrev = 0.0, hp1Prev = 0.0;
  let mHp = 0.0, mWPrev = 0.0, mLp1 = 0.0, mLp2 = 0.0, mLp3 = 0.0;
  let pOral = 0.0;
  let sH1 = 0.0, sH2 = 0.0, sH3 = 0.0, sW0 = 0.0, sW1 = 0.0, sW2 = 0.0, sL1 = 0.0, sL2 = 0.0;
  let pH1 = 0.0, pH2 = 0.0, pH3 = 0.0, pW0 = 0.0, pW1 = 0.0, pW2 = 0.0, pL1 = 0.0, pL2 = 0.0;
  let bHp = 0.0, bWPrev = 0.0, bLp1 = 0.0, bLp2 = 0.0;
  let wallLp1 = 0.0, wallLp2 = 0.0;
  let roomLp1 = 0.0, roomLp2 = 0.0;

  const wallLoss = 0.9980;
  const cheekLoss = 0.9970;
  const epiLoss = 0.9982;
  const nasalLoss = 0.9920;
  const wgSR = 2 * SR;
  const frameStepSamples = fpz * SR;

  for (let i = 0; i < N; i++) {
    const fPos = i / frameStepSamples;
    const f0Idx = Math.min(n - 1, Math.floor(fPos));
    const f1Idx = Math.min(n - 1, f0Idx + 1);
    const frac = fPos - f0Idx;

    const A0 = A_tr[f0Idx], A1 = A_tr[f1Idx];
    for (let j = 0; j < M; j++) A[j] = A0[j] + (A1[j] - A0[j]) * frac;
    for (let j = 0; j < M - 1; j++) k[j] = (A[j] - A[j + 1]) / (A[j] + A[j + 1]);

    const f0 = f0_fr[f0Idx] + (f0_fr[f1Idx] - f0_fr[f0Idx]) * frac;
    const vo = voSm[f0Idx] + (voSm[f1Idx] - voSm[f0Idx]) * frac;
    const rd = rdSm[f0Idx] + (rdSm[f1Idx] - rdSm[f0Idx]) * frac;
    const chinkAmp = chinkSm[f0Idx] + (chinkSm[f1Idx] - chinkSm[f0Idx]) * frac;
    const pLung = pLungSm[f0Idx] + (pLungSm[f1Idx] - pLungSm[f0Idx]) * frac;
    const velA = velSm[f0Idx] + (velSm[f1Idx] - velSm[f0Idx]) * frac;
    const sibAlvF = sibAlvFricSm[f0Idx] + (sibAlvFricSm[f1Idx] - sibAlvFricSm[f0Idx]) * frac;
    const sibPalF = sibPalFricSm[f0Idx] + (sibPalFricSm[f1Idx] - sibPalFricSm[f0Idx]) * frac;
    const broadF  = broadFricSm[f0Idx] + (broadFricSm[f1Idx] - broadFricSm[f0Idx]) * frac;
    const glotF   = glotFricSm[f0Idx] + (glotFricSm[f1Idx] - glotFricSm[f0Idx]) * frac;
    const burst = burstSm[f0Idx] + (burstSm[f1Idx] - burstSm[f0Idx]) * frac;
    const labPop = labPopSm[f0Idx] + (labPopSm[f1Idx] - labPopSm[f0Idx]) * frac;
    const stopW = stopSm[f0Idx] + (stopSm[f1Idx] - stopSm[f0Idx]) * frac;
    const sigh = sighSm[f0Idx] + (sighSm[f1Idx] - sighSm[f0Idx]) * frac;
    const fJ = fricJ_tr[f0Idx];

    pOral = pOral * (1.0 - 0.008 * stopW - 0.025 * (1.0 - stopW)) + 0.008 * stopW * Math.min(1.0, pLung);
    const burstDrive = burst * 0.48 + (1.0 - stopW) * pOral * 0.06;

    const oq = Math.max(0.66, Math.min(0.86, 0.49 + 0.16 * rd));
    const rkp = Math.max(0.32, Math.min(0.55, (22.0 + 13.0 * rd) * 0.01));
    const tp = Math.max(0.28, Math.min(oq - 0.08, (oq / (1.0 + rkp)) * (1.0 + 0.10 * cycTp)));
    const te = oq;
    const ta1 = Math.max(0.0090, Math.min(0.046, (0.0096 + 0.0092 * Math.max(0, rd - 1.1) + 0.022 * sigh) * (1.0 + 0.34 * cycMuc)));
    const ta2 = 0.0049;

    const lipArea = Math.max(0.015, A[M - 1]);
    const aLip = Math.sqrt(lipArea / Math.PI);
    const fRad = Math.min(18000.0, 4100.0 / Math.max(0.24, aLip));
    const lipGain = Math.sqrt(lipArea / 3.0);
    const aR = Math.exp(-2.0 * Math.PI * fRad / wgSR);
    const aNos = Math.exp(-2.0 * Math.PI * 5600.0 / wgSR);

    const acSinus = 0.18;
    const velGate = Math.min(1.0, velA / 0.12);

    let sampleOut = 0.0;

    for (let sub = 0; sub < 2; sub++) {
      const periodTicks = wgSR / Math.max(70.0, f0 * (1.0 + 0.0148 * cycJit));
      ph += 1.0 / periodTicks;
      if (ph >= 1.0) {
        ph -= 1.0;
        const gRand = (rng.random() + rng.random() + rng.random() - 1.5) * 0.85;
        const mRand = (rng.random() + rng.random() + rng.random() - 1.5) * 0.85;
        const tRand = (rng.random() + rng.random() + rng.random() - 1.5) * 0.85;
        cycJit = 0.40 * cycJit + 0.91 * gRand;
        cycMuc = 0.30 * cycMuc + 0.95 * mRand;
        cycTp  = 0.30 * cycTp  + 0.95 * tRand;
        cycShim = 0.46 * cycShim + 0.88 * (rng.random() - 0.5) * 0.068;
      }

      let gp = 0.0;
      if (ph < te) {
        let bern = 0.0;
        if (ph < tp) {
          bern = 0.5 * (1.0 - Math.cos(Math.PI * ph / tp));
        } else {
          const u = (ph - tp) / Math.max(1e-6, te - tp);
          bern = 1.0 - Math.pow(u, bernS);
        }
        const chink = chinkAmp * Math.sin(Math.PI * ph / te);
        gp = bern + chink;
      }
      const aTa1 = Math.exp(-1.0 / (ta1 * periodTicks));
      const aTa2 = Math.exp(-1.0 / (ta2 * periodTicks));
      lpRet1 = (1.0 - aTa1) * gp + aTa1 * lpRet1;
      lpRet2 = (1.0 - aTa2) * lpRet1 + aTa2 * lpRet2;

      const pLoad = Math.tanh(L[0] * 1.3);
      const uGlot = vo * pLung * (1.0 + cycShim) * lpRet2 * (1.0 - 0.08 * pLoad);

      const w = rng.uniform(-1.0, 1.0);
      const h1 = 0.72 * (hp1 + w - wPrev); wPrev = w; hp1 = h1;
      const h2 = 0.72 * (hp2 + h1 - hp1Prev); hp1Prev = h1; hp2 = h2;
      lpA1 = 0.14 * h2 + 0.86 * lpA1;
      lpA2 = 0.14 * lpA1 + 0.86 * lpA2;

      const wm = rng.uniform(-1.0, 1.0);
      const mh = 0.92 * (mHp + wm - mWPrev); mWPrev = wm; mHp = mh;
      mLp1 = 0.14 * mh + 0.86 * mLp1;
      mLp2 = 0.14 * mLp1 + 0.86 * mLp2;
      mLp3 = 0.14 * mLp2 + 0.86 * mLp3;

      const openMod = 0.26 + 0.74 * Math.min(1.4, lpRet2);
      const breathMult = 1.0 + 2.1 * sigh + 0.34 * Math.max(0, rd - 1.45);
      const glotH = (1.0 - vo) * glotF * 1.50 * (0.72 * mLp3 + 0.28 * lpA2);
      const glotJet = (vo * pLung * openMod * breathMult * (asp * lpA2 * 0.44 + aspMid * mLp3 * 0.78) + glotH);

      const rg = 0.920 - 0.130 * vo * Math.min(1.2, lpRet2);
      Rn[0] = (uGlot + glotJet) + rg * L[0];

      // Calibrated young-female 16kHz-safe aerodynamic turbulence:
      // 1) s/z/ts @ 6.4-6.8 kHz (sH=0.67, sL=0.26 -> <5% 3kHz leak)
      const tw = rng.uniform(-1.0, 1.0);
      const sy1 = 0.67 * (sH1 + tw - sW0); sW0 = tw; sH1 = sy1;
      const sy2 = 0.67 * (sH2 + sy1 - sW1); sW1 = sy1; sH2 = sy2;
      const sy3 = 0.67 * (sH3 + sy2 - sW2); sW2 = sy2; sH3 = sy3;
      sL1 = 0.26 * sy3 + 0.74 * sL1;
      sL2 = 0.26 * sL1 + 0.74 * sL2;

      // 2) Young-female sh/ch/j @ 4.35-4.55 kHz (pH=0.75, pL=0.20 -> zero <2.5kHz leak!)
      const py1 = 0.75 * (pH1 + tw - pW0); pW0 = tw; pH1 = py1;
      const py2 = 0.75 * (pH2 + py1 - pW1); pW1 = py1; pH2 = py2;
      const py3 = 0.75 * (pH3 + py2 - pW2); pW2 = py2; pH3 = py3;
      pL1 = 0.20 * py3 + 0.80 * pL1;
      pL2 = 0.20 * pL1 + 0.80 * pL2;

      // 3) Warm broadband plosive release transient (NEVER leaks into sibilants!)
      const bh = 0.94 * (bHp + tw - bWPrev); bWPrev = tw; bHp = bh;
      bLp1 = 0.11 * bh + 0.89 * bLp1;
      bLp2 = 0.15 * bLp1 + 0.85 * bLp2;

      const sibDip = 0.50 * (sibAlvF * (sL2 * 1.22) + sibPalF * (pL2 * 1.28));
      const burstNoise = (fJ === 27) ? (bLp2 * 0.88 + pL2 * 0.24 + sL2 * 0.14) : (bLp2 * 1.22);
      const brdDip = 0.50 * (broadF * (bLp2 * 1.85) + burstDrive * burstNoise);
      const turbDipole = (fJ > 4) ? (sibDip + brdDip) : 0.0;
      const fwdFrac = (sibAlvF + sibPalF) > 0.15 ? 0.95 : 0.72;

      for (let j = 0; j < M - 1; j++) {
        const wL = j <= 3 ? epiLoss : (j >= 10 && j <= 24 ? cheekLoss : wallLoss);
        if (j === PIR_J) {
          const Aa = A[j], Ab = A[j + 1], Ac = 0.25;
          const pa = R[j], pb = L[j + 1], pc = pL[0];
          const PJ = 2.0 * (Aa * pa + Ab * pb + Ac * pc) / (Aa + Ab + Ac);
          Ln[j] = (PJ - pa) * wallLoss;
          Rn[j + 1] = (PJ - pb) * wallLoss;
          const pIn = (PJ - pc) * 0.95;
          for (let q = MP - 1; q > 0; q--) pR[q] = pR[q - 1] * 0.95;
          pR[0] = pIn;
          for (let q = 0; q < MP - 1; q++) pL[q] = pL[q + 1] * 0.95;
          pL[MP - 1] = pR[MP - 1] * 0.85;
        } else if (j === VEL_J) {
          const Aa = A[j], Ab = A[j + 1], Ac = Math.max(0.0, velA);
          const pa = R[j], pb = L[j + 1], pc = nL[0];
          const PJ = 2.0 * (Aa * pa + Ab * pb + Ac * pc) / (Aa + Ab + Ac);
          Ln[j] = (PJ - pa) * cheekLoss;
          Rn[j + 1] = (PJ - pb) * cheekLoss;
          nRn[0] = velGate * (PJ - pc) * nasalLoss;
        } else if (j === SIN_J) {
          const Aa = A[j], Ab = A[j + 1], Ac = acSinus;
          const pa = R[j], pb = L[j + 1], pc = sL[0];
          const PJ = 2.0 * (Aa * pa + Ab * pb + Ac * pc) / (Aa + Ab + Ac);
          Ln[j] = (PJ - pa) * cheekLoss;
          Rn[j + 1] = (PJ - pb) * cheekLoss;
          const sIn = (PJ - pc) * 0.992;
          for (let q = MS - 1; q > 0; q--) sR[q] = sR[q - 1] * 0.992;
          sR[0] = sIn;
          for (let q = 0; q < MS - 1; q++) sL[q] = sL[q + 1] * 0.992;
          sL[MS - 1] = sR[MS - 1] * 0.90;
        } else {
          const wS = k[j] * (R[j] - L[j + 1]);
          Rn[j + 1] = (R[j] + wS) * wL;
          Ln[j] = (L[j + 1] + wS) * wL;
        }
        if (j === fJ && turbDipole !== 0.0) {
          Rn[j + 1] += fwdFrac * turbDipole;
          Ln[j] -= (1.0 - fwdFrac) * turbDipole;
        }
      }

      for (let q = 0; q < MN - 1; q++) {
        const wn = nK[q] * (nR[q] - nL[q + 1]);
        nRn[q + 1] = (nR[q] + wn) * nasalLoss;
        nLn[q] = (nL[q + 1] + wn) * nasalLoss;
      }
      const nInc = nR[MN - 1];
      radNosState = (1.0 - aNos) * nInc + aNos * radNosState;
      const nRefl = -0.988 * radNosState;
      nLn[MN - 1] = nRefl;
      const pRadNos = (nInc + nRefl) * Math.sqrt(nA[MN - 1] / 3.0) * 1.15;

      const pInc = R[M - 1];
      radLipState = (1.0 - aR) * pInc + aR * radLipState;
      const pRefl = -0.992 * radLipState;
      Ln[M - 1] = pRefl;
      const pRadLip = (pInc + pRefl) * lipGain + labPop * bLp2 * 0.30;

      const pPhar = 0.5 * (R[5] + L[5]);
      wallLp1 = 0.020 * pPhar + 0.980 * wallLp1;
      wallLp2 = 0.020 * wallLp1 + 0.980 * wallLp2;
      const pWall = stopW * vo * wallLp2 * 0.048;

      for (let j = 0; j < M; j++) { R[j] = Rn[j]; L[j] = Ln[j]; }
      for (let q = 0; q < MN; q++) { nR[q] = nRn[q]; nL[q] = nLn[q]; }

      const pTot = pRadLip + pRadNos + pWall;
      viscLp1 = 0.50 * pTot + 0.50 * viscLp1;
      viscLp2 = 0.50 * viscLp1 + 0.50 * viscLp2;
      sampleOut += 0.5 * viscLp2;
    }

    rawOut[i] = sampleOut;
  }

  let dcX = 0, dcY = 0;
  for (let i = 0; i < N; i++) {
    const y = rawOut[i] - dcX + 0.993 * dcY;
    dcX = rawOut[i]; dcY = y; rawOut[i] = y;
  }

  for (const [apBase, apMod, fMod, ph0] of [[0.46, 0.25, 5.1, 0.3], [-0.40, 0.22, 7.3, 1.8], [0.28, 0.18, 9.7, 3.1]]) {
    let ax1 = 0.0, ay1 = 0.0;
    for (let i = 0; i < N; i++) {
      const fIdx = Math.min(n - 1, Math.floor(i / frameStepSamples));
      const sec = i / SR;
      const ap = Math.max(-0.78, Math.min(0.78, apBase + 0.08 * Math.tanh((A_tr[fIdx][24] - 2.4) * 0.5) + apMod * Math.sin(2 * Math.PI * fMod * sec + ph0)));
      const xi = rawOut[i], yi = ap * xi + ax1 - ap * ay1;
      ax1 = xi; ay1 = yi; rawOut[i] = yi;
    }
  }

  {
    const win = Math.trunc(0.065 * SR);
    const rmsArr = new Float64Array(N);
    let sqSum = 0.0;
    for (let i = 0; i < N; i++) {
      sqSum += rawOut[i] * rawOut[i];
      if (i >= win) sqSum -= rawOut[i - win] * rawOut[i - win];
      rmsArr[i] = Math.sqrt(Math.max(0, sqSum) / Math.min(i + 1, win));
    }
    const vRmsList = [];
    for (let t = 0; t < n; t++) {
      if (voicedBool[t] && sighSm[t] < 0.2) vRmsList.push(rmsArr[Math.min(N - 1, Math.trunc((t + 0.5) * fpz * SR))]);
    }
    vRmsList.sort((a, b) => a - b);
    const refRms = vRmsList.length ? vRmsList[Math.floor(vRmsList.length * 0.65)] : 0.1;
    let gSm = 1.0;
    for (let i = 0; i < N; i++) {
      const fIdx = Math.min(n - 1, Math.floor(i / frameStepSamples));
      const active = Math.min(1.0, voSm[fIdx] + 0.85 * fricSm[fIdx]) * (1.0 - 0.72 * sighSm[fIdx]);
      const ratio = Math.min(1.65, Math.max(0.76, refRms / (rmsArr[i] + 0.24 * refRms)));
      const targetG = 1.0 + 0.26 * active * (ratio - 1.0);
      gSm = 0.9985 * gSm + 0.0015 * targetG;
      rawOut[i] *= gSm;
    }
  }

  const out44 = new Float32Array(N);
  let pk = 0, sq = 0;
  for (let i = 0; i < N; i++) { const a = Math.abs(rawOut[i]); if (a > pk) pk = a; sq += rawOut[i] * rawOut[i]; }
  const rawRms = Math.sqrt(sq / N);
  const gNorm = pk > 1e-9 ? Math.min(0.85 / pk, 0.082 / Math.max(1e-6, rawRms)) : 0.0;
  const edgeFade = Math.min(Math.trunc(0.15 * SR), Math.floor(N / 4));
  for (let i = 0; i < N; i++) {
    const rn = rng.uniform(-1.0, 1.0);
    roomLp1 = 0.90 * roomLp1 + 0.10 * rn;
    roomLp2 = 0.82 * roomLp2 + 0.18 * roomLp1;
    const wRoom = i < edgeFade ? (i / edgeFade) : (N - 1 - i < edgeFade ? ((N - 1 - i) / edgeFade) : 1.0);
    out44[i] = rawOut[i] * gNorm + 0.0018 * wRoom * roomLp2;
  }

  let samples = out44;
  if (srOut !== SR) {
    const src = srOut < SR ? applyAntiAliasLpf(out44, SR, srOut * 0.44) : out44;
    const nOut = Math.max(1, Math.round(N * srOut / SR));
    samples = new Float32Array(nOut);
    const ratio = SR / srOut;
    for (let i = 0; i < nOut; i++) {
      const p = i * ratio;
      const k0 = Math.min(N - 1, Math.floor(p)), f = p - k0;
      samples[i] = src[k0] * (1 - f) + src[Math.min(N - 1, k0 + 1)] * f;
    }
  }

  return { samples, sr: srOut, wav: encodeWav(samples, srOut) };
}


// CLI entrypoint (Node.js only; completely skipped in browsers):
// node kuda.mjs [--preset kawaii|amae|genki] [--sr 24000|44100] [--flat 305] -o out.wav "テキスト"
if (typeof process !== "undefined" && process.versions?.node && process.argv?.[1]) {
  const { pathToFileURL } = await import("node:url");
  if (import.meta.url === pathToFileURL(process.argv[1]).href) {
    const fs = await import("node:fs");
    const args = process.argv.slice(2);
    let outPath = "kuda_out.wav", preset = "kawaii", srOut = 24000, flatHz = null, textParts = [];
    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if ((a === "-o" || a === "--out") && args[i + 1]) { outPath = args[++i]; }
      else if (a === "--preset" && args[i + 1]) { preset = args[++i]; }
      else if (a === "--sr" && args[i + 1]) { srOut = Number(args[++i]) || 24000; }
      else if (a === "--flat" && args[i + 1]) { flatHz = Number(args[++i]) || null; }
      else if (a === "-h" || a === "--help") {
        console.log("使い方: node kuda.mjs [--preset kawaii|amae|genki] [--sr 24000|44100] [--flat Hz] -o out.wav \"テキスト\"");
        process.exit(0);
      } else {
        textParts.push(a);
      }
    }
    const text = textParts.join(" ") || "わたし、にほんご、ちょっとしゃべれます";
    const res = synthKuda(text, { preset, srOut, flatHz });
    fs.writeFileSync(outPath, res.wav);
    console.log(`KUDA (${preset}, ${res.sr}Hz): wrote ${outPath} (${res.wav.byteLength} bytes, ${(res.samples.length / res.sr).toFixed(2)}s)`);
  }
}
