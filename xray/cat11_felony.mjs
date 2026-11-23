// xray/cat11_felony.mjs — 懲役もんの前人未到・深淵解析ツール #101〜#110 (Pure JS, Zero Dependencies)
// Visibility Graphs, TDA Toroidality, RQA, Bicoherence, Time-Reversal Thermodynamics,
// Teager-Kaiser Vortex Energy, Predictive-Coding Surprise, Harmonic Organ Rank, Vocal-Tract Area Inversion
import { median, percentile } from "./core.mjs";

function voicedCenterSlice(d, len = 1024) {
  // Find loudest voiced frame and extract a clean voiced waveform window
  let bestT = -1, bestRms = 0.0;
  for (let t = 0; t < d.nFrames; t++) {
    if (d.f0Hz[t] > 0 && d.rmsFr[t] > bestRms) { bestRms = d.rmsFr[t]; bestT = t; }
  }
  if (bestT < 0) return { seg: d.x.subarray(0, Math.min(len, d.x.length)), f0: 300.0 };
  const c = bestT * d.hop + (d.wl >> 1);
  const a = Math.max(0, Math.min(Math.max(0, d.x.length - len), c - (len >> 1)));
  return { seg: d.x.subarray(a, Math.min(d.x.length, a + len)), f0: d.f0Hz[bestT] };
}

export function computeRqaSlice(seg, sr, f0) {
  const f0Safe = f0 > 50 ? f0 : 300.0;
  const tau = Math.max(2, Math.round(sr / (f0Safe * 4.0)));
  if (seg.length - 2 * tau < 12) return { entr: 0.0, lam: 0.0 };
  const step = Math.max(1, Math.floor((seg.length - 2 * tau) / 96));
  const pts = [];
  for (let i = 0; i + 2 * tau < seg.length && pts.length < 96; i += step) {
    pts.push([seg[i], seg[i + tau], seg[i + 2 * tau]]);
  }
  const M = pts.length;
  if (M < 12) return { entr: 0.0, lam: 0.0 };
  const dists = [];
  const D = new Float64Array(M * M);
  let maxDist = 0.0;
  for (let i = 0; i < M; i++) {
    for (let j = i + 1; j < M; j++) {
      const dist = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1], pts[i][2] - pts[j][2]);
      D[i * M + j] = D[j * M + i] = dist;
      dists.push(dist);
      if (dist > maxDist) maxDist = dist;
    }
  }
  // Guard silent/constant slices from returning spurious 100% LAM
  if (maxDist < 1e-9) return { entr: 0.0, lam: 0.0 };
  const eps = percentile(dists, 15) || 1e-6;
  const R = new Uint8Array(M * M);
  let recTot = 0;
  for (let i = 0; i < M * M; i++) if (D[i] <= eps) { R[i] = 1; recTot++; }

  // Diagonal line lengths (excluding main diagonal) -> Shannon Entropy (ENTR)
  const diagHist = new Map();
  let diagTot = 0;
  for (let k = 2; k < M - 2; k++) {
    let run = 0;
    for (let i = 0; i + k < M; i++) {
      if (R[i * M + (i + k)]) run++;
      else { if (run >= 2) { diagHist.set(run, (diagHist.get(run) || 0) + 1); diagTot++; } run = 0; }
    }
    if (run >= 2) { diagHist.set(run, (diagHist.get(run) || 0) + 1); diagTot++; }
  }
  let entr = 0.0;
  for (const c of diagHist.values()) { const p = c / (diagTot || 1); entr -= p * Math.log2(p + 1e-12); }

  // Vertical line points >= 2 -> Laminarity (LAM %)
  let lamPts = 0;
  for (let j = 0; j < M; j++) {
    let run = 0;
    for (let i = 0; i < M; i++) {
      if (R[i * M + j]) run++;
      else { if (run >= 2) lamPts += run; run = 0; }
    }
    if (run >= 2) lamPts += run;
  }
  return { entr, lam: (100.0 * lamPts) / (recTot || 1) };
}

function buildRqaStats(d) {
  if (d._rqa) return d._rqa;
  const allVo = [];
  let maxVoRms = 0.0;
  for (let t = 0; t < d.nFrames; t++) {
    if (d.f0Hz[t] > 0) {
      allVo.push(t);
      if (d.rmsFr[t] > maxVoRms) maxVoRms = d.rmsFr[t];
    }
  }
  if (!allVo.length) {
    d._rqa = { entr: 0.0, lam: 0.0 };
    return d._rqa;
  }
  const strongVo = allVo.filter((t) => d.rmsFr[t] >= 0.40 * maxVoRms);
  const cand = strongVo.length >= 5 ? strongVo : allVo;
  const K = Math.min(5, cand.length);
  const len = Math.max(256, Math.round(0.050 * d.sr));
  const picked = [];
  for (let q = 0; q < K; q++) {
    const i0 = Math.floor((q * cand.length) / K);
    const i1 = Math.max(i0 + 1, Math.floor(((q + 1) * cand.length) / K));
    let bestT = cand[i0], bestRms = -1.0;
    for (let i = i0; i < i1; i++) {
      const t = cand[i];
      if (d.rmsFr[t] > bestRms) { bestRms = d.rmsFr[t]; bestT = t; }
    }
    if (!picked.length || picked[picked.length - 1] !== bestT) picked.push(bestT);
  }
  const entrs = [], lams = [];
  for (const bestT of picked) {
    const c = bestT * d.hop + (d.wl >> 1);
    const a = Math.max(0, Math.min(Math.max(0, d.x.length - len), c - (len >> 1)));
    const seg = d.x.subarray(a, Math.min(d.x.length, a + len));
    const st = computeRqaSlice(seg, d.sr, d.f0Hz[bestT]);
    entrs.push(st.entr);
    lams.push(st.lam);
  }
  d._rqa = { entr: Number(median(entrs).toFixed(3)), lam: Number(median(lams).toFixed(1)) };
  return d._rqa;
}

function jacobiEigenvalues(mat, n) {
  const A = Float64Array.from(mat);
  for (let iter = 0; iter < 40; iter++) {
    let p = 0, q = 1, maxOff = 0.0;
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const v = Math.abs(A[i * n + j]);
        if (v > maxOff) { maxOff = v; p = i; q = j; }
      }
    }
    if (maxOff < 1e-8) break;
    const app = A[p * n + p], aqq = A[q * n + q], apq = A[p * n + q];
    const phi = 0.5 * Math.atan2(2.0 * apq, aqq - app);
    const c = Math.cos(phi), s = Math.sin(phi);
    for (let i = 0; i < n; i++) {
      if (i === p || i === q) continue;
      const aip = A[i * n + p], aiq = A[i * n + q];
      A[i * n + p] = A[p * n + i] = c * aip - s * aiq;
      A[i * n + q] = A[q * n + i] = s * aip + c * aiq;
    }
    A[p * n + p] = c * c * app - 2 * s * c * apq + s * s * aqq;
    A[q * n + q] = s * s * app + 2 * s * c * apq + c * c * aqq;
    A[p * n + q] = A[q * n + p] = 0.0;
  }
  const ev = [];
  for (let i = 0; i < n; i++) ev.push(Math.max(0.0, A[i * n + i]));
  return ev;
}

export const CAT11_TOOLS = [
  {
    id: 101, key: "svg_mean_degree", name: "[深淵] スペクトル可視性グラフ平均次数 (arXiv:2502.14110)", unit: "deg",
    run(d) {
      // Natural Visibility Graph on 96-bin averaged voiced spectrum (0-6kHz)
      const N = 96;
      const y = new Float64Array(N);
      let cnt = 0;
      for (let t = 0; t < d.nFrames; t++) {
        if (!d.f0Hz[t]) continue;
        for (let i = 0; i < N; i++) {
          const b = Math.min(d.nBins - 1, Math.floor((i / N) * (d.nBins * 0.75)));
          y[i] += d.magDb[t][b];
        }
        cnt++;
      }
      if (!cnt) return 0.0;
      for (let i = 0; i < N; i++) y[i] /= cnt;
      let edges = 0;
      for (let i = 0; i < N - 1; i++) {
        let maxSlope = -Infinity;
        for (let j = i + 1; j < N; j++) {
          const slope = (y[j] - y[i]) / (j - i);
          if (slope > maxSlope) { edges++; maxSlope = slope; }
        }
      }
      return Number(((2.0 * edges) / N).toFixed(2));
    },
  },
  {
    id: 102, key: "tda_toroidality", name: "[深淵] トポロジーH1ループ肉厚/トーラス度 (arXiv:2311.15210)", unit: "ratio",
    run(d) {
      // Delay-embedded 3D attractor radial shell thickness (std(r)/mean(r)): thin S^1 synth ring -> low; thick T^2 human -> higher
      const vals = [];
      for (let t = 0; t < d.nFrames; t += 4) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const tau = Math.max(2, Math.round(d.sr / (f0 * 4.0)));
        const off = t * d.hop;
        if (off + d.wl >= d.x.length) continue;
        const rs = [];
        let mR = 0.0;
        for (let i = 0; i + 2 * tau < d.wl; i += 2) {
          const r = Math.hypot(d.x[off + i], d.x[off + i + tau], d.x[off + i + 2 * tau]);
          rs.push(r); mR += r;
        }
        mR /= rs.length || 1;
        let vR = 0.0;
        for (const r of rs) vR += (r - mR) * (r - mR);
        vals.push(Math.sqrt(vR / (rs.length || 1)) / (mR + 1e-9));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 103, key: "rqa_diag_entropy", name: "[深淵] 再帰プロットRQA 対角線エントロピー ENTR", unit: "bits",
    run: (d) => buildRqaStats(d).entr,
  },
  {
    id: 104, key: "rqa_laminarity_pct", name: "[深淵] 再帰プロットRQA ラミナリティ LAM (声門停滞率)", unit: "%",
    run: (d) => buildRqaStats(d).lam,
  },
  {
    id: 105, key: "bicoherence_idx", name: "[深淵] バイコヒーレンス (f0+f0=2f0 3重非線形位相結合)", unit: "0..1",
    run(d) {
      const df = d.freqs[1] - d.freqs[0] || 20.0;
      let reSum = 0.0, imSum = 0.0, p12 = 0.0, p3 = 0.0, cnt = 0;
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const b1 = Math.min(d.nBins - 1, Math.round(f0 / df));
        const b2 = Math.min(d.nBins - 1, Math.round((2 * f0) / df));
        const b3 = Math.min(d.nBins - 1, Math.round((3 * f0) / df));
        if (b3 >= d.nBins) continue;
        const m1 = d.mag[t][b1], m2 = d.mag[t][b2], m3 = d.mag[t][b3];
        const ph = d.phase[t][b1] + d.phase[t][b2] - d.phase[t][b3];
        const amp = m1 * m2 * m3;
        reSum += amp * Math.cos(ph);
        imSum += amp * Math.sin(ph);
        p12 += (m1 * m2) * (m1 * m2);
        p3 += m3 * m3;
        cnt++;
      }
      if (cnt < 4) return 0.0;
      return Number(Math.min(1.0, Math.hypot(reSum, imSum) / (Math.sqrt(p12 * p3) + 1e-18)).toFixed(3));
    },
  },
  {
    id: 106, key: "time_arrow_asym", name: "[深淵] 熱力学「時間の矢」非可逆性 E[(x(t+τ)-x(t))^3]", unit: "skew3",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t += 2) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        const tau = Math.max(1, Math.round(d.sr / (f0 * 8.0)));
        const off = t * d.hop;
        if (off + d.wl >= d.x.length) continue;
        let m2 = 0.0, m3 = 0.0, n = 0;
        for (let i = 0; i + tau < d.wl; i++) {
          const dx = d.x[off + i + tau] - d.x[off + i];
          m2 += dx * dx; m3 += dx * dx * dx; n++;
        }
        const s = Math.sqrt(m2 / (n || 1)) || 1e-9;
        vals.push(Math.abs((m3 / (n || 1)) / (s * s * s)));
      }
      return Number(median(vals).toFixed(3));
    },
  },
  {
    id: 107, key: "tkeo_vortex_ratio", name: "[深淵] Teager-Kaiser 非線形乱流渦エネルギー比", unit: "ratio",
    run(d) {
      const vals = [];
      for (let t = 0; t < d.nFrames; t += 2) {
        if (!d.f0Hz[t]) continue;
        const off = t * d.hop;
        if (off + d.wl >= d.x.length) continue;
        const psi = [];
        for (let i = 1; i < d.wl - 1; i++) {
          const v = Math.abs(d.x[off + i] * d.x[off + i] - d.x[off + i - 1] * d.x[off + i + 1]);
          psi.push(v);
        }
        const med = median(psi) || 1e-12;
        vals.push(percentile(psi, 95) / med);
      }
      return Number(median(vals).toFixed(2));
    },
  },
  {
    id: 108, key: "brain_surprise_bits", name: "[深淵] 聴覚脳・予測誤差サプライズ (AR(2)予測残差)", unit: "bits/fr",
    run(d) {
      // Predictive-coding surprise on 8 log-band trajectories across active frames
      const B = 8;
      const traj = Array.from({ length: B }, () => []);
      for (let t = 0; t < d.nFrames; t++) {
        if (d.rmsFr[t] < 0.015) continue;
        for (let b = 0; b < B; b++) {
          const i0 = Math.floor((b / B) * d.nBins), i1 = Math.floor(((b + 1) / B) * d.nBins);
          let s = 0.0;
          for (let k = i0; k < i1; k++) s += d.magDb[t][k];
          traj[b].push(s / Math.max(1, i1 - i0));
        }
      }
      let bits = 0.0;
      for (let b = 0; b < B; b++) {
        const y = traj[b];
        if (y.length < 6) continue;
        let errSq = 0.0;
        for (let t = 2; t < y.length; t++) {
          // Linear extrapolation prediction: y_hat = 1.5*y[t-1] - 0.5*y[t-2]
          const pred = 1.5 * y[t - 1] - 0.5 * y[t - 2];
          const e = y[t] - pred;
          errSq += e * e;
        }
        const sigma = Math.sqrt(errSq / (y.length - 2)) + 1e-6;
        bits += 0.5 * Math.log2(2.0 * Math.PI * Math.E * sigma * sigma);
      }
      return Number((bits / B).toFixed(2));
    },
  },
  {
    id: 109, key: "harm_organ_rank", name: "[深淵] 倍音共謀ネットワーク有効ランク (独立物理器官数)", unit: "organs",
    run(d) {
      // Effective rank exp(H(eigenvalues)) of the 8x8 H1..H8 amplitude correlation matrix
      const K = 8, df = d.freqs[1] - d.freqs[0] || 20.0;
      const seq = Array.from({ length: K }, () => []);
      for (let t = 0; t < d.nFrames; t++) {
        const f0 = d.f0Hz[t]; if (!f0) continue;
        for (let k = 0; k < K; k++) {
          const b = Math.min(d.nBins - 1, Math.round(((k + 1) * f0) / df));
          seq[k].push(d.magDb[t][b]);
        }
      }
      const T = seq[0].length;
      if (T < 8) return 1.0;
      const means = seq.map((a) => a.reduce((x, y) => x + y, 0) / T);
      const stds = seq.map((a, i) => Math.sqrt(a.reduce((s, v) => s + (v - means[i]) ** 2, 0) / T) || 1e-6);
      const C = new Float64Array(K * K);
      for (let i = 0; i < K; i++) {
        for (let j = i; j < K; j++) {
          let s = 0.0;
          for (let t = 0; t < T; t++) s += ((seq[i][t] - means[i]) / stds[i]) * ((seq[j][t] - means[j]) / stds[j]);
          C[i * K + j] = C[j * K + i] = s / T;
        }
      }
      const ev = jacobiEigenvalues(C, K);
      const sumEv = ev.reduce((a, b) => a + b, 0) || 1.0;
      let H = 0.0;
      for (const lam of ev) { const p = lam / sumEv; if (p > 1e-12) H -= p * Math.log(p); }
      return Number(Math.exp(H).toFixed(2));
    },
  },
  {
    id: 110, key: "tract_area_ratio", name: "[深淵] 声道断面積の物理逆算 (LPC10反射係数 唇/喉比)", unit: "ratio",
    run(d) {
      // Levinson-Durbin LPC(10) on voiced vowel -> reflection coeffs k1..k10 -> front/back vocal-tract area ratio
      const { seg } = voicedCenterSlice(d, 1024);
      const P = 10, N = seg.length;
      if (N < 64) return 1.0;
      // Pre-emphasis + autocorrelation
      const r = new Float64Array(P + 1);
      const pe = new Float64Array(N);
      pe[0] = seg[0];
      for (let i = 1; i < N; i++) pe[i] = seg[i] - 0.95 * seg[i - 1];
      for (let lag = 0; lag <= P; lag++) {
        let s = 0.0;
        for (let i = 0; i < N - lag; i++) s += pe[i] * pe[i + lag];
        r[lag] = s;
      }
      if (r[0] < 1e-12) return 1.0;
      let a = new Float64Array(P + 1);
      let E = r[0];
      const ks = new Float64Array(P);
      for (let m = 1; m <= P; m++) {
        let acc = r[m];
        for (let j = 1; j < m; j++) acc += a[j] * r[m - j];
        const km = Math.max(-0.98, Math.min(0.98, -acc / (E + 1e-12)));
        ks[m - 1] = km;
        const aNew = new Float64Array(P + 1);
        aNew[m] = km;
        for (let j = 1; j < m; j++) aNew[j] = a[j] + km * a[m - j];
        a = aNew;
        E *= (1.0 - km * km);
      }
      // Area function A[m+1] = A[m] * (1 - k_m) / (1 + k_m)
      const A = new Float64Array(P + 1);
      A[0] = 1.0;
      for (let m = 0; m < P; m++) A[m + 1] = A[m] * ((1.0 - ks[m]) / (1.0 + ks[m]));
      const front = (A[1] + A[2] + A[3]) / 3.0;
      const back = (A[7] + A[8] + A[9]) / 3.0;
      return Number(Math.min(99.0, front / (back + 1e-6)).toFixed(2));
    },
  },
];
