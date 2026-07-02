"""
test_prospectus_quality_flags.py — structural-quality flags recorded into the
journal at prospectus creation (Guardrails Phase B, final piece).

The Risk Simulator already computes t.quality_flags for the Structural quality
gate (dashboard.py); the "Create prospectus" command passes the SAME flags
through via --quality-flags rather than re-fetching. j.py renders them into a
new "### Structural risk flags" section so the journal permanently records
what was known at entry — closing the loop the guardrails audit opened
(GPUS-class names previously left no trace of their risk profile anywhere).
"""
from types import SimpleNamespace

import pytest

import j


def test_render_empty_when_no_flags():
    assert j._render_quality_flags_section(None) == ""
    assert j._render_quality_flags_section("") == ""


def test_render_lists_each_flag_with_icon_and_description():
    section = j._render_quality_flags_section("PENNY,LOW_MC,HIGH_SHORT")
    assert "### Structural risk flags" in section
    assert "🪙" in section and "Penny stock" in section
    assert "🐜" in section and "Low market cap" in section
    assert "🎯" in section and "High short interest" in section
    assert "warn-loudly-never-block" in section


def test_render_handles_whitespace_and_unknown_keys_gracefully():
    section = j._render_quality_flags_section(" PENNY , SOME_FUTURE_FLAG ")
    assert "Penny stock" in section
    assert "SOME_FUTURE_FLAG" in section  # unknown key still renders, doesn't crash


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


def test_prospectus_with_flags_carries_the_section(tmp_journal):
    assert j.cmd_new(_args(quality_flags="PENNY,LOW_MC,HIGH_SHORT,HIGH_BETA,NO_COVERAGE")) == 0
    files = list(tmp_journal.glob("*_GPUS.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "### Structural risk flags" in text
    assert "Penny stock" in text and "High beta" in text and "No analyst coverage" in text


def test_prospectus_without_flags_omits_the_section(tmp_journal):
    assert j.cmd_new(_args(ticker="MRVL", quality_flags=None)) == 0
    files = list(tmp_journal.glob("*_MRVL.md"))
    text = files[0].read_text()
    assert "### Structural risk flags" not in text
