// 关亡婆の実データ集め：kusanagi(engine/hitofude.mjs) で台本の行を読ませ、16 kHz wav ＋ かなラベルを data/ に貯める。
//   node atsume.mjs --n 300 --workers 2 [--new daihon/x.json ...]
//   台本の出どころ: r5 コーパス（元 34 本＋ループ）＋ loop/daihon/round_*.json ＋ atsume/daihon/*.json。新しい台本は全行×全プリセットを先に。
//   split は台本 id の md5 で kiku と同じ（先頭 2 桁 < 64 = test）。ラベル = spokenKana（声が実際に読むかな）。
import fs from "fs"; import path from "path"; import crypto from "crypto"; import os from "os";
import { Worker, isMainThread, parentPort, workerData } from "worker_threads";
import { fileURLToPath } from "url";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENG = path.join(HERE, "engine");
const OUT_SR = 16000;
function resample(x, sr) {   // 窓付き sinc（Blackman, 片側 24 タップ）で sr → 16 kHz、カットオフ 7.6 kHz
  const r = sr / OUT_SR, fc = 7600 / sr, W = 24, n = Math.floor(x.length / r), y = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const c = i * r, c0 = Math.floor(c); let s = 0, ws = 0;
    for (let k = c0 - W + 1; k <= c0 + W; k++) {
      if (k < 0 || k >= x.length) continue;
      const t = k - c, a = (t / W + 1) / 2;
      const win = a <= 0 || a >= 1 ? 0 : 0.42 - 0.5 * Math.cos(2 * Math.PI * a) + 0.08 * Math.cos(4 * Math.PI * a);
      const h = 2 * fc * (t === 0 ? 1 : Math.sin(2 * Math.PI * fc * t) / (2 * Math.PI * fc * t)) * win;
      s += x[k] * h; ws += h;
    }
    y[i] = ws ? s / ws : 0;
  }
  return y;
}
function wav16(y) {
  const b = Buffer.alloc(44 + y.length * 2);
  b.write("RIFF", 0); b.writeUInt32LE(36 + y.length * 2, 4); b.write("WAVEfmt ", 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(OUT_SR, 24); b.writeUInt32LE(OUT_SR * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write("data", 36); b.writeUInt32LE(y.length * 2, 40);
  for (let i = 0; i < y.length; i++) b.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(y[i] * 32767))), 44 + 2 * i);
  return b;
}
if (!isMainThread) {
  const H = await import(path.join(ENG, "hitofude.mjs"));
  const KE = await import(path.join(ENG, "tools", "kiku_eval.mjs"));
  parentPort.on("message", (j) => {
    if (j === null) process.exit(0);
    const prm = { ...H.PRESETS[j.preset], seed: j.seed };
    const s = H.makeHitofude(j.kana, prm).samples;
    const y = resample(s, H.SR);
    fs.mkdirSync(path.dirname(j.abs), { recursive: true });
    fs.writeFileSync(j.abs + ".tmp", wav16(y)); fs.renameSync(j.abs + ".tmp", j.abs);
    parentPort.postMessage({ ...j, spoken: KE.spokenKana(H, j.kana, prm), dur: +(y.length / OUT_SR).toFixed(2) });
  });
} else {
  const A = {}; const av = process.argv.slice(2); const NEW = [];
  for (let i = 0; i < av.length; i++) { if (av[i] === "--new") NEW.push(av[++i]); else if (av[i].startsWith("--")) A[av[i].slice(2)] = av[++i]; }
  const N = +(A.n || 300), WORKERS = +(A.workers || 2);
  const TTS = fs.readFileSync(path.join(HERE, "tts_commit.txt"), "utf8").trim();
  const H = await import(path.join(ENG, "hitofude.mjs"));
  const PRESETS = Object.keys(H.PRESETS);
  const split = (id) => (parseInt(crypto.createHash("md5").update(id).digest("hex").slice(0, 2), 16) < 64 ? "test" : "tune");
  const scripts = new Map();
  const add = (sc, src) => { if (sc && sc.id && !scripts.has(sc.id)) scripts.set(sc.id, { id: sc.id, src, lines: sc.lines.filter((l) => l.kana) }); };
  const M = path.join(os.homedir(), "itako_mimi");
  try { for (const sc of JSON.parse(fs.readFileSync(path.join(M, "r5", "corpus_r5.json"), "utf8")).scripts) add(sc, sc.src || "base"); } catch {}
  for (const d of [[path.join(M, "loop", "daihon"), "obake_loop"], [path.join(HERE, "daihon"), "atsume"]])
    for (const f of fs.existsSync(d[0]) ? fs.readdirSync(d[0]).filter((f) => f.endsWith(".json")) : []) { try { for (const sc of JSON.parse(fs.readFileSync(path.join(d[0], f), "utf8")).scripts) add(sc, d[1]); } catch {} }
  const jobs = []; const rnd = () => crypto.randomInt(1, 1 << 30);
  const mk = (sc, li, preset) => { const seed = rnd(), id = `${sc.id}_L${String(li + 1).padStart(2, "0")}_${preset}_s${seed}`; return { id, sid: sc.id, li, preset, seed, kana: sc.lines[li].kana, text: sc.lines[li].text, src: sc.src, rel: `data/${TTS}/${sc.id}/${id}.wav` }; };
  for (const f of NEW) for (const sc of JSON.parse(fs.readFileSync(f, "utf8")).scripts) { add(sc, "atsume"); const s = scripts.get(sc.id); s.lines.forEach((_, li) => PRESETS.forEach((p) => jobs.push(mk(s, li, p)))); }
  const all = [...scripts.values()].filter((s) => s.lines.length);
  while (jobs.length < N) { const s = all[crypto.randomInt(all.length)]; jobs.push(mk(s, crypto.randomInt(s.lines.length), PRESETS[crypto.randomInt(PRESETS.length)])); }
  const ledger = fs.openSync(path.join(HERE, "ledger.jsonl"), "a"); const t0 = Date.now(); let done = 0, sec = 0;
  await new Promise((res) => {
    let next = 0, live = 0;
    for (let w = 0; w < WORKERS; w++) {
      const W = new Worker(fileURLToPath(import.meta.url)); live++;
      const feed = () => { if (next < jobs.length) { const j = jobs[next++]; W.postMessage({ ...j, abs: path.join(HERE, j.rel) }); } else W.postMessage(null); };
      W.on("message", (r) => { delete r.abs; fs.writeSync(ledger, JSON.stringify({ ...r, split: split(r.sid), sr: OUT_SR, tts_commit: TTS, at: new Date().toISOString() }) + "\n"); done++; sec += r.dur; feed(); });
      W.on("exit", () => { if (--live === 0) res(); }); feed();
    }
  });
  console.log(JSON.stringify({ clips: done, audio_sec: Math.round(sec), wall_sec: Math.round((Date.now() - t0) / 1000), scripts: all.length, new: NEW.length }));
}
