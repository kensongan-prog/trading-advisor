#!/usr/bin/env python3
"""
hl_flow.py — On-chain flow data for Hyperliquid perpetuals via the public API.

Hyperliquid runs on its own L1; the orderbook AND every user's positions are
public on-chain. This is the unique informational advantage of HL: you can
watch what whales are doing live, which on CEXes is invisible.

Single-purpose CLI invoked by the `hyperliquid-flow` skill. No auth required;
api.hyperliquid.xyz is fully public. POST endpoint with JSON body.

Subcommands:
    assets        Snapshot of all (or top-N) HL perps: funding, OI, volume.
    asset         Deep-dive on one coin: mark, funding, OI, order-book imbalance.
    whale         Positions, P&L, recent fills for a given address.
    compare       HL funding vs Binance funding for the same coin (cross-venue signal).

Usage:
    python3 hl_flow.py assets --sort funding-abs --top 15
    python3 hl_flow.py asset --coin HYPE
    python3 hl_flow.py whale --address 0xdfc24b077bc1425ad1dea75bcb6f8158e10df303
    python3 hl_flow.py compare --coin BTC

Never falls back to LLM memory. If the API errors, prints explicit failure.
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone


HL_INFO = "https://api.hyperliquid.xyz/info"
BINANCE_FAPI = "https://fapi.binance.com"


def hl_post(body):
    """POST to /info with JSON body. Returns (data, error_str)."""
    req = urllib.request.Request(
        HL_INFO,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "trading-advisor/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            body_s = e.read().decode("utf-8")[:300]
        except Exception:
            body_s = ""
        return None, f"HTTP {e.code}: {e.reason} :: {body_s}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def binance_get(path, params=None):
    import urllib.parse
    url = BINANCE_FAPI + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def fmt_money(x, places=0):
    v = f(x)
    if abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"${v/1e3:.2f}k"
    return f"${v:,.{places}f}"


def hourly_funding_to_annualized(rate_per_hour):
    """HL funds every hour. Annualize: rate × 24 × 365 × 100."""
    return f(rate_per_hour) * 24 * 365 * 100


def funding_signal_hourly(rate_per_hour):
    """Translate HL per-hour funding into a regime read.

    Binance's 0.01%/8h ≈ 11% annual = neutral baseline. HL equivalent per hour:
       neutral baseline: ~0.0000125/hr (= 11%/yr)
       crowded long:     > +0.000025/hr (> 22%/yr)
       very crowded long > +0.00006/hr  (> 53%/yr)
       and mirror for short.
    """
    r = f(rate_per_hour)
    if r > 6e-5:
        return "VERY CROWDED LONG (flush risk)"
    if r > 2.5e-5:
        return "crowded long"
    if r < -6e-5:
        return "VERY CROWDED SHORT (squeeze fuel)"
    if r < -2.5e-5:
        return "crowded short"
    return "neutral"


def fetch_assets():
    """Returns (meta, ctxs, err) where meta has 'universe' list and ctxs is parallel list of contexts."""
    data, err = hl_post({"type": "metaAndAssetCtxs"})
    if err:
        return None, None, err
    if not isinstance(data, list) or len(data) < 2:
        return None, None, "unexpected response shape"
    return data[0], data[1], None


def cmd_assets(args):
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta, ctxs, err = fetch_assets()
    if err:
        print(f"FETCH FAILED: {err}")
        return 1

    universe = meta.get("universe", [])
    rows = []
    for u, c in zip(universe, ctxs):
        name = u.get("name", "?")
        mark = f(c.get("markPx"))
        prev = f(c.get("prevDayPx"))
        oi_tokens = f(c.get("openInterest"))
        oi_usd = oi_tokens * mark
        vol_24h = f(c.get("dayNtlVlm"))
        funding = f(c.get("funding"))
        chg_24h_pct = ((mark - prev) / prev * 100) if prev else 0
        rows.append({
            "name": name,
            "mark": mark,
            "chg24": chg_24h_pct,
            "oi_usd": oi_usd,
            "vol_24h": vol_24h,
            "funding": funding,
            "funding_ann": hourly_funding_to_annualized(funding),
            "max_lev": u.get("maxLeverage", 0),
        })

    # Sort.
    if args.sort == "funding":
        rows.sort(key=lambda r: r["funding_ann"], reverse=True)
    elif args.sort == "funding-abs":
        rows.sort(key=lambda r: abs(r["funding_ann"]), reverse=True)
    elif args.sort == "oi":
        rows.sort(key=lambda r: r["oi_usd"], reverse=True)
    elif args.sort == "volume":
        rows.sort(key=lambda r: r["vol_24h"], reverse=True)
    elif args.sort == "change":
        rows.sort(key=lambda r: r["chg24"], reverse=True)
    elif args.sort == "change-abs":
        rows.sort(key=lambda r: abs(r["chg24"]), reverse=True)

    rows = rows[: args.top]

    print(f"HYPERLIQUID PERPS — {len(universe)} assets indexed")
    print(f"Source:        api.hyperliquid.xyz (public, no auth)")
    print(f"Fetched (UTC): {fetched}")
    print(f"Sort:          {args.sort}   showing top {len(rows)}")
    print()
    print(f"{'coin':10}  {'mark':>12}  {'24h %':>8}  {'OI ($)':>12}  {'24h vol':>14}  {'fund/h':>11}  {'fund ann%':>10}  {'regime':<32}  {'lev':>4}")
    for r in rows:
        print(f"{r['name']:10}  {r['mark']:>12.4f}  {r['chg24']:>+7.2f}%  {fmt_money(r['oi_usd']):>12}  {fmt_money(r['vol_24h']):>14}  {r['funding']:>+11.6f}  {r['funding_ann']:>+9.2f}%  {funding_signal_hourly(r['funding']):<32}  {r['max_lev']:>3}x")

    return 0


def cmd_asset(args):
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta, ctxs, err = fetch_assets()
    if err:
        print(f"FETCH FAILED: {err}")
        return 1

    universe = meta.get("universe", [])
    coin = args.coin.upper().strip()
    idx = next((i for i, u in enumerate(universe) if u.get("name", "").upper() == coin), None)
    if idx is None:
        print(f"COIN NOT FOUND on Hyperliquid: {coin}")
        print(f"Available examples: {[u['name'] for u in universe[:8]]} ...")
        return 1

    u = universe[idx]
    c = ctxs[idx]
    mark = f(c.get("markPx"))
    oi_tokens = f(c.get("openInterest"))
    oi_usd = oi_tokens * mark
    funding = f(c.get("funding"))
    funding_ann = hourly_funding_to_annualized(funding)
    prev = f(c.get("prevDayPx"))
    chg_24h = ((mark - prev) / prev * 100) if prev else 0
    premium = f(c.get("premium"))

    print(f"HYPERLIQUID — {coin}")
    print(f"Source:        api.hyperliquid.xyz")
    print(f"Fetched (UTC): {fetched}")
    print(f"Max leverage:  {u.get('maxLeverage')}x")
    print()
    print("PRICE & FUNDING")
    print(f"  Mark price:           {mark}")
    print(f"  Oracle price:         {c.get('oraclePx')}")
    print(f"  Mid price:            {c.get('midPx')}")
    print(f"  Prev day close:       {prev}")
    print(f"  24h change:           {chg_24h:+.2f}%")
    print(f"  Premium vs oracle:    {premium * 100:+.4f}%")
    print(f"  Funding (per hour):   {funding:+.7f}")
    print(f"  Funding (annualized): {funding_ann:+.2f}%")
    print(f"  Regime read:          {funding_signal_hourly(funding)}")
    print()
    print("OPEN INTEREST & VOLUME")
    print(f"  OI (tokens):          {oi_tokens:,.4f}")
    print(f"  OI (USD):             {fmt_money(oi_usd)}")
    print(f"  24h notional vol:     {fmt_money(f(c.get('dayNtlVlm')))}")
    print(f"  24h base vol:         {f(c.get('dayBaseVlm')):,.2f}")
    print()

    # Order book imbalance.
    book, err = hl_post({"type": "l2Book", "coin": coin})
    if err:
        print(f"warning: l2Book failed: {err}", file=sys.stderr)
    else:
        levels = book.get("levels", [])
        if len(levels) >= 2:
            bids = levels[0][: args.book_depth]
            asks = levels[1][: args.book_depth]
            bid_sz = sum(f(b.get("sz")) for b in bids)
            ask_sz = sum(f(a.get("sz")) for a in asks)
            tot = bid_sz + ask_sz
            imb = ((bid_sz - ask_sz) / tot * 100) if tot else 0
            print(f"ORDER BOOK IMBALANCE (top {args.book_depth} levels)")
            print(f"  Bid size (tokens):    {bid_sz:,.4f}")
            print(f"  Ask size (tokens):    {ask_sz:,.4f}")
            print(f"  Imbalance:            {imb:+.2f}%   ({'buy-heavy' if imb > 5 else 'sell-heavy' if imb < -5 else 'balanced'})")
            top_bid = f(bids[0].get("px")) if bids else 0
            top_ask = f(asks[0].get("px")) if asks else 0
            if top_bid and top_ask:
                spread = top_ask - top_bid
                spread_bps = (spread / top_bid) * 10000
                print(f"  Top bid / ask:        {top_bid} / {top_ask}   spread: {spread_bps:.2f} bps")
    return 0


def cmd_whale(args):
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    addr = args.address.strip()

    # Clearinghouse state (positions + margin).
    state, err = hl_post({"type": "clearinghouseState", "user": addr})
    if err:
        print(f"FETCH FAILED (clearinghouseState): {err}")
        return 1

    ms = state.get("marginSummary") or {}
    av = f(ms.get("accountValue"))
    ntl = f(ms.get("totalNtlPos"))
    raw_usd = f(ms.get("totalRawUsd"))
    margin_used = f(ms.get("totalMarginUsed"))
    positions = state.get("assetPositions") or []

    print(f"HYPERLIQUID WHALE WATCH")
    print(f"Address:       {addr}")
    print(f"Source:        api.hyperliquid.xyz")
    print(f"Fetched (UTC): {fetched}")
    print()
    print("ACCOUNT")
    print(f"  Account value:        ${av:,.2f}")
    print(f"  Total notional pos:   ${ntl:,.2f}")
    print(f"  Raw USD balance:      ${raw_usd:,.2f}")
    print(f"  Margin used:          ${margin_used:,.2f}")
    if av > 0:
        print(f"  Effective leverage:   {ntl / av:.2f}x")
    print()

    if not positions:
        print("OPEN POSITIONS: none")
    else:
        print(f"OPEN POSITIONS ({len(positions)})")
        print(f"{'coin':10}  {'side':6}  {'size':>14}  {'entry':>10}  {'lev':>5}  {'mark':>10}  {'uPnL ($)':>14}  {'liq':>10}")
        for ap in positions:
            p = ap.get("position", {})
            sz = f(p.get("szi"))
            side = "LONG" if sz > 0 else "SHORT"
            lev = p.get("leverage", {})
            lev_x = lev.get("value", "—") if isinstance(lev, dict) else lev
            print(f"{p.get('coin', '?'):10}  {side:6}  {sz:>14.4f}  {p.get('entryPx', '—'):>10}  {str(lev_x):>4}x  {p.get('markPx') or '—':>10}  ${f(p.get('unrealizedPnl')):>+13,.0f}  {p.get('liquidationPx') or '—':>10}")
    print()

    # Recent fills.
    fills, err = hl_post({"type": "userFills", "user": addr})
    if err:
        print(f"warning: userFills failed: {err}", file=sys.stderr)
        fills = []

    if fills:
        # Most-recent first; show top N.
        fills = sorted(fills, key=lambda x: x.get("time", 0), reverse=True)[: args.fills]
        print(f"RECENT FILLS (last {len(fills)})")
        print(f"{'time (UTC)':22}  {'coin':8}  {'side':6}  {'px':>12}  {'sz':>12}  {'$ notional':>14}  {'fee':>10}  {'closed PnL':>14}")
        for fi in fills:
            t = datetime.fromtimestamp(fi.get("time", 0) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            side = "BUY" if fi.get("side") == "B" else "SELL"
            px = f(fi.get("px"))
            sz = f(fi.get("sz"))
            ntl = px * sz
            print(f"{t:22}  {fi.get('coin', '?'):8}  {side:6}  {px:>12.4f}  {sz:>12.4f}  ${ntl:>13,.0f}  ${f(fi.get('fee')):>8,.2f}  ${f(fi.get('closedPnl')):>+13,.0f}")
    else:
        print("RECENT FILLS: none returned (account may be inactive or fills truncated)")
    return 0


def cmd_compare(args):
    fetched = datetime.now(timezone.utc).isoformat(timespec="seconds")
    coin = args.coin.upper().strip()

    # HL side.
    meta, ctxs, err = fetch_assets()
    if err:
        print(f"FETCH FAILED (HL): {err}")
        return 1
    idx = next((i for i, u in enumerate(meta.get("universe", [])) if u.get("name", "").upper() == coin), None)
    if idx is None:
        print(f"COIN NOT FOUND on Hyperliquid: {coin}")
        return 1
    hl_ctx = ctxs[idx]
    hl_mark = f(hl_ctx.get("markPx"))
    hl_funding = f(hl_ctx.get("funding"))
    hl_ann = hourly_funding_to_annualized(hl_funding)
    hl_oi_usd = f(hl_ctx.get("openInterest")) * hl_mark

    # Binance side. Symbol = COIN + USDT (works for majors; some HL-only coins won't exist).
    sym = coin + "USDT"
    bnb_pi, err = binance_get("/fapi/v1/premiumIndex", {"symbol": sym})
    bnb_oi, _ = binance_get("/fapi/v1/openInterest", {"symbol": sym})
    if err or not bnb_pi:
        print(f"NOTE: {sym} not found on Binance — HL-native coin, no cross-venue comparison possible.")
        bnb_mark = bnb_funding_8h = bnb_ann = bnb_oi_usd = None
    else:
        bnb_mark = f(bnb_pi.get("markPrice"))
        bnb_funding_8h = f(bnb_pi.get("lastFundingRate"))
        bnb_ann = bnb_funding_8h * 3 * 365 * 100  # Binance is per-8h, 3 funds/day.
        bnb_oi_usd = f(bnb_oi.get("openInterest")) * bnb_mark if bnb_oi else None

    print(f"FUNDING & POSITIONING COMPARE — {coin}")
    print(f"Source:        Hyperliquid + Binance Futures (public)")
    print(f"Fetched (UTC): {fetched}")
    print()
    print(f"{'venue':14}  {'mark':>14}  {'funding raw':>14}  {'cadence':>10}  {'annualized':>11}  {'regime':<32}  {'OI (USD)':>14}")
    print(f"{'Hyperliquid':14}  {hl_mark:>14.4f}  {hl_funding:>+14.7f}  {'per-hour':>10}  {hl_ann:>+10.2f}%  {funding_signal_hourly(hl_funding):<32}  {fmt_money(hl_oi_usd):>14}")
    if bnb_mark is not None:
        # Binance regime label using 8h thresholds (different scale).
        def binance_regime(r):
            if r > 0.0005: return "VERY CROWDED LONG (flush risk)"
            if r > 0.0002: return "crowded long"
            if r < -0.0005: return "VERY CROWDED SHORT (squeeze fuel)"
            if r < -0.0002: return "crowded short"
            return "neutral"
        print(f"{'Binance':14}  {bnb_mark:>14.4f}  {bnb_funding_8h:>+14.7f}  {'per-8h':>10}  {bnb_ann:>+10.2f}%  {binance_regime(bnb_funding_8h):<32}  {fmt_money(bnb_oi_usd or 0):>14}")
        print()
        # Divergence read.
        div = hl_ann - bnb_ann
        print("CROSS-VENUE DIVERGENCE (annualized funding spread)")
        print(f"  HL ann − Binance ann: {div:+.2f} pp")
        if abs(div) < 10:
            print("  Read: aligned across venues — no positioning split.")
        elif div > 20:
            print("  Read: HL longs paying materially more than Binance → HL bias more bullish / more leverage stacked.")
        elif div < -20:
            print("  Read: Binance longs paying materially more than HL → Binance crowd bias more bullish.")
        elif div > 0:
            print("  Read: mild HL > Binance positioning lean.")
        else:
            print("  Read: mild Binance > HL positioning lean.")
        # Price divergence flag.
        price_div_bps = ((hl_mark - bnb_mark) / bnb_mark) * 10000
        print(f"  Mark price spread:    {price_div_bps:+.2f} bps")
        if abs(price_div_bps) > 50:
            print("  ⚠ Material price divergence — verify before trading; one venue may be lagging.")

    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("assets", help="Snapshot of all HL perps")
    pa.add_argument("--sort", default="oi",
                    choices=["funding", "funding-abs", "oi", "volume", "change", "change-abs"])
    pa.add_argument("--top", type=int, default=20)
    pa.set_defaults(func=cmd_assets)

    pas = sub.add_parser("asset", help="Single-coin deep-dive")
    pas.add_argument("--coin", required=True)
    pas.add_argument("--book-depth", type=int, default=10)
    pas.set_defaults(func=cmd_asset)

    pw = sub.add_parser("whale", help="Address positions + P&L + recent fills")
    pw.add_argument("--address", required=True)
    pw.add_argument("--fills", type=int, default=10)
    pw.set_defaults(func=cmd_whale)

    pc = sub.add_parser("compare", help="HL vs Binance funding for one coin")
    pc.add_argument("--coin", required=True)
    pc.set_defaults(func=cmd_compare)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
