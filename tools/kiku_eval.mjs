#!/usr/bin/env node
/**
 * tools/kiku_eval.mjs — 変態耳（kiku）の書き取り成績を、关亡婆の台本を kusanagi に読ませて測る。外部ライブラリ 0（node 標準の worker_threads だけ）。
 *
 *   node tools/kiku_eval.mjs [--corpus tools/kiku_corpus_itako.json] [--split tune|test|all|dev] [--presets hitofude,toiki,alto,sasayaki,chibi,ossan]
 *                            [--seeds 2024,7,99] [--ear hand|mimi] [--table mimi_table.json] [--lmw X] [--pen Y] [--workers 6] [--wavdir DIR] [--ledger FILE] [--label NAME] [--out res.json] [--lines N]
 *
 * - 正解 = 台本の文を janome で下ごしらえしたカタカナ（tools/kiku_corpus_itako.json）。kusanagi がそれを読み、kiku が書き取る。
 * - 台本ごとに split（tune=調整用 / test=確認用、id の md5 で決まるので、新しい台本を足しても前の割り振りは変わらん）。
 * - 点: かな正答 = 1 − かな CER（「、」「?」を除く）、母音正答 = 1 − 母音列の編集距離 / 母音数。
 * - 取り違えの表: モーラ単位で並べ直して、子音の取り違え・母音の取り違え・抜け・余分を数える。
 * - --wavdir を渡すと wav を置く（同じ名前があれば読み直すだけ）。--ledger を渡すと、1発話 1行でオバケ台帳 (jsonl) に足す。
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

// ---- かなの道具 ----
const hira = (s) => [...s].map((c) => (c >= "ァ" && c <= "ヶ" ? String.fromCharCode(c.charCodeAt(0) - 0x60) : c)).join("");
const ROWS = "あいうえお かきくけこ がぎぐげご さしすせそ ざじずぜぞ たちつてと だぢづでど なにぬねの はひふへほ ばびぶべぼ ぱぴぷぺぽ まみむめも やいゆえよ らりるれろ わいうえを".split(" ");
const CONS = ["", "k", "g", "s", "z", "t", "d", "n", "h", "b", "p", "m", "y", "r", "w"];
const MORA = {};
ROWS.forEach((r, ri) => [...r].forEach((c, vi) => { if (!(c in MORA)) MORA[c] = [CONS[ri], "aiueo"[vi]]; }));
Object.assign(MORA, { "し": ["sh", "i"], "ち": ["ch", "i"], "つ": ["ts", "u"], "ふ": ["f", "u"], "じ": ["j", "i"], "ぢ": ["j", "i"], "づ": ["z", "u"], "を": ["", "o"], "ゔ": ["v", "u"] });
const SMALL = { "ゃ": "a", "ゅ": "u", "ょ": "o", "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o" };
/** ひらがな → モーラ列 [{c, v}]（ん=N、っ=Q、ー=前の母音） */
export function moras(s) {
  const out = [];
  for (const ch of s) {
    if (ch in SMALL && out.length) { const m = out[out.length - 1]; if (m.c === "k" || m.c === "g" || m.c === "n" || m.c === "h" || m.c === "b" || m.c === "p" || m.c === "m" || m.c === "r") m.c += "y"; else if (m.c === "" && SMALL[ch]) { m.c = m.v === "i" ? "y" : m.v === "u" ? "w" : m.c; } m.v = SMALL[ch]; continue; }
    if (ch === "ん") out.push({ c: "N", v: "" });
    else if (ch === "っ") out.push({ c: "Q", v: "" });
    else if (ch === "ー" && out.length) out.push({ c: "", v: out[out.length - 1].v || "a" });
    else if (ch in MORA) out.push({ c: MORA[ch][0], v: MORA[ch][1] });
  }
  return out;
}
/** 正解のカタカナ → kiku と比べるひらがな（「、」「?」を外し、ー は前の母音の字に） */
export function truthOf(kana) {
  let s = hira(kana.replace(/[、?？]/g, ""));
  const V = { a: "あ", i: "い", u: "う", e: "え", o: "お" };
  let r = "";
  for (const ch of s) { if (ch === "ー") { const m = moras(r); r += m.length ? V[m[m.length - 1].v] || "" : ""; } else r += ch; }
  return r;
}
export const vowels = (s) => moras(s).map((m) => m.v || m.c).join("");
export function ed(a, b) {
  a = [...a]; b = [...b];
  let d = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) { let p = d[0]; d[0] = i; for (let j = 1; j <= b.length; j++) { const t = d[j]; d[j] = Math.min(d[j] + 1, d[j - 1] + 1, p + (a[i - 1] !== b[j - 1] ? 1 : 0)); p = t; } }
  return d[b.length];
}
/** モーラ列どうしを並べる（置換は子音・母音の食い違いごとに 0.5） → 対応のリスト */
export function alignMoras(h, t) {
  const n = h.length, m = t.length, D = [];
  for (let i = 0; i <= n; i++) { D.push(new Float64Array(m + 1)); D[i][0] = i; }
  for (let j = 0; j <= m; j++) D[0][j] = j;
  const sub = (x, y) => (x.c !== y.c ? 0.5 : 0) + (x.v !== y.v ? 0.5 : 0);
  for (let i = 1; i <= n; i++) for (let j = 1; j <= m; j++) D[i][j] = Math.min(D[i - 1][j] + 1, D[i][j - 1] + 1, D[i - 1][j - 1] + sub(h[i - 1], t[j - 1]));
  const pairs = [];
  let i = n, j = m;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && D[i][j] === D[i - 1][j - 1] + sub(h[i - 1], t[j - 1])) { pairs.push([h[i - 1], t[j - 1]]); i--; j--; }
    else if (j > 0 && (i === 0 || D[i][j] === D[i][j - 1] + 1)) { pairs.push([null, t[j - 1]]); j--; }
    else { pairs.push([h[i - 1], null]); i--; }
  }
  return pairs.reverse();
}

// ---- 1発話の処理（worker） ----
async function workerMain() {
  const H = await import(path.join(ROOT, "hitofude.mjs"));
  const K = await import(path.join(ROOT, "kiku.mjs"));
  const ear = workerData.ear || "hand";
  let Mi = null, table = null;
  if (ear === "mimi") { Mi = await import(path.join(ROOT, "mimi.mjs")); table = JSON.parse(fs.readFileSync(workerData.table, "utf8")); }
  parentPort.on("message", (job) => {
    if (job === null) { process.exit(0); }
    const prm = { ...H.PRESETS[job.preset], seed: job.seed };
    let samples, sr = H.SR;
    const wp = job.wav;
    if (wp && fs.existsSync(wp)) { const w = K.decodeWavBytes(fs.readFileSync(wp)); samples = w.samples; sr = w.sr; }
    else {
      const s = H.makeHitofude(job.kana, prm).samples;
      if (wp) { fs.mkdirSync(path.dirname(wp), { recursive: true }); fs.writeFileSync(wp + ".tmp", H.encodeWav(s)); fs.renameSync(wp + ".tmp", wp); const w = K.decodeWavBytes(fs.readFileSync(wp)); samples = w.samples; sr = w.sr; }
      else samples = s;
    }
    const hyp = (ear === "mimi" ? Mi.decodeMimi(samples, sr, table, workerData.dec || {}) : K.decode(K.analyze(samples, sr))).text.replace(/、/g, "");
    parentPort.postMessage({ ...job, hyp, params: prm });
  });
}

function short(file) { return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex").slice(0, 12); }

async function main() {
  const A = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => (a.startsWith("--") ? [...acc, [a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : "1"]] : acc), []));
  const corpus = JSON.parse(fs.readFileSync(A.corpus || path.join(HERE, "kiku_corpus_itako.json"), "utf8"));
  const split = A.split || "all";
  const presets = (A.presets || "hitofude,toiki,alto,sasayaki,chibi,ossan").split(",");
  const seeds = (A.seeds || "2024,7,99").split(",").map(Number);
  const nWork = Number(A.workers || Math.max(1, Math.min(6, os.cpus().length - 1)));
  const maxLines = A.lines ? Number(A.lines) : Infinity;
  const ear = A.ear || "hand";
  const table = ear === "mimi" ? path.resolve(A.table || path.join(ROOT, "mimi_table.json")) : null;
  const dec = {}; if (A.lmw) dec.lmw = Number(A.lmw); if (A.pen) dec.pen = Number(A.pen);
  const engine = { kusanagi: A.kusanagi || "hitofude@" + short(path.join(ROOT, "hitofude.mjs")), kiku: A.kiku || "kiku@" + short(path.join(ROOT, "kiku.mjs")), mimi: ear === "mimi" ? (A.mimi || "mimi@" + short(path.join(ROOT, "mimi.mjs")) + "+table@" + short(table)) : "" };
  const label = A.label || engine.kiku;
  const jobs = [];
  for (const sc of corpus.scripts) {
    if (split === "dev" ? !(sc.split === "tune" && isDev(sc.id)) : split !== "all" && sc.split !== split) continue;
    sc.lines.slice(0, maxLines).forEach((ln, li) => {
      for (const preset of presets) for (const seed of seeds) {
        const wav = A.wavdir ? path.join(A.wavdir, `${sc.id}_L${String(li + 1).padStart(2, "0")}_${preset}_s${seed}.wav`) : null;
        jobs.push({ sid: sc.id, li: li + 1, split: sc.split, text: ln.text, kana: ln.kana, truth: truthOf(ln.kana), preset, seed, wav });
      }
    });
  }
  const t0 = Date.now(), res = [];
  await new Promise((resolve) => {
    let next = 0, done = 0;
    const ws = Array.from({ length: Math.min(nWork, jobs.length) }, () => new Worker(fileURLToPath(import.meta.url), { workerData: { worker: true, ear, table, dec } }));
    for (const w of ws) {
      w.on("message", (r) => { res.push(r); done++; if (done % 200 === 0) process.stderr.write(`${done}/${jobs.length} `); if (next < jobs.length) w.postMessage(jobs[next++]); else w.postMessage(null); if (done === jobs.length) resolve(); });
      w.on("error", (e) => { console.error(e); process.exit(1); });
      if (next < jobs.length) w.postMessage(jobs[next++]);
    }
  });
  // ---- 点と取り違え ----
  const agg = {}, conf = { cons: {}, vow: {}, del: {}, ins: {} };
  const bump = (o, k) => (o[k] = (o[k] || 0) + 1);
  for (const r of res) {
    r.ced = ed(r.hyp, r.truth); r.n = [...r.truth].length; r.cer = r.ced / Math.max(1, r.n);
    r.ved = ed(vowels(r.hyp), vowels(r.truth)); r.vn = vowels(r.truth).length;
    for (const key of [`${r.split}|${r.preset}`, `${r.split}|全体`]) { const a = (agg[key] ||= [0, 0, 0, 0, 0]); a[0] += r.ced; a[1] += r.n; a[2] += r.ved; a[3] += r.vn; a[4]++; }
    if (r.split === "tune" || split !== "all") for (const [h, t] of alignMoras(moras(r.hyp), moras(r.truth))) {
      if (!h) bump(conf.del, t.c + t.v); else if (!t) bump(conf.ins, h.c + h.v);
      else { if (h.c !== t.c) bump(conf.cons, `${t.c || "∅"}→${h.c || "∅"}`); if (h.v !== t.v) bump(conf.vow, `${t.v || "∅"}→${h.v || "∅"}`); }
    }
  }
  const pct = (a) => ({ kana: +(100 - (100 * a[0]) / a[1]).toFixed(1), vowel: +(100 - (100 * a[2]) / a[3]).toFixed(1), n: a[4] });
  const score = Object.fromEntries(Object.entries(agg).sort().map(([k, a]) => [k, pct(a)]));
  const top = (o, n = 15) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
  const report = { label, ear, dec, engine, split, presets, seeds, n: res.length, sec: Math.round((Date.now() - t0) / 1000), score, confusions: { cons: top(conf.cons), vow: top(conf.vow), del: top(conf.del), ins: top(conf.ins) } };
  console.log(JSON.stringify({ ...report, confusions: undefined }, null, 1));
  console.log("子音の取り違え(正→聞):", top(conf.cons, 12).map(([k, v]) => `${k} ${v}`).join(" / "));
  console.log("母音の取り違え(正→聞):", top(conf.vow, 10).map(([k, v]) => `${k} ${v}`).join(" / "));
  console.log("抜け:", top(conf.del, 10).map(([k, v]) => `${k} ${v}`).join(" / "), " | 余分:", top(conf.ins, 10).map(([k, v]) => `${k} ${v}`).join(" / "));
  if (A.out) fs.writeFileSync(A.out, JSON.stringify({ ...report, rows: res.map(({ params, ...r }) => r) }, null, 0));
  if (A.ledger) {   // オバケ台帳（ウンエイ設計 v1 の列 A〜L ＋ 耳の記録）
    const now = new Date(Date.now() + 9 * 3600e3).toISOString().replace("T", " ").slice(0, 19);
    const run = `${label}@${now}`;
    const order = {};
    const lines = res.sort((a, b) => (a.sid + a.li + a.preset + a.seed).localeCompare(b.sid + b.li + b.preset + b.seed)).map((r) => JSON.stringify({
      A_jikoku: now, B_corner: "変態耳の評価（放送外）", C_junban: (order[r.sid] = (order[r.sid] || 0) + 1), D_shurui: r.split === "test" ? "確認用" : "調整用",
      E_serifu: r.text, F_wav: r.wav ? path.basename(r.wav) : "", G_params: JSON.stringify(r.params), H_commit: engine, I_kana_cer: +r.cer.toFixed(4),
      J_P_hyouka: "", K_hyouka_jikoku: "", L_honban_ok: "",
      run, mimi_or_te: ear, daihon_id: r.sid, gyou: r.li, preset: r.preset, seed: r.seed, yomi: r.kana, seikai: r.truth, kiku: r.hyp, boin_er: +(r.ved / Math.max(1, r.vn)).toFixed(4), wav_path: r.wav || "",
    }));
    fs.mkdirSync(path.dirname(A.ledger), { recursive: true });
    fs.appendFileSync(A.ledger, lines.join("\n") + "\n");
    console.error(`台帳に ${lines.length} 行: ${A.ledger}`);
  }
}

if (!isMainThread && workerData?.worker) workerMain();
else if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main();
