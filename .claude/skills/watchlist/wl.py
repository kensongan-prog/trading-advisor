#!/usr/bin/env python3
"""
wl.py — Watchlist CLI: add / remove / update / list with auto-classification,
auto-thesis, validation, soft-delete, and atomic writes.

Source of truth: <project_root>/watchlist.md
Backups: .claude/cache/watchlist_backups/watchlist_YYYY-MM-DD_HHMMSS.md
Cache invalidation: .claude/cache/dashboard/yfin_TICKER.json deleted on add/update/remove.

Usage:
    python3 .claude/skills/watchlist/wl.py add KTOS
    python3 .claude/skills/watchlist/wl.py add HOOD --thesis "Robinhood; rate-sensitive broker"
    python3 .claude/skills/watchlist/wl.py add 5347
    python3 .claude/skills/watchlist/wl.py add PURR --section us       # override auto-classify
    python3 .claude/skills/watchlist/wl.py remove KTOS --reason "trend filter still failing after 3 weeks"
    python3 .claude/skills/watchlist/wl.py update KTOS --thesis "moved to SMA50 reclaim watch"
    python3 .claude/skills/watchlist/wl.py list
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore", category=Warning)

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
BACKUP_DIR = PROJECT_ROOT / ".claude" / "cache" / "watchlist_backups"
DASHBOARD_CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard"
# Resolution cache — written on add, read by dashboard so any newly-added crypto
# alt is auto-discoverable without touching the hardcoded SYMBOL_MAP / CRYPTO_TO_BINANCE dicts.
RESOLUTIONS_CACHE = PROJECT_ROOT / ".claude" / "cache" / "watchlist_resolutions"

# ── Skill .env (for COINGECKO_API_KEY) ─────────────────────────────────────
def load_env(skill_name):
    env_path = SKILLS_DIR / skill_name / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
load_env("crypto-coingecko")

# ── Section detection ──────────────────────────────────────────────────────
def _heading_first_word(line):
    """Return the first word of a markdown '## Header' line, lowercased."""
    # Strip leading '## ' and surrounding whitespace; take first token (split on space or paren)
    body = re.sub(r"^#+\s*", "", line).strip()
    m = re.match(r"([A-Za-z]+)", body)
    return m.group(1).lower() if m else ""

SECTION_HEADERS = {
    "us":      ("## Equities / ETFs",
                lambda h: _heading_first_word(h) in ("equities", "etfs", "etf", "us")),
    "klse":    ("## KLSE (Bursa Malaysia, spot equity only — no options per scope)",
                lambda h: _heading_first_word(h) in ("klse", "bursa", "malaysia")),
    "crypto":  ("## Crypto",
                lambda h: _heading_first_word(h) == "crypto"),
    "options": ("## Options (underlyings of interest)",
                lambda h: _heading_first_word(h) == "options"),
    "removed": ("## Removed / retired",
                lambda h: _heading_first_word(h) in ("removed", "retired")),
}

KNOWN_CRYPTO_SYMBOLS = {
    "BTC","ETH","SOL","BNB","XRP","HBAR","ADA","DOGE","TON","TRX","AVAX","MATIC",
    "DOT","LINK","UNI","LTC","ATOM","NEAR","APT","ARB","OP","ONDO","HYPE","SUI",
    "TIA","ENA","PYTH","STRK","WLD","SHIB","TRUMP","PEPE","BCH","ETC","FIL","ICP",
}

CRYPTO_SYMBOL_TO_CG_ID = {
    "btc":"bitcoin","eth":"ethereum","sol":"solana","bnb":"binancecoin","xrp":"ripple",
    "hbar":"hedera-hashgraph","ada":"cardano","doge":"dogecoin","ton":"the-open-network",
    "trx":"tron","avax":"avalanche-2","matic":"matic-network","dot":"polkadot",
    "link":"chainlink","uni":"uniswap","ltc":"litecoin","atom":"cosmos","near":"near",
    "apt":"aptos","arb":"arbitrum","op":"optimism","ondo":"ondo-finance","hype":"hyperliquid",
    "sui":"sui","tia":"celestia","ena":"ethena","pyth":"pyth-network","strk":"starknet",
    "wld":"worldcoin","shib":"shiba-inu","pepe":"pepe","bch":"bitcoin-cash","etc":"ethereum-classic",
    "fil":"filecoin","icp":"internet-computer",
}


def classify(ticker):
    """Return 'us' | 'klse' | 'crypto' | None."""
    t = ticker.strip().upper()
    if t.endswith(".KL"):
        return "klse"
    if t.isdigit() and 1 <= len(t) <= 4:
        return "klse"
    if t in KNOWN_CRYPTO_SYMBOLS:
        return "crypto"
    if re.match(r"^[A-Z]{1,5}$", t):
        return "us"
    return None


def normalize_for_section(ticker, section):
    """Convert ticker to display form for the section."""
    t = ticker.strip().upper()
    if section == "klse":
        if t.isdigit():
            # pad to 4 digits if needed and add .KL
            return f"{t.zfill(4)}.KL"
        if not t.endswith(".KL"):
            return f"{t}.KL"
        return t
    return t


# ── Watchlist parser (preserves line structure) ────────────────────────────
def read_watchlist():
    if not WATCHLIST_PATH.is_file():
        sys.exit(f"ERROR: watchlist.md not found at {WATCHLIST_PATH}")
    return WATCHLIST_PATH.read_text().splitlines()


def find_section_bounds(lines, section_key):
    """Find (start_line, end_line) for the section. start = line index of heading,
    end = exclusive index of next heading or EOF."""
    _, matcher = SECTION_HEADERS[section_key]
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and matcher(line):
            start = i
            break
    if start is None:
        return None, None
    # Find end: next "## " heading or EOF
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def extract_tickers_in_section(lines, start, end):
    """Return dict {ticker_upper: (line_index, full_line, thesis_text)} for entries in section."""
    result = {}
    for i in range(start + 1, end):
        line = lines[i]
        # Pattern 1: `- \`TICKER\` — thesis`
        m = re.match(r"\s*-\s*`([^`]+)`\s*[—\-:]?\s*(.*)", line)
        if m:
            t = m.group(1).strip().upper()
            result[t] = (i, line, m.group(2).strip())
            continue
        # Pattern 2: bare bullet `- TICKER`
        m = re.match(r"\s*-\s*([A-Z0-9.]+)\s*$", line)
        if m:
            t = m.group(1).strip().upper()
            result[t] = (i, line, "")
    return result


def find_existing(ticker_upper):
    """Search all sections for the ticker. Return (section_key, line_idx, line, thesis) or None."""
    lines = read_watchlist()
    for sec in ("us", "klse", "crypto", "options", "removed"):
        s, e = find_section_bounds(lines, sec)
        if s is None:
            continue
        entries = extract_tickers_in_section(lines, s, e)
        if ticker_upper in entries:
            i, l, th = entries[ticker_upper]
            return (sec, i, l, th)
    return None


# ── HTTP + data fetchers ──────────────────────────────────────────────────
def http_json(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "trading-advisor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fetch_us_meta(ticker):
    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance not installed"
    try:
        y = yf.Ticker(ticker)
        info = y.info or {}
        if not info.get("shortName") and not info.get("longName"):
            return None, "no name returned by yfinance"
        # quick history check
        h = y.history(period="5d")
        if h.empty:
            return None, "no price history available"
        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": info.get("exchange"),
            "country": info.get("country"),
            "price": float(h["Close"].iloc[-1]),
        }, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fetch_klse_meta(ticker):
    # Same yfinance path, but metadata sparser for .KL
    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance not installed"
    try:
        y = yf.Ticker(ticker)
        info = y.info or {}
        h = y.history(period="5d").dropna(subset=["Close"])
        if h.empty:
            return None, "no .KL price history (verify the Bursa code)"
        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector"),
            "currency": info.get("currency", "MYR"),
            "price": float(h["Close"].iloc[-1]),
        }, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fetch_crypto_meta(symbol):
    cg_id = CRYPTO_SYMBOL_TO_CG_ID.get(symbol.lower(), symbol.lower())
    cg_key = os.environ.get("COINGECKO_API_KEY")
    base = "https://pro-api.coingecko.com/api/v3" if cg_key else "https://api.coingecko.com/api/v3"
    headers = {"User-Agent": "trading-advisor/1.0"}
    if cg_key:
        headers["x-cg-pro-api-key"] = cg_key
    url = f"{base}/coins/{cg_id}?localization=false&tickers=false&community_data=false&developer_data=false&sparkline=false"
    data, err = http_json(url, headers=headers)
    if err:
        return None, err
    if not data or "id" not in data:
        return None, f"CoinGecko did not return a coin for id '{cg_id}'"
    md = data.get("market_data") or {}
    return {
        "ticker": symbol.upper(),
        "name": data.get("name"),
        "cg_id": data.get("id"),
        "market_cap_rank": data.get("market_cap_rank"),
        "categories": data.get("categories") or [],
        "current_price": (md.get("current_price") or {}).get("usd"),
    }, None


# ── Thesis builders ───────────────────────────────────────────────────────
def build_thesis_us(meta):
    bits = []
    if meta.get("name"):
        bits.append(meta["name"])
    if meta.get("sector") and meta.get("industry"):
        bits.append(f"{meta['sector']} / {meta['industry']}")
    elif meta.get("sector"):
        bits.append(meta["sector"])
    return "; ".join(bits) if bits else meta["ticker"]


def build_thesis_klse(meta):
    bits = []
    if meta.get("name"):
        bits.append(meta["name"])
    if meta.get("sector"):
        bits.append(meta["sector"])
    return "; ".join(bits) if bits else meta["ticker"]


def build_thesis_crypto(meta):
    bits = []
    if meta.get("name"):
        bits.append(meta["name"])
    if meta.get("market_cap_rank"):
        bits.append(f"#{meta['market_cap_rank']}")
    if meta.get("categories"):
        bits.append(" / ".join(meta["categories"][:2]))
    return "; ".join(bits) if bits else meta["ticker"]


# ── Atomic write + backup ─────────────────────────────────────────────────
def backup_watchlist():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    bk = BACKUP_DIR / f"watchlist_{ts}.md"
    bk.write_text(WATCHLIST_PATH.read_text())
    # Rotate: keep last 10
    backups = sorted(BACKUP_DIR.glob("watchlist_*.md"), reverse=True)
    for old in backups[10:]:
        try:
            old.unlink()
        except Exception:
            pass
    return bk


def atomic_write(lines):
    tmp = WATCHLIST_PATH.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(str(tmp), str(WATCHLIST_PATH))


def _probe_binance_spot(symbol_upper):
    """Return BASEUSDT pair string if listed on Binance spot, else None. ~200ms timeout."""
    pair = f"{symbol_upper}USDT"
    url = f"https://api.binance.com/api/v3/exchangeInfo?symbol={pair}"
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            if r.status == 200:
                return pair
    except Exception:
        return None
    return None


def write_resolution_cache(ticker_display, section, meta):
    """Persist resolved identifiers so the dashboard can look up newly-added tickers.
    Currently most useful for crypto (cg_id + binance_pair) but works for all sections.
    """
    RESOLUTIONS_CACHE.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker_display.upper(),
        "section": section,
        "name": (meta or {}).get("name"),
        "_resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if section == "crypto":
        payload["cg_id"] = (meta or {}).get("cg_id")
        # Probe Binance spot — silently None if not listed (HYPE, small alts).
        payload["binance_pair"] = _probe_binance_spot(ticker_display.upper())
    elif section in ("us", "options"):
        payload["sector"] = (meta or {}).get("sector")
        payload["industry"] = (meta or {}).get("industry")
    elif section == "klse":
        payload["sector"] = (meta or {}).get("sector")
    safe = ticker_display.upper().replace(".", "_").replace(":", "_")
    target = RESOLUTIONS_CACHE / f"{safe}.json"
    target.write_text(json.dumps(payload, indent=2))
    return target


def remove_resolution_cache(ticker_display):
    safe = ticker_display.upper().replace(".", "_").replace(":", "_")
    target = RESOLUTIONS_CACHE / f"{safe}.json"
    if target.is_file():
        try:
            target.unlink()
            return True
        except Exception:
            return False
    return False


def invalidate_dashboard_cache(ticker_display):
    """Delete the per-ticker cache file so next dashboard refresh fetches fresh."""
    safe = ticker_display.replace(".", "_").replace(":", "_")
    target = DASHBOARD_CACHE / f"yfin_{safe}.json"
    if target.is_file():
        try:
            target.unlink()
            return True
        except Exception:
            return False
    return False


# ── User confirmation ─────────────────────────────────────────────────────
def confirm(prompt, default_no=True):
    suffix = "[y/N]" if default_no else "[Y/n]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return not default_no
    return ans in ("y", "yes")


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_add(args):
    raw_ticker = args.ticker.strip().upper()
    section = args.section or classify(raw_ticker)
    if section is None:
        print(f"❌ Could not classify '{raw_ticker}'. Use --section us|klse|crypto|options to override.", file=sys.stderr)
        return 2

    display_ticker = normalize_for_section(raw_ticker, section)
    upper_key = display_ticker.upper()

    # Check duplicates / historical removals
    existing = find_existing(upper_key)
    if existing:
        sec, idx, line, thesis = existing
        if sec == "removed":
            print(f"⚠ {display_ticker} is in Removed/retired:")
            print(f"    {line.strip()}")
            if not args.yes and not confirm(f"Re-add to {section}?"):
                print("Aborted.")
                return 0
        else:
            print(f"❌ {display_ticker} already in '{sec}' section:", file=sys.stderr)
            print(f"    {line.strip()}", file=sys.stderr)
            print(f"   Use `wl.py update {display_ticker} --thesis \"...\"` to change its thesis.", file=sys.stderr)
            return 1

    # Resolve metadata
    print(f"Resolving {display_ticker} ({section})…")
    if section == "us":
        meta, err = fetch_us_meta(display_ticker)
    elif section == "klse":
        meta, err = fetch_klse_meta(display_ticker)
    elif section == "crypto":
        meta, err = fetch_crypto_meta(display_ticker)
    elif section == "options":
        meta, err = fetch_us_meta(display_ticker)  # options underlyings are US equities
    else:
        meta, err = None, f"unsupported section: {section}"

    if not meta:
        if args.allow_unresolved:
            print(f"⚠ Could not resolve: {err}. Proceeding because --allow-unresolved is set.")
            meta = {"ticker": display_ticker, "name": display_ticker}
        else:
            print(f"❌ Could not resolve {display_ticker}: {err}", file=sys.stderr)
            print(f"   Verify the ticker, or pass --allow-unresolved + --thesis to force add.", file=sys.stderr)
            return 1

    # Build thesis
    if args.thesis:
        thesis = args.thesis
    else:
        if section == "us" or section == "options":
            thesis = build_thesis_us(meta)
        elif section == "klse":
            thesis = build_thesis_klse(meta)
        elif section == "crypto":
            thesis = build_thesis_crypto(meta)
        else:
            thesis = meta.get("name", display_ticker)

    new_line = f"- `{display_ticker}` — {thesis}"

    # Preview + confirm
    print()
    print(f"Resolved:  {meta.get('name', display_ticker)}")
    if meta.get("sector"):
        print(f"  Sector:  {meta['sector']}" + (f" / {meta['industry']}" if meta.get('industry') else ""))
    if meta.get("price") is not None:
        cur = meta.get("currency", "USD")
        print(f"  Price:   {cur} {meta['price']:.4f}")
    elif meta.get("current_price") is not None:
        print(f"  Price:   USD {meta['current_price']:.4f}")
    if meta.get("market_cap_rank"):
        print(f"  Rank:    #{meta['market_cap_rank']}")
    print(f"  Section: {section}")
    print()
    print(f"Will insert into '{section}' section:")
    print(f"  {new_line}")
    print()

    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0

    # Perform edit
    lines = read_watchlist()
    backup_path = backup_watchlist()
    s, e = find_section_bounds(lines, section)
    if s is None:
        print(f"❌ Section '{section}' header not found in watchlist.md", file=sys.stderr)
        return 1
    # Find insertion point: last non-blank line before next section
    insert_idx = e
    for j in range(e - 1, s, -1):
        if lines[j].strip():
            insert_idx = j + 1
            break
    # If we're in 'removed' there was no previous bullet; insert right after header
    if insert_idx == e and not any(l.strip() for l in lines[s+1:e]):
        insert_idx = s + 1

    # If existing was in 'removed', also drop that historical line
    if existing and existing[0] == "removed":
        # Remove the old removed line first (its index may shift after insert)
        old_idx = existing[1]
        lines.pop(old_idx)
        if old_idx < insert_idx:
            insert_idx -= 1

    lines.insert(insert_idx, new_line)
    atomic_write(lines)
    invalidate_dashboard_cache(display_ticker)
    res_path = write_resolution_cache(display_ticker, section, meta)

    print(f"✓ Added to watchlist.md  ({section}, line {insert_idx + 1})")
    print(f"  Backup: {backup_path.relative_to(PROJECT_ROOT)}")
    print(f"  Dashboard cache invalidated for {display_ticker}")
    if section == "crypto":
        bp = json.loads(res_path.read_text()).get("binance_pair")
        cg = json.loads(res_path.read_text()).get("cg_id")
        print(f"  Resolution cached: cg_id={cg}, binance_pair={bp or '(not listed — CG OHLC fallback)'}")
    print(f"  Refresh dashboard: python3 .claude/skills/dashboard/dashboard.py")
    return 0


def cmd_remove(args):
    raw_ticker = args.ticker.strip().upper()
    if not args.reason:
        print("❌ --reason required (per doctrine: never delete history without a reason).", file=sys.stderr)
        return 2

    # Try variants if classify gives klse
    candidates = [raw_ticker]
    if raw_ticker.isdigit() and len(raw_ticker) <= 4:
        candidates.append(f"{raw_ticker.zfill(4)}.KL")
    if not raw_ticker.endswith(".KL") and classify(raw_ticker) == "klse":
        candidates.append(f"{raw_ticker}.KL")

    existing = None
    for c in candidates:
        existing = find_existing(c)
        if existing:
            raw_ticker = c
            break

    if not existing:
        print(f"❌ '{raw_ticker}' not found in any active watchlist section.", file=sys.stderr)
        return 1

    sec, idx, line, thesis = existing
    if sec == "removed":
        print(f"⚠ {raw_ticker} is already in Removed/retired:", file=sys.stderr)
        print(f"    {line.strip()}", file=sys.stderr)
        return 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_removed_line = f"- `{raw_ticker}` — {thesis} (removed {today}: {args.reason})"

    print(f"Will remove from '{sec}' section:")
    print(f"  {line.strip()}")
    print()
    print(f"Will append to 'Removed / retired':")
    print(f"  {new_removed_line}")
    print()

    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0

    lines = read_watchlist()
    backup_path = backup_watchlist()

    # Pop the active line
    lines.pop(idx)

    # Find Removed section and append
    rs, re_ = find_section_bounds(lines, "removed")
    if rs is None:
        # Append the section + line at EOF
        lines.append("")
        lines.append("## Removed / retired")
        lines.append("_Move tickers here when they stop earning their watchlist slot, with a one-line reason. Don't delete history — calibration depends on it._")
        lines.append("")
        lines.append(new_removed_line)
    else:
        # Insert after the last non-blank line of the Removed section
        insert_idx = re_
        for j in range(re_ - 1, rs, -1):
            if lines[j].strip():
                insert_idx = j + 1
                break
        lines.insert(insert_idx, new_removed_line)

    atomic_write(lines)
    invalidate_dashboard_cache(raw_ticker)
    remove_resolution_cache(raw_ticker)

    print(f"✓ Moved {raw_ticker} to Removed / retired")
    print(f"  Backup: {backup_path.relative_to(PROJECT_ROOT)}")
    return 0


def cmd_update(args):
    raw_ticker = args.ticker.strip().upper()
    if not args.thesis:
        print("❌ --thesis required.", file=sys.stderr)
        return 2

    # Try variants
    candidates = [raw_ticker]
    if raw_ticker.isdigit() and len(raw_ticker) <= 4:
        candidates.append(f"{raw_ticker.zfill(4)}.KL")
    existing = None
    for c in candidates:
        existing = find_existing(c)
        if existing and existing[0] != "removed":
            raw_ticker = c
            break

    if not existing or existing[0] == "removed":
        print(f"❌ '{raw_ticker}' not in any active watchlist section.", file=sys.stderr)
        return 1

    sec, idx, line, thesis = existing
    new_line = f"- `{raw_ticker}` — {args.thesis}"

    print(f"In '{sec}' section, line {idx+1}:")
    print(f"  OLD: {line.strip()}")
    print(f"  NEW: {new_line}")
    print()

    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0

    lines = read_watchlist()
    backup_path = backup_watchlist()
    lines[idx] = new_line
    atomic_write(lines)
    invalidate_dashboard_cache(raw_ticker)

    print(f"✓ Updated {raw_ticker} thesis")
    print(f"  Backup: {backup_path.relative_to(PROJECT_ROOT)}")
    return 0


def cmd_resolve(args):
    """Backfill the resolution cache for every active watchlist entry.
    Useful right after adding this feature, or when you suspect the cache drifted.
    """
    import time
    lines = read_watchlist()
    sections = ["us", "klse", "crypto", "options"] if not args.section else [args.section]
    total = 0; skipped = 0; resolved = 0; failed = 0
    first_call = True
    for sec in sections:
        s, e = find_section_bounds(lines, sec)
        if s is None: continue
        entries = extract_tickers_in_section(lines, s, e)
        for ticker in sorted(entries.keys()):
            total += 1
            safe = ticker.upper().replace(".", "_").replace(":", "_")
            target = RESOLUTIONS_CACHE / f"{safe}.json"
            if target.is_file() and not args.force:
                skipped += 1
                continue
            # Politeness delay between actual fetches — CoinGecko free tier
            # rate-limits aggressively (~10-30 calls/min depending on endpoint).
            if not first_call:
                time.sleep(args.delay)
            first_call = False
            print(f"  resolving {ticker} ({sec})…", end=" ", flush=True)
            try:
                if sec == "us" or sec == "options":
                    meta, err = fetch_us_meta(ticker)
                elif sec == "klse":
                    meta, err = fetch_klse_meta(ticker)
                elif sec == "crypto":
                    meta, err = fetch_crypto_meta(ticker)
                else:
                    meta, err = None, f"unsupported section: {sec}"
                if not meta:
                    print(f"✗ {err}")
                    failed += 1
                    continue
                write_resolution_cache(ticker, sec, meta)
                bp = ""
                if sec == "crypto":
                    bp_val = json.loads(target.read_text()).get("binance_pair")
                    bp = f" [cg={meta.get('cg_id')}, binance={bp_val or 'none'}]"
                print(f"✓{bp}")
                resolved += 1
            except Exception as ex:
                print(f"✗ {type(ex).__name__}: {ex}")
                failed += 1
    print(f"\n  Total: {total} entries · resolved: {resolved} · skipped (already cached): {skipped} · failed: {failed}")
    print(f"  Cache: {RESOLUTIONS_CACHE.relative_to(PROJECT_ROOT)}")
    return 0 if failed == 0 else 1


def cmd_list(args):
    lines = read_watchlist()
    sections_to_show = ["us", "klse", "crypto", "options"]
    if args.include_removed:
        sections_to_show.append("removed")
    total = 0
    for sec in sections_to_show:
        s, e = find_section_bounds(lines, sec)
        if s is None:
            continue
        entries = extract_tickers_in_section(lines, s, e)
        if not entries:
            continue
        title, _ = SECTION_HEADERS[sec]
        print(f"\n{title}  ({len(entries)})")
        print("─" * len(title))
        for ticker in sorted(entries.keys()):
            _, line, thesis = entries[ticker]
            print(f"  {ticker:12}  {thesis[:90]}")
            total += 1
    print(f"\nTotal: {total} active entries")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Watchlist CLI — add/remove/update/list")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="Add a ticker (auto-classify + auto-thesis)")
    pa.add_argument("ticker", help="Ticker symbol or Bursa code")
    pa.add_argument("--thesis", default=None, help="Override auto-generated thesis")
    pa.add_argument("--section", choices=["us", "klse", "crypto", "options"], help="Force section (skip auto-classify)")
    pa.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    pa.add_argument("--allow-unresolved", action="store_true", help="Add even if data source can't resolve the ticker")
    pa.set_defaults(func=cmd_add)

    pr = sub.add_parser("remove", help="Move a ticker to Removed/retired with reason")
    pr.add_argument("ticker", help="Ticker symbol")
    pr.add_argument("--reason", "-r", required=True, help="One-line reason for removal (doctrine: required)")
    pr.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    pr.set_defaults(func=cmd_remove)

    pu = sub.add_parser("update", help="Update thesis for an existing ticker")
    pu.add_argument("ticker", help="Ticker symbol")
    pu.add_argument("--thesis", required=True, help="New thesis line")
    pu.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    pu.set_defaults(func=cmd_update)

    pl = sub.add_parser("list", help="Show watchlist contents")
    pl.add_argument("--include-removed", action="store_true", help="Also show Removed/retired section")
    pl.set_defaults(func=cmd_list)

    prv = sub.add_parser("resolve", help="Backfill resolution cache (cg_id, binance_pair, etc.) for existing tickers — dashboard reads this on build")
    prv.add_argument("--section", choices=["us", "klse", "crypto", "options"], help="Only resolve one section")
    prv.add_argument("--force", action="store_true", help="Re-resolve even tickers that already have a cached entry")
    prv.add_argument("--delay", type=float, default=2.5, help="Seconds between data-source calls (default 2.5; raise if you hit rate limits)")
    prv.set_defaults(func=cmd_resolve)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
