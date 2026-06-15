"""
test_news_ttl_reconciliation.py — keep the news refresh TTLs honest vs Data Health.

Bug (2026-06-15): health.py flagged us_news stale at 48h, but news_cache's
P3_context (plain watchlist names) only refreshed after 168h — so --refresh-stale
silently skipped names the Data Health panel showed as "stale & refreshable." The
panel must never promise a refresh the queue won't deliver: the loosest news
priority TTL must be <= health's us_news TTL.
"""
import health
import news_cache


def test_loosest_news_ttl_not_looser_than_health():
    loosest = max(news_cache.PRIORITY_TTL_HOURS.values())
    assert loosest <= health.TTL_HOURS["us_news"], (
        f"news P3 TTL {loosest}h > health us_news TTL {health.TTL_HOURS['us_news']}h "
        "→ health will flag names stale that --refresh-stale won't refresh")


def test_active_priorities_refresh_at_least_as_often_as_health():
    # P0/P1/P2 may be tighter than health (fine — they stay fresher); none looser.
    for prio, ttl in news_cache.PRIORITY_TTL_HOURS.items():
        assert ttl <= health.TTL_HOURS["us_news"], f"{prio} TTL {ttl}h looser than health"


def test_stale_p3_name_is_now_refreshable(monkeypatch):
    # A plain watchlist name older than health's 48h must read stale at P3.
    monkeypatch.setattr(news_cache, "cache_age_hours", lambda t: 94.5)
    assert news_cache.is_stale("RYDE", "P3_context") is True
