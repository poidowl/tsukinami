#!/bin/bash
# bash yomu2.sh TAG [MJ.npz] ['extra json（頭にカンマ、無ければ空）'] 文1 文2 ...
#   MJ.npz が空（""）のとき：第1段（Python標準ライブラリのみの土台削り器）で out/TAG_{j}.wav を出力
#   MJ.npz を渡したとき：第1段 → erabu_mijikaiF.py で96帯目標軌道を生成 → 第2段の2段削りで out/TAG_{j}.wav を出力
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG=$1; MJ=$2; EX=$3; shift 3
P="${PY:-python3} -W ignore"
export OUT="${OUT:-$HERE/out}"
export SWAP="${SWAP:-$HERE/swap}"
mkdir -p "$OUT" "$SWAP"
if [ -n "$MJ" ] && [ -f "$MJ" ]; then MJ="$(cd "$(dirname "$MJ")" && pwd)/$(basename "$MJ")"; fi
cd "$HERE"
export TEXTS=$($P -c "import json,sys;print(json.dumps(sys.argv[1:],ensure_ascii=False))" "$@")
S0=$(cat "$HERE/S.txt"); OO=$(cat "$HERE/OO.txt"); V0='"vbump":{"a":[1,1.2,1],"e":[0.7,1.3,0.7],"o":[1,1.3,0.8],"i":[0.25,3.0,3.0]}'
if [ -z "$MJ" ] || [ "$MJ" = "none" ]; then
  $P "$HERE/mkt.py" "$TAG" "{$S0,$V0,$OO$EX}" 2>&1 | tail -1
  exit 0
fi
MO=1 $P "$HERE/mkt.py" "${TAG}b" "{$S0,$V0,$OO$EX}" 2>&1 | tail -1
OR=""; j=0
for t in "$@"; do
  j=$((j+1))
  env MJ="$MJ" MODE=mean NOUV=1 OROW=1 VAR=a GV="${GV:-1.4,1.1}" $P "$HERE/erabu_mijikaiF.py" "${TAG}s$j" "$t" "$OUT/${TAG}b_$j.wav" "$SWAP/mo_${TAG}b_$j.json" | tail -1
  rm -f "$SWAP/${TAG}s$j.wav"
  OR="$OR,\"$SWAP/orow_${TAG}s$j.json\""
done
OR="[${OR:1}]"
PTS="${IKI:-[[1200,0],[2500,0.1],[5000,0.4],[8000,0.7],[9000,0.7],[11000,0]]}"
$P "$HERE/mkt.py" "$TAG" "{$S0,$V0,$OO$EX,\"henv\":{\"low\":false,\"tab\":null,\"warp\":false,\"fc\":150,\"xp\":8,\"keep_hi\":9000,\"up\":{\"flo\":1200,\"fhi\":8000,\"pk\":4,\"q\":120,\"depth\":1.0,\"top\":1.0,\"b23\":0,\"sm_ms\":5,\"lev_ms\":30,\"cmute\":0,\"cdil\":0,\"uv\":true,\"ref\":[400,800],\"orow\":$OR},\"up2\":{\"flo\":150,\"fhi\":8000,\"pk\":4,\"q\":120,\"depth\":1.0,\"top\":1.0,\"b23\":0,\"sm_ms\":5,\"lev_ms\":30,\"cmute\":0,\"cdil\":0,\"orow\":$OR}},\"iki\":{\"pts\":$PTS}}" 2>&1 | tail -1
