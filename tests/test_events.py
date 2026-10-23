"""Checks for notable events from 8-K filings. Each tricky case below is a real false
alarm (or a real event) seen while testing on actual filings."""

from datetime import date

import pandas as pd

from analyzer.events import build_events, item_events, officer_change


def test_serious_item_codes_become_events_and_routine_ones_dont():
    assert item_events("4.02,9.01")[0][0] == "Restatement"
    assert item_events("2.02,9.01") == []          # quarterly earnings release: routine
    assert item_events("7.01") == []               # investor presentation: routine
    assert [e[0] for e in item_events("2.05,2.06")] == ["Restructuring", "Impairment"]


def test_ceo_departure_is_found_with_its_sentence():
    lines = ["Item 5.02 Departure of Directors or Certain Officers.",
             "On March 25, 2024, the Company announced that Mr. Calhoun decided to step "
             "down as President and Chief Executive Officer at the end of 2024."]
    category, title, evidence = officer_change(lines)
    assert title == "Chief Executive Officer departure announced"
    assert "step down as President and Chief Executive Officer" in evidence


def test_appointment_is_found():
    lines = ["On July 30, 2024, the Board of Directors of the Company elected Robert Ortberg "
             "to serve as President and Chief Executive Officer, effective August 8, 2024."]
    assert officer_change(lines)[1] == "Chief Executive Officer appointed"


def test_routine_pay_filings_are_not_events():
    # Pay tables say "Named Executive Officer"; table rows are ignored.
    lines = ["Item 5.02 Compensatory Arrangements of Certain Officers",
             "Named Executive Officer | Current Base Salary | New Base Salary",
             "Chief Executive Officer | $1,250,000 | $1,300,000"]
    assert officer_change(lines) is None


def test_biographies_divisions_and_reporting_lines_are_not_events():
    for sentence in [
        "He previously was appointed the Company's President and Chief Executive Officer in 2010.",
        "Ms. Lee will become an Advisor to the CEO on a reduced schedule.",
        "Jane Doe, Chief Executive Officer of Intel Products, will retire next year.",
        "In connection with her appointment as PSG Chief Executive Officer, an offer letter "
        "was signed.",
        "Amended the bylaws to enable the Chief Executive Officer to suspend elected officers.",
    ]:
        assert officer_change([sentence]) is None, sentence


def test_build_events_reads_only_filings_that_need_their_words_and_sorts_newest_first():
    filings = pd.DataFrame([
        {"form": "8-K", "filed": date(2024, 3, 25), "items": "5.02,9.01", "url": "u1"},
        {"form": "8-K", "filed": date(2024, 11, 20), "items": "3.01", "url": "u2"},
        {"form": "8-K", "filed": date(2024, 4, 24), "items": "2.02,9.01", "url": "u3"},
        {"form": "10-Q", "filed": date(2024, 5, 1), "items": "", "url": "u4"},
        {"form": "8-K", "filed": date(2019, 1, 1), "items": "4.02", "url": "u5"},  # too old
    ])
    read = []

    def read_lines(url):
        read.append(url)
        return ["Mr. Smith will retire as Chief Financial Officer of the Company."]

    events = build_events(filings, read_lines, since=date(2021, 1, 1))
    assert read == ["u1", "u2"]           # 5.02 and 3.01 are read; 2.02 (results) isn't
    assert [e.date for e in events] == [date(2024, 11, 20), date(2024, 3, 25)]
    assert events[0].category == "Listing" and events[0].severity == "high"
    assert events[1].title == "Chief Financial Officer departure announced"


def test_reorganization_filing_becomes_one_event_in_its_own_words():
    filings = pd.DataFrame([{"form": "8-K", "filed": date(2026, 7, 1), "items": "2.01,3.01,5.02",
                             "url": "u"}])
    text = ["Item 2.01 | Completion of Acquisition or Disposition of Assets.",
            "On July 1, 2026, the Company completed its previously announced redomiciliation "
            "merger, and each share was exchanged for one share of the new holding company.",
            "Mr. Smith was appointed Chief Executive Officer of the new holding company."]
    events = build_events(filings, lambda url: text, since=date(2026, 1, 1))
    assert [e.category for e in events] == ["Reorganization"]
    assert "redomiciliation" in events[0].evidence


def test_item_evidence_skips_heading_and_pointer_sentences():
    from analyzer.events import item_evidence
    lines = ["Item 2.01 | Completion of Acquisition or Disposition of Assets.",
             "The information set forth in Item 1.01 is incorporated by reference into this Item.",
             "On May 3, 2026, the Company completed its acquisition of Acme Corp for $1.2 billion."]
    assert item_evidence(lines, "2.01").startswith("On May 3, 2026, the Company completed")
    assert item_evidence(lines, "3.01") == ""
