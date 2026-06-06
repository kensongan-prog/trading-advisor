#!/usr/bin/env python3
"""
binance_derivs.py — Funding rates, open interest, and long/short ratios from
Binance Futures public API.

Single-purpose CLI invoked by the `crypto-derivatives` skill. No auth required;
Binance Futures market-data endpoints are public. If the API errors, the script
prints an explicit failure — it never falls back to memory.

Usage:
    python3 binance_derivs.py snapshot --symbol BTCUSDT
    python3 binance_derivs.py snapshot --symbol ETHUSDT --period 4h --lookback 8
    python3 binance_derivs.py funding-history --symbol BTCUSDT --limit 20

Symbol convention: Binance perpetual futures symbols. BTCUSDT, ETHUSDT, SOLUSDT,
HYPEUSDT, ONDOUSDT, etc. Accepts plain symbols too (btc → BTCUSDT).
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone


FAPI = "https://fapi.binance.com"

SYMBOL_HINTS = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "bnb": "BNBUSDT",
    "xrp": "XRPUSDT", "ada": "ADAUSDT", "doge": "DOGEUSDT", "ton": "TONUSDT",
    "trx": "TRXUSDT", "avax": "AVAXUSDT", "matic": "MATICUSDT", "dot": "DOTUSDT",
    "link": "LINKUSDT", "uni": "UNIUSDT", "ltc": "LTCUSDT", "atom": "ATOMUSDT",
    "near": "NEARUSDT", "apt": "APTUSDT", "arb": "ARBUSDT", "op": "OPUSDT",
    "ondo": "ONDOUSDT", "hype": "HYPEUSDT", "sui": "SUIUSDT", "ena": "ENAUSDT",
    "pyth": "PYTHUSDT", "strk": "STRKUSDT", "wld": "WLDUSDT", "tia": "TIAUSDT",
}


def normalize_symbol(raw):
    s = raw.strip().upper()
    if s.endswith("USDT") or s.endswith("BUSD") or s.endswith("USDC"):
        return s
    low = s.lower()
    if low in SYMBOL_HINTS:
        return SYMBOL_HINTS[low]
    return s + "USDT"


def get_json(path, params=None):
    url = FAPI + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "trading-advisor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            body = ""
        return None, f"HTTP {e.code}: {e.reason} :: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def annualized_funding_pct(rate_per_8h):
    """Binance funds 3x/day. Annualize for intuition."""
    try:
        r = float(rate_per_8h)
    except (TypeError, ValueError):
        return None
    return r * 3 * 365 * 100  # %


def funding_signal(rate_per_8h):
    """Translate raw funding into a positioning read.

    Thresholds based on common practice:
      > +0.05% (per 8h)  → very crowded long, flush risk
      > +0.02% to +0.05% → crowded long
      -0.02% to +0.02%  → neutral
      < -0.02%          → crowded short (squeeze fuel)
      < -0.05%          → very crowded short
    """
    try:
        r = float(rate_per_8h)
    except (TypeError, ValueError):
        return "—"
    if r > 0.0005:
        return "VERY CROWDED LONG (flush risk)"
    if r > 0.0002:
        return "crowded long"
    if r < -0.0005:
        return "VERY CROWDED SHORT (squeeze fuel)"
    if r < -0.0002:
        return "crowded short"
    return "neutral"


def fmt_ts(ms):
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return str(ms)


def fmt_money(x, places=2):
    try:
        return f"${float(x):,.{places}f}"
    except (TypeError, ValueError):
        return "—"


def cmd_snapshot(args):
    symbol = normalize_symbol(args.symbol)
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 1. Premium index → mark price + last funding rate.
    pi, err = get_json("/fapi/v1/premiumIndex", {"symbol": symbol})
    if err:
        print(f"FETCH FAILED ({symbol} premiumIndex): {err}")
        return 1

    # 2. Open interest (current).
    oi, err = get_json("/fapi/v1/openInterest", {"symbol": symbol})
    if err:
        print(f"warning: openInterest failed: {err}", file=sys.stderr)
        oi = {}

    # 3. Open interest history (USD value).
    oi_hist, err = get_json(
        "/futures/data/openInterestHist",
        {"symbol": symbol, "period": args.period, "limit": args.lookback},
    )
    if err:
        print(f"warning: openInterestHist failed: {err}", file=sys.stderr)
        oi_hist = []

    # 4. Long/short ratio — top traders by account.
    ls_top, err = get_json(
        "/futures/data/topLongShortAccountRatio",
        {"symbol": symbol, "period": args.period, "limit": args.lookback},
    )
    if err:
        print(f"warning: topLongShortAccountRatio failed: {err}", file=sys.stderr)
        ls_top = []

    # 5. Long/short ratio — all accounts (retail signal).
    ls_all, err = get_json(
        "/futures/data/globalLongShortAccountRatio",
        {"symbol": symbol, "period": args.period, "limit": args.lookback},
    )
    if err:
        print(f"warning: globalLongShortAccountRatio failed: {err}", file=sys.stderr)
        ls_all = []

    # 6. Taker buy/sell volume ratio.
    taker, err = get_json(
        "/futures/data/takerlongshortRatio",
        {"symbol": symbol, "period": args.period, "limit": args.lookback},
    )
    if err:
        print(f"warning: takerlongshortRatio failed: {err}", file=sys.stderr)
        taker = []

    rate = pi.get("lastFundingRate")
    next_fund = pi.get("nextFundingTime")

    print(f"CRYPTO DERIVATIVES — {symbol} (Binance Futures)")
    print(f"Source:        Binance fapi.binance.com (public, no auth)")
    print(f"Fetched (UTC): {fetched}")
    print(f"Period:        {args.period}  lookback={args.lookback}")
    print()
    print("FUNDING & MARK")
    print(f"  Mark price:           {pi.get('markPrice', '—')}")
    print(f"  Index price:          {pi.get('indexPrice', '—')}")
    print(f"  Last funding rate:    {rate}  (per 8h)")
    if rate is not None:
        ann = annualized_funding_pct(rate)
        print(f"  Annualized:           {ann:+.2f}%" if ann is not None else "  Annualized: —")
        print(f"  Read:                 {funding_signal(rate)}")
    print(f"  Next funding (UTC):   {fmt_ts(next_fund)}")
    print()

    print("OPEN INTEREST (now)")
    print(f"  OI (contracts):       {oi.get('openInterest', '—')}")
    if oi_hist:
        first = float(oi_hist[0].get("sumOpenInterest", 0) or 0)
        last = float(oi_hist[-1].get("sumOpenInterest", 0) or 0)
        first_usd = float(oi_hist[0].get("sumOpenInterestValue", 0) or 0)
        last_usd = float(oi_hist[-1].get("sumOpenInterestValue", 0) or 0)
        if first > 0:
            delta_pct = (last - first) / first * 100
        else:
            delta_pct = 0
        print(f"  OI value (latest):    {fmt_money(last_usd, 0)}")
        print(f"  OI value ({args.lookback}× {args.period} ago): {fmt_money(first_usd, 0)}")
        print(f"  OI Δ over window:     {delta_pct:+.2f}%")
        tag = ""
        if delta_pct > 10:
            tag = "  ← OI rising fast — fresh positioning"
        elif delta_pct < -10:
            tag = "  ← OI dropping fast — capitulation / position unwind"
        if tag:
            print(f"  {tag.strip()}")
    print()

    if ls_top:
        latest = ls_top[-1]
        avg_ratio = sum(float(r.get("longShortRatio", 0)) for r in ls_top) / len(ls_top)
        print("LONG/SHORT — TOP TRADER ACCOUNTS")
        print(f"  Latest L/S ratio:     {latest.get('longShortRatio')}  "
              f"(long={float(latest.get('longAccount', 0)) * 100:.1f}%  "
              f"short={float(latest.get('shortAccount', 0)) * 100:.1f}%)")
        print(f"  Avg over window:      {avg_ratio:.2f}")

    if ls_all:
        latest = ls_all[-1]
        print("LONG/SHORT — ALL ACCOUNTS (retail)")
        print(f"  Latest L/S ratio:     {latest.get('longShortRatio')}  "
              f"(long={float(latest.get('longAccount', 0)) * 100:.1f}%  "
              f"short={float(latest.get('shortAccount', 0)) * 100:.1f}%)")
        # Smart money divergence: top traders short while retail long is a classic short setup.
        if ls_top:
            top_ratio = float(ls_top[-1].get("longShortRatio", 0))
            ret_ratio = float(latest.get("longShortRatio", 0))
            if top_ratio > 0 and ret_ratio > 0:
                if top_ratio < 1.0 and ret_ratio > 1.5:
                    print("  ← DIVERGENCE: top traders net short, retail net long → bearish positioning read")
                elif top_ratio > 1.5 and ret_ratio < 1.0:
                    print("  ← DIVERGENCE: top traders net long, retail net short → bullish positioning read")
    print()

    if taker:
        latest = taker[-1]
        buy_sell = latest.get("buySellRatio")
        print("TAKER BUY/SELL (aggression read)")
        print(f"  Latest buy/sell:      {buy_sell}")
        if buy_sell is not None:
            try:
                v = float(buy_sell)
                if v > 1.2:
                    print("  ← aggressive buying")
                elif v < 0.8:
                    print("  ← aggressive selling")
            except (TypeError, ValueError):
                pass

    return 0


def cmd_funding_history(args):
    symbol = normalize_symbol(args.symbol)
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data, err = get_json("/fapi/v1/fundingRate", {"symbol": symbol, "limit": str(args.limit)})
    if err:
        print(f"FETCH FAILED: {err}")
        return 1
    if not data:
        print("NO DATA returned.")
        return 1

    print(f"FUNDING RATE HISTORY — {symbol}")
    print(f"Source:        Binance /fapi/v1/fundingRate")
    print(f"Fetched (UTC): {fetched}")
    print(f"Bars:          {len(data)} (most recent first not guaranteed; sorted below)")
    print()
    rows = sorted(data, key=lambda r: r.get("fundingTime", 0))
    rates = [float(r["fundingRate"]) for r in rows]
    print(f"{'time (UTC)':22}  {'rate per 8h':>14}  {'annualized':>12}")
    for r in rows:
        t = fmt_ts(r.get("fundingTime"))
        rate = float(r["fundingRate"])
        print(f"{t:22}  {rate:>14.6f}  {annualized_funding_pct(rate):>+11.2f}%")
    if rates:
        avg = sum(rates) / len(rates)
        print()
        print(f"Average rate over window: {avg:.6f}  ({annualized_funding_pct(avg):+.2f}% annualized)")
        print(f"Current regime read:      {funding_signal(avg)}")
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("snapshot", help="Funding + OI + L/S ratio + taker, single shot")
    ps.add_argument("--symbol", required=True)
    ps.add_argument("--period", default="4h", choices=["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"])
    ps.add_argument("--lookback", type=int, default=12, help="How many bars of history for OI/LS")
    ps.set_defaults(func=cmd_snapshot)

    pf = sub.add_parser("funding-history", help="Historical funding rates for the symbol")
    pf.add_argument("--symbol", required=True)
    pf.add_argument("--limit", type=int, default=30, help="Number of funding intervals (max 1000)")
    pf.set_defaults(func=cmd_funding_history)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
