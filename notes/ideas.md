# Ideas — future features and half-formed thoughts

Parking lot. Newest at top. **Do not act on these without explicit operator go-ahead** — they're not decisions, they're possibilities.

---

### 2026-06-11 — X (Twitter) as a 4th retail-sentiment leg

**Motivation:** Current retail stack is StockTwits (volume workhorse) + Reddit (meme-stocks) + HN (tech-substance) + Polymarket (money-weighted macro). All free tier. X would add **live retail pulse for fast-moving headline reactions** and **crypto-Twitter native signal**.

**Where X helps most:**
- Crypto sentiment — X is where crypto Twitter actually lives; Reddit's r/CryptoCurrency lags by hours
- Breaking-news reactions — tickers reacting to news in the first 30 minutes, faster than StockTwits cashtags fill up
- Influencer-driven moves (where the signal is direction-of-momentum not consensus)

**Where X helps least:**
- Established US equities with active StockTwits cashtags — duplicates
- Long-form opinion / fundamental analysis — Reddit/HN do this better

**Sketch:**
- `.claude/skills/x-sentiment/` mirroring `stocktwits-sentiment` shape
- Cashtag search (`$NVDA`, `$BTC`) with bot/spam filter (account age > 30d, follower count > N, no link-only posts)
- Raw cache → processed through the existing `sentiment_cache` classifier (relevance gate + LLM fallback already in place from v2.0.4/v2.0.6)
- Surfaces as 4th chip in the retail-sentiment column ("X: bull 47% · 60 tweets")
- Doctrine treatment: same as StockTwits/Reddit — contrarian filter, not primary signal

**Pricing reality (verified 2026-06-11, sources below):** X killed the tiered pricing model in February 2026. Current scheme is **pay-per-use**: $0.005 per post read, $0.010 per post create. Existing free-tier accounts got a one-time **$10 credit voucher** (~2,000 post reads) and then it's metered. **No recurring free tier exists.**

**Realistic monthly cost for this watchlist:**
- 80 posts/ticker × 25 tickers × daily refresh = ~$300/mo
- Top-10 active tickers × daily = ~$120/mo
- Top-5 × twice-weekly = ~$16/mo
- One-shot benchmark on $10 credit = $0

**Open questions:**
- Bot filtering — paid shills game cashtags. Pre-filter on account age + follower-to-following ratio before spending classifier tokens.
- Engagement weighting — likes vs reposts vs replies. Reposts are the strongest "moving-the-conversation" signal.
- KLSE coverage — Twitter has thin Bursa coverage; degraded-gracefully behavior as other sources.
- **Whether the signal justifies any cost** — needs a $10-credit benchmark run before committing to a recurring budget.

**Sources:** [Postproxy 2026 pricing](https://postproxy.dev/blog/x-api-pricing-2026/) · [xpoz.ai tier guide](https://www.xpoz.ai/blog/guides/understanding-twitter-api-pricing-tiers-and-alternatives/) · [SociaVault — free tier removed](https://sociavault.com/blog/twitter-api-alternative-2025)

**Status (2026-06-11):** Operator has a Bearer token from the pre-Feb-2026 free tier — now effectively a $10 credit. **Decided not to build** until either (a) X data becomes load-bearing for a specific signal gap, or (b) a free alternative re-emerges. Re-open this entry when one of those triggers.

---

### 2026-06-11 — One-click refresh from the Data Health rail chip — SHIPPED in v2.2.0

**Motivation:** Right now the see→fix loop for data degradation is: glance the DATA chip → click it (jumps to panel) → scroll to find the Control widget → click ⚡ Quick or 🔄 Full → wait. That's 3 clicks + scroll. The chip already knows *what's wrong* (transient vs permanent vs stale); it could trigger the right refresh kind directly.

**Outcome (v2.2.0):**
- `--refresh-stale` mode added to dashboard.py: reads the Data Health state, maps each stale/transient source to its REFRESH_VIA entry (flag / CLI / agent), enables the right flags, runs CLI tools first, then rebuilds.
- Per-source ↻ buttons in the Data Health panel for server-refreshable sources. Agent-only sources (crypto_unlocks) show an "agent" badge instead.
- "↻ refresh all stale" button in the panel header (calls Quick = --refresh-stale).
- Quick button now = --refresh-stale. DATA chip now counts only server-refreshable sources in "N refreshable" so it doesn't lie about things only an agent can fix.
- Fixed silent no-op: taRefresh now reads the response; when a job is busy, shows a message immediately instead of doing nothing.
- Progress banner at top of page while any job runs (not just when Control widget is open).
- Age text updates live every 2s poll cycle.
- Post-refresh toast: after reload, compares pre/post health counts and shows a diff ("5 cleared, 2 still stale").
- /api/refresh-source endpoint added (validates via health.validate_refresh_source, routes to --refresh-stale job).
- REFRESH_VIA registry in health.py maps every TTL_HOURS source to its refresh method. TTL gate mismatches fixed (screener: 18h→12h, polymarket: 18h→12h).

---

### 2026-06-10 — Data-health surface on the dashboard — SHIPPED in v2.1.0

Action Rail's 4th slot now shows DATA: `✓/⚠/🛑` summary; the `📊 Data Health` panel under the rail expands per-source breakdowns with chip counts (fresh/stale/transient-error/permanent-error/no-coverage/missing). State classifier in `.claude/skills/dashboard/health.py`, pure-logic tests in `tests/test_health.py` (41 tests). First deployment immediately surfaced 6 sentiment sources still cached in the pre-v2.0.6 HTTP 429 state — exactly the silent degradation this was meant to catch.

---

### 2026-06-10 — Paper-trade execution implementer

**Motivation:** The system already finds setups (Discovery, Setup Queue), drafts prospectuses (`j.py new`), and watches levels (`watcher.py`). But the operator still has to manually fill a prospectus and execute the paper trade. The 20-trade Phase-2 gate isn't filling because of that friction — every step exists but the chain takes effort to walk.

**Sketch:**
- "Take this trade as paper" button on each P1_READY row or each Setup Queue candidate.
- One click: writes the prospectus stub (`j.py new`), flips to LIVE — paper at the displayed sim levels, logs the entry. No keystrokes between "I see the setup" and "it's in the journal."
- Optional 2-step confirm: preview the prospectus that *would* be written, then commit.
- A paper-execution mode where the watcher fires "trigger hit — auto-flipped to LIVE-paper at fill price X" instead of just notifying — so the operator literally cannot miss it.

**Why deferred:** doctrine §1 says the agent never trades. Paper-trade-implementer is a soft interpretation — it's not real money, it's filling out the log on the operator's behalf — but it deserves explicit operator consent and a design pass to make sure it doesn't slide toward "agent decides when to enter." Worth designing carefully, not rushing.

**Could pair well with:** a journal-quality check that confirms every auto-paper-traded entry has a doctrine-eligible reason recorded before LIVE flip.

---

### 2026-06-09 — Standalone app (v2.0.0) — DESIGNED, DEFERRED

Decision: not worth the cost right now. The current static-HTML + paste-command workflow is friction-y but functional; rebuilding it as a long-running local server costs 5-6 weeks of focused work for a UX win that's nice-to-have, not load-bearing.

**Form factor we landed on if/when this resurfaces:**
- A: **local server + browser** (`tradingadvisor serve` → `localhost:8080`), single-user local-first
- B: Tauri-wrapped desktop app as a follow-up (~3-4 wk on top of A)
- C/D (multi-user web, mobile) explicitly out of scope
- Notifications deferred to v2.1+

**Architecture (high level):**
- FastAPI server (async) + APScheduler in-process for background jobs
- SQLite + WAL for runtime state; SQLAlchemy Core for migrations
- Jinja2 server-rendering the existing dashboard.html initially; SPA migration is a v2.x increment
- macOS Keychain (via `keyring`) for API key storage, `.env` fallback

**Key carve-out:** doctrine stays on disk. `AGENTS.md`, `CLAUDE.md`, `notes/*.md` continue to live as files so agent-session bootstrap keeps working. Only operational data (watchlist, journal, caches) migrates to DB. Watchlist + journal get auto-generated markdown export views so they're still readable in an editor.

**What gets harder if we wait:** every new skill (hn-sentiment, news_glyph, etc.) adds more JSON cache files + subprocess wiring the eventual migrator has to absorb. Manageable, but the surface area grows monotonically.

**What we recover if we do it:**
- Eliminate "paste command → wait → reload browser" workflow
- Real auto-refresh on schedules (news 1h, sentiment 6h, screener 18h)
- Job-status surface (last/next run, last error per job)
- Foundation for desktop wrapper, push notifications, mobile companion
- Query historical sentiment / discovery / news as a time series instead of grepping JSON

**Estimated effort:** 5-6 weeks (A only). +3-4 weeks for B.

**Phase plan if/when we pick it up:** Phases 0-7 outlined in the design conversation (foundation → migrator → skill wrapping → scheduler → dashboard adaptation → secrets → tests → beta). Migrator (Phase 1) is the highest-risk step — budget the full week, require dry-run + diff report before any DB write.

Trigger to revisit: (a) friction with the manual-refresh workflow becomes a sustained pain point across multiple weeks, or (b) we want notifications / scheduling badly enough that the cost-benefit flips, or (c) we want to give the dashboard to someone else and "git clone + run these Python scripts" stops being acceptable distribution.

---

### 2026-06-07 — Fundamentals-quality tag for Asian ADRs in the screener

Currently the screener's Buffett Q+V tagging (💎/🏆/💰) is US-equity-only. ADRs of Asian quality compounders (TSM, BABA, JD, NIO, SE, GRAB, etc.) could carry an additional 🌏 ASIA-Q+V tag if their fundamentals pass the same gross-margin / ROE / FCF-yield thresholds. Would need an ADR universe additions to the screener input list.

---

### 2026-06-07 — Notes folder convention (this file)

Adding `notes/` (ideas + decisions + learned) as a session-continuity layer. If this proves useful over a few weeks of real use, consider whether `journal/sessions/` (transcript dumps from past Claude sessions) is also worth adding for fully auditable continuity.

---

### Earlier ideas (no date — captured during initial build)

- Optional Telegram alert when a Risk Sim run produces a 🟢 GO verdict on a watchlist name (low-friction "this just became actionable" ping)
- Per-watchlist subdirectories so the operator can have a "core" watchlist and a "exploration" watchlist that the dashboard renders separately
- Screener tier-up: if the operator subscribes to FMP Starter, automatically expand fundamentals coverage from megacap to full universe and document the cost trade
- Backtesting framework — explicitly out of scope per AGENTS.md, but could become Phase 4 if the journaled record demonstrates enough doctrine adherence
