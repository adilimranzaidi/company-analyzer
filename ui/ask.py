"""Ask: a chat assistant that answers from the company's filings and the dashboard's own
figures, with numbered sources under every answer."""

import html

import streamlit as st

from analyzer.assistant import Answer, ask, dashboard_figures, friendly_error, search_query
from analyzer.edgar_client import Company, pretty_company_name
from analyzer.filings import latest_reports
from analyzer.financials import MetricData, fiscal_period
from analyzer.search import RECENT_FILINGS, choose_filings
from ui import data
from ui.style import placeholder

MAX_FILINGS = 4
MATCHING = "Filings that match my question (fastest)"
EVERYTHING = "Every 10-K and 10-Q (slower the first time)"
CHOSEN = "Only the filings I choose"


def _filing_label(row) -> str:
    return f"{row['form']} · period ending {row['period'] or 'n/a'} · filed {row['filed']}"


def _escape_dollars(text: str) -> str:
    # Streamlit treats text between two "$" signs as a math formula; show dollars as dollars.
    return text.replace("$", "\\$")


def _show_answer(answer: Answer, container=None) -> None:
    box = container or st
    box.markdown(_escape_dollars(answer.text))
    if answer.sources:
        with st.expander(f"Sources ({len(answer.sources)})"):
            for s in answer.sources:
                quote = html.escape(s.quote if len(s.quote) <= 400 else s.quote[:400] + "…")
                link = (f' · <a href="{html.escape(s.url, quote=True)}" target="_blank">'
                        "Open filing</a>") if s.url else ""
                st.markdown(f'<div class="ca-source"><b>[{s.number}]</b> '
                            f'{html.escape(s.title)}{link}<blockquote>{quote}</blockquote></div>',
                            unsafe_allow_html=True)
    extra = f" · {answer.note}" if answer.note else ""
    # Shown in cents: "$0.0045" was easy to misread as 4 cents; it's under half a cent.
    cents = answer.cost * 100
    cost = f"{cents:.2f}¢" if cents < 1 else f"{cents:.1f}¢"
    st.caption(f"Estimated cost of this answer: {cost} (of your Anthropic credit){extra}")


def render(company: Company, metrics: dict[str, MetricData]) -> None:
    api_key = data.get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        placeholder("<b>The assistant needs an Anthropic API key.</b> Add "
                    "<code>ANTHROPIC_API_KEY</code> to <code>.streamlit/secrets.toml</code> "
                    "and restart the dashboard.")
        return

    name = pretty_company_name(company.name)
    table = data.filings(data.user_agent(), company.cik)
    reports = table[table["form"].isin(["10-K", "10-Q", "20-F", "40-F"])]
    if reports.empty:
        st.info("No 10-K or 10-Q filings are available for the assistant to read.")
        return
    rows = reports.to_dict("records")
    fiscal_of = lambda d: fiscal_period(d, company.fiscal_year_end_month)   # noqa: E731

    # Start reading the most recent filings in the background as soon as Ask opens, so they
    # are ready by the time the first question is typed.
    recent = choose_filings(rows, "", fiscal_of)
    data.prefetch_filings(data.user_agent(), company.cik, [r["url"] for r in recent])

    # --- What to search -------------------------------------------------------------------
    labels = {_filing_label(r): r for r in rows}
    latest = latest_reports(table)
    defaults = [_filing_label(r) for r in (latest.annual, latest.quarterly) if r]
    key = f"ask_filings_{company.ticker}"
    st.session_state.setdefault(key, [d for d in defaults if d in labels])
    with st.expander("What the assistant searches", expanded=False):
        mode = st.radio("Search", [MATCHING, EVERYTHING, CHOSEN], key="ask_mode",
                        label_visibility="collapsed")
        if mode == CHOSEN:
            st.multiselect("Filings", list(labels), key=key, max_selections=MAX_FILINGS,
                           label_visibility="collapsed")
        st.caption(
            f"Matching: if your question names a year or quarter (\"Q2 FY25\", \"2023\"), the "
            f"filings for that fiscal year; otherwise the latest {RECENT_FILINGS} filings plus "
            f"the latest 10-K. Every filing: all {len(rows)} 10-K and 10-Q filings, which takes "
            "a few minutes the first time for each company. Filings are saved once read. The "
            "cost per question is the same either way.")

    st.markdown(
        f'<div class="ca-muted">Ask about {html.escape(name)} or anything on the dashboard. '
        "Answers come only from the company's filings and the dashboard's own figures, with "
        "numbered sources; if they don't cover your question, the assistant says so. Tip: name "
        "the quarter or year you mean. Uses Claude Haiku 5.5: each question costs a fraction "
        "of a cent of your Anthropic credit. Not investment advice.</div>",
        unsafe_allow_html=True)

    # --- Conversation ------------------------------------------------------------------
    history_key = f"chat_{company.ticker}"
    history: list[dict] = st.session_state.setdefault(history_key, [])

    for turn in history:
        with st.chat_message("user"):
            st.markdown(_escape_dollars(turn["question"]))
        with st.chat_message("assistant"):
            _show_answer(turn["answer"])

    pending = st.session_state.pop("ask_pending", None)
    if not history and not pending:
        st.markdown("**Try asking**")
        starters = [f"How does {name} make money?",
                    "What drove results in the latest quarter?",
                    f"What are the biggest risks {company.ticker} describes?",
                    "What does return on equity mean, and what is it here?"]
        cols = st.columns(2)
        for i, q in enumerate(starters):
            if cols[i % 2].button(q, key=f"starter_{i}", width="stretch"):
                st.session_state["ask_pending"] = q
                st.rerun()

    prompt = f"Ask about {company.ticker}, its filings, or the dashboard"
    question = st.chat_input(prompt) or pending
    if history:
        if st.button("Clear conversation"):
            st.session_state[history_key] = []
            st.rerun()
    if not question:
        return

    previous = [(t["question"], t["answer"].plain_text) for t in history]
    query = search_query(question, previous)
    if mode == MATCHING:
        to_read = choose_filings(rows, query, fiscal_of)
    elif mode == EVERYTHING:
        to_read = rows
    else:
        to_read = [labels[label] for label in st.session_state[key]]
    if not to_read:
        st.warning("Choose at least one filing under \"What the assistant searches\".")
        return

    with st.chat_message("user"):
        st.markdown(_escape_dollars(question))
    with st.chat_message("assistant"):
        progress = st.progress(0.0, text="Reading the filings...")
        passages = []
        for i, row in enumerate(to_read):
            passages += data.passages(data.user_agent(), row["url"], _filing_label(row),
                                      row["form"], row["period"] or "")
            progress.progress((i + 1) / len(to_read),
                              text=f"Reading the filings ({i + 1} of {len(to_read)}; "
                                   "saved after the first time)...")
        progress.empty()
        searcher = data.filing_search(company.cik, tuple(r["url"] for r in to_read),
                                      company.fiscal_year_end_month, passages)
        relevant = searcher.search(query)

        # Show the answer's words as they arrive, then replace them with the final version
        # (which adds the [n] source markers).
        live = st.empty()
        written: list[str] = []

        def show_live(chunk: str) -> None:
            written.append(chunk)
            live.markdown(_escape_dollars("".join(written)) + " ▌")

        with st.spinner("Thinking..."):
            try:
                answer = ask(api_key, company, question, relevant,
                             dashboard_figures(company, metrics,
                                               data.all_events(data.user_agent(), company.cik,
                                                               company.ticker)[0]),
                             previous, searched=searcher.coverage(), on_text=show_live)
            except Exception as err:            # shown to the user, never a crash
                live.empty()
                st.error(friendly_error(err))
                return
        _show_answer(answer, container=live)
    history.append({"question": question, "answer": answer})
