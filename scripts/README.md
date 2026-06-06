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

### Scheduled usage (Claude-managed)

The maintainer's setup uses Claude Code's built-in scheduler (`CronCreate`) to run this script on a daily schedule. To set it up in your own Claude Code session, ask Claude:

> "Set up a daily backup task that runs `./scripts/sync-backup.sh` from this project. Use CronCreate with durable=true, recurring=true, at a reasonable work-hour time, and remind me to re-schedule it before the 7-day expiry."

The scheduler is session-aware: jobs only fire while a Claude Code session is open. If you go several days without opening Claude Code, the backup won't fire — re-open Claude and the next scheduled tick will catch up.

**Limitations of the Claude scheduler:**
- Jobs auto-expire after 7 days (need to re-schedule weekly)
- Jobs only fire while Claude is running and the REPL is idle
- If Claude is closed at fire time, the run is skipped (not queued)

### Scheduled usage (system cron — alternative for headless setups)

If you want the backup to run even when Claude isn't open, you can add a system cron entry (any platform with cron):

```bash
crontab -e
# Add this line for daily 8:23am local:
23 8 * * * /full/path/to/trading-advisor/scripts/sync-backup.sh
```

This option exists for completeness; the project maintainer prefers the Claude-managed approach.

### What it does NOT do

- **Does not auto-commit uncommitted work-in-progress.** Only pushes what's already committed. If you want WIP backed up, run `git commit` to checkpoint it first.
- **Does not push to the public `origin` remote** — only to `backup`. Public releases stay deliberate and version-tagged.
- **Does not modify any project file.** The script is read-only against the repo (only `git push` is invoked).
