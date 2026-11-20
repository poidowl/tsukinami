// hitofude.mjs — 一筆彫り / 草薙版 (Single-Wire Subtractive Speech & Singing Synthesis in Pure JS)
// 外部パッケージ・外部データ・Node固有API 一切不使用（ブラウザ ES Module / Node.js / Deno / Bun 共通）。
//
// 【LLM向け設計原則】
//   音になる信号線は最初から最後まで「たった1本のホワイトノイズ x」のみを4段階で削って声と吐息にする。
//   - 正弦波オシレータ (sin/cos 音源)・固定波形の粒スタンプ (grain)・40段オールパス位相散らし 不要
//   - 有声/無声・子音帯・吐息はもちろん、呼気圧の漂い・ジッタ・ビブラートもすべて同じ1本のノイズ線 x からダシをとって彫る
//   - 帯域ごとの自動利得制御 (AGC) なし → 各ノブは他の段で打ち消されずほぼ直交に効く
//   - STFT 往復なし → 時間領域の1パス直列処理のみ

export const SR = 44100;
export const FP = 5.0; // 調音・韻律軌道のフレーム周期 (ms)

export const KNOB_KEYS = ["seed", "hz", "fscale", "rate", "g_vo", "tilt_w", "sigh", "jitter", "wander_st"];

export const PRESETS = {
  hitofude: {
    label: "澄み",
    description: "澄み（標準：非対称ベルヌーイ2唇扉×5極声道で彫る透明女声 350Hz）",
    seed: 2024, hz: 350.0, fscale: 1.17, rate: 1.26,
    g_vo: 0.89, damp: 0.08, shin: 1.0, tilt_w: 5, sigh: 0.0, jitter: 0.0026, wander_st: 0.18,
  },
  toiki: {
    label: "吐息",
    description: "吐息（非対称ベルヌーイ扉を句末で緩め、元の1本線の吐息へほどける女声 312Hz）",
    seed: 2024, hz: 312.0, fscale: 1.15, rate: 1.30,
    g_vo: 0.86, damp: 0.12, shin: 1.0, tilt_w: 6, sigh: 0.78, jitter: 0.0030, wander_st: 0.18,
  },
  alto: {
    label: "アルト",
    description: "大人アルト（落ち着いた中低域 220Hz・句末吐息つきのハスキー女声）",
    seed: 2024, hz: 220.0, fscale: 1.08, rate: 1.30,
    g_vo: 0.87, damp: 0.14, shin: 1.0, tilt_w: 5, sigh: 0.65, jitter: 0.0036, wander_st: 0.18,
  },
  sasayaki: {
    label: "囁き",
    description: "半有声囁き（浅い扉くびれG=0.64で倍音の谷に元のノイズの風を残す耳元ささやき）",
    seed: 2024, hz: 305.0, fscale: 1.15, rate: 1.30,
    g_vo: 0.64, damp: 0.16, shin: 1.0, tilt_w: 6, sigh: 0.85, jitter: 0.0036, wander_st: 0.16,
  },
  chibi: {
    label: "ちびっ子",
    description: "ちびっ子（短い声道 fscale=1.32・高ピッチ 400Hz・明るい粗削り tilt_w=4）",
    seed: 2024, hz: 400.0, fscale: 1.32, rate: 1.20,
    g_vo: 0.89, damp: 0.08, shin: 1.0, tilt_w: 4, sigh: 0.0, jitter: 0.0026, wander_st: 0.20,
  },
  ossan: {
    label: "おっさん",
    description: "おっさん（声門2唇粘膜扉×5極声道の再帰結合・低音 115Hz）",
    seed: 2024, hz: 115.0, fscale: 0.85, rate: 1.32,
    g_vo: 0.77, damp: 0.22, shin: 1.0,
    tilt_w: 5, sigh: 0.18, jitter: 0.0060, wander_st: 0.22,
  },
  hibiki: {
    label: "響",
    description: "響（母音ごとの色彩と拍のうねりを刻む、少し生意気な電子声）",
    seed: 2024, hz: 285.0, fscale: 1.12, rate: 1.21,
    g_vo: 0.86, damp: 0.11, shin: 1.0, tilt_w: 4, sigh: 0.34,
    jitter: 0.0028, wander_st: 0.13, character: 0.78,
  },
  hibiki_katari: {
    label: "語",
    description: "語（母音のつながり・句の終わりに反応して話し方が変わる電子声）",
    seed: 2024, hz: 288.0, fscale: 1.13, rate: 1.26,
    g_vo: 0.86, damp: 0.12, shin: 1.0, tilt_w: 5, sigh: 0.43,
    jitter: 0.0028, wander_st: 0.13, character: 0.38, edge: 0.22, cadence: 0.88,
  },
  hibiki_yorisoi: {
    label: "寄添",
    description: "寄添（息の残る静かな近接声。声の存在感を句に合わせて動かす）",
    seed: 2024, hz: 278.0, fscale: 1.105, rate: 1.33,
    g_vo: 0.85, damp: 0.15, shin: 1.0, tilt_w: 6, sigh: 0.67,
    jitter: 0.0027, wander_st: 0.14, character: 0.22, edge: 0.06,
    cadence: 0.52, closeness: 0.82,
  },
  hibiki_natsuku: {
    label: "懐",
    description: "懐（聞き慣れるほど輪郭が見える、音素の関係に応答する電子声）",
    seed: 2024, hz: 292.0, fscale: 1.14, rate: 1.28,
    g_vo: 0.865, damp: 0.12, shin: 1.0, tilt_w: 5, sigh: 0.48,
    jitter: 0.0025, wander_st: 0.11, character: 0.20, edge: 0.16,
    cadence: 0.50, closeness: 0.35, signature: 0.88,
  },
  hibiki_ibuki: {
    label: "息吹",
    description: "息吹（音程と声道の癖が同時に動く、言葉を受け止める電子声）",
    seed: 2024, hz: 295.0, fscale: 1.125, rate: 1.27,
    g_vo: 0.87, damp: 0.12, shin: 1.0, tilt_w: 5, sigh: 0.43,
    jitter: 0.0026, wander_st: 0.12, character: 0.15, edge: 0.10,
    cadence: 0.58, closeness: 0.28, signature: 0.68, gesture: 0.85,
  },
  hibiki_awa: {
    label: "泡",
    description: "泡（浮遊するささやきに、小さな歌心が混じる電子声）",
    seed: 2024, hz: 325.0, fscale: 1.20, rate: 1.27,
    g_vo: 0.81, damp: 0.16, shin: 1.0, tilt_w: 6, sigh: 0.76,
    jitter: 0.0031, wander_st: 0.20, character: 0.86, edge: 0.13,
  },
  hibiki_kiba: {
    label: "牙",
    description: "牙（低めで鋭く、拍頭がわずかに噛み付く電子声）",
    seed: 2024, hz: 250.0, fscale: 1.06, rate: 1.16,
    g_vo: 0.91, damp: 0.07, shin: 1.0, tilt_w: 4, sigh: 0.16,
    jitter: 0.0020, wander_st: 0.10, character: 0.68, edge: 0.84,
  },
  robot: {
    label: "ロボ",
    description: "冷凍ロボット（片道コム shin=0・周期ジッタ0・漂い0・強いくびれG=0.96）",
    seed: 2024, hz: 220.0, fscale: 1.06, rate: 1.15,
    g_vo: 0.96, damp: 0.0, shin: 0.0, tilt_w: 4, sigh: 0.0, jitter: 0.0, wander_st: 0.0,
  },
};

// 軽量・決定論的 32-bit PRNG (Mulberry32)：ブラウザでも Node でも同じ種から完全に同じ波形を返す
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

// ============================================================================
// 1. kotoba — かな文字列 -> 5msフレーム調音軌道 (F1..F3, 帯域ゲイン G1..G3, 子音帯 bands, 音量 loud)
// ============================================================================
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
  p: "lab", b: "lab", m: "lab", f: "lab", w: "lab", t: "alv", d: "alv", n: "alv", s: "alv", z: "alv", ts: "alv",
  r: "alv", sh: "pal", ch: "pal", j: "pal", y: "pal", k: "vel", g: "vel", h: "glot", "": null,
};
const MANNER = {
  p: "stop", b: "stop", t: "stop", d: "stop", k: "stop", g: "stop", m: "nas", n: "nas", s: "fric", z: "fric",
  sh: "fric", j: "fric", ch: "affr", ts: "affr", f: "fric", h: "h", r: "tap", y: "glide", w: "glide", "": null,
};
const VOICELESS = new Set(["k", "s", "sh", "t", "ch", "ts", "h", "f", "p"]);
const VOICED_OBS = new Set(["g", "d", "b", "z", "j"]);

// 日本語母音・子音の教科書テーブルと一筆彫り用の確定値
const KOTOBA_PRM = {
  alpha: 1.15, alpha3: 1.3, T: 30, Tvc: 30, Tvv: 40, Tpal: 40, undershoot: 80, f1on: 280, f1drop: true,
  smooth: 30, smooth_j: [30, 30, 30], ou_long: true,
  vdl: -4.0, vbg: 4.0, rdl: -4.0,
  VT: { a: [850, 1400, 2800], i: [330, 2750, 3300], u: [380, 1300, 2650], e: [520, 2350, 3000], o: [650, 1050, 2850] },
  LE: { lab: [0.75, 280], alv: [0.40, 1250], pal: [0.30, 1850], velF: [0.95, 300], velB: [1.05, 350] },
  gl: { y: [300, 2700, 3300], w: [360, 800, 2600] },
  nasT: { m: [280, 1100, 2500], n: [280, 1600, 2700], N: [300, 1300, 2600] },
  alvF2: 2350, alvF3: 3000,
  cues: ["fric", "stop", "nas", "h", "r"], sc: 6000, ssd: 1300, shc: 3600, shsd: 900, fg: 2.2, fvg: 0.15, ng2: 0.15, ndl: -1.2, asp: 3, bg: 3.0,
  r3: 2000, rtrack: true, cue_dl: true,
  rate: 1.0, fin: 1.5, pau: 0.35, qn: 0.10,
  sil: -30.0, qlev: -18.0, decl: 1.5, f0: 220.0, devmax: 0.045, Nlev: -1.0, fend: -6.0, fend_at: 0.16,
  CDUR: { "": 0, k: 70, g: 50, s: 100, z: 70, sh: 100, j: 70, t: 60, d: 40, ch: 80, ts: 80, n: 50, h: 70, f: 70, m: 50, y: 60, r: 25, w: 55, b: 40, p: 70 },
  VDUR: { a: 90, e: 90, i: 80, o: 90, u: 85 },
  VL: { a: 0.0, e: -0.5, i: -0.8, o: -0.3, u: -0.3 },
  CL: {
    k: [-12, -5], t: [-12, -5], p: [-12, -5], ch: [-12, -4], ts: [-12, -4], g: [-4, -2], d: [-4, -2], b: [-4, -2],
    s: [-3, -3], sh: [-3, -3], z: [-3, -2], j: [-3, -2], h: [-5, -4], f: [-5, -4], m: [-1.5, -1.5], n: [-1.5, -1.5],
    r: [-1.0, -1.0], w: [-0.5, -0.5], y: [-0.5, -0.5],
  },
  TAILT: { "stop-vl": -6.0, Q: -6.0, "fric-vl": -1.0, "h-vl": -1.0, stop: -2.0 },
  HEAD0: { h: -4.0, f: -4.0, r: -2.0, y: -1.0, w: -1.0 },
};

export function toKata(s) {
  let out = "";
  for (const ch of s) {
    const code = ch.codePointAt(0);
    out += (code >= 0x3041 && code <= 0x3096) ? String.fromCodePoint(code + 0x60) : ch;
  }
  return out;
}

// 句切れ前の「は→ワ」変換から除外する語彙（母・父母・笑い声・連体詞＋歯/葉・固有名詞）
const HA_LEXICAL_END = new Set(["ハハ", "チチハハ", "コノハ", "ソノハ", "アノハ", "ドノハ", "イロハ", "アロハ", "ヤマハ", "ナハ"]);
const HA_LAUGH_RE = /^(?:[アワウガエオ]|キャ|ギャ|ニャ)?ハ{2,}$/;
// 助詞「の・と・も」の直後で「おう→おー」長音化を止める自立語「う〜」語頭（農園=ノウエン・投影=トウエイ・初詣=ハツモウデ等は除外）
const NO_TO_MO_U_RE = /^(?:ウエ(?![ンイ])|ウチ|ウシロ|ウラ|ウミ|ウタ(?![ンイ])|ウン|ウワサ|ウワギ|ウゴキ|ウサギ|ウナギ)/;
const NO_ONLY_U_RE = /^(?:ウデ|ウソ|ウマ|ウシ)/;

function tokenizeKana(text, extraCuts = null) {
  const ms = [];
  const cuts = new Set();
  let moraIdx = 0;
  if (extraCuts) for (const c of extraCuts) cuts.add(c);
  for (const ch of toKata(text)) {
    if (ch === "'" || ch === "’") continue;
    if (ch === "/" || ch === "|") {
      if (moraIdx > 0) cuts.add(moraIdx);
      continue;
    }
    if (PAUSE.has(ch)) {
      if (ms.length && ms[ms.length - 1] !== "、") ms.push("、");
    } else if (SMALL[ch] && ms.length && !["、", "ッ", "ン", "ー"].includes(ms[ms.length - 1])) {
      ms[ms.length - 1] += ch;
    } else {
      ms.push(ch);
      moraIdx++;
    }
  }
  while (ms.length && ms[ms.length - 1] === "、") ms.pop();
  return { ms, cuts };
}

export function splitMoras(text) {
  return tokenizeKana(text).ms;
}

function parseKana(t, pv) {
  if (t === "ー") return ["", pv, false];
  const chars = Array.from(t);
  if (chars.length === 2 && SMALL[chars[1]]) {
    const [c] = K2V[chars[0]] || ["", pv];
    const v = SMALL[chars[1]];
    if (c === "sh" || c === "ch" || c === "j") return [c, v, false];
    if ("ャュョ".includes(chars[1])) {
      if (PALC[c]) return [PALC[c], v, false];
      return [c, v, true];
    }
    return [c || "w", v, false];
  }
  const [c, v] = K2V[t] || ["", pv];
  return [c, v, false];
}

function fi(s) { return Math.round((s * 1000) / FP); }

function linspace(a, b, k) {
  if (k <= 0) return [];
  if (k === 1) return [a];
  const st = (b - a) / (k - 1);
  const out = new Array(k);
  for (let i = 0; i < k; i++) out[i] = a + i * st;
  out[k - 1] = b;
  return out;
}

function clampSlice(n, a, b) {
  let s = a == null ? 0 : (a < 0 ? Math.max(0, n + a) : Math.min(n, a));
  let e = b == null ? n : (b < 0 ? Math.max(0, n + b) : Math.min(n, b));
  if (e < s) e = s;
  return [s, e];
}

function setslice(L, a, b, vals) {
  const [s, e] = clampSlice(L.length, a, b);
  if (typeof vals !== "object" || vals === null) {
    for (let i = s; i < e; i++) L[i] = vals;
  } else {
    for (let i = s; i < e; i++) L[i] = vals[i - s];
  }
}

function bisectRight(xp, v) {
  let lo = 0, hi = xp.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (v < xp[mid]) hi = mid; else lo = mid + 1;
  }
  return lo;
}

function interp(x, xp, fp) {
  const n = x.length;
  if (!xp.length) return new Array(n).fill(0.0);
  const out = new Array(n);
  const last = xp.length - 1;
  for (let i = 0; i < n; i++) {
    const v = x[i];
    if (v < xp[0]) { out[i] = fp[0]; continue; }
    if (v >= xp[last]) { out[i] = fp[last]; continue; }
    const j = bisectRight(xp, v) - 1;
    if (v === xp[j]) { out[i] = fp[j]; continue; }
    out[i] = fp[j] + ((fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j])) * (v - xp[j]);
  }
  return out;
}

export function smooth1(x, ms) {
  const k = Math.max(1, Math.trunc(ms / FP));
  const n = x.length;
  if (k <= 1 || n === 0) return Array.from(x);
  const N = n + 2 * k;
  const a = new Float64Array(N);
  for (let i = 0; i < k; i++) a[i] = x[0];
  for (let i = 0; i < n; i++) a[k + i] = x[i];
  for (let i = 0; i < k; i++) a[k + n + i] = x[n - 1];
  const off = Math.floor((k - 1) / 2);
  const out = new Array(n);
  const inv = 1.0 / k;
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

export function tracksFromKana(text, pre = 0.6, post = 0.1, params = null) {
  const P = Object.assign({}, KOTOBA_PRM, params || {});
  const { ms, cuts } = tokenizeKana(text, P.phraseCuts || null);
  // 読点「、」および空白・スラッシュ句切れごとにチャンク分けし、句末助詞「は→ワ」と「おう→おー」を適用
  const chunks = [];
  let curChunk = [], mOrd = 0;
  for (let j = 0; j < ms.length; j++) {
    if (ms[j] === "、") {
      if (curChunk.length) { chunks.push(curChunk); curChunk = []; }
      continue;
    }
    if (cuts.has(mOrd) && curChunk.length) {
      chunks.push(curChunk);
      curChunk = [];
    }
    curChunk.push(j);
    mOrd++;
  }
  if (curChunk.length) chunks.push(curChunk);

  for (const idxs of chunks) {
    if (P.ha_wa !== false && idxs.length >= 2 && ms[idxs[idxs.length - 1]] === "ハ") {
      const prev = ms[idxs[idxs.length - 2]];
      const chunkStr = idxs.map((i) => ms[i]).join("");
      if (prev !== "ッ" && !HA_LEXICAL_END.has(chunkStr) && !HA_LAUGH_RE.test(chunkStr)) {
        ms[idxs[idxs.length - 1]] = "ワ";
      }
    }
    if (P.ou_long) {
      let pv = null;
      for (let k = 0; k < idxs.length; k++) {
        const idx = idxs[k];
        const t = ms[idx];
        if (t === "ウ" && pv === "o") {
          const prev = k > 0 ? ms[idxs[k - 1]] : "";
          const prev2 = k > 1 ? ms[idxs[k - 2]] : "";
          const tail = idxs.slice(k).map((i) => ms[i]).join("");
          const blocked = prev === "ヲ" || (k >= 2 && (
            (prev === "ノ" && (NO_TO_MO_U_RE.test(tail) || NO_ONLY_U_RE.test(tail))) ||
            (prev2 !== "ン" && (prev === "ト" || prev === "モ") && NO_TO_MO_U_RE.test(tail))
          ));
          if (!blocked) ms[idx] = "ー";
        } else if (P.ei_long && t === "イ" && pv === "e") {
          ms[idx] = "ー";
        }
        pv = (ms[idx] === "ッ" || ms[idx] === "ン") ? null : parseKana(ms[idx], pv || "a")[1];
      }
    }
  }
  // モーラ種別と無声化判定 (i/u が無声子音に挟まれたとき母音無声化)
  const ml = [];
  let pv = "a";
  for (let j = 0; j < ms.length; j++) {
    const t = ms[j];
    const fin = (j + 1 === ms.length) || (ms[j + 1] === "、");
    const q = { t, cd: 0.0, vd: 0.0, p: 0.0, final: fin, dev: false };
    if (t === "、" || t === "ッ" || t === "ン") {
      Object.assign(q, { kind: t === "、" ? "pau" : (t === "ッ" ? "Q" : "N"), c: "", v: null, pal: false });
    } else {
      const [c, v, pal] = parseKana(t, pv);
      pv = v;
      Object.assign(q, { kind: "CV", c, v, pal });
    }
    ml.push(q);
  }
  for (let j = 0; j < ml.length; j++) {
    const q = ml[j];
    if (q.kind !== "CV") continue;
    const nx = j + 1 < ml.length ? ml[j + 1] : null;
    const nvl = nx !== null && ((nx.kind === "CV" && VOICELESS.has(nx.c)) || nx.kind === "Q");
    q.dev = !P.no_dev && (q.v === "i" || q.v === "u") && VOICELESS.has(q.c) && (nvl || (q.final && q.c === "s"));
  }
  // 拍ごとの子音長 cd / 母音長 vd
  const cd_s = P.cd_s !== undefined ? P.cd_s : 1.0;
  const vd_s = P.vd_s !== undefined ? P.vd_s : 1.0;
  for (const q of ml) {
    if (q.kind === "pau") { q.cd = 0.0; q.vd = P.pau; continue; }
    if (q.kind === "Q" || q.kind === "N") { q.cd = 0.0; q.vd = P.qn * ((q.final && q.kind === "Q") ? 1.3 : 1.0); continue; }
    let c = (P.CDUR[q.c] / 1000) * P.rate * cd_s;
    let v = (P.VDUR[q.v] / 1000) * P.rate * vd_s;
    if (q.dev) v = Math.min(v, P.devmax);
    if (q.final) v *= P.fin;
    q.cd = c; q.vd = v;
  }
  if (P.vd_ms) {
    let k = 0;
    for (const q of ml) {
      if (q.kind === "pau") continue;
      if (k < P.vd_ms.length && P.vd_ms[k] != null) q.vd = P.vd_ms[k] / 1000;
      k++;
    }
  }
  // 時間境界 a (開始), b (母音開始), e (終了)
  const seq = [];
  let tt = pre;
  for (const q of ml) {
    const a = tt, b = a + q.cd, e = b + q.vd;
    tt = e;
    const s = Object.assign({}, q, { a, b: q.kind === "Q" ? e : ((q.kind === "N" || q.kind === "pau") ? a : b), e });
    seq.push(s);
  }
  const n = fi(tt + post) + 1;

  // フォルマント軌道 F1..F3 (ローカス方程式 LE と調音点別ターゲット補間)
  const al = P.alpha, al3 = P.alpha3;
  const sc = (f) => [f[0] * al, f[1] * al, f[2] * al3];
  const vt = (s) => sc(P.VT[s.v]);
  const onset = (c, V, v, pal) => {
    const pl = PLACE[c], mn = MANNER[c];
    if (mn === "glide") return sc(P.gl[c]);
    if (pl === null) return V.slice();
    let f2 = V[1];
    if (pl !== "glot") {
      const [k, cc] = P.LE[pl !== "vel" ? pl : ((v === "i" || v === "e") ? "velF" : "velB")];
      f2 = k * V[1] + cc * al;
    }
    let f1 = V[0];
    if (P.f1drop) {
      if (["stop", "nas", "tap", "affr"].includes(mn)) f1 = Math.min(V[0], P.f1on * al);
      else if (mn === "fric") f1 = Math.min(V[0], (P.f1on + 80) * al);
    }
    let f3 = V[2];
    if (pl === "lab") f3 = V[2] - 250 * al3;
    else if (pl === "vel") f3 = (v === "i" || v === "e") ? Math.max(f2 + 400 * al, V[2] - 200 * al3) : Math.min(V[2], f2 + 900 * al);
    else if (pl === "alv") f3 = 0.5 * V[2] + 0.5 * 2900 * al3;
    else if (pl === "pal") f3 = Math.max(V[2], 3300 * al3);
    let O = [f1, f2, f3];
    if (pal) {
      const I = sc(P.VT.i);
      O = [0.5 * O[0] + 0.5 * I[0], 0.5 * O[1] + 0.5 * I[1], 0.5 * O[2] + 0.5 * I[2]];
    }
    return O;
  };
  const body = (c, V, v, O) => {
    const mn = MANNER[c];
    if (mn === "fric" || mn === "affr") return c === "f" ? O : [Math.min(V[0], 300 * al), O[1], O[2]];
    if (mn === "stop") {
      const B = O.slice();
      if (PLACE[c] === "alv") { B[1] = P.alvF2 * al; B[2] = Math.max(O[2], P.alvF3 * al3); }
      B[0] = Math.min(V[0], 260 * al);
      return B;
    }
    if (mn === "nas") {
      const B = sc(P.nasT[c]);
      if (c === "n" && v === "i") B[1] = 2200 * al;
      return B;
    }
    if (mn === "h") return V.slice();
    if (c === "r" && P.rtrack) return [350.0 * al, 1500.0 * al, P.r3];
    return O;
  };

  const kp = [];
  let cur = sc(P.VT.a), first = true;
  for (let j = 0; j < seq.length; j++) {
    const s = seq[j];
    if (s.kind === "pau") continue;
    if (s.kind === "Q" || s.kind === "N") {
      let nx = null;
      for (let q = j + 1; q < seq.length; q++) if (seq[q].kind === "CV") { nx = seq[q]; break; }
      const adj = nx !== null && seq[j + 1] === nx && Boolean(nx.c);
      if (s.kind === "N") {
        let B;
        if (adj) {
          const pl = PLACE[nx.c];
          B = sc(P.nasT[pl === "lab" ? "m" : ((pl === "alv" || pl === "pal") ? "n" : "N")]);
          if (pl === "vel") B[1] = onset(nx.c, vt(nx), nx.v, nx.pal)[1];
        } else B = sc(P.nasT.N);
        kp.push([s.a + P.Tvc / 1000, ...B], [s.e, ...B]);
      } else if (adj) {
        const V = vt(nx), B = body(nx.c, V, nx.v, onset(nx.c, V, nx.v, nx.pal));
        kp.push([s.a + P.Tvc / 1000, ...B], [s.e, ...B]);
      }
      continue;
    }
    const c = s.c, v = s.v;
    let V = vt(s);
    if (P.undershoot && (s.e - s.b) < P.undershoot / 1000) {
      const r = Math.max(0.4, (s.e - s.b) / (P.undershoot / 1000));
      V = [cur[0] + (V[0] - cur[0]) * r, cur[1] + (V[1] - cur[1]) * r, cur[2] + (V[2] - cur[2]) * r];
    }
    if (c) {
      const O = onset(c, V, v, s.pal), B = body(c, V, v, O);
      if (!first && s.b > s.a) kp.push([s.a, ...B]);
      kp.push([s.a + Math.min(P.Tvc / 1000, (s.b - s.a) * 0.5), ...B]);
      kp.push([Math.max(s.b - 0.005, s.a), ...B]);
      kp.push([s.b, ...O]);
      const Tt = (P.T + ((s.pal || MANNER[c] === "glide") ? P.Tpal : 0)) / 1000;
      kp.push([Math.min(s.b + Tt, s.e), ...V]);
    } else {
      kp.push([s.a + P.Tvv / 2000, ...V]);
    }
    const nxc = (j + 1 < seq.length && seq[j + 1].kind === "CV" && seq[j + 1].c) ? seq[j + 1].c : "";
    kp.push([s.e - (nxc ? P.Tvc / 1000 : P.Tvv / 2000), ...V]);
    cur = V.slice();
    first = false;
  }
  let Tr;
  if (!kp.length) {
    Tr = [new Array(n).fill(cur[0]), new Array(n).fill(cur[1]), new Array(n).fill(cur[2])];
  } else {
    kp.sort((a, b) => a[0] - b[0]);
    const tfr = new Array(n);
    for (let i = 0; i < n; i++) tfr[i] = (i * FP) / 1000;
    const xp = kp.map((q) => q[0]);
    const smj = P.smooth_j || [P.smooth, P.smooth, P.smooth];
    Tr = [0, 1, 2].map((j) => smooth1(interp(tfr, xp, kp.map((q) => q[j + 1])), smj[j]));
  }

  // 子音ノイズ帯域 bands とフォルマント減衰 G1..G3 / 閉鎖減衰 dl
  const G = [new Array(n).fill(1.0), new Array(n).fill(1.0), new Array(n).fill(1.0)];
  const dl = new Array(n).fill(0.0);
  const rawBands = [];
  const gset = (a, b, vals) => { for (let j = 0; j < 3; j++) setslice(G[j], a, b, vals[j]); };
  const gmul = (a, b, f) => {
    const [s0, e0] = clampSlice(n, a, b);
    for (let j = 0; j < 3; j++) for (let i = s0; i < e0; i++) G[j][i] *= f;
  };
  for (const s of seq) {
    const i0 = fi(s.a), ib = fi(s.b), ie = fi(s.e);
    if (s.kind === "Q") { setslice(dl, i0, ie, -6); continue; }
    if (s.kind === "N") { gset(i0, ie, [0.87, P.ng2, 0.5]); setslice(dl, i0, ie, P.ndl); continue; }
    if (s.kind !== "CV" || ib <= i0) continue;
    const c = s.c, v = s.v, nc = ib - i0;
    if (c === "m" || c === "n") { gset(i0, ib, [0.87, P.ng2, 0.5]); setslice(dl, i0, ib, P.ndl); }
    const fp_ = ["s", "z", "sh", "j"].includes(c) ? [i0, ib] : ((c === "ch" || c === "ts") ? [i0 + Math.floor(nc / 2), ib] : null);
    if (fp_) {
      const [cen, sd] = ["s", "z", "ts"].includes(c) ? [P.sc, P.ssd] : [P.shc, P.shsd];
      rawBands.push([fp_[0], fp_[1], cen, sd, P.fg + cen / 2500.0]);
      gmul(fp_[0], fp_[1], VOICED_OBS.has(c) ? 0.45 : P.fvg);
    }
    if (c === "h" || c === "f") {
      setslice(G[0], i0, ib, 0.4); setslice(G[1], i0, ib, 0.9); setslice(G[2], i0, ib, 0.9);
      if (v === "i" && c === "h") rawBands.push([i0, ib, 3500, 700, 1.0 + 3500 / 2500.0]);
    }
    if (["k", "g", "t", "d", "p", "b", "ch", "ts"].includes(c)) {
      const ce = i0 + ((c === "ch" || c === "ts") ? Math.floor(nc / 2) : Math.max(1, nc - P.asp));
      if (VOICED_OBS.has(c)) { gset(i0, ce, [0.8, 0.05, 0.05]); setslice(dl, i0, ce, P.vdl); }
      else setslice(dl, i0, ce, -6);
      const [cen, sd] = (c === "k" || c === "g") ? [((v === "i" || v === "e") ? 3000 : 1900), 500]
        : (["t", "d", "ch", "ts"].includes(c) ? [4500, 1000] : [1200, 900]);
      if (!VOICED_OBS.has(c)) rawBands.push([ce, Math.min(ce + 2, ib + 1), cen, sd, P.bg + cen / 2500.0]);
      if (c !== "ch" && c !== "ts") gset(ce, ib, VOICED_OBS.has(c) ? [1, 1, 1] : [0.4, 1, 1]);
    }
    if (c === "r") setslice(dl, i0, ib, P.rdl);
  }
  const Gs = G.map((g) => smooth1(g, 10));
  const dls = smooth1(dl, 10);

  // 音量対数曲線 loud と有声フラグ voiced
  const nxcls = (nx) => {
    if (!nx || nx.kind === "pau") return "end";
    if (nx.kind !== "CV") return nx.kind;
    if (!nx.c) return "V";
    return MANNER[nx.c] + (VOICELESS.has(nx.c) ? "-vl" : "");
  };
  let L = new Array(n).fill(P.sil);
  for (let j = 0; j < seq.length; j++) {
    const s = seq[j];
    const ia = fi(s.a), ib = fi(s.a + s.cd), ie = fi(s.e);
    const nx = j + 1 < seq.length ? seq[j + 1] : null;
    if (s.kind === "pau") continue;
    if (s.kind === "Q") { setslice(L, ia, ie, P.qlev); continue; }
    if (s.kind === "N") {
      setslice(L, ia, ie, P.Nlev);
    } else {
      if (P.CL[s.c] && ib > ia) {
        const [c1, c2] = P.CL[s.c];
        const im = ia + Math.trunc(0.7 * (ib - ia));
        setslice(L, ia, im, c1);
        setslice(L, im, ib, c2);
      }
      const lv = P.VL[s.v] + (s.dev ? -6 : 0);
      setslice(L, ib, ie, lv);
      if (P.HEAD0[s.c] !== undefined) {
        const k = Math.min(8, ie - ib);
        setslice(L, ib, ib + k, linspace(lv + P.HEAD0[s.c], lv, k));
      } else {
        const k = Math.min(3, ie - ib);
        if (k > 0) {
          const st = ib > 0 ? L[ib - 1] : P.sil;
          setslice(L, ib, ib + k, linspace(Math.min(st, lv - 3), lv, k));
        }
      }
    }
    const cls = nxcls(nx);
    if (cls === "end") {
      const k = s.kind === "CV" ? (ie - ib) : (ie - ia);
      const h = Math.trunc(k * P.fend_at);
      if (k - h > 0) setslice(L, ie - k + h, ie, linspace(L[ie - k + h], P.fend, k - h));
    } else if (P.TAILT[cls] !== undefined) {
      const lv = L[ie - 1];
      const k = Math.min(12, ie - ib);
      setslice(L, ie - k, ie, linspace(lv, lv + P.TAILT[cls] * 1.5, k));
    }
  }
  const dc = linspace(0, 1, n);
  for (let i = 0; i < n; i++) L[i] -= P.decl * dc[i];
  L = smooth1(L, 10);
  let mx = -Infinity;
  for (let i = 0; i < n; i++) if (L[i] > mx) mx = L[i];
  const loud = L.map((v) => v - mx);

  const vo = new Array(n).fill(false);
  for (const s of seq) {
    const a = s.a, b = s.a + s.cd, e = s.e;
    if (s.kind === "pau" || s.kind === "Q") continue;
    if (s.kind === "N" || !VOICELESS.has(s.c)) setslice(vo, fi(a), fi(b), true);
    if (!s.dev) setslice(vo, fi(b), fi(e), true);
  }

  return {
    fp_ms: FP, n,
    F1: Tr[0], F2: Tr[1], F3: Tr[2],
    G1: Gs[0], G2: Gs[1], G3: Gs[2],
    dl: dls, loud, voiced: vo,
    bands: rawBands.map(([a, b, c, d, g]) => [(a * FP) / 1000, (b * FP) / 1000, c, d, g]),
    moras: seq.map((s) => ({ t: s.t, kind: s.kind, c: s.c, v: s.v, a: s.a, b: s.b, e: s.e })),
  };
}

// ============================================================================
// 2. accent — 東京式ピッチアクセント推定 & 手動韻律記号 (' 核, 0 平板, / 句切れ, 、 間, ? 疑問)
// ============================================================================
const SPECIAL = new Set(["ン", "ッ", "ー"]);
const PART = new Set(Array.from("モニガヲデヘテ"));
const SMALL_SET = new Set(Array.from("ャュョァィゥェォ"));
const LONGV = { a: "ア", i: "イ", u: "ウ", e: "エイ", o: "オウ" };

export const ACCENT_NORMAL = { reg: 340.0, rng: 8.0, jump: 4.0, fall: 5.0, sag: 1.0, lag: 1.0, rlag: 0.5, ds: 2.0, ds_h: 0.5, reset: 0.6, decl: 1.2, fin: 3.0, qrise: 5.0, sm: 35.0 };
export const ACCENT_CUTE = { reg: 410.0, rng: 10.0, jump: 5.6, fall: 6.0, sag: 1.2, lag: 1.0, rlag: 0.5, ds: 2.0, ds_h: 0.4, reset: 0.7, decl: 1.0, fin: 2.0, qrise: 6.0, sm: 30.0 };

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
    } else if (SMALL_SET.has(ch) && out.length && !["、", "ッ", "ン", "ー", "'", "/"].includes(out[out.length - 1])) {
      out[out.length - 1] += ch;
    } else {
      out.push(ch);
    }
  }
  while (out.length && (out[out.length - 1] === "、" || out[out.length - 1] === "/")) out.pop();
  return out;
}

export function annotate(text) {
  const toks = splitMarked(text.replace(/0/g, "#"));
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

function guessPhrases(moras, accent = "ante", split = false, minlen = 3) {
  let ts = typeof moras === "string" ? splitMarked(moras) : moras.map((m) => (typeof m === "object" ? m.t : m));
  ts = ts.filter((t) => t !== "'" && t !== "/");
  const chunks = [], qs = [];
  let cur = [];
  for (const t of ts) {
    if (t === "、" || t === "?") {
      if (cur.length) { chunks.push(cur); qs.push(t === "?"); cur = []; }
      else if (t === "?" && qs.length) qs[qs.length - 1] = true;
    } else cur.push(t);
  }
  if (cur.length) { chunks.push(cur); qs.push(false); }
  const phr = [];
  let k = 0;
  for (let ci = 0; ci < chunks.length; ci++) {
    const ch = chunks[ci], isq = qs[ci];
    const cuts = [];
    let s = 0;
    if (split) {
      for (let j = 0; j < ch.length; j++) {
        if (PART.has(ch[j]) && (j + 1 - s) >= minlen && (ch.length - (j + 1)) >= minlen && (j + 1 >= ch.length || !SPECIAL.has(ch[j + 1]))) {
          cuts.push(j + 1); s = j + 1;
        }
      }
    }
    const bounds = [0, ...cuts, ch.length];
    for (let bi = 0; bi < bounds.length - 1; bi++) {
      const a = bounds[bi], b = bounds[bi + 1];
      const L = b - a, seg = ch.slice(a, b);
      const endedByPart = cuts.includes(b) || (PART.has(seg[seg.length - 1]) && L > 2);
      let acc = 0;
      if (accent === "ante") {
        const W = L - (endedByPart ? 1 : 0);
        acc = W >= 3 ? Math.max(1, W - 2) : 1;
        while (acc > 1 && SPECIAL.has(seg[acc - 1])) acc--;
      } else if (accent === "mixed") {
        acc = L <= 2 ? 1 : 0;
      }
      phr.push([k + a, L, acc, (isq && b === ch.length) ? 1 : 0]);
    }
    k += ch.length;
  }
  return phr;
}

function heavy(m1, m2) {
  if (SPECIAL.has(m2.t)) return true;
  const v = m1.v;
  return v != null && (LONGV[v] || "").includes(m2.t);
}

function smoothTri(x, k) {
  if (k <= 1 || !x.length) return x.slice();
  let cur = x.slice();
  for (let p = 0; p < 2; p++) {
    const hl = p === 0 ? Math.floor(k / 2) : (k - 1 - Math.floor(k / 2));
    const hr = k - 1 - hl;
    const n = cur.length;
    const pad = new Float64Array(hl + n + hr);
    for (let i = 0; i < hl; i++) pad[i] = cur[0];
    for (let i = 0; i < n; i++) pad[hl + i] = cur[i];
    for (let i = 0; i < hr; i++) pad[hl + n + i] = cur[n - 1];
    const c = new Float64Array(pad.length + 1);
    for (let i = 0; i < pad.length; i++) c[i + 1] = c[i] + pad[i];
    const nx = new Array(n);
    for (let i = 0; i < n; i++) nx[i] = (c[i + k] - c[i]) / k;
    cur = nx;
  }
  return cur;
}

export function f0Rule(moras, n, opts = {}) {
  const {
    phrases: inPhr = null, accent = "ante", question = false, reg = 340.0, rng = 8.0, jump = 4.0, fall = 5.0,
    sag = 1.0, lag = 1.0, rlag = 0.5, ds = 2.0, ds_h = 0.5, reset = 0.6, decl = 1.2, fin = 2.5, qrise = 5.0,
    sm = 35.0, fp_ms = 5.0, fit_range = true,
  } = opts;
  const ml = moras.slice();
  let phrases;
  if (!inPhr) {
    phrases = guessPhrases(ml, accent);
  } else {
    const nonPau = ml.filter((m) => m.kind !== "pau").map((m) => m.t);
    phrases = inPhr.map((p) => {
      if (p[2] !== null && p[2] !== undefined) return p.slice();
      const g = guessPhrases(nonPau.slice(p[0], p[0] + p[1]), accent, false)[0][2];
      return [p[0], p[1], g, ...p.slice(3)];
    });
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

// ============================================================================
// 3. 基礎ノミ（時間領域の引き算・移動平均プリミティブ：正弦波オシレータ不使用）
// ============================================================================
function perSample(fr, N, fp_ms = 5.0) {
  const n = fr.length;
  const step = 1000.0 / (fp_ms * SR);
  const out = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    const t = i * step;
    const k = Math.trunc(t);
    if (k >= n - 1) out[i] = fr[n - 1];
    else {
      const u = t - k;
      out[i] = fr[k] * (1.0 - u) + fr[k + 1] * u;
    }
  }
  return out;
}

// 粗削り（ローパス）：幅 w サンプルの移動平均を p 回かける。最初の零点は SR / w Hz
function arakezuri(x, w, p = 1) {
  const n = x.length;
  let cur = Float64Array.from(x);
  for (let pass = 0; pass < p; pass++) {
    const y = new Float64Array(n);
    let s = 0.0;
    for (let i = 0; i < n; i++) {
      s += cur[i];
      if (i >= w) s -= cur[i - w];
      y[i] = s / (i + 1 < w ? i + 1 : w);
    }
    cur = y;
  }
  return cur;
}

// 時間可変の粗削り：H[i]=1 の区間（破裂・摩擦子音）は高域の鋭さを削り残す
function arakezuriT(x, w, p, H) {
  const s = arakezuri(x, w, p);
  const n = x.length;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = x[i] - (1.0 - H[i]) * (x[i] - s[i]);
  return out;
}

// 軽くする（ハイパス）：幅 w の移動平均を引いて DC〜低域の濁りを落とす
function karuku(x, w) {
  const a = arakezuri(x, w, 1);
  const n = x.length;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i++) out[i] = x[i] - a[i];
  return out;
}

// 原石ホワイトノイズからダシをとるゆっくりした自然な漂い（平滑化ランダムウォーク）
function furafura(src, d0, haba, osoi) {
  const n = src.length;
  const out = new Float64Array(n);
  if (haba === 0.0) { out.fill(d0); return out; }
  let v = 0.0;
  const walk = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    v = (v + src[i]) * 0.9995;
    walk[i] = v;
  }
  const sm = arakezuri(walk, Math.max(1, Math.trunc(osoi * SR)), 2);
  let sum = 0.0;
  for (let i = 0; i < n; i++) sum += sm[i];
  const mean = sum / n;
  let pk = 0.0;
  for (let i = 0; i < n; i++) {
    sm[i] -= mean;
    const av = Math.abs(sm[i]);
    if (av > pk) pk = av;
  }
  if (pk === 0.0) pk = 1.0;
  const sc = haba / pk;
  for (let i = 0; i < n; i++) out[i] = d0 + sm[i] * sc;
  return out;
}

// 注意: ensureScratch の作業配列 (_cs, _tmp, _D, _wHi) は heikin/ffbb/yamaBp 内で共有するため入れ子呼び出し禁止
let _cs = new Float64Array(0), _tmp = new Float64Array(0), _D = new Float64Array(0), _wHi = new Float64Array(0);
function ensureScratch(n) {
  if (_cs.length < n + 1) {
    _cs = new Float64Array(n + 1);
    _tmp = new Float64Array(n);
    _D = new Float64Array(n);
    _wHi = new Float64Array(n);
  }
}

// 前後に位相ずれのない中心移動平均（累積和で O(N)）
function heikin(x, W, out = null) {
  const n = x.length;
  ensureScratch(n);
  const cs = _cs;
  cs[0] = 0.0;
  for (let i = 0; i < n; i++) cs[i + 1] = cs[i] + x[i];
  const y = out || new Float64Array(n);
  if (typeof W === "number") {
    const h = Math.max(1, Math.trunc(W / 2));
    for (let i = 0; i < n; i++) {
      const a = i - h > 0 ? i - h : 0;
      const b = i + h + 1 < n ? i + h + 1 : n;
      y[i] = (cs[b] - cs[a]) / (b - a);
    }
  } else {
    for (let i = 0; i < n; i++) {
      const h = Math.max(1, Math.trunc(W[i] / 2));
      const a = i - h > 0 ? i - h : 0;
      const b = i + h + 1 < n ? i + h + 1 : n;
      y[i] = (cs[b] - cs[a]) / (b - a);
    }
  }
  return y;
}

// 半周期 D 前の自分を反転フィードバックして奇数倍音 (SR / 2D) を立てる
function combHalf(x, D, g, out = null) {
  const n = x.length;
  const y = out || new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const d = D[i];
    const k = Math.trunc(d);
    const fr = d - k;
    const a = i - k, b = a - 1;
    y[i] = x[i] - g * (b >= 0 ? (y[a] * (1.0 - fr) + y[b] * fr) : 0.0);
  }
  return y;
}

// 前後双方向コムフィルタ（ゼロ位相共振）
function ffbb(x, D, g) {
  const n = x.length;
  ensureScratch(n);
  const y1 = combHalf(x, D, g, _tmp);
  const out = new Float64Array(n);
  for (let j = n - 1; j >= 0; j--) {
    const d = D[j];
    const k = Math.trunc(d);
    const fr = d - k;
    const a = j + k, b = a + 1;
    out[j] = y1[j] - g * (b < n ? (out[a] * (1.0 - fr) + out[b] * fr) : 0.0);
  }
  return out;
}

// 受動フォルマント帯域通過：周波数 F[i] Hz の山1つだけを残し、上下の裾を引き算で削る
function yamaBp(x, F, g = 0.7, pLow = 3, pHigh = 2) {
  const n = x.length;
  ensureScratch(n);
  const D = _D, wHi = _wHi;
  for (let i = 0; i < n; i++) {
    const fc = F[i] / 0.95;
    D[i] = SR / (2.0 * fc);
    wHi[i] = (2.0 * SR) / fc;
  }
  const bp = ffbb(x, D, g);
  let norm = (1.0 - g) * (1.0 - g);
  for (let p = 0; p < pLow; p++) {
    heikin(bp, D, bp);
    norm /= 0.6366;
  }
  for (let p = 0; p < pHigh; p++) {
    heikin(bp, wHi, _tmp);
    for (let i = 0; i < n; i++) bp[i] -= _tmp[i];
  }
  for (let i = 0; i < n; i++) bp[i] *= norm;
  return bp;
}

// 因果2極声道共振器（直列カスケード用、DCゲイン=1、高域は Q <= qMax で自然に帯域幅を広げる）
function resonator2Pole(x, F, bwMin, qMax = 12.0) {
  const n = x.length;
  const y = new Float64Array(n);
  const k = (2.0 * Math.PI) / SR;
  const piOverSR = Math.PI / SR;
  let y1 = 0.0, y2 = 0.0;
  for (let i = 0; i < n; i++) {
    const f = F[i];
    const bw = Math.max(bwMin, f / qMax);
    const r = Math.exp(-piOverSR * bw);
    const c = -r * r;
    const b = 2.0 * r * Math.cos(k * f);
    const a = 1.0 - b - c;
    const yi = a * x[i] + b * y1 + c * y2;
    y[i] = yi;
    y2 = y1;
    y1 = yi;
  }
  return y;
}

// 3次ラグランジュ補間による非整数サンプル遅延読み出し
function readDelay(buf, i, p) {
  const k = Math.trunc(p), u = p - k, i0 = i - k;
  if (i0 - 2 >= 0 && i0 + 1 < i) {
    return (
      (-u * (u - 1.0) * (u - 2.0) / 6.0) * buf[i0 + 1]
      + ((u + 1.0) * (u - 1.0) * (u - 2.0) / 2.0) * buf[i0]
      - ((u + 1.0) * u * (u - 2.0) / 2.0) * buf[i0 - 1]
      + ((u + 1.0) * u * (u - 1.0) / 6.0) * buf[i0 - 2]
    );
  }
  return i0 - 1 >= 0 ? (buf[i0] * (1.0 - u) + buf[i0 - 1] * u) : 0.0;
}

// 引き算①（音源くびれ）：周期 PER[i] と食い違う倍音間の谷を3次ラグランジュ補間コムで削る
// 入力に sqrt(1 - g^2) を掛けるためエネルギーが発散せず、G[i]=0 では同じノイズ線を素通しする
// damp > 0 のときはフィードバック帰還路に1極ローパス平滑を混ぜ、高域ほど自然に元のノイズの息を残す
export function combPeriod(x, PER, G, damp = 0.0) {
  const n = x.length;
  const y = new Float64Array(n);
  let lp = 0.0;
  for (let i = 0; i < n; i++) {
    const g = G[i];
    if (g <= 1e-4) { y[i] = x[i]; lp = x[i]; continue; }
    let fb = readDelay(y, i, PER[i]);
    if (damp > 0.0) {
      lp = (1.0 - damp) * fb + damp * lp;
      fb = lp;
    }
    y[i] = Math.sqrt(1.0 - g * g) * x[i] + g * fb;
  }
  return y;
}

function rmsActive(x) {
  let s = 0.0, c = 0;
  for (let i = 0; i < x.length; i++) {
    const v = x[i];
    if (v !== 0.0) { s += v * v; c++; }
  }
  return Math.sqrt(s / (c || 1));
}

function normalizeToRms(x, targetRms = 0.16, ceiling = 0.891, gateStart = 0, gateEnd = x.length) {
  const n = x.length;
  const out = new Float32Array(n);
  let s = 0.0, c = 0;
  for (let i = gateStart; i < gateEnd; i++) { s += x[i] * x[i]; c++; }
  const cur = Math.sqrt(s / (c || 1)) || 1.0;
  let gain = targetRms / cur;
  let pk = 0.0;
  for (let i = gateStart; i < gateEnd; i++) {
    const av = Math.abs(x[i]) * gain;
    if (av > pk) pk = av;
  }
  if (pk > ceiling) gain *= ceiling / pk;
  const fade = Math.min(882, Math.floor((gateEnd - gateStart) / 4));
  for (let i = gateStart; i < gateEnd; i++) {
    let w = 1.0;
    if (i - gateStart < fade) w = (i - gateStart) / fade;
    else if (gateEnd - 1 - i < fade) w = (gateEnd - 1 - i) / fade;
    out[i] = x[i] * gain * w;
  }
  return out;
}

// ============================================================================
// 4. 本体：1本のホワイトノイズから4手で彫る音声・歌声合成
// ============================================================================
export function makeHitofude(text, opts = {}) {
  const {
    seed = 2024,
    hz = 350.0,       // 基準ピッチ高さ (Hz)。女声 300〜360、アルト 220、子ども 400、男声 105〜155
    fscale = 1.17,    // 声道長逆スケール（フォルマント倍率）。1.15〜1.22=女声、1.08=アルト、0.85=太い男声
    rate = 1.26,      // 話速倍率（小さいほど速い、1.25〜1.32=自然な会話）
    g_vo = 0.89,      // 有声くびれ深さ G (0.0〜0.97)。扉の締まり・倍音の谷深さを決める
    tilt_w = 5,       // 高域粗削り幅 w (整数 >=1)。4〜5=標準、6=柔らかい吐息、>=8=こもった暗声
    sigh = 0.0,       // 句末の息抜き量 (0.0〜1.0)。句末母音後半で扉を緩め、声を元の吐息へ戻す
    jitter = 0.0026,  // 1周期ごとの微細周期揺らぎ率 (0.0=完全周期ロボ)
    wander_st = 0.18, // ピッチの緩やかな自然漂い幅 (半音、0.0=冷凍固定)
    damp = 0.08,      // 声帯波帰還路の高域減衰 (0.0..0.95、高域ほど自然に元のノイズの息を残す)
    shin = 1.0,       // 声門2唇粘膜扉×5極声道の再帰結合度 (1.0=既定、0.0=冷凍ロボ用の片道コム)
    character = 0.0,  // 響の固有声色・拍の訛り (0=草薙と同一、0..1=個性を増す)
    edge = 0.0,       // 響の拍頭アタック／粘膜扉の鋭さ (0=草薙と同一、0..1=鋭い声)
    cadence = 0.0,    // 響の文脈依存の節回し (0=無変更、0..1=母音・句末へ応答)
    closeness = 0.0,  // 響の句内存在感 (0=無変更、0..1=前半の柔らかさ→後半の芯)
    signature = 0.0,  // 響の音素連鎖に固有の声色 (0=無変更、0..1=強い個体差)
    gesture = 0.0,    // 響の音程・声道同時ジェスチャー (0=従来通り、0..1=最大)
    baby = 0.0,       // Bシリーズ専用: 未熟な調音・喃語の発声 (0=既存音声、0..1=強さ)
    b2_body = 0.0,    // B2専用: 呼気圧・声門扉・周期が結合する不安定さ
    b2_breaks = 0.0,  // B2専用: 呼気不足時のパルス化・息漏れ（0=従来どおり）
    level_k = 0.65,   // 母音定常部の1スカラー整音強度 (0.0〜1.0、瞬間スペクトル傾斜変化 0.00 dB)
    pre = 0.6,        // 発話前の無音長 (秒)
    post = 0.1,       // 発話後の無音長 (秒)
    uta_hz = null,    // 歌モード：モーラごとの目標周波数配列 [Hz, ...]
    vd_ms = null,     // 歌モード：モーラごとの母音長配列 [ms, ...]
    vib_c = 6.0,      // 歌モード：長音ビブラート深さ (cent)
    captureSteps = false, // true のとき [原石0, ①声帯波/谷, ②粘膜扉/角, ③声道, ④完成] の5波形を返す
  } = opts;

  let accentKw = null, targetText = text, phraseCuts = null;
  const hasMarks = /['’0/| 　?？]/.test(text);
  if (hasMarks && !uta_hz) {
    const [clean, phrases] = annotate(text);
    accentKw = { phrases, question: /[?？]$/.test(text.trim()) };
    targetText = clean;
    phraseCuts = phrases.slice(1).map((p) => p[0]);
  }

  const fpz = FP / 1000.0;
  const prm = { rate, fend_at: sigh > 0.0 ? 0.45 : 0.16, phraseCuts };
  if (vd_ms) prm.vd_ms = vd_ms;
  if (uta_hz && uta_hz.length) { prm.no_dev = true; prm.ou_long = false; }
  const r = tracksFromKana(targetText, pre, post, prm);
  const n = r.n;
  const N = Math.trunc(n * fpz * SR);
  if (!r.voiced.some(Boolean) && r.bands.length === 0) {
    const z = new Float32Array(N);
    return { samples: z, steps: captureSteps ? [z, z, z, z, z] : null, r: Object.assign({}, r, { f0_tr: new Array(n).fill(0.0) }), moras: r.moras };
  }

  // === Step 0: 原石ホワイトノイズ（声・息・漂い・ジッタ・ビブラートのすべてをこの1本から彫る） ===
  const rng = makeRng(seed);
  let x = new Float64Array(N);
  for (let i = 0; i < N; i++) x[i] = rng.uniform(-1.0, 1.0);
  const x0 = captureSteps ? x.slice() : null;

  // ピッチ軌道 f0_fr (Hz, 5ms フレーム)
  let f0_fr;
  if (uta_hz && uta_hz.length) {
    f0_fr = new Array(n).fill(uta_hz[0]);
    let k_ = 0;
    for (const m_ of r.moras) {
      if (m_.kind === "pau") continue;
      const h_ = uta_hz[Math.min(k_, uta_hz.length - 1)];
      k_++;
      for (let t_ = Math.max(0, Math.trunc(m_.a / fpz)); t_ < n; t_++) f0_fr[t_] = h_;
    }
    f0_fr = smooth1(f0_fr, 34);
    var vibWave = null;
    if (vib_c > 0.0) {
      const vHz = 4.2 + 1.8 * (x[0] * 0.5 + 0.5);
      const wv = Math.max(3, Math.round(1000.0 / FP / vHz / 2.0));
      const lenV = n + 30 * wv;
      const vn = new Float64Array(lenV);
      for (let i = 0; i < lenV; i++) vn[i] = x[(i * 220) % N];
      const vw = arakezuri(combHalf(vn, new Float64Array(lenV).fill(wv), 0.92), Math.max(2, Math.floor(wv / 2)), 2).subarray(30 * wv, 30 * wv + n);
      let vSq = 0.0;
      for (let i = 0; i < n; i++) vSq += vw[i] * vw[i];
      const invV = 1.0 / ((Math.sqrt(vSq / n) || 1.0) * 1.414);
      vibWave = new Float64Array(n);
      for (let t_ = 0; t_ < n; t_++) {
        vibWave[t_] = vw[t_] * invV;
        f0_fr[t_] *= Math.pow(2.0, (vib_c * 0.72 * vibWave[t_]) / 1200.0);
      }
    }
  } else {
    const acc = sigh >= 0.25
      ? Object.assign({}, ACCENT_NORMAL, { rng: 6.2, jump: 2.8, fall: 3.8, sag: 0.9, decl: 1.4, fin: 2.6 })
      : ACCENT_CUTE;
    f0_fr = f0Rule(r.moras, n, Object.assign({}, acc, { reg: hz }, accentKw || {}));
  }

  // 響: 母音の中だけで、モーラごとに決まった小さな音程の訛りを刻む。
  // ランダムな揺らぎではなく反復可能な「口癖」。母音の入りは保ち、核の後半で少し浮く。
  const charm = Math.max(0.0, Math.min(1.0, Number.isFinite(character) ? character : 0.0));
  const edgeAmt = Math.max(0.0, Math.min(1.0, Number.isFinite(edge) ? edge : 0.0));
  if (charm > 0.0 && !uta_hz) {
    const motif = [-0.80, 0.55, 1.00, -0.30, 0.35]; // 半音、固定の5拍モチーフ
    let mi = 0;
    for (const m of r.moras) {
      if (m.kind !== "CV") continue;
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      const step = motif[mi++ % motif.length];
      for (let t = ib; t < ie; t++) {
        if (!r.voiced[t]) continue;
        const u = (t - ib) / Math.max(1, ie - ib);
        const bump = 4.0 * u * (1.0 - u); // 母音境界で0、中央で1
        f0_fr[t] *= Math.pow(2.0, (charm * step * bump) / 12.0);
      }
    }
  }

  // 響「語」: 5拍周期ではなく、母音列・子音・句の終端に応じて同じ声の話し癖が出る。
  // 音素と句読点だけを入力に使うため、テキストに反応するが乱数は増えない。
  // かなに意味・感情を読み込んでいるわけではない（韻律上の文脈のみ）。
  const cadenceAmt = Math.max(0.0, Math.min(1.0, Number.isFinite(cadence) ? cadence : 0.0));
  if (cadenceAmt > 0.0 && !uta_hz) {
    const moras = r.moras;
    const vowelBias = { a: 0.38, i: 0.15, u: -0.28, e: 0.48, o: -0.34 };
    let phraseIndex = 0;
    for (let j = 0; j < moras.length; j++) {
      const m = moras[j];
      if (m.kind === "pau") { phraseIndex = 0; continue; }
      if (m.kind !== "CV") continue;
      const prev = j > 0 && moras[j - 1].kind === "CV" ? moras[j - 1] : null;
      const next = j + 1 < moras.length && moras[j + 1].kind === "CV" ? moras[j + 1] : null;
      const final = next === null;
      const contrast = prev && prev.v !== m.v ? 0.26 : -0.08;
      const onset = ["s", "sh", "z", "j", "ch", "ts"].includes(m.c) ? 0.21
        : ["m", "n", "r", "y", "w"].includes(m.c) ? -0.15 : 0.0;
      // 語頭は少し慎重、中盤で弾み、句末は落ち着く。5拍ループを排除する。
      const placement = phraseIndex === 0 ? -0.25 : Math.min(0.17, 0.04 * phraseIndex);
      const step = Math.max(-1.1, Math.min(1.1, (vowelBias[m.v] || 0) + contrast + onset + placement - (final ? 0.42 : 0)));
      phraseIndex++;
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      for (let q = ib; q < ie; q++) {
        if (!r.voiced[q]) continue;
        const u = (q - ib) / Math.max(1, ie - ib);
        const rise = 4.0 * u * (1.0 - u); // 境界ではゼロ: 子音の可読性と既存アクセントを保つ
        f0_fr[q] *= Math.pow(2.0, (cadenceAmt * step * rise) / 12.0);
      }
    }
  }

  // 息吹: 一つの発声ジェスチャーが音程と声道に同期して現れる。
  // 母音の系列から一意に生じる小さな意外性を与え、予測できる「同一人物」を保つ。
  // 音の入口・出口は0に戻し、子音の可読性を守る。意味の感情推定は行わない。
  const gestureAmt = Math.max(0.0, Math.min(1.0, Number.isFinite(gesture) ? gesture : 0.0));
  const gestureFr = new Float64Array(n);
  if (gestureAmt > 0.0 && !uta_hz) {
    const vowels = { a: 0.52, i: -0.35, u: 0.28, e: -0.56, o: 0.42 };
    let prevV = null;
    for (let j = 0; j < r.moras.length; j++) {
      const m = r.moras[j];
      if (m.kind === "pau") { prevV = null; continue; }
      if (m.kind !== "CV") continue;
      const adjacent = j + 1 < r.moras.length ? r.moras[j + 1] : null;
      const last = !adjacent || adjacent.kind === "pau";
      const v = vowels[m.v] ?? 0.0;
      const relation = prevV === null ? 0.0 : (prevV === m.v ? -0.16 : 0.22);
      const s = Math.max(-0.8, Math.min(0.8, v + relation - (last ? 0.21 : 0.0)));
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      for (let q = ib; q < ie; q++) {
        if (!r.voiced[q]) continue;
        const u = (q - ib) / Math.max(1, ie - ib);
        const shape = Math.sin(Math.PI * u) ** 2;
        const gestureValue = gestureAmt * s * shape;
        gestureFr[q] = gestureValue;
        f0_fr[q] *= Math.pow(2.0, (0.52 * gestureValue) / 12.0);
      }
      prevV = m.v;
    }
  }

  // B1: 乳児の喃語的なピッチの探り。ノイズ源 x に含まれる偏りを拍単位で使用する。
  // 高くするだけではなく、短い探索の上昇/下降を重ねる。既存V系列では完全無効。
  const babyAmt = Math.max(0, Math.min(1, Number.isFinite(baby) ? baby : 0));
  if (babyAmt > 0 && !uta_hz) {
    for (const m of r.moras) {
      if (m.kind !== "CV") continue;
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      const sampleIdx = Math.min(N - 1, Math.max(0, Math.trunc(m.b * SR)));
      const direction = x[sampleIdx] * 2.4; // noise-sourced, fixed per mora
      for (let q = ib; q < ie; q++) {
        if (!r.voiced[q]) continue;
        const u = (q - ib) / Math.max(1, ie - ib);
        const bend = direction * (u * u * (3 - 2 * u)) + 0.70 * Math.sin(Math.PI * u);
        f0_fr[q] *= Math.pow(2, babyAmt * bend / 12);
      }
    }
  }

  // 句末の息抜き軌道 sigh_fr：有声句の最後の母音後半 (u > 0.30) でくびれ G をほどく
  const sigh_fr = new Array(n).fill(0.0);
  if (sigh > 0.0) {
    for (let idx_m = 0; idx_m < r.moras.length; idx_m++) {
      const m_ = r.moras[idx_m];
      const ib = Math.max(0, Math.trunc(m_.b / fpz)), ie = Math.min(n, Math.trunc(m_.e / fpz));
      let hasVo = false;
      for (let t_ = ib; t_ < ie; t_++) if (r.voiced[t_]) { hasVo = true; break; }
      if (m_.kind !== "CV" || (ie - ib) < 7 || !hasVo) continue;
      let remVo = false;
      for (let k2 = idx_m + 1; k2 < r.moras.length; k2++) {
        const m2 = r.moras[k2];
        if (m2.kind === "pau") break;
        const b2 = Math.max(0, Math.trunc(m2.b / fpz)), e2 = Math.min(n, Math.trunc(m2.e / fpz));
        for (let t_ = b2; t_ < e2; t_++) if (r.voiced[t_]) { remVo = true; break; }
      }
      if (!remVo) {
        const sp_ = Math.max(1, ie - ib);
        for (let t_ = ib; t_ < ie; t_++) {
          const u = (t_ - ib) / sp_;
          if (u > 0.30) {
            const s_v = Math.min(1.0, sigh) * Math.pow((u - 0.30) / 0.70, 1.10);
            sigh_fr[t_] = s_v;
            f0_fr[t_] *= Math.pow(2.0, (-0.18 * s_v) / 12.0);
          }
        }
      }
    }
  }

  // 声道共鳴周波数 F1..F4 と子音共鳴中心 f_cons_cen
  const fs = fscale;
  // 響: 子音を壊さないよう母音の中央だけF2/F3を補色方向へ動かす。
  // F2が前舌母音で下がり、奥舌母音で上がることで、同じ高さでも声の色が変わる。
  const vowelTint = new Float64Array(n);
  if (charm > 0.0) {
    const tint = { a: 0.45, i: -0.85, u: 1.0, e: -0.55, o: 0.80 };
    for (const m of r.moras) {
      if (m.kind !== "CV" || !(m.v in tint)) continue;
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      for (let t = ib; t < ie; t++) {
        if (!r.voiced[t]) continue;
        const u = (t - ib) / Math.max(1, ie - ib);
        vowelTint[t] = charm * tint[m.v] * 4.0 * u * (1.0 - u);
      }
    }
  }
  // 懐：瞬間的な母音の色だけでなく「直前の母音→現在→次」の連なりで
  // その声だけの音色の通り道を刻む。固定プリセットの同じ音素列には常に同じ応答。
  // 語境界で色が飛ばないよう母音中央だけで作用し、子音のフォルマントは保つ。
  const signatureAmt = Math.max(0.0, Math.min(1.0, Number.isFinite(signature) ? signature : 0.0));
  const voicePrint = new Float64Array(n);
  if (signatureAmt > 0.0) {
    const vowels = { a: 0.31, i: -0.58, u: 0.66, e: -0.37, o: 0.47 };
    let prev = null;
    const ms = r.moras;
    for (let j = 0; j < ms.length; j++) {
      const m = ms[j];
      if (m.kind === "pau") { prev = null; continue; }
      if (m.kind !== "CV") continue;
      const next = j + 1 < ms.length && ms[j + 1].kind === "CV" ? ms[j + 1] : null;
      const cur = vowels[m.v] ?? 0.0;
      const from = prev ? (vowels[prev.v] ?? 0.0) : 0.0;
      const to = next ? (vowels[next.v] ?? 0.0) : 0.0;
      const raw = 0.62 * cur + 0.25 * from - 0.16 * to;
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      for (let q = ib; q < ie; q++) {
        if (!r.voiced[q]) continue;
        const u = (q - ib) / Math.max(1, ie - ib);
        voicePrint[q] = signatureAmt * raw * (4.0 * u * (1.0 - u));
      }
      prev = m;
    }
  }
  const F1 = new Array(n), F2 = new Array(n), F3 = new Array(n), F4 = new Array(n);
  for (let t = 0; t < n; t++) {
    // B1: 母音の輪郭を少し曖昧にする（口の形がまだ定まらない）。
    const central = babyAmt > 0 && r.voiced[t] ? 0.36 * babyAmt : 0.0;
    F1[t] = Math.max((r.F1[t] * (1 - central) + 520 * central) * fs, r.voiced[t] ? 1.04 * f0_fr[t] : 180.0);
    F2[t] = Math.min(Math.max((r.F2[t] * (1 - central) + 1650 * central) * fs * (1.0 + 0.13 * vowelTint[t] + 0.10 * voicePrint[t] + 0.042 * gestureFr[t]), F1[t] + 280.0), 8500.0);
    F3[t] = Math.min(Math.max(r.F3[t] * fs * (1.0 - 0.055 * vowelTint[t] - 0.08 * voicePrint[t] - 0.025 * gestureFr[t]), F2[t] + 350.0), 9000.0);
    F4[t] = Math.min(8600.0, F3[t] + 1150.0 * fs);
  }

  const f_cons_cen = new Array(n).fill(2500.0);
  const f_cons_w = new Array(n).fill(0.0);
  const cons_sharp = new Array(n).fill(0.0);
  const sortedBands = r.bands.slice().sort((a, b) => a[0] - b[0]);
  for (const [t0, t1, cen, , lev] of sortedBands) {
    const ia = Math.max(0, Math.round(t0 / fpz)), ib = Math.min(n, Math.round(t1 / fpz) + 1);
    for (let t_ = Math.max(0, ia - 2); t_ < Math.min(n, ib + 2); t_++) f_cons_cen[t_] = cen;
    for (let t_ = ia; t_ < ib; t_++) {
      f_cons_w[t_] = Math.max(f_cons_w[t_], Math.min(3.4, 0.58 * lev));
      cons_sharp[t_] = 1.0;
    }
  }
  for (let t_ = 1; t_ < n; t_++) {
    if (f_cons_w[t_] === 0.0 && cons_sharp[t_] === 0.0) f_cons_cen[t_] = f_cons_cen[t_ - 1];
  }

  // 響: 拍頭の「噛みつき」軌道。子音と母音の境界で最大、母音中央までに消える。
  // 音量のゲートは掛けず、既存の粘膜扉のしなりだけに介入する。
  const biteFr = new Float64Array(n);
  if (edgeAmt > 0.0) {
    for (const m of r.moras) {
      if (m.kind !== "CV") continue;
      const ib = Math.max(0, Math.trunc(m.b / fpz));
      const ie = Math.min(n, Math.trunc(m.e / fpz));
      for (let t = ib; t < ie; t++) {
        if (!r.voiced[t]) continue;
        const u = (t - ib) / Math.max(1, ie - ib);
        biteFr[t] = Math.max(biteFr[t], edgeAmt * Math.pow(Math.max(0.0, 1.0 - u / 0.52), 2));
      }
    }
  }
  const vo_sm = smooth1(r.voiced.map((v) => (v ? 1.0 : 0.0)), 10);
  const sigh_sm = smooth1(sigh_fr, 14);
  const g_fr = new Array(n);
  for (let t = 0; t < n; t++) g_fr[t] = vo_sm[t] * g_vo * (1.0 - 0.88 * sigh_sm[t]);
  // 寄添: 句の初めは息を残し、母音の芯に少し近づき、句末はふたたび息へ戻る。
  // 喉の周期性だけを動かす。独立ノイズも振幅ゲートも加えない。
  const closeAmt = Math.max(0.0, Math.min(1.0, Number.isFinite(closeness) ? closeness : 0.0));
  if (closeAmt > 0.0) {
    let phraseStart = 0;
    for (let j = 0; j <= r.moras.length; j++) {
      if (j !== r.moras.length && r.moras[j].kind !== "pau") continue;
      const phrase = r.moras.slice(phraseStart, j).filter((m) => m.kind === "CV");
      if (phrase.length) {
        const begin = phrase[0].b, end = phrase[phrase.length - 1].e;
        const dur = Math.max(0.05, end - begin);
        for (const m of phrase) {
          const ib = Math.max(0, Math.trunc(m.b / fpz)), ie = Math.min(n, Math.trunc(m.e / fpz));
          for (let q = ib; q < ie; q++) {
            if (!r.voiced[q]) continue;
            const tSec = q * fpz;
            const u = Math.max(0.0, Math.min(1.0, (tSec - begin) / dur));
            const open = Math.max(0.0, 1.0 - u / 0.32);
            const release = Math.max(0.0, (u - 0.72) / 0.28);
            const contour = -0.12 * open + 0.035 * Math.sin(Math.PI * u) - 0.10 * release;
            g_fr[q] = Math.max(0.0, Math.min(0.965, g_fr[q] + closeAmt * contour));
          }
        }
      }
      phraseStart = j + 1;
    }
  }

  // サンプル単位の基本周期 PER[i] (原石ノイズ x からダシをとった自然漂い wander + 周期ごとの微細ジッタ)
  const f0S = perSample(f0_fr, N);
  const wander = furafura(x, 0.0, wander_st, 0.09);
  const PER = new Float64Array(N);
  for (let i = 0; i < N; i++) PER[i] = SR / Math.max(60.0, f0S[i] * Math.pow(2.0, wander[i] / 12.0));
  const hRef = Math.max(85.0, hz);
  if (jitter > 0.0) {
    let idxP = 0;
    while (idxP < N) {
      const pl = Math.max(2, Math.trunc(PER[idxP]));
      const jf = 1.0 + jitter * x[idxP];
      const end = Math.min(N, idxP + pl);
      for (let k = idxP; k < end; k++) PER[k] *= jf;
      idxP += pl;
    }
    if (shin > 0.0) heikin(PER, Math.max(10, Math.round(SR / (hRef * 6.0))), PER);
  }

  // B2: 同一ノイズから得る遅い呼気圧のうねり。
  // 声門の締まり、基本周期、空気流を同じ圧力に依存させる。
  const bodyAmt = Math.max(0, Math.min(1, Number.isFinite(b2_body) ? b2_body : 0));
  const breaksAmt = bodyAmt > 0 ? Math.max(0, Math.min(1, Number.isFinite(b2_breaks) ? b2_breaks : 0)) : 0;
  const bodyPressure = bodyAmt > 0 ? furafura(x, 0.0, 1.0, 0.065) : null;
  if (bodyPressure) {
    for (let i = 0; i < N; i++) {
      // 声帯の緊張が追随しきらず、周期が呼気圧と同時に揺れる。
      const v = bodyPressure[i];
      // 圧力低下で一時的にパルス発声へ移行（連続遷移でクリックを避ける）。
      const slack = breaksAmt * Math.max(0, Math.min(1, (-v - 0.12) / 0.6));
      PER[i] *= Math.pow(2, (-bodyAmt * 0.85 * v + 5.0 * slack) / 12);
    }
  }
  const GS = perSample(g_fr, N);
  const SIGH_S = perSample(sigh_sm, N);
  const BITE_S = edgeAmt > 0.0 ? perSample(smooth1(biteFr, 10), N) : null;
  const wNorm = wander_st > 0.0 ? (1.0 / wander_st) : 0.0;
  if (wNorm > 0.0) for (let i = 0; i < N; i++) GS[i] = Math.min(0.975, Math.max(0.0, GS[i] * (1.0 + 0.032 * wander[i] * wNorm)));
  const tw = Math.max(1, Math.round(tilt_w));
  const ycRad = new Float64Array(N);
  let x1 = null, x2 = null;

  if (shin > 0.0) {
    // === Step 1–3 (統合粘膜再帰系): 非対称ベルヌーイ2唇扉 × 5極粘膜声道の1サンプル再帰ループ ===
    // 上唇は丸くめくれて開き、下唇は気流のベルヌーイ吸い寄せでスパッと閉じて全倍音のタイミングを揃える
    const hiMix = Math.min(1.0, Math.max(0.0, (hRef - 125.0) / 85.0));
    x = karuku(x, hRef >= 200.0 ? 115 : 220);
    const xClean = arakezuriT(x.slice(), tw, 2, perSample(cons_sharp, N));
    const pLungWalk = furafura(x, 0.38, 0.14 - 0.10 * hiMix, 0.045 + 0.175 * hiMix);
    if (bodyPressure) {
      for (let i = 0; i < N; i++) pLungWalk[i] = Math.max(0.055, pLungWalk[i] * (1.0 + 0.48 * bodyAmt * bodyPressure[i]));
    }
    const F5 = F4.map((v) => (fs < 0.92 ? Math.min(4850.0, v * 1.26) : Math.min(8800.0, v + 1100.0 * fs)));
    const F1S = perSample(F1, N), F2S = perSample(F2, N), F3S = perSample(F3, N), F4S = perSample(F4, N), F5S = perSample(F5, N);
    const gBuf = new Float64Array(N), gBuf2 = new Float64Array(N), uOut = new Float64Array(N), yc = new Float64Array(N);
    const twoPiSR = (2.0 * Math.PI) / SR, piSR = Math.PI / SR;
    const ret = 0.45 * shin;
    const qSoft = 1.45 - 0.30 * hiMix;
    const rawAir = 0.02 + 0.12 * hiMix;
    const radK = 0.42 + 0.54 * hiMix;
    const bern = 0.55 * hiMix;
    const loGain = 1.805 - 0.155 * hiMix;
    const upGain = 3.10 - 0.10 * hiMix;
    const knee = 0.22 - 0.04 * hiMix;
    const closeMul = 8.20 + 13.80 * hiMix;
    const closedDecay = 0.50 - 0.38 * hiMix;
    const seedFloor = (jitter > 0.0 ? 0.58 : 0.0) * hiMix;
    let doorLp1 = 0.0, doorLp2 = 0.0, doorPrev = 0.0, gLp1 = 0.0, gLp2 = 0.0, uFlow = 0.0, p1Prev = 0.0, ycPrev = 0.0;
    let y1_1 = 0.0, y1_2 = 0.0, y2_1 = 0.0, y2_2 = 0.0, y3_1 = 0.0, y3_2 = 0.0, y4_1 = 0.0, y4_2 = 0.0, y5_1 = 0.0, y5_2 = 0.0;
    for (let i = 0; i < N; i++) {
      const pressure = bodyPressure ? bodyPressure[i] : 0.0;
      const slack = breaksAmt * Math.max(0, Math.min(1, (-pressure - 0.12) / 0.6));
      const g = bodyPressure ? Math.min(0.975, Math.max(0, GS[i] * (1.0 + 0.11 * bodyAmt * pressure) * (1.0 - 0.36 * slack))) : GS[i];
      const vo = Math.min(1.0, g / (g_vo || 1.0)), p = PER[i];
      const gT = Math.max(g, seedFloor * (1.0 - SIGH_S[i]));
      const cIn = gT > 1e-4 ? Math.sqrt(1.0 - gT * gT) : 1.0;
      const aOpen = Math.exp(-(8.20 + 2.5 * bodyAmt * pressure) / p);
      const aClose = Math.exp(-(closeMul + 4.0 * bodyAmt * pressure) / p);
      const pRet = Math.tanh((0.70 * (y1_1 - p1Prev) + 0.30 * (ycPrev - (i > 1 ? yc[i - 2] : 0.0))) * 4.5);
      p1Prev = y1_1;
      const fb1 = readDelay(gBuf, i, p); gLp1 = (1.0 - damp) * fb1 + damp * gLp1;
      gBuf[i] = Math.tanh((cIn * xClean[i] + gT * (gLp1 + ret * 0.24 * doorPrev * pRet)) * 0.85) / 0.85;
      const fb2 = readDelay(gBuf2, i, p); gLp2 = (1.0 - damp) * fb2 + damp * gLp2;
      const gVal = Math.tanh((cIn * gBuf[i] + gT * (gLp2 + ret * 0.16 * doorPrev * pRet)) * 0.85) / 0.85;
      gBuf2[i] = gVal;
      doorLp1 = (1.0 - aClose) * gVal + aClose * doorLp1;
      doorLp2 = (1.0 - aOpen) * doorLp1 + aOpen * doorLp2;
      const bite = BITE_S ? BITE_S[i] : 0.0;
      const neck = Math.min(doorLp2 * upGain, doorLp1 * loGain - (bern + 0.13 * bite) * uFlow);
      const door = (vo > 0.01 && neck > 0.0) ? ((1.0 - hiMix + hiMix * vo) * (neck / (neck + knee * (1.0 - 0.23 * bite)))) : 0.0;
      doorPrev = door;
      if (door > 0.0) {
        const pLoad = Math.tanh((0.70 * y1_1 + 0.30 * ycPrev) * 3.0);
        const aFlHi = door > uFlow ? (0.35 - 0.07 * bite) : (0.08 - 0.015 * bite);
        const aFl = 0.88 + (aFlHi - 0.88) * hiMix;
        uFlow = aFl * uFlow + (1.0 - aFl) * door * (pLungWalk[i] + rawAir * xClean[i]) * (1.0 - ret * 0.50 * pLoad);
      } else {
        uFlow *= closedDecay;
      }
      // 圧力低下時は声帯接触の周期成分が薄まり、同じ原石ノイズ由来の息漏れが残る。
      uOut[i] = (1.0 - vo) * 0.28 * xClean[i] + vo * (uFlow * 3.6);
      if (slack > 0) uOut[i] += (0.11 * slack * bodyAmt) * xClean[i] * Math.max(0.0, pLungWalk[i]);
      const bw1 = Math.max(80.0, F1S[i] / 8.0) + (150.0 - 60.0 * hiMix) * door;
      const r1 = Math.exp(-piSR * bw1), c1 = -r1 * r1, b1 = 2.0 * r1 * Math.cos(twoPiSR * F1S[i]);
      const o1 = (1.0 - b1 - c1) * uOut[i] + b1 * y1_1 + c1 * y1_2; y1_2 = y1_1; y1_1 = o1;
      const bw2 = Math.max(110.0 * qSoft, F2S[i] / (11.0 / qSoft)) + (50.0 - 20.0 * hiMix) * door;
      const r2 = Math.exp(-piSR * bw2), c2 = -r2 * r2, b2 = 2.0 * r2 * Math.cos(twoPiSR * F2S[i]);
      const o2 = (1.0 - b2 - c2) * o1 + b2 * y2_1 + c2 * y2_2; y2_2 = y2_1; y2_1 = o2;
      const bw3 = Math.max(150.0 * qSoft, F3S[i] / (13.0 / qSoft)) + (30.0 - 15.0 * hiMix) * door;
      const r3 = Math.exp(-piSR * bw3), c3 = -r3 * r3, b3 = 2.0 * r3 * Math.cos(twoPiSR * F3S[i]);
      const o3 = (1.0 - b3 - c3) * o2 + b3 * y3_1 + c3 * y3_2; y3_2 = y3_1; y3_1 = o3;
      const bw4 = Math.max(220.0 * qSoft, F4S[i] / (14.0 / qSoft));
      const r4 = Math.exp(-piSR * bw4), c4 = -r4 * r4, b4 = 2.0 * r4 * Math.cos(twoPiSR * F4S[i]);
      const o4 = (1.0 - b4 - c4) * o3 + b4 * y4_1 + c4 * y4_2; y4_2 = y4_1; y4_1 = o4;
      const bw5 = Math.max(260.0 * qSoft, F5S[i] / (14.0 / qSoft));
      const r5 = Math.exp(-piSR * bw5), c5 = -r5 * r5, b5 = 2.0 * r5 * Math.cos(twoPiSR * F5S[i]);
      const o5 = (1.0 - b5 - c5) * o4 + b5 * y5_1 + c5 * y5_2; y5_2 = y5_1; y5_1 = o5;
      yc[i] = o5; ycPrev = o5;
    }
    if (captureSteps) { x1 = gBuf2.slice(); x2 = uOut.slice(); }
    const ycAc = karuku(yc, hRef >= 200.0 ? 115 : 220);
    x = uOut;
    for (let i = 1; i < N; i++) ycRad[i] = ycAc[i] - radK * ycAc[i - 1];
  } else {
    // === Step 1–3 (冷凍ロボ用 片道系 shin=0): 2段直列コム → 粗削り → F1–F4 カスケード ===
    x = combPeriod(x, PER, GS, damp);
    x = combPeriod(x, PER, GS, damp);
    if (captureSteps) x1 = x.slice();
    x = karuku(x, hz >= 200.0 ? 115 : 220);
    x = arakezuriT(x, tw, 2, perSample(cons_sharp, N));
    if (sigh > 0.0) {
      const sighKeep = new Array(n);
      for (let t = 0; t < n; t++) sighKeep[t] = 1.0 - 0.85 * sigh_sm[t];
      x = arakezuriT(x, tw + 3, 2, perSample(sighKeep, N));
    }
    if (captureSteps) x2 = x.slice();
    let yc = resonator2Pole(x, perSample(F1, N), 80.0, 8.0);
    yc = resonator2Pole(yc, perSample(F2, N), 110.0, 11.0);
    yc = resonator2Pole(yc, perSample(F3, N), 150.0, 13.0);
    yc = resonator2Pole(yc, perSample(F4, N), 220.0, 14.0);
    for (let i = 1; i < N; i++) ycRad[i] = yc[i] - 0.70 * yc[i - 1];
  }
  const vScale = 0.43 * (rmsActive(x) / (rmsActive(ycRad) || 1.0));
  const bpc = yamaBp(x, perSample(f_cons_cen, N), 0.50, 1, 2);
  const G1S = perSample(r.G1, N);
  const FCW = perSample(smooth1(f_cons_w, 6), N);

  const y = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    y[i] = vScale * G1S[i] * ycRad[i] + 0.40 * FCW[i] * bpc[i];
  }
  const x3 = captureSteps ? y.slice() : null;

  // === Step 4: 【引き算④】1スカラー整音 ＋ 時間包絡 ===
  if (level_k > 0.0) {
    const wSc = Math.trunc(0.028 * SR);
    const sq = new Float64Array(N);
    for (let i = 0; i < N; i++) sq[i] = y[i] * y[i];
    const pLoc = heikin(sq, wSc);
    const vPows = [];
    for (let t = 0; t < n; t++) {
      if (r.voiced[t] && sigh_sm[t] < 0.1 && cons_sharp[t] < 0.1) {
        vPows.push(pLoc[Math.trunc((t + 0.5) * fpz * SR)]);
      }
    }
    let refRms;
    if (vPows.length) {
      vPows.sort((a, b) => a - b);
      refRms = Math.sqrt(vPows[Math.floor(vPows.length / 2)]);
    } else {
      refRms = rmsActive(y) || 1.0;
    }
    const eps = Math.pow(0.12 * refRms, 2) + 1e-24;
    const wLvFr = new Array(n);
    for (let t = 0; t < n; t++) wLvFr[t] = level_k * vo_sm[t] * (1.0 - sigh_sm[t]) * (1.0 - cons_sharp[t]);
    const wLv = perSample(smooth1(wLvFr, 14), N);
    const rawGlv = new Float64Array(N);
    for (let i = 0; i < N; i++) {
      const ratio = Math.min(2.2, Math.max(0.45, refRms / Math.sqrt(pLoc[i] + eps)));
      rawGlv[i] = 1.0 + wLv[i] * (ratio - 1.0);
    }
    const gLv = heikin(rawGlv, Math.trunc(0.018 * SR));
    for (let i = 0; i < N; i++) y[i] *= gLv[i];
  }

  const loExp = new Array(n);
  for (let t = 0; t < n; t++) loExp[t] = Math.exp((r.loud[t] + r.dl[t] - (sigh > 0.0 ? 0.45 * sigh_sm[t] : 0.0)) / 2.0) * (vibWave ? Math.max(0.55, 1.0 + 0.015 * vib_c * vibWave[t]) : 1.0);
  const env = perSample(loExp, N);
  let pk = 0.0;
  for (let i = 0; i < N; i++) {
    y[i] *= env[i] * (wNorm > 0.0 ? Math.max(0.55, 1.0 + 0.24 * wander[i] * wNorm) : 1.0);
    const av = Math.abs(y[i]);
    if (av > pk) pk = av;
  }
  if (pk === 0.0) pk = 1.0;
  const out = new Float32Array(N);
  const scale = 0.891 / pk;
  for (let i = 0; i < N; i++) out[i] = y[i] * scale;

  let steps = null;
  if (captureSteps) {
    let vSq = 0.0, vCnt = 0;
    for (let t = 0; t < n; t++) {
      if (r.voiced[t]) {
        const a = Math.trunc(t * fpz * SR), b = Math.min(N, Math.trunc((t + 1) * fpz * SR));
        for (let i = a; i < b; i++) vSq += out[i] * out[i];
        vCnt += Math.max(0, b - a);
      }
    }
    const targetRms = Math.min(0.18, Math.max(0.11, Math.sqrt(vSq / (vCnt || 1))));
    const gStart = Math.max(0, Math.trunc((r.moras[0]?.a ?? pre) * SR));
    const gEnd = Math.min(N, Math.trunc((r.moras[r.moras.length - 1]?.e ?? (N / SR - post)) * SR));
    steps = [
      normalizeToRms(x0, targetRms * 0.72, 0.75, gStart, gEnd),
      normalizeToRms(x1, targetRms * 0.85, 0.85, gStart, gEnd),
      normalizeToRms(x2, targetRms * 0.92, 0.85, gStart, gEnd),
      normalizeToRms(x3, targetRms * 0.98, 0.88, gStart, gEnd),
      out,
    ];
  }

  return { samples: out, steps, r: Object.assign({}, r, { f0_tr: f0_fr }), moras: r.moras };
}

// ============================================================================
// 5. WAV エンコード & 音響自己計測 hakaru（ブラウザ・Node 共通、外部依存ゼロ）
// ============================================================================
export function encodeWav(samples, sampleRate = SR) {
  const n = samples.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const view = new DataView(buf);
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
  for (let i = 0; i < n; i++) {
    const clamped = Math.max(-1.0, Math.min(1.0, samples[i]));
    view.setInt16(44 + i * 2, Math.round(clamped * 32767.0), true);
  }
  return new Uint8Array(buf);
}

const FFT_CACHE = new Map();

export function fftRadix2(reIn) {
  const n = reIn.length;
  let plan = FFT_CACHE.get(n);
  if (!plan) {
    const bits = Math.round(Math.log2(n));
    const bitrev = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      let x = i, r = 0;
      for (let b = 0; b < bits; b++) { r = (r << 1) | (x & 1); x >>= 1; }
      bitrev[i] = r;
    }
    const twRe = [], twIm = [], steps = [];
    for (let step = 2; step <= n; step <<= 1) {
      const half = step >> 1;
      const cRe = new Float64Array(half), cIm = new Float64Array(half);
      for (let k = 0; k < half; k++) {
        const ang = (-2.0 * Math.PI * k) / step;
        cRe[k] = Math.cos(ang);
        cIm[k] = Math.sin(ang);
      }
      steps.push(step);
      twRe.push(cRe);
      twIm.push(cIm);
    }
    plan = { bitrev, steps, twRe, twIm };
    FFT_CACHE.set(n, plan);
  }
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) re[i] = reIn[plan.bitrev[i]];
  for (let si = 0; si < plan.steps.length; si++) {
    const step = plan.steps[si], half = step >> 1;
    const cRe = plan.twRe[si], cIm = plan.twIm[si];
    for (let s = 0; s < n; s += step) {
      for (let k = 0; k < half; k++) {
        const i1 = s + k, i2 = i1 + half;
        const vr = re[i2] * cRe[k] - im[i2] * cIm[k];
        const vi = re[i2] * cIm[k] + im[i2] * cRe[k];
        re[i2] = re[i1] - vr;
        im[i2] = im[i1] - vi;
        re[i1] += vr;
        im[i1] += vi;
      }
    }
  }
  return { re, im };
}

export function hakaru(samples, rInfo) {
  const N = samples.length;
  const fpz = FP / 1000.0;
  const voiced = rInfo.voiced || [];
  const moras = rInfo.moras || [];
  const f0Tr = rInfo.f0_tr || [0.0];
  let pk = 0.0;
  for (let i = 0; i < N; i++) { const av = Math.abs(samples[i]); if (av > pk) pk = av; }
  let vSq = 0.0, vCnt = 0;
  for (let t = 0; t < voiced.length; t++) {
    if (voiced[t]) {
      const a = Math.trunc(t * fpz * SR), b = Math.min(N, Math.trunc((t + 1) * fpz * SR));
      for (let i = a; i < b; i++) vSq += samples[i] * samples[i];
      vCnt += Math.max(0, b - a);
    }
  }
  const rmsV = vCnt > 0 ? Math.sqrt(vSq / vCnt) : rmsActive(samples);
  const crestDb = (pk > 0.0 && rmsV > 0.0) ? 20.0 * Math.log10(pk / (rmsV + 1e-12)) : 0.0;

  const nf = 2048, hb = (nf >> 1) + 1;
  const win = new Float64Array(nf);
  for (let k = 0; k < nf; k++) win[k] = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * k) / nf);
  const fq = new Float64Array(hb);
  for (let k = 0; k < hb; k++) fq[k] = (k * SR) / nf;

  const winSpec = (s0) => {
    const buf = new Float64Array(nf);
    const end = Math.min(nf, Math.max(0, N - s0));
    for (let k = 0; k < end; k++) buf[k] = samples[s0 + k] * win[k];
    return fftRadix2(buf);
  };

  const spAcc = new Float64Array(hb);
  if (N > 0 && N < nf && voiced.some(Boolean)) {
    const { re, im } = winSpec(0);
    for (let k = 0; k < hb; k++) spAcc[k] += re[k] * re[k] + im[k] * im[k];
  }
  for (let s0 = 0; s0 <= N - nf; s0 += nf) {
    const tc = Math.trunc(((s0 + (nf >> 1)) / SR) / fpz);
    if (tc >= 0 && tc < voiced.length && voiced[tc]) {
      const { re, im } = winSpec(s0);
      for (let k = 0; k < hb; k++) spAcc[k] += re[k] * re[k] + im[k] * im[k];
    }
  }
  let hasSp = false;
  for (let k = 0; k < hb; k++) if (spAcc[k] > 0.0) { hasSp = true; break; }
  let s0b = 1e-24, s1b = 1e-24, s2b = 1e-24;
  for (let k = 0; k < hb; k++) {
    if (fq[k] >= 120.0 && fq[k] < 1000.0) s0b += spAcc[k];
    else if (fq[k] >= 1000.0 && fq[k] < 2600.0) s1b += spAcc[k];
    else if (fq[k] >= 2600.0 && fq[k] < 5600.0) s2b += spAcc[k];
  }
  const b1 = hasSp ? 10.0 * Math.log10(s1b / s0b) : 0.0;
  const b2 = hasSp ? 10.0 * Math.log10(s2b / s0b) : 0.0;

  const taniAt = (ts) => {
    if (N === 0) return 0.0;
    const s0 = Math.max(0, Math.min(Math.max(0, N - nf), Math.trunc(ts * SR) - (nf >> 1)));
    const { re, im } = winSpec(s0);
    const spDb = new Float64Array(hb);
    for (let k = 0; k < hb; k++) spDb[k] = 10.0 * Math.log10(re[k] * re[k] + im[k] * im[k] + 1e-24);
    const f0 = Math.max(80.0, f0Tr[Math.min(f0Tr.length - 1, Math.max(0, Math.trunc(ts / fpz)))]);
    const diffs = [];
    for (let hIdx = 1; hIdx <= 6; hIdx++) {
      let pMax = -Infinity, vMin = Infinity, hp = false, hv = false;
      for (let k = 0; k < hb; k++) {
        if (fq[k] >= (hIdx - 0.18) * f0 && fq[k] <= (hIdx + 0.18) * f0) { if (spDb[k] > pMax) pMax = spDb[k]; hp = true; }
        if (fq[k] >= (hIdx + 0.32) * f0 && fq[k] <= (hIdx + 0.68) * f0) { if (spDb[k] < vMin) vMin = spDb[k]; hv = true; }
      }
      if (hp && hv) diffs.push(pMax - vMin);
    }
    return diffs.length ? diffs.reduce((a, b) => a + b, 0) / diffs.length : 0.0;
  };

  const cvs = moras.filter((m) => m.kind === "CV" && voiced.slice(Math.trunc(m.b / fpz), Math.trunc(m.e / fpz)).some(Boolean));
  const ml = cvs.length ? cvs[cvs.length - 1] : (moras[0] || null);
  const tCore = (ml && hasSp) ? taniAt(ml.b + 0.18 * (ml.e - ml.b)) : 0.0;
  const tTail = (ml && hasSp) ? taniAt(ml.b + 0.85 * (ml.e - ml.b)) : 0.0;
  return {
    dur_s: Number((N / SR).toFixed(2)),
    crest_db: Number(crestDb.toFixed(1)),
    band_1k_2k6_db: Number(b1.toFixed(1)),
    band_2k6_5k6_db: Number(b2.toFixed(1)),
    tani_core_db: Number(tCore.toFixed(1)),
    tani_tail_db: Number(tTail.toFixed(1)),
  };
}
