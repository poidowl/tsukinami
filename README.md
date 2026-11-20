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

## hibiki — チャッピィエディション：声に「口癖」を作る

草薙の再帰声門・声道モデルをそのまま使用し、**`--preset hibiki`** を追加。
従来の「何となく自然な声」ではなく、聴き覚えのある固有の電子声を目指す実験です。

- **モーラ・モチーフ**：5拍周期の小さな音程の訛り。母音の中央だけで持ち上げ／押し下げ、子音と母音境界を守る。
- **母音の補色**：母音の中央で F2/F3 を反対向きにゆっくり動かす。歌声にエフェクトを重ねるのでなく、声道そのものの発音癖を作る。
- **後方互換**：既存のプリセットは `character=0` 扱いで一切変わらない。歌モードの音程モチーフは自動停止（音符の音程を守る）。単一ノイズ源、外部依存なし。

```bash
node yomu.mjs --preset hibiki --measure --compare "わたしのこえは、つきなみではありません"
node yomu.mjs --preset hibiki --character 0 --measure "わたしのこえは、つきなみではありません"
node yomu.mjs --preset hibiki --character 1 --measure "わたしのこえは、つきなみではありません"
```

**評価**：盲聴で「どれが響か」「もう一度聞きたくなるか」「一語でも聞き取りを損ねたか」を記録。音響指標は音の違いの確認用で、魅力の証明にはしない。

## 響 v2 — 三つの声で魅力を探す

v1 のモーラ固有モチーフ＋母音 F2/F3 色彩に、**声門扉の拍頭アタック `edge`** を追加。
同じノイズ線、同じ再帰モデルの内側で扉の閉まり方だけを微調整。別の乱数・波形・録音は足さない。

| プリセット | 狙い | 個性 |
|---|---|---|
| `hibiki`（響） | 中域の生意気な電子声 | 色彩豊かな5拍モチーフ |
| `hibiki_awa`（泡） | 少し浮いた柔らかい語り | 吐息が多い、明るく揺れる |
| `hibiki_kiba`（牙） | 小気味よく歯切れのよい低めの声 | 拍頭の粘膜扉が鋭く閉まる |

`--character 0 --edge 0` にすれば同一レシピの草薙式の音に戻る。既存プリセットへの変更なし。

```bash
node yomu.mjs --preset hibiki --measure "あさのひかり、ゆめのかけら"
node yomu.mjs --preset hibiki_awa --measure "あさのひかり、ゆめのかけら"
node yomu.mjs --preset hibiki_kiba --measure "あさのひかり、ゆめのかけら"
node yomu.mjs --preset hibiki_kiba --edge 0 --measure "あさのひかり、ゆめのかけら"
node --test tests/hibiki.test.mjs
```

魅力は音響指標で測れない。**聞き取りやすさ・記名性（もう一度聞いて識別できるか）・飽きなさ**を、同じ台詞のブラインド比較で評価する。

## 響 v3 — 「語」(katari) / 長く聴くための声

新プリセット `hibiki_katari` は「同じ5拍が反復する」癖ではなく、
*母音の種類・前の母音との違い・子音の種類・句中の位置・句末*から、小さな音程の形を作る。
これは**意味理解や感情推定ではなく、発音上の文脈への反応**。音符指定の歌唱では無効。
`--cadence 0..1` で強さを変えられ、0 の時は旧音声を変更しない。

```bash
node yomu.mjs --preset hibiki_katari --measure "あいあい、ああああ"
node yomu.mjs --preset hibiki_katari --cadence 0 --measure "あいあい、ああああ"
node --test tests/hibiki.test.mjs
```

### 試聴評価の実験計画

同一文を**響・語・泡・牙**で生成し、ファイル名を隠して順序を入れ替える。
短文で第一印象、異なる文を10本続けて聴く条件で「途中で止めたくなるか」も比較。
評価軸は (1) 聞き取れた語 (2) 声の識別 (3) 耳の疲れ (4) 続きを聞きたいか。
多人数の比較と実測が済むまでは「魅力の改善」とは呼ばない。
