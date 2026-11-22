// xray/core.mjs — カワイイクサナギ変態音響X線スイート 共通コア（純JS・外部依存ゼロ・Node/ブラウザ共通）
import { fftRadix2 } from "../hitofude.mjs";

export function decodeWav(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let off = 12, sr = 44100, ch = 1, bits = 16, dataOff = 44, dataLen = bytes.byteLength - 44;
  while (off + 8 <= bytes.byteLength) {
    const id = String.fromCharCode(view.getUint8(off), view.getUint8(off + 1), view.getUint8(off + 2), view.getUint8(off + 3));
    const sz = view.getUint32(off + 4, true);
    if (id === "fmt ") {
      ch = view.getUint16(off + 10, true);
      sr = view.getUint32(off + 12, true);
      bits = view.getUint16(off + 22, true);
    } else if (id === "data") {
      dataOff = off + 8;
      dataLen = Math.min(sz, bytes.byteLength - dataOff);
      break;
    }
    off += 8 + sz + (sz & 1);
  }
  const bytesPerSample = Math.max(1, bits >> 3);
  const nFrames = Math.floor(dataLen / (bytesPerSample * ch));
  const x = new Float64Array(nFrames);
  for (let i = 0; i < nFrames; i++) {
    let sum = 0.0;
    for (let c = 0; c < ch; c++) {
      const p = dataOff + (i * ch + c) * bytesPerSample;
      if (bits === 16) sum += view.getInt16(p, true) / 32768.0;
      else if (bits === 32) sum += view.getFloat32(p, true);
      else sum += (view.getUint8(p) - 128) / 128.0;
    }
    x[i] = sum / ch;
  }
  return { sr, samples: x };
}

export function trimAndNormalize(sr, raw) {
  const N = raw.length;
  const win = Math.max(1, Math.trunc(0.02 * sr));
  const env = new Float64Array(N);
  let acc = 0.0, pk = 0.0;
  for (let i = 0; i < N; i++) {
    acc += raw[i] * raw[i];
    if (i >= win) acc -= raw[i - win] * raw[i - win];
    const v = acc / Math.min(i + 1, win);
    env[i] = v;
    if (v > pk) pk = v;
  }
  const thr = (pk + 1e-12) * 1e-4;
  let a = 0, b = N;
  while (a < N && env[a] <= thr) a++;
  while (b > a && env[b - 1] <= thr) b--;
  a = Math.max(0, a - Math.trunc(0.03 * sr));
  b = Math.min(N, b + Math.trunc(0.03 * sr));
  const sub = raw.subarray(a, b);
  let sq = 0.0;
  for (let i = 0; i < sub.length; i++) sq += sub[i] * sub[i];
  const rms = Math.sqrt(sq / (sub.length || 1)) || 1.0;
  const out = new Float64Array(sub.length);
  const g = 0.15 / rms;
  for (let i = 0; i < sub.length; i++) out[i] = sub[i] * g;
  return out;
}

export function median(arr) {
  if (!arr.length) return 0.0;
  const s = Float64Array.from(arr).sort();
  const m = s.length >> 1;
  return (s.length & 1) ? s[m] : 0.5 * (s[m - 1] + s[m]);
}

export function percentile(arr, p) {
  if (!arr.length) return 0.0;
  const s = Float64Array.from(arr).sort();
  const idx = Math.min(s.length - 1, Math.max(0, Math.floor((p / 100.0) * (s.length - 1))));
  return s[idx];
}

export function extractBaseFrameData(sr, rawSamples, fmax = 8000.0) {
  const x = trimAndNormalize(sr, rawSamples);
  const nfft = sr > 30000 ? 2048 : 1024;
  const wl = Math.trunc(0.026 * sr);
  const hop = Math.trunc(0.005 * sr);
  const win = new Float64Array(wl);
  let winSum = 0.0;
  for (let i = 0; i < wl; i++) {
    win[i] = 0.5 - 0.5 * Math.cos((2.0 * Math.PI * i) / (wl - 1));
    winSum += win[i];
  }
  const half = (nfft >> 1) + 1;
  const freqs = new Float64Array(half);
  let nBins = 0;
  for (let k = 0; k < half; k++) {
    freqs[k] = (k * sr) / nfft;
    if (freqs[k] <= fmax) nBins = k + 1;
  }
  const nFrames = Math.max(1, Math.floor((x.length - wl) / hop) + 1);
  const mag = new Array(nFrames);
  const magDb = new Array(nFrames);
  const envDb = new Array(nFrames); // ケプストラム包絡（F0倍音シマを除去した純粋な声道伝達特性）
  const phase = new Array(nFrames);
  const rmsFr = new Float64Array(nFrames);
  const f0Hz = new Float64Array(nFrames); // 0 = unvoiced
  const minLag = Math.max(2, Math.trunc(sr / 580));
  const maxLag = Math.min(wl - 2, Math.trunc(sr / 140));
  const buf = new Float64Array(nfft);
  const logFull = new Float64Array(nfft);
  const qCut = Math.max(8, Math.trunc(0.0017 * sr)); // 1.7ms リフタ（女性/アニメ高音F0を綺麗に除去）
  const invScale = 2.0 / (winSum || 1.0);

  for (let t = 0; t < nFrames; t++) {
    const off = t * hop;
    buf.fill(0.0);
    let sq = 0.0;
    for (let i = 0; i < wl; i++) {
      const v = x[off + i] * win[i];
      buf[i] = v;
      sq += v * v;
    }
    const rms = Math.sqrt(sq / wl);
    rmsFr[t] = rms;
    const { re, im } = fftRadix2(buf);
    const m = new Float64Array(nBins);
    const md = new Float64Array(nBins);
    const ph = new Float64Array(nBins);
    logFull.fill(0.0);
    for (let k = 0; k < half; k++) {
      const mv = Math.hypot(re[k], im[k]) * invScale + 1e-9;
      const db = 20.0 * Math.log10(mv);
      logFull[k] = db;
      if (k > 0 && k < nfft - k) logFull[nfft - k] = db;
      if (k < nBins) {
        m[k] = mv;
        md[k] = db;
        ph[k] = Math.atan2(im[k], re[k]);
      }
    }
    mag[t] = m;
    magDb[t] = md;
    phase[t] = ph;

    // Autocorrelation F0 (voiced frames)
    if (rms > 0.025) {
      let r0 = 0.0;
      for (let i = 0; i < wl; i++) r0 += buf[i] * buf[i];
      let bestLag = 0, bestVal = 0.0;
      const acVals = new Float64Array(maxLag + 2);
      for (let lag = minLag; lag <= maxLag; lag++) {
        let s = 0.0;
        for (let i = 0; i < wl - lag; i++) s += buf[i] * buf[i + lag];
        const v = s / (r0 + 1e-12);
        acVals[lag] = v;
        if (v > bestVal) { bestVal = v; bestLag = lag; }
      }
      if (bestVal > 0.48 && bestLag > 0) {
        let fracLag = bestLag;
        if (bestLag > minLag && bestLag < maxLag) {
          const yL = acVals[bestLag - 1], y0 = acVals[bestLag], yR = acVals[bestLag + 1];
          const denom = yL - 2.0 * y0 + yR;
          if (Math.abs(denom) > 1e-9) fracLag += Math.max(-0.5, Math.min(0.5, 0.5 * (yL - yR) / denom));
        }
        f0Hz[t] = sr / fracLag;
        // Cepstral liftering for clean vocal-tract envelope
        const { re: ceps } = fftRadix2(logFull);
        const lif = new Float64Array(nfft);
        lif[0] = ceps[0] / nfft;
        for (let q = 1; q < qCut; q++) {
          const w = 0.5 + 0.5 * Math.cos((Math.PI * q) / qCut);
          lif[q] = (ceps[q] / nfft) * w;
          lif[nfft - q] = (ceps[nfft - q] / nfft) * w;
        }
        const { re: envFull } = fftRadix2(lif);
        envDb[t] = Float64Array.from(envFull.subarray(0, nBins));
      }
    }
  }

  return { sr, x, nfft, wl, hop, freqs: freqs.subarray(0, nBins), nBins, nFrames, mag, magDb, envDb, phase, rmsFr, f0Hz };
}
