"""Checks for name search, peer suggestions, comparisons, and headline handling.
None of these touch the internet."""

from datetime import date, datetime

import pytest

from analyzer.compare import industry_medians, rank_in_group
from analyzer.edgar_client import build_search_options, build_ticker_table, \
    pretty_company_name, primary_ticker_by_cik
from analyzer.news import build_query, news_name, parse_articles
from analyzer.peers import rank_peers, recent_balance_sheet_periods

RAW_TICKERS = {
    "0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    "1": {"cik_str": 4962, "ticker": "AXP", "title": "AMERICAN EXPRESS CO"},
    "2": {"cik_str": 1067983, "ticker": "BRK-A", "title": "BERKSHIRE HATHAWAY INC"},
    "3": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}


# --- Company names and search ----------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("AMERICAN EXPRESS CO", "American Express Co"),
    ("BANK OF AMERICA CORP /DE/", "Bank of America Corp"),   # state tag removed
    ("Apple Inc.", "Apple Inc."),                    # already mixed case: untouched
    ("INTERNATIONAL BUSINESS MACHINES CORP", "International Business Machines Corp"),
    ("AT&T INC.", "AT&T Inc."),
    ("US BANCORP \\DE\\", "US Bancorp"),                   # backslash form too
])
def test_pretty_company_name(raw, expected):
    assert pretty_company_name(raw) == expected


def test_search_options_cover_every_ticker_with_readable_labels():
    options = build_search_options(build_ticker_table(RAW_TICKERS))
    labels = [o["label"] for o in options]
    assert "American Express Co (AXP)" in labels
    assert "Berkshire Hathaway Inc (BRK-A)" in labels
    assert "Berkshire Hathaway Inc (BRK-B)" in labels
    assert labels == sorted(labels, key=str.lower)


def test_primary_ticker_is_the_first_listed():
    assert primary_ticker_by_cik(RAW_TICKERS)["0001067983"] == "BRK-B"


# --- Peers -------------------------------------------------------------------

def test_recent_periods_skip_the_current_quarter():
    # On 17 Oct 2026 (Q4), the newest complete quarter is Q3 2026.
    assert recent_balance_sheet_periods(date(2026, 10, 17), 3) == \
        ["CY2026Q3I", "CY2026Q2I", "CY2026Q1I"]
    assert recent_balance_sheet_periods(date(2026, 2, 1), 2) == ["CY2025Q4I", "CY2025Q3I"]


def test_rank_peers_keeps_traded_companies_largest_first_and_excludes_self():
    industry = ["0000000001", "0000000002", "0000000003", "0000000004", "0000000002"]
    assets = {"0000000001": 50.0, "0000000002": 900.0, "0000000003": 300.0}
    tickers = {"0000000001": "AAA", "0000000002": "BBB", "0000000004": "DDD",
               "0000000003": "CCC"}
    peers = rank_peers(industry, assets, tickers, {}, exclude_cik="0000000003", limit=5)
    # CCC is the company itself; DDD has no assets figure; BBB appears once.
    assert [p.ticker for p in peers] == ["BBB", "AAA"]


def test_rank_peers_respects_limit():
    industry = [f"{i:010d}" for i in range(10)]
    assets = {c: float(i) for i, c in enumerate(industry)}
    tickers = {c: f"T{i}" for i, c in enumerate(industry)}
    assert len(rank_peers(industry, assets, tickers, {}, "x", limit=3)) == 3


# --- Industry comparisons ----------------------------------------------------

def test_industry_median_ignores_missing_values():
    snaps = [{"net_margin": 0.10}, {"net_margin": 0.20}, {"net_margin": None},
             {"net_margin": 0.40}]
    result = industry_medians(snaps)
    assert result["net_margin"] == pytest.approx(0.20)
    assert result["net_margin_count"] == 3


def test_median_resists_one_extreme_company():
    snaps = [{"roe": 0.10}, {"roe": 0.12}, {"roe": 1.60}]   # Apple-like outlier
    assert industry_medians(snaps)["roe"] == pytest.approx(0.12)


def test_rank_in_group():
    assert rank_in_group(0.30, [0.10, 0.50, 0.20]) == (2, 4)
    assert rank_in_group(None, [0.1]) is None


# --- Headlines ---------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("AMERICAN EXPRESS CO", "American Express"),
    ("Apple Inc.", "Apple"),
    ("JPMORGAN CHASE & CO", "Jpmorgan Chase"),
    ("BANK OF AMERICA CORP /DE/", "Bank Of America"),
])
def test_news_name_drops_legal_suffixes(raw, expected):
    assert news_name(raw) == expected


def test_build_query():
    assert build_query(["American Express"]) == '"American Express" sourcelang:english'
    assert build_query(["Visa", "Mastercard", "Visa"]) == \
        '("Visa" OR "Mastercard") sourcelang:english'


def test_parse_articles_dedupes_sorts_and_drops_bad_links():
    payload = {"articles": [
        {"title": "Older story", "url": "https://a.com/1", "domain": "a.com",
         "seendate": "20261001T120000Z"},
        {"title": "Newer story", "url": "https://b.com/2", "domain": "b.com",
         "seendate": "20261015T090000Z"},
        {"title": "newer STORY", "url": "https://c.com/3", "domain": "c.com",
         "seendate": "20261015T100000Z"},                       # duplicate title
        {"title": "Bad link", "url": "javascript:alert(1)", "domain": "x",
         "seendate": "20261016T000000Z"},                       # not a web link
    ]}
    articles = parse_articles(payload)
    assert [a["title"] for a in articles] == ["Newer story", "Older story"]
    assert articles[0]["date"] == datetime(2026, 10, 15, 9, 0)


# --- Headline retries and saved fallback -------------------------------------

class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload or {"articles": []}
        self.ok, self.text = status < 400, ""

    def json(self):
        return self._payload


ONE_ARTICLE = {"articles": [{"title": "AmEx news", "url": "https://n.com/1", "domain": "n.com",
                             "seendate": "20261015T090000Z"}]}


def news_client(tmp_path, responses):
    from analyzer.news import NewsClient
    client = NewsClient(cache_dir=tmp_path, sleep=lambda s: None)   # no real waiting
    replies = iter(responses)
    client.session.get = lambda *a, **k: next(replies)
    return client


def test_busy_service_is_retried_until_it_answers(tmp_path):
    client = news_client(tmp_path, [FakeResponse(429), FakeResponse(429),
                                    FakeResponse(200, ONE_ARTICLE)])
    result = client.headlines('"American Express"')
    assert [a["title"] for a in result.articles] == ["AmEx news"]
    assert result.saved_hours_ago is None


def test_saved_headlines_are_shown_when_still_busy(tmp_path):
    import os, time as _time
    client = news_client(tmp_path, [FakeResponse(200, ONE_ARTICLE)])
    client.headlines('"American Express"')                        # saves to cache
    for f in tmp_path.iterdir():                                  # pretend it's 3 hours old
        os.utime(f, (_time.time() - 3 * 3600,) * 2)
    client.session.get = lambda *a, **k: FakeResponse(429)
    result = client.headlines('"American Express"')
    assert [a["title"] for a in result.articles] == ["AmEx news"]
    assert result.saved_hours_ago == pytest.approx(3, abs=0.1)


def test_busy_with_nothing_saved_gives_a_clear_message(tmp_path):
    from analyzer.news import NewsError
    client = news_client(tmp_path, [FakeResponse(429)] * 3)
    with pytest.raises(NewsError, match="busy"):
        client.headlines('"American Express"')
