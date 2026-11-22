// xray/cat10_visual.mjs — 変態解析ツール #91〜#100: ビジュアルX線レンダラー (Pure JS SVG/HTML X-Ray Panels)
import { median } from "./core.mjs";

function infernoHex(u) {
  const pts = [
    [0.0, [5, 4, 22]], [0.22, [65, 16, 118]], [0.45, [147, 43, 128]],
    [0.68, [226, 78, 102]], [0.85, [254, 164, 112]], [1.0, [252, 253, 191]],
  ];
  const v = Math.max(0.0, Math.min(1.0, u));
  for (let i = 0; i < pts.length - 1; i++) {
    const [u0, c0] = pts[i], [u1, c1] = pts[i + 1];
    if (v >= u0 && v <= u1) {
      const w = (v - u0) / (u1 - u0);
      const r = Math.round(c0[0] * (1 - w) + c1[0] * w);
      const g = Math.round(c0[1] * (1 - w) + c1[1] * w);
      const b = Math.round(c0[2] * (1 - w) + c1[2] * w);
      return `rgb(${r},${g},${b})`;
    }
  }
  return "rgb(252,253,191)";
}

function makeHeatmapSvg(cols, rows, gridFn, title, w = 520, h = 110) {
  const cw = w / cols, ch = h / rows;
  const rects = [];
  for (let c = 0; c < cols; c++) {
    for (let r = 0; r < rows; r++) {
      const u = gridFn(c, r);
      rects.push(`<rect x="${(c * cw).toFixed(1)}" y="${(r * ch).toFixed(1)}" width="${(cw + 0.6).toFixed(1)}" height="${(ch + 0.6).toFixed(1)}" fill="${infernoHex(u)}"/>`);
    }
  }
  return `<svg viewBox="0 0 ${w} ${h + 18}" width="100%" style="background:#0a0e18;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="#f472b6" font-size="10" font-family="system-ui">${title}</text><g transform="translate(0,18)">${rects.join("")}</g></svg>`;
}

function makePolylineSvg(pts, title, color = "#f472b6", w = 520, h = 95, yLabel = "") {
  const poly = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h + 18}" width="100%" style="background:#0f1624;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="#e2e8f0" font-size="10" font-family="system-ui">${title} ${yLabel}</text><g transform="translate(0,18)"><line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="#1e293b" stroke-dasharray="3,3"/><polyline fill="none" stroke="${color}" stroke-width="2" points="${poly}"/></g></svg>`;
}

export const CAT10_TOOLS = [
  {
    id: 91, key: "vis_mag_spec_dr", name: "[SVG] 振幅スペクトログラム (0-8kHz) 生成", unit: "dB-DR",
    run(d, ctx) {
      const cols = 72, rows = 28;
      let mn = Infinity, mx = -Infinity;
      const svg = makeHeatmapSvg(cols, rows, (c, r) => {
        const t = Math.min(d.nFrames - 1, Math.floor((c / cols) * d.nFrames));
        const b = Math.min(d.nBins - 1, Math.floor(((rows - 1 - r) / rows) * d.nBins));
        const v = d.magDb[t][b];
        if (v < mn) mn = v; if (v > mx) mx = v;
        return (v + 75.0) / 65.0;
      }, "#91 Magnitude Spectrogram (0-8kHz)");
      if (ctx?.visuals) ctx.visuals.magSpec = svg;
      return Number((mx - mn).toFixed(1));
    },
  },
  {
    id: 92, key: "vis_phase_lock_map", name: "[SVG] 位相ロックマップ (d²φ/dt²) 生成", unit: "lock%",
    run(d, ctx) {
      const cols = 64, rows = 20;
      let sum = 0.0, cnt = 0;
      const svg = makeHeatmapSvg(cols, rows, (c, r) => {
        const t = Math.min(d.nFrames - 2, Math.max(1, Math.floor((c / cols) * d.nFrames)));
        const b = Math.min(d.nBins - 1, Math.floor(((rows - 1 - r) / rows) * d.nBins));
        let d2 = Math.abs(d.phase[t + 1][b] - 2 * d.phase[t][b] + d.phase[t - 1][b]);
        while (d2 > Math.PI) d2 = Math.abs(d2 - 2 * Math.PI);
        const lock = Math.max(0.0, 1.0 - d2 / Math.PI);
        sum += lock; cnt++;
        return lock;
      }, "#92 Phase-Lock Stability Map");
      if (ctx?.visuals) ctx.visuals.phaseMap = svg;
      return Number(((100.0 * sum) / (cnt || 1)).toFixed(1));
    },
  },
  {
    id: 93, key: "vis_ltas_curve", name: "[SVG] 0-8kHz LTASスペクトル曲線 生成", unit: "dB-end",
    run(d, ctx) {
      const nP = 48, vals = [];
      for (let i = 0; i < nP; i++) {
        const b = Math.min(d.nBins - 1, Math.floor((i / nP) * d.nBins));
        let s = 0.0, n = 0;
        for (let t = 0; t < d.nFrames; t++) if (d.f0Hz[t] > 0) { s += d.magDb[t][b]; n++; }
        vals.push(n ? s / n : -70.0);
      }
      const ref0 = vals[3] || -30.0;
      const pts = vals.map((v, i) => [(i / (nP - 1)) * 520, Math.max(4, Math.min(91, ((10 - (v - ref0)) / 50) * 95))]);
      if (ctx?.visuals) ctx.visuals.ltasSvg = makePolylineSvg(pts, "#93 LTAS Spectrum (0-8kHz)", "#38bdf8");
      return Number((vals[nP - 1] - ref0).toFixed(1));
    },
  },
  {
    id: 94, key: "vis_f0_contour", name: "[SVG] F0ピッチ＆語尾スクープ曲線 生成", unit: "vo%",
    run(d, ctx) {
      const pts = [];
      let vo = 0;
      for (let t = 0; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0) {
          vo++;
          const st = 12.0 * Math.log2(d.f0Hz[t] / 220.0);
          pts.push([(t / Math.max(1, d.nFrames - 1)) * 520, Math.max(4, Math.min(91, ((16 - st) / 24) * 95))]);
        }
      }
      if (ctx?.visuals) ctx.visuals.f0Svg = makePolylineSvg(pts, "#94 F0 Pitch Contour (st rel 220Hz)", "#f472b6");
      return Number(((100.0 * vo) / (d.nFrames || 1)).toFixed(1));
    },
  },
  {
    id: 95, key: "vis_formant_scatter", name: "[SVG] F1×F2 声道フォルマント散布図 生成", unit: "pts",
    run(d, ctx) {
      const f = d._formants || { f1s: [], f2s: [] };
      const dots = [];
      for (let i = 0; i < f.f1s.length; i += 2) {
        const x = Math.max(8, Math.min(252, ((3200 - f.f2s[i]) / 2600) * 260));
        const y = Math.max(8, Math.min(122, ((f.f1s[i] - 200) / 1000) * 130));
        dots.push(`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" fill="#fbbf24" fill-opacity="0.55"/>`);
      }
      const svg = `<svg viewBox="0 0 260 148" width="100%" style="background:#0f1624;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="#fbbf24" font-size="10" font-family="system-ui">#95 F1xF2 Vowel Space (F2<- / F1v)</text><g transform="translate(0,18)">${dots.join("")}</g></svg>`;
      if (ctx?.visuals) ctx.visuals.formantSvg = svg;
      return f.f1s.length;
    },
  },
  {
    id: 96, key: "vis_mod_spec_bars", name: "[SVG] 変調スペクトル (1-25Hz) バーSVG 生成", unit: "pk-dB",
    run(d, ctx) {
      const ms = d._modSpec || { freqs: [], amps: [] };
      const mx = Math.max(1e-6, ...ms.amps);
      const bars = ms.amps.map((a, i) => {
        const x = (i / Math.max(1, ms.amps.length)) * 260;
        const bh = (a / mx) * 110;
        return `<rect x="${x.toFixed(1)}" y="${(120 - bh).toFixed(1)}" width="4" height="${bh.toFixed(1)}" fill="#38bdf8"/>`;
      }).join("");
      const svg = `<svg viewBox="0 0 260 140" width="100%" style="background:#0f1624;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="#38bdf8" font-size="10" font-family="system-ui">#96 Modulation Spectrum (1-25Hz)</text><g transform="translate(0,18)">${bars}</g></svg>`;
      if (ctx?.visuals) ctx.visuals.modSvg = svg;
      return Number(mx.toFixed(2));
    },
  },
  {
    id: 97, key: "vis_harm_waterfall", name: "[SVG] H1-H12 倍音ラダーバーSVG 生成", unit: "dB-H8",
    run(d, ctx) {
      const df = d.freqs[1] - d.freqs[0] || 20.0;
      const hs = new Array(12).fill(0.0);
      let cnt = 0;
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        for (let k = 1; k <= 12; k++) {
          const b = Math.min(d.nBins - 1, Math.round((k * f0) / df));
          hs[k - 1] += d.magDb[t][b];
        }
        cnt++;
      }
      for (let k = 0; k < 12; k++) hs[k] = cnt ? hs[k] / cnt : -70.0;
      const h1 = hs[0] || -20.0;
      const bars = hs.map((v, i) => {
        const rel = v - h1;
        const bh = Math.max(2, Math.min(105, ((rel + 45) / 50) * 105));
        return `<rect x="${12 + i * 20}" y="${(115 - bh).toFixed(1)}" width="14" height="${bh.toFixed(1)}" fill="${i === 0 ? "#4ade80" : "#f472b6"}"/><text x="${14 + i * 20}" y="126" fill="#94a3b8" font-size="8">H${i + 1}</text>`;
      }).join("");
      const svg = `<svg viewBox="0 0 260 148" width="100%" style="background:#0f1624;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="#4ade80" font-size="10" font-family="system-ui">#97 Harmonic Ladder (H1..H12 rel H1)</text><g transform="translate(0,18)">${bars}</g></svg>`;
      if (ctx?.visuals) ctx.visuals.harmSvg = svg;
      return Number((hs[7] - h1).toFixed(1));
    },
  },
  {
    id: 98, key: "vis_artifact_flags", name: "[SVG] 異音・赤旗タイムライン検知 生成", unit: "flags",
    run(d, ctx) {
      let flags = 0;
      const bars = [];
      for (let t = 0; t < d.nFrames; t += 2) {
        if (!d.f0Hz[t]) continue;
        // Flag frame if sharp ear-fatigue peak in 2.5-4.2kHz exceeds low-mid by > -4dB
        let pk = -Infinity, lo = 0.0, ln = 0;
        for (let b = 0; b < d.nBins; b++) {
          if (d.freqs[b] >= 2500 && d.freqs[b] <= 4200 && d.magDb[t][b] > pk) pk = d.magDb[t][b];
          if (d.freqs[b] >= 400 && d.freqs[b] <= 1800) { lo += d.magDb[t][b]; ln++; }
        }
        const bad = pk - (lo / (ln || 1)) > 16.0;
        if (bad) {
          flags++;
          const x = (t / Math.max(1, d.nFrames - 1)) * 520;
          bars.push(`<rect x="${x.toFixed(1)}" y="6" width="3" height="24" fill="#ef4444"/>`);
        }
      }
      const svg = `<svg viewBox="0 0 520 52" width="100%" style="background:#0f1624;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="${flags ? "#ef4444" : "#4ade80"}" font-size="10" font-family="system-ui">#98 Artifact Red-Flag Timeline (${flags} flags)</text><g transform="translate(0,16)"><line x1="0" y1="18" x2="520" y2="18" stroke="#1e293b"/>${bars.join("")}</g></svg>`;
      if (ctx?.visuals) ctx.visuals.flagSvg = svg;
      return flags;
    },
  },
  {
    id: 99, key: "vis_kawaii_radar", name: "[SVG] 6軸カワイイ総合レーダーチャート 生成", unit: "area%",
    run(d, ctx) {
      const m = ctx?.metrics || {};
      const axes = [
        ["Kawaii", (m.kawaii_overall_100 ?? 50) / 100],
        ["Modern", (m.anime_modern_100 ?? 50) / 100],
        ["Sweet", (m.sweet_voice_100 ?? 50) / 100],
        ["Clean", 1 - (m.artifact_risk_100 ?? 0) / 100],
        ["Human", 1 - (m.uncanny_synth_100 ?? 50) / 100],
        ["V-Breath", Math.min(1, (m.voiced_breath_ratio ?? 0.5) / 0.85)],
      ];
      const cx = 130, cy = 78, R = 52;
      const pts = axes.map(([, v], i) => {
        const ang = -Math.PI / 2 + (i * 2 * Math.PI) / 6;
        return [cx + R * Math.max(0.05, v) * Math.cos(ang), cy + R * Math.max(0.05, v) * Math.sin(ang)];
      });
      const labels = axes.map(([name], i) => {
        const ang = -Math.PI / 2 + (i * 2 * Math.PI) / 6;
        const lx = cx + (R + 18) * Math.cos(ang), ly = cy + (R + 14) * Math.sin(ang);
        return `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" fill="#cbd5e1" font-size="9" text-anchor="middle">${name}</text>`;
      }).join("");
      const poly = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
      const svg = `<svg viewBox="0 0 260 152" width="100%" style="background:#0f1624;border-radius:8px;border:1px solid #24314a"><text x="6" y="13" fill="#f472b6" font-size="10" font-family="system-ui">#99 6-Axis Kawaii Radar</text><circle cx="${cx}" cy="${cy}" r="${R}" fill="none" stroke="#1e293b"/><circle cx="${cx}" cy="${cy}" r="${R / 2}" fill="none" stroke="#1e293b"/><polygon points="${poly}" fill="rgba(244,114,182,0.32)" stroke="#f472b6" stroke-width="2"/>${labels}</svg>`;
      if (ctx?.visuals) ctx.visuals.radarSvg = svg;
      const avg = axes.reduce((s, [, v]) => s + v, 0) / 6.0;
      return Number((avg * 100.0).toFixed(1));
    },
  },
  {
    id: 100, key: "vis_100_report_ready", name: "[HTML] 100ツール全部入りビジュアルHTMLレポート", unit: "tools",
    run(d, ctx) {
      return Object.keys(ctx?.metrics || {}).length + 1;
    },
  },
];

export function buildHtmlReport(results, allTools) {
  const hero = results[results.length - 1];
  const v = hero.visuals || {};
  const headers = results.map((r) => `<th>${r.label}</th>`).join("");
  const rows = allTools.map((t) => {
    const cells = results.map((r) => `<td>${r.metrics[t.key]}</td>`).join("");
    return `<tr><td>#${String(t.id).padStart(2, "0")}</td><td><code>${t.key}</code></td><td>${t.name}</td><td>${t.unit}</td>${cells}</tr>`;
  }).join("\n");
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カワイイクサナギ 変態解析ツール100選 X線レポート</title>
<style>
  :root { color-scheme: dark; --bg: #070b14; --panel: #101726; --border: #24314a; --pink: #f472b6; --cyan: #38bdf8; --fg: #f1f5f9; --muted: #94a3b8; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 14px; font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); }
  h1 { margin: 0 0 4px; font-size: 1.05rem; color: #fff; }
  .sub { font-size: 0.76rem; color: var(--muted); margin-bottom: 12px; }
  .vgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 8px; margin-bottom: 12px; }
  .vwide { display: grid; gap: 8px; margin-bottom: 10px; }
  details { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; }
  summary { cursor: pointer; font-weight: 800; font-size: 0.85rem; color: var(--pink); }
  table { width: 100%; border-collapse: collapse; font-size: 0.72rem; margin-top: 8px; }
  th, td { padding: 4px 6px; border-bottom: 1px solid var(--border); text-align: right; }
  th:nth-child(-n+4), td:nth-child(-n+4) { text-align: left; }
  th { color: var(--cyan); position: sticky; top: 0; background: var(--panel); }
  code { color: #fbbf24; font-size: 0.7rem; }
</style></head><body>
<h1>🔬 カワイイクサナギ — 変態解析ツール 100選 X線レポート (${allTools.length} Tools)</h1>
<div class="sub">純JS・外部依存ゼロ / ビジュアル対象: <b>${hero.label}</b>（全${results.length}ファイル比較）</div>
<div class="vwide">${v.magSpec || ""}${v.phaseMap || ""}${v.ltasSvg || ""}${v.f0Svg || ""}${v.flagSvg || ""}</div>
<div class="vgrid">${v.radarSvg || ""}${v.formantSvg || ""}${v.harmSvg || ""}${v.modSvg || ""}</div>
<details open><summary>📊 全 ${allTools.length} ツール計測テーブル（クリックで開閉）</summary>
<div style="overflow-x:auto;max-height:460px"><table><thead><tr><th>#</th><th>Key</th><th>Tool Name</th><th>Unit</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div>
</details></body></html>`;
}
