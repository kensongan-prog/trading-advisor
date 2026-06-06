# Crypto Unlocks Cache — User Guide

Records crypto token-unlock data so the dashboard's Risk Simulator can run the doctrine §5 48h-halt gate as a real check instead of a manual-check warning.

---

## Quick start

```bash
# 1. One-time: seed baseline entries for assets with no vesting (BTC, ETH, stables)
#    and regular emission (SOL, BNB, XRP, HBAR, ADA, DOGE)
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py baseline

# 2. Audit: which watchlist coins still need a manual entry?
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py audit

# 3. For each alt that shows "no cache entry":
#    a) Ask the agent to run the WebFetch crypto-unlocks skill on it
#       ("check the next unlock for HYPE")
#    b) Record the answer:
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py set HYPE \
  --date 2026-06-06 --type cliff --pct 2.54 --tokens 675000000 \
  --recipient "Core Contributors" --source "tokenomist.ai/hyperliquid"

# 4. Rebuild the dashboard so the sim picks it up
python3 .claude/skills/dashboard/dashboard.py
```

---

## Why this design (Q&A)

**Why a manual cache instead of auto-scraping tokenomist.ai?**
Tokenomist.ai is a Next.js single-page app — page HTML is mostly empty shells, and all unlock data arrives via client-side fetches. Python `urllib` gets back ~600KB of JS bundles and zero unlock data. DeFiLlama's emissions API moved to a paid plan (HTTP 402). CryptoRank and CoinGecko don't expose unlock schedules on their free tiers. Result: the only reliable retrieval path is the agent-driven WebFetch skill, which goes through Claude's browser-like fetcher and reads the rendered page. This cache is the bridge between that on-demand fetch and the dashboard's batch build.

**Why baseline entries?**
BTC, ETH, and stablecoins have no vesting schedule — running a "manual check needed" warn on every dashboard build would be noise. The baseline pre-fills them as auto-pass. SOL/BNB/XRP/HBAR have known regular emission patterns that almost never breach the 1% halt threshold, but we still flag them as warn ("verify on tokenomist.ai") because a major schedule change should be caught.

**Why no auto-refresh?**
Unlock schedules don't change daily. A manual model means you control when fresh data flows in — same pattern as `klse-refresh`, `klse-announcements`, and the AV news cache. Run the WebFetch skill + `set` when:
- You're about to size a new alt position
- A coin had an unlock event recently (re-fetch to get the *next* one)
- A team announces a buyback / lock extension / restructure

---

## Subcommands

| Command | What it does |
|---|---|
| `baseline` | Seeds entries for BTC, ETH, stables (no-schedule) and SOL, BNB, XRP, HBAR, ADA, DOGE (regular-emission) |
| `set <COIN> --date YYYY-MM-DD --type cliff --pct 2.5 …` | Records a manual entry with full detail |
| `set <COIN> --no-upcoming` | Explicitly records "no upcoming cliff" — satisfies the gate |
| `show [COIN]` | Pretty-prints cache state with gate status icons |
| `audit` | Walks `watchlist.md` crypto section and reports per-coin coverage |
| `clear [COIN] / --all` | Removes entries |

---

## How the dashboard uses it

The Risk Simulator's "Token unlock window" gate reads `.claude/cache/crypto_unlocks/{COIN}.json` and resolves to:

| State | Result |
|---|---|
| `baseline_no_schedule` (BTC/ETH/stables) | ✓ pass |
| `baseline_regular` (SOL/BNB/XRP/HBAR/…) | ⚠ warn ("verify on tokenomist.ai") |
| `manual`, unlock > 7d out | ✓ pass |
| `manual`, unlock 3-7d out | ⚠ warn |
| `manual`, unlock in 48h, ≥1% float | 🛑 **BAD — doctrine §5 halt** |
| `manual`, unlock in 48h, <1% float | ⚠ warn |
| `manual`, unlock in 48h, size unknown | 🛑 **BAD** (treat as inside halt) |
| `manual`, recorded date in past | ⚠ warn ("refresh") |
| No entry | ⚠ warn ("run the cache skill") |

---

## Typical agent workflow

User: "Run the sim on HYPE"
Agent flow:
1. Detect HYPE has no `manual` entry (or stale one)
2. Call WebFetch on `https://tokenomist.ai/hyperliquid` for next-unlock data
3. Run `set HYPE --date … --pct … --type cliff …`
4. Rebuild dashboard
5. Report sim results — the Token-unlock gate now reflects the live data

---

## Honest limitations

1. **Manual data entry can drift.** Re-fetch with the WebFetch skill before any high-conviction trade.
2. **Sizing on tokenomist.ai is partially Pro-gated.** If the % of float isn't visible, record `--pct` as omitted; the gate treats unknown sizing inside 48h as a hard halt per doctrine.
3. **Baseline assumptions can age.** SOL's regular-emission entry was true as of 2026 — if a new vesting tranche is announced, override with a manual `set`.
4. **Token slugs are not tickers.** HYPE→hyperliquid, ENA→ethena, ARB→arbitrum, OP→optimism, etc. See the `crypto-unlocks` WebFetch SKILL.md for verified slugs.

---

## Pairing with other skills

| Skill | Refresh script / call | What it pulls |
|---|---|---|
| `crypto-unlocks` (WebFetch) | Agent-only, on-demand | Live tokenomist.ai data for one coin |
| `crypto-unlocks-cache` (this) | `crypto_unlocks_cache.py` | Persists the above into JSON cache the dashboard reads |
| `crypto-coingecko regime` | dashboard does this on build | Fear & Greed + BTC dominance composite |
| `crypto-derivatives` | dashboard does this on build (per-coin funding) | Binance funding rate, OI, long/short |

A typical morning routine for crypto:

```bash
# Refresh dashboard (pulls fresh klines + funding + regime)
python3 .claude/skills/dashboard/dashboard.py

# For any alt you're about to size, get fresh unlock data
# (agent does this via WebFetch then `set`)

# Re-render dashboard
python3 .claude/skills/dashboard/dashboard.py
```

---

## TL;DR

- Run `baseline` once; coverage for BTC/ETH/SOL/BNB/XRP/HBAR/stables is free
- For alts (HYPE, ONDO, ENA, ARB, OP, APT, SUI, STRK…), use WebFetch + `set` per coin
- Manual by design — no cron, you decide when fresh data flows
- Dashboard sim's §5 48h-halt gate is now a real check, not a warn
