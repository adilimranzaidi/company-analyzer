"""Loading data for the dashboard, with Streamlit's caching so each download and
calculation happens once and is reused while the app runs."""

import streamlit as st

from analyzer.edgar_client import Company, EdgarClient, EdgarError
from analyzer.financials import MetricData, load_all_metrics
from analyzer.news import NewsClient, NewsError
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
def news_client(agent: str) -> NewsClient:
    return NewsClient(agent)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def search_options(agent: str) -> list[dict]:
    return edgar_client(agent).search_options()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def company(agent: str, ticker: str) -> Company:
    return edgar_client(agent).lookup_company(ticker)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def metrics(agent: str, cik: str, fye_month: int) -> dict[str, MetricData]:
    return load_all_metrics(edgar_client(agent).company_facts(cik), fye_month)


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


@st.cache_data(ttl=3600, show_spinner=False)
def headlines(agent: str, query: str, timespan: str) -> tuple[list[dict], str]:
    """(articles, error message). Errors are returned, not raised, so one failed news
    request never breaks the rest of the page."""
    try:
        return news_client(agent).headlines(query, timespan=timespan), ""
    except NewsError as err:
        return [], str(err)
