"""
test_watchlist_quality_flags.py — structural-quality warnings at wl.py add-time
(Guardrails Phase B).

GPUS-class names went through `wl.py add` with zero warnings before this
existed. Two things pinned here:
1. `quality_flags_for()` — the cross-skill bridge to dashboard/quality_flags.py
   (same pattern j.py already uses for portfolio sync — see wl.py's docstring).
2. `fetch_us_meta` / `fetch_klse_meta` / `fetch_crypto_meta` now carry the
   structural-quality fields (market_cap, short_pct_float, beta, analyst_count,
   or crypto market_cap/volume) so quality_flags_for() has something to read.
"""
import pytest

import wl

GPUS_META = {
    "price": 0.17, "market_cap": 53_212_272, "avg_vol_30d": 8_000_000,
    "short_pct_float": 0.4997, "beta": 2.594, "analyst_count": None,
    "currency": "USD",
}
AAPL_META = {
    "price": 275.0, "market_cap": 4_323_663_937_536, "avg_vol_30d": 50_000_000,
    "short_pct_float": 0.0098, "beta": 1.086, "analyst_count": 42,
    "currency": "USD",
}


class TestQualityFlagsFor:
    def test_gpus_style_meta_flags(self):
        flags = wl.quality_flags_for(GPUS_META, "us")
        assert set(flags) == {"PENNY", "LOW_MC", "ILLIQUID", "HIGH_SHORT", "HIGH_BETA", "NO_COVERAGE"}

    def test_clean_meta_no_flags(self):
        assert wl.quality_flags_for(AAPL_META, "us") == []

    def test_none_meta_returns_empty(self):
        assert wl.quality_flags_for(None, "us") == []

    def test_klse_uses_myr_penny_threshold(self):
        row = {"price": 0.30, "currency": "MYR", "analyst_count": 1}
        assert wl.quality_flags_for(row, "klse") == []   # RM0.30 > RM0.20 floor

    def test_crypto_low_rank(self):
        row = {"market_cap": 5_000_000, "market_cap_rank": 500, "volume": 6_000_000}
        assert "LOW_MC_RANK" in wl.quality_flags_for(row, "crypto")

    def test_no_pump_dump_composite_at_add_time(self):
        # Add-time meta has no price history / vol_ratio, so pump_dump_risk's
        # conservative "no volume evidence -> no fire" guard applies even for
        # an otherwise-alarming structural profile.
        flags = wl.quality_flags_for(GPUS_META, "us")
        assert "PUMP_DUMP_RISK" not in flags


def _fake_yf_module():
    pd = pytest.importorskip("pandas")

    class _FakeTicker:
        def __init__(self, ticker):
            self._ticker = ticker

        @property
        def info(self):
            return {
                "shortName": self._ticker, "longName": self._ticker, "currency": "USD",
                "marketCap": 53_212_272, "averageVolume": 8_000_000,
                "shortPercentOfFloat": 0.4997, "beta": 2.594, "numberOfAnalystOpinions": None,
            }

        def history(self, period="5d"):
            idx = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=5)
            return pd.DataFrame({"Close": 0.17}, index=idx)

    class _FakeYF:
        Ticker = _FakeTicker

    return _FakeYF


def test_fetch_us_meta_carries_quality_fields(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "yfinance", _fake_yf_module())
    meta, err = wl.fetch_us_meta("GPUS")
    assert err is None
    for key in ("market_cap", "avg_vol_30d", "short_pct_float", "beta", "analyst_count", "currency"):
        assert key in meta, f"fetch_us_meta dropped {key!r} — quality_flags_for needs it"
    assert meta["short_pct_float"] == 0.4997


def test_fetch_klse_meta_carries_quality_fields(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "yfinance", _fake_yf_module())
    meta, err = wl.fetch_klse_meta("9431.KL")
    assert err is None
    for key in ("market_cap", "avg_vol_30d", "short_pct_float", "beta", "analyst_count"):
        assert key in meta


def test_fetch_crypto_meta_carries_quality_fields(monkeypatch):
    fake_response = {
        "id": "test-coin", "name": "TestCoin", "market_cap_rank": 500, "categories": [],
        "market_data": {
            "current_price": {"usd": 0.01},
            "market_cap": {"usd": 5_000_000},
            "total_volume": {"usd": 6_000_000},
        },
    }
    monkeypatch.setattr(wl, "http_json", lambda url, headers=None, timeout=15: (fake_response, None))
    meta, err = wl.fetch_crypto_meta("TESTCOIN")
    assert err is None
    assert meta["market_cap"] == 5_000_000
    assert meta["volume"] == 6_000_000
