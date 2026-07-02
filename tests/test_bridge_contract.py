"""
test_bridge_contract.py — TA ↔ MooMoo bridge contract (TA side).

The MooMoo broker adapter (Projects/Codex/MooMoo, src/moomoo_adapter/
trading_advisor.py) reads THIS repo's watchlist.md + journal/*.md read-only and
parses them into trade intents. These tests pin the TA-side formats that parser
keys on, so a formatting change here (watchlist bullet style, j.py prospectus
template, status-flip strings) fails fast instead of silently breaking the
import on the MooMoo side.

The regexes below are MIRRORS of MooMoo's parser — keep in sync with
src/moomoo_adapter/trading_advisor.py. Cross-agent contract doc: vault note
"Bridge Contract — Trading Advisor ↔ MooMoo". MooMoo's own tests
(tests/test_trading_advisor.py there) cover the parser direction.

Real journal/*.md files are operator-owned and untracked, so the journal-side
tests exercise the GENERATOR (j.py new/live/close) into a temp dir rather than
reading personal files.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import j

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Mirrors of MooMoo's contract regexes (trading_advisor.py) ─────────────
WATCHLIST_ROW = re.compile(r"- `([^`]+)`\s+[-:–—]\s+(.+)")
CLOSED_STATUS = re.compile(r"\*\*Status:\*\*\s*CLOSED\b", re.IGNORECASE)
CLOSED_ARROW = re.compile(r"Status\s*→\s*CLOSED\b", re.IGNORECASE)
CLOSED_REALIZED_R = re.compile(r"^-\s*Realized R-(?:multiple)?:[ \t]*[-+0-9.]", re.IGNORECASE | re.MULTILINE)
NUM = r"([0-9]+(?:\.[0-9]+)?)"
LEVEL_ENTRY = re.compile(r"Reference entry:\s*\$?" + NUM, re.IGNORECASE)
LEVEL_STOP = re.compile(r"Stop:\s*\$?" + NUM, re.IGNORECASE)
LEVEL_TP1 = re.compile(r"\|\s*TP1[^\|]*\|[^\n$]*\$?" + NUM, re.IGNORECASE)


def _is_closed(text):
    return bool(CLOSED_STATUS.search(text) or CLOSED_ARROW.search(text)
                or ("## Exit" in text and CLOSED_REALIZED_R.search(text)))


# ── Watchlist format ──────────────────────────────────────────────────────
class TestWatchlistContract:
    def test_every_ticker_bullet_matches_bridge_pattern(self):
        # Any line that LOOKS like a ticker row ("- `") must parse with MooMoo's
        # row regex — catches drift to a different separator/bullet style.
        text = (PROJECT_ROOT / "watchlist.md").read_text()
        offenders = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("- `") and not WATCHLIST_ROW.match(s):
                offenders.append(s[:80])
        assert offenders == [], f"watchlist rows MooMoo cannot parse: {offenders}"

    def test_watchlist_yields_real_rows(self):
        text = (PROJECT_ROOT / "watchlist.md").read_text()
        rows = [m.group(1) for m in (WATCHLIST_ROW.match(l.strip())
                                     for l in text.splitlines()) if m]
        real = [r for r in rows if r.strip().upper() != "TICKER"]  # TICKER = example, skipped
        assert len(real) > 0


# ── Journal generator (j.py) ──────────────────────────────────────────────
def _new_args(**over):
    """Namespace covering every attribute cmd_new reads."""
    base = dict(
        ticker="AUPH", market="us", entry="15.39", stop="14.26", tp1="17.65",
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


@pytest.fixture
def tmp_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "JOURNAL_DIR", tmp_path)
    # cmd_live/cmd_close touch dashboard cache + portfolio sync — not under test
    monkeypatch.setattr(j, "invalidate_dashboard_cache", lambda *a, **k: None)
    monkeypatch.setattr(j, "sync_portfolio", lambda *a, **k: None)
    return tmp_path


def _make_stub(tmp_journal):
    assert j.cmd_new(_new_args()) == 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = tmp_journal / f"{today}_AUPH.md"
    assert p.exists()
    return p


class TestProspectusTemplateContract:
    def test_stub_carries_every_bridge_field(self, tmp_journal):
        text = _make_stub(tmp_journal).read_text()
        for needle in (
            "**Status:**",                 # status line MooMoo greps
            "## Recommendation",           # active-file marker
            "- **Action / structure:**",   # side inference (BUY/SELL)
            "| Entry trigger |",           # structured level fallbacks
            "| Stop-loss |",
            "| TP1 |",
            "Reference entry:",
            "Stop:",
            "- **Max loss:**",             # qty_or_risk field
        ):
            assert needle in text, f"prospectus template lost bridge field: {needle!r}"

    def test_stub_levels_parse_to_the_sim_numbers(self, tmp_journal):
        text = _make_stub(tmp_journal).read_text()
        assert float(LEVEL_ENTRY.search(text).group(1)) == 15.39
        assert float(LEVEL_STOP.search(text).group(1)) == 14.26
        assert float(LEVEL_TP1.search(text).group(1)) == 17.65

    def test_fresh_stub_is_not_detected_closed(self, tmp_journal):
        # The empty "## Exit" template (bare "- Realized R-multiple:" with no
        # number) must NOT trip MooMoo's closed detection.
        text = _make_stub(tmp_journal).read_text()
        assert _is_closed(text) is False

    def test_filename_stem_symbol_convention(self, tmp_journal):
        # MooMoo derives symbol from stem.split("_", 1)[1] — pin the US shape.
        p = _make_stub(tmp_journal)
        assert p.stem.split("_", 1)[1] == "AUPH"
        # KLSE caveat (documented in the bridge-contract vault note): j.py maps
        # "9431.KL" → stem "..._9431_KL", so MooMoo sees symbol "9431_KL" and
        # must normalize it back to Bursa form. Pin the TA-side shape it must handle.
        assert j.cmd_new(_new_args(ticker="9431.KL", market="klse",
                                   entry="1.25", stop="1.10", tp1="1.60")) == 0
        klse = [q for q in tmp_journal.glob("*_9431_KL.md")]
        assert len(klse) == 1


class TestStatusFlipContract:
    def test_live_then_close_matches_bridge_closed_detection(self, tmp_journal):
        p = _make_stub(tmp_journal)
        stem = p.stem
        rc = j.cmd_live(SimpleNamespace(id=stem, paper=True, real=False,
                                        fill=15.42, shares=353, time=None,
                                        notes=None, yes=True))
        assert rc == 0
        live_text = p.read_text()
        assert "LIVE — paper" in live_text
        assert _is_closed(live_text) is False  # live ≠ closed

        rc = j.cmd_close(SimpleNamespace(id=stem, result="win", r=None,
                                         entry=15.42, stop=14.26, exit="17.65",
                                         shares=None, price=None, notes=None,
                                         yes=True))
        assert rc == 0
        closed_text = p.read_text()
        # Both of MooMoo's closed signals must now fire: the status line AND
        # the filled Realized-R line in ## Exit.
        assert CLOSED_STATUS.search(closed_text)
        assert CLOSED_REALIZED_R.search(closed_text)
        assert _is_closed(closed_text) is True
