"""
test_sparkline.py — per-row sparkline series + SVG (Phase 1, live-dashboard upgrade).

Pins the downsample/round contract of `_spark_series`, the draw contract of
`_sparkline_svg` (direction class, empty-on-too-short so callers can append
unconditionally), and that the pure `_compute_indicators_from_ohlcv` fetcher path
emits the `spark` field the grids render.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"))
import dashboard  # noqa: E402


# ── _spark_series ──────────────────────────────────────────────────────────
def test_spark_series_too_short_is_empty():
    assert dashboard._spark_series([]) == []
    assert dashboard._spark_series([100.0]) == []


def test_spark_series_drops_nan_none_and_nonnumeric():
    assert dashboard._spark_series([1.0, float("nan"), None, 2.0, "x"]) == [1.0, 2.0]


def test_spark_series_downsamples_keeping_endpoints():
    s = dashboard._spark_series(list(range(1, 201)), n=40)
    assert len(s) == 40
    assert s[0] == 1
    assert s[-1] == 200  # newest point always preserved


def test_spark_series_rounds_compactly():
    # ~5 sig figs: mid-range keeps a decimal, sub-dollar keeps precision, large is integer
    assert dashboard._spark_series([1234.5678, 1234.5678]) == [1234.6, 1234.6]
    assert dashboard._spark_series([0.0123456, 0.0123456]) == [0.012346, 0.012346]
    big = dashboard._spark_series([98765.4, 98765.4])[0]
    assert big == int(big)  # no absurd decimals on large prices


# ── _sparkline_svg ─────────────────────────────────────────────────────────
def test_sparkline_empty_when_undrawable():
    assert dashboard._sparkline_svg([]) == ""
    assert dashboard._sparkline_svg([5.0]) == ""


def test_sparkline_direction_class():
    up = dashboard._sparkline_svg([1, 2, 3])
    down = dashboard._sparkline_svg([3, 2, 1])
    assert "<svg" in up and "<polyline" in up
    assert "spark-up" in up and "spark-down" not in up
    assert "spark-down" in down and "spark-up" not in down


# ── fetcher emits spark (needs pandas; the data env has it, the test venv may not) ──
def test_compute_indicators_includes_spark():
    pytest.importorskip("pandas")
    rows = [{"open": i, "high": i + 1, "low": i - 1, "close": float(i)} for i in range(1, 61)]
    res = dashboard._compute_indicators_from_ohlcv(rows)
    assert "spark" in res
    assert isinstance(res["spark"], list) and len(res["spark"]) >= 2
    assert res["spark"][-1] == 60.0  # last close preserved
