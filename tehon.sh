#!/bin/bash
# 手本を一件足す入口（天邪鬼TTS / 月並みTTS の学習パイプライン）。
#   bash tehon.sh hanashi SID     喋りの手本（wav/{SID}_*.wav と meta{SID}.json から mijikaiF_{SID}.npz・tani_{SID}.json・mijikaiF_m{k}.npz を作る）
#   bash tehon.sh uta 名前 a.wav  歌の手本（伴奏なしの独唱WAVから歌い回しの数字を一行 uta_hyou.jsonl に足す）
set -e
cd "$(dirname "$0")"
P="${PY:-python3} -W ignore"
LIST=tehon_sids.txt
[ -f "$LIST" ] || touch "$LIST"
case "$1" in
  hanashi)
    SID=$2
    if [ -z "$SID" ]; then echo "Usage: bash tehon.sh hanashi <SID>"; exit 1; fi
    if [ ! -f "mijikaiF_$SID.npz" ]; then
      SID="$SID" $P featF.py | tail -1
      WHO="$SID" $P mijikai_full.py | tail -1
      rm -f "unitsF$SID.pkl"
    fi
    $P tani.py "$SID" | tail -1
    grep -qw -- "$SID" "$LIST" || echo "$SID" >> "$LIST"
    SIDS="$(tr '\n' ' ' < "$LIST")" $P suki3.py;;
  uta)
    $P uta_hakaru.py "$2=$3" | grep '{';;
  *)
    sed -n 2,4p "$0";;
esac
