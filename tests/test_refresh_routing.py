"""
test_refresh_routing.py — dashboard._route_refresh source→flag/CLI routing.

Pins the v2.4.1 "real per-source refresh": refreshing a single source must enable
ONLY that source's REFRESH_VIA flag (not the whole stale batch), and a source that
shares a flag with siblings enables exactly that shared flag. Guards against the
per-source button silently reverting to a global refresh.
"""
import argparse
import health
import dashboard


def _args():
    # Mirror the dashboard's refresh-* argparse dests, all off.
    return argparse.Namespace(
        refresh_news=False, refresh_news_glyph=False, refresh_sentiment=False,
        refresh_polymarket=False, with_discovery=False,
    )


def test_polymarket_sets_only_polymarket_flag():
    a = _args()
    dashboard._route_refresh(["polymarket"], a, health, label="t")
    assert a.refresh_polymarket is True
    # nothing else turned on — true single-source scope
    assert (a.refresh_news, a.refresh_sentiment, a.refresh_news_glyph, a.with_discovery) == (False, False, False, False)


def test_us_news_sets_only_news_flag():
    a = _args()
    dashboard._route_refresh(["us_news"], a, health, label="t")
    assert a.refresh_news is True
    assert a.refresh_sentiment is False and a.refresh_polymarket is False


def test_sentiment_subsource_sets_sentiment_flag():
    a = _args()
    dashboard._route_refresh(["stocktwits_sentiment"], a, health, label="t")
    assert a.refresh_sentiment is True
    assert a.refresh_news is False


def test_screener_sets_discovery_flag():
    a = _args()
    dashboard._route_refresh(["screener"], a, health, label="t")
    assert a.with_discovery is True


def test_agent_only_source_sets_no_flags():
    a = _args()
    dashboard._route_refresh(["crypto_unlocks"], a, health, label="t")
    assert (a.refresh_news, a.refresh_sentiment, a.refresh_polymarket,
            a.refresh_news_glyph, a.with_discovery) == (False, False, False, False, False)


def test_stale_batch_sets_union_of_flags():
    # --refresh-stale path: multiple sources → union of their flags
    a = _args()
    dashboard._route_refresh({"polymarket", "us_news", "screener"}, a, health, label="t")
    assert a.refresh_polymarket and a.refresh_news and a.with_discovery
    assert a.refresh_sentiment is False  # no sentiment source in the set
