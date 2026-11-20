# tsukinami (`kusanagi` branch — Pure JavaScript Edition)

> **約79KBのピュアJavaScript（`.py` ゼロ）で、たった1本のホワイトノイズから日本語かな・歌を彫る。ブラウザでも Node.js でもそのまま鳴り、LLMの1コンテキストで丸ごと読める。**  
> 外部パッケージ不要・外部データファイル不要・Python互換ギプスなし・本体2ファイル計 1,881行（78.8 KB）。

**[ブラウザで声を聴く](https://poidowl.github.io/tsukinami/kusanagi.html)** — 「▶ 彫って鳴らす」を押すと、吐息の声で「わたし、にほんご、ちょっとしゃべれます」と読み上げます。

`hitofude`（一筆彫り）から Python 依存と互換用の乱数・丸めギプスをすべて外し、純粋な ES Module 2本（エンジン [`hitofude.mjs`](hitofude.mjs) ＋ CLI [`yomu.mjs`](yomu.mjs)）にまとめた「草薙（kusanagi）」ブランチです。

## 1. コンテキスト投入コマンド ＆ Raw URL（全コード一括）

本体の実装は以下の2ファイルだけで完結しています（`README.md` 込み合計 約87 KB）：

```bash
cat README.md hitofude.mjs yomu.mjs
```

Web取得型LLMには、以下の **Raw プレーンテキスト URL 3本**を渡してください：
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/README.md
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/hitofude.mjs
- https://raw.githubusercontent.com/poidowl/tsukinami/kusanagi/yomu.mjs

| ファイル | 行数 | 役割 |
| :--- | ---: | :--- |
| [`hitofude.mjs`](hitofude.mjs) | 1,607行 | **純JS音源・声道・調音・韻律エンジン（`import` ゼロ）**：かな→5ms軌道 `tracksFromKana`、東京式アクセント `f0Rule`、非対称ベルヌーイ粘膜扉×5極声道の単一乱数再帰合成 `makeHitofude`、WAV出力 `encodeWav`、FFT音響計測 `hakaru`（ブラウザ `<script type="module">` と Node.js 両対応） |
| [`yomu.mjs`](yomu.mjs) | 274行 | **Node.js CLI & レシピドライバ**：プリセット合成、`--measure` 自己計測、`--compare` 音響指標差分、`--uta` 歌唱、引数バリデーション（既定出力は上書きしない連番 `out/yomu_NNN_<preset>.wav`） |
| [`tools/build_x_player.mjs`](tools/build_x_player.mjs) | 補助 | [`hitofude.mjs`](hitofude.mjs) から X Player Card / GitHub Pages 用の単一HTML（`kusanagi.html` + `kusanagi_player.html`）を直接生成（公開URL: https://poidowl.github.io/tsukinami/kusanagi.html ） |

---

## 2. 信号処理の構造（1本のノイズ信号線 × 非対称ベルヌーイ粘膜扉 ＆ 5極声道再帰）

正弦波オシレータ（`sin/cos` 音源）、固定波形の粒スタンプ、STFT往復、40段オールパス、帯域別 AGC、別シード乱数はすべて廃止しています。**音になる有声・吐息・子音だけでなく、ピッチの自然漂い・周期ジッタ・歌唱ビブラート・呼気圧のゆらぎに至るまで、すべて Step 0 の 1本のホワイトノイズ `x` だけ**から削り出します。

```text
x = rng.uniform(-1, +1) × N   # [-1, +1] の一様ホワイトノイズ（乱数源はこの1本だけ）
  │
  ▼ 【統合粘膜再帰 Step ①–③ (shin = 1.0: 女声・アルト・ちびっ子・囁き・おっさん・歌)】
  │    ・① 声帯組織波: 声道の出口＆F1からの帰還圧を受けながら、2段コム＋高域dampで滑らかに声帯波が揺れる
  │    ・② 非対称ベルヌーイ2唇扉: 上唇は丸くめくれて開き、下唇は気流吸い寄せ×粘膜ソフトクッションでフランジャー櫛なく呼気流を刻む
  │         → 扉が閉じた瞬間に倍音位相が揃い、句末 (sigh > 0) は扉を緩めて元の吐息へほどける
  │    ・③ 5極粘膜声道: F1→F2→F3→F4→F5 直列カスケード（開扉時は肺ダンプ連動）＋唇微分放射 ＋ 子音・ハ行帯 yamaBp
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
| `hz` (`--hz`) | `326.0` | 基準ピッチ高さ Hz。女声 `290〜340`、アルト `220`、ちびっ子 `375`、低音男声 `105〜155` |
| `fscale` (`--fscale`) | `1.12` | フォルマント周波数倍率（声道長の逆数）。女声 `1.07〜1.12`、アルト `1.02`、ちびっ子 `1.20`、男声 `0.85` |
| `g_vo` (`--g-vo`) | `0.895` | 有声くびれ深さ $G \in [0, 0.97)$。`0.895`=澄んだ声、`0.77`=低音轟、`0.68`=半有声囁き |
| `tilt_w` (`--tilt`) | `5` | 粗削り移動平均幅（最初の零点 `SR / tilt_w` Hz）。`4〜5`=標準、`6`=落ち着いた吐息、`>=8`=暗声 |
| `sigh` (`--sigh`) | `0.0` | 句末母音後半（`u > 0.30`）での扉解放量 `0.0〜1.0`。`0.42`（`toiki`）で語尾が耳障りなく吐息へ溶ける |
| `damp` (`--damp`) | `0.30` | 声帯波帰還路の1極ローパス減衰 `0.0〜0.95`。高域コムのフランジャー櫛をほどき素の息の質感を残す |
| `shin` (`--shin`) | `1.0` | 声門扉と声道の再帰結合度 `0.0〜1.0`。`1.0`=非対称2唇粘膜扉×5極声道（既定）、`0.0`=冷凍ロボ片道コム |
| `rate` (`--rate`) | `1.20` | 話速倍率（小さいほど速い）。`1.15`=速め、`1.20〜1.26`=自然な会話 |
| `jitter` (`--jitter`) | `0.0022` | 周期ごとの微細揺らぎ率。`0.0` にすると機械的なロボット声 |
| `wander_st` (`--wander`) | `0.16` | ピッチの緩やかな自然漂い幅（半音）。`0.0` で完全固定ピッチ |
| `combG` (opts のみ) | `null` | サラサラ化オプション。数値（例: `0.985`、上限 `0.9995`）を渡すと有声中の粘膜コム帰還を `combG × 有声度` に固定。既定 `null` は `g_vo` に素直に従う |
| `rawAirMul` (opts のみ) | `1.0` | 扉を通る生ノイズ `rawAir` の倍率オプション（例: `0.6` でさらに抑制） |

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

- **かな入力と句切れ記号**: 読点 `、` は無音の間（ポーズ）を入れ、半角空白または `/` は間を入れずに文節・アクセント句だけを切ります（`'` はアクセント核、`0` は平板、`?` は疑問上昇）。話し声モードでは `おう`→`おー`・`えい`→`えー` の長音同化が自動適用されます（歌モード `--uta` 時はモーラ数保持のため無効）。句末（`、`・半角空白・`/`・文末の直前）の助詞 `は` は自動で `ワ` に変換され、ベタ書き文中の `は` は誤変換防止のため `ハ` のまま残ります。

### LLMがコードを改造するときの鉄則（アンチパターン防止）
1. **帯域別 AGC を足さない**：各フォルマント帯域に個別正規化を入れると、`tilt_w` や声道の傾きが打ち消されて再度多段補正が必要になる。
2. **別系統の息ノイズ・固定波形を足さない**：息や揺らぎは別乱数や固定波形を加算するのではなく、Step 0 の1本のノイズ `x` とくびれ・扉の開閉だけで表現する。
3. **`hitofude.mjs` に Node 専用 `import` を入れない**：[`hitofude.mjs`](hitofude.mjs) はブラウザでもそのまま動く純粋 ES Module として保ち、ファイル入出力は [`yomu.mjs`](yomu.mjs) 側に置く。
