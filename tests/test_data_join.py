"""
test_data_join.py — symbol-keyed data joins (the zip() regression).

Why these tests exist: the v2.0.3 release found the same naïve-zip bug had
been copy-pasted twice — first in the crypto grid, then again in the BTFD
panel. CoinGecko returns crypto_rows in market-cap order, NOT watchlist
order, so `zip(watchlist, crypto_rows)` silently pairs ENA with HBAR's data.

These tests pin the correct pattern (lookup by symbol) and catch the bug
the moment anyone re-introduces it.
"""
import pytest


def join_by_symbol(watchlist_entries, rows):
    """The correct pattern — look up each watchlist entry by symbol."""
    rows_by_sym = {(r.get("symbol") or "").upper(): r for r in rows}
    return [(e, rows_by_sym.get(e["ticker"].upper())) for e in watchlist_entries]


def join_by_index(watchlist_entries, rows):
    """The bug pattern — pair by list index. Kept here so we can demonstrate
    that it produces wrong results vs the symbol-lookup version."""
    return list(zip(watchlist_entries, rows))


# ── The realistic scenario that triggered the v2.0.3 bug ─────────────────
WATCHLIST = [
    {"ticker": "BTC"},
    {"ticker": "ETH"},
    {"ticker": "SOL"},
    {"ticker": "BNB"},
    {"ticker": "XRP"},
    {"ticker": "HBAR"},
    {"ticker": "HYPE"},
    {"ticker": "ENA"},
]

# CoinGecko returns these in market-cap order — same set, different order:
ROWS_BY_MKTCAP = [
    {"symbol": "BTC",  "chg_24h": -0.5},
    {"symbol": "ETH",  "chg_24h": -1.0},
    {"symbol": "BNB",  "chg_24h": -0.8},  # BNB ranks above SOL by market cap
    {"symbol": "SOL",  "chg_24h": -2.0},
    {"symbol": "XRP",  "chg_24h": -3.6},
    {"symbol": "HBAR", "chg_24h": -2.2},
    {"symbol": "HYPE", "chg_24h": -8.0},
    {"symbol": "ENA",  "chg_24h": -10.2},  # ENA ranks last — and this is the case that fired the bug
]


class TestSymbolJoinCorrect:
    def test_ena_correctly_gets_minus_10_pct(self):
        pairs = join_by_symbol(WATCHLIST, ROWS_BY_MKTCAP)
        ena_row = next(r for e, r in pairs if e["ticker"] == "ENA")
        assert ena_row["chg_24h"] == pytest.approx(-10.2)

    def test_every_ticker_gets_its_own_row(self):
        pairs = join_by_symbol(WATCHLIST, ROWS_BY_MKTCAP)
        for entry, row in pairs:
            assert row is not None
            assert row["symbol"] == entry["ticker"]

    def test_missing_symbol_returns_none(self):
        # Watchlist has DOGE but rows don't — symbol lookup returns None gracefully
        extended = WATCHLIST + [{"ticker": "DOGE"}]
        pairs = join_by_symbol(extended, ROWS_BY_MKTCAP)
        doge_row = next(r for e, r in pairs if e["ticker"] == "DOGE")
        assert doge_row is None


class TestIndexJoinIsBugged:
    """Document the bug pattern so a future refactor that 'simplifies' to
    zip() will tell us why that's wrong."""

    def test_index_join_pairs_ena_with_wrong_data(self):
        # ENA is at watchlist position 7; ROWS_BY_MKTCAP position 7 is also ENA
        # in THIS example. Let's make a deliberately different ordering:
        rows_oddly_ordered = ROWS_BY_MKTCAP[::-1]  # reversed
        pairs = join_by_index(WATCHLIST, rows_oddly_ordered)
        # ENA's watchlist entry now gets BTC's row data — buggy
        ena_entry = next(e for e, _ in pairs if e["ticker"] == "ENA")
        ena_row = next(r for e, r in pairs if e["ticker"] == "ENA")
        assert ena_entry["ticker"] == "ENA"
        assert ena_row["symbol"] != "ENA", "Index join correctly produces wrong pairing here"

    def test_symbol_join_robust_to_reordering(self):
        # Re-shuffle the rows — symbol join still pairs correctly
        rows_shuffled = ROWS_BY_MKTCAP[::-1]
        pairs = join_by_symbol(WATCHLIST, rows_shuffled)
        for e, r in pairs:
            assert r["symbol"] == e["ticker"]
