# Learned — gotchas + system quirks

Append-only log of things worth knowing. Newest at top. The agent reads this at session start.

---

### 2026-07-02 — Claude Preview MCP tool can't launch `server.py` from the SSD project path ("Operation not permitted")

While live-verifying Analysis C2–C4 (Risk Simulator gates + Discovery panel), `preview_start` on the `dashboard` launch config failed: `/Users/aiagent/.local/bin/python3: can't open file '.../server.py': [Errno 1] Operation not permitted`. The SAME command runs fine via the Bash tool (`python3 .claude/skills/dashboard/dashboard.py` builds cleanly). This smells like the same family of issue as the 2026-06-15 launchd/TCC finding below (a sandboxed subprocess lacking a permission grant the interactive shell inherits) but is NOT the same root cause — that one was `~/Documents`-specific and the project has since moved to the SSD (see the 2026-06-29 move note). Root cause not confirmed this session (no scriptable fix attempted — likely needs a one-time Full Disk Access grant for whatever process backs the preview MCP tool, done outside this session). **Workaround used:** when the preview tool can't reach the dashboard server, fall back to static verification — build `dashboard.html` via Bash, then parse the output directly (`window.TA_SIM = {...}` JSON blob for sim payload fields, grep the rendered rows for expected text/badges) rather than a live browser. This caught real, correct data end-to-end for C2–C4 (RS/sector fields in the sim payload, real earnings beat-streaks for MRVL/MS) even without an interactive browser session — good enough for pure-data verification, though it can't confirm JS gate *rendering* behavior the way a real click-through can.

### 2026-07-02 — Broker (MooMoo) panel (Bridge Phase 3): observed-but-never-submitted intents need their own display fallback

**Real bug caught only by live-verifying the panel against MooMoo's actual on-disk `staged_orders.json`** (not synthetic fixtures — the same pattern that caught the `broker-sync` bug earlier the same day): a staged order that's been observed in `sync_state.json` but never actually submitted (no `order_id`, no `journal_path`, hence no `journal_stem`) fell through to displaying the **raw `intent_id` string** in the panel's ticker column — a long, path-laden mess like `trading_advisor:AUPH:_Volumes_Mac_Mini_SSD_Projects_Claude_Trading_Advisor_journal_2026-06-03_AUPH.md`. Fix: `_display_ticker()` falls back to parsing the ticker out of `intent_id`'s own `source:TICKER:path` format (`intent_id.split(":")[1]`) before ever falling back to the whole raw string.

**Reusable lesson (second time in one day): always render/exercise a new cross-repo status surface against the real upstream artifact at least once, even after exhaustive synthetic-fixture tests pass.** Synthetic fixtures naturally model the "normal, complete" shapes an author expects; real production data reliably contains the partial/incomplete shapes (a staged-but-unfilled order, an observed-but-never-submitted intent) that only show up from actually running the thing.

**MooMoo's `trade_ledger.json` reflects the operator's REAL brokerage account, not paper trading** — it's built from `historical_fills`/`historical_orders`/`order_fees` with no `SIMULATE` filtering applied (MooMoo's ledger code intentionally ignores SIMULATE rows entirely). Any TA surface that reads it must label it unambiguously as real-account context, separate from the paper-trading picture `broker-sync`'s own `sync_state.json` tracks — conflating the two would misrepresent what Phase 1 doctrine is actually about.

---

### 2026-07-02 — broker-sync (Bridge Phase 2): MooMoo already aggregates fills; don't re-derive them

**MooMoo's `staged_orders.json` is the authoritative, ALREADY-AGGREGATED per-intent view — don't re-derive fill totals from raw `fills.json`.** Read `src/moomoo_adapter/execution.py::_refresh_staged_orders` in the MooMoo repo before building anything that touches fills: every sync there joins fills → staged orders by `order_id` and writes back `filled_qty` (sum), `filled_avg_price` (notional-weighted), `fill_count`, `last_fill_at`, and an `approval_state` state machine (`staged → submitted → partially_filled → filled` / `canceling → canceled` / `failed`) directly onto each staged order. TA's broker-sync reads THAT, not raw fills — far simpler and avoids two systems computing the same aggregate differently.

**Real bug caught by live-verifying against MooMoo's actual on-disk `staged_orders.json` (not just synthetic fixtures): a staged-but-not-yet-submitted order (`approval_state: "staged"`, no fill, no `journal_path` yet) was being flagged for manual review** because the original decision logic checked "did journal_path resolve?" before checking "is there even a fill to attribute?". This is the MOST COMMON state a staged order sits in (before it's submitted, or while waiting to fill) — flagging it every run would have been constant noise for a routine, expected state. Fix: check fill-existence FIRST; only look at journal resolution once there's actually something to attribute. **Lesson: always run a new sync/attribution loop against real on-disk data from the actual upstream system before shipping — synthetic fixtures had already covered every branch of the decision table and still missed this, because the fixtures didn't happen to model the "staged, unfilled, no journal_path key at all" shape that real un-submitted orders actually have.**

**MooMoo's paper-vs-real separation is a field, not a separate file — `trading_env` defaults to `"REAL"` when absent** (`str(row.get("trading_env") or "REAL").upper()` in MooMoo's own merge code). Old/pre-Phase-1 fill rows in `historical_fills.json` (real historical CLSK/GPUS fills from before paper trading existed) simply lack the field entirely — they are NOT tagged `SIMULATE`, so any code that reads MooMoo fills must explicitly filter `env == "SIMULATE"` and never assume absence-of-real-tag means paper.

**Journal resolution should match by the exact basename STEM of a cross-repo path, not the raw absolute path string.** MooMoo's `journal_path` field bakes in whatever absolute path `TRADING_ADVISOR_ROOT` resolved to on ITS machine/checkout at staging time — trusting that string directly is fragile across machines/checkouts. Since journal filenames are unique in this project's convention (flat `journal/` dir, `j.py new` refuses to silently overwrite), resolving by `Path(journal_path).stem` through `j.resolve_file()`'s existing "exact stem match wins" branch is EXACT traceability, not a heuristic — despite not trusting the literal path string.

---

### 2026-07-02 — Guardrails Phase B: why the pump-and-dump flag is `'warn'`, not `'bad'`; and cross-skill imports ARE allowed for shared logic

**The Risk Simulator's `hardBads` list has real teeth.** `gates.filter(x => x.ok === 'bad')` directly disables the "Create Prospectus" button (`canProsp = hardBads.length === 0`) — no override affordance exists anywhere in the UI. The Guardrails Phase A/B plan's own proposal ("P&D composite → bad, verdict downgrade to NO-by-default, override-able") assumed an override path that doesn't exist. Making it `'bad'` would have been the project's **first real hard block**, contradicting doctrine §1 (operator decides) and the "warn-loudly-never-block" principle the whole guardrails effort is built on. **Decision: ship it as `'warn'`** — visually distinct (🚩 prefix in the gate text) but never disables anything. Verified live in Chromium via Playwright: GPUS's Structural quality gate renders `warn` even while three OTHER pre-existing gates (Trend filter, Pullback shape, Macro halt) correctly fail it to 🔴 NO-TRADE — those are unrelated to this change. If a real override-able hard-block is wanted later, it needs actual UI work (a checkbox/confirm state), not just flipping a gate status.

**Cross-skill imports are an established, intentional pattern for genuinely shared logic — the "self-contained skill dirs" rule (2026-06-13 entry below) is about NOT sharing trivial boilerplate, not a blanket ban.** `j.py`'s `sync_portfolio()` already does `sys.path.insert(0, str(SKILLS_DIR / "dashboard")); import portfolio` — a real precedent found while wiring Phase B. `quality_flags.py`'s thresholds are exactly the kind of thing that MUST be single-sourced (if PENNY threshold changes, every consumer needs the same number): `wl.py` now imports it from `dashboard/` the same way, and `j.py` imports it a second time to render the prospectus's flag labels. Don't duplicate the module; mirror the existing cross-skill-import pattern.

**Operational note, not a code gotcha: be extremely careful chaining `git stash` into a "just check status" one-liner.** Mid-session, a command meant to check `git status` accidentally included `git stash -u -q` first, silently stashing ~200 lines of uncommitted work (dashboard.py + wl.py edits + a new test file) with no visible error. Caught immediately by comparing `git status`/`grep` for an expected function before/after; recovered cleanly with `git stash pop`. No data lost, but it's a reminder: never bundle `git stash` (or other state-mutating git commands) into a multi-command one-liner opportunistically — run it alone, deliberately, only when actually needed.

---

### 2026-07-02 — Structural-quality flags (quality_flags.py): two live-verification catches

**1. yfinance omits `numberOfAnalystOpinions` entirely (`None`) for zero-coverage names — it's not an explicit `0`.** Verified live on GPUS vs AAPL: AAPL returns `42`, GPUS returns `None`, not `0`. A naive `== 0` check misses every uncovered microcap, which is exactly the population this flag exists to catch. Fix: treat `None` as no-coverage too, but gate the check on `price is not None` first — otherwise a totally-failed fetch (every field `None`) spuriously flags NO_COVERAGE alone with zero other evidence.

**2. Context-only gauges (SPY, `EARNINGS_SKIP_TICKERS`) need the SAME skip applied to quality flags as to earnings.** SPY is an ETF/regime gauge, never a trade candidate — but it has no analyst coverage by construction (ETFs don't get sell-side opinions), so the NO_COVERAGE check fired on every build. Caught only by exact-match live verification (`<b>SPY</b>` in the rendered `dashboard.html`) — a loose substring search on the ticker missed it because "SPY" appears in unrelated contexts (sector-rotation baseline text, tooltips) elsewhere on the page. **Lesson: when grepping a rendered dashboard for a ticker's row, anchor on the exact cell pattern (`<b>{TICKER}</b>`), not a bare substring — false negatives AND false positives both hide behind loose matches.** Fix mirrors the existing `EARNINGS_SKIP_TICKERS` pattern exactly: `row_quality_flags()` takes an optional `ticker=` and skips gauges before classifying.

**Reusable pattern worth repeating elsewhere:** `chg_5d_pct`/`chg_30d_pct` were added to `fetch_yfinance_ticker`'s output for free — `h["Close"]` (the 1y price history) is already loaded in memory for RSI/SMA/ATR; deriving two more percentage changes from it costs zero extra API calls. Same principle as the ADR-tag work's `market_cap_rank` and this module's `short_pct_float`/`beta`/`analyst_count`: check what's already in the response/dataframe before reaching for a new fetch.

---

### 2026-07-01 — klsescreener comment threads + the "KLSE news already exists" trap

**Two findings from building the `klse-sentiment` leg.**

**1. klsescreener has a per-stock community comment thread — and a working endpoint.** `https://www.klsescreener.com/v2/comments/all/stock/{CODE}` (GET, server-rendered HTML, no auth) returns the full recent thread (caps ~26 comments). Real multilingual retail chatter (English/Chinese/Malay). This is the Bursa-native retail-sentiment source that fills the gap StockTwits (404s on KLSE) + Reddit (thin Bursa) leave — before this, KLSE names scored `UNKNOWN`. **Dead ends mapped:** the in-page AJAX pager `/v2/comments/comment/stock/{code}` (singular "comment") 404s — deprecated; the real double-"comments" path `/v2/comments/comments/stock/{code}/{page}` also 404s (the `#comment_load_more` button is commented out in the HTML). The live surface is the "all" page above. The stock **view** page only server-renders a ~2-comment preview — do NOT use it to gauge volume (every stock shows 2). Wired into `sentiment_cache` as `process_klse` (weight 1.0, additive) + coverage-haircut (`n_total` includes klse). Coverage is uneven: active names 12–25 recent comments, quiet names dead for months (→ `no_coverage`).

**2. KLSE *news* is ALREADY scraped programmatically by `news_glyph`, not the klse-news skill.** The `klse-news/SKILL.md` is WebFetch/agent-only, which is misleading — `us-news/news_glyph.py::refresh_klse` + `_scrape_klse_news` already scrape `/v2/news/stock/{code}` into `.claude/cache/klse_news/{code}.json` (`items[]` of `{date, source, headline, url}`), LLM-score it, and wire it into the dashboard news glyph + `--refresh-news-glyph`. **A standalone klse-news fetcher was built and then DELETED as redundant.** Lesson (the recurring one): **grep for the capability in the consuming module before building a fetcher** — the SKILL.md dir isn't the whole story. Two small fixes WERE made to the existing `refresh_klse`: a **180-day recency window** (`_window_klse_items`) and an **`html.unescape` in the headline cleaner** (`&#039;` was leaking through). Both tested in `tests/test_news_glyph_klse.py`.

### 2026-06-29 — Project moved off `~/Documents` to the external SSD — supersedes the TCC-trap context below

The repo now lives at **`/Volumes/Mac Mini SSD/Projects/Claude/Trading Advisor`** (moved 2026-06-29, off the old `~/Documents/Claude/Projects/…` location). This updates two now-stale claims in the 2026-06-26 entry below:
- **"This folder isn't moving anytime soon"** — it did move. The SSD must be mounted to reach the repo (and the vault); if a session can't find either, check the volume first.
- **The launchd `EX_CONFIG`/TCC trap was specific to `~/Documents`** (a macOS TCC-protected location). The project is no longer there, so that exact failure mode no longer applies here. The 2026-06-26 entry's trap writeup stays as **general reference** (it's still true for any project under `~/Documents`/`~/Desktop`/`~/Downloads`), but it's no longer a live constraint for *this* repo. Note `/Volumes/…` external volumes have their own caveat — they're not TCC-protected like `~/Documents`, but a launchd job firing before the volume mounts would fail differently (path not found). Autostart remains unwanted regardless — manual launch is the standing preference.

### 2026-06-26 — Dashboard launches manually via `Trading Dashboard.command`; `--lan` is the persistent piece

**Decision (Kenson, 2026-06-26):** the dashboard does NOT need to auto-start on reboot. Manual start is fine. The only thing that must persist is the `--lan` flag, so every manual launch binds dual-stack (`::`) and is reachable on Tailscale at **http://100.71.94.40:8787**. Without `--lan` the server is loopback-only and the phone/iPad get connection-refused — that's the bug we already fixed once; don't regress.

**How to launch:** double-click **`Trading Dashboard.command`** in the project root. It now does:
```sh
exec /usr/bin/env python3 ".claude/skills/dashboard/server.py" --lan --open
```
`--lan` → dual-stack bind; `--open` → opens browser to localhost. Manual workflow only — close the Terminal window to stop the server.

**Do NOT install a LaunchAgent for autostart.** An earlier session explored that path and discovered the TCC trap below; the LaunchAgent + autostart .command + Application Support directory were all removed when Kenson said autostart wasn't wanted. If a future session is tempted to "make it persistent again," check with Kenson first — manual launch is the standing preference.

**The TCC trap (kept here as reference, since this folder isn't moving anytime soon).** A naive LaunchAgent like `ProgramArguments = [/usr/bin/python3, .../server.py, --lan, --port, 8787]` **silently fails with exit code 78 (EX_CONFIG)** because the project lives under `~/Documents/`, which macOS TCC treats as protected. A launchd-spawned process has NO TCC grants for `~/Documents` and errors with `Operation not permitted` before `server.py` is even read. Symptoms in `launchctl print`:
- `state = spawn scheduled` (forever)
- `last exit code = 78: EX_CONFIG`
- nothing in StandardOutPath if that path is also in `~/Documents` (launchd can't open it for redirection either)

The workaround that **did** work (if it's ever wanted again) is `/usr/bin/open -g -j <autostart.command>` from a LaunchAgent, where the autostart .command lives outside ~/Documents and nohup-detaches a python that the user-session Terminal launches. `open` dispatches via LaunchServices so the spawned chain inherits the user's TCC grants. Don't set KeepAlive on that pattern — `open` exits immediately and it would respawn forever.

**Verify after a manual launch:** `curl -sS -o /dev/null -w "%{http_code}\n" http://100.71.94.40:8787/` should return `200`. If it's `000`, either the dashboard isn't running (double-click the .command) or `--lan` got dropped somewhere — check `Trading Dashboard.command` first.

### 2026-06-25 — Data builds need system `python3`, NOT `.venv-playwright` (pandas/yfinance)

The project venv `.venv-playwright` has **pytest + playwright but NOT pandas/yfinance**. So `dashboard.py --force` (or anything calling `fetch_yfinance_ticker` / `_compute_indicators_from_ohlcv`) only works under **system `python3`** — the venv only succeeds on cache hits (no recompute path triggers the import). `server.py` spawns builds via `sys.executable`, so **run the server with system `python3`** or builds will fail on the first cache miss. Tests that touch pandas use `pytest.importorskip("pandas")` so the suite stays green in the venv (3 skips are expected there as of 2026-06-29: `test_sparkline.py` + the two pandas-gated cases in `test_earnings_skip.py`). Bootstrap pytest still uses the venv; only *data builds* need system python.

### 2026-06-25 — klsescreener stock URL is `/v2/stocks/view/{code}`, not `/quote/`

The dashboard's KLSE 📊 quote button had drifted to `klsescreener.com/v2/stocks/quote/{code}` → HTTP 404. The real path is `/v2/stocks/view/{code}` — the exact path `klse-quote` + `klse-refresh` already use. Fixed v2.7.0 (`test_klse_quote_link.py` bans `/quote/`). The `/view/` page is a JS-rendered SPA, so a raw urllib fetch returning empty/no-`<title>` is normal flakiness — **trust the 200-vs-404 status, not page-body content**, when validating these URLs.

### 2026-06-25 — Server control-bar JS is scoped; re-query elements after an innerHTML swap

Two DOM gotchas from the v2.7.0 live-dashboard work:
1. **`server.py`'s CONTROL_BAR `<script>` is NOT global scope** — functions reachable from inline `onclick` are explicitly `window.X = …`; plain `function foo(){}` there is scoped (works in-scope, e.g. `taCaptureUiState` called right before `location.reload()`, but is **not** reachable from `page.evaluate` or the page's own JS). To test such a function, mirror its body in the test rather than calling it.
2. **An `innerHTML` swap detaches all children** — the in-place Data Health refresh does `panel.innerHTML = new`, so any element reference grabbed before the swap (e.g. the "updated" stamp span) is stale. Re-`getElementById` after swapping. Panel **collapse is event-delegated** (`document` click → `closest('.panel > h2')`) precisely so a swapped panel's new `<h2>` still folds without re-binding.

### 2026-06-15 — Data-utilization audit: "is each stream on the rung it deserves?"

When asked "does our analysis use all the data we ingest?", the useful reframe is a
**utilization ladder** per stream: rung 0 = not ingested by the build at all; rung 1
= displayed only; rung 2 = computed into a signal; rung 3 = gates a decision. The
gaps are almost never "missing data" — they're streams stuck a rung too low. Method:
for each source, trace whether it's consumed only to render, or actually feeds a
derived signal / a §5 gate / the sizing math. **Verify in code, don't trust the
mental map** — a v2.6.0 audit "discovered" funding was unused, but tracing showed it
already drove a sim factor (it was the *audit's* assumption that was stale).

Three gaps that audit found + closed in v2.6.0: (1) risk ⊥ sentiment were siloed —
the sim verdict never consulted the §4 contrarian flag; (2) sentiment was
sample-size blind (2 messages ≈ 50); (3) only funding was ingested from
crypto-derivatives, not OI / long-short. Key design rule that recurred: **don't
double-count correlated crowding signals** — funding + OI + L/S all measure the same
thing, so they share ONE "Perp positioning" gate, not three.

**Not everything belongs in the dashboard.** `hyperliquid-flow` whale-position
tracking needs a *target address* you supply → it's an interactive agent tool ("what
is address X holding"), not a per-coin auto-build signal. Correctly rung-0 for the
dashboard; don't try to wire address-less "whale flow" into the build. The
auto-buildable HL bit (cross-venue funding) duplicates Binance funding anyway.

---

### 2026-06-14 — HTTPS over Tailscale (for OS notifications) needs the admin HTTPS toggle, then `tailscale serve`

OS/browser notifications (the dashboard's refresh-complete pings) require a **secure
context** — `https://` or `localhost`. Over Tailscale you hit the dashboard at
`http://100.x.x.x:8787`, which is neither, so notifications silently don't fire
there (the in-page toast + banner still work).

Fix path (chosen 2026-06-14): use Tailscale's own TLS, no code/cert files, auto-renewing.
1. **Enable HTTPS certs in the admin console** — https://login.tailscale.com/admin/dns
   → "HTTPS Certificates" → Enable. (MagicDNS must be on too.) Without this,
   `tailscale cert` / `tailscale serve` fail with **"your Tailscale account does not
   support getting TLS certs"** (this is the toggle being off, not a plan limit on
   Personal/free).
2. **Then** run once: `tailscale serve --bg 8787` — terminates TLS and reverse-proxies
   `https://macbooks-macbook-pro.tail0e0dd8.ts.net` → `127.0.0.1:8787`. Persistent
   tailnet config (survives reboots); undo with `tailscale serve reset`.
3. Access the dashboard at that https URL (no `:8787`). server.py stays plain http on
   localhost — relative `/api/...` fetches + the static-page protocol checks all work
   behind the proxy unchanged. Notifications then work over Tailscale.

Gotcha: `tailscale serve --bg` **hangs** (no error) when HTTPS certs aren't enabled —
it blocks trying to provision a cert. Diagnose with `tailscale cert <fqdn>`, which
fails fast with the explicit 500 message above. Self-signed + a server.py `--https`
flag is the fallback if the admin toggle is unavailable (works, but one-time
"not private" cert warning per device).

---

### 2026-06-13 — Skill dirs are deliberately self-contained; don't DRY across them

During the v2.3.0 optimization pass the instinct was to dedup the `.env` loader
that's copy-pasted (with different names: `load_dotenv_if_present`, `_load_env`,
`load_env_file`, `load_env`) across 9 skill dirs, plus the 3 HTTP-helper variants.
**Decision: don't.** Each `.claude/skills/<x>/` dir runs standalone with *zero
cross-skill imports* — that self-containment is a feature (PROJECT_LOG documents
skills as independently copyable for replication). Sharing trivial, stable code
would force a `sys.path` bootstrap + a `_shared/` dependency into every skill and
break copy-one-folder portability, for ~10 lines of code that's never been a bug
source.

**What IS worth deduping:** same-directory helpers with real logic and a history
of drift. The operator-loop CLIs in `.claude/skills/dashboard/` (`rel_strength`,
`retired_scan`, `setup_queue`) had copy-pasted `watchlist_us` / `batch_closes` /
`load_json_cache` whose divergence caused v2.0.x bugs — those went into
`_cli_lib.py` (same dir, trivial `import`, no bootstrap). Rule of thumb:
**dedup within a dir, stay self-contained across dirs.**

Also measured and skipped in the same pass: a shared cache class (dashboard's
`cache_get`/`cache_set` are already single-source in one file), and lazy-loading
the Risk Simulator payload (it's 16.6KB of a 454KB page — 3.7%, not worth an
endpoint + `file://` fallback). Most of the dashboard's ~1091 rendered `style=`
attrs are dynamically generated per-row, not static-class candidates.

---

### 2026-06-12 — Dashboard "refresh does nothing" cluster: three structural root causes

**Symptom:** Operator clicks ⚡ Quick or 🔄 Full — stale warnings persist, or nothing visible happens.

**Root cause #1: sources with no refresh path in any button.** `klse_announcements` and `klse_fundamentals` appear in the Data Health panel as stale but are refreshed only by standalone CLIs (`.claude/skills/klse-announcements/klse_announcements.py`, `.claude/skills/klse-refresh/klse_refresh.py`) — no dashboard button ever ran those. `crypto_unlocks` is agent/WebFetch only; no subprocess can refresh it. The Data Health chip was counting all of these in "N sources need refresh," implying a button click would fix them.

**Root cause #2: TTL disagreements so a refresh never cleared the stale flag.** `health.py` marks screener stale after 12h, but `dashboard.py --with-discovery` had a gate that skipped the screener unless the cache was `> 18h`. Between 12h and 18h: chip says stale, button runs, gate says "cache still fresh (< 18h)" → screener NOT re-run → rebuild uses old data → chip still says stale. Same for polymarket (health TTL=12h, auto-refresh threshold=18h).

**Root cause #3: taRefresh silently discarded ok:false.** `server.py`'s `taRefresh` did `await fetch(...)` and threw away the response. When a job was already running (e.g. the auto-quick that fires on page load), the server replied `{ok:false, output:"a job is already running"}` — and the UI showed nothing. Operator clicks into void repeatedly.

**Fix (v2.2.0):**
- `health.py` `REFRESH_VIA` maps every source to `("flag", "--flag")` / `("cli", "path.py")` / `("agent",)`.
- `health.py` `summarize()` splits stale counts into `n_actionable_server` / `n_actionable_agent`. DATA chip uses `n_actionable_server` — no longer lies about what a button can fix.
- `dashboard.py --refresh-stale`: reads health state, enables exactly the needed flags, runs CLIs.
- TTL gates fixed: screener gate → `health.TTL_HOURS['screener']` (12h), polymarket → `health.TTL_HOURS['polymarket']` (12h).
- `taRefresh` reads response; on `ok:false`, shows "⏳ busy" immediately. Per-source ↻ buttons added. Progress banner at page top. Post-reload outcome toast diffs pre/post counts.

**Implication for new data sources:** Register in both `TTL_HOURS` AND `REFRESH_VIA`. A source in TTL_HOURS but not REFRESH_VIA would appear stale with no refresh path — invisible to `--refresh-stale`.

---

### 2026-06-11 — Polymarket crypto events expire daily; macro/geo don't — cache needed an age-based auto-refresh

**Symptom:** Dashboard's Event Probabilities panel rendered "no events" under the Crypto · Price column. Macro, Econ, and Geopolitics columns all populated normally. Data Health panel showed `polymarket ✓ 1` (fresh) — the cache wasn't broken, just empty for that category.

**Root cause:** The polymarket cache was 9h old (fetched yesterday afternoon). The crypto queries (`"bitcoin price"`, `"ethereum price"`) hit Polymarket markets that are *daily* price-band events — e.g. "Bitcoin price on June 10?", "Ethereum price on June 10?". These resolve at midnight UTC and Polymarket flips them to `closed=true`. The fetcher's `if ev.get("closed") or not ev.get("active", True): continue` filter at `polymarket_events.py:236-237` correctly dropped them — leaving the crypto category empty. Meanwhile macro_rates ("Fed rate cuts in 2026"), macro_econ ("US recession by end of 2026"), and geopolitics ("China invade Taiwan by EOY") are all **long-dated events** that survive cache age comfortably.

So Polymarket has **categorically different cache half-lives by category** — and the dashboard's "Quick refresh" wasn't pulling polymarket (only the explicit Full refresh or `--refresh-polymarket` was), so an overnight-aged cache silently emptied the Crypto column on every morning rebuild.

**Fix (this commit):** Polymarket now auto-refreshes during `dashboard.py` when its cache is >18h old or missing. Code path lives in `dashboard.py` main() just before `build_dashboard()`, mirroring the existing `--refresh-polymarket` block. Validated: with a fresh cache no refresh fires; with mtime set 20h back, `[polymarket] auto-refresh: cache 20.0h old (>18h)` prints and the fetcher runs. The 18h threshold matches the project's existing "daily marker" pattern used by the screener — assumes one rebuild per day catches the day's crypto events shortly after they're published.

**What I considered but didn't do:** tightening to 12h (would catch same-day flips earlier but doubles fetcher load with no real-world payoff — operator builds in the morning either way). Adding a per-query staleness signal to the fetcher (over-engineered for a 2-line problem).

**Audit recipe:** if Crypto column ever shows "no events" again, check cache age (`stat .claude/cache/polymarket/events.json`) and run `python3 .claude/skills/polymarket-events/polymarket_events.py` to confirm the API has active events today. The auto-refresh should make this a non-issue going forward, but if Polymarket changes the way they resolve daily events, this is the failure mode that surfaces first.

---

### 2026-06-11 — Data Health surface (v2.1.0) — what to expect on bootstrap

The dashboard now carries a sticky **DATA slot in the Action Rail** (R:R / Entries / Setups / DATA) plus a collapsed **Data Health panel** right below the rail. Each per-source row shows chip counts (✓ fresh, ⏰ stale, ⚠ transient-error, 🛑 permanent-error, — no-coverage, ? missing). Clicking a row expands a per-ticker detail list with the exact error or staleness reason.

When investigating a "why is X showing no data" question:
1. Glance the rail's DATA chip first — yellow `⚠ N sources need refresh` vs red `🛑 permanent errors` vs green `✓ N% healthy` is the one-second answer.
2. Open `📊 Data Health` and look at the source you care about (sentiment.stocktwits, us_news, etc).
3. Per-row detail will say e.g. `STALE — 165h old (TTL 48h)` or `ERROR_TRANSIENT — LLM scoring failed: HTTP 429: …`.
4. Transient errors → run a refresh (it'll go through the v2.0.6 fallback path now). Permanent errors → code/config issue. Stale → just old, refresh if you want fresh.

The health classifier (`.claude/skills/dashboard/health.py`) is pure-logic and tested (`tests/test_health.py` — 41 tests). The TTL defaults are in `health.TTL_HOURS`; if you change a fetcher's expected freshness, update there too.

**What this catches that nothing else does:** v2.0.x found four bugs where degraded data rendered identically to good data. The Data Health surface makes the difference visible. The first deployment immediately surfaced **6 sentiment sources still cached in the pre-v2.0.6 HTTP 429 state** for MRVL/RYDE/RKLB/ETH — the operator had no way to know those tickers' sentiment was broken until the panel showed it.

---

### 2026-06-10 — Sentiment classifier had no LLM fallback — a single Gemma 429 killed the whole source

**Symptom:** RGLD dashboard row showed "RETAIL SENTIMENT — UNKNOWN (no source data)". But `.claude/cache/stocktwits_sentiment/RGLD.json` clearly had 30 messages. Reading `.claude/cache/sentiment/RGLD.json` revealed the bug: the StockTwits source's `present: false` had `error: "HTTP 429: gemma-4-31b-it:free is temporarily rate-limited upstream"`. Reddit and HN were legitimately absent (no posts/stories for Royal Gold), so the composite went UNKNOWN.

**Root cause:** `sentiment_cache.classify_messages` made ONE LLM call. On any failure (including transient 429s), it gave up. The `FALLBACK_MODEL = "openai/gpt-oss-120b:free"` constant was defined at module-top but **never referenced anywhere**. By contrast, `news_glyph._llm_score_batch` HAS the retry-with-fallback loop. The two scorers had divergent reliability.

**Fix (this commit):** Extracted the single-attempt body into `_classify_one_attempt`; `classify_messages` now calls it once with the primary model, and on a transient error (429, 5xx, network) retries with `FALLBACK_MODEL`. Permanent errors (4xx other than 429, JSON parse failure) don't trigger fallback — the fallback would just fail the same way. Added a `_is_transient_error` helper with explicit codes so future tweaks can't accidentally widen "transient" to include programming errors.

**Validated end-to-end:** Re-scoring RGLD with the fix surfaced 🔥 **EXTREME_BULL (bull 84% / conviction 77%) — FADE flag**. That actionable contrarian read was being silently hidden whenever Gemma 429'd.

**Tests:** `tests/test_classifier_fallback.py` — 21 new tests cover the transient classifier (parametrized over codes), fallback trigger on 429, no-retry on permanent errors, no-loop when caller already specifies the fallback, both-fail error reporting.

**Operational gotcha (still):** Gemma 429s are common during batched scoring runs. The fallback now handles each call individually, so a single 429 no longer kills a source — but if BOTH models are rate-limited at the same time, the source still fails. `--model openai/gpt-oss-120b:free` to start on the fallback directly is still the way to do a large batch re-score session.

**This is the kind of bug the data-health surface (logged in notes/ideas.md) would also make visible** — `present: false + error: "HTTP 429"` should be operator-visible as "transient failure, will retry next refresh" not silently identical to `present: false + error: null` (legitimate no-coverage). Worth pairing the two fixes when the data-health work happens.

---

### 2026-06-10 — Sentiment classifier had no relevance gate — off-topic items polluted bull/bear%

**Symptom (already noted in v2.0.2):** the HN coverage fix admitted "Microsoft Project Solara" stories into the SOL HN signal. The downstream classifier (`sentiment_cache.classify_messages`) scored every body as bull/bear/neutral with no way to flag "this isn't actually about the ticker." Off-topic content silently diluted the on-topic read.

**Fix (this commit):** Added `relevance` to the classifier output schema. The prompt now asks for `{relevance: primary|mention|none, sentiment, conviction}`; bodies marked `none` get zero weight in `llm_pcts`, `mention` get half weight, `primary` get full weight. The company-name label (`TICKER (Company Name)`) is passed in the prompt — same pattern as the v2.0.1 news-glyph fix — so the LLM can correctly distinguish "Solana" from "Microsoft Project Solara" or "Federal" from "Hedera".

Validated end-to-end:
- **SOL HN**: 4 bodies (Microsoft Project Solara stories + comments) → 4 off-topic, 0 primary. HN signal correctly reads as no-on-topic-data instead of polluted-neutral.
- **BTC HN**: 27 bodies → 14 primary, 3 mention, 10 off-topic. Pre-fix bull/bear/neutral was diluted by the 10 off-topic items; now reflects only the on-topic 17 (14 primary + 3 mention at half-weight).
- **SOL StockTwits**: 30 messages → 15 primary, 14 mention, 1 off-topic. Multi-ticker posts ("$SOL.X + $MA = cool") correctly recognized as mention not primary — half-weighted so they contribute but don't dominate.
- **BTC StockTwits**: 30 messages → 25 primary, 5 mention, 0 off-topic. Almost entirely clean signal as expected.

**Architecture note:** the company-label resolution is `sentiment_cache._company_label() → news_glyph._company_label()` via lazy import. Single source-of-truth map in `news_glyph.COMPANY_LABELS`; both the per-headline scorer and the per-body classifier read it.

**Asset-class plumbing fix:** HN raw caches were missing the `asset_class` field that StockTwits/Reddit raw caches carry. `score_ticker` now infers it (via ticker-pattern fallback when no source has it) and injects into all three raw payloads before per-source processing — so the lazy import + label lookup work for HN even on older cache files.

**Operational gotcha:** OpenRouter free-tier `gemma-4-31b-it:free` 429s easily on consecutive scores. The `gpt-oss-120b:free` fallback handles overflow cleanly; specify `--model openai/gpt-oss-120b:free` for batch re-scoring sessions.

---

### 2026-06-10 — BTFD/STR panel: naïve zip() pairing crypto rows by index silently dropped candidates

**Symptom:** The Action Rail showed `2 BTFD` (counted from watchlist iteration) but the BTFD/STR panel rendered only 1 candidate (MRVL). ENA was qualifying (chg=-10.21%, vol=1.59x — passes crypto LIGHT_DIP gate of chg≤-4% AND vol≥1.5×) but never appeared.

**Root cause:** The BTFD panel iterated `zip(ctx["watchlist"]["crypto"], ctx["crypto_rows"])`. `crypto_rows` comes back from CoinGecko in **market-cap order**, not watchlist order. ENA sat at watchlist position 7 (BTC, ETH, SOL, BNB, XRP, HBAR, HYPE, ENA), but at a different position in `crypto_rows` — so the zip paired ENA's watchlist entry with whatever sat at index 7 in the rows list. The classifier got the wrong chg/vol data and missed the candidate.

This is the *same bug pattern* as the crypto grid (which was already fixed with a `_rows_by_sym = {(r.get("symbol") or "").upper(): r for r in ...}` lookup at line ~4853, with a "BUGFIX:" comment). The BTFD panel had a copy-paste of the original buggy code that nobody noticed because it failed silently — no error, just under-counted.

**Fix:** Same lookup-by-symbol pattern applied to the BTFD panel's crypto loop. Action Rail now uses the IDENTICAL classifier (`classify_btfd_str_shared`) hoisted to render_html scope, so rail counts and panel rows can never drift apart on threshold tweaks.

**Audit recipe:** Any time you see "rail count = X but panel shows Y" for crypto-derived signals, suspect a zip-by-index. Manual reconstruction (iterate watchlist + look up data by symbol explicitly) will reveal which tickers got mis-paired.

---

### 2026-06-10 — Mobile expanded-row dropdown was rendering 1543px wide in a 390px viewport

**Symptom:** Clicking a US/KLSE row to expand its dropdown details panel made the content scroll horizontally — the gates, thesis, sentiment, and news content were essentially off-screen unless you swiped right.

**Root cause:** The mobile CSS made `.panel table { overflow-x: auto; }` with `tbody { min-width: 1100px }` so the body fits all 16 columns horizontally. The expanded row is a separate `<tr.exp-details><td colspan="15">` inside that same tbody. So the `<td>` inherited the 1100px+ min-width and rendered ~1543px wide on a 390px viewport.

**Fix:** Made `.exp-details-content` use `position: sticky; left: 0; max-width: calc(100vw - 24px)`. The content visually clamps to the viewport regardless of the table's horizontal scroll position — and remains visible even if you've scrolled the table sideways to look at distant columns. Also collapsed `.exp-gates-grid` to single-column on mobile so the gates/sentiment/news sections stack instead of competing for narrow space.

**Test recipe:** Inspect computed widths after clicking an expand chevron at mobile width: `pg.evaluate(...)` to read `.exp-details-content` bounding-box width vs viewport width. If they're close, fix is in.

---

### 2026-06-10 — HN sentiment: `num_comments>=3` filter silently dropped niche-ticker coverage

**Symptom:** Inspecting `.claude/cache/hn_sentiment/` showed `story_count=0` for ETH, SOL, HYPE despite these being heavily HN-relevant. RYDE had 5 "stories" of pure junk (e.g. "Show HN: Freenet, a peer-to-peer platform for decentralized apps" — has nothing to do with Ryde Group).

**What was happening:** The Algolia search used `numericFilters: created_at_i>cutoff,num_comments>=3`. Direct API testing showed e.g. "Ethereum" returned 7 stories in the last 30 days *with the time filter alone*, but **0** when adding `num_comments>=3`. Niche-ticker HN posts often sit at 1-2 comments; the `>=3` floor (chosen as "not worth the round-trip") was eliminating every real signal for any non-mainstream name. Meanwhile RYDE's bare-ticker query `"Ryde"` produced false-positive substring matches across the HN corpus.

**Fix (this commit):** Lowered `MIN_COMMENTS_FILTER` from 3 → 1 in `hn_sentiment.py`. After force-rescoring, ETH 0→2, SOL 0→2, HYPE 0→1 (CIFR/CLSK genuinely have no HN coverage — they remain 0, which is correct degraded behavior). Marked `RYDE: None` in `TICKER_NAMES` to skip the noisy query entirely. Each refresh produces a clean cache (`status=no_coverage` with reason) instead of 5 junk stories.

**Tradeoff:** Relaxing the comment filter admits some noise (e.g. SOL now picks up "Microsoft Project Solara" stories which aren't about Solana). That's tolerable because the downstream classifier in `sentiment-cache.classify_messages` already classifies bodies as bull/bear/neutral — irrelevant content scores as `neutral`, diluting but not misleading the composite.

**Next-level improvement (not in this PATCH):** `sentiment-cache.classify_messages` for HN doesn't have a relevance gate (the news-glyph LLM call does — `relevance: primary|mention|none`). Adding a relevance pass to the HN classifier would let real bull/bear signal through cleanly while explicitly dropping noise instead of relying on neutral-dilution. That's a separate calibration project.

**Audit recipe:** `python3 .claude/skills/hn-sentiment/hn_sentiment.py --show` lists per-ticker queries + cache freshness. To verify Algolia behavior directly, hit `https://hn.algolia.com/api/v1/search?query=X&tags=story&numericFilters=created_at_i>{cutoff},num_comments>=N` — N=1 vs N=3 vs N=0 makes a huge difference for niche names.

---

### 2026-06-10 — News-glyph LLM scoring: KLSE non-English headlines need a company-label in the prompt

**Symptom:** Auditing 2110 cached LLM-scored items across 25 tickers (`audit_glyph.py`), the spot-checks looked clean on US/crypto but the four KLSE codes showed a striking pattern: 80%+ of Chinese-press headlines (e.g. `盛艺机构发股收购…`, `亚泛控股…`) scored `relevance=none / score=0.0` and silently dropped from the news signal. Latin-name headlines for the same companies scored fine.

**What was happening:** The scorer's prompt sent `TICKER: 9431` — a 4-digit Bursa code with zero semantic content. The model had no way to know `9431 = Seni Jaya = 盛艺机构`. It pattern-matched recurring proper nouns in English headlines but couldn't bridge to Chinese-only ones. The system prompt already said "TICKER or commonly-known company name" — the language was right, the data wasn't there.

**Fix (shipped in this commit):** Added a `COMPANY_LABELS` map per asset class in `news_glyph.py`. KLSE entries carry both Latin and Chinese forms (`"9431": "Seni Jaya Corporation Berhad / SJC (also written 盛艺机构)"`). The prompt now sends `TICKER: 9431 (Seni Jaya Corporation Berhad / SJC (also written 盛艺机构))`. Threaded `asset_class` through `llm_score_items_for_ticker → _llm_score_batch`. After force-rescoring the 4 KLSE codes, all Chinese-only relevant headlines correctly resolve to `primary` with non-zero scores; unrelated Chinese headlines (世界杯魔咒, 越南黄金) still correctly score `none`. US/crypto unchanged.

**Operational gotcha while validating:** OpenRouter free-tier rate-limit (429) kicked in after re-scoring 1 batch. The GPT-OSS-120B fallback handled the next batch cleanly (verifiable in cache: `models: {'gemma-4-31b-it:free', 'gpt-oss-120b:free'}`). For multi-ticker re-scoring, expect to space requests by ~60s to avoid the 429 → fallback → 429 → empty cache result.

**What NOT to do:** don't auto-add COMPANY_LABELS entries via watchlist parsing. The KLSE entries especially need Chinese forms which can't be auto-derived from the watchlist's English-only thesis line. Manual map entry on watchlist add is correct (~20 KLSE-relevant rows total across all foreseeable watchlist sizes).

**Audit tool:** `python3 .claude/skills/us-news/audit_glyph.py [--ticker X --asset-class Y] [--flagged-only]` joins every cached score to its headline, flags FALSE-NONE/FALSE-PRIMARY/ROUNDUP/NON-ASCII/DIR-MISMATCH. Treat the FALSE-PRIMARY flag as a *suggestion* — it has false positives on analyst-rating items (already filtered) and on legitimate primary headlines where the company name appears in a non-canonical form ("Cipher Unit" vs "Cipher Mining").

---

### 2026-06-10 — Finnhub free tier: `/stock/candle` returns HTTP 403 (premium-gated)

**Symptom:** `finnhub_client.candle_closes()` / `stock_candle()` return `HTTP 403`. Quotes (`/quote`) still work fine.

**Implication:** Finnhub free no longer serves historical candles — only real-time quotes, metrics, news, and upgrade/downgrade. Any code needing OHLCV history (returns, RSI-from-closes, relative strength) cannot use Finnhub on the free tier.

**Workaround:** Use yfinance for history. `rel_strength.py` and `retired_scan.py` both do a single **batched** `yf.download([...], period=...)` (not per-ticker `.info`, per the XProtect note below) to compute returns/indicators. Finnhub stays the source for live intraday quotes (the watcher, per-row 🔄 quote button).

---

### 2026-06-07 — macOS XProtect popup on dashboard build — investigated, unreproducible at real load

**Symptom:** Occasional "Malicious Script Blocked" popup during `dashboard.py --with-discovery`. Screener subprocess may exit early; dashboard.html still renders from cached `candidates.json`.

**What we initially thought:** XProtect tightened signatures to block per-ticker yfinance loops; ~130 sequential `yf.Ticker(t).info` calls in `screener.py:420` were matching a new signature.

**What the data actually showed (diagnostic 2026-06-07):**
- 2 / 10 / 50 / 130 sequential `yf.Ticker(t).info` calls all completed clean — no XProtect kill, no errors, RC=0.
- `fetch_fundamentals` is only called for **P1-passing candidates**, not the full 188-name universe. Real load is typically **1-2 yfinance.info calls per screener run**, not 130. Today's cache showed exactly 2 P1 passers (CMI, SPY) → 1 yfinance fallback.
- So the "130 rapid calls trip XProtect" hypothesis was based on an upper-bound that never actually happens.

**Plausible actual cause of the popup:**
- A one-off XProtect signature push from Apple that fired transiently then got revised
- A different process on the operator's Mac, not the screener
- An intermittent borderline match

**What's in place now:** Defensive `print(f"  [fund] [{i+1}/{len(to_fetch)}] {t} ...")` line at the top of the fundamentals loop (`screener.py` ~line 453). If XProtect fires again, the last-printed line tells us exactly which ticker, which call number, and elapsed time — actionable diagnostic data instead of guessing.

**What NOT to do:** don't ship a fundamentals-path migration to FMP-only "as a precaution." The real load is ~1-2 yfinance calls; the fix would solve a phantom and lose Q+V tagging for non-megacaps.

**If it happens again:** capture the terminal output (the new defensive log), check whether the popup names a specific script path, and revisit. Update this entry, don't preemptively rewrite code.

**Verified end-to-end (2026-06-08):** the defensive trace was exercised via a targeted `fetch_fundamentals(['CMI', 'SPY'], force=True)` invocation. Output was exactly as designed — `[fund] [1/2] CMI (yf_used=0, elapsed 0.0s)` and `[fund] [2/2] SPY (yf_used=1, elapsed 3.5s)` — clean lines, actionable post-mortem data. Cache repopulated correctly, dashboard.py end-to-end rebuild produced a clean 205KB dashboard.html with all panels (Risk Sim, watchlist, discovery) intact. No XProtect popup across the entire verification (130-call diagnostic + 2 forced fundamentals fetches + 2 full dashboard builds).

---

### 2026-06-05 — FMP free tier only covers ~30-50 megacap US symbols

**Symptom:** HTTP 402 (Payment Required) on most non-megacap symbol fetches from FMP `/stable/` endpoints.

**Implication:** Any fundamentals path that relies on FMP for the full screener universe (176 names) will hit paywalls for ~130 of them. The current code falls back to yfinance, but see XProtect note above.

**Workaround:** Either pay for FMP Starter ($14/mo, covers all US equities), or accept tech-only screening for non-megacaps.

---

### 2026-06-05 — Tokenomist.ai is a Next.js SPA — direct urllib scraping returns no data

**Symptom:** `urllib.request.urlopen("https://tokenomist.ai/<slug>")` returns near-empty HTML. All token-unlock data is fetched client-side via JS.

**Workaround:** The `crypto-unlocks` skill is agent-only — uses WebFetch (or whatever the agent's web tool is) to render the SPA. Then results get piped into `crypto-unlocks-cache` Python CLI for persistence. See `.claude/skills/crypto-unlocks-cache/SKILL.md`.

---

### 2026-06-04 — yfinance occasionally returns rows with NaN Close

**Symptom:** Some `yf.Ticker(t).history()` results have a final-row Close=NaN, especially for thinly-traded names or right after a session boundary.

**Fix:** Always `.dropna(subset=["Close"])` before reading the last row. Fall back to Twelve Data if the dropna leaves an empty DataFrame. Pattern used in `dashboard.py` and `screener.py`.

---

### 2026-06-15 — Free, no-spend sentiment re-scoring: the `sentiment-inline` skill

**Context:** the `sentiment-cache` LLM leg (OpenRouter free models) is the slow part of a build — free-tier 429s → backoff → fallback double-calls, serial per ticker. The only paid speedup (Haiku on OpenRouter, or the Anthropic API) breaks the project's "free LLM, zero metered spend" sentiment design.

**Insight:** during a session you ARE a capable classifier. The only thing that differs from `score_ticker` is the `classify_messages` LLM call — so `sentiment-inline` monkeypatches *only that one function* (capture bodies in `dump`, return session-scored classifications in `ingest`) and reuses 100% of the real pipeline (llm_pcts, engagement weighting, coverage haircut, compute_composite, cache format). No format drift.

**Use:** `score_inline.py dump --stale` → fill each batch's `scores` array (one `{sentiment,conviction,relevance}` per body) → `score_inline.py ingest`. Manual, session-only (NOT headless — automated builds still use `sentiment-cache`). Re-scores existing raw social caches; run the raw fetchers first if those are stale too.

**Landmines mapped while scoring real feeds:** StockTwits/HN feeds are heavily polluted — `$RUM` promo spam tagging RDDT, `$UPDOG.X` memecoin spam tagging SOL, "Microsoft Project Solara" matching SOL (the exact Solana-vs-Solara case in the prompt), "Sqlit" matching ENA, the word "hype" matching HYPE, generic HN (Lean Startup AMA, H1B visa, DVD ripping) matching BNB/HBAR. The `relevance: none` discount is doing real work — score look-alikes/tag-spam as `none` so they don't dilute the on-topic read.

---

### 2026-06-15 — launchd can't daemonize from ~/Documents (macOS TCC); + server dual-stack

**Two findings while making the dashboard control server robust.**

**1. Dual-stack bind.** `server.py` bound IPv4-only (`0.0.0.0` via `ThreadingHTTPServer`, which is `AF_INET`). On macOS `localhost` resolves to `::1` (IPv6) first, and Tailscale MagicDNS hands out an IPv6 address — both got connection-refused → "dashboard is down." Fix: `DualStackHTTPServer(ThreadingHTTPServer)` with `address_family = AF_INET6` and `setsockopt(IPPROTO_IPV6, IPV6_V6ONLY, 0)` in `server_bind`, binding `::` in `--lan`. One socket serves 127.0.0.1, LAN-v4, Tailscale-v4, ::1, IPv6, MagicDNS. Verify a dual-stack listener with `lsof` showing `IPv6 ... TCP *:PORT (LISTEN)` and curling BOTH `127.0.0.1` and `[::1]`.

**2. launchd LaunchAgent flaps with `EX_CONFIG` (78) when the job lives under ~/Documents.** The exact `ProgramArguments` command runs fine in an interactive shell but the agent exits 78 before Python writes a single line, `runs` climbs every `ThrottleInterval`. Cause: `~/Documents` (also `~/Desktop`, `~/Downloads`) is **TCC-protected**; a launchd agent can't read the script / write StandardOutPath there. The interactive shell only works because it inherited Terminal's TCC grant. There is NO scriptable fix — you must either grant **Full Disk Access to `/usr/bin/python3`** in System Settings → Privacy & Security (one-time, manual, GUI) and then `launchctl kickstart -k gui/$(id -u)/<label>`, OR move the whole project out of `~/Documents`. Until then, run detached with `nohup … & disown` (inherits the session's TCC grant; reparents to PID 1; survives the session but not reboot/logout). The plist is committed at `.claude/skills/dashboard/com.trading-advisor.dashboard.plist` ready to load once FDA is granted.

**Bonus gotcha:** a long-lived `server.py` (≈4 days) wedged — `/api/status` (small) still answered 200 but `/` and `/dashboard.html` (large) returned `ERR_EMPTY_RESPONSE`/HTTP 000. Code was fine (`render_dashboard()` worked standalone). A clean restart cleared it. If the dashboard goes empty while the process is still listening, restart it.

---

### 2026-06-15 — "N source(s) refreshable" stuck forever = health LOOKUP mismatch, not a data gap

**Symptom:** Data Health panel persistently shows "9 source(s) refreshable" even right after a Full refresh. `refreshable = stale + transient + MISSING` (health.summarize), and here it was 0 stale / 9 missing — so it's 9 phantom "missing" that no refresh can clear.

**Diagnosis recipe:** import `dashboard` + `health`, run `collect_health(dashboard.parse_watchlist())`, filter `state==MISSING`, print `(source, ticker)`. Don't theorize — list them.

**Two root causes found, both health expecting the WRONG filename:**
1. `crypto_news` caches are written by `news_glyph.py` keyed by **CoinGecko slug** (`bitcoin.json`, `hedera-hashgraph.json`), but `health._crypto_key` lowercased the ticker (`btc.json`, `hbar.json`) → never matched → all crypto names "missing" permanently. Fix: `_crypto_news_key` slug map (mirror of `dashboard.SYMBOL_MAP`).
2. SPY is **intentionally** never `us_news`-fetched (`news_cache.priority_for_ticker` returns None for the index gauge), but health expected `SPY.json`. Fix: `US_NEWS_SKIP = {"SPY"}` in `collect_health`.

**General lesson (3rd time this pattern has bitten):** the Data Health panel makes a *promise* — "this is refreshable." Whenever the panel and the actual refresh/fetch behavior disagree (TTL, filename key, intentional skip), the panel lies and the operator loses trust. When health flags something refreshable that a refresh won't fix, suspect a health-vs-reality mismatch, not a fetch failure. Cross-check: does the cache file actually exist under the name `collect_health` computes? `ls` the dir and compare to `key_fn(ticker)`.
