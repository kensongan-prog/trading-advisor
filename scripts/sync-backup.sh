#!/bin/bash
# Sync the local main branch + tags to the private backup remote.
# Runs from any directory; figures out the repo root from its own location.
#
# Safe to run any time:
# - If there's nothing new to push, exits silently
# - If the backup remote is unreachable, logs the error and exits non-zero (visible to launchd)
# - Never touches origin (public canonical repo); only pushes to `backup`

set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO_ROOT/.git/sync-backup.log"
cd "$REPO_ROOT" || exit 2

# Use a fixed PATH so launchd-spawned shells find git + gh
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

{
  echo "[$(ts)] sync-backup starting (cwd=$REPO_ROOT)"
  # Verify backup remote exists
  if ! git remote get-url backup >/dev/null 2>&1; then
    echo "[$(ts)] ERROR: 'backup' remote not configured. Run: git remote add backup <url>"
    exit 3
  fi
  # Push main (with tags). --force-with-lease is safer than --force.
  if git push backup main --follow-tags 2>&1; then
    echo "[$(ts)] OK: pushed main + tags to backup"
  else
    echo "[$(ts)] ERROR: push failed (see error above)"
    exit 4
  fi
} >> "$LOG" 2>&1
