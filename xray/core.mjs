// xray/core.mjs — カワイイクサナギ変態音響X線スイート 共通コア（純JS・外部依存ゼロ・Node/ブラウザ共通）

const FFT_CACHE = new Map();

export function fftRadix2(reIn) {
  const n = reIn.length;
  if (n <= 0) return { re: new Float64Array(0), im: new Float64Array(0) };
  let plan = FFT_CACHE.get(n);
  if (!plan) {
    const bits = Math.round(Math.log2(n));
    const bitrev = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      let x = i, r = 0;
      for (let b = 0; b < bits; b++) { r = (r << 1) | (x & 1); x >>= 1; }
      bitrev[i] = r;
    }
    const twRe = [], twIm = [], steps = [];
    for (let step = 2; step <= n; step <<= 1) {
      const half = step >> 1;
      const cRe = new Float64Array(half), cIm = new Float64Array(half);
      for (let k = 0; k < half; k++) {
        const ang = (-2.0 * Math.PI * k) / step;
        cRe[k] = Math.cos(ang);
        cIm[k] = Math.sin(ang);
      }
      steps.push(step);
      twRe.push(cRe);
      twIm.push(cIm);
    }
    plan = { bitrev, steps, twRe, twIm };
    FFT_CACHE.set(n, plan);
  }
  const re = new Float64Array(n), im = new Float64Array(n);
  for (let i = 0; i < n; i++) re[i] = reIn[plan.bitrev[i]];
  for (let si = 0; si < plan.steps.length; si++) {
    const step = plan.steps[si], half = step >> 1;
    const cRe = plan.twRe[si], cIm = plan.twIm[si];
    for (let s = 0; s < n; s += step) {
      for (let k = 0; k < half; k++) {
        const i1 = s + k, i2 = i1 + half;
        const vr = re[i2] * cRe[k] - im[i2] * cIm[k];
        const vi = re[i2] * cIm[k] + im[i2] * cRe[k];
        re[i2] = re[i1] - vr; im[i2] = im[i1] - vi;
        re[i1] += vr; im[i1] += vi;
      }
    }
  }
  return { re, im };
}

export function decodeWav(bytes) {
  if (!(bytes instanceof Uint8Array)) {
    throw new TypeError("Invalid WAV input: expected Uint8Array");
  }
  if (bytes.byteLength < 44) {
    throw new Error(`Invalid WAV: buffer too short (${bytes.byteLength} bytes, minimum 44)`);
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const readFourCC = (o) => String.fromCharCode(
    view.getUint8(o), view.getUint8(o + 1), view.getUint8(o + 2), view.getUint8(o + 3)
  );
  if (readFourCC(0) !== "RIFF" || readFourCC(8) !== "WAVE") {
    throw new Error("Invalid WAV header: missing RIFF/WAVE magic");
  }

  let off = 12;
  let hasFmt = false;
  let hasData = false;
  let audioFmt = 0;
  let sr = 0;
  let ch = 0;
  let bits = 0;
  let dataOff = 0;
  let dataLen = 0;

  while (off + 8 <= bytes.byteLength) {
    const id = readFourCC(off);
    const sz = view.getUint32(off + 4, true);
    const bodyOff = off + 8;
    if (id === "fmt ") {
      if (sz < 16 || bodyOff + 16 > bytes.byteLength) {
        throw new Error(`Invalid WAV: truncated 'fmt ' chunk (size=${sz})`);
      }
      audioFmt = view.getUint16(bodyOff, true);
      ch = view.getUint16(bodyOff + 2, true);
      sr = view.getUint32(bodyOff + 4, true);
      bits = view.getUint16(bodyOff + 14, true);
      if (audioFmt === 0xFFFE) {
        // WAVE_FORMAT_EXTENSIBLE: resolve PCM(1) / IEEE_FLOAT(3) if standard KSDATAFORMAT_SUBTYPE GUID tail matches
        if (sz < 40 || bodyOff + 40 > bytes.byteLength) {
          throw new Error(`Invalid WAV: truncated WAVE_FORMAT_EXTENSIBLE 'fmt ' chunk (size=${sz})`);
        }
        const guidTailOk =
          view.getUint16(bodyOff + 26, true) === 0x0000 &&
          view.getUint16(bodyOff + 28, true) === 0x0000 &&
          view.getUint16(bodyOff + 30, true) === 0x0010 &&
          view.getUint8(bodyOff + 32) === 0x80 && view.getUint8(bodyOff + 33) === 0x00 &&
          view.getUint8(bodyOff + 34) === 0x00 && view.getUint8(bodyOff + 35) === 0xAA &&
          view.getUint8(bodyOff + 36) === 0x00 && view.getUint8(bodyOff + 37) === 0x38 &&
          view.getUint8(bodyOff + 38) === 0x9B && view.getUint8(bodyOff + 39) === 0x71;
        if (!guidTailOk) {
          throw new Error("Unsupported WAV format: non-standard WAVE_FORMAT_EXTENSIBLE SubFormat GUID");
        }
        audioFmt = view.getUint16(bodyOff + 24, true);
      }
      hasFmt = true;
      if (hasData) break;
    } else if (id === "data") {
      dataOff = bodyOff;
      dataLen = Math.min(sz, bytes.byteLength - dataOff);
      hasData = true;
      if (hasFmt) break;
    }
    off += 8 + sz + (sz & 1);
  }

  if (!hasFmt) throw new Error("Invalid WAV: missing 'fmt ' chunk");
  if (!hasData) throw new Error("Invalid WAV: missing 'data' chunk");
  if (!Number.isInteger(sr) || sr <= 0 || sr > 384000) {
    throw new Error(`Invalid WAV sample rate: ${sr} Hz (expected 1..384000)`);
  }
  if (!Number.isInteger(ch) || ch <= 0 || ch > 16) {
    throw new Error(`Invalid WAV channel count: ${ch} (expected 1..16)`);
  }
  const isPcm = audioFmt === 1 && (bits === 8 || bits === 16 || bits === 24 || bits === 32);
  const isFloat = audioFmt === 3 && (bits === 32 || bits === 64);
  if (!isPcm && !isFloat) {
    throw new Error(`Unsupported WAV format: audioFormat=${audioFmt}, bitsPerSample=${bits}`);
  }

  const bytesPerSample = bits >> 3;
  const frameStride = bytesPerSample * ch;
  const nFrames = Math.floor(dataLen / frameStride);
  const x = new Float64Array(nFrames);
  for (let i = 0; i < nFrames; i++) {
    let sum = 0.0;
    for (let c = 0; c < ch; c++) {
      const p = dataOff + i * frameStride + c * bytesPerSample;
      if (audioFmt === 3) {
        const v = bits === 64 ? view.getFloat64(p, true) : view.getFloat32(p, true);
        if (!Number.isFinite(v)) {
          throw new Error(`Invalid WAV: non-finite IEEE float sample at frame ${i}`);
        }
        sum += v;
      } else if (bits === 16) {
        sum += view.getInt16(p, true) / 32768.0;
      } else if (bits === 24) {
        sum += ((view.getInt8(p + 2) << 16) | (view.getUint8(p + 1) << 8) | view.getUint8(p)) / 8388608.0;
      } else if (bits === 32) {
        sum += view.getInt32(p, true) / 2147483648.0;
      } else {
        sum += (view.getUint8(p) - 128) / 128.0;
      }
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

export function pctlInterp(arr, p) {
  if (!arr.length) return 0.0;
  const s = Float64Array.from(arr).sort();
  const pos = Math.min(s.length - 1, Math.max(0, (p / 100.0) * (s.length - 1)));
  const lo = Math.floor(pos);
  const hi = Math.min(s.length - 1, Math.ceil(pos));
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

export function extractBaseFrameData(sr, rawSamples, fmax = 8000.0) {
  let x = trimAndNormalize(sr, rawSamples);
  const wl = Math.max(4, Math.trunc(0.026 * sr));
  let nfft = sr > 30000 ? 2048 : 1024;
  while (nfft < wl) nfft <<= 1;
  const hop = Math.max(1, Math.trunc(0.005 * sr));
  if (x.length < wl) {
    const pad = new Float64Array(wl);
    pad.set(x);
    x = pad;
  }
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
  const lif = new Float64Array(nfft);
  const qCutMax = Math.max(8, Math.min((nfft >> 1) - 1, Math.trunc(0.0021 * sr))); // 2.1ms リフタ上限（高音F0は動的に0.82*T0へクランプ）
  const invScale = 2.0 / (winSum || 1.0);

  for (let t = 0; t < nFrames; t++) {
    const off = t * hop;
    buf.fill(0.0);
    let sq = 0.0;
    for (let i = 0; i < wl; i++) {
      const v = (off + i < x.length ? x[off + i] : 0.0) * win[i];
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
        // Adaptive cepstral liftering: stays bit-identical to 2.1ms for f0 <= 390Hz,
        // and clamps below 0.82 * T0 on high-F0 speech (400-580Hz) to block F0 ripple leakage.
        const qCut = Math.max(8, Math.min(qCutMax, Math.floor((0.82 * sr) / f0Hz[t])));
        const { re: ceps } = fftRadix2(logFull);
        lif.fill(0.0);
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
