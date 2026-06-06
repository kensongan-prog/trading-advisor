---
name: crypto-unlocks-cache
description: Python-callable cache for crypto token-unlock data, consumed by the dashboard's Risk Simulator §5 48h-halt gate. Seeds baseline entries for assets with no vesting schedule (BTC, ETH, stables) and assets with regular emission (SOL, BNB, XRP, HBAR). For alts with cliff/team unlocks (HYPE, ONDO, ENA, ARB, etc.), use the agent-only `crypto-unlocks` WebFetch skill to fetch tokenomist.ai data, then record it here via the `set` subcommand. Manual by design — no automation, no cron. Tokenomist.ai is a Next.js SPA so direct urllib scraping won't work; this skill is the bridge.
---

# Crypto Unlocks Cache Skill

## When to use

- "Refresh crypto unlocks" / "update unlock cache"
- Before sizing any alt-coin long where a vesting cliff could land inside the doctrine §5 48h window
- After running the `crypto-unlocks` (WebFetch) skill — pipe the answer into `set`
- Audit: "Show me crypto unlock cache" / "Which watchlist coins are missing entries?"

Do NOT use for:
- Per-coin price / RSI / ATR — that's `dashboard` (Binance klines + CoinGecko OHLC fallback)
- Live tokenomist.ai data — that's the agent-only `crypto-unlocks` WebFetch skill
- Crypto sentiment / Fear & Greed — that's `crypto-coingecko regime`

## Why this exists

CLAUDE.md §5 hard rule: **"Crypto: 48h before a scheduled token unlock > 1% of float"** — no new directional exposure.

Tokenomist.ai is the canonical unlock data source, but it's a Next.js SPA — page HTML is mostly empty, all data fetches happen client-side. Direct `urllib`/`requests` scraping returns no usable JSON. DeFiLlama emissions API moved behind a paid plan (HTTP 402). CoinGecko/CryptoRank don't expose unlock schedules on their free tiers.

Result: there is no scrape-friendly source for cliff-unlock dates. This skill solves it by maintaining the cache as a human/agent-curated JSON store. The dashboard reads it on build and runs a real §5 gate instead of a manual-check warn.

## What gets cached per coin

`.claude/cache/crypto_unlocks/{COIN}.json`:

```json
{
  "coin": "HYPE",
  "source": "tokenomist.ai/hyperliquid",
  "_source_type": "manual",
  "_fetched_at": "2026-06-04T22:30:00+00:00",
  "notes": "Major cliff unlock — team committed to claiming only ~$38M of the 675M tokens",
  "next_unlock": {
    "date": "2026-06-06",
    "type": "cliff",
    "pct_of_float": 2.54,
    "tokens": 675000000,
    "usd_value": 675000000,
    "recipient": "Core Contributors"
  }
}
```

For BTC/ETH/stables (no vesting):
```json
{
  "coin": "BTC",
  "_source_type": "baseline_no_schedule",
  "notes": "No vesting schedule — mining emission only (~6.25 BTC/block, halving every ~4y).",
  "next_unlock": null
}
```

`_source_type` controls how the dashboard gate treats it:
- `baseline_no_schedule` → ✓ auto-pass (BTC, ETH, USDC, USDT, DAI)
- `baseline_regular` → ⚠ warn ("verify on tokenomist.ai") — SOL, BNB, XRP, HBAR, ADA, DOGE
- `manual` → real gate based on `next_unlock.date` and `pct_of_float`

## Usage

```bash
# Seed baseline entries for BTC/ETH/SOL/BNB/XRP/HBAR/stables (run once after install)
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py baseline

# Audit watchlist: which coins have entries, which don't, what each gate would return
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py audit

# Record an alt's next unlock (typically after running the WebFetch crypto-unlocks skill)
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py set HYPE \
  --date 2026-06-06 --type cliff --pct 2.54 --tokens 675000000 \
  --recipient "Core Contributors" --source "tokenomist.ai/hyperliquid"

# Explicitly record "no upcoming cliff" (still satisfies the gate)
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py set ARB --no-upcoming

# Inspect cache state
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py show
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py show HYPE

# Wipe entries
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py clear HYPE
python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py clear --all

# Then rebuild dashboard so the sim picks up the new state
python3 .claude/skills/dashboard/dashboard.py
```

## Typical agent workflow for an alt

1. User asks for a sim run on HYPE / ONDO / ENA / etc.
2. Agent invokes `crypto-unlocks` (WebFetch on tokenomist.ai/{slug}) to get the next-unlock date + size
3. Agent runs `python3 …crypto_unlocks_cache.py set <COIN> --date … --pct … --type …` to record it
4. Agent runs `python3 …dashboard.py` to rebuild
5. Sim's Token-unlock gate now reflects reality, no manual-check warn

## Hard rules

1. **No fabrication.** If tokenomist.ai data isn't available for a coin, leave the cache empty — the gate emits a warn telling the user to run the WebFetch skill. Never write a `next_unlock` with invented values.
2. **Manual refresh.** No cron, no auto-fetch on dashboard build. Cache is the user's (or agent's) responsibility.
3. **Stale-aware.** Entries older than ~7 days for `manual` sources should be re-fetched — unlock schedules can shift (team buybacks, lock extensions). The `show` command displays `_fetched_at` so you can spot stale entries.
4. **Baseline beats blank.** Run `baseline` first so BTC/ETH/SOL etc don't trip a manual-check warn on every dashboard build.

## Gate logic (mirrors the dashboard sim's JS)

| Cache state | Gate status | Why |
|---|---|---|
| No entry | ⚠ warn | "run crypto-unlocks-cache `set`" |
| `baseline_no_schedule` | ✓ ok | "no vesting schedule" |
| `baseline_regular` | ⚠ warn | "verify on tokenomist.ai" |
| `next_unlock` null (manual) | ⚠ warn | "refresh — no next-unlock recorded" |
| Unlock date in past | ⚠ warn | "refresh — recorded date has passed" |
| Unlock within 48h, ≥1% float | 🛑 bad | §5 halt |
| Unlock within 48h, <1% float | ⚠ warn | inside window, below threshold |
| Unlock within 48h, size unknown | 🛑 bad | treat as inside halt window per doctrine |
| Unlock 3-7 days out | ⚠ warn | outside halt but inside trade duration |
| Unlock > 7 days out | ✓ ok | clear |

## Maintenance

- The baseline coin list lives in `BASELINE_NO_SCHEDULE` and `BASELINE_REGULAR_EMISSION` dicts at the top of the script. Add a coin there when a new stablecoin or majors-tier asset enters the watchlist.
- Tokenomist.ai slug != ticker. See the WebFetch `crypto-unlocks` SKILL.md for verified slugs (HYPE→hyperliquid, ENA→ethena, etc.).
- If you want to seed ARB/OP/SUI/etc. as manual entries with verified dates, batch them with `set --no-upcoming` initially, then run the WebFetch skill per-coin to refresh.
