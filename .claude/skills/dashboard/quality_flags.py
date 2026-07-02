#!/usr/bin/env python3
"""
quality_flags.py — structural-quality risk flags for watchlist names.

Pure classifier over fields the dashboard already fetches (yfinance .info via
fetch_yfinance_ticker, CoinGecko markets via fetch_crypto_markets). Answers
"what kind of thing am I holding" independent of technical setup quality — a
name can be P1_READY (clean pullback) and still be a $0.17 penny stock with
50% of its float sold short. GPUS passed the entire pipeline with zero
warnings before this module existed (2026-07-02 audit: price $0.17, MC $53M,
short 49.97% of float, beta 2.59, 0 analysts).

Warn-loudly-never-block: this module only classifies. Callers (wl.py add,
dashboard row chips, Risk Simulator) decide what to do with the flags.
Nothing here blocks a trade — doctrine §1 says the operator decides.

Thresholds below are operator-tunable constants; no downstream code depends
on the exact numbers, so adjust freely.
"""

# ── Thresholds (tune freely) ────────────────────────────────────────────
PENNY_USD = 5.0
PENNY_MYR = 0.20
LOW_MC_USD = 300_000_000
ILLIQUID_USD_VOL = 5_000_000
HIGH_SHORT_PCT = 0.20
HIGH_BETA = 2.5
LOW_MC_RANK = 100
THIN_VOLUME_PCT = 0.02
PD_PRICE_SPIKE_30D_PCT = 50.0
PD_PRICE_SPIKE_5D_PCT = 20.0
PD_VOL_RATIO = 2.0

# key -> (icon, short label, tooltip)
FLAG_LABELS = {
    "PENNY": ("🪙", "Penny stock",
              "Price below the penny threshold — wide spreads, thin float, easy to manipulate."),
    "LOW_MC": ("🐜", "Low market cap",
               "Market cap below the small-cap floor — high volatility, thin analyst/media coverage."),
    "ILLIQUID": ("🏜️", "Illiquid",
                 "Average dollar volume is thin — slippage risk on entry/exit, hard to size meaningfully."),
    "HIGH_SHORT": ("🎯", "High short interest",
                   "A large share of the float is sold short — squeeze risk cuts both ways."),
    "HIGH_BETA": ("🎢", "High beta",
                  "Historically moves much more than the market — size accordingly."),
    "NO_COVERAGE": ("👻", "No analyst coverage",
                    "Zero sell-side analysts — less independent scrutiny of the numbers."),
    "LOW_MC_RANK": ("🐜", "Low cap-rank",
                    "Outside the top market-cap-ranked coins — thinner liquidity, more manipulable."),
    "THIN_VOLUME": ("🏜️", "Thin volume",
                    "24h volume is a small fraction of market cap — illiquid for the size implied by MC."),
    "PUMP_DUMP_RISK": ("🚩", "Pump-and-dump pattern",
                       "Price + volume spike, extreme bullish retail sentiment, and thin structural "
                       "quality — the classic setup shape. Not proof, but worth a hard look."),
}


def equity_flags(row):
    """row: dict with price, market_cap, avg_vol_30d, short_pct_float, beta,
    analyst_count, currency (optional, default USD) — the shape
    fetch_yfinance_ticker already returns. Returns list[str] flag keys,
    in FLAG_LABELS order (stable for display)."""
    flags = []
    price = row.get("price")
    mc = row.get("market_cap")
    avg_vol = row.get("avg_vol_30d")
    currency = (row.get("currency") or "USD").upper()

    if price is not None:
        threshold = PENNY_MYR if currency == "MYR" else PENNY_USD
        if price < threshold:
            flags.append("PENNY")

    if mc is not None and mc < LOW_MC_USD:
        flags.append("LOW_MC")

    if price is not None and avg_vol is not None:
        if (price * avg_vol) < ILLIQUID_USD_VOL:
            flags.append("ILLIQUID")

    short_pct = row.get("short_pct_float")
    if short_pct is not None and short_pct > HIGH_SHORT_PCT:
        flags.append("HIGH_SHORT")

    beta = row.get("beta")
    if beta is not None and beta > HIGH_BETA:
        flags.append("HIGH_BETA")

    # yfinance omits numberOfAnalystOpinions entirely (None) for names with zero
    # coverage — it's not just an explicit 0. Gate on price being present so an
    # entirely-failed fetch (every field None) doesn't spuriously flag this alone.
    if price is not None and row.get("analyst_count") in (0, None):
        flags.append("NO_COVERAGE")

    return flags


def crypto_flags(row):
    """row: dict with market_cap, market_cap_rank, volume — the shape
    fetch_crypto_markets already returns."""
    flags = []
    mc = row.get("market_cap")
    vol = row.get("volume")
    rank = row.get("market_cap_rank")

    # A totally-empty row (no CoinGecko match at all, e.g. the crypto-grid
    # stub-row fallback) means "no data", not "confirmed low rank" — don't flag.
    if mc is None and vol is None and rank is None:
        return flags

    if rank is None or rank > LOW_MC_RANK:
        flags.append("LOW_MC_RANK")

    if mc and vol is not None and mc > 0 and (vol / mc) < THIN_VOLUME_PCT:
        flags.append("THIN_VOLUME")

    return flags


def pump_dump_risk(structural_flags, chg_30d=None, chg_5d=None, vol_ratio=None, sentiment_flag=None):
    """Composite: fires only when ALL four ingredients line up — a price spike,
    a volume spike, EXTREME_BULL retail sentiment (contrarian_flag == 'FADE'),
    and thin structural quality. Requires vol_ratio to be known (None = no
    evidence = does not fire) so this stays conservative rather than noisy.
    """
    if vol_ratio is None:
        return False
    price_spike = (
        (chg_30d is not None and chg_30d > PD_PRICE_SPIKE_30D_PCT)
        or (chg_5d is not None and chg_5d > PD_PRICE_SPIKE_5D_PCT)
    )
    vol_spike = vol_ratio > PD_VOL_RATIO
    extreme_bull = sentiment_flag == "FADE"
    thin_quality = bool({"LOW_MC", "PENNY", "HIGH_SHORT", "LOW_MC_RANK"} & set(structural_flags))
    return price_spike and vol_spike and extreme_bull and thin_quality


def all_flags(row, asset_class="us", chg_30d=None, chg_5d=None, vol_ratio=None, sentiment_flag=None):
    """One-call entry point: classify + compute the pump/dump composite.

    chg_30d / chg_5d / vol_ratio default to reading off `row` (matching each
    asset class's actual field names) when not passed explicitly — for crypto,
    chg_7d is used as the short-window proxy (there's no computed 5d change).
    Returns list[str], with 'PUMP_DUMP_RISK' appended when it fires.
    """
    if asset_class == "crypto":
        base = crypto_flags(row)
        chg_30d = row.get("chg_30d") if chg_30d is None else chg_30d
        chg_5d = row.get("chg_7d") if chg_5d is None else chg_5d
    else:
        base = equity_flags(row)
        chg_30d = row.get("chg_30d_pct") if chg_30d is None else chg_30d
        chg_5d = row.get("chg_5d_pct") if chg_5d is None else chg_5d
        vol_ratio = row.get("vol_ratio") if vol_ratio is None else vol_ratio
    if pump_dump_risk(base, chg_30d=chg_30d, chg_5d=chg_5d, vol_ratio=vol_ratio, sentiment_flag=sentiment_flag):
        return base + ["PUMP_DUMP_RISK"]
    return base
