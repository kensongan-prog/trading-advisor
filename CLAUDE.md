# CLAUDE.md — auto-bootstrap + pointer to AGENTS.md

## Doctrine location

The operating doctrine lives in **[AGENTS.md](AGENTS.md)** — the cross-agent standard so both Claude Code and Codex auto-load the same instructions. Read AGENTS.md first; it defines mission, risk doctrine, phased ramp, and output format.

## Auto-bootstrap (do this at session start, without being asked)

After loading AGENTS.md, in a fresh session you must also do these things **before responding to the operator's first request**:

1. **`notes/learned.md`** — known gotchas (XProtect, FMP paywall, yfinance edge cases). Don't re-discover landmines we already mapped.
2. **`CHANGELOG.md`** — specifically the `[Unreleased]` section (anything in flight from the last session) and the most recent shipped version (so you know what "now" looks like).
3. **`git log --oneline -10`** — last 10 commits for recent activity context.
4. **`.venv-playwright/bin/python3 -m pytest --tb=line -q`** — run the test suite (uses the project-local venv since pytest isn't installed system-wide). Should complete in <1s with all tests passing. If any fail, the codebase is in a known-broken state — flag this prominently in the orientation and do NOT make code changes until the operator decides how to handle it. If the venv is missing (fresh clone), say so and ask the operator before assuming tests don't matter.

Then orient yourself out loud with **three short bullets + a test-status line**:
- Current version (latest tag from changelog)
- Most recent shipped change (one line from the latest version's release notes)
- Anything in `[Unreleased]` still in flight (one line, or "nothing pending")
- Tests: `N/N passing` (or `N failing — needs attention before code changes`)

Keep this orientation under ~5 lines total. Then wait for the operator's actual request. The orientation tells the operator you're caught up; it isn't a status report — they wrote what's in those files, they don't need it read back to them.

**Why the test step matters:** v2.0.5 codified a contract — every bug fix leaves a regression test behind. A test failure at session start means either someone introduced a regression since the last green commit, or the test suite has drifted from current code reality. Either case is worth a beat before adding more code on top.

**Do NOT auto-read `PROJECT_LOG.md`** — it's heavy (~600 lines, architecture + setup + replication guide). Read it on demand when a question requires architectural context. For most session tasks, AGENTS.md + notes/learned.md is enough.

**Do NOT auto-read `notes/ideas.md` or `notes/decisions.md`** — read these only when relevant ("decisions" when the operator asks "why is X like this?", "ideas" when proposing new features).

## Skip the bootstrap when

Skip the auto-bootstrap and respond immediately to the operator if:
- The operator opens with **`quick:`** or **`oneshot:`** prefix (signals a small unrelated question)
- The session is resumed via `claude --resume` (you already have continuity from the prior session)
- The operator's first message is already a status check ("what version are we on?" — just answer, don't pre-bootstrap)

A **bare greeting** ("Hi", "hello", "hey", "yo") is NOT a skip trigger — it still counts as message #1, so run the bootstrap and give the 3-bullet orientation before replying. Don't suppress it for being polite/short.

## End-of-session ritual

Before the operator clears or closes the session **mid-task**:

1. **Run `.venv-playwright/bin/python3 -m pytest --tb=line -q`** one last time. If tests are red, either fix them or capture that fact in the in-flight note — don't leave the next session walking into broken tests without warning.
2. **Write an `### In flight` paragraph** to `CHANGELOG.md` `[Unreleased]` explaining what's pending and the next step. The next session's auto-bootstrap will pick it up. If the operator forgets, prompt them once: *"Want me to capture an in-flight note before you clear?"*
3. **Sync the knowledge vault** for every meaningful change shipped this session — **don't ask whether to, just do it** (skip only when nothing material shipped). See "Keep the knowledge vault in sync" below. This mirrors AGENTS.md's end-of-session ritual so Claude and Codex stay consistent.

## Keep the knowledge vault in sync

An Obsidian knowledge vault mirrors this project for cross-agent (Claude + Codex) and human navigation: **`/Volumes/Mac Mini SSD/Projects/Vaults/Claude Codex Vault/Trading Advisor/`** (entry point `00 — Trading Advisor Home.md`; on an external volume — `/Volumes/Mac Mini SSD` must be mounted to reach it). The **repo is the source of truth; the vault is a synthesized, navigable index** — when they disagree, the repo wins. It lives **outside this git repo**, so vault edits are not part of repo commits.

When you ship a meaningful change, mirror it into the vault — same discipline as the CHANGELOG entry, so it doesn't drift. Map the change to the note that owns it:
- New/changed skill → `Architecture — Skills Catalog`
- New regression test or test-count change → `Architecture — Tests`
- New gotcha/landmine → `Gotchas & Landmines` (the vault twin of `notes/learned.md`)
- Architecture or rationale change → the relevant `Architecture — *` / `Decisions Log`
- Version bump or live-state change → `00 — Trading Advisor Home` + the relevant `State — *` note

Follow the vault's own **`Vault Guide — Contributing.md`**: edit the owning note **in place** (don't duplicate), bump its `updated:` frontmatter, keep `source:` honest, and run the wikilink-verification script at the bottom of that guide. Synthesize — don't paste whole source files.

## Before any release (PATCH / MINOR / MAJOR)

Run the test suite. A green commit is the floor for shipping; releases inherit that floor. If you cut a tag against a red suite, you've broken the v2.0.5 contract — fix the tests first or hold the release.

**For MINOR and MAJOR releases additionally:** update `PROJECT_LOG.md` (the replication/handover guide) to reflect the new capability — new skill/tool row, new env var, new convention — before tagging. Edit its sections in place; the changelog owns history, the log describes *now*. PATCH releases don't touch it. (Rule added 2026-06-11 after the log drifted from v1.3 to v2.1.0 unmaintained.)
