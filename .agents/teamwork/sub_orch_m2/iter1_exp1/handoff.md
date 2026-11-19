# M2 Research Handoff — Explorer 1: Tier 1 Fast Kotoba Formant-Track Synthesizer & Built-in Corpus

## 1. Key Findings from Codebase Inspection

### 1.1 `kotoba.py` API, Tracks, Units, and Edge Cases
- **Entry point**: `kotoba.tracks_from_kana(text=None, moras=None, pre=0.1, post=0.1, timing='rule', n=None, params=None) -> dict`
- **Frame step**: `fp_ms = 5.0` ms (`kotoba.FP = 5.0`), corresponding to `hop = 80` samples at `sr = 16000` Hz.
- **Returned dictionary keys & units**:
  - `fp_ms`: `5.0` (float, ms per frame).
  - `n`: `int`, total number of 5 ms frames (total duration `n * 0.005` s).
  - `F1`, `F2`, `F3`: `list[float]` of length `n`, formant center frequencies in **Hz** (already scaled by `kotoba.DEF['alpha'] = 1.15` and `alpha3 = 1.3`).
  - `G1`, `G2`, `G3`: `list[float]` of length `n`, per-formant linear gain multipliers in `[0.05, ~1.0]` (encodes nasal anti-formants `G2=0.15`, `h/f` attenuation `G1=0.4`, voiced stop closure `(0.8, 0.05, 0.05)`, fricative vowel suppression `0.15`/`0.45`).
  - `dl`: `list[float]` of length `n`, consonant cue loudness delta in **dB** (e.g., `-6` dB during stop closure / `Q`, `-1.2` dB nasals, `-1.5` dB tap `r`).
  - `loud`: `list[float]` of length `n`, relative loudness envelope in **dB**, normalized so `max(loud) == 0.0` (silence floor `sil = -30.0` dB, `Q` closure `-18.0` dB).
  - `f0`: `list[float]` of length `n`, fundamental frequency in **Hz** (`0.0` during unvoiced frames; declination around `P['f0'] = 220.0` Hz during voiced frames).
  - `voiced`: `list[bool]` of length `n`, voicing mask (`True` on voiced frames, `False` on voiceless consonants / devocalized `i,u` / `Q` / `pau`).
  - `bands`: `list[tuple[float, float, float, float, float]]` of `(t_start_sec, t_end_sec, center_hz, sd_hz, gain)` for fricatives (`s/z/ts` ~6000 Hz, `sh/j/ch` ~3600 Hz), `hi` (3500 Hz), and stop bursts (`k/g` 3000/1900 Hz, `t/d/ch/ts` 4500 Hz, `p/b` 1200 Hz).
  - `moras`: `list[dict]` with keys `('t', 'kind', 'c', 'v', 'a', 'b', 'e')` where `a` = mora start (sec), `b` = vowel onset (sec), `e` = mora end (sec).
- **Critical `rate` convention in `kotoba.py` and `yomu.py`**:
  - In `kotoba.py` line 147 (`c = CDUR * rate`, `v = VDUR * rate`) and `yomu.py` line 274 (`--rate: 小さいほど速い`), `rate` is a **duration multiplier** (`rate > 1.0` = slower/longer duration; `rate < 1.0` = faster/shorter duration).
  - Note that `kotoba.rule_durations()` does **not** multiply `pau`, `qn` (for `ッ`/`ン`), or `devmax` by `P['rate']` automatically. Therefore, `synthesize_fast_kotoba` should pass:
    ```python
    params = {
        "rate": rate,
        "pau": kotoba.DEF["pau"] * rate,
        "qn": kotoba.DEF["qn"] * rate,
        "devmax": kotoba.DEF["devmax"] * rate,
        "f0": kotoba.DEF["f0"] * f0_scale,
    }
    ```
    so that **all** mora types (`CV`, `Q`, `N`, `pau`) and their `{"t", "a", "e"}` boundaries scale proportionally with `rate`!
- **Critical `kotoba.tracks_from_kana()` crash edge cases (empirically verified)**:
  1. Empty string `""`, whitespace-only `"   "`, or punctuation-only `"、、、"` -> `split_moras()` returns `[]` -> `kotoba.tracks_from_kana()` raises `IndexError: list index out of range`!
  2. Sokuon-only strings like `"ッ"` or `"ッッ"` -> `build_tracks()` appends nothing to `kp` -> raises `IndexError: list index out of range`!
  - **Required handling in `synthesize_fast_kotoba`**:
    - Validate numeric parameters (`sr > 0`, `f0_scale > 0`, `fscale > 0`, `rate > 0`, finite `snr_db` if provided; raise `ValueError` on invalid inputs).
    - Check `ms = kotoba.split_moras(text)`. If `not ms`, return `(np.zeros(0, dtype=np.float32), [])` cleanly.
    - If all moras in `ms` are in `{"ッ", "、"}` (no CV, `ン`, or `ー`), return a short silence buffer of appropriate duration (e.g., `int(round((0.2 + len(ms) * kotoba.DEF["qn"] * rate) * sr))` zeros) and synthetic mora timing dicts `[{"t": m, "a": ..., "e": ...}]` instead of crashing.
    - Hiragana vs Katakana: `kotoba.split_moras()` calls `kotoba.to_kata()`, so Hiragana and Katakana inputs produce identical tracks and katakana mora labels `t`.

### 1.2 Compatibility with M1 Interfaces (`asr/audio.py`, `asr/features.py`, `asr/tokenizer.py`)
- **`asr.audio.detect_vad(wav, sr=16000, threshold_db=-35.0)`**:
  - `kotoba.py` sets silence `loud = -30.0` dB. If converted naively via `10 ** (-30 / 20) = 0.0316` and normalized to peak `0.85`, silence would sit at `-31.4` dB > `-35.0` dB, causing VAD to classify silence padding as speech!
  - **Fix**: Apply a smooth silence gate `sil_gate = np.clip((loud - (-28.0)) / 5.0, 0.0, 1.0)` multiplied into `10 ** ((loud + dl) / 20.0)` so pre/post silence and pauses drop cleanly below `-60` dB. Verified: `detect_vad` cleanly finds speech `[0.10, 0.34]` on single vowels with `pre=0.1, post=0.1`.
- **`asr.audio.apply_corruption`**:
  - When `snr_db is not None`, delegate additive noise directly to `asr.audio.apply_corruption(wav, sr, snr_db=snr_db, noise_type="white", seed=noise_seed)` (derived deterministically from `rng`), then soft-normalize/clip to `[-1.0, 1.0]` so the return contract `float32 in [-1.0, 1.0]` always holds.
- **`asr.tokenizer.Tokenizer(mode="kana")`**:
  - Vocab contains: `<blank>` (0), 71 full-size Katakana from `kotoba.K2V`, `ン`, `ッ`, `ー`, 8 small kana (`ャュョァィゥェォ`), and `、`, `。`, ` `.
  - All built-in corpus texts MUST use only these characters (specifically Katakana + `ンッー` + small kana + optional internal `、`, no trailing `、`, no `。`, no ASCII/kanji) so `tokenizer.decode(tokenizer.encode(text)) == text` is 100% lossless.

---

## 2. Concrete Design: `synthesize_fast_kotoba`

### 2.1 Signature
```python
def synthesize_fast_kotoba(
    text: str,
    *,
    sr: int = 16000,
    f0_scale: float = 1.0,
    fscale: float = 1.0,
    rate: float = 1.0,
    snr_db: float | None = None,
    seed: int | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
```
- **Returns**: `(wav_float32, moras)`
  - `wav_float32`: 1D `np.ndarray` of dtype `np.float32`, values strictly in `[-1.0, 1.0]`, finite (no NaN/Inf).
  - `moras`: `list[dict]` where each item is `{"t": str, "a": float, "e": float}` (exact mora boundaries in seconds from `kotoba.tracks_from_kana`).

### 2.2 Vectorized Frame-Domain Overlap-Add Formant Synthesis Algorithm (Zero Python Sample Loops)
Empirically benchmarked on this 2-core CPU: **100 diverse 16 kHz utterances in 0.63 s (~6.3 ms/utt)** — nearly 8x faster than the 5 s target.

1. **Track Extraction**:
   - Call `tr = kotoba.tracks_from_kana(text, params=params)` where `params` scales `rate`, `pau`, `qn`, `devmax`, and `f0` by `f0_scale`.
   - `n = tr["n"]`, `fp_s = tr["fp_ms"] / 1000.0` (`0.005` s).
   - `hop = max(1, int(round(sr * fp_s)))` (`80` samples at 16 kHz).
   - `win_len = 2 * hop` (`160` samples = 10 ms; exact 50% overlap Hann window sums to `1.0` everywhere!).
   - `n_fft = max(256, 1 << (win_len - 1).bit_length())` (`256` at 16 kHz -> 129 bins, `df = 62.5` Hz).
   - `n_samples = (n + 1) * hop`.
2. **Sample-Level Phase-Continuous Glottal + Noise Excitation**:
   - Frame centers `t_fr = np.arange(n) * hop + 0.5 * hop`, sample indices `t_s = np.arange(n_samples)`.
   - Interpolate `f0` smoothly across unvoiced regions (using valid `f0 > 0` frames, fallback `kotoba.DEF["f0"] * f0_scale`) to get `f0_s` (length `n_samples`).
   - Interpolate `voiced` (`float64` in `[0, 1]`) to `vo_s`.
   - Integrate instantaneous phase: `phase = np.cumsum(2.0 * np.pi * f0_s / sr)` and `p_mod = np.mod(phase, 2.0 * np.pi)`.
   - **Alias-free sharp glottal pulse**:
     - Pulse angular width `sigma_s = np.maximum(0.08, 1.2 * (2.0 * np.pi * f0_s / sr))` (always >= 1.2 samples wide -> zero aliasing at any `f0` or `sr`, while retaining strong harmonic energy through F2/F3 up to ~4.5 kHz!).
     - `pulse = np.exp(-0.5 * ((p_mod - np.pi) / sigma_s) ** 2)`
     - First-order lip radiation derivative: `glottal[1:] = pulse[1:] - 0.95 * pulse[:-1]`, normalized by `std(glottal) + 1e-8`.
   - Generate unit-variance white noise `noise = rng.standard_normal(n_samples)`.
   - Mix excitation: `exc = vo_s * (glottal + 0.04 * noise) + (1.0 - vo_s) * (0.25 * noise)`.
3. **Batch Vectorized Formant Filtering (Parallel Lorentzian Resonators)**:
   - Frame `exc` with `np.lib.stride_tricks.sliding_window_view(exc, win_len)[::hop][:n]`, multiply by periodic Hann window `win`, and compute `E = np.fft.rfft(frames * win, n=n_fft, axis=1)` of shape `(n, n_fft // 2 + 1)`.
   - Clamp scaled formants safely below Nyquist:
     - `F1 = np.clip(F1_raw * fscale, 80.0, 0.45 * sr)`
     - `F2 = np.clip(F2_raw * fscale, 150.0, 0.45 * sr)`
     - `F3 = np.clip(F3_raw * fscale, 300.0, 0.47 * sr)`
   - Realistic Klatt-like formant bandwidths:
     - `B1 = 70.0 + 0.05 * F1`, `B2 = 100.0 + 0.06 * F2`, `B3 = 140.0 + 0.06 * F3`.
   - Parallel Lorentzian vocal-tract transfer function `H` of shape `(n, K)`:
     $$H(t, f) = \sum_{k=1}^{3} \frac{w_k \cdot G_k(t)}{\sqrt{\left(\frac{f - F_k(t)}{B_k(t)/2}\right)^2 + 1}}$$
     with weights `(w1, w2, w3) = (1.0, 0.85, 0.55)`.
   - `Y = E * H`.
4. **Fricative & Stop-Burst Consonant Noise Bands**:
   - If `tr["bands"]` is non-empty, compute `N_spec = np.fft.rfft(noise_frames * win, n=n_fft, axis=1)`.
   - For each `(t0, t1, cen, sd, gain)` in `tr["bands"]`:
     - Frame range `[i0, i1)` from `round(t0 / fp_s)` to `round(t1 / fp_s)`.
     - `c_hz = min(cen * fscale, 0.47 * sr)`, `s_hz = max(100.0, sd * fscale)`.
     - `band_h = (0.12 * gain) * np.exp(-0.5 * ((freqs - c_hz) / s_hz) ** 2)`.
     - `Y[i0:i1] += N_spec[i0:i1] * band_h`.
5. **Zero-Loop Overlap-Add & Loudness Shaping**:
   - `y_frames = np.fft.irfft(Y, n=n_fft, axis=1)[:, :win_len]`.
   - Because `win_len = 2 * hop` and periodic Hann sums to exact `1.0` at 50% overlap:
     - `even = y_frames[0::2].ravel(); wav[:even.size] += even`
     - `odd = y_frames[1::2].ravel(); wav[hop:hop + odd.size] += odd`
   - Loudness envelope with smooth silence gating:
     - `sil_gate = np.clip((loud - (-28.0)) / 5.0, 0.0, 1.0)`
     - `env_fr = sil_gate * (10.0 ** ((loud + dl) / 20.0))`
     - `env_s = np.interp(t_s, t_fr, env_fr)`; `wav *= env_s`.
   - Peak-normalize to `0.85` (if `max(|wav|) > 1e-8`), cast to `np.float32`.
6. **Optional SNR Corruption**:
   - If `snr_db is not None`: call `apply_corruption(wav, sr, snr_db=snr_db, noise_type="white", seed=int(rng.integers(0, 2**31)))` and clip/scale if `max(|wav|) > 1.0` so output remains in `[-1.0, 1.0]`.

### 2.3 Empirical Phonetic Quality Verification
Verified with `AudioConfig(cmvn=False)` Log-Mel peak extraction on `/a/, /i/, /u/, /e/, /o/`:
- `ア`: peaks at ~1529–1755 Hz (F2) and ~3652 Hz (F3)
- `イ`: peaks at ~3183 Hz (F2) and ~4190 Hz (F3)
- `ウ`: peaks at ~1755–1923 Hz (F2) and ~3488 Hz (F3)
- `エ`: peaks at ~657 Hz (F1), ~2650 Hz (F2), ~3823 Hz (F3)
- `オ`: peaks at ~657 Hz (F1), ~1060 Hz (F2), ~3652 Hz (F3)

---

## 3. Built-in Diverse Japanese Kana Corpus Design

Define three module-level constants in `asr/synth_data.py`:
- `TRAIN_CORPUS: tuple[str, ...]` — **~120 unique Katakana utterances** spanning 5 categories:
  1. **Greetings & Conversational Phrases** (~24): `オハヨウゴザイマス`, `コンニチハ`, `コンバンハ`, `アリガトウゴザイマス`, `ワタシ、ニホンゴ、チョットシャベレマス`, `キョウモイッショニガンバロウネ`, `オツカレサマデシタ`, `ヨロシクオネガイシマス`, `スミマセン`, `ゴメンナサイ`, `ダイジョウブデス`, `マタアシタ`, `オヤスミナサイ`, `イッテラッシャイ`, `タダイマ`, `オカエリナサイ`, `イタダキマス`, `ゴチソウサマ`, `ゲンキデスカ`, `トテモタノシイデス`, `ヨクデキマシタ`, `モウイチドオネガイシマス`, `ハジメマシテ`, `サヨウナラ`.
  2. **Voice Commands & Playground Actions** (~24): `オンガクヲサイセイシテ`, `ボリュームヲアゲテ`, `ボリュームヲサゲテ`, `ストップ`, `スタート`, `ツギノキョク`, `マエノキョク`, `タイマーヲセット`, `テンキヲオシエテ`, `ライトヲツケテ`, `ライトヲケシテ`, `アラームヲトメテ`, `ロクオンヲカイシ`, `ロクオンヲテイシ`, `キャンセル`, `モドル`, `ススム`, `カクダイ`, `シュクショウ`, `ホゾンシテ`, `ケンサクシテ`, `オンセイヲニュウリョク`, `スピードヲハヤク`, `ノイズヲフヤシテ`.
  3. **Digits, Numbers & Time** (~20): `ゼロ`, `イチ、ニ、サン`, `ヨン、ゴ、ロク`, `ナナ、ハチ、キュウ、ジュウ`, `ヒャク`, `セン`, `イチマン`, `サンジハン`, `ゴフンマエ`, `ジュウニガツ`, `イッカイ`, `ニカイ`, `サンカイ`, `ゴジュウ`, `ハチジュウ`, `キュウジュウキュウ`, `イッポン`, `ニホン`, `サンボン`, `ゼロテンゴ`.
  4. **Everyday Words, Nature, Food & Tech** (~34): `サクラ`, `ツキナミ`, `タイヨウ`, `アメ`, `カゼ`, `ヤマ`, `ウミ`, `ソラ`, `ホシ`, `ネコ`, `イヌ`, `トリ`, `ラーメン`, `スシ`, `コーヒー`, `オチャ`, `パン`, `リンゴ`, `ミカン`, `トウキョウ`, `オオサカ`, `キョウト`, `ホッカイドウ`, `デンシャ`, `ヒコウキ`, `コンピュータ`, `プログラム`, `オンセイニンシキ`, `ロボット`, `ギター`, `ピアノ`, `カメラ`, `テレビ`, `ラジオ`.
  5. **Phonetically Balanced / Special Mora Sentences** (~18): covering `パピプペポ`, `バビブベボ`, `ザジズゼゾ`, `ダヂヅデド`, `ガギグゲゴ`, `キャキュキョ`, `シャシュショ`, `チャチュチョ`, `ニャニュニョ`, `ヒャヒュヒョ`, `ミャミュミョ`, `リャリュリョ`, `ギャギュギョ`, `ジャジュジョ`, `ビャビュビョ`, `ピャピュピョ`, `ファフィフェフォ`, `ヴァヴィヴヴェヴォ` (or `ヴ`), `ッ`, `ン`, `ー`.
- `VAL_CORPUS: tuple[str, ...]` — **~30 unique Katakana utterances** strictly disjoint from `TRAIN_CORPUS` (`set(TRAIN_CORPUS).isdisjoint(VAL_CORPUS)`), covering greetings, commands, digits, words, and special moras, with **100% character subset** of `TRAIN_CORPUS` (every character in `VAL_CORPUS` appears in `TRAIN_CORPUS`).
- `BUILTIN_CORPUS: tuple[str, ...] = TRAIN_CORPUS + VAL_CORPUS` (~150 unique utterances).

### Validation Invariants for Corpus
1. Every entry `s` in `BUILTIN_CORPUS` satisfies `Tokenizer(mode="kana").decode(Tokenizer(mode="kana").encode(s)) == s` (lossless round-trip).
2. Every entry `s` has `len(kotoba.split_moras(s)) >= 1` and synthesizes without error via `synthesize_fast_kotoba(s)`.
3. `set(TRAIN_CORPUS).isdisjoint(set(VAL_CORPUS))` (genuine train/val text generalization split).
4. Every character occurring in `VAL_CORPUS` also occurs in `TRAIN_CORPUS`.

---

## 4. Verification Criteria for Unit Tests (`tests/test_asr_data.py`)
1. **Phonetic distinctiveness**: Log-Mel spectrograms of synthesized `/a/`, `/i/`, `/u/`, `/e/`, `/o/` have low pairwise cosine similarity / distinct spectral centroids & formant peaks; fricative `サ`/`シ` has significantly higher high-frequency (>3 kHz) energy ratio than nasal `マ`/`ナ` or vowel `ア`.
2. **Parameter effects**:
   - `f0_scale`: `f0_scale=1.5` produces higher fundamental frequency than `f0_scale=0.7`.
   - `fscale`: `fscale=1.25` shifts spectral centroid upward relative to `fscale=0.8`.
   - `rate`: `rate=1.5` produces longer audio and proportionally scaled mora durations `m["e"] - m["a"]` than `rate=0.75`.
   - `snr_db`: lower `snr_db` (e.g. `5.0`) increases noise floor in pre/post silence regions relative to clean (`snr_db=None`).
   - `seed`: identical `seed` produces bit-exact waveforms; different seeds produce different noise realizations.
3. **Edge cases**: `""`, `"   "`, `"、、、"`, `"ッ"`, `"ン"`, `"ー"`, `"ラーメン"`, `"キット"`, Hiragana vs Katakana (`"わたし"` vs `"ワタシ"` produce identical output with same seed), invalid params (`sr <= 0`, `rate <= 0`, `f0_scale <= 0`, `fscale <= 0`) raise `ValueError`.
4. **Performance**: Synthesizing 100 diverse 16 kHz utterances completes in `< 5.0` seconds (target `< 1.5` s).
5. **Corpus invariants**: `BUILTIN_CORPUS` >= 100 unique texts, lossless `Tokenizer("kana")` round-trip, disjoint `TRAIN_CORPUS` / `VAL_CORPUS`, valid `kotoba` tracks.
