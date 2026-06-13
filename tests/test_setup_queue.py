"""
test_setup_queue.py — Phase-1 gate + doctrine level math.

setup_queue surfaces watchlist names sitting in the P1 entry band and computes
§5-sized levels (1.5×ATR stop, 2R TP1, risk-%'d share count). Both the gate and
the sizing are doctrine; pin them.
"""
import pytest
import setup_queue


class TestP1Gate:
    def test_passes_in_band_with_trend(self):
        # price > sma50 > sma200, RSI in [35,50]
        assert setup_queue.passes_p1_gate(rsi=42, price=110, sma50=105, sma200=100) is True

    def test_rsi_too_high_fails(self):
        assert setup_queue.passes_p1_gate(rsi=55, price=110, sma50=105, sma200=100) is False

    def test_rsi_too_low_fails(self):
        assert setup_queue.passes_p1_gate(rsi=30, price=110, sma50=105, sma200=100) is False

    def test_rsi_boundaries_inclusive(self):
        assert setup_queue.passes_p1_gate(35, 110, 105, 100) is True
        assert setup_queue.passes_p1_gate(50, 110, 105, 100) is True

    def test_broken_trend_fails(self):
        # price below sma50 → downtrend, not a P1 pullback
        assert setup_queue.passes_p1_gate(rsi=42, price=104, sma50=105, sma200=100) is False
        # sma50 below sma200 → no uptrend structure
        assert setup_queue.passes_p1_gate(rsi=42, price=110, sma50=99, sma200=100) is False

    def test_missing_input_fails(self):
        assert setup_queue.passes_p1_gate(None, 110, 105, 100) is False
        assert setup_queue.passes_p1_gate(42, None, 105, 100) is False
        assert setup_queue.passes_p1_gate(42, 110, 105, None) is False


class TestComputeLevels:
    def test_standard_sizing(self):
        # price 100, atr 4 → stop = 100 - 1.5*4 = 94; risk_per = 6
        # tp1 = 100 + 2*6 = 112; shares = (20000*0.02)//6 = 400//6 = 66
        lv = setup_queue._compute_levels({"price": 100.0, "atr14": 4.0})
        assert lv["entry"] == 100.0
        assert lv["stop"] == 94.0
        assert lv["tp1"] == 112.0
        assert lv["risk_per_share"] == 6.0
        assert lv["shares"] == 66
        assert lv["dollar_risk"] == pytest.approx(66 * 6.0)
        assert lv["rr1"] == 2.0

    def test_tp1_is_2r_above_entry(self):
        lv = setup_queue._compute_levels({"price": 50.0, "atr14": 2.0})
        risk = lv["entry"] - lv["stop"]
        assert lv["tp1"] == pytest.approx(lv["entry"] + 2 * risk)

    def test_missing_price_or_atr_returns_none(self):
        assert setup_queue._compute_levels({"price": None, "atr14": 4.0}) is None
        assert setup_queue._compute_levels({"price": 100.0, "atr14": None}) is None
        assert setup_queue._compute_levels({}) is None

    def test_zero_risk_returns_none(self):
        # atr 0 → stop == price → risk_per 0 → cannot size
        assert setup_queue._compute_levels({"price": 100.0, "atr14": 0.0}) is None
