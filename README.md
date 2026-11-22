# tsukinami (`kusanagi` branch — Pure JavaScript Edition)

> **約72KBのピュアJavaScript（`.py` ゼロ）で、たった1本のホワイトノイズから日本語かな・歌を彫る。ブラウザでも Node.js でもそのまま鳴り、LLMの1コンテキストで丸ごと読める。**  
> 外部パッケージ不要・外部データファイル不要・Python互換ギプスなし・本体2ファイル計 1,600行（71.9 KB）。

**[ブラウザで声を聴く](https://poidowl.github.io/tsukinami/kusanagi.html)** — 「▶ 彫って鳴らす」を押すと、吐息の声で「わたし、にほんご、ちょっとしゃべれます」と読み上げます。

`hitofude`（一筆彫り）から Python 依存と互換用の乱数・丸めギプス・旧世代フィルタをすべて外し、純粋な ES Module 2本（エンジン [`hitofude.mjs`](hitofude.mjs) ＋ CLI [`yomu.mjs`](yomu.mjs)）にまとめた「草薙（kusanagi）」ブランチです。

## 1. コンテキスト投入コマンド ＆ Raw URL（全コード一括）

本体の実装は以下の2ファイルだけで完結しています（`README.md` 込み合計 約82 KB）：

```bash
cat README.md hitofude.mjs yomu.mjs
```

Web取得型LLMには、以下の **Raw プレーンテキスト URL 3本**を渡してください：
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/README.md
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/hitofude.mjs
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/yomu.mjs

| ファイル | 行数 | 役割 |
| :--- | ---: | :--- |
| [`hitofude.mjs`](hitofude.mjs) | 1,355行 | **純JS音源・声道・調音・韻律エンジン（`import` ゼロ）**：かな→5ms軌道 `tracksFromKana`、東京式アクセント `f0Rule`、単一因果ループによる非対称ベルヌーイ粘膜扉×5極声道合成 `makeHitofude`、WAV出力 `encodeWav`、FFT音響計測 `hakaru`（ブラウザ `<script type="module">` と Node.js 両対応） |
| [`yomu.mjs`](yomu.mjs) | 245行 | **Node.js CLI & レシピドライバ**：プリセット合成、`--measure` 自己計測、`--compare` 音響指標差分、`--uta` 歌唱、引数バリデーション（既定出力は上書きしない連番 `out/yomu_NNN_<preset>.wav`） |
| [`tools/build_x_player.mjs`](tools/build_x_player.mjs) | 補助 | [`hitofude.mjs`](hitofude.mjs) から X Player Card / GitHub Pages 用の単一HTML（`kusanagi.html` + `kusanagi_player.html`）を直接生成（公開URL: https://poidowl.github.io/tsukinami/kusanagi.html ） |

---

## 2. 信号処理の構造（1本のノイズ信号線 × 単一因果ループ再帰）

正弦波オシレータ（`sin/cos` 音源）、固定波形の粒スタンプ、STFT往復、非因果往復コム（`ffbb`/`yamaBp`）、40段オールパス、帯域別 AGC、別シード乱数はすべて廃止しています。**音になる有声・吐息・子音だけでなく、ピッチの自然漂い・周期ジッタ・歌唱ビブラート・呼気圧のゆらぎに至るまで、すべて Step 0 の 1本のホワイトノイズ `x` だけ**から完全因果1パスで削り出します。

```text
x = rng.uniform(-1, +1) × N   # [-1, +1] の一様ホワイトノイズ（乱数源はこの1本だけ）
  │
  ▼ 【単一因果ループ Step ①–③ (全プリセット・歌唱を1ループに統合)】
  │    ・① 声帯組織波: 声道からの帰還圧を受けながら、2段ラグランジュ遅延コム＋高域dampで声帯波が揺れる
  │    ・② 非対称ベルヌーイ2唇扉: 上唇は丸く開き、下唇は気流吸い寄せ×粘膜ソフトクッションでフランジャー櫛なく呼気流を刻む
  │         → 句末 (sigh > 0) は扉を緩めて元の吐息へほどけ、冷凍ロボ (shin = 0) は同じループのまま扉のみバイパス
  │    ・③ 5極粘膜声道＋唇微分放射: F1→F2→F3→F4→F5 直列2極共振器（開扉時は肺ダンプ連動）＋ ピーク利得一定の2極ゼロDC子音・ハ行帯バンドパス
  │
  ▼ 【引き算④ 1スカラー整音＋時間包絡】 y[i] * gLv[i] * env[i]
       ・母音定常部のみ全周波数に同じ1スカラー gLv[i] を掛けて音節間の音量暴れを整える（瞬間スペクトル傾斜変化 0.00 dB）
```

---

## 3. パラメータと物理・聴覚対応表（LLM改造ガイド）

帯域別 AGC が無いため各ノブは他の段で打ち消されず、**ほぼ直交**に効きます。

| 引数 / CLI | 既定 (`hitofude`) | 物理的な意味と聴覚上の変化 |
| :--- | :---: | :--- |
| `hz` (`--hz`) | `326.0` | 基準ピッチ高さ Hz。女声 `290〜340`、アルト `220`、ちびっ子 `375`、低音男声 `105〜155` |
| `fscale` (`--fscale`) | `1.12` | フォルマント周波数倍率（声道長の逆数）。女声 `1.07〜1.12`、アルト `1.02`、ちびっ子 `1.20`、男声 `0.85` |
| `g_vo` (`--g-vo`) | `0.895` | 有声くびれ深さ $G \in [0, 0.97)$。`0.895`=澄んだ声、`0.77`=低音轟、`0.68`=半有声囁き |
| `tilt_w` (`--tilt`) | `5` | 粗削り移動平均幅（最初の零点 `SR / tilt_w` Hz）。`4〜5`=標準、`6`=落ち着いた吐息、`>=8`=暗声 |
| `sigh` (`--sigh`) | `0.0` | 句末母音後半（`u > 0.30`）での扉解放量 `0.0〜1.0`。`0.42`（`toiki`）で語尾が耳障りなく吐息へ溶ける |
| `damp` (`--damp`) | `0.30` | 声帯波帰還路の1極ローパス減衰 `0.0〜0.95`。高域コムのフランジャー櫛をほどき素の息の質感を残す |
| `shin` (`--shin`) | `1.0` | 声門扉と声道の再帰結合度 `0.0〜1.0`。`1.0`=非対称2唇粘膜扉×5極声道（既定）、`0.0`=同一ループ内で扉バイパス（冷凍ロボ） |
| `rate` (`--rate`) | `1.20` | 話速倍率（小さいほど速い）。`1.15`=速め、`1.20〜1.26`=自然な会話 |
| `jitter` (`--jitter`) | `0.0022` | 周期ごとの微細揺らぎ率。`0.0` にすると機械的なロボット声 |
| `wander_st` (`--wander`) | `0.16` | ピッチの緩やかな自然漂い幅（半音）。`0.0` で完全固定ピッチ |
| `combG` (opts のみ) | `0.985` | **サラサラ化**既定（soroe2）。有声のあいだ粘膜コム帰還を `combG × 有声度` に固定し、周期ごとの新規ノイズによるシマーを減らす（上限 `0.9995`）。`null` で `g_vo` 連動の非固定動作 |
| `rawAirMul` (opts のみ) | `0.6` | **サラサラ化**既定（soroe2）。扉を通る生ノイズ `rawAir` の倍率。`1.0` で非減衰 |
| `pau_iki` (opts・レシピのみ) | `-30` | **v11.0 読点の息の床**（dB、有声部 RMS 比）。読点の間を完全無音にせず、同じ原石ノイズの無声吐息（5極声道＋唇放射後）をうっすら残す。ReazonSpeech が読点を文末と取り違える後半落ちを防ぐ。`null` で v10.8 (`b9b5eb8`) とバイト一致。`chibi` はプリセットで `null` |
| `pau_s` (opts・レシピのみ) | `0.35` | 読点の間の長さ（秒）。`null` で 0.35。詰めると ReazonSpeech の後半落ちが増える（0.20 秒で悪化）ので非推奨 |
| `f0_st` (opts・レシピのみ) | `null` | ポーズ以外のモーラごとの F0 加減（半音）。`null` 要素はそのモーラを変えない。母音区間だけに掛かり、端は約 20ms の余弦ランプ。未指定時は既定音とバイト一致。話し声の強調ではアクセント核（`'`）を動かさず、既存の `vd_ms`（母音長）および `loud_db` と連動させる |
| `loud_db` (opts・レシピのみ) | `null` | ポーズ以外のモーラごとの母音ゲイン（dB）。`null` 要素はそのモーラを変えない。掛かり方は `f0_st` と同じ（母音区間、端のランプ）。未指定時は既定音とバイト一致。強調では `vd_ms`・`f0_st` と揃えて使う |
| `yurume_acc` (opts・レシピのみ) | `null` | 削りゆるめ①。`sigh >= 0.25` だけが理由で `ACCENT_NORMAL` に落ちていた起伏を `ACCENT_CUTE` へ戻す（`0〜1` で表を線形にまぜる、`1.0` で hz だけで表を選ぶ）。`hz < 200` は従来どおり NORMAL。`toiki` の F0 レンジ 3.83 → 6.88 半音。推奨 `1.0` |
| `yurume_toji` (opts・レシピのみ) | `null` | 削りゆるめ②。声門扉の閉じの速さ `closeMul`（v8 `7f09d18`、高い声ほど 22.0/周期）を開きの速さ 8.20/周期 へ寄せる（`1.0` で低音枝 `hiMix=0` と同じ閉じ方）。`0.5` で `chibi` の子音安定、`1.0` で軟閉鎖最大。推奨 `0.5`（本命 R3b@2.0）／`1.0`（比較用 R3c@1.5） |
| `yurume_tani` (opts・レシピのみ) | `null` | 削りゆるめ③。サラサラ既定 `combG=0.985` の一律ピン留め（`2859fff`/`a084abe`）を、プリセット自身の `g_vo` 連動くびれへ寄せる（`1.0` で `{combG: null}` と同じ帰還）。推奨 `0.5` |
| `yurume_bern` (opts・レシピのみ) | `null` | 削りゆるめ④。v8 `7f09d18` の高い声のベルヌーイ急閉鎖 `bern=0.55*hiMix` と閉鎖直後の気流遮断 `closedDecay=0.12` を低音枝（`0.0` / `0.50`）へ寄せる。`doorLp1` の応答を鈍らせず `yurume_toji` との相乗で軟閉鎖と子音明瞭度を両立。推奨 `1.0` |

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

- **かな入力と句切れ記号**: 読点 `、` は既定で0.35秒の間を入れ、その間に薄く息を残します。`pau_iki: null` で息の追加をオフにできます（`chibi` は既定でオフ）。半角空白または `/` は間を入れずに文節・アクセント句だけを切ります（`'` はアクセント核、`0` は平板、`?` は疑問上昇）。話し声モードでは `おう`→`おー`・`えい`→`えー` の長音同化が自動適用されます（歌モード `--uta` 時はモーラ数保持のため無効）。句末（`、`・半角空白・`/`・文末の直前）の助詞 `は` は自動で `ワ` に変換され、ベタ書き文中の `は` は誤変換防止のため `ハ` のまま残ります。

### LLMがコードを改造するときの鉄則（アンチパターン防止）
1. **帯域別 AGC を足さない**：各フォルマント帯域に個別正規化を入れると、`tilt_w` や声道の傾きが打ち消されて再度多段補正が必要になる。
2. **別系統の息ノイズ・固定波形を足さない**：息や揺らぎは別乱数や固定波形を加算するのではなく、Step 0 の1本のノイズ `x` とくびれ・扉の開閉だけで表現する。
3. **`hitofude.mjs` に Node 専用 `import` を入れない**：[`hitofude.mjs`](hitofude.mjs) はブラウザでもそのまま動く純粋 ES Module として保ち、ファイル入出力は [`yomu.mjs`](yomu.mjs) 側に置く。

## 改変履歴（抜粋）

- **yurume（任意ノブ整理）**: 削りすぎの削り落とし 4 ノブ（`yurume_acc` / `yurume_toji` / `yurume_tani` / `yurume_bern`、すべて既定 `null`＝7 プリセットとも `abb2dae` とバイト一致；`yurume_lo`・`yurume_q` は測定の結果不採用）。既存ノブ `damp: 0.16`・`rawAirMul` と組んだ本命は R3b@2.0 `{yurume_acc: 1.0, yurume_toji: 0.5, yurume_tani: 0.5, yurume_bern: 1.0, damp: 0.16, rawAirMul: 2.0}`（イタコ ASR 8091/8092 平均 7.3%/7.0% vs base 10.2%/9.6%）、比較用は R3c@1.5 `{..., yurume_toji: 1.0, rawAirMul: 1.5}`（8.3%/10.3%）。
- **v11.0**: 読点の息の床 `pau_iki: -30` を既定化（ReazonSpeech k2 の後半落ち 大人6声×3 seed で 6/18 → 2/18）、間の長さノブ `pau_s` 追加。`{pau_iki: null}` で v10.8 とバイト一致（`node tools/test_pause.mjs`）。`chibi` は従来の無音のまま。
- **v10.8** (`b9b5eb8`): ノイズ削りコードの断捨離＆単一因果ループ統合。
