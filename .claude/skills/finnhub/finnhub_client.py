"""Finnhub free-tier REST client.

Used for: bulk historical OHLCV (sector rotation, screener technicals).
Free tier: 60 calls/min, no daily cap.
No bulk endpoint — every symbol is 1 call.

Sign up: https://finnhub.io/register → copy API key from dashboard.
Drop into: .claude/skills/finnhub/.env  →  FINNHUB_API_KEY=...
"""
from __future__ import annotations
import json, os, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_ENV_PATH   = _SCRIPT_DIR / ".env"
BASE_URL    = "https://finnhub.io/api/v1"
PACE_SECONDS = 1.05   # 60 calls/min → 1 call per 1.05s with 5% safety margin
RETRIES_429  = 3


def _load_env():
    if not _ENV_PATH.is_file():
        return
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ: os.environ[k] = v

_load_env()

def api_key():
    return os.environ.get("FINNHUB_API_KEY")

def is_configured():
    return bool(api_key())


def _get(path, params, retries=RETRIES_429):
    key = api_key()
    if not key:
        return None, "FINNHUB_API_KEY not set (drop it into .claude/skills/finnhub/.env)"
    params = dict(params or {})
    params["token"] = key
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read().decode()), None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(2 ** (attempt + 1)); continue
            return None, f"HTTP {e.code}"
        except Exception as e:
            if attempt < retries:
                time.sleep(1); continue
            return None, f"{type(e).__name__}: {e}"
    return None, "retry exhausted"


def stock_candle(symbol, resolution="D", days_back=400):
    """Daily OHLCV for `symbol`. Returns dict with arrays {t, o, h, l, c, v} or error.
    days_back default 400 → enough for SMA200 + buffer.
    Note: Finnhub free tier may have a 1-year cap on `D` resolution."""
    now = int(datetime.now(timezone.utc).timestamp())
    frm = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())
    data, err = _get("/stock/candle", {"symbol": symbol, "resolution": resolution, "from": frm, "to": now})
    if err: return None, err
    if not data or data.get("s") != "ok":
        return None, data.get("s", "no_data") if data else "empty response"
    return data, None


def candle_closes(symbol, days_back=400):
    """Convenience: returns just the list of closes (oldest→newest) or error."""
    data, err = stock_candle(symbol, "D", days_back)
    if err: return None, err
    return data.get("c") or [], None


def quote(symbol):
    """Current quote: c=current, h=high, l=low, o=open, pc=prev close, t=timestamp."""
    return _get("/quote", {"symbol": symbol})


def metric(symbol, kind="all"):
    """Basic ratios. Free tier limited fields. kind ∈ {'price', 'valuation', 'all', ...}."""
    return _get("/stock/metric", {"symbol": symbol, "metric": kind})


def company_news(symbol, days=2):
    """Recent company news. Returns list[{datetime, headline, source, summary, url, category, image, id}].

    `days` is the lookback window. Default 2 = today + yesterday (captures the 24h glyph window
    with a small buffer for timezone slop). Finnhub takes YYYY-MM-DD calendar dates.
    """
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    to  = now.strftime("%Y-%m-%d")
    data, err = _get("/company-news", {"symbol": symbol, "from": frm, "to": to})
    if err: return None, err
    if not isinstance(data, list):
        return None, "unexpected response shape"
    return data, None
