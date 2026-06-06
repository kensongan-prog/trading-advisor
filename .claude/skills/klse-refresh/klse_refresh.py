#!/usr/bin/env python3
"""
klse_refresh.py — Manually refresh klsescreener.com fundamentals for KLSE tickers.

Why this exists: WebFetch is an agent-only tool not callable from Python. The
dashboard's KLSE grid uses yfinance for prices/technicals but yfinance has only
sparse fundamentals for .KL tickers. klsescreener has rich fundamentals (P/E,
P/B, NTA, ROE, dividend yield, RSI(14), 52w range, sector) but is web-only —
so we hit it directly with urllib + regex and cache results to JSON files.

Manual (no automation): you run this when you want fresh KLSE fundamentals.
Output: .claude/cache/klse_fundamentals/{code}.json per ticker.

Usage:
    python3 .claude/skills/klse-refresh/klse_refresh.py             # all KLSE in watchlist
    python3 .claude/skills/klse-refresh/klse_refresh.py 1155 7241   # specific codes
    python3 .claude/skills/klse-refresh/klse_refresh.py --show      # cached values, no fetch
    python3 .claude/skills/klse-refresh/klse_refresh.py --clear     # wipe cache

Never falls back to LLM memory: if a fetch errors, the cache entry records the
failure with timestamp and the dashboard can show 'last refresh failed'.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning)

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "klse_fundamentals"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
DEFAULT_DELAY_SEC = 1.0  # be polite to klsescreener


# ── HTTP ──────────────────────────────────────────────────────────────────
def fetch_page(code, timeout=20):
    url = f"https://www.klsescreener.com/v2/stocks/view/{code}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── Parsing ───────────────────────────────────────────────────────────────
def _td_pair(html, label_regex):
    """Match <td...>LABEL</td>...<td class="...number...">VALUE</td>."""
    pat = re.compile(
        rf'<td[^>]*>\s*(?:{label_regex})\s*</td>\s*<td[^>]*class="[^"]*number[^"]*"[^>]*>([^<]+)</td>',
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(html)
    return m.group(1).strip() if m else None


def _td_pair_anyclass(html, label_regex):
    """Like _td_pair but value <td> can have any class and contain nested elements
    (e.g. RSI cell has a <span> label + the numeric value)."""
    pat = re.compile(
        rf'<td[^>]*>\s*(?:{label_regex})\s*</td>\s*<td[^>]*>(.*?)</td>',
        re.IGNORECASE | re.DOTALL,
    )
    m = pat.search(html)
    if not m:
        return None
    # Strip any nested tags and collapse whitespace
    val = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", val).strip()


def _num(s, allow_unit=False):
    if s is None:
        return None
    s = s.replace(",", "").strip()
    if not allow_unit:
        m = re.match(r"^-?\d+(?:\.\d+)?$", s)
        return float(m.group(0)) if m else None
    # allow suffix B / M / k
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*([BbMmKk])?$", s)
    if not m:
        return None
    v = float(m.group(1))
    suf = (m.group(2) or "").lower()
    if suf == "b": v *= 1e9
    elif suf == "m": v *= 1e6
    elif suf == "k": v *= 1e3
    return v


def parse_page(html, code):
    out = {"bursa_code": str(code)}

    # Stock name + symbol (from <title> or header)
    m = re.search(r"<title>\s*([^<|]+?)\s*(?:\([^)]+\))?\s*[\|<]", html)
    if m:
        out["page_title"] = m.group(1).strip()
    m = re.search(r'<h1[^>]*>\s*([^<]+?)\s*<', html)
    if m:
        out["stock_name"] = m.group(1).strip()
    # Try a stock_symbol header pattern
    m = re.search(r'class="[^"]*stock_name[^"]*"[^>]*>\s*([^<]+?)\s*<', html)
    if m and not out.get("stock_name"):
        out["stock_name"] = m.group(1).strip()

    # Price (from <span id="price" data-value="...">VALUE</span>)
    m = re.search(r'<span\s+id="price"\s+data-value="([\d.]+)"', html)
    if m:
        out["last_price"] = float(m.group(1))

    # Volume
    m = re.search(r'<td[^>]*id="volume"[^>]*>\s*([\d,]+)\s*</td>', html)
    if m:
        out["volume"] = int(m.group(1).replace(",", ""))

    # 52w range (single TD with "low - high")
    range_str = _td_pair(html, r"52w")
    if range_str and "-" in range_str:
        try:
            lo, hi = [x.strip() for x in range_str.split("-", 1)]
            out["week52_low"] = float(lo)
            out["week52_high"] = float(hi)
        except (ValueError, IndexError):
            out["week52_range_raw"] = range_str

    # Fundamentals (paired TDs with class=number)
    for label, key, allow_unit in [
        (r"P/E",            "pe_ratio",         False),
        (r"EPS",            "eps",              False),
        (r"NTA",            "nta",              False),
        (r"DPS",            "dps",              False),
        (r"DY%?",           "dividend_yield_pct", False),
        (r"P/B",            "pb_ratio",         False),
        (r"ROE",            "roe_pct",          False),
        (r"Market Cap",     "market_cap_raw",   True),
        (r"Revenue",        "revenue_raw",      True),
    ]:
        raw = _td_pair(html, label)
        if raw is not None:
            n = _num(raw, allow_unit=allow_unit)
            if n is not None:
                out[key] = n
            else:
                out[f"{key}_raw"] = raw

    # RSI(14) — value column has a span label ("Neutral", "Oversold", etc.) + the number
    rsi_raw = _td_pair_anyclass(html, r"RSI\(14\)")
    if rsi_raw:
        # The cell looks like "Neutral 32.8" — find the numeric part
        m = re.search(r"(\d+(?:\.\d+)?)", rsi_raw)
        if m:
            out["rsi_14"] = float(m.group(1))
        # Capture the label tag too if present
        lab = re.search(r"^([A-Za-z]+)", rsi_raw)
        if lab:
            out["rsi_14_label"] = lab.group(1)

    # Sector (look for "Sector" or "Industry" anchor / table cell)
    m = re.search(r"Sector[^<]*</[a-z]+>\s*<[^>]+>\s*<a[^>]*>([^<]+)</a>", html, re.IGNORECASE)
    if m:
        out["sector"] = m.group(1).strip()
    else:
        m = re.search(r">Sector</[a-z]+>\s*<[^>]+>([^<]+)<", html, re.IGNORECASE)
        if m:
            out["sector"] = m.group(1).strip()

    # Dividend Yield with %
    if "dividend_yield_pct" not in out:
        dy = _td_pair(html, r"DY")
        if dy is not None:
            n = _num(dy.replace("%", ""))
            if n is not None:
                out["dividend_yield_pct"] = n

    return out


# ── Watchlist parser (KLSE section only) ─────────────────────────────────
def klse_codes_from_watchlist():
    """Read watchlist.md, return list of bursa codes (4-digit strings)."""
    if not WATCHLIST_PATH.is_file():
        return []
    text = WATCHLIST_PATH.read_text()
    codes = []
    in_klse = False
    for line in text.splitlines():
        if line.startswith("## "):
            heading = re.sub(r"^#+\s*", "", line).strip().lower()
            in_klse = heading.startswith("klse") or heading.startswith("bursa") or heading.startswith("malaysia")
            continue
        if not in_klse or not line.strip():
            continue
        # Match `- \`CODE\`` or `- \`CODE.KL\``
        m = re.match(r"\s*-\s*`([^`]+)`", line)
        if m:
            tk = m.group(1).strip().upper()
            if tk.endswith(".KL"):
                tk = tk[:-3]
            if tk.isdigit():
                codes.append(tk.zfill(4))
    return codes


# ── Cache ─────────────────────────────────────────────────────────────────
def cache_path(code):
    return CACHE_DIR / f"{code}.json"


def write_cache(code, payload):
    payload = dict(payload)
    payload["_fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache_path(code).write_text(json.dumps(payload, indent=2, default=str))


def read_cache(code):
    p = cache_path(code)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_refresh(codes, delay=DEFAULT_DELAY_SEC, force=False):
    if not codes:
        print("No KLSE codes provided and none found in watchlist.md.")
        return 1
    print(f"Refreshing {len(codes)} KLSE ticker(s): {', '.join(codes)}")
    print(f"Source: klsescreener.com  |  delay between requests: {delay:.1f}s\n")

    n_ok = n_fail = 0
    for i, code in enumerate(codes):
        sys.stdout.write(f"[{i+1}/{len(codes)}] {code}  …  ")
        sys.stdout.flush()
        html, err = fetch_page(code)
        if err:
            print(f"❌ {err}")
            write_cache(code, {"bursa_code": code, "error": err})
            n_fail += 1
        else:
            data = parse_page(html, code)
            write_cache(code, data)
            nm = (data.get("stock_name") or data.get("page_title") or "?")[:24]
            price = data.get("last_price")
            pe = data.get("pe_ratio")
            rsi = data.get("rsi_14")
            dy = data.get("dividend_yield_pct")
            print(f"✓ {nm:<24}  px={price}  P/E={pe}  RSI={rsi}  DY={dy}")
            n_ok += 1
        if i < len(codes) - 1:
            time.sleep(delay)
    print(f"\n✓ Done.  {n_ok} ok, {n_fail} failed.  Cache: {CACHE_DIR.relative_to(PROJECT_ROOT)}")
    return 0 if n_fail == 0 else 1


def cmd_show(codes):
    if not codes:
        # show everything in cache
        codes = [p.stem for p in sorted(CACHE_DIR.glob("*.json"))]
    if not codes:
        print("No cached entries.")
        return 0
    for code in codes:
        d = read_cache(code)
        if not d:
            print(f"{code}  — no cache entry")
            continue
        ts = d.get("_fetched_at", "?")
        if d.get("error"):
            print(f"{code}  ⚠ LAST FETCH FAILED ({ts}): {d['error']}")
            continue
        nm = (d.get("stock_name") or "?")[:30]
        price = d.get("last_price"); pe = d.get("pe_ratio"); pb = d.get("pb_ratio")
        nta = d.get("nta"); roe = d.get("roe_pct"); dy = d.get("dividend_yield_pct")
        rsi = d.get("rsi_14"); sec = (d.get("sector") or "—")[:30]
        w52l = d.get("week52_low"); w52h = d.get("week52_high")
        mc = d.get("market_cap_raw")
        print(f"{code} {nm:<30}  px={price}  P/E={pe}  P/B={pb}  NTA={nta}  "
              f"ROE={roe}%  DY={dy}%  RSI={rsi}  52w={w52l}-{w52h}  mcap={mc}  sec={sec}  @ {ts}")
    return 0


def cmd_clear():
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        p.unlink(); n += 1
    print(f"✓ Cleared {n} cache entries.")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Refresh klsescreener fundamentals to local cache.")
    ap.add_argument("codes", nargs="*", help="Specific Bursa codes (default: all KLSE in watchlist)")
    ap.add_argument("--show", action="store_true", help="Display cached values without fetching")
    ap.add_argument("--clear", action="store_true", help="Wipe the cache and exit")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC, help="Seconds between requests (politeness)")
    args = ap.parse_args()

    # Normalize codes to 4-digit strings
    codes = []
    for c in args.codes:
        c = c.strip().upper()
        if c.endswith(".KL"): c = c[:-3]
        if c.isdigit(): codes.append(c.zfill(4))

    if args.clear:
        return cmd_clear()
    if args.show:
        return cmd_show(codes)
    if not codes:
        codes = klse_codes_from_watchlist()
    return cmd_refresh(codes, delay=args.delay)


if __name__ == "__main__":
    sys.exit(main())
