# 仕様：イタコASRループ（tsukinami hitofude）

## 目的
hitofude の式は変えずに、パラメータだけを動かして ASR の聞き取りの点を上げる。
式を見つける・書き換えるのは大きい LLM（Carbon）か P の役。このループは「見つけた式の評価を、パラメータをいじって高める」だけを受け持つ。

## 役割
- 作る：hitofude（Python が正本。速さが要るなら Node の JS エンジン）
- 聞く：ASR。M6 Mac mini 32GB（イタコ）に置く。8090 の Qwen3-14B とはポートを分ける。
- つまみ係：イタコの Qwen3-14B。点と履歴を見て、次に試すパラメータを決める。
- 採点：スクリプト（LLM には採点させない）

## 1回の流れ
1. つまみ係がパラメータの組を出す（範囲の外は弾く）
2. 決まった文の一覧を合成して wav にする
3. ASR で文字にする
4. 元の文と比べて点を出す（かな文字の誤り率 CER。低いほど良い）
5. 結果を1行の JSONL で追記する
6. 1 に戻る

## 決まりごと
- hitofude.py の式には触らない。動かすのはプリセットの数値だけ。
- 文の一覧は「調整用」と「確認用」に分ける。確認用の点は、つまみ係には見せない（ASR だけをだまくらかす方向に寄るのを見張るため）。
- ASR は2つ以上つなぐのが望ましい。点はそれぞれ記録し、平均で選ぶ。
- 乱数の種と文の一覧は固定する。同じパラメータなら同じ点が出ること。
- 節目ごとに上位の音を P が耳で聞く。P の評価も JSONL に残す。
- JS 側を更新したら tools/check_js_parity.py を通してから使う。
- 採点の前に、ASR出力と元の文を同じかな変換・同じ揃え方（句読点と空白を消す、長音を統一）にかける。揃え方はスクリプトに固定する。
- hakaru の値が、いまのプリセットを測って決めた枠の外に出た組は失格にする。
- つまみ係に渡す履歴は、いちばん良かった5件と直近5件、それにパラメータの範囲だけにする。

## 記録（1行ずつ追記）
回の番号、時刻（JST）、パラメータ、文ごとの ASR の文字起こし、調整用の CER、確認用の CER、hakaru の値、git のコミット

## 止めどき
- 決めた回数を回し切ったとき
- 調整用の点だけが良くなって、確認用の点が悪くなりだしたとき

## 置き場所
- コードはリポジトリの tools/ か新しいフォルダに置く。作業場だけに置かない。
- 報告に書くリンクは GitHub の URL にする。/home/... は P から開けない。

## 最初の一歩
ASR を1つ、パラメータを3つ（例：hz, fscale, rate）だけに絞って、10回だけ回して流れを確かめる。

---

## 実装詳細と実測テーブル

### 1. 現行6プリセットの `hakaru` 実測値と失格枠（`utt_00` 基準）
基準文 `utt_00`（`わたし、にほんご、ちょっとしゃべれます`, `seed=2024`）を `yomu.py` の現行6プリセットすべてで合成して実測した値と、その `[最小, 最大]` に固定マージン（スペクトル・クレスト `±1.5 dB`、倍音の谷深さ `±2.5 dB`）を足した失格判定枠：

| プリセット / 枠 | `crest_db` | `band_1k_2k6_db` | `band_2k6_5k6_db` | `tani_core_db` | `tani_tail_db` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `hitofude` | `15.4` | `-2.1` | `-4.8` | `39.3` | `39.9` |
| `toiki` | `15.7` | `-4.8` | `-8.0` | `39.8` | `19.3` |
| `sasayaki` | `16.4` | `-3.6` | `-8.0` | `24.5` | `17.4` |
| `chibi` | `15.3` | `+0.4` | `-3.1` | `38.2` | `36.5` |
| `ossan` | `16.8` | `-4.9` | `-6.3` | `17.0` | `15.3` |
| `robot` | `15.9` | `-2.7` | `-2.7` | `24.4` | `29.7` |
| **6プリセット実測 `[min, max]`** | **`[15.3, 16.8]`** | **`[-4.9, +0.4]`** | **`[-8.0, -2.7]`** | **`[17.0, 39.8]`** | **`[15.3, 39.9]`** |
| **失格枠 (`DEFAULT_HAKARU_GATE_UTT0`)** | **`[13.8, 18.3]`** | **`[-6.4, +1.9]`** | **`[-9.5, -1.2]`** | **`[14.5, 42.3]`** | **`[12.8, 42.4]`** |

- 6プリセットはすべて合格し、`tilt_w=2`（金属的な高域過多 `band_2k6_5k6_db = +0.2 dB`）や `tilt_w=9`（こもり過ぎ `-16.4 dB`）、ピッチ崩壊（`hz=120, fscale=0.82` で `tani_core_db = 13.5 dB`）は枠外として即座に `disqualified: true` になる。
- プリセット定義を将来更新した場合は `--remeasure-hakaru-gate` で起動時に再計測できる。

### 2. イタコ（Mac mini 32GB）での ASR 構成と実行手順
`Qwen3-14B` が `:8090` を使っているため、`tools/itako_asr_server.py` は `:8090` の指定を起動時に拒否し、`:8091` / `:8092` で待ち受ける。実際の常駐メモリ量（`maxrss_mb`）はモデルの大きさ・量子化に依存するため、推測値ではなく起動時および初回推論完了時に `itako_asr_server.py` が実測値を標準出力と `/health` に出す。

#### 最初の一歩（ASR 1つ・パラメータ3つ・10回）
```bash
# 1) イタコ側パッケージ導入（かな変換器 pykakasi + Apple Silicon 用 mlx-whisper）
pip install mlx-whisper pykakasi

# 2) ターミナル1: ASR サーバーを :8091 で起動（初回推論時に実測 maxrss_mb を表示）
python3 tools/itako_asr_server.py \
  --port 8091 \
  --backend mlx-whisper \
  --model mlx-community/whisper-large-v3-turbo \
  --name mlx-large-v3-turbo

# 3) ターミナル2: 3パラメータ (hz, fscale, rate) だけで 10回ループ実行
#    正本 Python で回す場合（既定）:
python3 tools/itako_asr_loop.py \
  --asr http://127.0.0.1:8091/transcribe \
  --llm-url http://127.0.0.1:8090/v1 \
  --knobs hz,fscale,rate \
  --max-iters 10

#    高速 Node エンジンで回す場合（自動で tools/check_js_parity.py を通してから開始）:
python3 tools/itako_asr_loop.py \
  --synth node \
  --asr http://127.0.0.1:8091/transcribe \
  --llm-url http://127.0.0.1:8090/v1 \
  --knobs hz,fscale,rate \
  --max-iters 10
```

#### 第2の ASR を足す場合（異種アーキテクチャ 2審判）
Whisper 系の自己回帰デコーダ特有の言語モデル補完に引っ張られるのを防ぐため、2つ目には非自己回帰 CTC 系の `sherpa-onnx` (`SenseVoiceSmall`) を `:8092` に並べ、`--asr` を2回渡す：
```bash
python3 tools/itako_asr_server.py \
  --port 8092 \
  --backend sherpa-sensevoice \
  --model /path/to/sherpa-onnx-sense-voice-zh-en-ja-ko-yue \
  --name sensevoice-small

python3 tools/itako_asr_loop.py \
  --synth node \
  --asr http://127.0.0.1:8091/transcribe \
  --asr http://127.0.0.1:8092/transcribe \
  --llm-url http://127.0.0.1:8090/v1 \
  --knobs hz,fscale,rate \
  --max-iters 10
```

#### P の耳評価を JSONL に残すコマンド
ベースライン（`iter_000_baseline`）と最良更新時の WAV は `out/itako_wavs/` に自動保存される。試聴後の評価は以下のコマンドで同じ JSONL に1行追記できる：
```bash
python3 tools/itako_asr_loop.py \
  --log out/itako_asr_log.jsonl \
  --rate-iter 4 \
  --p-score 4 \
  --p-note "パ行・カ行が聞き取りやすく、声の芯も残っている"
```
