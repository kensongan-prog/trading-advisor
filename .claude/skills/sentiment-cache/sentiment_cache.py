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

MAX_MESSAGES_PER_TICKER = 60  # cap to keep classification call snappy + within token budget
                              # (bumped 25→60 in v1.9.2 to accommodate Reddit
                              # comment-tree scoring: 10 posts × ~6 items each)


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
    '{"relevance": "primary"|"mention"|"none", "sentiment": "bullish"|"bearish"|"neutral", "conviction": 0.0-1.0}. '
    "relevance='primary' = the TICKER (or its commonly-known company name) is the main "
    "subject. relevance='mention' = the ticker appears but isn't the focus (peer mention, "
    "sector roundup, broad watchlist). relevance='none' = ticker doesn't actually appear, "
    "e.g. similar-looking word for a different company/topic (Solana vs 'Solara'). "
    "Conviction reflects how clear the sentiment is, NOT how strong the directional view. "
    "Sarcasm, irony, hedge-language reduce conviction. No prose, no markdown."
)


# Pulled from .claude/skills/us-news/news_glyph.py:COMPANY_LABELS. Sentiment lives
# in a separate skill module so we import lazily; the operator maintains a single
# source-of-truth map and this fetcher uses it. Falls back to bare ticker if the
# import fails (older deployments) — same degraded behavior as before.
def _company_label(ticker, asset_class=None):
    # Normalize asset_class — sentiment caches use "us_equity" but the
    # news_glyph COMPANY_LABELS keys use "us". Map common synonyms here so
    # both inputs work.
    ac = (asset_class or "us").lower()
    if ac in ("us_equity", "equity", "stock"): ac = "us"
    elif ac in ("crypto", "cryptocurrency"):   ac = "crypto"
    elif ac in ("klse", "bursa", "malaysia"):  ac = "klse"
    try:
        # Add the us-news skill to sys.path lazily, only on first use
        import sys
        ng_dir = str(SCRIPT_DIR.parent / "us-news")
        if ng_dir not in sys.path:
            sys.path.insert(0, ng_dir)
        import news_glyph as ng
        return ng._company_label(ticker, ac)
    except Exception:
        return ticker


def _is_transient_error(err_msg):
    """Decide if an LLM error is worth retrying against the fallback model.
    429 (rate limit) and 5xx (server-side) are transient; 4xx other than 429
    (bad request, auth failure) and JSON parse failures are not — the fallback
    would just produce the same error."""
    if not err_msg:
        return False
    # urllib errors come back as "HTTP 429: ..." or "HTTP 503: ..."
    for code in ("429", "500", "502", "503", "504"):
        if f"HTTP {code}" in err_msg:
            return True
    # Network-level errors (timeout, connection reset) — worth a fallback attempt
    if "URLError" in err_msg or "timeout" in err_msg.lower():
        return True
    return False


def classify_messages(messages, ticker, model=None, timeout=60, asset_class=None):
    """Classify a list of message body strings. Returns (results, error_or_none, raw_response_str).

    asset_class is used to look up the company label, threaded to the LLM prompt
    so it can correctly distinguish "Solana" from "Microsoft Project Solara" etc.
    Each result now includes `relevance` (primary|mention|none) which the
    aggregator uses to downweight off-topic items.

    On a 429/5xx from the primary model, automatically falls back to
    FALLBACK_MODEL. The pattern mirrors news_glyph's _llm_score_batch fallback.
    """
    if not messages:
        return [], None, ""
    primary = model or get_model()
    # Try primary; on a transient failure, retry against the fallback model.
    out, err, raw = _classify_one_attempt(messages, ticker, primary, timeout, asset_class)
    if err and primary != FALLBACK_MODEL and _is_transient_error(err):
        # Brief pace + retry. The fallback uses a different provider so a
        # 429 on Gemma doesn't preclude GPT-OSS-120B succeeding.
        time.sleep(1.5)
        out2, err2, raw2 = _classify_one_attempt(
            messages, ticker, FALLBACK_MODEL, timeout, asset_class)
        if not err2:
            return out2, None, raw2
        # Both failed — return the SECOND error (more recent) but mention both
        return None, f"primary={primary} {err[:120]} ; fallback={FALLBACK_MODEL} {err2[:120]}", raw2 or raw
    return out, err, raw


def _classify_one_attempt(messages, ticker, model, timeout, asset_class):
    """A single LLM call with the relevance-gated prompt. Returns the same
    shape as classify_messages."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None, f"OPENROUTER_API_KEY missing — set in {ENV_FILE}", ""

    subject = _company_label(ticker, asset_class)

    # Truncate each message body to 400 chars; trim collection to cap
    msgs = messages[:MAX_MESSAGES_PER_TICKER]
    numbered = "\n".join(f"{i+1}. {m[:400]}" for i, m in enumerate(msgs))
    user = f"TICKER: {subject}\nClassify these {len(msgs)} messages. Return JSON only.\n{numbered}"

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

    if not isinstance(parsed, list):
        return None, f"Expected list, got {type(parsed).__name__}", content
    # v1.9.2: LLMs occasionally miscount items on larger batches (Gemma 4 31B
    # returned 64 for a 60-item input). Tolerate length drift — truncate to the
    # request length when the LLM over-produces; pad with neutrals when under.
    if len(parsed) != len(msgs):
        if len(parsed) > len(msgs):
            parsed = parsed[:len(msgs)]  # over-produced — keep first N
        else:
            shortfall = len(msgs) - len(parsed)
            parsed = parsed + [{"sentiment": "neutral", "conviction": 0.0}] * shortfall

    # Normalize each entry. Older prompts didn't return `relevance`; default to
    # "primary" so legacy classifications continue to count at full weight.
    out = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            out.append({"sentiment": "neutral", "conviction": 0.0, "relevance": "primary"})
            continue
        sent = str(item.get("sentiment", "neutral")).lower().strip()
        if sent not in ("bullish", "bearish", "neutral"):
            sent = "neutral"
        try:
            conv = float(item.get("conviction", 0.0))
            conv = max(0.0, min(1.0, conv))
        except Exception:
            conv = 0.0
        rel = str(item.get("relevance", "primary")).lower().strip()
        if rel not in ("primary", "mention", "none"):
            rel = "primary"  # tolerate missing/garbage — assume relevant
        out.append({"sentiment": sent, "conviction": conv, "relevance": rel})
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


# Relevance → weight multiplier. 'none' fully discounts off-topic items (the
# "Microsoft Project Solara" tagged-as-SOL case the v2.0.2 HN audit found).
# 'mention' counts at half — a peer-mention is real signal but should not
# dominate a single name's read. 'primary' is the unmodified standard.
_RELEVANCE_WEIGHT = {"primary": 1.0, "mention": 0.5, "none": 0.0}


def llm_pcts(classifications, engagements=None):
    """Convert list of {sentiment, conviction, relevance} into weighted bull/bear/neutral pcts.

    If `engagements` is provided (parallel list of floats — upvotes, likes, etc.),
    each message's effective weight becomes `conviction × relevance × engagement_weight(e)`.
    Otherwise weight is `conviction × relevance`.
    Items with `relevance="none"` drop out entirely (weight 0) — they were classified
    as off-topic noise (the SOL/Solara case) and shouldn't dilute the on-topic read.
    """
    if not classifications:
        return None
    # Normalize missing relevance to "primary" so legacy classifications (pre-v2.0.4
    # callers that don't yet emit the field) count at full weight — matches the
    # default in classify_messages's output normalization.
    for c in classifications:
        if c.get("relevance") not in ("primary", "mention", "none"):
            c["relevance"] = "primary"
    rel_w = [_RELEVANCE_WEIGHT[c["relevance"]] for c in classifications]
    if engagements is None or len(engagements) != len(classifications):
        weights = [c["conviction"] * r for c, r in zip(classifications, rel_w)]
    else:
        weights = [c["conviction"] * r * _engagement_weight(e)
                   for c, r, e in zip(classifications, rel_w, engagements)]
    total_w = sum(weights)
    if total_w == 0:
        # All-zero-weight = no on-topic signal. Report as "uniform neutral" so
        # the composite calculator can include it as a low-conviction read; the
        # n_off_topic counter lets downstream UI flag "no real HN signal" to
        # distinguish from a genuine neutral 50/50 read.
        return {"bull": 0.0, "bear": 0.0, "neutral": 1.0, "avg_conviction": 0.0,
                "engagement_weighted": engagements is not None,
                "n_off_topic": sum(1 for c in classifications if c.get("relevance") == "none"),
                "n_mention":   sum(1 for c in classifications if c.get("relevance") == "mention"),
                "n_primary":   sum(1 for c in classifications if c.get("relevance") == "primary"),
                "n_scored":    len(classifications)}
    bull = sum(w for c, w in zip(classifications, weights) if c["sentiment"] == "bullish") / total_w
    bear = sum(w for c, w in zip(classifications, weights) if c["sentiment"] == "bearish") / total_w
    neut = sum(w for c, w in zip(classifications, weights) if c["sentiment"] == "neutral") / total_w
    # Only the on-topic subset contributes to avg_conviction — keeps the metric
    # honest when half the batch is off-topic noise.
    on_topic = [c for c in classifications if c.get("relevance") != "none"]
    avg_conv = (sum(c["conviction"] for c in on_topic) / len(on_topic)) if on_topic else 0.0
    return {
        "bull": round(bull, 3),
        "bear": round(bear, 3),
        "neutral": round(neut, 3),
        "avg_conviction": round(avg_conv, 3),
        "engagement_weighted": engagements is not None,
        "n_off_topic": sum(1 for c in classifications if c.get("relevance") == "none"),
        "n_mention": sum(1 for c in classifications if c.get("relevance") == "mention"),
        "n_primary": sum(1 for c in classifications if c.get("relevance") == "primary"),
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
    classifications, err, _raw = classify_messages(
        bodies, raw["ticker"], model=model,
        asset_class=raw.get("asset_class"))
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
        "n_off_topic": pcts.get("n_off_topic") if pcts else None,
        "n_mention": pcts.get("n_mention") if pcts else None,
        "n_primary": pcts.get("n_primary") if pcts else None,
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

    classifications, err, _raw = classify_messages(
        bodies, raw["ticker"], model=model,
        asset_class=raw.get("asset_class"))
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
        "n_off_topic": pcts.get("n_off_topic") if pcts else None,
        "n_mention": pcts.get("n_mention") if pcts else None,
        "n_primary": pcts.get("n_primary") if pcts else None,
    }, None


def process_reddit(raw, model):
    if not raw or not raw.get("posts"):
        return None, None
    posts = raw["posts"]
    # v1.9.2: flatten posts + top comments into one scoring batch. Comment bodies
    # often carry the meatier signal than the OP. Engagement weighting picks up
    # both when available — OAuth gives per-comment scores; RSS-sourced comments
    # have score=None and get a uniform low weight (still scored, just not boosted).
    items = []  # list of (body, engagement, kind) tuples for ranking
    n_posts = 0
    n_comments = 0
    for p in posts:
        title = p.get("title", "")
        if p.get("selftext_excerpt"):
            title += " — " + p["selftext_excerpt"][:200]
        if title:
            post_engagement = (p.get("score") or 0) + 2 * (p.get("num_comments") or 0)
            items.append((title, post_engagement, "post"))
            n_posts += 1
        for c in (p.get("top_comments") or []):
            body = (c.get("body") or "").strip()
            if not body:
                continue
            # RSS-sourced comments lack `score`. Floor at 3 so they don't get
            # crushed out of the batch by zero-engagement weighting.
            comment_engagement = c.get("score") if c.get("score") is not None else 3
            items.append((body, comment_engagement, "comment"))
            n_comments += 1
    if not items:
        return None, None
    # Rank all items by engagement desc, cap at MAX_MESSAGES_PER_TICKER so the
    # most impactful posts + comments compete for slots together.
    items.sort(key=lambda x: x[1], reverse=True)
    items = items[:MAX_MESSAGES_PER_TICKER]
    bodies      = [x[0] for x in items]
    engagements = [x[1] for x in items]

    classifications, err, _raw = classify_messages(
        bodies, raw["ticker"], model=model,
        asset_class=raw.get("asset_class"))
    if err:
        return None, f"LLM scoring failed: {err}"
    engagements = engagements[:len(classifications)]
    pcts = llm_pcts(classifications, engagements=engagements)
    return {
        "present": True,
        "n_posts": n_posts,
        "n_comments": n_comments,
        "n_scored_bodies": len(classifications),
        "mention_count": raw.get("mention_count", len(posts)),
        "engagement_source": "oauth" if any((p.get("source") == "oauth") for p in posts) else "rss",
        "llm_bull_pct": pcts["bull"] if pcts else None,
        "llm_bear_pct": pcts["bear"] if pcts else None,
        "llm_neutral_pct": pcts["neutral"] if pcts else None,
        "llm_avg_conviction": pcts["avg_conviction"] if pcts else None,
        "n_off_topic": pcts.get("n_off_topic") if pcts else None,
        "n_mention": pcts.get("n_mention") if pcts else None,
        "n_primary": pcts.get("n_primary") if pcts else None,
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
    conviction_raw = round(sum(convictions) / len(convictions), 3) if convictions else 0.0

    # Volume/coverage haircut (gap #3): a read off 2 messages must not carry the
    # same conviction as one off 50. Dampen conviction by how much on-topic sample
    # actually backs it — log-scaled, reaching ~full confidence at TARGET_N items.
    # This flows through to the contrarian-flag thresholds AND every downstream
    # consumer (the Risk Simulator's §4 factor, the Contrarian Setups panel), so a
    # thin sample can no longer fire a high-conviction flag.
    import math as _math
    def _sample_n(s):
        if not s or not s.get("present"):
            return 0
        if s.get("n_scored_bodies") is not None:
            return s["n_scored_bodies"]
        return (s.get("n_messages") or 0) + (s.get("n_posts") or 0) + (s.get("n_comments") or 0)
    n_total = _sample_n(st_summary) + _sample_n(rd_summary) + _sample_n(hn_summary)
    TARGET_N = 25  # on-topic items for ~full-confidence; below this, conviction is dampened
    coverage = round(min(1.0, _math.log1p(n_total) / _math.log1p(TARGET_N)), 3) if n_total > 0 else 0.0
    conviction = round(conviction_raw * coverage, 3)

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
        "conviction_raw": conviction_raw,   # pre-coverage (text-only) conviction
        "coverage": coverage,               # 0-1 sample-size confidence multiplier
        "n_total": n_total,                 # on-topic items backing this read
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
        nc = rd.get("n_comments")
        post_str = f"{rd.get('n_posts')} posts" + (f" + {nc} comments" if nc else "")
        parts.append(
            f"Reddit: {post_str}, "
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

    # Resolve asset_class once and inject into every raw cache so the per-source
    # processors can pass it to classify_messages → _company_label. StockTwits
    # and Reddit raw files store it; the HN fetcher doesn't yet. Fall back to a
    # crude ticker-pattern guess so older caches without the field still get a
    # useful prompt subject.
    inferred_asset_class = (st_raw or rd_raw or hn_raw or {}).get("asset_class")
    if not inferred_asset_class:
        if ticker.upper().endswith(".KL"):
            inferred_asset_class = "klse"
        elif ticker.upper() in {"BTC","ETH","SOL","BNB","XRP","HBAR","HYPE","ENA","ONDO","ADA","DOGE"}:
            inferred_asset_class = "crypto"
        else:
            inferred_asset_class = "us_equity"
    for raw in (st_raw, rd_raw, hn_raw):
        if raw is not None and "asset_class" not in raw:
            raw["asset_class"] = inferred_asset_class

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
