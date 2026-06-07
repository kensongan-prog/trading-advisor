#!/usr/bin/env python3
"""
fred.py — US macro data via FRED (St. Louis Fed) API.

Single-purpose CLI invoked by the `macro-rates` skill. Reads FRED_API_KEY from
.env in the same directory (preferred) or from environment.

Subcommands:
    snapshot   One-shot macro dashboard: rates, curve, real yields, last inflation
               prints, last NFP, dollar, VIX, with regime tag.
    series     Fetch a single FRED series with last N observations + % change.
    regime     Composite regime read combining curve + real rates + inflation + DXY.

Usage:
    python3 fred.py snapshot
    python3 fred.py series --id DGS10 --limit 30
    python3 fred.py regime

Never falls back to LLM memory. If the API errors, prints explicit failure.
Free tier: get a key at https://fredaccount.stlouisfed.org/apikeys (instant, no card).
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


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


def fred_get(series_id, api_key, limit=10, sort="desc"):
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": sort,
        "limit": str(limit),
    }
    url = FRED_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "trading-advisor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            body = ""
        return None, f"HTTP {e.code}: {e.reason} :: {body}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    obs = data.get("observations", []) or []
    # Filter out "." values which FRED uses for missing data on holidays etc.
    cleaned = [o for o in obs if o.get("value") and o.get("value") != "."]
    return cleaned, None


def latest_value(observations):
    if not observations:
        return None, None
    obs = observations[0]
    try:
        return float(obs["value"]), obs["date"]
    except (KeyError, ValueError, TypeError):
        return None, None


def yoy_change(observations):
    """Compute YoY % change for monthly series (assumes ~12 months in 'observations')."""
    if len(observations) < 13:
        return None
    try:
        cur = float(observations[0]["value"])
        prior = float(observations[12]["value"])
        return (cur / prior - 1) * 100
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None


def mom_change(observations):
    """Month-over-month % change."""
    if len(observations) < 2:
        return None
    try:
        cur = float(observations[0]["value"])
        prior = float(observations[1]["value"])
        return (cur / prior - 1) * 100
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None


def fmt_num(x, places=2, suffix=""):
    if x is None:
        return "—"
    try:
        return f"{float(x):.{places}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def fmt_sign_pct(x, places=2):
    if x is None:
        return "—"
    try:
        return f"{float(x):+.{places}f}%"
    except (TypeError, ValueError):
        return "—"


# Series IDs used in snapshot/regime. Edit here to add more.
SERIES_CATALOG = {
    # Policy + short rates
    "DFF":     ("Fed Funds Effective Rate",       "%", "daily"),
    # Yield curve
    "DGS2":    ("2-Year Treasury",                "%", "daily"),
    "DGS10":   ("10-Year Treasury",               "%", "daily"),
    "DGS30":   ("30-Year Treasury",               "%", "daily"),
    "T10Y2Y":  ("10y-2y Curve Spread",            "%", "daily"),
    "T10Y3M":  ("10y-3m Curve Spread (Fed)",      "%", "daily"),
    # Real yields / inflation expectations
    "DFII10":  ("10-Year TIPS (real yield)",      "%", "daily"),
    "T10YIE":  ("10y Breakeven Inflation",        "%", "daily"),
    # Inflation
    "CPIAUCSL":  ("CPI All Urban (headline)",     "idx", "monthly"),
    "CPILFESL":  ("Core CPI",                     "idx", "monthly"),
    "PCEPI":     ("PCE Price Index (Fed pref.)",  "idx", "monthly"),
    "PCEPILFE":  ("Core PCE (Fed pref.)",         "idx", "monthly"),
    # Labor
    "UNRATE":  ("Unemployment Rate",              "%",   "monthly"),
    "PAYEMS":  ("Total Nonfarm Payrolls (NFP)",   "k",   "monthly"),
    # Dollar
    "DTWEXBGS": ("Trade-Weighted Dollar Index (broad)", "idx", "daily"),
    # Vol
    "VIXCLS":  ("VIX (S&P 500 30-day IV)",        "",    "daily"),
}


def cmd_snapshot(args, api_key):
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"MACRO SNAPSHOT — US")
    print(f"Source:        FRED (Federal Reserve Bank of St. Louis)")
    print(f"Fetched (UTC): {fetched}")
    print()

    def pull(sid, limit=15):
        obs, err = fred_get(sid, api_key, limit=limit)
        if err:
            print(f"  warn ({sid}): {err}", file=sys.stderr)
            return None, None
        v, d = latest_value(obs)
        return (v, d), obs

    # ---- RATES & CURVE ----
    print("RATES & CURVE")
    for sid in ("DFF", "DGS2", "DGS10", "DGS30"):
        (v, d), _ = pull(sid, 5)
        name, unit, _ = SERIES_CATALOG[sid]
        print(f"  {name:32} {fmt_num(v, 2, unit):>10}   as of {d or '—'}")
    (cv2, cd2), _ = pull("T10Y2Y", 5)
    (cv3m, cd3m), _ = pull("T10Y3M", 5)
    print(f"  {'10y-2y spread':32} {fmt_num(cv2,2,'%'):>10}   as of {cd2 or '—'}   "
          f"{'(INVERTED)' if cv2 is not None and cv2 < 0 else '(NORMAL)'}")
    print(f"  {'10y-3m spread (Fed)':32} {fmt_num(cv3m,2,'%'):>10}   as of {cd3m or '—'}   "
          f"{'(INVERTED — recession signal)' if cv3m is not None and cv3m < 0 else '(NORMAL)'}")
    print()

    # ---- REAL YIELDS / INFLATION EXPECTATIONS ----
    print("REAL YIELDS & INFLATION EXPECTATIONS")
    (rv, rd), _ = pull("DFII10", 5)
    (bv, bd), _ = pull("T10YIE", 5)
    print(f"  {'10y real yield (TIPS)':32} {fmt_num(rv,2,'%'):>10}   as of {rd or '—'}")
    print(f"  {'10y breakeven inflation':32} {fmt_num(bv,2,'%'):>10}   as of {bd or '—'}")
    if rv is not None:
        if rv > 2.0:
            print("    → real yields elevated → headwind for long-duration assets (growth, gold, crypto)")
        elif rv < 0:
            print("    → real yields negative → tailwind for inflation hedges (gold, BTC, hard assets)")
    print()

    # ---- INFLATION ----
    print("INFLATION (monthly, ~2-week lag)")
    for sid in ("CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"):
        name = SERIES_CATALOG[sid][0]
        _, obs = pull(sid, 14)
        if obs:
            yoy = yoy_change(obs)
            mom = mom_change(obs)
            v, d = latest_value(obs)
            yoy_s = fmt_sign_pct(yoy, 2)
            mom_s = fmt_sign_pct(mom, 2)
            print(f"  {name:32} idx={fmt_num(v,2):>8}  MoM {mom_s:>7}  YoY {yoy_s:>7}   as of {d or '—'}")
    print()

    # ---- LABOR ----
    print("LABOR")
    _, ur_obs = pull("UNRATE", 6)
    if ur_obs:
        v, d = latest_value(ur_obs)
        print(f"  {'Unemployment Rate':32} {fmt_num(v,2,'%'):>10}   as of {d or '—'}")
    _, py_obs = pull("PAYEMS", 6)
    if py_obs and len(py_obs) >= 2:
        try:
            cur = float(py_obs[0]["value"])
            prior = float(py_obs[1]["value"])
            d = py_obs[0]["date"]
            chg = cur - prior  # in thousands
            print(f"  {'Nonfarm Payrolls (NFP)':32} {chg:>+8.0f}k  vs prior month   as of {d}")
        except Exception:
            pass
    print()

    # ---- DOLLAR & VOL ----
    print("DOLLAR & VOL")
    (dv, dd), dobs = pull("DTWEXBGS", 30)
    print(f"  {'Trade-weighted USD (broad)':32} idx={fmt_num(dv,2):>8}   as of {dd or '—'}")
    if dobs and len(dobs) >= 22:
        try:
            mo_ago = float(dobs[21]["value"])
            chg = (dv / mo_ago - 1) * 100
            print(f"    → DXY 30d change: {chg:+.2f}%")
        except Exception:
            pass
    (vix, vd), _ = pull("VIXCLS", 5)
    print(f"  {'VIX (S&P 30d IV)':32} {fmt_num(vix,2):>10}   as of {vd or '—'}")
    if vix is not None:
        if vix > 25:
            print("    → elevated vol → equity risk-off / option premium rich")
        elif vix < 13:
            print("    → low vol → complacency / cheap option premium")
        else:
            print("    → normal vol range")
    return 0


def cmd_series(args, api_key):
    sid = args.id.upper()
    obs, err = fred_get(sid, api_key, limit=args.limit)
    if err:
        print(f"FETCH FAILED ({sid}): {err}")
        return 1
    if not obs:
        print(f"NO DATA returned for {sid}.")
        return 1
    name = SERIES_CATALOG.get(sid, (sid, "", "?"))[0]
    print(f"FRED SERIES — {sid}   ({name})")
    print(f"Source:        FRED")
    print(f"Fetched (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    print(f"Observations:  {len(obs)} (most recent first)")
    print()
    print(f"{'date':12}  {'value':>12}")
    for o in obs:
        print(f"{o.get('date',''):12}  {o.get('value',''):>12}")
    if len(obs) >= 2:
        try:
            cur = float(obs[0]["value"])
            prior = float(obs[1]["value"])
            print(f"\nLatest change vs prior obs: {cur - prior:+.4f}  ({(cur/prior - 1)*100:+.2f}%)")
        except Exception:
            pass
    if len(obs) >= 13:
        try:
            cur = float(obs[0]["value"])
            yr = float(obs[12]["value"])
            print(f"YoY change (vs 12 obs ago):  {cur - yr:+.4f}  ({(cur/yr - 1)*100:+.2f}%)")
        except Exception:
            pass
    return 0


def cmd_regime(args, api_key):
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"MACRO REGIME READ")
    print(f"Source:        FRED")
    print(f"Fetched (UTC): {fetched}")
    print()

    def get(sid, n=15):
        obs, _ = fred_get(sid, api_key, limit=n)
        return obs

    signals = []
    notes = []

    # Yield curve
    t10y2y_obs = get("T10Y2Y", 5)
    t10y3m_obs = get("T10Y3M", 5)
    if t10y2y_obs:
        v, _ = latest_value(t10y2y_obs)
        if v is not None:
            if v < 0:
                signals.append(("curve_inverted", -1, f"10y-2y inverted at {v:.2f}%"))
            elif v < 0.3:
                signals.append(("curve_flat", -0.5, f"10y-2y flat at {v:.2f}%"))
            else:
                signals.append(("curve_normal", +0.5, f"10y-2y positive at {v:.2f}%"))
    if t10y3m_obs:
        v, _ = latest_value(t10y3m_obs)
        if v is not None and v < 0:
            signals.append(("curve3m_inverted", -1, f"10y-3m inverted at {v:.2f}% (Fed's recession signal)"))

    # Real yields
    rv_obs = get("DFII10", 30)
    if rv_obs:
        v, _ = latest_value(rv_obs)
        if v is not None:
            if v > 2:
                signals.append(("real_yields_high", -1, f"10y real yield {v:.2f}% → strong headwind for duration"))
            elif v < 0:
                signals.append(("real_yields_negative", +1, f"10y real yield {v:.2f}% → tailwind for inflation hedges"))
            else:
                signals.append(("real_yields_normal", 0, f"10y real yield {v:.2f}%"))
        # 30-day trend
        if len(rv_obs) >= 22:
            try:
                cur = float(rv_obs[0]["value"])
                old = float(rv_obs[21]["value"])
                chg = cur - old
                if abs(chg) > 0.2:
                    direction = "rising" if chg > 0 else "falling"
                    signals.append(("real_yields_trend", -1 if chg > 0 else +1,
                                    f"real yields {direction} {chg:+.2f}% over 30d"))
            except Exception:
                pass

    # Inflation trajectory
    cpi_obs = get("CPILFESL", 14)
    if cpi_obs:
        yoy = yoy_change(cpi_obs)
        if yoy is not None:
            if yoy > 4:
                signals.append(("inflation_hot", -1, f"Core CPI YoY {yoy:.2f}% (above Fed comfort)"))
            elif yoy < 2:
                signals.append(("inflation_cool", +0.5, f"Core CPI YoY {yoy:.2f}% (below 2% target)"))
            else:
                signals.append(("inflation_normal", 0, f"Core CPI YoY {yoy:.2f}% (in Fed band)"))

    # Dollar trend
    dxy_obs = get("DTWEXBGS", 30)
    if dxy_obs and len(dxy_obs) >= 22:
        try:
            cur = float(dxy_obs[0]["value"])
            old = float(dxy_obs[21]["value"])
            chg = (cur / old - 1) * 100
            if chg > 1.5:
                signals.append(("dxy_strong", -0.5,
                                f"USD broad index +{chg:.2f}% over 30d (risk-off / EM/crypto/gold headwind)"))
            elif chg < -1.5:
                signals.append(("dxy_weak", +0.5,
                                f"USD broad index {chg:.2f}% over 30d (risk-on tailwind)"))
            else:
                signals.append(("dxy_stable", 0, f"USD broad index {chg:+.2f}% over 30d (stable)"))
        except Exception:
            pass

    # Vol
    vix_obs = get("VIXCLS", 5)
    if vix_obs:
        v, _ = latest_value(vix_obs)
        if v is not None:
            if v > 25:
                signals.append(("vol_high", -1, f"VIX {v:.1f} (elevated — equity risk-off; option premium rich)"))
            elif v < 13:
                signals.append(("vol_low", -0.3, f"VIX {v:.1f} (complacent — option premium cheap; reversal risk if shock)"))
            else:
                signals.append(("vol_normal", 0, f"VIX {v:.1f} (normal range)"))

    # Composite
    score = sum(s[1] for s in signals)
    if score >= 1.5:
        regime = "RISK-ON tailwind"
    elif score <= -1.5:
        regime = "RISK-OFF headwind"
    elif score <= -0.5:
        regime = "CAUTIOUS — mixed with bearish lean"
    elif score >= 0.5:
        regime = "CONSTRUCTIVE — mixed with bullish lean"
    else:
        regime = "NEUTRAL — no clear regime"

    print("SIGNAL TABLE")
    for tag, weight, note in signals:
        sign = "+" if weight > 0 else ("−" if weight < 0 else "0")
        print(f"  [{sign}{abs(weight):.1f}]  {note}")
    print()
    print(f"COMPOSITE SCORE: {score:+.1f}")
    print(f"REGIME READ:     {regime}")
    print()
    print("Apply to recommendation logic per AGENTS.md §4:")
    print("  - RISK-OFF / CAUTIOUS  → bias toward defensive sectors (RGLD-type), avoid high-beta longs,")
    print("                            tighten R:R floors (prefer 2R+), shrink position sizes.")
    print("  - RISK-ON / CONSTRUCTIVE → standard sizing OK; high-beta/growth names viable per playbook P1.")
    print("  - NEUTRAL              → no regime tailwind/headwind — confluence must stand on its own.")
    return 0


def main():
    load_dotenv_if_present()
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("ERROR: no API key. Set FRED_API_KEY in .claude/skills/macro-rates/.env "
              "or in shell env.", file=sys.stderr)
        print("Get a free key (instant, no card) at https://fredaccount.stlouisfed.org/apikeys",
              file=sys.stderr)
        return 2

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("snapshot", help="Full macro dashboard")
    ps.set_defaults(func=cmd_snapshot)

    pser = sub.add_parser("series", help="Fetch one FRED series")
    pser.add_argument("--id", required=True, help="FRED series ID, e.g. DGS10")
    pser.add_argument("--limit", type=int, default=24)
    pser.set_defaults(func=cmd_series)

    pr = sub.add_parser("regime", help="Composite regime read")
    pr.set_defaults(func=cmd_regime)

    args = p.parse_args()
    return args.func(args, api_key)


if __name__ == "__main__":
    sys.exit(main())
