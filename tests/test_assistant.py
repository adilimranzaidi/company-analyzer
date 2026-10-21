"""Checks for the filing reader, passage search, and how answers and citations are
assembled. None of these call the internet or the Claude API."""

from datetime import date
from types import SimpleNamespace

from analyzer.assistant import build_documents, parse_answer, search_query
from analyzer.filing_text import Passage, html_to_lines, split_passages
from analyzer.financials import fiscal_period
from analyzer.search import (
    BM25,
    FilingSearch,
    choose_filings,
    expand_query,
    time_hints,
    tokenize,
    top_passages,
)

BUSINESS_TEXT = ("We operate a global payments network. Card members spend on our cards. "
                 + "More detail about the business. " * 8)
CREDIT_TEXT = ("Provisions increased due to higher net write-offs and a reserve build. "
               + "Further discussion of credit trends. " * 8)
FILING_HTML = f"""
<html><body>
<div style="display:none"><ix:header>hidden XBRL data</ix:header></div>
<p>PART I</p>
<p>ITEM 1. BUSINESS</p>
<p>{BUSINESS_TEXT}</p>
<p>12</p>
<p>ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION</p>
<p>PROVISIONS FOR CREDIT LOSSES</p>
<p>{CREDIT_TEXT}</p>
<table><tr><td>Provisions</td><td>$</td><td>1,100</td><td>900</td></tr></table>
</body></html>
"""


# --- Reading filings ----------------------------------------------------------

def test_html_to_lines_drops_hidden_data_and_page_numbers_and_keeps_table_rows():
    lines = html_to_lines(FILING_HTML)
    assert "hidden XBRL data" not in " ".join(lines)
    assert "12" not in lines                                   # page number
    assert "Provisions | 1,100 | 900" in lines                  # table row on one line


def test_passages_are_labelled_with_item_and_heading():
    lines = html_to_lines(FILING_HTML)
    passages = split_passages(lines, "10-K FY2025", "https://sec.gov/x", "10-K")
    sections = [p.section for p in passages]
    assert any(s.startswith("Item 1. Business") for s in sections)
    expected = "Item 7. Management’s discussion and analysis (MD&A) › Provisions for credit losses"
    assert expected in sections


def test_part_ii_prefix_only_for_10q():
    lines = ["PART II", "Item 1A. Risk Factors"] + ["word"] * 40
    q = split_passages(lines, "10-Q", "u", "10-Q")[0].section
    k = split_passages(lines, "10-K", "u", "10-K")[0].section
    assert q.startswith("Part II, Item 1A") and k.startswith("Item 1A")


# --- Search ---------------------------------------------------------------------

def test_tokenize_drops_common_words_and_plurals():
    assert tokenize("What are the company's credit losses?") == ["credit", "loss"]


def test_bm25_ranks_the_relevant_passage_first():
    index = BM25(["card members spend on cards", "provision for credit losses rose",
                  "the weather was nice"])
    scores = index.scores("Why did credit losses rise?")
    assert scores.index(max(scores)) == 1
    assert scores[2] == 0


def p(filing, text, section="Item 7"):
    return Passage(filing, section, text, "u")


def test_each_filing_gets_a_fair_share():
    # A long 10-K full of matches must not crowd out the 10-Q's one relevant passage.
    passages = [p("10-K", "credit losses credit losses") for _ in range(20)] + \
               [p("10-Q", "credit losses this quarter")]
    chosen = top_passages(passages, "credit losses", k=4)
    assert len(chosen) == 4
    assert any(c.filing == "10-Q" for c in chosen)


def test_follow_up_questions_include_the_previous_question():
    assert search_query("why?", [("What drove credit losses?", "...")]) == \
        "why? What drove credit losses?"


# --- Answers and citations ------------------------------------------------------

def test_documents_put_dashboard_figures_and_methods_first():
    docs, meta = build_documents([p("10-Q Q2", "text")], "figures")
    assert [d["title"] for d in docs][:2] == ["Dashboard figures", "How the dashboard works"]
    assert all(d["citations"] == {"enabled": True} for d in docs)    # all or none
    assert meta[2]["title"] == "10-Q Q2, Item 7"


def block(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def cite(index, quote):
    return SimpleNamespace(type="char_location", document_index=index, cited_text=quote)


def test_parse_answer_numbers_sources_and_reuses_numbers():
    meta = [{"title": "Dashboard figures", "url": ""}, {"title": "Methods", "url": ""},
            {"title": "10-Q, Item 2", "url": "https://sec.gov/q"}]
    content = [
        SimpleNamespace(type="thinking", thinking=""),            # ignored
        block("Provisions fell"),
        block(" 22.8%", [cite(0, "was $1.1B, -22.8%")]),
        block(" because delinquencies were lower", [cite(2, "driven by lower delinquencies")]),
        block(" (again", [cite(0, "was $1.1B, -22.8%")]),          # same quote: same number
        block(")."),
    ]
    marked, plain, sources = parse_answer(content, meta)
    assert marked == ("Provisions fell 22.8% [1] because delinquencies were lower [2] "
                      "(again [1]).")
    assert plain == "Provisions fell 22.8% because delinquencies were lower (again)."
    assert [(s.number, s.title, s.url) for s in sources] == [
        (1, "Dashboard figures", ""), (2, "10-Q, Item 2", "https://sec.gov/q")]


def test_tables_are_not_cut_in_half():
    header = "(Millions) | 2025 | 2024 | 2023"
    rows = [f"Line item {i} | {i},000 | {i},100 | {i},200" for i in range(40)]
    lines = ["ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS", "Some introduction text " * 3,
             header] + rows + ["Closing paragraph after the table " * 3]
    passages = split_passages(lines, "10-K", "u", "10-K", target_words=60)
    holding_rows = [p for p in passages if "Line item 39" in p.text]
    assert holding_rows and header in holding_rows[0].text      # last row keeps its headings


# --- Searching all filings, with attention to time -----------------------------




def test_time_hints_read_quarters_and_years():
    assert time_hints("Why did provisions jump in Q2 2023?") == ({2023}, {(2023, 2)})
    assert time_hints("the second quarter of 2023") == ({2023}, {(2023, 2)})
    assert time_hints("How did FY2024 compare with 2023?") == ({2023, 2024}, set())
    assert time_hints("What are the main risks?") == (set(), set())


def filing(period, form="10-Q",
           text="provision for credit losses increased due to a reserve build"):
    label = f"{form} for {period}"
    return Passage(label, "Item 2. MD&A", text, f"https://sec.gov/{period}", form, period)


def searcher(passages):
    return FilingSearch(passages, lambda d: fiscal_period(d, 12), today=date(2026, 10, 21))


def test_named_quarter_wins_over_newer_filings():
    passages = [filing("2026-06-30"), filing("2025-06-30"), filing("2023-06-30"),
                filing("2023-03-31")]
    best = searcher(passages).search("Why did provision for credit losses jump in Q2 2023?", k=1)
    assert best[0].period == "2023-06-30"


def test_without_a_date_recent_filings_are_preferred():
    passages = [filing("2021-06-30"), filing("2026-06-30"), filing("2023-06-30")]
    best = searcher(passages).search("Why did the provision for credit losses change?", k=1)
    assert best[0].period == "2026-06-30"


def test_no_single_filing_takes_every_slot():
    passages = [filing("2026-06-30") for _ in range(10)] + [filing("2025-06-30")]
    chosen = searcher(passages).search("provision for credit losses", k=8, per_filing=6)
    assert sum(p.period == "2026-06-30" for p in chosen) == 6
    assert any(p.period == "2025-06-30" for p in chosen)


def test_coverage_describes_what_was_searched():
    s = searcher([filing("2023-06-30"), filing("2025-12-31", form="10-K")])
    assert s.coverage() == "2 filings (10-K and 10-Q) for periods from 2023-06-30 to 2025-12-31"


# --- Choosing which filings to read, and widening finance terms -----------------


ROWS = [{"form": "10-Q", "period": p} for p in
        ["2026-06-30", "2026-03-31", "2025-09-30", "2025-06-30", "2025-03-31",
         "2024-09-30", "2024-06-30", "2024-03-31", "2023-06-30"]] + \
       [{"form": "10-K", "period": p} for p in ["2025-12-31", "2024-12-31", "2023-12-31"]]
FISCAL = lambda d: fiscal_period(d, 12)   # noqa: E731


def test_named_year_reads_only_that_years_filings():
    chosen = choose_filings(ROWS, "why did cash jump in q2fy25", FISCAL)
    assert {r["period"] for r in chosen} == {"2025-12-31", "2025-09-30", "2025-06-30",
                                             "2025-03-31"}


def test_no_date_reads_recent_filings_and_the_latest_10k():
    chosen = choose_filings(ROWS, "what are the main risks?", FISCAL)
    periods = [r["period"] for r in chosen]
    assert periods[0] == "2026-06-30" and len(chosen) <= 7
    assert "2025-12-31" in periods                     # latest annual report included
    assert "2023-06-30" not in periods                 # old filings left out


def test_a_year_with_no_filings_falls_back_to_recent_ones():
    chosen = choose_filings(ROWS, "what happened in 2015?", FISCAL)
    assert chosen[0]["period"] == "2026-06-30"


def test_cash_questions_also_search_cash_flow_words():
    expanded = expand_query("why did their cash increase?")
    assert "liquidity" in expanded and "financing" in expanded
    assert expand_query("what are the risks?") == "what are the risks?"
