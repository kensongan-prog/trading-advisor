#!/bin/zsh
# Double-click launcher for the trading dashboard control server.
# As of 2026-07-07 the server runs under launchd (ai.hermes.trading-advisor-dashboard,
# GG-8-owned, KeepAlive) instead of being started per-session from this script. This
# wrapper just makes sure that service is up, then opens a browser tab — it no longer
# spawns its own server process, so closing this window does NOT stop the dashboard.
# Reachable at:
#   http://127.0.0.1:8789/      (local)
#   http://<your-LAN-IP>:8789/  (same WiFi)
#   http://100.71.94.40:8789/   (Tailscale — phone, iPad, other Macs)
launchctl print gui/502/ai.hermes.trading-advisor-dashboard >/dev/null 2>&1 \
  || launchctl bootstrap gui/502 /Users/aiagent/Library/LaunchAgents/ai.hermes.trading-advisor-dashboard.plist
launchctl kickstart gui/502/ai.hermes.trading-advisor-dashboard >/dev/null 2>&1
sleep 1
open "http://127.0.0.1:8789/"
