# Ideas — future features and half-formed thoughts

Parking lot. Newest at top. **Do not act on these without explicit operator go-ahead** — they're not decisions, they're possibilities.

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
