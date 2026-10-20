"""Checks for name search, peer suggestions, comparisons, and headline handling.
None of these touch the internet."""

from datetime import date, datetime

import pytest

from analyzer.compare import industry_medians, rank_in_group
from analyzer.edgar_client import build_search_options, build_ticker_table, \
    pretty_company_name, primary_ticker_by_cik
from analyzer.news import NewsClient, NewsError, merge_articles, parse_articles
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


# --- Headlines (Finnhub) ------------------------------------------------------

def item(headline, ts, url="https://n.com/a", source="Reuters"):
    return {"headline": headline, "datetime": ts, "url": url, "source": source,
            "summary": "", "related": "AXP"}


def test_parse_articles_dedupes_sorts_and_drops_bad_links():
    articles = parse_articles([
        item("Older story", 1759320000),                       # 2025-10-01
        item("Newer story", 1760518800),                       # 2025-10-15
        item("newer STORY", 1760522400, url="https://c.com"),  # duplicate headline
        item("Bad link", 1760600000, url="javascript:alert(1)"),
        item("", 1760600000),                                  # no headline
    ], "AXP")
    assert [a["title"] for a in articles] == ["Newer story", "Older story"]
    assert articles[0]["date"] == datetime(2025, 10, 15, 9, 0)
    assert articles[0]["ticker"] == "AXP"


def test_merge_articles_combines_tickers_newest_first_without_repeats():
    a = parse_articles([item("Shared story", 1760518800), item("AXP only", 1759320000)], "AXP")
    b = parse_articles([item("Shared story", 1760518800), item("COF only", 1760000000)], "COF")
    assert [x["title"] for x in merge_articles([a, b], 10)] ==         ["Shared story", "COF only", "AXP only"]


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload if payload is not None else []
        self.ok = status < 400

    def json(self):
        return self._payload


def client_with(tmp_path, responses):
    client = NewsClient("test-key", cache_dir=tmp_path)
    replies = iter(responses)
    client.session.get = lambda *a, **k: next(replies)
    return client


def test_missing_key_gives_setup_instructions():
    with pytest.raises(NewsError, match="FINNHUB_API_KEY"):
        NewsClient("")


def test_key_is_sent_as_a_header_not_in_the_address():
    client = NewsClient("test-key")
    assert client.session.headers["X-Finnhub-Token"] == "test-key"


def test_rejected_key_gives_a_clear_message(tmp_path):
    with pytest.raises(NewsError, match="didn't accept the API key"):
        client_with(tmp_path, [FakeResponse(401)]).company_news("AXP")


def test_saved_headlines_are_shown_when_finnhub_is_unavailable(tmp_path):
    import os, time as _time
    client = client_with(tmp_path, [FakeResponse(200, [item("AmEx news", 1760518800)])])
    client.company_news("AXP", today=date(2026, 10, 17))           # saves to cache
    for f in tmp_path.iterdir():                                   # pretend it's 3 hours old
        os.utime(f, (_time.time() - 3 * 3600,) * 2)
    client.session.get = lambda *a, **k: FakeResponse(429)
    result = client.company_news("AXP", today=date(2026, 10, 17))
    assert [a["title"] for a in result.articles] == ["AmEx news"]
    assert result.saved_hours_ago == pytest.approx(3, abs=0.1)


# --- Competitors named in the 10-K --------------------------------------------

from analyzer.peers import brand_name, find_named_competitors

COMPETITION = ("Our global card network competes with other card networks, including, among "
               "others, Visa, Mastercard and Discover (owned by Capital One). Principal "
               "competitive factors include rewards. Customers expect strong security; our "
               "customers value service. We have offices in the District of Columbia.")
LISTED = [
    {"cik": "1", "ticker": "V", "name": "Visa Inc."},
    {"cik": "2", "ticker": "MA", "name": "Mastercard Inc"},
    {"cik": "3", "ticker": "COF", "name": "CAPITAL ONE FINANCIAL CORP"},
    {"cik": "4", "ticker": "PFG", "name": "PRINCIPAL FINANCIAL GROUP INC"},
    {"cik": "5", "ticker": "CUBI", "name": "Customers Bancorp, Inc."},
    {"cik": "6", "ticker": "CLBK", "name": "Columbia Financial, Inc."},
    {"cik": "7", "ticker": "TINY", "name": "Mastercard Tiny Shell Corp"},
    {"cik": "9", "ticker": "AXP", "name": "AMERICAN EXPRESS CO"},
]
ASSETS = {c: 50e9 for c in "1234569"} | {"7": 1e6}


@pytest.mark.parametrize("raw, expected", [
    ("CAPITAL ONE FINANCIAL CORP", "Capital One"),
    ("Visa Inc.", "Visa"),
    ("PayPal Holdings, Inc.", "PayPal"),
])
def test_brand_name(raw, expected):
    assert brand_name(raw) == expected


def test_named_competitors_are_found_and_ordinary_words_are_not():
    found = find_named_competitors(COMPETITION, LISTED, exclude_cik="9", assets_by_cik=ASSETS)
    assert sorted(p.ticker for p in found) == ["COF", "MA", "V"]
    assert all(p.source == "Named in the 10-K" for p in found)
    assert "Capital One" in next(p for p in found if p.ticker == "COF").evidence
