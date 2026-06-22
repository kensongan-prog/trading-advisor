"""
test_health_crypto_news.py — health must look up caches by their real filenames.

Bug (2026-06-15): the Data Health panel showed "9 source(s) refreshable" forever,
even after a full refresh. Cause: two health *lookup* mismatches, not real gaps —
  (a) crypto_news caches are keyed by CoinGecko slug (bitcoin.json), but health
      keyed them by lowercased ticker (btc.json) → every crypto name read as
      missing & refreshable, and no refresh could ever fix it;
  (b) SPY is intentionally never us_news-fetched (it's the index gauge), yet
      health expected a SPY.json and flagged it missing.
These pin both so the "refreshable" count stays honest.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"))
import health  # noqa: E402


def test_crypto_news_key_maps_ticker_to_slug():
    assert health._crypto_news_key("BTC") == "bitcoin"
    assert health._crypto_news_key("eth") == "ethereum"
    assert health._crypto_news_key("HBAR") == "hedera-hashgraph"
    assert health._crypto_news_key("HYPE") == "hyperliquid"
    assert health._crypto_news_key("ENA") == "ethena"
    assert health._crypto_news_key("ZZZ") == "zzz"  # unknown → lowercase fallback


def test_crypto_news_resolved_by_slug_is_fresh_not_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "CACHE_ROOT", tmp_path)
    d = tmp_path / "crypto_news"
    d.mkdir()
    # File named by slug, as news_glyph actually writes it — NOT btc.json.
    (d / "bitcoin.json").write_text(json.dumps({
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "items": [{"title": "BTC headline"}],
    }))
    recs = health.collect_health({"crypto": ["BTC"]})
    cn = [r for r in recs if r["source"] == "crypto_news" and r["ticker"] == "BTC"]
    assert len(cn) == 1
    assert cn[0]["state"] == health.STATE_FRESH, "slug-named cache must be found, not 'missing'"


def test_spy_excluded_from_us_news(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "CACHE_ROOT", tmp_path)
    recs = health.collect_health({"us": ["SPY"]})
    spy_news = [r for r in recs if r["source"] == "us_news" and r["ticker"] == "SPY"]
    assert spy_news == [], "SPY is not us_news-fetched; it must not appear as missing/refreshable"
