#!/bin/zsh
# Double-click launcher for the trading dashboard control server.
# Starts server.py on localhost:8787 and opens the browser.
cd "$(dirname "$0")"
exec /usr/bin/env python3 ".claude/skills/dashboard/server.py" --open
