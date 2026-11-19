# 仕様：イタコASRループ（tsukinami hitofude）

## 目的
hitofude の式は変えずに、パラメータだけを動かして ASR の聞き取りの点を上げる。
式を見つける・書き換えるのは大きい LLM（Carbon）か P の役。このループは「見つけた式の評価を、パラメータをいじって高める」だけを受け持つ。

## 役割
- 作る：hitofude（Python が正本。速さが要るなら Node の JS エンジン）
- 聞く：ASR。关亡婆 (M6 Mac mini 32GB) に、すでに 8091 (Qwen3-ASR-1.7B) と 8092 (parakeet-tdt_ctc-0.6b-ja) が動いている。LLM の 8090 とはポートが分かれている。
- つまみ係：関亡婆の 8090、Qwen3-30B-A3B-Instruct-2507-4bit。呼ぶときの model は必ず `default_model`（他の名前を出すと 30B が降ろされる）。点と履歴を見て、次に試すパラメータを決める。
- 採点：スクリプト（LLM には採点させない）。2つの ASR の点は文ごとに悪いほう（CER が高いほう）を公式の点にする。

## 1回の流れ
1. つまみ係がパラメータの組を出す（範囲の外は端に丸める）
2. 決まった文の一覧を合成して wav にする
3. ASR で文字にする
4. 元の文と比べて点を出す（かな文字の誤り率 CER。低いほど良い）
5. 結果を1行の JSONL で追記する
6. 1 に戻る

## 決まりごと
- hitofude.py の式には触らない。動かすのはプリセットの数値だけ。
- 文の一覧は「調整用」と「確認用」に分ける。確認用の点は、つまみ係には見せない（ASR だけをだまくらかす方向に寄るのを見張るため）。
- ASR は既定で2つつなぐ（8091 と 8092）。点はそれぞれ記録し、公式の点は文ごとに悪いほうを使う。k2 (`~/asr/k2_transcribe.py`) は参考用で、既定のループには入れない。
- 乱数の種と文の一覧は固定する。同じパラメータなら同じ点が出ること。
- 節目ごとに上位の音を P が耳で聞く。P の評価も JSONL に残す。
- JS 側を更新したら tools/check_js_parity.py を通してから使う。
- 採点の前に、ASR出力と元の文を同じかな変換にかける。既定は関亡婆の `~/kana/bin/python` の pyopenjtalk（`g2p(..., kana=True)`）。警告が標準出力に出るので、本物の行には `@@` を付けて拾う。古い pykakasi 経路は `--kana-backend pykakasi` のときだけ使う。
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
既定の ASR 2本（8091 と 8092）のまま、パラメータを3つ（例：hz, fscale, rate）だけに絞って、10回だけ回して流れを確かめる。

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

### 2. 关亡婆（M6 Mac mini 32GB）での ASR / LLM 構成と実行手順

8090 / 8091 / 8092 はカフカが入れたサーバーがすでに待っている。`tools/itako_asr_server.py` を 8091 や 8092 で立てないこと（Qwen3-ASR / parakeet と衝突する）。8093 はオバケ wav の読み取り専用配信（`/Users/p/obake_serve`）用なので、ここでも立てない。やむを得ずこの予備サーバーを使うときは既定の 8094 を使う。mlx-whisper は使わない。

| ポート | 中身 | 待ち受け | 呼び方 |
| --- | --- | --- | --- |
| 8090 | Qwen3-30B-A3B-Instruct-2507-4bit (`mlx_lm.server`) | 0.0.0.0（LAN 可） | `POST /v1/chat/completions`、`"model": "default_model"` |
| 8091 | Qwen3-ASR-1.7B-8bit | 127.0.0.1 のみ | `POST /v1/audio/transcriptions` |
| 8092 | parakeet-tdt_ctc-0.6b-ja | 127.0.0.1 のみ | 同上 |
| 8093 | obake_serve（wav 読み取り専用） | 0.0.0.0（LAN 可） | `GET /index` と許可ファイルのみ |
| 8094 | `tools/itako_asr_server.py` の既定（予備。关亡婆では通常立てない） | 127.0.0.1 | `POST /transcribe` |

ASR の送り方は JSON `{"path": "/Users/p/…/x.wav"}`（同じマシンならこちらが速い）か、multipart の `file`。返りは `{"text", "sec", "load_sec", "peak_gb"}`（`model` も付く）。`GET /health` で生きているか確認できる。読めるのは WAV と FLAC だけ（ffmpeg が無いので mp3 は不可）。アイドル 300 秒でモデルは降りる。接続が切れたり断られたりしたら、ループ側が 1・2・4・8 秒と空けて、合わせて約 90 秒までやり直す。1回の待ち上限は 120 秒以上。

起動・停止（ループからは触らない。再起動後は手で上げる）:

```bash
# 8090 は別途 mlx_lm.server
~/asr/start.sh        # 8091 / 8092
~/asr/stop.sh
```

システムの `python3` と `git` は关亡婆では使わない。uv の環境（`~/asr`、`~/mlx`、かな変換は `~/kana`）を使う。

#### 最初の一歩（パラメータ3つ・10回）

ASR サーバーは起動済み前提。ループは关亡婆の上で回す（8091/8092 は 127.0.0.1 だけを待つ）。

```bash
# システムの python3 は使わない。tsukinami を回せる uv の環境で:
python tools/itako_asr_loop.py \
  --llm-url http://127.0.0.1:8090/v1 \
  --llm-model default_model \
  --knobs hz,fscale,rate \
  --max-iters 10

# 高速 Node エンジンで回す場合（自動で tools/check_js_parity.py を通してから開始）:
python tools/itako_asr_loop.py \
  --synth node \
  --llm-url http://127.0.0.1:8090/v1 \
  --llm-model default_model \
  --knobs hz,fscale,rate \
  --max-iters 10
```

`--asr` を省略すると、既定で次の2本を使う:

- `http://127.0.0.1:8091/v1/audio/transcriptions`
- `http://127.0.0.1:8092/v1/audio/transcriptions`

LLM の JSON が読めなければ 1 回だけやり直す。範囲外のつまみは許容範囲の端に丸める。

#### P の耳評価を JSONL に残すコマンド

ベースライン（`iter_000_baseline`）と最良更新時の WAV は `out/itako_wavs/` に自動保存される。試聴後の評価は以下のコマンドで同じ JSONL に1行追記できる:

```bash
python tools/itako_asr_loop.py \
  --log out/itako_asr_log.jsonl \
  --rate-iter 4 \
  --p-score 4 \
  --p-note "パ行・カ行が聞き取りやすく、声の芯も残っている"
```

### 3. クレジット

本ループの既定 ASR のひとつ **parakeet-tdt_ctc-0.6b-ja**（NVIDIA、MLX 版は `mlx-community/parakeet-tdt_ctc-0.6b-ja`）は [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) です。公開物や配信でこの認識器を使うときは、そのクレジットを残すこと。

- https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja
- https://huggingface.co/mlx-community/parakeet-tdt_ctc-0.6b-ja

Qwen3-ASR-1.7B は Apache-2.0。
