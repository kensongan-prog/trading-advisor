---
name: watchlist
description: Manage the project's watchlist.md via a CLI with four operations — add (auto-classify + auto-thesis + validate via yfinance/CoinGecko), remove (soft-delete with required reason, audit trail in Removed/retired), update (change a thesis line in-place), list (show all sections with counts). Use when the user wants to add a ticker without manual markdown editing, soft-delete a watchlist entry with a reason, change a thesis line for an existing ticker, or audit the current watchlist contents. Source of truth remains watchlist.md; CLI provides safety + automation around it.
---

# Watchlist CLI Skill

## When to use

Trigger this skill when the user says:

- "Add X to my watchlist" / "Add HOOD"
- "Remove KTOS from watchlist"
- "Update the thesis on AUPH to ..."
- "What's on my watchlist?"
- "Take X off my watchlist because Y"

Do NOT use for: ticker analysis (use the underlying skills), journal entries (separate workflow), or dashboard refresh (separate skill).

## Why this exists

Hand-editing `watchlist.md` is error-prone — bare tokens without backticks break the dashboard's parser, "thesis TBD" entries clutter the file, and "remove" often means "delete" which destroys calibration history. The CLI standardizes the format, validates against real data sources, and enforces the doctrine's soft-delete-with-reason rule.

## Subcommands

### `add` — add a ticker with auto-everything

```bash
python3 .claude/skills/watchlist/wl.py add <TICKER> [--thesis "..."] [--section us|klse|crypto|options] [--yes] [--allow-unresolved]
```

Auto-classifies ticker by format (4-digit → KLSE; known symbol → crypto; ALL-CAPS → US). Fetches metadata from yfinance / CoinGecko to validate the ticker exists. Builds a default thesis from name + sector / category unless `--thesis` overrides. Shows a preview and prompts for confirmation by default. Writes atomically with backup. Invalidates per-ticker dashboard cache.

### `remove` — soft-delete with required reason

```bash
python3 .claude/skills/watchlist/wl.py remove <TICKER> --reason "..." [--yes]
```

Captures the current thesis, removes the line from its active section, appends to `## Removed / retired` with format `- \`TICKER\` — original thesis (removed YYYY-MM-DD: reason)`. `--reason` is required by doctrine.

### `update` — change thesis in-place

```bash
python3 .claude/skills/watchlist/wl.py update <TICKER> --thesis "..." [--yes]
```

### `list` — show watchlist contents

```bash
python3 .claude/skills/watchlist/wl.py list [--include-removed]
```

## Hard rules

1. **Confirmation by default.** Every add/update/remove asks before writing. `--yes` to skip.
2. **No deletes, only soft-deletes.** `remove` ALWAYS moves to Removed/retired with a date and reason. The reason is required.
3. **Validation by default.** `add` refuses to add tickers that yfinance/CoinGecko can't resolve. Use `--allow-unresolved` to force.
4. **Atomic writes.** Every edit takes a backup first. Original file is untouched if anything fails.
5. **No dashboard auto-refresh.** Cache is invalidated for the affected ticker; user runs dashboard separately.
6. **No journal coupling.** Adding a ticker does NOT create a journal entry. Journal is for trades.

## Architecture

- Single Python file: `wl.py` (~400 lines)
- Source of truth: `<project>/watchlist.md`
- Backups: `.claude/cache/watchlist_backups/watchlist_YYYY-MM-DD_HHMMSS.md` (rolling 10)
- Data fetchers:
  - US / KLSE / Options underlyings: yfinance
  - Crypto: CoinGecko `/coins/{id}` (uses `COINGECKO_API_KEY` from `crypto-coingecko/.env` if present)
- Section detection: matches section headers by first word (e.g., `## Equities / ETFs` → first word "equities"); avoids substring collisions like "spot equity only — no options" falsely matching the Options section

## See also

- `README.md` in this directory — user-facing guide with examples and edge cases
- `dashboard/SKILL.md` — sibling skill that reads watchlist.md to render the dashboard
