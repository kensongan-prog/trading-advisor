"""
test_company_label.py — TICKER→company name resolution for LLM prompts.

Why these tests exist: v2.0.1 fixed KLSE Chinese-headline scoring by adding
the company label to the prompt. v2.0.4 made sentiment-cache reuse the same
map. The asset-class normalization (sentiment caches use 'us_equity'; map
keys are 'us') is the kind of detail that breaks silently — pin it.
"""
import pytest
import news_glyph as ng
import sentiment_cache as sc


class TestNewsGlyphLabels:
    def test_us_ticker_with_name(self):
        # KO → "KO (Coca-Cola)"
        label = ng._company_label("KO", "us")
        assert "Coca-Cola" in label
        assert "KO" in label

    def test_klse_code_resolves_to_chinese_form(self):
        # 9431 → must include Chinese form so the LLM can match Chinese-press headlines
        label = ng._company_label("9431", "klse")
        assert "Seni Jaya" in label
        assert "盛艺机构" in label

    def test_crypto_slug_lowercase(self):
        # CoinGecko slugs are lowercase
        label = ng._company_label("ethena", "crypto")
        assert "Ethena" in label

    def test_unknown_ticker_returns_bare(self):
        # Unmapped US ticker falls back to the bare symbol (not a crash)
        label = ng._company_label("ZZZZZ", "us")
        assert label == "ZZZZZ"

    def test_unknown_asset_class_falls_back(self):
        # Garbage asset class shouldn't crash; just returns bare ticker
        label = ng._company_label("KO", "futures")
        assert label == "KO"


class TestSentimentCacheBridge:
    def test_us_equity_normalized_to_us(self):
        # Sentiment caches store 'us_equity'; news_glyph map uses 'us'
        # The bridge must normalize so KO still resolves
        label = sc._company_label("KO", "us_equity")
        assert "Coca-Cola" in label

    def test_crypto_normalized(self):
        label = sc._company_label("ethena", "crypto")
        assert "Ethena" in label

    def test_klse_normalized(self):
        label = sc._company_label("9431", "klse")
        assert "Seni Jaya" in label

    def test_none_asset_class_defaults_to_us(self):
        # No asset_class info → assume US (most common case)
        label = sc._company_label("KO", None)
        assert "Coca-Cola" in label

    def test_synonyms_resolve(self):
        # 'equity' and 'stock' should map like 'us_equity'
        assert sc._company_label("KO", "equity") == sc._company_label("KO", "us")
        assert sc._company_label("KO", "stock") == sc._company_label("KO", "us")


class TestWatchlistCoverage:
    """Every watchlist ticker should resolve to a meaningful label (not just bare)."""

    WATCHLIST_US = ["AUPH", "CIFR", "CLOV", "CLSK", "KO", "KTOS", "MRVL", "PURR",
                    "RDDT", "RGLD", "RKLB", "SPY"]
    WATCHLIST_KLSE = ["0293", "4057", "7241", "9431"]

    @pytest.mark.parametrize("ticker", WATCHLIST_US)
    def test_us_watchlist_has_label(self, ticker):
        label = ng._company_label(ticker, "us")
        # P1 watchlist names should have a real company-name in the label
        # (label is "TICKER (Company)" so length > len(ticker) means something resolved)
        assert len(label) > len(ticker) + 2, f"{ticker} has no company label"

    @pytest.mark.parametrize("code", WATCHLIST_KLSE)
    def test_klse_watchlist_has_label(self, code):
        label = ng._company_label(code, "klse")
        assert len(label) > len(code) + 2, f"KLSE {code} has no company label"
