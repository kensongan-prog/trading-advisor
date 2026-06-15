"""
test_sentiment_inline.py — the session-scored sentiment round-trip.

score_inline.py re-scores sentiment using the session model instead of OpenRouter
by monkeypatching only sentiment_cache.classify_messages: `dump` captures the body
batches the real scorer would send, `ingest` replays score_ticker with supplied
classifications. Everything else (llm_pcts, compute_composite, coverage haircut,
cache format) is the real pipeline. These tests pin: (1) the content key, (2) the
dump→ingest round-trip writing a correct cache, and (3) no global-state leak.
"""
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / ".claude" / "skills"
for sub in ("sentiment-cache", "sentiment-inline"):
    p = str(SKILLS / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import sentiment_cache as sc  # noqa: E402
import score_inline as si      # noqa: E402


def test_key_stable_case_insensitive_and_distinct():
    base = si._key("nvda", ["alpha", "beta"])
    assert base == si._key("NVDA", ["alpha", "beta"])   # ticker case-folded
    assert base != si._key("amd", ["alpha", "beta"])    # different ticker
    assert base != si._key("nvda", ["alpha", "gamma"])  # different bodies


def test_round_trip_writes_real_composite(tmp_path, monkeypatch):
    raw = {"ticker": "TEST", "asset_class": "us_equity", "messages": [
        {"body": "to the moon, loading up", "likes": 5},
        {"body": "undervalued gem, buying more", "likes": 3},
        {"body": "best setup on my board", "likes": 2},
    ]}
    monkeypatch.setattr(sc, "load_stocktwits", lambda t: raw)
    monkeypatch.setattr(sc, "load_reddit", lambda t: None)
    monkeypatch.setattr(sc, "load_hackernews", lambda t: None)
    monkeypatch.setattr(sc, "cache_path", lambda t: tmp_path / f"{t.upper()}.json")

    inbox_path = tmp_path / "inbox.json"
    inbox = si.dump_tickers(["TEST"], inbox_path)

    st = [b for b in inbox["batches"] if b["source"] == "stocktwits"]
    assert len(st) == 1 and st[0]["n"] == 3        # captured the 3 ST bodies

    for b in inbox["batches"]:
        b["scores"] = [{"sentiment": "bullish", "conviction": 0.9, "relevance": "primary"}] * b["n"]
    json.dump(inbox, open(inbox_path, "w"))

    si.ingest(inbox_path)

    written = json.loads((tmp_path / "TEST.json").read_text())
    c = written["composite"]
    assert c["bull_score"] >= 0.9                   # all-bullish read flows through
    assert written["model"].startswith("inline")    # tagged as session-scored
    assert "scored_at" in written and written["scored_at"]   # fresh timestamp


def test_no_global_classify_leak(tmp_path, monkeypatch):
    # After a dump+ingest, sentiment_cache.classify_messages must be restored
    # (it would otherwise poison any later test importing the module).
    before = sc.classify_messages
    raw = {"ticker": "ZZ", "asset_class": "us_equity",
           "messages": [{"body": "great", "likes": 1}]}
    monkeypatch.setattr(sc, "load_stocktwits", lambda t: raw)
    monkeypatch.setattr(sc, "load_reddit", lambda t: None)
    monkeypatch.setattr(sc, "load_hackernews", lambda t: None)
    monkeypatch.setattr(sc, "cache_path", lambda t: tmp_path / f"{t.upper()}.json")
    inbox_path = tmp_path / "inbox.json"
    inbox = si.dump_tickers(["ZZ"], inbox_path)
    for b in inbox["batches"]:
        b["scores"] = [{"sentiment": "neutral", "conviction": 0.1, "relevance": "primary"}] * b["n"]
    json.dump(inbox, open(inbox_path, "w"))
    si.ingest(inbox_path)
    assert sc.classify_messages is before
