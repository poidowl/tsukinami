#!/bin/zsh
rm -f ~/itako_mimi/atsume/STOP
cp ~/itako_mimi/atsume/jp.nukumi.atsume.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/jp.nukumi.atsume 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/jp.nukumi.atsume.plist && echo "started (10分おき)"
