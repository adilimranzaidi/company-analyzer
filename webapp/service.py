"""The data behind the web dashboard: the same loading rules as the Streamlit version
(ui/data.py), without Streamlit.

Speed rules
- Every result is remembered in memory for a while (and most are also saved to disk by the
  analyzer code), so a second visit is instant.
- "Single flight": when two requests ask for the same thing at the same moment (the page
  asks for several panels at once), the work is done once and both get the result.
- Slow downloads that don't depend on each other (peer companies) run side by side.
"""

import json
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import pandas as pd
import requests

from analyzer.compare import snapshot
from analyzer.edgar_client import Company, EdgarClient, EdgarError
from analyzer.events import Event, build_events
from analyzer.filing_text import Passage, filing_lines, filing_passages
from analyzer.filings import company_filings, latest_reports
from analyzer.financials import MetricData, fiscal_period, load_all_metrics_saved
from analyzer.news import NewsClient, NewsError, merge_articles
from analyzer.peers import Peer, competition_text, suggest_peers
from analyzer.prices import MARKET, PriceClient, PriceError, big_moves, describe_move
from analyzer.search import FilingSearch

ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILE = ROOT / ".streamlit" / "secrets.toml"
CACHE_DIR = ROOT / "data" / "cache"
EVENT_YEARS = 5
PRICE_YEARS = 5

# Threads for slow, independent downloads (SEC pacing is enforced inside EdgarClient).
POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ca")


# ---------------------------------------------------------------------------
# Remembering results
# ---------------------------------------------------------------------------

def remembered(ttl_seconds: float):
    """Remember a function's results for a while, by its arguments. Errors are not
    remembered (a failed download is retried next time). Concurrent calls with the same
    arguments wait for the first one instead of repeating the work."""
    def wrap(fn):
        store: dict = {}
        locks: dict = {}
        guard = threading.Lock()

        @wraps(fn)
        def inner(*args):
            hit = store.get(args)
            if hit and time.monotonic() - hit[0] < ttl_seconds:
                return hit[1]
            with guard:
                lock = locks.setdefault(args, threading.Lock())
            with lock:
                hit = store.get(args)                 # someone may have just filled it
                if hit and time.monotonic() - hit[0] < ttl_seconds:
                    return hit[1]
                value = fn(*args)
                store[args] = (time.monotonic(), value)
                return value

        inner.forget = store.clear
        return inner
    return wrap


# ---------------------------------------------------------------------------
# Settings and clients
# ---------------------------------------------------------------------------

def secret(name: str) -> str:
    """A key from .streamlit/secrets.toml, or "" if missing. Never logged or shown."""
    try:
        with open(SECRETS_FILE, "rb") as f:
            return str(tomllib.load(f).get(name, "")).strip()
    except FileNotFoundError:
        return ""


_client_lock = threading.Lock()
_client: EdgarClient | None = None


def edgar() -> EdgarClient:
    """One shared SEC client, so its pause between requests is respected by every thread."""
    global _client
    with _client_lock:
        if _client is None:
            _client = EdgarClient(secret("SEC_USER_AGENT"))
        return _client


# ---------------------------------------------------------------------------
# Companies and their figures
# ---------------------------------------------------------------------------

@remembered(24 * 3600)
def search_index() -> list[list[str]]:
    """[ticker, name] for every listed company, for the search box (searched in the page)."""
    return [[o["ticker"], o["label"].rsplit(" (", 1)[0]] for o in edgar().search_options()]


@remembered(6 * 3600)
def company(ticker: str) -> Company:
    return edgar().lookup_company(ticker)


@remembered(6 * 3600)
def metrics(ticker: str) -> dict[str, MetricData]:
    co = company(ticker)
    return load_all_metrics_saved(edgar(), co.cik, co.fiscal_year_end_month)


@remembered(6 * 3600)
def filings(ticker: str) -> pd.DataFrame:
    co = company(ticker)
    return company_filings(edgar(), co.cik)


def company_and_metrics(ticker: str):
    """(company, metrics), or None if the company has no usable data."""
    try:
        return company(ticker), metrics(ticker)
    except EdgarError:
        return None


@remembered(6 * 3600)
def peer_snapshot(ticker: str) -> dict | None:
    loaded = company_and_metrics(ticker)
    return snapshot(loaded[1]) if loaded else None


# ---------------------------------------------------------------------------
# Logo, website and market value (Finnhub company profile)
# ---------------------------------------------------------------------------

PROFILE_DIR = CACHE_DIR / "profiles"
PROFILE_MAX_AGE = 7 * 24 * 3600


@remembered(24 * 3600)
def profile(ticker: str) -> dict:
    """{"logo", "weburl", "market_cap" (US$ millions), "name"} or {} if unavailable."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILE_DIR / f"{ticker}.json"
    if path.exists() and time.time() - path.stat().st_mtime < PROFILE_MAX_AGE:
        return json.loads(path.read_text(encoding="utf-8"))
    key = secret("FINNHUB_API_KEY")
    if not key:
        return {}
    try:
        r = requests.get("https://finnhub.io/api/v1/stock/profile2", params={"symbol": ticker},
                         headers={"X-Finnhub-Token": key}, timeout=15)
        raw = r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        return {}
    data = {"logo": raw.get("logo") or "", "weburl": raw.get("weburl") or "",
            "market_cap": raw.get("marketCapitalization"), "name": raw.get("name") or ""}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def logo(ticker: str) -> bytes | None:
    """The company's logo image, downloaded once and saved. Served from our own address so
    the page can read its colours (to pick the company's brand colour)."""
    path = PROFILE_DIR / f"{ticker}.png"
    if path.exists():
        return path.read_bytes() or None
    url = profile(ticker).get("logo")
    if not url:
        return None
    for _ in range(2):                     # one retry: the image host is sometimes slow
        try:
            r = requests.get(url, timeout=(5, 10))
        except requests.RequestException:
            continue
        if r.ok and r.content and r.headers.get("content-type", "").startswith("image/"):
            path.write_bytes(r.content)
            return r.content
    return None


# ---------------------------------------------------------------------------
# Prices and events
# ---------------------------------------------------------------------------

@remembered(3600)
def prices(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(stock, market) daily prices for the last few years. Raises PriceError."""
    client = PriceClient(secret("TIINGO_API_KEY"))
    start = date.today() - timedelta(days=round(365.25 * PRICE_YEARS))
    futures = [POOL.submit(client.daily, t, start) for t in (ticker, MARKET)]
    return futures[0].result(), futures[1].result()


@remembered(6 * 3600)
def filed_events(ticker: str) -> list[Event]:
    since = date.today() - timedelta(days=round(365.25 * EVENT_YEARS))
    client = edgar()
    return build_events(filings(ticker), lambda url: filing_lines(client.download_text, url),
                        since)


def all_events(ticker: str) -> tuple[list[Event], str]:
    """8-K events plus big stock moves, newest first, and a note if prices are unavailable."""
    events = filed_events(ticker)
    try:
        stock, market = prices(ticker)
        moves, note = big_moves(stock, market), ""
    except PriceError as err:
        moves, note = pd.DataFrame(), str(err)
    table = filings(ticker)
    eight_ks = table[table["form"].isin(["8-K", "8-K/A"])]
    combined = list(events)
    for _, row in moves.iterrows():
        title, severity, explanation = describe_move(row, ticker)
        day = row["date"]
        nearby = eight_ks[eight_ks["filed"].apply(lambda d, day=day: abs((d - day).days) <= 3)]
        if not nearby.empty:
            explanation += " 8-Ks filed within three days: " + "; ".join(
                f"{r['about'] or r['form']} ({r['filed']:%b %d})"
                for _, r in nearby.iterrows()) + "."
        combined.append(Event(day, "Stock move", title, severity, explanation, "", "Price data"))
    return sorted(combined, key=lambda e: e.date, reverse=True), note


# ---------------------------------------------------------------------------
# Headlines
# ---------------------------------------------------------------------------

def _news() -> NewsClient | None:
    key = secret("FINNHUB_API_KEY")
    return NewsClient(key) if key else None


def headlines(ticker: str, days: int = 14) -> tuple[list[dict], str]:
    client = _news()
    if client is None:
        return [], "Add a Finnhub key to see headlines."
    try:
        return merge_articles([client.company_news(ticker, days=days).articles], limit=30), ""
    except NewsError as err:
        return [], str(err)


def headlines_around(ticker: str, day: date) -> tuple[list[dict], str]:
    client = _news()
    if client is None:
        return [], "Add a Finnhub key to see headlines."
    try:
        return client.news_between(ticker, day - timedelta(days=1), day + timedelta(days=2)), ""
    except NewsError as err:
        return [], str(err)


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------

@remembered(24 * 3600)
def peers(ticker: str) -> list[Peer]:
    """Competitors named in the latest 10-K first, then same-industry companies."""
    co = company(ticker)
    competition = ""
    try:
        annual = latest_reports(filings(ticker)).annual
        if annual:
            competition = competition_text(
                filing_passages(edgar().download_text, annual["url"], "10-K", annual["form"]))
    except EdgarError:
        pass
    try:
        return suggest_peers(edgar(), co.cik, co.sic_code, limit=6, competition=competition)
    except EdgarError:
        return []


def load_many(tickers: list[str]) -> dict[str, tuple]:
    """ticker -> (company, metrics) for each that has data, loaded side by side."""
    futures = {t: POOL.submit(company_and_metrics, t) for t in tickers}
    return {t: f.result() for t, f in futures.items() if f.result()}


# ---------------------------------------------------------------------------
# Filing text for the assistant
# ---------------------------------------------------------------------------

@remembered(7 * 24 * 3600)
def passages(url: str, label: str, form: str, period: str = "") -> list[Passage]:
    return filing_passages(edgar().download_text, url, label, form, period)


def filing_label(row: dict) -> str:
    return f"{row['form']} · period ending {row['period'] or 'n/a'} · filed {row['filed']}"


def row_passages(row: dict) -> list[Passage]:
    """Passages for one filing; for an 8-K, also its Exhibit 99 press releases."""
    label = filing_label(row)
    out = passages(row["url"], label, row["form"], row.get("period") or "")
    if str(row["form"]).startswith("8-K"):
        try:
            for url in edgar().exhibit_urls(row["url"]):
                out = out + passages(url, f"{label} · Exhibit 99 (press release)", row["form"],
                                     row.get("period") or "")
        except EdgarError:
            pass
    return out


def read_filings(rows: list[dict]) -> list[Passage]:
    """Passages from several filings, read side by side (each is saved once read)."""
    results = list(POOL.map(row_passages, rows))
    return [p for group in results for p in group]


_searches: dict = {}


def filing_search(ticker: str, rows: list[dict]) -> FilingSearch:
    """A search index over these filings, built once per set of filings."""
    key = (ticker, tuple(r["url"] for r in rows))
    if key not in _searches:
        fye = company(ticker).fiscal_year_end_month
        _searches[key] = FilingSearch(read_filings(rows), lambda d: fiscal_period(d, fye),
                                      date.today())
    return _searches[key]


_prefetched: set[str] = set()


def prefetch(rows: list[dict]) -> None:
    """Start reading filings in the background, ready for the first question."""
    client = edgar()
    for row in rows:
        if row["url"] in _prefetched:
            continue
        _prefetched.add(row["url"])
        POOL.submit(lambda url=row["url"]: filing_lines(client.download_text, url))
