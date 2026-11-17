#!/bin/bash
# 長い歌（自前の詞と節、4 句）。
#   bash nagauta.sh TAG [MJ.npz]
#   MJ.npz を省略または "" にすると第1段（標準ライブラリのみ）で歌い、MJ.npz を渡すと第2段まで回して歌う。
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PRE=$1; MJ="${2:-}"
if [ -n "$MJ" ] && [ -f "$MJ" ]; then MJ="$(cd "$(dirname "$MJ")" && pwd)/$(basename "$MJ")"; fi
cd "$HERE"
hz(){ python3 -c "import sys;print(','.join(str(round(440*2**((int(k)-69)/12))) for k in sys.argv[1].split()))" "$1"; }
VD='280,280,280,280,280,280,600,280,280,280,280,280,280,900'
T=('アサノヒカリガマドオタタクヨ' 'キョウモイッショニウタオウタオウ' 'ソラワアオクテカゼモヤサシイ' 'ネエネエミンナデワライマショウ')
M=('60 62 64 64 62 60 62 64 65 67 67 65 64 62' '64 64 62 60 60 62 64 65 65 64 62 62 60 60' '67 67 65 64 64 65 67 65 64 62 62 64 62 60' '60 62 64 65 67 67 64 62 62 64 62 60 59 60')
for j in ${LINES:-0 1 2 3}; do
  D=",\"P.vd_ms\":[$VD],\"rc.tadayoi\":0.0,\"line.D_haba\":0,\"uta_vib\":[5.5,20,250,300],\"uta_hz\":[$(hz "${M[$j]}")],\"rc.yure_hayai\":0.02$NEX"
  IKI='[[1200,0],[2500,0],[5000,0],[8000,0]]' TV=120 GV=1,1 bash "$HERE/yomu2.sh" "${PRE}$j" "$MJ" "$D" "${T[$j]}" > "${PRE}$j.log" 2>&1 &
done; wait
