"""
test_adr_tag.py — the 🌏 Asian-ADR discovery tag.

Two contracts:
1. Data: `screener.adr_regions()` is the source of truth for which universe names
   are ADRs + their region. Every ADR must also live in universe.json's sectors
   (else it's never scanned) — this pins the map⊆universe invariant that would
   otherwise silently drop a name.
2. Render: `dashboard.adr_badge_and_note(region)` composes the 🌏 badge WITH the
   tier tag (never replaces it), and only China carries the delisting-overhang risk.
"""
import json
import pathlib

import pytest

import screener
import dashboard

VALID_REGIONS = {"Taiwan", "China", "India", "Japan", "Singapore", "South Korea"}
UNIVERSE = pathlib.Path(__file__).resolve().parent.parent / ".claude" / "skills" / "us-screener" / "universe.json"


class TestAdrRegionsData:
    def test_map_nonempty_and_regions_valid(self):
        m = screener.adr_regions()
        assert len(m) >= 20                          # a real ADR set, not a stub
        assert all(v in VALID_REGIONS for v in m.values())

    def test_every_adr_is_in_the_scan_universe(self):
        # An ADR in the map but missing from sectors would never be fetched/tagged.
        m = screener.adr_regions()
        univ = {t.upper() for ts in json.loads(UNIVERSE.read_text())["sectors"].values() for t in ts}
        missing = sorted(t for t in m if t not in univ)
        assert missing == [], f"ADRs in map but not in universe sectors: {missing}"

    def test_us_names_are_not_adrs(self):
        m = screener.adr_regions()
        for t in ("AAPL", "MSFT", "SPY", "GS"):
            assert t not in m


class TestAdrBadge:
    def test_non_adr_renders_nothing(self):
        assert dashboard.adr_badge_and_note(None) == ("", "")
        assert dashboard.adr_badge_and_note("") == ("", "")

    def test_badge_composes_with_region(self):
        badge, note = dashboard.adr_badge_and_note("Taiwan")
        assert "🌏" in badge and "b-adr" in badge and "Taiwan" in badge
        assert "Taiwan" in note
        # Not a tier class — it's additive, never a tier replacement.
        assert "BUFFETT" not in badge and "b-green" not in badge

    def test_china_carries_delisting_risk(self):
        _b, note = dashboard.adr_badge_and_note("China")
        assert "PCAOB" in note or "delisting" in note

    def test_non_china_omits_delisting_risk(self):
        for region in ("Taiwan", "India", "Japan", "Singapore", "South Korea"):
            _b, note = dashboard.adr_badge_and_note(region)
            assert "PCAOB" not in note and "delisting" not in note
