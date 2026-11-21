/**
 * mimi.mjs — 変態耳（育てる耳）。kiku.mjs の「鏡写しのノミ」で取った 16 帯の断面を、kusanagi 自身が読んだ声で育てた
 * 小さな表（mimi_table.json）と突き合わせて書き取る。ニューラル網なし・学習済みの外の重みなし・外部ライブラリなし。
 *
 * 育て方（tools/mimi_sodate.mjs）:
 *   关亡婆の台本 → kusanagi が読む → 1 フレームごとに「いまどの音か」（kusanagi のモーラ時刻表がそのまま正解）
 *   → 音ごとに小さな混合ガウス（平均と分散の表、k-means と EM）を当てる → モーラの並びやすさ（2-gram）を数える。
 * 聴き方（decodeMimi）: フレームごとの当てはまり ＋ モーラの並びやすさで、いちばん筋の通るモーラ列を Viterbi で選ぶ（隠れマルコフ）。
 */
import { analyze } from "./kiku.mjs";

const EPS = 1e-9;
export const FEAT_BASE = 21;

/** kiku.analyze のフレーム → 特徴（21 次元 ＋ 前後差 21 次元）。発話ごとに帯の形の平均を引く（声の主の違いを薄める）。 */
export function features(samples, sr, feat = "v1") {
  // 16bit の格子に丸めてから聴く（wav を通しても通さんでも同じ特徴になる。無音が「ぴったり 0」になるのが肝）
  const q = new Float32Array(samples.length);
  for (let i = 0; i < q.length; i++) q[i] = Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767) / 32767;
  const fr = analyze(q, sr);
  const T = fr.length;
  if (!T) return { X: [], T: 0, frames: fr };
  let peak = 0;
  for (const f of fr) if (f.rms > peak) peak = f.rms;
  const vf0 = fr.filter((f) => f.vo > 0.45 && f.f0 >= 70 && f.f0 <= 600 && f.rms > peak * 0.1).map((f) => f.f0).sort((a, b) => a - b);
  const medF0 = vf0.length ? vf0[vf0.length >> 1] : 200;
  const B = fr.map((f) => {
    const lr = Math.log(f.rms + EPS);
    const bands = [...f.e1Vec, ...f.e2Vec, ...f.eHi].map((e) => Math.log(e + EPS) - lr);
    return [...bands, Math.log((f.rms + EPS) / (peak + EPS)), f.vo, Math.min(3, f.d1), Math.log(f.hiRatio + 1e-4), f.vo > 0.45 && f.f0 > 0 ? Math.log(f.f0 / medF0) : 0];
  });
  // 帯の形（0..15）の平均を、ある程度の音量のフレームで取って引く
  const mu = new Float64Array(16); let c = 0;
  for (let t = 0; t < T; t++) if (fr[t].rms > peak * 0.05) { for (let d = 0; d < 16; d++) mu[d] += B[t][d]; c++; }
  if (c) for (let d = 0; d < 16; d++) mu[d] /= c;
  for (let t = 0; t < T; t++) for (let d = 0; d < 16; d++) B[t][d] -= mu[d];
  const X = new Array(T);
  for (let t = 0; t < T; t++) {
    const a = B[Math.max(0, t - 2)], b = B[Math.min(T - 1, t + 2)];
    const v2 = feat === "v2";
    const v = new Float32Array(FEAT_BASE * 2 + (v2 ? 5 : 0));
    for (let d = 0; d < FEAT_BASE; d++) { v[d] = B[t][d]; v[FEAT_BASE + d] = (b[d] - a[d]) / 2; }
    if (v2) { // v2: 音量・有声度・d1・高域比・f0 の ±5 フレーム（約 50ms）の変わり方（音節の境目を見やすく）
      const a5 = B[Math.max(0, t - 5)], b5 = B[Math.min(T - 1, t + 5)];
      for (let d = 16; d < FEAT_BASE; d++) v[FEAT_BASE * 2 + d - 16] = (b5[d] - a5[d]) / 5;
    }
    X[t] = v;
  }
  return { X, T, frames: fr, medF0 };
}

/** モーラの時刻表（kusanagi の正解）→ フレームの状態名。frameT はフレームの真ん中の時刻（秒）。 */
export function frameLabels(moras, frameT, ctx = false) {
  const segs = [];
  for (const m of moras) {
    if (m.kind === "pau") segs.push([m.a, m.e, "sil"]);
    else if (m.kind === "Q") segs.push([m.a, m.b, "Q"]);
    else if (m.kind === "N") segs.push([m.a, m.e, "N"]);
    else { if (m.c && m.b > m.a) segs.push([m.a, m.b, "c:" + m.c + (ctx ? "+" + m.v : "")]); segs.push([m.b, m.e, "v:" + m.v]); }
  }
  let j = 0;
  return frameT.map((t) => { while (j < segs.length && segs[j][1] <= t) j++; return j < segs.length && segs[j][0] <= t ? segs[j][2] : "sil"; });
}

// ---- 混合ガウス（対角） ----
export function gmmLogLik(g, x) {
  let best = -Infinity; const ls = [];
  for (const k of g.k) {
    let s = k.c;
    for (let d = 0; d < x.length; d++) { const z = x[d] - k.m[d]; s -= 0.5 * z * z * k.ip[d]; }
    ls.push(s); if (s > best) best = s;
  }
  let acc = 0; for (const s of ls) acc += Math.exp(s - best);
  return best + Math.log(acc);
}

/** 書き取り: Viterbi（モーラ環・2-gram）。table は mimi_sodate が書いた表。 */
export function decodeMimi(samples, sr, table, opt = {}) {
  const { X, T } = features(samples, sr, table.feat || "v1");
  if (!T) return { text: "", moras: [] };
  const lmw = opt.lmw ?? table.dec.lmw, pen = opt.pen ?? table.dec.pen;
  const mean = table.norm.mean, sd = table.norm.sd;
  const st = Object.keys(table.gmm);
  const sIdx = Object.fromEntries(st.map((s, i) => [s, i]));
  // フレームごとの当てはまり（状態ごと）
  const E = new Array(T);
  for (let t = 0; t < T; t++) {
    const x = X[t], z = new Float64Array(x.length);
    for (let d = 0; d < x.length; d++) z[d] = (x[d] - mean[d]) / sd[d];
    E[t] = st.map((s) => gmmLogLik(table.gmm[s], z) * table.dec.ac);
  }
  // HMM: 単位（モーラ）= 状態の鎖。各状態は minDur 個の小部屋、最後の部屋だけ居残れる
  const units = table.units; // [{tok, kana, states:[name...]}]
  const U = units.length;
  const sub = []; // 小部屋 {u, si(状態番号), last(単位の最後の小部屋か), stay}
  const firstOf = new Int32Array(U), lastOf = new Int32Array(U);
  for (let u = 0; u < U; u++) {
    firstOf[u] = sub.length;
    units[u].states.forEach((s, k) => {
      const d = table.dur[s] || { min: 1, stay: 0.5 };
      for (let r = 0; r < d.min; r++) sub.push({ u, si: sIdx[s], lastState: k === units[u].states.length - 1, lastRoom: r === d.min - 1, stay: r === d.min - 1 ? Math.log(d.stay) : -Infinity, go: r === d.min - 1 ? Math.log(1 - d.stay) : 0 });
    });
    lastOf[u] = sub.length - 1;
  }
  const S = sub.length;
  // r3（关亡婆 teian_loop_001 の P3 / P2）: 単位に入るときの追加の罰。penQ/penN は余分な っ/ん を抑え、penR（負なら得）はら行の切れ目を拾いやすくする
  const penQ = opt.penQ ?? table.dec.penQ ?? 0, penN = opt.penN ?? table.dec.penN ?? 0, penR = opt.penR ?? table.dec.penR ?? 0;
  const upen = units.map((x) => (x.tok === "Q" ? penQ : x.tok === "N" ? penN : x.states[0] && x.states[0].startsWith("c:r") ? penR : 0));
  const lm = table.lm; // lm[from][to] 対数（from/to は単位番号、U は文頭）
  let dp = new Float64Array(S).fill(-Infinity);
  const bp = new Array(T); // 単位をまたいで入ったときの前の単位 (+1)、0 は中で進んだ
  const bpPrev = new Array(T);
  const silU = units.findIndex((x) => x.tok === "sil");
  // 始まりと終わりは無音（kusanagi は前後に無音を置く）。無音の単位が表に無ければどこからでも
  for (let u = 0; u < U; u++) if (silU < 0 || u === silU) dp[firstOf[u]] = E[0][sub[firstOf[u]].si];
  bp[0] = new Int32Array(S).fill(-1); bpPrev[0] = new Int32Array(S).fill(-1);
  for (let t = 1; t < T; t++) {
    const nd = new Float64Array(S).fill(-Infinity), b = new Int32Array(S).fill(-1), bpv = new Int32Array(S).fill(-1);
    // 単位の終わりからの出口
    const exitScore = new Float64Array(U);
    for (let u = 0; u < U; u++) { const s = lastOf[u]; exitScore[u] = dp[s] + sub[s].go; }
    for (let s = 0; s < S; s++) {
      const r = sub[s];
      // 居残り
      let best = dp[s] + r.stay, from = s, cross = -1;
      // 前の小部屋から（同じ単位の中）
      if (s !== firstOf[r.u]) { const p = sub[s - 1]; const v = dp[s - 1] + p.go; if (v > best) { best = v; from = s - 1; } }
      else {
        // 別の単位から入る
        const row = r.u;
        for (let u = 0; u < U; u++) { const v = exitScore[u] + lm[u][row] * lmw + pen + upen[row]; if (v > best) { best = v; from = lastOf[u]; cross = u; } }
      }
      nd[s] = best + E[t][r.si]; b[s] = from; bpv[s] = cross;
    }
    dp = nd; bp[t] = b; bpPrev[t] = bpv;
  }
  // 終わり: 単位の最後の小部屋のいちばん良い所
  let s = -1, best = -Infinity;
  for (let u = 0; u < U; u++) { if (silU >= 0 && u !== silU && opt.endSil !== false) continue; const v = dp[lastOf[u]]; if (v > best) { best = v; s = lastOf[u]; } }
  const seq = [], vlen = [];
  let lastLen = 0;
  for (let t = T - 1; t >= 0; t--) {
    const r = sub[s];
    if (r.lastState) lastLen++;
    if (t === 0 || bpPrev[t][s] >= 0) { seq.push(r.u); vlen.push(lastLen); lastLen = 0; }
    if (t > 0) s = bp[t][s];
  }
  seq.reverse(); vlen.reverse();
  const toks = seq.map((u) => units[u]);
  // 長さで母音を足す（r2）: 母音で終わる単位の母音が、1 モーラ分の平均長 vdur の thr 倍を超えたら同じ母音を足す
  //（kusanagi の「ほー」「ああ」は境目のない一続きの母音なので、HMM は 1 つにまとめがち）
  const nobi = opt.nobi ?? table.dec.nobi;
  const VK = { a: "あ", i: "い", u: "う", e: "え", o: "お" };
  const kanaOf = (x, k) => {
    const st = x.states[x.states.length - 1];
    if (!nobi || !table.vdur || !st.startsWith("v:")) return x.kana;
    const v = st.slice(2), m = table.vdur[v];
    // 句末（次が無音）の母音は kusanagi が句末で伸ばすので、閾値を nobiKu 倍にする
    const th = nobi * m * (toks[k + 1] && toks[k + 1].tok !== "sil" ? 1 : (opt.nobiKu ?? table.dec.nobiKu ?? 1));
    if (!m || vlen[k] < th) return x.kana;
    const extra = Math.min(2, 1 + Math.floor((vlen[k] - th) / m));
    return x.kana + VK[v].repeat(extra);
  };
  const text = toks.map((x, k) => kanaOf(x, k)).join("").replace(/、+/g, "、").replace(/^、|、$/g, "");
  return { text, units: toks.map((x) => x.tok) };
}
