"""Checks for 'Explain from filing': which filings are read for each kind of event, the
questions asked, and saving answers. No internet or Claude calls."""

from datetime import date, datetime

import pandas as pd

from analyzer.assistant import Answer, Source
from analyzer.explain import (
    cache_key,
    change_question,
    event_question,
    filings_for_change,
    filings_for_event,
    filings_for_stock_move,
    headlines_document,
    load_saved,
    save,
)

FILINGS = pd.DataFrame([
    {"form": "10-Q", "filed": date(2023, 7, 25), "period": "2023-06-30", "accession": "A1",
     "url": "q2"},
    {"form": "8-K", "filed": date(2024, 1, 8), "period": "2024-01-05", "accession": "A2",
     "url": "k1"},
    {"form": "8-K", "filed": date(2024, 1, 20), "period": "2024-01-20", "accession": "A3",
     "url": "k2"},
    {"form": "10-K", "filed": date(2024, 2, 9), "period": "2023-12-31", "accession": "A4",
     "url": "annual"},
    {"form": "10-Q", "filed": date(2024, 4, 26), "period": "2024-03-31", "accession": "A5",
     "url": "q1"},
])


def urls(rows):
    return [r["url"] for r in rows]


def test_unusual_change_reads_the_filing_that_first_reported_it():
    assert urls(filings_for_change(FILINGS, "A1")) == ["q2"]
    assert filings_for_change(FILINGS, "not-in-list") == []


def test_8k_event_reads_the_8k_and_the_next_report():
    assert urls(filings_for_event(FILINGS, "k1", date(2024, 1, 8))) == ["k1", "annual"]


def test_stock_move_reads_nearby_8ks_and_the_next_report():
    # A move on Jan 9: the Jan 8 8-K is within three days; the Jan 20 one isn't.
    assert urls(filings_for_stock_move(FILINGS, date(2024, 1, 9))) == ["k1", "annual"]


def test_questions_name_the_period_and_ask_for_an_honest_answer():
    q = change_question("Provision for credit losses", "Q2 FY2023", "+192.2%")
    assert "Q2 FY2023" in q and "+192.2%" in q and "doesn't explain" in q
    q = event_question("Chief Executive Officer departure announced", date(2024, 3, 25),
                       "Calhoun decided to step down")
    assert "March 25, 2024" in q and "Calhoun decided to step down" in q


def test_headlines_become_one_clearly_labelled_document():
    articles = [{"title": "Boeing shares slide", "source": "Reuters", "url": "https://r.com/1",
                 "date": datetime(2024, 1, 8, 14, 0)}]
    title, text, url = headlines_document(articles, "BA", date(2024, 1, 8))
    assert title == "News headlines around Jan 08, 2024"
    assert "Jan 08, Reuters: Boeing shares slide" in text
    assert url == "https://r.com/1"


def test_saved_answers_come_back_identical(tmp_path):
    answer = Answer("Write-offs rose [1].", [Source(1, "10-Q, Item 2", "Write-offs rose.", "u")],
                    0.004, "", "Write-offs rose.")
    key = cache_key("0000004962", "change", "credit_provision|Q2 FY2023")
    assert load_saved(key, tmp_path) is None
    save(key, answer, tmp_path)
    assert load_saved(key, tmp_path) == answer


def test_different_events_get_different_saved_answers():
    assert cache_key("1", "change", "a|Q1") != cache_key("1", "change", "a|Q2")
    assert cache_key("1", "change", "a|Q1") != cache_key("2", "change", "a|Q1")
