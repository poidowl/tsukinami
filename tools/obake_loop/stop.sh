#!/bin/zsh
# オバケ台帳ループを止める。走っとる周はその周の終わりで止まる（STOP 札）。--now で今の周も止める。
touch ~/itako_mimi/loop/STOP
launchctl bootout gui/$(id -u)/jp.nukumi.obake_daicho 2>/dev/null
rm -f ~/Library/LaunchAgents/jp.nukumi.obake_daicho.plist
if [ "$1" = "--now" ]; then pkill -f "itako_mimi/loop/(run_round|daihon_gen|soudan)" ; pkill -f "tools/kiku_eval.mjs --corpus /Users/p/itako_mimi/loop"; rmdir ~/itako_mimi/loop/lock 2>/dev/null; fi
echo "stopped"
