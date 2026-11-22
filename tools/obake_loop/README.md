# オバケ台帳ループ（回すのは关亡婆、育てるのはナグリ）

关亡婆（M6）が 20 分おきに 1 周まわす:

1. **台本**: 8090（Qwen3-30B-A3B）が新しい台本を 1 本（8 行前後）書く。お題と「耳の苦手どころ」（長音・ん/に・拗音・っ・ら行・母音連続）から 2 つを毎回くじ引き。読みは janome（itako_kana.py と同じ下ごしらえ）。→ `loop/daihon/`
2. **読む**: kusanagi（**b205f58**＝kusanagi ブランチ 2026-11-21 12:45 JST 版の hitofude.mjs、純 JS）がプリセット 6 × seed 2（2024 ＋ 毎回くじの初見 seed）で読む。→ `loop/wav/<台本id>/`（3 日で片づける。kusanagi は決定的なので G_params と seed から作り直せる）
3. **聞く**: 耳 = mimi r3（kiku-ear-r3 の mimi.mjs ＋ mimi_table.json、kusanagi b205f58 の声で育て直した。確認用かな 90.6%）。中身は `loop/ear_<耳の版>/`（hitofude.mjs = 声も同じ dir）。版は `loop/ear_commit.txt` / `loop/tts_commit.txt` / `loop/ear_round.txt` に書く。r2 のころの混ぜ dir `loop/ear_cd293c8_tts_b205f58/` は残してある。`tools/kiku_eval.mjs --split loop --ear mimi`。
4. **台帳**: 1 発話 1 行で `~/itako_mimi/obake_daichou.jsonl` に足す（列 A〜L ＋ 耳の記録。`run` は `loop-mimi-r2@…`、正解 seikai＝kusanagi が実際に読んだかな、kiku＝耳の書き取り、I_kana_cer、wav_path、preset、seed、H_commit、**tts_commit**＝声の版、**ear_commit**＝耳の版）。17:35 より前のループ行は tts_commit=cd293c8 を後から足した（元は obake_daichou.jsonl.bak_20261121_1735）。
5. **要約と提案**: 6 周ごと（約 2 時間）に `digest.mjs` が前回からの行（いちばん新しい行と同じ tts_commit・ear_commit の行だけ）を集計 → `soudan.py` で关亡婆が聞き間違いの型と耳の育て方の提案を書く。→ `loop/digest/digest_loop_NNN.json`, `teian_loop_NNN.json`

**耳は自動では変えない。** mimi_table.json もコードも触らん。提案を読んで、何を耳に入れるかはナグリが決める。

## 8090 を詰まらせない工夫（測った）
- 8090 は 1 本ずつしか処理せん。400 トークンを 1 回で頼むと約 6 秒ふさがり、その間の問い合わせは 5.6 秒待たされた（局の kome_henji は 3 秒で諦める）。
- そこで `kotodama.py` が 1 回 48 トークン（0.4〜1 秒）に切って、間に 1.2 秒（重かった直後は 3.6 秒）あけて続きを頼む。長い入力は前から少しずつ prompt cache に載せる。
- 測った値: 台本づくり中の 8090 の返り 最大 0.45 秒。提案づくり（約 66 秒・30 回）中 最大 1.03 秒。3 秒超え 0 回。
- 周の前に 8090 に 4 トークン聞いて 1.5 秒より遅ければ、その周は休む。ComfyUI（8188）が動いとる時、メモリの空きが 15% 未満の時も休む。
- 書き取りは nice 15・2 並列・launchd の Background で、1 周 40 秒ほど。

## 動かす / 止める
```
~/itako_mimi/loop/start.sh        # launchd jp.nukumi.obake_daicho を入れる（20 分おき）
~/itako_mimi/loop/stop.sh         # 止める（走っとる周はその周の終わりで止まる）
~/itako_mimi/loop/stop.sh --now   # 今の周も止める
zsh ~/itako_mimi/loop/run_round.sh  # 手で 1 周
DIGEST_EVERY=1 zsh ~/itako_mimi/loop/run_round.sh  # 手で 1 周＋要約と提案
```
ログ: `loop/logs/loop.log`（周ごとの 1 行）、`loop/logs/loop.err`。鍵: `loop/lock`（40 分より古いのは消す）。

## ファイル
- `loop/kotodama.py` 8090 への細切れ問い合わせ（＋測るとき用の見張り）
- `loop/daihon_gen.py` 台本 → corpus（split=loop）
- `loop/run_round.sh` 1 周
- `loop/digest.mjs` 台帳 → 集計
- `loop/soudan.py` 集計 → 提案
- `loop/repo_cd293c8/` kiku-ear cd293c8 の中身（codeload から。耳を育てたら、ここを差し替えて run_round.sh の EAR / EAR_COMMIT を直す）
- `loop/venv/` uv の venv（janome）
- 昔の 1 回きりの材料: `digest_r1.json`, `teian_r1*.json`, `itako_soudan.py`, `mihari.sh`, `s8094.*`

## 声を b205f58 に上げたとき（2026-11-21 17:35）
同じ 3 本の台本・同じ seed を声だけ替えて読ませた比較（耳は cd293c8 のまま）: かな 88.6% → 44.3%、母音 95.2% → 70.7%。
耳が旧い声（非対称ベルヌーイ扉）だけで育っとるので、新しい声（折れ角ゼロ粘膜扉×実寸声道、プリセットの hz/fscale/damp も変更）には合わん。耳を育て直すかはナグリが決める。

## 耳を r3 に上げたとき（2026-11-21）
r3（K 64・minf 0.8、b205f58 の声で育て直し）: 確認用 かな 90.6% / 母音 95.6%（同じ声で r2 は 46.3 / 70.0）。作り方と下見の表は tsukinami `kiku-ear-r3` の `docs/hentai_mimi_rounds.md`、作業場所は `~/itako_mimi/r3/`。
- 声だけ替えて耳はそのままにしたいときは、`$L/ear_dir.txt` に混ぜ dir の名前（例 `ear_b933e6c_tts_da87173`）を書く。無ければ `ear_<ear_commit>`。
- `soudan.py` は关亡婆の JSON がこわれとっても（`\6` のような変な `\`、制御文字）甘めに読み直す。読めたら `_parse_fixed` に元のエラーを残す。
