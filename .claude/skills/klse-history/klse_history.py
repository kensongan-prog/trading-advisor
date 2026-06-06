#!/usr/bin/env python3
"""
klse_history.py — historical OHLCV + indicators for Bursa Malaysia tickers via yfinance.

Designed to be invoked by the `klse-history` skill. Single-purpose CLI; no external
state, no caching, no fabricated data. If yfinance returns empty, this script says so
explicitly — it does NOT fall back to memory or estimates.

Usage:
    python3 klse_history.py --ticker 1155 --period 6mo --interval 1d
    python3 klse_history.py --ticker 1155.KL --period 1y --indicators rsi,sma20,sma50,sma200
    python3 klse_history.py --ticker 5285 --start 2025-01-01 --end 2026-06-01

Output is plain text formatted for an LLM to read and quote into a recommendation.
All numeric values are real, from yfinance, timestamped at fetch time.
"""

import argparse
import sys
import warnings
from datetime import datetime, timezone

# Suppress noisy LibreSSL/urllib3 warning on macOS system Python — it is not actionable.
warnings.filterwarnings("ignore", category=Warning)

try:
    import yfinance as yf
    import pandas as pd
except ImportError as e:
    print(f"ERROR: missing dependency ({e}). Run: pip3 install yfinance pandas", file=sys.stderr)
    sys.exit(2)


def normalize_ticker(raw: str) -> str:
    """Accept '1155', '1155.KL', '1155.kl' → return '1155.KL'."""
    raw = raw.strip().upper()
    if raw.endswith(".KL"):
        return raw
    if raw.isdigit():
        return f"{raw}.KL"
    # Allow named tickers passed through unchanged (yfinance may resolve them).
    return raw


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=window, min_periods=window).mean()


def fetch(ticker, period, interval, start, end):
    t = yf.Ticker(ticker)
    if start or end:
        df = t.history(start=start, end=end, interval=interval, auto_adjust=False)
    else:
        df = t.history(period=period or "6mo", interval=interval, auto_adjust=False)
    return df


def fmt_price(x) -> str:
    try:
        return f"{float(x):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "—"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", required=True, help="Bursa code (1155), or 1155.KL")
    p.add_argument("--period", default=None, help="yfinance period e.g. 5d, 1mo, 6mo, 1y, 5y, max")
    p.add_argument("--start", default=None, help="YYYY-MM-DD (overrides --period)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (overrides --period)")
    p.add_argument("--interval", default="1d", help="1d, 1h, 30m, 15m, 5m, 1m")
    p.add_argument(
        "--indicators",
        default="",
        help="Comma list: rsi, sma20, sma50, sma200, atr14",
    )
    p.add_argument("--rows", type=int, default=10, help="How many recent rows to display")
    args = p.parse_args()

    ticker = normalize_ticker(args.ticker)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        df = fetch(ticker, args.period, args.interval, args.start, args.end)
    except Exception as e:
        print(f"ERROR fetching {ticker} from yfinance: {e}", file=sys.stderr)
        print(f"\nFETCH FAILED — DO NOT USE MEMORY. Tell the user the data source failed.")
        return 1

    if df is None or df.empty:
        print(f"NO DATA returned for {ticker} (period={args.period} start={args.start} end={args.end} interval={args.interval})")
        print("Possible causes: wrong ticker, market closed for the whole window, yfinance outage.")
        print("DO NOT substitute estimates or LLM memory.")
        return 1

    # Compute requested indicators.
    indicators = {s.strip().lower() for s in args.indicators.split(",") if s.strip()}
    close = df["Close"]

    if "rsi" in indicators or "rsi14" in indicators:
        df["RSI14"] = rsi(close, 14)
    if "sma20" in indicators:
        df["SMA20"] = sma(close, 20)
    if "sma50" in indicators:
        df["SMA50"] = sma(close, 50)
    if "sma200" in indicators:
        df["SMA200"] = sma(close, 200)
    if "atr14" in indicators or "atr" in indicators:
        df["ATR14"] = atr(df, 14)

    # Header.
    print(f"KLSE HISTORY — {ticker}")
    print(f"Source:        yfinance (Yahoo Finance backend)")
    print(f"Fetched (UTC): {fetched_at}")
    if args.start or args.end:
        print(f"Window:        {args.start or '...'} → {args.end or '...'}  interval={args.interval}")
    else:
        print(f"Window:        period={args.period or '6mo'}  interval={args.interval}")
    print(f"Rows returned: {len(df)}  (showing last {min(args.rows, len(df))})")
    print()

    # Recent rows.
    display_cols = ["Open", "High", "Low", "Close", "Volume"]
    extra = [c for c in ("RSI14", "SMA20", "SMA50", "SMA200", "ATR14") if c in df.columns]
    show = df[display_cols + extra].tail(args.rows).copy()
    # Round for readability.
    for c in show.columns:
        if c == "Volume":
            show[c] = show[c].astype("Int64", errors="ignore")
        else:
            show[c] = show[c].round(4)
    # Print as plain table.
    print(show.to_string())
    print()

    # Latest-bar summary.
    last = df.iloc[-1]
    last_date = df.index[-1].strftime("%Y-%m-%d %H:%M %Z")
    print("LATEST BAR")
    print(f"  Date:    {last_date}")
    print(f"  OHLC:    {fmt_price(last['Open'])} / {fmt_price(last['High'])} / {fmt_price(last['Low'])} / {fmt_price(last['Close'])}")
    if "Volume" in last:
        try:
            print(f"  Volume:  {int(last['Volume']):,}")
        except (TypeError, ValueError):
            pass

    # Range stats.
    print()
    print("WINDOW STATS")
    print(f"  High:      {fmt_price(df['High'].max())}  on {df['High'].idxmax().strftime('%Y-%m-%d')}")
    print(f"  Low:       {fmt_price(df['Low'].min())}  on {df['Low'].idxmin().strftime('%Y-%m-%d')}")
    first_close = df["Close"].iloc[0]
    last_close = df["Close"].iloc[-1]
    chg = last_close - first_close
    chg_pct = (chg / first_close) * 100 if first_close else 0
    print(f"  Period Δ:  {chg:+.4f} ({chg_pct:+.2f}%)  [{fmt_price(first_close)} → {fmt_price(last_close)}]")

    # Indicator readouts.
    if extra:
        print()
        print("INDICATOR READOUTS (latest)")
        for col in extra:
            val = df[col].iloc[-1]
            tag = ""
            if col == "RSI14" and pd.notna(val):
                if val > 70:
                    tag = "  ← OVERBOUGHT"
                elif val < 30:
                    tag = "  ← OVERSOLD"
            print(f"  {col:7}: {fmt_price(val) if col != 'Volume' else int(val):>10}{tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
