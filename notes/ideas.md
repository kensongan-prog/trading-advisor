# Ideas — future features and half-formed thoughts

Parking lot. Newest at top. **Do not act on these without explicit operator go-ahead** — they're not decisions, they're possibilities.

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
