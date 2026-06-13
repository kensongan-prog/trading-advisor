"""
test_mae_mfe.py — MAE/MFE → R-multiple math.

The excursion math is what eventually tells the operator whether stops are too
tight (winners show big MAE) or targets too small (MFE >> realized R). If the R
conversion is wrong, the calibration evidence is wrong. Pins the pure
`excursion_r` helper extracted from snapshot().
"""
import pytest
import mae_mfe


class TestExcursionR:
    def test_basic_long_excursion(self):
        # entry 100, stop 90 → risk 10. low 95 → MAE -0.5R; high 120 → MFE +2.0R
        mae, mfe = mae_mfe.excursion_r(100, 90, 95, 120)
        assert mae == pytest.approx(-0.5)
        assert mfe == pytest.approx(2.0)

    def test_price_never_dipped_below_entry(self):
        # low == entry → MAE 0R
        mae, mfe = mae_mfe.excursion_r(100, 90, 100, 110)
        assert mae == pytest.approx(0.0)
        assert mfe == pytest.approx(1.0)

    def test_full_stop_loss_is_minus_one_r(self):
        mae, mfe = mae_mfe.excursion_r(100, 90, 90, 100)
        assert mae == pytest.approx(-1.0)
        assert mfe == pytest.approx(0.0)

    def test_fractional_risk(self):
        # entry 15.20, stop 13.98 → risk 1.22
        mae, mfe = mae_mfe.excursion_r(15.20, 13.98, 14.50, 18.00)
        assert mae == pytest.approx((14.50 - 15.20) / 1.22, abs=0.001)
        assert mfe == pytest.approx((18.00 - 15.20) / 1.22, abs=0.001)

    def test_invalid_risk_returns_none(self):
        assert mae_mfe.excursion_r(100, 100, 99, 101) is None   # entry == stop
        assert mae_mfe.excursion_r(90, 100, 85, 95) is None     # stop above entry

    def test_rounds_to_three_places(self):
        mae, mfe = mae_mfe.excursion_r(100, 97, 96.5, 103.7)
        # 3-decimal rounding, no float dust
        assert mae == round(mae, 3)
        assert mfe == round(mfe, 3)
