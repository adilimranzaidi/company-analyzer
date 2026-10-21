"""Loading data for the dashboard, with Streamlit's caching so each download and
calculation happens once and is reused while the app runs."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from analyzer.edgar_client import Company, EdgarClient, EdgarError
from analyzer.events import Event, build_events
from analyzer.filing_text import Passage, filing_lines, filing_passages
from analyzer.filings import filings_table, latest_reports
from analyzer.financials import MetricData, fiscal_period, load_all_metrics
from analyzer.news import NewsClient, NewsError, merge_articles
from analyzer.peers import Peer, competition_text, suggest_peers
from analyzer.search import FilingSearch
from analyzer.prices import MARKET, PriceClient, PriceError, big_moves, describe_move


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
def passages(agent: str, url: str, label: str, form: str, period: str = "") -> list[Passage]:
    """A filing split into labelled passages (filings never change once filed)."""
    return filing_passages(edgar_client(agent).download_text, url, label, form, period)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def peers(agent: str, cik: str, sic_code: str) -> list[Peer]:
    """Competitors named in the latest 10-K first, then same-industry companies."""
    competition = ""
    try:
        annual = latest_reports(filings(agent, cik)).annual
        if annual:
            competition = competition_text(passages(agent, annual["url"], "10-K", annual["form"]))
    except EdgarError:
        pass                      # no 10-K text: industry-code peers only
    try:
        return suggest_peers(edgar_client(agent), cik, sic_code, limit=6, competition=competition)
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


EVENT_YEARS = 5   # how far back notable events go


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def events(agent: str, cik: str) -> list[Event]:
    """Notable events from the company's 8-Ks over the last few years."""
    since = date.today() - timedelta(days=round(365.25 * EVENT_YEARS))
    client = edgar_client(agent)
    return build_events(filings(agent, cik), lambda url: filing_lines(client.download_text, url),
                        since)


def event_headlines(ticker: str, day: date) -> tuple[list[dict], str]:
    """Headlines from the day before to two days after an event. Finnhub's free plan keeps
    about a year of news, so older events return nothing (said plainly on the page)."""
    key = get_secret("FINNHUB_API_KEY")
    if not key:
        return [], "Add a Finnhub key to see headlines from that day."
    try:
        return news_client(key).news_between(ticker, day - timedelta(days=1),
                                             day + timedelta(days=2)), ""
    except NewsError as err:
        return [], str(err)


def price_moves(ticker: str) -> tuple[pd.DataFrame, str]:
    """Big one-day stock moves over the event window, or ("", error message).
    Not cached here (failures shouldn't be remembered); PriceClient saves prices to disk."""
    try:
        client = PriceClient(get_secret("TIINGO_API_KEY"))
        start = date.today() - timedelta(days=round(365.25 * EVENT_YEARS))
        stock = client.daily(ticker, start)
        market = client.daily(MARKET, start)
        return big_moves(stock, market), ""
    except PriceError as err:
        return pd.DataFrame(), str(err)


def all_events(agent: str, cik: str, ticker: str) -> tuple[list[Event], str]:
    """8-K events plus big stock moves, newest first, and a note if prices are unavailable.
    Each stock move lists any 8-K filed within three days, as a likely explanation."""
    filed = events(agent, cik)
    moves, note = price_moves(ticker)
    # For explaining stock moves, every 8-K counts, including routine earnings releases:
    # many of the biggest one-day moves happen on earnings day.
    table = filings(agent, cik)
    eight_ks = table[table["form"].isin(["8-K", "8-K/A"])]
    combined = list(filed)
    for _, row in moves.iterrows():
        title, severity, explanation = describe_move(row, ticker)
        nearby = eight_ks[eight_ks["filed"].apply(lambda d: abs((d - row["date"]).days) <= 3)]
        if not nearby.empty:
            explanation += " 8-Ks filed within three days: " + "; ".join(
                f"{r['about'] or r['form']} ({r['filed']:%b %d})" for _, r in nearby.iterrows()) + "."
        combined.append(Event(row["date"], "Stock move", title, severity, explanation, "",
                              "Price data"))
    return sorted(combined, key=lambda e: e.date, reverse=True), note


@st.cache_resource(show_spinner=False)
def filing_search(cik: str, urls: tuple[str, ...], fye_month: int, _passages: list[Passage]):
    """A search index over all the given filings' passages, built once per company and set
    of filings. (The leading underscore tells Streamlit not to hash the long passage list;
    the filing addresses identify it.)"""
    return FilingSearch(_passages, lambda d: fiscal_period(d, fye_month), date.today())
