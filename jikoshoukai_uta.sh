#!/bin/bash
# 月並みTTS 自己紹介ソング（7+7拍 × 4句 ＋ 決め台詞）
#   bash jikoshoukai_uta.sh [TAG] [--trance|--choir]
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PRE="uta_intro_"
for arg in "$@"; do
  case "$arg" in
    --trance) TRANCE=1 ;;
    --choir) CHOIR=1; TRANCE=1 ;;
    *) PRE="$arg" ;;
  esac
done
if [ -n "$CHOIR" ]; then TRANCE=1; fi
cd "$HERE"
mkdir -p out
hz(){ python3 -c "import sys;print(','.join(str(round(440*2**((int(k)-69)/12))) for k in sys.argv[1].split()))" "$1"; }
VD='260,260,260,260,260,260,560,260,260,260,260,260,260,820'
T=(
  'ワタシノナマエツキナミノコエ'
  'タダノランスウヨンジュウツブデ'
  'ニホンゴカナオパイソンデヨム'
  'ソノシクミサエパイソンデヨム'
)
M=(
  '60 62 64 67 67 64 62 64 65 67 69 67 64 62'
  '64 64 62 60 60 62 64 65 67 67 65 64 62 60'
  '67 69 67 64 65 67 69 67 65 64 62 64 62 60'
  '60 62 64 65 67 69 67 65 64 62 60 62 59 60'
)
EX_MODE=""
OUTRO_FLAGS=()
if [ -n "$TRANCE" ]; then
  EX_MODE=',"uta_trance":true'
  OUTRO_FLAGS=(--trance)
fi
if [ -n "$CHOIR" ]; then
  EX_MODE=',"uta_trance":true,"uta_choir":true'
  OUTRO_FLAGS=(--choir)
fi
for j in 0 1 2 3; do
  D=",\"P.vd_ms\":[$VD],\"rc.tadayoi\":0.0,\"line.D_haba\":0,\"uta_vib\":[5.5,22,220,280],\"uta_scoop\":[1.5,45],\"uta_hz\":[$(hz "${M[$j]}")],\"rc.yure_hayai\":0.02${EX_MODE}"
  IKI='[[1200,0],[2500,0],[5000,0],[8000,0]]' TV=120 GV=1,1 bash "$HERE/yomu2.sh" "${PRE}$j" "" "$D" "${T[$j]}" > "out/${PRE}$j.log" 2>&1 &
done
wait
python3 "$HERE/yomu.py" "${OUTRO_FLAGS[@]}" "わたし、にほんご、ちょっとしゃべれます" -o "out/${PRE}outro.wav"
echo "Generated out/${PRE}0_1.wav .. out/${PRE}3_1.wav and out/${PRE}outro.wav"
