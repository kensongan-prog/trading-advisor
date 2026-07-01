"""
test_klse_sentiment.py — KLSE community-comment fetcher (klsescreener).

Pure-logic tests over the HTML comment parser + recency window. This skill scrapes
server-rendered HTML with regex, so the parse contract is the fragile part: date↔body
pairing (each etime pairs with its OWN comment, never a neighbour's), HTML/entity
stripping, empty-body drop, and window filtering. Output must match the shape
sentiment_cache ingests (messages[].body + asset_class + no_coverage).

(KLSE *news* is intentionally NOT here — news_glyph.refresh_klse already scrapes
/v2/news/stock/{code}; a parallel fetcher would duplicate it. See notes/learned.md.)
"""
from datetime import date, timedelta

import klse_sentiment
import sentiment_cache as sc

COMMENTS_HTML = """
<div class="cardmy panel panel-default comment">
  <span class="date" etime="2026-06-27 10:00:00 +0800">1 week</span>
  <div class="comment-message ml-1">Wait for the breakout above 55 cents &amp; confirm volume<br>before you jump in</div>
</div>
<div class="cardmy panel panel-default comment">
  <span class="date" etime="2024-02-01 09:00:00 +0800">old</span>
  <div class="comment-message">   </div>
</div>
<div class="cardmy panel panel-default comment">
  <span class="date" etime="2026-06-05 12:00:00 +0800">3 weeks</span>
  <div class="comment-message"><a href="/x">DOOH</a> gives brands repeated exposure</div>
</div>
"""


def test_parse_pairs_date_and_body_and_strips_html():
    msgs = klse_sentiment.parse_comments(COMMENTS_HTML)
    # 3 blocks, but the middle one is whitespace-only → dropped
    assert len(msgs) == 2
    assert msgs[0]["date"] == "2026-06-27"
    assert msgs[0]["body"] == "Wait for the breakout above 55 cents & confirm volume before you jump in"
    assert msgs[1]["date"] == "2026-06-05"
    assert "DOOH gives brands" in msgs[1]["body"]
    assert "<a" not in msgs[1]["body"]


def test_each_etime_pairs_with_its_own_comment():
    # The (?!etime=) guard must stop a date binding to a later block's message.
    two = """
    <div><span etime="2026-06-01 00:00:00">x</span>
      <div class="comment-message">first</div></div>
    <div><span etime="2026-05-01 00:00:00">y</span>
      <div class="comment-message">second</div></div>
    """
    msgs = klse_sentiment.parse_comments(two)
    assert [(m["date"], m["body"]) for m in msgs] == [("2026-06-01", "first"), ("2026-05-01", "second")]


def test_window_filter():
    cutoff = date.today() - timedelta(days=180)
    recent = (date.today() - timedelta(days=10)).isoformat()
    old = (date.today() - timedelta(days=400)).isoformat()
    assert klse_sentiment._within_window(recent, cutoff) is True
    assert klse_sentiment._within_window(old, cutoff) is False
    assert klse_sentiment._within_window("garbage", cutoff) is False


def test_output_shape_matches_scorer_contract():
    # sentiment_cache.process_* reads raw["messages"][i]["body"]
    msgs = klse_sentiment.parse_comments(COMMENTS_HTML)
    assert all("body" in m and m["body"] for m in msgs)


# ── sentiment_cache composite integration ─────────────────────────────────
def _klse(bull, msgs, conv=0.7):
    return {"present": True, "llm_bull_pct": bull, "llm_bear_pct": round(1 - bull - 0.05, 3),
            "llm_neutral_pct": 0.05, "llm_avg_conviction": conv, "n_messages": msgs}


def test_composite_klse_only_produces_real_read():
    # A Bursa name with ONLY klse comments (the common case — ST 404s, Reddit thin)
    # must still yield a non-UNKNOWN composite, and its messages must count toward
    # the coverage haircut (else conviction would be dampened to ~0).
    comp = sc.compute_composite(None, None, None, _klse(0.8, 20))
    assert comp["bull_score"] == 0.8
    assert comp["label"] != "UNKNOWN"
    assert comp["conviction"] > 0            # coverage counted klse's 20 msgs


def test_composite_klse_blends_with_other_sources():
    st = {"present": True, "llm_bull_pct": 0.4, "llm_bear_pct": 0.4, "llm_neutral_pct": 0.2,
          "llm_avg_conviction": 0.6, "n_messages": 10}
    only_st = sc.compute_composite(st, None, None, None)["bull_score"]
    with_klse = sc.compute_composite(st, None, None, _klse(0.9, 20))["bull_score"]
    assert with_klse > only_st               # bullish klse pulls the blend up


def test_composite_backward_compatible_without_klse():
    # existing 3-arg callers must be unaffected
    st = {"present": True, "llm_bull_pct": 0.7, "llm_bear_pct": 0.2, "llm_neutral_pct": 0.1,
          "llm_avg_conviction": 0.5, "n_messages": 30}
    assert sc.compute_composite(st, None, None)["bull_score"] == 0.7


def test_load_klse_comments_maps_kl_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "KLSE_COMMENTS_CACHE", tmp_path)
    (tmp_path / "9431.json").write_text('{"ticker":"9431","messages":[{"body":"hi"}],"no_coverage":false}')
    raw = sc.load_klse_comments("9431.KL")
    assert raw and raw["ticker"] == "9431"
    assert sc.load_klse_comments("0293.KL") is None
