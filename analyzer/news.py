"""Headlines from Finnhub (finnhub.io), looked up by stock ticker.

Why Finnhub rather than GDELT: Finnhub finds news by ticker, so "V" means Visa the company,
not every article containing the word "visa". GDELT searched by name, which matched
unrelated articles ("Strategy") or missed the company ("Coinbase Global"), and its shared
rate limit refused most requests on this network.

Free-plan limits: about 60 requests a minute, about one year of history, personal and
non-commercial use. Headlines are shown as links to the original articles; nothing here
is summarized or interpreted by AI. Results are saved for an hour.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "news"
CACHE_HOURS = 1


class NewsError(Exception):
    """A problem fetching headlines, with a message written for the dashboard user."""


@dataclass
class NewsResult:
    articles: list[dict]
    saved_hours_ago: float | None = None   # set when showing saved headlines instead of fresh


def parse_articles(items: list[dict], ticker: str = "") -> list[dict]:
    """Keep only the fields we show, newest first, one entry per headline."""
    seen, articles = set(), []
    for a in items or []:
        title = (a.get("headline") or "").strip()
        url = a.get("url") or ""
        if not title or title.lower() in seen or not url.startswith("http"):
            continue
        seen.add(title.lower())
        stamp = a.get("datetime")
        when = (datetime.fromtimestamp(stamp, tz=timezone.utc).replace(tzinfo=None)
                if isinstance(stamp, (int, float)) and stamp > 0 else None)
        articles.append({"title": title, "url": url, "source": a.get("source", ""),
                         "date": when, "ticker": ticker,
                         "summary": (a.get("summary") or "").strip()})
    return sorted(articles, key=lambda x: x["date"] or datetime.min, reverse=True)


def merge_articles(groups: list[list[dict]], limit: int) -> list[dict]:
    """Combine several tickers' headlines, newest first, dropping repeats."""
    seen, merged = set(), []
    for a in sorted((a for g in groups for a in g),
                    key=lambda x: x["date"] or datetime.min, reverse=True):
        if a["title"].lower() not in seen:
            seen.add(a["title"].lower())
            merged.append(a)
    return merged[:limit]


class NewsClient:
    def __init__(self, api_key: str, cache_dir: Path = CACHE_DIR):
        if not api_key:
            raise NewsError("Add FINNHUB_API_KEY to .streamlit/secrets.toml to see headlines.")
        self.cache_dir = Path(cache_dir)
        self.session = requests.Session()
        # Sent as a header, not in the web address, so the key doesn't end up in logs.
        self.session.headers["X-Finnhub-Token"] = api_key

    def company_news(self, ticker: str, days: int = 30, today: date | None = None) -> NewsResult:
        today = today or date.today()
        start = today - timedelta(days=days)
        key = hashlib.sha1(f"{ticker}|{days}|{today}".encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"finnhub_{key}.json"
        age_hours = ((time.time() - cache_file.stat().st_mtime) / 3600
                     if cache_file.exists() else None)
        if age_hours is not None and age_hours < CACHE_HOURS:
            return NewsResult(_from_cache(json.loads(cache_file.read_text(encoding="utf-8"))))

        try:
            articles = self._fetch(ticker, start, today)
        except NewsError:
            if age_hours is not None:      # show the last saved headlines, and say so
                saved = _from_cache(json.loads(cache_file.read_text(encoding="utf-8")))
                return NewsResult(saved, saved_hours_ago=age_hours)
            raise
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(_to_cache(articles)), encoding="utf-8")
        return NewsResult(articles)

    def news_between(self, ticker: str, start: date, end: date) -> list[dict]:
        """Headlines for a fixed date range (e.g. the days around an event). Saved for a
        day; news about past dates rarely changes."""
        key = hashlib.sha1(f"{ticker}|{start}|{end}".encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"finnhub_range_{key}.json"
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 24 * 3600:
            return _from_cache(json.loads(cache_file.read_text(encoding="utf-8")))
        articles = self._fetch(ticker, start, end)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(_to_cache(articles)), encoding="utf-8")
        return articles

    def _fetch(self, ticker: str, start: date, end: date) -> list[dict]:
        try:
            response = self.session.get(FINNHUB_NEWS_URL, timeout=30, params={
                "symbol": ticker, "from": start.isoformat(), "to": end.isoformat(),
            })
        except requests.RequestException as exc:
            raise NewsError("Couldn't reach Finnhub. Check your internet connection.") from exc
        if response.status_code in (401, 403):
            raise NewsError("Finnhub didn't accept the API key. Check FINNHUB_API_KEY in "
                            ".streamlit/secrets.toml.")
        if response.status_code == 429:
            raise NewsError("Finnhub's free-plan limit (about 60 requests a minute) was "
                            "reached. Try again in a minute.")
        if not response.ok:
            raise NewsError(f"Finnhub returned an error ({response.status_code}).")
        try:
            return parse_articles(response.json(), ticker)
        except ValueError as exc:
            raise NewsError("Finnhub sent a reply the app couldn't read.") from exc


def _to_cache(articles):
    return [{**a, "date": a["date"].isoformat() if a["date"] else None} for a in articles]


def _from_cache(rows):
    return [{**a, "date": datetime.fromisoformat(a["date"]) if a["date"] else None} for a in rows]
