"""
test_watcher_parse.py — journal level extraction + market-hours gate + dedupe.

The watcher fires alerts when price tags a level. If `parse_levels` misreads a
table (pulls "20-EMA" or "2R" as a price, or grabs the account size as TP2), the
operator gets alerted at the wrong level. Pins the currency-only parser and the
once-per-day dedupe.
"""
from datetime import datetime, timezone
import watcher


STD_TABLE = """# AUPH

**Status:** PROSPECTUS

| | Value | Logic |
|---|---|---|
| Entry trigger | $15.20 to $15.50 | zone |
| Stop-loss | **$13.98** | 1.5× ATR |
| TP1 | **$18.00** | 2R above entry |
| TP2 | trail behind 20-EMA | no fixed level |
"""


class TestParseLevels:
    def test_extracts_standard_levels(self):
        lv = watcher.parse_levels(STD_TABLE)
        assert lv["entry"] == 15.50      # zone high (max of the row's numbers)
        assert lv["stop"] == 13.98
        assert lv["tp1"] == 18.00

    def test_skips_non_currency_tp2(self):
        # "trail behind 20-EMA" has the number 20 but no $ → not a level
        lv = watcher.parse_levels(STD_TABLE)
        assert "tp2" not in lv

    def test_ignores_non_table_prose(self):
        txt = "Some prose mentioning $99.00 and a 20-EMA, no table here.\n"
        assert watcher.parse_levels(txt) == {}

    def test_account_size_outside_table_not_misread(self):
        txt = STD_TABLE + "\n- Account size at draft: $20,000\n"
        lv = watcher.parse_levels(txt)
        # account line is not a table row → must not pollute levels
        assert lv["entry"] == 15.50
        assert lv.get("stop") == 13.98
        assert 20000 not in lv.values()

    def test_malformed_row_too_few_cells_skipped(self):
        txt = "**Status:** LIVE\n\n| Stop $13.98 |\n"   # only 2 cells, no logic col
        assert watcher.parse_levels(txt) == {}

    def test_myr_currency_recognized(self):
        txt = "x\n\n| Stop-loss | MYR 1.25 | structure |\n"
        assert watcher.parse_levels(txt)["stop"] == 1.25


class TestFloats:
    def test_only_currency_marked_numbers(self):
        assert watcher._floats("$15.20 and 20-EMA and 2R and $18") == [15.20, 18.0]

    def test_empty_when_no_currency(self):
        assert watcher._floats("RSI 42, 1.5x ATR, Jun 17") == []


class TestMarketHours:
    def test_weekend_closed(self):
        sat = datetime(2026, 6, 13, 18, 0, tzinfo=timezone.utc)  # Saturday
        assert watcher.us_market_open(sat) is False

    def test_weekday_midday_open(self):
        # 15:00 UTC = 11:00 EDT on a Thursday → open
        thu = datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc)
        assert watcher.us_market_open(thu) is True

    def test_weekday_before_open(self):
        # 12:00 UTC = 08:00 EDT → before 09:30 open
        thu = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
        assert watcher.us_market_open(thu) is False


class TestDedupe:
    def test_fired_today_is_deduped(self):
        state = {}
        key = "AUPH:entry:15.5"
        assert watcher.already_fired(state, key) is False
        watcher.mark_fired(state, key)
        assert watcher.already_fired(state, key) is True

    def test_different_key_not_deduped(self):
        state = {}
        watcher.mark_fired(state, "AUPH:entry:15.5")
        assert watcher.already_fired(state, "AUPH:stop:13.98") is False
