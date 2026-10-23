"""Checks for the SEC connection code. None of these touch the internet."""

import json

import pytest

from analyzer.edgar_client import (
    EdgarClient,
    EdgarError,
    TickerNotFound,
    build_ticker_table,
    find_company,
    format_cik,
    format_fiscal_year_end,
    normalize_ticker,
)

# A tiny stand-in for the SEC's ticker file, in the same shape as the real one.
FAKE_SEC_TICKERS = {
    "0": {"cik_str": 4962, "ticker": "AXP", "title": "AMERICAN EXPRESS CO"},
    "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
}


def test_normalize_ticker_cleans_spaces_and_case():
    assert normalize_ticker("  axp ") == "AXP"


def test_normalize_ticker_converts_share_class_dot_to_dash():
    assert normalize_ticker("brk.b") == "BRK-B"


def test_format_cik_pads_to_ten_digits():
    assert format_cik(4962) == "0000004962"
    assert format_cik("0000004962") == "0000004962"


@pytest.mark.parametrize("raw, expected", [
    ("1231", "December 31"),
    ("0630", "June 30"),
    ("", ""),
    ("1331", ""),   # month 13 doesn't exist
    ("abcd", ""),
])
def test_format_fiscal_year_end(raw, expected):
    assert format_fiscal_year_end(raw) == expected


def test_find_company_returns_cik_and_name():
    company = find_company("axp", build_ticker_table(FAKE_SEC_TICKERS))
    assert company.cik == "0000004962"
    assert company.name == "AMERICAN EXPRESS CO"
    assert company.ticker == "AXP"


def test_find_company_accepts_dot_share_class():
    company = find_company("BRK.B", build_ticker_table(FAKE_SEC_TICKERS))
    assert company.cik == "0001067983"


def test_unknown_ticker_gives_friendly_error():
    with pytest.raises(TickerNotFound, match="ZZZZ"):
        find_company("zzzz", build_ticker_table(FAKE_SEC_TICKERS))


def test_blank_ticker_gives_friendly_error():
    with pytest.raises(TickerNotFound, match="enter a ticker"):
        find_company("   ", build_ticker_table(FAKE_SEC_TICKERS))


def test_client_requires_email_in_user_agent():
    with pytest.raises(EdgarError, match="name and email"):
        EdgarClient("Just A Name")


def test_client_sends_user_agent_header(tmp_path):
    client = EdgarClient("Jane Doe jane@example.com", cache_dir=tmp_path)
    assert client.session.headers["User-Agent"] == "Jane Doe jane@example.com"


def test_fresh_cache_is_used_without_contacting_the_sec(tmp_path):
    (tmp_path / "company_tickers.json").write_text(json.dumps(FAKE_SEC_TICKERS))
    client = EdgarClient("Jane Doe jane@example.com", cache_dir=tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Should have used the cache, not the internet")

    client.session.get = fail_if_called
    assert "AXP" in client.ticker_table()


def test_merge_facts_keeps_both_histories():
    from analyzer.edgar_client import merge_facts, predecessor
    def facts(**labels):
        return {"facts": {"us-gaap": {k: {"units": {"USD": rows}} for k, rows in labels.items()}}}

    old = facts(Revenues=[{"end": "2024-12-31", "val": 1}])
    new = facts(Revenues=[{"end": "2026-06-30", "val": 2}],
                NetIncomeLoss=[{"end": "2026-06-30", "val": 3}])
    merged = merge_facts(old, new)["facts"]["us-gaap"]
    assert [r["val"] for r in merged["Revenues"]["units"]["USD"]] == [1, 2]
    assert merged["NetIncomeLoss"]["units"]["USD"][0]["val"] == 3
    assert old["facts"]["us-gaap"]["Revenues"]["units"]["USD"] == [{"end": "2024-12-31", "val": 1}]
    assert predecessor("2115436") == "0000034088"          # ExxonMobil Holdings <- Exxon Mobil
    assert predecessor("4962") is None
