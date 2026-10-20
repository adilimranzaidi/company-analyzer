"""Loading data for the dashboard, with Streamlit's caching so each download and
calculation happens once and is reused while the app runs."""

import pandas as pd
import streamlit as st

from analyzer.edgar_client import Company, EdgarClient, EdgarError
from analyzer.filing_text import Passage, filing_passages
from analyzer.filings import filings_table
from analyzer.financials import MetricData, load_all_metrics
from analyzer.news import NewsClient, NewsError, merge_articles
from analyzer.peers import Peer, suggest_peers


def get_secret(name: str) -> str:
    """Read a secret, returning "" if it's missing. Never displays the value."""
    try:
        return str(st.secrets[name]).strip()
    except (KeyError, FileNotFoundError):
        return ""


def user_agent() -> str:
    return get_secret("SEC_USER_AGENT")


@st.cache_resource
def edgar_client(agent: str) -> EdgarClient:
    # Created once and reused, so the pause between SEC requests is respected.
    return EdgarClient(agent)


@st.cache_resource
def news_client(api_key: str) -> NewsClient:
    return NewsClient(api_key)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def search_options(agent: str) -> list[dict]:
    return edgar_client(agent).search_options()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def company(agent: str, ticker: str) -> Company:
    return edgar_client(agent).lookup_company(ticker)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def metrics(agent: str, cik: str, fye_month: int) -> dict[str, MetricData]:
    return load_all_metrics(edgar_client(agent).company_facts(cik), fye_month)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def filings(agent: str, cik: str) -> pd.DataFrame:
    return filings_table(edgar_client(agent).submissions(cik), cik)


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def passages(agent: str, url: str, label: str, form: str) -> list[Passage]:
    """A filing split into labelled passages (filings never change once filed)."""
    return filing_passages(edgar_client(agent).download_text, url, label, form)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def peers(agent: str, cik: str, sic_code: str) -> list[Peer]:
    try:
        return suggest_peers(edgar_client(agent), cik, sic_code, limit=6)
    except EdgarError:
        return []


def company_and_metrics(ticker: str) -> tuple[Company, dict[str, MetricData]] | None:
    """For comparisons: returns None (instead of stopping the page) if a company has no data."""
    try:
        co = company(user_agent(), ticker)
        return co, metrics(user_agent(), co.cik, co.fiscal_year_end_month)
    except EdgarError:
        return None


# Not cached here: NewsClient already saves successful results to disk for an hour, and
# caching here would also remember failures.
def headlines(tickers: tuple[str, ...], days: int) -> tuple[list[dict], str, float | None]:
    """(articles, error message, hours since saved if not fresh) for one or more tickers.
    Errors are returned, not raised, so a news problem never breaks the rest of the page."""
    try:
        client = news_client(get_secret("FINNHUB_API_KEY"))
        groups, oldest = [], None
        for t in tickers:
            result = client.company_news(t, days=days)
            groups.append(result.articles)
            if result.saved_hours_ago is not None:
                oldest = max(oldest or 0, result.saved_hours_ago)
        return merge_articles(groups, limit=40), "", oldest
    except NewsError as err:
        return [], str(err), None
