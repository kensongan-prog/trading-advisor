"""
test_broker_sync.py — TA-side Phase 2 of the Trading Advisor <-> MooMoo bridge.

Covers the full contract from the vault note "Bridge Contract — Trading
Advisor <-> MooMoo": read-only MooMoo ingestion, exact traceability via
journal_path (not heuristic ticker matching), BUY-fill-only auto-actions,
SELL-always-review, never-regress, never-touch-a-terminal-journal, and
idempotent re-runs (a second sync with no new fills performs zero writes).
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import broker_sync as bs
import j


# ── decide_action — pure logic, the core of the design ─────────────────────
class TestDecideAction:
    def test_no_journal_resolved_is_review(self):
        action, reason, _ = bs.decide_action({"side": "BUY", "filled_qty": 5}, None, None)
        assert action == "review" and reason == "journal_path_not_found"

    def test_unsupported_side_is_review(self):
        action, reason, _ = bs.decide_action({"side": "SHORT", "filled_qty": 5}, "PROSPECTUS", None)
        assert action == "review" and reason == "unsupported_side"

    def test_staged_unfilled_order_with_no_journal_path_yet_is_not_flagged(self):
        # The REAL common case (verified against MooMoo's actual staged_orders.json,
        # 2026-07-02): a staged-but-not-yet-submitted order has approval_state
        # "staged", no order_id, no filled_qty, and no journal_path field at all.
        # There is nothing to attribute yet -- this must be a quiet 'none', not a
        # review item. journal_status=None (unresolved) must NOT be checked before
        # the no-fill-yet short-circuit.
        action, reason, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": None, "journal_path": None}, None, None)
        assert action == "none" and reason is None

    def test_sell_with_fill_is_always_review_never_auto_close(self):
        action, reason, _ = bs.decide_action(
            {"side": "SELL", "filled_qty": 100, "filled_avg_price": 17.65}, "LIVE — paper", None)
        assert action == "review" and reason == "sell_fill_needs_manual_review"

    def test_sell_no_fill_yet_is_none(self):
        action, _, _ = bs.decide_action({"side": "SELL", "filled_qty": None}, "LIVE — paper", None)
        assert action == "none"

    def test_buy_no_fill_yet_is_none(self):
        action, _, _ = bs.decide_action({"side": "BUY", "filled_qty": 0}, "PROSPECTUS", None)
        assert action == "none"
        action, _, _ = bs.decide_action({"side": "BUY", "filled_qty": None}, "PROSPECTUS", None)
        assert action == "none"

    def test_buy_first_fill_on_prospectus_flips_live(self):
        action, reason, note = bs.decide_action(
            {"side": "BUY", "filled_qty": 353, "filled_avg_price": 15.42}, "PROSPECTUS — pending entry trigger.", None)
        assert action == "flip_live" and reason is None
        assert "353" in note

    def test_buy_fill_grown_on_live_journal_is_update(self):
        prior = {"last_filled_qty": 100}
        action, reason, note = bs.decide_action(
            {"side": "BUY", "filled_qty": 353, "filled_avg_price": 15.42}, "LIVE — paper", prior)
        assert action == "update_partial" and reason is None
        assert "100" in note and "353" in note

    def test_buy_no_change_since_last_sync_is_none_idempotent(self):
        prior = {"last_filled_qty": 353}
        action, _, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": 353, "filled_avg_price": 15.42}, "LIVE — paper", prior)
        assert action == "none"

    def test_buy_fill_decreased_is_review_never_acted_on(self):
        prior = {"last_filled_qty": 353}
        action, reason, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": 100, "filled_avg_price": 15.42}, "LIVE — paper", prior)
        assert action == "review" and reason == "filled_qty_decreased"

    def test_closed_journal_is_never_touched_even_with_a_fill(self):
        action, reason, note = bs.decide_action(
            {"side": "BUY", "filled_qty": 353, "filled_avg_price": 15.42}, "CLOSED — win (+2.05R)", None)
        assert action == "skip_journal_ahead" and reason is None
        assert "CLOSED" in note

    def test_dead_journal_is_never_touched(self):
        action, _, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": 353, "filled_avg_price": 15.42}, "DEAD — trigger missed", None)
        assert action == "skip_journal_ahead"

    def test_non_integer_fill_qty_is_review(self):
        action, reason, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": 12.7, "filled_avg_price": 1.0}, "PROSPECTUS", None)
        assert action == "review" and reason == "non_integer_fill_qty"

    def test_unexpected_status_text_is_review_not_a_guess(self):
        action, reason, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": 100, "filled_avg_price": 1.0}, "SOME GARBLED STATUS", None)
        assert action == "review" and reason == "unexpected_journal_status"

    def test_empty_status_treated_like_fresh_prospectus(self):
        action, _, _ = bs.decide_action(
            {"side": "BUY", "filled_qty": 100, "filled_avg_price": 1.0}, "", None)
        assert action == "flip_live"


# ── build_plan / execute_plan — integration against real journal files ─────
def _new_args(**over):
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
    monkeypatch.setattr(j, "invalidate_dashboard_cache", lambda *a, **k: None)
    monkeypatch.setattr(j, "sync_portfolio", lambda *a, **k: None)
    return tmp_path


def _make_prospectus(tmp_journal, ticker="AUPH", **over):
    assert j.cmd_new(_new_args(ticker=ticker, **over)) == 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = tmp_journal / f"{today}_{ticker.replace('.', '_')}.md"
    assert p.exists()
    return p


def _staged(journal_path, **over):
    base = dict(
        intent_id="trading_advisor:AUPH:x", env="SIMULATE", market="US", code="AUPH",
        side="BUY", order_id="FM123", broker_status="FILLED_ALL", approval_state="filled",
        filled_qty=353, filled_avg_price=15.42, fill_count=1, last_fill_at="2026-07-01 09:35:00",
        journal_path=str(journal_path),
    )
    base.update(over)
    return base


class TestBuildAndExecutePlan:
    def test_resolves_by_full_stem_not_raw_path(self, tmp_journal):
        # journal_path encodes a DIFFERENT machine's absolute prefix -- only the
        # basename should matter for resolution (exact traceability, not the string).
        real = _make_prospectus(tmp_journal)
        fake_other_machine_path = f"/some/other/machine/checkout/journal/{real.name}"
        plan = bs.build_plan([_staged(fake_other_machine_path)], {"synced": {}})
        assert plan[0]["journal_stem"] == real.stem
        assert plan[0]["action"] == "flip_live"

    def test_unresolvable_journal_path_is_review(self, tmp_journal):
        plan = bs.build_plan([_staged("/nowhere/2099-01-01_ZZZZ.md")], {"synced": {}})
        assert plan[0]["action"] == "review"
        assert plan[0]["review_reason"] == "journal_path_not_found"

    def test_end_to_end_flip_live_then_idempotent_rerun(self, tmp_journal):
        p = _make_prospectus(tmp_journal)
        staged = [_staged(p)]

        # First sync: fresh PROSPECTUS + a fill -> flips LIVE.
        plan1 = bs.build_plan(staged, {"synced": {}})
        assert plan1[0]["action"] == "flip_live"
        synced1, review1, executed1 = bs.execute_plan(plan1)
        assert executed1 == 1 and review1 == []
        text = p.read_text()
        assert "LIVE — paper" in text
        assert "MooMoo broker-sync — order FM123" in text

        # Second sync, SAME broker state, using the persisted sync_state ->
        # must be a pure no-op (idempotency): zero further journal writes.
        mtime_before = p.stat().st_mtime_ns
        plan2 = bs.build_plan(staged, {"synced": synced1})
        assert plan2[0]["action"] == "none"
        synced2, review2, executed2 = bs.execute_plan(plan2)
        assert executed2 == 0 and review2 == []
        assert p.stat().st_mtime_ns == mtime_before, "idempotent re-run must not touch the journal file"

    def test_partial_fill_growth_across_multiple_syncs(self, tmp_journal):
        p = _make_prospectus(tmp_journal)

        # Run 1: partial fill of 100/353 -> flips live.
        staged_partial = [_staged(p, filled_qty=100, filled_avg_price=15.40,
                                  approval_state="partially_filled", broker_status="FILLED_PART")]
        plan1 = bs.build_plan(staged_partial, {"synced": {}})
        assert plan1[0]["action"] == "flip_live"
        synced1, _, executed1 = bs.execute_plan(plan1)
        assert executed1 == 1
        assert "LIVE — paper" in p.read_text()

        # Run 2: fill grew to 250/353 -> update note, NOT a re-flip.
        staged_grown = [_staged(p, filled_qty=250, filled_avg_price=15.41,
                                approval_state="partially_filled", broker_status="FILLED_PART")]
        plan2 = bs.build_plan(staged_grown, {"synced": synced1})
        assert plan2[0]["action"] == "update_partial"
        synced2, _, executed2 = bs.execute_plan(plan2)
        assert executed2 == 1
        text = p.read_text()
        assert text.count("Status → LIVE") == 1, "must not re-flip an already-LIVE journal"
        assert "fill grew to 250" in text

        # Run 3: fully filled at 353/353 -> another update, still not a re-flip.
        staged_full = [_staged(p, filled_qty=353, filled_avg_price=15.42,
                               approval_state="filled", broker_status="FILLED_ALL")]
        plan3 = bs.build_plan(staged_full, {"synced": synced2})
        assert plan3[0]["action"] == "update_partial"
        synced3, _, executed3 = bs.execute_plan(plan3)
        assert executed3 == 1
        text = p.read_text()
        assert text.count("Status → LIVE") == 1
        assert "fill grew to 353" in text

        # Run 4: same state again -> idempotent no-op.
        plan4 = bs.build_plan(staged_full, {"synced": synced3})
        assert plan4[0]["action"] == "none"

    def test_never_touches_a_closed_journal(self, tmp_journal):
        p = _make_prospectus(tmp_journal)
        stem = p.stem
        # Operator manually closes it BEFORE broker-sync ever runs.
        assert j.cmd_live(SimpleNamespace(id=stem, paper=True, real=False, fill=15.42,
                                          shares=353, time=None, notes=None, yes=True)) == 0
        assert j.cmd_close(SimpleNamespace(id=stem, result="win", r=None, entry=15.42, stop=14.26,
                                           exit="17.65", shares=None, price=None, notes=None, yes=True)) == 0
        closed_text_before = p.read_text()

        staged = [_staged(p, filled_qty=353, filled_avg_price=15.42)]
        plan = bs.build_plan(staged, {"synced": {}})
        assert plan[0]["action"] == "skip_journal_ahead"
        synced, review, executed = bs.execute_plan(plan)
        assert executed == 0
        assert p.read_text() == closed_text_before, "a CLOSED journal must never be mutated by broker-sync"

    def test_sell_fill_lands_in_review_not_executed(self, tmp_journal):
        p = _make_prospectus(tmp_journal)
        stem = p.stem
        assert j.cmd_live(SimpleNamespace(id=stem, paper=True, real=False, fill=15.42,
                                          shares=353, time=None, notes=None, yes=True)) == 0
        text_before = p.read_text()

        staged = [_staged(p, side="SELL", filled_qty=353, filled_avg_price=17.65)]
        plan = bs.build_plan(staged, {"synced": {}})
        assert plan[0]["action"] == "review"
        assert plan[0]["review_reason"] == "sell_fill_needs_manual_review"
        synced, review, executed = bs.execute_plan(plan)
        assert executed == 0
        assert len(review) == 1
        assert p.read_text() == text_before, "SELL fills must never be auto-executed"

    def test_regression_in_filled_qty_is_flagged_not_acted_on(self, tmp_journal):
        p = _make_prospectus(tmp_journal)
        stem = p.stem
        assert j.cmd_live(SimpleNamespace(id=stem, paper=True, real=False, fill=15.40,
                                          shares=100, time=None, notes=None, yes=True)) == 0
        prior_state = {"synced": {"trading_advisor:AUPH:x": {"last_filled_qty": 100}}}

        staged = [_staged(p, filled_qty=40, filled_avg_price=15.40)]  # broker data went BACKWARDS
        plan = bs.build_plan(staged, prior_state)
        assert plan[0]["action"] == "review"
        assert plan[0]["review_reason"] == "filled_qty_decreased"


# ── config ───────────────────────────────────────────────────────────────
class TestConfig:
    def test_missing_moomoo_root_returns_none(self, monkeypatch):
        monkeypatch.delenv("MOOMOO_ROOT", raising=False)
        monkeypatch.setattr(bs, "SCRIPT_DIR", bs.SCRIPT_DIR.parent / "_no_such_skill_dir_")
        assert bs.moomoo_root() is None

    def test_nonexistent_dir_is_rejected_not_guessed(self, monkeypatch):
        monkeypatch.setenv("MOOMOO_ROOT", "/definitely/does/not/exist/anywhere")
        assert bs.moomoo_root() is None

    def test_valid_dir_is_returned(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MOOMOO_ROOT", str(tmp_path))
        assert bs.moomoo_root() == tmp_path


class TestCliOrchestration:
    """cmd_sync / cmd_show themselves — confirm flow, state persistence, the
    parts build_plan/execute_plan tests above don't cover directly."""

    def test_main_refuses_retired_workflow_without_explicit_legacy_override(self, monkeypatch, capsys):
        monkeypatch.delenv(bs.LEGACY_ENABLE_ENV, raising=False)
        assert bs.main() == 2
        assert "deprecated" in capsys.readouterr().err

    def _patch_moomoo(self, monkeypatch, tmp_path, staged_rows):
        moomoo_dir = tmp_path / "moomoo_root" / "data" / "moomoo"
        moomoo_dir.mkdir(parents=True)
        (moomoo_dir / "staged_orders.json").write_text(
            json.dumps({"orders": staged_rows}))
        monkeypatch.setattr(bs, "moomoo_root", lambda: tmp_path / "moomoo_root")
        state_dir = tmp_path / "ta_state"
        monkeypatch.setattr(bs, "STATE_PATH", state_dir / "sync_state.json")
        monkeypatch.setattr(bs, "REVIEW_PATH", state_dir / "review.json")

    def test_sync_without_yes_prompts_and_aborts_on_no(self, tmp_journal, tmp_path, monkeypatch, capsys):
        p = _make_prospectus(tmp_journal)
        self._patch_moomoo(monkeypatch, tmp_path, [_staged(p)])
        monkeypatch.setattr(j, "confirm", lambda *a, **k: False)  # operator says no

        rc = bs.cmd_sync(SimpleNamespace(yes=False))
        assert rc == 0
        assert "Aborted" in capsys.readouterr().out
        # PROSPECTUS boilerplate text itself mentions "LIVE"; check the actual
        # status-flip marker, not a bare substring.
        assert "**Status:** LIVE" not in p.read_text()

    def test_sync_with_yes_executes_without_prompting(self, tmp_journal, tmp_path, monkeypatch):
        p = _make_prospectus(tmp_journal)
        self._patch_moomoo(monkeypatch, tmp_path, [_staged(p)])
        monkeypatch.setattr(j, "confirm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not prompt with --yes")))

        rc = bs.cmd_sync(SimpleNamespace(yes=True))
        assert rc == 0
        assert "LIVE — paper" in p.read_text()
        assert bs.STATE_PATH.is_file()

    def test_sync_missing_moomoo_root_errors_cleanly(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bs, "moomoo_root", lambda: None)
        rc = bs.cmd_sync(SimpleNamespace(yes=True))
        assert rc == 2

    def test_show_reads_back_persisted_state(self, tmp_journal, tmp_path, monkeypatch, capsys):
        p = _make_prospectus(tmp_journal)
        self._patch_moomoo(monkeypatch, tmp_path, [_staged(p)])
        assert bs.cmd_sync(SimpleNamespace(yes=True)) == 0

        out = capsys.readouterr()  # drain sync's output
        rc = bs.cmd_show(SimpleNamespace())
        assert rc == 0
        shown = capsys.readouterr().out
        assert "flip_live" in shown
        assert p.stem in shown


class TestLoadStagedOrders:
    def test_filters_to_simulate_only(self, tmp_path):
        moomoo_dir = tmp_path / "data" / "moomoo"
        moomoo_dir.mkdir(parents=True)
        (moomoo_dir / "staged_orders.json").write_text('''
            {"orders": [
                {"intent_id": "a", "env": "SIMULATE"},
                {"intent_id": "b", "env": "REAL"},
                {"intent_id": "c", "env": "simulate"}
            ]}
        ''')
        rows = bs.load_staged_orders(tmp_path)
        assert {r["intent_id"] for r in rows} == {"a", "c"}

    def test_missing_file_returns_empty_not_an_error(self, tmp_path):
        assert bs.load_staged_orders(tmp_path) == []
