# scripts/

Operator-side utilities. **None of these are required to use the project** — they're conveniences for the maintainer's local setup.

## `sync-backup.sh`

Pushes the local `main` branch (plus tags) to a separate `backup` remote — intended for a private personal backup repo that's separate from the canonical public repo.

### One-time setup

```bash
# 1. Create a private GitHub repo (or use any git host)
gh repo create trading-advisor-backup --private --description "Private personal backup of trading-advisor"

# 2. Add it as a second git remote called `backup`
git remote add backup https://github.com/YOUR_USERNAME/trading-advisor-backup.git

# 3. Verify
git remote -v
# Should show: origin (public) + backup (private)
```

### Manual usage

```bash
./scripts/sync-backup.sh
# Logs to .git/sync-backup.log
```

If there are no new commits since the last run, the script exits cleanly with "Everything up-to-date" in the log.

## `com.kenson.trading-advisor-backup.plist`

A macOS LaunchAgent that runs `sync-backup.sh` automatically every hour (and once at load time). **Installing it is a deliberate maintainer choice; the script also works fine as a manual or cron-driven job on other platforms.**

### Install (macOS)

```bash
# 1. Edit the plist if your project path is different from the default
#    (currently hardcoded to /Users/aiagent/Documents/Claude/Projects/Trading Advisor/)
$EDITOR scripts/com.kenson.trading-advisor-backup.plist

# 2. Copy into your user LaunchAgents directory
cp scripts/com.kenson.trading-advisor-backup.plist ~/Library/LaunchAgents/

# 3. Load it (registers + starts the agent)
launchctl load -w ~/Library/LaunchAgents/com.kenson.trading-advisor-backup.plist

# 4. Verify it's registered
launchctl list | grep trading-advisor-backup
# Should show a line ending in com.kenson.trading-advisor-backup

# 5. Tail the log to confirm the first run worked
tail -f .git/sync-backup.log
```

### Pause / uninstall

```bash
# Pause (keep installed but stop running)
launchctl unload ~/Library/LaunchAgents/com.kenson.trading-advisor-backup.plist

# Permanently remove
launchctl unload ~/Library/LaunchAgents/com.kenson.trading-advisor-backup.plist
rm ~/Library/LaunchAgents/com.kenson.trading-advisor-backup.plist
```

### Adjust frequency

Edit `StartInterval` in the plist (value is seconds):

| Interval | Value |
|---|---|
| Every 15 minutes | `900` |
| Every 30 minutes | `1800` |
| Every hour (default) | `3600` |
| Every 4 hours | `14400` |
| Every 12 hours | `43200` |

After editing, reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.kenson.trading-advisor-backup.plist
launchctl load -w ~/Library/LaunchAgents/com.kenson.trading-advisor-backup.plist
```

### Linux / WSL equivalent (cron)

```bash
# Add this line to your crontab (crontab -e) for hourly runs
0 * * * * /path/to/trading-advisor/scripts/sync-backup.sh
```

### What it does NOT do

- **Does not auto-commit uncommitted work-in-progress.** Only pushes what's already committed. If you want WIP backed up, run `git commit` to checkpoint it first.
- **Does not push to the public `origin` remote** — only to `backup`. Public releases stay deliberate and version-tagged.
- **Does not modify any project file.** The script is read-only against the repo (only `git push` is invoked).
