#!/usr/bin/env python3
"""
audit_glyph.py — Quality audit for the news-glyph LLM scorer.

Joins every cached LLM score back to its source headline and auto-flags the
failure modes the v2.0 watch-thread named:

  - FALSE-NONE     : relevance=none but ticker symbol / company name is in the
                     headline (LLM missed a relevant item → undercounts signal)
  - FALSE-PRIMARY  : relevance=primary but neither ticker nor company name
                     appears (LLM hallucinated focus → cross-attribution risk)
  - ROUNDUP?       : 3+ distinct tickers or a long comma list in the headline
                     AND relevance=primary (sector-roundup that should usually
                     be 'mention', diluting a single name's read)
  - NON-ASCII      : headline carries non-ASCII chars (KLSE Bahasa headlines —
                     verify the model handled them rather than defaulting none)
  - DIR-MISMATCH   : crude keyword polarity disagrees with the LLM score sign
                     (weak heuristic; only flags strong-word vs opposite-sign)

This is an offline audit over what's already on disk — no LLM calls, no fetches.

Usage:
  python3 .claude/skills/us-news/audit_glyph.py                  # all tickers
  python3 .claude/skills/us-news/audit_glyph.py --ticker KTOS --asset-class us
  python3 .claude/skills/us-news/audit_glyph.py --flagged-only   # only show flags
"""
import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import news_glyph as ng  # noqa: E402

# Reuse the curated map from hn-sentiment as ground-truth company names.
sys.path.insert(0, str(SCRIPT_DIR.parent / "hn-sentiment"))
try:
    from hn_sentiment import TICKER_NAMES  # noqa: E402
except Exception:
    TICKER_NAMES = {}

PROJECT_ROOT = ng.PROJECT_ROOT
LLM_SCORE_CACHE = ng.LLM_SCORE_CACHE

# Crypto slug → display name (the cache keys for crypto are CoinGecko slugs)
CRYPTO_NAMES = {
    "bitcoin": "Bitcoin", "ethereum": "Ethereum", "solana": "Solana",
    "binancecoin": "Binance", "ripple": "Ripple", "hedera-hashgraph": "Hedera",
    "hyperliquid": "Hyperliquid", "ethena": "Ethena", "ondo-finance": "Ondo",
}

# KLSE code → name (best-effort; klse cache also carries stock_name)
KLSE_NAMES = {}


def company_name_for(key, asset_class):
    key_u = key.upper()
    if asset_class == "crypto":
        return CRYPTO_NAMES.get(key.lower())
    if asset_class == "klse":
        return KLSE_NAMES.get(key_u)
    return TICKER_NAMES.get(key_u)


TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")


def _flags_for(key, asset_class, headline, rel, score, is_analyst=False):
    flags = []
    h = headline or ""
    h_low = h.lower()
    name = company_name_for(key, asset_class)
    name_in = bool(name) and name.lower() in h_low
    # ticker symbol appears as a word (US only — KLSE codes are numeric, crypto uses names)
    sym_in = False
    if asset_class == "us":
        sym_in = bool(re.search(rf"\b{re.escape(key.upper())}\b", h))

    appears = name_in or sym_in

    if rel == "none" and appears:
        flags.append("FALSE-NONE")
    # FALSE-PRIMARY only on *real news* headlines — analyst-rating items
    # ("Barclays reiterates Overweight") legitimately omit the company name
    # because they come from the ticker's own rating feed.
    if rel == "primary" and not appears and name is not None and asset_class == "us" and not is_analyst:
        flags.append("FALSE-PRIMARY?")

    # Roundup: many distinct uppercase tickers in the headline
    if rel == "primary" and asset_class == "us":
        caps = set(TICKER_RE.findall(h))
        # drop common non-ticker all-caps words
        caps -= {"A", "I", "THE", "CEO", "CFO", "IPO", "AI", "ETF", "USA", "US",
                 "Q1", "Q2", "Q3", "Q4", "FDA", "SEC", "GF", "YOU", "AND", "FOR"}
        if len(caps) >= 3:
            flags.append(f"ROUNDUP?({len(caps)}tk)")

    if not h.isascii():
        flags.append("NON-ASCII")

    # Direction mismatch (only flag strong keyword vs opposite-sign LLM score)
    kw = ng._keyword_score(h)
    if rel == "primary" and score is not None:
        if kw >= 0.25 and score <= -0.5:
            flags.append("DIR-MISMATCH(kw+/llm−)")
        elif kw <= -0.25 and score >= 0.5:
            flags.append("DIR-MISMATCH(kw−/llm+)")
    return flags


def audit_ticker(key, asset_class, flagged_only=False):
    if asset_class == "us":
        items = ng._load_us_items(key)
    elif asset_class == "klse":
        items = ng._load_klse_items(key)
    else:
        items = ng._load_crypto_items(key)

    rows = []
    for it in items:
        # Only items that actually carry an LLM score (score_source == llm)
        if it.get("score_source") != "llm":
            continue
        headline = it.get("headline", "")
        rel = it.get("llm_relevance", "?")
        score = it.get("sentiment_score")
        is_analyst = bool(it.get("is_analyst_action"))
        flags = _flags_for(key, asset_class, headline, rel, score, is_analyst=is_analyst)
        if flagged_only and not flags:
            continue
        rows.append((rel, score, flags, headline))
    return rows


def discover_tickers():
    """Map each score-cache file to an asset class by inspecting the watchlist."""
    out = []
    wl = ng.PROJECT_ROOT / "watchlist.md"
    klse_codes, crypto_slugs = set(), set(CRYPTO_NAMES.keys())
    if wl.is_file():
        for line in wl.read_text().splitlines():
            m = re.match(r"\s*-\s*`([^`]+)`", line)
            if not m:
                continue
            t = m.group(1).strip()
            if re.fullmatch(r"\d{4}", t) or t.endswith(".KL"):
                klse_codes.add(t.replace(".KL", ""))
    for p in sorted(LLM_SCORE_CACHE.glob("*.json")):
        stem = p.stem
        if stem.upper() in (c.upper() for c in klse_codes) or re.fullmatch(r"\d{4}", stem):
            out.append((stem, "klse"))
        elif stem.lower() in crypto_slugs:
            out.append((stem, "crypto"))
        else:
            out.append((stem, "us"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--asset-class", choices=["us", "klse", "crypto"])
    ap.add_argument("--flagged-only", action="store_true")
    args = ap.parse_args()

    if args.ticker:
        targets = [(args.ticker, args.asset_class or "us")]
    else:
        targets = discover_tickers()

    total_items = 0
    total_flags = 0
    flag_counts = {}
    by_rel = {"primary": 0, "mention": 0, "none": 0, "?": 0}

    for key, ac in targets:
        rows = audit_ticker(key, ac, flagged_only=args.flagged_only)
        if not rows:
            continue
        print(f"\n=== {key} ({ac}) — {len(rows)} scored item(s) ===")
        for rel, score, flags, headline in rows:
            total_items += 1
            by_rel[rel if rel in by_rel else "?"] = by_rel.get(rel, 0) + 1
            for f in flags:
                base = f.split("(")[0]
                flag_counts[base] = flag_counts.get(base, 0) + 1
                total_flags += 1
            flag_str = ("  ⚠ " + " ".join(flags)) if flags else ""
            sc = f"{score:+.2f}" if isinstance(score, (int, float)) else "  ?  "
            print(f"  [{rel:7}] {sc}  {headline[:90]}{flag_str}")

    print("\n" + "=" * 70)
    print(f"AUDIT SUMMARY: {total_items} LLM-scored items across {len(targets)} ticker(s)")
    print(f"  relevance split: primary={by_rel['primary']} · "
          f"mention={by_rel['mention']} · none={by_rel['none']}")
    if flag_counts:
        print(f"  flags raised ({total_flags} total):")
        for f, n in sorted(flag_counts.items(), key=lambda x: -x[1]):
            print(f"    {f:20} {n}")
    else:
        print("  no flags raised 🎉")


if __name__ == "__main__":
    main()
