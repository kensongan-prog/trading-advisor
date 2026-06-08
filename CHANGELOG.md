# Changelog

All notable changes to this project are recorded here.

---

## Versioning policy

This project uses **semantic versioning**: `MAJOR.MINOR.PATCH`.

| Bump | When | Real examples |
|---|---|---|
| **PATCH** (e.g. v1.4 → v1.4.1) | Bug fix, doc typo, defensive logging, dependency bump, investigation outcome, README clarity, link rot, refactor with no behavior change, doctrine rephrasing that doesn't change rules | v1.2 (README clone URL fix); a future "Investigated, no action" audit entry; defensive trace logging |
| **MINOR** (e.g. v1.4 → v1.5) | New capability appears (skill, panel, field, command, convention); the mental model an operator holds about the system shifts; new data source for existing functionality; meaningful optimization | v1.1 (Risk Sim size field); v1.3 (AGENTS.md cross-agent rename); v1.4 (auto-bootstrap + notes/ folder); adding a dashboard panel |
| **MAJOR** (e.g. v1.x → v2.0.0) | Doctrine §1-10 change that re-classifies past recommendations; breaking change to a CLI signature, data file format, or SKILL.md contract; existing operator setup would silently break or behave differently | A future §5 risk cap change from 2% to 1%; renaming `wl.py add` to `wl.py register`; flipping `--with-discovery` default behavior |

### Decision rules

**Pick PATCH when ALL of these are true:**
- The change is backward-compatible AND
- No new user-facing capability is added AND
- The mental model an operator holds about the system doesn't change

**Pick MINOR when EITHER:**
- A new capability appears (skill, panel, field, command, convention), OR
- The mental model shifts (operators now think about the system differently)

**Pick MAJOR when EITHER:**
- A past recommendation would be re-classified under the new rules, OR
- An existing operator's setup would silently break or behave differently

### Edge cases (resolved upfront so we don't argue at release time)

| Situation | Bump |
|---|---|
| Defensive logging added, no user-facing change | PATCH |
| "Investigated, no action" audit entry | No release needed alone; ride with whatever's next |
| Doc-only typo / clarification / link fix | PATCH |
| Doc-only addition that teaches operators something new | MINOR |
| Multiple small fixes batched in one release | Single PATCH (e.g. 3 fixes → v1.4.1, not v1.4.3) |
| Doctrine rule change | MINOR (or MAJOR if past recommendations get re-classified) |
| Doctrine rephrasing that doesn't change rules | PATCH |
| Optimization with no behavior change | PATCH |
| Optimization that meaningfully changes runtime characteristics | MINOR |

### Release-cut threshold (when to publish at all)

Cut a release when **EITHER**:
- `[Unreleased]` contains a real fix users need (any PATCH), OR
- `[Unreleased]` accumulates enough to be worth reading (typically 1-3 MINOR items or 3-5 PATCH items), OR
- You're taking a break and want a clean checkpoint.

**Don't** cut a release when:
- You haven't shipped functional changes (only in-flight notes or non-user-facing `notes/` updates)
- You're mid-experiment

### Historical note

Versions **v1.0 through v1.4** used the older two-level `MAJOR.MINOR` scheme. v1.2 (README clone URL fix) would have been v1.1.1 under the current rules. We adopted full semver from **v1.4.1 / v1.5** onward. Historical tags are not renumbered — `v1.2` stays as it shipped to preserve link integrity.

Versions are tagged in git as `vX.Y.Z` (e.g. `v1.4.1`, `v1.5.0`, `v2.0.0`) and mirrored as GitHub releases. The `.0` PATCH suffix is explicit (write `v1.5.0`, not `v1.5`) so versions sort lexically the way humans read them.

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

**Doctrinal rule:** if you are not sure whether a change is MAJOR, MINOR, or PATCH, ask the operator (or, if you are the operator, sit with the question for a moment). **Never silently break a published interface or doctrine.**

---

## [Unreleased]

### In flight (as of 2026-06-08 end-of-session)

- **Reddit OAuth upgrade pending.** v1.5.0 ships using the RSS workaround (unauthenticated Atom feeds, which Reddit hasn't blocked the way they blocked JSON). The proper OAuth path is wired and auto-activates the moment `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` land in `.claude/skills/reddit-sentiment/.env`. Reddit's developer app approval can take 2-4 weeks — code transparently upgrades without changes; will cut as v1.5.1 (PATCH) once verified.
- **Dead subreddit audit.** A few crypto subs 404'd during the first RSS refresh (`binance`, `Ripple`, possibly others). Tickers still got data from primary subs; cleanup is a follow-up patch.
- **Threshold-stability observation.** First scored refresh fired 4 FADE flags (PURR, KTOS, RGLD, CIFR). Want a few refresh cycles across changing market conditions to confirm the contrarian-filter thresholds (`bull_score ≥ 0.80` AND `conviction ≥ 0.70`) are calibrated correctly.

### Added

### Changed

### Fixed

### Removed

### Deprecated

### Security

---

## [v1.5.0] — 2026-06-08

Sentiment + prediction-market confluence layer. The doctrine's §4 sentiment leg gained two new primitives:

1. **Retail forum sentiment as a contrarian filter** (Phase A) — Reddit + StockTwits raw fetchers, LLM-scored via free OpenRouter models, composited into per-ticker 🔥 FADE / 🧊 BUY flags when retail is uniformly crowded one-sided. First scored refresh fired 4 FADE flags (PURR, KTOS, RGLD, CIFR) — concrete evidence the contrarian gate has bite.
2. **Polymarket implied probabilities as macro confluence** (Phase B) — money-weighted speculator consensus on Fed cuts, recession, inflation, BTC/ETH price ranges, geopolitics. Different from forum sentiment because participants put cash on outcomes — less gameable, treated as additive macro confluence rather than contrarian fade.

The dashboard surfaces all of this: a new "Retail" column on the US, KLSE, and crypto grids, a per-row sentiment block in the expand-on-click dropdown, and a top-of-page "Event Probabilities" panel with the Polymarket reads grouped by category.

### Added

- **Retail-sentiment layer (Phase A).** New `reddit-sentiment`, `stocktwits-sentiment`, and `sentiment-cache` skills bring retail-forum sentiment into the doctrine as a **contrarian filter** (per §4). Raw fetchers collect posts/messages; the cache layer LLM-scores them via OpenRouter free models (Gemma 4 31B IT primary, GPT-OSS 120B fallback — no metered API spend) and produces a composite per-ticker read with two flags: **🔥 FADE** (`bull_score ≥ 0.80` + `conviction ≥ 0.70`, retail crowded long → downgrade conviction on extended technicals) and **🧊 BUY** (mirror for capitulation + constructive P1). KLSE entries gracefully render `— UNKNOWN` (sparse forum coverage is expected, not a bug).
- **Reddit access via RSS workaround.** Reddit blocked unauthenticated JSON in 2023 but left Atom/RSS open. The skill defaults to RSS (no credentials needed) and transparently upgrades to OAuth when `REDDIT_CLIENT_ID`/`SECRET` are present in `.env`. Score and comment-count fields are unavailable via RSS but title + body excerpts are sufficient for downstream LLM scoring.
- **"Retail" column in the dashboard.** New sortable column on the US, KLSE, and crypto grids showing the composite badge + bull%. Pink-tinted cells flag FADE; green-tinted flag BUY. Hover tooltip carries the full rationale (bull/bear/conviction breakdown + source attribution + flag explanation).
- **Sentiment block in dashboard row dropdowns.** Each row's expand-on-click details panel now includes a third "Retail Sentiment" column alongside the existing P1-gates and Status-decision columns, showing per-source (Reddit + StockTwits) message counts, user-tagged-vs-LLM bull/bear/neutral percentages, LLM conviction, and the contrarian-flag explanation.
- **AGENTS.md §4 retail-sentiment subsection** codifies the contrarian-filter doctrine, including the conviction-gate rationale — the LLM safeguard against gameable self-reported badges. Concrete example preserved: AUPH 100% user-tagged bull on StockTwits but 64% LLM conviction → no FADE flag, because the message bodies were hedgier than the badges suggested.
- **Dashboard auto-fills sentiment for newly-added watchlist tickers.** Add a ticker via `wl.py add` (or by editing `watchlist.md`), run `dashboard.py`, and the new name's retail-sentiment column populates automatically — the dashboard detects missing-from-sentiment-cache tickers and subprocesses the reddit/stocktwits/scorer chain just for those names. New flags: `--refresh-sentiment` force-refreshes ALL watchlist tickers; `--no-sentiment` skips the auto-fill (e.g. if Reddit RSS or OpenRouter is down).
- **Polymarket prediction-market layer (Phase B).** New `polymarket-events` skill fetches implied probabilities from Polymarket's Gamma public-search API (no auth, free). Curated queries across 4 categories (macro_rates, macro_econ, crypto, geopolitics) pull event probabilities like "How many Fed rate cuts in 2026?" (80% no cuts), "US recession by end of 2026?" (18%), "Fed Decision in June?" (99% no change), and BTC/ETH price ranges. Stores historical snapshots for Δ7d computation. Noise filter drops occasional meme-market pollution (`GTA VI` / `Jesus return` / etc.) that sneaks through serious queries.
- **"Event Probabilities" panel on the dashboard.** New 4-column panel near the top (alongside macro regime + halt-window timeline) showing tracked Polymarket events grouped by category. Each row shows probability (color-coded: green ≥75%, yellow 25-75%, red ≤25%), title (clickable through to Polymarket), and Δ7d arrow when historical snapshot is available. Sorted within category by extremity (decisive markets first).
- **`--refresh-polymarket` flag on dashboard.py** for one-command refresh of the macro confluence layer (~5s, no auth).
- **AGENTS.md §4 prediction-market subsection** documents how Polymarket signals slot into the doctrine — additive macro confluence (not contrarian fade), with explicit treatment of aligned-vs-diverged-vs-uncertain cases, plus the §5 halt-window framing connection.
- **🗑️ Remove button on each watchlist row.** Each US/KLSE/crypto row gains a small trash icon next to the chevron. Click → browser prompts for a one-line removal reason (required by doctrine, surfaces in the watchlist's audit trail) → builds the `wl.py remove TICKER -r "REASON" --yes` command and copies to clipboard for terminal paste. Dashboard remains fully static HTML — this follows the same copy-then-paste pattern used by the Refresh button and prospectus actions. Falls back to a `prompt()` dialog showing the command if clipboard write is blocked.

### Changed

- **`dashboard.py` row-detail layout** moved from a fixed 2-column grid to `repeat(auto-fit, minmax(280px, 1fr))` so the new Retail Sentiment column flows alongside P1 gates + Status on wide screens and wraps gracefully on narrow viewports. Colspans bumped from 13→14 (US) and 14→15 (KLSE + crypto).

### Fixed

- **Watchlist parser** in both `reddit-sentiment` and `stocktwits-sentiment` was treating the literal placeholder ``\`TICKER\``` from the watchlist's `Format:` example line as a real ticker. Now explicitly skipped alongside italicized section markers.

---

## [v1.4.1] — 2026-06-08

Versioning policy update. The project now uses full semver (`MAJOR.MINOR.PATCH`) instead of two-level `MAJOR.MINOR`. Pure docs change — no behavior, no code.

### Changed

- **Versioning policy** in `CHANGELOG.md` rewritten as `MAJOR.MINOR.PATCH` (semver). Decision rules, edge cases, and release-cut threshold codified upfront so future release calls don't depend on judgment-in-the-moment. PATCH releases (e.g. v1.4.1) are now distinct from MINOR releases (v1.5.0) — small fixes no longer burn MINOR slots. Historical tags v1.0 through v1.4 are not renumbered; v1.2 (README clone URL fix) would have been v1.1.1 under the new rules but stays as it shipped to preserve link integrity.
- `README.md` Changelog section gains a one-line mention of semver.
- `notes/decisions.md` records why we adopted semver mid-project (sharp operator question after v1.4 noticed several minor releases were really patches).

---

## [v1.4] — 2026-06-08

Session-continuity infrastructure. New agent sessions auto-orient before responding, so neither operator nor agent loses context across `/clear`s, fresh sessions, or returning days later. Plus a defensive trace in the screener so the next time a subprocess dies mid-loop we have actionable data instead of guessing.

### Added

- **Auto-bootstrap on session start** (`CLAUDE.md` + `AGENTS.md`). When Claude Code or Codex opens this project, the agent reads `notes/learned.md` + `CHANGELOG.md [Unreleased]` + `git log --oneline -10` *before responding to the operator's first message*, then orients in 3 short lines (current version / last shipped change / anything in flight). Cost: ~5 seconds; operator typing required: zero. Prefix the first message with `quick:` or `oneshot:` to skip for one-off unrelated questions. README's "Supported agents" section documents the behavior and the disable path.
- **New `notes/` folder convention**: `notes/learned.md` (gotchas + system quirks), `notes/decisions.md` (rationale for non-obvious choices), `notes/ideas.md` (future-feature parking lot). Read at session start (learned only) so known landmines don't need re-discovering. Seeded with the XProtect investigation, FMP free tier paywall, tokenomist SPA limitation, yfinance NaN edge cases, and decisions around AGENTS.md rename, CronCreate vs cron, and the public+backup repo split.
- **Defensive trace logging in `screener.py` fundamentals loop** — prints `[fund] [i/N] {ticker} (yf_used=N, elapsed Xs)` on every iteration. If the process dies mid-loop (XProtect, OOM, network, anything), the last-printed line tells us exactly which ticker and call number triggered it. Cost: ~one extra log line per P1-passing candidate (typically 1-5 per run). Verified end-to-end via targeted `fetch_fundamentals(['CMI', 'SPY'], force=True)` invocation.

### Changed

- `CLAUDE.md` expanded from a 7-line pointer to ~35 lines, now carrying the auto-bootstrap instructions. Still points at AGENTS.md for the actual doctrine; the doctrine still has zero duplication.
- `AGENTS.md` "Session continuity" section reframed as "Session bootstrap" with mirrored auto-bootstrap instructions, so Codex sessions get identical behavior to Claude Code sessions.
- `README.md` Supported agents section gains an "Auto-bootstrap on session start" subsection documenting the behavior, the `quick:` / `oneshot:` skip path, and how to disable entirely.

### Investigated, no action

- **XProtect popup during dashboard build (reported 2026-06-07)** — Diagnostic showed 130 sequential `yf.Ticker(t).info` calls complete cleanly with no XProtect interference. Further analysis revealed `fetch_fundamentals` is only called for P1-passing candidates (typically 1-5 per run), not the full 188-name universe — the "130 yfinance calls" estimate that drove the initial concern was an upper bound that never occurs in practice. Likely cause of the original popup: a transient XProtect signature update from Apple, a different process, or an intermittent match. No fix shipped; the defensive trace logging above captures actionable data if it recurs. See `notes/learned.md` for the full investigation writeup.

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
[Unreleased]: https://github.com/kensongan-prog/trading-advisor/compare/v1.4.1...HEAD
[v1.4.1]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.4.1
[v1.4]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.4
[v1.3]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.3
[v1.2]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.2
[v1.1]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.1
[v1.0]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.0
