# Project Log — Trading Research & Advisory Agent

This file is the **replication guide**. Hand it (along with everything in the project folder) to another AI agent + operator pair and they should be able to stand up an identical instance.

**Read this together with `CLAUDE.md`** (the agent's operating doctrine — 10 sections including the asymmetric strategy mandate, risk doctrine, and the phased ramp). The doctrine is the *what and why*; this file is the *how to build it*.

---

## TL;DR — what this project is

A Claude Code agent that produces grounded trading research and risk-managed recommendations across **US equities, KLSE (Bursa Malaysia) equities, and crypto**. Every recommendation must be backed by real, current data pulled this session via the project's wired skills — never fabricated. Operates under a Phase 1 / 2 / 3 ramp that unlocks more complex structures only after enough logged trades prove out.

Output medium: a self-contained static HTML dashboard at `dashboard.html` plus a journal of timestamped prospectus / live / closed entries.

It is a **research and analysis tool, not a licensed advisor and not an execution system.** The human makes every final decision.

---

## What's been built (build log, chronological)

Each item below is a skill or feature shipped during the build sessions. The skill folders under `.claude/skills/` are self-contained — most have their own `SKILL.md` + `README.md`.

### Data sources (skills that fetch raw data)

| Skill | Purpose | Provider | Auth |
|---|---|---|---|
| `macro-rates` | FRED snapshot + composite regime (RISK-ON / NEUTRAL / CAUTIOUS / RISK-OFF) | FRED | `FRED_API_KEY` |
| `macro-calendar` | US scheduled macro events (FOMC/CPI/NFP/PCE) with §5 halt-window enforcement | Curated JSON | none |
| `us-news` | AV NEWS_SENTIMENT with budget-aware priority queue (25 calls/day) | Alpha Vantage | `ALPHAVANTAGE_API_KEY` |
| `us-fundamentals` | yfinance fundamentals + earnings calendar (per-ticker) | yfinance | none |
| `klse-quote` | Bursa Malaysia per-ticker snapshot via klsescreener.com (WebFetch, agent-only) | klsescreener.com | none |
| `klse-history` | yfinance historical OHLCV + indicators for `.KL` tickers | yfinance | none |
| `klse-news` | klsescreener.com news + Bursa announcements (WebFetch) | klsescreener.com | none |
| `klse-refresh` | Python-callable batch fundamentals (P/E, P/B, NTA, ROE, DY, RSI) → cache | urllib + regex | none |
| `klse-announcements` | Python-callable Bursa filings + derived next Q-results date → cache | urllib + regex | none |
| `crypto-coingecko` | Per-coin snapshot + dev/community + regime composite | CoinGecko | optional `COINGECKO_API_KEY` |
| `crypto-derivatives` | Binance Futures funding/OI/long-short ratios | Binance public | none |
| `crypto-unlocks` | tokenomist.ai live unlock data (WebFetch, agent-only) | tokenomist.ai | none |
| `crypto-unlocks-cache` | Python-callable cache for the §5 48h unlock halt gate | local JSON | none |
| `hyperliquid-flow` | Per-coin perp funding + OI + on-chain whale positions | Hyperliquid public | none |
| `finnhub` | Real-time quote endpoint (live US prices) — also embedded in dashboard JS | Finnhub | `FINNHUB_API_KEY` |
| `twelve-data` | Bulk historical OHLCV (sector rotation + screener technicals) | Twelve Data | `TWELVE_DATA_API_KEY` |
| `fmp` | Per-ticker fundamentals via `/stable/` endpoints (Buffett Q+V) | FMP | `FMP_API_KEY` |

### Analysis + discovery skills

| Skill | Purpose | Notes |
|---|---|---|
| `sector-rotation` | Rank 11 SPDR sector ETFs by composite vs SPY (1m/3m/6m weighted) | Twelve Data backend; 4h TTL; cooldown + stale fallback |
| `us-screener` | Curated 176-name universe scan: P1 technical gates + Buffett Q+V tagging | TD for technicals, FMP→yfinance fallback for fundamentals; tiered HOT/WARM/COLD cache |
| `dashboard` | Render `dashboard.html` (the operating surface) | Aggregates everything; supports `--with-discovery` for one-command refresh |
| `watchlist` | CLI for `watchlist.md` add/remove/update/resolve | Maintains resolution cache so new alts auto-discover their CoinGecko id + Binance pair |
| `journal` | Lifecycle CLI for `journal/*.md` (new / live / update / close / dead / R-multiple calc) | Backups + audit trail |

### Dashboard features (rendered in `dashboard.html`)

- **Regime strip** (US macro + crypto regime + macro halt-window timeline)
- **Risk Simulator** — interactive form per market (US/KLSE/crypto); 12-gate doctrine check + R:R + heat math + "Create prospectus" command generator
- **US grid** — RSI · ATR% · vs SMA50/200 · earnings · news · P1 status with click-to-expand thesis + 8-gate breakdown
- **KLSE grid** — same shape with fundamentals + Bursa-filing watch
- **Crypto grid** — vs SMA50 · ATR% · funding · regime + expandable thesis
- **🔭 Discovery panel** — sector rotation heat strip + top-20 P1 + Q+V candidates (💎 BUFFETT / 🏆 QUALITY / 💰 VALUE / ⚡ TECH) with one-click "+ Add to watchlist"
- **Watchlist Manager** — inline forms generating `wl.py add/remove/update` commands with live preview
- **Prospectus cards** + per-prospectus action forms (live / update / close with auto-R / dead)
- **Journal tail**
- **Live quote buttons** — 🔄 next to each US price (Finnhub real-time), 🔄 for crypto (Binance/CoinGecko), 📊 link for KLSE (klsescreener.com)
- **Status badge tooltips** explaining every state ("OVERBOUGHT", "DOWNTREND", etc.) with recommended action

### Architectural patterns established

- **Cache + cooldown + stale-fallback** for every external data source (rate limits never crash the dashboard)
- **Budget tracking** for capped APIs (AV 25/day, TD 800/day, FMP 250/day) with soft + hard caps + on-demand reserves
- **Budget visualization** — header bar shows AV/TD/FMP usage % live, color-coded green/yellow/red (T3-B2)
- **Tiered cache TTLs** (HOT 24h / WARM 72h / COLD 7d) for the screener so daily calls stay low
- **Daily-only markers** — full screener pass < 18h ago short-circuits the next refresh
- **Skip-if-fresh subprocess spawn** — `dashboard.py --with-discovery` skips spawning subprocesses when their caches are still warm
- **Provider fallback chains** — FMP paywalled symbol → yfinance fallback; yfinance NaN-Close bar → Twelve Data fallback
- **Live quote endpoints** are browser-side (JS fetches Finnhub/Binance directly), separate from cached daily-close pipeline
- **Bulk resolution cache** — single directory scan instead of per-ticker file reads (T3-S2)
- **Parallel I/O** — yfinance per-ticker calls use `ThreadPoolExecutor` (T3-S3)
- **Watchlist auto-inclusion** in screener universe (T3-E3)

---

## Architecture overview

```
                            ┌────────────────────────────────┐
                            │       CLAUDE.md (doctrine)     │
                            │    + USER CONFIG block         │
                            └───────────────┬────────────────┘
                                            │
                       ┌────────────────────┼────────────────────┐
                       ▼                    ▼                    ▼
              ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
              │  Data skills  │    │ Analysis skills│    │ Lifecycle CLI │
              │  (fetchers)   │    │ (screener,     │    │ (watchlist.py │
              │               │    │ sector-rot,    │    │  journal.py)  │
              └───────┬───────┘    │ dashboard.py)  │    └───────────────┘
                      │            └───────┬───────┘
                      │                    │
                      ▼                    ▼
              ┌────────────────────────────────────────┐
              │  .claude/cache/ (JSON files, per-key)  │
              │  - macro_regime, crypto_regime         │
              │  - per-ticker yfin/td/fmp data         │
              │  - screener candidates.json            │
              │  - sector_rotation/data.json           │
              │  - news priority queue                 │
              └────────────────────────────────────────┘
                              │
                              ▼
              ┌────────────────────────────────────────┐
              │  dashboard.html (static, regenerable)  │
              │  rendered by .claude/skills/dashboard  │
              └────────────────────────────────────────┘
```

Refresh model: **operator-driven** (no cron, no auto-poll). The dashboard's refresh button copies a single command (`python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html`) — operator pastes in terminal, dashboard regenerates with whatever fresh data the TTLs allow.

---

## Replication steps

### Prerequisites

| Need | macOS | Linux | Windows |
|---|---|---|---|
| Python ≥ 3.9 | `brew install python` | `apt install python3 python3-pip` (or distro equiv) | Install from python.org, ensure `python3` is on PATH |
| Claude Code | Install from `claude.ai/code` | Install from `claude.ai/code` | Use WSL2 (recommended) — most scripts assume Unix shell |
| pandas + yfinance | `pip3 install pandas yfinance` | same | same |
| node (optional) | `brew install node` | distro pkg manager | from nodejs.org |

`node` is only used for the JS syntax check at the end of `dashboard.py`; it's `--check` only, doesn't run anything. Dashboard works without it.

**macOS-specific gotcha**: yfinance's bulk download (`yf.download(multiple_tickers, ...)`) triggers macOS XProtect false-positive ("Malicious Script Blocked") on recent macOS versions. The screener and sector-rotation skills work around this by using Twelve Data instead. Per-ticker `yf.Ticker(t).history()` and `.info` calls do **not** trigger it — keep those.

### Step 1: Copy the project folder

Take the entire `Trading Advisor/` directory and place it under whatever project root the brother prefers (e.g. `~/Documents/Claude/Projects/Trading Advisor/`).

**Files to copy:**
- `CLAUDE.md`
- `PROJECT_LOG.md` (this file)
- `.gitignore`
- `.claude/skills/` (all 21 skill folders)
- `rules/` (playbooks + risk doctrine)
- `journal/README.md` (keep the template; rest can be empty)
- `watchlist.md` (keep as a template — see Step 5)
- `portfolio.md` (template)

**Files to wipe / start empty:**
- `.claude/cache/` (don't copy — let it regenerate)
- `.claude/skills/*/.env` files (don't copy — brother needs his own keys)
- `dashboard.html` (will be regenerated)
- `journal/*.md` (except `README.md`)

### Step 2: Sign up for the API keys

All free tiers. Total time ~15 minutes.

| # | Provider | URL | Tier | Used for |
|---|---|---|---|---|
| 1 | **FRED** (St Louis Fed) | https://fred.stlouisfed.org/docs/api/api_key.html | Free, instant | Macro regime |
| 2 | **Alpha Vantage** | https://www.alphavantage.co/support/#api-key | Free, 25 calls/day | US news + sentiment |
| 3 | **Finnhub** | https://finnhub.io/register | Free, 60/min | Live quote buttons |
| 4 | **Twelve Data** | https://twelvedata.com/register | Free, 800/day + 8/min | Sector rotation + screener technicals (bulk historical OHLCV) |
| 5 | **FMP** (Financial Modeling Prep) | https://site.financialmodelingprep.com/developer/docs → "Get my Free API key" | Free, 250/day | Screener fundamentals (Buffett Q+V) |
| 6 | **CoinGecko Pro** (optional) | https://www.coingecko.com/en/api/pricing | Free demo or skip | Crypto regime + per-coin data (works without key on free public endpoints; Pro raises rate limits) |

For each, drop the key into the matching skill's `.env` file:

```bash
echo "FRED_API_KEY=YOUR_KEY"        > .claude/skills/macro-rates/.env
echo "ALPHAVANTAGE_API_KEY=YOUR_KEY" > .claude/skills/us-news/.env
echo "FINNHUB_API_KEY=YOUR_KEY"      > .claude/skills/finnhub/.env
echo "TWELVE_DATA_API_KEY=YOUR_KEY"  > .claude/skills/twelve-data/.env
echo "FMP_API_KEY=YOUR_KEY"          > .claude/skills/fmp/.env
# CoinGecko Pro optional:
# echo "COINGECKO_API_KEY=YOUR_KEY"   > .claude/skills/crypto-coingecko/.env
```

Each skill's `.env.template` shows the expected variable name.

### Step 3: Fill in `CLAUDE.md` USER CONFIG

Open `CLAUDE.md` and scroll to the bottom — the `USER CONFIG` block. Edit:

- **Account size** (currently set to a placeholder)
- **Max risk per trade %** (doctrine default 2%)
- **Max portfolio heat %** (doctrine default 6%)
- **Drawdown circuit-breaker %** (doctrine default 15%)
- **Aggression level** (Conservative / Balanced / Aggressive)
- **PHASED RAMP** — start at Phase 1 (paper + spot only) unless brother has prior logged results

The default doctrine is correct for most operators. Customize only the personalized fields.

### Step 4: Initialize the watchlist

`watchlist.md` is currently the template. Brother edits the three section bodies to put in tickers he wants to track:

- **US equities / ETFs**
- **KLSE (Bursa Malaysia, spot equity only)**
- **Crypto**

He can use the dashboard's Watchlist Manager to do this (after first dashboard build) or hand-edit. The CLI works too:

```bash
python3 .claude/skills/watchlist/wl.py add NVDA --thesis "AI semis leader"
python3 .claude/skills/watchlist/wl.py add 1155.KL --thesis "Maybank — KLSE bank megacap"
python3 .claude/skills/watchlist/wl.py add ETH --thesis "L1 #2"
```

### Step 5: Seed the crypto unlocks baseline (if using crypto)

```bash
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py baseline
```

This pre-fills the doctrine §5 unlock gate cache with no-schedule entries for BTC/ETH/stables and regular-emission warnings for SOL/BNB/XRP/HBAR/ADA/DOGE. For alts (HYPE, ENA, ARB, etc.) the agent uses the WebFetch `crypto-unlocks` skill on-demand then writes via `set`.

### Step 6: First dashboard build

```bash
python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html
```

(On Linux: replace `open` with `xdg-open`. On Windows: omit the `open` part and double-click `dashboard.html`.)

The first run will:
- Fetch FRED macro regime (~3s)
- Fetch crypto regime (~3s)
- Fetch yfinance data for each watchlist ticker (US + KLSE)
- Fetch crypto market snapshot from CoinGecko
- Fetch crypto klines from Binance (per coin)
- Fetch Binance funding (per coin)
- Run the full us-screener scan via Twelve Data (~22 min — only first time)
- Run sector rotation via Twelve Data (~90 sec)
- Render `dashboard.html`

Subsequent builds with the same `--with-discovery` flag: **~0.15 seconds** when caches are warm.

### Step 7: Verify everything works

Open `dashboard.html` in a browser. You should see:

1. ✅ Header strip with US macro regime + crypto regime + halt-window timeline
2. ✅ Risk Simulator panel (try picking a ticker, fill in entry/stop/TP1, see gate verdict)
3. ✅ US grid with technical columns + status badges
4. ✅ KLSE grid (if any KLSE tickers in watchlist)
5. ✅ Crypto grid
6. ✅ 🔭 Discovery panel with sector rotation heat strip + candidates
7. ✅ Watchlist Manager form (try adding a test ticker via the form)
8. ✅ Click a 🔄 button next to any US price → live Finnhub quote appears inline
9. ✅ Click a row chevron → expandable details with full gate breakdown + synthesized thesis

If anything fails: check the corresponding skill's `.env` for the API key, then re-run `dashboard.py`.

---

## Day-to-day operator usage

### Daily routine (~2 min)

```bash
# Refresh dashboard with discovery scan (skips fresh caches automatically)
python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html
```

### When you want fresh news for a watchlist ticker

```bash
# Burns 1 of 25 daily AV calls
python3 .claude/skills/dashboard/dashboard.py --refresh-news
```

### When you spot a new candidate

Open dashboard → Discovery panel → click **+ Add** on a row → paste the copied command into terminal → run.

### When a setup triggers entry

Open dashboard → Risk Simulator → pick ticker → set entry/stop/TP1 → if verdict is 🟢/🟡 GO → click **Convert to prospectus** → paste the command → run. Creates `journal/YYYY-MM-DD_TICKER.md`. When you actually enter:

```bash
python3 .claude/skills/journal/j.py live YYYY-MM-DD_TICKER --paper --fill 15.40 --shares 354
```

### When you close

```bash
python3 .claude/skills/journal/j.py close YYYY-MM-DD_TICKER --result win --entry 15.40 --stop 14.26 --exit 17.65 --shares 354
```

### KLSE-specific refresh

```bash
# Refresh KLSE fundamentals + announcements (run weekly or before sizing a KLSE position)
python3 .claude/skills/klse-refresh/klse_refresh.py
python3 .claude/skills/klse-announcements/klse_announcements.py
```

### Crypto-unlock cache update

When the agent reports it has fresh tokenomist.ai data for an alt:

```bash
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py set HYPE \
  --date 2026-11-29 --type cliff --pct 12.3 --source tokenomist.ai/hyperliquid
```

---

## Caveats & gotchas (learned during the build)

### macOS XProtect blocks yfinance bulk download
`yf.download(multiple_tickers, ...)` triggers a "Malicious Script Blocked" popup on macOS. Our screener + sector-rotation use Twelve Data instead. **Don't migrate them back to yfinance bulk** — it'll break again. Per-ticker `yf.Ticker(t).history()` and `.info` are fine.

### Yahoo Finance IP bans on bursts
Direct `query1.finance.yahoo.com` calls (the urllib path) get IP-banned after a single concurrent burst. Bans last 30-60 min. **Don't** parallelize Yahoo chart calls. We don't use them anymore (moved to Twelve Data), but if you re-enable them, sequential with 5+ second spacing only.

### FMP free tier only covers ~30-50 megacap symbols
`/stable/ratios-ttm` and `/stable/key-metrics-ttm` return HTTP 402 for most names. **The screener falls back to yfinance per-ticker `.info` for those**, which works for everything but is slower. Don't be surprised when many candidates show `_source: yfinance fallback` in fundamentals.json.

### yfinance returns NaN-Close bars occasionally
Some daily bars come back with Volume populated but Close=NaN. Dashboard drops those rows and uses the prior clean close; surfaces the date with a yellow `!` mark. E1 optimization adds Twelve Data fallback for these cases (one TD call per affected ticker).

### Finnhub free tier dropped historical OHLCV in 2024
Their `/stock/candle` endpoint is paid now. We only use `/quote` (still free, real-time) for the live quote buttons.

### Tokenomist.ai is a Next.js SPA
Direct `urllib` requests return ~600KB of JS bundles with no embedded data. The `crypto-unlocks` skill uses WebFetch (agent-only) to render the page; `crypto-unlocks-cache` is the Python-callable storage layer the dashboard reads on build.

### KLSE has no free real-time quote API
Finnhub free + Twelve Data free don't cover Bursa Malaysia. Live KLSE quotes require either paid tier or operator clicking through to klsescreener.com. The 📊 button on KLSE rows opens klsescreener in a new tab.

### CoinGecko 429s aggressively on bursts
Especially without a Pro key. Dashboard now has a 30-min cooldown + stale-fallback pattern. The Pro key (free demo tier) helps if rate limits keep biting.

---

## Tier 3 optimizations (shipped)

All four landed. Diffs below are the canonical reference — they're already applied in this codebase. A brother's-agent fork copying this project gets them for free.

### S2 — Memoize resolution cache ✓

**Location:** `.claude/skills/dashboard/dashboard.py` near `_load_resolution`

**Before:** Per-call file reads (`_RESOLUTION_CACHE_LOADED` was a dict but populated lazily one-key-at-a-time).
**After:** Bulk `glob('*.json')` on first call, all entries loaded into a module-level dict.

```python
_RESOLUTION_CACHE_LOADED = None  # None = not bulk-loaded yet; dict once loaded

def _bulk_load_resolutions():
    """S2: load ALL resolution JSONs in one directory scan rather than
    one file-read per ticker. Saves ~200ms per build with 25+ watchlist names."""
    global _RESOLUTION_CACHE_LOADED
    out = {}
    if RESOLUTIONS_DIR.is_dir():
        for p in RESOLUTIONS_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                key = (data.get("ticker") or p.stem.replace("_", ".")).upper()
                out[key] = data
            except Exception:
                continue
    _RESOLUTION_CACHE_LOADED = out
    return out

def _load_resolution(ticker_upper):
    global _RESOLUTION_CACHE_LOADED
    if _RESOLUTION_CACHE_LOADED is None:
        _bulk_load_resolutions()
    return _RESOLUTION_CACHE_LOADED.get(ticker_upper)
```

**Impact:** ~200ms saved per build; scales linearly with watchlist size.

### S3 — Parallel dashboard data load ✓

**Location:** `.claude/skills/dashboard/dashboard.py` at `build_dashboard()` — steps [5/8] and [6/8]

**Before:** Sequential `for entry in watchlist["us"]: fetch_yfinance_ticker(...)`.
**After:** `ThreadPoolExecutor` with 8 workers for US, 4 for KLSE.

```python
from concurrent.futures import ThreadPoolExecutor as _Pool, as_completed as _ac
print("[5/8] Fetching US ticker data via yfinance (parallel)...")
us_data = {}
us_tickers = [e["ticker"] for e in watchlist["us"]]
with _Pool(max_workers=min(8, max(1, len(us_tickers)))) as pool:
    futs = {pool.submit(fetch_yfinance_ticker, tk, force): tk for tk in us_tickers}
    for f in _ac(futs):
        tk = futs[f]
        try: us_data[tk], _ = f.result()
        except Exception as e: us_data[tk] = {"error": f"fetch failed: {e}"}

print("[6/8] Fetching KLSE ticker data via yfinance (parallel)...")
klse_data = {}
klse_tickers = [e["ticker"] for e in watchlist["klse"]]
with _Pool(max_workers=min(4, max(1, len(klse_tickers)))) as pool:
    futs = {pool.submit(fetch_yfinance_ticker, tk, force): tk for tk in klse_tickers}
    for f in _ac(futs):
        tk = futs[f]
        try: klse_data[tk], _ = f.result()
        except Exception as e: klse_data[tk] = {"error": f"fetch failed: {e}"}
```

**Impact:** Warm cache: imperceptible (was already < 1s for this stage). Cold cache: ~5× speedup on the per-ticker fetch phase (13-ticker US watchlist drops from ~25s to ~5s).
**Why per-ticker yfinance is safe to parallelize:** the XProtect issue we saw is specific to `yf.download(multi_tickers)`. Per-ticker `yf.Ticker(t).history()` calls don't trigger it, even in parallel.

### B2 — Budget bar in dashboard header ✓

**Location:** `.claude/skills/dashboard/dashboard.py` — new helper `_budget_bar_html()` + header insertion + CSS

**Helper function:**
```python
def _budget_bar_html():
    """B2: render a compact budget bar showing AV/TD/FMP daily usage."""
    def _load_skill_budget(path, cap):
        try:
            d = json.loads(path.read_text())
            from datetime import datetime as _dt, timezone as _tz
            if d.get("date") != _dt.now(_tz.utc).strftime("%Y-%m-%d"):
                return {"used": 0, "cap": cap}
            return {"used": d.get("calls_used", 0), "cap": cap}
        except Exception:
            return {"used": 0, "cap": cap}

    td_b  = _load_skill_budget(PROJECT_ROOT / ".claude/cache/twelve_data/budget.json", 800)
    fmp_b = _load_skill_budget(PROJECT_ROOT / ".claude/cache/fmp/budget.json",         250)
    av_b  = {"used": 0, "cap": 25}
    nc_mod = _import_news_cache()
    if nc_mod:
        try:
            b = nc_mod.load_budget()
            av_b["used"] = b.get("calls_used", 0)
        except Exception: pass

    def cell(name, used, cap):
        pct = (used / cap * 100) if cap > 0 else 0
        cls = "b-green" if pct < 60 else "b-yellow" if pct < 85 else "b-red"
        return (f'<span class="budget-cell {cls}" '
                f'title="{name}: {used}/{cap} calls used today ({pct:.0f}%)">'
                f'{name} {used}/{cap}</span>')

    return (f'<span class="budget-bar">'
            f'{cell("AV", av_b["used"], av_b["cap"])}'
            f'{cell("TD", td_b["used"], td_b["cap"])}'
            f'{cell("FMP", fmp_b["used"], fmp_b["cap"])}'
            f'</span>')
```

**Header insertion:**
```python
# In render_html(), add:
budget_bar = _budget_bar_html()
# Then inject into the meta div:
<div class="meta">Built {now_str} (local: {now_local_str}) · {budget_bar} · <span class="refresh-btn"...
```

**CSS:**
```css
.budget-bar { display: inline-flex; gap: 4px; margin-left: 4px; }
.budget-cell { display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 10px; font-weight: bold; cursor: help; letter-spacing: 0.04em;
  border: 1px solid var(--bord); }
```

**Impact:** Always-visible usage indicator at top of dashboard. Color-codes green / yellow (>60%) / red (>85%) so you know when you're approaching a daily cap.

### E3 — Auto-include watchlist names in screener universe ✓

**Location:** `.claude/skills/us-screener/screener.py` at `load_universe()`

```python
def load_universe(include_watchlist=True):
    """E3: by default, union the watchlist names into the screener universe so
    watchlist tickers always get tracked in the discovery scan (freshness parity).
    Watchlist-added names are tagged sector='_watchlist' if not already in universe.json."""
    j = json.loads(UNIVERSE.read_text())
    seen = set()
    out = []
    for sector, tickers in j["sectors"].items():
        for t in tickers:
            tk = t.upper()
            if tk in seen: continue
            seen.add(tk)
            out.append((tk, sector))
    if include_watchlist:
        for tk in watchlist_us_tickers():
            if tk in seen: continue
            seen.add(tk)
            out.append((tk, "_watchlist"))  # sector marker for distinguishability
    return out
```

**Impact:** Watchlist names that aren't in the curated 176-name universe (e.g. a small-cap, an ADR, or a name brother added that he wouldn't normally screen) now get refreshed by the screener on its normal cadence. Eliminates the "this is on my watchlist but Discovery doesn't know about it" mismatch.

### Stretch goals

- **Crypto screener** (mirror us-screener for top-100 alts using CoinGecko + Binance)
- **Options chain wiring for Phase 3** (currently dark — see CLAUDE.md PHASED RAMP)
- **Perp simulator** (Phase 3 unlock — leverage + liquidation math)
- **Sector ETF correlation matrix** in Discovery panel
- **Phase progression tracker** (count closed trades + R-multiple toward Phase 2 gate)

---

## File structure reference

```
Trading Advisor/
├── CLAUDE.md                      # Doctrine + USER CONFIG (10 sections)
├── PROJECT_LOG.md                 # This file
├── .gitignore                     # Excludes .env, dashboard.html, caches
├── watchlist.md                   # Source of truth for tracked tickers
├── portfolio.md                   # Open positions (manually updated)
├── dashboard.html                 # Generated artifact (don't edit)
├── rules/
│   ├── playbooks.md               # Named pre-approved setups (P1, P2, P3)
│   └── risk-doctrine.md           # Operational expansion of CLAUDE.md §5-6
├── journal/
│   ├── README.md                  # Journal entry template
│   └── YYYY-MM-DD_TICKER.md       # One file per trade
└── .claude/
    ├── cache/                     # Runtime data (don't commit)
    └── skills/                    # 21 skill folders, each with SKILL.md + code
        ├── crypto-coingecko/
        ├── crypto-derivatives/
        ├── crypto-unlocks/        # Agent-only (WebFetch)
        ├── crypto-unlocks-cache/
        ├── dashboard/             # The main render skill
        ├── finnhub/
        ├── fmp/
        ├── hyperliquid-flow/
        ├── journal/
        ├── klse-announcements/
        ├── klse-history/
        ├── klse-news/             # Agent-only (WebFetch)
        ├── klse-quote/            # Agent-only (WebFetch)
        ├── klse-refresh/
        ├── macro-calendar/
        ├── macro-rates/
        ├── sector-rotation/
        ├── twelve-data/
        ├── us-fundamentals/
        ├── us-news/
        ├── us-screener/
        └── watchlist/
```

---

## Doctrine summary (read `CLAUDE.md` for full text)

1. **Never fabricate a number.** Every price, indicator, IV, Greek, sentiment, fundamental must come from a tool call this session.
2. **Always timestamp data.** Stale data is fine if labeled; silent staleness is not.
3. **"No trade" is a valid output.** Patience is a position.
4. **Every recommendation defines its invalidation.** Without a stop, there's no trade.
5. **Cap downside first, then maximize upside.** Defined-risk structures, hard stops, position sizing — bounded loss is non-negotiable.
6. **Phased ramp.**
   - Phase 1 (current default): paper + spot long only (US + KLSE + crypto)
   - Phase 2 (unlock at 20 closed trades + ≥0R + 40% win rate): defined-risk options (long calls/puts, debit spreads)
   - Phase 3 (unlock at 50 closed trades + positive expectancy + no recent doctrine violations): premium selling, lottery sleeve, optional perps
   - Demotion rule: trailing-20 negative expectancy → drop one phase
7. **R-multiples, not dollars.** Win rate × average R is the only valid scoreboard.
8. **Calibration via the journal.** Closed trades feed back into playbook updates.

---

## How to use this file with a new agent

When opening this project in Claude Code (or any agent) for the first time:

```
"Read PROJECT_LOG.md, CLAUDE.md, and CHANGELOG.md. Then check the .env files
for any missing API keys, run a test dashboard build, and tell me what's
working and what's missing. Don't make any recommendations until I've
confirmed the setup is complete."
```

The agent should:
1. Read all three context files (doctrine + replication + version history)
2. List which API keys are configured vs missing
3. Try a build (will fail gracefully on missing keys)
4. Report status + ask for missing pieces

---

## Versioning + changelog

The project uses a **`MAJOR.MINOR`** scheme tagged in git as `vX.Y`:

| Bump | When |
|---|---|
| **MINOR** (e.g. v1.0 → v1.1) | Backward-compatible changes — bug fixes, optimizations, new columns, threshold tuning, documentation, new data sources for existing functionality |
| **MAJOR** (e.g. v1.x → v2.0) | Doctrine changes, breaking interface changes, new asset class, phase unlock changes, architectural rewrites |

**Every code change must update `CHANGELOG.md` before commit.** Add entries under `## [Unreleased]` at the top, categorized as `### Added` / `### Changed` / `### Fixed` / `### Removed` / `### Deprecated` / `### Security`. Write entries from the user's perspective, past tense.

When releasing: rename `[Unreleased]` to the new version, create a fresh empty `[Unreleased]` above, commit, then:

```bash
git tag -a vX.Y -m "Short release summary"
git push origin vX.Y
gh release create vX.Y --title "vX.Y — <theme>" --notes "<excerpt from changelog>"
```

Full policy + procedure live in `CHANGELOG.md`. **If you're unsure whether a change is MAJOR or MINOR, ask the operator. Never silently break a published interface or doctrine.**

---

## Acknowledgment

This project was built incrementally across many sessions. The skill-by-skill architecture, doctrine-first design, and cache+cooldown patterns emerged from real operational experience — especially the painful discovery that yfinance bulk downloads trigger macOS XProtect, Yahoo IP-bans bursts, FMP free is megacap-only, and Finnhub dropped historical from free in 2024. **The replication target is not "perfect first build" but "self-healing system that survives provider misbehavior."**

If the brother's setup hits a wall, the most likely culprits in order:
1. Missing API key in a `.env` file
2. yfinance flaking on macOS (try `pip3 install --upgrade yfinance`)
3. Provider rate limit (look for stale flags in the dashboard headers)
4. Cache out of sync (`rm -rf .claude/cache/` and rebuild — costs one full Twelve Data scan ~22 min)

Good luck.
