#!/bin/zsh
# 关亡婆の実データ集め 1 回分（launchd jp.nukumi.atsume が 10 分おき）。低優先度・8090 を守る・容量上限つき。
# 1) 8090 が空いとれば关亡婆に新しい台本 1 本（daihon/） 2) kusanagi で N 本読ませて 16 kHz wav＋かなラベル（data/, ledger.jsonl）
# 3) 8092/8091 で K 本書き取り（asr.jsonl）。止めるには touch STOP。
A=$HOME/itako_mimi/atsume; L=$HOME/itako_mimi/loop
NODE=$HOME/itako_kusanagi/node/bin/node
N=${N:-240}; K=${K:-40}; CAP_GB=${CAP_GB:-15}; MIN_FREE_GB=${MIN_FREE_GB:-25}
log() { echo "$(date '+%F %T') $*" >> $A/logs/atsume.log; }
[ -f $A/STOP ] && exit 0
if ! mkdir $A/lock 2>/dev/null; then
  if [ -n "$(find $A/lock -maxdepth 0 -mmin +30 2>/dev/null)" ]; then rmdir $A/lock; mkdir $A/lock || exit 0; else exit 0; fi
fi
trap 'rmdir $A/lock 2>/dev/null' EXIT
[ -d $L/lock ] && { log "skip: obake loop round running"; exit 0; }
if /usr/sbin/lsof -nP -iTCP:8188 -sTCP:LISTEN >/dev/null 2>&1 || /usr/bin/pgrep -f ComfyUI >/dev/null; then log "skip: ComfyUI"; exit 0; fi
FREE=$(/usr/bin/memory_pressure | /usr/bin/tail -1 | /usr/bin/grep -o '[0-9]*' | /usr/bin/tail -1)
[ "${FREE:-0}" -lt 20 ] && { log "skip: memory free ${FREE}%"; exit 0; }
USED_KB=$(/usr/bin/du -sk $A/data | /usr/bin/cut -f1); DISK_FREE_KB=$(/bin/df -k $HOME | /usr/bin/tail -1 | /usr/bin/awk '{print $4}')
if [ $USED_KB -ge $((CAP_GB*1024*1024)) ]; then log "cap reached: data $((USED_KB/1024)) MB >= ${CAP_GB} GB — 集めるのを止めとる"; exit 0; fi
if [ $DISK_FREE_KB -lt $((MIN_FREE_GB*1024*1024)) ]; then log "skip: disk free $((DISK_FREE_KB/1024/1024)) GB < ${MIN_FREE_GB} GB"; exit 0; fi
probe() { /usr/bin/curl -s -m 8 -o /dev/null -w "%{time_total}" localhost:8090/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"default_model","messages":[{"role":"user","content":"一言"}],"max_tokens":4}' || echo 9; }
P0=$(probe)
NEW=()
if (( P0 < 0.5 )); then
  C=$A/daihon/atsume_$(date +%Y%m%d_%H%M%S).json
  G=$(nice -n 15 $L/venv/bin/python $A/daihon_gen.py $C 2>>$A/logs/atsume.err); rc=$?
  log "daihon rc=$rc $G"
  [ $rc = 0 ] && [ -s $C ] && NEW=(--new $C)
else log "8090 busy ($P0 s): 台本はお休み、読ませるだけ"; fi
R=$(cd $A && nice -n 15 $NODE atsume.mjs --n $N --workers 2 $NEW 2>>$A/logs/atsume.err); log "render $R"
P1=$(probe)
if (( P1 < 0.5 )); then S=$(cd $A && nice -n 15 $HOME/kana/bin/python asr_pass.py $K 2>/dev/null | tail -1); log "asr $S"; else log "8090 busy ($P1 s): 書き取りはお休み"; fi
