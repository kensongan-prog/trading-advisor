"""
test_earnings_skip.py — context gauges (SPY) skip the yfinance earnings call.

Why this exists: SPY is the dashboard's index/regime gauge — an ETF with no
company earnings. yfinance's `.calendar` (calendarEvents quoteSummary module)
404s for ETFs ("No fundamentals data found for symbol: SPY") and logs the HTTP
error as noise on every build. We skip the earnings fetch for tickers in
EARNINGS_SKIP_TICKERS. This pins that contract: the calendar call is made for a
normal equity but NOT for a skip-listed gauge.
"""
import pytest

import dashboard


def test_spy_in_skip_list():
    # Guards against the constant being deleted/renamed — the guard is dead without it.
    assert "SPY" in dashboard.EARNINGS_SKIP_TICKERS


def _fake_yf_module(calendar_flag):
    """Build a fake `yfinance` whose Ticker records whether `.calendar` is read."""
    pd = pytest.importorskip("pandas")

    class _FakeTicker:
        def __init__(self, ticker):
            self._ticker = ticker

        @property
        def info(self):
            return {"shortName": self._ticker, "currency": "USD"}

        def history(self, period="1y"):
            # ~210 business days ending today so SMA200/ATR compute and the
            # Twelve Data freshness fallback (price_date < expected) doesn't fire.
            idx = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=210)
            return pd.DataFrame(
                {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000},
                index=idx,
            )

        @property
        def calendar(self):
            calendar_flag["accessed"] = True
            return {}

    class _FakeYF:
        Ticker = _FakeTicker

    return _FakeYF


def _run(monkeypatch, ticker):
    flag = {"accessed": False}
    monkeypatch.setitem(__import__("sys").modules, "yfinance", _fake_yf_module(flag))
    monkeypatch.setattr(dashboard, "cache_set", lambda *a, **k: None)  # don't pollute real cache
    out, _ = dashboard.fetch_yfinance_ticker(ticker, force=True)
    return out, flag["accessed"]


def test_calendar_skipped_for_spy(monkeypatch):
    out, accessed = _run(monkeypatch, "SPY")
    assert accessed is False           # earnings call never made
    assert out.get("next_earnings") is None
    assert out.get("error") is None    # the rest of the fetch still succeeds


def test_calendar_called_for_normal_equity(monkeypatch):
    _out, accessed = _run(monkeypatch, "AAPL")
    assert accessed is True            # normal names still fetch earnings
