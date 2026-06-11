# Project Log — Trading Research & Advisory Agent

This file is the **replication guide**. Hand it (along with everything in the project folder) to another AI agent + operator pair and they should be able to stand up an identical instance.

**Read this together with `AGENTS.md`** (the agent's operating doctrine — 10 sections including the asymmetric strategy mandate, risk doctrine, and the phased ramp). The doctrine is the *what and why*; this file is the *how to build it*.

**Last reconciled with reality: v2.1.0 (2026-06-11).** Maintenance rule (see CLAUDE.md): update this file before tagging any MINOR or MAJOR release; PATCH releases don't touch it.

---

## TL;DR — what this project is

An AI-coding-agent project (Claude Code, Codex, or compatible) that produces grounded trading research and risk-managed recommendations across **US equities, KLSE (Bursa Malaysia) equities, and crypto**. Every recommendation must be backed by real, current data pulled this session via the project's wired skills — never fabricated. Operates under a Phase 1 / 2 / 3 ramp that unlocks more complex structures only after enough logged trades prove out.

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
| `reddit-sentiment` | Per-ticker posts + (OAuth-only) top comments — raw retail-forum cache | Reddit RSS (free) / OAuth (optional) | optional `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` |
| `stocktwits-sentiment` | Per-ticker messages + user-tagged bull/bear% — raw retail-forum cache | StockTwits public | none |
| `hn-sentiment` | Per-ticker stories + top comments via Algolia HN — the "less-gameable" retail leg (1.2× source weight) | Algolia HN | none |
| `sentiment-cache` | LLM-scores raw retail caches into composite per-ticker read with 🔥 FADE / 🧊 BUY contrarian flags; relevance-gated (primary/mention/none) since v2.0.4; transient-error fallback to gpt-oss-120b since v2.0.6 | OpenRouter free | `OPENROUTER_API_KEY` |
| `polymarket-events` | Implied probabilities on Fed cuts, recession, inflation, BTC/ETH ranges, geopolitics — money-weighted macro confluence (additive, not contrarian) | Polymarket Gamma | none |

### Analysis + discovery skills

| Skill | Purpose | Notes |
|---|---|---|
| `sector-rotation` | Rank 11 SPDR sector ETFs by composite vs SPY (1m/3m/6m weighted) | Twelve Data backend; 4h TTL; cooldown + stale fallback |
| `us-screener` | Curated 176-name universe scan: P1 technical gates + Buffett Q+V tagging | TD for technicals, FMP→yfinance fallback for fundamentals; tiered HOT/WARM/COLD cache |
| `dashboard` | Render `dashboard.html` (the operating surface) | Aggregates everything; supports `--with-discovery` for one-command refresh |
| `watchlist` | CLI for `watchlist.md` add/remove/update/resolve | Maintains resolution cache so new alts auto-discover their CoinGecko id + Binance pair |
| `journal` | Lifecycle CLI for `journal/*.md` (new / live / update / close / dead / R-multiple calc) | Backups + audit trail |

### Operator-loop CLIs (added v2.0.0 — signal → logged trade)

These live in `.claude/skills/dashboard/` alongside `dashboard.py` and are invoked either via the local server's control bar or directly from terminal.

| Tool | Purpose |
|---|---|
| `server.py` | Local control server at `http://localhost:8787`. Serves `dashboard.html` with a control bar (Quick / Full refresh, Watchlist form, Journal form, watcher start/stop). Hybrid auto-refresh: stale-by->12h triggers one quick refresh per session. `--lan` binds 0.0.0.0 for phone access (Tailscale-trusted networks). Launch via `Trading Dashboard.command` in project root. |
| `watcher.py` | Level/alert watcher — polls Finnhub during US market hours, fires macOS notifications on prospectus entry-trigger breaks, stop hits, TP1/TP2 touches, and watchlist names entering the Phase-1 band. Read-only and doctrine-clean: never trades, never writes journal. |
| `setup_queue.py` | Turns Phase-1-band watchlist names into decision-ready prospectus drafts (ATR stop, 2R TP1, §5 size math) with one click via `j.py new`. Cuts friction from "P1-ready" to "logged paper trade." |
| `portfolio.py` | Auto-derives portfolio heat + calibration metrics from the journal (source of truth). `j.py live` / `close` auto-regenerate `portfolio.md` — no hand-maintained drift. |
| `mae_mfe.py` | Daily snapshot recording max adverse / favourable excursion in R for every open position. Tells you whether stops are too tight or targets too small after 15-20 closes. |
| `rel_strength.py` | 1m return vs SPY + 3m + vs-sector-ETF spreads per US watchlist name. Batched yfinance download (avoids the per-ticker pattern). |
| `retired_scan.py` | Scans names in "Removed / retired" for forming 🧊 BUY re-entry conditions. Surfaces only when triggered — no row clutter. |
| `snap.py` | Playwright screenshot harness (desktop/tablet/mobile + per-component closeups). Uses project-local `.venv-playwright/`. |
| `health.py` | Pure-logic health classifier (fresh / stale / error_transient / error_permanent / no_coverage / missing) — backs the v2.1.0 Data Health surface. |
| `audit_glyph.py` (under `us-news/`) | Joins every LLM-scored news item to its source headline and flags FALSE-NONE / FALSE-PRIMARY / ROUNDUP / NON-ASCII / DIR-MISMATCH. |

### Dashboard features (rendered in `dashboard.html`)

**Action-first layout (v2.0.0 reorder — first screen answers "what's my R:R floor / can I trade right now / what setups are live?"):**

- **Action Rail (sticky top band)** — 4 slots: R:R floor (regime-derived), next macro halt window (red-pulsing 🛑 inside window), live setup chip counts (🟢 P1_READY, 🔥 FADE, 🧊 BUY, 🩸 BTFD, 🚀 STR), and a **DATA chip** (v2.1.0) — `✓ N% healthy` / `⚠ N sources need refresh` / `🛑 N permanent errors`.
- **Halt-window spotlight** — 2-event spotlight panel with countdown + 🛑 HALT WINDOW ACTIVE pill; full calendar collapses behind expander.
- **Action Zone** (green-bordered region — see→size is one eye movement):
  - **⚠ Contrarian Setups** — surfaces only names where retail FADE/BUY flags *align* with technical state (RSI/vs-SMA50 thresholds). The §4 operational rule: sentiment modifies conviction on existing setups; it doesn't generate them.
  - **🩸 BTFD / 🚀 STR — Price × Volume Setups** — 24h move × volume × RSI tiers (asset-class scaled). Cross-signal boosts/warnings (🧊 BUY on a BTFD-flagged name, halt-window proximity, earnings within 24h) layer inline.
  - **♻️ Retired re-entry forming** — names in "Removed / retired" that re-enter constructive 🧊 BUY conditions.
  - **Risk Simulator** — interactive form per market (US/KLSE/crypto); 12-gate doctrine check + R:R + heat math + "Create prospectus" command generator.
- **Active Prospectuses cards** + per-prospectus action forms (live / update / close with auto-R / dead).
- **US grid** — RSI · ATR% · vs SMA50/200 · earnings · **Retail/News** (composite badge + news glyph 🟢🔴⚪ with ❗ analyst-action modifier) · **vs SPY relative-strength** · P1 status. Click-to-expand: thesis + 8-gate breakdown + sentiment block + news 72h list + Polymarket markets. Sorted by tradability (P1_READY floats up). Status-coloured left border per row. One-click `→Sim` per row.
- **KLSE grid** — same shape with fundamentals + Bursa-filing watch + KLSE-specific news (klsescreener.com Chinese-press headlines correctly LLM-attributed since v2.0.1).
- **Crypto grid** — watchlist-declaration order (not market-cap), vs SMA50 · ATR% · funding · regime + expandable thesis + per-coin Polymarket markets.
- **🪙 Event Probabilities (Polymarket)** — money-weighted speculator consensus on Fed cuts, recession, inflation, BTC/ETH ranges, geopolitics. Color-coded by extremity; Δ7d arrows when historical snapshot is available.
- **Regime Read** — collapsed headline (`US Macro: ... · Crypto: ...`); full factor breakdown one click away.
- **📊 Data Health panel** (v2.1.0) — per-source rows with chip counts (✓/⏰/⚠/🛑/—/?); expandable per-ticker detail with exact error or staleness reason. The thing that makes degraded data visible instead of silently identical to good data.
- **🔭 Discovery panel** — sector-rotation heat strip + Q+V tagged candidates (💎 BUFFETT / 🏆 QUALITY / 💰 VALUE — ⚡ TECH retired in v1.9.1) with one-click "+ Add to watchlist". Tightened qualification (RSI 38-48, SMA50 slope ≥ 1%/5d).
- **Portfolio & Calibration panel** — auto-derived heat, sector-correlation warning, expectancy line, MAE/MFE per open position.
- **Watchlist Manager** — inline forms generating `wl.py add/remove/update` commands with live preview. 🗑️ remove buttons on every row.
- **Journal tail**.
- **Account KPI strip** — single-line collapsible (`$20k · Phase 1 · Heat $0/$1,200 · P2 gate · AV news`).
- **Live quote buttons** — 🔄 next to each US price (Finnhub real-time), 🔄 for crypto (Binance/CoinGecko), 📊 link for KLSE (klsescreener.com).
- **Status badge tooltips** explaining every state ("OVERBOUGHT", "DOWNTREND", etc.) with recommended action.
- **Refresh dropdown** — 3 options: ↻ Quick (cache-only, ~10-15s) / 📰 News (fresh AV + Finnhub + klsescreener + crypto RSS, LLM-score new items) / ⟳ Full (sentiment + Polymarket + force-refetch all).
- **Mobile layout (≤780px / ≤420px)** — Action Rail stacks, halt spotlight reflows, BTFD/Contrarian rows wrap, Risk Simulator becomes single-column, big grids horizontally scroll inside their panels. `theme-color` meta for iOS Safari. Validated via Playwright at 1440×900 / 768×1024 / 390×844.
- **Viewer-timezone reformat** — every absolute UTC timestamp (Built at, halt event times, fmt_fetched chips) gets rewritten to the viewer's browser timezone via `Intl.DateTimeFormat`. Static HTML stays portable across build host / viewing device.

### Architectural patterns established

- **Cache + cooldown + stale-fallback** for every external data source (rate limits never crash the dashboard)
- **Budget tracking** for capped APIs (AV 25/day, TD 800/day, FMP 250/day) with soft + hard caps + on-demand reserves
- **Budget visualization** — header bar shows AV/TD/FMP usage % live, color-coded green/yellow/red (T3-B2)
- **Tiered cache TTLs** (HOT 24h / WARM 72h / COLD 7d) for the screener so daily calls stay low
- **Daily-only markers** — full screener pass < 18h ago short-circuits the next refresh
- **Skip-if-fresh subprocess spawn** — `dashboard.py --with-discovery` skips spawning subprocesses when their caches are still warm
- **Provider fallback chains** — FMP paywalled symbol → yfinance fallback; yfinance NaN-Close bar → Twelve Data fallback
- **LLM fallback chains** — both the news-glyph scorer AND `sentiment-cache.classify_messages` retry with `gpt-oss-120b:free` on transient errors from Gemma (v2.0.6 closed the parity gap; the fallback constant was defined but never referenced before that release). `_is_transient_error` explicitly enumerates 429/5xx/URLError/timeout so future tweaks can't accidentally widen the trigger.
- **Live quote endpoints** are browser-side (JS fetches Finnhub/Binance directly), separate from cached daily-close pipeline
- **Bulk resolution cache** — single directory scan instead of per-ticker file reads (T3-S2)
- **Parallel I/O** — yfinance per-ticker calls use `ThreadPoolExecutor` (T3-S3)
- **Watchlist auto-inclusion** in screener universe (T3-E3)
- **Per-item LLM-score immutability** — news headlines and forum messages are immutable once published, so per-item LLM scores key on `hash(text)` and bank forever. Re-fetches only re-score the truly new items, keeping OpenRouter spend near zero after warmup.
- **Relevance gate on every LLM scorer** — `relevance: primary|mention|none` with weights 1.0/0.5/0.0 in the aggregate. Off-topic items drop out instead of polluting bull/bear% (solves the SOL ↔ "Microsoft Project Solara" type collision). Same trichotomy in both `news_glyph` and `sentiment_cache.classify_messages`, single `COMPANY_LABELS` source-of-truth.
- **Engagement-weighted sentiment** — each Reddit post / StockTwits message / HN comment contributes `1 + log1p(engagement)` instead of equal weight. Logarithmic so one viral 50k-upvote post can't drown out the sample. v1.9.0.
- **Symbol-keyed joins (not zip-by-index)** — the crypto grid + BTFD panel + Action Rail all look up rows by ticker explicitly because `crypto_rows` comes back from CoinGecko in market-cap order and zip-pairing silently mis-pairs candidates. Bug found twice in production (v1.7.0, v2.0.3); `test_data_join.py` now locks the regression.
- **Hoisted shared classifiers** — `_classify_btfd_str_shared` lives at module scope so both the Action Rail count and the BTFD/STR panel reference the same function (v2.0.3 — they used to be independent code paths and drifted on every threshold tweak).
- **Health-state taxonomy** — every data source classified into one of six explicit states (`fresh` / `stale` / `error_transient` / `error_permanent` / `no_coverage` / `missing`). Degraded data must never render identically to good data. v2.1.0.

### Test suite (added v2.0.5, expanded v2.0.6 + v2.1.0 — currently 153 tests, ~3s)

Pure-logic regression net under the dashboard's silent-failure surfaces. Every bug fix in the v2.0.x → v2.1.0 series left a regression test behind.

| File | Covers |
|---|---|
| `test_r_math.py` | `j.compute_r` single-leg + partial fills + entry-above-stop invariant. Drives every calibration metric the Phase-2 gate depends on. |
| `test_btfd_str.py` | Full tier table for `_classify_btfd_str_shared` (equity + crypto, all three tiers each direction). Pins the thresholds the Action Rail + BTFD panel both reference. |
| `test_us_status.py` | Phase 1 status gating across P1_READY, blocked tiers, warnings, edge cases (missing SMA200, macro halt windows). |
| `test_llm_pcts.py` | Relevance-weighted aggregation. Pins the weight constants (primary 1.0, mention 0.5, none 0.0), engagement-weighting interactions, all-off-topic fallback, backward compat for legacy classifications. |
| `test_company_label.py` | TICKER→company-name resolution across asset classes. Parametrized over every watchlist ticker so no future watchlist add can land without a label. |
| `test_data_join.py` | Symbol-keyed join regression test. Documents both correct pattern AND the zip-bug pattern; fails the moment anyone re-introduces it. |
| `test_classifier_fallback.py` | `_is_transient_error` parametrized across 7 transient codes (429, 5xx, URLError, timeout) + 6 permanent ones. `classify_messages` retries fallback exactly once on 429, doesn't retry on 401, no infinite loop when caller already specifies fallback. |
| `test_health.py` | State classifier across every state + TTL boundaries + all 5 timestamp-key variants different caches use + sentiment-composite classifier (including exact RGLD failure mode) + summarizer counts + state priority. |

Run: `.venv-playwright/bin/python3 -m pytest --tb=line -q` (the project-local venv since pytest isn't installed system-wide). Auto-runs at session start per `CLAUDE.md`.

---

## Architecture overview

```
                            ┌────────────────────────────────┐
                            │       AGENTS.md (doctrine)     │
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
| Claude Code (or Codex) | Install from `claude.ai/code` | Install from `claude.ai/code` | Use WSL2 (recommended) — most scripts assume Unix shell |
| pandas + yfinance | `pip3 install pandas yfinance` | same | same |
| pytest (for the session-bootstrap test gate) | `python3 -m venv .venv-playwright && .venv-playwright/bin/pip install pytest playwright` | same | same |
| Playwright Chromium (optional, for `snap.py` screenshot harness) | `.venv-playwright/bin/playwright install chromium` | same | same |
| node (optional) | `brew install node` | distro pkg manager | from nodejs.org |

`node` is only used for the JS syntax check at the end of `dashboard.py`; it's `--check` only, doesn't run anything. Dashboard works without it.

**macOS-specific gotcha**: yfinance's bulk download (`yf.download(multiple_tickers, ...)`) triggers macOS XProtect false-positive ("Malicious Script Blocked") on recent macOS versions. The screener and sector-rotation skills work around this by using Twelve Data instead. Per-ticker `yf.Ticker(t).history()` and `.info` calls do **not** trigger it — keep those.

### Step 1: Copy the project folder

Take the entire `Trading Advisor/` directory and place it under whatever project root the brother prefers (e.g. `~/Documents/Claude/Projects/Trading Advisor/`).

**Files to copy:**
- `AGENTS.md`, `CLAUDE.md` (CLAUDE auto-loads its bootstrap; AGENTS.md is the cross-agent doctrine)
- `PROJECT_LOG.md` (this file)
- `CHANGELOG.md` (version history)
- `notes/learned.md`, `notes/decisions.md`, `notes/ideas.md` (gotcha log + decision rationale + deferred-features log)
- `.gitignore`
- `.claude/skills/` (all 27 skill folders)
- `tests/` (153 pytest cases — the session-bootstrap test gate runs these)
- `rules/` (playbooks + risk doctrine)
- `journal/README.md` (keep the template; rest can be empty)
- `watchlist.md` (keep as a template — see Step 5)
- `portfolio.md` (template — auto-regenerated by `portfolio.py` once the journal has entries)
- `Trading Dashboard.command` (double-click launcher for `server.py`)

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
| 7 | **OpenRouter** (required for sentiment + news LLM scoring) | https://openrouter.ai/keys | Free tier (Gemma 4 31B IT + GPT-OSS 120B both free) | LLM-scoring of retail forum messages, news headline sentiment + relevance, KLSE Chinese-headline attribution |
| 8 | **Reddit OAuth** (optional, unlocks per-comment upvote weighting) | https://www.reddit.com/prefs/apps → "create app" → script type | Free, 2-4 week review | Engagement-weighted comment scoring on Reddit. Without it, the skill auto-degrades to RSS with uniform comment weight (still works, just less precise). |

For each, drop the key into the matching skill's `.env` file:

```bash
echo "FRED_API_KEY=YOUR_KEY"         > .claude/skills/macro-rates/.env
echo "ALPHAVANTAGE_API_KEY=YOUR_KEY"  > .claude/skills/us-news/.env
echo "FINNHUB_API_KEY=YOUR_KEY"       > .claude/skills/finnhub/.env
echo "TWELVE_DATA_API_KEY=YOUR_KEY"   > .claude/skills/twelve-data/.env
echo "FMP_API_KEY=YOUR_KEY"           > .claude/skills/fmp/.env
echo "OPENROUTER_API_KEY=YOUR_KEY"    > .claude/skills/sentiment-cache/.env
# CoinGecko Pro optional:
# echo "COINGECKO_API_KEY=YOUR_KEY"   > .claude/skills/crypto-coingecko/.env
# Reddit OAuth optional (auto-detected when present):
# echo "REDDIT_CLIENT_ID=YOUR_KEY"    > .claude/skills/reddit-sentiment/.env
# echo "REDDIT_CLIENT_SECRET=YOUR_KEY" >> .claude/skills/reddit-sentiment/.env
```

Each skill's `.env.template` shows the expected variable name.

### Step 3: Fill in `AGENTS.md` USER CONFIG

Open `AGENTS.md` and scroll to the bottom — the `USER CONFIG` block. Edit:

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

**First — confirm the test gate is green:**

```bash
.venv-playwright/bin/python3 -m pytest --tb=line -q
```

Should report `153 passed in ~3s`. If anything is red, fix the test or capture it in `CHANGELOG.md` `[Unreleased]` before stacking more code on top — every session's bootstrap re-runs this and refuses code changes on a red suite (`CLAUDE.md` contract).

**Then — open `dashboard.html` (or `http://localhost:8787` via `Trading Dashboard.command`) and walk through:**

1. ✅ **Action Rail** at top (sticky) — 4 slots: R:R floor, halt-window status, live setup chip counts, DATA health chip
2. ✅ **Halt-window spotlight** with countdown to next FOMC/CPI/NFP
3. ✅ **Action Zone** — Contrarian Setups + BTFD/STR + Risk Simulator clustered together
4. ✅ Risk Simulator (try picking a ticker, fill in entry/stop/TP1, see 12-gate verdict)
5. ✅ Active Prospectuses cards (empty on a fresh install — populates as `j.py new` runs)
6. ✅ US grid with technical columns + Retail/News glyph + relative-strength column + status badges
7. ✅ KLSE grid (if any KLSE tickers in watchlist)
8. ✅ Crypto grid (in watchlist-declaration order)
9. ✅ 🪙 Polymarket Event Probabilities panel
10. ✅ 📊 Data Health panel — expand a source row to see per-ticker detail
11. ✅ 🔭 Discovery panel with sector-rotation heat strip + Q+V candidates
12. ✅ Portfolio & Calibration panel (shows "no open positions" on fresh install)
13. ✅ Watchlist Manager form
14. ✅ Click a 🔄 button next to any US price → live Finnhub quote appears inline
15. ✅ Click a row chevron → expandable details with gate breakdown + thesis + sentiment block + 72h news list + Polymarket markets
16. ✅ Click `→Sim` on any P1-ready row → Risk Simulator loads ticker + prefills entry / 1.5×ATR stop / 2R TP1 / max size, scrolls itself into view
17. ✅ Mobile check (open `dashboard.html` on phone via Tailscale or `server.py --lan`) — Action Rail stacks, grids horizontally scroll inside their panels

If a per-source data row shows ⚠ or 🛑 in the Data Health panel, click it for the exact reason (transient 429, stale TTL, missing cache file, permanent auth failure). Then refresh that source via the appropriate CLI or the dashboard refresh dropdown.

If sentiment shows UNKNOWN across many tickers: confirm `OPENROUTER_API_KEY` is set and `sentiment-cache` re-scored after the v2.0.6 fallback was wired in.

---

## Day-to-day operator usage

### Daily routine (~2 min)

**Preferred — local control server (terminal-free):**

Double-click `Trading Dashboard.command` in the project root. Opens `http://localhost:8787` with control bar:
- **⚡ Quick refresh** — prices/macro/Polymarket (~10-15s, auto-tails the build log)
- **🔄 Full refresh** — Quick + sentiment + news + news-glyph + discovery (always manual press)
- **Watchlist** + **Journal** forms wired to `wl.py` / `j.py`
- **Watcher** start/stop (level alerts + macOS notifications during market hours)

Hybrid policy: when the dashboard is >12h old, a quick refresh fires automatically once per browser session. LLM-scored sentiment never auto-runs (that's deliberate — OpenRouter free-tier 429s during burst scoring).

**CLI fallback (when not using the server):**

```bash
# Refresh dashboard with discovery scan (skips fresh caches automatically)
python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html
```

### When you want fresh news for a watchlist ticker

```bash
# Per-row news-glyph refresh — re-fetches all sources at hourly TTL + LLM-scores new items
python3 .claude/skills/dashboard/dashboard.py --refresh-news-glyph

# Legacy single-shot news+sentiment refresh (still burns 1 of 25 daily AV calls)
python3 .claude/skills/dashboard/dashboard.py --refresh-news
```

### When you want fresh retail sentiment

```bash
# Force-refresh sentiment for all watchlist tickers (Reddit + StockTwits + HN raw fetch → LLM score)
python3 .claude/skills/dashboard/dashboard.py --refresh-sentiment

# Or on a single ticker (avoids OpenRouter 429s during burst scoring):
python3 .claude/skills/sentiment-cache/score_ticker.py NVDA --force

# If Gemma is rate-limited, start on the fallback model directly:
python3 .claude/skills/sentiment-cache/score_ticker.py NVDA --model openai/gpt-oss-120b:free
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

### OpenRouter free-tier 429s on consecutive scores
`gemma-4-31b-it:free` 429s easily during batched scoring runs. Since v2.0.6, both `news_glyph` and `sentiment_cache.classify_messages` retry with `gpt-oss-120b:free` on transient errors — so a single 429 no longer kills a source. **But if BOTH models are rate-limited simultaneously, the source still fails.** For large batch re-scoring sessions: pass `--model openai/gpt-oss-120b:free` to start on the fallback directly, or space requests ~60s apart.

### KLSE non-English headlines need a company-label in the LLM prompt
The news-glyph scorer used to send `TICKER: 9431` — semantically opaque to the LLM, no way to know `9431 = Seni Jaya = 盛艺机构`. Chinese-press headlines silently scored `relevance=none`, dropping ~80% of the KLSE news signal. Fixed in v2.0.1 via the `COMPANY_LABELS` map (carries both Latin AND Chinese forms for KLSE). **When adding a new KLSE name to the watchlist, hand-add a `COMPANY_LABELS` entry** for it — can't be auto-derived from the watchlist's English-only thesis line. Same map is now used by `sentiment_cache.classify_messages` (v2.0.4) so HN/Reddit/StockTwits also resolve company names correctly.

### Zip-by-index silently mis-pairs crypto rows
CoinGecko returns market-cap-ordered data; the watchlist is operator-declaration-ordered. Any code that does `zip(watchlist.crypto, crypto_rows)` will pair the wrong data per ticker — found twice in production (v1.7.0 live-quote button, v2.0.3 BTFD panel). **Always look up crypto rows by ticker explicitly** (`_rows_by_sym = {sym: row for ...}`). `test_data_join.py` locks the regression.

### Mobile expanded-row dropdown inherited table min-width
The mobile CSS gives the watchlist table `tbody { min-width: 1100px }` so columns stay legible. The expanded-row `<tr>` lives inside that same tbody, so the `<td>` inherited 1100px+ and rendered ~1543px wide on a 390px viewport. Fix: `.exp-details-content` uses `position: sticky; left: 0; max-width: calc(100vw - 24px)` so it visually clamps to viewport regardless of horizontal scroll. v2.0.3.

### Dashboard auto-scroll past the Action Zone (caught by Playwright)
The Watchlist Manager's add-form auto-focused its ticker input on initial render → Chrome scroll-jacked past the entire action-first layout. Auto-focus now only fires on user-driven tab click. Invisible to code review; caught only by `snap.py`'s fresh-load fold screenshot. **Lesson: visual regression suite earns its keep on UI changes that don't break tests but do break the user experience.** v2.0.0.

### Degraded data renders identically to good data
v2.0.x found four bugs where the dashboard rendered cleanly but inputs were silently wrong (crypto-zip × 2, KLSE Chinese-headline silent score=none, HN comment-filter dropping coverage, sentiment 429s hiding behind `present:false`). The v2.1.0 Data Health surface explicitly distinguishes fresh / stale / transient-error / permanent-error / no-coverage / missing per source — degraded data now triggers an operator-visible warning instead of silently identical rendering. **When adding a new data source: register it with `health.py`'s TTL table** so the panel can classify it.

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
- **Options chain wiring for Phase 3** (currently dark — see AGENTS.md PHASED RAMP)
- **Perp simulator** (Phase 3 unlock — leverage + liquidation math)
- **Sector ETF correlation matrix** in Discovery panel
- **Phase progression tracker** (count closed trades + R-multiple toward Phase 2 gate)

---

## File structure reference

```
Trading Advisor/
├── AGENTS.md                      # Doctrine + USER CONFIG (10 sections)
├── CLAUDE.md                      # Bootstrap shim — pointer to AGENTS.md + auto-bootstrap rules
├── PROJECT_LOG.md                 # This file — replication/handover guide
├── CHANGELOG.md                   # Version history (semver MAJOR.MINOR.PATCH since v1.4.1)
├── .gitignore                     # Excludes .env, dashboard.html, caches, .venv-playwright, .agents/
├── pytest.ini                     # Test runner config
├── watchlist.md                   # Source of truth for tracked tickers
├── portfolio.md                   # Auto-derived from journal by portfolio.py (don't hand-edit)
├── dashboard.html                 # Generated artifact (don't edit)
├── Trading Dashboard.command      # Double-click launcher for server.py
├── notes/
│   ├── learned.md                 # Append-only gotcha log, newest first (auto-loaded at session start)
│   ├── decisions.md               # Why things are the way they are (read on demand)
│   └── ideas.md                   # Deferred features + investigations (read on demand)
├── rules/
│   ├── playbooks.md               # Named pre-approved setups (P1, P2, P3)
│   └── risk-doctrine.md           # Operational expansion of AGENTS.md §5-6
├── journal/
│   ├── README.md                  # Journal entry template
│   └── YYYY-MM-DD_TICKER.md       # One file per trade
├── tests/                         # 153 pytest cases (~3s); session bootstrap runs these
│   ├── conftest.py
│   ├── README.md                  # What's covered, what's not, contract for adding regression tests
│   ├── test_r_math.py
│   ├── test_btfd_str.py
│   ├── test_us_status.py
│   ├── test_llm_pcts.py
│   ├── test_company_label.py
│   ├── test_data_join.py
│   ├── test_classifier_fallback.py
│   └── test_health.py
├── .venv-playwright/              # Project-local venv: pytest + Playwright (don't commit)
└── .claude/
    ├── cache/                     # Runtime data (don't commit)
    └── skills/                    # 27 skill folders, each with SKILL.md + code
        ├── crypto-coingecko/
        ├── crypto-derivatives/
        ├── crypto-unlocks/         # Agent-only (WebFetch)
        ├── crypto-unlocks-cache/
        ├── dashboard/              # The main render skill + server.py + watcher.py
        │                           # + setup_queue.py + portfolio.py + mae_mfe.py
        │                           # + rel_strength.py + retired_scan.py + snap.py + health.py
        ├── finnhub/
        ├── fmp/
        ├── hn-sentiment/           # NEW (v1.9.0) — third retail-sentiment leg
        ├── hyperliquid-flow/
        ├── journal/
        ├── klse-announcements/
        ├── klse-history/
        ├── klse-news/              # Agent-only (WebFetch)
        ├── klse-quote/             # Agent-only (WebFetch)
        ├── klse-refresh/
        ├── macro-calendar/
        ├── macro-rates/
        ├── polymarket-events/      # NEW (v1.5.0) — macro confluence leg
        ├── reddit-sentiment/       # NEW (v1.5.0) — raw retail-forum cache
        ├── sector-rotation/
        ├── sentiment-cache/        # NEW (v1.5.0) — LLM scorer + composite + 🔥/🧊 flags
        ├── stocktwits-sentiment/   # NEW (v1.5.0) — raw retail-forum cache
        ├── twelve-data/
        ├── us-fundamentals/
        ├── us-news/                # + news_glyph.py + audit_glyph.py (v1.8.0)
        ├── us-screener/
        └── watchlist/
```

---

## Doctrine summary (read `AGENTS.md` for full text)

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
"Read AGENTS.md (doctrine + USER CONFIG), PROJECT_LOG.md (this file —
replication guide), CHANGELOG.md (version history + what's [Unreleased]),
and notes/learned.md (known gotchas). Then run the test suite
(.venv-playwright/bin/python3 -m pytest --tb=line -q), check the .env files
for any missing API keys, try a dashboard build, and tell me what's working
and what's missing. Don't make any recommendations until I've confirmed
the setup is complete."
```

The agent should:
1. Read AGENTS.md + PROJECT_LOG.md + CHANGELOG.md + notes/learned.md (doctrine + replication + version history + gotchas)
2. Run the pytest suite — green is the gate; if red, flag and stop before code changes
3. List which API keys are configured vs missing (FRED, AV, Finnhub, TD, FMP, OpenRouter are required; Reddit OAuth + CoinGecko Pro are optional)
4. Try a build (will fail gracefully on missing keys)
5. Report status + ask for missing pieces

If your harness uses a different file convention (e.g. Cursor's `.cursorrules`), add a one-paragraph pointer there saying *"The operating doctrine lives in AGENTS.md — read that first."* AGENTS.md is the cross-agent canonical; never duplicate doctrine across pointer files.

---

## Versioning + changelog

The project uses **`MAJOR.MINOR.PATCH`** semver (adopted v1.4.1) tagged in git as `vX.Y.Z`:

| Bump | When |
|---|---|
| **PATCH** (e.g. v2.1.0 → v2.1.1) | Backward-compatible fix, no new capability, operator's mental model unchanged |
| **MINOR** (e.g. v2.0.6 → v2.1.0) | New capability (skill, panel, field, command, convention) OR mental model shifts |
| **MAJOR** (e.g. v1.x → v2.0.0) | Doctrine §1-10 change re-classifying past recommendations, breaking interface, existing setup silently breaks |

**When you make a meaningful change, update `CHANGELOG.md`.** Add entries under `## [Unreleased]` at the top, categorized as `### Added` / `### Changed` / `### Fixed` / `### Removed` / `### Deprecated` / `### Security`. Write entries from the user's perspective, past tense. When ready to release, rename `[Unreleased]` to the new version and create a fresh empty `[Unreleased]` above it.

**For MINOR and MAJOR releases additionally, update PROJECT_LOG.md (this file).** Edit sections in place to reflect the new capability — new skill/tool row, new env var, new convention. The changelog owns history; the log describes *now*. PATCH releases don't touch it. Rule added 2026-06-11 after the log drifted from v1.3 to v2.1.0 unmaintained.

**Pre-release checklist** (every PATCH / MINOR / MAJOR):
1. Run `.venv-playwright/bin/python3 -m pytest --tb=line -q` — green is the floor for shipping (v2.0.5 contract). Never tag against a red suite.
2. If MINOR or MAJOR: update PROJECT_LOG.md.
3. Rename `[Unreleased]` to `vX.Y.Z` + ISO date in CHANGELOG.md, open a fresh `[Unreleased]`.
4. `git tag -a vX.Y.Z -m "Short release summary"` (optional but recommended).

**Git, GitHub, and remote backups are entirely optional.** The project ships with no automatic git or GitHub operations — nothing pushes anywhere on your behalf. You can use the changelog policy with or without version control. If you do maintain a git repository, you can optionally tag and publish releases (`git tag -a vX.Y.Z` + `git push origin vX.Y.Z` + `gh release create vX.Y.Z` — see `CHANGELOG.md` for the full optional workflow).

Full policy + procedure live in `CHANGELOG.md`. **If you're unsure whether a change is PATCH, MINOR, or MAJOR, ask the operator. Never silently break a published interface or doctrine.**

---

## Acknowledgment

This project was built incrementally across many sessions. The skill-by-skill architecture, doctrine-first design, and cache+cooldown patterns emerged from real operational experience — especially the painful discovery that yfinance bulk downloads trigger macOS XProtect, Yahoo IP-bans bursts, FMP free is megacap-only, and Finnhub dropped historical from free in 2024. **The replication target is not "perfect first build" but "self-healing system that survives provider misbehavior."**

If the brother's setup hits a wall, the most likely culprits in order:
1. Missing API key in a `.env` file
2. yfinance flaking on macOS (try `pip3 install --upgrade yfinance`)
3. Provider rate limit (look for stale flags in the dashboard headers)
4. Cache out of sync (`rm -rf .claude/cache/` and rebuild — costs one full Twelve Data scan ~22 min)

Good luck.
