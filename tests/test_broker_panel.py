"""
test_broker_panel.py — the read-only "Broker (MooMoo)" dashboard panel
(Bridge Phase 3).

moomoo_status.collect_broker_status() is pure data collection (reuses
broker-sync's own MOOMOO_ROOT resolution + cache files, reads MooMoo's
data/moomoo/*.json read-only); dashboard.render_broker_panel_html() renders
it. No order controls anywhere in this panel — see the vault note "Bridge
Contract — Trading Advisor ↔ MooMoo": execution stays in MooMoo only.
"""
import json
import sys
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"
sys.path.insert(0, str(DASH_DIR))
import dashboard  # noqa: E402
import moomoo_status  # noqa: E402
import broker_sync  # noqa: E402


# ── collect_broker_status ───────────────────────────────────────────────────
class TestCollectBrokerStatus:
    def test_unconfigured_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(broker_sync, "moomoo_root", lambda: None)
        status = moomoo_status.collect_broker_status()
        assert status["configured"] is False
        assert status["error"] is None

    def test_missing_moomoo_data_dir_degrades_gracefully(self, monkeypatch, tmp_path, tmp_path_factory):
        root = tmp_path_factory.mktemp("moomoo_empty")
        monkeypatch.setattr(broker_sync, "moomoo_root", lambda: root)
        state_dir = tmp_path / "ta_state"
        monkeypatch.setattr(broker_sync, "STATE_PATH", state_dir / "sync_state.json")
        monkeypatch.setattr(broker_sync, "REVIEW_PATH", state_dir / "review.json")

        status = moomoo_status.collect_broker_status()
        assert status["configured"] is True
        assert status["sync"]["n_tracked"] == 0
        assert status["review"]["items"] == []
        assert status["real"]["positions"] == []
        assert status["real"]["realized_pl"] is None

    def test_reads_real_moomoo_shaped_data(self, monkeypatch, tmp_path):
        root = tmp_path / "moomoo_root"
        moomoo_data = root / "data" / "moomoo"
        moomoo_data.mkdir(parents=True)
        (moomoo_data / "positions.json").write_text(json.dumps({
            "as_of": "2026-07-02T00:00:00+00:00",
            "positions": [{"code": "US.NVDA", "name": "NVIDIA", "qty": 1.0,
                          "market_value": 198.49, "unrealized_pl": 198.75}],
        }))
        (moomoo_data / "trade_ledger.json").write_text(json.dumps({
            "as_of": "2026-07-02T02:11:55+00:00",
            "summary": {"realized_pl": 468.38, "total_fees": 67.38,
                       "realized_trade_count": 2, "open_lot_count": 9, "issue_count": 4},
        }))
        monkeypatch.setattr(broker_sync, "moomoo_root", lambda: root)
        state_dir = tmp_path / "ta_state"
        (state_dir).mkdir()
        (state_dir / "sync_state.json").write_text(json.dumps({
            "as_of": "2026-07-02T06:00:00+00:00",
            "synced": {
                "trading_advisor:AUPH:x": {
                    "journal_stem": "2026-06-03_AUPH", "order_id": "FM123",
                    "last_filled_qty": 353, "last_broker_status": "FILLED_ALL",
                    "last_approval_state": "filled", "last_action": "flip_live",
                    "synced_at": "2026-07-02T06:00:00+00:00",
                },
            },
        }))
        (state_dir / "review.json").write_text(json.dumps({
            "as_of": "2026-07-02T06:00:00+00:00",
            "items": [{"code": "GME", "review_reason": "sell_fill_needs_manual_review", "note": "SELL 10 @ 25"}],
        }))
        monkeypatch.setattr(broker_sync, "STATE_PATH", state_dir / "sync_state.json")
        monkeypatch.setattr(broker_sync, "REVIEW_PATH", state_dir / "review.json")

        status = moomoo_status.collect_broker_status()
        assert status["configured"] is True
        assert status["sync"]["n_tracked"] == 1
        assert status["sync"]["intents"][0]["ticker"] == "AUPH"  # derived from journal_stem
        assert status["sync"]["intents"][0]["filled_qty"] == 353
        assert len(status["review"]["items"]) == 1
        assert status["real"]["positions"][0]["code"] == "US.NVDA"
        assert status["real"]["realized_pl"] == 468.38
        assert status["real"]["issue_count"] == 4

    def test_never_submitted_intent_shows_parsed_ticker_not_raw_intent_id(self, monkeypatch, tmp_path):
        # Real bug caught by live-verifying against MooMoo's actual on-disk data
        # (2026-07-02): an observed-but-never-submitted staged order has no
        # journal_stem (never got a resolved journal_path) — the ticker column
        # must not fall back to the whole raw intent_id string.
        root = tmp_path / "moomoo_root"
        (root / "data" / "moomoo").mkdir(parents=True)
        monkeypatch.setattr(broker_sync, "moomoo_root", lambda: root)
        state_dir = tmp_path / "ta_state"; state_dir.mkdir()
        long_path = "_Volumes_Mac_Mini_SSD_Projects_Claude_Trading_Advisor_journal_2026-06-03_AUPH.md"
        (state_dir / "sync_state.json").write_text(json.dumps({
            "as_of": "2026-07-02T06:00:00+00:00",
            "synced": {f"trading_advisor:AUPH:{long_path}": {
                "journal_stem": None, "order_id": None, "last_filled_qty": None,
                "last_broker_status": None, "last_approval_state": "staged",
                "last_action": "none", "synced_at": "2026-07-02T06:00:00+00:00",
            }},
        }))
        (state_dir / "review.json").write_text(json.dumps({"as_of": None, "items": []}))
        monkeypatch.setattr(broker_sync, "STATE_PATH", state_dir / "sync_state.json")
        monkeypatch.setattr(broker_sync, "REVIEW_PATH", state_dir / "review.json")

        status = moomoo_status.collect_broker_status()
        assert status["sync"]["intents"][0]["ticker"] == "AUPH"


# ── render_broker_panel_html ────────────────────────────────────────────────
class TestRenderBrokerPanel:
    def test_unconfigured_renders_gracefully_with_hint(self):
        frag = dashboard.render_broker_panel_html({"configured": False, "error": None})
        assert "Broker (MooMoo)" in frag
        assert "MOOMOO_ROOT" in frag

    def test_none_status_is_handled(self):
        frag = dashboard.render_broker_panel_html(None)
        assert "Broker (MooMoo)" in frag

    def test_configured_no_activity_renders_empty_state(self):
        status = {
            "configured": True, "error": None, "moomoo_root": "/x",
            "sync": {"as_of": None, "n_tracked": 0, "intents": []},
            "review": {"as_of": None, "items": []},
            "real": {"positions_as_of": None, "positions": [], "ledger_as_of": None,
                     "realized_pl": None, "total_fees": None, "realized_trade_count": None,
                     "open_lot_count": None, "issue_count": None},
        }
        frag = dashboard.render_broker_panel_html(status)
        assert "No SIMULATE staged orders tracked yet" in frag
        assert "⚠ Needs review" not in frag  # no review section when empty

    def test_intent_table_renders_ticker_and_action(self):
        status = {
            "configured": True, "error": None, "moomoo_root": "/x",
            "sync": {"as_of": "2026-07-02T06:00:00+00:00", "n_tracked": 1, "intents": [
                {"intent_id": "a", "ticker": "AUPH", "journal_stem": "2026-06-03_AUPH",
                 "order_id": "FM123", "filled_qty": 353, "broker_status": "FILLED_ALL",
                 "approval_state": "filled", "last_action": "flip_live",
                 "synced_at": "2026-07-02T06:00:00+00:00"},
            ]},
            "review": {"as_of": None, "items": []},
            "real": {"positions_as_of": None, "positions": [], "ledger_as_of": None,
                     "realized_pl": None, "total_fees": None, "realized_trade_count": None,
                     "open_lot_count": None, "issue_count": None},
        }
        frag = dashboard.render_broker_panel_html(status)
        assert "AUPH" in frag
        assert "flip_live" in frag
        assert "353" in frag

    def test_review_items_render_in_flagged_section(self):
        status = {
            "configured": True, "error": None, "moomoo_root": "/x",
            "sync": {"as_of": None, "n_tracked": 0, "intents": []},
            "review": {"as_of": "2026-07-02T06:00:00+00:00", "items": [
                {"code": "GME", "review_reason": "sell_fill_needs_manual_review", "note": "SELL 10 @ 25"},
            ]},
            "real": {"positions_as_of": None, "positions": [], "ledger_as_of": None,
                     "realized_pl": None, "total_fees": None, "realized_trade_count": None,
                     "open_lot_count": None, "issue_count": None},
        }
        frag = dashboard.render_broker_panel_html(status)
        assert "⚠ Needs review" in frag
        assert "GME" in frag
        assert "sell_fill_needs_manual_review" in frag

    def test_real_positions_are_labeled_not_paper_trading(self):
        status = {
            "configured": True, "error": None, "moomoo_root": "/x",
            "sync": {"as_of": None, "n_tracked": 0, "intents": []},
            "review": {"as_of": None, "items": []},
            "real": {"positions_as_of": "2026-07-02T00:00:00+00:00",
                     "positions": [{"code": "US.NVDA", "name": "NVIDIA", "qty": 1.0,
                                    "market_value": 198.49, "unrealized_pl": 198.75}],
                     "ledger_as_of": "2026-07-02T02:11:55+00:00",
                     "realized_pl": 468.38, "total_fees": 67.38,
                     "realized_trade_count": 2, "open_lot_count": 9, "issue_count": 4},
        }
        frag = dashboard.render_broker_panel_html(status)
        assert "NOT paper trading" in frag
        assert "US.NVDA" in frag
        assert "468" in frag  # realized P&L
        assert "4 ledger issue(s)" in frag

    def test_no_order_controls_anywhere_in_the_panel(self):
        # The one invariant that must never regress: this panel is read-only.
        status = {
            "configured": True, "error": None, "moomoo_root": "/x",
            "sync": {"as_of": None, "n_tracked": 1, "intents": [
                {"intent_id": "a", "ticker": "AUPH", "journal_stem": "x", "order_id": "FM1",
                 "filled_qty": 100, "broker_status": "FILLED_ALL", "approval_state": "filled",
                 "last_action": "flip_live", "synced_at": None},
            ]},
            "review": {"as_of": None, "items": [{"code": "X", "review_reason": "r", "note": "n"}]},
            "real": {"positions_as_of": None,
                     "positions": [{"code": "US.X", "name": "X", "qty": 1, "market_value": 1, "unrealized_pl": 1}],
                     "ledger_as_of": None, "realized_pl": 1, "total_fees": 1,
                     "realized_trade_count": 1, "open_lot_count": 1, "issue_count": 1},
        }
        frag = dashboard.render_broker_panel_html(status)
        for forbidden in ("submit-live", "place_order", "cancel_paper_order", "modify_paper_order",
                          "onclick=\"taSubmit", "onclick=\"taCancel", "onclick=\"taModify"):
            assert forbidden not in frag


class TestClientWiring:
    def test_panel_is_wired_into_the_page(self):
        src = (DASH_DIR / "dashboard.py").read_text()
        assert "{broker_panel}" in src
        assert "render_broker_panel_html" in src
        assert "collect_broker_status" in src
