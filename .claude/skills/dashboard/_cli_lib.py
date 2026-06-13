"""
_cli_lib.py — shared helpers for the operator-loop CLIs in this directory
(rel_strength.py, retired_scan.py, setup_queue.py, …).

These three functions were copy-pasted across the CLIs with small variations; the
drift between copies caused several v2.0.x bugs (see notes/learned.md — refresh
TTLs and yfinance handling diverging). Centralising them here makes a fix reach
every caller. Each CLI keeps a thin module-local wrapper that binds its own
path/period, so call sites and public names are unchanged.
"""
import json
import re
from pathlib import Path


def watchlist_us(watchlist_md):
    """US-equity tickers from watchlist.md's '… Equities/ETF' section.
    Uppercased; skips the 'ticker' placeholder bullet. [] if the file is absent."""
    p = Path(watchlist_md)
    if not p.is_file():
        return []
    out, in_us = [], False
    for line in p.read_text().splitlines():
        if line.startswith("## "):
            h = line[3:].lower()
            in_us = ("equities" in h or "etf" in h)
            continue
        if in_us:
            m = re.match(r"\s*-\s*`([^`]+)`", line)
            if m and m.group(1).strip().lower() != "ticker":
                out.append(m.group(1).strip().upper())
    return out


def load_json_cache(path):
    """Read a JSON cache file. None on missing file or malformed JSON."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def batch_closes(tickers, period="4mo"):
    """One batched yfinance download → {ticker: [closes oldest→newest]}.

    Batched (not per-ticker .info) to avoid the sequential-call pattern flagged
    in notes/learned.md. `period` varies by caller (rel-strength 4mo, retired
    scan 10mo). Tickers with no usable history are omitted from the result.
    """
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    df = yf.download(tickers, period=period, interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    out = {}
    # Multi-ticker → columns are a MultiIndex ('Close', TICKER); single → flat
    close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    for t in tickers:
        try:
            series = close[t] if hasattr(close, "columns") and t in close.columns else close
            vals = [float(x) for x in series.dropna().tolist()]
            if vals:
                out[t] = vals
        except Exception:
            continue
    return out
