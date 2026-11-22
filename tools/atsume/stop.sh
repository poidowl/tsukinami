#!/bin/zsh
touch ~/itako_mimi/atsume/STOP
launchctl bootout gui/$(id -u)/jp.nukumi.atsume 2>/dev/null; echo stopped
