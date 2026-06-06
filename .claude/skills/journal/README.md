# Journal Lifecycle CLI — User Guide

Move journal entries through their trade lifecycle (`PROSPECTUS → LIVE → CLOSED`) without hand-editing the markdown. Updates and Exit sections fill themselves; atomic writes with backups protect against bad edits.

---

## Quick start

```bash
# From project root:

# Show all journal entries with their current status
python3 .claude/skills/journal/j.py list

# Look at one entry's Status + Updates + Exit
python3 .claude/skills/journal/j.py show AUPH

# Trigger filled (paper trade)
python3 .claude/skills/journal/j.py live AUPH --paper --fill 15.39 --shares 354 --time "2026-06-04 09:35 ET"

# Trigger filled (real money)
python3 .claude/skills/journal/j.py live AUPH --real --fill 15.39 --shares 354 --time "2026-06-04 09:35 ET"

# Add a note as the trade develops
python3 .claude/skills/journal/j.py update AUPH --notes "Scaled half at TP1 17.65, trailing remainder behind 20-EMA"

# Close as a win
python3 .claude/skills/journal/j.py close AUPH --result win --r 2.05 --price 17.65 --notes "TP1 hit clean, runner trailing"

# Close as a loss
python3 .claude/skills/journal/j.py close AUPH --result loss --r -1.0 --price 14.26 --notes "Stopped out on weak open"

# Setup never triggered — mark it dead
python3 .claude/skills/journal/j.py dead AUPH --reason "No trigger in 14 days; setup expired"
```

Every write prompts for confirmation. Pass `-y` to skip.

---

## What it does to the file

Each operation:

1. **Reads** `journal/YYYY-MM-DD_TICKER.md`
2. **Backs up** the current state to `.claude/cache/journal_backups/` (rolling 10/file)
3. **Replaces** the `**Status:**` field at the top with the new value
4. **Appends** a timestamped bullet under `## Updates`
5. **Fills** the `## Exit` section (close only)
6. **Atomic write** — original is untouched if anything fails

The dashboard's Active Prospectuses panel re-reads journal files on every refresh, so the new status appears as soon as you re-run the dashboard.

---

## The six operations

### `live` — trigger filled

```bash
python3 .claude/skills/journal/j.py live AUPH --paper --fill 15.39 --shares 354 --time "2026-06-04 09:35 ET"
```

Status flips from `PROSPECTUS` to `LIVE — paper` (or `LIVE — real`). A new Updates bullet is appended:

```
- 2026-06-04 09:35 +08 — Status → LIVE — paper. Filled @ $15.39 · 354 sh · at 2026-06-04 09:35 ET.
```

Pass extras with `--notes "any free-text"` and they get appended after the fill details.

### `update` — note without status change

```bash
python3 .claude/skills/journal/j.py update AUPH --notes "Half scaled at TP1 17.65, trailing remainder"
```

Just appends one bullet. Status untouched.

### `close` — exit + post-mortem template

```bash
python3 .claude/skills/journal/j.py close AUPH --result win --r 2.05 --price 17.65 --notes "TP1 hit, runner stopped at 16.80"
```

- Status → `CLOSED — win (+2.05R)`
- Updates bullet appended with exit details
- `## Exit` section gets six fields filled:

```
- Date / price / reason: 2026-06-04 — $17.65, win (TP1 hit, runner stopped at 16.80)
- Realized R-multiple: +2.05R
- Time in trade: (compute from entry → exit; see prior Updates)
- Process correct? (was the gate-clean entry executed per plan? did stops hold?)
- Outcome lucky? (would the same process have failed on a slightly different tape?)
- Lesson (one line): (TODO — fill in)
```

The TODO lines are for you to come back to — the post-mortem questions matter more than the realized R. Open the file in your editor and fill them in once you've had a day to reflect.

`--result` is one of: `win`, `loss`, `scratch`, `timeout`. `--r` is the realized R-multiple (`2.05`, `-1.0`, etc).

### `dead` — setup never fired

```bash
python3 .claude/skills/journal/j.py dead AUPH --reason "Trigger never fired by 2-week setup expiry"
```

Status → `DEAD — Trigger never fired by 2-week setup expiry`. No trade was taken; the entry stays in the journal for calibration ("how often do my prospectuses actually trigger?").

### `list` — overview

```bash
python3 .claude/skills/journal/j.py list

# Filter to just prospectuses or live trades
python3 .claude/skills/journal/j.py list --status prospectus
python3 .claude/skills/journal/j.py list --status live
python3 .claude/skills/journal/j.py list --status closed
```

### `show` — focused view of one entry

```bash
python3 .claude/skills/journal/j.py show AUPH
```

Prints just the Status + Updates + Exit sections. Use for quick audits.

---

## File lookup

You can refer to a journal entry by:

- **Ticker** — `AUPH` (matches the latest `YYYY-MM-DD_AUPH.md`)
- **Stem** — `2026-06-03_AUPH`
- **Filename** — `2026-06-03_AUPH.md`

If multiple files match the ticker (you've journaled AUPH twice in different weeks), the CLI errors with a disambiguation list — use the stem to pick the right one.

---

## Dashboard buttons

When you refresh the dashboard, every Active Prospectus card now has six small buttons:

> [ Live paper ] [ Live real ] [ Update ] [ Close win ] [ Close loss ] [ Mark dead ]

Click any button → a pre-formed CLI command (with the file stem filled in) is copied to your clipboard. The button briefly turns green to confirm. Paste in your terminal, fill in the `_FILL_` / `_RR_` / `_NOTE_` placeholders with real values, run.

This is the same model as the dashboard's main Refresh button — static HTML can't write to your filesystem, but it can hand you the right command.

---

## Backups & safety

- Every write backs up to `.claude/cache/journal_backups/{stem}_{microsecond-timestamp}.md`
- Last 10 backups per file are kept; older are pruned
- Atomic write: temp file → rename, so torn writes are impossible
- Microsecond timestamps mean back-to-back commands don't overwrite each other's backups

If you ever need to roll back, find the right backup file and `cp` it over the active journal.

---

## When something looks wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `no journal entry matches 'X'` | Typo or wrong ticker | Run `j.py list` to see available entries |
| `'X' matches multiple entries` | Ticker journaled multiple times | Use the full stem like `2026-06-03_AUPH` |
| Status field unchanged after `live` | The file didn't have a `**Status:**` line | The CLI inserts one near the top heading; verify it landed correctly |
| Exit section duplicated | The file had no `## Exit` header originally | The CLI appends a new section — clean up the duplicate manually |
| Dashboard still shows old status | Dashboard hasn't been refreshed since the edit | Re-run `python3 .claude/skills/dashboard/dashboard.py` |

---

## TL;DR

- `live --paper` / `live --real` when trigger fires
- `update --notes` as the trade develops
- `close --result --r --price --notes` when exiting
- `dead --reason` when a prospectus never triggers
- Confirmation by default, `-y` to skip
- Backups in `.claude/cache/journal_backups/` (rolling 10)
- Dashboard buttons copy CLI commands to your clipboard
