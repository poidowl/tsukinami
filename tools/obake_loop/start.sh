#!/bin/zsh
# オバケ台帳ループを動かす（20 分おき）。
rm -f ~/itako_mimi/loop/STOP
cp ~/itako_mimi/loop/jp.nukumi.obake_daicho.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/jp.nukumi.obake_daicho 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/jp.nukumi.obake_daicho.plist && echo "started (20分おき)"
