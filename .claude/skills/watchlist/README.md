# Watchlist CLI — User Guide

A small command-line tool to manage `watchlist.md` cleanly. Auto-classifies, auto-builds thesis lines, validates tickers, preserves removal history with audit trail.

---

## Quick start

```bash
# Add a ticker — auto-detects section, fetches name + sector, builds default thesis
python3 .claude/skills/watchlist/wl.py add HOOD

# Add with custom thesis
python3 .claude/skills/watchlist/wl.py add HOOD --thesis "Robinhood; rate-sensitive broker"

# Remove a ticker (moves to Removed/retired with date + reason)
python3 .claude/skills/watchlist/wl.py remove HOOD --reason "trend filter still failing after 3 weeks"

# Update the thesis line for an existing ticker
python3 .claude/skills/watchlist/wl.py update HOOD --thesis "moved to SMA50 reclaim watch"

# List everything in the watchlist
python3 .claude/skills/watchlist/wl.py list
```

All operations prompt for confirmation before writing. Pass `-y` or `--yes` to skip.

---

## What the four commands do

### `add` — add a ticker

```
python3 .claude/skills/watchlist/wl.py add <TICKER> [options]
```

What it does:
1. **Auto-classifies** the ticker into US / KLSE / Crypto (see classification table below)
2. **Validates** by fetching real data (yfinance for US/KLSE, CoinGecko for crypto). Refuses if the source returns no data — protects you from typos and dead tickers
3. **Builds a default thesis line** from the resolved name + sector / category
4. **Shows you what it's about to write** and asks for confirmation
5. **Writes atomically** — saves a backup of the previous `watchlist.md` to `.claude/cache/watchlist_backups/` and writes the new version via rename (no torn writes)
6. **Invalidates the dashboard cache** for that ticker so the next dashboard refresh fetches fresh data

Options:
- `--thesis "..."` — override the auto-generated thesis
- `--section us|klse|crypto|options` — override auto-classify (needed for ambiguous cases like `PURR`)
- `--yes` / `-y` — skip the confirmation prompt
- `--allow-unresolved` — add even if the data source can't resolve (you must also pass `--thesis`)

### `remove` — soft-delete with audit trail

```
python3 .claude/skills/watchlist/wl.py remove <TICKER> --reason "..."
```

What it does:
1. Finds the ticker in any active section
2. **Captures the current thesis text**
3. Removes the line from the active section
4. **Appends to "Removed / retired"** with format:
   ```
   - `TICKER` — original thesis (removed YYYY-MM-DD: reason)
   ```
5. Backup + cache invalidation as in `add`

`--reason` is **required** — per doctrine, history is preserved with context. The CLI refuses to remove without a reason.

### `update` — change the thesis line

```
python3 .claude/skills/watchlist/wl.py update <TICKER> --thesis "..."
```

In-place edit of the thesis text. Section unchanged. Backup taken. Useful when your thinking on a name evolves.

### `list` — see what's in the watchlist

```
python3 .claude/skills/watchlist/wl.py list                    # active sections only
python3 .claude/skills/watchlist/wl.py list --include-removed  # also show Removed/retired
```

Prints each section with count and ticker → thesis lines. Useful sanity check after a batch of edits.

---

## Auto-classification rules

| Ticker form | Auto-routes to | Examples |
|---|---|---|
| 1-4 digits, all numeric | KLSE (pads to 4, appends `.KL`) | `1155` → `1155.KL`, `293` → `0293.KL` |
| Already has `.KL` suffix | KLSE (used as-is) | `1155.KL` |
| In the known-crypto-symbol list (BTC, ETH, SOL, LINK, etc.) | Crypto | `LINK`, `ADA` |
| ALL-CAPS letters, 1-5 chars, no dots | US Equity | `HOOD`, `MRVL` |
| Anything else | Refuse, ask for `--section` override | `BRK.B`, `PURR` (US treasury, not crypto) |

Override with `--section us|klse|crypto|options` whenever the auto-classify is wrong. The `PURR` case is the canonical example — it auto-classifies as crypto (it's in the known list as Hyperliquid meme) but should actually go to US (NASDAQ:PURR = Hyperliquid Strategies Inc).

---

## Auto-thesis generation

When you don't pass `--thesis`, the CLI builds one from the resolved metadata:

| Section | Format | Example |
|---|---|---|
| US | `{Name}; {Sector} / {Industry}` | `Robinhood Markets, Inc.; Financial Services / Capital Markets` |
| KLSE | `{Name}; {Sector}` | `TENAGA; Utilities` |
| Crypto | `{Name}; #{rank}; {top 2 categories}` | `Chainlink; #19; Artificial Intelligence (AI) / Infrastructure` |

You're always shown the proposed line before it's written. If the default is wrong or not enough, cancel and re-run with `--thesis "..."`.

---

## Examples

### Add a US equity with a real thesis you've thought about

```
$ python3 .claude/skills/watchlist/wl.py add HOOD --thesis "Robinhood; rate-sensitive broker — watching for SMA20 pullback"
Resolving HOOD (us)…

Resolved:  Robinhood Markets, Inc.
  Sector:  Financial Services / Capital Markets
  Price:   USD 83.6960
  Section: us

Will insert into 'us' section:
  - `HOOD` — Robinhood; rate-sensitive broker — watching for SMA20 pullback

Proceed? [y/N] y
✓ Added to watchlist.md  (us, line 21)
  Backup: .claude/cache/watchlist_backups/watchlist_2026-06-03_175705.md
  Dashboard cache invalidated for HOOD
  Refresh dashboard: python3 .claude/skills/dashboard/dashboard.py
```

### Add a KLSE ticker by bare Bursa code

```
$ python3 .claude/skills/watchlist/wl.py add 5347
Resolving 5347.KL (klse)…

Resolved:  TENAGA
  Sector:  Utilities
  Price:   MYR 14.2800
  Section: klse

Will insert into 'klse' section:
  - `5347.KL` — TENAGA; Utilities
```

### Remove a ticker that's stopped earning its slot

```
$ python3 .claude/skills/watchlist/wl.py remove KTOS --reason "trend filter fails 3 weeks running; not P1-shaped"
Will remove from 'us' section:
  - `KTOS` — Kratos Defense; AI-defense...

Will append to 'Removed / retired':
  - `KTOS` — Kratos Defense; AI-defense... (removed 2026-06-03: trend filter fails 3 weeks running; not P1-shaped)

Proceed? [y/N] y
✓ Moved KTOS to Removed / retired
```

### Try to add a ticker that's been removed before

```
$ python3 .claude/skills/watchlist/wl.py add KTOS
⚠ KTOS is in Removed/retired:
    - `KTOS` — Kratos Defense; AI-defense... (removed 2026-06-03: trend filter fails 3 weeks running)
Re-add to us? [y/N]
```

The CLI surfaces the history so you can reconsider — useful when you're tempted to chase the same name twice.

### Try to add a duplicate

```
$ python3 .claude/skills/watchlist/wl.py add AUPH
❌ AUPH already in 'us' section:
    - `AUPH` — Aurinia Pharma; small-cap biotech, catalyst-driven (binary event risk)
   Use `wl.py update AUPH --thesis "..."` to change its thesis.
```

Clear error + the suggested fix. Won't ever silently double-add.

---

## Edge cases handled

| Case | Behavior |
|---|---|
| Add a ticker already in active watchlist | Refuse, show existing line, suggest `update` |
| Add a ticker that's in Removed/retired | Surface the historical removal note, ask "re-add anyway?" |
| Remove a ticker not in any section | Error: "not in watchlist" |
| Remove without `--reason` | Refuse (doctrine requires a reason) |
| Remove a ticker that's already in Removed/retired | Refuse with current line shown |
| Update a ticker in Removed/retired | Refuse — must re-add first |
| Ambiguous classification (e.g. PURR) | First-match auto-routes; pass `--section` to override |
| yfinance / CoinGecko returns no data | Refuse unless `--allow-unresolved` is passed |
| User says "no" to confirmation | Aborts cleanly, no edit, no backup |
| Atomic write interrupted | Original file untouched; backup exists |

---

## Backups

Every edit (add / update / remove) takes a backup first to:
```
.claude/cache/watchlist_backups/watchlist_YYYY-MM-DD_HHMMSS.md
```

The last 10 backups are kept; older ones are auto-pruned. If you ever blow up the watchlist, restore from the most recent backup.

Caveat: backups are timestamped to the second. Multiple edits within one second share a filename and only the last one wins. Avoid scripting many sub-second edits if you need granular rollback.

---

## How this works with the dashboard

The CLI and the dashboard share the same `watchlist.md` as the source of truth.

- **CLI edits → dashboard reflects them on next refresh.** When you add/update/remove, the CLI invalidates the per-ticker cache file (`.claude/cache/dashboard/yfin_<ticker>.json`) so the next dashboard run fetches fresh data for that ticker. Other tickers' caches stay intact.
- **The CLI does NOT auto-refresh the dashboard.** You run `python3 .claude/skills/dashboard/dashboard.py` separately when you want updated visuals. (Your design choice — saves tokens.)
- **You can still edit `watchlist.md` directly** in your text editor. The CLI is for convenience, not enforcement. As long as you keep the format `- \`TICKER\` — thesis`, both the dashboard and the CLI will parse it cleanly.

---

## When something feels wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| "Could not classify '<ticker>'" | Ticker doesn't match any auto-classify rule | Pass `--section us|klse|crypto|options` |
| "Could not resolve <ticker>: HTTP 404" | yfinance or CoinGecko doesn't know the ticker | Verify spelling. If you're sure it's right (illiquid alt, recent IPO), use `--allow-unresolved --thesis "..."` |
| "already in 'us' section" but you don't see it | Maybe in Options / Removed / etc. | `wl.py list --include-removed` to see everything |
| Section bounds detected wrong | Section header in `watchlist.md` was edited | The CLI matches headings by their first word — `## Equities / ETFs` works, but `## US Stocks` would not. Restore the standard heading or add a matcher in `wl.py`. |
| Dashboard still shows ❓ DATA for a ticker I just added | Dashboard cache not refreshed yet | Run `python3 .claude/skills/dashboard/dashboard.py --force` |

---

## What the CLI does NOT do (by design)

- **No auto journal entry.** Adding a ticker doesn't create `journal/...md`. Journal entries are for trades, not watchlist hygiene.
- **No auto dashboard refresh.** You explicitly run the dashboard when you want it. Saves tokens / API calls.
- **No reordering.** New entries land at the end of their section. If you want alphabetical, edit by hand.
- **No format reflow.** The CLI only touches the line it's adding/removing/updating. Other lines and your formatting are untouched.
- **No thesis quality check.** If your thesis is "vibes," it accepts vibes. Human judgment is the field.
- **No sync with broker positions.** That's a different problem.

---

## TL;DR

- **Add:** `wl.py add <TICKER>` — auto-everything, you confirm
- **Remove:** `wl.py remove <TICKER> --reason "..."` — soft delete with audit trail
- **Update:** `wl.py update <TICKER> --thesis "..."` — change the thesis line
- **List:** `wl.py list` — see what's in the watchlist
- **Confirm by default, `-y` to skip.**
- **Backups in `.claude/cache/watchlist_backups/`** — rolling 10.
- **Run the dashboard separately** to see changes reflected with live data.
