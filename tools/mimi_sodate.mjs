#!/usr/bin/env node
/**
 * tools/mimi_sodate.mjs — 変態耳を育てる。关亡婆の台本（調整用 tune だけ）を kusanagi に読ませ、フレームごとの正解
 * （kusanagi のモーラ時刻表）で、音ごとの混合ガウスとモーラ 2-gram を数えて mimi_table.json に書く。外部ライブラリ 0。
 *
 *   node tools/mimi_sodate.mjs [--corpus tools/kiku_corpus_itako.json] [--wavdir DIR] [--presets ...] [--seeds 2024,7,99]
 *                              [--K 16] [--max 12000] [--workers 6] [--out mimi_table.json] [--nodev] [--noctx] [--minf 0.6] [--lmw 10] [--pen -10] [--nobi 1.7] [--nobiKu 1.5] [--feat v1|v2]
 * 確認用 (test) の台本は一切読まん。--nodev で調整用の「下見」台本も外して育て、lmw/pen を下見で選ぶ。
 */
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";
import { fileURLToPath } from "node:url";

/** 調整用の中の「下見」台本（育て方の加減を選ぶとき用）: id の md5 先頭 2 桁が 64..99 */
export const isDev = (id) => { const b = parseInt(crypto.createHash("md5").update(id).digest("hex").slice(0, 2), 16); return b >= 64 && b < 100; };
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const hira = (s) => [...s].map((c) => (c >= "ァ" && c <= "ヶ" ? String.fromCharCode(c.charCodeAt(0) - 0x60) : c)).join("");

/** makeHitofude と同じ手順で、モーラの時刻表だけを作る（音は作らん） */
export function moraTimes(H, text, prm) {
  const { rate = 1.26, sigh = 0.0, pre = 0.6, post = 0.1, vd_ms = null, uta_hz = null } = prm;
  let targetText = text, phraseCuts = null;
  if (/['’0/| 　?？]/.test(text) && !uta_hz) { const [clean, phrases] = H.annotate(text); targetText = clean; phraseCuts = phrases.slice(1).map((p) => p[0]); }
  const p = { rate, fend_at: sigh > 0.0 ? 0.45 : 0.16, phraseCuts };
  if (vd_ms) p.vd_ms = vd_ms;
  return H.tracksFromKana(targetText, pre, post, p).moras;
}
export function unitOf(m, ctx = false) {
  if (m.kind === "pau") return { key: "sil", kana: "、", states: ["sil"] };
  if (m.kind === "Q") return { key: "Q", kana: "っ", states: ["Q"] };
  if (m.kind === "N") return { key: "N", kana: "ん", states: ["N"] };
  return { key: `${m.c}|${m.v}`, kana: hira(m.t), states: m.c ? ["c:" + m.c + (ctx ? "+" + m.v : ""), "v:" + m.v] : ["v:" + m.v] };
}

async function worker() {
  const H = await import(path.join(ROOT, "hitofude.mjs"));
  const K = await import(path.join(ROOT, "kiku.mjs"));
  const M = await import(path.join(ROOT, "mimi.mjs"));
  parentPort.on("message", (job) => {
    if (job === null) process.exit(0);
    const prm = { ...H.PRESETS[job.preset], seed: job.seed };
    let samples, sr = H.SR;
    if (job.wav && fs.existsSync(job.wav)) ({ samples, sr } = K.decodeWavBytes(fs.readFileSync(job.wav)));
    else {
      const s = H.makeHitofude(job.kana, prm).samples;
      if (job.wav) { fs.mkdirSync(path.dirname(job.wav), { recursive: true }); fs.writeFileSync(job.wav + ".tmp", H.encodeWav(s)); fs.renameSync(job.wav + ".tmp", job.wav); ({ samples, sr } = K.decodeWavBytes(fs.readFileSync(job.wav))); }
      else samples = s;
    }
    const f = M.features(samples, sr, job.feat);
    const winS = Math.round(22050 * 0.025) / 22050 / 2;
    const lab = M.frameLabels(moraTimes(H, job.kana, prm), f.frames.map((x) => x.t + winS), job.ctx);
    const mt = moraTimes(H, job.kana, prm);
    const units = mt.map((m) => unitOf(m, job.ctx));
    // モーラ 1 つぶんの母音の長さ（フレーム）。続く同じ母音とまとめずに数える（長さで母音を足すとき用）
    const hop = Math.round(22050 * 0.01) / 22050;
    const vd = mt.filter((m) => m.kind === "CV").map((m) => [m.v, (m.e - m.b) / hop]);
    const dim = f.X[0].length, flat = new Float32Array(f.T * dim);
    f.X.forEach((v, t) => flat.set(v, t * v.length));
    parentPort.postMessage({ id: job.id, flat, dim, lab, units, vd }, [flat.buffer]);
  });
}

function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }

function fitGmm(rows, K, r) {
  const n = rows.length, D = rows[0].length;
  K = Math.max(1, Math.min(K, Math.floor(n / 40)));
  // k-means++
  const C = [rows[Math.floor(r() * n)].slice()];
  const d2 = new Float64Array(n).fill(Infinity);
  while (C.length < K) {
    let tot = 0;
    for (let i = 0; i < n; i++) { let s = 0; const c = C[C.length - 1]; for (let d = 0; d < D; d++) { const z = rows[i][d] - c[d]; s += z * z; } if (s < d2[i]) d2[i] = s; tot += d2[i]; }
    let u = r() * tot, i = 0; while (i < n - 1 && (u -= d2[i]) > 0) i++;
    C.push(rows[i].slice());
  }
  let comp = C.map((m) => ({ w: 1 / K, m: Float64Array.from(m), v: new Float64Array(D).fill(1) }));
  const resp = new Float64Array(n * K);
  for (let it = 0; it < 12; it++) {
    // E
    for (let i = 0; i < n; i++) {
      let best = -Infinity; const ls = new Float64Array(K);
      for (let k = 0; k < K; k++) { const c = comp[k]; let s = Math.log(c.w); for (let d = 0; d < D; d++) { const z = rows[i][d] - c.m[d]; s -= 0.5 * (z * z / c.v[d] + Math.log(c.v[d])); } ls[k] = s; if (s > best) best = s; }
      let acc = 0; for (let k = 0; k < K; k++) { ls[k] = Math.exp(ls[k] - best); acc += ls[k]; }
      for (let k = 0; k < K; k++) resp[i * K + k] = ls[k] / acc;
    }
    // M
    comp = comp.map((c, k) => {
      let w = 0; const m = new Float64Array(D), v = new Float64Array(D);
      for (let i = 0; i < n; i++) { const g = resp[i * K + k]; w += g; for (let d = 0; d < D; d++) m[d] += g * rows[i][d]; }
      if (w < 1e-6) return c;
      for (let d = 0; d < D; d++) m[d] /= w;
      for (let i = 0; i < n; i++) { const g = resp[i * K + k]; for (let d = 0; d < D; d++) { const z = rows[i][d] - m[d]; v[d] += g * z * z; } }
      for (let d = 0; d < D; d++) v[d] = Math.max(0.01, v[d] / w);
      return { w: w / n, m, v };
    });
  }
  const r4 = (x) => Math.round(x * 1e4) / 1e4;
  return { k: comp.map((c) => { let lc = Math.log(c.w) - 0.5 * D * Math.log(2 * Math.PI); for (let d = 0; d < D; d++) lc -= 0.5 * Math.log(c.v[d]); return { c: r4(lc), m: Array.from(c.m, r4), ip: Array.from(c.v, (x) => r4(1 / x)) }; }), n };
}

async function main() {
  const A = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => (a.startsWith("--") ? [...acc, [a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : "1"]] : acc), []));
  const corpus = JSON.parse(fs.readFileSync(A.corpus || path.join(HERE, "kiku_corpus_itako.json"), "utf8"));
  const presets = (A.presets || "hitofude,toiki,alto,sasayaki,chibi,ossan").split(",");
  const seeds = (A.seeds || "2024,7,99").split(",").map(Number);
  const K = Number(A.K || 16), MAX = Number(A.max || 12000), nW = Number(A.workers || Math.max(1, Math.min(6, os.cpus().length - 1)));
  const jobs = [];
  for (const sc of corpus.scripts) if (sc.split === "tune" && !(A.nodev && isDev(sc.id))) sc.lines.forEach((ln, li) => { for (const preset of presets) for (const seed of seeds) jobs.push({ id: jobs.length, kana: ln.kana, preset, seed, ctx: !A.noctx, feat: A.feat || "v1", wav: A.wavdir ? path.join(A.wavdir, `${sc.id}_L${String(li + 1).padStart(2, "0")}_${preset}_s${seed}.wav`) : null }); });
  const r = rng(20261120);
  const vds = {};
  const pool = {}, seen = {}, runs = {}, unitsSeen = {}, big = {};
  let D = 0, done = 0;
  const t0 = Date.now();
  await new Promise((resolve) => {
    let next = 0, want = 0;
    const held = new Map();
    const ws = Array.from({ length: Math.min(nW, jobs.length) }, () => new Worker(fileURLToPath(import.meta.url), { workerData: { worker: true, sodate: true } }));
    for (const w of ws) {
      w.on("message", (msg) => {
        // 届いた順ではなく job 番号順に数える（何コアで回しても同じ表になる）
        held.set(msg.id, msg);
        while (held.has(want)) { take(held.get(want)); held.delete(want); want++; }
        done++; if (done % 300 === 0) process.stderr.write(`${done}/${jobs.length} `);
        if (next < jobs.length) w.postMessage(jobs[next++]); else w.postMessage(null);
        if (done === jobs.length) resolve();
      });
      w.on("error", (e) => { console.error(e); process.exit(1); });
      w.postMessage(jobs[next++]);
    }
    function take(m) {
        D = m.dim;
        for (let t = 0; t < m.lab.length; t++) {
          const s = m.lab[t]; seen[s] = (seen[s] || 0) + 1; (pool[s] ||= []);
          const row = m.flat.subarray(t * D, (t + 1) * D);
          if (pool[s].length < MAX) pool[s].push(Float64Array.from(row)); else { const j = Math.floor(r() * seen[s]); if (j < MAX) pool[s][j] = Float64Array.from(row); }
        }
        for (const [v, f] of m.vd) { const q = (vds[v] ||= [0, 0]); q[0] += f; q[1]++; }
        for (let t = 0, a = 0; t <= m.lab.length; t++) if (t === m.lab.length || m.lab[t] !== m.lab[a]) { (runs[m.lab[a]] ||= []).push(t - a); a = t; }
        const seq = [{ key: "sil", kana: "、", states: ["sil"] }, ...m.units, { key: "sil", kana: "、", states: ["sil"] }];
        for (let i = 0; i < seq.length; i++) {
          const u = seq[i]; const us = (unitsSeen[u.key] ||= { n: 0, kana: {}, states: u.states }); us.n++; us.kana[u.kana] = (us.kana[u.kana] || 0) + 1;
          if (i > 0) { const k = seq[i - 1].key + ">" + u.key; big[k] = (big[k] || 0) + 1; }
        }
    }
  });
  console.error(`\n特徴 ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  // 全体の平均・ばらつき（標準化）
  const all = Object.values(pool).flat();
  const mean = new Float64Array(D), sd = new Float64Array(D);
  for (const x of all) for (let d = 0; d < D; d++) mean[d] += x[d] / all.length;
  for (const x of all) for (let d = 0; d < D; d++) sd[d] += (x[d] - mean[d]) ** 2 / all.length;
  for (let d = 0; d < D; d++) sd[d] = Math.sqrt(sd[d]) || 1;
  const gmm = {};
  for (const [s, rows] of Object.entries(pool)) {
    if (rows.length < 20) continue;
    const z = rows.map((x) => Float64Array.from(x, (v, d) => (v - mean[d]) / sd[d]));
    gmm[s] = fitGmm(z, K, r);
  }
  const dur = {};
  for (const [s, rs] of Object.entries(runs)) {
    const md = rs.reduce((a, b) => a + b, 0) / rs.length;
    const min = Math.max(1, Math.min(8, Math.floor(md * Number(A.minf || 0.6))));
    dur[s] = { mean: +md.toFixed(2), min, stay: +Math.min(0.97, Math.max(0.05, 1 - 1 / Math.max(1.05, md - min + 1))).toFixed(4) };
  }
  const units = Object.entries(unitsSeen).filter(([k, u]) => u.n >= 3 && u.states.every((s) => gmm[s])).map(([key, u]) => ({ tok: key, kana: Object.entries(u.kana).sort((a, b) => b[1] - a[1])[0][0], states: u.states, n: u.n })).sort((a, b) => b.n - a.n);
  const U = units.length, ix = Object.fromEntries(units.map((u, i) => [u.tok, i]));
  const lm = [];
  const cnt = Array.from({ length: U + 1 }, () => new Float64Array(U));
  for (const [k, n] of Object.entries(big)) { const [a, b] = k.split(">"); if (ix[b] === undefined) continue; if (ix[a] !== undefined) cnt[ix[a]][ix[b]] += n; if (a === "sil") cnt[U][ix[b]] += n; }
  for (let a = 0; a <= U; a++) { const tot = cnt[a].reduce((x, y) => x + y, 0) + 0.5 * U; lm.push(Array.from(cnt[a], (c) => Math.round(Math.log((c + 0.5) / tot) * 100) / 100)); }
  const table = { kind: "mimi-table v1", from: { corpus: corpus.source, split: A.nodev ? "tune-dev" : "tune", presets, seeds, utterances: jobs.length, engine: "hitofude@" + crypto.createHash("sha256").update(fs.readFileSync(path.join(ROOT, "hitofude.mjs"))).digest("hex").slice(0, 12) }, K, feat: A.feat || "v1", ctx: !A.noctx, minf: Number(A.minf || 0.6), max: MAX, norm: { mean: Array.from(mean, (x) => +x.toFixed(4)), sd: Array.from(sd, (x) => +x.toFixed(4)) }, dur, vdur: Object.fromEntries(Object.entries(vds).map(([v, q]) => [v, +(q[0] / q[1]).toFixed(2)])), gmm, units: units.map(({ n, ...u }) => u), lm, dec: { ac: 1.0, lmw: Number(A.lmw || 10), pen: Number(A.pen || -10), nobi: Number(A.nobi ?? 1.7), nobiKu: Number(A.nobiKu ?? 1.5) } };
  const out = A.out || path.join(ROOT, "mimi_table.json");
  fs.writeFileSync(out, JSON.stringify(table));
  console.error(`表: ${out} 状態 ${Object.keys(gmm).length} 単位 ${U} ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
}

if (!isMainThread && workerData?.sodate) worker();
else if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
