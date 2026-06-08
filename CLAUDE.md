# CLAUDE.md — auto-bootstrap + pointer to AGENTS.md

## Doctrine location

The operating doctrine lives in **[AGENTS.md](AGENTS.md)** — the cross-agent standard so both Claude Code and Codex auto-load the same instructions. Read AGENTS.md first; it defines mission, risk doctrine, phased ramp, and output format.

## Auto-bootstrap (do this at session start, without being asked)

After loading AGENTS.md, in a fresh session you must also read these files **before responding to the operator's first request**:

1. **`notes/learned.md`** — known gotchas (XProtect, FMP paywall, yfinance edge cases). Don't re-discover landmines we already mapped.
2. **`CHANGELOG.md`** — specifically the `[Unreleased]` section (anything in flight from the last session) and the most recent shipped version (so you know what "now" looks like).
3. **`git log --oneline -10`** — last 10 commits for recent activity context.

Then orient yourself out loud with **three short bullets**:
- Current version (latest tag from changelog)
- Most recent shipped change (one line from the latest version's release notes)
- Anything in `[Unreleased]` still in flight (one line, or "nothing pending")

Keep this orientation under ~5 lines total. Then wait for the operator's actual request. The orientation tells the operator you're caught up; it isn't a status report — they wrote what's in those files, they don't need it read back to them.

**Do NOT auto-read `PROJECT_LOG.md`** — it's heavy (~600 lines, architecture + setup + replication guide). Read it on demand when a question requires architectural context. For most session tasks, AGENTS.md + notes/learned.md is enough.

**Do NOT auto-read `notes/ideas.md` or `notes/decisions.md`** — read these only when relevant ("decisions" when the operator asks "why is X like this?", "ideas" when proposing new features).

## Skip the bootstrap when

Skip the auto-bootstrap and respond immediately to the operator if:
- The operator opens with **`quick:`** or **`oneshot:`** prefix (signals a small unrelated question)
- The session is resumed via `claude --resume` (you already have continuity from the prior session)
- The operator's first message is already a status check ("what version are we on?" — just answer, don't pre-bootstrap)

## End-of-session ritual

Before the operator clears or closes the session **mid-task**, write an `### In flight` paragraph to `CHANGELOG.md` `[Unreleased]` explaining what's pending and the next step. The next session's auto-bootstrap will pick it up. If the operator forgets, prompt them once: *"Want me to capture an in-flight note before you clear?"*
