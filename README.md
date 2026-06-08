# Trading Advisor

A doctrine-driven trading research agent that produces grounded, risk-managed recommendations across US equities, KLSE (Bursa Malaysia), and crypto — all backed by real, current data pulled at recommendation time.

Built as a cross-agent project — works with **[Claude Code](https://claude.ai/code)** (auto-loads doctrine via `CLAUDE.md` pointer → `AGENTS.md`) and **[Codex](https://github.com/openai/codex)** or any agent that follows the `AGENTS.md` convention. Outputs a self-contained static HTML dashboard plus a journaled record of every prospectus, live position, and closed trade.

> ⚠️ **Research tool, not financial advice.** This software does not execute trades and does not provide personalized investment recommendations. See [LICENSE](LICENSE) for the full disclaimer.

---

## What it does

- **Pulls real-time technical, fundamental, news, and macro data** from 7+ providers (FRED, Twelve Data, FMP, yfinance, CoinGecko, Binance, Alpha Vantage, Finnhub)
- **Enforces a written risk doctrine** (see [`AGENTS.md`](AGENTS.md)) on every recommendation — bounded downside, R-multiples, position sizing math, event-window halts (FOMC/CPI/NFP/earnings/token unlocks)
- **Phased ramp** unlocks complex structures only after enough logged trades prove out (paper-only Phase 1 → defined-risk options Phase 2 → full doctrine Phase 3)
- **Daily discovery scan** of a 176-name US universe with Buffett-style quality + value tagging (`💎 BUFFETT` / `🏆 QUALITY` / `💰 VALUE` / `⚡ TECH`)
- **Risk Simulator** with 12-gate doctrine check + R:R + heat math + one-click prospectus generation
- **Journaled lifecycle** — prospectus → live → closed with auto-computed R-multiples
- **Resilient by design** — cache + cooldown + stale-fallback for every external API; the dashboard renders even when providers misbehave

## Sample output (dashboard)

The dashboard is a single static HTML file that aggregates everything: regime strip, risk simulator, US/KLSE/crypto grids with click-to-expand thesis panels, sector rotation heat map, candidate screener with one-click "+ Add to watchlist," prospectus cards, journal tail, and live quote buttons on every ticker.

Refresh with one command:
```bash
python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html
```

Subsequent refreshes are sub-second when caches are warm.

## Quick start

**What you need:**
- Python 3.9+ and `pip3`
- An AI coding agent — **[Claude Code](https://claude.ai/code)** or **[Codex](https://github.com/openai/codex)** (recommended for the full doctrine-driven workflow). Both will auto-load `AGENTS.md` (Codex natively; Claude via the `CLAUDE.md` pointer). The static HTML dashboard and CLI tools work standalone with just Python, but you'll lose the agent workflow (live KLSE quotes, crypto unlock fetches, conversational recommendations).
- ~15 minutes to register for 5 free API keys (no credit card required for any of them)

```bash
# 1. Clone
git clone https://github.com/kensongan-prog/trading-advisor.git
cd trading-advisor

# 2. Dependencies
pip3 install pandas yfinance

# 3. Sign up for free API keys (~15 min total)
#    Full URLs + step-by-step: see PROJECT_LOG.md (link below)
#    Required: FRED, Alpha Vantage, Finnhub, Twelve Data, FMP
#    Optional: CoinGecko Pro

# 4. Drop keys into .env files
echo "FRED_API_KEY=YOUR_KEY"         > .claude/skills/macro-rates/.env
echo "ALPHAVANTAGE_API_KEY=YOUR_KEY" > .claude/skills/us-news/.env
echo "FINNHUB_API_KEY=YOUR_KEY"      > .claude/skills/finnhub/.env
echo "TWELVE_DATA_API_KEY=YOUR_KEY"  > .claude/skills/twelve-data/.env
echo "FMP_API_KEY=YOUR_KEY"          > .claude/skills/fmp/.env

# 5. Edit AGENTS.md USER CONFIG block (account size, risk %, phase, etc.)

# 6. Edit watchlist.md with your tickers, or use the CLI:
python3 .claude/skills/watchlist/wl.py add NVDA --thesis "AI semis"

# 7. Seed crypto unlock baseline (if using crypto)
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py baseline

# 8. First dashboard build (the first run scans 176 names ~22 min; subsequent are sub-second)
python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html
```

### Verify it worked

After step 8, opening `dashboard.html` in a browser, you should see:

1. **Header strip** — US macro regime (e.g. "CAUTIOUS") + crypto regime + halt-window timeline + budget bar (AV / TD / FMP usage)
2. **Risk Simulator panel** — pick any watchlist ticker; entry/stop/TP1/Size fields auto-prefill; gates show 12 doctrine checks
3. **US grid** — your watchlist tickers with RSI · ATR% · vs SMA50/200 · status badges
4. **🔭 Discovery panel** — sector rotation heat strip on top, 1-20 candidates tagged 💎/🏆/💰/⚡ below
5. **Watchlist Manager** — inline form to add/remove/update tickers
6. **Live quote buttons** — click 🔄 next to any US price → Finnhub real-time quote appears inline

If any panel is missing or shows "no data" warnings: check the corresponding `.env` file has its API key, then re-run step 8.

**Full setup walkthrough** including cross-platform notes (macOS / Linux / WSL), troubleshooting, and the bootstrap prompt for new agents: **[PROJECT_LOG.md](PROJECT_LOG.md#replication-steps)**.

## Project structure

```
trading-advisor/
├── AGENTS.md              # Doctrine: risk management, phased ramp, output format (read first)
├── PROJECT_LOG.md         # Replication guide: setup, API keys, gotchas, T3 optimization diffs
├── README.md              # This file
├── LICENSE                # MIT + trading disclaimer
├── watchlist.md           # Source of truth for tracked tickers
├── portfolio.md           # Current open positions (template)
├── rules/                 # Named playbooks + operational risk doctrine
│   ├── playbooks.md
│   └── risk-doctrine.md
├── journal/               # One markdown file per trade (entry-date based)
└── .claude/
    └── skills/            # 21 self-contained skills (data fetchers, analysis, CLI, dashboard)
        ├── dashboard/           # The main render skill
        ├── us-screener/         # Discovery: 176-name universe + Buffett Q+V
        ├── sector-rotation/     # 11 SPDR ETFs vs SPY
        ├── twelve-data/         # Bulk historical OHLCV
        ├── fmp/                 # Fundamentals (per-ticker)
        ├── finnhub/             # Live quotes (browser-embedded)
        ├── macro-rates/         # FRED composite regime
        ├── macro-calendar/      # FOMC/CPI/NFP halt-window gates
        ├── us-news/             # Alpha Vantage news + sentiment with budget tracking
        ├── crypto-coingecko/    # Crypto regime + per-coin data
        ├── crypto-derivatives/  # Binance funding + OI
        ├── crypto-unlocks-cache/# Token-unlock 48h halt gate
        ├── klse-refresh/        # Bursa Malaysia fundamentals
        ├── klse-announcements/  # Bursa filings + derived next-earnings date
        ├── watchlist/           # CLI for watchlist.md
        ├── journal/             # CLI for journal/*.md (prospectus → live → closed)
        └── ...                  # (full list in PROJECT_LOG.md)
```

## Doctrine in one paragraph

Never fabricate a number. Every price, indicator, fundamental, sentiment, or flow figure must come from a tool call this session — never from memory. Every recommendation states its invalidation level (the price/condition that proves the thesis wrong) and is sized so the dollar loss at that stop is bounded and known before entry. R-multiples beat dollar P&L; doctrine compliance beats individual outcomes. When in doubt, "no trade" is a valid output. Read [`AGENTS.md`](AGENTS.md) for the full ten-section doctrine.

## What this project is *not*

- A trading bot — there is no execution layer, no broker integration, no order placement
- A signal service — recommendations are produced when a human asks, not on a schedule
- Financial advice — see the [LICENSE](LICENSE) disclaimer
- A backtesting framework — calibration happens forward-only via the journaled trade record
- A market-data API — it consumes data from third parties; it does not provide one

## Supported agents

The project follows the emerging **`AGENTS.md`** convention so multiple coding agents can adopt it without forking.

| Agent | Status | How it loads the doctrine | Notes |
|---|---|---|---|
| **[Claude Code](https://claude.ai/code)** | ✓ Primary (built here) | Auto-loads `CLAUDE.md`, which points at `AGENTS.md` | All 21 skills tested. WebFetch skills (klse-*, crypto-unlocks) use Claude's WebFetch tool. |
| **[Codex](https://github.com/openai/codex)** | ✓ Compatible | Auto-loads `AGENTS.md` directly | Agent-only WebFetch skills will use whatever browsing tool Codex provides. Python CLI skills work identically. |
| Other agents | Should work | Read `AGENTS.md` first | Any agent that supports project-level instruction files and can invoke shell scripts can drive this project. |

The Python codebase, dashboard, data integrations, CLI tools, and doctrine are all platform-agnostic. Only the agent orchestration layer (which web-fetch tool, which scheduler) differs between platforms — and those are noted where they matter.

### Auto-bootstrap on session start

When you open Claude Code or Codex in this project folder, the agent will **automatically read** these three files before responding to your first message:

1. `notes/learned.md` — known gotchas so it doesn't re-discover landmines
2. `CHANGELOG.md` `[Unreleased]` + most recent shipped version
3. `git log --oneline -10` for recent context

It then orients with a 3-line summary (current version / last shipped change / anything in flight), then waits for your request. Cost: ~5 seconds on session start, zero for you.

**Skip the bootstrap** by prefixing your first message with `quick:` or `oneshot:` for small unrelated questions. **Disable entirely** by deleting the "Auto-bootstrap" section from `CLAUDE.md` and the "Session bootstrap" section from `AGENTS.md` in your fork.

## Changelog

Release history and the versioning policy are in **[CHANGELOG.md](CHANGELOG.md)**. The project uses a `MAJOR.MINOR` scheme: minor bumps (e.g. v1.0 → v1.1) for backward-compatible changes; major bumps (v1.x → v2.0) for doctrine or interface-breaking changes. Operators are encouraged to update the changelog when making meaningful changes — git, GitHub, and remote backups are entirely optional and nothing in the project pushes anywhere on your behalf.

## License

MIT — see [LICENSE](LICENSE) for the full text and the trading-specific disclaimer.

## Contributing

Issues and PRs welcome. If you propose a doctrine change, please open an issue first to discuss; the risk doctrine is the project's spine and changes there ripple through every other component.
