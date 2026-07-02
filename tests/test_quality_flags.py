"""
test_quality_flags.py — structural-quality risk flags (guardrails Phase A).

Motivating case: GPUS ($0.17, MC $53M, short 49.97% of float, beta 2.594, 0
analysts) went through the entire pipeline in 2026-07-01/02 with zero
warnings anywhere. These fixtures are the REAL numbers captured live that
day — pin them as the regression case this module exists to catch.
"""
import quality_flags as qf
import dashboard

# Real GPUS snapshot (2026-07-02 live probe)
GPUS_ROW = {
    "price": 0.17, "market_cap": 53_212_272, "avg_vol_30d": 8_000_000,
    "short_pct_float": 0.4997, "beta": 2.594, "analyst_count": None,
    "currency": "USD",
}
# Real AAPL snapshot (same probe) — the clean-name control case
AAPL_ROW = {
    "price": 275.0, "market_cap": 4_323_663_937_536, "avg_vol_30d": 50_000_000,
    "short_pct_float": 0.0098, "beta": 1.086, "analyst_count": 42,
    "currency": "USD",
}


class TestEquityFlags:
    def test_gpus_trips_every_structural_flag(self):
        # $0.17 * 8M avg vol = $1.36M/day, also under the $5M illiquidity floor.
        flags = qf.equity_flags(GPUS_ROW)
        assert set(flags) == {"PENNY", "LOW_MC", "ILLIQUID", "HIGH_SHORT", "HIGH_BETA", "NO_COVERAGE"}

    def test_aapl_trips_nothing(self):
        assert qf.equity_flags(AAPL_ROW) == []

    def test_penny_threshold_is_currency_aware(self):
        us = {"price": 0.30, "currency": "USD"}
        klse = {"price": 0.30, "currency": "MYR"}
        assert "PENNY" in qf.equity_flags(us)          # $0.30 < $5 USD floor
        assert "PENNY" not in qf.equity_flags(klse)    # RM0.30 > RM0.20 floor

    def test_illiquid_uses_dollar_volume_not_share_volume(self):
        # 10M shares at $0.30 = $3M/day < $5M floor -> illiquid despite "high" share count
        thin = {"price": 0.30, "avg_vol_30d": 10_000_000, "currency": "USD"}
        assert "ILLIQUID" in qf.equity_flags(thin)
        thick = {"price": 50.0, "avg_vol_30d": 10_000_000, "currency": "USD"}
        assert "ILLIQUID" not in qf.equity_flags(thick)

    def test_no_coverage_fires_on_none_not_just_zero(self):
        # yfinance OMITS numberOfAnalystOpinions (None) for uncovered names —
        # this is the exact bug caught while building this module. price=10
        # stays above every other threshold so NO_COVERAGE is isolated.
        assert qf.equity_flags({"price": 10.0, "analyst_count": None}) == ["NO_COVERAGE"]
        assert qf.equity_flags({"price": 10.0, "analyst_count": 0}) == ["NO_COVERAGE"]
        assert qf.equity_flags({"price": 10.0, "analyst_count": 1}) == []

    def test_no_coverage_does_not_fire_on_a_totally_failed_fetch(self):
        # price is None -> we have no confirmation the fetch succeeded at all;
        # don't flag NO_COVERAGE alone off an empty row.
        assert qf.equity_flags({"price": None, "analyst_count": None}) == []

    def test_missing_fields_do_not_crash_or_false_flag(self):
        assert qf.equity_flags({}) == []


class TestCryptoFlags:
    def test_unranked_low_cap_coin(self):
        row = {"market_cap": 5_000_000, "market_cap_rank": None, "volume": 50_000}
        flags = qf.crypto_flags(row)
        assert "LOW_MC_RANK" in flags
        assert "THIN_VOLUME" in flags   # 50k/5M = 1% < 2% floor

    def test_top_coin_clean(self):
        row = {"market_cap": 1_000_000_000_000, "market_cap_rank": 1, "volume": 30_000_000_000}
        assert qf.crypto_flags(row) == []

    def test_rank_just_inside_and_outside_floor(self):
        assert "LOW_MC_RANK" not in qf.crypto_flags({"market_cap_rank": 100})
        assert "LOW_MC_RANK" in qf.crypto_flags({"market_cap_rank": 101})

    def test_totally_empty_row_is_not_flagged(self):
        # The crypto-grid stub-row fallback (no CoinGecko match at all) has
        # every field None — that's "no data", not "confirmed low rank".
        stub = {"symbol": "XYZ", "name": "XYZ", "price": None, "chg_24h": None,
                "chg_7d": None, "chg_30d": None, "market_cap": None, "volume": None}
        assert qf.crypto_flags(stub) == []


class TestPumpDumpRisk:
    def test_fires_when_all_four_align(self):
        assert qf.pump_dump_risk(
            ["PENNY", "LOW_MC"], chg_30d=80, vol_ratio=3.0, sentiment_flag="FADE",
        ) is True

    def test_does_not_fire_without_volume_evidence(self):
        # vol_ratio unknown -> conservative default: no fire, even with everything else present
        assert qf.pump_dump_risk(
            ["PENNY"], chg_30d=80, vol_ratio=None, sentiment_flag="FADE",
        ) is False

    def test_does_not_fire_on_clean_structural_quality(self):
        # spike + volume + FADE sentiment but no thin-quality flag (e.g. AAPL) -> no fire
        assert qf.pump_dump_risk(
            [], chg_30d=80, vol_ratio=3.0, sentiment_flag="FADE",
        ) is False

    def test_does_not_fire_on_buy_flag_extreme_bear(self):
        # EXTREME_BEAR/BUY is capitulation, not a pump — different risk shape entirely
        assert qf.pump_dump_risk(
            ["PENNY"], chg_30d=80, vol_ratio=3.0, sentiment_flag="BUY",
        ) is False

    def test_5d_spike_alone_can_trigger_price_spike_leg(self):
        assert qf.pump_dump_risk(
            ["PENNY"], chg_5d=25, vol_ratio=3.0, sentiment_flag="FADE",
        ) is True

    def test_price_spike_below_both_thresholds_does_not_fire(self):
        assert qf.pump_dump_risk(
            ["PENNY"], chg_30d=10, chg_5d=5, vol_ratio=3.0, sentiment_flag="FADE",
        ) is False


class TestAllFlags:
    def test_reads_defaults_off_equity_row(self):
        row = dict(GPUS_ROW, chg_30d_pct=90, vol_ratio=4.0)
        flags = qf.all_flags(row, asset_class="us", sentiment_flag="FADE")
        assert "PUMP_DUMP_RISK" in flags
        assert "PENNY" in flags  # base structural flags still present

    def test_explicit_kwargs_override_row_fields(self):
        row = dict(GPUS_ROW, chg_30d_pct=1, vol_ratio=0.1)  # row itself looks calm
        flags = qf.all_flags(row, asset_class="us", chg_30d=90, vol_ratio=4.0, sentiment_flag="FADE")
        assert "PUMP_DUMP_RISK" in flags

    def test_crypto_uses_chg_7d_as_short_window_proxy(self):
        row = {"market_cap": 5_000_000, "market_cap_rank": 300, "volume": 6_000_000,
               "chg_30d": 5, "chg_7d": 60}
        flags = qf.all_flags(row, asset_class="crypto", vol_ratio=3.0, sentiment_flag="FADE")
        assert "PUMP_DUMP_RISK" in flags   # fires off the 7d proxy, not 30d

    def test_no_composite_flag_when_sentiment_missing(self):
        row = dict(GPUS_ROW, chg_30d_pct=90, vol_ratio=4.0)
        flags = qf.all_flags(row, asset_class="us", sentiment_flag=None)
        assert "PUMP_DUMP_RISK" not in flags


class TestRowQualityFlagsGaugeSkip:
    """dashboard.row_quality_flags — the wrapper called from the render loops.

    Bug caught during live verification: SPY (an index/regime gauge, never a
    trade candidate) flagged NO_COVERAGE on every build, because ETFs
    structurally have no analyst opinions — pure noise. Mirrors the existing
    EARNINGS_SKIP_TICKERS precedent (dashboard.py, the yfinance .calendar fix).
    """
    def test_context_gauge_is_never_flagged(self):
        # SPY would otherwise trip NO_COVERAGE (analyst_count None) every time.
        row = {"price": 500.0, "analyst_count": None}
        assert dashboard.row_quality_flags(row, "us", ticker="SPY") == []

    def test_normal_ticker_still_flags(self):
        assert dashboard.row_quality_flags(GPUS_ROW, "us", ticker="GPUS") != []

    def test_no_ticker_passed_still_flags_normally(self):
        # Backward-compat: ticker is optional: callers that omit it aren't
        # silently suppressed.
        assert dashboard.row_quality_flags(GPUS_ROW, "us") != []
