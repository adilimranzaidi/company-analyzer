"""Headlines from the GDELT Project (gdeltproject.org): a free, open index of worldwide
news coverage, used through its official API rather than by scraping news sites.

GDELT asks for at most one request every 5 seconds, so we pace requests and save each
result for an hour. Headlines are shown as links to the original articles; nothing here
is summarized or interpreted by AI.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "news"
CACHE_HOURS = 1
MIN_SECONDS_BETWEEN_REQUESTS = 6

# Legal-form words to drop from SEC names before searching the news:
# "AMERICAN EXPRESS CO" is written "American Express" in articles.
_LEGAL_SUFFIXES = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED",
    "PLC", "LLC", "LP", "L.P.", "NV", "N.V.", "SA", "S.A.", "AG", "SE", "HOLDINGS",
    "HOLDING", "GROUP", "THE", "&", "DE", "NEW", "CLASS", "A", "B",
}


class NewsError(Exception):
    """A problem fetching headlines, with a message written for the dashboard user."""


def news_name(sec_name: str) -> str:
    """"AMERICAN EXPRESS CO" -> "American Express";  "Apple Inc." -> "Apple"."""
    words = re.sub(r"/[A-Z]{2,3}/?", " ", sec_name).replace(",", " ").split()
    while words and words[-1].upper().strip(".") in {w.strip(".") for w in _LEGAL_SUFFIXES}:
        words.pop()
    while words and words[0].upper() == "THE":
        words.pop(0)
    cleaned = " ".join(words) or sec_name
    return cleaned.title() if cleaned.isupper() else cleaned


def build_query(names: list[str]) -> str:
    """GDELT search: exact phrases joined with OR, English-language sources only."""
    phrases = [f'"{n}"' for n in dict.fromkeys(n for n in names if n)]
    body = phrases[0] if len(phrases) == 1 else "(" + " OR ".join(phrases) + ")"
    return f"{body} sourcelang:english"


def parse_articles(payload: dict) -> list[dict]:
    """Keep only the fields we show, newest first, one entry per title."""
    seen, articles = set(), []
    for a in payload.get("articles", []):
        title = (a.get("title") or "").strip()
        if not title or title.lower() in seen or not a.get("url", "").startswith("http"):
            continue
        seen.add(title.lower())
        try:
            when = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ")
        except ValueError:
            when = None
        articles.append({"title": title, "url": a["url"], "source": a.get("domain", ""),
                         "date": when})
    return sorted(articles, key=lambda x: x["date"] or datetime.min, reverse=True)


RETRIES = 3   # GDELT's limit is shared by everyone on the same internet address, so a
              # refusal is often gone a few seconds later.


@dataclass
class NewsResult:
    articles: list[dict]
    saved_hours_ago: float | None = None   # set when showing saved headlines instead of fresh


class NewsClient:
    def __init__(self, user_agent: str = "", cache_dir: Path = CACHE_DIR, sleep=time.sleep):
        self.cache_dir = Path(cache_dir)
        self.session = requests.Session()
        if user_agent:
            self.session.headers["User-Agent"] = user_agent
        self._last_request = 0.0
        self._sleep = sleep

    def headlines(self, query: str, timespan: str = "1month", limit: int = 30) -> NewsResult:
        key = hashlib.sha1(f"{query}|{timespan}|{limit}".encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"{key}.json"
        age_hours = ((time.time() - cache_file.stat().st_mtime) / 3600
                     if cache_file.exists() else None)
        if age_hours is not None and age_hours < CACHE_HOURS:
            return NewsResult(_from_cache(json.loads(cache_file.read_text(encoding="utf-8"))))

        try:
            articles = self._fetch(query, timespan, limit)
        except NewsError:
            # Still refused after retrying: show the last saved headlines, if any, and say so.
            if age_hours is not None:
                saved = _from_cache(json.loads(cache_file.read_text(encoding="utf-8")))
                return NewsResult(saved, saved_hours_ago=age_hours)
            raise
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(_to_cache(articles)), encoding="utf-8")
        return NewsResult(articles)

    def _fetch(self, query: str, timespan: str, limit: int) -> list[dict]:
        for attempt in range(RETRIES):
            wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - self._last_request)
            if wait > 0:
                self._sleep(wait)
            try:
                response = self.session.get(GDELT_URL, timeout=30, params={
                    "query": query, "mode": "artlist", "format": "json", "sort": "datedesc",
                    "maxrecords": limit, "timespan": timespan,
                })
            except requests.RequestException as exc:
                raise NewsError("Couldn't reach the GDELT news service. Check your connection.") from exc
            finally:
                self._last_request = time.time()
            if response.status_code != 429:
                break
        else:
            raise NewsError("The GDELT news service is busy for your network right now (it "
                            f"refused {RETRIES} tries). Try again in a minute.")

        if not response.ok:
            raise NewsError(f"The GDELT news service returned an error ({response.status_code}).")
        try:
            payload = response.json()
        except ValueError:
            # GDELT replies in plain text when a query is too short or too broad.
            raise NewsError("GDELT couldn't run this search: " + response.text[:150])
        return parse_articles(payload)


def _to_cache(articles):
    return [{**a, "date": a["date"].isoformat() if a["date"] else None} for a in articles]


def _from_cache(rows):
    return [{**a, "date": datetime.fromisoformat(a["date"]) if a["date"] else None} for a in rows]
