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

同一文を**響・語・泡・牙・寄添**で生成し、ファイル名を隠して順序を入れ替える。
短文で第一印象、異なる文を10本続けて聴く条件で「途中で止めたくなるか」も比較。
評価軸は (1) 聞き取れた語 (2) 声の識別 (3) 耳の疲れ (4) 続きを聞きたいか。
多人数の比較と実測が済むまでは「魅力の改善」とは呼ばない。

### 匿名試聴パックを一括生成

```bash
node tools/hibiki_listen.mjs
```

`out/hibiki_blind` に5声×3文の15 WAV、採点ガイド `LISTEN_FIRST.txt`、回答表 `answer_key.json` を生成。
**試聴前には回答表を開かないこと**。出力フォルダが既にある場合は上書きせず失敗する。

## 響 v4 — 「寄添」(yorisoi) / 声の親しみ

`hibiki_yorisoi` は近接感を想定した実験声。
`--closeness 0..1` は、句頭で声門の周期性をわずかに緩めて息を残し、句中の母音で芯を作り、句末で解放する。
声を録音・ミックスしていない。**単一のノイズ線で同じ発声器官の一貫した振る舞いを作る**のが目的。

```bash
node yomu.mjs --preset hibiki_yorisoi --measure --compare "おかえり、きょうもはなそう"
node yomu.mjs --preset hibiki_yorisoi --closeness 0 --measure "おかえり、きょうもはなそう"
```

判定基準は「近くで鳴っているように感じるか」「繰り返し聞いて疲れないか」。
聴取実験前なので、これらを達成したとは主張しない。

### 自動テスト

`.github/workflows/hibiki-tests.yml` を追加。`hibiki` への push / PR / 手動実行時に Node.js 22 で構文・回帰テストと短いWAV生成を確認する。ワークフローの追加と実際の実行成功は別なので、Actionsでジョブ完了を確認すること。

## 響 v5 — 「懐」(natsuku)：音素の連なりに声の指紋を刻む

新プリセット `hibiki_natsuku` は、既存の固定母音色とは別に **前の母音／今の母音／次の母音** に反応する
決定論的な F2/F3 移動（`--signature 0..1`）を導入。発音の中央だけを動かし、子音の判別を守る。
パターンは固定で、声が毎回別人にならないことを優先。単一ノイズ・録音なし・追加パッケージなし。
`signature=0` では旧音声と完全互換になる設計。

```bash
node yomu.mjs --preset hibiki_natsuku --measure "おかえり、きょうはどんなひだった"
node yomu.mjs --preset hibiki_natsuku --signature 0 --measure "おかえり、きょうはどんなひだった"
node tools/hibiki_listen.mjs
node --test tests/hibiki.test.mjs
```

匿名試聴は 6声 × 3文 = 18 WAV。声の新しさと「聞き続けたい」は別なので、嗜好の改善は未検証。

## 響 v6 — 「息吹」(ibuki)：声の一体感

`hibiki_ibuki` を追加。母音の種類と直前母音の関係から、**同じ形のジェスチャーで音程とF2/F3が同時に動く**。
従来の各々独立した装飾を減らし、一貫した「喋り方」を試す。`--gesture 0..1` は母音内部のみ、歌唱モードでは無効。
単一ホワイトノイズ源と純JSを維持。`gesture=0` の過去音声は不変。

```bash
node yomu.mjs --preset hibiki_ibuki --measure "おかえり、きょうはどんなひだった"
node yomu.mjs --preset hibiki_ibuki --gesture 0 --measure "おかえり、きょうはどんなひだった"
node --test tests/hibiki.test.mjs
```

匿名パック：7声 × 3文 = 21 WAV。発話可読性を維持する設計だが、魅力の向上は未実証。

## Bシリーズ — B1「アカンボシミュレータ」

**Vシリーズとは別の試み**。成人TTSの聞き取りやすさを競わず、乳児の喃語（アー、ウー、ママ、ババなど）を
「調音の曖昧さ」「不安定なピッチ探索」「短い音節の反復」で模した実験用合成器。
生理学的に正確な乳児の音声モデルを主張するものではなく、第一段階は**喃語のみ**（泣き声は未実装）。

- `b1_akambo.mjs`：喃語の決定論的生成器、B1プリセット、合成API（純JS）。
- `b1_yomu.mjs`：B1専用CLI（Node標準ライブラリのみ）。
- `makeHitofude` の `baby` ノブは既定0。Vシリーズ・草薙音源の出力は不変。
- 元の1本のホワイトノイズ信号源、5極声道、ベルヌーイ扉をそのまま活用。

```bash
node b1_yomu.mjs --out b1_akambo.wav
node b1_yomu.mjs --seed 42 --phrases 5 --out b1_second.wav
node b1_yomu.mjs --text "あー、うー、まま、ばぶ" --out b1_manual.wav
node --test tests/hibiki.test.mjs
```

実際に聴いて、**赤ちゃんらしさ・かわいさ・聞き続けたさ**を別々に評価。

## B2 — ナマなアカンボ（呼気・声門・周期の結合）

B1の「高い声・未熟な調音」に加え、**ひとつの遅い呼気圧の揺らぎ**が声門の締まり、開閉速度、基本周期、
肺からの流量を同時に変える `b2_body` を実装。呼吸の揺らぎは従来の1本のノイズ線から抽出し、
別サンプルや別乱数源を足さない。B2はB1とVシリーズから独立したモジュールとCLIを使う。

```bash
node b2_yomu.mjs --out b2_akambo.wav
node b2_yomu.mjs --text "あー、うー、まま、ばぶ" --out b2_manual.wav
node b2_yomu.mjs --body 0 --text "あー、うー、まま、ばぶ" --out b2_dry.wav
node --test tests/hibiki.test.mjs
```

`--body 0` は同一B2レシピの結合機構だけを無効化する比較用。
B1とB2のレシピ自体は異なるため、B1のWAVと同一にはならない。
目標は「息が声を生む」生々しさ。乳児の実録を再現したものではなく、見た目の可愛さや臨場感は聴取評価が必要。

### B2 改訂：生後2か月のクーイングに寄せる

- デフォルトを「バババ」型の模倣から、`アー、ウアー、オー` など母音主体のクーイングに変更。
- `--mode babble` で従来型の子音反復も生成できる。
- 呼気が不足する局面で、同じ声門扉の周期を伸ばし、接触を弱め、元のノイズから息漏れが増える
  `--breaks 0..1` を導入（パルス化・発声途切れの**近似**）。
- B1/Vの既存WAVは不変。B2の旧版はGit履歴から再現可能。

```bash
node b2_yomu.mjs --seed 42 --mode coo --out b2_coo.wav
node b2_yomu.mjs --seed 42 --mode babble --out b2_babble.wav
node b2_yomu.mjs --seed 42 --breaks 0 --out b2_no_breaks.wav
```

参考: Wikimedia Commons 公開録音「Gabbling baby 2 months old」(23秒、PD):
https://commons.wikimedia.org/wiki/File:Gabbling_baby_2_months_old.ogg
学術的な非定常発声: https://pmc.ncbi.nlm.nih.gov/articles/PMC6177330/

**比較状況**: 音声ファイルのローカル取得は環境側の通信制約で失敗。
現段階で実録との音響距離や聴感の一致を確認したと主張しない。音は別途実録とAB比較が必要。

### B2再調整（Hodoki実測を受けた試作）

使用者の計測（対象録音: 2か月、23秒）:
| 指標 | 実録 | B2改 | 目標 |
| --- | ---: | ---: | --- |
| 中央F0 | 349 Hz | 388 Hz | 高すぎる基準音を下げる |
| Jitter | 2.2% | 2.1% | なるべく維持 |
| Shimmer | 5.7% | 12.2% | 周期振幅差を減らす |
| HNR | 16.2 dB | 8.8 dB | ノイズを減らす |
| 周期類似 | 0.99 | 0.93 | 周期形状を安定させる |

数値は測定手法と録音条件に依存。**新バージョンの実測値ではない。**
試作では `hz` を390→351にし、`b2_breaks` と `b2_body` を弱めて、
`b2_clean` で声門へ注ぐ非周期ノイズ・息漏れを減らした。
ジッターのノブは保持。耳で聴いた似方・HNR/シマーの改善は追試が必要。

```bash
node b2_yomu.mjs --seed 42 --text "アー、ウー、ウアー" --out b2_tuned.wav
node b2_yomu.mjs --seed 42 --text "アー、ウー、ウアー" --profile legacy --out b2_legacy.wav
node b2_yomu.mjs --seed 42 --text "アー、ウー、ウアー" --clean 0 --out b2_no_clean.wav
```

### B2 周期振幅実験（実録への忠実度優先）

Hodoki計測（ユーザー報告）では B2改2 は F0=347Hz, jitter=1.7%, shimmer=11.0%, HNR=11.2dB, 周期類似度=0.96。
実録（生後2か月）はそれぞれ 349Hz, 2.2%, 5.7%, 16.2dB, 0.99。

- 新デフォルト `--profile cycle`: 発声器内の実周期 `PER` に基づき、各周期のRMSを前後2周期へ近づけるゲイン整流を導入。**周期長は変更しない**。
- 整流ゲインは周期境界で連続となるよう補間する。発声の立ち上がり・無声部は無理に増幅しない。
- `--profile tuned` は測定済みB2改2のコード・数値設定を保持、`--profile legacy` も引き続き再現可能。
- `--cycle 0..1` が整流量。B1とVシリーズでは既定ゼロ。

```bash
node b2_yomu.mjs --seed 42 --text "アー、ウー、ウアー" --profile cycle --out b2_cycle.wav
node b2_yomu.mjs --seed 42 --text "アー、ウー、ウアー" --profile tuned --out b2_tuned.wav
node b2_yomu.mjs --seed 42 --text "アー、ウー、ウアー" --profile cycle --cycle 0 --out b2_cycle_off.wav
```

注意：**シマー・HNR改善は未計測**。また周期整流だけでHNRが一致する保証はない。
発声源の構造を取り替えること、録音を計測のみに使うこと、サンプルを合成へ使うことのいずれもBシリーズでは選択可能。

## B3 — サラサラ技術 / 実録への一致を最優先

Hodoki `hodoki/zarazara` で突き止めた一次原因は、有声コム帰還の非周期ノイズ注入。
`combG=0.99`（soroe1）と `combG=0.985,rawAirMul=0.6`（soroe2）を、
`hitofude.mjs` に**ゼロ影響のオプトイン**として統合。B1・B2・Vのデフォルトは不変。

B3は B2改2（`B2_TUNED`）を基礎に、**baby bendを保持**し、B2後段cycle整流は無効。
`--profile soroe1` は Hodoki実測に近い設定、`--profile candidate` は
`soroe1` に周期ジッターを増やす仮説（0.018→0.027）を加えた**未評価候補**。
`--profile soroe2` も独立比較可能。

```bash
node b3_yomu.mjs --seed 42 --profile soroe1 --text "アー、ウー、ウアー" --out b3_soroe1.wav
node b3_yomu.mjs --seed 42 --profile candidate --text "アー、ウー、ウアー" --out b3_candidate.wav
node b3_yomu.mjs --seed 42 --profile soroe2 --text "アー、ウー、ウアー" --out b3_soroe2.wav
```

目標: 実録 F0 349Hz / jitter 2.18% / shimmer 5.70% / HNR 16.16dB /
周期相関 .991。Hodokiによる既知のB2改2+soroe1実測:
348Hz / 1.36% / 8.1% / 14.4dB / .983。
数値は音声区間・検出条件・圧縮条件に依存するため、測定値は再現条件を明記すること。
**歌の長さ指定・baby bend歌唱対応は別課題。**

実録 `samples/reference/infant_2months_stephan.ogg` と生成したWAVを
同じ `soroi` 解析器で比較する `tools/b3_measure.mjs` を整備。
