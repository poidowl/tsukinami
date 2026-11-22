# atsume — kusanagi 実データ集め（关亡婆）
P 2026-11-22 16:53「关亡婆、kusanagiの実データいっぱい集めといて」。
- launchd `jp.nukumi.atsume` が 10 分おきに `atsume.sh`（nice 15・Background・LowPriorityIO）。止める: `zsh stop.sh` / 動かす: `zsh start.sh`。
- 1 回分: ①8090 の返りが 0.5 秒未満なら关亡婆に台本 1 本（daihon/atsume_*.json、id の md5 で test/tune）②kusanagi（engine/ = 声 da87173）で 240 本読ませる：新しい台本は全行×7 プリセット、残りは全台本からランダム行×プリセット×ランダム seed ③8090 が空いとれば 8092/8091 で 40 本書き取り（1 本 3 秒超えたら打ち切り）。
- オバケ台帳ループの周の最中・ComfyUI 中・メモリ空き 20% 未満は休む。
- 置き場: `data/<tts_commit>/<台本id>/<id>.wav`（16 kHz mono 16-bit）、ラベル `ledger.jsonl`（kana=台本のかな、spoken=声が実際に読むかな=耳の正解、preset, seed, split, tts_commit）、書き取り `asr.jsonl`（parakeet / qwen3 の text・kana・CER）。
- 上限: data/ が 15 GB で止まる（CAP_GB）。ディスク空きが 25 GB を切っても止まる。
- 声を替えたら engine/ と tts_commit.txt を差し替える（data/ は版ごとに分かれる）。
