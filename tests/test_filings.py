"""Checks for the filings list and the plain-English 8-K labels."""

from analyzer.filings import (
    describe_items,
    filings_table,
    index_url,
    is_significant,
    filing_url,
    latest_reports,
)

SUBMISSIONS = {"filings": {"recent": {
    "form": ["8-K", "4", "10-Q", "8-K", "10-K", "10-Q/A"],
    "filingDate": ["2026-10-15", "2026-10-01", "2026-07-24", "2026-07-17", "2026-02-07",
                   "2025-11-01"],
    "reportDate": ["2026-10-15", "", "2026-06-30", "2026-07-17", "2025-12-31", "2025-09-30"],
    "accessionNumber": ["0000004962-26-000383", "0000004962-26-000300",
                        "0000004962-26-000250", "0000004962-26-000240",
                        "0000004962-26-000100", "0000004962-25-000400"],
    "primaryDocument": ["axp-8k.htm", "form4.xml", "axp-10q.htm", "axp-8k2.htm",
                        "axp-10k.htm", ""],
    "items": ["7.01", "", "", "2.02,9.01", "", ""],
}}}


def test_urls_follow_the_sec_archive_layout():
    assert filing_url("0000004962", "0000004962-26-000383", "axp-8k.htm") == \
        "https://www.sec.gov/Archives/edgar/data/4962/000000496226000383/axp-8k.htm"
    assert index_url("0000004962", "0000004962-26-000383") == \
        "https://www.sec.gov/Archives/edgar/data/4962/000000496226000383/" \
        "0000004962-26-000383-index.htm"


def test_8k_items_in_plain_english():
    assert describe_items("2.02,9.01") == [
        "Quarterly or annual results (earnings release)",
        "Financial statements and exhibits attached",
    ]
    assert describe_items("") == []
    assert describe_items("9.99") == ["Item 9.99"]      # unknown code: shown, not guessed


def test_routine_8ks_are_not_significant():
    assert is_significant("2.02,9.01")      # earnings release
    assert is_significant("5.02")           # executive change
    assert not is_significant("7.01")       # investor presentation
    assert not is_significant("9.01")       # exhibits only


def test_table_keeps_main_forms_newest_first():
    table = filings_table(SUBMISSIONS, "0000004962")
    assert list(table["form"]) == ["8-K", "10-Q", "8-K", "10-K", "10-Q/A"]   # Form 4 dropped
    earnings = table[table["items"] == "2.02,9.01"].iloc[0]
    assert earnings["significant"]
    assert "earnings release" in earnings["about"]
    # No primary document: fall back to the filing's index page.
    assert table.iloc[-1]["url"].endswith("-index.htm")


def test_latest_reports_prefer_originals():
    latest = latest_reports(filings_table(SUBMISSIONS, "0000004962"))
    assert latest.annual["form"] == "10-K" and latest.annual["period"] == "2025-12-31"
    assert latest.quarterly["form"] == "10-Q" and latest.quarterly["period"] == "2026-06-30"
