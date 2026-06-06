---
name: journal
description: Journal lifecycle CLI — flip a prospectus's Status field through PROSPECTUS → LIVE → CLOSED (or DEAD), append timestamped Updates entries, and auto-fill the Exit section with realized R-multiple on close. Use whenever a user reports a trigger filling, a position closing, or a setup expiring — instead of hand-editing the journal markdown. Source of truth remains journal/*.md; CLI provides atomic writes with backups and consistent formatting that the dashboard's prospectus parser keys on.
---

# Journal Lifecycle CLI

## When to use

Trigger this skill when the user says:

- "AUPH triggered, fill at $X"
- "Mark the AUPH trade live"
- "Close the AUPH trade — TP1 hit at $17.65"
- "AUPH stopped out at $14.26"
- "AUPH trigger never fired, mark it dead"
- "Add a note to the AUPH journal"

Do NOT trigger this skill for:
- Creating a new journal entry from scratch (that's still manual — the file structure is too rich for a CLI template; write the prospectus in editor)
- Reading the full journal entry contents (use Read tool directly)

## Why this exists

Journal `**Status:**` fields drive the dashboard's Active Prospectuses panel. Hand-editing them risks formatting drift (the parser keys on the bold marker + first sentence-ish chunk) and missed Exit-section fills on close. This CLI:

- Updates Status field atomically with a backup
- Appends a timestamped `## Updates` bullet with one consistent format
- On close, auto-fills `## Exit` with date, exit price, realized R-multiple, and TODO prompts for the post-mortem fields
- Validates the file exists, the result is valid, the R is a number

## Subcommands

### `live` — flip Status to LIVE (paper or real)

```bash
python3 .claude/skills/journal/j.py live <id> [--paper | --real] \
    [--fill PRICE] [--shares N] [--time "YYYY-MM-DD HH:MM ET"] [--notes "..."] [--yes]
```

Status becomes `LIVE — paper` or `LIVE — real`. An Updates bullet is appended with the fill details.

### `update` — append a timestamped Updates note (no status change)

```bash
python3 .claude/skills/journal/j.py update <id> --notes "Scaled half at TP1 $17.65, trailing remainder"
```

### `close` — flip Status to CLOSED + fill Exit section

```bash
python3 .claude/skills/journal/j.py close <id> --result {win|loss|scratch|timeout} --r R_MULTIPLE \
    [--price EXIT_PRICE] [--notes "..."] [--yes]
```

Status becomes `CLOSED — {result} (±R.RRR)`. Exit section is rewritten with date, exit price, realized R, and TODO prompts for "Process correct?", "Outcome lucky?", "Lesson."

### `dead` — flip Status to DEAD (missed trigger / setup expired)

```bash
python3 .claude/skills/journal/j.py dead <id> --reason "Trigger never fired by 2-week setup expiry"
```

### `list` / `show` — read-only views

```bash
python3 .claude/skills/journal/j.py list                                  # all entries with status
python3 .claude/skills/journal/j.py list --status prospectus              # filter
python3 .claude/skills/journal/j.py show <id>                             # Status + Updates + Exit
```

## File identification

Pass `<id>` as a ticker (`AUPH`), a full stem (`2026-06-03_AUPH`), or a filename (`2026-06-03_AUPH.md`). If a ticker matches multiple files, the CLI errors with a disambiguation list — pass the stem.

## Hard rules

1. **Confirmation by default.** Every write asks before committing. `--yes` to skip.
2. **Atomic writes + backups.** Each edit writes to `.claude/cache/journal_backups/{stem}_{ts}.md` first, then atomically replaces. Microsecond timestamps so back-to-back edits don't collide.
3. **Rotating backups.** Keep last 10 per file. Older are pruned.
4. **R-multiple is required on close.** No silent "what was the R?" — the doctrine needs every trade's realized R for the 20-trade phase gate.
5. **Status string follows convention.** The dashboard parser is forgiving (it matches "prospectus" / "live" / "pending" / "closed" / "dead" substrings) but the CLI writes the canonical forms: `PROSPECTUS`, `LIVE — paper`, `LIVE — real`, `CLOSED — win (+R.RR R)`, `DEAD — reason`.
6. **No journal entry creation.** Use a text editor + the existing AUPH journal as a template.

## Dashboard integration

The dashboard's "Active Prospectuses" panel renders six action buttons per card: **Live paper · Live real · Update · Close win · Close loss · Mark dead**. Clicking a button copies the pre-formed CLI command (with the file stem filled in but with `_PLACEHOLDER_` tokens for fill price, R, notes, etc.) to your clipboard. You paste it in a terminal, replace the placeholders with real values, and run.

This is the same model as the dashboard's main Refresh button — static HTML can't write to your filesystem, but it can hand you the right command to run.

## See also

- `README.md` in this directory — user-facing guide with examples
- Backups live in `.claude/cache/journal_backups/`
