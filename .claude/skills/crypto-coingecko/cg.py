#!/usr/bin/env python3
"""
cg.py — CoinGecko fetcher for crypto prices, history, sentiment, and community/dev signals.

Single-purpose CLI invoked by the `crypto-coingecko` skill. Uses the public free
CoinGecko API (no key required for basic calls; if a COINGECKO_API_KEY is set it
will be passed in headers and you get higher rate limits).

Reads .env from the same directory if present.

Subcommands:
    quote      Snapshot: price, % change, market cap, vol, ATH, sentiment %, dev/community stats.
    history    OHLC over a window + computed indicators (RSI14, SMA20/50/200, ATR14).
    markets    Side-by-side comparison of multiple coins.

Usage:
    python3 cg.py quote --coin bitcoin
    python3 cg.py history --coin bitcoin --days 180 --indicators rsi,sma20,sma50,sma200,atr14
    python3 cg.py markets --coins bitcoin,ethereum,solana

Never falls back to LLM memory or fabrication. If the API errors or rate-limits,
the script prints an explicit failure message.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning)

PUBLIC_BASE = "https://api.coingecko.com/api/v3"
PRO_BASE = "https://pro-api.coingecko.com/api/v3"

# Tiny symbol → CoinGecko ID map for convenience. Anything not here must be
# passed as the explicit CoinGecko ID (e.g. "ethereum", "the-graph", "ondo-finance").
SYMBOL_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "ton": "the-open-network",
    "trx": "tron",
    "avax": "avalanche-2",
    "matic": "matic-network",
    "dot": "polkadot",
    "link": "chainlink",
    "uni": "uniswap",
    "ltc": "litecoin",
    "atom": "cosmos",
    "near": "near",
    "apt": "aptos",
    "arb": "arbitrum",
    "op": "optimism",
    "ondo": "ondo-finance",
    "hype": "hyperliquid",
    "sui": "sui",
}


def load_dotenv_if_present():
    p = Path(__file__).resolve().parent / ".env"
    if not p.is_file():
        return
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception as e:
        print(f"warning: failed to parse .env: {e}", file=sys.stderr)


def normalize_coin(raw):
    raw = raw.strip().lower()
    return SYMBOL_MAP.get(raw, raw)


def cg_get(path, params=None):
    """GET on CoinGecko. Returns (data, error_str). Uses pro endpoint if a key is set."""
    key = os.environ.get("COINGECKO_API_KEY")
    base = PRO_BASE if key else PUBLIC_BASE
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": "trading-advisor/1.0", "Accept": "application/json"}
    if key:
        # CoinGecko pro accepts the key via header on the pro domain.
        headers["x-cg-pro-api-key"] = key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            body = ""
        return None, f"HTTP {e.code}: {e.reason} :: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fmt_money(x, places=2):
    try:
        return f"${float(x):,.{places}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(x, places=2):
    try:
        return f"{float(x):+.{places}f}%"
    except (TypeError, ValueError):
        return "—"


def cmd_quote(args):
    coin = normalize_coin(args.coin)
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data, err = cg_get(
        f"/coins/{coin}",
        {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "true",
            "developer_data": "true",
            "sparkline": "false",
        },
    )
    if err:
        print(f"FETCH FAILED for {coin}: {err}")
        print("DO NOT use LLM memory or web search as a substitute.")
        return 1
    if not data or "id" not in data:
        print(f"NO DATA returned for {coin}.")
        return 1

    md = data.get("market_data") or {}
    cd = data.get("community_data") or {}
    dd = data.get("developer_data") or {}
    cur = (md.get("current_price") or {}).get("usd")
    mc = (md.get("market_cap") or {}).get("usd")
    vol = (md.get("total_volume") or {}).get("usd")
    ath = (md.get("ath") or {}).get("usd")
    atl = (md.get("atl") or {}).get("usd")
    ath_chg = (md.get("ath_change_percentage") or {}).get("usd")
    atl_chg = (md.get("atl_change_percentage") or {}).get("usd")

    print(f"CRYPTO QUOTE — {data.get('name', coin).upper()} ({(data.get('symbol') or '').upper()})")
    print(f"Source:        CoinGecko (api.coingecko.com)")
    print(f"Fetched (UTC): {fetched}")
    print(f"CoinGecko ID:  {data.get('id')}")
    print(f"Genesis date:  {data.get('genesis_date') or 'unknown'}")
    print(f"Categories:    {', '.join(data.get('categories') or []) or '—'}")
    print(f"Market rank:   #{data.get('market_cap_rank') or '—'}")
    print()
    print("PRICE")
    print(f"  Current:     {fmt_money(cur, 4 if (cur or 0) < 10 else 2)}")
    print(f"  24h change:  {fmt_pct(md.get('price_change_percentage_24h'))}")
    print(f"  7d change:   {fmt_pct(md.get('price_change_percentage_7d'))}")
    print(f"  30d change:  {fmt_pct(md.get('price_change_percentage_30d'))}")
    print(f"  1y change:   {fmt_pct(md.get('price_change_percentage_1y'))}")
    print(f"  ATH:         {fmt_money(ath, 4 if (ath or 0) < 10 else 2)}  ({fmt_pct(ath_chg)} from ATH)")
    print(f"  ATL:         {fmt_money(atl, 6 if (atl or 0) < 1 else 4)}  ({fmt_pct(atl_chg)} from ATL)")
    print()
    print("MARKET")
    print(f"  Market cap:  {fmt_money(mc, 0)}")
    print(f"  24h volume:  {fmt_money(vol, 0)}")
    circ = md.get("circulating_supply")
    total = md.get("total_supply")
    maxs = md.get("max_supply")
    print(f"  Supply:      circ={circ:,.0f}  total={total or '—'}  max={maxs or '—'}" if circ else f"  Supply: —")
    print()
    print("SENTIMENT (CoinGecko community votes)")
    up = data.get("sentiment_votes_up_percentage")
    dn = data.get("sentiment_votes_down_percentage")
    if up is not None and dn is not None:
        tag = ""
        if up >= 70:
            tag = "  ← strongly bullish community"
        elif up <= 30:
            tag = "  ← strongly bearish community"
        print(f"  Up: {up:.1f}%   Down: {dn:.1f}%{tag}")
    else:
        print("  (not reported)")
    print()
    print("COMMUNITY")
    print(f"  Twitter followers:  {cd.get('twitter_followers') or '—'}")
    print(f"  Reddit subs:        {cd.get('reddit_subscribers') or '—'}")
    print(f"  Telegram users:     {cd.get('telegram_channel_user_count') or '—'}")
    print()
    print("DEVELOPER (last 4 weeks)")
    print(f"  GitHub stars:       {dd.get('stars') or '—'}")
    print(f"  Forks:              {dd.get('forks') or '—'}")
    print(f"  Commits (4w):       {dd.get('commit_count_4_weeks') or '—'}")
    print(f"  PRs merged (4w):    {dd.get('pull_requests_merged') or '—'}")
    return 0


def rsi_wilder(closes, window=14):
    """Wilder's RSI on a list of close prices, returns the most recent value or None."""
    if len(closes) < window + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    # Initial avg.
    avg_g = sum(gains[:window]) / window
    avg_l = sum(losses[:window]) / window
    # Wilder smoothing on the rest.
    for i in range(window, len(gains)):
        avg_g = (avg_g * (window - 1) + gains[i]) / window
        avg_l = (avg_l * (window - 1) + losses[i]) / window
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))


def sma(closes, window):
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def atr_simple(ohlc, window=14):
    """Simple ATR on list of [t, o, h, l, c] rows."""
    if len(ohlc) < window + 1:
        return None
    trs = []
    for i in range(1, len(ohlc)):
        h = ohlc[i][2]
        l = ohlc[i][3]
        pc = ohlc[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-window:]) / window


def cmd_history(args):
    coin = normalize_coin(args.coin)
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data, err = cg_get(f"/coins/{coin}/ohlc", {"vs_currency": "usd", "days": str(args.days)})
    if err:
        print(f"FETCH FAILED for {coin} OHLC: {err}")
        return 1
    if not data or not isinstance(data, list) or len(data) == 0:
        print(f"NO DATA returned for {coin} OHLC (days={args.days}).")
        return 1

    # Rows: [timestamp_ms, open, high, low, close]
    rows = data
    closes = [r[4] for r in rows]
    indicators = {s.strip().lower() for s in args.indicators.split(",") if s.strip()}

    print(f"CRYPTO HISTORY — {coin}")
    print(f"Source:        CoinGecko /coins/{{id}}/ohlc")
    print(f"Fetched (UTC): {fetched}")
    print(f"Window:        last {args.days} day(s), USD")
    print(f"Bars returned: {len(rows)}")
    print()

    # Show recent rows.
    n_show = min(args.rows, len(rows))
    print(f"RECENT BARS (showing last {n_show}; CoinGecko uses 4h candles up to 30d, daily over 30d)")
    print(f"{'date (UTC)':20}  {'open':>12}  {'high':>12}  {'low':>12}  {'close':>12}")
    for r in rows[-n_show:]:
        dt = datetime.fromtimestamp(r[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"{dt:20}  {r[1]:>12.4f}  {r[2]:>12.4f}  {r[3]:>12.4f}  {r[4]:>12.4f}")
    print()

    # Stats.
    high_max = max(r[2] for r in rows)
    low_min = min(r[3] for r in rows)
    first_c = rows[0][4]
    last_c = rows[-1][4]
    print("WINDOW STATS")
    print(f"  High:  {high_max:.4f}   Low: {low_min:.4f}")
    print(f"  Δ:     {(last_c - first_c):+.4f}  ({((last_c - first_c) / first_c) * 100:+.2f}%)")
    print()

    if indicators:
        print("INDICATOR READOUTS (latest)")
        if "rsi" in indicators or "rsi14" in indicators:
            v = rsi_wilder(closes, 14)
            tag = ""
            if v is not None:
                if v > 70:
                    tag = "  ← OVERBOUGHT"
                elif v < 30:
                    tag = "  ← OVERSOLD"
            print(f"  RSI14 : {('%.4f' % v) if v is not None else 'insufficient data':>12}{tag}")
        for w in (20, 50, 200):
            key = f"sma{w}"
            if key in indicators:
                v = sma(closes, w)
                print(f"  SMA{w:<3}: {('%.4f' % v) if v is not None else 'insufficient data':>12}")
        if "atr14" in indicators or "atr" in indicators:
            v = atr_simple(rows, 14)
            print(f"  ATR14 : {('%.4f' % v) if v is not None else 'insufficient data':>12}")
    return 0


def cmd_markets(args):
    coins = [normalize_coin(c) for c in args.coins.split(",") if c.strip()]
    if not coins:
        print("ERROR: --coins is empty.", file=sys.stderr)
        return 2
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data, err = cg_get(
        "/coins/markets",
        {
            "vs_currency": "usd",
            "ids": ",".join(coins),
            "order": "market_cap_desc",
            "per_page": "250",
            "page": "1",
            "price_change_percentage": "1h,24h,7d,30d",
        },
    )
    if err:
        print(f"FETCH FAILED for /coins/markets: {err}")
        return 1
    if not data:
        print("NO DATA returned.")
        return 1

    print(f"CRYPTO MARKETS COMPARISON")
    print(f"Source:        CoinGecko /coins/markets")
    print(f"Fetched (UTC): {fetched}")
    print(f"Coins:         {', '.join(coins)}")
    print()
    print(f"{'symbol':8}  {'name':18}  {'price':>12}  {'24h%':>8}  {'7d%':>8}  {'30d%':>8}  {'mkt cap':>16}  {'24h vol':>14}")
    for r in data:
        sym = (r.get("symbol") or "").upper()
        name = (r.get("name") or "")[:18]
        price = r.get("current_price")
        ch24 = r.get("price_change_percentage_24h_in_currency")
        ch7 = r.get("price_change_percentage_7d_in_currency")
        ch30 = r.get("price_change_percentage_30d_in_currency")
        mc = r.get("market_cap")
        vol = r.get("total_volume")
        print(f"{sym:8}  {name:18}  {price:>12.4f}  {ch24 or 0:>+7.2f}%  {ch7 or 0:>+7.2f}%  {ch30 or 0:>+7.2f}%  {mc or 0:>16,.0f}  {vol or 0:>14,.0f}")
    return 0


FNG_URL = "https://api.alternative.me/fng/"


def fng_get(limit=8):
    """Fetch Crypto Fear & Greed Index from alternative.me. No auth."""
    url = f"{FNG_URL}?limit={limit}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "trading-advisor/1.0"}),
            timeout=20,
        ) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:200]
        except Exception:
            body = ""
        return None, f"HTTP {e.code}: {e.reason} :: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fng_signal(value):
    """Contrarian signal per Alt.me classification:
       <=25 Extreme Fear (+1 contrarian buy)
       <=45 Fear (+0.5)
       46-54 Neutral (0)
       >=55 Greed (-0.5)
       >=75 Extreme Greed (-1 contrarian sell)
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0, "unknown"
    if v <= 25:
        return +1, "Extreme Fear (contrarian buy zone)"
    if v <= 45:
        return +0.5, "Fear"
    if v < 55:
        return 0, "Neutral"
    if v < 75:
        return -0.5, "Greed"
    return -1, "Extreme Greed (contrarian top zone)"


def cmd_regime(args):
    """Composite crypto regime read: Fear & Greed + BTC dominance + total mcap + stable %."""
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"CRYPTO REGIME READ")
    print(f"Source:        CoinGecko /global  +  alternative.me Fear & Greed")
    print(f"Fetched (UTC): {fetched}")
    print()

    signals = []  # (label, weight, note)

    # 1. Fear & Greed.
    fng_data, err = fng_get(limit=8)
    fng_cur = fng_prev = None
    if err:
        print(f"  warn (F&G): {err}", file=sys.stderr)
    elif fng_data and fng_data.get("data"):
        rows = fng_data["data"]  # most recent first
        try:
            fng_cur = int(rows[0]["value"])
            fng_cur_label = rows[0].get("value_classification", "?")
        except (KeyError, ValueError, TypeError):
            pass
        if len(rows) >= 8:
            try:
                fng_prev = int(rows[7]["value"])
            except (KeyError, ValueError, TypeError):
                pass

    if fng_cur is not None:
        w, lab = fng_signal(fng_cur)
        signals.append(("fng_level", w, f"Fear & Greed {fng_cur}/100 ({fng_cur_label}) — {lab}"))
        if fng_prev is not None:
            delta = fng_cur - fng_prev
            if delta >= 20:
                signals.append(("fng_trend", -0.5, f"F&G rising fast ({fng_prev}→{fng_cur} in 7d, +{delta}) — euphoria building"))
            elif delta <= -20:
                signals.append(("fng_trend", +0.5, f"F&G falling fast ({fng_prev}→{fng_cur} in 7d, {delta}) — capitulation accelerating"))

    # 2. CoinGecko /global → BTC.D, ETH.D, total mcap, stablecoin %, 24h change.
    g_data, g_err = cg_get("/global")
    if g_err:
        print(f"  warn (/global): {g_err}", file=sys.stderr)
    elif g_data and "data" in g_data:
        d = g_data["data"]
        mcp = d.get("market_cap_percentage") or {}
        btc_d = mcp.get("btc")
        eth_d = mcp.get("eth")
        # Stablecoin dominance: sum of USDT/USDC/DAI/USDE if present
        stable_d = sum(mcp.get(s, 0) or 0 for s in ("usdt", "usdc", "dai", "usde", "fdusd", "tusd"))
        total_mc_usd = (d.get("total_market_cap") or {}).get("usd")
        total_vol_usd = (d.get("total_volume") or {}).get("usd")
        mc_24h = d.get("market_cap_change_percentage_24h_usd")
        n_coins = d.get("active_cryptocurrencies")

        if btc_d is not None:
            if btc_d >= 60:
                signals.append(("btc_dom_high", -0.5, f"BTC dominance {btc_d:.1f}% — alts under pressure (BTC-only regime)"))
            elif btc_d <= 45:
                signals.append(("btc_dom_low", +0.5, f"BTC dominance {btc_d:.1f}% — alt-season territory"))
            else:
                signals.append(("btc_dom_mid", 0, f"BTC dominance {btc_d:.1f}% — neutral"))

        if mc_24h is not None:
            if mc_24h >= 5:
                signals.append(("mcap_24h_up", +0.5, f"Total mcap +{mc_24h:.2f}% 24h — risk-on burst"))
            elif mc_24h <= -5:
                signals.append(("mcap_24h_down", -0.5, f"Total mcap {mc_24h:.2f}% 24h — risk-off flush"))
            else:
                signals.append(("mcap_24h_flat", 0, f"Total mcap {mc_24h:+.2f}% 24h — flat"))

        if stable_d > 0:
            # Point-in-time stablecoin dominance — trend would be ideal but /global is snapshot only
            if stable_d >= 8:
                signals.append(("stable_dom_high", +0.3, f"Stablecoin mcap share {stable_d:.2f}% — significant dry powder on sidelines"))
            elif stable_d <= 4:
                signals.append(("stable_dom_low", -0.3, f"Stablecoin mcap share {stable_d:.2f}% — most capital deployed (less buying power left)"))

        # Header context
        print("MARKET CONTEXT")
        print(f"  Total crypto mcap:     ${total_mc_usd/1e12:.2f}T" if total_mc_usd else "")
        print(f"  Total 24h volume:      ${total_vol_usd/1e9:.2f}B" if total_vol_usd else "")
        print(f"  24h mcap change:       {mc_24h:+.2f}%" if mc_24h is not None else "")
        print(f"  Active coins tracked:  {n_coins:,}" if n_coins else "")
        print(f"  BTC dominance:         {btc_d:.2f}%" if btc_d is not None else "")
        print(f"  ETH dominance:         {eth_d:.2f}%" if eth_d is not None else "")
        print(f"  Stablecoin share:      {stable_d:.2f}%   (USDT+USDC+DAI+USDE+FDUSD+TUSD)" if stable_d > 0 else "")
        print()

    # Composite
    print("SIGNAL TABLE")
    for tag, weight, note in signals:
        sign = "+" if weight > 0 else ("−" if weight < 0 else "0")
        print(f"  [{sign}{abs(weight):.1f}]  {note}")
    score = sum(s[1] for s in signals)
    print()
    print(f"COMPOSITE SCORE: {score:+.2f}")
    if score >= 1.5:
        regime = "STRONG ACCUMULATION — fear extreme + alt-season setup"
    elif score >= 0.5:
        regime = "CONSTRUCTIVE — mild contrarian-buy lean"
    elif score <= -1.5:
        regime = "EUPHORIA — likely late-cycle / top zone; bias to take profits, no new chase entries"
    elif score <= -0.5:
        regime = "DISTRIBUTION — mild bearish/cautious lean"
    else:
        regime = "NEUTRAL — no crypto-specific regime tilt"
    print(f"REGIME READ:     {regime}")
    print()
    print("Apply to crypto recommendation logic (AGENTS.md §4 + §5):")
    print("  - F&G is a contrarian signal — extremes can persist; do NOT fade without a price trigger.")
    print("  - BTC dominance > 60 → avoid alts unless idiosyncratic. < 45 → alts viable per playbook.")
    print("  - Combine with `crypto-derivatives snapshot` for positioning (flush risk) and")
    print("    `crypto-unlocks` for the 48h supply-event halt before any new directional entry.")
    return 0


def main():
    load_dotenv_if_present()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pq = sub.add_parser("quote", help="Single-coin snapshot + sentiment + community/dev stats")
    pq.add_argument("--coin", required=True, help="CoinGecko ID (e.g. bitcoin) or common symbol (btc/eth/sol/...)")
    pq.set_defaults(func=cmd_quote)

    ph = sub.add_parser("history", help="OHLC + indicators")
    ph.add_argument("--coin", required=True)
    ph.add_argument("--days", type=int, default=90, help="1, 7, 14, 30, 90, 180, 365, or 'max'")
    ph.add_argument("--indicators", default="rsi,sma20,sma50,sma200,atr14")
    ph.add_argument("--rows", type=int, default=10)
    ph.set_defaults(func=cmd_history)

    pm = sub.add_parser("markets", help="Side-by-side comparison of multiple coins")
    pm.add_argument("--coins", required=True, help="Comma-separated CoinGecko IDs or symbols")
    pm.set_defaults(func=cmd_markets)

    pr = sub.add_parser("regime", help="Composite crypto regime (F&G + BTC dominance + total mcap)")
    pr.set_defaults(func=cmd_regime)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
