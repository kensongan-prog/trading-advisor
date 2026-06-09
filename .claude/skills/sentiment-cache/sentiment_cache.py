#!/usr/bin/env python3
"""
sentiment_cache.py — LLM-score raw retail sentiment and produce composite per-ticker reads.

Consumes the raw caches from reddit-sentiment and stocktwits-sentiment skills, sends
untagged message bodies to OpenRouter for sentiment classification, combines into a
composite output with the §4 contrarian-filter flag.

Output: .claude/cache/sentiment/{TICKER}.json — canonical sentiment cache the dashboard reads.

Setup:
    .claude/skills/sentiment-cache/.env  with OPENROUTER_API_KEY=sk-or-v1-...

Usage:
    python3 .claude/skills/sentiment-cache/sentiment_cache.py             # all watchlist
    python3 .claude/skills/sentiment-cache/sentiment_cache.py AUPH BTC    # specific
    python3 .claude/skills/sentiment-cache/sentiment_cache.py --show
    python3 .claude/skills/sentiment-cache/sentiment_cache.py --show AUPH
    python3 .claude/skills/sentiment-cache/sentiment_cache.py --clear
    python3 .claude/skills/sentiment-cache/sentiment_cache.py --check-auth
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "sentiment"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

REDDIT_CACHE = PROJECT_ROOT / ".claude" / "cache" / "reddit_sentiment"
STOCKTWITS_CACHE = PROJECT_ROOT / ".claude" / "cache" / "stocktwits_sentiment"
HACKERNEWS_CACHE = PROJECT_ROOT / ".claude" / "cache" / "hn_sentiment"
ENV_FILE = SCRIPT_DIR / ".env"

DEFAULT_MODEL = "google/gemma-4-31b-it:free"
FALLBACK_MODEL = "openai/gpt-oss-120b:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_MESSAGES_PER_TICKER = 25  # cap to keep classification call snappy + within token budget


# ── .env loader ───────────────────────────────────────────────────────────
def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def get_model():
    return os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)


# ── OpenRouter classification ─────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are a financial sentiment classifier. You receive a numbered list of short "
    "messages about a single ticker, and return ONLY a JSON array, one object per "
    "message in the same order. Each object: "
    '{"sentiment": "bullish" | "bearish" | "neutral", "conviction": 0.0-1.0}. '
    "Conviction reflects how clear the sentiment is, NOT how strong the directional "
    "view is. Sarcasm, irony, and hedge-language reduce conviction. No prose, no markdown."
)


def classify_messages(messages, ticker, model=None, timeout=60):
    """Classify a list of message body strings. Returns (results, error_or_none, raw_response_str)."""
    if not messages:
        return [], None, ""
    model = model or get_model()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None, f"OPENROUTER_API_KEY missing — set in {ENV_FILE}", ""

    # Truncate each message body to 400 chars; trim collection to cap
    msgs = messages[:MAX_MESSAGES_PER_TICKER]
    numbered = "\n".join(f"{i+1}. {m[:400]}" for i, m in enumerate(msgs))
    user = f"Classify these {len(msgs)} messages about ${ticker}. Return JSON only.\n{numbered}"

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 1500,
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/local/trading-advisor",  # OpenRouter etiquette
            "X-Title": "trading-advisor sentiment scorer",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:300]}", ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", ""

    content = (d.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    # Strip optional markdown fence
    if content.startswith("```"):
        parts = content.split("```", 2)
        content = parts[1].lstrip()
        if content.startswith("json"):
            content = content[4:].lstrip()
        content = content.rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(content)
    except Exception as e:
        return None, f"JSON parse failed: {e}", content

    if not isinstance(parsed, list) or len(parsed) != len(msgs):
        return None, f"Expected list of {len(msgs)}, got {type(parsed).__name__} len={len(parsed) if isinstance(parsed,list) else '?'}", content

    # Normalize each entry
    out = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            out.append({"sentiment": "neutral", "conviction": 0.0})
            continue
        sent = str(item.get("sentiment", "neutral")).lower().strip()
        if sent not in ("bullish", "bearish", "neutral"):
            sent = "neutral"
        try:
            conv = float(item.get("conviction", 0.0))
            conv = max(0.0, min(1.0, conv))
        except Exception:
            conv = 0.0
        out.append({"sentiment": sent, "conviction": conv})
    return out, None, content


# ── Aggregate LLM scores into per-source pcts ──────────────────────────────
import math


def _engagement_weight(engagement):
    """Compress raw engagement into a per-message multiplier.

    Formula: 1.0 + log1p(engagement)
      e=0    → 1.0 (zero-engagement still counts as one vote — never silently dropped)
      e=10   → ~3.4
      e=100  → ~5.6
      e=1000 → ~7.9
      e=10000 → ~10.2

    A hot 1000-upvote post contributes ~8× more than a 0-upvote one — meaningful
    but not extreme. The log curve prevents a single 50k-upvote viral post from
    drowning out the rest of the sample.
    """
    e = max(0.0, float(engagement or 0))
    return 1.0 + math.log1p(e)


def llm_pcts(classifications, engagements=None):
    """Convert list of {sentiment, conviction} into weighted bull/bear/neutral pcts.

    If `engagements` is provided (parallel list of floats — upvotes, likes, etc.),
    each message's effective weight becomes `conviction × engagement_weight(e)`.
    Otherwise reverts to conviction-only weighting (old behavior).
    """
    if not classifications:
        return None
    if engagements is None or len(engagements) != len(classifications):
        weights = [c["conviction"] for c in classifications]
    else:
        weights = [c["conviction"] * _engagement_weight(e)
                   for c, e in zip(classifications, engagements)]
    total_w = sum(weights)
    if total_w == 0:
        # All zero weight = treat as uniform neutral
        return {"bull": 0.0, "bear": 0.0, "neutral": 1.0, "avg_conviction": 0.0,
                "engagement_weighted": engagements is not None}
    bull = sum(w for c, w in zip(classifications, weights) if c["sentiment"] == "bullish") / total_w
    bear = sum(w for c, w in zip(classifications, weights) if c["sentiment"] == "bearish") / total_w
    neut = sum(w for c, w in zip(classifications, weights) if c["sentiment"] == "neutral") / total_w
    return {
        "bull": round(bull, 3),
        "bear": round(bear, 3),
        "neutral": round(neut, 3),
        "avg_conviction": round(sum(c["conviction"] for c in classifications) / len(classifications), 3),
        "engagement_weighted": engagements is not None,
    }


# ── Per-source processing ─────────────────────────────────────────────────
def load_stocktwits(ticker):
    p = STOCKTWITS_CACHE / f"{ticker.upper()}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_reddit(ticker):
    p = REDDIT_CACHE / f"{ticker.upper()}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_hackernews(ticker):
    p = HACKERNEWS_CACHE / f"{ticker.upper()}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def process_hackernews(raw, model):
    """Flatten HN stories + top comments into a single classification pass.
    Each story title contributes one body with engagement = story.engagement.
    Each top-level comment contributes one body with engagement = comment.points.
    The MAX_MESSAGES_PER_TICKER cap in classify_messages will trim if needed.
    """
    if not raw or raw.get("no_coverage") or raw.get("error"):
        return None, None
    stories = raw.get("stories") or []
    if not stories:
        return None, None
    bodies, engagements = [], []
    for s in stories:
        # Story title + optional excerpt as one scoring unit
        title = (s.get("title") or "").strip()
        if title:
            text = title
            if s.get("story_text_excerpt"):
                text += " — " + s["story_text_excerpt"][:200]
            bodies.append(text)
            engagements.append(s.get("engagement") or 0)
        # Top-level comments
        for c in (s.get("top_comments") or []):
            body = (c.get("body") or "").strip()
            if not body or len(body) < 40:
                continue
            bodies.append(body)
            engagements.append(c.get("points") or 0)
    if not bodies:
        return None, None
    classifications, err, _raw = classify_messages(bodies, raw["ticker"], model=model)
    if err:
        return None, f"LLM scoring failed: {err}"
    engagements = engagements[:len(classifications)]
    pcts = llm_pcts(classifications, engagements=engagements)
    return {
        "present": True,
        "story_count": len(stories),
        "n_bodies_scored": len(classifications),
        "total_engagement": sum(engagements),
        "llm_bull_pct": pcts["bull"] if pcts else None,
        "llm_bear_pct": pcts["bear"] if pcts else None,
        "llm_neutral_pct": pcts["neutral"] if pcts else None,
        "llm_avg_conviction": pcts["avg_conviction"] if pcts else None,
    }, None


def process_stocktwits(raw, model):
    """Returns (source_summary_dict_or_None, error_or_none)."""
    if not raw or raw.get("no_coverage") or not raw.get("messages"):
        return None, None

    msgs = [m for m in raw["messages"] if m.get("body")]
    if not msgs:
        return None, None
    bodies = [m["body"] for m in msgs]
    # Engagement per ST message: likes + reshares × 2 (reshares mean someone
    # found it worth their followers' attention — heavier signal than a like).
    engagements = [(m.get("likes") or 0) + 2 * (m.get("reshares") or 0) for m in msgs]

    classifications, err, _raw = classify_messages(bodies, raw["ticker"], model=model)
    if err:
        return None, f"LLM scoring failed: {err}"

    # classify_messages may truncate to MAX_MESSAGES_PER_TICKER — keep engagements aligned.
    engagements = engagements[:len(classifications)]
    pcts = llm_pcts(classifications, engagements=engagements)
    user_tagged_bull = raw.get("tagged_bull_pct")

    return {
        "present": True,
        "n_messages": len(msgs),
        "user_tagged_bull_pct": user_tagged_bull,
        "tagged_counts": raw.get("tagged_counts"),
        "llm_bull_pct": pcts["bull"] if pcts else None,
        "llm_bear_pct": pcts["bear"] if pcts else None,
        "llm_neutral_pct": pcts["neutral"] if pcts else None,
        "llm_avg_conviction": pcts["avg_conviction"] if pcts else None,
    }, None


def process_reddit(raw, model):
    if not raw or not raw.get("posts"):
        return None, None
    posts = raw["posts"]
    # Title + first 200 chars of selftext as the scoring unit; engagement
    # weight = upvotes + num_comments × 2. Posts in RSS-only mode (no OAuth)
    # have score=None → fall back to 0 (the +1 floor in _engagement_weight
    # ensures they still count as one vote).
    bodies, engagements = [], []
    for p in posts:
        text = p.get("title", "")
        if p.get("selftext_excerpt"):
            text += " — " + p["selftext_excerpt"][:200]
        bodies.append(text)
        engagements.append((p.get("score") or 0) + 2 * (p.get("num_comments") or 0))
    if not bodies:
        return None, None

    classifications, err, _raw = classify_messages(bodies, raw["ticker"], model=model)
    if err:
        return None, f"LLM scoring failed: {err}"
    engagements = engagements[:len(classifications)]
    pcts = llm_pcts(classifications, engagements=engagements)
    return {
        "present": True,
        "n_posts": len(posts),
        "mention_count": raw.get("mention_count", len(posts)),
        "llm_bull_pct": pcts["bull"] if pcts else None,
        "llm_bear_pct": pcts["bear"] if pcts else None,
        "llm_neutral_pct": pcts["neutral"] if pcts else None,
        "llm_avg_conviction": pcts["avg_conviction"] if pcts else None,
    }, None


# ── Composite ─────────────────────────────────────────────────────────────
def compute_composite(st_summary, rd_summary, hn_summary=None):
    """Combine source summaries into composite scores + label + contrarian flag.

    Source weights: ST 1.0, Reddit 1.0, HN 1.2 (HN signal is generally less
    gameable + carries higher per-comment information density, so it earns
    a slight bump above the cheap-talk forums)."""
    weights = []
    bulls, bears, neuts = [], [], []
    convictions = []

    if st_summary and st_summary.get("present"):
        # ST sub-blend: when user-tagged data exists, 40% tagged + 60% LLM (LLM covers untagged too)
        # When no user-tagged data, 100% LLM
        st_bull = st_summary.get("llm_bull_pct") or 0.0
        st_bear = st_summary.get("llm_bear_pct") or 0.0
        st_neut = st_summary.get("llm_neutral_pct") or 0.0
        ut_bull = st_summary.get("user_tagged_bull_pct")
        if ut_bull is not None:
            # Tagged data is bull/bear binary among tagged-only — fold in at 40%
            st_bull = 0.4 * ut_bull + 0.6 * st_bull
            st_bear = 0.4 * (1 - ut_bull) + 0.6 * st_bear
            st_neut = 0.6 * st_neut  # tagged data has no neutral component
        bulls.append(st_bull); bears.append(st_bear); neuts.append(st_neut)
        weights.append(1.0)
        if st_summary.get("llm_avg_conviction") is not None:
            convictions.append(st_summary["llm_avg_conviction"])

    if rd_summary and rd_summary.get("present"):
        bulls.append(rd_summary.get("llm_bull_pct") or 0.0)
        bears.append(rd_summary.get("llm_bear_pct") or 0.0)
        neuts.append(rd_summary.get("llm_neutral_pct") or 0.0)
        weights.append(1.0)
        if rd_summary.get("llm_avg_conviction") is not None:
            convictions.append(rd_summary["llm_avg_conviction"])

    if hn_summary and hn_summary.get("present"):
        bulls.append(hn_summary.get("llm_bull_pct") or 0.0)
        bears.append(hn_summary.get("llm_bear_pct") or 0.0)
        neuts.append(hn_summary.get("llm_neutral_pct") or 0.0)
        weights.append(1.2)
        if hn_summary.get("llm_avg_conviction") is not None:
            convictions.append(hn_summary["llm_avg_conviction"])

    if not weights:
        return {
            "bull_score": None, "bear_score": None, "neutral_score": None,
            "conviction": None, "label": "UNKNOWN", "badge": "—",
            "contrarian_flag": None,
            "rationale": "No source data available.",
        }

    total_w = sum(weights)
    bull_score = round(sum(b * w for b, w in zip(bulls, weights)) / total_w, 3)
    bear_score = round(sum(b * w for b, w in zip(bears, weights)) / total_w, 3)
    neut_score = round(sum(n * w for n, w in zip(neuts, weights)) / total_w, 3)
    conviction = round(sum(convictions) / len(convictions), 3) if convictions else 0.0

    # Label + contrarian flag
    if bull_score >= 0.80 and conviction >= 0.70:
        label, badge, flag = "EXTREME_BULL", "🔥", "FADE"
    elif bear_score >= 0.80 and conviction >= 0.70:
        label, badge, flag = "EXTREME_BEAR", "🧊", "BUY"
    elif bull_score >= 0.60:
        label, badge, flag = "BULL", "📈", None
    elif bear_score >= 0.60:
        label, badge, flag = "BEAR", "📉", None
    else:
        label, badge, flag = "NEUTRAL", "—", None

    return {
        "bull_score": bull_score,
        "bear_score": bear_score,
        "neutral_score": neut_score,
        "conviction": conviction,
        "label": label,
        "badge": badge,
        "contrarian_flag": flag,
    }


def build_rationale(st, rd, composite, hn=None):
    parts = []
    if st and st.get("present"):
        ut = st.get("user_tagged_bull_pct")
        ut_str = f"{ut:.0%} user-tagged bull, " if ut is not None else ""
        parts.append(
            f"ST: {st['n_messages']} msgs, {ut_str}"
            f"LLM bull/bear/neut {st.get('llm_bull_pct'):.0%}/{st.get('llm_bear_pct'):.0%}/{st.get('llm_neutral_pct'):.0%}"
        )
    if rd and rd.get("present"):
        parts.append(
            f"Reddit: {rd.get('n_posts')} posts, "
            f"LLM bull/bear/neut {rd.get('llm_bull_pct'):.0%}/{rd.get('llm_bear_pct'):.0%}/{rd.get('llm_neutral_pct'):.0%}"
        )
    if hn and hn.get("present"):
        parts.append(
            f"HN: {hn.get('story_count')} stories ({hn.get('n_bodies_scored')} bodies), "
            f"LLM bull/bear/neut {hn.get('llm_bull_pct'):.0%}/{hn.get('llm_bear_pct'):.0%}/{hn.get('llm_neutral_pct'):.0%}"
        )
    if not parts:
        return "No source data available."
    flag_note = ""
    if composite.get("contrarian_flag") == "FADE":
        flag_note = "  ⚠️  Extreme retail crowded long — contrarian FADE on extended technicals."
    elif composite.get("contrarian_flag") == "BUY":
        flag_note = "  ⚠️  Extreme retail capitulation — contrarian BUY on constructive P1."
    return " | ".join(parts) + flag_note


# ── Per-ticker orchestration ──────────────────────────────────────────────
def score_ticker(ticker, model=None, verbose=True):
    model = model or get_model()
    st_raw = load_stocktwits(ticker)
    rd_raw = load_reddit(ticker)
    hn_raw = load_hackernews(ticker)

    if verbose:
        st_status = "ok" if (st_raw and not st_raw.get("no_coverage") and st_raw.get("messages")) else "missing"
        rd_status = "ok" if (rd_raw and rd_raw.get("posts")) else "missing"
        hn_status = "ok" if (hn_raw and (hn_raw.get("stories") or [])) else ("skip" if hn_raw and hn_raw.get("no_coverage") else "missing")
        print(f"  sources: stocktwits={st_status}  reddit={rd_status}  hn={hn_status}")

    st_summary, st_err = process_stocktwits(st_raw, model) if st_raw else (None, None)
    if st_err and verbose:
        print(f"  stocktwits LLM error: {st_err}")
    rd_summary, rd_err = process_reddit(rd_raw, model) if rd_raw else (None, None)
    if rd_err and verbose:
        print(f"  reddit LLM error: {rd_err}")
    hn_summary, hn_err = process_hackernews(hn_raw, model) if hn_raw else (None, None)
    if hn_err and verbose:
        print(f"  hn LLM error: {hn_err}")

    asset_class = (st_raw or rd_raw or hn_raw or {}).get("asset_class", "unknown")
    composite = compute_composite(st_summary, rd_summary, hn_summary)
    rationale = build_rationale(st_summary, rd_summary, composite, hn=hn_summary)
    composite["rationale"] = rationale

    return {
        "ticker": ticker.upper(),
        "asset_class": asset_class,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "model": model,
        "sources": {
            "stocktwits":  st_summary or {"present": False, "error": st_err},
            "reddit":      rd_summary or {"present": False, "error": rd_err},
            "hackernews":  hn_summary or {"present": False, "error": hn_err},
        },
        "composite": composite,
    }


# ── Watchlist + cache I/O ─────────────────────────────────────────────────
def parse_watchlist():
    if not WATCHLIST_PATH.exists():
        return []
    text = WATCHLIST_PATH.read_text(encoding="utf-8")
    out, seen = [], set()
    for m in re.finditer(r"^\s*-\s*`([^`]+)`", text, re.MULTILINE):
        sym = m.group(1).strip().upper()
        if sym and not sym.startswith("_") and sym != "TICKER" and sym not in seen:
            seen.add(sym); out.append(sym)
    return out


def cache_path(ticker):
    safe = ticker.upper().replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe}.json"


def save_cache(ticker, data):
    cache_path(ticker).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_cache(ticker):
    p = cache_path(ticker)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_check_auth():
    print(f"ENV file: {ENV_FILE}  (exists: {ENV_FILE.exists()})")
    print(f"OPENROUTER_API_KEY: {'set' if os.environ.get('OPENROUTER_API_KEY') else 'MISSING'}")
    print(f"OPENROUTER_MODEL: {get_model()}")
    if not os.environ.get("OPENROUTER_API_KEY"):
        return 1
    # Tiny probe
    res, err, _ = classify_messages(["This stock is going to the moon!"], "TEST")
    if err:
        print(f"\nAUTH/PROBE FAILED: {err}")
        return 1
    print(f"\nAUTH OK — probe returned: {res}")
    return 0


def cmd_score(tickers, model=None):
    if not tickers:
        tickers = parse_watchlist()
        if not tickers:
            print("ERROR: no tickers and watchlist empty", file=sys.stderr); return 1
        print(f"Scoring {len(tickers)} tickers from watchlist")
    else:
        print(f"Scoring {len(tickers)} tickers: {' '.join(tickers)}")
    print(f"Model: {model or get_model()}\n")

    summary = []
    for i, t in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {t}")
        result = score_ticker(t, model=model, verbose=True)
        save_cache(t, result)
        c = result["composite"]
        bs = f"{c['bull_score']:.0%}" if c['bull_score'] is not None else "—"
        cv = f"{c['conviction']:.0%}" if c['conviction'] is not None else "—"
        flag = c['contrarian_flag'] or ""
        print(f"  → {c['badge']} {c['label']:<14} bull={bs} conv={cv} {flag}\n")
        summary.append((t, c['label'], c['badge'], c['bull_score'], c['conviction'], c['contrarian_flag']))

    print("── Summary " + "─" * 60)
    print(f"{'TICKER':<10}{'BADGE':<6}{'LABEL':<16}{'BULL':>6}{'CONV':>6}  FLAG")
    for t, lbl, bdg, bs, cv, fl in summary:
        bs_s = f"{bs:.0%}" if bs is not None else "—"
        cv_s = f"{cv:.0%}" if cv is not None else "—"
        print(f"{t:<10}{bdg:<6}{lbl:<16}{bs_s:>6}{cv_s:>6}  {fl or ''}")
    return 0


def cmd_show(tickers):
    if tickers:
        for t in tickers:
            d = load_cache(t)
            if not d:
                print(f"{t}: no cache entry"); continue
            c = d["composite"]
            print(f"\n── {t} ({d['asset_class']}) — scored {d['scored_at']} — {d['model']} ──")
            print(f"  {c['badge']} {c['label']}  (bull={c['bull_score']}, bear={c['bear_score']}, neutral={c['neutral_score']}, conv={c['conviction']})")
            if c['contrarian_flag']:
                print(f"  ⚠️  contrarian flag: {c['contrarian_flag']}")
            print(f"  rationale: {c['rationale']}")
            print(f"  sources:")
            st = d['sources']['stocktwits']
            rd = d['sources']['reddit']
            if st.get('present'):
                print(f"    StockTwits: {st['n_messages']} msgs, user-tagged bull={st.get('user_tagged_bull_pct')}, "
                      f"LLM bull/bear/neut={st.get('llm_bull_pct')}/{st.get('llm_bear_pct')}/{st.get('llm_neutral_pct')}")
            else:
                print(f"    StockTwits: absent")
            if rd.get('present'):
                print(f"    Reddit: {rd.get('n_posts')} posts, "
                      f"LLM bull/bear/neut={rd.get('llm_bull_pct')}/{rd.get('llm_bear_pct')}/{rd.get('llm_neutral_pct')}")
            else:
                print(f"    Reddit: absent")
        return 0

    files = sorted(CACHE_DIR.glob("*.json"))
    if not files:
        print("(sentiment cache empty)"); return 0
    print(f"{'TICKER':<10}{'BADGE':<6}{'LABEL':<16}{'BULL':>6}{'CONV':>6}  FLAG       SCORED_AT")
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            c = d['composite']
            bs = f"{c['bull_score']:.0%}" if c['bull_score'] is not None else "—"
            cv = f"{c['conviction']:.0%}" if c['conviction'] is not None else "—"
            print(f"{d['ticker']:<10}{c['badge']:<6}{c['label']:<16}{bs:>6}{cv:>6}  {(c['contrarian_flag'] or '—'):<10} {d['scored_at']}")
        except Exception as e:
            print(f"{p.stem}: unreadable ({e})")
    return 0


def cmd_clear():
    files = list(CACHE_DIR.glob("*.json"))
    for p in files:
        p.unlink()
    print(f"Cleared {len(files)} files from {CACHE_DIR}")
    return 0


def main():
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--check-auth", action="store_true")
    ap.add_argument("--model", help="Override OPENROUTER_MODEL for this run")
    args = ap.parse_args()
    if args.clear: return cmd_clear()
    if args.check_auth: return cmd_check_auth()
    if args.show: return cmd_show([t.upper() for t in args.tickers])
    return cmd_score([t.upper() for t in args.tickers], model=args.model)


if __name__ == "__main__":
    sys.exit(main())
