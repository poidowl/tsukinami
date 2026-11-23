// xray/cat13_audit.mjs — 変態解析ツール #131〜#150:
// 総合音質監査・子音/立上がり・5大物理機構バリデータ (Plomp-Levelt ERB, All-Sample Cliff/Jerk,
// Post-Pause Onset Toe, Voiced Sibilant & Affricate Closure/Burst, Sturm-Liouville F4 Lift,
// Hopf Tail Dissolution, 1/f Pink F0 Fluctuation, F1-F0 Tuning, Intelligibility Guard)
import { median, percentile } from "./core.mjs";
import { getCloseSharpStats } from "./cat01_glottal.mjs";
import { getPlompLeveltErb } from "./cat08_psycho.mjs";

function clamp01(v) {
  return Math.max(0.0, Math.min(1.0, v));
}

function frameSfm(freqs, mag, fLo, fHi) {
  let logSum = 0.0, linSum = 0.0, n = 0;
  for (let b = 0; b < freqs.length; b++) {
    const f = freqs[b];
    if (f >= fLo && f <= fHi) {
      const p = mag[b] * mag[b] + 1e-18;
      logSum += Math.log(p);
      linSum += p;
      n++;
    }
  }
  if (!n) return 0.0;
  return Math.exp(logSum / n) / (linSum / n + 1e-18);
}

function frameBandHnr(d, t, fLo, fHi) {
  const f0 = d.f0Hz[t];
  if (!f0) return null;
  const md = d.magDb[t];
  const k0 = Math.max(1, Math.ceil(fLo / f0));
  const k1 = Math.floor(fHi / f0);
  if (k1 <= k0) return null;
  const diffs = [];
  for (let k = k0; k < k1; k++) {
    let pMax = -Infinity, vMin = Infinity, hp = false, hv = false;
    const pLo = (k - 0.20) * f0, pHi = (k + 0.20) * f0;
    const vLo = (k + 0.30) * f0, vHi = (k + 0.70) * f0;
    for (let b = 0; b < d.nBins; b++) {
      const f = d.freqs[b];
      if (f >= pLo && f <= pHi) { if (md[b] > pMax) pMax = md[b]; hp = true; }
      if (f >= vLo && f <= vHi) { if (md[b] < vMin) vMin = md[b]; hv = true; }
    }
    if (hp && hv) diffs.push(pMax - vMin);
  }
  if (!diffs.length) return null;
  let s = 0.0;
  for (let i = 0; i < diffs.length; i++) s += diffs[i];
  return s / diffs.length;
}

function getFineRms(d) {
  if (d._fineRms) return d._fineRms;
  const winF = Math.max(4, Math.round(0.004 * d.sr));
  const hopF = Math.max(2, Math.round(0.002 * d.sr));
  const stepMs = (1000.0 * hopF) / d.sr;
  const N = d.x.length;
  const nF = Math.max(1, Math.floor((N - winF) / hopF) + 1);
  const fRms = new Float64Array(nF);
  const x = d.x;
  for (let k = 0; k < nF; k++) {
    const off = k * hopF;
    let sq = 0.0;
    for (let i = 0; i < winF; i++) {
      const v = off + i < N ? x[off + i] : 0.0;
      sq += v * v;
    }
    fRms[k] = Math.sqrt(sq / winF);
  }
  d._fineRms = { fRms, winF, hopF, stepMs, nF };
  return d._fineRms;
}

function getCliffJerk(d) {
  if (d._cliffJerk) return d._cliffJerk;
  const cs = getCloseSharpStats(d);
  let hasVoiced = false;
  for (let t = 0; t < d.nFrames; t++) {
    if (d.f0Hz[t] > 0) { hasVoiced = true; break; }
  }
  const x = d.x;
  const N = x.length;
  const d2Full = new Float64Array(N);
  const d2 = [];
  const d3 = [];
  let maxD2 = 0.0;
  let maxD3 = 0.0;
  let sumSq = 0.0;
  let maxD1 = 0.0;
  for (let i = 0; i < N; i++) {
    const v = x[i];
    sumSq += v * v;
    if (i >= 1) {
      const d1 = Math.abs(v - x[i - 1]);
      if (d1 > maxD1) maxD1 = d1;
    }
    const t = Math.max(0, Math.min(d.nFrames - 1, Math.round((i - 0.5 * d.wl) / d.hop)));
    if (i >= 2) {
      const v2 = Math.abs(v - 2.0 * x[i - 1] + x[i - 2]);
      d2Full[i] = v2;
      if (v2 > maxD2) maxD2 = v2;
      if (d.rmsFr[t] > 0.012) {
        d2.push(v2);
      }
    }
    if (i >= 3 && d.rmsFr[t] > 0.012) {
      const v3 = Math.abs(v - 3.0 * x[i - 1] + 3.0 * x[i - 2] - x[i - 3]);
      d3.push(v3);
      if (v3 > maxD3) maxD3 = v3;
    }
  }

  const medD2 = d2.length >= 16 ? median(d2) : 0.0;
  let cliffAll = 0.0;
  if (d2.length >= 16) {
    if (medD2 <= 1e-12) {
      cliffAll = maxD2 > 1e-9 ? 999.0 : 0.0;
    } else {
      const pVal = percentile(d2, 99.99);
      let bestD2 = pVal;
      const R = Math.max(16, Math.round(0.0015 * d.sr));
      const nb = [];
      for (let idx = 2; idx < N; idx++) {
        const v2 = d2Full[idx];
        const isLeftEdge = idx === 2 && Math.abs(x[0] - x[1]) >= 2.0 * Math.abs(x[1] - x[2]);
        const isRightEdge = idx === N - 1 && Math.abs(x[N - 1] - x[N - 2]) >= 2.0 * Math.abs(x[N - 2] - x[N - 3]);
        const effV2 = (isLeftEdge || isRightEdge) ? 2.0 * v2 : v2;
        if (effV2 <= pVal) continue;
        nb.length = 0;
        const lo = Math.max(2, idx - R);
        const hi = Math.min(N - 1, idx + R);
        for (let j = lo; j <= hi; j++) {
          if (Math.abs(j - idx) <= 2) continue;
          nb.push(d2Full[j]);
        }
        if (nb.length < 4) continue;
        nb.sort((a, b) => a - b);
        const nbP80 = nb[Math.min(nb.length - 1, Math.floor(0.80 * (nb.length - 1)))];
        if (v2 / Math.max(nbP80, 1e-12) >= 5.0 && effV2 > bestD2) bestD2 = effV2;
      }
      cliffAll = Number(Math.min(999.0, bestD2 / medD2).toFixed(2));
    }
  }

  const medD3 = d3.length >= 16 ? median(d3) : 0.0;
  let c2Jerk = 0.0;
  if (d3.length >= 16) {
    if (medD3 <= 1e-12) {
      c2Jerk = maxD3 > 1e-9 ? 999.0 : 0.0;
    } else {
      c2Jerk = Number(Math.min(999.0, percentile(d3, 99.9) / medD3).toFixed(2));
    }
  }

  const rmsAll = Math.sqrt(sumSq / (N || 1));
  const maxJump = rmsAll > 1e-9
    ? Number(Math.min(999.0, maxD1 / rmsAll).toFixed(2))
    : 0.0;

  d._cliffJerk = {
    cliffAll,
    maxJump,
    c2Jerk,
    medD2,
    csMed: cs.med,
    csP90: cs.p90,
    hasVoiced,
  };
  return d._cliffJerk;
}

function getOnsetAudit(d) {
  if (d._onsetAudit) return d._onsetAudit;
  const { fRms, hopF, stepMs, nF } = getFineRms(d);
  const minPauseFr = Math.round((0.080 * d.sr) / d.hop);
  const cands = [];
  let hasPriorVoice = false;

  for (let t = 0; t < d.nFrames; t++) {
    if (d.f0Hz[t] > 0 && (t === 0 || d.f0Hz[t - 1] === 0)) {
      let k = t - 1;
      let preUnvFric = 0;
      while (k >= 0 && d.f0Hz[k] === 0 && d.rmsFr[k] >= 0.020) {
        preUnvFric++;
        k--;
      }
      let preSil = 0;
      while (k >= 0 && d.f0Hz[k] === 0 && d.rmsFr[k] < 0.020) {
        preSil++;
        k--;
      }
      const isPostPause = hasPriorVoice && preSil >= minPauseFr && preUnvFric <= 4;
      const isInitial = !hasPriorVoice && preUnvFric <= 4;
      if (isInitial || isPostPause) cands.push({ t, isInitial });
      hasPriorVoice = true;
    } else if (d.f0Hz[t] > 0) {
      hasPriorVoice = true;
    }
  }

  const hopMs = (1000.0 * d.hop) / d.sr;
  const halfWlMs = (500.0 * d.wl) / d.sr;
  const bandPow = (tFr, lo, hi) => {
    const tf = Math.max(0, Math.min(d.nFrames - 1, tFr));
    const m = d.mag[tf];
    let s = 0.0;
    for (let b = 0; b < d.nBins; b++) {
      const f = d.freqs[b];
      if (f >= lo && f <= hi) s += m[b] * m[b];
    }
    return s + 1e-18;
  };

  const measured = [];
  for (const cand of cands) {
    const tVo = cand.t;
    const fVo = Math.min(nF - 1, Math.max(0, Math.round((tVo * d.hop) / hopF)));
    let fPk = fVo;
    let pk = fRms[fVo];
    const fHi = Math.min(nF - 1, fVo + 28);
    for (let k = fVo + 1; k <= fHi; k++) {
      if (fRms[k] > pk) { pk = fRms[k]; fPk = k; }
      else if (fRms[k] < 0.85 * pk && k >= fPk + 3) break;
    }
    if (pk < 0.025) continue;

    const fLo = Math.max(0, fVo - 28);
    let f10 = fPk;
    while (f10 > fLo && fRms[f10] > 0.10 * pk) f10--;
    // Skip abrupt full-level starts (e.g., continuous steady sine with no quiet onset floor)
    if (fRms[f10] > 0.30 * pk || fPk <= f10) continue;

    const crossMs = (thr) => {
      for (let k = f10; k < fPk; k++) {
        if (fRms[k] <= thr && fRms[k + 1] >= thr) {
          const dv = fRms[k + 1] - fRms[k];
          const frac = dv > 1e-12 ? (thr - fRms[k]) / dv : 0.0;
          return (k + Math.max(0.0, Math.min(1.0, frac))) * stepMs;
        }
      }
      return (fRms[f10] >= thr ? f10 : fPk) * stepMs;
    };

    const t10 = crossMs(0.10 * pk);
    const t50 = crossMs(0.50 * pk);
    const t85 = crossMs(0.85 * pk);
    const riseMs = Math.max(0.0, t85 - t10);
    const rawToe = Math.max(0.0, Math.min(1.0, (t50 - t10) / Math.max(1.0, riseMs)));

    const fastDamp = clamp01((riseMs - 8.0) / 6.0);
    const dampToe = rawToe > 0.50 ? 0.50 + (rawToe - 0.50) * fastDamp : rawToe;

    // Exclude true utterance-initial CV consonant releases (/w/,/m/ -> /a/ labial opening or /k/,/t/,/p/ burst drop)
    // while keeping bare-vowel initial onsets (|centLag| <= 3.3 dB) and all post-pause candidates intact.
    if (cand.isInitial) {
      const tEarlyC = Math.round((t10 + 4.0 - halfWlMs) / hopMs);
      const tSteadyC = Math.round((t85 + 8.0 - halfWlMs) / hopMs);
      const rEarlyC = 10.0 * Math.log10(bandPow(tEarlyC, 700, 2800) / bandPow(tEarlyC, 150, 650));
      const rSteadyC = 10.0 * Math.log10(bandPow(tSteadyC, 700, 2800) / bandPow(tSteadyC, 150, 650));
      const centLag = rSteadyC - rEarlyC;
      if ((centLag > 14.0 && rEarlyC < -6.0) || centLag < -10.0) continue;
    }

    const tEarly = Math.round((t10 + 4.0) / hopMs);
    const tSteady = Math.round((t85 + 8.0) / hopMs);
    const ratioEarly = 10.0 * Math.log10(bandPow(tEarly, 700, 2800) / bandPow(tEarly, 150, 650));
    const ratioSteady = 10.0 * Math.log10(bandPow(tSteady, 700, 2800) / bandPow(tSteady, 150, 650));
    const lagDb = ratioSteady - ratioEarly;
    const lagBonus = (riseMs > 18.0 && lagDb > 4.0) ? Math.min(0.15, (lagDb - 4.0) * 0.015) : 0.0;
    const effToe = Math.min(1.0, Math.max(0.0, dampToe + lagBonus));

    const pToe = riseMs >= 16.0 ? clamp01((effToe - 0.56) / 0.22) : 0.0;
    const pSlow = clamp01((riseMs - 38.0) / 25.0);
    const sev = 14.0 * pToe + 6.0 * pSlow;
    measured.push({ riseMs, effToe, sev });
  }

  let best = null;
  for (const item of measured) {
    if (!best) { best = item; continue; }
    if (item.sev > best.sev + 1e-9) { best = item; continue; }
    if (Math.abs(item.sev - best.sev) <= 1e-9) {
      const aSlowToe = item.riseMs >= 16.0 ? item.effToe : 0.0;
      const bSlowToe = best.riseMs >= 16.0 ? best.effToe : 0.0;
      if (aSlowToe > bSlowToe + 1e-9) { best = item; continue; }
      if (Math.abs(aSlowToe - bSlowToe) <= 1e-9) {
        if (item.effToe > best.effToe + 1e-9 || (Math.abs(item.effToe - best.effToe) <= 1e-9 && item.riseMs > best.riseMs)) {
          best = item;
        }
      }
    }
  }

  d._onsetAudit = {
    riseMs: best ? Number(best.riseMs.toFixed(1)) : 0.0,
    toe: best ? Number(best.effToe.toFixed(3)) : 0.0,
    nOnsets: measured.length,
  };
  return d._onsetAudit;
}

function getConsonantAudit(d) {
  if (d._consAudit) return d._consAudit;
  const isUnvSib = new Uint8Array(d.nFrames);
  let sibFrames = 0;
  let vsibFrames = 0;
  const vsibCents = [];
  // Stay below Nyquist/anti-aliasing rolloff at 16 kHz (0.45*16000 = 7200 Hz); bit-identical (8000 Hz) for sr >= 18 kHz
  const sfmHiMax = Math.min(8000.0, 0.45 * d.sr);

  for (let t = 0; t < d.nFrames; t++) {
    if (d.rmsFr[t] < 0.005) continue;
    const m = d.mag[t];
    let pLo = 0.0, pMid = 0.0, pSib = 0.0, pSibHi = 0.0;
    let c2Num = 0.0, c2Den = 0.0, c15Num = 0.0, c15Den = 0.0;
    for (let b = 0; b < d.nBins; b++) {
      const f = d.freqs[b];
      const p = m[b] * m[b];
      if (f >= 150.0 && f <= 650.0) pLo += p;
      else if (f > 650.0 && f <= 2800.0) pMid += p;
      else if (f > 2800.0 && f <= 8000.0) pSib += p;
      if (f >= 3500.0 && f <= 8000.0) pSibHi += p;
      if (f >= 2000.0 && f <= 8000.0) { c2Num += f * p; c2Den += p; }
      if (f >= 1500.0 && f <= 8000.0) { c15Num += f * p; c15Den += p; }
    }
    const pTot = pLo + pMid + pSib + 1e-18;
    const sfmHi = frameSfm(d.freqs, m, 2800.0, sfmHiMax);
    if (pSib / pTot > 0.14 && sfmHi > 0.28) {
      const c2k8k = c2Den > 0.0 ? c2Num / c2Den : 0.0;
      const c15k8k = c15Den > 0.0 ? c15Num / c15Den : 0.0;
      const isVoSib = d.f0Hz[t] > 0 || pLo / pTot > 0.10;
      if (d.rmsFr[t] >= 0.012) {
        sibFrames++;
        if (isVoSib) {
          vsibFrames++;
          vsibCents.push(c2k8k);
        }
      }
      if (!isVoSib && pSibHi / pTot > 0.62 && c15k8k > 4100.0) {
        isUnvSib[t] = 1;
      }
    }
  }

  const hasSib = sibFrames >= 3;
  const vsibCoexistPct = hasSib ? Number(((100.0 * vsibFrames) / sibFrames).toFixed(1)) : 0.0;
  const vsibCentroidHz = vsibFrames >= 3 ? Math.round(median(vsibCents)) : 0;

  // Bridge 1-2 frame gaps inside a single unvoiced sibilant run
  for (let t = 1; t < d.nFrames - 2; t++) {
    if (!isUnvSib[t] && isUnvSib[t - 1] && (isUnvSib[t + 1] || isUnvSib[t + 2])) isUnvSib[t] = 1;
  }

  // Affricate stop closure depth & burst jump detector
  const { fRms, winF, hopF, stepMs, nF } = getFineRms(d);
  let maxDepth = 0.0;
  let maxBurstJump = 0.0;
  const nCeil = 6; // exact 14ms sustained stop-closure ceiling window: (6 - 1)*2ms + 4ms = 14ms
  let t = 0;
  while (t < d.nFrames) {
    if (!isUnvSib[t]) { t++; continue; }
    const tStart = t;
    while (t < d.nFrames && isUnvSib[t]) t++;
    const runLen = t - tStart;
    if (runLen < 4) continue; // require >= 20ms unvoiced sibilant run

    // Center-aligned STFT -> fine-RMS mapping + forward edge snap across pre-burst silence
    const fSibRaw = Math.min(nF - 1, Math.max(0, Math.round((tStart * d.hop + 0.5 * (d.wl - winF)) / hopF)));
    const sibScanEnd = Math.min(nF - 1, fSibRaw + 12);
    let sibPk = 0.0;
    for (let k = fSibRaw; k <= sibScanEnd; k++) {
      if (fRms[k] > sibPk) sibPk = fRms[k];
    }
    const snapThr = Math.max(0.005, 0.25 * sibPk);
    let fSib = fSibRaw;
    const snapLim = Math.min(nF - 1, fSibRaw + 8); // up to +16ms (covers STFT half-window +13ms)
    while (fSib < snapLim && fRms[fSib] < snapThr) fSib++;

    // Preceding speech peak search (up to 150ms prior so 75ms closure + 15ms burst + vowel decay fits)
    const pLoIdx = Math.max(0, fSib - 75);
    const pHiIdx = Math.max(0, fSib - 7);
    let prePk = 0.0, fPrePk = pLoIdx;
    for (let k = pLoIdx; k <= pHiIdx && k < nF; k++) {
      if (fRms[k] > prePk) { prePk = fRms[k]; fPrePk = k; }
    }
    if (prePk < 0.04) continue;

    // Sustained 14ms stop-closure trough search (latest tie-breaking; widened to 96ms for 75ms closure + 15ms burst)
    const sLo = Math.max(fPrePk + 1, fSib - 48);
    const sHi = Math.min(nF - nCeil, fSib - nCeil);
    if (sHi < sLo) continue;

    let bestTrough = Infinity;
    let bestK = sLo;
    for (let k = sLo; k <= sHi; k++) {
      let ceilVal = fRms[k];
      for (let j = 1; j < nCeil; j++) {
        if (fRms[k + j] > ceilVal) ceilVal = fRms[k + j];
      }
      if (ceilVal < bestTrough) {
        bestTrough = ceilVal;
        bestK = k;
      } else if (ceilVal <= bestTrough + 1e-9) {
        bestK = k;
      }
    }
    if (!Number.isFinite(bestTrough)) continue;
    const fMin = bestK + (nCeil >> 1);

    // Exclude comma/phrase pauses (> 80 ms contiguous silence around trough); cap silThr below active /s/ level
    const silThr = Math.min(0.15 * prePk, 0.45 * Math.max(sibPk, 0.008));
    let qL = fMin, qR = fMin;
    while (qL > 0 && fRms[qL - 1] < silThr) qL--;
    while (qR < nF - 1 && fRms[qR + 1] < silThr) qR++;
    const silDurMs = fRms[fMin] < silThr ? (qR - qL + 1) * stepMs : 0.0;
    if (silDurMs > 80.0) continue;

    // Burst release peak: scan from right edge of closure (qR) into burst/sibilant onset (immune to noisy -55 dB floors)
    const relStart = fRms[fMin] < silThr ? qR : fMin;
    const bEnd = Math.min(nF - 1, Math.max(fSib + 4, relStart + 4), relStart + 14);
    let bPk = 0.0;
    for (let k = relStart; k <= bEnd; k++) {
      if (fRms[k] > bPk) bPk = fRms[k];
    }
    const jump = Math.max(0.0, Math.min(60.0, 20.0 * Math.log10((bPk + 1e-6) / (bestTrough + 1e-6))));
    if (jump < 10.0) continue; // reject vowel-to-fricative crossfades without true stop burst release

    const depth = Math.max(0.0, Math.min(60.0, 20.0 * Math.log10((prePk + 1e-6) / (bestTrough + 1e-6))));
    if (depth > maxDepth) maxDepth = depth;
    if (jump > maxBurstJump) maxBurstJump = jump;
  }

  d._consAudit = {
    vsibCoexistPct,
    vsibCentroidHz,
    vsibFrames,
    sibFrames,
    affrDepth: Number(maxDepth.toFixed(1)),
    affrBurstJump: Number(maxBurstJump.toFixed(1)),
  };
  return d._consAudit;
}

function getFormants4(d) {
  if (d._formants4) return d._formants4;
  const df = d.freqs.length > 1 ? (d.freqs[1] - d.freqs[0]) : (d.sr / d.nfft);
  const nBins = d.nBins;
  const hw = Math.max(3, Math.round(360.0 / Math.max(1.0, df)));
  const tilt = new Float64Array(nBins);
  for (let b = 0; b < nBins; b++) {
    tilt[b] = 4.0 * Math.log2(Math.max(100.0, d.freqs[b]) / 500.0);
  }
  const eTilt = new Float64Array(nBins);
  const eRes = new Float64Array(nBins);
  const ps = new Float64Array(nBins + 1);
  const f1s = [], f2s = [], f3s = [], f4s = [], margins = [];
  let nVo = 0;

  const refine = (arr, b) => {
    const yL = arr[b - 1], y0 = arr[b], yR = arr[b + 1];
    const denom = yL - 2.0 * y0 + yR;
    const delta = Math.abs(denom) > 1e-9
      ? Math.max(-0.5, Math.min(0.5, (0.5 * (yL - yR)) / denom))
      : 0.0;
    return d.freqs[b] + delta * df;
  };

  for (let t = 0; t < d.nFrames; t++) {
    const e = d.envDb[t];
    const f0 = d.f0Hz[t];
    if (!e || f0 <= 0) continue;
    nVo++;

    ps[0] = 0.0;
    for (let b = 0; b < nBins; b++) {
      ps[b + 1] = ps[b] + e[b];
      eTilt[b] = e[b] + tilt[b];
    }
    // Symmetric local-baseline subtraction cancels arbitrary linear spectral tilt (0 to -30 dB/oct) without peak shift
    for (let b = 0; b < nBins; b++) {
      const w = Math.min(hw, b, nBins - 1 - b);
      const base = w > 0 ? (ps[b + w + 1] - ps[b - w]) / (2 * w + 1) : e[b];
      eRes[b] = e[b] - base;
    }

    const rawPks = [];
    const tiltPks = [];
    const resPks = [];
    for (let b = 1; b < nBins - 1; b++) {
      const f = d.freqs[b];
      if (f < 240.0 || f > 6000.0) continue;
      if (e[b] > e[b - 1] && e[b] >= e[b + 1]) {
        rawPks.push({ f: refine(e, b), vRaw: e[b], vTilt: eTilt[b], vRes: eRes[b] });
      }
      if (eTilt[b] > eTilt[b - 1] && eTilt[b] >= eTilt[b + 1]) {
        tiltPks.push({ f: refine(eTilt, b), vRaw: e[b], vTilt: eTilt[b], vRes: eRes[b] });
      }
      if (b >= 2 && b < nBins - 2 && eRes[b] > eRes[b - 1] && eRes[b] >= eRes[b + 1] && eRes[b] > 0.22) {
        resPks.push({ f: refine(eRes, b), vRaw: e[b], vTilt: eTilt[b], vRes: eRes[b] });
      }
    }

    // 1. F1: pick strongest RAW cepstral peak in [240, 1200] Hz (never erased or upward-biased by tilt)
    let p1 = null;
    for (const p of rawPks) {
      if (p.f >= 240.0 && p.f <= 1200.0 && (!p1 || p.vRaw > p1.vRaw)) p1 = p;
    }
    if (!p1) {
      for (const p of resPks) {
        if (p.f >= 240.0 && p.f <= 1200.0 && (!p1 || p.vRaw > p1.vRaw)) p1 = p;
      }
    }
    if (!p1) continue;
    f1s.push(p1.f);
    margins.push(p1.f - f0);

    // Filter deep noise-floor ripples (> 58 dB below F1) from high-band candidates
    const minHiDb = p1.vRaw - 58.0;
    const hiPks = resPks.filter((p) => p.vRaw >= minHiDb);

    // Guard against F3 hijacking F2: any candidate > 2300 Hz MUST have two genuine formants (F3 <= 4000, F4) above it
    const hasF3F4Above = (fCand) => {
      const f3Min = Math.max(fCand + 350.0, 2200.0);
      for (let i = 0; i < hiPks.length; i++) {
        const q3 = hiPks[i];
        if (q3.f < f3Min || q3.f > 4000.0 || q3.vRes < 0.25) continue;
        const f4Min = Math.max(q3.f + 350.0, 3400.0);
        for (let j = i + 1; j < hiPks.length; j++) {
          const q4 = hiPks[j];
          if (q4.f >= f4Min && q4.f <= 5800.0 && q4.vRes >= 0.25) return true;
        }
      }
      return false;
    };

    // 2. F2: prominent raw (vRes >= 0.70) -> tilt-cancelled eRes shoulder -> raw fallback -> capped mild eTilt
    // Prefer primary-band [f2Lo, 2300 Hz] candidates over > 2300 Hz so 5-formant F3 cannot hijack F2 via (F4, F5)
    const f2Lo = Math.max(p1.f + 280.0, 850.0);
    const hasPrimaryF2 =
      rawPks.some((p) => p.f >= f2Lo && p.f <= 2300.0 && p.vRaw >= p1.vRaw - 30.0 && p.vRes >= 0.35) ||
      hiPks.some((p) => p.f >= f2Lo && p.f <= 2300.0 && p.vRes >= 0.40);
    const validF2 = (p) => {
      if (p.f < f2Lo || p.f > 2850.0) return false;
      if (p.f > 2300.0) return !hasPrimaryF2 && p.vRes >= 0.25 && hasF3F4Above(p.f);
      return true;
    };

    let p2 = null;
    for (const p of rawPks) {
      if (validF2(p) && p.vRes >= 0.70 && (!p2 || p.vRaw > p2.vRaw)) p2 = p;
    }
    if (!p2) {
      for (const p of hiPks) {
        if (validF2(p) && p.vRes >= 0.30 && (!p2 || p.vRes > p2.vRes)) p2 = p;
      }
    }
    if (!p2) {
      for (const p of rawPks) {
        if (validF2(p) && (!p2 || p.vRaw > p2.vRaw)) p2 = p;
      }
    }
    if (!p2) {
      for (const p of tiltPks) {
        if (p.f >= f2Lo && p.f <= 2300.0 && p.vRaw >= p1.vRaw - 20.0 && (!p2 || p.vTilt > p2.vTilt)) p2 = p;
      }
    }
    if (p2) f2s.push(p2.f);

    // 3. Paired (F3, F4) on eRes — decoupled from !p2 and strictly paired on the same frame
    const f3Lo = p2 ? Math.max(p2.f + 350.0, 2200.0) : 2300.0;
    const c3 = hiPks.filter((p) => p.f >= f3Lo && p.f <= 4000.0);
    const c4All = hiPks.filter((p) => p.f >= 3400.0 && p.f <= 5800.0);

    let bestP3 = null, bestP4 = null, bestScore = -Infinity;
    for (const q3 of c3) {
      // F5 guard: penalize skipping a prominent peak (true F3 below q3, or true F4 between q3 and q4)
      const skippedF3 = c3.some((pre) => pre.f >= f3Lo && pre.f <= q3.f - 350.0 && pre.vRes >= Math.max(0.45, q3.vRes * 0.30));
      const f4Lo = Math.max(q3.f + 350.0, 3400.0);
      for (const q4 of c4All) {
        if (q4.f < f4Lo) continue;
        const skippedF4 = c4All.some((mid) => mid.f >= f4Lo && mid.f <= q4.f - 350.0 && mid.vRes >= Math.max(0.45, q4.vRes * 0.30));
        const sc = q3.vRes + q4.vRes - (skippedF3 ? 12.0 : 0.0) - (skippedF4 ? 12.0 : 0.0);
        if (sc > bestScore) {
          bestScore = sc;
          bestP3 = q3;
          bestP4 = q4;
        }
      }
    }
    if (bestP3 && bestP4) {
      f3s.push(bestP3.f);
      f4s.push(bestP4.f);
    }
  }

  // Reject edge-transient F2 ghosts (< 15% of voiced frames on utterances with >= 8 voiced frames)
  const minF2Fr = nVo >= 8 ? Math.ceil(0.15 * nVo) : 1;
  d._formants4 = {
    f1: median(f1s),
    f2: f2s.length >= minF2Fr ? median(f2s) : 0.0,
    f3: median(f3s),
    f4: median(f4s),
    margin: Number(median(margins).toFixed(1)),
    nVo,
  };
  return d._formants4;
}

function tailRqaLamSlice(norm, off, tau, step, M) {
  const pts = new Array(M);
  for (let m = 0; m < M; m++) {
    const idx = off + m * step;
    pts[m] = [norm[idx], norm[idx + tau], norm[idx + 2 * tau]];
  }
  const dists = [];
  const D = new Float64Array(M * M);
  let maxDist = 0.0;
  for (let i = 0; i < M; i++) {
    const pi = pts[i];
    for (let j = i + 1; j < M; j++) {
      const pj = pts[j];
      const dist = Math.hypot(pi[0] - pj[0], pi[1] - pj[1], pi[2] - pj[2]);
      D[i * M + j] = D[j * M + i] = dist;
      dists.push(dist);
      if (dist > maxDist) maxDist = dist;
    }
  }
  if (maxDist < 1e-9) return 0.0;
  const eps = percentile(dists, 15) || 1e-6;
  const R = new Uint8Array(M * M);
  let recTot = 0;
  for (let i = 0; i < M * M; i++) {
    if (D[i] <= eps) { R[i] = 1; recTot++; }
  }
  let lamPts = 0;
  for (let j = 0; j < M; j++) {
    let run = 0;
    for (let i = 0; i < M; i++) {
      if (R[i * M + j]) run++;
      else { if (run >= 2) lamPts += run; run = 0; }
    }
    if (run >= 2) lamPts += run;
  }
  return (100.0 * lamPts) / (recTot || 1);
}

function getHopfTailAudit(d) {
  if (d._hopfTail) return d._hopfTail;
  const voMask = new Uint8Array(d.nFrames);
  for (let t = 0; t < d.nFrames; t++) voMask[t] = d.f0Hz[t] > 0 ? 1 : 0;
  // Bridge 1-frame autocorrelation dropouts
  for (let t = 1; t < d.nFrames - 1; t++) {
    if (!voMask[t] && voMask[t - 1] && voMask[t + 1]) voMask[t] = 1;
  }
  const islands = [];
  let idx = 0;
  while (idx < d.nFrames) {
    while (idx < d.nFrames && !voMask[idx]) idx++;
    const a = idx;
    while (idx < d.nFrames && voMask[idx]) idx++;
    if (idx > a) islands.push([a, idx - 1]);
  }
  const minLong = Math.round((0.200 * d.sr) / d.hop);
  const minShort = Math.round((0.080 * d.sr) / d.hop);
  const longIslands = islands.filter(([a, b]) => b - a + 1 >= minLong);
  const useIslands = longIslands.length ? longIslands : islands.filter(([a, b]) => b - a + 1 >= minShort);
  if (!useIslands.length) {
    d._hopfTail = { tailLam: 0.0, hopf: 0.0 };
    return d._hopfTail;
  }

  const lamVals = [];
  const hopfVals = [];
  const rWin = Math.max(4, Math.round(0.008 * d.sr));
  const rHalf = rWin >> 1;

  for (const [a, b] of useIslands) {
    const f0s = [];
    for (let t = a; t <= b; t++) if (d.f0Hz[t] > 0) f0s.push(d.f0Hz[t]);
    const medF0 = median(f0s) || 300.0;

    let bExt = b;
    const bExtMax = Math.min(d.nFrames - 1, b + 6);
    while (bExt < bExtMax && d.rmsFr[bExt + 1] > 0.015) bExt++;

    // #146: T0/24-oversampled + 8ms local-RMS normalized tail RQA LAM
    const sEnd = Math.min(d.x.length, bExt * d.hop + d.wl);
    const sStart = Math.max(a * d.hop, sEnd - Math.round(0.120 * d.sr));
    const tailLen = sEnd - sStart;
    const f0Safe = medF0 > 50.0 ? medF0 : 300.0;
    const tau = Math.max(2, Math.round(d.sr / (f0Safe * 4.0)));
    const step = Math.max(1, Math.round(d.sr / (f0Safe * 24.0)));
    const M = 96;
    const span = (M - 1) * step + 2 * tau + 1;

    if (tailLen >= span) {
      const ps = new Float64Array(tailLen + 1);
      for (let i = 0; i < tailLen; i++) {
        const v = d.x[sStart + i];
        ps[i + 1] = ps[i] + v * v;
      }
      const norm = new Float64Array(tailLen);
      for (let i = 0; i < tailLen; i++) {
        const lo = Math.max(0, i - rHalf);
        const hi = Math.min(tailLen, i + rHalf + 1);
        const localRms = Math.sqrt((ps[hi] - ps[lo]) / Math.max(1, hi - lo));
        norm[i] = d.x[sStart + i] / (localRms + 1e-4);
      }
      const winStart = Math.max(0, tailLen - Math.round(0.085 * d.sr));
      const maxOff = tailLen - span;
      const offs = [];
      if (maxOff <= winStart) {
        offs.push(maxOff);
      } else if (maxOff - winStart < 8) {
        offs.push(winStart, maxOff);
      } else {
        offs.push(winStart, Math.floor(0.5 * (winStart + maxOff)), maxOff);
      }
      const sliceLams = [];
      for (const off of offs) sliceLams.push(tailRqaLamSlice(norm, off, tau, step, M));
      lamVals.push(median(sliceLams));
    }

    // #147: Hopf dissolution score (HNR decay + high-band SFM rise + smooth envelope)
    const tSplit = Math.max(a + 2, b - Math.min(24, Math.floor(0.45 * (b - a))));
    const coreHnr = [], tailHnr = [], coreSfm = [], tailSfm = [];
    for (let t = a; t < tSplit; t++) {
      const h = frameBandHnr(d, t, 200.0, 3500.0);
      if (h !== null) coreHnr.push(h);
      coreSfm.push(frameSfm(d.freqs, d.mag[t], 3000.0, 7500.0));
    }
    for (let t = tSplit; t <= b; t++) {
      const h = frameBandHnr(d, t, 200.0, 3500.0);
      if (h !== null) tailHnr.push(h);
    }
    let bSfmEnd = b;
    const bSfmMax = Math.min(d.nFrames - 1, b + 4);
    while (bSfmEnd < bSfmMax && d.rmsFr[bSfmEnd + 1] > 0.008) bSfmEnd++;
    for (let t = tSplit; t <= bSfmEnd; t++) {
      tailSfm.push(frameSfm(d.freqs, d.mag[t], 3000.0, 7500.0));
    }

    let maxDrop = 0.0;
    for (let t = Math.max(a + 1, tSplit); t <= bExt; t++) {
      if (d.rmsFr[t - 1] > 0.025) {
        const drop = 20.0 * Math.log10((d.rmsFr[t - 1] + 1e-6) / (d.rmsFr[t] + 1e-6));
        if (drop > maxDrop) maxDrop = drop;
      }
    }
    const hnrDecay = (coreHnr.length && tailHnr.length) ? (median(coreHnr) - median(tailHnr)) : 0.0;
    const sfmRise = (coreSfm.length && tailSfm.length) ? (median(tailSfm) - median(coreSfm)) : 0.0;
    const cHnr = clamp01((hnrDecay - 0.5) / 10.0);
    const cSfm = clamp01((sfmRise - 0.01) / 0.25);
    const cSmooth = 1.0 - clamp01((maxDrop - 5.0) / 12.0);
    hopfVals.push((0.50 * cHnr + 0.50 * cSfm) * (0.35 + 0.65 * cSmooth));
  }

  d._hopfTail = {
    tailLam: Number(median(lamVals).toFixed(1)),
    hopf: Number(median(hopfVals).toFixed(3)),
  };
  return d._hopfTail;
}

function getF0PinkBeta(d) {
  if (typeof d._f0PinkBeta === "number") return d._f0PinkBeta;
  const fps = d.sr / d.hop;
  const chunks = [];
  let t = 0;
  while (t < d.nFrames) {
    while (t < d.nFrames && d.f0Hz[t] <= 0) t++;
    const a = t;
    while (t < d.nFrames && d.f0Hz[t] > 0) t++;
    const segLen = t - a;
    if (segLen < 24) continue;
    const st = new Float64Array(segLen);
    for (let i = 0; i < segLen; i++) st[i] = 12.0 * Math.log2(d.f0Hz[a + i] / 220.0);
    if (segLen <= 220) {
      chunks.push(st);
    } else {
      let s = 0;
      for (; s + 200 <= segLen; s += 100) chunks.push(st.subarray(s, s + 200));
      if (s < segLen && segLen - s >= 24 && (segLen - 200) > (s - 100)) {
        chunks.push(st.subarray(segLen - 200, segLen));
      }
    }
  }
  if (!chunks.length) {
    d._f0PinkBeta = 0.0;
    return 0.0;
  }

  const nGrid = 16;
  const fGrid = new Float64Array(nGrid);
  for (let j = 0; j < nGrid; j++) {
    fGrid[j] = 1.5 * Math.pow(15.0 / 1.5, j / (nGrid - 1));
  }
  const pAcc = new Float64Array(nGrid);
  const wAcc = new Float64Array(nGrid);

  for (const y of chunks) {
    const L = y.length;
    const mX = 0.5 * (L - 1);
    let mY = 0.0;
    for (let i = 0; i < L; i++) mY += y[i];
    mY /= L;
    let sNum = 0.0, sDen = 0.0;
    for (let i = 0; i < L; i++) {
      const dx = i - mX;
      sNum += dx * (y[i] - mY);
      sDen += dx * dx;
    }
    const slope = sNum / (sDen || 1.0);
    const res = new Float64Array(L);
    let sq = 0.0;
    for (let i = 0; i < L; i++) {
      const r = y[i] - (mY + slope * (i - mX));
      res[i] = r;
      sq += r * r;
    }
    const resRms = Math.sqrt(sq / L);
    if (resRms < 0.015) continue; // skip constant F0 chunks

    const wRes = new Float64Array(L);
    let wSq = 0.0;
    for (let i = 0; i < L; i++) {
      const w = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * i) / (L - 1));
      wRes[i] = res[i] * w;
      wSq += w * w;
    }
    const durS = L / fps;
    const fMin = Math.max(1.5, 1.5 / durS);
    for (let j = 0; j < nGrid; j++) {
      const f = fGrid[j];
      if (f < fMin) continue;
      let re = 0.0, im = 0.0;
      const stepAng = (2.0 * Math.PI * f) / fps;
      for (let i = 0; i < L; i++) {
        const ang = stepAng * i;
        re += wRes[i] * Math.cos(ang);
        im -= wRes[i] * Math.sin(ang);
      }
      const P = (re * re + im * im) / (wSq * fps + 1e-18);
      pAcc[j] += L * P;
      wAcc[j] += L;
    }
  }

  const xs = [], ys = [];
  for (let j = 0; j < nGrid; j++) {
    if (wAcc[j] > 0.0 && pAcc[j] > 0.0) {
      xs.push(Math.log10(fGrid[j]));
      ys.push(Math.log10(pAcc[j] / wAcc[j]));
    }
  }
  if (xs.length < 4) {
    d._f0PinkBeta = 0.0;
    return 0.0;
  }
  let mX = 0.0, mY = 0.0;
  for (let i = 0; i < xs.length; i++) { mX += xs[i]; mY += ys[i]; }
  mX /= xs.length; mY /= xs.length;
  let cov = 0.0, varX = 0.0;
  for (let i = 0; i < xs.length; i++) {
    const dx = xs[i] - mX;
    cov += dx * (ys[i] - mY);
    varX += dx * dx;
  }
  const beta = varX > 1e-12 ? Math.max(-1.0, Math.min(3.5, -cov / varX)) : 0.0;
  d._f0PinkBeta = Number(beta.toFixed(2));
  return d._f0PinkBeta;
}

export function getAuditPrimitives(d) {
  if (d._audit) return d._audit;
  const cj = getCliffJerk(d);
  const ons = getOnsetAudit(d);
  const cons = getConsonantAudit(d);
  d._audit = {
    cliffAll: cj.cliffAll,
    maxJump: cj.maxJump,
    c2Jerk: cj.c2Jerk,
    medD2: cj.medD2,
    csMed: cj.csMed,
    csP90: cj.csP90,
    hasVoiced: cj.hasVoiced,
    postPauseRiseMs: ons.riseMs,
    onsetToeRatio: ons.toe,
    nOnsets: ons.nOnsets,
    vsibCoexistPct: cons.vsibCoexistPct,
    vsibCentroidHz: cons.vsibCentroidHz,
    vsibFrames: cons.vsibFrames,
    sibFrames: cons.sibFrames,
    affrClosureDepthDb: cons.affrDepth,
    affrBurstJumpDb: cons.affrBurstJump,
  };
  return d._audit;
}

export const CAT13_TOOLS = [
  {
    id: 131, key: "pl_erb_rough_med", name: "[監査] Plomp-Levelt ERB感覚粗さ (中央値)", unit: "idx",
    run: (d) => getPlompLeveltErb(d).med,
  },
  {
    id: 132, key: "pl_erb_rough_p90", name: "[監査] Plomp-Levelt ERB感覚粗さ (p90局所ピーク)", unit: "idx",
    run: (d) => getPlompLeveltErb(d).p90,
  },
  {
    id: 133, key: "erb_mod_rough", name: "[監査] 18ch ERBフィルタバンク時間変調粗さ", unit: "idx",
    run: (d) => getPlompLeveltErb(d).mod,
  },
  {
    id: 134, key: "cliff_all_ratio", name: "[監査] 全サンプル崖/クリック比 (有声+無声+境界 p99.99)", unit: "ratio",
    run: (d) => getCliffJerk(d).cliffAll,
  },
  {
    id: 135, key: "max_sample_jump", name: "[監査] 最大サンプル跳躍比 (max|Δx|/RMS)", unit: "ratio",
    run: (d) => getCliffJerk(d).maxJump,
  },
  {
    id: 136, key: "c2_jerk_p999", name: "[監査] C2躍度ジャーク比 (3階微分p99.9/中央値)", unit: "ratio",
    run: (d) => getCliffJerk(d).c2Jerk,
  },
  {
    id: 137, key: "post_pause_rise_ms", name: "[監査] 句読点後・裸母音立上がり時間 (最悪値)", unit: "ms",
    run: (d) => getOnsetAudit(d).riseMs,
  },
  {
    id: 138, key: "onset_toe_ratio", name: "[監査] 立上がり凹みトー比 (t50-t10)/(t85-t10)", unit: "ratio",
    run: (d) => getOnsetAudit(d).toe,
  },
  {
    id: 139, key: "vsib_coexist_pct", name: "[監査] 有声歯擦音(ざじずぜぞ) 声帯+摩擦共存率", unit: "%",
    run: (d) => getConsonantAudit(d).vsibCoexistPct,
  },
  {
    id: 140, key: "vsib_centroid_hz", name: "[監査] 有声歯擦音 摩擦スペクトル重心 (2-8kHz)", unit: "Hz",
    run: (d) => getConsonantAudit(d).vsibCentroidHz,
  },
  {
    id: 141, key: "affr_closure_depth_db", name: "[監査] 破擦音(つ/ち) 閉鎖谷深さ", unit: "dB",
    run: (d) => getConsonantAudit(d).affrDepth,
  },
  {
    id: 142, key: "affr_burst_jump_db", name: "[監査] 破擦音(つ/ち) 破裂バースト跳躍", unit: "dB",
    run: (d) => getConsonantAudit(d).affrBurstJump,
  },
  {
    id: 143, key: "f4_median_hz", name: "[物理1] 第4フォルマント F4 中央値 (笑顔キラ帯)", unit: "Hz",
    run: (d) => Math.round(getFormants4(d).f4),
  },
  {
    id: 144, key: "f3f4_bright_lift_hz", name: "[物理1] vs基準 F3/F4平均ブライト上昇量", unit: "Hz",
    run(d, ctx) {
      if (!ctx?.ref || ctx.ref === d) return 0.0;
      const cur = getFormants4(d);
      const ref = getFormants4(ctx.ref);
      if (!cur.f3 || !cur.f4 || !ref.f3 || !ref.f4) return 0.0;
      return Number((0.5 * ((cur.f3 - ref.f3) + (cur.f4 - ref.f4))).toFixed(1));
    },
  },
  {
    id: 145, key: "f1f2_drift_pct", name: "[物理1] vs基準 F1/F2母音直交ドリフト率", unit: "%",
    run(d, ctx) {
      if (!ctx?.ref || ctx.ref === d) return 0.0;
      const cur = getFormants4(d);
      const ref = getFormants4(ctx.ref);
      if (!cur.f1 || !ref.f1) return 0.0;
      const drift = (cur.f2 && ref.f2)
        ? 50.0 * (
            Math.abs(cur.f1 - ref.f1) / Math.max(100.0, ref.f1) +
            Math.abs(cur.f2 - ref.f2) / Math.max(200.0, ref.f2)
          )
        : 100.0 * (Math.abs(cur.f1 - ref.f1) / Math.max(100.0, ref.f1));
      return Number(drift.toFixed(2));
    },
  },
  {
    id: 146, key: "tail_rqa_lam_pct", name: "[物理2] 語尾120ms RQAラミナリティ (機械停滞率)", unit: "%",
    run: (d) => getHopfTailAudit(d).tailLam,
  },
  {
    id: 147, key: "tail_hopf_dissolve", name: "[物理2] 語尾ホップ分岐・有機吐息溶解度", unit: "0..1",
    run: (d) => getHopfTailAudit(d).hopf,
  },
  {
    id: 148, key: "f0_pink_beta", name: "[物理4] F0微細ゆらぎ 1/f^β スペクトル勾配", unit: "beta",
    run: (d) => getF0PinkBeta(d),
  },
  {
    id: 149, key: "f1_f0_margin_hz", name: "[物理5] 高音F1-F0調律マージン (F1 - F0)", unit: "Hz",
    run: (d) => getFormants4(d).margin,
  },
  {
    id: 150, key: "intelligibility_guard_100", name: "[監査総合] 聞き取り安全ガードスコア (0-100)", unit: "pts",
    run(d, ctx) {
      let maxRms = 0.0;
      for (let t = 0; t < d.nFrames; t++) if (d.rmsFr[t] > maxRms) maxRms = d.rmsFr[t];
      if (d.x.length < 32 || maxRms < 0.005) return 0.0;
      const m = ctx?.metrics || {};
      const pl = getPlompLeveltErb(d);
      const cj = getCliffJerk(d);
      const ons = getOnsetAudit(d);
      const cons = getConsonantAudit(d);
      const f4 = getFormants4(d);
      let pen = 0.0;
      pen += 18.0 * clamp01((cj.cliffAll - 50.0) / 45.0);
      pen += 14.0 * clamp01((cj.maxJump - 5.5) / 3.0);
      pen += 16.0 * clamp01((pl.p90 - 13.0) / 12.0);
      pen += 6.0  * clamp01((pl.mod - 18.0) / 15.0);
      if (ons.nOnsets > 0) {
        const pToe  = ons.riseMs >= 16.0 ? clamp01((ons.toe - 0.56) / 0.22) : 0.0;
        const pSlow = clamp01((ons.riseMs - 38.0) / 25.0);
        pen += 14.0 * pToe + 6.0 * pSlow;
      }
      if (cons.vsibFrames >= 3) pen += 14.0 * clamp01((2900.0 - cons.vsibCentroidHz) / 700.0);
      if (f4.nVo >= 8 && (m.f0_mean_hz ?? 0) > 350.0) pen += 12.0 * clamp01((40.0 - f4.margin) / 100.0);
      if (cj.hasVoiced) pen += 14.0 * clamp01(((m.fixed_whistle_db ?? 0) - 6.0) / 4.0);
      return Number(Math.max(0.0, Math.min(100.0, 100.0 - pen)).toFixed(1));
    },
  },
];
