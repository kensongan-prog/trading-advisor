"""Twelve Data free-tier REST client.

Used for: bulk historical OHLCV (sector rotation, screener technicals).
Free tier: 800 calls/day, 8 calls/minute, no per-call cost on multi-asset.

Sign up: https://twelvedata.com/register → API key on dashboard.
Drop into: .claude/skills/twelve-data/.env  →  TWELVE_DATA_API_KEY=...

Budget tracker: .claude/cache/twelve_data/budget.json — counts per UTC day.
Pacer: enforces minimum 7.5s between calls (8/min with margin).
"""
from __future__ import annotations
import json, os, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR   = Path(__file__).resolve().parent
_ENV_PATH     = _SCRIPT_DIR / ".env"
_PROJECT_ROOT = _SCRIPT_DIR.parents[2]
BASE_URL      = "https://api.twelvedata.com"
BUDGET_FILE   = _PROJECT_ROOT / ".claude" / "cache" / "twelve_data" / "budget.json"
LAST_CALL_FILE = _PROJECT_ROOT / ".claude" / "cache" / "twelve_data" / ".last_call_ts"

DAILY_CAP    = 800
SOFT_LIMIT   = 650   # warn here
HARD_LIMIT   = 760   # block non-reserved calls here
RESERVE_FOR_ONDEMAND = 40  # always-available headroom for ad-hoc agent queries

PER_MINUTE_LIMIT = 8
PACE_SECONDS     = 7.6   # 60s / 8 calls = 7.5s, add safety margin


def _load_env():
    if not _ENV_PATH.is_file(): return
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ: os.environ[k] = v

_load_env()

def api_key():
    return os.environ.get("TWELVE_DATA_API_KEY")

def is_configured():
    return bool(api_key())


# ─── Budget tracking ──────────────────────────────────────────────────────
def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def load_budget():
    if not BUDGET_FILE.is_file():
        return {"date": _today_utc(), "calls_used": 0}
    try:
        b = json.loads(BUDGET_FILE.read_text())
        if b.get("date") != _today_utc():
            return {"date": _today_utc(), "calls_used": 0}
        return b
    except Exception:
        return {"date": _today_utc(), "calls_used": 0}

def save_budget(b):
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUDGET_FILE.write_text(json.dumps(b))

def budget_status():
    b = load_budget()
    used = b.get("calls_used", 0)
    remaining = DAILY_CAP - used
    return {"date": b.get("date"), "used": used, "remaining": remaining,
            "soft_ok": used < SOFT_LIMIT, "hard_ok": used < HARD_LIMIT,
            "ondemand_reserve_intact": remaining >= RESERVE_FOR_ONDEMAND}


def _check_budget(reserved=False):
    b = load_budget()
    used = b.get("calls_used", 0)
    if reserved:
        if used >= DAILY_CAP: return False, f"TD daily cap hit ({used}/{DAILY_CAP})"
        return True, None
    if used >= HARD_LIMIT:
        return False, f"TD soft cap hit ({used}/{HARD_LIMIT}); {DAILY_CAP - used} calls reserved. Pass reserved=True to use."
    return True, None


# ─── Per-minute rate pacer (cross-process via file timestamp) ─────────────
def _pace():
    """Enforce minimum PACE_SECONDS between calls. Uses a file so spacing works
    across multiple script invocations within the same minute."""
    BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LAST_CALL_FILE.is_file():
        try:
            last_ts = float(LAST_CALL_FILE.read_text().strip())
            elapsed = time.time() - last_ts
            if elapsed < PACE_SECONDS:
                time.sleep(PACE_SECONDS - elapsed)
        except Exception:
            pass
    LAST_CALL_FILE.write_text(str(time.time()))


# ─── Core GET with budget + pacing + retry ────────────────────────────────
def _get(path, params=None, reserved=False, retries=2):
    ok, msg = _check_budget(reserved=reserved)
    if not ok: return None, msg
    key = api_key()
    if not key:
        return None, "TWELVE_DATA_API_KEY not set (drop it into .claude/skills/twelve-data/.env)"
    params = dict(params or {})
    params["apikey"] = key
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries + 1):
        _pace()
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                data = json.loads(r.read().decode())
            # TD returns 200 with {"status": "error", "code": 429, "message": ...} on rate limit
            if isinstance(data, dict) and data.get("status") == "error":
                code = data.get("code")
                msg  = data.get("message", "unknown error")
                if code == 429 and attempt < retries:
                    # explicit rate-limit hit — wait a full minute window
                    time.sleep(15 * (attempt + 1)); continue
                return None, f"TD code {code}: {msg}"
            # Successful call — count it
            b = load_budget(); b["calls_used"] = b.get("calls_used", 0) + 1; save_budget(b)
            return data, None
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:
                time.sleep(10 * (attempt + 1)); continue
            return None, f"HTTP {e.code}"
        except Exception as e:
            if attempt < retries:
                time.sleep(2); continue
            return None, f"{type(e).__name__}: {e}"
    return None, "retry exhausted"


# ─── Endpoints we actually use ────────────────────────────────────────────
def time_series(symbol, interval="1day", outputsize=400, reserved=False):
    """Daily OHLCV. outputsize default 400 → enough for SMA200 + buffer.
    Returns dict with 'values' = list of bars (newest first per TD convention) or error."""
    return _get("/time_series", {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "order": "ASC",  # ask TD to sort oldest→newest so we don't have to flip
    }, reserved=reserved)


def candle_closes(symbol, outputsize=400, reserved=False):
    """Convenience: returns list of closes oldest→newest (or None, error)."""
    data, err = time_series(symbol, "1day", outputsize, reserved)
    if err: return None, err
    values = (data or {}).get("values") or []
    if not values: return None, "empty series"
    return [float(v["close"]) for v in values], None


def candle_ohlcv(symbol, outputsize=400, reserved=False):
    """Returns list of {open, high, low, close, volume, datetime} oldest→newest (or None, error)."""
    data, err = time_series(symbol, "1day", outputsize, reserved)
    if err: return None, err
    values = (data or {}).get("values") or []
    if not values: return None, "empty series"
    out = []
    for v in values:
        try:
            out.append({
                "datetime": v.get("datetime"),
                "open":   float(v["open"]),
                "high":   float(v["high"]),
                "low":    float(v["low"]),
                "close":  float(v["close"]),
                "volume": float(v.get("volume") or 0),
            })
        except (KeyError, ValueError):
            continue
    return out, None


def quote(symbol, reserved=False):
    """Current quote with previous close, change, %change."""
    return _get("/quote", {"symbol": symbol}, reserved=reserved)
