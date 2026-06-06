# Dashboard — User Guide

A one-page, browser-viewable view of your entire trading state. Refresh on demand, read in 60 seconds, act with the doctrine.

---

## Quick start

```bash
# From project root:
python3 .claude/skills/dashboard/dashboard.py --open

# Refresh without re-opening (page is the same file, just reload your browser tab):
python3 .claude/skills/dashboard/dashboard.py

# Force a full refetch (bypass all 30-60 minute caches):
python3 .claude/skills/dashboard/dashboard.py --force
```

The output is a single self-contained file at `<project>/dashboard.html`. Bookmark it. It works offline once built.

The header has a "↻ Refresh" badge — clicking copies the rebuild command to your clipboard so you can paste it into a terminal.

---

## How the dashboard is organized

Top to bottom, the page is structured around the doctrine's decision flow.

### 1. Header strip (account + phase + heat)

Four tiles showing your immutable trading constraints.

| Tile | What it means | Why it's here |
|---|---|---|
| **Account** | Equity used for sizing math | Every position size is derived from this |
| **Phase** | Phase 1 / 2 / 3 — what's allowed | Phase 1 = spot longs only, no options/shorts/leverage |
| **Portfolio Heat** | $ at risk across all open positions vs ceiling | Cannot open a new position if it would exceed the ceiling |
| **Phase 2 gate** | Closed trades counted toward 20-trade unlock | Phase 2 unlocks defined-risk options after 20 logged trades + ≥0R expectancy |

If `Heat used = Heat max`, no new entries are doctrine-allowed. If `Trades closed < 20`, you're still in Phase 1 and options remain DARK.

### 2. Regime read (US Macro + Crypto, side-by-side)

Two boxes, each with a composite score, a one-word verdict, and a signal table.

**US Macro (FRED data)** drives R:R floor and position sizing tilt:

| Regime | What it means for you |
|---|---|
| **RISK-ON tailwind** (≥ +1.5) | Standard sizing; growth/high-beta names viable |
| **CONSTRUCTIVE** (+0.5 to +1.5) | Standard sizing; mild risk-on lean |
| **NEUTRAL** (−0.5 to +0.5) | No regime tilt; trade only the cleanest confluence setups |
| **CAUTIOUS** (−0.5 to −1.5) | Tighten R:R floor to **2R**; standard sizing; prefer defensive sectors |
| **RISK-OFF headwind** (≤ −1.5) | Cut size 50%; require 2R+; avoid high-beta; consider standing aside |

**Crypto (Fear & Greed + CoinGecko /global)** is independent of macro:

| Regime | What it means for you |
|---|---|
| **STRONG ACCUMULATION** (≥ +1.5) | Extreme fear + alt-season setup; be ready for next reclaim signal |
| **CONSTRUCTIVE** (+0.5 to +1.5) | Mild contrarian-buy lean |
| **NEUTRAL** (−0.5 to +0.5) | No tilt; confluence-only |
| **DISTRIBUTION** (−0.5 to −1.5) | Mild bearish lean; consider trims |
| **EUPHORIA** (≤ −1.5) | Likely top zone; no new chase entries |

**These two regimes do not average** — they describe different things. Macro tilts sizing, crypto regime tilts confluence threshold. Use them independently.

### 3. Halt-window timeline

Up to ten upcoming macro events (NFP / CPI / PCE / FOMC) with hours-until and a 🛑 flag if you're inside the **12-hour halt window** before that event.

If you see 🛑, **you cannot open a new US-equity directional position right now per §5 doctrine**. Wait until after the event prints, or use a defined-risk options structure where the event IS the thesis (which is Phase 3 only — DARK for you currently).

### 4. Active prospectuses

Cards for any journal entry whose Status field mentions "prospectus" / "live" / "pending." This is your "what's already armed" view.

Edit `journal/YYYY-MM-DD_TICKER.md` to change a prospectus → live; the dashboard reads the Status field on next refresh.

### 5. Risk Simulator

A form for testing a hypothetical entry against the doctrine before you place the order. Five inputs:

- **Ticker** — dropdown of every US watchlist name (uses already-cached technicals)
- **Entry** — your planned fill price
- **Stop** — your planned stop level
- **TP1** — your first take-profit
- **TP2** — optional second target (informational only)

Press **↻ Suggest** to auto-fill levels from the cached data: entry = SMA20, stop = wider of (1.5×ATR below entry) or (5% below entry), TP1 = entry + 2R. Tune from there.

As you type, the result panel updates live with:

- **Position size** — `floor((account × risk%) / (entry − stop))` shares
- **Notional** — `shares × entry`, also as % of account
- **$ at risk** — `shares × (entry − stop)`, also as % of equity
- **R:R to TP1** — `(TP1 − entry) / (entry − stop)`
- **R:R to TP2** — same for TP2 if provided
- **Heat after entry** — current heat + this trade's risk, vs. the $1,200 ceiling
- **R:R floor (regime)** — 1.5R under NEUTRAL+, 2.0R under CAUTIOUS, 2.5R under RISK-OFF
- **Risk per share** — `entry − stop`

And then 10–11 **gate checks** with ✓ / ⚠ / ✗:

1. **Phase 1 spot long** — always passes (the simulator is spot-only by design)
2. **Trend filter** — price > SMA50 > SMA200 from cache
3. **SMA50 direction** — slope over last 5d (rising/flat = ok, falling = warn)
4. **RSI zone** — 35–50 = ✓, 50–70 = warn, >70 = ✗, <30 = warn
5. **Pullback shape** — price within ±3% of SMA20 = ✓, ±10% = warn, beyond = ✗
6. **Volume profile** — recent 5d vs 30d avg (1.3×+ = distribution)
7. **Earnings window** — next earnings ≥ 10 calendar days away
8. **Macro halt** — no FOMC/CPI/NFP/PCE within 72 hours
9. **R:R floor** — computed R:R to TP1 ≥ regime-adjusted floor
10. **Heat headroom** — total risk after entry ≤ $1,200 ceiling
11. **Entry vs current price** — warn if your entry is more than 5% from cached price (recompute when you actually fill)

The verdict at the top is one of:

- **🟢 GO — all gates pass** → doctrine-compliant; set the order, write the journal
- **🟡 GO WITH CAVEATS — N warnings** → no hard fails; review the yellows and decide
- **🔴 NO-TRADE — N hard gate failures** → doctrine refuses; adjust levels or wait

**The simulator uses cached data**, not live. If the watchlist ticker's cache is 30+ min old, refresh the dashboard first. For accurate fills, recompute at execution time using the cached "entry vs current" warning.

**The simulator does NOT replace the journal.** When the verdict is GO, the next step is `journal/YYYY-MM-DD_TICKER.md` with the full thesis, not a one-line "the simulator said yes."

### 6–8. Watchlist grids (US / KLSE / Crypto)

The heart of the dashboard. One row per watchlist ticker, sortable by any column (click the header).

Each row shows live technicals plus a **Status badge** (the part you actually act on).

The Status badge is derived from the **eight-gate P1 check** (see badge reference below).

### 8. Journal tail

Last 8 files in `journal/` with their Status. Quick audit that what's logged matches what's live in your broker.

---

## ⭐ Status badge reference (read this!)

Every US / KLSE row gets one of these badges. They describe **trade readiness under P1 (Trend Pullback)**, the only live playbook in Phase 1.

### 🟢 P1_READY — clean setup, take the trigger when it fires

Every gate of the P1 playbook is satisfied:
- ✅ Price > SMA50 > SMA200 (trend filter)
- ✅ SMA50 is rising (or at worst flat)
- ✅ RSI(14) is in the 35-50 entry band (cooled but not broken)
- ✅ Price is within ±3% of SMA20 (the "tag of 20-EMA" pullback shape)
- ✅ Volume on the recent 5 days is ≤ 1.3× the 30-day average (healthy pullback, not distribution)
- ✅ No earnings within 7 trading days (~10 calendar days)
- ✅ No FOMC / CPI / NFP / PCE within 72 hours
- ✅ Today's price change is ≤ ±5% (no violent break of structure)

**Action:** This is a setup worth working. Pull up the chart, set a price alert at "prior day's high + buffer," and prepare to enter on the next P1 trigger (first daily close back above prior day's high). Run a full pre-trade workflow before sizing in — including `us-news` for current catalysts and `us-fundamentals` for fresh earnings/valuation.

### 🟡 Yellow badges — "interesting but not ready"

All yellow badges mean: trend filter survived, but at least one other gate failed. Watch, don't enter.

| Label | What broke | Action |
|---|---|---|
| **WATCH** | RSI is above the 35-50 entry band (typically 50-60) but everything else is fine. The name is in a healthy trend but hasn't cooled enough yet. | Wait for a pullback to bring RSI into the 35-50 zone. |
| **EXTENDED** | Price is ≥ 10% above SMA20 — too far from the trend to call this a pullback yet. | Wait for a deeper pullback (price closer to SMA20) before considering. |
| **ABOVE_SMA20** | Price is +3 to +10% above SMA20 — closer than EXTENDED but not yet tagging. | Wait for a closer tag. |
| **BROKEN_SMA20** | Price has cracked > 5% below SMA20. RSI may be in the band but the structure is broken. | Wait for price to reclaim SMA20 from below with confirmation. Often the start of a longer decline. |
| **VIOLENT** | Today's move is > ±5%. Either a face-ripping rip or a flushing drop — too volatile to enter into. | Wait 1-2 sessions for stabilization. Re-evaluate then. |
| **OVERSOLD** | RSI < 30. Looks cheap but the doctrine says wait for a price trigger (reclaim of SMA20 or higher-low structure). | Catching knives without a trigger is gambling, not P1. |
| **NEAR_EARNINGS** | Earnings within 10 calendar days. §5 forbids new exposure 24h before earnings. | Wait until after the print. If you'd be in too deep, time-stop the existing position 3 days before instead. |
| **NEAR_FOMC / NEAR_CPI / NEAR_NFP / NEAR_PCE** | A macro event within 72 hours. Doctrine wants 3 trading days of clear air for a P1 setup. | Wait until after the event. The setup may improve or break post-print. |
| **HEAVY_VOLUME** | Recent 5d volume is > 1.3× the 30d average. Rising volume on a pullback = distribution, not healthy. | Wait for volume to subside. Heavy-volume pullbacks frequently continue down. |
| **SMA50_FALLING** | Trend filter mechanically passes but SMA50 is dropping over the last 5 days — trend may be transitioning. | Wait for SMA50 to flatten or turn back up. Falling SMA50 in an "uptrend" is often the late stage. |
| **NEW** | Recent IPO; SMA200 isn't available yet (need ~10 months of data). | P1 can't apply cleanly. Catalog only. Re-check in 6-12 months. |

### 🔴 Red badges — no-trade under P1

Hard structural failures. Do not force these into the playbook.

| Label | What broke | Action |
|---|---|---|
| **DOWNTREND** | Price < SMA50 < SMA200. All three trend-filter conditions fail. This is a downtrend. | NO-TRADE under P1. Either wait for a full structural reclaim (price back above SMA50, SMA50 turning up) or write a separate playbook for catching falling knives. The doctrine doesn't have one. |
| **BELOW50** | Price < SMA50 (but SMA50 > SMA200 still). The medium-term trend is intact but price has broken short-term support. | NO-TRADE. Wait for daily close back above SMA50 with confirmation. |
| **NO_GOLDEN_CROSS** | SMA50 < SMA200. Long-term trend is questionable regardless of where price sits. | NO-TRADE. Often takes weeks-to-months to repair. |
| **OVERBOUGHT** | RSI > 70. Chasing a vertical move is the most common retail loss. | NO-TRADE. Wait for a real pullback into the 35-50 RSI zone before re-evaluating. |
| **TREND_FAIL** | A different combination of the trend gates failed (catch-all). | NO-TRADE. |

### ⚪ Context badge — not a trade

| Label | Meaning |
|---|---|
| **CONTEXT** | Reference signal only (e.g., SPY). Watch what it's doing as a macro regime read, never as a trade. |

### ❓ Data badge — can't decide

| Label | Meaning | Action |
|---|---|---|
| **DATA** | yfinance returned an error or insufficient bars. | Re-run with `--force`. If still failing, the ticker may be delisted, suspended, or have a data-source issue. |

### Crypto badges (simplified — no formal P1 playbook for crypto spot yet)

| Label | Meaning |
|---|---|
| **WATCH** | Default crypto state |
| **DEEP DRAWDOWN** | Down > 20% over 30 days. Often the late stage of a downtrend; can mark a reversal zone but needs a price trigger. |
| **PULLBACK** | Down 10-20% over 30 days. Moderate pullback territory. |
| **EXTENDED** | Up > 20% over 30 days. Hot tape; don't chase. |

For crypto entries, regime + funding + on-chain flow + unlock check matter more than the badge. Use the underlying skills (`crypto-coingecko`, `crypto-derivatives`, `hyperliquid-flow`, `crypto-unlocks`) before sizing in.

---

## How to use the dashboard for a session

### Morning routine (~3 minutes)

1. **Refresh:** `python3 .claude/skills/dashboard/dashboard.py --open`
2. **Read the header strip** — do you have heat headroom? Are you still in Phase 1?
3. **Read the regimes** — what's the R:R floor today? (CAUTIOUS = 2R, NEUTRAL+ = 1.5R)
4. **Read the halt timeline** — is any event in the next 72 hours? If so, expect a lot of 🟡 NEAR_X badges in the watchlist; many setups are blocked.
5. **Scan the watchlist for 🟢 P1_READY.** If you see any, those are today's candidates.
6. **Glance at active prospectuses.** Anything armed waiting on a trigger?

### When you see a 🟢 P1_READY name

Don't trade off the dashboard alone. The badge only confirms the technical+event gates. You still need:
- `python3 .claude/skills/us-news/av_news.py --ticker X --hours 48` for current catalysts
- `python3 .claude/skills/us-fundamentals/us_fundamentals.py fundamentals --ticker X` for valuation context
- Re-check the macro halt for the actual planned entry time: `python3 .claude/skills/macro-calendar/macro_cal.py check --at "YYYY-MM-DD HH:MM ET"`
- Draft a journal prospectus (use `journal/2026-06-03_AUPH.md` as a template)

The dashboard tells you **where** to look. The skills tell you **whether** to act.

### When the watchlist is all 🟡 / 🔴 (like today)

That's a signal too — there is no clean P1 setup right now. The doctrine wants you to wait, not force. Use the time to read journal entries, refine the watchlist, or work on a different playbook (Phase 2/3 prep).

---

## Cache and freshness

Each section shows its data age in the "stale" label.

| Source | TTL | Notes |
|---|---|---|
| Macro regime (FRED) | 60 min | FRED data is daily; 60 min is plenty fresh |
| Crypto regime | 60 min | F&G updates daily; CG /global updates minutely |
| Macro calendar | rebuild each run | Loaded from static `schedule.json`, no API |
| US ticker data (yfinance) | 30 min | Includes price, RSI, SMAs, volume, earnings date |
| KLSE ticker data | 30 min | yfinance .KL — fundamentals via `klse-quote` separately |
| Crypto markets | 30 min | Batch via CG `/coins/markets` |
| Crypto funding | 30 min | Binance per-symbol |

Use `--force` to bypass all caches and refetch everything. Useful right after a major intraday move where you want the latest read.

---

## What the dashboard does NOT do

These are explicit non-features in Phase A. Some will arrive in Phase B.

- **Trade execution** — out of scope, ever. The agent never trades.
- **Per-ticker news** — would burn Alpha Vantage's 25/day budget on every refresh. Run `us-news` per ticker on demand.
- **KLSE fundamentals** — yfinance only gives prices/technicals for `.KL` tickers. For P/E, P/B, NTA, ROE, dividend yield, run `klse-quote` separately (uses WebFetch, which can't run from a Python script).
- **Position sizing simulator** — Phase B. For now use the journal template's sizing math.
- **News flagging** — the dashboard surfaces journal status, not real-time news. Run `us-news` for current sentiment.
- **Inline watchlist editing** — edit `watchlist.md` directly in your editor; dashboard re-reads on next refresh.
- **Auto-refresh** — by design (you asked for refresh-button-only).

---

## JS sanity check at build time

After writing `dashboard.html`, the build script extracts the embedded JS (the IIFE that runs the Risk Simulator + table sorting) and pipes it through `node --check` if `node` is available on your PATH. This catches the class of bugs (broken string escapes, unbalanced braces, stray characters) that would otherwise only surface in the browser console — silently breaking the Risk Simulator.

You'll see one of three messages at the end of every build:
- `✓ Wrote ... (JS syntax check passed)` — happy path
- `✓ Wrote ... (JS check skipped — \`node\` not on PATH)` — node not installed; build still succeeds, no validation
- `⚠ Wrote ... but JS SYNTAX CHECK FAILED:` followed by the node error — the HTML was written but the simulator and sorting are broken; fix the JS in `dashboard.py` and re-run

Skipping the check (no node) is fine for normal use. Install Node.js any time you want the safety net back.

## When something looks wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| Section says "data unavailable" | Source API errored | Check API key in skill `.env`; try `--force` |
| Stale label says "10h old" but you ran `--force` | Cache write failed (permissions?) | `ls -la .claude/cache/dashboard/` |
| Ticker shows ❓ DATA | yfinance has no history for it | Verify ticker; might be delisted/suspended |
| KLSE ticker has wrong sector | yfinance metadata for .KL is sparse | Expected — use `klse-quote` for accurate info |
| Status badge feels wrong | The eight-gate check missed a nuance | Re-read the gate definitions above; if a real bug, the logic is in `us_status()` in `dashboard.py` line ~570 |

---

## Editing the watchlist

Open `watchlist.md` in any editor. Use the bullet format the file already has:

```markdown
- `TICKER` — thesis / setup / timeframe in one line
```

On next dashboard refresh, the new entry appears in the appropriate grid with live data and a status badge. Remove the line (or move it to the "Removed / retired" section at the bottom) to take it off the dashboard.

---

## Editing the journal

Same as before — journal entries live in `journal/YYYY-MM-DD_TICKER.md`. The dashboard reads the `**Status:**` field at the top of each entry. Use one of these conventional values so the dashboard parses cleanly:

- `**Status:** PROSPECTUS — pending trigger`
- `**Status:** LIVE — paper`
- `**Status:** LIVE — real`
- `**Status:** CLOSED — win / loss / scratch`

The dashboard's "Active Prospectuses" panel shows any entry whose status contains "prospectus" / "live" / "pending."

---

## TL;DR

- **Refresh:** `python3 .claude/skills/dashboard/dashboard.py --open`
- **🟢 = trade candidate**, **🟡 = watch**, **🔴 = no-trade**, **⚪ = context**, **❓ = data issue**
- The dashboard tells you **where to look**, the skills tell you **whether to act**.
- If the whole watchlist is yellow/red, that's a signal: no setup right now. Patience.
