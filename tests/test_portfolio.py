"""
test_portfolio.py — portfolio heat + calibration math.

Heat is an AGENTS.md §5 safety rail (6% / $1,200 ceiling on a $20k account). If
`heat()` sums $-at-risk wrongly, or the journal parser misreads a LIVE entry, the
operator loses a hard guardrail silently. These tests pin the parsing + math by
pointing the module at a temp journal dir (so they exercise the real markdown
parse, not a mock).
"""
import importlib
import json
import pytest
import portfolio


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """Redirect portfolio's JOURNAL_DIR to a temp dir; yield a writer."""
    jdir = tmp_path / "journal"
    jdir.mkdir()
    monkeypatch.setattr(portfolio, "JOURNAL_DIR", jdir)
    # _sector reads DASH_CACHE; point it somewhere empty so sector is "—"
    monkeypatch.setattr(portfolio, "DASH_CACHE", tmp_path / "nocache")

    def write(stem, text):
        (jdir / f"{stem}.md").write_text(text)
    return write


LIVE_TPL = """# {ticker}

**Status:** LIVE — paper

| | Value | Logic |
|---|---|---|
| Entry trigger | $15.20 | ref |
| Stop-loss | **$13.98** | sim |
| TP1 | **$18.00** | 2R |

- **Max loss:** $183 (0.91% of $20,000)
- $ at risk: $183.00
"""


class TestHeat:
    def test_empty_journal_is_zero_heat(self, journal):
        h = portfolio.heat()
        assert h["used"] == 0.0
        assert h["max"] == 1200.0
        assert h["headroom"] == 1200.0
        assert h["n_positions"] == 0

    def test_single_live_position_sums_risk(self, journal):
        journal("2026-06-11_CLSK", LIVE_TPL.format(ticker="CLSK"))
        h = portfolio.heat()
        assert h["used"] == 183.0
        assert h["n_positions"] == 1
        assert h["headroom"] == pytest.approx(1017.0)
        assert h["pct_equity"] == pytest.approx(183.0 / 20000 * 100, abs=0.01)

    def test_heat_sums_across_multiple_live(self, journal):
        journal("2026-06-11_CLSK", LIVE_TPL.format(ticker="CLSK"))
        journal("2026-06-12_AUPH", LIVE_TPL.format(ticker="AUPH"))
        h = portfolio.heat()
        assert h["used"] == 366.0
        assert h["n_positions"] == 2

    def test_closed_entries_excluded_from_heat(self, journal):
        journal("2026-06-11_CLSK", LIVE_TPL.format(ticker="CLSK"))
        journal("2026-05-01_OLD", "# OLD\n\n**Status:** CLOSED — win (+2.1R)\n")
        h = portfolio.heat()
        assert h["n_positions"] == 1   # the CLOSED one is not heat
        assert h["used"] == 183.0


class TestExpectancy:
    def test_no_closed_trades(self, journal):
        e = portfolio.expectancy()
        assert e["n"] == 0
        assert e["win_rate"] is None
        assert e["sum_r"] == 0.0

    def test_win_loss_aggregation(self, journal):
        journal("2026-05-01_A", "# A\n\n**Status:** CLOSED — win (+2.0R)\n")
        journal("2026-05-02_B", "# B\n\n**Status:** CLOSED — loss (-1.0R)\n")
        journal("2026-05-03_C", "# C\n\n**Status:** CLOSED — win (+1.5R)\n")
        e = portfolio.expectancy()
        assert e["n"] == 3
        assert e["wins"] == 2
        assert e["losses"] == 1
        assert e["sum_r"] == pytest.approx(2.5)
        assert e["avg_r"] == pytest.approx(2.5 / 3, abs=0.001)
        assert e["win_rate"] == pytest.approx(66.7, abs=0.1)

    def test_scratch_zero_r_counts_as_loss_side(self, journal):
        # r <= 0 is the "losses" bucket (a 0R scratch is not a win)
        journal("2026-05-01_S", "# S\n\n**Status:** CLOSED — scratch (0.0R)\n")
        e = portfolio.expectancy()
        assert e["wins"] == 0
        assert e["losses"] == 1


class TestCorrelationNote:
    def test_no_clusters_returns_empty(self):
        h = {"by_sector": {"Tech": ["NVDA"], "Energy": ["CLSK"]}}
        assert portfolio.correlation_note(h) == ""

    def test_flags_two_in_same_sector(self):
        h = {"by_sector": {"Tech": ["NVDA", "MRVL"]}}
        note = portfolio.correlation_note(h)
        assert "Tech" in note and "NVDA" in note and "MRVL" in note
        assert "one bet" in note


class TestRiskParams:
    """Bridge Phase 4: risk_params.json is the machine-readable artifact MooMoo
    reads read-only (same TRADING_ADVISOR_ROOT it already uses for watchlist.md/
    journal/*.md) to validate staging against TA's live account params and to
    gate MOOMOO_LIVE_TRADING_ENABLED on the same 20-trade paper gate that
    unlocks TA's own Phase 2 — one unified ramp, not two separate criteria."""

    def test_gate_not_passed_below_target(self, journal):
        for i in range(19):
            journal(f"2026-05-{i+1:02d}_T{i}", f"# T{i}\n\n**Status:** CLOSED — win (+1.0R)\n")
        assert portfolio.phase2_gate_passed() is False

    def test_gate_passed_at_target_with_nonneg_cum_r(self, journal):
        for i in range(20):
            journal(f"2026-05-{i+1:02d}_T{i}", f"# T{i}\n\n**Status:** CLOSED — win (+1.0R)\n")
        assert portfolio.phase2_gate_passed() is True

    def test_gate_not_passed_with_negative_cum_r_even_at_target(self, journal):
        for i in range(20):
            journal(f"2026-05-{i+1:02d}_T{i}", f"# T{i}\n\n**Status:** CLOSED — loss (-1.0R)\n")
        assert portfolio.phase2_gate_passed() is False

    def test_risk_params_shape_and_values(self, journal):
        journal("2026-06-11_CLSK", LIVE_TPL.format(ticker="CLSK"))
        journal("2026-05-01_A", "# A\n\n**Status:** CLOSED — win (+2.0R)\n")
        rp = portfolio.risk_params()
        assert rp["equity_scope"] == "isolated_strategy_sleeve"
        assert rp["strategy_sleeve_equity_usd"] == portfolio.ACCOUNT
        assert rp["account_equity_usd"] == portfolio.ACCOUNT
        assert rp["heat_scope"] == "trading_advisor_live_journals"
        assert rp["max_risk_pct_per_trade"] == portfolio.RISK_PCT_PER_TRADE
        assert rp["heat_ceiling_usd"] == portfolio.HEAT_MAX
        assert rp["heat_ceiling_pct"] == pytest.approx(portfolio.HEAT_MAX / portfolio.ACCOUNT)
        assert rp["heat_used_usd"] == 183.0
        assert rp["heat_headroom_usd"] == pytest.approx(1017.0)
        assert rp["phase2_gate"]["closed_trades"] == 1
        assert rp["phase2_gate"]["target_trades"] == 20
        assert rp["phase2_gate"]["cum_r"] == 2.0
        assert rp["phase2_gate"]["passed"] is False
        assert rp["live_trading_unlock_eligible"] is False
        assert "_generated_at" in rp

    def test_live_trading_unlock_eligible_tracks_gate_passed(self, journal):
        for i in range(20):
            journal(f"2026-05-{i+1:02d}_T{i}", f"# T{i}\n\n**Status:** CLOSED — win (+1.0R)\n")
        rp = portfolio.risk_params()
        assert rp["phase2_gate"]["passed"] is True
        assert rp["live_trading_unlock_eligible"] is True

    def test_write_risk_params_writes_valid_json(self, journal, tmp_path, monkeypatch):
        out = tmp_path / "risk_params.json"
        monkeypatch.setattr(portfolio, "RISK_PARAMS_JSON", out)
        result_path = portfolio.write_risk_params()
        assert result_path == out
        assert out.is_file()
        data = json.loads(out.read_text())
        assert data["equity_scope"] == "isolated_strategy_sleeve"
        assert data["strategy_sleeve_equity_usd"] == portfolio.ACCOUNT
        assert data["account_equity_usd"] == portfolio.ACCOUNT
        # No leftover temp file after the atomic replace.
        assert not out.with_suffix(".json.tmp").exists()


class TestParsingHelpers:
    def test_status_strips_trailing_period(self):
        assert portfolio._status("**Status:** LIVE — paper.") == "LIVE — paper"

    def test_money_after_label(self):
        assert portfolio._money_after("- $ at risk: $183.00", "$ at risk:") == 183.0

    def test_money_after_handles_commas(self):
        assert portfolio._money_after("Max loss: $1,250.50", "Max loss:") == 1250.50

    def test_table_value_reads_first_dollar_cell(self):
        txt = "| Stop-loss | **$13.98** | sim |"
        assert portfolio._table_value(txt, "stop") == 13.98
