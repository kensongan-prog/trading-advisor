#!/usr/bin/env python3
"""us-screener — discovery layer for US equities.

Runs the 8 P1 technical gates (same as us_status() in dashboard.py) across a
curated ~180-name universe and layers Buffett-style quality+value filters on
top. Output: ranked candidate list of names that pass P1 AND meet quality/value
thresholds, excluding anything already on the watchlist.

Caches:
  .claude/cache/screener/technicals.json  — per-ticker price+indicators (24h TTL)
  .claude/cache/screener/fundamentals.json — per-ticker quality+value (7d TTL)
  .claude/cache/screener/candidates.json  — final ranked output

Usage:
  python3 .claude/skills/us-screener/screener.py                # run full scan + show output
  python3 .claude/skills/us-screener/screener.py --refresh      # force re-fetch all
  python3 .claude/skills/us-screener/screener.py --tech-only    # skip fundamentals
  python3 .claude/skills/us-screener/screener.py --show         # just print last cached output
"""
from __future__ import annotations
import argparse, json, sys, time, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
WATCHLIST = PROJECT_ROOT / "watchlist.md"
UNIVERSE  = SCRIPT_DIR / "universe.json"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "screener"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Sibling skill clients
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "skills" / "twelve-data"))
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "skills" / "fmp"))
import twelve_data_client as td  # noqa: E402
import fmp_client as fmp         # noqa: E402

TECH_CACHE = CACHE_DIR / "technicals.json"
FUND_CACHE = CACHE_DIR / "fundamentals.json"
OUT_CACHE  = CACHE_DIR / "candidates.json"

# Cache TTLs
TECH_TTL_HOURS = 24
FUND_TTL_HOURS = 24 * 7
COOLDOWN_FILE = CACHE_DIR / ".yfinance_cooldown_until"
COOLDOWN_MINUTES_ON_FAIL = 45   # if yfinance bulk fetch dies, back off for 45 min

# ── Universe + watchlist loading ─────────────────────────────────────────
def load_universe(include_watchlist=True):
    """E3: by default, union the watchlist names into the screener universe so
    watchlist tickers always get tracked in the discovery scan (freshness parity).
    Watchlist-added names are tagged sector='_watchlist' if not already in universe.json."""
    j = json.loads(UNIVERSE.read_text())
    seen = set()
    out = []
    for sector, tickers in j["sectors"].items():
        for t in tickers:
            tk = t.upper()
            if tk in seen: continue
            seen.add(tk)
            out.append((tk, sector))
    if include_watchlist:
        for tk in watchlist_us_tickers():
            if tk in seen: continue
            seen.add(tk)
            out.append((tk, "_watchlist"))  # sector marker so they're distinguishable
    return out

def watchlist_us_tickers():
    if not WATCHLIST.exists(): return set()
    out = set()
    in_us = False
    import re
    for line in WATCHLIST.read_text().splitlines():
        s = line.strip()
        if s.startswith("##"):
            in_us = s.lower().startswith("## equities")
            continue
        if in_us:
            m = re.match(r"-\s*`([^`]+)`", s)
            if m: out.add(m.group(1).upper())
    return out

# ── Cache I/O ────────────────────────────────────────────────────────────
def load_cache(path):
    if not path.is_file(): return {}
    try: return json.loads(path.read_text())
    except Exception: return {}

def save_cache(path, data):
    path.write_text(json.dumps(data, indent=2, default=str))

def is_stale(entry, ttl_hours):
    ts = (entry or {}).get("_fetched_at")
    if not ts: return True
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
        return age > ttl_hours
    except Exception:
        return True

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Cooldown + stale-fallback (mirrors sector-rotation pattern) ───────────
def in_cooldown():
    if not COOLDOWN_FILE.is_file(): return False
    try:
        until = datetime.fromisoformat(COOLDOWN_FILE.read_text().strip())
        return datetime.now(timezone.utc) < until
    except Exception:
        return False

def set_cooldown(minutes=COOLDOWN_MINUTES_ON_FAIL):
    from datetime import timedelta
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    COOLDOWN_FILE.write_text(until.isoformat(timespec="seconds"))
    return until

def clear_cooldown():
    if COOLDOWN_FILE.is_file():
        try: COOLDOWN_FILE.unlink()
        except Exception: pass

def cooldown_remaining_minutes():
    if not COOLDOWN_FILE.is_file(): return 0
    try:
        until = datetime.fromisoformat(COOLDOWN_FILE.read_text().strip())
        return max(0, (until - datetime.now(timezone.utc)).total_seconds() / 60)
    except Exception:
        return 0

def stale_output_with_warning(reason):
    """Return the last good candidates.json marked as stale."""
    if not OUT_CACHE.is_file(): return None
    try:
        data = json.loads(OUT_CACHE.read_text())
        data["_stale"] = True
        data["_stale_reason"] = reason
        return data
    except Exception:
        return None

# ── Tier classification (HOT/WARM/COLD for differential refresh) ──────────
# Tiering reduces daily TD calls by refreshing high-signal names more often
# than clearly-failing ones. Tier is set based on prior-scan P1 gate pass count.

def classify_tier(prior_cache_entry):
    """Return 'hot' | 'warm' | 'cold' based on prior tech-cache entry."""
    if not prior_cache_entry: return "warm"  # unknown → check soon
    if prior_cache_entry.get("error"): return "warm"
    # Re-evaluate P1 gates on the cached data to count passes
    ok, _ = eval_p1_technical(prior_cache_entry)
    if ok == "pass": return "hot"
    # If RSI is in 30-55 range and trend OK, name is "almost passing" → warm
    rsi = prior_cache_entry.get("rsi14")
    p, s50, s200 = prior_cache_entry.get("price"), prior_cache_entry.get("sma50"), prior_cache_entry.get("sma200")
    if p and s50 and s200 and p > s50 > s200 and rsi is not None and 30 <= rsi <= 55:
        return "warm"
    return "cold"

TIER_TTL_HOURS = {"hot": 24, "warm": 72, "cold": 168}  # 1d / 3d / 7d


def tier_is_stale(entry, tier):
    ts = (entry or {}).get("_fetched_at")
    if not ts: return True
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
        return age > TIER_TTL_HOURS[tier]
    except Exception:
        return True


# ── Technical fetch (Twelve Data per-ticker, tiered) ─────────────────────
def _compute_indicators_from_td_bars(bars):
    """Bars = list of {datetime, open, high, low, close, volume} oldest→newest from TD.
    Returns the same indicator dict shape as the old fetch_technicals_bulk output."""
    import pandas as pd
    if not bars:
        return {"error": "no bars"}
    df = pd.DataFrame(bars)
    last = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2]) if len(df) >= 2 else last
    chg  = (last/prev - 1) * 100 if prev else 0
    d = df["close"].diff()
    g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = l.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi_s = 100 - 100/(1 + ag/al)
    rsi = float(rsi_s.iloc[-1]) if not rsi_s.empty else None
    s20s = df["close"].rolling(20).mean()
    s50s = df["close"].rolling(50).mean()
    s20  = float(s20s.iloc[-1])  if len(df) >= 20  else None
    s50  = float(s50s.iloc[-1])  if len(df) >= 50  else None
    s200 = float(df["close"].rolling(200).mean().iloc[-1]) if len(df) >= 200 else None
    slope = None
    if len(df) >= 55 and s50:
        try:
            s50_5 = float(s50s.iloc[-6])
            if s50_5: slope = (s50/s50_5 - 1) * 100
        except Exception: pass
    vol_ratio = None
    if len(df) >= 30:
        try:
            a30 = float(df["volume"].tail(30).mean()); r5 = float(df["volume"].tail(5).mean())
            if a30 > 0: vol_ratio = r5/a30
        except Exception: pass
    atr = None
    try:
        tr = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift(1)).abs(),
                        (df["low"]-df["close"].shift(1)).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None
    except Exception: pass
    return {
        "price": last, "change_pct": chg, "rsi14": rsi,
        "sma20": s20, "sma50": s50, "sma200": s200,
        "sma50_slope_pct": slope, "vol_ratio": vol_ratio, "atr14": atr,
        "atr_pct": (atr/last*100) if (atr and last) else None,
    }


def fetch_technicals_bulk(tickers, force=False):
    """Tiered Twelve Data fetch. Returns (cache, n_fetched, error).
    Only refreshes names whose tier TTL has expired (HOT 24h / WARM 72h / COLD 7d).
    Cooldown-aware: if TD recently failed, falls back to existing cache."""
    cache = load_cache(TECH_CACHE)
    # Classify each ticker against the prior cache
    tiered = []
    for t in tickers:
        prior = cache.get(t, {})
        tier = classify_tier(prior)
        tiered.append((t, tier, prior))

    if force:
        to_fetch = [(t, tier) for t, tier, _ in tiered]
    else:
        to_fetch = [(t, tier) for t, tier, prior in tiered if tier_is_stale(prior, tier)]

    if not to_fetch:
        return cache, 0, None

    # Cooldown short-circuit
    if in_cooldown() and not force:
        rem = cooldown_remaining_minutes()
        msg = f"TD cooldown active ({rem:.0f} min remaining); skipping fetch"
        print(f"  [tech] {msg}", file=sys.stderr)
        return cache, 0, msg

    # Configuration check
    if not td.is_configured():
        msg = "TWELVE_DATA_API_KEY not set"
        return cache, 0, msg

    # Tier distribution log
    tier_counts = {"hot": 0, "warm": 0, "cold": 0}
    for _, tier in to_fetch: tier_counts[tier] += 1
    budget = td.budget_status()
    est_secs = int(len(to_fetch) * td.PACE_SECONDS)
    print(f"  [tech] fetching {len(to_fetch)} tickers via Twelve Data "
          f"(HOT {tier_counts['hot']} · WARM {tier_counts['warm']} · COLD {tier_counts['cold']}) "
          f"~{est_secs}s · TD budget {budget['used']}/{td.DAILY_CAP}", flush=True)

    # Proactive cooldown — if process is killed mid-fetch, future runs see it
    set_cooldown(minutes=COOLDOWN_MINUTES_ON_FAIL)
    fetched = 0
    fatal = None
    for i, (t, tier) in enumerate(to_fetch):
        bars, err = td.candle_ohlcv(t, outputsize=250)
        if err:
            cache[t] = {"error": err, "_fetched_at": now_iso(), "_tier": tier}
            # Stop on hard failures
            if "cap hit" in err or "API key" in err or "unauthorized" in err.lower():
                fatal = err
                print(f"  [tech] fatal ({i+1}/{len(to_fetch)}): {err}", file=sys.stderr)
                break
            continue
        ind = _compute_indicators_from_td_bars(bars)
        if "error" in ind:
            cache[t] = {**ind, "_fetched_at": now_iso(), "_tier": tier}
            continue
        cache[t] = {**ind, "_fetched_at": now_iso(), "_tier": tier}
        fetched += 1
        if (i + 1) % 20 == 0:
            save_cache(TECH_CACHE, cache)
            print(f"    …{i+1}/{len(to_fetch)} done", flush=True)
    save_cache(TECH_CACHE, cache)
    if fetched > 0 and not fatal:
        clear_cooldown()
    return cache, fetched, fatal


# ── Old yfinance bulk path (retained reference, no longer used) ──────────
def _fetch_technicals_bulk_yfinance_DEPRECATED(tickers, force=False):
    """Returns dict ticker → {price, rsi14, sma20, sma50, sma200, atr14, sma50_slope_pct,
    vol_ratio, change_pct}. Uses one yf.download() call for all, then per-ticker compute.

    Cooldown-aware: if a recent fetch failed catastrophically (XProtect kill / Yahoo
    ban), skip the bulk download entirely and let the caller fall back to the existing
    candidates.json with a stale flag.
    """
    cache = load_cache(TECH_CACHE)
    to_fetch = [t for t in tickers if force or is_stale(cache.get(t), TECH_TTL_HOURS)]
    if not to_fetch:
        return cache, 0, None  # third return: None = no error
    # Cooldown short-circuit
    if in_cooldown() and not force:
        rem = cooldown_remaining_minutes()
        msg = f"yfinance cooldown active ({rem:.0f} min remaining); skipping bulk fetch"
        print(f"  [tech] {msg}", file=sys.stderr)
        return cache, 0, msg
    print(f"  [tech] bulk-fetching {len(to_fetch)} tickers via yfinance.download (~30-60s)…", flush=True)
    try:
        import yfinance as yf, pandas as pd
    except ImportError:
        print("  [tech] ERROR: yfinance / pandas not installed", file=sys.stderr)
        return cache, 0, "yfinance not installed"

    # Bulk download — single HTTP-batched call. Set cooldown PROACTIVELY so that if
    # XProtect kills the process mid-fetch, the next run sees a cooldown marker and
    # doesn't immediately try again (which would also get killed). On success, clear.
    set_cooldown(minutes=COOLDOWN_MINUTES_ON_FAIL)
    try:
        data = yf.download(to_fetch, period="1y", group_by="ticker", progress=False, threads=True, auto_adjust=True)
    except Exception as e:
        msg = f"bulk download error: {e}"
        print(f"  [tech] {msg}", file=sys.stderr)
        return cache, 0, msg
    # If download returned no usable data at all, treat as failure
    if data is None or (hasattr(data, 'empty') and data.empty):
        return cache, 0, "yfinance returned empty data"

    fetched = 0
    for t in to_fetch:
        try:
            # yf returns either a flat DF (1 ticker) or MultiIndex (>1)
            if len(to_fetch) == 1:
                h = data
            else:
                h = data[t] if t in data.columns.get_level_values(0) else None
            if h is None or h.empty:
                cache[t] = {"error": "no history", "_fetched_at": now_iso()}
                continue
            h = h.dropna(subset=["Close"])
            if h.empty:
                cache[t] = {"error": "all NaN", "_fetched_at": now_iso()}
                continue
            last = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else last
            chg = (last/prev - 1) * 100 if prev else 0
            d = h["Close"].diff()
            g = d.clip(lower=0); l = -d.clip(upper=0)
            ag = g.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
            al = l.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
            rsi_s = 100 - 100/(1 + ag/al)
            rsi = float(rsi_s.iloc[-1]) if not rsi_s.empty else None
            s20s = h["Close"].rolling(20).mean()
            s50s = h["Close"].rolling(50).mean()
            s20  = float(s20s.iloc[-1])  if len(h) >= 20  else None
            s50  = float(s50s.iloc[-1])  if len(h) >= 50  else None
            s200 = float(h["Close"].rolling(200).mean().iloc[-1]) if len(h) >= 200 else None
            slope = None
            if len(h) >= 55 and s50:
                try:
                    s50_5 = float(s50s.iloc[-6])
                    if s50_5: slope = (s50/s50_5 - 1) * 100
                except Exception: pass
            vol_ratio = None
            if len(h) >= 30 and "Volume" in h.columns:
                try:
                    a30 = float(h["Volume"].tail(30).mean()); r5 = float(h["Volume"].tail(5).mean())
                    if a30 > 0: vol_ratio = r5/a30
                except Exception: pass
            atr = None
            try:
                tr = pd.concat([h["High"]-h["Low"], (h["High"]-h["Close"].shift(1)).abs(), (h["Low"]-h["Close"].shift(1)).abs()], axis=1).max(axis=1)
                atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) >= 14 else None
            except Exception: pass
            cache[t] = {
                "price": last, "change_pct": chg,
                "rsi14": rsi, "sma20": s20, "sma50": s50, "sma200": s200,
                "sma50_slope_pct": slope, "vol_ratio": vol_ratio, "atr14": atr,
                "atr_pct": (atr/last*100) if (atr and last) else None,
                "_fetched_at": now_iso(),
            }
            fetched += 1
        except Exception as e:
            cache[t] = {"error": str(e), "_fetched_at": now_iso()}
    save_cache(TECH_CACHE, cache)
    # Success — clear the proactive cooldown marker we set before the fetch
    if fetched > 0:
        clear_cooldown()
    return cache, fetched, None

# ── Fundamentals fetch (per-ticker, slower) ──────────────────────────────
def fetch_fundamentals(tickers, force=False):
    """Fetch quality+value fundamentals via FMP /stable/ endpoints.
    Uses 3 calls per ticker (profile, ratios-ttm, key-metrics-ttm). Result normalized
    to the same field names the Q+V eval expects (gross_margin 0-1, roe 0-1, etc).
    debt_equity now in decimal (0.795 = 79.5%); threshold updated in eval_quality.
    """
    cache = load_cache(FUND_CACHE)
    to_fetch = [t for t in tickers if force or is_stale(cache.get(t), FUND_TTL_HOURS)]
    if not to_fetch:
        return cache, 0
    # FMP free tier only covers ~30-50 megacap symbols; for everything else we
    # fall through to yfinance .info (which DOES work per-ticker — only bulk had XProtect issues).
    try:
        import yfinance as yf
        _have_yf = True
    except ImportError:
        _have_yf = False

    def _yf_fallback(ticker):
        if not _have_yf: return None
        try:
            info = yf.Ticker(ticker).info or {}
            # Normalize to FMP-shaped fields (debt_equity as decimal, not percent)
            de_pct = info.get("debtToEquity")
            return {
                "trailing_pe":   info.get("trailingPE"),
                "forward_pe":    info.get("forwardPE"),
                "roe":           info.get("returnOnEquity"),
                "roic":          None,  # yfinance doesn't expose ROIC directly
                "gross_margin":  info.get("grossMargins"),
                "op_margin":     info.get("operatingMargins"),
                "net_margin":    info.get("profitMargins"),
                "debt_equity":   (de_pct / 100) if de_pct is not None else None,  # 79.5 → 0.795
                "fcf_yield":     None,  # compute below
                "earnings_yield": (1 / info.get("trailingPE")) if info.get("trailingPE") and info["trailingPE"] > 0 else None,
                "ev_ebitda":     info.get("enterpriseToEbitda"),
                "market_cap":    info.get("marketCap"),
                "free_cashflow": info.get("freeCashflow"),
                "revenue_growth_yoy": info.get("revenueGrowth"),
                "sector":        info.get("sector"),
                "industry":      info.get("industry"),
                "name":          info.get("shortName") or info.get("longName"),
                "_source":       "yfinance fallback",
            }
        except Exception:
            return None

    if not fmp.is_configured() and not _have_yf:
        print(f"  [fund] neither FMP nor yfinance available — skipping fundamentals fetch", file=sys.stderr)
        return cache, 0
    budget = fmp.budget_status() if fmp.is_configured() else {"used": "n/a", "remaining": 0}
    print(f"  [fund] fetching {len(to_fetch)} tickers (FMP primary, yfinance fallback; budget {budget['used']}/{fmp.DAILY_CAP if fmp.is_configured() else 'n/a'})…",
          flush=True)
    fetched = 0; fmp_used = 0; yf_used = 0
    _loop_t0 = time.time()  # defensive: timing reference for XProtect post-mortem
    for i, t in enumerate(to_fetch):
        try:
            # Defensive trace — if XProtect kills the process mid-loop, this last-printed
            # line tells us exactly which ticker + call # + elapsed time triggered it.
            # See notes/learned.md for the 2026-06-07 investigation that showed the
            # real load is 1-2 yfinance calls per run, not 130.
            print(f"  [fund] [{i+1}/{len(to_fetch)}] {t} (yf_used={yf_used}, elapsed {time.time()-_loop_t0:.1f}s)", flush=True)
            # Try FMP first
            prof, perr = (fmp.profile(t) if fmp.is_configured() else (None, "FMP not configured"))
            rats, rerr = (fmp.ratios_ttm(t) if fmp.is_configured() else (None, "FMP not configured"))
            mets, merr = (fmp.key_metrics_ttm(t) if fmp.is_configured() else (None, "FMP not configured"))
            # Detect FMP free-tier paywall and fall through to yfinance
            paywalled = any(("Premium Query" in str(e)) or ("HTTP 402" in str(e)) for e in (perr, rerr, merr) if e)
            if paywalled or (perr and rerr and merr):
                yf_data = _yf_fallback(t)
                if yf_data:
                    # Compute fcf_yield from FCF / mcap if both present
                    if yf_data.get("free_cashflow") and yf_data.get("market_cap"):
                        yf_data["fcf_yield"] = yf_data["free_cashflow"] / yf_data["market_cap"]
                    cache[t] = {**yf_data, "_fetched_at": now_iso()}
                    yf_used += 1
                    fetched += 1
                    continue
                cache[t] = {"error": f"FMP paywalled + yfinance fallback failed", "_fetched_at": now_iso()}
                continue
            if perr or rerr or merr:
                cache[t] = {"error": f"profile:{perr or 'ok'} / ratios:{rerr or 'ok'} / metrics:{merr or 'ok'}",
                            "_fetched_at": now_iso()}
                continue
            prof = prof or {}; rats = rats or {}; mets = mets or {}
            cache[t] = {
                "trailing_pe":   rats.get("priceToEarningsRatioTTM"),
                "forward_pe":    None,  # /stable/ free doesn't expose forward P/E reliably
                "roe":           mets.get("returnOnEquityTTM"),
                "roic":          mets.get("returnOnInvestedCapitalTTM"),
                "gross_margin":  rats.get("grossProfitMarginTTM"),
                "op_margin":     rats.get("operatingProfitMarginTTM"),
                "net_margin":    rats.get("netProfitMarginTTM"),
                "debt_equity":   rats.get("debtToEquityRatioTTM"),  # decimal e.g. 0.795
                "fcf_yield":     mets.get("freeCashFlowYieldTTM"),
                "earnings_yield": mets.get("earningsYieldTTM"),
                "ev_ebitda":     mets.get("evToEBITDATTM"),
                "market_cap":    mets.get("marketCap") or prof.get("marketCap"),
                "free_cashflow": (mets.get("freeCashFlowYieldTTM") or 0) * (mets.get("marketCap") or prof.get("marketCap") or 0) or None,
                "revenue_growth_yoy": None,  # filled below if income-growth succeeds
                "sector":        prof.get("sector"),
                "industry":      prof.get("industry"),
                "name":          prof.get("companyName"),
                "_fetched_at":   now_iso(),
                "_source":       "fmp /stable/",
            }
            # Optional 4th call for revenue growth — skip if budget tight
            if fmp.is_configured():
                bs = fmp.budget_status()
                if bs["remaining"] > 30:
                    gr, gerr = fmp.income_growth(t, period="annual")
                    if not gerr and isinstance(gr, list) and gr:
                        cache[t]["revenue_growth_yoy"] = gr[0].get("growthRevenue")
            cache[t]["_source"] = "fmp /stable/"
            fmp_used += 1
            fetched += 1
        except Exception as e:
            cache[t] = {"error": str(e)[:120], "_fetched_at": now_iso()}
        if (i + 1) % 5 == 0:
            print(f"    …{i+1}/{len(to_fetch)} done (FMP {fmp_used} · yfinance fallback {yf_used})", flush=True)
            save_cache(FUND_CACHE, cache)
    save_cache(FUND_CACHE, cache)
    print(f"  [fund] done: FMP {fmp_used} · yfinance fallback {yf_used} · failed {len(to_fetch)-fetched}", flush=True)
    return cache, fetched

# ── P1 gate evaluation (mirrors us_status() in dashboard.py) ─────────────
def eval_p1_technical(t):
    """Returns ('pass'|'fail', reason_str). Pass = all 8 gates ok except earnings/macro
    (those are entry-specific and can't be batch-evaluated)."""
    if t.get("error"): return ("fail", f"data: {t['error']}")
    p, s50, s200, rsi = t.get("price"), t.get("sma50"), t.get("sma200"), t.get("rsi14")
    if p is None or s50 is None: return ("fail", "insufficient bars")
    if s200 is None:             return ("fail", "no SMA200 (recent IPO)")
    if not (p > s50 > s200):     return ("fail", f"trend filter: price ${p:.2f} vs SMA50 ${s50:.2f} vs SMA200 ${s200:.2f}")
    if rsi is None:              return ("fail", "RSI unavailable")
    if rsi > 70:                 return ("fail", f"RSI {rsi:.1f} > 70 overbought")
    if rsi < 30:                 return ("fail", f"RSI {rsi:.1f} < 30 oversold")
    ch = t.get("change_pct") or 0
    if abs(ch) > 5:              return ("fail", f"today {ch:+.1f}% violent")
    slope = t.get("sma50_slope_pct")
    if slope is not None and slope < -0.5: return ("fail", f"SMA50 falling {slope:+.2f}%/5d")
    vr = t.get("vol_ratio")
    if vr is not None and vr > 1.3:        return ("fail", f"vol {vr:.2f}× distribution")
    s20 = t.get("sma20")
    if s20:
        vs20 = (p / s20 - 1) * 100
        if vs20 > 10:    return ("fail", f"+{vs20:.1f}% above SMA20 (extended)")
        if vs20 < -5:    return ("fail", f"{vs20:.1f}% below SMA20 (broken)")
    if 35 <= rsi <= 50:
        return ("pass", f"RSI {rsi:.1f} in 35-50, trend OK, vol healthy")
    return ("fail", f"RSI {rsi:.1f} outside 35-50 entry band")

# ── Quality + Value evaluation (Buffett-style) ────────────────────────────
def eval_quality(f):
    """Quality gates — need 4/5 to qualify."""
    if not f or f.get("error"): return (0, 5, [("data error", False, str((f or {}).get("error", "no data"))[:80])])
    checks = []
    roe = f.get("roe")
    if roe is not None and roe > 0.15: checks.append(("ROE", True,  f"{roe*100:.1f}% > 15%"))
    else: checks.append(("ROE", False, f"{(roe or 0)*100:.1f}% (need >15%)"))
    gm = f.get("gross_margin")
    if gm is not None and gm > 0.35: checks.append(("Gross margin", True,  f"{gm*100:.1f}% > 35%"))
    else: checks.append(("Gross margin", False, f"{(gm or 0)*100:.1f}% (need >35%)"))
    om = f.get("op_margin")
    if om is not None and om > 0.15: checks.append(("Op margin", True,  f"{om*100:.1f}% > 15%"))
    else: checks.append(("Op margin", False, f"{(om or 0)*100:.1f}% (need >15%)"))
    de = f.get("debt_equity")
    # FMP /stable/ returns decimal ratio (0.795 = 79.5%). Threshold 1.5 = 150% D/E.
    if de is not None and de < 1.5: checks.append(("Debt/equity", True,  f"{de:.2f} < 1.50"))
    else: checks.append(("Debt/equity", False, f"{de if de is not None else 0:.2f} (need <1.50)"))
    rg = f.get("revenue_growth_yoy")
    if rg is not None and rg > 0.08: checks.append(("Rev growth YoY", True,  f"{rg*100:.1f}% > 8%"))
    else: checks.append(("Rev growth YoY", False, f"{(rg or 0)*100:.1f}% (need >8%)"))
    passes = sum(1 for c in checks if c[1])
    return (passes, len(checks), checks)

def eval_value(f):
    """Value gates — need 2/3 to qualify."""
    if not f or f.get("error"): return (0, 3, [("data error", False, str((f or {}).get("error", "no data"))[:80])])
    checks = []
    tpe = f.get("trailing_pe"); fpe = f.get("forward_pe")
    if tpe is not None and 0 < tpe < 25: checks.append(("Trailing P/E", True,  f"{tpe:.1f} < 25"))
    else: checks.append(("Trailing P/E", False, f"{tpe or '—'} (need 0<P/E<25)"))
    # EV/EBITDA — cleaner value signal than Fwd<Trailing P/E (which FMP /stable/ free doesn't expose).
    # Threshold 15 = reasonable. Below 10 = cheap. Above 20 = rich.
    ev_eb = f.get("ev_ebitda")
    if ev_eb is not None and 0 < ev_eb < 15: checks.append(("EV/EBITDA", True, f"{ev_eb:.1f} < 15"))
    else: checks.append(("EV/EBITDA", False, f"{ev_eb if ev_eb is not None else 0:.1f} (need 0<EV/EBITDA<15)"))
    # FMP /stable/ provides fcf_yield directly as a decimal (0.028 = 2.8%)
    fcf_yield_dec = f.get("fcf_yield")
    fcf_yield = fcf_yield_dec * 100 if fcf_yield_dec is not None else None
    # Fallback: compute from raw FCF if direct yield missing
    if fcf_yield is None:
        fcf = f.get("free_cashflow"); mcap = f.get("market_cap")
        fcf_yield = (fcf / mcap * 100) if (fcf and mcap and fcf > 0) else None
    if fcf_yield is not None and fcf_yield > 4: checks.append(("FCF yield", True,  f"{fcf_yield:.2f}% > 4%"))
    else: checks.append(("FCF yield", False, f"{fcf_yield or 0:.2f}% (need >4%)"))
    passes = sum(1 for c in checks if c[1])
    return (passes, len(checks), checks)

def tag_candidate(p1_ok, q_pass, v_pass):
    """Compose candidate tag from gate combinations."""
    if not p1_ok: return None
    q_ok = q_pass >= 4
    v_ok = v_pass >= 2
    if q_ok and v_ok: return ("💎 BUFFETT", "Quality + Value + P1 technical — best signal")
    if q_ok:          return ("🏆 QUALITY", "Quality + P1 but stretched on valuation")
    if v_ok:          return ("💰 VALUE",   "Value + P1 but doesn't pass full quality bar")
    return ("⚡ TECH",  "Passes P1 technical but neither quality nor value gates")

# ── Main scan ─────────────────────────────────────────────────────────────
FULL_PASS_TTL_HOURS = 18  # skip a fresh full scan if we ran one less than this many hours ago

def run_scan(force=False, tech_only=False):
    # Daily-only short-circuit: skip if a full pass ran recently
    if not force:
        prior = load_cache(OUT_CACHE)
        last_pass = prior.get("_last_full_pass_at") or prior.get("_generated_at")
        if last_pass:
            try:
                age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last_pass)).total_seconds() / 3600
                if age_h < FULL_PASS_TTL_HOURS:
                    print(f"Last full pass was {age_h:.1f}h ago (< {FULL_PASS_TTL_HOURS}h TTL). Returning cached candidates. Pass --refresh to override.")
                    return prior
            except Exception:
                pass

    universe = load_universe()
    tickers = [t for t, _ in universe]
    sector_map = {t: s for t, s in universe}
    wl = watchlist_us_tickers()

    print(f"Universe: {len(tickers)} tickers · {len(set(s for _, s in universe))} sectors · watchlist excludes {len(wl)} names")

    tech, n_tech, tech_err = fetch_technicals_bulk(tickers, force=force)
    valid_count = sum(1 for t in tickers if not tech.get(t, {}).get("error") and tech.get(t, {}).get("price"))
    print(f"  [tech] {n_tech} re-fetched · {valid_count} valid")

    # Failure detection: if we couldn't fetch any new data AND we have no valid technicals
    # at all, fall back to the last good candidates.json with a stale flag.
    if tech_err and valid_count == 0:
        stale = stale_output_with_warning(f"yfinance fetch failed: {tech_err}")
        if stale:
            print(f"  [tech] FAIL — using stale candidates.json from {stale.get('_generated_at')}", file=sys.stderr)
            return stale
        # No prior cache to fall back to — return empty
        return {"_generated_at": now_iso(), "universe_size": len(tickers), "p1_passers": 0,
                "candidates": [], "_stale": True, "_stale_reason": tech_err}

    # First pass: P1 technical filter
    p1_passers = []
    for t in tickers:
        ok, why = eval_p1_technical(tech.get(t, {}))
        if ok == "pass":
            p1_passers.append({"ticker": t, "tech_reason": why, "tech": tech.get(t, {}), "sector": sector_map.get(t)})

    print(f"  [p1] {len(p1_passers)}/{len(tickers)} pass technical gates")

    # Second pass: fundamentals (only on passers + only if not tech-only mode)
    if not tech_only and p1_passers:
        fund, n_fund = fetch_fundamentals([c["ticker"] for c in p1_passers], force=force)
        print(f"  [fund] {n_fund} re-fetched")
    else:
        fund = load_cache(FUND_CACHE)

    candidates = []
    for c in p1_passers:
        f = fund.get(c["ticker"], {})
        q_pass, q_total, q_checks = eval_quality(f) if not tech_only else (0, 5, [])
        v_pass, v_total, v_checks = eval_value(f)   if not tech_only else (0, 3, [])
        tag, tag_desc = tag_candidate(True, q_pass, v_pass) if not tech_only else ("⚡ TECH", "tech-only mode")
        already_on_wl = c["ticker"] in wl
        candidates.append({
            **c,
            "in_watchlist": already_on_wl,
            "fundamentals": f,
            "quality": {"passes": q_pass, "total": q_total, "checks": q_checks},
            "value":   {"passes": v_pass, "total": v_total, "checks": v_checks},
            "tag": tag, "tag_desc": tag_desc,
        })

    # Sort: BUFFETT first, then QUALITY, then VALUE, then TECH
    tag_order = {"💎 BUFFETT": 0, "🏆 QUALITY": 1, "💰 VALUE": 2, "⚡ TECH": 3}
    candidates.sort(key=lambda c: (
        c["in_watchlist"],                            # not-on-watchlist first
        tag_order.get(c["tag"], 9),                   # best tag first
        -(c["quality"]["passes"] + c["value"]["passes"]),  # higher composite first
    ))

    out = {"_generated_at": now_iso(), "_last_full_pass_at": now_iso(),
           "universe_size": len(tickers), "p1_passers": len(p1_passers),
           "candidates": candidates}
    save_cache(OUT_CACHE, out)
    return out

# ── CLI output ────────────────────────────────────────────────────────────
def cmd_show(out):
    cands = out.get("candidates", [])
    if not cands:
        print("\nNo P1-passing candidates in cache. Run without --show first.")
        return
    fresh = [c for c in cands if not c["in_watchlist"]]
    print(f"\n=== US SCREENER OUTPUT ===  generated {out['_generated_at']}")
    print(f"Universe: {out['universe_size']} · P1 passers: {out['p1_passers']} · Fresh (not on watchlist): {len(fresh)}\n")
    print(f"{'TAG':<14} {'TICKER':<7} {'SECTOR':<24} {'Q':<5} {'V':<5} REASON")
    print(f"{'-'*14:<14} {'-'*7:<7} {'-'*24:<24} {'-'*5:<5} {'-'*5:<5} {'-'*60}")
    for c in cands:
        prefix = "★ " if c["in_watchlist"] else "  "
        q = f"{c['quality']['passes']}/{c['quality']['total']}"
        v = f"{c['value']['passes']}/{c['value']['total']}"
        sect = (c["sector"] or "—")[:23]
        print(f"{prefix}{c['tag']:<14} {c['ticker']:<7} {sect:<24} {q:<5} {v:<5} {c['tech_reason'][:60]}")
    print(f"\n★ = already in your watchlist. Top non-★ rows are your discovery output.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh",   action="store_true", help="Force re-fetch (ignore TTLs)")
    ap.add_argument("--tech-only", action="store_true", help="Skip fundamentals fetch + Q+V scoring")
    ap.add_argument("--show",      action="store_true", help="Just print last cached candidates")
    args = ap.parse_args()

    if args.show:
        out = load_cache(OUT_CACHE)
        if not out: print("No cache yet — run the screener first."); return 1
        cmd_show(out); return 0

    out = run_scan(force=args.refresh, tech_only=args.tech_only)
    cmd_show(out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
