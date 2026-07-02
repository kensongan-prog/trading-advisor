"""
test_calibration_report.py — Analysis C1: the outcome engine.

Pins the bucketing logic (RSI band / sentiment flag / RS bucket / sector /
structural-quality flags) against synthetic journal fixtures, plus the
low-confidence (n<MIN_N) flagging and the "unknown" fallback for closed
trades predating the 2026-07-02 sector/sentiment/RS capture fields.
"""
from pathlib import Path

import calibration_report as cr


def test_rsi_band():
    assert cr._rsi_band("22.0") == "<30 (oversold)"
    assert cr._rsi_band("45.2") == "30-50"
    assert cr._rsi_band("61.0") == "50-70"
    assert cr._rsi_band("78.3") == ">=70 (overbought)"
    assert cr._rsi_band("—") == "unknown"
    assert cr._rsi_band(None) == "unknown"


def test_rs_bucket():
    assert cr._rs_bucket("+3.2%") == "leader (RS>0)"
    assert cr._rs_bucket("-1.5%") == "laggard (RS<0)"
    assert cr._rs_bucket("0.0%") == "flat (RS=0)"
    assert cr._rs_bucket("—") == "unknown"
    assert cr._rs_bucket(None) == "unknown"


def test_table_field_exact_label_match():
    txt = (
        "| Field | Value | Source | Fetched (UTC) |\n"
        "|---|---|---|---|\n"
        "| RSI(14) daily | 45.2 | dashboard cache | 2026-07-02 11:25 UTC |\n"
        "| Sector | Technology | dashboard cache | 2026-07-02 11:25 UTC |\n"
    )
    assert cr._table_field(txt, "RSI(14) daily") == "45.2"
    assert cr._table_field(txt, "Sector") == "Technology"
    assert cr._table_field(txt, "Nonexistent") is None


def _journal_text(rsi="45.2", sector="Technology", sentiment="FADE", rs="+3.2%", quality_flags=True):
    flags_section = (
        "\n### Structural risk flags\n\n- 🪙 **Penny stock:** ...\n\n"
        "_warn-loudly-never-block._\n" if quality_flags else ""
    )
    return f"""# 2026-06-01 — TEST (Test Co)

**Status:** CLOSED — win (+2.00R)

---

### Event risk

_(none)_
{flags_section}
### Data snapshot

| Field | Value | Source | Fetched (UTC) |
|---|---|---|---|
| Price (reference) | $10.00 | dashboard sim | 2026-06-01 00:00 UTC |
| RSI(14) daily | {rsi} | dashboard cache | 2026-06-01 00:00 UTC |
| ATR(14) % of price | 3.00% | dashboard cache | 2026-06-01 00:00 UTC |
| Market regime | NEUTRAL (R:R floor 1.5R) | macro-rates / dashboard | 2026-06-01 00:00 UTC |
| Sector | {sector} | dashboard cache | 2026-06-01 00:00 UTC |
| Sentiment flag | {sentiment} | dashboard sentiment composite | 2026-06-01 00:00 UTC |
| RS vs SPY (1m) | {rs} | dashboard rel_strength cache | 2026-06-01 00:00 UTC |

---

## Exit

- Realized R-multiple: +2.00R
"""


def test_closed_entries_with_context_parses_full_row(tmp_path, monkeypatch):
    p = tmp_path / "2026-06-01_TEST.md"
    p.write_text(_journal_text())
    monkeypatch.setattr(cr.portfolio, "JOURNAL_DIR", tmp_path)
    monkeypatch.setattr(cr.portfolio, "closed_trades", lambda: [
        {"ticker": "TEST", "date": "2026-06-01", "result": "win", "r": 2.0, "file": p.name},
    ])
    entries = cr.closed_entries_with_context()
    assert len(entries) == 1
    e = entries[0]
    assert e["r"] == 2.0
    assert e["rsi_band"] == "30-50"
    assert e["sentiment_flag"] == "FADE"
    assert e["rs_bucket"] == "leader (RS>0)"
    assert e["sector"] == "Technology"
    assert e["has_quality_flags"] is True


def test_pre_capture_entry_shows_unknown_but_not_dropped(tmp_path, monkeypatch):
    """A closed trade predating the sector/sentiment/RS fields still counts toward
    win-rate/avg-R — it just can't be bucketed by the newer dimensions."""
    txt = (
        "# 2026-05-01 — OLD (Old Co)\n\n**Status:** CLOSED — loss (-1.00R)\n\n"
        "### Data snapshot\n\n| Field | Value | Source | Fetched (UTC) |\n|---|---|---|---|\n"
        "| RSI(14) daily | 55.0 | dashboard cache | 2026-05-01 00:00 UTC |\n\n"
        "## Exit\n\n- Realized R-multiple: -1.00R\n"
    )
    p = tmp_path / "2026-05-01_OLD.md"
    p.write_text(txt)
    monkeypatch.setattr(cr.portfolio, "JOURNAL_DIR", tmp_path)
    monkeypatch.setattr(cr.portfolio, "closed_trades", lambda: [
        {"ticker": "OLD", "date": "2026-05-01", "result": "loss", "r": -1.0, "file": p.name},
    ])
    entries = cr.closed_entries_with_context()
    assert len(entries) == 1
    e = entries[0]
    assert e["rsi_band"] == "50-70"
    assert e["sentiment_flag"] == "unknown"
    assert e["rs_bucket"] == "unknown"
    assert e["sector"] == "unknown"
    assert e["has_quality_flags"] is False


def test_entries_with_no_realized_r_are_excluded(monkeypatch):
    monkeypatch.setattr(cr.portfolio, "closed_trades", lambda: [
        {"ticker": "STUB", "date": "2026-06-01", "result": "?", "r": None, "file": "x.md"},
    ])
    assert cr.closed_entries_with_context() == []


def test_bucket_stats_flags_low_confidence():
    entries = [{"r": 1.0}, {"r": -1.0}]
    stats = cr._bucket_stats(entries, lambda e: "bucket")
    b = stats["bucket"]
    assert b["n"] == 2
    assert b["win_rate"] == 50.0
    assert b["avg_r"] == 0.0
    assert b["low_confidence"] is True  # n=2 < MIN_N=3


def test_bucket_stats_not_low_confidence_at_min_n():
    entries = [{"r": 1.0}, {"r": 1.0}, {"r": 1.0}]
    stats = cr._bucket_stats(entries, lambda e: "bucket")
    assert stats["bucket"]["low_confidence"] is False


def test_build_report_empty_journal(monkeypatch):
    monkeypatch.setattr(cr.portfolio, "closed_trades", lambda: [])
    rep = cr.build_report()
    assert rep["n_closed"] == 0
    assert rep["overall"] == {}
    assert rep["by_rsi_band"] == {}


def test_print_report_handles_empty(capsys):
    cr.print_report({"n_closed": 0})
    out = capsys.readouterr().out
    assert "No closed trades yet" in out


def test_print_report_smoke(capsys):
    rep = {
        "n_closed": 1,
        "overall": {"all": {"n": 1, "win_rate": 100.0, "avg_r": 2.0, "sum_r": 2.0, "low_confidence": True}},
        "by_rsi_band": {"30-50": {"n": 1, "win_rate": 100.0, "avg_r": 2.0, "sum_r": 2.0, "low_confidence": True}},
        "by_sentiment_flag": {},
        "by_rs_bucket": {},
        "by_sector": {},
        "by_structural_quality": {},
    }
    cr.print_report(rep)
    out = capsys.readouterr().out
    assert "1 closed trade" in out
    assert "30-50" in out
    assert "low-confidence" in out


def test_cli_report_json(monkeypatch, capsys):
    monkeypatch.setattr(cr.portfolio, "closed_trades", lambda: [])
    import argparse
    rc = cr.cmd_report(argparse.Namespace(json=True))
    assert rc == 0
    out = capsys.readouterr().out
    import json
    parsed = json.loads(out)
    assert parsed["n_closed"] == 0
