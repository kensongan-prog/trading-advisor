#!/usr/bin/env python3
"""
us_fundamentals.py — US equity fundamentals and earnings calendar via yfinance.

Single-purpose CLI invoked by the `us-fundamentals` skill. Two subcommands:

    fundamentals   Valuation ratios, profitability, growth, balance-sheet snapshot.
    earnings       Next earnings date, recent earnings history, and 24h-window flag.

Never falls back to LLM memory or fabrication. If yfinance returns nothing, prints
explicit failure and exits 1.

Usage:
    python3 us_fundamentals.py fundamentals --ticker AAPL
    python3 us_fundamentals.py earnings --ticker AAPL
    python3 us_fundamentals.py earnings --ticker AAPL --halt-window-hours 24
"""

import argparse
import sys
import warnings
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore", category=Warning)

try:
    import yfinance as yf
    import pandas as pd
except ImportError as e:
    print(f"ERROR: missing dependency ({e}). Run: pip3 install yfinance pandas", file=sys.stderr)
    sys.exit(2)


def fmt_money(x, places=0):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1e12:
        return f"${v/1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:,.{places}f}"


def fmt_pct(x, places=2):
    try:
        return f"{float(x) * 100:+.{places}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_num(x, places=2):
    try:
        return f"{float(x):.{places}f}"
    except (TypeError, ValueError):
        return "—"


def safe_get(info, key, default=None):
    v = info.get(key)
    return v if v not in (None, "", "N/A") else default


def cmd_fundamentals(args):
    ticker = args.ticker.upper().strip()
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        print(f"FETCH FAILED for {ticker}: {type(e).__name__}: {e}")
        print("DO NOT use LLM memory or web search as a substitute.")
        return 1

    if not info or "symbol" not in info and "shortName" not in info:
        print(f"NO DATA returned for {ticker}. Possible: invalid ticker or yfinance outage.")
        return 1

    name = safe_get(info, "shortName") or safe_get(info, "longName") or ticker
    sector = safe_get(info, "sector", "—")
    industry = safe_get(info, "industry", "—")
    country = safe_get(info, "country", "—")
    exchange = safe_get(info, "exchange", "—")

    print(f"US FUNDAMENTALS — {name} ({ticker})")
    print(f"Source:        yfinance (Yahoo Finance backend)")
    print(f"Fetched (UTC): {fetched}")
    print(f"Exchange:      {exchange}  |  Country: {country}")
    print(f"Sector:        {sector}  |  Industry: {industry}")
    print(f"Website:       {safe_get(info, 'website', '—')}")
    print()

    print("VALUATION (TTM unless noted)")
    print(f"  Market cap:           {fmt_money(safe_get(info, 'marketCap'))}")
    print(f"  Enterprise value:     {fmt_money(safe_get(info, 'enterpriseValue'))}")
    print(f"  Trailing P/E:         {fmt_num(safe_get(info, 'trailingPE'))}")
    print(f"  Forward P/E:          {fmt_num(safe_get(info, 'forwardPE'))}")
    print(f"  PEG (5y expected):    {fmt_num(safe_get(info, 'pegRatio'))}")
    print(f"  Price / sales (TTM):  {fmt_num(safe_get(info, 'priceToSalesTrailing12Months'))}")
    print(f"  Price / book:         {fmt_num(safe_get(info, 'priceToBook'))}")
    print(f"  EV / EBITDA:          {fmt_num(safe_get(info, 'enterpriseToEbitda'))}")
    print(f"  EV / revenue:         {fmt_num(safe_get(info, 'enterpriseToRevenue'))}")
    print()

    print("PROFITABILITY & RETURNS")
    print(f"  Gross margin:         {fmt_pct(safe_get(info, 'grossMargins'))}")
    print(f"  Operating margin:     {fmt_pct(safe_get(info, 'operatingMargins'))}")
    print(f"  Profit margin:        {fmt_pct(safe_get(info, 'profitMargins'))}")
    print(f"  ROE:                  {fmt_pct(safe_get(info, 'returnOnEquity'))}")
    print(f"  ROA:                  {fmt_pct(safe_get(info, 'returnOnAssets'))}")
    print(f"  Free cash flow:       {fmt_money(safe_get(info, 'freeCashflow'))}")
    print(f"  Operating cash flow:  {fmt_money(safe_get(info, 'operatingCashflow'))}")
    print()

    print("GROWTH (YoY)")
    print(f"  Revenue growth:       {fmt_pct(safe_get(info, 'revenueGrowth'))}")
    print(f"  Earnings growth:      {fmt_pct(safe_get(info, 'earningsGrowth'))}")
    print(f"  Earnings Q growth:    {fmt_pct(safe_get(info, 'earningsQuarterlyGrowth'))}")
    print(f"  Revenue Q growth:     {fmt_pct(safe_get(info, 'revenueQuarterlyGrowth'))}")
    print()

    print("BALANCE SHEET")
    print(f"  Total cash:           {fmt_money(safe_get(info, 'totalCash'))}")
    print(f"  Total debt:           {fmt_money(safe_get(info, 'totalDebt'))}")
    print(f"  Debt / equity:        {fmt_num(safe_get(info, 'debtToEquity'))}")
    print(f"  Current ratio:        {fmt_num(safe_get(info, 'currentRatio'))}")
    print(f"  Quick ratio:          {fmt_num(safe_get(info, 'quickRatio'))}")
    print()

    print("DIVIDEND")
    div_yield = safe_get(info, "dividendYield")
    div_rate = safe_get(info, "dividendRate")
    payout = safe_get(info, "payoutRatio")
    # yfinance returns dividendYield as already-percent (e.g. 0.34 = 0.34%), unlike other margin fields.
    print(f"  Dividend yield:       {float(div_yield):.2f}%" if div_yield else "  Dividend yield:       —")
    print(f"  Dividend rate:        ${div_rate}" if div_rate else "  Dividend rate:        —")
    print(f"  Payout ratio:         {fmt_pct(payout)}")
    print()

    print("SHARE INFO")
    print(f"  Shares outstanding:   {safe_get(info, 'sharesOutstanding'):,}" if safe_get(info, 'sharesOutstanding') else "  Shares outstanding:   —")
    print(f"  Float:                {safe_get(info, 'floatShares'):,}" if safe_get(info, 'floatShares') else "  Float:                —")
    print(f"  % short of float:     {fmt_pct(safe_get(info, 'shortPercentOfFloat'))}")
    print(f"  Insider ownership:    {fmt_pct(safe_get(info, 'heldPercentInsiders'))}")
    print(f"  Institutional own:    {fmt_pct(safe_get(info, 'heldPercentInstitutions'))}")
    print(f"  Beta:                 {fmt_num(safe_get(info, 'beta'))}")
    print()

    # Analyst targets if present.
    target_mean = safe_get(info, "targetMeanPrice")
    target_high = safe_get(info, "targetHighPrice")
    target_low = safe_get(info, "targetLowPrice")
    n_analysts = safe_get(info, "numberOfAnalystOpinions")
    rec = safe_get(info, "recommendationKey")
    if any([target_mean, rec]):
        print("ANALYST CONSENSUS")
        print(f"  Recommendation:       {rec or '—'}")
        print(f"  Number of analysts:   {n_analysts or '—'}")
        print(f"  Target mean:          ${target_mean}" if target_mean else "  Target mean: —")
        print(f"  Target range:         ${target_low} – ${target_high}" if (target_low and target_high) else "")
        current = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
        if current and target_mean:
            try:
                upside = (float(target_mean) / float(current) - 1) * 100
                print(f"  Implied upside:       {upside:+.2f}%  (current ${current})")
            except (TypeError, ValueError, ZeroDivisionError):
                pass

    return 0


def cmd_earnings(args):
    ticker = args.ticker.upper().strip()
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    now = datetime.now(timezone.utc)

    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        edates = t.earnings_dates
    except Exception as e:
        print(f"FETCH FAILED for {ticker}: {type(e).__name__}: {e}")
        return 1

    print(f"US EARNINGS — {ticker}")
    print(f"Source:        yfinance (Yahoo Finance backend)")
    print(f"Fetched (UTC): {fetched}")
    print()

    # Calendar: dict or DataFrame. Recent yfinance returns dict.
    next_date = None
    eps_estimate = None
    revenue_estimate = None
    if isinstance(cal, dict) and cal:
        # Most common shape: {'Earnings Date': [Timestamp, ...], 'EPS Estimate': ..., 'Revenue Estimate': ...}
        ed = cal.get("Earnings Date")
        if ed:
            if isinstance(ed, list):
                # Range of dates [start, end]; take first.
                next_date = ed[0]
            else:
                next_date = ed
        eps_estimate = cal.get("Earnings Average") or cal.get("EPS Estimate")
        revenue_estimate = cal.get("Revenue Average") or cal.get("Revenue Estimate")
    elif hasattr(cal, "iloc") and not cal.empty:
        # DataFrame fallback.
        try:
            next_date = cal.iloc[0, 0]
        except Exception:
            pass

    print("NEXT EARNINGS")
    if next_date is None:
        print("  Date:                 NOT REPORTED by yfinance")
        print("  (For high-conviction calls, confirm via the company's IR page.)")
    else:
        # Normalize to datetime.
        if hasattr(next_date, "to_pydatetime"):
            next_dt = next_date.to_pydatetime()
        elif isinstance(next_date, datetime):
            next_dt = next_date
        else:
            next_dt = pd.to_datetime(next_date).to_pydatetime()
        # yfinance dates are timezone-naive; assume UTC for comparison.
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=timezone.utc)
        delta = next_dt - now
        hours_until = delta.total_seconds() / 3600
        print(f"  Date (UTC):           {next_dt.isoformat(timespec='minutes')}")
        print(f"  Hours from now:       {hours_until:+.1f}")
        if eps_estimate is not None:
            print(f"  EPS estimate:         {eps_estimate}")
        if revenue_estimate is not None:
            print(f"  Revenue estimate:     {fmt_money(revenue_estimate)}")
        print()
        print("EVENT-WINDOW STATUS (AGENTS.md §5: 24h pre-earnings halt)")
        if 0 <= hours_until <= args.halt_window_hours:
            print(f"  *** WITHIN {args.halt_window_hours}h HALT WINDOW ***")
            print(f"  Per doctrine: NO new directional exposure on this name.")
            print(f"  Defined-risk options structure required if entering, with event AS thesis.")
        elif hours_until < 0:
            print(f"  Earnings already passed ({-hours_until:.1f}h ago) — check for reaction trade only.")
        else:
            print(f"  Outside halt window ({hours_until:.1f}h > {args.halt_window_hours}h). OK to consider entry, but time-stop the trade pre-earnings.")
    print()

    # Recent earnings history.
    print("RECENT EARNINGS HISTORY (last 8 announced, most recent first)")
    if edates is None or (hasattr(edates, "empty") and edates.empty):
        print("  No earnings history returned.")
    else:
        # edates is a DataFrame indexed by datetime.
        try:
            # Filter to past only and show top 8.
            past = edates[edates.index <= now]
            past = past.sort_index(ascending=False).head(8)
            cols_present = [c for c in ("EPS Estimate", "Reported EPS", "Surprise(%)") if c in past.columns]
            if not cols_present:
                print(past.head(8).to_string())
            else:
                print(f"{'date':25}  {'EPS est':>10}  {'EPS rep':>10}  {'surprise %':>12}")
                for idx, row in past.iterrows():
                    eps_est = row.get("EPS Estimate")
                    eps_rep = row.get("Reported EPS")
                    surp = row.get("Surprise(%)")
                    print(f"{str(idx)[:25]:25}  {fmt_num(eps_est):>10}  {fmt_num(eps_rep):>10}  {fmt_num(surp):>12}")
        except Exception as e:
            print(f"  (history table parse error: {e})")

    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fundamentals", help="Valuation + profitability + growth + balance sheet")
    pf.add_argument("--ticker", required=True)
    pf.set_defaults(func=cmd_fundamentals)

    pe = sub.add_parser("earnings", help="Next earnings date + recent history + halt-window check")
    pe.add_argument("--ticker", required=True)
    pe.add_argument("--halt-window-hours", type=int, default=24,
                    help="Halt window in hours before earnings (AGENTS.md §5 default: 24).")
    pe.set_defaults(func=cmd_earnings)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
