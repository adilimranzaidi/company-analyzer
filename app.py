"""Company Analyzer: the dashboard page.

This file only arranges the page: search, the company header, and the section menu.
Each section is drawn by a file in ui/, and all data and math live in analyzer/.
"""

import streamlit as st

from analyzer.edgar_client import EdgarError, pretty_company_name
from ui import ask, compare, data, filings, industry, news_events, overview, style, trends
from ui.terms import glossary_panel

st.set_page_config(page_title="Company Analyzer", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")
style.apply()

SECTIONS = ["Overview", "Company trends", "Industry", "Compare", "News and events", "Filings",
            "Ask"]

agent = data.user_agent()
if "@" not in agent:
    st.error("Add your name and email as SEC_USER_AGENT in .streamlit/secrets.toml. "
             "The SEC requires it on every request.")
    st.stop()

# --- Sidebar: setup check (out of the way) ----------------------------------
with st.sidebar:
    st.header("Setup check")
    for label, secret in [("SEC contact", "SEC_USER_AGENT"),
                          ("Anthropic API key", "ANTHROPIC_API_KEY"),
                          ("Finnhub key (headlines)", "FINNHUB_API_KEY"),
                          ("Tiingo key (stock prices)", "TIINGO_API_KEY")]:
        (st.success if data.get_secret(secret) else st.warning)(
            f"{label}: {'configured' if data.get_secret(secret) else 'missing'}")

# --- Search: company name or ticker -----------------------------------------
try:
    options = data.search_options(agent)
except EdgarError as err:
    st.error(str(err))
    st.stop()
labels = [o["label"] for o in options]
ticker_by_label = {o["label"]: o["ticker"] for o in options}

st.session_state.setdefault("ticker", "AXP")
current_label = next((o["label"] for o in options if o["ticker"] == st.session_state.ticker),
                     None)


def _on_search() -> None:
    picked = st.session_state.get("search")
    if picked:
        st.session_state.ticker = ticker_by_label[picked]
        st.session_state.section = "Overview"


title_col, search_col, glossary_col = st.columns([1, 2, 0.45], vertical_alignment="bottom")
title_col.markdown('<p class="ca-brand">Company Analyzer</p>', unsafe_allow_html=True)
with glossary_col.popover("Glossary", width="stretch"):
    glossary_panel()
search_col.selectbox(
    "Search", labels, index=labels.index(current_label) if current_label in labels else None,
    key="search", on_change=_on_search, label_visibility="collapsed",
    placeholder="Search by company name or ticker, e.g. American Express or AXP",
)

# --- Company header -----------------------------------------------------------
try:
    with st.spinner("Loading company from SEC EDGAR..."):
        company = data.company(agent, st.session_state.ticker)
        metrics = data.metrics(agent, company.cik, company.fiscal_year_end_month)
except EdgarError as err:
    st.error(f"Couldn't load this company's financial data. Some filers (many funds and "
             f"recent IPOs) don't have it yet. Details: {err}")
    st.stop()

st.markdown(f"# {pretty_company_name(company.name)}")
meta = [company.ticker, ", ".join(company.exchanges), company.industry,
        f"Fiscal year ends {company.fiscal_year_end}" if company.fiscal_year_end else ""]
st.markdown(f'<div class="ca-meta">{" · ".join(m for m in meta if m)} · '
            f'<a href="{company.edgar_url}" target="_blank">SEC filings</a></div>',
            unsafe_allow_html=True)
st.write("")

# --- Section menu -------------------------------------------------------------
st.session_state.setdefault("section", "Overview")
section = st.segmented_control("Section", SECTIONS, key="section",
                               label_visibility="collapsed") or "Overview"
st.divider()

if section == "Overview":
    overview.render(company, metrics)
elif section == "Company trends":
    trends.render(company, metrics)
elif section == "Industry":
    industry.render(company, metrics, options)
elif section == "Compare":
    compare.render(company, options)
elif section == "News and events":
    news_events.render(company, metrics)
elif section == "Filings":
    filings.render(company)
else:
    ask.render(company, metrics)
