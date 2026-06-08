# Changelog

All notable changes to this project are recorded here.

---

## Versioning policy

This project uses a **two-level scheme**: `MAJOR.MINOR`.

| Bump | When | Examples |
|---|---|---|
| **MINOR** (e.g. v1.0 → v1.1) | Backward-compatible additions, bug fixes, small features, optimization, documentation updates, new data sources for existing functionality, threshold tuning | Adding a new column to a grid; fixing a calculation bug; tuning a cache TTL; adding a tooltip; documenting a new caveat |
| **MAJOR** (e.g. v1.x → v2.0) | Doctrine changes, breaking interface changes, new asset class, phase unlock mechanic changes, architectural rewrites, new top-level skill that other skills depend on | Adding options trading support (Phase 3 unlock); changing the Risk Simulator's gate count; rewriting the cache layer; flipping `--with-discovery` default behavior |

Versions are tagged in git as `vX.Y` (e.g. `v1.0`, `v1.1`, `v2.0`) and mirrored as GitHub releases.

---

## Procedure for adding a changelog entry

This file is a manually-maintained log. **The workflow applies whether or not you use git/GitHub.** Maintaining the changelog is good practice for traceability; whether you back up to a public repo, a private repo, a local-only git folder, or no version control at all is entirely your choice. The project ships with **no automatic git or GitHub operations** — nothing in this repository will push anywhere on your behalf.

### Steps

1. **Whenever you make a meaningful change**, add an entry under `## [Unreleased]` at the top of this file (below the policy section).
2. **Categorize each change** under one of: `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Deprecated`, `### Security`.
3. **Write entries in the past tense, from the user's perspective**, not the developer's. Example:
   - ✓ Good: `Status badges now show a hover tooltip explaining what the state means and what action it implies.`
   - ✗ Bad: `Added tooltip rendering logic to badge HTML in render_us_grid().`
4. When you decide a batch of changes constitutes a release, **rename `[Unreleased]` to the new version + ISO date**, then create a fresh empty `[Unreleased]` section above it.

### Optional: tag + publish (only if you use git/GitHub)

If you maintain a git repository for this project and want to mark the release with a tag (and optionally a GitHub release), the workflow is:

```bash
git add CHANGELOG.md
git commit -m "Release vX.Y"
git tag -a vX.Y -m "Short release summary"
git push                # only if you have a remote configured
git push origin vX.Y    # only if you have a remote configured
gh release create vX.Y --title "vX.Y — <theme>" --notes "<excerpt from changelog>"  # only if you use gh
```

**None of these steps are required to use the project.** They're conveniences for operators who want a public or backed-up release history.

**Doctrinal rule:** if you are not sure whether a change is MAJOR or MINOR, ask the operator (or, if you are the operator, sit with the question for a moment). **Never silently break a published interface or doctrine.**

---

## [Unreleased]

### In flight (as of 2026-06-07)

**XProtect re-blocking screener (yfinance fundamentals fallback path)** — macOS XProtect has tightened signatures over 2026; per-ticker `yf.Ticker(t).info` calls in a loop (~130 non-megacap symbols in `screener.py:420`) now match a blocked pattern, not just the bulk `yf.download()` we already disabled. Investigation paused mid-discussion.

Next step: run the Option C diagnostic (test whether 5/10/50 sequential yfinance calls trigger XProtect) to confirm whether it's rate-based or signature-based. Then either:
- **Option A** (if rate-based): add throttling + cooldown — ~15 min
- **Option B** (if signature-based): migrate fundamentals to FMP-only, accept tech-only screening for non-megacap symbols — ~1 hr, recommended
- See conversation around the diagnostic decision for full context.

The screener still fails gracefully — `dashboard.html` rebuilds from cached `candidates.json` when the subprocess dies. Operator-visible impact is stale Q+V tags for ~130 names until fix ships.

Also: see `notes/learned.md` entry for this gotcha so future sessions know the landscape without re-discovering it.

### Added

- New `notes/` folder convention: `notes/learned.md` (gotchas), `notes/decisions.md` (rationale), `notes/ideas.md` (parking lot). Seeded with current state. AGENTS.md now points new sessions at `notes/learned.md` so known landmines don't need re-discovering. Demonstrated by capturing the XProtect investigation above as an in-flight note.

### Changed

- AGENTS.md gained a "Session continuity" section at the top listing the read-order for any new session (AGENTS.md → notes/learned.md → CHANGELOG [Unreleased] → PROJECT_LOG.md).

### Fixed

### Removed

### Deprecated

### Security

---

## [v1.3] — 2026-06-07

Cross-agent compatibility. The project now follows the `AGENTS.md` convention so Codex (and any other agent that adopts the same convention) can pick up the doctrine alongside Claude Code.

### Changed

- **Doctrine file renamed `CLAUDE.md` → `AGENTS.md`**, following the emerging cross-agent standard so Codex auto-loads it natively. `CLAUDE.md` remains as a one-line pointer file so Claude Code (which auto-loads `CLAUDE.md`) still finds the doctrine. All internal references (`§5`, `§6`, etc., across 22 files) updated to read "AGENTS.md".
- `README.md` "Built with" section replaced by a "Supported agents" table covering Claude Code, Codex, and other agents that read `AGENTS.md`.
- `AGENTS.md` opens with an agent-agnostic intro paragraph addressing whoever's reading (Claude Code, Codex, or similar) — instead of presuming a single platform.
- `PROJECT_LOG.md` TL;DR rewritten as "an AI-coding-agent project (Claude Code, Codex, or compatible)" instead of "a Claude Code agent."

### Added

- README's `## Supported agents` table documents what works on each platform: Claude Code (primary, built here) and Codex (compatible via native `AGENTS.md` auto-load). Python code, dashboard, data integrations, and CLIs are platform-agnostic; only the agent orchestration layer differs.

### Backward compatibility

- Anyone with existing references to `CLAUDE.md` (forks, external links, notes) is unaffected — `CLAUDE.md` still exists as a pointer file and Claude Code still finds it.
- The Python codebase has no naming changes — only docstring and comment references updated. No code paths break.

---

## [v1.2] — 2026-06-06

Install-experience polish. Anyone landing on the GitHub front page can now follow the README to a working dashboard without hitting a 404 on the clone command or wondering whether they need Claude Code.

### Added

- README Quick Start now opens with a "What you need" block — Python 3.9+, Claude Code (recommended), and ~15 minutes for free API key sign-ups. Sets expectations before the first command.
- A "Verify it worked" section right after the 8-step install lists the six panels you should see in the dashboard, with a fallback hint if anything's missing.
- Trailing link to PROJECT_LOG.md now anchors directly to `#replication-steps` so users land on the full walkthrough instead of the file's top.

### Fixed

- **README clone command was unusable.** The Quick Start said `git clone https://github.com/YOUR_USERNAME/trading-advisor.git` — a fresh user copy-pasting this got a 404. Corrected to the canonical repo path.

---

## [v1.1] — 2026-06-06

Operator-defined position sizing in the Risk Simulator, plus the bug fix that came with it.

### Added

- Risk Simulator now lets the operator define their own position size. Doctrine §5 says the formula derives the *maximum permitted* size, not the obligatory size — operators routinely want to size down (correlation tax, lower conviction, partial-fill caution). The new "Size" field is auto-prefilled to the doctrine maximum when you pick a ticker, then you edit it as you see fit.
- New "Per-trade risk cap (§5)" gate that explicitly verifies your chosen size doesn't exceed the doctrine ceiling. Sizing above the 2% per-trade risk cap hard-fails the gate (clearly explaining the doctrine max at the current entry/stop); sizing under it passes cleanly within the cap.
- Position-size display in the result block now shows the doctrine maximum as a quiet sub-line whenever your size differs from it — so the ceiling is always visible without needing to mentally re-derive the formula.

### Changed

- The simulator's role is now framed honestly: it tells you whether *your* proposed trade is doctrine-compliant and whether your portfolio is at risk, rather than dictating the size for you. The sim-blurb now reflects this.

### Fixed

- Crypto positions (BTC, ETH, SOL, etc.) were silently sizing to 0 in the Risk Simulator due to a JavaScript falsy-coercion bug: `lot_size = 0` (the fractional-size marker for crypto) was being treated as falsy and replaced with `1` via `|| 1` fallback in three places. Crypto fractional sizing now works end-to-end across prefill, compute, gate, and result display. The §5 gate message also formats fractional sizes correctly (was rounding to "0 units" in the prose).

---

## [v1.0] — 2026-06-06

First stable release. Snapshot of everything built across the initial Claude Code sessions, packaged for replication.

### Added

- **Doctrine** — `AGENTS.md` (10 sections) covering role/mission, hard rules, data sources, analytical framework, risk doctrine, asymmetric strategy construction, decision process, output format, calibration, and tone. Includes the PHASED RAMP from Phase 1 (paper + spot only) through Phase 3 (full doctrine).
- **Replication guide** — `PROJECT_LOG.md` with cross-platform setup instructions, all six API key sign-up URLs (FRED, Alpha Vantage, Finnhub, Twelve Data, FMP, optional CoinGecko Pro), and known caveats from real operational experience.
- **21 self-contained skills** under `.claude/skills/`:
  - **Data fetchers**: `macro-rates` (FRED), `macro-calendar` (curated FOMC/CPI/NFP/PCE), `us-news` (Alpha Vantage with budget queue), `us-fundamentals` (yfinance), `klse-quote` / `klse-history` / `klse-news` (Bursa Malaysia), `klse-refresh` / `klse-announcements` (Python-callable caches), `crypto-coingecko`, `crypto-derivatives` (Binance funding/OI), `crypto-unlocks` + `crypto-unlocks-cache` (§5 48h halt gate), `hyperliquid-flow`, `finnhub` (live US quotes), `twelve-data` (bulk historical), `fmp` (fundamentals).
  - **Analysis + lifecycle**: `sector-rotation` (11 SPDR ETFs vs SPY), `us-screener` (176-name P1 + Buffett Q+V), `dashboard` (HTML render), `watchlist` (CLI), `journal` (prospectus → live → closed lifecycle with auto-R).
- **Dashboard** (`dashboard.html`) with regime strip, Risk Simulator (12-gate doctrine check per market + prospectus generator), US/KLSE/crypto grids with click-to-expand thesis + 8-gate breakdown, 🔭 Discovery panel (sector rotation heat strip + ranked candidates), Watchlist Manager inline forms, prospectus cards with action forms, journal tail, status badge tooltips.
- **Live quote buttons** — 🔄 next to every US price (Finnhub real-time), 🔄 for crypto (Binance / CoinGecko), 📊 link for KLSE (klsescreener.com).
- **Discovery layer** — sector rotation + 176-name screener universe with Buffett quality+value tagging (💎 BUFFETT / 🏆 QUALITY / 💰 VALUE / ⚡ TECH).
- **Tier 1 optimizations** — extended cache TTLs across all sources, daily-only screener marker, skip-if-fresh subprocess spawn from `--with-discovery`.
- **Tier 2 optimizations** — Twelve Data fallback for yfinance NaN-Close bars; CoinGecko cooldown + stale fallback; FMP → yfinance fallback for paywalled symbols.
- **Tier 3 optimizations** — bulk-load resolution cache (single directory scan), parallel yfinance per-ticker fetches via `ThreadPoolExecutor`, color-coded budget bar in dashboard header (AV / TD / FMP usage), watchlist auto-inclusion in screener universe.

### Architectural patterns established

- Cache + cooldown + stale-fallback for every external data source.
- Budget tracking for capped APIs with soft + hard caps and on-demand reserves.
- Tiered cache TTLs for the screener (HOT 24h / WARM 72h / COLD 7d).
- Provider fallback chains across yfinance / Twelve Data / FMP / Finnhub / CoinGecko / Binance.
- Browser-side live quote endpoints separate from cached daily-close pipeline.

### Performance

- Refresh button on warm caches: **~0.15 seconds**.
- Daily API budget consumption: well under 30% of all free-tier limits during typical use.
- First-time setup screener scan: ~22 minutes; thereafter sub-second on tier rotation.

### Known caveats (documented in PROJECT_LOG.md)

- macOS XProtect blocks `yfinance.download(multi_tickers)` — sector rotation and screener migrated to Twelve Data; per-ticker yfinance still works.
- Yahoo Finance IP-bans bursts via the urllib chart endpoint — no longer used directly; we go through Twelve Data instead.
- FMP free tier only covers ~30-50 megacap symbols for `/stable/ratios-ttm` and `/stable/key-metrics-ttm` — automatic yfinance fallback for everything else.
- Finnhub dropped historical OHLCV from free tier in 2024 — we only use `/quote` (still free, real-time).
- Tokenomist.ai is a Next.js SPA — direct urllib returns no usable JSON; agent uses WebFetch then writes to local cache.
- No free CORS-friendly API covers KLSE real-time — 📊 button opens klsescreener.com in a new tab instead.

### Licensing

- MIT license with explicit trading disclaimer.

---

<!-- Link targets below point at the canonical public repo. If you maintain
     your own fork, update or delete these as appropriate for your setup. -->
[Unreleased]: https://github.com/kensongan-prog/trading-advisor/compare/v1.3...HEAD
[v1.3]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.3
[v1.2]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.2
[v1.1]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.1
[v1.0]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.0
