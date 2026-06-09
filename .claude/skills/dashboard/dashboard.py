#!/usr/bin/env python3
"""
dashboard.py — Generate a self-contained HTML trading dashboard.

Reads watchlist.md, journal/*.md, all wired data sources (FRED, yfinance,
CoinGecko, alternative.me, Binance, klsescreener via WebFetch where available)
and renders ONE static HTML file at <project_root>/dashboard.html.

Usage:
    python3 .claude/skills/dashboard/dashboard.py
    python3 .claude/skills/dashboard/dashboard.py --force        # bypass cache
    python3 .claude/skills/dashboard/dashboard.py --no-news      # skip AV news (save budget)
    python3 .claude/skills/dashboard/dashboard.py --open         # open in browser when done

Architecture:
    - Source of truth: watchlist.md + journal/*.md + skill .env files
    - Cache: .claude/cache/dashboard/*.json with per-section TTLs
    - Output: dashboard.html (single self-contained file with embedded CSS/JS)
    - Never falls back to LLM memory: if a source fails, the section shows
      "data unavailable" with timestamp + reason.
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning)

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "dashboard"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_HTML = PROJECT_ROOT / "dashboard.html"
WATCHLIST_MD = PROJECT_ROOT / "watchlist.md"
JOURNAL_DIR = PROJECT_ROOT / "journal"

# ── .env loading (per-skill) ───────────────────────────────────────────────
def load_skill_env(skill_name):
    env_path = SKILLS_DIR / skill_name / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

for skill in ("macro-rates", "us-news", "crypto-coingecko", "finnhub", "twelve-data", "fmp"):
    load_skill_env(skill)

# ── Cache layer ────────────────────────────────────────────────────────────
def cache_get(key, ttl_seconds, force=False):
    if force:
        return None, "forced refresh"
    p = CACHE_DIR / f"{key}.json"
    if not p.is_file():
        return None, "no cache"
    try:
        data = json.loads(p.read_text())
        ts = datetime.fromisoformat(data.get("_fetched_at", "1970-01-01T00:00:00+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > ttl_seconds:
            return None, f"stale ({age/60:.0f}m old)"
        return data, f"cached ({age/60:.0f}m old)"
    except Exception as e:
        return None, f"cache read error: {e}"

def cache_set(key, payload):
    # Stamp in place so callers' returned dict also carries _fetched_at
    payload["_fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p = CACHE_DIR / f"{key}.json"
    p.write_text(json.dumps(payload, default=str))

def _read_cache(key):
    """Read cache without TTL check — used by cooldown fallback paths."""
    p = CACHE_DIR / f"{key}.json"
    if not p.is_file(): return None
    try: return json.loads(p.read_text())
    except Exception: return None

# ── HTTP helpers ───────────────────────────────────────────────────────────
def http_json(url, headers=None, timeout=20, post_body=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "trading-advisor/1.0"})
    if post_body is not None:
        req.data = json.dumps(post_body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.method = "POST"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:200]
        except Exception:
            body = ""
        return None, f"HTTP {e.code}: {e.reason} {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

# ── Watchlist parser ───────────────────────────────────────────────────────
def parse_watchlist():
    """Parse watchlist.md into US / KLSE / Crypto lists with thesis lines.

    Returns dict: {"us": [...], "klse": [...], "crypto": [...]}
    Each entry: {"ticker": "AUPH", "thesis": "..."}
    """
    if not WATCHLIST_MD.is_file():
        return {"us": [], "klse": [], "crypto": []}
    text = WATCHLIST_MD.read_text()

    sections = {"us": "", "klse": "", "crypto": ""}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            h = line[3:].lower()
            if "equities" in h or "etf" in h:
                current = "us"
            elif "klse" in h or "bursa" in h or "malaysia" in h:
                current = "klse"
            elif "crypto" in h:
                current = "crypto"
            else:
                current = None
            continue
        if current and line.strip():
            sections[current] += line + "\n"

    def extract_entries(block, is_klse=False):
        entries = []
        for line in block.splitlines():
            # Pattern 1: `- \`TICKER\` — thesis`
            m = re.match(r"\s*-\s*`([^`]+)`\s*[—\-:]?\s*(.*)", line)
            if m:
                ticker = m.group(1).strip()
                thesis = m.group(2).strip()
                # Skip placeholder bullets
                if ticker.lower() in ("ticker",) or thesis.startswith("_add tickers"):
                    continue
                entries.append({"ticker": ticker, "thesis": thesis})
                continue
            # Pattern 2: bare bullet `- TICKER` without backticks
            m = re.match(r"\s*-\s*([A-Z0-9.]+)\s*$", line)
            if m:
                entries.append({"ticker": m.group(1).strip(), "thesis": ""})
        return entries

    return {
        "us": extract_entries(sections["us"]),
        "klse": extract_entries(sections["klse"], is_klse=True),
        "crypto": extract_entries(sections["crypto"]),
    }

# ── Journal parser ─────────────────────────────────────────────────────────
def parse_journal():
    """Return list of journal entries with status + summary."""
    if not JOURNAL_DIR.is_dir():
        return []
    entries = []
    for p in sorted(JOURNAL_DIR.glob("*.md"), reverse=True):
        if p.name.startswith("_") or p.name.lower() == "readme.md":
            continue
        txt = p.read_text()
        status = "unknown"
        m = re.search(r"\*\*Status:\*\*\s*([^\n]+)", txt)
        if m:
            raw = m.group(1).strip().rstrip(".")
            # Truncate at first sentence boundary or 80 chars
            for sep in [". ", " — ", " - "]:
                if sep in raw:
                    raw = raw.split(sep, 1)[0]
                    break
            status = raw[:80]
        # Pull first line / heading
        title = p.stem
        m = re.search(r"^#\s*(.+)$", txt, re.MULTILINE)
        if m:
            title = m.group(1).strip()
        ticker = ""
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)", p.stem)
        if m:
            ticker = m.group(2)
        entries.append({
            "file": p.name,
            "title": title,
            "ticker": ticker,
            "status": status,
            "path": str(p),
        })
    return entries

# ── Data fetchers ──────────────────────────────────────────────────────────
def fetch_macro_regime(force=False):
    data, age = cache_get("macro_regime", 43200, force)  # 12h — FRED publishes daily/monthly, no need for hourly refresh
    if data:
        return data, age
    try:
        sys.path.insert(0, str(SKILLS_DIR / "macro-rates"))
        import fred as f
    except Exception as e:
        return {"error": f"import fred: {e}"}, "fresh (import failed)"
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return {"error": "FRED_API_KEY not set"}, "fresh"

    def get(sid, n=15):
        obs, _ = f.fred_get(sid, api_key, limit=n)
        return obs or []

    out = {"signals": [], "values": {}}
    t10y2y = get("T10Y2Y", 5)
    if t10y2y:
        v, _ = f.latest_value(t10y2y)
        out["values"]["T10Y2Y"] = v
        if v is not None:
            if v < 0:
                out["signals"].append({"w": -1, "note": f"10y-2y inverted at {v:.2f}%"})
            elif v < 0.3:
                out["signals"].append({"w": -0.5, "note": f"10y-2y flat at {v:.2f}%"})
            else:
                out["signals"].append({"w": +0.5, "note": f"10y-2y positive at {v:.2f}%"})
    dfii10 = get("DFII10", 30)
    if dfii10:
        v, _ = f.latest_value(dfii10)
        out["values"]["DFII10"] = v
        if v is not None:
            if v > 2:
                out["signals"].append({"w": -1, "note": f"10y real yield {v:.2f}% (duration headwind)"})
            elif v < 0:
                out["signals"].append({"w": +1, "note": f"10y real yield {v:.2f}% (inflation-hedge tailwind)"})
            else:
                out["signals"].append({"w": 0, "note": f"10y real yield {v:.2f}%"})
    cpi = get("CPILFESL", 14)
    if cpi:
        yoy = f.yoy_change(cpi)
        if yoy is not None:
            out["values"]["coreCPI_yoy"] = yoy
            if yoy > 4:
                out["signals"].append({"w": -1, "note": f"Core CPI YoY {yoy:.2f}% (above Fed comfort)"})
            elif yoy < 2:
                out["signals"].append({"w": +0.5, "note": f"Core CPI YoY {yoy:.2f}% (below 2% target)"})
            else:
                out["signals"].append({"w": 0, "note": f"Core CPI YoY {yoy:.2f}% (in Fed band)"})
    dxy = get("DTWEXBGS", 30)
    if dxy and len(dxy) >= 22:
        try:
            cur = float(dxy[0]["value"])
            old = float(dxy[21]["value"])
            chg = (cur / old - 1) * 100
            out["values"]["DXY_30d_pct"] = chg
            if chg > 1.5:
                out["signals"].append({"w": -0.5, "note": f"USD +{chg:.2f}% 30d (EM/crypto/gold headwind)"})
            elif chg < -1.5:
                out["signals"].append({"w": +0.5, "note": f"USD {chg:.2f}% 30d (risk-on tailwind)"})
            else:
                out["signals"].append({"w": 0, "note": f"USD {chg:+.2f}% 30d (stable)"})
        except Exception:
            pass
    vix = get("VIXCLS", 5)
    if vix:
        v, _ = f.latest_value(vix)
        out["values"]["VIX"] = v
        if v is not None:
            if v > 25:
                out["signals"].append({"w": -1, "note": f"VIX {v:.1f} (elevated)"})
            elif v < 13:
                out["signals"].append({"w": -0.3, "note": f"VIX {v:.1f} (complacent)"})
            else:
                out["signals"].append({"w": 0, "note": f"VIX {v:.1f} (normal)"})

    # Additional values used in header strip
    for sid in ("DFF", "DGS10", "CPIAUCSL", "PCEPI", "PCEPILFE"):
        obs = get(sid, 14)
        if obs:
            v, _ = f.latest_value(obs)
            out["values"][sid] = v

    score = sum(s["w"] for s in out["signals"])
    out["score"] = score
    if score >= 1.5:    out["regime"] = "RISK-ON tailwind"
    elif score >= 0.5:  out["regime"] = "CONSTRUCTIVE"
    elif score <= -1.5: out["regime"] = "RISK-OFF headwind"
    elif score <= -0.5: out["regime"] = "CAUTIOUS"
    else:               out["regime"] = "NEUTRAL"
    cache_set("macro_regime", out)
    return out, "fresh"


def fetch_crypto_regime(force=False):
    data, age = cache_get("crypto_regime", 21600, force)  # 6h — F&G updates daily, BTC.D moves slowly
    if data:
        return data, age
    out = {"signals": [], "values": {}}

    # Fear & Greed
    fng, err = http_json("https://api.alternative.me/fng/?limit=8")
    if not err and fng and fng.get("data"):
        rows = fng["data"]
        try:
            cur = int(rows[0]["value"])
            label = rows[0].get("value_classification", "?")
            out["values"]["FNG"] = cur
            out["values"]["FNG_label"] = label
            if cur <= 25:
                w, note = +1, f"F&G {cur}/100 ({label}) — contrarian buy zone"
            elif cur <= 45:
                w, note = +0.5, f"F&G {cur}/100 ({label}) — fear"
            elif cur < 55:
                w, note = 0, f"F&G {cur}/100 ({label}) — neutral"
            elif cur < 75:
                w, note = -0.5, f"F&G {cur}/100 ({label}) — greed"
            else:
                w, note = -1, f"F&G {cur}/100 ({label}) — top zone"
            out["signals"].append({"w": w, "note": note})
        except Exception:
            pass

    # CoinGecko /global
    cg_key = os.environ.get("COINGECKO_API_KEY")
    cg_base = "https://pro-api.coingecko.com/api/v3" if cg_key else "https://api.coingecko.com/api/v3"
    headers = {"User-Agent": "trading-advisor/1.0"}
    if cg_key:
        headers["x-cg-pro-api-key"] = cg_key
    g, err = http_json(f"{cg_base}/global", headers=headers)
    if not err and g and "data" in g:
        d = g["data"]
        mcp = d.get("market_cap_percentage") or {}
        btc_d = mcp.get("btc")
        eth_d = mcp.get("eth")
        stable_d = sum(mcp.get(s, 0) or 0 for s in ("usdt", "usdc", "dai", "usde", "fdusd", "tusd"))
        total_mc = (d.get("total_market_cap") or {}).get("usd")
        mc_24h = d.get("market_cap_change_percentage_24h_usd")
        out["values"].update({
            "BTC_D": btc_d, "ETH_D": eth_d, "stable_D": stable_d,
            "total_mcap_usd": total_mc, "mcap_24h_pct": mc_24h,
        })
        if btc_d is not None:
            if btc_d >= 60:
                out["signals"].append({"w": -0.5, "note": f"BTC.D {btc_d:.1f}% (alts pressured)"})
            elif btc_d <= 45:
                out["signals"].append({"w": +0.5, "note": f"BTC.D {btc_d:.1f}% (alt season)"})
            else:
                out["signals"].append({"w": 0, "note": f"BTC.D {btc_d:.1f}% (neutral)"})
        if mc_24h is not None:
            if mc_24h >= 5:
                out["signals"].append({"w": +0.5, "note": f"Total mcap +{mc_24h:.2f}% 24h"})
            elif mc_24h <= -5:
                out["signals"].append({"w": -0.5, "note": f"Total mcap {mc_24h:.2f}% 24h"})
        if stable_d > 0:
            if stable_d >= 8:
                out["signals"].append({"w": +0.3, "note": f"Stable share {stable_d:.1f}% (dry powder)"})
            elif stable_d <= 4:
                out["signals"].append({"w": -0.3, "note": f"Stable share {stable_d:.1f}% (deployed)"})

    score = sum(s["w"] for s in out["signals"])
    out["score"] = score
    if score >= 1.5:    out["regime"] = "STRONG ACCUMULATION"
    elif score >= 0.5:  out["regime"] = "CONSTRUCTIVE"
    elif score <= -1.5: out["regime"] = "EUPHORIA"
    elif score <= -0.5: out["regime"] = "DISTRIBUTION"
    else:               out["regime"] = "NEUTRAL"
    cache_set("crypto_regime", out)
    return out, "fresh"


def fetch_macro_calendar(force=False, window_hours=12):
    schedule_path = SKILLS_DIR / "macro-calendar" / "schedule.json"
    if not schedule_path.is_file():
        return {"events": [], "error": "schedule.json not found"}, "n/a"
    sched = json.loads(schedule_path.read_text())
    now = datetime.now(timezone.utc)
    upcoming = []
    try:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
    except Exception:
        ET = timezone(timedelta(hours=-4))
    for ev in sched.get("events", []):
        try:
            dt = datetime.strptime(f"{ev['date']} {ev.get('time_et','08:30')}", "%Y-%m-%d %H:%M").replace(tzinfo=ET).astimezone(timezone.utc)
        except Exception:
            continue
        if dt < now:
            continue
        hrs = (dt - now).total_seconds() / 3600
        upcoming.append({
            "type": ev["type"],
            "date_iso": dt.isoformat(timespec="minutes"),
            "date_et": dt.astimezone(ET).strftime("%Y-%m-%d (%a) %H:%M ET"),
            "hours_until": hrs,
            "in_halt": 0 <= hrs <= window_hours,
            "note": ev.get("note", ""),
        })
    upcoming.sort(key=lambda x: x["hours_until"])
    return {
        "events": upcoming[:12],
        "verified_through": sched.get("_meta", {}).get("verified_through"),
        "window_hours": window_hours,
    }, "fresh"


# yfinance fetcher (US + KLSE technicals)
def fetch_fx_rate(pair, force=False):
    """Fetch FX rate via yfinance. pair like 'MYRUSD' → returns rate where 1 unit of MYR = rate USD.

    Returns ({pair, rate, _fetched_at, error?}, age_str).
    Cached 30 min.
    """
    cache_key = f"fx_{pair}"
    data, age = cache_get(cache_key, 14400, force)  # 4h — FX moves slowly enough
    if data:
        return data, age
    out = {"pair": pair}
    try:
        import yfinance as yf
    except ImportError:
        out["error"] = "yfinance not installed"
        cache_set(cache_key, out)
        return out, "fresh"
    try:
        sym = f"{pair}=X"
        h = yf.Ticker(sym).history(period="5d").dropna(subset=["Close"])
        if h.empty:
            out["error"] = f"no fx data for {sym}"
        else:
            out["rate"] = float(h["Close"].iloc[-1])
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    cache_set(cache_key, out)
    return out, "fresh"


def fetch_yfinance_ticker(ticker, force=False):
    cache_key = f"yfin_{ticker.replace('.', '_').replace(':', '_')}"
    data, age = cache_get(cache_key, 14400, force)  # 4h TTL — daily bars don't change intraday; user wanting live quote uses the Finnhub quote button
    if data:
        return data, age
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return {"error": "yfinance not installed"}, "fresh"

    out = {"ticker": ticker}
    try:
        y = yf.Ticker(ticker)
        info = y.info or {}
        h = y.history(period="1y")
        if h.empty:
            out["error"] = "no history returned"
            return out, "fresh"
        # Drop rows with NaN Close (partial/closed-market bars yfinance sometimes returns,
        # especially for non-US exchanges like .KL)
        h = h.dropna(subset=["Close"])
        if h.empty:
            out["error"] = "history all NaN after cleaning"
            return out, "fresh"
        last_close = float(h["Close"].iloc[-1])
        prev_close = float(h["Close"].iloc[-2]) if len(h) >= 2 else last_close
        chg_pct = (last_close / prev_close - 1) * 100 if prev_close else 0
        # Capture the actual bar date — yfinance occasionally returns NaN-Close bars for the
        # most recent trading day; we dropna upstream, so this is the last CLEAN close date.
        # Surfacing it lets the dashboard show whether the price is yesterday's or older.
        try:
            price_date = h.index[-1].strftime("%Y-%m-%d")
        except Exception:
            price_date = None

        # E1: if yfinance's last clean close is older than the expected last trading day
        # (typical when YF returns NaN-Close for today's bar), try Twelve Data as fallback
        # for a SINGLE call to get the fresher daily close. This only fires for non-KLSE
        # tickers (TD free tier doesn't cover .KL reliably) and only when stale.
        try:
            if price_date and not ticker.endswith(".KL"):
                expected = _last_us_trading_day()
                if price_date < expected:
                    sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "skills" / "twelve-data"))
                    try:
                        import twelve_data_client as _td
                        if _td.is_configured():
                            td_closes, td_err = _td.candle_closes(ticker, outputsize=3)
                            if not td_err and td_closes and len(td_closes) >= 2:
                                td_last = float(td_closes[-1])
                                td_prev = float(td_closes[-2])
                                if abs(td_last - last_close) / max(last_close, 1e-9) > 0.002:  # >0.2% delta means fresher data
                                    last_close = td_last
                                    chg_pct = (td_last / td_prev - 1) * 100 if td_prev else 0
                                    price_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                                    out["_td_fallback_used"] = True
                    except Exception:
                        pass
        except Exception:
            pass

        # RSI(14)
        d = h["Close"].diff()
        g = d.clip(lower=0); l = -d.clip(upper=0)
        ag = g.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        al = l.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        rsi_series = 100 - 100/(1 + ag/al)
        rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else None

        sma20_series = h["Close"].rolling(20).mean()
        sma50_series = h["Close"].rolling(50).mean()
        sma20 = float(sma20_series.iloc[-1]) if len(h) >= 20 else None
        sma50 = float(sma50_series.iloc[-1]) if len(h) >= 50 else None
        sma200 = float(h["Close"].rolling(200).mean().iloc[-1]) if len(h) >= 200 else None

        # SMA50 slope (today vs 5 trading days ago) — rising = healthy trend
        sma50_5d_ago = None
        sma50_slope_pct = None
        if len(h) >= 55:
            try:
                sma50_5d_ago = float(sma50_series.iloc[-6])
                if sma50_5d_ago:
                    sma50_slope_pct = (sma50 / sma50_5d_ago - 1) * 100
            except Exception:
                pass

        # Volume profile — recent 5d avg vs trailing 30d avg
        avg_vol_30d = None
        recent_vol_5d = None
        vol_ratio = None
        if len(h) >= 30:
            try:
                avg_vol_30d = float(h["Volume"].tail(30).mean())
                recent_vol_5d = float(h["Volume"].tail(5).mean())
                if avg_vol_30d > 0:
                    vol_ratio = recent_vol_5d / avg_vol_30d
            except Exception:
                pass

        # ATR(14)
        try:
            tr = pd.concat([
                (h["High"] - h["Low"]),
                (h["High"] - h["Close"].shift(1)).abs(),
                (h["Low"] - h["Close"].shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None
        except Exception:
            atr = None

        # Next earnings
        next_earnings = None
        try:
            cal = y.calendar or {}
            ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if isinstance(ed, list) and ed:
                ed = ed[0]
            if ed:
                if hasattr(ed, "isoformat"):
                    next_earnings = ed.isoformat()[:10]
                else:
                    next_earnings = str(ed)[:10]
        except Exception:
            pass

        out.update({
            "name": info.get("shortName") or info.get("longName") or ticker,
            "price": last_close,
            "price_date": price_date,
            "change_pct": chg_pct,
            "rsi14": rsi,
            "sma20": sma20,
            "sma50": sma50,
            "sma200": sma200,
            "sma50_slope_pct": sma50_slope_pct,
            "avg_vol_30d": avg_vol_30d,
            "recent_vol_5d": recent_vol_5d,
            "vol_ratio": vol_ratio,
            "atr14": atr,
            "vs_sma50_pct": ((last_close / sma50 - 1) * 100) if sma50 else None,
            "vs_sma200_pct": ((last_close / sma200 - 1) * 100) if sma200 else None,
            "next_earnings": next_earnings,
            "sector": info.get("sector"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency", "USD"),
            "trailing_pe": info.get("trailingPE"),
        })
    except Exception as e:
        out["error"] = f"yfinance error: {type(e).__name__}: {e}"
    cache_set(cache_key, out)
    return out, "fresh"


# CoinGecko batch markets
SYMBOL_MAP = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "binancecoin",
    "xrp": "ripple", "ada": "cardano", "doge": "dogecoin", "hbar": "hedera-hashgraph",
    "ondo": "ondo-finance", "hype": "hyperliquid", "ena": "ethena",
}

# Resolution cache (populated by wl.py on add) — preferred source for newly-added alts
# so we don't need to keep updating SYMBOL_MAP / CRYPTO_TO_BINANCE by hand.
RESOLUTIONS_DIR = PROJECT_ROOT / ".claude" / "cache" / "watchlist_resolutions"
SENTIMENT_DIR = PROJECT_ROOT / ".claude" / "cache" / "sentiment"

_SENTIMENT_CACHE_LOADED = None

def _bulk_load_sentiment():
    """Load all per-ticker sentiment composites in one directory scan. Mirrors the
    resolution-cache pattern. Returns dict keyed by uppercase ticker."""
    global _SENTIMENT_CACHE_LOADED
    out = {}
    if SENTIMENT_DIR.is_dir():
        for p in SENTIMENT_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                key = (data.get("ticker") or p.stem).upper()
                out[key] = data
            except Exception:
                continue
    _SENTIMENT_CACHE_LOADED = out
    return out


def load_sentiment(ticker_upper):
    global _SENTIMENT_CACHE_LOADED
    if _SENTIMENT_CACHE_LOADED is None:
        _bulk_load_sentiment()
    return _SENTIMENT_CACHE_LOADED.get(ticker_upper)


POLYMARKET_CACHE_FILE = PROJECT_ROOT / ".claude" / "cache" / "polymarket" / "events.json"

def load_polymarket():
    """Load the Polymarket events cache. Returns dict or None."""
    if not POLYMARKET_CACHE_FILE.exists():
        return None
    try:
        return json.loads(POLYMARKET_CACHE_FILE.read_text())
    except Exception:
        return None
_RESOLUTION_CACHE_LOADED = None  # None = not bulk-loaded yet; dict once loaded

def _bulk_load_resolutions():
    """S2 optimization: load ALL resolution JSONs in one directory scan rather than
    one file-read per ticker. Saves ~200ms per dashboard build with 25+ watchlist names."""
    global _RESOLUTION_CACHE_LOADED
    out = {}
    if RESOLUTIONS_DIR.is_dir():
        for p in RESOLUTIONS_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                # Key is stored ticker symbol (uppercase); also accept derived from filename
                key = (data.get("ticker") or p.stem.replace("_", ".")).upper()
                out[key] = data
            except Exception:
                continue
    _RESOLUTION_CACHE_LOADED = out
    return out

def _load_resolution(ticker_upper):
    global _RESOLUTION_CACHE_LOADED
    if _RESOLUTION_CACHE_LOADED is None:
        _bulk_load_resolutions()
    return _RESOLUTION_CACHE_LOADED.get(ticker_upper)

def normalize_coin(s):
    """Resolve ticker → CoinGecko ID. Order:
       1. Hardcoded SYMBOL_MAP (fast path for majors)
       2. wl.py-populated resolution cache (auto-discovered alts)
       3. Lowercase ticker as last resort (works if symbol == cg_id)"""
    s_low = s.strip().lower()
    if s_low in SYMBOL_MAP:
        return SYMBOL_MAP[s_low]
    res = _load_resolution(s.strip().upper())
    if res and res.get("cg_id"):
        return res["cg_id"]
    return s_low

_CG_COOLDOWN_FILE = CACHE_DIR / ".coingecko_cooldown_until"
_CG_COOLDOWN_MINUTES = 30

def _cg_in_cooldown():
    if not _CG_COOLDOWN_FILE.is_file(): return False
    try:
        until = datetime.fromisoformat(_CG_COOLDOWN_FILE.read_text().strip())
        return datetime.now(timezone.utc) < until
    except Exception:
        return False

def _cg_set_cooldown(minutes=_CG_COOLDOWN_MINUTES):
    from datetime import timedelta
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    _CG_COOLDOWN_FILE.write_text(until.isoformat(timespec="seconds"))

def _cg_clear_cooldown():
    if _CG_COOLDOWN_FILE.is_file():
        try: _CG_COOLDOWN_FILE.unlink()
        except Exception: pass

def fetch_crypto_markets(coins, force=False):
    """Batch fetch markets for list of crypto symbols."""
    ids = sorted({normalize_coin(c) for c in coins})
    key = "crypto_markets_" + "_".join(ids)[:80]
    data, age = cache_get(key, 3600, force)  # 1h TTL — crypto moves but dashboard isn't watched live
    if data:
        return data, age
    # CoinGecko cooldown short-circuit — if recently 429'd, return last good cache (even if stale)
    if _cg_in_cooldown() and not force:
        cached = _read_cache(key)
        if cached:
            cached["_stale"] = True
            cached["_stale_reason"] = "CoinGecko cooldown active"
            return cached, "stale"
    cg_key = os.environ.get("COINGECKO_API_KEY")
    base = "https://pro-api.coingecko.com/api/v3" if cg_key else "https://api.coingecko.com/api/v3"
    headers = {"User-Agent": "trading-advisor/1.0"}
    if cg_key:
        headers["x-cg-pro-api-key"] = cg_key
    params = {
        "vs_currency": "usd",
        "ids": ",".join(ids),
        "order": "market_cap_desc",
        "per_page": "250",
        "page": "1",
        "price_change_percentage": "24h,7d,30d",
    }
    url = f"{base}/coins/markets?{urllib.parse.urlencode(params)}"
    raw, err = http_json(url, headers=headers)
    if err:
        # If 429 (CG rate limit), trip cooldown and fall back to stale cache
        if "429" in str(err):
            _cg_set_cooldown()
            cached = _read_cache(key)
            if cached:
                cached["_stale"] = True
                cached["_stale_reason"] = f"CoinGecko 429; {_CG_COOLDOWN_MINUTES}min cooldown set"
                return cached, "stale"
        return {"error": err, "rows": []}, "fresh"
    _cg_clear_cooldown()
    rows = []
    by_id = {r.get("id"): r for r in raw} if isinstance(raw, list) else {}
    for cid in ids:
        r = by_id.get(cid) or {}
        rows.append({
            "id": cid,
            "symbol": (r.get("symbol") or cid)[:8].upper(),
            "name": r.get("name") or cid,
            "price": r.get("current_price"),
            "chg_24h": r.get("price_change_percentage_24h_in_currency"),
            "chg_7d": r.get("price_change_percentage_7d_in_currency"),
            "chg_30d": r.get("price_change_percentage_30d_in_currency"),
            "market_cap": r.get("market_cap"),
            "volume": r.get("total_volume"),
        })
    out = {"rows": rows}
    cache_set(key, out)
    return out, "fresh"


# Binance funding for crypto rows
def fetch_binance_funding(symbol_usdt, force=False):
    key = f"binance_funding_{symbol_usdt}"
    data, age = cache_get(key, 7200, force)  # 2h TTL — funding updates every 8h, 30min was excessive
    if data:
        return data, age
    url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol_usdt}"
    raw, err = http_json(url)
    if err:
        out = {"error": err}
    else:
        out = {
            "symbol": symbol_usdt,
            "mark": raw.get("markPrice"),
            "last_funding": raw.get("lastFundingRate"),
            "next_funding_ms": raw.get("nextFundingTime"),
        }
        try:
            rate = float(raw.get("lastFundingRate", 0))
            out["annualized_pct"] = rate * 3 * 365 * 100
        except Exception:
            out["annualized_pct"] = None
    cache_set(key, out)
    return out, "fresh"


# Crypto daily klines + indicators (Binance public spot API — no key)
CRYPTO_TO_BINANCE = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "bnb": "BNBUSDT",
    "xrp": "XRPUSDT", "hbar": "HBARUSDT", "ada": "ADAUSDT", "doge": "DOGEUSDT",
    "ondo": "ONDOUSDT", "ena": "ENAUSDT",
    # HYPE: not on Binance spot — uses CoinGecko fallback
    "hype": None,
}

# CoinGecko OHLC fallback for coins absent from Binance spot.
# CoinGecko returns [t,o,h,l,c] only (no volume) so vol_ratio will be None for these.
CRYPTO_COINGECKO_FALLBACK = {
    "hype": "hyperliquid",
}

def _compute_indicators_from_ohlcv(rows):
    """rows = list of dicts {open,high,low,close,volume?} oldest→newest. Returns indicator dict."""
    import pandas as pd
    df = pd.DataFrame(rows)
    if df.empty or "close" not in df:
        return {"error": "no rows"}
    h = df.rename(columns={"close":"Close","high":"High","low":"Low","open":"Open"})
    if "volume" in df.columns:
        h = h.rename(columns={"volume":"Volume"})
    last = float(h["Close"].iloc[-1])
    prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else last
    chg  = (last/prev - 1)*100 if prev else 0
    d = h["Close"].diff()
    g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = l.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi_s = 100 - 100/(1 + ag/al)
    rsi = float(rsi_s.iloc[-1]) if not rsi_s.empty else None
    s20s = h["Close"].rolling(20).mean()
    s50s = h["Close"].rolling(50).mean()
    s20 = float(s20s.iloc[-1]) if len(h) >= 20 else None
    s50 = float(s50s.iloc[-1]) if len(h) >= 50 else None
    s200 = float(h["Close"].rolling(200).mean().iloc[-1]) if len(h) >= 200 else None
    slope = None
    if len(h) >= 55 and s50:
        try:
            s50_5 = float(s50s.iloc[-6])
            if s50_5: slope = (s50/s50_5 - 1)*100
        except Exception: pass
    vol_ratio = None
    if "Volume" in h.columns and len(h) >= 30:
        try:
            a30 = float(h["Volume"].tail(30).mean()); r5 = float(h["Volume"].tail(5).mean())
            if a30 > 0: vol_ratio = r5/a30
        except Exception: pass
    try:
        tr = pd.concat([
            h["High"] - h["Low"],
            (h["High"] - h["Close"].shift(1)).abs(),
            (h["Low"]  - h["Close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None
    except Exception:
        atr = None
    return {
        "price": last, "change_pct": chg,
        "rsi14": rsi, "sma20": s20, "sma50": s50, "sma200": s200,
        "sma50_slope_pct": slope, "vol_ratio": vol_ratio, "atr14": atr,
        "atr_pct": (atr/last*100) if (atr and last) else None,
    }

def _fetch_coingecko_ohlc(cg_id):
    """CoinGecko free OHLC endpoint: 365 days of 4hr or daily candles depending on range.
    Returns list of [open,high,low,close] rows in chronological order."""
    cg_key = os.environ.get("COINGECKO_API_KEY")
    base = "https://pro-api.coingecko.com/api/v3" if cg_key else "https://api.coingecko.com/api/v3"
    headers = {"User-Agent": "trading-advisor/1.0"}
    if cg_key: headers["x-cg-pro-api-key"] = cg_key
    url = f"{base}/coins/{cg_id}/ohlc?vs_currency=usd&days=365"
    raw, err = http_json(url, headers=headers)
    if err: return None, err
    if not isinstance(raw, list) or not raw: return None, "empty ohlc"
    # raw rows: [timestamp_ms, open, high, low, close]
    return [{"open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in raw], None

def fetch_crypto_indicators(coin, force=False):
    coin_l = coin.lower(); coin_u = coin.upper()
    # 1. Try hardcoded maps first (majors)
    sym = CRYPTO_TO_BINANCE.get(coin_l)
    cg_id = CRYPTO_COINGECKO_FALLBACK.get(coin_l)
    # 2. Fall back to wl.py-populated resolution cache (newly-added alts)
    if sym is None and cg_id is None:
        res = _load_resolution(coin_u)
        if res:
            sym = res.get("binance_pair")     # may be None if not on Binance spot
            if not sym:
                cg_id = res.get("cg_id")      # use CoinGecko OHLC fallback
    if sym:
        key = f"crypto_kline_{sym}"
        source = "binance"
    elif cg_id:
        key = f"crypto_cg_ohlc_{cg_id}"
        source = "coingecko"
    else:
        return {"error": f"no data source mapped for {coin_u} — run `python3 .claude/skills/watchlist/wl.py resolve` to backfill", "coin": coin_u}, "fresh"

    data, age = cache_get(key, 21600, force)  # 6h TTL — daily candles don't change intraday
    if data:
        return data, age

    try:
        if source == "binance":
            url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1d&limit=250"
            raw, err = http_json(url)
            if err:
                out = {"error": err, "symbol": sym, "coin": coin.upper()}
                cache_set(key, out); return out, "fresh"
            if not isinstance(raw, list) or not raw:
                out = {"error": "empty klines", "symbol": sym, "coin": coin.upper()}
                cache_set(key, out); return out, "fresh"
            rows = [{"open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
                     "close": float(r[4]), "volume": float(r[5])} for r in raw]
            out = _compute_indicators_from_ohlcv(rows)
            out["symbol"] = sym
        else:  # coingecko
            rows, err = _fetch_coingecko_ohlc(cg_id)
            if err:
                out = {"error": err, "cg_id": cg_id, "coin": coin.upper()}
                cache_set(key, out); return out, "fresh"
            out = _compute_indicators_from_ohlcv(rows)
            out["symbol"] = cg_id
            out["data_source"] = "coingecko"  # marker — no volume data
        out["coin"] = coin.upper()
    except Exception as e:
        out = {"error": f"compute error: {type(e).__name__}: {e}", "coin": coin.upper()}
    cache_set(key, out)
    return out, "fresh"


# ── Status determiners ────────────────────────────────────────────────────
def us_status(t, macro_events=None):
    """Return (badge_emoji, status_label, reason) for a US ticker dict.

    Full P1 playbook conditions checked here:
      1. Trend filter: price > SMA50 > SMA200
      2. SMA50 direction: rising (or at worst flat)
      3. Pullback shape: price near SMA20 (within ±3%) — proxies for "tag of 20-EMA"
      4. RSI(14) in 35-50 (cooled but not broken)
      5. No violent day (|today change| ≤ 5%)
      6. Volume on pullback ≤ average (vol_ratio ≤ ~1.2)
      7. No earnings within 7 trading days (~10 calendar days)
      8. No FOMC/CPI/NFP/PCE within 3 trading days (~72h)
    All eight must hold for 🟢 P1_READY. Otherwise downgrade with reason.
    """
    if t.get("error"):
        return ("❓", "DATA", t["error"][:50])
    p = t.get("price")
    s20 = t.get("sma20"); s50 = t.get("sma50"); s200 = t.get("sma200")
    rsi = t.get("rsi14")
    ch_today = t.get("change_pct")
    sma50_slope = t.get("sma50_slope_pct")
    vol_ratio = t.get("vol_ratio")
    next_earn = t.get("next_earnings")

    if t["ticker"] == "SPY":
        return ("⚪", "CONTEXT", "market regime gauge only")
    if p is None or s50 is None:
        return ("❓", "DATA", "insufficient bars")
    if s200 is None:
        return ("🟡", "NEW", "no SMA200 (recent IPO) — P1 cannot apply cleanly")

    # Gate 1: P1 trend filter
    if not (p > s50 > s200):
        if p < s50 < s200:
            return ("🔴", "DOWNTREND", f"price < SMA50 < SMA200 (trend filter fails)")
        if p < s50:
            return ("🔴", "BELOW50", f"price ${p:.2f} < SMA50 ${s50:.2f}")
        if s50 < s200:
            return ("🔴", "NO_GOLDEN_CROSS", f"SMA50 ${s50:.2f} < SMA200 ${s200:.2f}")
        return ("🔴", "TREND_FAIL", "P1 trend filter fails")

    # Gate 5: violent today = wait
    if ch_today is not None and abs(ch_today) > 5:
        direction = "drop" if ch_today < 0 else "rip"
        return ("🟡", "VIOLENT", f"today {ch_today:+.1f}% {direction} — wait for stabilization")

    # Gate 4: RSI extremes
    if rsi is None:
        return ("🟡", "WATCH", "RSI unavailable")
    if rsi > 70:
        return ("🔴", "OVERBOUGHT", f"RSI {rsi:.1f} > 70 — do not chase")
    if rsi < 30:
        return ("🟡", "OVERSOLD", f"RSI {rsi:.1f} — wait for trigger confirmation")

    # Gate 7: earnings proximity (~7 trading days = 10 cal days)
    if next_earn:
        try:
            ed = datetime.fromisoformat(next_earn).replace(tzinfo=timezone.utc)
            cal_days = (ed - datetime.now(timezone.utc)).days
            if 0 <= cal_days <= 10:
                return ("🟡", "NEAR_EARNINGS", f"earnings in {cal_days}d — inside 7 trading-day pre-window")
        except Exception:
            pass

    # Gate 8: macro event proximity (3 trading days ~ 72h)
    if macro_events:
        for ev in macro_events:
            hrs = ev.get("hours_until", 99999)
            if 0 <= hrs <= 72:
                return ("🟡", f"NEAR_{ev['type']}", f"{ev['type']} in {hrs:.0f}h — inside 3-day pre-event window")

    # Gate 2: SMA50 direction (must be rising or at worst flat)
    if sma50_slope is not None and sma50_slope < -0.5:
        return ("🟡", "SMA50_FALLING", f"trend filter OK but SMA50 falling ({sma50_slope:+.2f}% / 5d)")

    # Gate 3: pullback shape via SMA20 proximity
    vs_s20 = (p / s20 - 1) * 100 if s20 is not None else None

    # Gate 6: volume profile
    vol_caveat = ""
    if vol_ratio is not None:
        if vol_ratio > 1.3:
            return ("🟡", "HEAVY_VOLUME", f"recent 5d volume {vol_ratio:.1f}× the 30d avg — distribution risk, not healthy pullback")
        elif vol_ratio > 1.1:
            vol_caveat = f" (vol elevated {vol_ratio:.2f}×)"

    # P1_READY requires all gates pass and RSI in 35-50 entry band
    if 35 <= rsi <= 50:
        if vs_s20 is None:
            return ("🟢", "P1_READY", f"trend OK + RSI {rsi:.1f}; SMA20 unavailable for shape check{vol_caveat}")
        if -3 <= vs_s20 <= 3:
            return ("🟢", "P1_READY", f"trend OK + SMA50 rising + RSI {rsi:.1f} + tag of SMA20 ({vs_s20:+.1f}%) + vol healthy{vol_caveat}")
        if vs_s20 > 10:
            return ("🟡", "EXTENDED", f"RSI {rsi:.1f} in band but price +{vs_s20:.1f}% above SMA20 — no pullback yet")
        if vs_s20 > 3:
            return ("🟡", "ABOVE_SMA20", f"RSI {rsi:.1f} OK but {vs_s20:+.1f}% above SMA20 — wait for closer tag")
        if vs_s20 < -5:
            return ("🟡", "BROKEN_SMA20", f"RSI {rsi:.1f} cooling but {vs_s20:+.1f}% below SMA20 — wait for stabilization")
        return ("🟡", "WATCH", f"RSI {rsi:.1f}, vs SMA20 {vs_s20:+.1f}% — borderline shape")

    # RSI 50-70 zone — extended but not overbought
    if rsi > 60:
        return ("🟡", "EXTENDED", f"RSI {rsi:.1f} — wait for pullback into 35-50 zone")
    return ("🟡", "WATCH", f"trend OK; RSI {rsi:.1f} above P1 entry band (35-50)")

# ── Status tooltips ───────────────────────────────────────────────────────
# Each entry: a concise (what it means) + (recommended action). Surfaced as
# native HTML `title` attribute on the badge spans → renders on hover.
STATUS_TOOLTIPS = {
    # — neutral / data states —
    "DATA":              "Insufficient market data to evaluate — yfinance/CoinGecko returned an error or no history. Wait and refresh; verify the symbol if it persists.",
    "CONTEXT":           "Watchlist context-only (not a trade candidate). Used for regime gauges like SPY. Action: read for market context, do not size as a position.",
    "NEW":               "Recently listed — no SMA200 yet, so the Phase 1 trend filter (price > SMA50 > SMA200) cannot be evaluated cleanly. Action: hold off until ~200 trading days of price history exist; classify with raw bias only.",
    "WATCH":             "Trend OK but no clean P1 setup right now — RSI outside the 35-50 entry band or shape borderline. Action: keep on the list, wait for a pullback into the entry zone.",

    # — trend failures (P1 trend filter gate) —
    "DOWNTREND":         "Full downtrend: price < SMA50 < SMA200. P1 trend filter fails. Action: NO-TRADE for spot longs; wait for SMA50 reclaim AND golden cross before re-evaluating.",
    "BELOW50":           "Price has lost SMA50. Trend filter fails. Action: NO-TRADE long; wait for a daily close back above SMA50 + bullish structure.",
    "NO_GOLDEN_CROSS":   "SMA50 still below SMA200 (no golden cross). Phase 1 requires SMA50 > SMA200. Action: NO-TRADE long; needs SMA50 to cross above SMA200 first.",
    "TREND_FAIL":        "Generic trend-filter failure (price/SMA50/SMA200 ordering wrong). Action: NO-TRADE long until the P1 ordering holds.",

    # — price-action warnings on a trend-passing name —
    "VIOLENT":           "Price moved >5% today. Too noisy to enter even if other gates pass. Action: WAIT — let the bar close and stabilize before re-evaluating tomorrow.",
    "SMA50_FALLING":     "Trend filter OK but the SMA50 is rolling over (slope <-0.5%/5d). Trend health is deteriorating. Action: tighten or skip new entries; existing positions should consider trailing stops.",
    "HEAVY_VOLUME":      "Recent 5-day volume is >1.3× the 30-day average on a pullback. That's distribution (institutional selling), not a healthy reset. Action: NO-TRADE long; wait for volume to normalize.",

    # — RSI extremes —
    "OVERBOUGHT":        "RSI(14) > 70. Chasing here pays bad R:R and usually mean-reverts. Action: NO-TRADE long; wait for RSI to cool back to the 35-50 zone.",
    "OVERSOLD":          "RSI(14) < 30. Often precedes a bounce but can stay oversold for weeks. Action: WAIT for a reversal trigger (higher low + RSI ticking back above 30) before entering.",
    "EXTENDED":          "Price extended above SMA20 or RSI in the 60-70 zone — pullback hasn't happened yet. Action: WAIT for a clean tag of SMA20 with RSI in 35-50.",

    # — shape / pullback details —
    "ABOVE_SMA20":       "RSI is in the entry band but price is >3% above SMA20 — not yet a clean tag. Action: WAIT a few days for price to mean-revert closer to SMA20.",
    "BROKEN_SMA20":      "Price is >5% below SMA20 — structure looks broken even though longer-trend filter holds. Action: WAIT for stabilization (basing pattern or higher low) before entering.",

    # — event-window halts —
    "NEAR_EARNINGS":     "Earnings within 7 trading days. Doctrine §5 forbids new directional entries through binary events. Action: NO new exposure until 24h after the print.",
    "NEAR_FOMC":         "FOMC decision within 3 trading days (~72h). Doctrine §5 12h halt. Action: NO new US-directional entries; wait for the print to land.",
    "NEAR_CPI":          "CPI release within 3 trading days. Doctrine §5 12h halt. Action: NO new US-directional entries; wait for the print.",
    "NEAR_NFP":          "Non-Farm Payrolls within 3 trading days. Doctrine §5 12h halt. Action: NO new US-directional entries; wait for the print.",
    "NEAR_PCE":          "PCE release within 3 trading days. Doctrine §5 12h halt. Action: NO new US-directional entries; wait for the print.",

    # — ready-to-trade —
    "P1_READY":          "All 8 Phase 1 gates pass: trend OK, SMA50 rising, RSI in 35-50, clean SMA20 tag, healthy volume, no earnings/macro halt. Action: this is a valid P1 entry candidate — run the Risk Simulator, size per doctrine, write a prospectus.",

    # — crypto bias reads (no formal P1 for crypto spot in Phase 1) —
    "DEEP DRAWDOWN":     "Down >20% over 30 days. Often near a capitulation low but can extend further. Action: WAIT for stabilization signs (higher low, RSI divergence); size SMALL if entering.",
    "PULLBACK":          "Down 10-20% over 30 days — healthy correction in an uptrend or early-stage downtrend. Action: WAIT for a structural reversal trigger before sizing.",
    # "EXTENDED" and "WATCH" already defined above and reuse cleanly for crypto.
}

# ── Grid-row thesis synthesis (powers the expandable details panels) ───────
# Each market produces a list of HTML <p> blocks explaining: current setup,
# what the status means, the gate breakdown, action to take, and key meta.

def _gate_html(label, ok, why):
    icon = "✓" if ok else "✗"
    cls  = "green" if ok else "red"
    return f'<div class="gate-line"><span class="{cls}">{icon}</span> <b>{html.escape(label)}</b> — {html.escape(why)}</div>'

def evaluate_us_p1_gates(t, macro_events=None):
    """Return list[(label, ok, why)] for the 8 P1 technical gates — mirrors us_status() logic."""
    p, s20, s50, s200 = t.get("price"), t.get("sma20"), t.get("sma50"), t.get("sma200")
    rsi = t.get("rsi14"); ch = t.get("change_pct"); slope = t.get("sma50_slope_pct")
    vol_ratio = t.get("vol_ratio"); next_earn = t.get("next_earnings")
    out = []
    # 1. Trend filter
    if p is None or s50 is None or s200 is None:
        out.append(("Trend filter", False, "insufficient bars / no SMA200"))
    elif p > s50 > s200:
        out.append(("Trend filter", True, f"price ${p:.2f} > SMA50 ${s50:.2f} > SMA200 ${s200:.2f}"))
    else:
        out.append(("Trend filter", False, f"price ${p:.2f} vs SMA50 ${s50:.2f} vs SMA200 ${s200:.2f}"))
    # 2. SMA50 direction
    if slope is None:
        out.append(("SMA50 direction", False, "no slope data"))
    elif slope >= -0.5:
        out.append(("SMA50 direction", True, f"slope {slope:+.2f}%/5d (rising/flat)"))
    else:
        out.append(("SMA50 direction", False, f"slope {slope:+.2f}%/5d (falling)"))
    # 3. RSI zone (P1 entry band 35-50)
    if rsi is None:
        out.append(("RSI zone", False, "no RSI"))
    elif 35 <= rsi <= 50:
        out.append(("RSI zone", True, f"RSI {rsi:.1f} in P1 entry band 35-50"))
    elif rsi > 70:
        out.append(("RSI zone", False, f"RSI {rsi:.1f} > 70 (overbought)"))
    elif rsi < 30:
        out.append(("RSI zone", False, f"RSI {rsi:.1f} < 30 (oversold)"))
    else:
        out.append(("RSI zone", False, f"RSI {rsi:.1f} outside 35-50 band"))
    # 4. Pullback shape (SMA20 tag)
    if s20 is None or p is None:
        out.append(("Pullback shape", False, "no SMA20"))
    else:
        vs20 = (p / s20 - 1) * 100
        if -3 <= vs20 <= 3:
            out.append(("Pullback shape", True, f"price {vs20:+.1f}% from SMA20 (clean tag)"))
        elif vs20 > 3:
            out.append(("Pullback shape", False, f"price +{vs20:.1f}% above SMA20 (not yet a tag)"))
        else:
            out.append(("Pullback shape", False, f"price {vs20:.1f}% below SMA20 (broken)"))
    # 5. Volume profile
    if vol_ratio is None:
        out.append(("Volume profile", False, "no volume data"))
    elif vol_ratio <= 1.1:
        out.append(("Volume profile", True, f"5d/30d vol {vol_ratio:.2f}× (healthy)"))
    elif vol_ratio <= 1.3:
        out.append(("Volume profile", False, f"5d/30d vol {vol_ratio:.2f}× (elevated)"))
    else:
        out.append(("Volume profile", False, f"5d/30d vol {vol_ratio:.2f}× (distribution risk)"))
    # 6. Day stability
    if ch is None:
        out.append(("Day stability", False, "no change data"))
    elif abs(ch) <= 5:
        out.append(("Day stability", True, f"today {ch:+.2f}% (within ±5%)"))
    else:
        out.append(("Day stability", False, f"today {ch:+.2f}% (violent)"))
    # 7. Earnings window
    if not next_earn:
        out.append(("Earnings window", False, "no earnings date in cache"))
    else:
        try:
            ed = datetime.fromisoformat(next_earn).replace(tzinfo=timezone.utc)
            cal_days = (ed - datetime.now(timezone.utc)).days
            if cal_days < 0 or cal_days > 10:
                out.append(("Earnings window", True, f"next earnings in {cal_days}d (clear)"))
            else:
                out.append(("Earnings window", False, f"earnings in {cal_days}d (inside 7-trading-day halt)"))
        except Exception:
            out.append(("Earnings window", False, f"unparseable date {next_earn}"))
    # 8. Macro halt window
    if not macro_events:
        out.append(("Macro halt", True, "no macro events checked"))
    else:
        nearest = next((e for e in macro_events if 0 <= (e.get("hours_until") or 99999) <= 72), None)
        if nearest:
            out.append(("Macro halt", False, f"{nearest['type']} in {nearest['hours_until']:.0f}h (inside 72h halt)"))
        else:
            out.append(("Macro halt", True, "no event in next 72h"))
    return out


def synthesize_us_thesis(ticker, t, status_label, status_reason, macro_events, news_entry=None):
    """Plain-English synthesis for a US watchlist row."""
    name = t.get("name") or ticker
    sector = t.get("sector") or "—"
    rsi = t.get("rsi14"); atr14 = t.get("atr14"); price = t.get("price")
    atr_p = (atr14 / price * 100) if (atr14 and price) else None
    gates = evaluate_us_p1_gates(t, macro_events)
    pass_count = sum(1 for _, ok, _ in gates if ok)
    bits = []
    # Headline summary
    bits.append(f"<b>{html.escape(name)}</b> ({html.escape(sector)}) — current status: <b>{html.escape(status_label)}</b>. {html.escape(status_reason)}")
    # Setup
    if price and rsi is not None:
        atr_str = f", ATR {atr_p:.2f}%/day" if atr_p else ""
        bits.append(f"<b>Current read:</b> price ${price:.2f}, RSI {rsi:.1f}{atr_str}. Passes {pass_count}/8 P1 gates.")
    # What the status means + action
    action_map = {
        "P1_READY":        "<b>Action:</b> all 8 P1 gates pass. Run the Risk Simulator with your intended entry/stop/TP1 to confirm R:R + event proximity, then size per doctrine.",
        "DOWNTREND":       "<b>Action:</b> NO-TRADE long. Wait for daily close back above SMA50 with bullish structure, then for golden cross (SMA50 > SMA200) to re-evaluate.",
        "BELOW50":         "<b>Action:</b> NO-TRADE long. Wait for a daily close above SMA50 with a higher low for trend repair.",
        "NO_GOLDEN_CROSS": "<b>Action:</b> NO-TRADE long. Phase 1 requires SMA50 > SMA200; wait for the cross to confirm.",
        "TREND_FAIL":      "<b>Action:</b> NO-TRADE long. P1 trend ordering must hold first.",
        "OVERBOUGHT":      "<b>Action:</b> NO-TRADE long here. Wait for RSI to cool back into 35-50 with a structural pullback before re-evaluating.",
        "OVERSOLD":        "<b>Action:</b> WAIT. RSI under 30 can persist for weeks; need a higher low + RSI back above 30 before considering entry.",
        "VIOLENT":         "<b>Action:</b> WAIT until tomorrow. A >5% day is too noisy to enter — let the dust settle and re-read the chart.",
        "EXTENDED":        "<b>Action:</b> WAIT for pullback into SMA20 ±3% with RSI back into the 35-50 zone.",
        "ABOVE_SMA20":     "<b>Action:</b> WAIT a few days for price to mean-revert closer to SMA20 (within ±3%).",
        "BROKEN_SMA20":    "<b>Action:</b> WAIT for stabilization (basing pattern or higher low) before considering entry.",
        "HEAVY_VOLUME":    "<b>Action:</b> NO-TRADE long. Heavy volume on a pullback is distribution, not a healthy reset.",
        "SMA50_FALLING":   "<b>Action:</b> SKIP new entries; trend is deteriorating. Existing positions should consider trailing stops.",
        "NEAR_EARNINGS":   "<b>Action:</b> NO new exposure within 7 trading days of earnings. Wait 24h after the print.",
        "NEAR_FOMC":       "<b>Action:</b> NO new US-directional entries within 72h of FOMC.",
        "NEAR_CPI":        "<b>Action:</b> NO new US-directional entries within 72h of CPI.",
        "NEAR_NFP":        "<b>Action:</b> NO new US-directional entries within 72h of NFP.",
        "NEAR_PCE":        "<b>Action:</b> NO new US-directional entries within 72h of PCE.",
        "WATCH":           "<b>Action:</b> trend OK but setup not clean. Keep watching for a pullback into the P1 entry zone.",
        "CONTEXT":         "<b>Action:</b> not a trade candidate — this is a market-regime gauge only.",
        "NEW":             "<b>Action:</b> P1 trend filter can't apply cleanly without SMA200. Wait until ~200 trading days of price history exist.",
        "DATA":            "<b>Action:</b> data fetch failed. Refresh dashboard; verify ticker if it persists.",
    }
    bits.append(action_map.get(status_label.upper(), f"<b>Action:</b> {status_reason} — re-read the chart in context."))
    # Event risk note
    if next_earn := t.get("next_earnings"):
        try:
            ed = datetime.fromisoformat(next_earn).replace(tzinfo=timezone.utc)
            cal_days = (ed - datetime.now(timezone.utc)).days
            if 0 <= cal_days <= 30:
                bits.append(f"<b>Event watch:</b> earnings in {cal_days}d ({next_earn}). Plan exits accordingly.")
        except Exception: pass
    # News context
    if news_entry and not news_entry.get("error"):
        d = news_entry.get("data") or {}
        sent = d.get("aggregate_sentiment_score")
        if sent is not None:
            label = "Bullish" if sent > 0.15 else "Bearish" if sent < -0.15 else "Neutral"
            bits.append(f"<b>News sentiment (48h):</b> {label} (aggregate score {sent:+.2f}). See Recent News Flags panel.")
    return ("\n".join(f"<p>{b}</p>" for b in bits), gates)


def synthesize_klse_thesis(ticker, t, status_label, status_reason, fund=None, ann=None):
    """Plain-English synthesis for a KLSE watchlist row."""
    name = (fund or {}).get("stock_name") or (ann or {}).get("stock_name") or t.get("name") or ticker
    rsi = t.get("rsi14"); atr14 = t.get("atr14"); price = t.get("price")
    atr_p = (atr14 / price * 100) if (atr14 and price) else None
    gates = evaluate_us_p1_gates(t, None)  # KLSE reuses us_status logic
    pass_count = sum(1 for _, ok, _ in gates if ok)
    bits = []
    bits.append(f"<b>{html.escape(name)}</b> (KLSE {html.escape(ticker)}) — current status: <b>{html.escape(status_label)}</b>. {html.escape(status_reason)}")
    if price and rsi is not None:
        atr_str = f", ATR {atr_p:.2f}%/day" if atr_p else ""
        bits.append(f"<b>Current read:</b> price MYR {price:.4f}, RSI {rsi:.1f}{atr_str}. Passes {pass_count}/8 P1 gates (US-style framework applied to KLSE).")
    # Fundamentals snapshot
    if fund:
        pe = fund.get("pe_ratio"); pb = fund.get("pb_ratio"); dy = fund.get("dividend_yield_pct"); roe = fund.get("roe_pct")
        f_bits = []
        if pe: f_bits.append(f"P/E {pe:.2f}")
        if pb: f_bits.append(f"P/B {pb:.2f}")
        if dy: f_bits.append(f"DY {dy:.2f}%")
        if roe: f_bits.append(f"ROE {roe:.2f}%")
        if f_bits:
            bits.append(f"<b>Fundamentals (klsescreener):</b> {' · '.join(f_bits)}.")
    # Action
    action_map = {
        "P1_READY":   "<b>Action:</b> all 8 P1 gates pass on the technical layer. Cross-check the KLSE-specific earnings/announcement gate before sizing (Bursa filing window).",
        "DOWNTREND":  "<b>Action:</b> NO-TRADE long. Wait for SMA50 reclaim + golden cross.",
        "BELOW50":    "<b>Action:</b> NO-TRADE long. Daily close above SMA50 + higher low required.",
        "NO_GOLDEN_CROSS": "<b>Action:</b> NO-TRADE long. SMA50 needs to cross above SMA200 first.",
        "WATCH":      "<b>Action:</b> trend OK but setup not clean. Wait for pullback into the entry zone.",
        "NEW":        "<b>Action:</b> insufficient history — P1 trend filter cannot apply cleanly yet.",
        "DATA":       "<b>Action:</b> data fetch failed. Refresh; verify ticker.",
    }
    bits.append(action_map.get(status_label.upper(), f"<b>Action:</b> {status_reason}"))
    # KLSE-specific event gate
    if ann:
        fr = ann.get("most_recent_financial_results") or {}
        next_fr = fr.get("next_expected_filing_by")
        if next_fr:
            try:
                fd = datetime.fromisoformat(next_fr).replace(tzinfo=timezone.utc)
                cal_days = (fd - datetime.now(timezone.utc)).days
                if 0 <= cal_days <= 20:
                    bits.append(f"<b>Bursa filing watch:</b> next quarterly results deadline in {cal_days}d ({next_fr}). Within 14d = re-check daily for early filing.")
                elif cal_days > 20:
                    bits.append(f"<b>Bursa filing window:</b> next deadline in {cal_days}d ({next_fr}) — clear.")
            except Exception: pass
        for e in (ann.get("upcoming_events") or [])[:2]:
            try:
                ed = datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
                cal_days = (ed - datetime.now(timezone.utc)).days
                if 0 <= cal_days <= 30:
                    bits.append(f"<b>Corporate event:</b> {e['type'].upper()} on {e['date']} ({cal_days}d away).")
            except Exception: pass
    return ("\n".join(f"<p>{b}</p>" for b in bits), gates)


def synthesize_crypto_thesis(symbol, row, ind, funding, unlock_entry, crypto_regime):
    """Plain-English synthesis for a crypto watchlist row (no formal P1 for spot in Phase 1)."""
    name = row.get("name") or symbol
    price = row.get("price")
    ch24 = row.get("chg_24h"); ch7 = row.get("chg_7d"); ch30 = row.get("chg_30d")
    rsi = ind.get("rsi14"); atr_p = ind.get("atr_pct")
    ann = (funding or {}).get("annualized_pct")
    bits = []
    bits.append(f"<b>{html.escape(name)}</b> ({html.escape(symbol)}) — crypto bias read. Doctrine has no formal P1 for crypto spot in Phase 1; this is risk-framework guidance only.")
    if price is not None:
        rsi_str = f"{rsi:.1f}" if rsi is not None else "—"
        atr_str = f" · ATR {atr_p:.2f}%/day" if atr_p else ""
        ch24v = ch24 or 0; ch7v = ch7 or 0; ch30v = ch30 or 0
        bits.append(f"<b>Current read:</b> ${price:.4f} · 24h {ch24v:+.2f}% · 7d {ch7v:+.2f}% · 30d {ch30v:+.2f}% · RSI {rsi_str}{atr_str}.")
    # Volatility context
    if atr_p:
        if atr_p > 8:
            bits.append(f"<b>Volatility:</b> {atr_p:.1f}%/day ATR is high — even a 1.5× ATR stop is ~{atr_p*1.5:.1f}% below entry. Position sizing must shrink accordingly.")
        elif atr_p > 4:
            bits.append(f"<b>Volatility:</b> {atr_p:.1f}%/day ATR is typical for majors — stops in the 1.5-2× ATR range are standard.")
        else:
            bits.append(f"<b>Volatility:</b> {atr_p:.1f}%/day ATR is unusually low for crypto — may indicate compression before a move.")
    # Funding context
    if ann is not None:
        if ann > 50:
            bits.append(f"<b>Perp positioning:</b> funding {ann:+.1f}% APR — crowded long. Flush risk if leveraged longs get liquidated; spot longs feel the second-order pain.")
        elif ann < -30:
            bits.append(f"<b>Perp positioning:</b> funding {ann:+.1f}% APR — crowded short. Squeeze fuel; favors longs.")
        else:
            bits.append(f"<b>Perp positioning:</b> funding {ann:+.1f}% APR — neutral, no positioning edge either way.")
    # Unlock gate
    if unlock_entry:
        st = unlock_entry.get("_source_type")
        nu = unlock_entry.get("next_unlock")
        if st == "baseline_no_schedule":
            bits.append(f"<b>Unlock gate:</b> ✓ no vesting schedule — {html.escape(unlock_entry.get('notes', ''))}")
        elif st == "baseline_regular":
            bits.append(f"<b>Unlock gate:</b> ⚠ regular emission — verify on tokenomist.ai if sizing meaningful.")
        elif nu:
            try:
                ud = datetime.fromisoformat(nu['date']).replace(tzinfo=timezone.utc)
                cal_days = (ud - datetime.now(timezone.utc)).days
                pct = nu.get('pct_of_float')
                pct_str = f"{pct:.2f}% float" if pct is not None else "size unknown"
                if cal_days <= 2:
                    bits.append(f"<b>Unlock gate:</b> 🛑 {nu.get('type','unknown')} unlock in {cal_days}d ({nu['date']}), {pct_str} — inside doctrine §5 48h halt window.")
                elif cal_days <= 7:
                    bits.append(f"<b>Unlock gate:</b> ⚠ {nu.get('type','unknown')} unlock in {cal_days}d ({nu['date']}), {pct_str} — within trade duration.")
                else:
                    bits.append(f"<b>Unlock gate:</b> ✓ next unlock in {cal_days}d ({nu['date']}), {pct_str} — clear.")
            except Exception: pass
    else:
        bits.append(f"<b>Unlock gate:</b> ⚠ no entry in crypto-unlocks cache — run the WebFetch crypto-unlocks skill + cache `set`.")
    # Regime context
    if crypto_regime and crypto_regime.get("score") is not None:
        s = crypto_regime["score"]; lab = crypto_regime.get("label", "—")
        if s <= -0.4:
            bits.append(f"<b>Crypto regime:</b> {lab} ({s:+.2f}) — RISK-OFF tilt; consider waiting or sizing down.")
        elif s >= 0.4:
            bits.append(f"<b>Crypto regime:</b> {lab} ({s:+.2f}) — RISK-ON tilt favors longs.")
        else:
            bits.append(f"<b>Crypto regime:</b> {lab} ({s:+.2f}) — neutral.")
    bits.append(f"<b>Action:</b> use the Risk Simulator to validate entry/stop/TP against ATR-based sizing and the active doctrine gates.")
    return "\n".join(f"<p>{b}</p>" for b in bits)


def _last_us_trading_day():
    """Naive 'most recent expected trading day' in ET. Doesn't account for holidays —
    good enough for a yfinance-staleness visual cue."""
    from datetime import datetime, timedelta, timezone
    # Use ET-ish (UTC-4) approx; for staleness comparison we just need a day-level reference.
    now_et = datetime.now(timezone.utc) - timedelta(hours=4)
    d = now_et.date()
    # Walk back to last weekday (Mon=0..Sun=6); if today is Sat/Sun, go to Fri.
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    # If we're before US market open (~9:30 ET), the "latest close" is yesterday.
    if now_et.hour < 16:  # before close
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d.isoformat()

def _price_stale(price_date):
    if not price_date: return False
    try:
        return price_date < _last_us_trading_day()
    except Exception:
        return False

def _price_age_suffix(price_date):
    """Small inline marker: '·' for normal (last trading day), '·!' if older."""
    if not price_date: return ""
    return ' <span class="stale-mark">!</span>' if _price_stale(price_date) else ''

def _price_tooltip(price_date):
    if not price_date: return "Bar date unknown — price source did not return an index."
    expected = _last_us_trading_day()
    if price_date == expected:
        return f"Last close: {price_date} (latest US trading-day bar — fresh)"
    return (f"Last clean close: {price_date} — older than expected last trading day ({expected}). "
            f"yfinance returned a NaN-Close bar for the more recent day; this is the most recent "
            f"non-NaN close. Treat 24h% as 'change vs prior clean bar', not literal 24h.")


def status_tooltip(label):
    """Return the tooltip text for a status label. Falls back to a generic note if unknown."""
    if not label: return ""
    return STATUS_TOOLTIPS.get(label.upper(), f"{label}: no detailed explanation defined yet — see us_status() / crypto_status() in dashboard.py.")


def crypto_status(row, fnd):
    # Simple bias read; doctrine doesn't have a formal P1 for crypto spot
    ch24 = row.get("chg_24h") or 0
    ch30 = row.get("chg_30d") or 0
    ann = (fnd or {}).get("annualized_pct")
    notes = []
    if ann is not None:
        if ann > 50: notes.append("crowded long (flush risk)")
        elif ann < -50: notes.append("crowded short (squeeze fuel)")
    if ch30 < -20: tag = "🟡"; lab = "DEEP DRAWDOWN"
    elif ch30 < -10: tag = "🟡"; lab = "PULLBACK"
    elif ch30 > 20: tag = "🟡"; lab = "EXTENDED"
    else: tag = "⚪"; lab = "WATCH"
    return (tag, lab, "; ".join(notes) if notes else "")


# ── HTML rendering ─────────────────────────────────────────────────────────
def fmt_num(x, places=2, default="—"):
    if x is None:
        return default
    try:
        return f"{float(x):,.{places}f}"
    except (TypeError, ValueError):
        return default

def fmt_pct(x, places=2, default="—"):
    if x is None:
        return default
    try:
        return f"{float(x):+.{places}f}%"
    except (TypeError, ValueError):
        return default

def fmt_money(x):
    if x is None:
        return "—"
    try:
        v = float(x)
        if abs(v) >= 1e12: return f"${v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"${v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return "—"


def humanize_age(seconds):
    """Convert seconds to an unambiguous age string. Avoids 'M' (ambiguous: minute vs month)."""
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if s < 0:           return "0 sec"
    if s < 60:          return f"{int(s)} sec"
    if s < 3600:        return f"{int(s/60)} min"
    if s < 86400:       return f"{s/3600:.1f} hr"
    if s < 86400 * 14:  return f"{s/86400:.1f} days"
    return f"{int(s/86400)} days"


def _ago_span(dt):
    """Return '<span class="ago" data-ts="ISO">9 sec ago</span>' — JS ticks this in-place."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_s = (datetime.now(timezone.utc) - dt).total_seconds()
    iso = dt.astimezone(timezone.utc).isoformat()
    return f'<span class="ago" data-ts="{iso}">{humanize_age(age_s)} ago</span>'


def fmt_fetched(iso_ts_or_str):
    """Return '<span class="ago">X min ago</span> · <span class="fetched-at-utc">14:23 UTC</span>'.

    Both age and absolute clock are kept in the markup so they survive a stale page reload.
    The relative-age span's text is recomputed every 15s via JS (tickAgo). The absolute UTC
    span carries data-utc so the same Intl.DateTimeFormat reformatter that handles "Built at"
    converts it to the viewer's local timezone on page load. Original UTC string is in the
    tooltip via title="..." as a fallback.
    """
    if not iso_ts_or_str:
        return "—"
    try:
        if isinstance(iso_ts_or_str, datetime):
            dt = iso_ts_or_str
        else:
            dt = datetime.fromisoformat(str(iso_ts_or_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - dt).total_seconds()
        utc_dt = dt.astimezone(timezone.utc)
        if age_s < 86400:
            abs_str = utc_dt.strftime("%H:%M UTC")
        else:
            abs_str = utc_dt.strftime("%b %d %H:%M UTC")
        iso_z = utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            f'{_ago_span(dt)} · '
            f'<span class="fetched-at-utc" data-utc="{iso_z}" title="UTC: {abs_str}">{abs_str}</span>'
        )
    except Exception:
        return "—"


def fetched_at_of(data):
    """Pull the _fetched_at marker my cache layer writes onto every cached dict."""
    if not isinstance(data, dict):
        return None
    return data.get("_fetched_at")

CSS = """
:root {
  --bg: #0f1115; --panel: #161a22; --panel-2: #1c2030;
  --text: #e8ebf2; --dim: #8a93a6; --bord: #2a2f3d;
  --green: #4ade80; --yellow: #fbbf24; --red: #f87171; --blue: #60a5fa;
  --accent: #a78bfa;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 13px; line-height: 1.4; }
.container { max-width: 1600px; margin: 0 auto; padding: 16px; }
.header { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; background: var(--panel); border-radius: 8px;
  border: 1px solid var(--bord); margin-bottom: 16px; }
.header h1 { margin: 0; font-size: 16px; color: var(--accent); }
.header .meta { color: var(--dim); font-size: 12px; }
.strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.strip.strip-5 { grid-template-columns: repeat(5, 1fr); }
.strip .cell { background: var(--panel); padding: 12px; border-radius: 8px; border: 1px solid var(--bord); }
.strip .label { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.strip .value { font-size: 18px; margin-top: 4px; color: var(--text); }
.strip .value.yellow { color: var(--yellow); }
.strip .value.red { color: var(--red); }
.strip .sub { color: var(--dim); font-size: 11px; margin-top: 2px; }
/* News flags panel */
.news-row { padding: 6px 0; border-bottom: 1px solid var(--bord); font-size: 12px; }
.news-row:last-child { border-bottom: none; }
.news-row .arrow { display: inline-block; width: 14px; }
.news-row .arrow.up { color: var(--green); }
.news-row .arrow.down { color: var(--red); }
.news-row .arrow.flat { color: var(--dim); }
.news-row .ticker { display: inline-block; min-width: 56px; font-weight: bold; }
.news-row .src { color: var(--dim); font-size: 11px; margin-left: 6px; }
.news-row .time { color: var(--dim); font-size: 11px; }
.news-row .sent { font-size: 10px; padding: 1px 6px; border-radius: 3px; margin-left: 6px; }
.news-row .sent.bull { background: rgba(74,222,128,0.18); color: var(--green); }
.news-row .sent.bear { background: rgba(248,113,113,0.18); color: var(--red); }
.news-row .sent.neu { background: var(--panel-2); color: var(--dim); }
.news-row .title { display: block; margin-top: 2px; color: var(--text); }
.panel { background: var(--panel); border: 1px solid var(--bord); border-radius: 8px;
  padding: 14px; margin-bottom: 16px; }
.panel h2 { margin: 0 0 10px 0; font-size: 13px; color: var(--accent);
  text-transform: uppercase; letter-spacing: 0.06em; }
.panel .stale { color: var(--dim); font-size: 11px; float: right; font-weight: normal;
  text-transform: none; letter-spacing: normal; }
.regime-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.regime-box { background: var(--panel-2); padding: 12px; border-radius: 6px; border: 1px solid var(--bord); }
.regime-box .title { color: var(--dim); font-size: 11px; text-transform: uppercase; }
.regime-box .verdict { font-size: 16px; font-weight: bold; margin-top: 4px; }
.regime-box .signals { margin-top: 8px; font-size: 11px; color: var(--dim); }
.regime-box .signals .sig { padding: 2px 0; }
.regime-box .v-pos { color: var(--green); }
.regime-box .v-neg { color: var(--red); }
.regime-box .v-neu { color: var(--dim); }
.events { display: flex; flex-wrap: wrap; gap: 8px; }
.event { background: var(--panel-2); padding: 8px 12px; border-radius: 6px;
  border: 1px solid var(--bord); font-size: 12px; }
.event.halt { border-color: var(--red); }
.event .type { font-weight: bold; color: var(--blue); }
.event .when { color: var(--dim); font-size: 11px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; color: var(--dim); font-weight: normal;
  padding: 8px 6px; border-bottom: 1px solid var(--bord);
  text-transform: uppercase; letter-spacing: 0.03em; font-size: 10px;
  cursor: pointer; user-select: none; }
th:hover { color: var(--text); }
th.sort-asc::after { content: " ▲"; color: var(--accent); }
th.sort-desc::after { content: " ▼"; color: var(--accent); }
td { padding: 6px; border-bottom: 1px solid var(--bord); }
tr:hover { background: var(--panel-2); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.green { color: var(--green); }
td.red { color: var(--red); }
td.dim { color: var(--dim); }
.badge { display: inline-block; padding: 2px 6px; border-radius: 4px;
  font-size: 10px; font-weight: bold; letter-spacing: 0.04em; cursor: help; }
.badge:hover { filter: brightness(1.15); }
/* Stale-price marker */
.stale-price { color: var(--yellow); cursor: help; }
.stale-mark { color: var(--yellow); font-weight: bold; font-size: 10px; margin-left: 2px; }
/* B2: API budget bar in header */
.budget-bar { display: inline-flex; gap: 4px; margin-left: 4px; }
.budget-cell { display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 10px; font-weight: bold; cursor: help; letter-spacing: 0.04em;
  border: 1px solid var(--bord); }
/* Live quote button (Finnhub on-demand fetch) */
.ta-quote-btn { cursor: pointer; font-size: 10px; padding: 1px 4px; background: var(--panel-2);
  color: var(--text); border: 1px solid var(--bord); border-radius: 3px; margin-left: 4px;
  font-family: inherit; vertical-align: baseline; }
.ta-quote-btn:hover { background: var(--accent); color: white; border-color: var(--accent); }
.ta-quote-btn.loading { opacity: 0.5; cursor: wait; }
.live-quote { font-size: 11px; margin-left: 6px; font-weight: bold; }
.live-quote .lq-time { color: var(--dim); font-size: 10px; font-weight: normal; margin-left: 4px; }
.live-quote .lq-err  { color: var(--red); font-size: 10px; }
.b-green { background: rgba(74, 222, 128, 0.15); color: var(--green); border: 1px solid var(--green); }
.b-red { background: rgba(248, 113, 113, 0.15); color: var(--red); border: 1px solid var(--red); }
.b-yellow { background: rgba(251, 191, 36, 0.15); color: var(--yellow); border: 1px solid var(--yellow); }
.b-dim { background: var(--panel-2); color: var(--dim); border: 1px solid var(--bord); }
.sent-fade { background: rgba(248, 113, 113, 0.16); border-left: 3px solid rgba(248, 113, 113, 0.6); }
.sent-buy { background: rgba(74, 222, 128, 0.16); border-left: 3px solid rgba(74, 222, 128, 0.6); }
.sent-flag-fade { color: var(--red); font-weight: bold; font-size: 10px; letter-spacing: 0.5px; }
.sent-flag-buy { color: var(--green); font-weight: bold; font-size: 10px; letter-spacing: 0.5px; }
.pm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.pm-col { background: var(--bg); padding: 10px 12px; border-radius: 4px; border: 1px solid var(--bord); }
.pm-head { font-weight: bold; color: var(--text); margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid var(--bord); font-size: 12px; }
.pm-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; }
.pm-prob { display: inline-block; min-width: 38px; text-align: right; font-weight: bold; font-variant-numeric: tabular-nums; padding: 1px 4px; border-radius: 3px; }
.pm-high { color: var(--green); background: rgba(74, 222, 128, 0.10); }
.pm-low { color: var(--red); background: rgba(248, 113, 113, 0.10); }
.pm-mid { color: var(--yellow); background: rgba(251, 191, 36, 0.10); }
.pm-title { color: var(--text); text-decoration: none; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pm-title:hover { color: var(--accent); text-decoration: underline; }
.wl-remove-btn { background: transparent; border: none; color: var(--dim); cursor: pointer; padding: 0 4px; font-size: 12px; opacity: 0.4; transition: opacity 0.15s, color 0.15s; }
.wl-remove-btn:hover { opacity: 1; color: var(--red); }
@media print { .wl-remove-btn { display: none; } }

.cs-explainer { font-size: 11px; margin: 4px 0 12px; padding: 8px 12px; background: var(--bg); border-left: 3px solid var(--yellow); border-radius: 0 4px 4px 0; line-height: 1.5; }
.cs-rows { display: flex; flex-direction: column; gap: 10px; }
.cs-row { background: var(--bg); border: 1px solid var(--bord); border-radius: 4px; padding: 10px 12px; display: grid; grid-template-columns: 30px 60px 70px 60px 1fr auto auto; gap: 8px; align-items: center; font-size: 12px; }
.cs-badge { font-size: 18px; text-align: center; }
.cs-flag { font-weight: bold; font-size: 10px; letter-spacing: 0.5px; text-align: center; }
.cs-ticker { font-weight: bold; font-size: 13px; }
.cs-class { color: var(--dim); font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
.cs-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cs-stats { font-variant-numeric: tabular-nums; color: var(--text); font-size: 11px; }
.cs-tech { font-variant-numeric: tabular-nums; color: var(--yellow); font-size: 11px; padding: 2px 6px; background: rgba(251, 191, 36, 0.08); border-radius: 3px; }
.cs-action { grid-column: 1 / -1; font-size: 11px; color: var(--text); padding-top: 6px; border-top: 1px dashed var(--bord); margin-top: 4px; }
.cs-rationale { grid-column: 1 / -1; font-size: 10px; line-height: 1.5; }

/* BTFD / STR price×volume setups panel */
.bs-section { margin-top: 10px; }
.bs-section-head { font-weight: bold; font-size: 12px; color: var(--text); margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid var(--bord); }
.bs-rows { display: flex; flex-direction: column; gap: 6px; }
.bs-row { display: grid; grid-template-columns: 130px 60px 50px 1fr auto; gap: 8px; align-items: center; padding: 6px 10px; border-radius: 4px; font-size: 11px; background: var(--bg); border: 1px solid var(--bord); }
.bs-tier { font-weight: bold; font-size: 11px; }
.bs-ticker { font-weight: bold; font-size: 12px; }
.bs-class { color: var(--dim); font-size: 10px; text-transform: uppercase; }
.bs-name { color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bs-stats { font-variant-numeric: tabular-nums; color: var(--text); }
.bs-tech { font-variant-numeric: tabular-nums; }
.bs-cross { font-size: 10px; }
.boost-up { color: var(--green); font-weight: bold; font-size: 10px; padding: 1px 4px; background: rgba(74,222,128,0.12); border-radius: 3px; }
.event-warn { color: var(--yellow); font-weight: bold; font-size: 10px; padding: 1px 4px; background: rgba(251,191,36,0.12); border-radius: 3px; margin-left: 4px; }
.btfd-cap   { border-left: 3px solid var(--red); }
.btfd-real  { border-left: 3px solid rgba(248,113,113,0.5); }
.btfd-light { border-left: 3px solid rgba(248,113,113,0.25); }
.str-blow   { border-left: 3px solid var(--green); }
.str-real   { border-left: 3px solid rgba(74,222,128,0.5); }
.str-light  { border-left: 3px solid rgba(74,222,128,0.25); }
.prospectus { background: var(--panel-2); padding: 12px; border-radius: 6px;
  border-left: 3px solid var(--accent); margin-bottom: 8px; }
.prospectus .head { font-weight: bold; }
.prospectus .meta { color: var(--dim); font-size: 11px; margin-top: 4px; }
.prospectus .actions { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
.prospectus .actions button { background: var(--panel); color: var(--text); border: 1px solid var(--bord);
  padding: 4px 8px; border-radius: 4px; font-family: inherit; font-size: 11px; cursor: pointer; }
.prospectus .actions button:hover { background: var(--accent); color: white; border-color: var(--accent); }
.prospectus .actions button.active { background: var(--accent); color: white; border-color: var(--accent); }
.prospectus .actions button.copied { background: var(--green); color: white; border-color: var(--green); }

/* Inline form for prospectus actions */
.action-form { margin-top: 10px; padding: 12px; background: var(--bg); border: 1px solid var(--bord);
  border-radius: 6px; display: none; }
.action-form.open { display: block; }
.action-form .form-title { font-weight: bold; color: var(--accent); margin-bottom: 8px;
  text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px; }
.action-form .form-row { display: grid; grid-template-columns: 120px 1fr; gap: 8px; align-items: center;
  margin-bottom: 6px; }
.action-form label { color: var(--dim); font-size: 11px; }
.action-form input, .action-form textarea { background: var(--panel-2); color: var(--text);
  border: 1px solid var(--bord); padding: 5px 7px; border-radius: 4px; font-family: inherit;
  font-size: 12px; width: 100%; }
.action-form input:focus, .action-form textarea:focus { outline: none; border-color: var(--accent); }
.action-form textarea { min-height: 40px; resize: vertical; }
.action-form .help { color: var(--dim); font-size: 10px; margin-top: 2px; grid-column: 2; }
.action-form .preview { margin-top: 10px; padding: 8px 10px; background: var(--panel);
  border: 1px solid var(--bord); border-radius: 4px; font-size: 11px; color: var(--text);
  white-space: pre-wrap; word-break: break-all; line-height: 1.4; }
.action-form .preview-label { color: var(--dim); font-size: 10px; margin-bottom: 4px;
  text-transform: uppercase; letter-spacing: 0.05em; }
.action-form .preview-invalid { color: var(--yellow); }
.action-form .form-actions { margin-top: 10px; display: flex; gap: 6px; }
.action-form .form-actions button { padding: 5px 10px; font-size: 11px; cursor: pointer;
  border-radius: 4px; font-family: inherit; border: 1px solid var(--bord); }
.action-form .form-actions .primary { background: var(--accent); color: white; border-color: var(--accent); }
.action-form .form-actions .primary:hover { background: #8b5cf6; }
.action-form .form-actions .primary.copied { background: var(--green); border-color: var(--green); }
.action-form .form-actions .secondary { background: var(--panel); color: var(--text); }
.action-form .form-actions .secondary:hover { background: var(--panel-2); }
.action-form .calc-result { margin-top: 10px; padding: 10px; background: var(--panel);
  border-left: 3px solid var(--accent); border-radius: 4px; font-size: 12px; line-height: 1.5; }
.action-form .calc-result .big { font-size: 18px; font-weight: bold; }
.action-form .calc-result .pos { color: var(--green); }
.action-form .calc-result .neg { color: var(--red); }
/* Watchlist Manager tabs */
.wl-mode-tabs { display: flex; gap: 6px; margin-bottom: 12px; border-bottom: 1px solid var(--bord); padding-bottom: 8px; }
.wl-mode-tabs .wl-tab { padding: 6px 12px; background: var(--panel); color: var(--text); border: 1px solid var(--bord);
  border-radius: 4px; font-size: 12px; cursor: pointer; }
.wl-mode-tabs .wl-tab:hover { background: var(--panel-2); }
.wl-mode-tabs .wl-tab.active { background: var(--accent); color: white; border-color: var(--accent); }
/* Discovery panel */
.sector-strip { display: grid; grid-template-columns: repeat(11, 1fr); gap: 4px; margin-bottom: 4px; }
.sector-cell { padding: 6px 4px; border-radius: 4px; text-align: center; cursor: help;
  border: 1px solid var(--bord); background: var(--panel-2); }
.sector-cell .sym { font-weight: bold; font-size: 11px; }
.sector-cell .comp { font-size: 13px; font-weight: bold; margin: 2px 0; }
.sector-cell .name { font-size: 9px; color: var(--dim); }
.sector-strong { background: rgba(74, 222, 128, 0.18); border-color: var(--green); }
.sector-strong .comp { color: var(--green); }
.sector-weak { background: rgba(248, 113, 113, 0.18); border-color: var(--red); }
.sector-weak .comp { color: var(--red); }
.sector-neutral { background: var(--panel-2); }
.discovery-add { padding: 3px 8px; font-size: 11px; background: var(--accent); color: white;
  border: 1px solid var(--accent); border-radius: 3px; cursor: pointer; }
.discovery-add:hover { background: #8b5cf6; }
.discovery-add.copied { background: var(--green); border-color: var(--green); }
/* Discovery expandable rows */
.discovery-row { cursor: pointer; }
.discovery-row:hover { background: var(--panel-2); }
.discovery-row.expanded { background: var(--panel-2); }
.discovery-chevron { display: inline-block; color: var(--dim); font-size: 11px; transition: transform 0.15s; user-select: none; }
.discovery-details { display: none; }
.discovery-details.open { display: table-row; }
.discovery-details-content { padding: 14px 18px; background: var(--panel); border-left: 3px solid var(--accent);
  border-radius: 0 4px 4px 0; margin: 4px 0 8px; }
.dd-thesis p { margin: 0 0 8px; font-size: 12px; line-height: 1.55; color: var(--text); }
.dd-thesis p b { color: var(--accent); }
.dd-gates-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
.dd-gate-col { background: var(--bg); padding: 10px 12px; border-radius: 4px; border: 1px solid var(--bord); }
.dd-gate-head { font-weight: bold; font-size: 11px; color: var(--dim); margin-bottom: 6px;
  text-transform: uppercase; letter-spacing: 0.05em; }
.gate-line { font-size: 12px; padding: 3px 0; line-height: 1.4; }
.gate-line .green { color: var(--green); font-weight: bold; }
.gate-line .red { color: var(--red); font-weight: bold; }
.dd-meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 11px; color: var(--dim);
  padding-top: 10px; border-top: 1px solid var(--bord); margin-top: 10px; }
.dd-meta b { color: var(--text); }
/* Shared expandable row pattern (used by US, KLSE, Crypto grids) */
.exp-row { cursor: pointer; }
.exp-row:hover { background: var(--panel-2); }
.exp-row.expanded { background: var(--panel-2); }
.exp-chevron { display: inline-block; color: var(--dim); font-size: 11px; user-select: none; width: 12px; }
.exp-details { display: none; }
.exp-details.open { display: table-row; }
.exp-details-content { padding: 14px 18px; background: var(--panel); border-left: 3px solid var(--accent);
  border-radius: 0 4px 4px 0; margin: 4px 0 8px; }
.exp-thesis p { margin: 0 0 8px; font-size: 12px; line-height: 1.55; color: var(--text); }
.exp-thesis p b { color: var(--accent); }
.exp-gates-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin: 12px 0; }
.exp-gate-col { background: var(--bg); padding: 10px 12px; border-radius: 4px; border: 1px solid var(--bord); }
.exp-gate-head { font-weight: bold; font-size: 11px; color: var(--dim); margin-bottom: 6px;
  text-transform: uppercase; letter-spacing: 0.05em; }
.exp-meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 11px; color: var(--dim);
  padding-top: 10px; border-top: 1px solid var(--bord); margin-top: 10px; }
.exp-meta b { color: var(--text); }
.action-form select { background: var(--panel-2); color: var(--text); border: 1px solid var(--bord); padding: 4px 6px;
  border-radius: 3px; font-size: 12px; font-family: inherit; }
.footer { color: var(--dim); font-size: 11px; text-align: center; margin-top: 24px; padding: 12px; }
.refresh-btn { background: var(--accent); color: white; padding: 8px 16px;
  border-radius: 6px; text-decoration: none; font-weight: bold; font-size: 12px;
  display: inline-block; cursor: pointer; border: none; }
.refresh-btn:hover { background: #8b5cf6; }
/* Refresh dropdown */
.refresh-menu { position: relative; display: inline-block; }
.refresh-menu-items { display: none; position: absolute; right: 0; top: calc(100% + 4px);
  background: var(--panel-2); border: 1px solid var(--bord); border-radius: 6px;
  min-width: 280px; box-shadow: 0 6px 20px rgba(0,0,0,0.4); z-index: 100;
  padding: 4px 0; }
.refresh-menu.open .refresh-menu-items { display: block; }
.refresh-menu-item { padding: 8px 12px; cursor: pointer; font-size: 12px;
  color: var(--text); display: block; line-height: 1.4; border: none; background: none;
  width: 100%; text-align: left; font-family: inherit; }
.refresh-menu-item:hover { background: var(--panel); }
.refresh-menu-item .rm-label { font-weight: bold; color: var(--text); }
.refresh-menu-item .rm-desc { color: var(--dim); font-size: 10px; margin-top: 2px; }
.refresh-toast { display: inline-block; margin-left: 8px; color: var(--green); font-size: 11px;
  opacity: 0; transition: opacity 0.2s; }
.refresh-toast.show { opacity: 1; }
.error { color: var(--red); font-size: 11px; }
/* Risk Simulator */
.sim-form { display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr 1fr auto; gap: 8px; align-items: end; margin-bottom: 12px; }
.sim-form label { display: block; color: var(--dim); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
.sim-form input, .sim-form select { background: var(--panel-2); color: var(--text); border: 1px solid var(--bord);
  padding: 6px 8px; border-radius: 4px; font-family: inherit; font-size: 13px; width: 100%; }
.sim-form input:focus, .sim-form select:focus { outline: none; border-color: var(--accent); }
.sim-form button { background: var(--accent); color: white; border: none; padding: 7px 14px; border-radius: 4px;
  font-weight: bold; font-size: 12px; cursor: pointer; }
.sim-result { background: var(--panel-2); padding: 14px; border-radius: 6px; border: 1px solid var(--bord); }
.sim-verdict { font-size: 22px; font-weight: bold; margin-bottom: 8px; }
.sim-verdict.go { color: var(--green); }
.sim-verdict.no { color: var(--red); }
.sim-verdict.pending { color: var(--dim); }
.sim-blurb { color: var(--dim); font-size: 12px; margin-bottom: 12px; }
.sim-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 12px 0; }
.sim-stat { background: var(--bg); padding: 10px; border-radius: 4px; border: 1px solid var(--bord); }
.sim-stat .l { color: var(--dim); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
.sim-stat .v { font-size: 15px; margin-top: 3px; font-weight: bold; }
.sim-stat .v.green { color: var(--green); }
.sim-stat .v.red { color: var(--red); }
.sim-substat { color: var(--dim); font-size: 11px; margin-top: 2px; font-weight: normal; }
.sim-gates { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; margin-top: 12px; font-size: 12px; }
.sim-prosp { margin-top: 16px; padding: 12px 14px; background: var(--bg); border: 1px solid var(--bord);
  border-left: 3px solid var(--green); border-radius: 4px; }
.sim-prosp.disabled { border-left-color: var(--red); opacity: 0.65; }
.sim-prosp-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; gap: 12px; }
.sim-prosp-cmd { padding: 8px 10px; background: var(--panel); border-radius: 3px; font-family: monospace;
  font-size: 11px; word-break: break-all; color: var(--text); margin-bottom: 8px; }
.sim-prosp-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sim-prosp-copy { padding: 5px 12px; font-size: 12px; background: var(--accent); color: white;
  border: 1px solid var(--accent); border-radius: 3px; cursor: pointer; font-weight: bold; }
.sim-prosp-copy:hover { background: #8b5cf6; }
.sim-prosp-copy.copied { background: var(--green); border-color: var(--green); }
.sim-prosp-copy:disabled { cursor: not-allowed; opacity: 0.5; }
.sim-gate { padding: 4px 0; display: flex; gap: 8px; }
.sim-gate .mark { font-weight: bold; flex-shrink: 0; width: 18px; }
.sim-gate .mark.ok { color: var(--green); }
.sim-gate .mark.bad { color: var(--red); }
.sim-gate .mark.warn { color: var(--yellow); }
.sim-gate .label { color: var(--text); font-weight: bold; }
.sim-gate .why { color: var(--dim); font-size: 11px; margin-left: 4px; }
@media print { .refresh-btn { display: none; } body { background: white; color: black; } }
"""

JS = """
// Live-ticking relative-age timers. Every <span class="ago" data-ts="ISO"> element
// has its textContent recomputed from the current wall-clock — so reloading the page
// (or just waiting) shows accurate "X sec/min/hr ago" without rebuilding the dashboard.
function humanizeAgeJS(seconds) {
  if (seconds < 0) return '0 sec';
  if (seconds < 60)        return Math.floor(seconds) + ' sec';
  if (seconds < 3600)      return Math.floor(seconds / 60) + ' min';
  if (seconds < 86400)     return (seconds / 3600).toFixed(1) + ' hr';
  if (seconds < 86400*14)  return (seconds / 86400).toFixed(1) + ' days';
  return Math.floor(seconds / 86400) + ' days';
}
function tickAgo() {
  const now = Date.now();
  document.querySelectorAll('.ago[data-ts]').forEach(el => {
    const dt = new Date(el.dataset.ts);
    if (isNaN(dt.getTime())) return;
    const age = (now - dt.getTime()) / 1000;
    el.textContent = humanizeAgeJS(age) + ' ago';
  });
}
tickAgo();
setInterval(tickAgo, 15000);  // tick every 15s

// Reformat absolute UTC timestamps into the viewer's browser TZ everywhere they appear.
// Each element opts in via a class + data-utc attribute. The original ET/UTC text is
// preserved in the tooltip via title="..." so the source-of-truth is still visible.
(function() {
  const fmtFull = new Intl.DateTimeFormat([], {
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, timeZoneName: 'short',
  });
  const fmtShort = new Intl.DateTimeFormat([], {
    month: 'short', day: '2-digit', weekday: 'short',
    hour: '2-digit', minute: '2-digit',
    hour12: false, timeZoneName: 'short',
  });
  document.querySelectorAll('.built-at[data-utc]').forEach(el => {
    const dt = new Date(el.dataset.utc);
    if (isNaN(dt.getTime())) return;
    el.textContent = fmtFull.format(dt);
  });
  document.querySelectorAll('.event-time[data-utc]').forEach(el => {
    const dt = new Date(el.dataset.utc);
    if (isNaN(dt.getTime())) return;
    el.textContent = fmtShort.format(dt);
  });
  // fetched-at chips (rendered by fmt_fetched in Python): the absolute clock portion
  // is a child <span class="fetched-at-utc" data-utc="..."> that we reformat in place.
  document.querySelectorAll('.fetched-at-utc[data-utc]').forEach(el => {
    const dt = new Date(el.dataset.utc);
    if (isNaN(dt.getTime())) return;
    el.textContent = fmtShort.format(dt);
  });
  // Refresh-dropdown: click outside the menu closes it.
  document.addEventListener('click', function(ev) {
    const menu = document.getElementById('refresh-menu');
    if (menu && menu.classList.contains('open') && !menu.contains(ev.target)) {
      menu.classList.remove('open');
    }
  });
})();

// Watchlist remove — prompt for required reason, copy `wl.py remove` command to clipboard.
// Dashboard is static HTML so we can't write to disk; this is the copy-then-paste pattern
// already used elsewhere (Refresh button, prospectus actions, etc.).
function wlRemove(ticker) {
  const reason = prompt('Remove ' + ticker + ' from watchlist?\\n\\nEnter a one-line reason (required by doctrine):', '');
  if (!reason || !reason.trim()) return;
  // Single-quote-shell-quote: wrap in single quotes, replace any embedded single quote with '\\''
  const r = reason.trim().replace(/'/g, "'\\\\''");
  const cmd = "python3 .claude/skills/watchlist/wl.py remove " + ticker + " -r '" + r + "' --yes";
  navigator.clipboard.writeText(cmd).then(function() {
    alert('Command copied to clipboard. Paste in terminal to remove:\\n\\n' + cmd);
  }, function() {
    // Clipboard write can fail under restricted contexts; fall back to a prompt with the command
    prompt('Copy this command and run in terminal:', cmd);
  });
}

// Prospectus action forms — inline form per button with live command preview.
// Calc R is special: shows math result inline, optional "append to journal" cmd.
(function() {
  const J = 'python3 .claude/skills/journal/j.py';
  // Shell-quote a string for safe paste — wrap in double quotes, escape inner quote and backslash.
  function shq(s) {
    if (s == null) return '""';
    return '"' + String(s).replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"') + '"';
  }
  function num(s) { const n = parseFloat(s); return isNaN(n) ? null : n; }
  function nums(s) { // comma list → array of floats or null if any bad
    if (!s) return null;
    const parts = String(s).split(',').map(x => x.trim()).filter(Boolean);
    const out = parts.map(parseFloat);
    return out.some(isNaN) ? null : out;
  }
  // Action configs. Each returns { title, fields, build(values) → {cmd, valid, hint} }
  const ACTIONS = {
    'live-paper': (stem) => ({
      title: 'Live (paper)',
      fields: [
        {name: 'fill',   label: 'Fill price', type: 'number', step: '0.01', placeholder: 'e.g. 15.39'},
        {name: 'shares', label: 'Shares',     type: 'number', step: '1',    placeholder: 'e.g. 354'},
        {name: 'time',   label: 'Time (ET)',  type: 'text',                placeholder: 'YYYY-MM-DD HH:MM ET', help: 'When the order filled.'},
        {name: 'notes',  label: 'Notes',      type: 'text',                placeholder: 'optional context'},
      ],
      build: (v) => {
        const valid = v.fill && v.shares && v.time;
        let cmd = `${J} live ${stem} --paper`;
        if (v.fill)   cmd += ` --fill ${v.fill}`;
        if (v.shares) cmd += ` --shares ${v.shares}`;
        if (v.time)   cmd += ` --time ${shq(v.time)}`;
        if (v.notes)  cmd += ` --notes ${shq(v.notes)}`;
        return {cmd, valid, hint: valid ? '' : 'fill / shares / time required'};
      },
    }),
    'live-real': (stem) => ({
      title: 'Live (real)',
      fields: [
        {name: 'fill',   label: 'Fill price', type: 'number', step: '0.01', placeholder: 'e.g. 15.39'},
        {name: 'shares', label: 'Shares',     type: 'number', step: '1',    placeholder: 'e.g. 354'},
        {name: 'time',   label: 'Time (ET)',  type: 'text',                placeholder: 'YYYY-MM-DD HH:MM ET'},
        {name: 'notes',  label: 'Notes',      type: 'text',                placeholder: 'optional context'},
      ],
      build: (v) => {
        const valid = v.fill && v.shares && v.time;
        let cmd = `${J} live ${stem} --real`;
        if (v.fill)   cmd += ` --fill ${v.fill}`;
        if (v.shares) cmd += ` --shares ${v.shares}`;
        if (v.time)   cmd += ` --time ${shq(v.time)}`;
        if (v.notes)  cmd += ` --notes ${shq(v.notes)}`;
        return {cmd, valid, hint: valid ? '' : 'fill / shares / time required'};
      },
    }),
    'update': (stem) => ({
      title: 'Add update note',
      fields: [
        {name: 'notes', label: 'Notes', type: 'textarea', placeholder: 'e.g. Scaled half at TP1 17.65, trailing remainder behind 20-EMA'},
      ],
      build: (v) => {
        const valid = !!v.notes;
        return {cmd: `${J} update ${stem} --notes ${shq(v.notes || '')}`, valid, hint: valid ? '' : 'note text required'};
      },
    }),
    'calc-r': (stem) => ({
      title: 'Calc R — live in browser (no CLI needed unless you want to log)',
      fields: [
        {name: 'entry',  label: 'Entry',  type: 'number', step: '0.0001', placeholder: 'e.g. 15.39'},
        {name: 'stop',   label: 'Stop',   type: 'number', step: '0.0001', placeholder: 'e.g. 14.26'},
        {name: 'exit',   label: 'Exit(s)', type: 'text',                  placeholder: 'single: 17.65  OR partial: 17.65,17.20', help: 'Comma-list for partial fills.'},
        {name: 'shares', label: 'Shares',  type: 'text',                  placeholder: 'single: 354  OR per-leg: 177,177'},
      ],
      mode: 'calc',  // signal to renderer
      build: (v) => {
        const entry = num(v.entry), stop = num(v.stop);
        const exits = nums(v.exit), shares = v.shares ? nums(v.shares) : null;
        if (entry == null || stop == null || !exits) return {valid: false, hint: 'fill in entry, stop, and exit(s) to see R'};
        if (entry <= stop) return {valid: false, hint: 'entry must be > stop for a long', invalid: true};
        const sharesArr = shares || exits.map(_ => 1);
        if (sharesArr.length !== exits.length) return {valid: false, hint: `${sharesArr.length} shares vs ${exits.length} exits — counts must match`, invalid: true};
        const riskPerShare = entry - stop;
        let totalPl = 0, totalRisk = 0;
        const legs = exits.map((px, i) => {
          const sh = sharesArr[i];
          const pl = (px - entry) * sh;
          const risk = riskPerShare * sh;
          totalPl += pl; totalRisk += risk;
          return {px, sh, pl, risk, r: (px - entry) / riskPerShare};
        });
        const blended = totalRisk ? totalPl / totalRisk : 0;
        const result = blended >= 0.1 ? 'win' : blended <= -0.1 ? 'loss' : 'scratch';
        const recordPrice = exits[exits.length - 1];
        const appendCmd = `${J} r --entry ${entry} --stop ${stop} --exit ${exits.join(',')} --shares ${sharesArr.join(',')} --append ${stem}`;
        return {
          valid: true, calc: true,
          riskPerShare, legs, totalPl, totalRisk, blended, result, recordPrice,
          appendCmd,
        };
      },
    }),
    'close-win': (stem) => ({
      title: 'Close (result = win)',
      fields: [
        {name: 'entry',  label: 'Entry',   type: 'number', step: '0.0001', placeholder: 'e.g. 15.39'},
        {name: 'stop',   label: 'Stop',    type: 'number', step: '0.0001', placeholder: 'e.g. 14.26'},
        {name: 'exit',   label: 'Exit(s)', type: 'text',                  placeholder: 'single: 17.65  OR: 17.65,17.20'},
        {name: 'shares', label: 'Shares',  type: 'text',                  placeholder: 'single: 354  OR: 177,177'},
        {name: 'notes',  label: 'Notes',   type: 'textarea',              placeholder: 'exit context'},
      ],
      build: (v) => closeCmd(stem, 'win', v),
    }),
    'close-loss': (stem) => ({
      title: 'Close (result = loss)',
      fields: [
        {name: 'entry',  label: 'Entry',   type: 'number', step: '0.0001', placeholder: 'e.g. 15.39'},
        {name: 'stop',   label: 'Stop',    type: 'number', step: '0.0001', placeholder: 'e.g. 14.26'},
        {name: 'exit',   label: 'Exit(s)', type: 'text',                  placeholder: 'e.g. 14.26'},
        {name: 'shares', label: 'Shares',  type: 'text',                  placeholder: 'e.g. 354'},
        {name: 'notes',  label: 'Notes',   type: 'textarea',              placeholder: 'why we stopped out'},
      ],
      build: (v) => closeCmd(stem, 'loss', v),
    }),
    'mark-dead': (stem) => ({
      title: 'Mark dead (setup never triggered)',
      fields: [
        {name: 'reason', label: 'Reason', type: 'textarea',
         placeholder: 'e.g. Trigger never fired by Jun 17 expiry; AUPH broke SMA50 with NFP whipsaw'},
      ],
      build: (v) => ({
        cmd: `${J} dead ${stem} --reason ${shq(v.reason || '')}`,
        valid: !!v.reason, hint: v.reason ? '' : 'reason required',
      }),
    }),
  };

  function closeCmd(stem, result, v) {
    const entry = num(v.entry), stop = num(v.stop);
    const exitsRaw = (v.exit || '').trim(), sharesRaw = (v.shares || '').trim();
    if (entry == null || stop == null || !exitsRaw || !sharesRaw) {
      return {cmd: `${J} close ${stem} --result ${result} --entry _ENTRY_ --stop _STOP_ --exit _EXIT_ --shares _N_ --notes ${shq(v.notes || '')}`,
              valid: false, hint: 'entry / stop / exit(s) / shares required for auto-R'};
    }
    if (entry <= stop) return {cmd: '', valid: false, hint: 'entry must be > stop for a long', invalid: true};
    const exits = nums(exitsRaw), shares = nums(sharesRaw);
    if (!exits || !shares || exits.length !== shares.length) {
      return {cmd: '', valid: false, hint: 'exit and shares must be matching comma-lists', invalid: true};
    }
    let cmd = `${J} close ${stem} --result ${result} --entry ${entry} --stop ${stop} --exit ${exitsRaw} --shares ${sharesRaw}`;
    if (v.notes) cmd += ` --notes ${shq(v.notes)}`;
    // Also compute R preview so user sees what it will become
    const riskPerShare = entry - stop;
    let totalPl = 0, totalRisk = 0;
    exits.forEach((px, i) => { totalPl += (px - entry) * shares[i]; totalRisk += riskPerShare * shares[i]; });
    const blended = totalRisk ? totalPl / totalRisk : 0;
    return {cmd, valid: true, hint: `→ R-multiple will be ${blended >= 0 ? '+' : ''}${blended.toFixed(2)}R`};
  }

  function buildForm(host, actionKey, stem) {
    const def = ACTIONS[actionKey](stem);
    host.innerHTML = '';
    host.classList.add('open');
    const form = document.createElement('div');
    form.className = 'action-form open';
    form.innerHTML = `
      <div class="form-title">${def.title}</div>
      ${def.fields.map(f => `
        <div class="form-row">
          <label for="af_${f.name}">${f.label}</label>
          ${f.type === 'textarea'
            ? `<textarea id="af_${f.name}" name="${f.name}" placeholder="${f.placeholder || ''}"></textarea>`
            : `<input id="af_${f.name}" name="${f.name}" type="${f.type}" ${f.step ? `step="${f.step}"` : ''} placeholder="${f.placeholder || ''}" />`}
          ${f.help ? `<div class="help">${f.help}</div>` : ''}
        </div>
      `).join('')}
      <div class="preview-label">Command preview</div>
      <div class="preview" data-preview>(fill the form to generate)</div>
      <div class="form-actions">
        <button type="button" class="primary" data-copy>Copy command</button>
        <button type="button" class="secondary" data-close>Close form</button>
      </div>
    `;
    host.appendChild(form);

    const inputs = form.querySelectorAll('input,textarea');
    const previewEl = form.querySelector('[data-preview]');
    const copyBtn   = form.querySelector('[data-copy]');
    const closeBtn  = form.querySelector('[data-close]');

    function values() {
      const v = {};
      inputs.forEach(i => v[i.name] = i.value);
      return v;
    }
    function refresh() {
      const v = values();
      const r = def.build(v);
      if (def.mode === 'calc') {
        // Calc R: render result block instead of CLI preview
        if (!r.valid) {
          previewEl.innerHTML = `<span class="preview-invalid">${r.hint || 'fill the form'}</span>`;
          copyBtn.disabled = true; copyBtn.textContent = 'Copy command';
          return;
        }
        const sign = r.blended >= 0 ? '+' : '';
        const cls = r.blended >= 0 ? 'pos' : 'neg';
        const legsTbl = r.legs.length > 1
          ? r.legs.map((l, i) => `<div>  Leg ${i+1}: ${l.sh} sh @ $${l.px.toFixed(4)} → $${l.pl.toFixed(2)} (${l.r >= 0 ? '+' : ''}${l.r.toFixed(2)}R)</div>`).join('')
          : '';
        previewEl.innerHTML = `<div class="calc-result">
          <div>Risk / share: $${r.riskPerShare.toFixed(4)}</div>
          ${legsTbl}
          <div>Total P/L: <span class="${cls}">$${r.totalPl.toFixed(2)}</span> on $${r.totalRisk.toFixed(2)} risk</div>
          <div class="big ${cls}">Blended R: ${sign}${r.blended.toFixed(2)}R</div>
          <div style="margin-top:6px;color:var(--dim);font-size:11px">Suggested close --result ${r.result}, --price ${r.recordPrice}</div>
        </div>`;
        copyBtn.disabled = false;
        copyBtn.textContent = 'Copy "append to journal" cmd';
        copyBtn.dataset.cmd = r.appendCmd;
        return;
      }
      if (r.invalid) {
        previewEl.innerHTML = `<span class="preview-invalid">⚠ ${r.hint}</span>`;
        copyBtn.disabled = true; copyBtn.textContent = 'Copy command';
        return;
      }
      previewEl.textContent = r.cmd;
      copyBtn.disabled = !r.valid;
      copyBtn.textContent = r.valid ? 'Copy command' : (`Need: ${r.hint}`);
      copyBtn.dataset.cmd = r.cmd;
      if (r.hint && r.valid) {
        previewEl.insertAdjacentHTML('beforeend', `<div style="color:var(--green);font-size:11px;margin-top:4px">${r.hint}</div>`);
      }
    }
    inputs.forEach(i => i.addEventListener('input', refresh));
    refresh();
    inputs[0] && inputs[0].focus();

    copyBtn.addEventListener('click', () => {
      const cmd = copyBtn.dataset.cmd || previewEl.textContent;
      if (!cmd) return;
      navigator.clipboard.writeText(cmd).then(() => {
        copyBtn.classList.add('copied');
        const orig = copyBtn.textContent;
        copyBtn.textContent = '✓ copied — paste in terminal';
        setTimeout(() => { copyBtn.classList.remove('copied'); copyBtn.textContent = orig; }, 2400);
      });
    });
    closeBtn.addEventListener('click', () => {
      host.innerHTML = '';
      host.classList.remove('open');
      // Also deactivate any active button
      const card = host.closest('.prospectus');
      card && card.querySelectorAll('.actions button.active').forEach(b => b.classList.remove('active'));
    });
  }

  document.querySelectorAll('.prospectus').forEach(card => {
    const stem = card.dataset.stem;
    const host = card.querySelector('.action-form-host');
    if (!host) return;
    card.querySelectorAll('.actions .ta-action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const alreadyActive = btn.classList.contains('active');
        card.querySelectorAll('.actions button').forEach(b => b.classList.remove('active'));
        if (alreadyActive) {
          host.innerHTML = '';
          host.classList.remove('open');
          return;
        }
        btn.classList.add('active');
        buildForm(host, action, stem);
      });
    });
  });
})();

// Click column header to sort
document.querySelectorAll('table').forEach(t => {
  const headers = t.querySelectorAll('th');
  headers.forEach((th, idx) => {
    th.addEventListener('click', () => {
      const tbody = t.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const asc = !th.classList.contains('sort-asc');
      headers.forEach(h => h.classList.remove('sort-asc','sort-desc'));
      th.classList.add(asc ? 'sort-asc' : 'sort-desc');
      rows.sort((a,b) => {
        const av = a.children[idx]?.dataset.sort ?? a.children[idx]?.textContent.trim() ?? '';
        const bv = b.children[idx]?.dataset.sort ?? b.children[idx]?.textContent.trim() ?? '';
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return asc ? an-bn : bn-an;
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      });
      rows.forEach(r => tbody.appendChild(r));
    });
  });
});

// ── Risk Simulator ─────────────────────────────────────────────
// Uses window.TA_SIM (injected by Python) which holds:
//   { config: {account, risk_pct, heat_used, heat_max, phase}, regime: {label, score, rr_floor},
//     macro_events: [{type, hours_until, date_et, note}, ...],
//     tickers: { "AAPL": { price, rsi14, sma20, sma50, sma200, atr14, sma50_slope_pct, vol_ratio, change_pct, next_earnings, name, status_label }, ... } }

(function(){
  const sim = window.TA_SIM;
  if (!sim) return;
  const sel = document.getElementById('sim-ticker');
  const eIn = document.getElementById('sim-entry');
  const sIn = document.getElementById('sim-stop');
  const t1In = document.getElementById('sim-tp1');
  const t2In = document.getElementById('sim-tp2');
  const szIn = document.getElementById('sim-size');
  const reset = document.getElementById('sim-prefill');
  if (!sel) return;
  // Populate ticker dropdown — group by market for clarity
  const tickers = Object.keys(sim.tickers).sort();
  const usTickers     = tickers.filter(t => (sim.tickers[t].market || 'us') === 'us');
  const klseTickers   = tickers.filter(t => (sim.tickers[t].market || 'us') === 'klse');
  const cryptoTickers = tickers.filter(t => (sim.tickers[t].market || 'us') === 'crypto');
  function optHtml(arr) {
    return arr.map(t => {
      const m = sim.tickers[t];
      const name = (m.name || '').slice(0, 30);
      const cur = m.currency || 'USD';
      return `<option value="${t}">${t} · ${name} (${cur})</option>`;
    }).join('');
  }
  let html = '<option value="">— select a watchlist ticker —</option>';
  if (usTickers.length)     html += `<optgroup label="US (USD)">${optHtml(usTickers)}</optgroup>`;
  if (klseTickers.length)   html += `<optgroup label="KLSE (MYR)">${optHtml(klseTickers)}</optgroup>`;
  if (cryptoTickers.length) html += `<optgroup label="Crypto (USD, spot)">${optHtml(cryptoTickers)}</optgroup>`;
  sel.innerHTML = html;

  // Currency-aware decimals: crypto can be $0.0001 (HBAR) → 6dp; KLSE 0.130 → 4dp; US $290 → 2dp
  function dpFor(price) {
    if (price == null) return 2;
    if (price < 0.1) return 6;
    if (price < 5)   return 4;
    return 2;
  }
  // lot === 0 → fractional (crypto): no rounding, truncate to 6dp.
  // lot === 1 → US single shares.
  // lot >= 100 → KLSE board lots.
  function roundToLot(rawShares, lot) {
    if (lot === 0) return Math.floor(rawShares * 1e6) / 1e6;
    if (!lot || lot <= 1) return Math.floor(rawShares);
    return Math.floor(rawShares / lot) * lot;
  }
  function unitLabel(market) { return market === 'crypto' ? 'units' : 'sh'; }
  function fxFactor(market) {
    if (market === 'klse') {
      const r = (sim.fx && sim.fx.MYR_USD) || null;
      return r || null;  // null = FX missing
    }
    return 1.0;
  }
  function curSymbol(currency) { return currency === 'MYR' ? 'MYR ' : '$'; }

  function prefillFromTicker() {
    const t = sim.tickers[sel.value];
    if (!t || t.price == null) return;
    const p = t.price;
    const atr = t.atr14 || (p * 0.03);
    const sma20 = t.sma20;
    const dp = dpFor(p);
    eIn.value = (sma20 || p).toFixed(dp);
    const atrStop = parseFloat(eIn.value) - 1.5 * atr;
    const pctStop = parseFloat(eIn.value) * 0.95;
    sIn.value = Math.min(atrStop, pctStop).toFixed(dp);
    const risk = parseFloat(eIn.value) - parseFloat(sIn.value);
    t1In.value = (parseFloat(eIn.value) + 2 * risk).toFixed(dp);
    t2In.value = '';
    // Prefill Size to the doctrine maximum so the field is always an editable starting point.
    // Use the same formula compute() uses below; lot_size is honored as-is (0 = crypto fractional).
    const fxNow = fxFactor(t.market || 'us');
    const rpsUSD = risk * ((t.market === 'klse' && fxNow == null) ? 1 : (fxNow || 1));
    const lot = t.lot_size ?? 1;
    const maxShares = roundToLot((sim.config.account * sim.config.risk_pct) / rpsUSD, lot);
    szIn.value = (t.market === 'crypto') ? maxShares.toFixed(6).replace(/\.?0+$/, '') : maxShares.toString();
    // Update field labels to reflect detected market currency
    updateFormLabels(t);
    compute();
  }
  function updateFormLabels(t) {
    const cur = (t && t.currency) || 'USD';
    const symbol = curSymbol(cur);
    document.querySelectorAll('.sim-cur-label').forEach(el => { el.textContent = symbol; });
    document.querySelectorAll('.sim-unit-label').forEach(el => { el.textContent = unitLabel(t && t.market); });
    const banner = document.getElementById('sim-market-banner');
    if (!banner) return;
    if (!t) { banner.textContent = ''; return; }
    if (t.market === 'klse') {
      const fx = fxFactor('klse');
      const fxStr = fx ? `1 MYR = $${fx.toFixed(4)}` : 'FX unavailable — sizing will fall back to MYR-direct';
      banner.innerHTML = `<b>Market:</b> Bursa Malaysia (KLSE) · lot size 100 · ${fxStr}` +
        (t.pe || t.dy ? ` · <span style="color:var(--dim)">P/E ${t.pe ?? '—'} · P/B ${t.pb ?? '—'} · DY ${t.dy ?? '—'}% · ROE ${t.roe ?? '—'}%</span>` : '');
    } else if (t.market === 'crypto') {
      const atrPctStr = t.atr_pct != null ? `ATR(14) ${t.atr_pct.toFixed(2)}%` : 'ATR unavailable';
      const fundStr = t.funding_annualized_pct != null
        ? `funding ${t.funding_annualized_pct >= 0 ? '+' : ''}${t.funding_annualized_pct.toFixed(1)}% APR`
        : 'funding unavailable';
      const cr = (sim.crypto_regime || {});
      const fngStr = cr.fng != null ? ` · F&G ${cr.fng} ${cr.fng_label || ''}` : '';
      banner.innerHTML = `<b>Market:</b> Crypto spot · fractional units · USD-native · ${atrPctStr} · ${fundStr}${fngStr} · <span style="color:var(--dim)">Phase 1: spot long only, no perps</span>`;
    } else {
      banner.innerHTML = `<b>Market:</b> US (NASDAQ/NYSE) · single-share lots · USD account`;
    }
  }
  sel.addEventListener('change', prefillFromTicker);
  if (reset) reset.addEventListener('click', prefillFromTicker);
  [eIn, sIn, t1In, t2In, szIn].forEach(i => i.addEventListener('input', compute));

  function compute() {
    const out = document.getElementById('sim-result');
    const tkr = sel.value;
    const t = sim.tickers[tkr];
    const entry = parseFloat(eIn.value);
    const stop = parseFloat(sIn.value);
    const tp1 = parseFloat(t1In.value);
    const tp2 = parseFloat(t2In.value);

    if (!tkr || isNaN(entry) || isNaN(stop) || isNaN(tp1)) {
      out.innerHTML = '<div class="sim-verdict pending">PENDING — fill in ticker, entry, stop, TP1</div><div class="sim-blurb">Pick a watchlist ticker to auto-fill suggested levels, then tune to your actual plan.</div>';
      return;
    }
    if (entry <= stop) {
      out.innerHTML = '<div class="sim-verdict no">🛑 INVALID — stop must be BELOW entry for a long</div>';
      return;
    }
    if (tp1 <= entry) {
      out.innerHTML = '<div class="sim-verdict no">🛑 INVALID — TP1 must be ABOVE entry for a long</div>';
      return;
    }

    // Market context
    const market   = (t && t.market) || 'us';
    const currency = (t && t.currency) || 'USD';
    const lotSize  = (t && t.lot_size != null) ? t.lot_size : 1;  // 0 = crypto fractional; default 1 for unknown markets
    const fxAvail  = market === 'klse' ? ((sim.fx && sim.fx.MYR_USD) || null) : 1.0;
    // Sizing math — entry/stop are in LOCAL currency; account is USD.
    // Convert risk-per-share to USD, derive shares from max_risk_USD, then round to lot.
    const acct = sim.config.account;
    const riskPct = sim.config.risk_pct;
    const maxRiskUSD = acct * riskPct;
    const riskPerShareLocal = entry - stop;
    const riskPerShareUSD = riskPerShareLocal * (fxAvail || 1);
    // Doctrine §5: derive the MAXIMUM position size that keeps trade-risk ≤ riskPct of equity.
    // Operator chooses the actual size in the Size field (auto-prefilled to the max);
    // sim's job is to verify it stays within doctrine. Single sizing path for all markets.
    const fxMissing = market === 'klse' && fxAvail == null;
    const riskPerShareForSize = fxMissing ? riskPerShareLocal : riskPerShareUSD;
    const doctrineMaxShares = roundToLot(maxRiskUSD / riskPerShareForSize, lotSize);

    // Size field is always prefilled with doctrineMaxShares (see prefillFromTicker).
    // Treat the field as a plain editable number; only fall back to the max if it's empty/invalid.
    const sizeRaw = parseFloat(szIn && szIn.value);
    const shares = isNaN(sizeRaw) || sizeRaw <= 0
      ? doctrineMaxShares
      : roundToLot(sizeRaw, lotSize);
    const oversize = shares > doctrineMaxShares + 1e-9;

    const actualRiskUSD = shares * riskPerShareForSize;
    const notionalLocal = shares * entry;
    const notionalUSD   = fxMissing ? null
                        : market === 'us' ? notionalLocal
                        : notionalLocal * fxAvail;
    // Format share count consistently (fractional for crypto, integer-grouped for stocks).
    const fmtShares = (s) => market === 'crypto'
      ? s.toLocaleString(undefined, {maximumFractionDigits: 6, minimumFractionDigits: Math.min(6, Math.max(2, 6 - Math.floor(Math.log10(Math.max(s, 1e-9)))))})
      : s.toLocaleString();
    const actualRiskPct = (actualRiskUSD / acct) * 100;
    const capPct = riskPct * 100;
    const notionalPctEquity = ((notionalUSD ?? notionalLocal) / acct) * 100;
    const rrTp1 = (tp1 - entry) / riskPerShareLocal;
    const rrTp2 = isNaN(tp2) ? null : (tp2 - entry) / riskPerShareLocal;

    // Regime-adjusted R:R floor
    const rrFloor = sim.regime.rr_floor || 1.5;
    const heatAfter = sim.config.heat_used + actualRiskUSD;
    const heatHeadroom = sim.config.heat_max - heatAfter;

    // Currency formatting helpers
    const sym = curSymbol(currency);
    const dp = dpFor(entry);
    const fLoc = (v) => `${sym}${Number(v).toFixed(dp)}`;

    // Gate evaluations
    const gates = [];
    function g(ok, label, why) { gates.push({ok, label, why}); }

    // 1. Phase 1 compatibility (spot long only — always true for this simulator)
    g('ok', 'Phase 1 spot long', 'long-only entry, no options/leverage');

    // 2. Trend filter (cached) — universal
    if (t.sma200 != null && t.sma50 != null && t.price != null) {
      const trendOk = t.price > t.sma50 && t.sma50 > t.sma200;
      g(trendOk ? 'ok' : 'bad', 'Trend filter',
        trendOk ? `price > SMA50 > SMA200 (${fLoc(t.price)} > ${fLoc(t.sma50)} > ${fLoc(t.sma200)})`
                : `fails (price ${fLoc(t.price)}, SMA50 ${fLoc(t.sma50)}, SMA200 ${fLoc(t.sma200)})`);
    } else if (t.sma200 == null) {
      g('warn', 'Trend filter', 'no SMA200 — recent IPO, P1 cannot apply cleanly');
    } else {
      g('warn', 'Trend filter', 'insufficient indicator data');
    }

    // 3. SMA50 direction
    if (t.sma50_slope_pct != null) {
      const slopeOk = t.sma50_slope_pct >= -0.5;
      g(slopeOk ? 'ok' : 'warn', 'SMA50 direction',
        `slope ${t.sma50_slope_pct >= 0 ? '+' : ''}${t.sma50_slope_pct.toFixed(2)}% / 5d (${slopeOk ? 'rising/flat' : 'falling — trend deteriorating'})`);
    }

    // 4. RSI zone
    if (t.rsi14 != null) {
      const r = t.rsi14;
      let st = 'ok', why = `RSI ${r.toFixed(1)} in P1 entry zone (35-50)`;
      if (r > 70) { st = 'bad'; why = `RSI ${r.toFixed(1)} > 70 (overbought)`; }
      else if (r < 30) { st = 'warn'; why = `RSI ${r.toFixed(1)} < 30 (oversold — wait for trigger)`; }
      else if (r > 60) { st = 'warn'; why = `RSI ${r.toFixed(1)} > 60 (extended, no clean pullback)`; }
      else if (r > 50) { st = 'warn'; why = `RSI ${r.toFixed(1)} above 35-50 entry band`; }
      g(st, 'RSI zone', why);
    }

    // 5. SMA20 proximity (pullback shape) — thresholds scale with ATR% for high-vol assets (crypto)
    if (t.sma20 != null) {
      const vs20 = (t.price / t.sma20 - 1) * 100;
      // Default (US/KLSE-tuned) thresholds: tag ±3%, warn 3-10%, bad >10% or <-5%
      let warnAbove = 3, badAbove = 10, badBelow = -5;
      if (market === 'crypto' && t.atr_pct != null && t.atr_pct > 2.5) {
        // Scale: a 5% ATR/day asset needs 2× wider bands than a 1% one.
        const k = Math.max(1, t.atr_pct / 2.5);
        warnAbove = 3 * k; badAbove = 10 * k; badBelow = -5 * k;
      }
      let st = 'ok', why = `price ${vs20 >= 0 ? '+' : ''}${vs20.toFixed(1)}% from SMA20 (tag)`;
      if (vs20 > badAbove) { st = 'bad'; why = `+${vs20.toFixed(1)}% above SMA20 — extended (band ${badAbove.toFixed(1)}%)`; }
      else if (vs20 > warnAbove) { st = 'warn'; why = `+${vs20.toFixed(1)}% above SMA20 — not yet a clean tag (band ${warnAbove.toFixed(1)}%)`; }
      else if (vs20 < badBelow) { st = 'bad'; why = `${vs20.toFixed(1)}% below SMA20 — broken structure (band ${badBelow.toFixed(1)}%)`; }
      g(st, 'Pullback shape', why);
    }

    // 6. Volume profile
    if (t.vol_ratio != null) {
      const v = t.vol_ratio;
      let st = 'ok', why = `5d vol ${v.toFixed(2)}× the 30d avg (healthy pullback)`;
      if (v > 1.3) { st = 'bad'; why = `5d vol ${v.toFixed(2)}× the 30d avg (distribution risk)`; }
      else if (v > 1.1) { st = 'warn'; why = `5d vol ${v.toFixed(2)}× the 30d avg (elevated)`; }
      g(st, 'Volume profile', why);
    }

    // 7. Earnings window — US: hard gate via yfinance date; KLSE: skip with manual-check note
    if (market === 'us') {
      if (t.next_earnings) {
        const ed = new Date(t.next_earnings + 'T00:00:00Z');
        const now = new Date();
        const calDays = Math.floor((ed - now) / (1000*60*60*24));
        if (calDays >= 0 && calDays <= 10) {
          g('bad', 'Earnings window', `next earnings in ${calDays}d — inside 7 trading-day pre-window`);
        } else if (calDays >= 0) {
          g('ok', 'Earnings window', `next earnings in ${calDays}d (clear)`);
        } else {
          g('ok', 'Earnings window', 'no earnings date / passed');
        }
      } else {
        g('warn', 'Earnings window', 'no earnings date in cache');
      }
    } else if (market === 'klse') {
      // KLSE earnings/announcement halt — uses klse-announcements cache
      const nextFr   = t.fr_next_expected_filing_by;
      const upcoming = t.upcoming_events || [];
      const annTs    = t.ann_fetched_at;
      if (!annTs) {
        g('warn', 'Earnings / announcement window',
          'no klse-announcements cache — run `python3 .claude/skills/klse-announcements/klse_announcements.py` to populate');
      } else {
        const now = new Date();
        const todayMs = now.getTime();
        // Next Financial Results filing — Bursa mandates within 60 days of period end.
        // Treat 7 trading days (~10 cal days) BEFORE the 60-day deadline as the halt window,
        // and the 14-day window before that as a "filing could come early" warning.
        if (nextFr) {
          const filingBy = new Date(nextFr + 'T00:00:00Z').getTime();
          const calDays = Math.floor((filingBy - todayMs) / (1000*60*60*24));
          if (calDays >= 0 && calDays <= 10) {
            g('bad', 'Q-results filing window',
              `next Q-results filing-by deadline in ${calDays}d (${nextFr}) — inside the 7 trading-day pre-window. Filing could land any day.`);
          } else if (calDays >= 0 && calDays <= 20) {
            g('warn', 'Q-results filing window',
              `next Q-results filing-by deadline in ${calDays}d (${nextFr}). Filing often comes 7-14d before the deadline — re-check before entry.`);
          } else if (calDays >= 0) {
            g('ok', 'Q-results filing window',
              `next Q-results filing-by deadline in ${calDays}d (${nextFr}) — clear`);
          } else {
            g('warn', 'Q-results filing window',
              `derived next-filing deadline has passed (${nextFr}); klse-announcements cache may be stale — refresh it`);
          }
        } else {
          g('warn', 'Q-results filing window',
            'no recent Financial Results in cache — refresh klse-announcements');
        }
        // Upcoming ex-div / AGM / EGM within 7 days
        const within7 = upcoming.filter(e => {
          const d = new Date(e.date + 'T00:00:00Z').getTime();
          const calDays = (d - todayMs) / (1000*60*60*24);
          return calDays >= 0 && calDays <= 7;
        });
        const within30 = upcoming.filter(e => {
          const d = new Date(e.date + 'T00:00:00Z').getTime();
          const calDays = (d - todayMs) / (1000*60*60*24);
          return calDays > 7 && calDays <= 30;
        });
        if (within7.length) {
          const e = within7[0];
          const calDays = Math.floor((new Date(e.date + 'T00:00:00Z').getTime() - todayMs) / (1000*60*60*24));
          g('bad', 'Upcoming corporate event',
            `${e.type.toUpperCase()} on ${e.date} (${calDays}d away) — gap risk / dividend price adjustment. Halt new exposure.`);
        } else if (within30.length) {
          const events = within30.map(e => `${e.type.toUpperCase()} ${e.date}`).join(', ');
          g('warn', 'Upcoming corporate events',
            `${within30.length} event(s) in next 30d: ${events}. Outside halt window but within trade duration.`);
        } else {
          g('ok', 'Upcoming corporate events', 'none flagged in next 30d');
        }
      }
    } else if (market === 'crypto') {
      // §5 48h-halt gate, sourced from .claude/cache/crypto_unlocks/{COIN}.json
      const ue = t.unlock_entry;
      if (!ue) {
        g('warn', 'Token unlock window',
          'no entry in crypto-unlocks cache for ' + tkr + ' — run `python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py baseline` then use the `crypto-unlocks` WebFetch skill + `set` subcommand to record alts');
      } else if (ue._source_type === 'baseline_no_schedule') {
        g('ok', 'Token unlock window', ue.notes || 'no vesting schedule');
      } else if (ue._source_type === 'baseline_regular') {
        g('warn', 'Token unlock window', (ue.notes || 'regular emission — verify on tokenomist.ai'));
      } else if (ue.next_unlock == null) {
        g('warn', 'Token unlock window',
          'cache entry exists but no next-unlock recorded — refresh via the crypto-unlocks WebFetch skill');
      } else {
        const nu = ue.next_unlock;
        const ud = new Date(nu.date + 'T00:00:00Z');
        const calDays = Math.floor((ud - new Date()) / (1000*60*60*24));
        const pct = nu.pct_of_float;
        const pctStr = pct != null ? `${pct.toFixed(2)}% float` : 'size unknown';
        const typeStr = nu.type || 'unknown';
        if (calDays < 0) {
          g('warn', 'Token unlock window',
            `recorded ${typeStr} unlock date ${nu.date} has passed — refresh via crypto-unlocks WebFetch + \`set\``);
        } else if (calDays <= 2) {
          if (pct == null) {
            g('bad', 'Token unlock window',
              `${typeStr} unlock in ${calDays}d (${nu.date}); ${pctStr} — treat as inside 48h-halt window per doctrine §5`);
          } else if (pct >= 1.0) {
            g('bad', 'Token unlock window',
              `${typeStr} unlock in ${calDays}d (${nu.date}), ${pctStr} — inside 48h-halt window (doctrine §5)`);
          } else {
            g('warn', 'Token unlock window',
              `${typeStr} unlock in ${calDays}d (${nu.date}), ${pctStr} — inside 48h window but below 1% halt threshold`);
          }
        } else if (calDays <= 7) {
          g('warn', 'Token unlock window',
            `${typeStr} unlock in ${calDays}d (${nu.date}), ${pctStr} — outside 48h halt but within trade duration`);
        } else {
          g('ok', 'Token unlock window',
            `next ${typeStr} unlock in ${calDays}d (${nu.date}), ${pctStr}`);
        }
      }
    }

    // 8. Macro halt window (3 trading days = 72h)
    // US: hard gate per §5. KLSE: warning — US macro events transmit via risk-on/off but don't strictly halt KLSE trading.
    const nearest = sim.macro_events.find(e => e.hours_until >= 0 && e.hours_until <= 72);
    if (market === 'us') {
      if (nearest) {
        g('bad', 'Macro halt', `${nearest.type} in ${nearest.hours_until.toFixed(0)}h — inside 3-day pre-event window`);
      } else if (sim.macro_events.length > 0) {
        const next = sim.macro_events[0];
        g('ok', 'Macro halt', `next ${next.type} in ${(next.hours_until/24).toFixed(1)}d (clear)`);
      } else {
        g('warn', 'Macro halt', 'no upcoming events in cache');
      }
    } else if (market === 'klse') {
      if (nearest) {
        g('warn', 'US macro spillover',
          `${nearest.type} in ${nearest.hours_until.toFixed(0)}h — US event; affects KLSE via risk-on/off transmission. Not a hard halt but expect amplified vol.`);
      } else if (sim.macro_events.length > 0) {
        const next = sim.macro_events[0];
        g('ok', 'US macro spillover', `next US ${next.type} in ${(next.hours_until/24).toFixed(1)}d (clear)`);
      }
    } else if (market === 'crypto') {
      // Crypto trades 24/7 through US macro events — not a hard halt, but FOMC/CPI prints
      // routinely cause a 2-4% vol burst in BTC. Warn within 24h.
      const near24 = sim.macro_events.find(e => e.hours_until >= 0 && e.hours_until <= 24);
      if (near24) {
        g('warn', 'US macro spillover',
          `${near24.type} in ${near24.hours_until.toFixed(0)}h — crypto trades through it; expect a vol burst on the print. Consider sizing down or waiting.`);
      } else if (sim.macro_events.length > 0) {
        const next = sim.macro_events[0];
        g('ok', 'US macro spillover', `next US ${next.type} in ${(next.hours_until/24).toFixed(1)}d (no crypto halt)`);
      }

      // Crypto-specific: ATR% sanity on stop distance.
      if (t.atr14 != null && t.atr_pct != null) {
        const stopDistAtr = (entry - stop) / t.atr14;
        if (stopDistAtr < 1.0) {
          g('warn', 'Stop vs ATR', `stop ${stopDistAtr.toFixed(2)}× ATR(14) below entry — tight; likely to be wicked by normal noise (ATR ${t.atr_pct.toFixed(2)}%/day)`);
        } else if (stopDistAtr > 3.0) {
          g('warn', 'Stop vs ATR', `stop ${stopDistAtr.toFixed(2)}× ATR(14) below entry — wide; position size will be small and R:R harder to hit (ATR ${t.atr_pct.toFixed(2)}%/day)`);
        } else {
          g('ok', 'Stop vs ATR', `stop ${stopDistAtr.toFixed(2)}× ATR(14) (1-3× zone, healthy for ATR ${t.atr_pct.toFixed(2)}%/day)`);
        }
      } else {
        g('warn', 'Stop vs ATR', 'ATR unavailable — cannot validate stop distance against typical noise');
      }

      // Crypto-specific: Funding rate extreme (Binance perp proxy for spot crowding).
      if (t.funding_annualized_pct != null) {
        const f = t.funding_annualized_pct;
        if (f > 50) {
          g('warn', 'Perp funding', `${f.toFixed(1)}% APR — perps crowded long; spot longs face elevated flush risk on a funding-driven liquidation cascade`);
        } else if (f < -30) {
          g('ok', 'Perp funding', `${f.toFixed(1)}% APR — perps crowded short; squeeze fuel favors a long`);
        } else {
          g('ok', 'Perp funding', `${f.toFixed(1)}% APR — neutral positioning`);
        }
      } else {
        g('warn', 'Perp funding', 'Binance funding unavailable — cannot assess perp crowding');
      }

      // Crypto-specific: regime tilt nudges R:R expectations (informational, not a hard gate).
      const cr = (sim.crypto_regime || {});
      if (cr.score != null) {
        if (cr.score <= -0.4) {
          g('warn', 'Crypto regime', `${cr.label} (${cr.score.toFixed(2)}) — RISK-OFF tilt; consider waiting for confirmation or sizing down`);
        } else if (cr.score >= 0.4) {
          g('ok', 'Crypto regime', `${cr.label} (${cr.score.toFixed(2)}) — RISK-ON tilt favors longs`);
        } else {
          g('ok', 'Crypto regime', `${cr.label} (${cr.score.toFixed(2)}) — neutral`);
        }
      }
    }

    // 9. R:R floor (regime-adjusted)
    // Tolerance on the R:R compare — float precision can produce 1.9999999987 from cleanly
    // doctrine-passing inputs (e.g. entry 15.55, stop 14.77, TP1 17.11 → 2.0R exactly).
    // Compare at the display precision (2dp) to match what the user sees.
    const rrOk = Math.round(rrTp1 * 100) / 100 >= rrFloor;
    g(rrOk ? 'ok' : 'bad', `R:R floor (${rrFloor}R)`,
      `R:R to TP1 = ${rrTp1.toFixed(2)}R ${rrOk ? '≥' : '<'} ${rrFloor}R required under ${sim.regime.label}`);

    // 10. Doctrine per-trade risk cap — §5: trade-risk must not exceed riskPct of equity.
    const u = unitLabel(market);
    const capTail = oversize
      ? `ABOVE the ${capPct.toFixed(1)}% cap (max permitted: ${fmtShares(doctrineMaxShares)} ${u})`
      : `within the ${capPct.toFixed(1)}% cap`;
    g(oversize ? 'bad' : 'ok', 'Per-trade risk cap (§5)',
      `${fmtShares(shares)} ${u} = $${actualRiskUSD.toFixed(0)} risk = ${actualRiskPct.toFixed(2)}% account, ${capTail}`);

    // 11. Heat headroom (all currencies normalized to USD via fx)
    const heatOk = heatAfter <= sim.config.heat_max;
    g(heatOk ? 'ok' : 'bad', 'Heat headroom',
      `$${actualRiskUSD.toFixed(0)} USD added → $${heatAfter.toFixed(0)} of $${sim.config.heat_max} ceiling (headroom $${heatHeadroom.toFixed(0)})`);

    // 11. Entry sanity vs current price
    if (t.price != null) {
      const drift = (entry / t.price - 1) * 100;
      if (Math.abs(drift) > 5) {
        g('warn', 'Entry vs current', `entry ${drift >= 0 ? '+' : ''}${drift.toFixed(1)}% from cached price ${fLoc(t.price)} — recompute if filling near current`);
      } else {
        g('ok', 'Entry vs current', `entry ${drift >= 0 ? '+' : ''}${drift.toFixed(2)}% from cached price`);
      }
    }

    // 12. FX availability (KLSE only) — flag if MYR/USD rate missing
    if (market === 'klse') {
      if (fxMissing) {
        g('warn', 'FX availability', 'MYR/USD rate not available — sizing treats MYR as 1:1 USD (overstates risk). Refresh dashboard with --force.');
      }
      // 13. Lot size check — show informational note
      const sharesRaw = maxRiskUSD / Math.max(riskPerShareUSD, 0.0001);
      if (shares < sharesRaw * 0.9) {
        g('warn', 'Lot rounding', `wanted ${Math.floor(sharesRaw).toLocaleString()} sh, rounded down to ${shares.toLocaleString()} (lot of ${lotSize}). Effective risk below target.`);
      } else {
        g('ok', 'Lot rounding', `position size rounded to lot of ${lotSize} shares`);
      }
    }

    // Compute final verdict
    const hardBads = gates.filter(x => x.ok === 'bad');
    const warns = gates.filter(x => x.ok === 'warn');
    let verdictClass, verdictText, verdictBlurb;
    if (hardBads.length === 0 && warns.length === 0) {
      verdictClass = 'go'; verdictText = '🟢 GO — all gates pass';
      verdictBlurb = 'Doctrine-compliant entry under current regime. Set the order, write the journal.';
    } else if (hardBads.length === 0) {
      verdictClass = 'go'; verdictText = '🟡 GO WITH CAVEATS — ' + warns.length + ' warning(s)';
      verdictBlurb = `No hard gate failures. Review the yellow flags below; if they are acceptable, proceed with a journal entry.`;
    } else {
      verdictClass = 'no'; verdictText = '🔴 NO-TRADE — ' + hardBads.length + ' hard gate failure(s)';
      verdictBlurb = 'Doctrine refuses this entry. Either change the entry/stop/TP to satisfy the failing gate, or wait for the condition to change.';
    }

    const lotNote = lotSize > 1 ? ` <span style="font-weight:normal;color:var(--dim);font-size:11px">(lot ${lotSize})</span>`
                                : (lotSize === 0 ? ` <span style="font-weight:normal;color:var(--dim);font-size:11px">(fractional)</span>` : '');
    const notionalDisplay = (market === 'klse' && notionalUSD != null)
      ? `MYR ${notionalLocal.toLocaleString(undefined,{maximumFractionDigits:0})} <span style="font-weight:normal;color:var(--dim);font-size:11px">≈ $${notionalUSD.toLocaleString(undefined,{maximumFractionDigits:0})}</span>`
      : `${sym}${notionalLocal.toLocaleString(undefined,{maximumFractionDigits:0})} <span style="font-weight:normal;color:var(--dim);font-size:11px">(${notionalPctEquity.toFixed(1)}% acct)</span>`;
    const sharesDisplay = fmtShares(shares);
    const unit = unitLabel(market);
    // Build the "Create prospectus" command (only enabled when verdict is GO or GO-WITH-CAVEATS)
    function shqSim(s){ if(s==null) return "''"; return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
    const tName = (t && t.name) ? t.name : tkr;
    const phaseMode = 'paper'; // doctrine: Phase 1 = paper only
    const prospParts = [
      `python3 .claude/skills/journal/j.py new ${tkr}`,
      `--market ${market}`,
      `--entry ${entry}`,
      `--stop ${stop}`,
      `--tp1 ${tp1}`,
    ];
    if (!isNaN(tp2))      prospParts.push(`--tp2 ${tp2}`);
    if (shares)           prospParts.push(`--shares ${shares}`);
    prospParts.push(`--account ${acct}`);
    prospParts.push(`--risk-pct ${riskPct}`);
    prospParts.push(`--heat-used ${sim.config.heat_used}`);
    prospParts.push(`--heat-max ${sim.config.heat_max}`);
    prospParts.push(`--phase 1`);
    prospParts.push(`--phase-mode ${phaseMode}`);
    prospParts.push(`--regime ${shqSim(sim.regime.label)}`);
    prospParts.push(`--rr-floor ${rrFloor.toFixed(2)}R`);
    if (t && t.rsi14 != null)   prospParts.push(`--rsi ${t.rsi14.toFixed(1)}`);
    if (t && (t.atr_pct != null || (t.atr14 && t.price))) {
      const atrP = t.atr_pct != null ? t.atr_pct : (t.atr14 / t.price * 100);
      prospParts.push(`--atr-pct ${shqSim(atrP.toFixed(2) + '%')}`);
    }
    if (tName)            prospParts.push(`--name ${shqSim(tName)}`);
    const prospCmd = prospParts.join(' ');
    const canProsp = hardBads.length === 0;
    const prospBlock = `
      <div class="sim-prosp ${canProsp ? '' : 'disabled'}">
        <div class="sim-prosp-head">
          <b>📝 Convert to prospectus</b>
          <span class="dim" style="font-size:11px">${canProsp ? 'Creates a Phase 1 paper-trade prospectus stub in journal/' : 'Disabled — fix the failing gates above before creating a prospectus'}</span>
        </div>
        <div class="sim-prosp-cmd"><code data-prosp-cmd>${prospCmd}</code></div>
        <div class="sim-prosp-actions">
          <button type="button" class="sim-prosp-copy" ${canProsp ? '' : 'disabled'}>Copy command</button>
          <span class="dim" style="font-size:11px">Run the command in terminal · then ↻ Refresh dashboard · the new prospectus appears in the Journal Tail panel</span>
        </div>
      </div>`;
    out.innerHTML = `
      <div class="sim-verdict ${verdictClass}">${verdictText}</div>
      <div class="sim-blurb">${verdictBlurb}</div>
      <div class="sim-grid">
        <div class="sim-stat"><div class="l">Position size</div><div class="v ${oversize ? 'red' : ''}">${sharesDisplay} ${unit}${lotNote}</div>${shares !== doctrineMaxShares ? `<div class="sim-substat">doctrine max: ${fmtShares(doctrineMaxShares)} ${unit}</div>` : ''}</div>
        <div class="sim-stat"><div class="l">Notional</div><div class="v">${notionalDisplay}</div></div>
        <div class="sim-stat"><div class="l">$ at risk (USD)</div><div class="v">$${actualRiskUSD.toFixed(0)} <span style="font-weight:normal;color:var(--dim);font-size:11px"> (${actualRiskPct.toFixed(2)}%)</span></div></div>
        <div class="sim-stat"><div class="l">R:R to TP1</div><div class="v ${rrOk ? 'green' : 'red'}">${rrTp1.toFixed(2)}R</div></div>
        ${rrTp2 != null ? `<div class="sim-stat"><div class="l">R:R to TP2</div><div class="v">${rrTp2.toFixed(2)}R</div></div>` : ''}
        <div class="sim-stat"><div class="l">Heat after entry</div><div class="v ${heatOk ? 'green' : 'red'}">$${heatAfter.toFixed(0)} / $${sim.config.heat_max}</div></div>
        <div class="sim-stat"><div class="l">R:R floor (regime)</div><div class="v">${rrFloor.toFixed(2)}R <span style="font-weight:normal;color:var(--dim);font-size:11px">${sim.regime.label}</span></div></div>
        <div class="sim-stat"><div class="l">Risk per ${unit === 'units' ? 'unit' : 'share'}</div><div class="v">${sym}${riskPerShareLocal.toFixed(dp)}</div></div>
      </div>
      <div class="sim-gates">
        ${gates.map(g => `<div class="sim-gate"><span class="mark ${g.ok}">${g.ok === 'ok' ? '✓' : g.ok === 'warn' ? '⚠' : '✗'}</span><div><span class="label">${g.label}</span><div class="why">${g.why}</div></div></div>`).join('')}
      </div>
      ${prospBlock}`;
    // Wire the copy button (rebound on every render)
    const copyBtn = out.querySelector('.sim-prosp-copy');
    if (copyBtn && canProsp) {
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(prospCmd).then(() => {
          copyBtn.classList.add('copied');
          const orig = copyBtn.textContent;
          copyBtn.textContent = '✓ copied — paste in terminal';
          setTimeout(() => { copyBtn.classList.remove('copied'); copyBtn.textContent = orig; }, 2600);
        });
      });
    }
  }
})();

// ── Live quote button — Finnhub (US), Binance/CoinGecko (crypto) ─────────
// KLSE uses a plain link (no API supports live KLSE quotes on free + CORS-friendly).
(function(){
  const fhKey = window.TA_FINNHUB_KEY;
  const nowHHMM = () => new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});

  async function fetchUSQuote(sym) {
    if (!fhKey) return {err: 'FINNHUB_API_KEY not set'};
    const r = await fetch(`https://finnhub.io/api/v1/quote?symbol=${encodeURIComponent(sym)}&token=${fhKey}`);
    if (!r.ok) return {err: `HTTP ${r.status}`};
    const d = await r.json();
    if (!d || d.c == null) return {err: 'no data'};
    return {
      price: d.c, change_pct: d.dp, change_abs: d.d,
      ts: d.t ? new Date(d.t * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : nowHHMM(),
      currency: '$',
    };
  }

  async function fetchBinanceQuote(pair) {
    const r = await fetch(`https://api.binance.com/api/v3/ticker/24hr?symbol=${encodeURIComponent(pair)}`);
    if (!r.ok) return {err: `HTTP ${r.status}`};
    const d = await r.json();
    if (!d || d.lastPrice == null) return {err: 'no data'};
    return {
      price: parseFloat(d.lastPrice),
      change_pct: parseFloat(d.priceChangePercent),
      change_abs: parseFloat(d.priceChange),
      ts: nowHHMM(),
      currency: '$',
    };
  }

  async function fetchCoinGeckoQuote(coinId) {
    const r = await fetch(`https://api.coingecko.com/api/v3/simple/price?ids=${encodeURIComponent(coinId)}&vs_currencies=usd&include_24hr_change=true&include_last_updated_at=true`);
    if (!r.ok) return {err: `HTTP ${r.status}`};
    const d = await r.json();
    const e = d[coinId];
    if (!e || e.usd == null) return {err: 'no data'};
    return {
      price: e.usd,
      change_pct: e.usd_24h_change ?? 0,
      change_abs: null,
      ts: e.last_updated_at ? new Date(e.last_updated_at * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : nowHHMM(),
      currency: '$',
    };
  }

  function renderResult(target, q) {
    if (q.err) {
      target.innerHTML = `<span class="lq-err">${q.err}</span>`;
      return;
    }
    const cls = q.change_pct >= 0 ? 'green' : 'red';
    const sign = q.change_pct >= 0 ? '+' : '';
    const dp = q.price < 0.1 ? 6 : q.price < 5 ? 4 : 2;
    target.innerHTML = `<span class="${cls}">${q.currency}${q.price.toFixed(dp)} (${sign}${q.change_pct.toFixed(2)}%)</span><span class="lq-time">${q.ts}</span>`;
  }

  document.querySelectorAll('button.ta-quote-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const target = btn.nextElementSibling;  // .live-quote span (US + crypto only — KLSE is an <a>, not button)
      if (!target) return;
      btn.classList.add('loading');
      target.innerHTML = '<span class="lq-time">…</span>';
      try {
        let q;
        const cryptoSrc = btn.dataset.cryptoSource;
        const cryptoSym = btn.dataset.cryptoSymbol;
        const usSym     = btn.dataset.symbol;
        if (cryptoSym && cryptoSrc === 'binance') {
          q = await fetchBinanceQuote(cryptoSym);
        } else if (cryptoSym && cryptoSrc === 'coingecko') {
          q = await fetchCoinGeckoQuote(cryptoSym);
        } else if (usSym) {
          q = await fetchUSQuote(usSym);
        } else {
          q = {err: 'unsupported ticker type'};
        }
        renderResult(target, q);
      } catch (err) {
        target.innerHTML = `<span class="lq-err">err: ${err.message}</span>`;
      } finally {
        btn.classList.remove('loading');
      }
    });
  });
})();

// ── Generic expandable-row toggle (used by US, KLSE, Crypto grids) ───────
(function(){
  document.querySelectorAll('tr.exp-row').forEach(row => {
    row.addEventListener('click', (e) => {
      // Don't toggle if the click was inside an interactive child (button, link, input)
      if (e.target.closest('button, a, input, select')) return;
      const id = row.dataset.rowId;
      const body = document.getElementById(id + '-body');
      const chev = row.querySelector('.exp-chevron');
      if (!body) return;
      const opening = !body.classList.contains('open');
      body.classList.toggle('open', opening);
      row.classList.toggle('expanded', opening);
      if (chev) chev.textContent = opening ? '▼' : '▶';
    });
  });
})();

// ── Watchlist Manager — inline forms that generate wl.py CLI commands ─────
(function(){
  const wl = window.TA_WL;
  const tabs = document.getElementById('wl-tabs');
  const host = document.getElementById('wl-form-host');
  if (!wl || !tabs || !host) return;

  const WL = 'python3 .claude/skills/watchlist/wl.py';
  function shq(s) { if (s == null) return "''"; return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
  function allTickers() {
    return [...(wl.us||[]), ...(wl.klse||[]), ...(wl.crypto||[])];
  }
  function sectionOf(t) {
    if ((wl.us||[]).includes(t)) return 'US';
    if ((wl.klse||[]).includes(t)) return 'KLSE';
    if ((wl.crypto||[]).includes(t)) return 'Crypto';
    return '—';
  }

  // Form definitions — same shape as the journal forms (def.fields + def.build)
  const FORMS = {
    add: () => ({
      title: '➕ Add a ticker (auto-classify + auto-thesis)',
      fields: [
        {name: 'ticker',  label: 'Ticker',  type: 'text',     placeholder: 'e.g. NVDA, 7113.KL, ENA',
         help: 'Auto-classified by section unless overridden. Validated via yfinance / CoinGecko.'},
        {name: 'section', label: 'Section', type: 'select',   options: ['auto','us','klse','crypto','options']},
        {name: 'thesis',  label: 'Thesis',  type: 'textarea', placeholder: 'Optional — leave blank for auto-generated thesis from sector/snapshot',
         help: 'One line. Why is it on the list? What setup / catalyst / structure?'},
        {name: 'allow_unresolved', label: 'Force-add', type: 'checkbox',
         help: 'Add even if data source can\\'t resolve the ticker (use only when you\\'re sure of the symbol).'},
      ],
      build: (v) => {
        const tkr = (v.ticker || '').trim();
        if (!tkr) return {cmd: '', valid: false, hint: 'ticker required'};
        if (allTickers().some(t => t.toUpperCase() === tkr.toUpperCase()))
          return {cmd: '', valid: false, hint: `${tkr} is already in the watchlist (${sectionOf(allTickers().find(t => t.toUpperCase() === tkr.toUpperCase()))} section)`, invalid: true};
        let cmd = `${WL} add ${tkr}`;
        if (v.section && v.section !== 'auto') cmd += ` --section ${v.section}`;
        if (v.thesis && v.thesis.trim()) cmd += ` --thesis ${shq(v.thesis.trim())}`;
        if (v.allow_unresolved === 'on' || v.allow_unresolved === true) cmd += ' --allow-unresolved';
        cmd += ' -y';
        return {cmd, valid: true, hint: ''};
      },
    }),

    remove: () => ({
      title: '➖ Remove a ticker (soft-delete to Removed/retired)',
      fields: [
        {name: 'ticker', label: 'Ticker', type: 'datalist', source: allTickers(),
         placeholder: 'pick or type', help: `Current watchlist: ${allTickers().length} tickers.`},
        {name: 'reason', label: 'Reason', type: 'textarea', placeholder: 'e.g. Thesis invalidated — broke SMA200 with no recovery',
         help: 'Required by doctrine. Goes in the audit trail.'},
      ],
      build: (v) => {
        const tkr = (v.ticker || '').trim();
        const reason = (v.reason || '').trim();
        if (!tkr) return {cmd: '', valid: false, hint: 'ticker required'};
        if (!allTickers().some(t => t.toUpperCase() === tkr.toUpperCase()))
          return {cmd: '', valid: false, hint: `${tkr} is not in the watchlist`, invalid: true};
        if (!reason) return {cmd: `${WL} remove ${tkr} --reason _REASON_ -y`, valid: false, hint: 'reason required (doctrine)'};
        return {cmd: `${WL} remove ${tkr} --reason ${shq(reason)} -y`, valid: true, hint: `→ moved to Removed/retired (${sectionOf(tkr)})`};
      },
    }),

    update: () => ({
      title: '✎ Update a ticker\\'s thesis (in-place)',
      fields: [
        {name: 'ticker', label: 'Ticker', type: 'datalist', source: allTickers(),
         placeholder: 'pick or type', help: 'Must already be in the watchlist.'},
        {name: 'thesis', label: 'New thesis', type: 'textarea', placeholder: 'e.g. Now a momentum thesis post-breakout vs. prior pullback setup',
         help: 'Replaces the existing thesis line entirely.'},
      ],
      build: (v) => {
        const tkr = (v.ticker || '').trim();
        const thesis = (v.thesis || '').trim();
        if (!tkr) return {cmd: '', valid: false, hint: 'ticker required'};
        if (!allTickers().some(t => t.toUpperCase() === tkr.toUpperCase()))
          return {cmd: '', valid: false, hint: `${tkr} is not in the watchlist`, invalid: true};
        if (!thesis) return {cmd: `${WL} update ${tkr} --thesis _THESIS_ -y`, valid: false, hint: 'new thesis required'};
        return {cmd: `${WL} update ${tkr} --thesis ${shq(thesis)} -y`, valid: true, hint: `→ thesis updated in ${sectionOf(tkr)} section`};
      },
    }),
  };

  function renderForm(mode) {
    const def = FORMS[mode]();
    host.innerHTML = '';
    const form = document.createElement('div');
    form.className = 'action-form open';
    form.innerHTML = `
      <div class="form-title">${def.title}</div>
      ${def.fields.map(f => {
        let input;
        if (f.type === 'textarea') {
          input = `<textarea id="wlf_${f.name}" name="${f.name}" placeholder="${f.placeholder || ''}"></textarea>`;
        } else if (f.type === 'select') {
          input = `<select id="wlf_${f.name}" name="${f.name}">${(f.options || []).map(o => `<option value="${o}">${o}</option>`).join('')}</select>`;
        } else if (f.type === 'checkbox') {
          input = `<label style="font-weight:normal"><input id="wlf_${f.name}" name="${f.name}" type="checkbox" /> enable</label>`;
        } else if (f.type === 'datalist') {
          const listId = `wldl_${f.name}`;
          input = `<input id="wlf_${f.name}" name="${f.name}" type="text" placeholder="${f.placeholder || ''}" list="${listId}" />
                   <datalist id="${listId}">${(f.source || []).map(s => `<option value="${s}">`).join('')}</datalist>`;
        } else {
          input = `<input id="wlf_${f.name}" name="${f.name}" type="${f.type}" placeholder="${f.placeholder || ''}" />`;
        }
        return `
          <div class="form-row">
            <label for="wlf_${f.name}">${f.label}</label>
            ${input}
            ${f.help ? `<div class="help">${f.help}</div>` : ''}
          </div>`;
      }).join('')}
      <div class="preview-label">Command preview</div>
      <div class="preview" data-preview>(fill the form to generate)</div>
      <div class="form-actions">
        <button type="button" class="primary" data-copy>Copy command</button>
      </div>
    `;
    host.appendChild(form);

    const inputs = form.querySelectorAll('input,textarea,select');
    const previewEl = form.querySelector('[data-preview]');
    const copyBtn   = form.querySelector('[data-copy]');

    function values() {
      const v = {};
      inputs.forEach(i => {
        if (i.type === 'checkbox') v[i.name] = i.checked;
        else v[i.name] = i.value;
      });
      return v;
    }
    function refresh() {
      const r = def.build(values());
      if (r.invalid) {
        previewEl.innerHTML = `<span class="preview-invalid">⚠ ${r.hint}</span>`;
        copyBtn.disabled = true; copyBtn.textContent = 'Copy command';
        return;
      }
      previewEl.textContent = r.cmd || '(fill the form to generate)';
      copyBtn.disabled = !r.valid;
      copyBtn.textContent = r.valid ? 'Copy command' : (r.hint ? `Need: ${r.hint}` : 'Copy command');
      copyBtn.dataset.cmd = r.cmd || '';
      if (r.hint && r.valid) {
        previewEl.insertAdjacentHTML('beforeend', `<div style="color:var(--green);font-size:11px;margin-top:4px">${r.hint}</div>`);
      }
    }
    inputs.forEach(i => i.addEventListener('input', refresh));
    inputs.forEach(i => i.addEventListener('change', refresh));
    refresh();
    inputs[0] && inputs[0].focus();

    copyBtn.addEventListener('click', () => {
      const cmd = copyBtn.dataset.cmd;
      if (!cmd) return;
      navigator.clipboard.writeText(cmd).then(() => {
        copyBtn.classList.add('copied');
        const orig = copyBtn.textContent;
        copyBtn.textContent = '✓ copied — paste in terminal';
        setTimeout(() => { copyBtn.classList.remove('copied'); copyBtn.textContent = orig; }, 2400);
      });
    });
  }

  tabs.querySelectorAll('.wl-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      tabs.querySelectorAll('.wl-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderForm(btn.dataset.mode);
    });
  });
  renderForm('add');  // default tab
})();
"""

def _budget_bar_html():
    """B2: render a compact budget bar showing AV/TD/FMP daily usage."""
    cells = []
    # Alpha Vantage (us-news)
    try:
        av_budget = ctx_news_budget if False else None  # set below in render_html via globals
    except Exception:
        av_budget = None
    # TD + FMP from their respective skill budget files
    def _load_skill_budget(path, cap):
        try:
            d = json.loads(path.read_text())
            from datetime import datetime as _dt, timezone as _tz
            if d.get("date") != _dt.now(_tz.utc).strftime("%Y-%m-%d"):
                return {"used": 0, "cap": cap}
            return {"used": d.get("calls_used", 0), "cap": cap}
        except Exception:
            return {"used": 0, "cap": cap}

    td_b  = _load_skill_budget(PROJECT_ROOT / ".claude/cache/twelve_data/budget.json", 800)
    fmp_b = _load_skill_budget(PROJECT_ROOT / ".claude/cache/fmp/budget.json",         250)

    # AV: tracked by news_cache module if available
    av_b = {"used": 0, "cap": 25}
    nc_mod = _import_news_cache()
    if nc_mod:
        try:
            b = nc_mod.load_budget()
            av_b["used"] = b.get("calls_used", 0)
        except Exception: pass

    def cell(name, used, cap):
        pct = (used / cap * 100) if cap > 0 else 0
        cls = "b-green" if pct < 60 else "b-yellow" if pct < 85 else "b-red"
        return f'<span class="budget-cell {cls}" title="{name}: {used}/{cap} calls used today ({pct:.0f}%)">{name} {used}/{cap}</span>'

    return (f'<span class="budget-bar">'
            f'{cell("AV", av_b["used"], av_b["cap"])}'
            f'{cell("TD", td_b["used"], td_b["cap"])}'
            f'{cell("FMP", fmp_b["used"], fmp_b["cap"])}'
            f'</span>')


def render_html(ctx):
    # ── Header ─────
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    now_iso_utc = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # for JS to re-format in viewer's TZ
    # Server-side local string kept as a fallback if JS is disabled. Whatever the build host's
    # tz is — likely UTC — gets shown until JS reformats it.
    now_local_str = now_dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    budget_bar = _budget_bar_html()
    macro = ctx["macro_regime"]; macro_age = ctx["macro_regime_age"]
    crypto = ctx["crypto_regime"]; crypto_age = ctx["crypto_regime_age"]
    cal = ctx["macro_calendar"]; cal_age = ctx["macro_calendar_age"]
    config = ctx["config"]

    def regime_class(score):
        if score is None: return "v-neu"
        if score >= 0.5: return "v-pos"
        if score <= -0.5: return "v-neg"
        return "v-neu"

    def signals_html(sigs):
        lines = []
        for s in sigs[:6]:
            w = s.get("w", 0)
            sign = "+" if w > 0 else ("−" if w < 0 else "0")
            cls = "v-pos" if w > 0 else ("v-neg" if w < 0 else "v-neu")
            lines.append(f'<div class="sig"><span class="{cls}">[{sign}{abs(w):.1f}]</span> {html.escape(s.get("note",""))}</div>')
        return "\n".join(lines)

    # Strip
    budget = ctx.get("news_budget") or {"calls_used": 0, "calls_max": 25, "reserve_for_ondemand": 8}
    nc_mod = _import_news_cache()
    reset_str = nc_mod.time_until_reset_str() if nc_mod else "—"
    budget_used = budget.get("calls_used", 0)
    budget_max = budget.get("calls_max", 25)
    budget_pct = (budget_used / budget_max * 100) if budget_max else 0
    budget_cls = "red" if budget_pct >= 90 else ("yellow" if budget_pct >= 70 else "")
    strip = f"""
<div class="strip strip-5">
  <div class="cell">
    <div class="label">Account</div>
    <div class="value">${config['account']:,}</div>
    <div class="sub">Risk/trade ${config['max_risk']:,} ({config['risk_pct']*100:.0f}%)</div>
  </div>
  <div class="cell">
    <div class="label">Phase</div>
    <div class="value">{config['phase']}</div>
    <div class="sub">{config['phase_desc']}</div>
  </div>
  <div class="cell">
    <div class="label">Portfolio Heat</div>
    <div class="value">${config['heat_used']:,} / ${config['heat_max']:,}</div>
    <div class="sub">Headroom ${config['heat_max']-config['heat_used']:,}</div>
  </div>
  <div class="cell">
    <div class="label">Phase 2 gate</div>
    <div class="value">{config['trades_closed']} / 20</div>
    <div class="sub">trades closed with ≥0R cumulative</div>
  </div>
  <div class="cell">
    <div class="label">AV News Budget</div>
    <div class="value {budget_cls}">{budget_used} / {budget_max}</div>
    <div class="sub">reset in {reset_str} UTC · reserve {budget.get('reserve_for_ondemand', 8)} on-demand</div>
  </div>
</div>
"""

    # Regime
    macro_fetched = fmt_fetched(fetched_at_of(macro))
    crypto_fetched = fmt_fetched(fetched_at_of(crypto))
    regime_panel = f"""
<div class="panel">
  <h2>Regime Read</h2>
  <div class="regime-row">
    <div class="regime-box">
      <div class="title">US Macro (FRED) <span style="float:right;color:var(--dim);text-transform:none;letter-spacing:normal;font-weight:normal">fetched {macro_fetched}</span></div>
      <div class="verdict {regime_class(macro.get('score'))}">{html.escape(macro.get('regime','—'))} ({macro.get('score',0):+.2f})</div>
      <div class="signals">{signals_html(macro.get('signals',[]))}</div>
      <div class="signals" style="margin-top:6px">
        VIX {fmt_num(macro.get('values',{}).get('VIX'),1)} · DGS10 {fmt_num(macro.get('values',{}).get('DGS10'),2)}% · DFF {fmt_num(macro.get('values',{}).get('DFF'),2)}% · Core CPI YoY {fmt_num(macro.get('values',{}).get('coreCPI_yoy'),2)}%
      </div>
    </div>
    <div class="regime-box">
      <div class="title">Crypto (CG + alt.me) <span style="float:right;color:var(--dim);text-transform:none;letter-spacing:normal;font-weight:normal">fetched {crypto_fetched}</span></div>
      <div class="verdict {regime_class(crypto.get('score'))}">{html.escape(crypto.get('regime','—'))} ({crypto.get('score',0):+.2f})</div>
      <div class="signals">{signals_html(crypto.get('signals',[]))}</div>
      <div class="signals" style="margin-top:6px">
        F&amp;G {fmt_num(crypto.get('values',{}).get('FNG'),0)} {html.escape(str(crypto.get('values',{}).get('FNG_label','')))} · BTC.D {fmt_num(crypto.get('values',{}).get('BTC_D'),1)}% · ETH.D {fmt_num(crypto.get('values',{}).get('ETH_D'),1)}% · Stable {fmt_num(crypto.get('values',{}).get('stable_D'),1)}%
      </div>
    </div>
  </div>
</div>
"""

    # Halt timeline
    events_html = ""
    for ev in cal.get("events", [])[:10]:
        halt_class = " halt" if ev["in_halt"] else ""
        when = f"{ev['hours_until']:.1f}h" if ev["hours_until"] < 24 else f"{ev['hours_until']/24:.1f}d"
        events_html += f'<div class="event{halt_class}"><span class="type">{ev["type"]}</span> <span class="event-time" data-utc="{html.escape(ev.get("date_iso",""), quote=True)}" title="ET (source): {html.escape(ev["date_et"], quote=True)}">{html.escape(ev["date_et"])}</span><br><span class="when">in {when}{" 🛑" if ev["in_halt"] else ""}</span></div>'
    halt_panel = f"""
<div class="panel">
  <h2>Macro Halt-Window Timeline <span class="stale">static schedule (loaded {fmt_fetched(now_dt.isoformat())}) · verified through {html.escape(str(cal.get('verified_through','—')))}</span></h2>
  <div class="events">{events_html or '<div class="dim">no upcoming events</div>'}</div>
</div>
"""

    # Active prospectuses
    # Build prospectus cards. Each has data-stem so JS can render forms per action.
    # The forms + click handlers live in the JS block — see TA_PROSPECTUS_ACTIONS there.
    pros_html = ""
    actions = [
        ("live-paper", "Live paper"),
        ("live-real",  "Live real"),
        ("update",     "Update"),
        ("calc-r",     "Calc R"),
        ("close-win",  "Close win"),
        ("close-loss", "Close loss"),
        ("mark-dead",  "Mark dead"),
    ]
    for j in ctx["journal"][:5]:
        status_lc = j["status"].lower()
        if not ("prospectus" in status_lc or "live" in status_lc or "pending" in status_lc):
            continue
        stem = j["file"][:-3] if j["file"].endswith(".md") else j["file"]
        btns = "".join(
            f'<button class="ta-action-btn" data-action="{a}" data-label="{html.escape(lbl, quote=True)}">{html.escape(lbl)}</button>'
            for a, lbl in actions
        )
        pros_html += (
            f'<div class="prospectus" data-stem="{html.escape(stem, quote=True)}">'
            f'<div class="head">{html.escape(j["ticker"])} — {html.escape(j["status"])}</div>'
            f'<div class="meta">{html.escape(j["file"])}</div>'
            f'<div class="actions">{btns}</div>'
            f'<div class="action-form-host"></div>'
            f'</div>'
        )
    if not pros_html:
        pros_html = '<div class="dim">no active prospectuses</div>'
    prospectus_panel = f"""
<div class="panel">
  <h2>Active Prospectuses</h2>
  {pros_html}
</div>
"""

    macro_events_for_status = ctx["macro_calendar"].get("events", [])

    # ── Risk Simulator data + panel ──────────────────────────
    # Map macro score → R:R floor (per macro-rates SKILL.md rules)
    macro_score = ctx["macro_regime"].get("score") or 0
    if macro_score <= -0.5:
        rr_floor = 2.0
    elif macro_score <= -1.5:
        rr_floor = 2.5
    else:
        rr_floor = 1.5

    # Build per-ticker simulator data — US + KLSE (crypto deferred to a later phase)
    sim_tickers = {}
    for entry in ctx["watchlist"]["us"]:
        tk = entry["ticker"]
        t = ctx["us_data"].get(tk, {}) or {}
        if t.get("error") or t.get("price") is None:
            continue
        _, status_label, _ = us_status({**t, "ticker": tk}, macro_events_for_status)
        sim_tickers[tk] = {
            "market": "us",
            "currency": "USD",
            "lot_size": 1,
            "name": t.get("name"),
            "price": t.get("price"),
            "rsi14": t.get("rsi14"),
            "sma20": t.get("sma20"),
            "sma50": t.get("sma50"),
            "sma200": t.get("sma200"),
            "atr14": t.get("atr14"),
            "sma50_slope_pct": t.get("sma50_slope_pct"),
            "vol_ratio": t.get("vol_ratio"),
            "change_pct": t.get("change_pct"),
            "next_earnings": t.get("next_earnings"),
            "status_label": status_label,
        }

    # KLSE: same shape, plus market='klse', currency='MYR', lot_size=100, fundamentals if cached
    klse_fund_local = ctx.get("klse_fundamentals", {}) or {}
    klse_ann_local = ctx.get("klse_announcements", {}) or {}
    for entry in ctx["watchlist"]["klse"]:
        tk = entry["ticker"]
        t = ctx["klse_data"].get(tk, {}) or {}
        if t.get("error") or t.get("price") is None:
            continue
        _, status_label, _ = us_status({**t, "ticker": tk}, None)
        code = tk.upper().replace(".KL", "")
        fund = klse_fund_local.get(code, {}) or {}
        ann = klse_ann_local.get(code, {}) or {}
        name = (fund.get("stock_name") or ann.get("stock_name") or fund.get("page_title") or t.get("name") or tk)
        # Trim announcements to just the fields the gate needs (keep payload small)
        fr_info = ann.get("most_recent_financial_results") or {}
        sim_tickers[tk] = {
            "market": "klse",
            "currency": "MYR",
            "lot_size": 100,
            "name": name,
            "price": t.get("price"),
            "rsi14": t.get("rsi14"),
            "sma20": t.get("sma20"),
            "sma50": t.get("sma50"),
            "sma200": t.get("sma200"),
            "atr14": t.get("atr14"),
            "sma50_slope_pct": t.get("sma50_slope_pct"),
            "vol_ratio": t.get("vol_ratio"),
            "change_pct": t.get("change_pct"),
            "status_label": status_label,
            # KLSE fundamentals (display only, no gating)
            "pe": fund.get("pe_ratio"),
            "pb": fund.get("pb_ratio"),
            "dy": fund.get("dividend_yield_pct"),
            "roe": fund.get("roe_pct"),
            "fund_fetched_at": fund.get("_fetched_at"),
            # KLSE announcements (used by earnings gate)
            "ann_fetched_at": ann.get("_fetched_at"),
            "fr_filed_date": fr_info.get("filed_date"),
            "fr_period_end": fr_info.get("period_end"),
            "fr_next_expected_period_end": fr_info.get("next_expected_period_end"),
            "fr_next_expected_filing_by": fr_info.get("next_expected_filing_by"),
            "upcoming_events": ann.get("upcoming_events") or [],
        }

    # Crypto: spot-only, USD-native, fractional units. Indicators from Binance daily klines.
    crypto_ind_local    = ctx.get("crypto_indicators", {}) or {}
    crypto_fund_local   = ctx.get("crypto_funding", {}) or {}
    crypto_regime_local = ctx.get("crypto_regime", {}) or {}
    crypto_unlocks_local = ctx.get("crypto_unlocks", {}) or {}
    for entry in ctx["watchlist"]["crypto"]:
        tk = entry["ticker"].upper()
        ind = crypto_ind_local.get(tk, {}) or {}
        if ind.get("error") or ind.get("price") is None:
            # Skip coins without Binance spot pair / failed klines (e.g. HYPE)
            continue
        sym_pair = ind.get("symbol") or (tk + "USDT")
        fnd = crypto_fund_local.get(sym_pair, {}) or {}
        sim_tickers[tk] = {
            "market": "crypto",
            "currency": "USD",
            "lot_size": 0,  # 0 = fractional units, no rounding
            "name": tk,
            "price": ind.get("price"),
            "rsi14": ind.get("rsi14"),
            "sma20": ind.get("sma20"),
            "sma50": ind.get("sma50"),
            "sma200": ind.get("sma200"),
            "atr14": ind.get("atr14"),
            "atr_pct": ind.get("atr_pct"),
            "sma50_slope_pct": ind.get("sma50_slope_pct"),
            "vol_ratio": ind.get("vol_ratio"),
            "change_pct": ind.get("change_pct"),
            "status_label": None,
            # Derivatives positioning (Binance perp funding)
            "funding_annualized_pct": fnd.get("annualized_pct"),
            "funding_last": fnd.get("last_funding"),
            "binance_pair": sym_pair,
            # Token unlock cache (consumed by §5 48h-halt gate)
            "unlock_entry": crypto_unlocks_local.get(tk),
            "data_source": ind.get("data_source", "binance"),
        }

    sim_payload = {
        "config": {
            "account": ctx["config"]["account"],
            "risk_pct": ctx["config"]["risk_pct"],
            "heat_used": ctx["config"]["heat_used"],
            "heat_max": ctx["config"]["heat_max"],
            "phase": ctx["config"]["phase"],
        },
        "regime": {
            "label": ctx["macro_regime"].get("regime", "—"),
            "score": macro_score,
            "rr_floor": rr_floor,
        },
        "crypto_regime": {
            "label": crypto_regime_local.get("regime", "—"),
            "score": crypto_regime_local.get("score"),
            "fng": (crypto_regime_local.get("values", {}) or {}).get("FNG"),
            "fng_label": (crypto_regime_local.get("values", {}) or {}).get("FNG_label"),
            "btc_d": (crypto_regime_local.get("values", {}) or {}).get("BTC_D"),
        },
        "macro_events": [
            {"type": e["type"], "hours_until": e["hours_until"], "date_et": e["date_et"], "note": e.get("note", "")}
            for e in ctx["macro_calendar"].get("events", [])
        ],
        "fx": ctx.get("fx", {}),
        "tickers": sim_tickers,
    }
    sim_json = json.dumps(sim_payload)

    # Watchlist manager payload — current ticker rosters by section for the dropdowns
    wl_payload = {
        "us":     [e["ticker"] for e in ctx["watchlist"]["us"]],
        "klse":   [e["ticker"] for e in ctx["watchlist"]["klse"]],
        "crypto": [e["ticker"] for e in ctx["watchlist"]["crypto"]],
    }
    wl_json = json.dumps(wl_payload)

    sim_panel = f"""
<div class="panel">
  <h2>Risk Simulator <span class="stale">R:R floor under <b>{html.escape(sim_payload['regime']['label'])}</b>: {rr_floor:.1f}R · US + KLSE + crypto (spot) supported</span></h2>
  <div id="sim-market-banner" style="color:var(--dim);font-size:11px;margin-bottom:8px;min-height:14px"></div>
  <div class="sim-form">
    <div><label>Ticker</label><select id="sim-ticker"></select></div>
    <div><label>Entry (<span class="sim-cur-label">$</span>)</label><input id="sim-entry" type="number" step="0.0001" placeholder="entry" /></div>
    <div><label>Stop (<span class="sim-cur-label">$</span>)</label><input id="sim-stop" type="number" step="0.0001" placeholder="stop" /></div>
    <div><label>TP1 (<span class="sim-cur-label">$</span>)</label><input id="sim-tp1" type="number" step="0.0001" placeholder="TP1" /></div>
    <div><label>TP2 (optional)</label><input id="sim-tp2" type="number" step="0.0001" placeholder="TP2" /></div>
    <div><label>Size (<span class="sim-unit-label">sh</span>, optional)</label><input id="sim-size" type="number" step="0.000001" placeholder="auto = doctrine max" title="Optional. Leave blank to size at the doctrine maximum (2% account risk). Enter a number to size your own position; sim will verify it doesn't exceed the cap and check heat headroom." /></div>
    <button id="sim-prefill" type="button" title="Reset to suggested entry/stop/TP1 from cached data">↻ Suggest</button>
  </div>
  <div class="sim-result" id="sim-result">
    <div class="sim-verdict pending">PENDING — pick a ticker and fill in entry, stop, TP1</div>
    <div class="sim-blurb">You pick entry / stop / TP / size; the sim verifies the trade is doctrine-compliant (per-trade risk cap §5, portfolio heat, regime R:R floor, technical confluence, event-window halts). The Size field is auto-prefilled to the doctrine maximum — edit it down for partial conviction, correlation tax, or partial-fill plans. Sim uses the dashboard's cached technicals; refresh the dashboard for the freshest numbers.</div>
  </div>
</div>
<script>
window.TA_SIM = {sim_json};
window.TA_FINNHUB_KEY = {json.dumps(os.environ.get("FINNHUB_API_KEY") or "")};
</script>
"""

    wl_us_count = len(wl_payload["us"]); wl_klse_count = len(wl_payload["klse"]); wl_crypto_count = len(wl_payload["crypto"])
    wl_panel = f"""
<div class="panel">
  <h2>Watchlist Manager <span class="stale">generate <code>wl.py</code> commands · current: {wl_us_count} US · {wl_klse_count} KLSE · {wl_crypto_count} crypto</span></h2>
  <div class="wl-mode-tabs" id="wl-tabs">
    <button type="button" data-mode="add"    class="wl-tab active">➕ Add</button>
    <button type="button" data-mode="remove" class="wl-tab">➖ Remove</button>
    <button type="button" data-mode="update" class="wl-tab">✎ Update thesis</button>
  </div>
  <div id="wl-form-host"></div>
</div>
<script>window.TA_WL = {wl_json};</script>
"""

    # ── Discovery panel — US screener + sector rotation ──────────────────
    screener_cache = PROJECT_ROOT / ".claude" / "cache" / "screener" / "candidates.json"
    sector_cache   = PROJECT_ROOT / ".claude" / "cache" / "sector_rotation" / "data.json"
    screener_data = json.loads(screener_cache.read_text()) if screener_cache.is_file() else None
    sector_data   = json.loads(sector_cache.read_text())   if sector_cache.is_file()   else None

    def render_sector_strip():
        if not sector_data or not sector_data.get("rows"):
            return '<div class="dim" style="padding:8px">No sector rotation data — run <code>python3 .claude/skills/sector-rotation/sector_rotation.py</code></div>'
        rows = sector_data["rows"]
        spy = sector_data.get("baseline_spy", {})
        cells = []
        for r in rows:
            comp = r.get("composite") or 0
            cls = "sector-strong" if comp > 2 else "sector-weak" if comp < -2 else "sector-neutral"
            tip = (f"{r['name']} ({r['symbol']})\n"
                   f"1m: {r.get('perf_1m', 0):+.1f}% (vs SPY {r.get('vs_spy_1m', 0):+.1f}%)\n"
                   f"3m: {r.get('perf_3m', 0):+.1f}% (vs SPY {r.get('vs_spy_3m', 0):+.1f}%)\n"
                   f"6m: {r.get('perf_6m', 0):+.1f}% (vs SPY {r.get('vs_spy_6m', 0):+.1f}%)\n"
                   f"Composite vs SPY: {comp:+.1f}")
            cells.append(f'<div class="sector-cell {cls}" title="{html.escape(tip, quote=True)}">'
                         f'<div class="sym">{r["symbol"]}</div>'
                         f'<div class="comp">{comp:+.1f}</div>'
                         f'<div class="name">{html.escape(r["name"])}</div>'
                         f'</div>')
        spy_str = f"SPY: {spy.get('1m', 0):+.1f}% (1m) · {spy.get('3m', 0):+.1f}% (3m) · {spy.get('6m', 0):+.1f}% (6m)"
        return (f'<div style="color:var(--dim);font-size:11px;margin-bottom:6px">'
                f'Sector rotation — composite = weighted vs-SPY (50% 1m / 30% 3m / 20% 6m). Baseline {spy_str}'
                f'</div><div class="sector-strip">' + "".join(cells) + '</div>')

    DISCOVERY_CAP = 20

    def synthesize_thesis(c, f, tech, tag, q_checks, v_checks, sector):
        """Plain-English synthesis of why this name is interesting."""
        tag_clean = tag.split(' ', 1)[1] if ' ' in tag else tag
        rsi = tech.get("rsi14"); atr_p = tech.get("atr_pct")
        name = f.get("name") or c["ticker"]
        roe = f.get("roe"); gm = f.get("gross_margin"); om = f.get("op_margin")
        pe = f.get("trailing_pe"); fcf = f.get("free_cashflow"); mcap = f.get("market_cap")
        fcfy = (fcf/mcap*100) if (fcf and mcap and fcf > 0) else None
        bits = []
        # Technical setup
        bits.append(f"<b>Technical setup:</b> {name} is currently in a Phase 1-ready position — price > SMA50 > SMA200 with RSI at {rsi:.1f} (P1 entry band 35-50), trend healthy, volume not showing distribution. Daily ATR is {atr_p:.2f}% so a 1.5× ATR stop sits ~{(atr_p*1.5):.1f}% below entry.")
        # Quality narrative
        if tag in ("💎 BUFFETT", "🏆 QUALITY"):
            qual_strengths = []
            if roe and roe > 0.15: qual_strengths.append(f"ROE {roe*100:.0f}% (compounder territory)")
            if gm and gm > 0.35:   qual_strengths.append(f"gross margins {gm*100:.0f}% (real pricing power)")
            if om and om > 0.15:   qual_strengths.append(f"operating margins {om*100:.0f}% (operationally efficient)")
            if qual_strengths:
                bits.append(f"<b>Business quality:</b> {'; '.join(qual_strengths[:3])}. This is a durable franchise — exactly the kind of name Buffett's quality lens looks for.")
        # Value narrative
        if tag in ("💎 BUFFETT", "💰 VALUE"):
            val_pts = []
            if pe and 0 < pe < 25: val_pts.append(f"trailing P/E {pe:.1f} (below the 25 ceiling)")
            if fcfy and fcfy > 4:  val_pts.append(f"FCF yield {fcfy:.2f}% (you get paid real cash for holding)")
            fpe = f.get("forward_pe")
            if pe and fpe and 0 < fpe < pe: val_pts.append(f"forward P/E {fpe:.1f} < trailing {pe:.1f} (earnings improving)")
            if val_pts:
                bits.append(f"<b>Valuation:</b> {'; '.join(val_pts[:3])}. Not just a chart — you're buying assets cheaper than the market average.")
        # Why it's NOT BUFFETT (honest caveats)
        q_fails = [c[2] for c in q_checks if not c[1]]
        v_fails = [c[2] for c in v_checks if not c[1]]
        if tag == "🏆 QUALITY" and v_fails:
            bits.append(f"<b>What's holding it back:</b> Quality bar passed but valuation looks rich — {'; '.join(v_fails[:2])}. Wait for a deeper pullback, or accept you're paying for the quality.")
        elif tag == "💰 VALUE" and q_fails:
            bits.append(f"<b>What's holding it back:</b> Cheap, but quality is lower than ideal — {'; '.join(q_fails[:2])}. Could be a value trap; verify business durability before sizing.")
        elif tag == "⚡ TECH":
            bits.append(f"<b>Caution:</b> Technical setup is real, but neither quality nor value support it. Don't fall in love — treat this as a trade, not an investment.")
        elif tag == "💎 BUFFETT":
            bits.append(f"<b>Why this is rare:</b> A name passing both the strict 4/5 quality bar AND 2/3 value bar at the same time as a clean P1 technical entry is unusual. Worth genuine watchlist attention.")
        # Next steps
        bits.append(f"<b>Next steps:</b> Click <b>+ Add</b> to drop {c['ticker']} on the watchlist, then run the Risk Simulator with your intended entry/stop/TP to verify R:R and event gates.")
        return "\n".join(f"<p>{b}</p>" for b in bits)

    # Live watchlist set — cross-check at render time so a ticker added since the screener
    # last ran disappears from Discovery on the next dashboard rebuild (no need to re-run
    # the screener just for in_watchlist correctness).
    live_wl_set = {t.upper() for t in wl_payload.get("us", [])}

    def render_screener_rows():
        if not screener_data:
            return '<tr><td colspan="12" class="dim">No screener data — run <code>python3 .claude/skills/us-screener/screener.py</code></td></tr>'
        cands = screener_data.get("candidates", [])
        # v1.9.1 defensive render-time filter: even if a stale candidates.json from
        # before the criteria-tightening (or any future drift) sits on disk, the
        # dashboard applies current rules. Covers all four tightening options so
        # stale-cache entries don't leak through:
        #   A. drop ⚡ TECH tier
        #   B. require Q≥3/5 for 💰 VALUE tier
        #   C. require RSI in 38-48 (was 35-50)
        #   D. require SMA50 slope ≥ 1%/5d (was ≥ -0.5%)
        def _passes_current_rules(c):
            tag = c.get("tag") or ""
            tech = c.get("tech") or {}
            if tag == "⚡ TECH":
                return False
            q_pass = (c.get("quality") or {}).get("passes", 0)
            if tag == "💰 VALUE" and q_pass < 3:
                return False
            rsi = tech.get("rsi14")
            if rsi is None or not (38 <= rsi <= 48):
                return False
            slope = tech.get("sma50_slope_pct")
            if slope is None or slope < 1.0:
                return False
            return True
        cands = [c for c in cands if _passes_current_rules(c)]
        fresh = [c for c in cands if not c["in_watchlist"] and c["ticker"].upper() not in live_wl_set]
        if not fresh:
            return '<tr><td colspan="12" class="dim">No P1-passing candidates outside the watchlist right now. (Total P1 passers: ' + str(screener_data.get("p1_passers", 0)) + ')</td></tr>'
        rows = []
        for idx, c in enumerate(fresh[:DISCOVERY_CAP]):
            tech = c.get("tech", {})
            f = c.get("fundamentals", {})
            tag = c.get("tag", "—")
            tag_cls = {
                "💎 BUFFETT": "b-green",
                "🏆 QUALITY":  "b-yellow",
                "💰 VALUE":   "b-yellow",
                "⚡ TECH":     "b-dim",
            }.get(tag, "b-dim")
            sector = c.get("sector") or f.get("sector") or "—"
            rsi    = tech.get("rsi14")
            atr_p  = tech.get("atr_pct")
            price  = tech.get("price")
            pe     = f.get("trailing_pe")
            fcf    = f.get("free_cashflow"); mcap = f.get("market_cap")
            fcfy   = (fcf/mcap*100) if (fcf and mcap and fcf > 0) else None
            q = c.get("quality", {}); v = c.get("value", {})
            q_str = f"{q.get('passes',0)}/{q.get('total',5)}"
            v_str = f"{v.get('passes',0)}/{v.get('total',3)}"
            q_checks = q.get("checks", [])
            v_checks = v.get("checks", [])
            name = (f.get("name") or c["ticker"])[:40].replace("'", "")
            auto_thesis = f"{name}; {sector}; {tag.split(' ',1)[1] if ' ' in tag else tag} candidate ex-screener"
            wl_cmd = f"python3 .claude/skills/watchlist/wl.py add {c['ticker']} --thesis '{auto_thesis}' -y"
            tag_tip = c.get("tag_desc", "")

            # Build details panel (full Q/V gate breakdown + synthesized why)
            def render_checks(checks, tip):
                if not checks: return '<div class="dim">no detail</div>'
                lines = []
                for item in checks:
                    # Tolerate both new 3-tuple format and legacy string-only format
                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                        label, ok, why = item[0], item[1], item[2]
                    elif isinstance(item, str):
                        label, ok, why = item, False, "legacy cache — refresh screener for detail"
                    else:
                        continue
                    icon = "✓" if ok else "✗"
                    cls = "green" if ok else "red"
                    lines.append(f'<div class="gate-line"><span class="{cls}">{icon}</span> <b>{html.escape(str(label))}</b> — {html.escape(str(why))}</div>')
                return "\n".join(lines)
            details_html = (
                f'<div class="discovery-details-content">'
                f'  <div class="dd-thesis">{synthesize_thesis(c, f, tech, tag, q_checks, v_checks, sector)}</div>'
                f'  <div class="dd-gates-grid">'
                f'    <div class="dd-gate-col"><div class="dd-gate-head">Quality gates ({q_str})</div>{render_checks(q_checks, "")}</div>'
                f'    <div class="dd-gate-col"><div class="dd-gate-head">Value gates ({v_str})</div>{render_checks(v_checks, "")}</div>'
                f'  </div>'
                f'  <div class="dd-meta">'
                f'    <span><b>Industry:</b> {html.escape((f.get("industry") or "—"))}</span>'
                f'    <span><b>Market cap:</b> {fmt_money(mcap) if mcap else "—"}</span>'
                f'    <span><b>FCF:</b> {fmt_money(fcf) if fcf else "—"}</span>'
                f'    <span><b>Rev growth YoY:</b> {(f.get("revenue_growth_yoy") or 0)*100:.1f}%</span>'
                f'    <span><b>ROE:</b> {(f.get("roe") or 0)*100:.1f}%</span>'
                f'    <span><b>Debt/Equity:</b> {(f.get("debt_equity") or 0):.0f}</span>'
                f'  </div>'
                f'</div>'
            )

            rows.append(f"""
<tr class="discovery-row" data-row-id="dd-{idx}">
  <td><span class="discovery-chevron">▶</span></td>
  <td><span class="badge {tag_cls}" title="{html.escape(tag_tip, quote=True)}">{html.escape(tag)}</span></td>
  <td><b>{html.escape(c['ticker'])}</b></td>
  <td class="dim">{html.escape((f.get('name') or '')[:24])}</td>
  <td class="dim">{html.escape(sector[:18])}</td>
  <td class="num">{fmt_num(price, 2)}</td>
  <td class="num">{fmt_num(rsi, 1)}</td>
  <td class="num" title="Daily ATR(14) as % of price">{fmt_num(atr_p, 2)}%</td>
  <td class="num" title="Trailing P/E">{fmt_num(pe, 1)}</td>
  <td class="num" title="Free cash flow yield = FCF/market cap">{fmt_num(fcfy, 2) + '%' if fcfy is not None else '—'}</td>
  <td class="num" title="Quality gates: ROE>15%, gross>35%, op>15%, D/E<150, rev growth>8%">{q_str}</td>
  <td class="num" title="Value gates: P/E<25, fwd P/E<trailing, FCF yield>4%">{v_str}</td>
  <td><button class="discovery-add" data-cmd="{html.escape(wl_cmd, quote=True)}" data-ticker="{html.escape(c['ticker'], quote=True)}" title="Copy add-to-watchlist command">+ Add</button></td>
</tr>
<tr class="discovery-details" id="dd-{idx}-body"><td colspan="13">{details_html}</td></tr>""")
        return "\n".join(rows)

    screener_age = fmt_fetched((screener_data or {}).get("_generated_at"))
    sector_age   = fmt_fetched((sector_data or {}).get("_fetched_at"))
    sector_stale_note = ""
    if (sector_data or {}).get("_stale"):
        reason = (sector_data or {}).get("_stale_reason", "stale")
        sector_stale_note = f' <span style="color:var(--yellow);font-weight:bold">⚠ STALE: {html.escape(reason)}</span>'
    screener_stale_note = ""
    if (screener_data or {}).get("_stale"):
        reason = (screener_data or {}).get("_stale_reason", "stale")
        screener_stale_note = f' <span style="color:var(--yellow);font-weight:bold">⚠ STALE: {html.escape(reason)}</span>'
    else:
        # v1.9.1 bug fix: detect the silent-stale case the dashboard used to hide.
        # The screener has an 18h full-pass TTL. If our cache is older than that,
        # the next refresh tried and failed (likely cooldown or process-kill).
        # Also surface active cooldown explicitly so the operator knows why
        # subsequent refreshes are getting blocked.
        gen_at = (screener_data or {}).get("_generated_at") or (screener_data or {}).get("_last_full_pass_at")
        if gen_at:
            try:
                age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(gen_at)).total_seconds() / 3600.0
            except Exception:
                age_h = None
            if age_h is not None and age_h > 18.0:
                screener_stale_note = (
                    f' <span style="color:var(--yellow);font-weight:bold">⚠ STALE — last full pass {age_h:.0f}h ago '
                    f'(TTL 18h). Likely cause: a recent screener run errored out and the cooldown file '
                    f'is blocking the retry. Try <code>--force</code>.</span>'
                )
        cooldown_file = PROJECT_ROOT / ".claude" / "cache" / "screener" / ".yfinance_cooldown_until"
        if cooldown_file.is_file():
            try:
                until = datetime.fromisoformat(cooldown_file.read_text().strip())
                rem_min = (until - datetime.now(timezone.utc)).total_seconds() / 60.0
                if rem_min > 0:
                    screener_stale_note += (
                        f' <span style="color:var(--yellow);font-weight:bold">· 🥶 screener cooldown active '
                        f'({rem_min:.0f} min remaining) — refreshes will skip the screener until then. '
                        f'Pass <code>--force</code> to override.</span>'
                    )
            except Exception:
                pass
    n_universe   = (screener_data or {}).get("universe_size", "—")
    n_p1passers  = (screener_data or {}).get("p1_passers", "—")
    n_fresh      = 0
    if screener_data:
        n_fresh = sum(1 for c in screener_data.get("candidates", []) if not c.get("in_watchlist"))
    n_shown = min(n_fresh, 20)
    counter_text = f"showing {n_shown} of {n_fresh} fresh candidates" if n_shown else "no fresh candidates"
    discovery_panel = f"""
<div class="panel">
  <h2>🔭 Discovery <span class="stale">sector rotation fetched {sector_age}{sector_stale_note} · screener generated {screener_age}{screener_stale_note} · {n_universe} universe · {n_p1passers} P1 passers · {counter_text}</span></h2>
  {render_sector_strip()}
  <div style="color:var(--dim);font-size:11px;margin:14px 0 6px">
    Top P1-passing candidates NOT already on watchlist (capped at 20) — sorted by Buffett tag then composite score.
    Click the <b>▶</b> chevron on any row to expand full reasoning. Click <b>+ Add</b> to copy a watchlist command.
  </div>
  <table>
    <thead><tr>
      <th></th>
      <th>Tag</th><th>Ticker</th><th>Name</th><th>Sector</th>
      <th>Price</th><th>RSI</th><th>ATR%</th><th>P/E</th><th>FCF yld</th>
      <th title="Quality gates: ROE>15%, gross>35%, op>15%, D/E<150, rev growth>8%">Q</th>
      <th title="Value gates: P/E<25, fwd<trailing, FCF yield>4%">V</th>
      <th>Add</th>
    </tr></thead>
    <tbody>{render_screener_rows()}</tbody>
  </table>
</div>
<script>
(function(){{
  // Add-to-watchlist clipboard copy
  document.querySelectorAll('.discovery-add').forEach(btn => {{
    btn.addEventListener('click', (e) => {{
      e.stopPropagation();
      const cmd = btn.dataset.cmd;
      navigator.clipboard.writeText(cmd).then(() => {{
        const orig = btn.textContent;
        btn.classList.add('copied');
        btn.textContent = '✓ copied';
        setTimeout(() => {{ btn.classList.remove('copied'); btn.textContent = orig; }}, 2200);
      }});
    }});
  }});
  // Expandable details — click row (anywhere except Add button) to toggle
  document.querySelectorAll('tr.discovery-row').forEach(row => {{
    row.addEventListener('click', () => {{
      const id = row.dataset.rowId;
      const body = document.getElementById(id + '-body');
      const chev = row.querySelector('.discovery-chevron');
      if (!body) return;
      const opening = !body.classList.contains('open');
      body.classList.toggle('open', opening);
      row.classList.toggle('expanded', opening);
      if (chev) chev.textContent = opening ? '▼' : '▶';
    }});
  }});
}})();
</script>
"""

    # US grid
    us_news_cache = ctx.get("us_news_cache", {})

    def news_age_cell(ticker):
        entry = us_news_cache.get(ticker.upper())
        if not entry:
            return ("—", "—", "dim")
        if entry.get("error"):
            return ("err", "error", "red")
        age = entry.get("age_h")
        if age is None:
            return ("—", "—", "dim")
        if age < 24:
            txt = f"{age:.0f}h"
        else:
            txt = f"{age/24:.0f}d"
        if age < 12:
            cls = "green"
        elif age < 72:
            cls = ""
        else:
            cls = "dim"
        return (txt, f"{age:.1f}", cls)

    def render_btfd_str_panel():
        """Surface watchlist names showing large % moves on outsized volume.
        BTFD = Buy The F***ing Dip (entry candidate review, long bias).
        STR  = Sell The Rip (profit-take / trim candidate review on existing longs;
               occasionally a Phase 2+ short candidate).

        Asset-class-aware thresholds — crypto moves 2-3x bigger normally, so its
        tiers are calibrated wider:

                  Equity                       Crypto
        BTFD 🩸  drop ≤ −7%, vol ≥ 2.5×, RSI≤30   drop ≤ −12%, vol ≥ 3×,   RSI≤25
        BTFD 💧  drop ≤ −4%, vol ≥ 1.8×, RSI≤40   drop ≤ −7%,  vol ≥ 2×,   RSI≤35
        BTFD ⬇️  drop ≤ −2%, vol ≥ 1.3×           drop ≤ −4%,  vol ≥ 1.5×
        STR  🚀  rip  ≥ +7%, vol ≥ 2.5×, RSI≥70   rip  ≥ +12%, vol ≥ 3×,   RSI≥75
        STR  💸  rip  ≥ +4%, vol ≥ 1.8×, RSI≥60   rip  ≥ +7%,  vol ≥ 2×,   RSI≥65
        STR  ⬆️  rip  ≥ +2%, vol ≥ 1.3×           rip  ≥ +4%,  vol ≥ 1.5×

        Cross-signals layered on top (boosts/warnings, do not change tier classification):
          - 🧊 BUY sentiment on a BTFD-flagged name = high-conviction capitulation
          - 🔥 FADE sentiment on a STR-flagged name = high-conviction exhaustion
          - Halt-window proximity (FOMC/CPI/NFP within 12-24h) = ⚠ event-risk warning

        Per AGENTS.md doctrine: this panel generates CANDIDATES FOR REVIEW, not trades.
        The §4 confluence rule still applies — technical + one of {sentiment, fundamentals,
        flow} before any entry. The panel surfaces *where to look*, not *what to do*.
        """
        # Tier thresholds, indexed by asset_class and direction
        # Tier emoji choice: 🩸/💧/⬇️ for dips, 🚀/💸/⬆️ for rips. The arrow emojis
        # (⬇️/⬆️) avoid colliding with 📉/📈 used by the retail-sentiment column for
        # BEAR/BULL — both can appear in the same row and 📉/📈 would be ambiguous.
        BTFD = {
            "equity": [
                ("🩸 CAPITULATION", "btfd-cap",   -7.0, 2.5, 30),
                ("💧 REAL DIP",     "btfd-real", -4.0, 1.8, 40),
                ("⬇️ LIGHT DIP",   "btfd-light",-2.0, 1.3, None),
            ],
            "crypto": [
                ("🩸 CAPITULATION", "btfd-cap",   -12.0, 3.0, 25),
                ("💧 REAL DIP",     "btfd-real",  -7.0,  2.0, 35),
                ("⬇️ LIGHT DIP",   "btfd-light", -4.0,  1.5, None),
            ],
        }
        STR_TIERS = {
            "equity": [
                ("🚀 BLOW-OFF",  "str-blow",  7.0, 2.5, 70),
                ("💸 REAL RIP",  "str-real",  4.0, 1.8, 60),
                ("⬆️ LIGHT RIP","str-light", 2.0, 1.3, None),
            ],
            "crypto": [
                ("🚀 BLOW-OFF",  "str-blow",  12.0, 3.0, 75),
                ("💸 REAL RIP",  "str-real",  7.0,  2.0, 65),
                ("⬆️ LIGHT RIP","str-light", 4.0,  1.5, None),
            ],
        }

        def classify(chg, vol_ratio, rsi, asset_kind):
            """Return (tier_label, tier_cls, direction) or (None, None, None)."""
            if chg is None or vol_ratio is None:
                return None, None, None
            # BTFD: chg is negative
            for label, cls, thr_chg, thr_vol, thr_rsi in BTFD[asset_kind]:
                if chg <= thr_chg and vol_ratio >= thr_vol and (thr_rsi is None or (rsi is not None and rsi <= thr_rsi)):
                    return label, cls, "BTFD"
            # STR: chg is positive
            for label, cls, thr_chg, thr_vol, thr_rsi in STR_TIERS[asset_kind]:
                if chg >= thr_chg and vol_ratio >= thr_vol and (thr_rsi is None or (rsi is not None and rsi >= thr_rsi)):
                    return label, cls, "STR"
            return None, None, None

        # Pre-build halt-window lookup (any FOMC/CPI/NFP within 24h flags every US/equity row)
        macro_events_local = (ctx.get("macro_calendar") or {}).get("events", []) or []
        in_24h_halt = any(ev.get("hours_until") is not None and 0 <= ev["hours_until"] <= 24 for ev in macro_events_local)
        next_macro_event = None
        for ev in macro_events_local:
            hrs = ev.get("hours_until")
            if hrs is not None and hrs > 0:
                next_macro_event = ev
                break

        rows_btfd = []
        rows_str = []

        def collect(ticker, asset_class, asset_kind, chg, vol_ratio, rsi, atr_pct, vs50, vs200, name="—", earnings_warning=False):
            label, cls, direction = classify(chg, vol_ratio, rsi, asset_kind)
            if not label:
                return
            # Cross-signals
            sent = (ctx.get("sentiment") or {}).get(ticker.upper())
            sent_flag = ((sent or {}).get("composite") or {}).get("contrarian_flag") if sent else None
            sent_boost = ""
            if direction == "BTFD" and sent_flag == "BUY":
                sent_boost = ' <span class="boost-up">+ 🧊 BUY sentiment</span>'
            elif direction == "STR" and sent_flag == "FADE":
                sent_boost = ' <span class="boost-up">+ 🔥 FADE sentiment</span>'
            elif sent_flag:
                # Mention sentiment even if direction-aligned isn't true (informational)
                sent_boost = f' <span class="dim" style="font-size:10px">· sentiment: {sent_flag}</span>'

            # Event-risk warnings (US-equity halt windows only — KLSE & crypto don't use macro-calendar)
            event_warn = ""
            if asset_kind == "equity" and asset_class == "us":
                if in_24h_halt and next_macro_event is not None:
                    event_warn = f' <span class="event-warn">⚠ {html.escape(next_macro_event.get("type","event"))} in {next_macro_event["hours_until"]:.0f}h</span>'
                if earnings_warning:
                    event_warn += ' <span class="event-warn">⚠ earnings within 24h</span>'

            atr_mult = (abs(chg) / atr_pct) if (atr_pct and atr_pct > 0) else None

            # Technical context line — where is price relative to key MAs?
            tech_ctx = []
            if vs50 is not None:
                tech_ctx.append(f"{vs50:+.1f}% vs SMA50")
            if vs200 is not None and asset_kind != "crypto":  # crypto SMA200 less universal
                tech_ctx.append(f"{vs200:+.1f}% vs SMA200")
            tech_ctx_str = " · ".join(tech_ctx) if tech_ctx else ""

            rsi_str = f"RSI {rsi:.0f}" if rsi is not None else "RSI —"
            atr_mult_str = f"{atr_mult:.1f}× ATR" if atr_mult is not None else ""

            row_html = (
                f'<div class="bs-row {cls}">'
                f'  <span class="bs-tier">{label}</span>'
                f'  <span class="bs-ticker">{html.escape(ticker)}</span>'
                f'  <span class="bs-class">{asset_class}</span>'
                f'  <span class="bs-name dim">{html.escape((name or "")[:28])}</span>'
                f'  <span class="bs-stats">{chg:+.1f}% · vol {vol_ratio:.1f}× · {rsi_str} {("· " + atr_mult_str) if atr_mult_str else ""}</span>'
                f'  <span class="bs-tech dim">{tech_ctx_str}</span>'
                f'  <span class="bs-cross">{sent_boost}{event_warn}</span>'
                f'</div>'
            )
            if direction == "BTFD":
                rows_btfd.append((label.startswith("🩸"), abs(chg), row_html))  # capitulation first, then by drop size
            else:
                rows_str.append((label.startswith("🚀"), chg, row_html))

        # US equities
        for entry in ctx.get("watchlist", {}).get("us", []):
            tk = entry["ticker"]
            t = (ctx.get("us_data") or {}).get(tk, {}) or {}
            price = t.get("price")
            atr_pct = (t.get("atr14") / price * 100) if (t.get("atr14") and price) else None
            # Earnings within 24h check
            ne = t.get("next_earnings")
            earn_warn = False
            if ne:
                try:
                    de_h = (datetime.fromisoformat(ne).replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 3600
                    earn_warn = (0 <= de_h <= 24)
                except Exception:
                    pass
            collect(tk, "us", "equity", t.get("change_pct"), t.get("vol_ratio"), t.get("rsi14"),
                    atr_pct, t.get("vs_sma50_pct"), t.get("vs_sma200_pct"),
                    name=t.get("name") or "—", earnings_warning=earn_warn)
        # KLSE
        for entry in ctx.get("watchlist", {}).get("klse", []):
            tk = entry["ticker"]
            t = (ctx.get("klse_data") or {}).get(tk, {}) or {}
            price = t.get("price")
            atr_pct = (t.get("atr14") / price * 100) if (t.get("atr14") and price) else None
            collect(tk, "klse", "equity", t.get("change_pct"), t.get("vol_ratio"), t.get("rsi14"),
                    atr_pct, t.get("vs_sma50_pct"), t.get("vs_sma200_pct"),
                    name=t.get("name") or "—")
        # Crypto — uses 24h CoinGecko change and Binance/CG-derived vol_ratio
        for entry, r in zip(ctx.get("watchlist", {}).get("crypto", []), ctx.get("crypto_rows", [])):
            tk = entry["ticker"]
            ind = (ctx.get("crypto_indicators") or {}).get(tk.upper(), {}) or {}
            chg = r.get("chg_24h")
            vol_ratio = ind.get("vol_ratio")
            rsi = ind.get("rsi14")
            atr_pct = ind.get("atr_pct")
            price = ind.get("price") or r.get("price")
            s50 = ind.get("sma50")
            vs50 = ((price / s50 - 1) * 100) if (price and s50) else None
            collect(tk, "crypto", "crypto", chg, vol_ratio, rsi, atr_pct, vs50, None,
                    name=r.get("name") or tk)

        # Sort: tier severity first, then magnitude
        rows_btfd.sort(key=lambda x: (not x[0], -x[1]))  # capitulations first, then by drop size desc
        rows_str.sort(key=lambda x: (not x[0], -x[1]))   # blow-offs first, then by rip size desc

        def render_section(title_emoji, title_text, rows, empty_msg):
            if not rows:
                return f'<div class="bs-section"><div class="bs-section-head">{title_emoji} {title_text}</div><div class="dim" style="padding:6px 0">{empty_msg}</div></div>'
            return (
                f'<div class="bs-section">'
                f'<div class="bs-section-head">{title_emoji} {title_text} <span class="dim" style="font-size:10px">({len(rows)} candidate{"s" if len(rows)!=1 else ""})</span></div>'
                f'<div class="bs-rows">' + "".join(r[2] for r in rows) + '</div>'
                f'</div>'
            )

        btfd_html = render_section("🩸", "BTFD candidates — large drops on volume",  rows_btfd,
                                   "No watchlist names showing dip + volume signature today.")
        str_html  = render_section("🚀", "STR candidates — large rallies on volume", rows_str,
                                   "No watchlist names showing rip + volume signature today.")

        return (
            f'<div class="panel">'
            f'<h2>🩸 BTFD / 🚀 STR — Price × Volume Setups <span class="stale">large moves on outsized volume across the watchlist</span></h2>'
            f'<div class="cs-explainer dim">'
            f'  Names showing large 24h moves on volume meaningfully above their 30-day average. <b>Candidates for review, not trades.</b> '
            f'  BTFD frames potential dip-buy entries on long bias; STR frames potential profit-take or trim points on existing longs. '
            f'  Per §4, sentiment/news/flow confluence still required before any entry. Cross-signal boosts (🧊 BUY, 🔥 FADE, halt windows) shown inline.'
            f'</div>'
            f'{btfd_html}'
            f'{str_html}'
            f'</div>'
        )

    def render_contrarian_setups_panel():
        """Find watchlist names where the retail-sentiment contrarian flag (🔥 FADE / 🧊 BUY)
        aligns with the underlying technical state. This is the actionable §4 confluence read:
          - 🔥 FADE + extended technicals (RSI > 70 OR > 8% above SMA50) → fade the crowd
          - 🧊 BUY + constructive technicals (RSI 35-55 AND -5% ≤ vs SMA50 ≤ 10%) → capitulation buy
        Plain FADE/BUY flags without technical alignment are informational only — they show in
        the per-ticker Retail column but don't earn a setups-panel slot."""
        setups = []

        def consider(ticker, asset_class, rsi, vs50, name="—"):
            sent = (ctx.get("sentiment") or {}).get(ticker.upper())
            if not sent:
                return
            c = sent.get("composite") or {}
            flag = c.get("contrarian_flag")
            if flag not in ("FADE", "BUY"):
                return
            bull = c.get("bull_score"); bear = c.get("bear_score"); conv = c.get("conviction")
            aligned = False; tech_note = []
            if flag == "FADE":
                if rsi is not None and rsi > 70:
                    aligned = True; tech_note.append(f"RSI {rsi:.0f} (overbought)")
                if vs50 is not None and vs50 > 8:
                    aligned = True; tech_note.append(f"+{vs50:.0f}% vs SMA50 (extended)")
                if not tech_note and rsi is not None:
                    tech_note.append(f"RSI {rsi:.0f} (not extended — flag informational only)")
            elif flag == "BUY":
                rsi_ok = rsi is not None and 35 <= rsi <= 55
                vs50_ok = vs50 is not None and -5 <= vs50 <= 10
                if rsi_ok and vs50_ok:
                    aligned = True; tech_note.append(f"RSI {rsi:.0f} (constructive), {vs50:+.0f}% vs SMA50 (basing)")
                elif rsi_ok:
                    tech_note.append(f"RSI {rsi:.0f} (constructive — but check structure)")
                elif vs50_ok:
                    tech_note.append(f"{vs50:+.0f}% vs SMA50 (basing — but RSI not in 35-55)")

            if not aligned:
                return  # only surface aligned setups; informational-only flags stay in the per-ticker column
            setups.append({
                "ticker": ticker, "asset_class": asset_class, "name": name,
                "flag": flag, "badge": c.get("badge", "—"), "label": c.get("label"),
                "bull": bull, "bear": bear, "conv": conv,
                "rsi": rsi, "vs50": vs50,
                "tech_note": " · ".join(tech_note),
                "rationale": (sent.get("composite") or {}).get("rationale", "—"),
            })

        # US equities
        for entry in ctx.get("watchlist", {}).get("us", []):
            tk = entry["ticker"]
            t = (ctx.get("us_data") or {}).get(tk, {}) or {}
            consider(tk, "us", t.get("rsi14"), t.get("vs_sma50_pct"), t.get("name") or "—")
        # KLSE
        for entry in ctx.get("watchlist", {}).get("klse", []):
            tk = entry["ticker"]
            t = (ctx.get("klse_data") or {}).get(tk, {}) or {}
            consider(tk, "klse", t.get("rsi14"), t.get("vs_sma50_pct"), t.get("name") or "—")
        # Crypto — technicals live in crypto_indicators
        for entry in ctx.get("watchlist", {}).get("crypto", []):
            tk = entry["ticker"]
            ind = (ctx.get("crypto_indicators") or {}).get(tk.upper(), {}) or {}
            rsi = ind.get("rsi14")
            price = ind.get("price")
            s50 = ind.get("sma50")
            vs50 = ((price / s50 - 1) * 100) if (price and s50) else None
            consider(tk, "crypto", rsi, vs50, name=tk)

        # Total flagged count for the no-setup case
        all_flags = []
        for s in (ctx.get("sentiment") or {}).values():
            f = (s.get("composite") or {}).get("contrarian_flag")
            if f in ("FADE", "BUY"):
                all_flags.append(f)
        n_fade = sum(1 for f in all_flags if f == "FADE")
        n_buy = sum(1 for f in all_flags if f == "BUY")

        if not setups:
            body = (
                f'<div class="dim">No contrarian × technical setups today. '
                f'{n_fade} 🔥 FADE flag(s) and {n_buy} 🧊 BUY flag(s) on the watchlist but none have aligned technicals '
                f'(FADE needs RSI&gt;70 or &gt;8% above SMA50; BUY needs RSI 35-55 and -5% to +10% vs SMA50). '
                f'Flags without alignment are informational only — see per-ticker Retail columns above.</div>'
            )
        else:
            rows_html = []
            for s in setups:
                flag_cls = "sent-flag-fade" if s["flag"] == "FADE" else "sent-flag-buy"
                flag_action = "FADE — downgrade conviction on this setup" if s["flag"] == "FADE" else "BUY — upgrade conviction on constructive P1"
                bull_pct = f"{s['bull']*100:.0f}%" if s['bull'] is not None else "—"
                bear_pct = f"{s['bear']*100:.0f}%" if s['bear'] is not None else "—"
                conv_pct = f"{s['conv']*100:.0f}%" if s['conv'] is not None else "—"
                rows_html.append(
                    f'<div class="cs-row">'
                    f'  <span class="cs-badge">{s["badge"]}</span>'
                    f'  <span class="{flag_cls} cs-flag">{s["flag"]}</span>'
                    f'  <span class="cs-ticker">{html.escape(s["ticker"])}</span>'
                    f'  <span class="cs-class">{s["asset_class"]}</span>'
                    f'  <span class="cs-name dim">{html.escape((s["name"] or "")[:32])}</span>'
                    f'  <span class="cs-stats">bull {bull_pct} · bear {bear_pct} · conv {conv_pct}</span>'
                    f'  <span class="cs-tech">{html.escape(s["tech_note"])}</span>'
                    f'  <div class="cs-action">→ {flag_action}</div>'
                    f'  <div class="cs-rationale dim">{html.escape(s["rationale"])}</div>'
                    f'</div>'
                )
            body = '<div class="cs-rows">' + "".join(rows_html) + '</div>'

        return (
            f'<div class="panel">'
            f'<h2>⚠ Contrarian Setups <span class="stale">retail sentiment × technical alignment (§4 contrarian-filter doctrine)</span></h2>'
            f'<div class="cs-explainer dim">'
            f'  Watchlist names where a retail-sentiment flag (🔥 FADE for crowded longs, 🧊 BUY for capitulation) coincides with '
            f'  technical extension or constructive setup. <b>Flags alone are not trade signals</b> — they modify conviction on '
            f'  existing setups. Mid-range sentiment and unaligned flags stay in the per-ticker Retail columns below.'
            f'</div>'
            f'{body}'
            f'</div>'
        )

    def render_polymarket_panel():
        """Render the Event Probabilities panel from the Polymarket cache."""
        pm = ctx.get("polymarket") or {}
        cats = pm.get("categories") or {}
        fetched = pm.get("fetched_at")
        if not cats:
            return (
                '<div class="panel">'
                '<h2>Event Probabilities (Polymarket)</h2>'
                '<div class="dim">No Polymarket cache. Run: <code>python3 .claude/skills/polymarket-events/polymarket_events.py</code></div>'
                '</div>'
            )

        CAT_LABELS = {
            "macro_rates":  "Macro · Rates",
            "macro_econ":   "Macro · Economy",
            "crypto":       "Crypto · Price",
            "geopolitics":  "Geopolitics",
        }

        def fmt_delta(d):
            if d is None:
                return ""
            arrow = "▲" if d > 0.005 else ("▼" if d < -0.005 else "·")
            cls = "up" if d > 0.005 else ("down" if d < -0.005 else "flat")
            return f' <span class="arrow {cls}" style="font-size:10px">{arrow} {d*100:+.0f}pp</span>'

        cols = []
        for cat_key, cat_label in CAT_LABELS.items():
            evs = (cats.get(cat_key) or {}).get("events", []) or []
            # Sort by abs probability extremity (most decisive markets first), then by abs delta
            evs_sorted = sorted(
                evs,
                key=lambda e: (abs((e.get("headline_prob") or 0.5) - 0.5)),
                reverse=True,
            )
            rows_html = []
            for ev in evs_sorted[:5]:
                hp = ev.get("headline_prob")
                hq = ev.get("headline_question") or "—"
                title = ev.get("title") or "—"
                url = ev.get("url") or "#"
                hp_pct = f"{hp*100:.0f}%" if hp is not None else "—"
                # Delta on the headline market
                top_market = (ev.get("markets") or [{}])[0]
                d = top_market.get("delta_7d")
                # Tint by probability extremity
                if hp is not None:
                    if hp >= 0.75: prob_cls = "pm-high"
                    elif hp <= 0.25: prob_cls = "pm-low"
                    else: prob_cls = "pm-mid"
                else:
                    prob_cls = "pm-mid"
                rows_html.append(
                    f'<div class="pm-row" title="{html.escape(hq, quote=True)}">'
                    f'<span class="pm-prob {prob_cls}">{hp_pct}</span>'
                    f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" class="pm-title">{html.escape(title[:75])}</a>'
                    f'{fmt_delta(d)}'
                    f'</div>'
                )
            if not rows_html:
                rows_html.append('<div class="dim" style="padding:4px 0">no events</div>')
            cols.append(
                f'<div class="pm-col">'
                f'<div class="pm-head">{html.escape(cat_label)}</div>'
                f'{"".join(rows_html)}'
                f'</div>'
            )
        return (
            f'<div class="panel">'
            f'<h2>Event Probabilities <span class="stale">Polymarket · fetched {fmt_fetched(fetched)} · Δ7d shown when historical snapshot available</span></h2>'
            f'<div class="pm-grid">{"".join(cols)}</div>'
            f'</div>'
        )

    def sentiment_details_html(ticker):
        """Render the expanded sentiment block for a row's dropdown details.
        Shows badge, scores, per-source breakdown, and rationale. Used inside exp-details-content."""
        s = (ctx.get("sentiment") or {}).get(ticker.upper())
        if not s:
            return (
                '<div class="exp-gate-col">'
                '<div class="exp-gate-head">Retail Sentiment</div>'
                '<div class="gate-line dim">No sentiment cache. Run reddit-sentiment + stocktwits-sentiment + sentiment-cache to populate.</div>'
                '</div>'
            )
        c = s.get("composite") or {}
        srcs = s.get("sources") or {}
        st = srcs.get("stocktwits") or {}
        rd = srcs.get("reddit") or {}
        hn = srcs.get("hackernews") or {}
        badge = c.get("badge", "—"); label = c.get("label", "UNKNOWN")
        bs = c.get("bull_score"); bear = c.get("bear_score"); neut = c.get("neutral_score"); conv = c.get("conviction")
        flag = c.get("contrarian_flag")
        scored_at = s.get("scored_at", "—")
        model = s.get("model", "—")

        if label == "UNKNOWN" or bs is None:
            return (
                '<div class="exp-gate-col">'
                '<div class="exp-gate-head">Retail Sentiment</div>'
                f'<div class="gate-line dim">— UNKNOWN (no source data). Scored {html.escape(scored_at)}.</div>'
                '</div>'
            )

        flag_html = ""
        if flag == "FADE":
            flag_html = ' <span class="sent-flag-fade">FADE</span> <span class="dim" style="font-size:11px">(contrarian: downgrade conviction on extended setups)</span>'
        elif flag == "BUY":
            flag_html = ' <span class="sent-flag-buy">BUY</span> <span class="dim" style="font-size:11px">(contrarian: upgrade conviction on constructive P1)</span>'

        def pct(v, places=0):
            return f"{v*100:.{places}f}%" if v is not None else "—"

        st_line = ""
        if st.get("present"):
            ut = st.get("user_tagged_bull_pct")
            tagged = st.get("tagged_counts") or {}
            ut_str = f"{pct(ut)} user-tagged bull (of {tagged.get('Bullish',0)+tagged.get('Bearish',0)} tagged)" if ut is not None else "no user-tagged messages"
            st_line = (
                f'<div class="gate-line"><b>StockTwits:</b> {st.get("n_messages",0)} msgs · {ut_str} · '
                f'LLM bull/bear/neut <b>{pct(st.get("llm_bull_pct"))} / {pct(st.get("llm_bear_pct"))} / {pct(st.get("llm_neutral_pct"))}</b> '
                f'<span class="dim">(LLM avg conviction {pct(st.get("llm_avg_conviction"))})</span></div>'
            )
        else:
            st_line = '<div class="gate-line dim"><b>StockTwits:</b> absent (no coverage or no messages)</div>'

        rd_line = ""
        if rd.get("present"):
            src = rd.get("engagement_source", "rss")
            src_note = (
                ' <span class="dim" style="font-size:10px">[OAuth — per-comment scores live]</span>'
                if src == "oauth" else
                ' <span class="dim" style="font-size:10px" title="RSS path — comments have no per-item score; engagement weighting uses a uniform floor. Set up Reddit OAuth credentials to unlock real upvote weighting.">[RSS — uniform comment weight]</span>'
            )
            rd_line = (
                f'<div class="gate-line"><b>Reddit:</b> {rd.get("n_posts",0)} posts + {rd.get("n_comments",0)} comments '
                f'(of {rd.get("mention_count",0)} total mentions, {rd.get("n_scored_bodies",0)} scored) · '
                f'LLM bull/bear/neut <b>{pct(rd.get("llm_bull_pct"))} / {pct(rd.get("llm_bear_pct"))} / {pct(rd.get("llm_neutral_pct"))}</b> '
                f'<span class="dim">(conv {pct(rd.get("llm_avg_conviction"))})</span>'
                f'{src_note}</div>'
            )
        else:
            rd_line = '<div class="gate-line dim"><b>Reddit:</b> absent (no posts in lookback window, or no Reddit data)</div>'

        hn_line = ""
        if hn.get("present"):
            hn_line = (
                f'<div class="gate-line"><b>Hacker News:</b> {hn.get("story_count",0)} stories · '
                f'{hn.get("n_bodies_scored",0)} bodies scored (engagement {hn.get("total_engagement",0)}) · '
                f'LLM bull/bear/neut <b>{pct(hn.get("llm_bull_pct"))} / {pct(hn.get("llm_bear_pct"))} / {pct(hn.get("llm_neutral_pct"))}</b> '
                f'<span class="dim">(conviction {pct(hn.get("llm_avg_conviction"))})</span></div>'
            )
        else:
            hn_line = '<div class="gate-line dim"><b>Hacker News:</b> absent (no coverage in last 30d, or ticker mapped-to-skip)</div>'

        return (
            '<div class="exp-gate-col">'
            f'<div class="exp-gate-head">Retail Sentiment <span class="dim" style="font-size:10px">(engagement-weighted)</span></div>'
            f'<div class="gate-line"><b>{badge} {html.escape(label)}</b>{flag_html}</div>'
            f'<div class="gate-line">Composite: bull <b>{pct(bs)}</b> · bear <b>{pct(bear)}</b> · neutral <b>{pct(neut)}</b> · conviction <b>{pct(conv)}</b></div>'
            f'{st_line}'
            f'{rd_line}'
            f'{hn_line}'
            f'<div class="gate-line dim" style="margin-top:6px;font-size:11px">Scored {html.escape(scored_at)} · model {html.escape(model)}</div>'
            '</div>'
        )

    # v1.9.2: Polymarket inline surfacing — pick the most-relevant money-backed
    # markets per watchlist ticker for the sentiment dropdown. Surface only, do
    # not fold into the bull/bear% composite (AGENTS.md §4 keeps Polymarket as
    # categorically-different signal from forum/retail sentiment).
    _CRYPTO_KEYWORDS = {
        "BTC":  ["bitcoin", "btc"],
        "ETH":  ["ethereum", "eth"],
        "SOL":  ["solana"],
        "BNB":  ["binance"],
        "XRP":  ["xrp", "ripple"],
        "HBAR": ["hedera"],
        "HYPE": ["hyperliquid"],
        "ENA":  ["ethena"],
        "ONDO": ["ondo"],
    }
    _BTC_PROXY_EQUITIES = {"CLSK", "CIFR", "RIOT", "MARA", "MSTR", "COIN", "HOOD"}

    def _polymarket_signals_for(ticker, asset_class, max_items=3):
        """Return list of {question, prob, vol_24h, liquidity, category, lean} tuples
        most relevant to this ticker. Empty list if no relevant markets exist."""
        pm = ctx.get("polymarket") or {}
        cats = pm.get("categories") or {}
        all_events = []
        for cat_name, cat in cats.items():
            for ev in (cat.get("events") or []):
                for m in (ev.get("markets") or []):
                    yp = m.get("yes_price")
                    if yp is None:
                        continue
                    all_events.append({
                        "category": cat_name,
                        "event_title": ev.get("title") or "",
                        "question": m.get("question") or "—",
                        "prob": yp,
                        "vol_24h": m.get("volume_24h") or 0,
                        "liquidity": m.get("liquidity") or 0,
                    })
        if not all_events:
            return []

        def _matches_keywords(m, kws):
            text = (m["question"] + " " + m["event_title"]).lower()
            return any(kw in text for kw in kws)

        relevant = []
        if asset_class == "crypto":
            kws = _CRYPTO_KEYWORDS.get(ticker.upper())
            if kws:
                relevant = [m for m in all_events
                            if m["category"] == "crypto" and _matches_keywords(m, kws)]
            # Fall back: any crypto-category market
            if not relevant:
                relevant = [m for m in all_events if m["category"] == "crypto"]
        elif asset_class == "us":
            # BTC-proxy equities get BTC markets first, then macro
            if ticker.upper() in _BTC_PROXY_EQUITIES:
                relevant = [m for m in all_events
                            if m["category"] == "crypto" and _matches_keywords(m, ["bitcoin", "btc"])]
            # Add general macro_rates + macro_econ as broad-market context
            relevant += [m for m in all_events if m["category"] in ("macro_rates", "macro_econ")]
        # KLSE has no Polymarket coverage — return empty

        # Rank by volume_24h (the "real money" signal) desc, take top N
        relevant.sort(key=lambda x: x["vol_24h"], reverse=True)
        # Tag each market with a directional lean for the operator
        out = []
        for m in relevant[:max_items]:
            p = m["prob"]
            if p >= 0.80:
                lean = ("strong-yes", "🟢")
            elif p >= 0.60:
                lean = ("lean-yes", "🟡")
            elif p <= 0.20:
                lean = ("strong-no", "🔴")
            elif p <= 0.40:
                lean = ("lean-no", "🟠")
            else:
                lean = ("uncertain", "⚪")
            out.append({**m, "lean_label": lean[0], "lean_glyph": lean[1]})
        return out

    def _polymarket_inline_html(ticker, asset_class):
        """Render the Polymarket money-backed section for a row's expanded dropdown."""
        sigs = _polymarket_signals_for(ticker, asset_class)
        if not sigs:
            if asset_class == "klse":
                return ('<div class="gate-line dim" style="font-size:11px"><b>🪙 Money-backed (Polymarket):</b> '
                        'no coverage (Polymarket doesn\'t carry KLSE markets)</div>')
            return ('<div class="gate-line dim" style="font-size:11px"><b>🪙 Money-backed (Polymarket):</b> '
                    'no relevant markets in cache (run polymarket-events refresh)</div>')

        def _fmt_vol(v):
            if v is None or v <= 0: return "—"
            if v >= 1_000_000: return f"${v/1_000_000:.1f}M"
            if v >= 1_000:     return f"${v/1_000:.0f}K"
            return f"${v:.0f}"

        rows = []
        for s in sigs:
            q = html.escape(s["question"][:72])
            prob_pct = f"{s['prob']*100:.0f}%"
            rows.append(
                f'<div class="gate-line" style="font-size:11px">'
                f'  {s["lean_glyph"]} <b>{prob_pct}</b> · {q} '
                f'<span class="dim">[{_fmt_vol(s["vol_24h"])} 24h vol]</span>'
                f'</div>'
            )
        return (
            '<div class="gate-line" style="font-size:11px;margin-top:6px"><b>🪙 Money-backed (Polymarket):</b> '
            '<span class="dim">real-money odds, ranked by 24h volume</span></div>'
            + "\n".join(rows)
        )

    def _news_glyph_payload(ticker, asset_class):
        """Look up the pre-computed news glyph for a watchlist entry.

        Keys: US uses uppercase ticker; KLSE uses the 4-digit code (with .KL stripped);
        crypto uses the watchlist symbol uppercase (e.g. 'BTC') OR the CG slug — both
        are pre-indexed in ctx['news_glyphs']."""
        glyphs = ctx.get("news_glyphs") or {}
        if asset_class == "klse":
            key = klse_code(ticker)
        else:
            key = str(ticker).upper()
        return glyphs.get((asset_class, key))

    def _news_glyph_inline(ticker, asset_class):
        """Return an inline `<span>📈❗</span>` (or empty string) to append to a sentiment cell.
        72h window drives the glyph color (🟢/🔴/⚪); ❗ modifier marks fresh analyst action."""
        if ctx.get("news_glyphs_skipped"):
            return ""  # operator-intentional skip via --no-news-glyph — not an error
        g = _news_glyph_payload(ticker, asset_class)
        if not g:
            return ""
        glyph = (g.get("glyph") or "⚪") + (g.get("modifier") or "")
        tip = html.escape(f"News (72h): {g.get('summary','')}" +
                          (f" · {g['caveat']}" if g.get("caveat") else ""), quote=True)
        return f' <span class="news-glyph" title="{tip}" style="font-size:13px">{glyph}</span>'

    def _news_glyph_details_html(ticker, asset_class):
        """Render the News section for a row's expanded dropdown."""
        if ctx.get("news_glyphs_skipped"):
            return (
                '<div class="exp-gate-col"><div class="exp-gate-head">News</div>'
                '<div class="gate-line dim">News glyph disabled for this build '
                '(<code>--no-news-glyph</code> flag was passed). '
                'Re-run the dashboard without that flag to load the cache.</div></div>'
            )
        g = _news_glyph_payload(ticker, asset_class)
        if not g:
            return (
                '<div class="exp-gate-col"><div class="exp-gate-head">News</div>'
                '<div class="gate-line dim">No news cache for this ticker. Run '
                '<code>python3 .claude/skills/us-news/news_glyph.py refresh-' + asset_class + ' --...</code> '
                'to populate, or press <b>📰 News refresh</b> on the dashboard header.</div></div>'
            )
        glyph = (g.get("glyph") or "⚪") + (g.get("modifier") or "")
        head = f'<div class="exp-gate-head">News {glyph} <span class="dim" style="font-size:11px">· {html.escape(g.get("summary","") or "")}</span></div>'

        def _row(it, is_old=False):
            dt = it.get("dt") or ""
            try:
                d_local = datetime.fromisoformat(dt).astimezone().strftime("%b %d %H:%M")
            except Exception:
                d_local = dt[:16]
            src = html.escape((it.get("source") or "")[:24])
            head_txt = html.escape((it.get("headline") or "")[:160])
            url = it.get("url") or ""
            link = (f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener" '
                    f'onclick="event.stopPropagation()">{head_txt}</a>') if url else head_txt
            mark = "❗ " if it.get("is_analyst_action") else ""
            score = it.get("sentiment_score")
            score_html = ""
            if isinstance(score, (int, float)):
                cls = "green" if score >= 0.15 else "red" if score <= -0.15 else "dim"
                # Always render, even at 0.00, so the dropdown average reconciles visibly.
                score_html = f' <span class="{cls}" style="font-size:11px">({score:+.2f})</span>'
            cls_outer = "gate-line" + (" dim" if is_old else "")
            return (f'<div class="{cls_outer}" style="font-size:12px">'
                    f'{mark}<span class="dim">{d_local}</span> '
                    f'<span class="dim" style="font-size:10px">[{src}]</span> '
                    f'{link}{score_html}</div>')

        parts = [head]
        # Scrollable inner container — names like SPY can carry 90+ items in 72h.
        scroll_open = '<div class="news-scroll" style="max-height:360px;overflow-y:auto;padding-right:6px;margin-top:4px">'
        scroll_close = '</div>'
        body = []
        items_window = g.get("items_72h") or []
        if items_window:
            for it in items_window[:30]:
                body.append(_row(it))
            if len(items_window) > 30:
                body.append(f'<div class="gate-line dim" style="font-size:11px">… {len(items_window)-30} more in-window item(s) not shown.</div>')
        else:
            body.append('<div class="gate-line dim" style="font-size:12px">No items in 72h.</div>')
        older = g.get("older_context") or []
        if older:
            body.append('<div class="gate-line dim" style="font-size:11px;margin-top:6px;border-top:1px solid var(--dim);padding-top:4px">'
                        '↓ older context (&gt;72h, does not drive glyph) — up to 14d back</div>')
            for it in older[:15]:
                body.append(_row(it, is_old=True))
            if len(older) > 15:
                body.append(f'<div class="gate-line dim" style="font-size:11px">… {len(older)-15} more older item(s) not shown.</div>')
        parts.append(scroll_open + "\n".join(body) + scroll_close)
        if g.get("caveat"):
            parts.append(f'<div class="gate-line" style="margin-top:6px;font-size:11px;color:var(--warn,#c80)">⚠ {html.escape(g["caveat"])}</div>')
        return '<div class="exp-gate-col">' + "\n".join(parts) + '</div>'

    def sentiment_details_with_polymarket(ticker, asset_class):
        """Wrap sentiment_details_html with the Polymarket inline section appended."""
        base = sentiment_details_html(ticker)
        pm = _polymarket_inline_html(ticker, asset_class)
        # Inject Polymarket inside the same exp-gate-col so it sits below the
        # scored-at line cleanly. The base ends with '</div>' — splice in before it.
        if base.endswith("</div>"):
            return base[:-len("</div>")] + pm + "</div>"
        return base + pm

    def sentiment_cell(ticker, asset_class="us"):
        """Render the Retail Sentiment column cell for one ticker.
        Returns (html_td, sort_key_numeric). Sort key is bull_score - bear_score so
        bullish names sort high and bearish names sort low.
        The cell also carries the news-direction glyph (🟢/🔴/⚪ + optional ❗ analyst
        modifier) appended after the retail badge — full headlines render in the
        row's expanded dropdown via _news_glyph_details_html()."""
        s = (ctx.get("sentiment") or {}).get(ticker.upper())
        ng = _news_glyph_inline(ticker, asset_class)
        if not s:
            return (f'<td class="num dim" data-sort="-2" title="No sentiment cache. Run reddit-sentiment + stocktwits-sentiment + sentiment-cache.">—{ng}</td>', -2)
        c = s.get("composite") or {}
        bs = c.get("bull_score"); bear = c.get("bear_score"); conv = c.get("conviction")
        label = c.get("label", "UNKNOWN"); badge = c.get("badge", "—"); flag = c.get("contrarian_flag")
        rationale = c.get("rationale") or "—"
        sort_key = (bs or 0) - (bear or 0) if bs is not None else -1
        if label == "UNKNOWN" or bs is None:
            return (f'<td class="num dim" data-sort="-1" title="No source data yet.">—{ng}</td>', -1)
        cell_cls = ""
        if flag == "FADE":
            cell_cls = "sent-fade"; flag_html = ' <span class="sent-flag-fade">FADE</span>'
        elif flag == "BUY":
            cell_cls = "sent-buy"; flag_html = ' <span class="sent-flag-buy">BUY</span>'
        else:
            flag_html = ""
        bs_pct = f"{bs*100:.0f}%" if bs is not None else "—"
        cv_pct = f"{conv*100:.0f}%" if conv is not None else "—"
        tooltip = f"{label} · bull={bs_pct} bear={(bear*100 if bear is not None else 0):.0f}% conv={cv_pct}\n{rationale}"
        return (
            f'<td class="num {cell_cls}" data-sort="{sort_key:.3f}" title="{html.escape(tooltip, quote=True)}">'
            f'{badge}{flag_html} <span class="dim" style="font-size:11px">{bs_pct}</span>{ng}'
            f'</td>',
            sort_key,
        )

    def render_us_grid():
        rows = []
        for idx, entry in enumerate(ctx["watchlist"]["us"]):
            tk = entry["ticker"]
            t = ctx["us_data"].get(tk, {})
            badge, label, reason = us_status({**t, "ticker": tk}, macro_events_for_status)
            badge_cls = {"🟢": "b-green", "🔴": "b-red", "🟡": "b-yellow", "⚪": "b-dim", "❓": "b-dim"}[badge]
            ne = t.get("next_earnings") or "—"
            days_to_e = "—"
            try:
                de = (datetime.fromisoformat(ne).replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
                days_to_e = f"{de}d"
            except Exception:
                pass
            price = t.get("price")
            chg = t.get("change_pct")
            chg_cls = "green" if (chg or 0) > 0 else "red" if (chg or 0) < 0 else "dim"
            rsi = t.get("rsi14")
            atr14 = t.get("atr14")
            atr_pct = (atr14 / price * 100) if (atr14 and price) else None
            v50 = t.get("vs_sma50_pct"); v200 = t.get("vs_sma200_pct")
            news_txt, news_sort, news_cls = news_age_cell(tk)
            # Build expandable details
            news_entry = (ctx.get("us_news_cache") or {}).get(tk.upper())
            thesis_html, gates = synthesize_us_thesis(tk, t, label, reason, macro_events_for_status, news_entry)
            gates_html = "\n".join(_gate_html(*g) for g in gates)
            details_html = (
                f'<div class="exp-details-content">'
                f'  <div class="exp-thesis">{thesis_html}</div>'
                f'  <div class="exp-gates-grid">'
                f'    <div class="exp-gate-col"><div class="exp-gate-head">P1 technical gates ({sum(1 for _,o,_ in gates if o)}/{len(gates)})</div>{gates_html}</div>'
                f'    <div class="exp-gate-col"><div class="exp-gate-head">Status decision</div>'
                f'      <div class="gate-line"><b>Label:</b> {html.escape(label)}</div>'
                f'      <div class="gate-line"><b>Reason:</b> {html.escape(reason)}</div>'
                f'      <div class="gate-line dim" style="margin-top:6px;font-size:11px">Tooltip on badge: {html.escape(status_tooltip(label))}</div>'
                f'    </div>'
                f'    {sentiment_details_with_polymarket(tk, "us")}'
                f'    {_news_glyph_details_html(tk, "us")}'
                f'  </div>'
                f'  <div class="exp-meta">'
                f'    <span><b>Sector:</b> {html.escape(t.get("sector") or "—")}</span>'
                f'    <span><b>Market cap:</b> {fmt_money(t.get("market_cap")) if t.get("market_cap") else "—"}</span>'
                f'    <span><b>Currency:</b> {html.escape(t.get("currency") or "USD")}</span>'
                f'    <span><b>vs SMA50:</b> {fmt_pct(v50,2)}</span>'
                f'    <span><b>vs SMA200:</b> {fmt_pct(v200,2)}</span>'
                f'    <span><b>Next earnings:</b> {ne} ({days_to_e})</span>'
                f'  </div>'
                f'</div>'
            )
            rows.append(f"""
<tr class="exp-row" data-row-id="us-{idx}">
  <td><span class="exp-chevron">▶</span><button class="wl-remove-btn" onclick="event.stopPropagation(); wlRemove('{html.escape(tk, quote=True)}')" title="Remove from watchlist">🗑️</button></td>
  <td><b>{html.escape(tk)}</b></td>
  <td class="dim">{html.escape((t.get('name') or '')[:24])}</td>
  <td class="num{' stale-price' if _price_stale(t.get('price_date')) else ''}" data-sort="{price or 0}" title="{_price_tooltip(t.get('price_date'))}">{fmt_num(price,2)}{_price_age_suffix(t.get('price_date'))} <button class="ta-quote-btn" data-symbol="{html.escape(tk, quote=True)}" title="Fetch live quote (Finnhub)">🔄</button><span class="live-quote"></span></td>
  <td class="num {chg_cls}" data-sort="{chg or 0}" title="Day-over-day vs last cleanly-closed prior bar — not a true 24h read if a recent yfinance bar was NaN-skipped.">{fmt_pct(chg,2)}</td>
  <td class="num" data-sort="{rsi or 0}">{fmt_num(rsi,1)}</td>
  <td class="num" data-sort="{atr_pct or 0}" title="Daily Average True Range as % of price — typical 1-day move. Used for stop-distance sizing.">{fmt_num(atr_pct,2)}%</td>
  <td class="num" data-sort="{v50 or 0}">{fmt_pct(v50,1)}</td>
  <td class="num" data-sort="{v200 or 0}">{fmt_pct(v200,1)}</td>
  <td class="dim" data-sort="{ne}" title="Earnings calendar date as reported by yfinance — company-local calendar date (typically NY for US listings), not a timestamp. The 'in Xd' is days from today UTC.">{ne} <span class="dim">{days_to_e}</span></td>
  <td class="num {news_cls}" data-sort="{news_sort}">{news_txt}</td>
  {sentiment_cell(tk, "us")[0]}
  <td><span class="badge {badge_cls}" title="{html.escape(status_tooltip(label), quote=True)}">{badge} {label}</span></td>
  <td class="dim">{html.escape(reason)}</td>
</tr>
<tr class="exp-details" id="us-{idx}-body"><td colspan="14">{details_html}</td></tr>""")
        return "\n".join(rows) or '<tr><td colspan="14" class="dim">no US tickers in watchlist</td></tr>'

    news_stats = ctx.get("news_stats") or {}
    n_queue = len(news_stats.get("queued", []))
    n_made = news_stats.get("calls_made", 0)
    news_note = (
        f"news refresh: {n_made} pulled, {n_queue - n_made} skipped" if n_made
        else (f"{n_queue} ticker(s) stale; run with --refresh-news to pull" if n_queue
              else "news cache fresh for all priorities")
    )
    # Compute oldest fetched_at across US ticker data for the panel header
    us_oldest = None
    for _, d in ctx["us_data"].items():
        ts = fetched_at_of(d)
        if ts and (us_oldest is None or ts < us_oldest):
            us_oldest = ts
    us_panel = f"""
<div class="panel">
  <h2>US Equities <span class="stale">oldest ticker fetched {fmt_fetched(us_oldest)} · {news_note}</span></h2>
  <table>
    <thead><tr>
      <th></th>
      <th>Ticker</th><th>Name</th><th>Price</th><th>24h%</th><th>RSI</th>
      <th title="Daily ATR(14) as % of price — typical 1-day move">ATR%</th>
      <th>vs SMA50</th><th>vs SMA200</th><th>Next Earnings</th><th>News</th>
      <th title="Retail sentiment composite (Reddit + StockTwits, LLM-scored) + news-direction glyph (🟢/🔴/⚪ over last 72h, ❗=fresh analyst rating action). Full headlines in the row dropdown.">Retail / News</th>
      <th>P1 Status</th><th>Reason</th>
    </tr></thead>
    <tbody>{render_us_grid()}</tbody>
  </table>
</div>
"""

    # News Flags panel — top signal items across the watchlist (last 48h, relevance > 0.5)
    def sentiment_class(score):
        try: s = float(score)
        except (TypeError, ValueError): return "neu"
        if s >= 0.15: return "bull"
        if s <= -0.15: return "bear"
        return "neu"

    def render_news_flags():
        rows = []
        for it in ctx.get("news_flags", []):
            arrow = "↑" if it["sentiment_score"] > 0.15 else ("↓" if it["sentiment_score"] < -0.15 else "·")
            arrow_cls = "up" if it["sentiment_score"] > 0.15 else ("down" if it["sentiment_score"] < -0.15 else "flat")
            scls = sentiment_class(it["sentiment_score"])
            # Live-ticking relative-age span based on the article's published time
            ago_html = _ago_span(it["time"])
            time_local = it["time"].astimezone().strftime("%b %d %H:%M")
            url = it.get("url") or "#"
            rows.append(
                f'<div class="news-row">'
                f'<span class="arrow {arrow_cls}">{arrow}</span>'
                f'<span class="ticker">{html.escape(it["ticker"])}</span>'
                f'<span class="time">{time_local}</span>'
                f'<span class="src">[{html.escape(it["source"])}]</span>'
                f'<span class="sent {scls}">{html.escape(it["sentiment_label"])} ({it["sentiment_score"]:+.2f})</span>'
                f'<span class="src">rel {it["relevance"]:.2f} · {ago_html}</span>'
                f'<a class="title" href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(it["title"][:160])}</a>'
                f'</div>'
            )
        return "\n".join(rows) or '<div class="dim">no high-signal items in last 48h — run dashboard with --refresh-news</div>'

    # Oldest news cache among watchlist tickers
    news_oldest = None
    for tk, entry in us_news_cache.items():
        ts = (entry.get("data") or {}).get("_fetched_at")
        if ts and (news_oldest is None or ts < news_oldest):
            news_oldest = ts
    news_panel = f"""
<div class="panel">
  <h2>Recent News Flags <span class="stale">last 48h · relevance &gt; 0.5 · top 8 · oldest ticker cache fetched {fmt_fetched(news_oldest)}</span></h2>
  {render_news_flags()}
</div>
"""

    # KLSE grid (uses same logic; macro events don't apply to KLSE so we pass None)
    klse_fund = ctx.get("klse_fundamentals", {})

    def klse_code(ticker):
        t = ticker.upper()
        return t[:-3] if t.endswith(".KL") else t

    klse_ann_for_render = ctx.get("klse_announcements", {}) or {}
    def render_klse_grid():
        rows = []
        for idx, entry in enumerate(ctx["watchlist"]["klse"]):
            tk = entry["ticker"]
            t = ctx["klse_data"].get(tk, {})
            badge, label, reason = us_status({**t, "ticker": tk}, None)
            price = t.get("price")
            chg = t.get("change_pct")
            chg_cls = "green" if (chg or 0) > 0 else "red" if (chg or 0) < 0 else "dim"
            rsi = t.get("rsi14")
            atr14 = t.get("atr14")
            atr_pct = (atr14 / price * 100) if (atr14 and price) else None
            v50 = t.get("vs_sma50_pct"); v200 = t.get("vs_sma200_pct")
            badge_cls = {"🟢": "b-green", "🔴": "b-red", "🟡": "b-yellow", "⚪": "b-dim", "❓": "b-dim"}[badge]
            code = klse_code(tk)
            f = klse_fund.get(code, {})
            ann = klse_ann_for_render.get(code, {})
            pe = f.get("pe_ratio"); pb = f.get("pb_ratio"); dy = f.get("dividend_yield_pct"); roe = f.get("roe_pct")
            fund_age = ""
            ts = f.get("_fetched_at")
            if ts:
                try:
                    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
                    fund_age = f"{age_h:.0f}h" if age_h < 48 else f"{age_h/24:.0f}d"
                except Exception: pass
            thesis_html, gates = synthesize_klse_thesis(tk, t, label, reason, f, ann)
            gates_html = "\n".join(_gate_html(*g) for g in gates)
            details_html = (
                f'<div class="exp-details-content">'
                f'  <div class="exp-thesis">{thesis_html}</div>'
                f'  <div class="exp-gates-grid">'
                f'    <div class="exp-gate-col"><div class="exp-gate-head">P1 technical gates ({sum(1 for _,o,_ in gates if o)}/{len(gates)})</div>{gates_html}</div>'
                f'    <div class="exp-gate-col"><div class="exp-gate-head">Status decision</div>'
                f'      <div class="gate-line"><b>Label:</b> {html.escape(label)}</div>'
                f'      <div class="gate-line"><b>Reason:</b> {html.escape(reason)}</div>'
                f'      <div class="gate-line dim" style="margin-top:6px;font-size:11px">Tooltip on badge: {html.escape(status_tooltip(label))}</div>'
                f'    </div>'
                f'    {sentiment_details_with_polymarket(tk, "klse")}'
                f'    {_news_glyph_details_html(tk, "klse")}'
                f'  </div>'
                f'  <div class="exp-meta">'
                f'    <span><b>Sector:</b> {html.escape(f.get("sector") or t.get("sector") or "—")}</span>'
                f'    <span><b>vs SMA50:</b> {fmt_pct(v50,2)}</span>'
                f'    <span><b>vs SMA200:</b> {fmt_pct(v200,2)}</span>'
                f'    <span><b>P/E:</b> {fmt_num(pe,2)}</span>'
                f'    <span><b>P/B:</b> {fmt_num(pb,2)}</span>'
                f'    <span><b>DY:</b> {fmt_num(dy,2)}%</span>'
                f'    <span><b>ROE:</b> {fmt_num(roe,2)}%</span>'
                f'    <span><b>Fund age:</b> {fund_age or "—"}</span>'
                f'  </div>'
                f'</div>'
            )
            rows.append(f"""
<tr class="exp-row" data-row-id="klse-{idx}">
  <td><span class="exp-chevron">▶</span><button class="wl-remove-btn" onclick="event.stopPropagation(); wlRemove('{html.escape(tk, quote=True)}')" title="Remove from watchlist">🗑️</button></td>
  <td><b>{html.escape(tk)}</b></td>
  <td class="dim">{html.escape((t.get('name') or '')[:22])}</td>
  <td class="num{' stale-price' if _price_stale(t.get('price_date')) else ''}" data-sort="{price or 0}" title="{_price_tooltip(t.get('price_date'))}">MYR {fmt_num(price,3)}{_price_age_suffix(t.get('price_date'))} <a class="ta-quote-btn" href="https://klsescreener.com/v2/stocks/quote/{html.escape(code, quote=True)}" target="_blank" rel="noopener" title="Open klsescreener.com (free real-time KLSE quote not available via Finnhub)" onclick="event.stopPropagation()">📊</a></td>
  <td class="num {chg_cls}" data-sort="{chg or 0}">{fmt_pct(chg,2)}</td>
  <td class="num" data-sort="{rsi or 0}">{fmt_num(rsi,1)}</td>
  <td class="num" data-sort="{atr_pct or 0}" title="Daily ATR(14) as % of price">{fmt_num(atr_pct,2)}%</td>
  <td class="num" data-sort="{v50 or 0}">{fmt_pct(v50,1)}</td>
  <td class="num" data-sort="{pe or 0}">{fmt_num(pe,2)}</td>
  <td class="num" data-sort="{pb or 0}">{fmt_num(pb,2)}</td>
  <td class="num" data-sort="{dy or 0}">{fmt_num(dy,2)}%</td>
  <td class="num" data-sort="{roe or 0}">{fmt_num(roe,2)}%</td>
  {sentiment_cell(tk, "klse")[0]}
  <td><span class="badge {badge_cls}" title="{html.escape(status_tooltip(label), quote=True)}">{badge} {label}</span></td>
  <td class="dim">{html.escape(reason)} <span style="color:var(--dim);font-size:10px">{('· fund ' + fund_age) if fund_age else '· no klse-refresh data'}</span></td>
</tr>
<tr class="exp-details" id="klse-{idx}-body"><td colspan="15">{details_html}</td></tr>""")
        return "\n".join(rows) or '<tr><td colspan="15" class="dim">no KLSE tickers</td></tr>'

    n_klse_fund = len(klse_fund)
    klse_oldest_tech = None
    for _, d in ctx["klse_data"].items():
        ts = fetched_at_of(d)
        if ts and (klse_oldest_tech is None or ts < klse_oldest_tech):
            klse_oldest_tech = ts
    klse_oldest_fund = None
    for _, d in klse_fund.items():
        ts = fetched_at_of(d)
        if ts and (klse_oldest_fund is None or ts < klse_oldest_fund):
            klse_oldest_fund = ts
    if n_klse_fund:
        klse_fund_note = f"{n_klse_fund} cached fundamentals · oldest klse-refresh {fmt_fetched(klse_oldest_fund)}"
    else:
        klse_fund_note = "no klse-refresh cache yet — run `python3 .claude/skills/klse-refresh/klse_refresh.py`"
    # KLSE announcements freshness
    klse_ann_local = ctx.get("klse_announcements", {}) or {}
    klse_oldest_ann = None
    for _, d in klse_ann_local.items():
        ts = fetched_at_of(d)
        if ts and (klse_oldest_ann is None or ts < klse_oldest_ann):
            klse_oldest_ann = ts
    if klse_ann_local:
        klse_ann_note = f"{len(klse_ann_local)} cached announcements · oldest {fmt_fetched(klse_oldest_ann)}"
    else:
        klse_ann_note = "no klse-announcements cache — run `python3 .claude/skills/klse-announcements/klse_announcements.py` for earnings-gate data"
    klse_panel = f"""
<div class="panel">
  <h2>KLSE / Bursa Malaysia <span class="stale">tech (yfinance) oldest {fmt_fetched(klse_oldest_tech)} · {klse_fund_note} · {klse_ann_note}</span></h2>
  <table>
    <thead><tr>
      <th></th>
      <th>Code</th><th>Name</th><th>Price</th><th>24h%</th><th>RSI</th>
      <th title="Daily ATR(14) as % of price — typical 1-day move">ATR%</th>
      <th>vs SMA50</th>
      <th>P/E</th><th>P/B</th><th>DY</th><th>ROE</th>
      <th title="Retail sentiment composite (sparse for KLSE — no StockTwits coverage, low Reddit volume) + news-direction glyph (🟢/🔴/⚪ from klsescreener.com, 72h window). Headlines in row dropdown.">Retail / News</th>
      <th>Status</th><th>Reason</th>
    </tr></thead>
    <tbody>{render_klse_grid()}</tbody>
  </table>
</div>
"""

    # Crypto grid
    crypto_ind_grid = ctx.get("crypto_indicators", {}) or {}
    crypto_unlocks_grid = ctx.get("crypto_unlocks", {}) or {}
    crypto_regime_grid = ctx.get("crypto_regime", {}) or {}
    def render_crypto_grid():
        rows = []
        # BUGFIX: ctx["crypto_rows"] comes back from CoinGecko in market-cap order, NOT watchlist
        # order. The naïve zip() paired the wrong rows (BNB's row got BTC's data, etc.) and the
        # live-quote button picked up data-crypto-symbol from a different coin. Build a symbol→row
        # index and look up by the watchlist entry's ticker instead.
        _rows_by_sym = {(r.get("symbol") or "").upper(): r for r in ctx["crypto_rows"]}
        _pairs = []
        for entry in ctx["watchlist"]["crypto"]:
            tk = entry["ticker"].upper()
            r = _rows_by_sym.get(tk)
            if r is None:
                # Fall back to a stub row so the grid still renders something legible
                r = {"symbol": tk, "name": tk, "price": None, "chg_24h": None, "chg_7d": None,
                     "chg_30d": None, "market_cap": None, "volume": None}
            _pairs.append((entry, r))
        for idx, (entry, r) in enumerate(_pairs):
            fnd = ctx["crypto_funding"].get(r.get("symbol", entry["ticker"]).upper() + "USDT", {})
            badge, label, reason = crypto_status(r, fnd)
            badge_cls = {"🟢": "b-green", "🔴": "b-red", "🟡": "b-yellow", "⚪": "b-dim", "❓": "b-dim"}[badge]
            ch24 = r.get("chg_24h"); ch7 = r.get("chg_7d"); ch30 = r.get("chg_30d")
            ann = fnd.get("annualized_pct")
            tk_up = entry["ticker"].upper()
            ind = crypto_ind_grid.get(tk_up, {}) or {}
            rsi = ind.get("rsi14")
            atr_pct = ind.get("atr_pct")
            price_ind = ind.get("price") or r.get("price")
            s50 = ind.get("sma50")
            v50 = ((price_ind / s50 - 1) * 100) if (price_ind and s50) else None
            unlock_entry = crypto_unlocks_grid.get(tk_up)
            cr_summary = {"label": crypto_regime_grid.get("regime"), "score": crypto_regime_grid.get("score")}
            thesis_html = synthesize_crypto_thesis(tk_up, r, ind, fnd, unlock_entry, cr_summary)
            # Build a simplified gate readout column for crypto (not a P1 framework but useful context)
            ctx_lines = []
            ctx_lines.append(_gate_html("Spot price source", price_ind is not None, f"${price_ind:.4f}" if price_ind else "no data"))
            ctx_lines.append(_gate_html("Indicators (Binance/CG)", ind.get("rsi14") is not None, f"RSI {ind.get('rsi14'):.1f}, ATR {atr_pct:.2f}%" if ind.get("rsi14") and atr_pct else "missing"))
            ctx_lines.append(_gate_html("Perp funding (Binance)", ann is not None, f"{ann:+.1f}% APR" if ann is not None else "missing"))
            ctx_lines.append(_gate_html("Unlock entry", unlock_entry is not None, (unlock_entry or {}).get("_source_type", "—")))
            ctx_lines.append(_gate_html("Crypto regime", cr_summary["score"] is not None, f"{cr_summary['label']} ({cr_summary['score']:+.2f})" if cr_summary["score"] is not None else "missing"))
            details_html = (
                f'<div class="exp-details-content">'
                f'  <div class="exp-thesis">{thesis_html}</div>'
                f'  <div class="exp-gates-grid">'
                f'    <div class="exp-gate-col"><div class="exp-gate-head">Data coverage</div>{"".join(ctx_lines)}</div>'
                f'    <div class="exp-gate-col"><div class="exp-gate-head">Bias decision</div>'
                f'      <div class="gate-line"><b>Label:</b> {html.escape(label)}</div>'
                f'      <div class="gate-line"><b>Reason:</b> {html.escape(reason) or "—"}</div>'
                f'      <div class="gate-line dim" style="margin-top:6px;font-size:11px">Tooltip on badge: {html.escape(status_tooltip(label))}</div>'
                f'    </div>'
                f'    {sentiment_details_with_polymarket(entry["ticker"], "crypto")}'
                f'    {_news_glyph_details_html(entry["ticker"], "crypto")}'
                f'  </div>'
                f'  <div class="exp-meta">'
                f'    <span><b>Price:</b> ${r.get("price"):.4f}</span>' if r.get("price") else '<span><b>Price:</b> —</span>'
            )
            details_html += (
                f'    <span><b>Mkt cap:</b> {fmt_money(r.get("market_cap")) if r.get("market_cap") else "—"}</span>'
                f'    <span><b>24h vol:</b> {fmt_money(r.get("volume")) if r.get("volume") else "—"}</span>'
                f'    <span><b>vs SMA50:</b> {fmt_pct(v50,2)}</span>'
                f'    <span><b>Funding:</b> {fmt_pct(ann,1)} APR</span>'
                f'    <span><b>Data source:</b> {ind.get("data_source","binance")}</span>'
                f'  </div>'
                f'</div>'
            )
            rows.append(f"""
<tr class="exp-row" data-row-id="crypto-{idx}">
  <td><span class="exp-chevron">▶</span><button class="wl-remove-btn" onclick="event.stopPropagation(); wlRemove('{html.escape(entry['ticker'], quote=True)}')" title="Remove from watchlist">🗑️</button></td>
  <td><b>{html.escape(r.get('symbol','—'))}</b></td>
  <td class="dim">{html.escape((r.get('name') or '')[:18])}</td>
  <td class="num" data-sort="{r.get('price') or 0}">${fmt_num(r.get('price'),4)} <button class="ta-quote-btn" data-crypto-source="{ind.get('data_source','binance')}" data-crypto-symbol="{html.escape(ind.get('symbol') or (tk_up + 'USDT'), quote=True)}" title="Fetch live quote (Binance/CoinGecko)" onclick="event.stopPropagation()">🔄</button><span class="live-quote"></span></td>
  <td class="num {'green' if (ch24 or 0)>0 else 'red'}" data-sort="{ch24 or 0}">{fmt_pct(ch24,2)}</td>
  <td class="num {'green' if (ch7 or 0)>0 else 'red'}" data-sort="{ch7 or 0}">{fmt_pct(ch7,2)}</td>
  <td class="num {'green' if (ch30 or 0)>0 else 'red'}" data-sort="{ch30 or 0}">{fmt_pct(ch30,2)}</td>
  <td class="num" data-sort="{rsi or 0}">{fmt_num(rsi,1)}</td>
  <td class="num" data-sort="{atr_pct or 0}" title="Daily ATR(14) as % of price">{fmt_num(atr_pct,2)}%</td>
  <td class="num" data-sort="{v50 or 0}">{fmt_pct(v50,1)}</td>
  <td class="num" data-sort="{ann or 0}">{fmt_pct(ann,1)}</td>
  <td class="dim">{fmt_money(r.get('market_cap'))}</td>
  {sentiment_cell(entry["ticker"], "crypto")[0]}
  <td><span class="badge {badge_cls}" title="{html.escape(status_tooltip(label), quote=True)}">{badge} {label}</span></td>
  <td class="dim">{html.escape(reason)}</td>
</tr>
<tr class="exp-details" id="crypto-{idx}-body"><td colspan="15">{details_html}</td></tr>""")
        return "\n".join(rows) or '<tr><td colspan="15" class="dim">no crypto tickers</td></tr>'

    crypto_mkt_ts = None
    # Look up the markets cache that fetch_crypto_markets used
    for entry in ctx.get("watchlist", {}).get("crypto", []):
        pass
    # Simpler: read most recent crypto_markets_* cache file directly
    try:
        from pathlib import Path as _P
        for p in (CACHE_DIR.glob("crypto_markets_*.json")):
            try:
                td = json.loads(p.read_text())
                ts = td.get("_fetched_at")
                if ts and (crypto_mkt_ts is None or ts > crypto_mkt_ts):
                    crypto_mkt_ts = ts
            except Exception:
                pass
    except Exception:
        pass
    crypto_panel = f"""
<div class="panel">
  <h2>Crypto (CoinGecko + Binance funding) <span class="stale">markets fetched {fmt_fetched(crypto_mkt_ts)}</span></h2>
  <table>
    <thead><tr>
      <th></th>
      <th>Sym</th><th>Name</th><th>Price</th><th>24h%</th><th>7d%</th><th>30d%</th>
      <th>RSI</th><th title="Daily ATR(14) as % of price — typical 1-day move">ATR%</th><th>vs SMA50</th>
      <th>Funding (ann.)</th><th>Mkt Cap</th>
      <th title="Retail sentiment composite (Reddit + StockTwits, LLM-scored) + news-direction glyph (🟢/🔴/⚪ from CoinDesk/Cointelegraph/Decrypt RSS, 72h window). Headlines in row dropdown.">Retail / News</th>
      <th>Status</th><th>Notes</th>
    </tr></thead>
    <tbody>{render_crypto_grid()}</tbody>
  </table>
</div>
"""

    # Journal tail
    journal_html = ""
    for j in ctx["journal"][:8]:
        journal_html += f'<tr><td>{html.escape(j["file"])}</td><td>{html.escape(j["ticker"])}</td><td>{html.escape(j["status"])}</td></tr>'
    journal_panel = f"""
<div class="panel">
  <h2>Journal Tail</h2>
  <table>
    <thead><tr><th>File</th><th>Ticker</th><th>Status</th></tr></thead>
    <tbody>{journal_html or '<tr><td colspan="3" class="dim">no entries</td></tr>'}</tbody>
  </table>
</div>
"""

    refresh_cmd      = "python3 .claude/skills/dashboard/dashboard.py --with-discovery && open dashboard.html"
    refresh_cmd_news = "python3 .claude/skills/dashboard/dashboard.py --refresh-news --refresh-news-glyph --with-discovery && open dashboard.html"
    refresh_cmd_full = "python3 .claude/skills/dashboard/dashboard.py --refresh-news --refresh-news-glyph --refresh-sentiment --refresh-polymarket --with-discovery --force && open dashboard.html"

    def _rb_item(label, desc, cmd):
        # Inline onclick: copy command, show toast, close menu. Single-quote-safe via JSON encoding.
        cmd_js = json.dumps(cmd)
        return (f'<button class="refresh-menu-item" onclick=\'(function(b){{'
                f'navigator.clipboard.writeText({cmd_js});'
                f'var t=document.getElementById("refresh-toast");if(t){{t.textContent="Copied — paste in terminal";t.classList.add("show");setTimeout(function(){{t.classList.remove("show");}},2400);}}'
                f'b.closest(".refresh-menu").classList.remove("open");'
                f'}})(this)\'><span class="rm-label">{label}</span><div class="rm-desc">{desc}</div></button>')

    refresh_dropdown = (
        '<span class="refresh-menu" id="refresh-menu">'
        '<button class="refresh-btn" onclick="event.stopPropagation();document.getElementById(\'refresh-menu\').classList.toggle(\'open\');">↻ Refresh ▾</button>'
        '<div class="refresh-menu-items">'
        + _rb_item("↻ Quick refresh",
                   "Rebuild from caches; only fetch what's expired. ~10-15s. Use for mid-day re-looks.",
                   refresh_cmd)
        + _rb_item("📰 News refresh",
                   "Quick + pull fresh AV news, Finnhub headlines, klsescreener, crypto RSS, and LLM-score new items. ~30-60s.",
                   refresh_cmd_news)
        + _rb_item("⟳ Full refresh",
                   "Everything fresh: news + glyph + retail sentiment + Polymarket + force-refetch all sources. Several minutes on cold caches.",
                   refresh_cmd_full)
        + '</div>'
        '</span>'
        '<span class="refresh-toast" id="refresh-toast"></span>'
    )

    html_out = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><title>Trading Dashboard</title>
<style>{CSS}</style>
</head><body>
<div class="container">
  <div class="header">
    <h1>📊 Trading Advisor — Dashboard</h1>
    <div class="meta">Built <span class="built-at" data-utc="{now_iso_utc}">{now_str}</span> <span class="dim" style="font-size:11px">(server-local fallback: {now_local_str})</span> · {budget_bar} · {refresh_dropdown}</div>
  </div>
  {strip}
  {regime_panel}
  {halt_panel}
  {render_polymarket_panel()}
  {prospectus_panel}
  {sim_panel}
  {render_contrarian_setups_panel()}
  {render_btfd_str_panel()}
  {us_panel}
  {news_panel}
  {klse_panel}
  {crypto_panel}
  {wl_panel}
  {discovery_panel}
  {journal_panel}
  <div class="footer">
    Doctrine: spot-long only in Phase 1 · §5 halt rules enforced via macro-calendar + us-fundamentals earnings ·
    R:R floor: 1.5R (NEUTRAL+) / 2R (CAUTIOUS) / 2R+ (RISK-OFF)<br>
    Refresh command: <code>{refresh_cmd}</code>
  </div>
</div>
<script>{JS}</script>
</body></html>
"""
    return html_out


# ── AV news cache + budget-aware refresh (Phase B) ───────────────────────
def _import_news_cache():
    """Defer import so missing optional module doesn't break dashboard build."""
    try:
        sys.path.insert(0, str(SKILLS_DIR / "us-news"))
        import news_cache as nc
        return nc
    except ImportError as e:
        print(f"  warn: news_cache not available ({e}) — news section will be skipped")
        return None


def fetch_av_for_ticker_to_cache(ticker, api_key, hours=168, limit=20):
    """Direct AV NEWS_SENTIMENT fetch, write to cache + bump budget. Used by dashboard
    when refreshing. Returns (ok, error_msg). Identical logic to av_news.fetch()."""
    nc = _import_news_cache()
    if nc is None:
        return False, "news_cache module unavailable"
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "apikey": api_key,
        "sort": "LATEST",
        "limit": str(min(max(limit, 1), 1000)),
    }
    if hours:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        params["time_from"] = cutoff.strftime("%Y%m%dT%H%M")
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "trading-advisor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        nc.write_cache(ticker, {"error": str(e), "feed": []})
        return False, str(e)
    try:
        data = json.loads(raw)
    except Exception as e:
        nc.write_cache(ticker, {"error": f"JSON decode: {e}", "feed": []})
        return False, f"JSON decode: {e}"
    # AV returns errors inside 200 responses
    if "Error Message" in data:
        nc.write_cache(ticker, {"error": data["Error Message"], "feed": []})
        return False, data["Error Message"]
    if ("Note" in data or "Information" in data) and "feed" not in data:
        msg = data.get("Note") or data.get("Information") or "AV rate-limit / info"
        nc.write_cache(ticker, {"error": msg, "feed": []})
        return False, msg
    nc.write_cache(ticker, data)
    nc.increment_budget(1)
    return True, None


def refresh_news_for_us_tickers(watchlist_us, us_data, journal_entries, refresh_news=False):
    """Apply priority queue + budget gate. Refresh only what deserves a refresh.

    Returns dict {ticker: {"badge": str, "label": str, "reason": str}} (the status
    determiner's output) keyed identically to us_data, plus stats: refresh_count,
    budget_state.
    """
    nc = _import_news_cache()
    if nc is None:
        return {"calls_made": 0, "queued": [], "budget": None, "tickers_skipped": []}

    # Build journal_statuses map for priority lookup (ticker → most recent status)
    j_status = {}
    for j in journal_entries:
        tk = (j.get("ticker") or "").upper()
        if tk and tk not in j_status:
            j_status[tk] = j.get("status", "")

    # Build dashboard_status_badges map by running us_status (already done in render,
    # but we need it here too — light call, no fetches)
    badges = {}
    for entry in watchlist_us:
        t = us_data.get(entry["ticker"], {})
        _, label, _ = us_status({**t, "ticker": entry["ticker"]}, None)
        badges[entry["ticker"].upper()] = label

    # Compute priorities + figure out who's stale
    queue = []
    for entry in watchlist_us:
        tk = entry["ticker"].upper()
        prio = nc.priority_for_ticker(tk, j_status, badges)
        if prio is None:
            continue
        if nc.is_stale(tk, prio):
            queue.append((prio, tk))

    queue.sort(key=lambda x: (
        0 if x[0] == "P0_active" else
        1 if x[0] == "P1_armed" else
        2 if x[0] == "P2_ready" else 3,
        x[1],
    ))

    state = nc.load_budget()
    stats = {
        "calls_made": 0,
        "queued": [t for _, t in queue],
        "budget_state": state,
        "tickers_skipped": [],
        "errors": [],
    }

    if not refresh_news:
        # Build-time uses cache only; queue is informational
        return stats

    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        stats["errors"].append("ALPHAVANTAGE_API_KEY not set")
        return stats

    headroom = nc.remaining_for_dashboard(state)
    import time as _time
    burst_limited = False
    for i, (prio, tk) in enumerate(queue):
        if headroom <= 0 or burst_limited:
            stats["tickers_skipped"].append(tk)
            continue
        if i > 0:
            _time.sleep(1.2)  # AV free tier: 1 req/sec burst limit
        ok, err = fetch_av_for_ticker_to_cache(tk, api_key, hours=168, limit=20)
        if ok:
            stats["calls_made"] += 1
            headroom -= 1
        else:
            stats["errors"].append(f"{tk}: {err}")
            # If AV scolded us for burst, stop — repeat attempts will keep failing
            if err and ("per second" in err.lower() or "spreading out" in err.lower()):
                burst_limited = True
                stats["errors"].append("⚠ AV burst-rate hit; halting further refreshes this run.")
    stats["budget_state"] = nc.load_budget()
    return stats


# ── Main orchestration ────────────────────────────────────────────────────
def _refresh_sentiment_for(tickers, label):
    """Subprocess the reddit-sentiment, stocktwits-sentiment, sentiment-cache chain
    for the given list of tickers. Quiet output unless a step fails. Returns True if all 3 steps succeed."""
    if not tickers:
        return True
    import subprocess
    print(f"[sentiment] {label}: {' '.join(tickers)}", flush=True)
    steps = [
        ("reddit", PROJECT_ROOT / ".claude/skills/reddit-sentiment/reddit_sentiment.py"),
        ("stocktwits", PROJECT_ROOT / ".claude/skills/stocktwits-sentiment/stocktwits_sentiment.py"),
        ("hn", PROJECT_ROOT / ".claude/skills/hn-sentiment/hn_sentiment.py"),
        ("scorer", PROJECT_ROOT / ".claude/skills/sentiment-cache/sentiment_cache.py"),
    ]
    ok = True
    for name, path in steps:
        cmd = [sys.executable, str(path), *tickers]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                print(f"[sentiment] {name} step failed (rc={r.returncode}): {r.stderr.strip()[:200]}", flush=True)
                ok = False
        except subprocess.TimeoutExpired:
            print(f"[sentiment] {name} step timed out (>300s) — partial cache may be left; "
                  f"re-run `python3 .claude/skills/dashboard/dashboard.py --refresh-sentiment` to retry.",
                  flush=True)
            ok = False
        except Exception as e:
            print(f"[sentiment] {name} step crashed: {e}", flush=True)
            ok = False
    # Invalidate the in-memory sentiment cache so the dashboard sees the new files
    global _SENTIMENT_CACHE_LOADED
    _SENTIMENT_CACHE_LOADED = None
    return ok


def _detect_missing_sentiment(watchlist):
    """Return list of watchlist tickers that have no entry in the sentiment cache."""
    all_tickers = []
    for section in ("us", "klse", "crypto"):
        for e in watchlist.get(section, []):
            all_tickers.append(e["ticker"].upper())
    cache = _bulk_load_sentiment()
    return [t for t in all_tickers if t not in cache]


# Watchlist crypto entries store symbols (BTC); news_glyph keys by CoinGecko slug.
# Keep this map in sync with .claude/skills/crypto-coingecko/cg.py SYMBOL_MAP.
_CRYPTO_SYMBOL_TO_SLUG = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "HBAR": "hedera-hashgraph",
    "HYPE": "hyperliquid", "ENA": "ethena", "ONDO": "ondo-finance",
    "LINK": "chainlink", "AVAX": "avalanche-2", "DOT": "polkadot",
    "ARB": "arbitrum", "OP": "optimism", "APT": "aptos", "SUI": "sui",
    "LTC": "litecoin", "TON": "the-open-network", "TRX": "tron", "MATIC": "matic-network",
    "UNI": "uniswap", "ATOM": "cosmos", "NEAR": "near",
}


def _crypto_slug(symbol_or_slug):
    """Return the CoinGecko slug for a watchlist crypto entry.
    Accepts either a symbol ('BTC') or a slug ('bitcoin')."""
    s = (symbol_or_slug or "").strip()
    if not s:
        return s
    if s.upper() in _CRYPTO_SYMBOL_TO_SLUG:
        return _CRYPTO_SYMBOL_TO_SLUG[s.upper()]
    return s.lower()


def _refresh_news_glyphs(watchlist, force=False):
    """Subprocess news_glyph.py refresh-{us,klse,crypto} for the watchlist."""
    import subprocess
    script = PROJECT_ROOT / ".claude/skills/us-news/news_glyph.py"
    us = [e["ticker"].upper() for e in watchlist.get("us", [])]
    klse = [str(e["ticker"]).replace(".KL", "").strip() for e in watchlist.get("klse", [])]
    crypto_slugs = sorted({_crypto_slug(e["ticker"]) for e in watchlist.get("crypto", [])})
    for label, args in (
        ("us",     ["refresh-us",     "--tickers", ",".join(us)]      if us else None),
        ("klse",   ["refresh-klse",   "--codes",   ",".join(klse)]    if klse else None),
        ("crypto", ["refresh-crypto", "--coins",   ",".join(crypto_slugs)] if crypto_slugs else None),
    ):
        if not args:
            continue
        cmd = [sys.executable, str(script), *args] + (["--force"] if force else [])
        print(f"[news-glyph] {label}: {len(args[2].split(','))} entries...", flush=True)
        try:
            # First-pass LLM scoring across the watchlist can be slow (~3s/ticker for
            # 30-150 items). Subsequent refreshes amortize to ~1-5 new items per ticker.
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                print(f"[news-glyph] {label} rc={r.returncode}: {r.stderr.strip()[:200]}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"[news-glyph] {label} timeout (>900s) — partial cache OK, re-run to finish", flush=True)
        except Exception as e:
            print(f"[news-glyph] {label} crashed: {e}", flush=True)


def _load_news_glyphs(watchlist, refresh=False, skip=False):
    """Return {(asset_class, key): payload} for the dashboard renderer.
    Keys: us=ticker.upper(); klse=4-digit code; crypto=ticker.upper() (renderer
    uses symbol, the lookup is symbol-keyed for ergonomics — we resolve to slug
    inside this function)."""
    if skip:
        return {}
    if refresh:
        _refresh_news_glyphs(watchlist)
    # Import the news_glyph module to call glyph_for
    sys.path.insert(0, str(PROJECT_ROOT / ".claude/skills/us-news"))
    try:
        import news_glyph as ng
    except Exception as e:
        print(f"[news-glyph] import failed: {e}")
        return {}
    out = {}
    for e in watchlist.get("us", []):
        tk = e["ticker"].upper()
        p = ng.glyph_for(tk, "us")
        if p is not None:
            out[("us", tk)] = p
    for e in watchlist.get("klse", []):
        code = str(e["ticker"]).replace(".KL", "").strip()
        p = ng.glyph_for(code, "klse")
        if p is not None:
            out[("klse", code)] = p
    for e in watchlist.get("crypto", []):
        symbol = e["ticker"].upper()
        slug = _crypto_slug(symbol)
        p = ng.glyph_for(slug, "crypto")
        if p is not None:
            out[("crypto", symbol)] = p
    return out


def build_dashboard(force=False, skip_news=False, refresh_news=False, refresh_sentiment=False, skip_sentiment=False,
                    refresh_news_glyph=False, skip_news_glyph=False):
    print("[1/8] Parsing watchlist + journal...")
    watchlist = parse_watchlist()
    journal = parse_journal()
    print(f"      → {len(watchlist['us'])} US, {len(watchlist['klse'])} KLSE, {len(watchlist['crypto'])} crypto · {len(journal)} journal entries")

    # Sentiment refresh — auto-fill missing watchlist tickers (e.g. after a `wl.py add`).
    # Pass --refresh-sentiment to force-refresh all watchlist tickers.
    # Pass --no-sentiment to skip the auto-fill entirely.
    if not skip_sentiment:
        if refresh_sentiment:
            all_t = [e["ticker"].upper() for section in ("us","klse","crypto") for e in watchlist.get(section, [])]
            _refresh_sentiment_for(all_t, "full refresh (--refresh-sentiment)")
        else:
            missing = _detect_missing_sentiment(watchlist)
            if missing:
                _refresh_sentiment_for(missing, f"auto-fill {len(missing)} ticker(s) missing from cache")

    print("[2/8] Fetching US macro regime (FRED)...")
    macro, macro_age = fetch_macro_regime(force)
    print(f"      → regime: {macro.get('regime')} ({macro_age})")

    print("[3/8] Fetching crypto regime (F&G + CG /global)...")
    crypto_r, crypto_age = fetch_crypto_regime(force)
    print(f"      → regime: {crypto_r.get('regime')} ({crypto_age})")

    print("[4/8] Building halt-window timeline...")
    cal, cal_age = fetch_macro_calendar(force)
    print(f"      → {len(cal.get('events',[]))} upcoming events")

    # S3 optimization: parallel per-ticker yfinance fetches via ThreadPoolExecutor.
    # Cache hits are instant; only true cache misses parallelize. ~5x speedup on cold cache.
    from concurrent.futures import ThreadPoolExecutor as _Pool, as_completed as _ac
    print("[5/8] Fetching US ticker data via yfinance (parallel)...")
    us_data = {}
    us_tickers = [e["ticker"] for e in watchlist["us"]]
    with _Pool(max_workers=min(8, max(1, len(us_tickers)))) as pool:
        futs = {pool.submit(fetch_yfinance_ticker, tk, force): tk for tk in us_tickers}
        for f in _ac(futs):
            tk = futs[f]
            try: us_data[tk], _ = f.result()
            except Exception as e: us_data[tk] = {"error": f"fetch failed: {e}"}

    print("[6/8] Fetching KLSE ticker data via yfinance (parallel)...")
    klse_data = {}
    klse_tickers = [e["ticker"] for e in watchlist["klse"]]
    with _Pool(max_workers=min(4, max(1, len(klse_tickers)))) as pool:
        futs = {pool.submit(fetch_yfinance_ticker, tk, force): tk for tk in klse_tickers}
        for f in _ac(futs):
            tk = futs[f]
            try: klse_data[tk], _ = f.result()
            except Exception as e: klse_data[tk] = {"error": f"fetch failed: {e}"}

    # Load klse-refresh fundamentals cache (manual refresh — never auto-fetched here)
    klse_fundamentals = {}
    klse_cache_dir = PROJECT_ROOT / ".claude" / "cache" / "klse_fundamentals"
    if klse_cache_dir.is_dir():
        for p in klse_cache_dir.glob("*.json"):
            try:
                klse_fundamentals[p.stem] = json.loads(p.read_text())
            except Exception:
                pass
    print(f"      → {len(klse_fundamentals)} klse-refresh fundamentals cached")

    # FX for KLSE sizing (cached 30m). Only fetch if we have KLSE tickers on the watchlist.
    fx = {}
    if watchlist["klse"]:
        myrusd, _ = fetch_fx_rate("MYRUSD", force)
        if myrusd and myrusd.get("rate"):
            fx["MYR_USD"] = myrusd["rate"]
            fx["MYR_USD_fetched_at"] = myrusd.get("_fetched_at")
        else:
            fx["MYR_USD_error"] = (myrusd or {}).get("error", "fx unavailable")
        print(f"      → FX MYR/USD: {fx.get('MYR_USD', 'unavailable')}")

    # Load klse-announcements cache (manual refresh — never auto-fetched)
    klse_announcements = {}
    klse_ann_dir = PROJECT_ROOT / ".claude" / "cache" / "klse_announcements"
    if klse_ann_dir.is_dir():
        for p in klse_ann_dir.glob("*.json"):
            try:
                klse_announcements[p.stem] = json.loads(p.read_text())
            except Exception:
                pass
    print(f"      → {len(klse_announcements)} klse-announcements cached")

    # ── News refresh + cache load (Phase B) ──
    print("[6.5/8] Evaluating AV news cache + priority queue...")
    news_stats = refresh_news_for_us_tickers(watchlist["us"], us_data, journal, refresh_news=refresh_news and not skip_news)
    if refresh_news and not skip_news:
        bs = news_stats.get("budget_state") or {}
        print(f"      → refreshed {news_stats['calls_made']} ticker(s); skipped {len(news_stats['tickers_skipped'])} (budget exhausted); "
              f"budget {bs.get('calls_used','?')}/{bs.get('calls_max','?')}")
        if news_stats.get("errors"):
            for e in news_stats["errors"][:3]:
                print(f"      ⚠ {e}")
    else:
        print(f"      → cache-only mode (pass --refresh-news to pull); {len(news_stats.get('queued',[]))} ticker(s) would be refreshed")

    # Load news cache + budget for the renderer
    nc = _import_news_cache()
    us_news_cache = {}
    news_flags = []
    news_budget = None
    if nc is not None:
        for entry in watchlist["us"]:
            tk = entry["ticker"].upper()
            d = nc.read_cache(tk)
            if d is not None:
                us_news_cache[tk] = {
                    "data": d,
                    "age_h": nc.cache_age_hours(tk),
                    "error": d.get("error"),
                }
        news_flags = nc.top_signal_items(min_relevance=0.5, hours_window=48, max_items=8)
        news_budget = nc.load_budget()

    print("[7/8] Fetching crypto markets + funding...")
    crypto_coins = [e["ticker"] for e in watchlist["crypto"]]
    mkt, _ = fetch_crypto_markets(crypto_coins, force) if crypto_coins else ({"rows": []}, "")
    crypto_rows = mkt.get("rows", [])
    crypto_funding = {}
    for r in crypto_rows:
        sym = (r.get("symbol") or "").upper() + "USDT"
        f, _ = fetch_binance_funding(sym, force)
        crypto_funding[sym] = f

    # Per-coin daily klines + indicators for risk simulator (BTC, ETH, SOL, BNB, XRP, HBAR…)
    crypto_indicators = {}
    for coin in crypto_coins:
        ind, _ = fetch_crypto_indicators(coin, force)
        crypto_indicators[coin.upper()] = ind

    # News-glyph payloads (per-ticker 🟢/🔴/⚪ + ❗ analyst modifier — see news_glyph.py)
    news_glyphs = _load_news_glyphs(watchlist, refresh=refresh_news_glyph, skip=skip_news_glyph)
    news_glyphs_skipped = bool(skip_news_glyph)

    # Token-unlock cache (populated by crypto-unlocks-cache skill; consumed by sim §5 gate)
    crypto_unlocks = {}
    unlocks_dir = CACHE_DIR.parent / "crypto_unlocks"
    if unlocks_dir.exists():
        for p in unlocks_dir.glob("*.json"):
            try:
                crypto_unlocks[p.stem.upper()] = json.loads(p.read_text())
            except Exception:
                pass

    print("[8/8] Rendering HTML...")
    ctx = {
        "watchlist": watchlist,
        "journal": journal,
        "macro_regime": macro, "macro_regime_age": macro_age,
        "crypto_regime": crypto_r, "crypto_regime_age": crypto_age,
        "macro_calendar": cal, "macro_calendar_age": cal_age,
        "us_data": us_data,
        "klse_data": klse_data,
        "klse_fundamentals": klse_fundamentals,
        "klse_announcements": klse_announcements,
        "fx": fx,
        "us_news_cache": us_news_cache,
        "news_flags": news_flags,
        "news_budget": news_budget,
        "news_stats": news_stats,
        "crypto_rows": crypto_rows,
        "crypto_funding": crypto_funding,
        "crypto_indicators": crypto_indicators,
        "crypto_unlocks": crypto_unlocks,
        "news_glyphs": news_glyphs,
        "news_glyphs_skipped": news_glyphs_skipped,
        "sentiment": _bulk_load_sentiment(),
        "polymarket": load_polymarket(),
        "config": {
            "account": 20000, "phase": "1 (paper, spot only)",
            "phase_desc": "until 20 closed trades + ≥0R",
            "risk_pct": 0.02, "max_risk": 400,
            "heat_used": 0, "heat_max": 1200,
            "trades_closed": 0,
        },
    }
    rendered = render_html(ctx)
    OUTPUT_HTML.write_text(rendered)

    # Sanity check: validate embedded JS via `node --check` if node is available.
    # Catches the class of bugs (broken string escapes, unbalanced braces) that
    # would otherwise only surface in a browser console.
    js_check = validate_embedded_js(rendered)
    if js_check == "ok":
        print(f"\n✓ Wrote {OUTPUT_HTML}  (JS syntax check passed)")
    elif js_check == "skipped":
        print(f"\n✓ Wrote {OUTPUT_HTML}  (JS check skipped — `node` not on PATH)")
    else:
        # js_check is the error message; HTML was still written so dashboard partially works
        print(f"\n⚠ Wrote {OUTPUT_HTML} but JS SYNTAX CHECK FAILED:")
        print(js_check)
        print("\nThe dashboard will load but the Risk Simulator and table sorting may not work.")
        print("Fix the JS in dashboard.py and re-run.")
    print(f"  Open with: open '{OUTPUT_HTML}'")


def validate_embedded_js(html_text):
    """Extract last <script> block (the IIFE) and run `node --check`.

    Returns 'ok' on success, 'skipped' if node isn't available, or an error
    string if syntax invalid.
    """
    import re, shutil, tempfile
    scripts = re.findall(r"<script>(.*?)</script>", html_text, re.DOTALL)
    if not scripts:
        return "ok"  # nothing to check
    js_blob = scripts[-1]  # the main IIFE block is the last one
    if not shutil.which("node"):
        return "skipped"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(js_blob)
        tmp_path = f.name
    try:
        r = subprocess.run(
            ["node", "--check", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return "ok"
        return (r.stderr or r.stdout or "node --check failed").strip()
    except Exception as e:
        return f"node check error: {type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Bypass cache; refetch all non-news sources.")
    ap.add_argument("--refresh-news", action="store_true", help="Pull fresh AV news for stale tickers (uses budget; respects 8-call on-demand reserve).")
    ap.add_argument("--refresh-sentiment", action="store_true", help="Force-refresh retail sentiment (reddit + stocktwits + scorer) for ALL watchlist tickers. Without this flag the dashboard auto-fills only tickers missing from the sentiment cache.")
    ap.add_argument("--no-sentiment", action="store_true", help="Skip the sentiment auto-fill step entirely (e.g. if Reddit RSS or OpenRouter is down). Dashboard still renders whatever's already cached.")
    ap.add_argument("--refresh-polymarket", action="store_true", help="Pull fresh Polymarket event probabilities (no auth, ~5s). Without this flag the dashboard uses whatever's cached.")
    ap.add_argument("--no-news", action="store_true", help="Skip news entirely (cache-only, no panel update).")
    ap.add_argument("--refresh-news-glyph", action="store_true", help="Pull fresh per-row news glyph data (Finnhub headlines + yfinance analyst actions for US, klsescreener for KLSE, RSS for crypto). 60-call/min Finnhub free tier — runs on full watchlist.")
    ap.add_argument("--no-news-glyph", action="store_true", help="Skip news-glyph entirely (per-row glyph column shows nothing).")
    ap.add_argument("--with-discovery", action="store_true", help="Also run us-screener + sector-rotation before rendering (TTL-cached, no-op if fresh).")
    ap.add_argument("--open", action="store_true", help="Open dashboard.html in default browser when done.")
    args = ap.parse_args()

    if args.with_discovery:
        # Skip subprocess spawn if caches are still fresh — save ~3-5s per refresh.
        def _cache_fresh(path, ttl_hours):
            try:
                if not path.is_file(): return False
                d = json.loads(path.read_text())
                ts = d.get("_last_full_pass_at") or d.get("_fetched_at") or d.get("_generated_at")
                if not ts: return False
                age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
                return age_h < ttl_hours
            except Exception:
                return False
        screener_cache = PROJECT_ROOT / ".claude/cache/screener/candidates.json"
        sector_cache   = PROJECT_ROOT / ".claude/cache/sector_rotation/data.json"

        if not args.force and _cache_fresh(screener_cache, 18):
            print("[discovery] us-screener cache fresh (< 18h); skipping subprocess.", flush=True)
        else:
            screener_cmd = [sys.executable, str(PROJECT_ROOT / ".claude/skills/us-screener/screener.py")]
            if args.force: screener_cmd.append("--refresh")
            print("[discovery] running us-screener…", flush=True)
            subprocess.run(screener_cmd, check=False)

        if not args.force and _cache_fresh(sector_cache, 4):
            print("[discovery] sector-rotation cache fresh (< 4h); skipping subprocess.", flush=True)
        else:
            sector_cmd = [sys.executable, str(PROJECT_ROOT / ".claude/skills/sector-rotation/sector_rotation.py")]
            if args.force: sector_cmd.append("--refresh")
            print("[discovery] running sector-rotation…", flush=True)
            subprocess.run(sector_cmd, check=False)

    if args.refresh_polymarket:
        print("[polymarket] refreshing event probabilities…", flush=True)
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / ".claude/skills/polymarket-events/polymarket_events.py")],
            check=False, capture_output=True,
        )

    build_dashboard(
        force=args.force,
        skip_news=args.no_news,
        refresh_news=args.refresh_news,
        refresh_sentiment=args.refresh_sentiment,
        skip_sentiment=args.no_sentiment,
        refresh_news_glyph=args.refresh_news_glyph,
        skip_news_glyph=args.no_news_glyph,
    )
    if args.open:
        try:
            subprocess.run(["open", str(OUTPUT_HTML)], check=False)
        except Exception as e:
            print(f"  (warning: could not auto-open dashboard: {type(e).__name__}: {e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
