"""
test_sentiment_coverage.py — volume/coverage haircut on composite conviction.

Gap #3 fix: a contrarian read off a handful of messages must not carry the same
conviction as one off dozens. compute_composite now dampens conviction by a
log-scaled coverage factor (on-topic sample size vs TARGET_N=25), which gates the
FADE/BUY contrarian flag and flows downstream to the Risk Simulator's §4 factor.
"""
import math
import sentiment_cache as sc


def _st(bull, conv, n):
    """A StockTwits-style source summary with `n` scored on-topic items."""
    return {
        "present": True,
        "llm_bull_pct": bull,
        "llm_bear_pct": round(1 - bull, 3),
        "llm_neutral_pct": 0.0,
        "llm_avg_conviction": conv,
        "n_scored_bodies": n,
    }


class TestCoverageHaircut:
    def test_thin_sample_cannot_fire_flag(self):
        # Extreme-bull, high text conviction, but only 2 messages → dampened below
        # the 0.70 flag threshold → no FADE.
        comp = sc.compute_composite(_st(0.9, 0.9, 2), None, None)
        assert comp["bull_score"] >= 0.80
        assert comp["conviction"] < 0.70
        assert comp["contrarian_flag"] is None
        assert comp["conviction_raw"] == 0.9          # text-only conviction preserved
        assert comp["conviction"] < comp["conviction_raw"]

    def test_well_covered_sample_fires_flag(self):
        # Same read backed by a full sample → coverage ~1.0 → FADE fires.
        comp = sc.compute_composite(_st(0.9, 0.9, 60), None, None)
        assert comp["coverage"] == 1.0
        assert comp["conviction"] >= 0.70
        assert comp["contrarian_flag"] == "FADE"

    def test_coverage_is_monotonic_in_sample_size(self):
        cs = [sc.compute_composite(_st(0.9, 0.9, n), None, None)["coverage"]
              for n in (1, 5, 15, 25, 100)]
        assert cs == sorted(cs)              # non-decreasing
        assert cs[0] < cs[-1]
        assert cs[-1] == 1.0                 # saturates at/above TARGET_N

    def test_coverage_formula(self):
        comp = sc.compute_composite(_st(0.7, 0.8, 10), None, None)
        expected = round(min(1.0, math.log1p(10) / math.log1p(25)), 3)
        assert comp["coverage"] == expected
        assert comp["n_total"] == 10

    def test_no_sources_unknown(self):
        comp = sc.compute_composite(None, None, None)
        assert comp["contrarian_flag"] is None
        assert comp["label"] == "UNKNOWN"
