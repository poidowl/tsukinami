#!/usr/bin/env node
/**
 * kuda.mjs — 0バイト純粋物理・分岐声道管デジタルウェーブガイド音声合成エンジン (管 / KUDA)
 *
 * 100% 純JS・ゼロ依存・0バイト重み・ゼロEQ・ゼロ別系統子音フィルタの物理声道管シンセサイザ。
 * 5極カスケードIIRの構造限界 (母音/子音分断・固定笛・高RQA停滞・低CPP・2kHz鼻声山) を
 * 真の分岐声道デジタルウェーブガイド (Kelly-Lochbaum) により根本から突破する。
 *
 * 物理構造:
 *   1. M=31 若年女性主声道管 (L=12.4cm @ 88.2kHz 2倍速 Kelly-Lochbaum 散乱格子)
 *      - Titze & Story (1997) 1:5 動的軟粘膜喉頭管カラー (j=0..3, 4.5-5.3kHz 輝き・固定笛ゼロ)
 *      - Dang, Honda & Suzuki (1994) 4.0cm 閉端副鼻腔側枝 (MS=10 @ SIN_J=15: 2.205kHz & 6.615kHz 反共振, 4.410kHz 透過)
 *      - 解剖学的鼻道管 (MN=23 @ VEL_J=14) + 連続軟口蓋ゲート (velGate: クリックゼロ)
 *      - 浅い若年梨状窩側枝 (MP=3 @ PIR_J=4, ~6.6kHz 反共振)
 *      - Flanagan (1972) 円形ピストン放射インピーダンス × √(A_exit) エネルギー保存則
 *   2. Fant-LF 滑らか2段指数リターン相 + 複合 Bernoulli-OpenChink 声門流 + 粘膜弾性(ta1/tp微小ゆらぎ):
 *      - Klatt & Klatt (1990) 3極温息・後部声門間隙気流 (1.0-2.6kHz: 4-8kHzヒス無しに高次倍音位相を自然解放)
 *      - 母音中央核の自然な声門圧膨らみ (CV境界オーバーシュート防止 -> 全抑揚で低RQA停滞)
 *   3. 声道狭窄部への直接ダイポール乱流注入 + 軟組織3D位相分散 (0.00 dB 振幅平坦オールパス)
 *      + Butterworth アンチエイリアシング・リサンプラ (24kHz / 44.1kHz 等に対応)
 */
import fs from "node:fs";
import { pathToFileURL } from "node:url";
import { encodeWav, f0Rule, makeRng, smooth1, toKata, annotate, ACCENT_KAWAII } from "./hitofude.mjs";

export const SR = 44100;
const FP = 5.0;
const M = 31;       // 12.4cm young female vocal tract (@ 88.2kHz -> dx = 0.40cm)
const MN = 23;      // 9.2cm nasal tract (opens on true nasals n/m/N)
const MS = 10;      // 4.0cm closed-end maxillary sinus branch (zeros @ 2.205kHz & 6.615kHz, passband @ 4.410kHz)
const MP = 3;       // 1.2cm shallow young piriform fossa (~6.6kHz anti-resonance)
const VEL_J = 14;
const SIN_J = 15;
const PIR_J = 4;

/** 物理声道プリセット (すべて純粋な物理パラメータのみ) */
export const KUDA_PRESETS = {
  kawaii: { hz: 296.0, smile: 0.50, rd_base: 1.54, rd_tail: 2.20, scoop: 1.65, asp: 0.042, aspMid: 0.195, rate: 1.00 },
  amae:   { hz: 286.0, smile: 0.44, rd_base: 1.68, rd_tail: 2.38, scoop: 1.95, asp: 0.048, aspMid: 0.220, rate: 1.08 },
  genki:  { hz: 312.0, smile: 0.62, rd_base: 1.44, rd_tail: 2.08, scoop: 1.50, asp: 0.038, aspMid: 0.175, rate: 0.94 },
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
const SIBILANT = new Set(["s", "sh", "z", "j", "ts", "ch"]);

function parseMoras(text) {
  const s = toKata(String(text || ""));
  const ms = [];
  for (const ch of s) {
    if (PAUSE.has(ch)) {
      if (ms.length && ms[ms.length - 1] !== "、") ms.push("、");
    } else if (SMALL[ch] && ms.length && !["、", "ッ", "ン", "ー"].includes(ms[ms.length - 1])) {
      ms[ms.length - 1] += ch;
    } else if (K2V[ch] || ch === "ッ" || ch === "ン" || ch === "ー") {
      ms.push(ch);
    }
  }
  while (ms.length && ms[0] === "、") ms.shift();
  while (ms.length && ms[ms.length - 1] === "、") ms.pop();
  return ms;
}

function decodeMora(m) {
  if (m === "、") return { kind: "pau", c: "", v: null };
  if (m === "ッ") return { kind: "Q", c: "", v: null };
  if (m === "ン") return { kind: "N", c: "", v: null };
  if (m === "ー") return { kind: "long", c: "", v: null };
  if (m.length === 2 && SMALL[m[1]] && K2V[m[0]]) {
    const [c0] = K2V[m[0]];
    const c = PALC[c0] || c0;
    return { kind: "CV", c, v: SMALL[m[1]], pal: c0 !== c || c === "sh" || c === "ch" || c === "j" };
  }
  const [c, v] = K2V[m] || ["", "a"];
  return { kind: "CV", c, v, pal: false };
}

/** 31節の若年女性声道断面積関数 A(j) [cm²] を生成する */
export function buildVowelArea(v, smile = 0.50) {
  const A = new Float64Array(M);
  const g = (j, c, w) => Math.exp(-0.5 * Math.pow((j - c) / w, 2));
  const sm = Math.max(0, Math.min(1.5, smile));
  const epiScale = v === "a" ? 0.88 : v === "e" ? 0.94 : v === "i" ? 1.08 : v === "u" ? 1.14 : v === "o" ? 1.03 : 1.0;
  for (let j = 0; j < M; j++) {
    let a = 2.45;
    if (j <= 3) {
      // Titze & Story (1997) 1:5 epilarynx collar
      a = (0.34 + 0.055 * j) * epiScale;
    } else if (j === 4) {
      a = 1.72 * (0.6 + 0.4 * epiScale);
    } else {
      if (v === "a") {
        a = 2.45 - 1.42 * g(j, 11.8, 3.8) + 2.15 * g(j, 23.2, 4.8) + (1.58 + 0.26 * sm) * g(j, 30.0, 2.5);
      } else if (v === "i") {
        a = 2.45 + 0.88 * g(j, 9.5, 3.8) - 0.96 * g(j, 21.0, 3.8) + (0.64 + 0.14 * sm) * g(j, 30.0, 2.0);
      } else if (v === "u") {
        a = 2.45 + 0.78 * g(j, 8.2, 3.0) - 1.24 * g(j, 15.8, 3.4) + 0.78 * g(j, 23.0, 2.7) - (0.86 - 0.22 * sm) * g(j, 29.6, 2.2);
      } else if (v === "e") {
        a = 2.45 + 0.64 * g(j, 9.5, 3.6) - 0.68 * g(j, 20.5, 3.6) + (1.12 + 0.20 * sm) * g(j, 29.6, 2.5);
      } else if (v === "o") {
        a = 2.45 - 1.32 * g(j, 11.6, 3.6) + 1.18 * g(j, 22.0, 3.2) - (0.98 - 0.24 * sm) * g(j, 29.6, 2.3);
      } else {
        a = 2.35;
      }
    }
    A[j] = Math.max(0.20, a);
  }
  return A;
}

const CONS_LOC = {
  lab: { c: 29.4, w: 1.40, inj: 29 },
  alv: { c: 25.8, w: 1.35, inj: 25 },
  pal: { c: 22.0, w: 1.70, inj: 22 },
  vel: { c: 16.0, w: 1.85, inj: 16 },
  uvl: { c: 14.2, w: 1.90, inj: 15 },
};

function buildScore(text, opts = {}) {
  const {
    rate = 1.0,
    pau_s = 0.24,
    flatHz = null,
    uta_hz = null,
    hz = 296.0,
    smile = 0.50,
    rd_base = 1.54,
    rd_tail = 2.20,
    scoop = 1.65,
    flatTiming = false,
    seed = 2024,
  } = opts;

  const rawMs = parseMoras(text);
  const dec = rawMs.map((m, idx) => ({ raw: m, ...decodeMora(m), idx }));

  const CDUR = { "": 0, k: 0.056, g: 0.048, s: 0.112, z: 0.062, sh: 0.114, j: 0.062, t: 0.052, d: 0.042, ch: 0.104, ts: 0.100, n: 0.054, h: 0.064, f: 0.072, m: 0.056, y: 0.048, r: 0.028, w: 0.046, b: 0.046, p: 0.054 };
  const VDUR = { a: 0.070, e: 0.056, i: 0.058, o: 0.074, u: 0.050 };

  const pre = 0.25, post = 0.27;
  let curT = pre;
  const events = [];

  for (let i = 0; i < dec.length; i++) {
    const d = dec[i];
    const prev = dec[i - 1];
    const nxt = dec[i + 1];
    const isPhraseStart = !prev || prev.kind === "pau";
    const isPhraseEnd = !nxt || nxt.kind === "pau";
    const isUttEnd = i === dec.length - 1;

    if (d.kind === "pau") {
      const dur = pau_s;
      events.push({ ...d, a: curT, cEnd: curT, e: curT + dur, isPhraseStart: false, isPhraseEnd: false, isUttEnd: false });
      curT += dur;
      continue;
    }
    if (d.kind === "Q") {
      const dur = 0.056 * rate;
      const nextPlace = nxt ? PLACE[nxt.c] : "alv";
      events.push({ ...d, a: curT, cEnd: curT + dur, e: curT + dur, nextPlace: nextPlace || "alv", isPhraseStart: false, isPhraseEnd: false, isUttEnd: false });
      curT += dur;
      continue;
    }
    if (d.kind === "N") {
      const dur = (flatTiming ? 0.096 : (isPhraseEnd ? 0.120 : 0.094)) * rate;
      events.push({ ...d, a: curT, cEnd: curT, e: curT + dur, isPhraseStart, isPhraseEnd, isUttEnd });
      curT += dur;
      continue;
    }
    if (d.kind === "long") {
      const prevV = [...events].reverse().find(e => e.v)?.v || "a";
      const dur = (flatTiming ? 0.100 : 0.105) * rate;
      events.push({ ...d, v: prevV, a: curT, cEnd: curT, e: curT + dur, isPhraseStart, isPhraseEnd, isUttEnd });
      curT += dur;
      continue;
    }

    const cd = (flatTiming ? (d.c ? 0.074 : 0.0) : (CDUR[d.c] || 0.0)) * rate;
    let vd = (flatTiming ? 0.086 : (VDUR[d.v] || 0.060)) * rate;
    if (!flatTiming && isPhraseStart) vd *= 0.88;
    if (isPhraseEnd) vd *= (isUttEnd ? 1.50 : 2.25);
    const isFinalSu = isUttEnd && (d.c === "s" || d.c === "sh") && (d.v === "u" || d.v === "i");
    const devoiced = isFinalSu;
    if (devoiced) vd *= 0.55;

    events.push({ ...d, a: curT, cEnd: curT + cd, e: curT + cd + vd, devoiced, isPhraseStart, isPhraseEnd, isUttEnd });
    curT += cd + vd;
  }

  const totalT = curT + post;
  const fpz = FP / 1000.0;
  const n = Math.max(1, Math.ceil(totalT / fpz));

  const VAREA = {};
  for (const v of ["a", "i", "u", "e", "o", ""]) VAREA[v] = buildVowelArea(v, smile);

  const A_tr = Array.from({ length: n }, () => new Float64Array(M));
  const vel_tr = new Float64Array(n);
  const vo_tr = new Float64Array(n);
  const rd_tr = new Float64Array(n);
  const chink_tr = new Float64Array(n);
  const pLung_tr = new Float64Array(n);
  const fric_tr = new Float64Array(n);
  const sib_tr = new Float64Array(n);
  const fricJ_tr = new Int32Array(n).fill(25);
  const stop_tr = new Float64Array(n);
  const sigh_tr = new Float64Array(n);
  const scoop_tr = new Float64Array(n);
  const voicedBool = new Array(n).fill(false);

  const vowelTarget = new Array(n).fill("");
  for (let t = 0; t < n; t++) {
    const sec = (t + 0.5) * fpz;
    let v = "";
    for (const ev of events) {
      if (sec >= ev.a && sec < ev.e) {
        if (ev.v) v = ev.v;
        else if (ev.kind === "Q") v = events[events.indexOf(ev) + 1]?.v || "";
        break;
      }
    }
    if (!v) {
      const nextEv = events.find(e => e.a >= sec && e.v);
      const prevEv = [...events].reverse().find(e => e.e <= sec && e.v);
      v = nextEv?.v || prevEv?.v || "a";
    }
    vowelTarget[t] = v;
  }

  for (let j = 0; j < M; j++) {
    const raw = new Array(n);
    for (let t = 0; t < n; t++) raw[t] = VAREA[vowelTarget[t]][j];
    const sm = smooth1(raw, 46);
    for (let t = 0; t < n; t++) {
      const sec = t * fpz;
      const sway = 1.0 + (j <= 4 ? 0.095 : 0.032) * Math.sin(2 * Math.PI * (0.65 + 0.032 * j) * sec + j * 0.72);
      A_tr[t][j] = Math.max(0.20, sm[t] * sway);
    }
  }

  const consAmt = { lab: new Array(n).fill(0), alv: new Array(n).fill(0), pal: new Array(n).fill(0), vel: new Array(n).fill(0), uvl: new Array(n).fill(0) };
  const consMinA = { lab: new Array(n).fill(2.0), alv: new Array(n).fill(2.0), pal: new Array(n).fill(2.0), vel: new Array(n).fill(2.0), uvl: new Array(n).fill(2.0) };

  rd_tr.fill(rd_base);
  chink_tr.fill(0.84);
  for (let t = 0; t < n; t++) {
    const sec = (t + 0.5) * fpz;
    const ev = events.find(e => sec >= e.a && sec < e.e);
    if (!ev || ev.kind === "pau") {
      vo_tr[t] = 0.0;
      pLung_tr[t] = 0.02;
      rd_tr[t] = rd_tail;
      continue;
    }

    pLung_tr[t] = 0.94 + 0.06 * Math.sin(2 * Math.PI * 0.9 * sec);

    if (ev.kind === "Q") {
      vo_tr[t] = 0.0;
      stop_tr[t] = 1.0;
      const pl = ev.nextPlace || "alv";
      consAmt[pl][t] = 1.0;
      consMinA[pl][t] = 0.015;
      fricJ_tr[t] = CONS_LOC[pl].inj;
      continue;
    }

    if (ev.kind === "N") {
      vo_tr[t] = 0.72;
      voicedBool[t] = true;
      vel_tr[t] = 1.25;
      consAmt.uvl[t] = 0.95;
      consMinA.uvl[t] = 0.05;
      rd_tr[t] = rd_base + 0.22;
      pLung_tr[t] *= 0.80;
      continue;
    }

    const inCons = sec < ev.cEnd;
    const pl = PLACE[ev.c];
    const mn = MANNER[ev.c];
    const isSib = SIBILANT.has(ev.c);

    if (inCons && pl) {
      const u = (sec - ev.a) / Math.max(0.005, ev.cEnd - ev.a);
      sib_tr[t] = isSib ? 1.0 : 0.0;
      if (pl === "glot") {
        vo_tr[t] = u > 0.62 ? (u - 0.62) / 0.38 : 0.0;
        rd_tr[t] = 2.40;
        fric_tr[t] = 0.56 * Math.pow(Math.sin(Math.PI * Math.min(1, u)), 1.5);
        fricJ_tr[t] = 2;
      } else if (mn === "stop") {
        const isVL = VOICELESS.has(ev.c);
        vo_tr[t] = isVL ? 0.0 : 0.62;
        if (!isVL) voicedBool[t] = true;
        if (u < 0.46) {
          consAmt[pl][t] = 1.0;
          consMinA[pl][t] = 0.014;
          stop_tr[t] = 1.0;
          if (isVL) fric_tr[t] = 0.14 * Math.pow(u / 0.46, 1.4);
          fricJ_tr[t] = CONS_LOC[pl].inj;
        } else {
          const rel = (u - 0.46) / 0.54;
          consAmt[pl][t] = 1.0 - 0.85 * rel;
          consMinA[pl][t] = 0.06 + 0.40 * rel;
          fric_tr[t] = (isVL ? 0.40 : 0.20) * Math.pow(Math.sin(Math.PI * (0.12 + 0.88 * rel)), 1.6);
          fricJ_tr[t] = CONS_LOC[pl].inj;
        }
      } else if (mn === "affr") {
        vo_tr[t] = 0.0;
        if (u < 0.26) {
          consAmt[pl][t] = 1.0;
          consMinA[pl][t] = 0.012;
          stop_tr[t] = 1.0;
          fric_tr[t] = 0.24 * Math.pow(u / 0.26, 1.25);
        } else {
          const fr = (u - 0.26) / 0.74;
          consAmt[pl][t] = 0.94 - 0.24 * fr;
          consMinA[pl][t] = 0.12 + 0.08 * fr;
          fric_tr[t] = 0.74 * Math.pow(Math.sin(Math.PI * (0.18 + 0.82 * fr)), 1.65);
        }
        fricJ_tr[t] = CONS_LOC[pl].inj;
      } else if (mn === "fric") {
        const isVL = VOICELESS.has(ev.c);
        vo_tr[t] = isVL ? 0.0 : 0.68;
        if (!isVL) voicedBool[t] = true;
        const envF = Math.pow(Math.sin(Math.PI * u), 1.5);
        consAmt[pl][t] = 0.94;
        consMinA[pl][t] = (ev.c === "f") ? 0.18 : 0.12;
        fric_tr[t] = (isVL ? 0.80 : 0.36) * envF;
        fricJ_tr[t] = CONS_LOC[pl].inj;
      } else if (mn === "nas") {
        vo_tr[t] = 0.72;
        voicedBool[t] = true;
        vel_tr[t] = 1.25;
        consAmt[pl][t] = 1.0;
        consMinA[pl][t] = 0.02;
        rd_tr[t] = rd_base + 0.20;
        pLung_tr[t] *= 0.80;
      } else if (mn === "tap") {
        vo_tr[t] = 0.82;
        voicedBool[t] = true;
        consAmt[pl][t] = Math.sin(Math.PI * u) * 0.88;
        consMinA[pl][t] = 0.12;
      } else if (mn === "glide") {
        vo_tr[t] = 0.92;
        voicedBool[t] = true;
        consAmt[pl][t] = (1.0 - u) * 0.72;
        consMinA[pl][t] = ev.c === "y" ? 0.38 : 0.44;
      }
    } else {
      const vU = (sec - ev.cEnd) / Math.max(0.01, ev.e - ev.cEnd);
      if (ev.devoiced) {
        vo_tr[t] = 0.0;
        sib_tr[t] = isSib ? 1.0 : 0.0;
        fric_tr[t] = 0.68 * Math.pow(Math.sin(Math.PI * (0.14 + 0.86 * vU)), 1.5);
        fricJ_tr[t] = PLACE[ev.c] ? CONS_LOC[PLACE[ev.c]].inj : 25;
        rd_tr[t] = 2.3;
      } else {
        vo_tr[t] = 1.0;
        voicedBool[t] = true;
        let sTail = 0.0;
        if (ev.isPhraseEnd && vU > 0.42) {
          sTail = Math.pow((vU - 0.42) / 0.58, 1.25);
        }
        const nextEv = events[events.indexOf(ev) + 1];
        const endsIsland = ev.isPhraseEnd || (nextEv && (nextEv.kind === "Q" || VOICELESS.has(nextEv.c)));
        if (endsIsland && (ev.e - sec) < 0.115) {
          const scU = 1.0 - Math.max(0, ev.e - sec) / 0.115;
          scoop_tr[t] = scU * scU * (ev.isPhraseEnd ? 1.0 : 0.85);
        }
        const edge = Math.max(0, 1.0 - vU * 4.2) * 0.20 + (vU > 0.80 ? (vU - 0.80) / 0.20 * 0.22 : 0);
        sigh_tr[t] = sTail;
        rd_tr[t] = rd_base + (rd_tail - rd_base) * sTail + 0.22 * edge;

        // Centered vowel-nucleus swell prevents CV boundary RMS overshoot
        const afterVL = VOICELESS.has(ev.c);
        const onsetRamp = afterVL ? Math.min(1.0, 0.58 + 1.25 * vU) : Math.min(1.0, 0.94 + 0.25 * vU);
        const nucShape = Math.sin(Math.PI * Math.pow(Math.max(0, Math.min(1, vU)), 0.80));
        pLung_tr[t] *= onsetRamp * (0.89 + 0.17 * nucShape);

        if (ev.v === "a") {
          pLung_tr[t] *= 1.18;
          chink_tr[t] = 0.26;
          rd_tr[t] -= 0.14;
        } else if (ev.v === "o") {
          pLung_tr[t] *= 0.96;
          chink_tr[t] = 0.88;
        } else {
          pLung_tr[t] *= 0.94;
          chink_tr[t] = 0.88;
        }
        if (ev.isPhraseEnd && vU > 0.52) {
          pLung_tr[t] *= 1.0 - 0.46 * ((vU - 0.52) / 0.48);
        }
      }
    }
  }

  for (const pl of Object.keys(CONS_LOC)) {
    const smAmt = smooth1(consAmt[pl], pl === "alv" ? 24 : 28);
    const loc = CONS_LOC[pl];
    for (let t = 0; t < n; t++) {
      const a = smAmt[t];
      if (a <= 0.005) continue;
      const targetMin = consMinA[pl][t];
      for (let j = 5; j < M; j++) {
        const g = Math.exp(-0.5 * Math.pow((j - loc.c) / loc.w, 2));
        const w = a * g;
        if (w > 0.001) A_tr[t][j] = A_tr[t][j] * (1.0 - w) + targetMin * w;
      }
    }
  }

  const velSm = smooth1(Array.from(vel_tr), 36);
  const voSm = smooth1(Array.from(vo_tr), 16);
  const rdSm = smooth1(Array.from(rd_tr), 30);
  const chinkSm = smooth1(Array.from(chink_tr), 32);
  const pLungSm = smooth1(Array.from(pLung_tr), 28);
  const fricSm = smooth1(Array.from(fric_tr), 102);
  const sibSm = smooth1(Array.from(sib_tr), 50);
  const stopSm = smooth1(Array.from(stop_tr), 34);
  const sighSm = smooth1(Array.from(sigh_tr), 32);
  const scoopSm = smooth1(Array.from(scoop_tr), 16);

  // Build F0 contour
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

  // Living-larynx micro-prosody (ribbon-smooth F0, zero 25Hz zig-zag)
  {
    const rngF0 = makeRng(seed + 7919);
    const microSt = new Array(n).fill(0.0);
    let cf0 = 0.0;
    let mu1 = 0.0, mu2 = 0.0;
    const decay = Math.exp(-fpz / 0.028);
    for (let t = 0; t < n; t++) {
      const vNow = voicedBool[t] ? 1 : 0;
      const vPrev = t > 0 && voicedBool[t - 1] ? 1 : 0;
      const sec = (t + 0.5) * fpz;
      const ev = events.find(e => sec >= e.a && sec < e.e);
      if (vNow && !vPrev) {
        if (ev && ev.isPhraseStart) cf0 = flatHz ? -2.35 : -0.60;
        else cf0 = (ev && VOICED_OBS.has(ev.c)) ? -1.45 : (flatHz ? 2.05 : 1.70);
      } else {
        cf0 *= decay;
      }
      const g = (rngF0.random() + rngF0.random() + rngF0.random() - 1.5) * 0.85;
      const muNew = 0.80 * mu1 - 0.28 * mu2 + 0.31 * g;
      mu2 = mu1; mu1 = muNew;
      const microVib = 0.42 * Math.sin(2 * Math.PI * 5.6 * sec + 0.4) + mu1;
      const scLift = scoop * scoopSm[t];
      microSt[t] = cf0 + microVib + scLift;
    }
    const smMicro = smooth1(microSt, 5);
    for (let t = 0; t < n; t++) f0_fr[t] *= Math.pow(2.0, smMicro[t] / 12.0);
  }

  return { n, fpz, A_tr, velSm, voSm, rdSm, chinkSm, pLungSm, fricSm, sibSm, fricJ_tr, stopSm, sighSm, f0_fr, voicedBool, events };
}

/** 2次 Butterworth アンチエイリアシング・ローパスフィルタ */
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

/**
 * テキストを分岐声道管デジタルウェーブガイドで音声合成する。
 * @param {string} text 日本語テキスト (ひらがな・カタカナ・句読点)
 * @param {object} [opts]
 * @param {"kawaii"|"amae"|"genki"} [opts.preset="kawaii"] 声道プリセット
 * @param {number} [opts.srOut=24000] 出力サンプルレート (24000 または 44100 等)
 * @param {number|null} [opts.flatHz=null] 固定ピッチ評価用 F0 [Hz]
 * @param {number[]|null} [opts.uta_hz=null] モーラごとの外部 F0 列 [Hz]
 * @param {number} [opts.seed=2024] 乱数シード
 * @returns {{ samples: Float32Array, sr: number, wav: Buffer }}
 */
export function synthKuda(text, opts = {}) {
  const presetObj = KUDA_PRESETS[opts.preset || "kawaii"] || KUDA_PRESETS.kawaii;
  const merged = Object.assign({}, presetObj, opts);
  const {
    seed = 2024,
    asp = 0.042,
    aspMid = 0.195,
    bernS = 3.55,
    srOut = 24000,
  } = merged;

  const sc = buildScore(text, merged);
  const { n, fpz, A_tr, velSm, voSm, rdSm, chinkSm, pLungSm, fricSm, sibSm, fricJ_tr, stopSm, sighSm, f0_fr, voicedBool } = sc;
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
  let tHp1 = 0.0, tHp2 = 0.0, tWPrev = 0.0, tH1Prev = 0.0, tLp = 0.0;
  let bHp = 0.0, bWPrev = 0.0, bLp = 0.0;
  let roomLp1 = 0.0, roomLp2 = 0.0;

  const wallLoss = 0.9978;
  const cheekLoss = 0.9964;
  const epiLoss = 0.9980;
  const nasalLoss = 0.9915;
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
    const fric = fricSm[f0Idx] + (fricSm[f1Idx] - fricSm[f0Idx]) * frac;
    const isSib = sibSm[f0Idx] + (sibSm[f1Idx] - sibSm[f0Idx]) * frac;
    const stopW = stopSm[f0Idx] + (stopSm[f1Idx] - stopSm[f0Idx]) * frac;
    const sigh = sighSm[f0Idx] + (sighSm[f1Idx] - sighSm[f0Idx]) * frac;
    const fJ = fricJ_tr[f0Idx];

    pOral = pOral * (1.0 - 0.005 * stopW - 0.018 * (1.0 - stopW)) + 0.005 * stopW * pLung;
    const burstDrive = (1.0 - stopW) * pOral * 0.20;

    const oq = Math.max(0.68, Math.min(0.88, 0.50 + 0.16 * rd));
    const rkp = Math.max(0.32, Math.min(0.56, (22.0 + 13.0 * rd) * 0.01));
    const tp = Math.max(0.28, Math.min(oq - 0.08, (oq / (1.0 + rkp)) * (1.0 + 0.10 * cycTp)));
    const te = oq;
    const ta1 = Math.max(0.0102, Math.min(0.052, (0.0116 + 0.011 * Math.max(0, rd - 1.1) + 0.022 * sigh) * (1.0 + 0.24 * cycMuc)));
    const ta2 = 0.0050;

    // Exact Flanagan (1972) circular-piston radiation with √(A_exit) energy conservation
    const lipArea = Math.max(0.015, A[M - 1]);
    const aLip = Math.sqrt(lipArea / Math.PI);
    const fRad = Math.min(18000.0, 4100.0 / Math.max(0.24, aLip));
    const lipGain = Math.sqrt(lipArea / 3.0);
    const aR = Math.exp(-2.0 * Math.PI * fRad / wgSR);
    const aNos = Math.exp(-2.0 * Math.PI * 5600.0 / wgSR);

    const acSinus = 0.90 - 0.16 * Math.tanh((A[22] - 2.2) * 0.7);
    const velGate = Math.min(1.0, velA / 0.12);

    let sampleOut = 0.0;

    for (let sub = 0; sub < 2; sub++) {
      const periodTicks = wgSR / Math.max(70.0, f0 * (1.0 + 0.0128 * cycJit));
      ph += 1.0 / periodTicks;
      if (ph >= 1.0) {
        ph -= 1.0;
        const gRand = (rng.random() + rng.random() + rng.random() - 1.5) * 0.85;
        const mRand = (rng.random() + rng.random() + rng.random() - 1.5) * 0.85;
        const tRand = (rng.random() + rng.random() + rng.random() - 1.5) * 0.85;
        cycJit = 0.40 * cycJit + 0.91 * gRand;
        cycMuc = 0.30 * cycMuc + 0.95 * mRand;
        cycTp  = 0.30 * cycTp  + 0.95 * tRand;
        cycShim = 0.46 * cycShim + 0.88 * (rng.random() - 0.5) * 0.058;
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

      // 1) Gentle upper air (2.6-4.2kHz)
      const w = rng.uniform(-1.0, 1.0);
      const h1 = 0.72 * (hp1 + w - wPrev); wPrev = w; hp1 = h1;
      const h2 = 0.72 * (hp2 + h1 - hp1Prev); hp1Prev = h1;
      lpA1 = 0.14 * h2 + 0.86 * lpA1;
      lpA2 = 0.14 * lpA1 + 0.86 * lpA2;

      // 2) 3-pole warm posterior-chink breath turbulence (1.0-2.6kHz, steep -18dB/oct above 3kHz)
      const wm = rng.uniform(-1.0, 1.0);
      const mh = 0.92 * (mHp + wm - mWPrev); mWPrev = wm; mHp = mh;
      mLp1 = 0.14 * mh + 0.86 * mLp1;
      mLp2 = 0.14 * mLp1 + 0.86 * mLp2;
      mLp3 = 0.14 * mLp2 + 0.86 * mLp3;

      const openMod = 0.26 + 0.74 * Math.min(1.4, lpRet2);
      const breathMult = 1.0 + 2.2 * sigh + 0.35 * Math.max(0, rd - 1.45);
      const glotJet = (vo * pLung * openMod * breathMult * (asp * lpA2 * 0.42 + aspMid * mLp3 * 0.78)
        + (1.0 - vo) * fric * (fJ <= 4 ? 0.58 : 0.0) * lpA2 * 0.44);

      const rg = 0.905 - 0.18 * vo * Math.min(1.2, lpRet2);
      Rn[0] = (uGlot + glotJet) + rg * L[0];

      // Place-dependent constriction turbulence dipole
      const tw = rng.uniform(-1.0, 1.0);
      const th1 = 0.66 * (tHp1 + tw - tWPrev); tWPrev = tw; tHp1 = th1;
      const th2 = 0.66 * (tHp2 + th1 - tH1Prev); tH1Prev = th1; tHp2 = th2;
      tLp = 0.36 * th2 + 0.64 * tLp;

      const bh = 0.42 * (bHp + tw - bWPrev); bWPrev = tw; bHp = bh;
      bLp = 0.30 * bh + 0.70 * bLp;

      const jetSig = isSib * tLp + (1.0 - isSib) * (bLp * 1.15);
      const turbDipole = (fric * 0.40 + burstDrive * 0.11) * pLung * jetSig;

      for (let j = 0; j < M - 1; j++) {
        const wL = j <= 3 ? epiLoss : (j >= 10 && j <= 24 ? cheekLoss : wallLoss);
        if (j === PIR_J) {
          const Aa = A[j], Ab = A[j + 1], Ac = 0.28;
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
          Rn[j + 1] += 0.65 * turbDipole;
          Ln[j] -= 0.35 * turbDipole;
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
      const pRadNos = (nInc + nRefl) * Math.sqrt(nA[MN - 1] / 3.0) * 0.72;

      const pInc = R[M - 1];
      radLipState = (1.0 - aR) * pInc + aR * radLipState;
      const pRefl = -0.992 * radLipState;
      Ln[M - 1] = pRefl;
      const pRadLip = (pInc + pRefl) * lipGain;

      for (let j = 0; j < M; j++) { R[j] = Rn[j]; L[j] = Ln[j]; }
      for (let q = 0; q < MN; q++) { nR[q] = nRn[q]; nL[q] = nLn[q]; }

      const pTot = pRadLip + pRadNos;
      viscLp1 = 0.465 * pTot + 0.535 * viscLp1;
      viscLp2 = 0.465 * viscLp1 + 0.535 * viscLp2;
      sampleOut += 0.5 * viscLp2;
    }

    rawOut[i] = sampleOut;
  }

  // Gentle 70Hz DC blocker
  let dcX = 0, dcY = 0;
  for (let i = 0; i < N; i++) {
    const y = rawOut[i] - dcX + 0.993 * dcY;
    dcX = rawOut[i]; dcY = y; rawOut[i] = y;
  }

  // Soft-tissue 3D micro-phase dispersion (0.00 dB magnitude)
  for (const [apBase, apMod, fMod, ph0] of [[0.46, 0.15, 5.1, 0.3], [-0.40, 0.14, 7.3, 1.8], [0.28, 0.11, 9.7, 3.1]]) {
    let ax1 = 0.0, ay1 = 0.0;
    for (let i = 0; i < N; i++) {
      const fIdx = Math.min(n - 1, Math.floor(i / frameStepSamples));
      const sec = i / SR;
      const ap = Math.max(-0.78, Math.min(0.78, apBase + 0.08 * Math.tanh((A_tr[fIdx][24] - 2.4) * 0.5) + apMod * Math.sin(2 * Math.PI * fMod * sec + ph0)));
      const xi = rawOut[i], yi = ap * xi + ax1 - ap * ay1;
      ax1 = xi; ay1 = yi; rawOut[i] = yi;
    }
  }

  // Light loudness balance
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
      const ratio = Math.min(1.45, Math.max(0.82, refRms / (rmsArr[i] + 0.30 * refRms)));
      const targetG = 1.0 + 0.18 * active * (ratio - 1.0);
      gSm = 0.9985 * gSm + 0.0015 * targetG;
      rawOut[i] *= gSm;
    }
  }

  const out44 = new Float32Array(N);
  let pk = 0;
  for (let i = 0; i < N; i++) { const a = Math.abs(rawOut[i]); if (a > pk) pk = a; }
  const gNorm = pk > 1e-9 ? (0.87 / pk) : 0.0;
  for (let i = 0; i < N; i++) {
    const rn = rng.uniform(-1.0, 1.0);
    roomLp1 = 0.90 * roomLp1 + 0.10 * rn;
    roomLp2 = 0.82 * roomLp2 + 0.18 * roomLp1;
    out44[i] = rawOut[i] * gNorm + 0.0044 * roomLp2;
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

  return { samples, sr: srOut, wav: Buffer.from(encodeWav(samples, srOut)) };
}

// CLI entrypoint: node kuda.mjs [--preset kawaii|amae|genki] [--sr 24000|44100] [--flat 305] -o out.wav "テキスト"
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
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
  console.log(`KUDA (${preset}, ${res.sr}Hz): wrote ${outPath} (${res.wav.length} bytes, ${(res.samples.length / res.sr).toFixed(2)}s)`);
}
