#!/bin/zsh
# Double-click launcher for the trading dashboard control server.
# Starts server.py with --lan so it binds dual-stack on :: which is
# reachable at:
#   http://127.0.0.1:8787/      (local)
#   http://<your-LAN-IP>:8787/  (same WiFi)
#   http://100.71.94.40:8787/   (Tailscale — phone, iPad, other Macs)
# WITHOUT --lan the server is loopback-only and Tailscale gets refused.
cd "$(dirname "$0")"
exec /usr/bin/env python3 ".claude/skills/dashboard/server.py" --lan --open
