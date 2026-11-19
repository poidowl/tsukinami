# tsukinami (`kusanagi` branch — Pure JavaScript Edition)

> **約67KBのピュアJavaScript（`.py` ゼロ）で、1本のホワイトノイズから4手で日本語かな・歌を彫る。ブラウザでも Node.js でもそのまま鳴り、LLMの1コンテキストで丸ごと読める。**  
> 外部パッケージ不要・外部データファイル不要・Python互換ギプスなし・本体2ファイル計 1,683行（67.0 KB）。

`hitofude`（一筆彫り）から Python 依存と互換用の乱数・丸めギプスをすべて外し、純粋な ES Module 2本（エンジン [`hitofude.mjs`](hitofude.mjs) ＋ CLI [`yomu.mjs`](yomu.mjs)）にまとめた「草薙（kusanagi）」ブランチです。

## 1. コンテキスト投入コマンド ＆ Raw URL（全コード一括）

本体の実装は以下の2ファイルだけで完結しています（`README.md` 込み合計 約73 KB）：

```bash
cat README.md hitofude.mjs yomu.mjs
```

Web取得型LLMには、以下の **Raw プレーンテキスト URL 3本**を渡してください：
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/README.md
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/hitofude.mjs
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/yomu.mjs

| ファイル | 行数 | 役割 |
| :--- | ---: | :--- |
| [`hitofude.mjs`](hitofude.mjs) | 1,452行 | **純JS音源・声道・調音・韻律エンジン（`import` ゼロ）**：かな→5ms軌道 `tracksFromKana`、東京式アクセント `f0Rule`、4手引き算合成 `makeHitofude`、WAV出力 `encodeWav`、FFT音響計測 `hakaru`（ブラウザ `<script type="module">` と Node.js 両対応） |
| [`yomu.mjs`](yomu.mjs) | 231行 | **Node.js CLI & レシピドライバ**：プリセット合成、`--measure` 自己計測、`--compare` 音響指標差分、`--uta` 歌唱（既定出力は上書きしない連番 `out/yomu_NNN_<preset>.wav`） |
| [`tools/build_x_player.mjs`](tools/build_x_player.mjs) | 補助 | [`hitofude.mjs`](hitofude.mjs) から X Player Card / GitHub Pages 用の単一HTML（`hitofude.html` + `hitofude_player.html`）を直接生成 |

---

## 2. 信号処理の構造（1本のノイズ信号線 × 4回の引き算）

正弦波オシレータ（`sin/cos` 音源）、固定波形の粒スタンプ、STFT往復、40段オールパス、帯域別 AGC はすべて廃止しています。**音になる信号線は最初から最後まで 1本のホワイトノイズ `x` だけ**を直列に通します（※ピッチの自然漂い・周期ジッタ・歌唱ビブラートという周波数制御側のみ別シード乱数を使用）。

```text
x = rng.uniform(-1, +1) × N   # [-1, +1] の一様ホワイトノイズ（音になる原石は1本だけ）
  │
  ▼ 【引き算① 倍音の谷】 combPeriod(x, PER, GS) × 2段
  │    ・有声区間 (G > 0): 周期 PER と食い違う倍音間の谷を削る（谷深さ ≒ 40*log10((1+G)/(1-G)) dB）
  │    ・無声子音 (G = 0): 同じノイズ線 x がそのまま素通しになる
  │    ・句末吐息 (sigh > 0): 句末母音の後半で G を緩めるだけで、外部ノイズを足さずに声が元の吐息へほどけて戻る
  │
  ▼ 【引き算② 低域濁りと高域の角】 karuku(x) → arakezuriT(x, tilt_w, 2, cons_sharp)
  │    ・f0 未満の低域ドリフトを除去し、移動平均幅 tilt_w で声色の明るさ（スペクトル傾斜）を決める
  │    ・破裂・摩擦子音区間 (cons_sharp = 1) だけ高域の角を削り残す
  │
  ▼ 【引き算③ 受動声道共鳴】 yamaBp(x, F1..F4) + yamaBp(x, f_cons_cen)
  │    ・帯域ごとの自動利得制御 (AGC) は 0回（声道フィルタの自然な振幅応答をそのまま残す）
  │
  ▼ 【引き算④ 1スカラー整音＋時間包絡】 y[i] * gLv[i] * env[i]
       ・母音定常部のみ全周波数に同じ1スカラー gLv[i] を掛けて音節間の音量暴れを整える（瞬間スペクトル傾斜変化 0.00 dB）
```

---

## 3. パラメータと物理・聴覚対応表（LLM改造ガイド）

帯域別 AGC が無いため各ノブは他の段で打ち消されず、**ほぼ直交**に効きます。

| 引数 / CLI | 既定 (`hitofude`) | 物理的な意味と聴覚上の変化 |
| :--- | :---: | :--- |
| `hz` (`--hz`) | `350.0` | 基準ピッチ高さ Hz。女声 `300〜360`、少女 `400`、男声 `135〜165` |
| `fscale` (`--fscale`) | `1.17` | フォルマント周波数倍率（声道長の逆数）。女声 `1.15〜1.22`（**< 1.0 に下げると男声声道になる**） |
| `g_vo` (`--g-vo`) | `0.92` | 有声くびれ深さ $G \in [0, 0.97]$。`0.92`=澄んだ声、`0.895`=柔らかい声、`0.58`=半有声ささやき、`0.0`=無声息 |
| `tilt_w` (`--tilt`) | `5` | 粗削り移動平均幅（最初の零点 `SR / tilt_w` Hz）。`4〜5`=華やかな女声、`6`=落ち着いた吐息、`>=8`=こもった暗声 |
| `sigh` (`--sigh`) | `0.0` | 句末母音後半（`u > 0.30`）での $G$ 解放量 `0.0〜1.0`。`0.78`（`toiki`）で語尾が自然に吐息へ溶ける |
| `rate` (`--rate`) | `1.26` | 話速倍率（小さいほど速い）。`1.15`=速め、`1.26〜1.30`=自然な会話 |
| `jitter` (`--jitter`) | `0.0013` | 周期ごとの微細揺らぎ率。`0.0` にすると機械的なロボット声 |
| `wander_st` (`--wander`) | `0.18` | ピッチの緩やかな自然漂い幅（半音）。`0.0` で完全固定ピッチ |

---

## 4. クイック実行 ＆ LLM自己検証ループ（Node.js 18+）

```bash
# 1) プリセット一覧
node yomu.mjs --list-presets

# 2) 吐息プリセットで合成（約0.15秒）＋音響指標＆基準との差分を数値確認
node yomu.mjs --preset toiki --measure --compare "わたし、にほんご、ちょっとしゃべれます"

# 3) 歌モード（モーラごとの Hz 指定）
node yomu.mjs --preset toiki --uta 349,392,440,523,523,440,392,440,466,523,587,523,440,392 --measure "ワタシノナマエツキナミノコエ"

# 4) X Player Card / GitHub Pages 用 HTML 2枚のビルド（out/ に出力）
node tools/build_x_player.mjs
```

### LLMがコードを改造するときの鉄則（アンチパターン防止）
1. **帯域別 AGC を足さない**：`bp1..bp4` の各帯域に個別正規化を入れると、`tilt_w` や音源の傾きが打ち消されて再度多段補正が必要になる。
2. **別系統の息ノイズを足さない**：息や囁きは別乱数を加算するのではなく、同じ1本線上の `g_vo` / `sigh` を下げて倍音の谷を残すことで表現する（マイク吹かれ音にならない）。
3. **`hitofude.mjs` に Node 専用 `import` を入れない**：[`hitofude.mjs`](hitofude.mjs) はブラウザでもそのまま動く純粋 ES Module として保ち、ファイル入出力は [`yomu.mjs`](yomu.mjs) 側に置く。
