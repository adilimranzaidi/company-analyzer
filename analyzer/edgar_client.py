"""All communication with SEC EDGAR lives in this file.

Rules the SEC asks every program to follow, and how this file follows them:
- Identify yourself: every request carries a User-Agent with a name and email.
- Don't overload the servers (max 10 requests per second): we wait a short moment
  between requests, and we save every download to data/cache/ so the same file isn't
  fetched again until it's due for a refresh.
"""

import calendar
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_PAGE_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

# The SEC allows at most 10 requests per second. Waiting 0.15s keeps us under ~7.
MIN_SECONDS_BETWEEN_REQUESTS = 0.15

# How long a saved download stays "fresh" before we fetch it again.
TICKERS_MAX_AGE_HOURS = 24      # the ticker list changes rarely
SUBMISSIONS_MAX_AGE_HOURS = 6   # new filings can appear any business day


class EdgarError(Exception):
    """A problem talking to the SEC, with a message written for the dashboard user."""


class TickerNotFound(EdgarError):
    """The ticker isn't in the SEC's list of companies."""


@dataclass
class Company:
    """Basic facts about one company, as the SEC records them."""

    cik: str                      # 10-digit SEC ID, e.g. "0000004962" for AmEx
    ticker: str
    name: str
    industry: str = ""            # SEC's industry description (from its SIC code)
    sic_code: str = ""            # Standard Industrial Classification number
    exchanges: list[str] = field(default_factory=list)
    fiscal_year_end: str = ""     # e.g. "December 31"
    filer_category: str = ""      # e.g. "Large accelerated filer"

    @property
    def edgar_url(self) -> str:
        return COMPANY_PAGE_URL.format(cik=self.cik)


# ---------------------------------------------------------------------------
# Small helpers (no internet needed, so they're easy to test)
# ---------------------------------------------------------------------------

def normalize_ticker(text: str) -> str:
    """Clean up what the user typed so it matches the SEC's format.

    "  axp " -> "AXP".  The SEC writes share classes with a dash, so "BRK.B" -> "BRK-B".
    """
    return text.strip().upper().replace(".", "-").replace("/", "-")


def format_cik(cik: int | str) -> str:
    """The SEC's web addresses need the CIK padded to 10 digits: 4962 -> "0000004962"."""
    return str(int(cik)).zfill(10)


def format_fiscal_year_end(mmdd: str) -> str:
    """The SEC stores fiscal year end as "MMDD": "1231" -> "December 31"."""
    if not mmdd or len(mmdd) != 4 or not mmdd.isdigit():
        return ""
    month, day = int(mmdd[:2]), int(mmdd[2:])
    if not 1 <= month <= 12:
        return ""
    return f"{calendar.month_name[month]} {day}"


def build_ticker_table(raw: dict) -> dict[str, dict]:
    """Turn the SEC's ticker file into a lookup table: {"AXP": {"cik": ..., "name": ...}}."""
    table = {}
    for row in raw.values():
        table[row["ticker"].upper()] = {
            "cik": format_cik(row["cik_str"]),
            "name": row["title"],
        }
    return table


def find_company(ticker: str, table: dict[str, dict]) -> Company:
    """Look a ticker up in the table, or raise TickerNotFound with a helpful message."""
    clean = normalize_ticker(ticker)
    if not clean:
        raise TickerNotFound("Please enter a ticker symbol, for example AXP.")
    row = table.get(clean)
    if row is None:
        raise TickerNotFound(
            f'"{clean}" isn\'t in the SEC\'s list of company tickers. Check the spelling. '
            "Note that only companies that file with the SEC are included, so most "
            "foreign-listed companies and funds won't appear."
        )
    return Company(cik=row["cik"], ticker=clean, name=row["name"])


# ---------------------------------------------------------------------------
# The client: the only part of the project that actually contacts the SEC
# ---------------------------------------------------------------------------

class EdgarClient:
    def __init__(self, user_agent: str, cache_dir: Path = CACHE_DIR):
        user_agent = (user_agent or "").strip()
        if "@" not in user_agent:
            raise EdgarError(
                "The SEC requires a name and email on every request. Set SEC_USER_AGENT "
                'in .streamlit/secrets.toml, e.g. "Jane Doe jane@example.com".'
            )
        self.cache_dir = Path(cache_dir)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        })
        self._last_request_time = 0.0

    # --- downloading with caching -----------------------------------------

    def _get_json(self, url: str, cache_name: str, max_age_hours: float) -> dict:
        """Return JSON from the cache if it's fresh enough, otherwise download it."""
        cache_file = self.cache_dir / cache_name
        if cache_file.exists():
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            if age_hours < max_age_hours:
                return json.loads(cache_file.read_text(encoding="utf-8"))

        data = self._download_json(url)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data

    def _download_json(self, url: str) -> dict:
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - self._last_request_time)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.session.get(url, timeout=30)
        except requests.RequestException as exc:
            raise EdgarError(
                "Couldn't reach the SEC website. Check your internet connection and try again."
            ) from exc
        finally:
            self._last_request_time = time.time()

        if response.status_code == 403:
            raise EdgarError(
                "The SEC refused the request (error 403). This usually means the "
                "SEC_USER_AGENT name/email is missing or malformed, or too many requests "
                "were sent. Wait a minute and try again."
            )
        if response.status_code == 404:
            raise EdgarError(f"The SEC has no data at {url} (error 404).")
        if not response.ok:
            raise EdgarError(
                f"The SEC website returned an error ({response.status_code}). Try again shortly."
            )
        return response.json()

    # --- public functions used by the dashboard ---------------------------

    def ticker_table(self) -> dict[str, dict]:
        raw = self._get_json(TICKERS_URL, "company_tickers.json", TICKERS_MAX_AGE_HOURS)
        return build_ticker_table(raw)

    def submissions(self, cik: str) -> dict:
        """The SEC's "submissions" record: company details plus its list of filings."""
        cik = format_cik(cik)
        return self._get_json(
            SUBMISSIONS_URL.format(cik=cik),
            f"submissions_{cik}.json",
            SUBMISSIONS_MAX_AGE_HOURS,
        )

    def lookup_company(self, ticker: str) -> Company:
        """Ticker -> Company, with industry and fiscal-year details filled in."""
        company = find_company(ticker, self.ticker_table())
        details = self.submissions(company.cik)
        company.industry = details.get("sicDescription", "") or ""
        company.sic_code = details.get("sic", "") or ""
        # The SEC lists the exchange once per share class (Berkshire: NYSE, NYSE),
        # so drop repeats while keeping the original order.
        company.exchanges = list(dict.fromkeys(e for e in details.get("exchanges", []) if e))
        company.fiscal_year_end = format_fiscal_year_end(details.get("fiscalYearEnd", ""))
        company.filer_category = details.get("category", "") or ""
        return company
