"""
test_us_status.py — Phase 1 status gating for US/KLSE tickers.

Why these tests exist: this is the function that decides whether a watchlist
name is P1_READY (the dashboard's actionable signal). Wrong classification
here either misses real setups (false negatives = lost edge) or surfaces bad
ones (false positives = lost capital). Pin the gates explicitly.
"""
import pytest
from dashboard import us_status


def _base(ticker="AUPH", **kwargs):
    """A baseline 'should-be-P1_READY' ticker dict. Override fields as needed."""
    base = {
        "ticker": ticker,
        "price": 100.0,
        "sma20": 100.0,
        "sma50": 95.0,
        "sma200": 85.0,
        "rsi14": 42.0,
        "change_pct": -0.5,
        "sma50_slope_pct": 0.5,
        "vol_ratio": 1.0,
        "next_earnings": None,
    }
    base.update(kwargs)
    return base


class TestP1Ready:
    def test_clean_p1_ready(self):
        badge, label, _ = us_status(_base())
        assert badge == "🟢"
        assert label == "P1_READY"

    def test_p1_ready_at_rsi_band_edges(self):
        # RSI exactly 35 → still in band
        _, lbl_lo, _ = us_status(_base(rsi14=35.0))
        # RSI exactly 50 → still in band
        _, lbl_hi, _ = us_status(_base(rsi14=50.0))
        assert lbl_lo == "P1_READY"
        assert lbl_hi == "P1_READY"

    def test_p1_with_no_macro_events(self):
        # macro_events=None is the default; ensure it doesn't crash
        badge, label, _ = us_status(_base(), macro_events=None)
        assert label == "P1_READY"


class TestBlocked:
    def test_spy_is_context(self):
        _, label, _ = us_status(_base(ticker="SPY"))
        assert label == "CONTEXT"

    def test_data_missing_price(self):
        _, label, _ = us_status(_base(price=None))
        assert label == "DATA"

    def test_new_listing_no_sma200(self):
        # No SMA200 = recent IPO; can't apply P1 cleanly
        _, label, _ = us_status(_base(sma200=None))
        assert label == "NEW"

    def test_downtrend(self):
        # price < SMA50 < SMA200 → full downtrend
        _, label, _ = us_status(_base(price=80.0, sma50=85.0, sma200=90.0))
        assert label == "DOWNTREND"

    def test_below_sma50_only(self):
        # price < SMA50 but SMA50 > SMA200 (still in golden cross)
        _, label, _ = us_status(_base(price=90.0, sma50=95.0, sma200=85.0))
        assert label == "BELOW50"

    def test_no_golden_cross(self):
        # price > SMA50 but SMA50 < SMA200 → no golden cross
        _, label, _ = us_status(_base(price=92.0, sma50=90.0, sma200=95.0))
        assert label == "NO_GOLDEN_CROSS"

    def test_overbought(self):
        _, label, _ = us_status(_base(rsi14=75.0))
        assert label == "OVERBOUGHT"


class TestWarnings:
    def test_oversold_below_30(self):
        _, label, _ = us_status(_base(rsi14=25.0))
        assert label == "OVERSOLD"

    def test_violent_day(self):
        # ±5% day → wait for stabilization
        _, label, _ = us_status(_base(change_pct=-7.0))
        assert label == "VIOLENT"

    def test_heavy_volume(self):
        # vol_ratio > 1.3 → distribution risk
        _, label, _ = us_status(_base(vol_ratio=1.5))
        assert label == "HEAVY_VOLUME"

    def test_extended_above_rsi_band(self):
        # RSI > 60 but < 70 → EXTENDED
        _, label, _ = us_status(_base(rsi14=65.0))
        assert label == "EXTENDED"

    def test_near_macro_event(self):
        # FOMC in 24h → NEAR_FOMC warning
        events = [{"type": "FOMC", "hours_until": 24}]
        _, label, _ = us_status(_base(), macro_events=events)
        assert label == "NEAR_FOMC"

    def test_macro_event_outside_72h_passes(self):
        # FOMC in 96h is outside the 3-day pre-event window
        events = [{"type": "FOMC", "hours_until": 96}]
        _, label, _ = us_status(_base(), macro_events=events)
        assert label == "P1_READY"


class TestEdgeCases:
    def test_sma50_falling_warning(self):
        # SMA50 slope < -0.5% → SMA50_FALLING
        _, label, _ = us_status(_base(sma50_slope_pct=-1.0))
        assert label == "SMA50_FALLING"

    def test_sma50_flat_passes(self):
        # Slope exactly -0.5% should not trigger (boundary)
        _, label, _ = us_status(_base(sma50_slope_pct=-0.5))
        # The boundary check is `< -0.5`, so -0.5 itself passes
        assert label == "P1_READY"

    def test_error_field_returns_data(self):
        _, label, _ = us_status({"ticker": "X", "error": "yfinance timeout"})
        assert label == "DATA"
