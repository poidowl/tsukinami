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
    description: "澄み（標準：VDP自励声帯×軟閉鎖2唇扉×5極声道のクリア女声 326Hz）",
    seed: 2024, hz: 326.0, fscale: 1.12, rate: 1.20,
    g_vo: 0.895, damp: 0.16, shin: 1.0, tilt_w: 3, sigh: 0.0, jitter: 0.0022, wander_st: 0.16,
  },
  toiki: {
    label: "吐息",
    description: "吐息（句末吐息と明瞭度・クリアさを両立した自然女声 292Hz）",
    seed: 2024, hz: 292.0, fscale: 1.07, rate: 1.22,
    g_vo: 0.885, damp: 0.16, shin: 1.0, tilt_w: 3, sigh: 0.42, jitter: 0.0024, wander_st: 0.16,
  },
  alto: {
    label: "アルト",
    description: "大人アルト（落ち着いた中低域 220Hz・句末吐息つきのハスキー女声）",
    seed: 2024, hz: 220.0, fscale: 1.02, rate: 1.26,
    g_vo: 0.875, damp: 0.16, shin: 1.0, tilt_w: 3, sigh: 0.55, jitter: 0.0028, wander_st: 0.16,
  },
  sasayaki: {
    label: "囁き",
    description: "半有声囁き（浅い扉くびれG=0.68で元のノイズの風を残す耳元ささやき）",
    seed: 2024, hz: 295.0, fscale: 1.08, rate: 1.26,
    g_vo: 0.68, damp: 0.16, shin: 1.0, tilt_w: 4, sigh: 0.78, jitter: 0.0030, wander_st: 0.16,
  },
  chibi: {
    label: "ちびっ子",
    description: "ちびっ子（短め声道 fscale=1.20・高ピッチ 375Hz・クリアな明るい声）",
    seed: 2024, hz: 375.0, fscale: 1.20, rate: 1.18,
    g_vo: 0.895, damp: 0.16, shin: 1.0, tilt_w: 3, sigh: 0.0, jitter: 0.0024, wander_st: 0.18,
    pau_iki: null, // v11.0: 子ども声は読点の息で ReazonSpeech の崩れが出たため完全無音のまま
  },
  ossan: {
    label: "おっさん",
    description: "おっさん（強粘膜逆流 ret=0.45 の VDP自励声帯×5極声道・低音 115Hz）",
    seed: 2024, hz: 115.0, fscale: 0.85, rate: 1.32,
    g_vo: 0.77, damp: 0.22, shin: 1.0,
    tilt_w: 5, sigh: 0.18, jitter: 0.0060, wander_st: 0.22,
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
  smooth: 30, ou_long: true, ei_long: true, vdl: -4.0, rdl: -4.0,
  VT: { a: [850, 1400, 2800], i: [330, 2750, 3300], u: [380, 1300, 2650], e: [520, 2350, 3000], o: [650, 1050, 2850] },
  LE: { lab: [0.75, 280], alv: [0.40, 1250], pal: [0.30, 1850], velF: [0.95, 300], velB: [1.05, 350] },
  gl: { y: [300, 2700, 3300], w: [360, 800, 2600] },
  nasT: { m: [280, 1100, 2500], n: [280, 1600, 2700], N: [300, 1300, 2600] },
  alvF2: 2350, alvF3: 3000,
  sc: 6000, shc: 3600, fg: 2.2, fvg: 0.15, ndl: -1.2, asp: 3, bg: 3.0, r3: 2000, rtrack: true,
  rate: 1.0, fin: 1.5, pau: 0.35, qn: 0.10,
  sil: -30.0, qlev: -18.0, decl: 1.5, devmax: 0.045, Nlev: -1.0, fend: -6.0, fend_at: 0.16,
  CDUR: { "": 0, k: 70, g: 50, s: 100, z: 70, sh: 100, j: 70, t: 60, d: 40, ch: 80, ts: 80, n: 50, h: 70, f: 70, m: 50, y: 60, r: 25, w: 55, b: 40, p: 70 },
  VDUR: { a: 90, e: 90, i: 80, o: 90, u: 85 },
  VL: { a: 0.0, e: -0.5, i: -0.8, o: -0.3, u: -0.3 },
  CL: {
    k: [-12, -5], t: [-12, -5], p: [-12, -5], ch: [-12, -4], ts: [-12, -4], g: [-4, -2], d: [-4, -2], b: [-4, -2],
    s: [-3, -3], sh: [-3, -3], z: [-3, -2], j: [-3, -2], h: [-2.4, -1.6], f: [-2.4, -1.6], m: [-1.5, -1.5], n: [-1.5, -1.5],
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
  const kata = toKata(text)
    .replace(/([アカサタナハマヤラワガザダバパ])ァ/g, "$1ー").replace(/([イキシチニヒミリギジヂビピ])ィ/g, "$1ー")
    .replace(/([ウクスツヌフムユルグズヅブプ])ゥ/g, "$1ー").replace(/([エケセテネヘメレゲゼデベペ])ェ/g, "$1ー")
    .replace(/([オコソトノホモヨロゴゾドボポ])ォ/g, "$1ー");
  for (const ch of kata) {
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
  const st = (b - a) / (k - 1), out = new Array(k);
  for (let i = 0; i < k; i++) out[i] = a + i * st;
  out[k - 1] = b;
  return out;
}

function clampSlice(n, a, b) {
  const s = a == null ? 0 : (a < 0 ? Math.max(0, n + a) : Math.min(n, a));
  const e = b == null ? n : (b < 0 ? Math.max(0, n + b) : Math.min(n, b));
  return [s, e < s ? s : e];
}

function setslice(L, a, b, vals) {
  const [s, e] = clampSlice(L.length, a, b);
  if (typeof vals !== "object" || vals === null) {
    for (let i = s; i < e; i++) L[i] = vals;
  } else {
    for (let i = s; i < e; i++) L[i] = vals[i - s];
  }
}

function interp(x, xp, fp) {
  const n = x.length;
  if (!xp.length) return new Array(n).fill(0.0);
  const out = new Array(n), last = xp.length - 1;
  let j = 0;
  for (let i = 0; i < n; i++) {
    const v = x[i];
    if (v < xp[0]) { out[i] = fp[0]; continue; }
    if (v >= xp[last]) { out[i] = fp[last]; continue; }
    while (j + 1 <= last && xp[j + 1] <= v) j++;
    out[i] = v === xp[j] ? fp[j] : fp[j] + ((fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j])) * (v - xp[j]);
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

export function tracksFromKana(text, pre = 0.6, post = 0.1, params = null) {
  const P = Object.assign({}, KOTOBA_PRM, params || {});
  const { ms, cuts } = tokenizeKana(text, P.phraseCuts || null);
  // 読点「、」および空白・スラッシュ句切れごとにチャンク分けし、句末助詞「は→ワ」と「おう→おー」「えい→えー」を適用
  const chunks = [];
  let curChunk = [], mOrd = 0;
  for (let j = 0; j < ms.length; j++) {
    if (ms[j] === "、") {
      if (curChunk.length) { chunks.push(curChunk); curChunk = []; }
      continue;
    }
    if (cuts.has(mOrd) && curChunk.length) { chunks.push(curChunk); curChunk = []; }
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
        const idx = idxs[k], t = ms[idx];
        if (t === "ウ" && pv === "o") {
          const prev = k > 0 ? ms[idxs[k - 1]] : "", prev2 = k > 1 ? ms[idxs[k - 2]] : "";
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
    const t = ms[j], fin = (j + 1 === ms.length) || (ms[j + 1] === "、");
    if (t === "、" || t === "ッ" || t === "ン") {
      ml.push({ t, cd: 0.0, vd: 0.0, final: fin, dev: false, kind: t === "、" ? "pau" : (t === "ッ" ? "Q" : "N"), c: "", v: null, pal: false });
    } else {
      const [c, v, pal] = parseKana(t, pv);
      pv = v;
      ml.push({ t, cd: 0.0, vd: 0.0, final: fin, dev: false, kind: "CV", c, v, pal });
    }
  }
  for (let j = 0; j < ml.length; j++) {
    const q = ml[j];
    if (q.kind !== "CV") continue;
    const nx = j + 1 < ml.length ? ml[j + 1] : null;
    const nvl = nx !== null && ((nx.kind === "CV" && VOICELESS.has(nx.c)) || nx.kind === "Q");
    q.dev = !P.no_dev && (q.v === "i" || q.v === "u") && VOICELESS.has(q.c) && (nvl || (q.final && q.c === "s"));
  }
  // 拍ごとの子音長 cd / 母音長 vd
  const cd_s = P.cd_s ?? 1.0, vd_s = P.vd_s ?? 1.0;
  for (const q of ml) {
    if (q.kind === "pau") { q.cd = 0.0; q.vd = P.pau; continue; }
    if (q.kind === "Q" || q.kind === "N") { q.cd = 0.0; q.vd = P.qn * ((q.final && q.kind === "Q") ? 1.3 : 1.0); continue; }
    let v = (P.VDUR[q.v] / 1000) * P.rate * vd_s;
    if (q.dev) v = Math.min(v, P.devmax);
    if (q.final) v *= P.fin;
    q.cd = (P.CDUR[q.c] / 1000) * P.rate * cd_s;
    q.vd = v;
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
    seq.push(Object.assign({}, q, { a, b: q.kind === "Q" ? e : ((q.kind === "N" || q.kind === "pau") ? a : b), e }));
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
    Tr = [0, 1, 2].map((j) => smooth1(interp(tfr, xp, kp.map((q) => q[j + 1])), P.smooth));
  }

  // 子音ノイズ帯域 bands と声道ゲート G1 / 閉鎖減衰 dl
  const G1 = new Array(n).fill(1.0);
  const dl = new Array(n).fill(0.0);
  const rawBands = [];
  for (const s of seq) {
    const i0 = fi(s.a), ib = fi(s.b), ie = fi(s.e);
    if (s.kind === "Q") { setslice(dl, i0, ie, -6); continue; }
    if (s.kind === "N") { setslice(G1, i0, ie, 0.87); setslice(dl, i0, ie, P.ndl); continue; }
    if (s.kind !== "CV" || ib <= i0) continue;
    const c = s.c, v = s.v, nc = ib - i0;
    if (c === "m" || c === "n") { setslice(G1, i0, ib, 0.87); setslice(dl, i0, ib, P.ndl); }
    const fp_ = ["s", "z", "sh", "j"].includes(c) ? [i0, ib] : ((c === "ch" || c === "ts") ? [i0 + Math.floor(nc / 2), ib] : null);
    if (fp_) {
      const cen = ["s", "z", "ts"].includes(c) ? P.sc : P.shc;
      rawBands.push([fp_[0], fp_[1], cen, P.fg + cen / 2500.0]);
      const [s0, e0] = clampSlice(n, fp_[0], fp_[1]), gm = VOICED_OBS.has(c) ? 0.45 : P.fvg;
      for (let i = s0; i < e0; i++) G1[i] *= gm;
    }
    if (c === "h" || c === "f") {
      setslice(G1, i0, ib, 0.4);
      if (v === "i" && c === "h") rawBands.push([i0, ib, 3400, 2.0]);
      else if (c === "f") rawBands.push([i0, ib, 1750, 1.08]);
      else rawBands.push([i0, ib, Math.round(vt(s)[1]), 1.25]);
    }
    if (["k", "g", "t", "d", "p", "b", "ch", "ts"].includes(c)) {
      const ce = i0 + ((c === "ch" || c === "ts") ? Math.floor(nc / 2) : Math.max(1, nc - P.asp));
      if (VOICED_OBS.has(c)) { setslice(G1, i0, ce, 0.8); setslice(dl, i0, ce, P.vdl); }
      else setslice(dl, i0, ce, -6);
      const cen = (c === "k" || c === "g") ? ((v === "i" || v === "e") ? 3000 : 1900)
        : (["t", "d", "ch", "ts"].includes(c) ? 4500 : 1200);
      if (!VOICED_OBS.has(c)) rawBands.push([ce, Math.min(ce + 2, ib + 1), cen, P.bg + cen / 2500.0]);
      if (c !== "ch" && c !== "ts") setslice(G1, ce, ib, VOICED_OBS.has(c) ? 1 : 0.4);
    }
    if (c === "r") setslice(dl, i0, ib, P.rdl);
  }

  // 音量対数曲線 loud と有声フラグ voiced
  const nxcls = (nx) => {
    if (!nx || nx.kind === "pau") return "end";
    if (nx.kind !== "CV") return nx.kind;
    return nx.c ? MANNER[nx.c] + (VOICELESS.has(nx.c) ? "-vl" : "") : "V";
  };
  let L = new Array(n).fill(P.sil);
  for (let j = 0; j < seq.length; j++) {
    const s = seq[j], ia = fi(s.a), ib = fi(s.a + s.cd), ie = fi(s.e);
    const nx = j + 1 < seq.length ? seq[j + 1] : null;
    if (s.kind === "pau") continue;
    if (s.kind === "Q") { setslice(L, ia, ie, P.qlev); continue; }
    if (s.kind === "N") {
      setslice(L, ia, ie, P.Nlev);
    } else {
      if (P.CL[s.c] && ib > ia) {
        const [c1, c2] = P.CL[s.c], im = ia + Math.trunc(0.7 * (ib - ia));
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
        if (k > 0) setslice(L, ib, ib + k, linspace(Math.min(ib > 0 ? L[ib - 1] : P.sil, lv - 3), lv, k));
      }
    }
    const cls = nxcls(nx);
    if (cls === "end") {
      const k = s.kind === "CV" ? (ie - ib) : (ie - ia), h = Math.trunc(k * P.fend_at);
      if (k - h > 0) setslice(L, ie - k + h, ie, linspace(L[ie - k + h], P.fend, k - h));
    } else if (P.TAILT[cls] !== undefined) {
      const lv = L[ie - 1], k = Math.min(12, ie - ib);
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
    if (s.kind === "pau" || s.kind === "Q") continue;
    if (s.kind === "N" || !VOICELESS.has(s.c)) setslice(vo, fi(s.a), fi(s.a + s.cd), true);
    if (!s.dev) setslice(vo, fi(s.a + s.cd), fi(s.e), true);
  }

  return {
    fp_ms: FP, n,
    F1: Tr[0], F2: Tr[1], F3: Tr[2],
    G1: smooth1(G1, 10), dl: smooth1(dl, 10), loud, voiced: vo,
    bands: rawBands.map(([a, b, c, g]) => [(a * FP) / 1000, (b * FP) / 1000, c, g]),
    moras: seq.map((s) => ({ t: s.t, kind: s.kind, c: s.c, v: s.v, a: s.a, b: s.b, e: s.e })),
  };
}

// ============================================================================
// 2. accent — 東京式ピッチアクセント推定 & 手動韻律記号 (' 核, 0 平板, / 句切れ, 、 間, ? 疑問)
// ============================================================================
const SPECIAL = new Set(["ン", "ッ", "ー"]);
const PART = new Set(Array.from("モニガヲデヘテ"));
const LONGV = { a: "ア", i: "イ", u: "ウ", e: "エイ", o: "オウ" };

export const ACCENT_NORMAL = { reg: 340.0, rng: 6.2, jump: 2.8, fall: 3.8, sag: 0.9, lag: 1.0, rlag: 0.5, ds: 2.0, ds_h: 0.5, reset: 0.6, decl: 1.4, fin: 2.6, qrise: 5.0, sm: 35.0 };
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

let _cs = new Float64Array(0);

// 前後に位相ずれのない中心移動平均（累積和で O(N)）
function heikin(x, W, out = null) {
  const n = x.length, h = Math.max(1, Math.trunc(W / 2));
  if (_cs.length < n + 1) _cs = new Float64Array(n + 1);
  const cs = _cs, y = out || new Float64Array(n);
  cs[0] = 0.0;
  for (let i = 0; i < n; i++) cs[i + 1] = cs[i] + x[i];
  for (let i = 0; i < n; i++) {
    const a = i - h > 0 ? i - h : 0, b = i + h + 1 < n ? i + h + 1 : n;
    y[i] = (cs[b] - cs[a]) / (b - a);
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

function rmsActive(x) {
  let s = 0.0, c = 0;
  for (let i = 0; i < x.length; i++) if (x[i] !== 0.0) { s += x[i] * x[i]; c++; }
  return Math.sqrt(s / (c || 1));
}

function voicedRms(samples, voiced, fpz) {
  const N = samples.length;
  let vSq = 0.0, vCnt = 0;
  for (let t = 0; t < voiced.length; t++) {
    if (voiced[t]) {
      const a = Math.trunc(t * fpz * SR), b = Math.min(N, Math.trunc((t + 1) * fpz * SR));
      for (let i = a; i < b; i++) vSq += samples[i] * samples[i];
      vCnt += Math.max(0, b - a);
    }
  }
  return { vSq, vCnt };
}

function normalizeToRms(x, targetRms = 0.16, ceiling = 0.891, gateStart = 0, gateEnd = x.length) {
  const out = new Float32Array(x.length);
  let s = 0.0, c = 0;
  for (let i = gateStart; i < gateEnd; i++) { s += x[i] * x[i]; c++; }
  let gain = targetRms / (Math.sqrt(s / (c || 1)) || 1.0), pk = 0.0;
  for (let i = gateStart; i < gateEnd; i++) { const av = Math.abs(x[i]) * gain; if (av > pk) pk = av; }
  if (pk > ceiling) gain *= ceiling / pk;
  const fade = Math.min(882, Math.floor((gateEnd - gateStart) / 4));
  for (let i = gateStart; i < gateEnd; i++) {
    const w = i - gateStart < fade ? (i - gateStart) / fade : (gateEnd - 1 - i < fade ? (gateEnd - 1 - i) / fade : 1.0);
    out[i] = x[i] * gain * w;
  }
  return out;
}

// ============================================================================
// 4. 本体：1本のホワイトノイズから4手で彫る音声・歌声合成
// ============================================================================

function eachNonPauMora(moras, arr, fn) {
  if (!arr) return;
  let k = 0;
  for (const m of moras) {
    if (m.kind === "pau") continue;
    if (k < arr.length && arr[k] != null && Number.isFinite(Number(arr[k]))) fn(m, Number(arr[k]), k);
    k++;
  }
}

function applyLoudDb(r, loud_db, fpz) {
  if (!loud_db) return;
  const n = r.n, loud = r.loud.slice();
  eachNonPauMora(r.moras, loud_db, (m, db) => {
    // env = exp(loud/2) なので、dB を同じ倍率にするには Δloud = 2 * ln(10^(dB/20))
    const dL = 2.0 * Math.log(Math.pow(10, db / 20.0));
    const ib = Math.max(0, Math.trunc(m.b / fpz)), ie = Math.min(n, Math.trunc(m.e / fpz));
    const ramp = Math.max(1, Math.min(4, Math.trunc((ie - ib) / 4))); // 約 20ms
    for (let t = ib; t < ie; t++) {
      const k = Math.min(t - ib, ie - 1 - t);
      const w = k >= ramp ? 1.0 : Math.pow(Math.sin((0.5 * Math.PI * k) / ramp), 2);
      loud[t] += dL * w;
    }
  });
  r.loud = loud;
}

function applyF0St(f0_fr, r, n, fpz, f0_st) {
  if (!f0_st) return;
  eachNonPauMora(r.moras, f0_st, (m, st) => {
    const mul = Math.pow(2.0, st / 12.0);
    const ib = Math.max(0, Math.trunc(m.b / fpz)), ie = Math.min(n, Math.trunc(m.e / fpz));
    const ramp = Math.max(1, Math.min(4, Math.trunc((ie - ib) / 4)));
    for (let t = ib; t < ie; t++) {
      const k = Math.min(t - ib, ie - 1 - t);
      const w = k >= ramp ? 1.0 : Math.pow(Math.sin((0.5 * Math.PI * k) / ramp), 2);
      f0_fr[t] *= Math.pow(mul, w);
    }
  });
}

export function makeHitofude(text, opts = {}) {
  const {
    seed = 2024,
    hz = 326.0,       // 基準ピッチ高さ (Hz)。女声 290〜340、アルト 220、ちびっ子 375、男声 105〜155
    fscale = 1.12,    // 声道長逆スケール（フォルマント倍率）。1.07〜1.12=女声、1.02=アルト、0.85=太い男声
    rate = 1.20,      // 話速倍率（小さいほど速い、1.20〜1.26=自然な会話）
    g_vo = 0.895,     // 有声くびれ深さ G (0.0〜0.97)。扉の締まり・倍音の谷深さを決める
    tilt_w = 3,       // 高域粗削り幅 w (整数 >=1)。3=クリア女声、4=囁き、5=低音おっさん
    sigh = 0.0,       // 句末の息抜き量 (0.0〜1.0)。句末母音後半で扉を緩め、声を元の吐息へ戻す
    jitter = 0.0022,  // 1周期ごとの微細周期揺らぎ率 (0.0=完全周期ロボ)
    wander_st = 0.16, // ピッチの緩やかな自然漂い幅 (半音、0.0=冷凍固定)
    damp = 0.16,      // ロボ片道コム帰還路の高域減衰 (0.0..0.95)
    shin = 1.0,       // 声門2唇粘膜扉×5極声道の再帰結合度 (1.0=既定、0.0=冷凍ロボ用の片道コム)
    level_k = 0.65,   // 母音定常部の1スカラー整音強度 (0.0〜1.0、瞬間スペクトル傾斜変化 0.00 dB)
    pre = 0.6,        // 発話前の無音長 (秒)
    post = 0.1,       // 発話後の無音長 (秒)
    uta_hz = null,    // 歌モード：モーラごとの目標周波数配列 [Hz, ...]
    vd_ms = null,     // 歌モード：モーラごとの母音長配列 [ms, ...]
    f0_st = null,     // 任意: ポーズ以外のモーラごとの F0 加減 [半音]（null 要素は変更しない）
    loud_db = null,   // 任意: ポーズ以外のモーラごとの母音ゲイン [dB]（null 要素は変更しない）
    vib_c = 6.0,      // 歌モード：長音ビブラート深さ (cent)
    captureSteps = false, // true のとき [原石0, ①声帯波/谷, ②粘膜扉/角, ③声道, ④完成] の5波形を返す
    rawAirMul = 0.6,  // 扉を通る生ノイズ rawAir の倍率 (既定 0.6)
    pau_s = null,     // 読点「、」の間の長さ (秒)。null で従来の 0.35 秒
    pau_iki = -30,    // 読点の間に残す息の床 (dB, 有声部 RMS 比)。null で完全無音
  } = opts;

  let accentKw = null, targetText = text, phraseCuts = null;
  if (/['’0/| 　?？]/.test(text) && !uta_hz) {
    const [clean, phrases] = annotate(text);
    accentKw = { phrases, question: /[?？]$/.test(text.trim()) };
    targetText = clean;
    phraseCuts = phrases.slice(1).map((p) => p[0]);
  }

  const fpz = FP / 1000.0;
  const prm = { rate, fend_at: sigh > 0.0 ? 0.45 : 0.16, phraseCuts };
  if (vd_ms) prm.vd_ms = vd_ms;
  if (pau_s != null) prm.pau = Math.max(0.0, +pau_s);
  if (uta_hz && uta_hz.length) { prm.no_dev = true; prm.ou_long = false; prm.ei_long = false; }
  const r = tracksFromKana(targetText, pre, post, prm);
  applyLoudDb(r, loud_db, fpz);
  const n = r.n, N = Math.trunc(n * fpz * SR);
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
  let f0_fr, vibWave = null;
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
    if (vib_c > 0.0) {
      const vHz = 4.2 + 1.8 * (x[0] * 0.5 + 0.5), wv = Math.max(3, Math.round(1000.0 / FP / vHz / 2.0));
      const lenV = n + 30 * wv, vn = new Float64Array(lenV);
      for (let i = 0; i < lenV; i++) vn[i] = x[(i * 220) % N];
      for (let i = wv; i < lenV; i++) vn[i] -= 0.92 * vn[i - wv];
      const vw = arakezuri(vn, Math.max(2, Math.floor(wv / 2)), 2).subarray(30 * wv, 30 * wv + n);
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
    const acc = hz < 200.0 ? ACCENT_NORMAL : ACCENT_CUTE;
    f0_fr = f0Rule(r.moras, n, Object.assign({}, acc, { reg: hz }, accentKw || {}));
  }

  applyF0St(f0_fr, r, n, fpz, f0_st);

  // 句末の息抜き軌道 sigh_fr：有声句の最後の母音後半 (u > 0.30) でくびれ G をほどく
  const sigh_fr = new Array(n).fill(0.0);
  if (sigh > 0.0) {
    const hasVoIn = (m_) => {
      const a = Math.max(0, Math.trunc(m_.b / fpz)), b = Math.min(n, Math.trunc(m_.e / fpz));
      for (let t_ = a; t_ < b; t_++) if (r.voiced[t_]) return true;
      return false;
    };
    for (let idx_m = 0; idx_m < r.moras.length; idx_m++) {
      const m_ = r.moras[idx_m];
      const ib = Math.max(0, Math.trunc(m_.b / fpz)), ie = Math.min(n, Math.trunc(m_.e / fpz));
      if (m_.kind !== "CV" || (ie - ib) < 7 || !hasVoIn(m_)) continue;
      let remVo = false;
      for (let k2 = idx_m + 1; k2 < r.moras.length && r.moras[k2].kind !== "pau"; k2++) {
        if (hasVoIn(r.moras[k2])) { remVo = true; break; }
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
  const F1 = new Array(n), F2 = new Array(n), F3 = new Array(n), F4 = new Array(n);
  for (let t = 0; t < n; t++) {
    F1[t] = Math.max(r.F1[t] * fs, r.voiced[t] ? 1.04 * f0_fr[t] : 180.0);
    F2[t] = Math.min(Math.max(r.F2[t] * fs, F1[t] + 280.0), 8500.0);
    F3[t] = Math.min(Math.max(r.F3[t] * fs, F2[t] + 350.0), 9000.0);
    F4[t] = Math.min(8600.0, F3[t] + 1150.0 * fs);
  }

  const f_cons_cen = new Array(n).fill(2500.0), f_cons_w = new Array(n).fill(0.0), cons_sharp = new Array(n).fill(0.0);
  for (const [t0, t1, cen, lev] of r.bands.slice().sort((a, b) => a[0] - b[0])) {
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

  const vo_sm = smooth1(r.voiced.map((v) => (v ? 1.0 : 0.0)), 10);
  const sigh_sm = smooth1(sigh_fr, 14);
  const g_fr = new Array(n);
  for (let t = 0; t < n; t++) g_fr[t] = vo_sm[t] * g_vo * (1.0 - 0.88 * sigh_sm[t]);

  // サンプル単位の基本周期 PER[i] (原石ノイズ x からダシをとった自然漂い wander + 周期ごとの微細ジッタ)
  const f0S = perSample(f0_fr, N);
  const wander = furafura(x, 0.0, wander_st, 0.09);
  const PER = new Float64Array(N);
  for (let i = 0; i < N; i++) PER[i] = SR / Math.max(60.0, f0S[i] * Math.pow(2.0, wander[i] / 12.0));
  const hRef = Math.max(85.0, hz);
  if (jitter > 0.0) {
    for (let idxP = 0; idxP < N;) {
      const pl = Math.max(2, Math.trunc(PER[idxP])), jf = 1.0 + jitter * x[idxP], end = Math.min(N, idxP + pl);
      for (let k = idxP; k < end; k++) PER[k] *= jf;
      idxP += pl;
    }
    if (shin > 0.0) heikin(PER, Math.max(10, Math.round(SR / (hRef * 6.0))), PER);
  }

  const GS = perSample(g_fr, N);
  const wNorm = wander_st > 0.0 ? (1.0 / wander_st) : 0.0;
  if (wNorm > 0.0) for (let i = 0; i < N; i++) GS[i] = Math.min(0.975, Math.max(0.0, GS[i] * (1.0 + 0.032 * wander[i] * wNorm)));
  const tw = Math.max(1, Math.round(tilt_w));
  const ycRad = new Float64Array(N);
  let x1 = null, x2 = null;

  // === Step 1–3: 単一因果ループ（shin>0: VDP自励声帯×軟閉鎖2唇扉×5極声道 / shin=0: 冷凍ロボ片道コム） ===
  // 低音 (hiMix=0) は強い粘膜逆流 ret=0.45 と厚い非線形 mu でダンディな艶を残し、高音 (hiMix=1) は軽結合でクリアに鳴らす
  const coupled = shin > 0.0;
  const hiMix = Math.min(1.0, Math.max(0.0, (hRef - 125.0) / 85.0));
  x = karuku(x, coupled ? 320 : (hz >= 200.0 ? 115 : 220));
  const xClean = arakezuriT(x.slice(), tw, (coupled && hiMix > 0.5) ? 1 : 2, perSample(cons_sharp, N));
  const softPos = (v) => { const z = v * 12.0; return z > 20.0 ? v : (z < -20.0 ? 0.0 : Math.log1p(Math.exp(z)) / 12.0); };
  const pLungWalk = coupled ? furafura(x, 0.38, (0.14 - 0.10 * hiMix) * 0.15, 0.045 + 0.175 * hiMix) : null;
  const F5 = F4.map((v) => (fs < 0.92 ? Math.min(4850.0, v * 1.26) : Math.min(8800.0, v + 1100.0 * fs)));
  const FS = [F1, F2, F3, F4, F5].map((Fk) => perSample(Fk, N));
  const nPoles = coupled ? 5 : 4;
  const gBuf = coupled ? null : new Float64Array(N), gBuf2 = coupled ? null : new Float64Array(N);
  const vdpBuf = (coupled && captureSteps) ? new Float64Array(N) : null, uOut = new Float64Array(N), yc = new Float64Array(N);
  const twoPiSR = (2.0 * Math.PI) / SR, piSR = Math.PI / SR;
  const ret = 0.45 * shin * (1.0 - 0.75 * hiMix), qSoft = coupled ? (1.45 - 0.57 * hiMix) : 1.0;
  const rawAir = (0.02 - 0.008 * hiMix) * rawAirMul;
  const radK = coupled ? (0.42 + 0.46 * hiMix) : 0.70;
  const loGain = 1.805 - 0.155 * hiMix, upGain = 3.10 - 0.10 * hiMix, knee = 0.22 - 0.04 * hiMix;
  const bwMinP = [80.0 + (coupled ? 70.0 * hiMix : 0.0), 110.0 * qSoft, 150.0 * qSoft, 220.0 * qSoft, 260.0 * qSoft];
  const qDivP = [8.0 - (coupled ? 2.8 * hiMix : 0.0), 11.0 / qSoft, 13.0 / qSoft, 14.0 / qSoft, 14.0 / qSoft];
  const dMulP = [150.0 - 60.0 * hiMix, 50.0 - 20.0 * hiMix, 30.0 - 15.0 * hiMix, 0.0, 0.0];
  const y1 = new Float64Array(5), y2 = new Float64Array(5);
  let doorLp1 = 0.0, doorLp2 = 0.0, doorPrev = 0.0, gLp1 = 0.0, gLp2 = 0.0, uFlow = 0.0, p1Prev = 0.0, ycPrev = 0.0, vx = 0.0, vv = 0.0;
  for (let i = 0; i < N; i++) {
    const g = GS[i], vo = Math.min(1.0, g / (g_vo || 1.0)), p = PER[i];
    let sig;
    if (coupled) {
      const pRet = Math.tanh((0.70 * (y1[0] - p1Prev) + 0.30 * (ycPrev - (i > 1 ? yc[i - 2] : 0.0))) * 4.5);
      p1Prev = y1[0];
      // VDP非線形度 mu/w0: 高音(0.18)=澄んだ弱非線形、低音(0.43)=厚い粘膜の弛緩寄り（草薙の中で選んだ値、外部数値不使用）
      const w0 = (2.0 * Math.PI) / p, mu = (0.18 + 0.25 * (1.0 - hiMix)) * w0;
      vv += -w0 * w0 * vx + mu * (1.0 - vx * vx) * vv + 0.015 * w0 * xClean[i] + ret * 0.35 * w0 * doorPrev * pRet;
      vx += vv;
      if (Math.abs(vx) > 4.0) { vx = Math.sign(vx) * 4.0; vv = 0.0; }
      // 高音のみ OQ 休止開度バイアス (+0.32) と軽めの閉じ際で半波整流の奇数倍音陥没を解消（草薙内選定値・外部数値不使用）
      const gVal = (vx + 0.32 * hiMix) * 0.35;
      if (vdpBuf) vdpBuf[i] = gVal;
      const aDoor = Math.exp(-(8.20 + 7.80 * hiMix) / p);
      doorLp1 = (1.0 - aDoor) * gVal + aDoor * doorLp1;
      doorLp2 = (1.0 - aDoor) * doorLp1 + aDoor * doorLp2;
      const uUp = doorLp2 * upGain, uLo = doorLp1 * loGain;
      const neck = hiMix > 0.4
        ? softPos(0.5 * (uUp + uLo - Math.sqrt((uUp - uLo) * (uUp - uLo) + 0.010)))
        : Math.max(0.0, Math.min(uUp, uLo));
      const door = vo > 0.01 ? ((1.0 - hiMix + hiMix * vo) * (neck / (neck + knee))) : 0.0;
      doorPrev = door;
      if (door > 0.0) {
        const pLoad = Math.tanh((0.70 * y1[0] + 0.30 * ycPrev) * 3.0);
        const aFl = 0.88 + ((door > uFlow ? 0.28 : 0.02) - 0.88) * hiMix;
        uFlow = aFl * uFlow + (1.0 - aFl) * door * (pLungWalk[i] + rawAir * xClean[i]) * (1.0 - ret * 0.50 * pLoad);
      } else uFlow *= (0.50 - 0.28 * hiMix);
      sig = (1.0 - vo) * 0.28 * xClean[i] + vo * (uFlow * 3.6);
    } else {
      const cIn = g > 1e-4 ? Math.sqrt(1.0 - g * g) : 1.0;
      const fb1 = readDelay(gBuf, i, p); gLp1 = (1.0 - damp) * fb1 + damp * gLp1;
      gBuf[i] = g > 1e-4 ? (cIn * xClean[i] + g * gLp1) : xClean[i];
      const fb2 = readDelay(gBuf2, i, p); gLp2 = (1.0 - damp) * fb2 + damp * gLp2;
      sig = g > 1e-4 ? (cIn * gBuf[i] + g * gLp2) : gBuf[i];
      gBuf2[i] = sig;
    }
    uOut[i] = sig;
    for (let k = 0; k < nPoles; k++) {
      const fk = FS[k][i], rk = Math.exp(-piSR * (Math.max(bwMinP[k], fk / qDivP[k]) + dMulP[k] * doorPrev));
      const ck = -rk * rk, bk = 2.0 * rk * Math.cos(twoPiSR * fk);
      sig = (1.0 - bk - ck) * sig + bk * y1[k] + ck * y2[k];
      y2[k] = y1[k]; y1[k] = sig;
    }
    yc[i] = sig; ycPrev = sig;
  }
  if (captureSteps) { x1 = coupled ? vdpBuf : gBuf2.slice(); x2 = uOut.slice(); }
  x = xClean;
  for (let i = 1; i < N; i++) ycRad[i] = yc[i] - radK * yc[i - 1];
  if (coupled) {
    // 扉の片側整流で生じる F0 以下の低域濁り (40..0.72*hRef Hz) を 2極 Butterworth HPF で削る
    const w0 = twoPiSR * (0.72 * hRef), cw = Math.cos(w0), al = Math.sin(w0) / Math.SQRT2;
    const a0 = 1.0 + al, b0 = (1.0 + cw) * 0.5 / a0, b1 = -(1.0 + cw) / a0, b2 = b0, a1 = (-2.0 * cw) / a0, a2 = (1.0 - al) / a0;
    let hx1 = 0.0, hx2 = 0.0, hy1 = 0.0, hy2 = 0.0;
    for (let i = 0; i < N; i++) {
      const xi = ycRad[i], yi = b0 * xi + b1 * hx1 + b2 * hx2 - a1 * hy1 - a2 * hy2;
      hx2 = hx1; hx1 = xi; hy2 = hy1; hy1 = yi; ycRad[i] = yi;
    }
  }
  let vInSq = 0.0, vOutSq = 0.0, vCnt = 0;
  for (let i = 1; i < N; i++) if (GS[i] > 0.25) { vInSq += x[i] * x[i]; vOutSq += ycRad[i] * ycRad[i]; vCnt++; }
  const vScale = (coupled ? 0.45 : 0.43) * ((vCnt > 0 ? Math.sqrt(vInSq / vCnt) : rmsActive(x)) / ((vCnt > 0 ? Math.sqrt(vOutSq / vCnt) : rmsActive(ycRad)) || 1.0));

  // 子音・ハ行気息帯域 bpc：ピーク利得一定の因果2極ゼロDCバンドパス H(z) = 0.5*(1-r^2)*(1-z^-2) / (1 - 2r cos w0 z^-1 + r^2 z^-2)
  const FCEN = perSample(f_cons_cen, N), bpc = new Float64Array(N);
  let bp1 = 0.0, bp2 = 0.0;
  for (let i = 0; i < N; i++) {
    const f = FCEN[i], r0 = Math.exp(-piSR * Math.max(420.0, f * 0.38));
    const o = 0.5 * (1.0 - r0 * r0) * (x[i] - (i > 1 ? x[i - 2] : 0.0)) + 2.0 * r0 * Math.cos(twoPiSR * f) * bp1 - r0 * r0 * bp2;
    bpc[i] = o; bp2 = bp1; bp1 = o;
  }
  const G1S = perSample(r.G1, N), FCW = perSample(smooth1(f_cons_w, 6), N);

  const y = new Float64Array(N);
  for (let i = 0; i < N; i++) y[i] = vScale * G1S[i] * ycRad[i] + 0.40 * FCW[i] * bpc[i];
  const x3 = captureSteps ? y.slice() : null;

  // === Step 4: 【引き算④】1スカラー整音 ＋ 時間包絡 ===
  if (level_k > 0.0) {
    const sq = new Float64Array(N);
    for (let i = 0; i < N; i++) sq[i] = y[i] * y[i];
    const pLoc = heikin(sq, Math.trunc(0.028 * SR));
    const vPows = [];
    for (let t = 0; t < n; t++) {
      if (r.voiced[t] && sigh_sm[t] < 0.1 && cons_sharp[t] < 0.1) vPows.push(pLoc[Math.trunc((t + 0.5) * fpz * SR)]);
    }
    vPows.sort((a, b) => a - b);
    const refRms = vPows.length ? Math.sqrt(vPows[Math.floor(vPows.length / 2)]) : (rmsActive(y) || 1.0);
    const eps = Math.pow(0.12 * refRms, 2) + 1e-24;
    const wLvFr = new Array(n);
    for (let t = 0; t < n; t++) wLvFr[t] = level_k * vo_sm[t] * (1.0 - sigh_sm[t]) * (1.0 - cons_sharp[t]);
    const wLv = perSample(smooth1(wLvFr, 14), N), rawGlv = new Float64Array(N);
    for (let i = 0; i < N; i++) rawGlv[i] = 1.0 + wLv[i] * (Math.min(2.2, Math.max(0.45, refRms / Math.sqrt(pLoc[i] + eps))) - 1.0);
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
  // 読点の息の床 pau_iki：完全無音を彫り切らず、同じ原石ノイズが無声のまま声道 (5極) と放射を通った吐息 ycRad を、
  // 間の区間だけ有声部 RMS の pau_iki dB にうっすら残す（両端は上げ下げの余弦窓）。null なら一切触らない
  if (pau_iki != null && Number.isFinite(+pau_iki)) {
    const pauz = r.moras.filter((m_) => m_.kind === "pau" && m_.e > m_.a);
    if (pauz.length) {
      let vSq = 0.0, vCnt = 0;
      for (let t = 0; t < n; t++) {
        if (!r.voiced[t]) continue;
        const a_ = Math.trunc(t * fpz * SR), b_ = Math.min(N, Math.trunc((t + 1) * fpz * SR));
        for (let i = a_; i < b_; i++) { vSq += y[i] * y[i]; vCnt++; }
      }
      const vRms = Math.sqrt(vSq / (vCnt || 1));
      let bSq = 0.0, bCnt = 0;
      for (const m_ of pauz) {
        for (let i = Math.max(0, Math.trunc(m_.a * SR)); i < Math.min(N, Math.trunc(m_.e * SR)); i++) { bSq += ycRad[i] * ycRad[i]; bCnt++; }
      }
      const bRms = Math.sqrt(bSq / (bCnt || 1)) || 1.0, gIki = vRms * Math.pow(10.0, +pau_iki / 20.0) / bRms;
      for (const m_ of pauz) {
        const ia = Math.max(0, Math.trunc(m_.a * SR)), ie = Math.min(N, Math.trunc(m_.e * SR));
        const ramp = Math.max(1, Math.min(Math.trunc(0.06 * SR), Math.trunc((ie - ia) / 3)));
        for (let i = ia; i < ie; i++) {
          const k = Math.min(i - ia, ie - 1 - i), w = k >= ramp ? 1.0 : Math.pow(Math.sin((0.5 * Math.PI * k) / ramp), 2);
          y[i] += gIki * w * ycRad[i];
        }
      }
      pk = 0.0;
      for (let i = 0; i < N; i++) { const av = Math.abs(y[i]); if (av > pk) pk = av; }
    }
  }
  const out = new Float32Array(N), scale = 0.891 / (pk || 1.0);
  for (let i = 0; i < N; i++) out[i] = y[i] * scale;

  let steps = null;
  if (captureSteps) {
    const { vSq, vCnt } = voicedRms(out, r.voiced, fpz);
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

const FFT_CACHE = new Map();

export function fftRadix2(reIn) {
  const n = reIn.length;
  let plan = FFT_CACHE.get(n);
  if (!plan) {
    const bits = Math.round(Math.log2(n)), bitrev = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      let x = i, r = 0;
      for (let b = 0; b < bits; b++) { r = (r << 1) | (x & 1); x >>= 1; }
      bitrev[i] = r;
    }
    const twRe = [], twIm = [], steps = [];
    for (let step = 2; step <= n; step <<= 1) {
      const half = step >> 1, cRe = new Float64Array(half), cIm = new Float64Array(half);
      for (let k = 0; k < half; k++) {
        const ang = (-2.0 * Math.PI * k) / step;
        cRe[k] = Math.cos(ang); cIm[k] = Math.sin(ang);
      }
      steps.push(step); twRe.push(cRe); twIm.push(cIm);
    }
    plan = { bitrev, steps, twRe, twIm };
    FFT_CACHE.set(n, plan);
  }
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) re[i] = reIn[plan.bitrev[i]];
  for (let si = 0; si < plan.steps.length; si++) {
    const step = plan.steps[si], half = step >> 1, cRe = plan.twRe[si], cIm = plan.twIm[si];
    for (let s = 0; s < n; s += step) {
      for (let k = 0; k < half; k++) {
        const i1 = s + k, i2 = i1 + half;
        const vr = re[i2] * cRe[k] - im[i2] * cIm[k], vi = re[i2] * cIm[k] + im[i2] * cRe[k];
        re[i2] = re[i1] - vr; im[i2] = im[i1] - vi;
        re[i1] += vr; im[i1] += vi;
      }
    }
  }
  return { re, im };
}

export function hakaru(samples, rInfo) {
  const N = samples.length, fpz = FP / 1000.0;
  const voiced = rInfo.voiced || [], moras = rInfo.moras || [], f0Tr = rInfo.f0_tr || [0.0];
  let pk = 0.0;
  for (let i = 0; i < N; i++) { const av = Math.abs(samples[i]); if (av > pk) pk = av; }
  const { vSq, vCnt } = voicedRms(samples, voiced, fpz);
  const rmsV = vCnt > 0 ? Math.sqrt(vSq / vCnt) : rmsActive(samples);
  const crestDb = (pk > 0.0 && rmsV > 0.0) ? 20.0 * Math.log10(pk / (rmsV + 1e-12)) : 0.0;

  const nf = 2048, hb = (nf >> 1) + 1;
  const win = new Float64Array(nf), fq = new Float64Array(hb);
  for (let k = 0; k < nf; k++) win[k] = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * k) / nf);
  for (let k = 0; k < hb; k++) fq[k] = (k * SR) / nf;

  const winSpec = (s0) => {
    const buf = new Float64Array(nf), end = Math.min(nf, Math.max(0, N - s0));
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
  let hasSp = false, s0b = 1e-24, s1b = 1e-24, s2b = 1e-24;
  for (let k = 0; k < hb; k++) {
    if (spAcc[k] > 0.0) hasSp = true;
    if (fq[k] >= 120.0 && fq[k] < 1000.0) s0b += spAcc[k];
    else if (fq[k] >= 1000.0 && fq[k] < 2600.0) s1b += spAcc[k];
    else if (fq[k] >= 2600.0 && fq[k] < 5600.0) s2b += spAcc[k];
  }

  const taniAt = (ts) => {
    if (N === 0) return 0.0;
    const { re, im } = winSpec(Math.max(0, Math.min(Math.max(0, N - nf), Math.trunc(ts * SR) - (nf >> 1))));
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
  return {
    dur_s: Number((N / SR).toFixed(2)),
    crest_db: Number(crestDb.toFixed(1)),
    band_1k_2k6_db: Number((hasSp ? 10.0 * Math.log10(s1b / s0b) : 0.0).toFixed(1)),
    band_2k6_5k6_db: Number((hasSp ? 10.0 * Math.log10(s2b / s0b) : 0.0).toFixed(1)),
    tani_core_db: Number(((ml && hasSp) ? taniAt(ml.b + 0.18 * (ml.e - ml.b)) : 0.0).toFixed(1)),
    tani_tail_db: Number(((ml && hasSp) ? taniAt(ml.b + 0.85 * (ml.e - ml.b)) : 0.0).toFixed(1)),
  };
}
