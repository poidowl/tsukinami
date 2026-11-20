# Hodoki ザラザラ調べ（草薙 v8 hitofude）

草薙 v8（kusanagi `7f09d18`）の hitofude 声がザラザラ（シマー高・HNR 低・周期類似低め）に聞こえる元を、段を 1 つずつ切って Hodoki soroi で測った記録と、opt-in の対策。

- `hitofude_lab.mjs` … `hitofude.mjs` の実験用コピー。`opts.lab` で段を切り替える。`lab={}` なら本体と同一波形（`test_zarazara.mjs` で hitofude/ossan/robot の maxdiff 0 を確認）。草薙本体と既定値は変えていない。
- `kurabe.mjs` … 切り替え表（文「わたし、にほんご、ちょっとしゃべれます」＋持続母音「ア」2 秒 350 Hz ビブラート 0）。シマーを有声区間の端 60 ms 以内（端）とそれ以外（定常）に分けても出す。
- `naoshi.mjs` … 対策 soroe1 / soroe2 の前後比較（seed 2024, 7, 99 の平均）と「読める」の代理指標。
- `yomeru.mjs` … 読める代理：ケプストラム包絡距離（dB）と michi の F1–F3 軌跡の差。ASR は使っていない（tsukinami のイタコ ASR は関亡婆＝ニューラルのため）。

## lab スイッチ
`noRawAir` 扉を通る生ノイズ rawAir·x を 0 ／ `rawAirMul` その倍率 ／ `combG` 有声時のコム帰還を固定値に ／ `combLock` コム入力を位相固定ノイズ（同じ x を周期位相で読む）に混ぜる割合 ／ `airLock` rawAir 側の同じもの ／ `idealDoor` 扉を位相だけで決まる半余弦パルスに ／ `noTanh` コム帰還の tanh を外す ／ `noLoad` 声道→扉の負荷帰還を切る ／ `doorBwOff` 扉による帯域幅の広がりを切る ／ `noLungWalk` 肺圧の漂いを一定に ／ `noEnvWander`・`noGsWander` 漂いによる音量／コム利得のゆれを切る。

## 対策（opt-in）
- `soroe1 = { combG: 0.99 }`
- `soroe2 = { combG: 0.985, rawAirMul: 0.6 }`

どちらも一本のノイズ x をコムと共鳴の引き算で削る作りのまま（別の音源を足していない）。使い方：`makeHitofude(text, { ...PRESETS.hitofude, lab: { combG: 0.99 } })`（`hitofude_lab.mjs` から）。

結果の数字は `/workspace/hodoki/zarazara/kurabe.json`・`naoshi.json`（ボックス上）と報告を参照。
