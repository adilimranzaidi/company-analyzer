"""News and events: notable events from the company's 8-K filings (with headlines from
the same days), and recent headlines."""

import html
from datetime import date, timedelta

import streamlit as st

from analyzer.edgar_client import Company
from analyzer.events import Event
from ui import data, headlines
from ui.style import placeholder

VIEWS = ["Notable events", "Headlines"]
SEVERITY_LABEL = {"high": "Serious", "medium": "Notable"}


def _event_html(e: Event) -> str:
    badge = (f'<span class="ca-badge ca-badge-{e.severity}">'
             f'{SEVERITY_LABEL.get(e.severity, "")}</span>')
    link = (f' · <a href="{html.escape(e.url, quote=True)}" target="_blank">{e.form}</a>'
            if e.url else "")
    if e.category == "Stock move":
        evidence = f'<div class="ca-muted">{html.escape(e.evidence)}</div>'
    elif e.evidence:
        evidence = (f'<blockquote>{html.escape(e.evidence)}</blockquote>'
                    '<div class="ca-muted">Detected from the 8-K\'s own text; check the quote.</div>')
    else:
        evidence = ""
    return (f'<div class="ca-event"><div class="ca-event-date">{e.date:%b %d, %Y}</div>'
            f'<div>{badge} <b>{html.escape(e.title)}</b>{link}'
            f'{evidence}</div></div>')


def render(company: Company) -> None:
    st.session_state.setdefault("news_view", VIEWS[0])
    view = st.segmented_control("View", VIEWS, key="news_view",
                                label_visibility="collapsed") or VIEWS[0]
    if view == "Headlines":
        headlines.render(company)
        return

    st.markdown(
        '<div class="ca-muted">Things that happened to the company, from the 8-K reports it '
        "must file within four business days of a major event: executive departures and "
        "appointments, restatements, cybersecurity incidents, listing problems, "
        "acquisitions, write-downs and restructurings. Routine 8-Ks (quarterly earnings "
        f"releases, investor presentations) are left out. Last {data.EVENT_YEARS} years.</div>",
        unsafe_allow_html=True)

    with st.spinner("Reading 8-K filings and daily prices (first time only)..."):
        events, price_note = data.all_events(data.user_agent(), company.cik, company.ticker)
    st.markdown(
        '<div class="ca-muted"><b>Stock moves</b> are days the stock moved far more than usual '
        "<i>after allowing for the whole market's move that day</i> (compared with SPY, which "
        "tracks the S&amp;P 500), and by at least 4%. Prices from Tiingo.</div>",
        unsafe_allow_html=True)
    if price_note:
        setup = (" Sign up free at tiingo.com, then add <code>TIINGO_API_KEY = "
                 "\"your-token\"</code> to <code>.streamlit/secrets.toml</code> and restart "
                 "the dashboard." if "TIINGO_API_KEY" in price_note else "")
        placeholder(html.escape(price_note) + setup)
    if not events:
        st.info(f"No notable 8-K events in the last {data.EVENT_YEARS} years. Routine filings "
                "are listed in the Filings section.")
        return

    kinds = sorted({e.category for e in events})
    chosen = st.multiselect("Types", kinds, default=kinds, key=f"ev_kinds_{company.ticker}")
    shown = [e for e in events if e.category in chosen]
    news_cutoff = date.today() - timedelta(days=365)
    for i, e in enumerate(shown):
        st.markdown(_event_html(e), unsafe_allow_html=True)
        if e.date >= news_cutoff and data.get_secret("FINNHUB_API_KEY"):
            with st.expander("Headlines around that day"):
                articles, error = data.event_headlines(company.ticker, e.date)
                if error:
                    st.caption(error)
                elif not articles:
                    st.caption("No headlines found for those days.")
                for a in articles[:6]:
                    when = a["date"].strftime("%b %d") if a["date"] else ""
                    st.markdown(f'<div class="ca-headline"><a href="{html.escape(a["url"], quote=True)}" '
                                f'target="_blank">{html.escape(a["title"])}</a>'
                                f'<div>{html.escape(a["source"])} · {when}</div></div>',
                                unsafe_allow_html=True)
    st.caption("Headlines are shown for events in the last year (Finnhub's free plan keeps "
               "about a year of news).")
