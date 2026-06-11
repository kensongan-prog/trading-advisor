"""
test_r_math.py — R-multiple math in the journal CLI.

Why these tests exist: R-multiples drive every closed-trade calibration
metric (win rate, average R, the Phase-2 unlock gate). Silent math errors
here would corrupt the entire feedback loop the doctrine is built on.
"""
import pytest
import j


def test_simple_winner_2r():
    """A clean 2R win: entry 100, stop 95, exit 110."""
    per_leg, blended, total_pl, total_risk = j.compute_r(100.0, 95.0, [110.0], [1.0])
    assert blended == pytest.approx(2.0)
    assert total_pl == pytest.approx(10.0)
    assert total_risk == pytest.approx(5.0)
    assert len(per_leg) == 1
    assert per_leg[0]["r"] == pytest.approx(2.0)


def test_simple_loser_minus_1r():
    """Full stop hit: entry 100, stop 95, exit at the stop."""
    _, blended, total_pl, total_risk = j.compute_r(100.0, 95.0, [95.0], [1.0])
    assert blended == pytest.approx(-1.0)
    assert total_pl == pytest.approx(-5.0)
    assert total_risk == pytest.approx(5.0)


def test_scratch_zero_r():
    """Exit at entry = 0R."""
    _, blended, _, _ = j.compute_r(100.0, 95.0, [100.0], [1.0])
    assert blended == pytest.approx(0.0)


def test_partial_fills_blended_r():
    """50/50 partial fills: TP1 at 2R, TP2 at 4R → blended 3R."""
    per_leg, blended, total_pl, total_risk = j.compute_r(
        100.0, 95.0, [110.0, 120.0], [50.0, 50.0])
    assert len(per_leg) == 2
    assert per_leg[0]["r"] == pytest.approx(2.0)
    assert per_leg[1]["r"] == pytest.approx(4.0)
    # Equal share weight → average of 2R and 4R = 3R
    assert blended == pytest.approx(3.0)
    # 50 sh × $10 + 50 sh × $20 = $1500 profit; risk = 100 sh × $5 = $500
    assert total_pl == pytest.approx(1500.0)
    assert total_risk == pytest.approx(500.0)


def test_partial_fills_unequal_weights():
    """Unequal partials: 70 sh at 2R, 30 sh at -1R → weighted blended."""
    per_leg, blended, total_pl, total_risk = j.compute_r(
        100.0, 95.0, [110.0, 95.0], [70.0, 30.0])
    # 70 × $10 = $700, 30 × $-5 = $-150. Total PL = $550. Total risk = 100 × $5 = $500.
    assert total_pl == pytest.approx(550.0)
    assert total_risk == pytest.approx(500.0)
    assert blended == pytest.approx(1.1)


def test_entry_below_stop_rejected():
    """Long with stop above entry is invalid — must SystemExit per Phase 1 doctrine."""
    with pytest.raises(SystemExit):
        j.compute_r(100.0, 105.0, [110.0], [1.0])


def test_zero_risk_per_share_rejected():
    """Entry == stop = zero risk per share → div-by-zero land — must reject."""
    with pytest.raises(SystemExit):
        j.compute_r(100.0, 100.0, [110.0], [1.0])


def test_per_leg_pl_and_r_shapes():
    """compute_r returns dicts with the expected keys per leg."""
    per_leg, *_ = j.compute_r(100.0, 95.0, [110.0, 120.0], [50.0, 50.0])
    for leg in per_leg:
        assert {"price", "shares", "pl", "risk", "r"} <= leg.keys()


def test_fractional_crypto_shares():
    """Crypto positions use fractional share counts; math must hold."""
    per_leg, blended, total_pl, total_risk = j.compute_r(
        50000.0, 47500.0, [55000.0], [0.123456])
    expected_pl = 5000.0 * 0.123456
    expected_risk = 2500.0 * 0.123456
    assert total_pl == pytest.approx(expected_pl)
    assert total_risk == pytest.approx(expected_risk)
    assert blended == pytest.approx(2.0)  # 5000/2500 = 2R
