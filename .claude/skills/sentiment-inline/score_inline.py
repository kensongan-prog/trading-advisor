#!/usr/bin/env python3
"""
score_inline.py — manually re-score sentiment using classifications supplied by
the current analyst session instead of the normal headless scorer.

Why this exists
---------------
sentiment-cache's normal path uses the authenticated OpenAI/Codex route to
classify each batch of social messages. For an explicit manual diagnostic, an
interactive analyst session can instead supply reviewed classifications through
this dump/ingest round trip without creating a second headless provider path.

The catch: this only works while a session is driving it. It is NOT a headless
scorer — automated builds/watcher refreshes still use sentiment_cache.py.

How it reuses the real pipeline (no format drift)
-------------------------------------------------
The ONLY thing that differs from sentiment_cache.score_ticker is the LLM call,
`classify_messages`. So this script monkeypatches *only* that one function and
lets the real process_*/llm_pcts/compute_composite/build_rationale/save_cache do
everything else — identical engagement weighting, relevance downweighting, the
v2.6.0 coverage haircut, composite math, rationale, and on-disk cache format.

Two phases, one round-trip file (the "inbox"):
  1. dump   — capture the exact body batches the real scorer would send to the
              LLM, into an inbox JSON. (classify_messages is replaced by a stub
              that records bodies and returns a benign placeholder.)
  2. <you>  — the session reads the inbox and fills a "scores" array on each batch
              (one {sentiment, conviction, relevance} per body, in order).
  3. ingest — replay score_ticker with classify_messages replaced by a stub that
              returns YOUR scores (matched by content hash), then save_cache.

Usage:
    python3 score_inline.py dump --stale [--ttl-hours 24] [--inbox PATH]
    python3 score_inline.py dump TICK1 TICK2 ...
    python3 score_inline.py dump --all
    # ... session fills "scores" on each batch in the inbox ...
    python3 score_inline.py ingest [PATH]      # defaults to the same inbox
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SENTIMENT_CACHE_DIR = SCRIPT_DIR.parent / "sentiment-cache"
if str(SENTIMENT_CACHE_DIR) not in sys.path:
    sys.path.insert(0, str(SENTIMENT_CACHE_DIR))

import sentiment_cache as sc  # noqa: E402

DEFAULT_INBOX = Path("/tmp/ta_sentiment_inbox.json")
INLINE_MODEL_TAG = "inline (claude session, hand-scored)"


def _key(ticker, capped_bodies):
    """Stable content key for a body batch — identical in dump and ingest since
    both extract from the same raw caches through the same code path."""
    h = hashlib.sha1()
    h.update((ticker or "").upper().encode("utf-8", "replace"))
    h.update(b"\x01")
    h.update("\n".join(capped_bodies).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def _cap(messages):
    """Mirror _classify_one_attempt: cap to MAX_MESSAGES_PER_TICKER, 400 chars each."""
    return [str(m)[:400] for m in (messages or [])[: sc.MAX_MESSAGES_PER_TICKER]]


def _neutral(n):
    return [{"sentiment": "neutral", "conviction": 0.0, "relevance": "primary"} for _ in range(n)]


def _norm_score(s):
    """Validate one session-produced score the same way classify_messages would."""
    if not isinstance(s, dict):
        return {"sentiment": "neutral", "conviction": 0.0, "relevance": "primary"}
    sent = str(s.get("sentiment", "neutral")).lower().strip()
    if sent not in ("bullish", "bearish", "neutral"):
        sent = "neutral"
    try:
        conv = max(0.0, min(1.0, float(s.get("conviction", 0.0))))
    except Exception:
        conv = 0.0
    rel = str(s.get("relevance", "primary")).lower().strip()
    if rel not in ("primary", "mention", "none"):
        rel = "primary"
    return {"sentiment": sent, "conviction": conv, "relevance": rel}


def _wrap_process_for_source():
    """Wrap the three process_* fns so the capturing stub can label each batch's
    source (metadata only — helps the session score with the right lens).
    Returns {name: original} so callers can restore and not leak global state."""
    originals = {}
    for name in ("process_stocktwits", "process_reddit", "process_hackernews"):
        orig = getattr(sc, name)
        originals[name] = orig
        src = name.replace("process_", "")

        def mk(orig, src):
            def wrapped(raw, model):
                sc._INLINE_SRC = src
                return orig(raw, model)
            return wrapped
        setattr(sc, name, mk(orig, src))
    return originals


# ── Phase 1: dump ──────────────────────────────────────────────────────────
def dump_tickers(tickers, inbox_path=DEFAULT_INBOX):
    captured = []

    def _capture(messages, ticker, model=None, timeout=60, asset_class=None):
        capped = _cap(messages)
        if capped:
            captured.append({
                "ticker": (ticker or "").upper(),
                "source": getattr(sc, "_INLINE_SRC", "?"),
                "asset_class": asset_class,
                "key": _key(ticker, capped),
                "n": len(capped),
                "bodies": capped,
                "scores": None,  # ← session fills this: one obj per body, in order
            })
        return _neutral(len(capped)), None, ""

    orig_classify = sc.classify_messages
    orig_process = _wrap_process_for_source()
    sc.classify_messages = _capture
    try:
        scored_tickers = []
        for t in tickers:
            sc.score_ticker(t, verbose=False)  # drives real body extraction → _capture
            scored_tickers.append(t.upper())
    finally:
        sc.classify_messages = orig_classify
        for name, fn in orig_process.items():
            setattr(sc, name, fn)

    inbox = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scorer": "claude-code-session",
        "rubric": (
            "Per body return {relevance: primary|mention|none, "
            "sentiment: bullish|bearish|neutral, conviction: 0.0-1.0}. "
            "relevance=primary: ticker/company is the main subject; mention: appears but not the "
            "focus; none: ticker doesn't actually appear (look-alike word). conviction = how CLEAR "
            "the sentiment is (sarcasm/hedge lowers it), not how strong the directional view."
        ),
        "tickers": scored_tickers,
        "batches": captured,
    }
    Path(inbox_path).write_text(json.dumps(inbox, indent=2), encoding="utf-8")
    return inbox


# ── Phase 2 happens in the session: fill "scores" on each batch ──────────────


# ── Phase 3: ingest ─────────────────────────────────────────────────────────
def ingest(scores_path=DEFAULT_INBOX):
    data = json.loads(Path(scores_path).read_text(encoding="utf-8"))
    batches = data.get("batches", [])
    lookup = {}
    missing = []
    for b in batches:
        scores = b.get("scores")
        if not scores:
            missing.append((b.get("ticker"), b.get("source")))
            continue
        lookup[b["key"]] = [_norm_score(s) for s in scores]
    if missing:
        print("WARNING: batches with no scores (will be neutral-filled): "
              + ", ".join(f"{t}/{s}" for t, s in missing))

    def _return(messages, ticker, model=None, timeout=60, asset_class=None):
        capped = _cap(messages)
        scores = lookup.get(_key(ticker, capped))
        if scores is None:
            return _neutral(len(capped)), None, ""
        out = [scores[i] if i < len(scores) else
               {"sentiment": "neutral", "conviction": 0.0, "relevance": "primary"}
               for i in range(len(capped))]
        return out, None, ""

    tickers_with_data = []
    seen = set()
    for b in batches:
        t = b.get("ticker")
        if t and t not in seen:
            seen.add(t)
            tickers_with_data.append(t)

    orig_classify = sc.classify_messages
    sc.classify_messages = _return
    summary = []
    try:
        for t in tickers_with_data:
            result = sc.score_ticker(t, verbose=False)
            result["model"] = INLINE_MODEL_TAG
            sc.save_cache(t, result)
            c = result["composite"]
            summary.append((t, c.get("badge", "—"), c.get("label", "?"),
                            c.get("bull_score"), c.get("conviction"), c.get("contrarian_flag")))
    finally:
        sc.classify_messages = orig_classify

    print(f"Wrote {len(summary)} sentiment cache file(s) from session scoring.\n")
    print(f"{'TICKER':<10}{'BADGE':<6}{'LABEL':<16}{'BULL':>6}{'CONV':>6}  FLAG")
    for t, bdg, lbl, bs, cv, fl in summary:
        bs_s = f"{bs:.0%}" if bs is not None else "—"
        cv_s = f"{cv:.0%}" if cv is not None else "—"
        print(f"{t:<10}{bdg:<6}{lbl:<16}{bs_s:>6}{cv_s:>6}  {fl or ''}")
    return summary


# ── Ticker selection ─────────────────────────────────────────────────────────
def stale_tickers(ttl_hours=24.0):
    """Watchlist names whose sentiment cache is missing or older than ttl_hours."""
    now = datetime.now(timezone.utc)
    out = []
    for t in sc.parse_watchlist():
        d = sc.load_cache(t)
        if not d:
            out.append(t)
            continue
        sa = d.get("scored_at", "")
        try:
            dt = datetime.fromisoformat(sa.replace("Z", "+00:00"))
            if (now - dt).total_seconds() / 3600.0 > ttl_hours:
                out.append(t)
        except Exception:
            out.append(t)
    return out


def main():
    sc.load_env()
    ap = argparse.ArgumentParser(description="Session-supplied manual sentiment classification.")
    ap.add_argument("mode", choices=["dump", "ingest"])
    ap.add_argument("args", nargs="*", help="dump: tickers; ingest: scored-inbox path")
    ap.add_argument("--stale", action="store_true", help="dump: select stale/missing watchlist names")
    ap.add_argument("--all", action="store_true", help="dump: select entire watchlist")
    ap.add_argument("--ttl-hours", type=float, default=24.0)
    ap.add_argument("--inbox", default=str(DEFAULT_INBOX))
    a = ap.parse_args()

    if a.mode == "dump":
        if a.all:
            tickers = sc.parse_watchlist()
        elif a.stale:
            tickers = stale_tickers(a.ttl_hours)
        else:
            tickers = [t.upper() for t in a.args]
        if not tickers:
            print("No tickers selected (use TICKERS, --stale, or --all).", file=sys.stderr)
            return 1
        inbox = dump_tickers(tickers, a.inbox)
        n_batches = len(inbox["batches"])
        n_bodies = sum(b["n"] for b in inbox["batches"])
        with_data = sorted({b["ticker"] for b in inbox["batches"]})
        no_data = [t for t in tickers if t.upper() not in set(with_data)]
        print(f"Dumped {n_batches} batch(es), {n_bodies} bodies across "
              f"{len(with_data)} ticker(s) → {a.inbox}")
        if no_data:
            print(f"No raw social data (skipped): {', '.join(no_data)}")
        print("\nNext: fill the \"scores\" array on each batch (one "
              "{sentiment,conviction,relevance} per body, in order), then run:")
        print(f"  python3 {Path(__file__).name} ingest {a.inbox}")
        return 0

    # ingest
    path = a.args[0] if a.args else a.inbox
    ingest(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
