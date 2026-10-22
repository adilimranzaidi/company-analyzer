"""The 'Explain from filing' button, shared by Unusual changes and Notable events."""

import streamlit as st

from analyzer.assistant import ask, dashboard_figures, friendly_error
from analyzer.edgar_client import Company
from analyzer.explain import cache_key, load_saved, save
from analyzer.financials import MetricData
from ui import data
from ui.ask import _filing_label, _show_answer


def explain_box(company: Company, metrics: dict[str, MetricData], kind: str, identifier: str,
                question: str, filings: list[dict], extra=None, button_label="Explain from filing"):
    """Show a saved explanation, or a button that creates one.

    kind/identifier name the thing being explained (used to save the answer);
    filings are the filing rows to read; extra optionally returns more documents
    (e.g. headlines) and is only called when the button is pressed.
    """
    key = cache_key(company.cik, kind, identifier)
    saved = load_saved(key)
    if saved:
        with st.expander("Explanation (saved, free to reopen)", expanded=False):
            _show_answer(saved, show_cost=False)
        return
    if not data.get_secret("ANTHROPIC_API_KEY"):
        st.caption("Add an Anthropic API key to get explanations.")
        return
    if not filings:
        st.caption("No filing covering this period is in the SEC's recent list.")
        return
    if not st.button(button_label, key=f"explain_{key}", help="Reads the filing(s) that cover "
                     "this and gives management's explanation, with sources (under half a cent)."):
        return

    with st.spinner("Reading the filing and asking the assistant…"):
        passages = []
        for row in filings:
            passages += data.filing_row_passages(data.user_agent(), row, _filing_label(row))
        searcher = data.filing_search(company.cik, tuple(r["url"] for r in filings),
                                      company.fiscal_year_end_month, passages)
        try:
            answer = ask(data.get_secret("ANTHROPIC_API_KEY"), company, question,
                         searcher.search(question, k=14),
                         dashboard_figures(company, metrics,
                                           data.all_events(data.user_agent(), company.cik,
                                                           company.ticker)[0]),
                         [], searched=searcher.coverage(),
                         extra=extra() if extra else None)
        except Exception as err:            # shown to the user, never a crash
            st.error(friendly_error(err))
            return
    save(key, answer)
    _show_answer(answer)
