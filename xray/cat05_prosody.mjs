// xray/cat05_prosody.mjs — 変態解析ツール #41〜#50: ピッチ・カワイイ抑揚 (Pitch & Kawaii Prosody)
import { median, percentile } from "./core.mjs";

function voicedSt(d) {
  const st = [];
  const tSec = [];
  for (let t = 0; t < d.nFrames; t++) {
    if (d.f0Hz[t] > 0) {
      st.push(12.0 * Math.log2(d.f0Hz[t] / 220.0));
      tSec.push((t * d.hop) / d.sr);
    }
  }
  return { st, tSec };
}

function stdOf(vals) {
  if (vals.length < 2) return 0.0;
  let m = 0.0;
  for (let i = 0; i < vals.length; i++) m += vals[i];
  m /= vals.length;
  let v = 0.0;
  for (let i = 0; i < vals.length; i++) { const x = vals[i] - m; v += x * x; }
  return Math.sqrt(v / vals.length);
}

export const CAT05_TOOLS = [
  {
    id: 41, key: "f0_mean_hz", name: "平均ピッチ F0 (有声部)", unit: "Hz",
    run(d) {
      let s = 0.0, n = 0;
      for (let t = 0; t < d.nFrames; t++) if (d.f0Hz[t] > 0) { s += d.f0Hz[t]; n++; }
      return n ? Number((s / n).toFixed(1)) : 0.0;
    },
  },
  {
    id: 42, key: "f0_range_st", name: "ピッチ躍動レンジ (p95-p05)", unit: "st",
    run(d) {
      const { st } = voicedSt(d);
      if (st.length < 4) return 0.0;
      return Number((percentile(st, 95) - percentile(st, 5)).toFixed(2));
    },
  },
  {
    id: 43, key: "tail_lift_st", name: "末尾ピッチ上昇 tail_lift (後半20% - 前半80%)", unit: "st",
    run(d) {
      const { st } = voicedSt(d);
      if (st.length < 4) return 0.0;
      const tailLen = Math.max(2, Math.floor(st.length / 5));
      let mHead = 0.0, mTail = 0.0;
      for (let i = 0; i < st.length - tailLen; i++) mHead += st[i];
      for (let i = st.length - tailLen; i < st.length; i++) mTail += st[i];
      return Number((mTail / tailLen - mHead / (st.length - tailLen)).toFixed(3));
    },
  },
  {
    id: 44, key: "f0_jitter_st", name: "ピッチ微細揺らぎ f0_jitter (std Δst)", unit: "st",
    run(d) {
      const { st } = voicedSt(d);
      if (st.length < 4) return 0.0;
      const diffs = [];
      for (let i = 1; i < st.length; i++) diffs.push(st[i] - st[i - 1]);
      return Number(stdOf(diffs).toFixed(3));
    },
  },
  {
    id: 45, key: "final_scoop_st", name: "句末100ms語尾スクープ検知", unit: "st",
    run(d) {
      const scoops = [];
      const dt = d.hop / d.sr;
      const scFr = Math.max(4, Math.round(0.10 / dt));
      for (let t = scFr; t < d.nFrames; t++) {
        // Detect end of a voiced island (voiced now, unvoiced for next >=4 frames or end)
        if (d.f0Hz[t] > 0) {
          let isEnd = t === d.nFrames - 1;
          if (!isEnd) {
            let unv = 0;
            for (let k = 1; k <= 5 && t + k < d.nFrames; k++) if (d.f0Hz[t + k] === 0) unv++;
            if (unv >= 4) isEnd = true;
          }
          if (isEnd && d.f0Hz[t - scFr] > 0) {
            const stEnd = 12.0 * Math.log2(d.f0Hz[t] / d.f0Hz[t - scFr]);
            scoops.push(stEnd);
          }
        }
      }
      return Number(median(scoops).toFixed(2));
    },
  },
  {
    id: 46, key: "declination_st_s", name: "文全体のピッチ下降/上昇勾配", unit: "st/s",
    run(d) {
      const { st, tSec } = voicedSt(d);
      if (st.length < 4) return 0.0;
      const mT = tSec.reduce((a, b) => a + b, 0) / tSec.length;
      const mY = st.reduce((a, b) => a + b, 0) / st.length;
      let cov = 0.0, vT = 0.0;
      for (let i = 0; i < st.length; i++) {
        cov += (tSec[i] - mT) * (st[i] - mY);
        vT += (tSec[i] - mT) * (tSec[i] - mT);
      }
      return Number((cov / (vT || 1.0)).toFixed(2));
    },
  },
  {
    id: 47, key: "pitch_vel_st_s", name: "ピッチ躍動速度 (median |dF0/dt|)", unit: "st/s",
    run(d) {
      const dt = d.hop / d.sr;
      const vels = [];
      for (let t = 1; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0 && d.f0Hz[t - 1] > 0) {
          vels.push(Math.abs(12.0 * Math.log2(d.f0Hz[t] / d.f0Hz[t - 1])) / dt);
        }
      }
      return Number(median(vels).toFixed(1));
    },
  },
  {
    id: 48, key: "micro_vib_4_7hz", name: "4-7Hz 微ビブラート強度 (語尾の有機揺れ)", unit: "st",
    run(d) {
      const dt = d.hop / d.sr;
      // Extract contiguous voiced segments >= 24 frames (120ms) and measure 4-7Hz DFT energy
      let best = 0.0;
      let seg = [];
      const evalSeg = (s) => {
        if (s.length < 24) return;
        const m = s.reduce((a, b) => a + b, 0) / s.length;
        for (const f of [4.5, 5.2, 6.0, 6.8]) {
          let cr = 0.0, ci = 0.0;
          for (let i = 0; i < s.length; i++) {
            const ang = 2.0 * Math.PI * f * i * dt;
            cr += (s[i] - m) * Math.cos(ang);
            ci += (s[i] - m) * Math.sin(ang);
          }
          const amp = (2.0 * Math.hypot(cr, ci)) / s.length;
          if (amp > best) best = amp;
        }
      };
      for (let t = 0; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0) seg.push(12.0 * Math.log2(d.f0Hz[t] / 220.0));
        else { evalSeg(seg); seg = []; }
      }
      evalSeg(seg);
      return Number(best.toFixed(3));
    },
  },
  {
    id: 49, key: "falsetto_flip_cnt", name: "裏返り/急跳躍カウンタ (>3.5st/10ms)", unit: "cnt",
    run(d) {
      let cnt = 0;
      for (let t = 2; t < d.nFrames; t++) {
        if (d.f0Hz[t] > 0 && d.f0Hz[t - 2] > 0) {
          const jump = 12.0 * Math.log2(d.f0Hz[t] / d.f0Hz[t - 2]);
          if (jump > 3.5 && jump < 14.0) cnt++;
        }
      }
      return cnt;
    },
  },
  {
    id: 50, key: "smile_pulse_6_8hz", name: "6-8Hz 笑顔/笑い脈動エネルギー", unit: "dB-mod",
    run(d) {
      const dt = d.hop / d.sr;
      const env = [];
      for (let t = 0; t < d.nFrames; t++) env.push(20.0 * Math.log10(d.rmsFr[t] + 1e-6));
      const m = env.reduce((a, b) => a + b, 0) / (env.length || 1);
      let acc = 0.0;
      for (const f of [6.0, 6.7, 7.3, 8.0]) {
        let cr = 0.0, ci = 0.0;
        for (let i = 0; i < env.length; i++) {
          const ang = 2.0 * Math.PI * f * i * dt;
          cr += (env[i] - m) * Math.cos(ang);
          ci += (env[i] - m) * Math.sin(ang);
        }
        acc += (2.0 * Math.hypot(cr, ci)) / (env.length || 1);
      }
      return Number((acc / 4.0).toFixed(2));
    },
  },
];
