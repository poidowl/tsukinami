#!/bin/zsh
# オバケ台帳ループ 1 周: 关亡婆(8090)が台本 → kusanagi が読む → 耳(mimi, kiku-ear) が書き取る → 台帳に足す → N 周ごとに关亡婆が要約と提案。
# launchd (jp.nukumi.obake_daicho) が 20 分おきに呼ぶ。耳の表(mimi_table.json)は一切書き換えん。提案だけ。
L=$HOME/itako_mimi/loop
# 耳と声の版は ear_commit.txt / tts_commit.txt に書く（r3 から: 耳 = kiku-ear-r3 の中身、声 = その中の hitofude.mjs = kusanagi b205f58）。
# 耳を差し替えるときは、新しい中身を $L/ear_<版> に置いて ear_commit.txt を書き換えるだけ（周の合間に stop.sh → start.sh）。
EAR_COMMIT=${EAR_COMMIT:-$(cat $L/ear_commit.txt)}; TTS_COMMIT=${TTS_COMMIT:-$(cat $L/tts_commit.txt)}
EAR=$L/$(cat $L/ear_dir.txt 2>/dev/null || echo ear_${EAR_COMMIT})   # ear_dir.txt があればその dir（声だけ差し替えた混ぜ dir 用）
NODE=$HOME/itako_kusanagi/node/bin/node
PY=$L/venv/bin/python
DAICHO=$HOME/itako_mimi/obake_daichou.jsonl
DIGEST_EVERY=${DIGEST_EVERY:-6}
log() { echo "$(date '+%F %T') $*" >> $L/logs/loop.log; }
[ -f $L/STOP ] && exit 0
# 鍵（同時に 2 周走らせん）。40 分より古い鍵は死んだ周の残りとみなす
if ! mkdir $L/lock 2>/dev/null; then
  if [ -n "$(find $L/lock -maxdepth 0 -mmin +40 2>/dev/null)" ]; then rmdir $L/lock; mkdir $L/lock || exit 0; log "stale lock removed"; else log "skip: lock"; exit 0; fi
fi
trap 'rmdir $L/lock 2>/dev/null' EXIT
# 画像生成(ComfyUI)中や、メモリがきついときは休む
if /usr/sbin/lsof -nP -iTCP:8188 -sTCP:LISTEN >/dev/null 2>&1 || /usr/bin/pgrep -f ComfyUI >/dev/null; then log "skip: ComfyUI running"; exit 0; fi
FREE=$(/usr/bin/memory_pressure | /usr/bin/tail -1 | /usr/bin/grep -o '[0-9]*' | /usr/bin/tail -1)
if [ "${FREE:-0}" -lt 15 ]; then log "skip: memory free ${FREE}%"; exit 0; fi
C=$L/daihon/round_$(date +%Y%m%d_%H%M%S).json
G=$(nice -n 10 $PY $L/daihon_gen.py $C 2>>$L/logs/loop.err); rc=$?
log "daihon rc=$rc $G"
[ $rc -ne 0 ] && exit 0
SID=$($PY -c "import json,sys;print(json.load(open('$C'))['scripts'][0]['id'])")
SEED2=$(( RANDOM % 9000 + 1000 ))
cd $EAR
nice -n 15 $NODE tools/kiku_eval.mjs --corpus $C --split loop --ear mimi --workers 2 --seeds 2024,$SEED2 \
  --wavdir $L/wav/$SID --ledger $L/out/$SID.ledger.jsonl --out $L/out/$SID.json --round $SID --label loop-mimi-$(cat $L/ear_round.txt 2>/dev/null || echo r3) \
  --kusanagi hitofude@kusanagi-$TTS_COMMIT --kiku kiku@$EAR_COMMIT --mimi mimi-$(cat $L/ear_round.txt 2>/dev/null || echo r3)@$EAR_COMMIT > $L/out/$SID.txt 2>>$L/logs/loop.err
rc=$?
# 台帳へ: 声の版(tts_commit)と耳の版(ear_commit)を別の列で足す
[ -f $L/out/$SID.ledger.jsonl ] && $PY -c "
import json,sys
with open('$DAICHO','a') as f:
    for l in open('$L/out/$SID.ledger.jsonl'):
        if l.strip(): r=json.loads(l); r['tts_commit']='$TTS_COMMIT'; r['ear_commit']='$EAR_COMMIT'; f.write(json.dumps(r,ensure_ascii=False)+'\\n')
" && rm $L/out/$SID.ledger.jsonl
SC=$($PY -c "import json;d=json.load(open('$L/out/$SID.json'));print(json.dumps(d['score'].get('loop|全体'),ensure_ascii=False), d['sec'],'s')" 2>/dev/null)
log "eval rc=$rc $SID seeds=2024,$SEED2 score=$SC"
# 古い wav は 3 日で片づける（台帳の G_params と seed で同じ音が作り直せる：kusanagi は決定的）
find $L/wav -mindepth 1 -maxdepth 1 -type d -mtime +3 -exec rm -rf {} + 2>/dev/null
# N 周ごとに关亡婆の要約と提案
N=$(ls $L/out/loop_*.json 2>/dev/null | wc -l | tr -d ' ')
LAST=$(cat $L/last_digest_n 2>/dev/null || echo 0)
if [ $(( N - LAST )) -ge $DIGEST_EVERY ]; then
  D=$(nice -n 15 $NODE $L/digest.mjs $DAICHO $L/digest 2>>$L/logs/loop.err); log "digest $D"
  if [ -n "$D" ]; then
    T=$(nice -n 10 $PY $L/soudan.py $D 2>>$L/logs/loop.err) && { echo $N > $L/last_digest_n; log "teian $T"; } || log "teian failed/skipped: $T"
  fi
fi
