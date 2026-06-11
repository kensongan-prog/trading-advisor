"""
test_btfd_str.py — BTFD/STR tier classifier.

Why these tests exist: the v2.0.3 release found that the Action Rail count
diverged from the BTFD panel because the rail used a simplified inline
counter while the panel used the tiered table. Hoisting the classifier to
module level + tests pin the contract so the rail and panel can never
drift again, and so threshold tweaks have to update the tests too.
"""
import pytest
from dashboard import _classify_btfd_str_shared as classify


# ── BTFD tiers (drops) ─────────────────────────────────────────────────────
class TestBTFDEquity:
    def test_capitulation_full_match(self):
        # Equity CAP: chg ≤ -7, vol ≥ 2.5, RSI ≤ 30
        assert classify(-8.0, 3.0, 25, "equity") == "BTFD"

    def test_capitulation_fails_on_rsi(self):
        # Same drop + vol, but RSI > 30 → falls to next tier
        assert classify(-8.0, 3.0, 45, "equity") == "BTFD"  # real_dip

    def test_real_dip(self):
        assert classify(-5.0, 2.0, 35, "equity") == "BTFD"

    def test_light_dip_no_rsi_gate(self):
        # LIGHT_DIP has no RSI threshold; any RSI passes
        assert classify(-3.0, 1.5, 80, "equity") == "BTFD"

    def test_below_light_threshold(self):
        # -1.5% drop is below the -2% LIGHT threshold
        assert classify(-1.5, 1.5, 50, "equity") is None

    def test_vol_below_threshold(self):
        # Drop big enough but volume too small
        assert classify(-5.0, 1.0, 50, "equity") is None


class TestBTFDCrypto:
    def test_crypto_tiers_are_wider(self):
        # Crypto LIGHT_DIP requires -4% drop, vol ≥ 1.5 — not equity's -2/1.3
        assert classify(-3.0, 2.0, 50, "crypto") is None
        assert classify(-5.0, 1.6, 50, "crypto") == "BTFD"

    def test_capitulation_crypto(self):
        # Crypto CAP: chg ≤ -12, vol ≥ 3.0, RSI ≤ 25
        assert classify(-15.0, 3.5, 20, "crypto") == "BTFD"

    def test_real_dip_crypto(self):
        assert classify(-8.0, 2.2, 30, "crypto") == "BTFD"


# ── STR tiers (rallies) ────────────────────────────────────────────────────
class TestSTREquity:
    def test_blow_off(self):
        assert classify(+8.0, 3.0, 75, "equity") == "STR"

    def test_real_rip(self):
        assert classify(+5.0, 2.0, 65, "equity") == "STR"

    def test_light_rip(self):
        assert classify(+3.0, 1.5, 50, "equity") == "STR"  # no rsi gate at LIGHT

    def test_below_light_rip(self):
        # Move too small even for LIGHT_RIP (+2 threshold)
        assert classify(+1.5, 1.5, 50, "equity") is None


class TestSTRCrypto:
    def test_crypto_rip_thresholds_wider(self):
        assert classify(+3.0, 1.5, 50, "crypto") is None  # below crypto LIGHT_RIP +4
        assert classify(+5.0, 1.6, 50, "crypto") == "STR"


# ── Edge cases ────────────────────────────────────────────────────────────
class TestEdges:
    def test_none_chg(self):
        assert classify(None, 2.0, 50, "equity") is None

    def test_none_vol(self):
        assert classify(-5.0, None, 50, "equity") is None

    def test_unknown_asset_kind_returns_none(self):
        assert classify(-5.0, 2.0, 50, "fx") is None

    def test_zero_change_no_signal(self):
        assert classify(0.0, 1.5, 50, "equity") is None

    def test_btfd_priority_over_str(self):
        # Negative chg can only fire BTFD, never STR — direction is signed
        result = classify(-5.0, 2.0, 50, "equity")
        assert result == "BTFD"

    def test_high_tier_rsi_gate_at_boundary(self):
        # CAP RSI threshold is ≤30; 30 exactly should match
        assert classify(-8.0, 3.0, 30, "equity") == "BTFD"

    def test_light_rip_rsi_none_ignored(self):
        # LIGHT_RIP has no RSI gate, so RSI=None still passes
        assert classify(+3.0, 1.5, None, "equity") == "STR"
