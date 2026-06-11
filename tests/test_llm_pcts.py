"""
test_llm_pcts.py — relevance-weighted sentiment aggregation.

Why these tests exist: v2.0.4 added the relevance gate so off-topic items
(the SOL/Solara case) drop out of bull/bear%. The math is now multi-factor
(conviction × relevance_weight × engagement_weight). Pin the weights so
a future refactor can't silently change scoring without test failure.
"""
import pytest
from sentiment_cache import llm_pcts, _RELEVANCE_WEIGHT


def _c(sentiment, conviction=1.0, relevance="primary"):
    return {"sentiment": sentiment, "conviction": conviction, "relevance": relevance}


class TestBasicAggregation:
    def test_all_bullish_returns_full_bull(self):
        out = llm_pcts([_c("bullish")] * 3)
        assert out["bull"] == pytest.approx(1.0)
        assert out["bear"] == pytest.approx(0.0)
        assert out["neutral"] == pytest.approx(0.0)

    def test_mixed_50_50(self):
        out = llm_pcts([_c("bullish"), _c("bearish")])
        assert out["bull"] == pytest.approx(0.5)
        assert out["bear"] == pytest.approx(0.5)

    def test_empty_returns_none(self):
        assert llm_pcts([]) is None

    def test_avg_conviction_reported(self):
        out = llm_pcts([_c("bullish", 0.8), _c("bearish", 0.4)])
        assert out["avg_conviction"] == pytest.approx(0.6)


class TestRelevanceGate:
    def test_off_topic_drops_out(self):
        # 2 bullish primary + 2 off-topic bearish → 100% bull (off-topic ignored)
        out = llm_pcts([
            _c("bullish", relevance="primary"),
            _c("bullish", relevance="primary"),
            _c("bearish", relevance="none"),
            _c("bearish", relevance="none"),
        ])
        assert out["bull"] == pytest.approx(1.0)
        assert out["bear"] == pytest.approx(0.0)
        assert out["n_primary"] == 2
        assert out["n_off_topic"] == 2

    def test_mention_half_weight(self):
        # 1 bullish primary + 1 bearish mention → bull dominates because mention
        # only counts half. Effective weights: 1.0 vs 0.5 → 2/3 bull, 1/3 bear.
        out = llm_pcts([
            _c("bullish", relevance="primary"),
            _c("bearish", relevance="mention"),
        ])
        assert out["bull"] == pytest.approx(2/3, abs=0.001)
        assert out["bear"] == pytest.approx(1/3, abs=0.001)
        assert out["n_primary"] == 1
        assert out["n_mention"] == 1

    def test_all_off_topic_falls_back_to_neutral_baseline(self):
        # All zero weight = the "uniform neutral" fallback the SOL HN case hits
        out = llm_pcts([
            _c("bullish", relevance="none"),
            _c("bullish", relevance="none"),
        ])
        assert out["bull"] == pytest.approx(0.0)
        assert out["bear"] == pytest.approx(0.0)
        assert out["neutral"] == pytest.approx(1.0)
        assert out["n_off_topic"] == 2
        assert out["n_primary"] == 0

    def test_relevance_weights_match_constants(self):
        # Pin the weight constants — a refactor that changes them silently is suspicious
        assert _RELEVANCE_WEIGHT["primary"] == 1.0
        assert _RELEVANCE_WEIGHT["mention"] == 0.5
        assert _RELEVANCE_WEIGHT["none"] == 0.0


class TestBackwardCompat:
    def test_missing_relevance_field_defaults_primary(self):
        # Legacy classifications without `relevance` should default to primary
        out = llm_pcts([
            {"sentiment": "bullish", "conviction": 1.0},  # no relevance key
        ])
        assert out["bull"] == pytest.approx(1.0)
        # 1 item with primary default
        assert out["n_primary"] == 1


class TestEngagementWeighting:
    def test_high_engagement_boosts_weight(self):
        # Same sentiment + relevance, but second item has 1000 upvotes → dominates
        out = llm_pcts(
            classifications=[_c("bearish"), _c("bullish")],
            engagements=[0, 1000],
        )
        # log1p(1000) ≈ 6.9, so bullish weight ~7.9 vs bearish 1.0 → bull > 80%
        assert out["bull"] > 0.85
        assert out["engagement_weighted"] is True

    def test_off_topic_zeroed_even_with_engagement(self):
        # Off-topic item with massive engagement should still not contribute
        out = llm_pcts(
            classifications=[
                _c("bullish", relevance="primary"),
                _c("bearish", relevance="none"),
            ],
            engagements=[1.0, 9999.0],
        )
        assert out["bull"] == pytest.approx(1.0)
        assert out["bear"] == pytest.approx(0.0)
