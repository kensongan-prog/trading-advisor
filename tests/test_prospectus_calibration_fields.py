"""
test_prospectus_calibration_fields.py — sector / sentiment flag / RS-vs-SPY
captured into the journal's Data snapshot table at prospectus creation
(Analysis C1 prep).

The calibration-report skill (C1) buckets closed-trade outcomes by gate state
at entry. RSI/regime were already captured; sector, sentiment flag, and RS
vs SPY were not recorded anywhere, so a closed trade's entry-time context
couldn't be reconstructed. The Risk Simulator already computes t.sector,
t.sentiment_flag, and t.rs_vs_spy_1m for its own gates — the "Create
prospectus" command passes the SAME values through via --sector /
--sentiment-flag / --rs-1m rather than re-fetching, mirroring the
--quality-flags precedent from Guardrails Phase B.
"""
from types import SimpleNamespace

import pytest

import j


@pytest.fixture
def tmp_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "JOURNAL_DIR", tmp_path)
    monkeypatch.setattr(j, "invalidate_dashboard_cache", lambda *a, **k: None)
    monkeypatch.setattr(j, "sync_portfolio", lambda *a, **k: None)
    return tmp_path


def _args(**over):
    base = dict(
        ticker="GPUS", market="us", entry="0.17", stop="0.15", tp1="0.25",
        tp2=None, shares=None, account=None, risk_pct=None, heat_used=None,
        heat_max=None, overwrite=False, name=None, phase=None, phase_mode=None,
        structure=None, conviction=None, conviction_note=None, playbook=None,
        timeframe=None, status_line=None, entry_logic=None, entry_note=None,
        stop_logic=None, tp1_logic=None, tp2_logic=None, thesis=None,
        case_against=None, event_risk=None, regime=None, rr_floor=None,
        rsi=None, atr_pct=None, quality_flags=None, sector=None, sentiment_flag=None, rs_1m=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_fields_present_render_into_data_snapshot(tmp_journal):
    assert j.cmd_new(_args(sector="Technology", sentiment_flag="FADE", rs_1m="+3.2%")) == 0
    files = list(tmp_journal.glob("*_GPUS.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "| Sector | Technology |" in text
    assert "| Sentiment flag | FADE |" in text
    assert "| RS vs SPY (1m) | +3.2% |" in text


def test_fields_absent_render_em_dash(tmp_journal):
    assert j.cmd_new(_args(ticker="MRVL")) == 0
    files = list(tmp_journal.glob("*_MRVL.md"))
    text = files[0].read_text()
    assert "| Sector | — |" in text
    assert "| Sentiment flag | — |" in text
    assert "| RS vs SPY (1m) | — |" in text
