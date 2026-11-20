/**
 * hodoki/zarazara/yomeru.mjs — 「読める」を落としてないかの客観代理（ASR なし）
 *
 * 本物の読み取り（tsukinami のイタコ ASR）は M6 の関亡婆＝ニューラルなので、ここでは使わない。代わりに：
 *   ① michi のフォルマント軌跡 F1..F3 を、基準音と同じ時刻のフレームで比べた |ΔF| の中央値 [Hz]
 *   ② スペクトル包絡距離：25 ms 窓・10 ms 送りの対数スペクトルをケプストラム 1..24 次で滑らかにし、
 *      フレームごとのケプストラム距離（dB, 10/ln10·√(2Σc²)）を有音フレームで平均
 * 物差しとして「同じ設定で seed だけ違う 2 本」の距離も出す（それ以下なら seed の揺れ程度の差）。
 * 限界：言葉が聞き取れるかを直接は測っていない。包絡とフォルマントが変わっていないことしか言えない。
 */
import { analyzeMichi } from "../michi.mjs";
import { fft } from "../soroi.mjs";

export function cepFrames(x, sr, nc = 24) {
  const W = Math.round(0.025 * sr), H = Math.round(0.01 * sr), N = 2048;
  const out = [];
  for (let s = 0; s + W <= x.length; s += H) {
    const re = new Float64Array(N), im = new Float64Array(N);
    let e = 0;
    for (let i = 0; i < W; i++) { const w = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (W - 1)); re[i] = x[s + i] * w; e += re[i] * re[i]; }
    fft(re, im);
    const lr = new Float64Array(N), li = new Float64Array(N);
    for (let k = 0; k < N; k++) lr[k] = Math.log(Math.max(1e-12, re[k] * re[k] + im[k] * im[k])) / 2;
    fft(lr, li); // 実偶関数なので順変換で代用（1/N 倍）
    const c = new Float64Array(nc + 1);
    for (let q = 0; q <= nc; q++) c[q] = lr[q] / N;
    out.push({ t: (s + W / 2) / sr, e: 10 * Math.log10(e + 1e-20), c });
  }
  return out;
}

export function envDistance(a, b, sr) {
  const A = cepFrames(a, sr), B = cepFrames(b, sr), n = Math.min(A.length, B.length);
  const emax = Math.max(...A.map((f) => f.e));
  let s = 0, m = 0;
  for (let i = 0; i < n; i++) {
    if (A[i].e < emax - 40) continue;
    let d = 0;
    for (let q = 1; q < A[i].c.length; q++) d += (A[i].c[q] - B[i].c[q]) ** 2;
    s += (10 / Math.LN10) * Math.sqrt(2 * d); m++;
  }
  return m ? s / m : NaN;
}

export function formantDiff(a, b, sr) {
  const fa = analyzeMichi(a, sr).frames, fb = analyzeMichi(b, sr).frames;
  const mb = new Map(fb.filter((f) => f.F).map((f) => [Math.round(f.t * 100), f]));
  const d = [[], [], []];
  for (const f of fa) {
    if (!f.F) continue;
    const g = mb.get(Math.round(f.t * 100));
    if (!g) continue;
    for (let i = 0; i < 3; i++) d[i].push(Math.abs(f.F[i] - g.F[i]));
  }
  const med = (v) => { if (!v.length) return NaN; const s = [...v].sort((p, q) => p - q); return s[s.length >> 1]; };
  return { n: d[0].length, F1: med(d[0]), F2: med(d[1]), F3: med(d[2]) };
}

export function yomeru(ref, x, sr) {
  return { env_db: envDistance(ref, x, sr), formant: formantDiff(ref, x, sr) };
}
