"""Financial Modeling Prep (FMP) free-tier REST client — /stable/ endpoints.

Used for: fundamentals (P/E, ROE, margins, FCF, debt, growth — Buffett Q+V gates).
Free tier: 250 calls/day, /stable/ endpoint URLs.

(Old /api/v3/ endpoints are legacy as of Aug 2025; this module uses the current
/stable/ family which works with new free-tier keys.)

Sign up: https://site.financialmodelingprep.com → free dev account → API key.
Drop into: .claude/skills/fmp/.env  →  FMP_API_KEY=...

Budget tracker: .claude/cache/fmp/budget.json — counts per UTC day.
"""
from __future__ import annotations
import json, os, time
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR   = Path(__file__).resolve().parent
_ENV_PATH     = _SCRIPT_DIR / ".env"
_PROJECT_ROOT = _SCRIPT_DIR.parents[2]
BASE_URL      = "https://financialmodelingprep.com/stable"
BUDGET_FILE   = _PROJECT_ROOT / ".claude" / "cache" / "fmp" / "budget.json"

DAILY_CAP    = 250
SOFT_LIMIT   = 200    # warn here
HARD_LIMIT   = 240    # block non-reserved calls
RESERVE_FOR_ONDEMAND = 10


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
    return os.environ.get("FMP_API_KEY")

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
        if used >= DAILY_CAP: return False, f"FMP daily cap hit ({used}/{DAILY_CAP})"
        return True, None
    if used >= HARD_LIMIT:
        return False, f"FMP soft cap hit ({used}/{HARD_LIMIT}); {DAILY_CAP - used} calls reserved. Pass reserved=True to use."
    return True, None


# ─── Core GET — /stable/ uses query-param `symbol` (not path component) ───
def _get(path, params=None, reserved=False, retries=2):
    ok, msg = _check_budget(reserved=reserved)
    if not ok: return None, msg
    key = api_key()
    if not key:
        return None, "FMP_API_KEY not set (drop it into .claude/skills/fmp/.env)"
    params = dict(params or {})
    params["apikey"] = key
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                raw = r.read().decode()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return None, f"non-JSON response: {raw[:120]}"
            # FMP error shape: {"Error Message": "..."}
            if isinstance(data, dict) and "Error Message" in data:
                err_msg = data["Error Message"][:200]
                # Restricted-endpoint errors don't burn budget conceptually but FMP did
                # technically respond — count it cautiously
                b = load_budget(); b["calls_used"] = b.get("calls_used", 0) + 1; save_budget(b)
                return None, f"FMP: {err_msg}"
            b = load_budget(); b["calls_used"] = b.get("calls_used", 0) + 1; save_budget(b)
            return data, None
        except urllib.error.HTTPError as e:
            if e.code == 402:
                return None, f"HTTP 402 (paywalled endpoint): {path}"
            if e.code in (429, 503) and attempt < retries:
                time.sleep(2 * (attempt + 1)); continue
            return None, f"HTTP {e.code}"
        except Exception as e:
            if attempt < retries:
                time.sleep(1); continue
            return None, f"{type(e).__name__}: {e}"
    return None, "retry exhausted"


# ─── Endpoints (free-tier safe) ───────────────────────────────────────────
def profile(symbol, reserved=False):
    """Company profile — name, sector, industry, mcap, price, beta, range, etc."""
    data, err = _get("/profile", {"symbol": symbol}, reserved=reserved)
    if err: return None, err
    return (data[0] if isinstance(data, list) and data else data), None


def historical_price_eod(symbol, reserved=False):
    """Daily EOD bars: list of {date, open, high, low, close, volume, change, ...}.
    Returns newest first per FMP convention."""
    return _get("/historical-price-eod/full", {"symbol": symbol}, reserved=reserved)


def historical_closes(symbol, days_back=400, reserved=False):
    """Convenience: returns list of closes oldest→newest (flipped from FMP's order)."""
    data, err = historical_price_eod(symbol, reserved=reserved)
    if err: return None, err
    if not isinstance(data, list) or not data:
        return None, "empty series"
    closes = [b["close"] for b in reversed(data[:days_back])]
    return closes, None


def ratios_ttm(symbol, reserved=False):
    """Trailing-twelve-month ratios — gross/op/net margins, ROIC, debt ratios, growth."""
    data, err = _get("/ratios-ttm", {"symbol": symbol}, reserved=reserved)
    if err: return None, err
    return (data[0] if isinstance(data, list) and data else data), None


def key_metrics_ttm(symbol, reserved=False):
    """Trailing-twelve-month key metrics — P/E, EV/EBITDA, ROE, FCF yield, etc."""
    data, err = _get("/key-metrics-ttm", {"symbol": symbol}, reserved=reserved)
    if err: return None, err
    return (data[0] if isinstance(data, list) and data else data), None


def income_growth(symbol, period="annual", reserved=False):
    """Revenue/EPS growth incl. 1y / 3y / 5y CAGR. Used for Buffett quality gate."""
    return _get("/income-statement-growth", {"symbol": symbol, "period": period}, reserved=reserved)


def quote(symbol, reserved=False):
    """Current quote — price, change, %change, day high/low."""
    data, err = _get("/quote", {"symbol": symbol}, reserved=reserved)
    if err: return None, err
    return (data[0] if isinstance(data, list) and data else data), None
