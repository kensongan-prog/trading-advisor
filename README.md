# Trading Advisor

A doctrine-driven trading research agent that produces grounded, risk-managed recommendations across US equities, KLSE (Bursa Malaysia), and crypto — all backed by real, current data pulled at recommendation time.

Built as a Claude Code project. Outputs a self-contained static HTML dashboard plus a journaled record of every prospectus, live position, and closed trade.

> ⚠️ **Research tool, not financial advice.** This software does not execute trades and does not provide personalized investment recommendations. See [LICENSE](LICENSE) for the full disclaimer.

---

## What it does

- **Pulls real-time technical, fundamental, news, and macro data** from 7+ providers (FRED, Twelve Data, FMP, yfinance, CoinGecko, Binance, Alpha Vantage, Finnhub)
- **Enforces a written risk doctrine** (see [`CLAUDE.md`](CLAUDE.md)) on every recommendation — bounded downside, R-multiples, position sizing math, event-window halts (FOMC/CPI/NFP/earnings/token unlocks)
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

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/trading-advisor.git
cd trading-advisor

# 2. Dependencies
pip3 install pandas yfinance

# 3. Sign up for free API keys (~15 min total)
#    See PROJECT_LOG.md → "Step 2: Sign up for the API keys"
#    Required: FRED, Alpha Vantage, Finnhub, Twelve Data, FMP
#    Optional: CoinGecko Pro

# 4. Drop keys into .env files
echo "FRED_API_KEY=YOUR_KEY"         > .claude/skills/macro-rates/.env
echo "ALPHAVANTAGE_API_KEY=YOUR_KEY" > .claude/skills/us-news/.env
echo "FINNHUB_API_KEY=YOUR_KEY"      > .claude/skills/finnhub/.env
echo "TWELVE_DATA_API_KEY=YOUR_KEY"  > .claude/skills/twelve-data/.env
echo "FMP_API_KEY=YOUR_KEY"          > .claude/skills/fmp/.env

# 5. Edit CLAUDE.md USER CONFIG block (account size, risk %, phase, etc.)

# 6. Edit watchlist.md with your tickers, or use the CLI:
python3 .claude/skills/watchlist/wl.py add NVDA --thesis "AI semis"

# 7. Seed crypto unlock baseline (if using crypto)
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py baseline

# 8. First dashboard build (the first run scans 176 names ~22 min)
python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html
```

Full setup walkthrough including cross-platform notes (macOS / Linux / WSL): **[PROJECT_LOG.md](PROJECT_LOG.md)**.

## Project structure

```
trading-advisor/
├── CLAUDE.md              # Doctrine: risk management, phased ramp, output format (read first)
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

Never fabricate a number. Every price, indicator, fundamental, sentiment, or flow figure must come from a tool call this session — never from memory. Every recommendation states its invalidation level (the price/condition that proves the thesis wrong) and is sized so the dollar loss at that stop is bounded and known before entry. R-multiples beat dollar P&L; doctrine compliance beats individual outcomes. When in doubt, "no trade" is a valid output. Read [`CLAUDE.md`](CLAUDE.md) for the full ten-section doctrine.

## What this project is *not*

- A trading bot — there is no execution layer, no broker integration, no order placement
- A signal service — recommendations are produced when a human asks, not on a schedule
- Financial advice — see the [LICENSE](LICENSE) disclaimer
- A backtesting framework — calibration happens forward-only via the journaled trade record
- A market-data API — it consumes data from third parties; it does not provide one

## Built with

[Claude Code](https://claude.ai/code) — the project is structured as a collection of Claude Code skills with shared cache and doctrine. Any Claude Code instance with this repository checked out and API keys in place will produce identical behavior.

## License

MIT — see [LICENSE](LICENSE) for the full text and the trading-specific disclaimer.

## Contributing

Issues and PRs welcome. If you propose a doctrine change, please open an issue first to discuss; the risk doctrine is the project's spine and changes there ripple through every other component.
