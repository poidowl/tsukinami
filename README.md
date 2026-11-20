# tsukinami (`kusanagi` branch — Pure JavaScript Edition)

> **約77KBのピュアJavaScript（`.py` ゼロ）で、たった1本のホワイトノイズから日本語かな・歌を彫る。ブラウザでも Node.js でもそのまま鳴り、LLMの1コンテキストで丸ごと読める。**  
> 外部パッケージ不要・外部データファイル不要・Python互換ギプスなし・本体2ファイル計 1,864行（77.4 KB）。

`hitofude`（一筆彫り）から Python 依存と互換用の乱数・丸めギプスをすべて外し、純粋な ES Module 2本（エンジン [`hitofude.mjs`](hitofude.mjs) ＋ CLI [`yomu.mjs`](yomu.mjs)）にまとめた「草薙（kusanagi）」ブランチです。

## 1. コンテキスト投入コマンド ＆ Raw URL（全コード一括）

本体の実装は以下の2ファイルだけで完結しています（`README.md` 込み合計 約85 KB）：

```bash
cat README.md hitofude.mjs yomu.mjs
```

Web取得型LLMには、以下の **Raw プレーンテキスト URL 3本**を渡してください：
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/README.md
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/hitofude.mjs
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/yomu.mjs

| ファイル | 行数 | 役割 |
| :--- | ---: | :--- |
| [`hitofude.mjs`](hitofude.mjs) | 1,590行 | **純JS音源・声道・調音・韻律エンジン（`import` ゼロ）**：かな→5ms軌道 `tracksFromKana`、東京式アクセント `f0Rule`、非対称ベルヌーイ粘膜扉×5極声道の単一乱数再帰合成 `makeHitofude`、WAV出力 `encodeWav`、FFT音響計測 `hakaru`（ブラウザ `<script type="module">` と Node.js 両対応） |
| [`yomu.mjs`](yomu.mjs) | 274行 | **Node.js CLI & レシピドライバ**：プリセット合成、`--measure` 自己計測、`--compare` 音響指標差分、`--uta` 歌唱、引数バリデーション（既定出力は上書きしない連番 `out/yomu_NNN_<preset>.wav`） |
| [`tools/build_x_player.mjs`](tools/build_x_player.mjs) | 補助 | [`hitofude.mjs`](hitofude.mjs) から X Player Card / GitHub Pages 用の単一HTML（`kusanagi.html` + `kusanagi_player.html`）を直接生成（公開URL: https://poidowl.github.io/tsukinami/kusanagi.html ） |

---

## 2. 信号処理の構造（1本のノイズ信号線 × 非対称ベルヌーイ粘膜扉 ＆ 5極声道再帰）

正弦波オシレータ（`sin/cos` 音源）、固定波形の粒スタンプ、STFT往復、40段オールパス、帯域別 AGC、別シード乱数はすべて廃止しています。**音になる有声・吐息・子音だけでなく、ピッチの自然漂い・周期ジッタ・歌唱ビブラート・呼気圧のゆらぎに至るまで、すべて Step 0 の 1本のホワイトノイズ `x` だけ**から削り出します。

```text
x = rng.uniform(-1, +1) × N   # [-1, +1] の一様ホワイトノイズ（乱数源はこの1本だけ）
  │
  ▼ 【統合粘膜再帰 Step ①–③ (shin = 1.0: 女声・アルト・ちびっ子・囁き・おっさん・歌)】
  │    ・① 声帯組織波: 声道の出口＆F1からの帰還圧を受けながら、2段コム＋dampで声帯波が揺れる
  │    ・② 非対称ベルヌーイ2唇扉: 上唇は丸くめくれて開き、下唇は気流吸い寄せ (-bern*uFlow) で急閉鎖して呼気流を刻む
  │         → 扉が閉じた瞬間に高次倍音まで位相が揃い、句末 (sigh > 0) は扉を緩めて元の吐息へほどける
  │    ・③ 5極粘膜声道: F1→F2→F3→F4→F5 直列カスケード（開扉時は肺ダンプ連動）＋唇微分放射 ＋ 子音帯 yamaBp
  │      （※冷凍ロボ robot のみ shin = 0.0 の片道コム固定モード）
  │
  ▼ 【引き算④ 1スカラー整音＋時間包絡】 y[i] * gLv[i] * env[i]
       ・母音定常部のみ全周波数に同じ1スカラー gLv[i] を掛けて音節間の音量暴れを整える（瞬間スペクトル傾斜変化 0.00 dB）
```

---

## 3. パラメータと物理・聴覚対応表（LLM改造ガイド）

帯域別 AGC が無いため各ノブは他の段で打ち消されず、**ほぼ直交**に効きます。

| 引数 / CLI | 既定 (`hitofude`) | 物理的な意味と聴覚上の変化 |
| :--- | :---: | :--- |
| `hz` (`--hz`) | `350.0` | 基準ピッチ高さ Hz。女声 `300〜360`、アルト `220`、少女 `400`、低音男声 `105〜155` |
| `fscale` (`--fscale`) | `1.17` | フォルマント周波数倍率（声道長の逆数）。女声 `1.15〜1.22`、アルト `1.08`、男声 `0.85` |
| `g_vo` (`--g-vo`) | `0.89` | 有声くびれ深さ $G \in [0, 0.97)$。`0.89`=澄んだ声、`0.77`=低音轟、`0.64`=半有声囁き |
| `tilt_w` (`--tilt`) | `5` | 粗削り移動平均幅（最初の零点 `SR / tilt_w` Hz）。`4〜5`=標準、`6`=落ち着いた吐息、`>=8`=暗声 |
| `sigh` (`--sigh`) | `0.0` | 句末母音後半（`u > 0.30`）での扉解放量 `0.0〜1.0`。`0.78`（`toiki`）で語尾が自然に吐息へ溶ける |
| `damp` (`--damp`) | `0.08` | 声帯波帰還路の1極ローパス減衰 `0.0〜0.95`。高い倍音ほど早くほどいて元の息の質感を残す |
| `shin` (`--shin`) | `1.0` | 声門扉と声道の再帰結合度 `0.0〜1.0`。`1.0`=非対称2唇粘膜扉×5極声道（既定）、`0.0`=冷凍ロボ片道コム |
| `rate` (`--rate`) | `1.26` | 話速倍率（小さいほど速い）。`1.15`=速め、`1.26〜1.32`=自然な会話 |
| `jitter` (`--jitter`) | `0.0026` | 周期ごとの微細揺らぎ率。`0.0` にすると機械的なロボット声 |
| `wander_st` (`--wander`) | `0.18` | ピッチの緩やかな自然漂い幅（半音）。`0.0` で完全固定ピッチ |

---

## 4. クイック実行 ＆ LLM自己検証ループ（Node.js 18+）

```bash
# 1) プリセット一覧
node yomu.mjs --list-presets

# 2) 吐息女声 / 再帰低音おっさん で合成＋音響指標を数値確認
node yomu.mjs --preset toiki --measure --compare "わたし、にほんご、ちょっとしゃべれます"
node yomu.mjs --preset ossan --measure "こんばんは、いいよるですね"

# 3) 歌モード（モーラごとの Hz 指定）
node yomu.mjs --preset toiki --uta 349,392,440,523,523,440,392,440,466,523,587,523,440,392 --measure "ワタシノナマエツキナミノコエ"

# 4) X Player Card / GitHub Pages 用 HTML 2枚のビルド（out/kusanagi.html, out/kusanagi_player.html）
node tools/build_x_player.mjs
```

- **かな入力と句切れ記号**: 読点 `、` は無音の間（ポーズ）を入れ、半角空白または `/` は間を入れずに文節・アクセント句だけを切ります（`'` はアクセント核、`0` は平板、`?` は疑問上昇）。句末（`、`・半角空白・`/`・文末の直前）の助詞 `は` は自動で `ワ` に変換され、ベタ書き文中の `は` は誤変換防止のため `ハ` のまま残ります。

### LLMがコードを改造するときの鉄則（アンチパターン防止）
1. **帯域別 AGC を足さない**：各フォルマント帯域に個別正規化を入れると、`tilt_w` や声道の傾きが打ち消されて再度多段補正が必要になる。
2. **別系統の息ノイズ・固定波形を足さない**：息や揺らぎは別乱数や固定波形を加算するのではなく、Step 0 の1本のノイズ `x` とくびれ・扉の開閉だけで表現する。
3. **`hitofude.mjs` に Node 専用 `import` を入れない**：[`hitofude.mjs`](hitofude.mjs) はブラウザでもそのまま動く純粋 ES Module として保ち、ファイル入出力は [`yomu.mjs`](yomu.mjs) 側に置く。

---

## 5. Hodoki（ほどき）— 音声汎用デコーダー ／ 第1モジュール「揃い・不揃い（soroi）」

声に重なっている情報（高さ・声道・揃い不揃い・息・言葉）を1枚ずつほどいて読み出す観察装置。いまは**揃い／不揃いの観察だけ**（フィルターなし）。純JS・`import` は Node 標準のみ・学習済み重みなし・外部データなし。

| ファイル | 役割 |
| :--- | :--- |
| [`hodoki.mjs`](hodoki.mjs) | CLI 入口（モジュール名＋wav、または `--synth` で草薙合成音をその場で観察） |
| [`hodoki/soroi.mjs`](hodoki/soroi.mjs) | 揃いモジュール本体（`import` ゼロ・ブラウザでも動く）：WAV 読み込み・自前 FFT・f0/HNR・周期切り出し・非整数倍度・HTML レポート |
| [`hodoki/test_soroi.mjs`](hodoki/test_soroi.mjs) | 物差し検定：JS で作った既知の揺れ入りテスト音で①〜④が仕込み量どおり動くか assert |
| [`hodoki/sample/`](hodoki/sample/) | 見本：草薙 v8（7f09d18）`hitofude` プリセット「わたし、にほんご、ちょっとしゃべれます」のレポート（HTML / JSON） |

```bash
node hodoki/test_soroi.mjs                                   # 物差し検定（25項目）
node hodoki.mjs soroi some.wav                               # 任意のモノラル wav → out/hodoki_soroi_some.html
node hodoki.mjs soroi --synth "わたし、にほんご、ちょっとしゃべれます" --preset hitofude
node hodoki.mjs soroi --synth "わたし、にほんご" --preset hitofude --set jitter=0 --set wander_st=0   # ノブを変えて比べる
```

レポート（自己完結 HTML・インライン SVG）のレーン。すべて同じ時間軸で、薄い橙の帯は有声と判定したフレーム：

| レーン | 何を見ているか |
| :--- | :--- |
| 波形 / f0 | 振幅の min/max と、フレーム自己相関（10 ms 刻み・3周期窓）で出した基本周波数 |
| ① ジッター | 隣り合う周期の**長さ**のずれ `|T[i+1]−T[i]| / 平均周期`（%）。点＝1周期、線＝±25 ms 中央値。要約には高さの滑らかな動きを差し引いた `|T[i]−(T[i−1]+T[i+1])/2|` 版も出す |
| ② シマー | 隣り合う周期の**強さ**（周期内ピーク間振幅）のずれ `|20·log10(A[i+1]/A[i])|`（dB）。要約には % 版も |
| ③ 非整数倍度 | 倍音ピーク（46 ms Hann・×8 ゼロ詰め・放物線補間）が、最もよく合う f0\* の**整数倍からずれる量**（cents、振幅重み付き平均）。③' は倍音ごとの符号つきずれ（青＝低い／赤＝高い） |
| ④ HNR | 倍音とノイズのパワー比。Boersma (1993) の窓補正つき正規化自己相関 r から `10·log10(r/(1−r))`（dB、高いほど揃い） |

周期の切り出しは、有声区間の頭を最大振幅点にそろえ、「いまの1周期」と「1周期先」を正規化相互相関で照合して1歩ずつ進む方式（波形照合・放物線補間でサンプル未満まで）。長さ比が 1.3 を超える隣接ペアは数えない。

物差し検定（帯域制限パルス列、f0=220 Hz）の結果：完全周期で ジッター 0.000 %・シマー 0.028 dB・HNR 47 dB・非整数倍度 0.02 cents。一様 ±1.5 % の周期揺れで ジッター 1.00 %（期待 1.00 %）、一様 ±10 % の振幅揺れで シマー 6.77 %（期待 6.67 %）、白色ノイズ SNR 20 dB で HNR 20.0 dB、倍音を ±15 cents 交互にずらすと 10.8 cents（同じ重み付き当てはめでの期待値 10.8）。

---

## 6. Hodoki 第2モジュール「声の道（michi）」＋ 話し手像カード ＋ つまみ逆算（tsumami）

聞き手の頭に浮かぶ「話し手像」のうち、**音から測れる物理の手がかり**（声道の長さ・高さの帯・息っぽさ・揃い・話速）だけを、点ではなく**幅**で読み出す。性別・年齢などの「聞こえ方」の判定はしない（聞き手データが要るため）。純JS・外部ライブラリ／学習済み重み／ダウンロードなし。

| ファイル | 役割 |
| :--- | :--- |
| [`hodoki/michi.mjs`](hodoki/michi.mjs) | 自前 LPC（44.1→22.05 kHz 間引き・プリエンファシス＋窓ごとの適応1次・25 ms Hamming・18 次・Levinson-Durbin・Durand–Kerner 根）、F1–F4、声道長、H1−H2 / H1*−H2* / H1−A1 / H1−A3、話速、話し手像カード、HTML |
| [`hodoki/tsumami.mjs`](hodoki/tsumami.mjs) | 草薙のつまみ当て：乱数合成 study、自前リッジ回帰（一個抜き R²）、Fisher 幅と取り違え相関、自前 Nelder–Mead による合成分析、seed 再当て |
| [`hodoki/test_michi.mjs`](hodoki/test_michi.mjs) | 一様管テスト（f0 100–450 Hz × 声道 12/14.5/17.5 cm）、H1−H2、草薙の真値フォルマント軌道との比較、つまみ当ての assert（25 項目・約 40 秒） |
| [`hodoki/sample/kusanagi_hitofude_michi.html`](hodoki/sample/kusanagi_hitofude_michi.html) | 見本：草薙 v8 `hitofude`「わたし、にほんご、ちょっとしゃべれます」の話し手像カード＋つまみ逆算表 |

```bash
node hodoki/test_michi.mjs                         # 検定（--quick でつまみ study を省く）
node hodoki.mjs michi some.wav                      # 話し手像カード → out/hodoki_michi_some.html
node hodoki.mjs tsumami --study-n 200               # つまみ当ての study（約 85 秒）→ out/hodoki_tsumami_study.json
node hodoki.mjs michi --synth "わたし、にほんご、ちょっとしゃべれます" --preset hitofude --decode --study-json out/hodoki_tsumami_study.json
```

**測り方**
- **フォルマント**：既定は「倍音包絡 LPC（henv）」。46 ms 窓で f0 の倍音ピークを拾い、その dB を周波数で線形補間した包絡のパワーから自己相関を作って Levinson にかける。普通の LPC（plain）も同じ次数で並べて出す。帯域幅 600 Hz 未満の共鳴を下から4本とって F1–F4 にする。
- **声道長 VTL**：一様管 F_i=(2i−1)c/(4L) への原点通過最小二乗（主）と、分散法 c/(2·(F4−F1)/3)（副）。c=35000 cm/s。
- **H1−H2**：未補正と、Iseli & Alwan (2004) の式で LPC の F1・F2（帯域幅は 40–500 Hz に制限）の持ち上がりを差し引いた H1*−H2*。H1−A1・H1−A3 は未補正。
- **話速**：有声フレーム上の強度ピーク（周囲より 2 dB 以上・間隔 90 ms 以上）＝音節核の数 / 有声区間の長さ。
- **幅**：フレームごとの推定の中央値・四分位範囲・中央値のブートストラップ 90% 区間（400 回）。

**高い声でのフォルマントの偏り**（一様管・音源 −12 dB/oct・定常母音、`test_michi.mjs` A 節）
- 声道長は f0 100–450 Hz・12/14.5/17.5 cm の全 24 条件で真値の ±3% 以内（henv）。
- F1 の平均|誤差|：f0 ≤ 200 Hz で henv 0.7% / plain 1.7%、f0 ≥ 300 Hz で henv 4.2% / plain 7.8%。最大は f0=300 Hz・17.5 cm の F1 +10.3%（henv）。plain は f0=450 Hz・17.5 cm で4本そろわなかった。
- 未補正 H1−H2 は f0 によって −6.8〜+27.4 dB（真値 12.04 dB）。補正後 H1*−H2* は 9.8〜14.8 dB。

**草薙の真値（合成に使ったフォルマント軌道）との比較**（同じ文、`test_michi.mjs` C 節）
- 声道長（真値軌道に同じ一様管あてはめをした値との比較）：hitofude 11.08 / 10.92 cm、alto 11.81 / 11.83、ossan 14.93 / 15.03、chibi 9.75 / 9.68、sasayaki 11.10 / 11.11、hitofude fscale=0.9 は 13.37 / 14.19 cm（−5.8%）。
- フレームごとの F1 |誤差| 中央値は 11–25%（fscale=0.9 では 50%）、F2–F4 はおおむね 2–9%。F1 は草薙の側で「F1 ≥ 1.04·f0」に下限がかかっている。
- fscale 0.9→1.3 の推定 VTL：12.66 → 12.55 → 11.44 → 10.64 → 9.94 cm（0.9→1.0 はほぼ平ら）。
- 次数 18 と間引き 1/2 は、この草薙の真値つき比較を見て選んだ（同じ音で選んで同じ音で測っているので、甘く出ている可能性あり）。

**草薙のつまみはどこまで当たるか**（`makeHitofude` の引数。study＝つまみと seed を一様乱数で振った 200 本、同じ文、shin=1.0 固定）

| つまみ | 範囲 | 回帰 R²（一個抜き） | 主な手がかり | 判定 |
| :--- | :--- | ---: | :--- | :--- |
| `hz` | 110–420 | 0.994 | f0 中央値 | 当てられる |
| `fscale` | 0.85–1.32 | 0.986 | F4・F3・声道長 | 当てられる |
| `rate` | 1.10–1.40 | 1.000 | 発話の長さ（文が1つなので） | 当てられる（この文に限る） |
| `g_vo` | 0.60–0.96 | 0.950 | 非整数倍度・HNR・ジッター | 当てられる |
| `sigh` | 0–0.9 | 0.589 | f0 の幅（半音） | 幅つき |
| `level_k` | 0.3–1.0 | 0.254 | 有声割合 | 当てられない |
| `tilt_w` | 3–8 | 0.033 | — | 当てられない |
| `jitter` | 0–0.008 | −0.052 | — | 当てられない |
| `wander_st` | 0–0.25 | −0.056 | — | 当てられない |
| `damp` | 0–0.4 | −0.082 | — | 当てられない |

合成による分析（回帰の予測から始め、別 seed の草薙で Nelder–Mead 150 回、幅＝Fisher ±2σ ∪ seed 10 通りの再当て）を hitofude / alto / ossan の3プリセットにかけると、真値が幅に入ったのは 30 中 28（外れ：hitofude の `damp`、alto の `fscale`）。Fisher の相関で |r|>0.5 になった組（取り違え）は設定によって変わり、`wander_st`・`jitter`・`damp` が `fscale`・`g_vo`・`sigh` と組むことが多い。見本（hitofude）では `wander_st` の真値 0.18 が幅 0.084–0.148 の外だった。
