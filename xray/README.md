# カワイイクサナギ 変態音響解析ツール 150選 (`xray/`)

**完全スタンドアロン純JS・外部依存ゼロ（親モジュール非依存・Node.js / ブラウザ ESM 両対応）** で、任意の音声（WAV）を **13カテゴリ・全150ツール** で多角的に丸裸にする音響X線スイートです。単体WAV比較に加え、マルチ発話・マルチピッチの自動品質ゲート付きスイート実行 (`--suite` / `--gate-strict`) に対応しています。

## クイックスタート

```bash
# 登録されている全150ツール一覧を表示
node xray/run.mjs

# 複数WAVを150軸で一括比較（1本目が比較基準になる）
node xray/run.mjs voice_a.wav voice_b.wav

# JSON出力（stdoutは純JSON保証）
node xray/run.mjs --json voice_a.wav voice_b.wav

# 全150ツール＋SVGビジュアルX線パネル入りHTMLレポートを一発生成
node xray/run.mjs --report report.html voice_a.wav voice_b.wav

# マルチ発話・マルチピッチ品質ゲート付きスイート実行（全ゲート合格で exit 0 / 失敗で exit 1）
node xray/run.mjs --suite suite_manifest.json --ref-wav hanamaru.wav --gate-strict --json

# 自己検証テスト（合成正解信号・エッジケース・スイート・実人声/回帰テスト）
node xray/test_xray.mjs
```

## ESM API (`xray/engine.mjs` / `xray/run.mjs` / `xray/suite.mjs`)

- **ブラウザ / 純JS ESM（`node:*` 非依存）**: `./xray/engine.mjs` から `ALL_TOOLS` / `analyzeBuffer` をインポートできます。
- **Node.js ESM（単体WAV＋スイートAPI）**: `./xray/run.mjs` から `ALL_TOOLS` / `analyzeBuffer` / `runSuite` / `DEFAULT_SAFETY_GATES` をインポートできます。

```js
// ブラウザ・Node共通（純JS・0依存）
import { ALL_TOOLS, analyzeBuffer } from "./xray/engine.mjs";

// Node.js スイートAPI込み
import { ALL_TOOLS, analyzeBuffer, runSuite, DEFAULT_SAFETY_GATES } from "./xray/run.mjs";

// 単体WAV解析 (ALL_TOOLS.length === 150)
const ref = analyzeBuffer(refWavBytes);
const cur = analyzeBuffer(wavBytes, ref.d, ref.metrics);

// マルチ発話スイート実行
const suite = runSuite(
  [{ id: "zrow_302", category: "voiced_sibilant", hz: 302, wav: "zrow_302.wav", gates: { vsib_coexist_pct: [">=", 35] } }],
  { refObj: ref }
);
// suite -> { items, rollups, gates, failures, passed }
```

## 入力WAV検証 & CLIバリデーション

- **厳格WAV検証 (`decodeWav`)**: `RIFF`/`WAVE` ヘッダ、`fmt `/`data` チャンク（順不同対応）、サンプルレート (`1..384000 Hz`)、チャンネル数 (`1..16`)、8/16/24/32-bit 整数PCM・32/64-bit IEEE float（非有限サンプル拒否）・`WAVE_FORMAT_EXTENSIBLE` (`0xFFFE`) を検証し、破損/非WAV入力は例外（CLI は exit `1`）で確実に拒否します。
- **スイート専用オプション**: `--ref-wav`、`--gate-strict`、`--no-default-gates` は `--suite <manifest.json>` との併用が必須です（単体指定や空引数は exit `1`）。

## スイートマニフェスト形式 (`suite_manifest.json`) & デフォルト安全ゲート

各エントリ: `{ id, category, hz?, wav, ref?, refWav?, gates?: Record<string, [">="|"<="|">"|"<", number] | null> }`（明示的 `id` の重複はエラー、`id` 省略時の同名ファイルは `name`, `name#2` ... へ自動一意化）

- **デフォルト安全ゲート (`DEFAULT_SAFETY_GATES`)**:
  - `artifact_risk_100 <= 12.0`
  - `cliff_all_ratio <= 55.0`
  - `max_sample_jump <= 6.0`
  - `pl_erb_rough_p90 <= 14.0`
  - `intelligibility_guard_100 >= 85.0`
- **8種の標準ロールアップ (`rollups`)**:
  `worst_artifact_risk_100`, `worst_cliff_all_ratio`, `worst_pl_erb_rough_p90`, `worst_max_sample_jump`, `worst_post_pause_rise_ms`, `min_vsib_coexist_pct`, `min_affr_closure_depth_db`, `min_intelligibility_guard_100`.

## 13カテゴリ・全150ツール一覧

| Cat | ファイル | # | 解析ドメイン | 代表的な指標 |
|---|---|---|---|---|
| 01 | `cat01_glottal.mjs` | #01–#10 | 声門・声帯ソース | `H1-H2`, `H1-A1`, `H1-A3`, `CPP`, `OQ推定`, `HRF`, `声門閉鎖尖度(med/p90)`, `語頭立ち上がり` |
| 02 | `cat02_artifacts.mjs` | #11–#20 | 異音・アーティファクト狩り | `帯域別HNR(4帯域)`, `非倍音固定ピー音`, `全活性フレーム1サンプル崖検知`, `フェイザーノッチ` |
| 03 | `cat03_vocal_tract.mjs` | #21–#30 | 声道・フォルマント・零点 | `F1/F2/F3`, `推定声道長VTL`, `IDS母音空間幅`, `笑顔声道`, `3kHz喉頭管`, `4.3kHz梨状窩ノッチ` |
| 04 | `cat04_phase.mjs` | #31–#40 | 位相・分散・微細構造 | `phase_stability`, `群遅延ゆらぎ`, `倍音位相ロック度`, `波形尖度/非対称度`, `周期再現率` |
| 05 | `cat05_prosody.mjs` | #41–#50 | ピッチ・カワイイ抑揚 | `tail_lift`, `f0_jitter`, `句末100msスクープ`, `下降勾配`, `4-7Hz微ビブラート`, `6-8Hz笑い脈動` |
| 06 | `cat06_breath.mjs` | #51–#60 | 息・吐息・有声息吸い | `有声の息吸い検知 (Ishi+ 2026)`, `非モーダル声質率`, `有声気息キープ率`, `4-8kHz平坦度` |
| 07 | `cat07_consonants.mjs` | #61–#70 | 子音・共調音・レガート | `摩擦音レンガ壁スコア`, `低域漏れ(<2.5kHz)`, `スペクトルフラックス`, `変調スペクトル(3-8/10-22Hz)` |
| 08 | `cat08_psycho.mjs` | #71–#80 | 心理音響・聴覚モデル | `brightness`, `Zwicker鋭さ(acum)`, `Plomp-Levelt ERB感覚粗さ統合`, `耳元度`, `耳刺さり指数` |
| 09 | `cat09_composite.mjs` | #81–#90 | 総合スコア＆A/B距離 | `総合カワイイ(異音上限付)`, `シンセ臭`, `異音警報(崖/粗さ統合)`, `現代アニメ度`, `スイートボイス`, `LSD/MCD` |
| 10 | `cat10_visual.mjs` | #91–#100 | ビジュアルX線レンダラー | `振幅/位相ロックSVG`, `LTAS/F0曲線`, `F1×F2散布図`, `赤旗/崖/粗さタイムライン`, `6軸レーダー`, `150本HTMLレポート` |
| 11 | `cat11_felony.mjs` | #101–#110 | 深淵非線形物理・RQA・TDA | `スペクトル可視性グラフ`, `TDAトーラス度`, `5点中央値RQA(ENTR/LAM)`, `バイコヒーレンス`, `TKEO渦`, `LPC声道断面積逆算` |
| 12 | `cat12_babaa.mjs` | #111–#130 | ババア検知20連反証センサー | `低域重さ`, `鼻声2k`, `2-4Hz老人性トレモロ(純度重み付)`, `乾きカスレ`, `過制御`, `ババア度総合指数` |
| 13 | `cat13_audit.mjs` | #131–#150 | 総合音質監査＆5大物理機構バリデータ | `PL-ERB粗さ(med/p90/18ch変調)`, `全サンプル崖/最大跳躍/C2躍度`, `句読点後立上がり/トー比`, `有声歯擦音/破擦音閉鎖・破裂`, `F4/F3F4上昇/F1F2直交`, `語尾RQA/ホップ溶解`, `F0 1/f^β`, `F1-F0調律`, `聞き取り安全ガード100` |
