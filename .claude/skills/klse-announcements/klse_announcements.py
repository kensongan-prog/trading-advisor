#!/usr/bin/env python3
"""
klse_announcements.py — Refresh klsescreener.com Bursa announcements per KLSE ticker.

Sibling to klse-refresh (fundamentals) — same urllib + regex pattern. This script
exists so the dashboard can run a real KLSE earnings/announcement halt gate
without relying on agent-only WebFetch (the klse-news skill).

Output per ticker: .claude/cache/klse_announcements/{code}.json containing:
  - recent announcements (date, category, title, time)
  - most recent Financial Results filing (date + period-end + next-expected window)
  - upcoming events parsed from titles (ex-dividend dates, AGM/EGM dates)

Usage:
    python3 .claude/skills/klse-announcements/klse_announcements.py             # watchlist KLSE
    python3 .claude/skills/klse-announcements/klse_announcements.py 1155 7241   # specific codes
    python3 .claude/skills/klse-announcements/klse_announcements.py --show
    python3 .claude/skills/klse-announcements/klse_announcements.py --clear
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning)

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "klse_announcements"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
DEFAULT_DELAY_SEC = 1.0


# ── HTTP ──────────────────────────────────────────────────────────────────
def fetch_page(code, timeout=20):
    url = f"https://www.klsescreener.com/v2/announcements/stock/{code}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── Date inference ────────────────────────────────────────────────────────
MONTH_MAP = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
             "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def infer_year(month_num, day, now=None):
    """If the month is in the future relative to current month, it's last year.
    Otherwise current year. Handles year-rollovers like seeing 'Dec' in January."""
    now = now or datetime.now()
    candidate = now.year if month_num <= now.month else now.year - 1
    # Edge: same-month, but day in future → probably yesterday's month from last year (rare)
    if month_num == now.month and day > now.day + 1:
        candidate -= 1
    return candidate


# ── Parsing ───────────────────────────────────────────────────────────────
ITEM_RE = re.compile(
    r'<a[^>]*class="[^"]*announcement-item[^"]*"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
DAY_RE  = re.compile(r'<span\s+class="day">\s*(\d{1,2})\s*</span>', re.IGNORECASE)
MON_RE  = re.compile(r'<span\s+class="month">\s*([A-Za-z]+)\s*</span>', re.IGNORECASE)
CAT_RE  = re.compile(r'<span\s+class="category-tag\s+cat-([A-Z]+)"[^>]*>\s*([^<]+?)\s*</span>', re.IGNORECASE)
TIME_RE = re.compile(r'<span\s+class="time-ago">\s*([^<]+?)\s*</span>', re.IGNORECASE)
TITLE_RE = re.compile(r'<div\s+class="title"[^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE)


def parse_page(html, code, now=None):
    now = now or datetime.now()
    out = {"bursa_code": str(code), "announcements": []}

    # Stock name from <title> or header
    m = re.search(r'<h1[^>]*class="[^"]*company[^"]*"[^>]*>\s*([^<]+?)\s*<', html, re.IGNORECASE)
    if not m:
        m = re.search(r'company-label[^>]*>\s*([^<]+?)\s*<', html)
    if m:
        out["stock_name"] = m.group(1).strip()
    m = re.search(r'<title>\s*([^<|]+?)\s*\(', html)
    if m and not out.get("stock_name"):
        out["stock_name"] = m.group(1).strip()

    # Walk each announcement-item
    for raw in ITEM_RE.findall(html):
        item = {}
        m_day = DAY_RE.search(raw)
        m_mon = MON_RE.search(raw)
        m_cat = CAT_RE.search(raw)
        m_time = TIME_RE.search(raw)
        m_title = TITLE_RE.search(raw)
        if not (m_day and m_mon):
            continue
        try:
            day = int(m_day.group(1))
            month_abbr = m_mon.group(1).strip().title()
            month = MONTH_MAP.get(month_abbr)
            if not month:
                continue
            year = infer_year(month, day, now)
            item["date"] = f"{year:04d}-{month:02d}-{day:02d}"
        except (ValueError, TypeError):
            continue
        if m_cat:
            item["category_code"] = m_cat.group(1).strip()
            item["category"] = m_cat.group(2).strip()
        if m_time:
            item["time_of_day"] = m_time.group(1).strip()
        if m_title:
            title = re.sub(r"<[^>]+>", " ", m_title.group(1))
            item["title"] = re.sub(r"\s+", " ", title).strip()
        out["announcements"].append(item)

    # ── Derived: most recent Financial Results filing + next expected ──
    fr = next((a for a in out["announcements"]
               if a.get("category_code") in ("FA", "FRCO") or a.get("category") == "Financial Results"), None)
    if fr:
        out["most_recent_financial_results"] = {
            "filed_date": fr["date"],
            "title": fr.get("title", ""),
        }
        # Extract period-end like "31/03/2026" or "31/12/2025"
        m_pe = re.search(r"(\d{2})/(\d{2})/(\d{4})", fr.get("title", ""))
        if m_pe:
            d, mo, y = int(m_pe.group(1)), int(m_pe.group(2)), int(m_pe.group(3))
            try:
                pe_date = datetime(y, mo, d).date()
                out["most_recent_financial_results"]["period_end"] = pe_date.isoformat()
                # Next quarter-end: add ~3 months (12-week step ≈ quarter)
                next_pe_month = mo + 3
                next_pe_year = y
                if next_pe_month > 12:
                    next_pe_month -= 12; next_pe_year += 1
                last_day = (datetime(next_pe_year, next_pe_month + 1, 1) - timedelta(days=1)).day \
                           if next_pe_month < 12 else 31
                next_pe = datetime(next_pe_year, next_pe_month, last_day).date()
                # Bursa mandates filing within 60 days of quarter end
                next_filing_by = next_pe + timedelta(days=60)
                out["most_recent_financial_results"]["next_expected_period_end"] = next_pe.isoformat()
                out["most_recent_financial_results"]["next_expected_filing_by"] = next_filing_by.isoformat()
            except (ValueError, TypeError):
                pass

    # ── Derived: upcoming events parsed from Entitlements / Meetings titles ──
    upcoming = []
    date_in_title = re.compile(
        r"(\d{1,2})[\s\-/](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-/](\d{2,4})",
        re.IGNORECASE,
    )
    ex_re = re.compile(r"ex[\s\-]*date\s*[:\-]?\s*(\d{1,2}[\s\-/][A-Za-z]+[\s\-/]\d{2,4})", re.IGNORECASE)
    agm_re = re.compile(r"(?:to\s+be\s+held|date\s+of\s+meeting|meeting\s+date)\s*[:\-]?\s*(\d{1,2}[\s\-/][A-Za-z]+[\s\-/]\d{2,4})", re.IGNORECASE)

    def parse_dmy(s):
        m = date_in_title.search(s)
        if not m:
            return None
        try:
            d = int(m.group(1))
            mon = MONTH_MAP.get(m.group(2).title()[:3])
            y_raw = int(m.group(3))
            y = 2000 + y_raw if y_raw < 100 else y_raw
            return datetime(y, mon, d).date().isoformat()
        except (ValueError, TypeError):
            return None

    for a in out["announcements"]:
        title = a.get("title", "")
        cc = a.get("category_code", "")
        if cc in ("EA", "ENCO") or a.get("category", "").startswith("Entitlement"):
            m = ex_re.search(title)
            ex = parse_dmy(m.group(1)) if m else None
            if ex:
                upcoming.append({"type": "ex_dividend", "date": ex, "title": title, "filed_on": a["date"]})
        if cc in ("GM", "MECO") or a.get("category", "").startswith("General Meeting"):
            m = agm_re.search(title)
            mtg = parse_dmy(m.group(1)) if m else parse_dmy(title)
            if mtg:
                ev_type = "egm" if "extraordinary" in title.lower() else "agm"
                upcoming.append({"type": ev_type, "date": mtg, "title": title, "filed_on": a["date"]})

    # Filter to future-only and sort
    today_iso = now.date().isoformat()
    upcoming = sorted([u for u in upcoming if u["date"] >= today_iso], key=lambda x: x["date"])
    out["upcoming_events"] = upcoming
    return out


# ── Watchlist parser ──────────────────────────────────────────────────────
def klse_codes_from_watchlist():
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
def cmd_refresh(codes, delay=DEFAULT_DELAY_SEC):
    if not codes:
        print("No KLSE codes provided and none found in watchlist.md.")
        return 1
    print(f"Refreshing announcements for {len(codes)} ticker(s): {', '.join(codes)}")
    print(f"Source: klsescreener.com  |  delay between requests: {delay:.1f}s\n")
    n_ok = n_fail = 0
    for i, code in enumerate(codes):
        sys.stdout.write(f"[{i+1}/{len(codes)}] {code}  …  ")
        sys.stdout.flush()
        html, err = fetch_page(code)
        if err:
            print(f"❌ {err}")
            write_cache(code, {"bursa_code": code, "error": err, "announcements": []})
            n_fail += 1
        else:
            data = parse_page(html, code)
            write_cache(code, data)
            nm = (data.get("stock_name") or "?")[:24]
            n_ann = len(data.get("announcements") or [])
            fr = data.get("most_recent_financial_results") or {}
            next_by = fr.get("next_expected_filing_by", "—")
            n_upcoming = len(data.get("upcoming_events") or [])
            print(f"✓ {nm:<24}  {n_ann} announcements  · next FR by {next_by}  · {n_upcoming} upcoming events")
            n_ok += 1
        if i < len(codes) - 1:
            time.sleep(delay)
    print(f"\n✓ Done.  {n_ok} ok, {n_fail} failed.  Cache: {CACHE_DIR.relative_to(PROJECT_ROOT)}")
    return 0 if n_fail == 0 else 1


def cmd_show(codes):
    if not codes:
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
        n_ann = len(d.get("announcements") or [])
        fr = d.get("most_recent_financial_results") or {}
        upcoming = d.get("upcoming_events") or []
        print(f"\n{code} {nm}  (cached {ts})")
        if fr:
            print(f"  Most recent Financial Results: {fr.get('filed_date','?')} (period ended {fr.get('period_end','?')})")
            print(f"  Next expected filing by:       {fr.get('next_expected_filing_by','?')} (next period end {fr.get('next_expected_period_end','?')})")
        if upcoming:
            print(f"  Upcoming events ({len(upcoming)}):")
            for e in upcoming[:5]:
                print(f"    {e['date']}  {e['type']:6}  {(e.get('title') or '')[:80]}")
        print(f"  Total announcements cached: {n_ann}")
    return 0


def cmd_clear():
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        p.unlink(); n += 1
    print(f"✓ Cleared {n} cache entries.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", help="Bursa codes (default: all KLSE in watchlist)")
    ap.add_argument("--show", action="store_true", help="Display cached values, no fetch")
    ap.add_argument("--clear", action="store_true", help="Wipe cache and exit")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC)
    args = ap.parse_args()
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
