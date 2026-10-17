"""All communication with SEC EDGAR lives in this file.

Rules the SEC asks every program to follow, and how this file follows them:
- Identify yourself: every request carries a User-Agent with a name and email.
- Don't overload the servers (max 10 requests per second): we wait a short moment
  between requests, and we save every download to data/cache/ so the same file isn't
  fetched again until it's due for a refresh.
"""

import calendar
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
COMPANY_PAGE_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

# The SEC allows at most 10 requests per second. Waiting 0.15s keeps us under ~7.
MIN_SECONDS_BETWEEN_REQUESTS = 0.15

# How long a saved download stays "fresh" before we fetch it again.
TICKERS_MAX_AGE_HOURS = 24      # the ticker list changes rarely
SUBMISSIONS_MAX_AGE_HOURS = 6   # new filings can appear any business day
COMPANY_FACTS_MAX_AGE_HOURS = 6
INDUSTRY_LIST_MAX_AGE_HOURS = 24 * 7   # which companies share an industry code changes slowly
FRAMES_MAX_AGE_HOURS = 24

# Every company registered under one SEC industry code (an Atom feed the SEC publishes).
INDUSTRY_LIST_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
# One figure for every company at once, e.g. everyone's total assets at 2025 year end.
FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json"


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
    fiscal_year_end_month: int = 12  # 1-12; used to label fiscal quarters
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


# Words that stay as written when tidying up the SEC's ALL-CAPS company names.
_NAME_KEEP_UPPER = {"IBM", "AT&T", "USA", "US", "UK", "LLC", "LP", "PLC", "NV", "SA", "AG",
                    "SE", "ETF", "REIT", "II", "III", "IV", "HP", "AMD", "CSX", "BNY",
                    "UPS", "NXP", "TJX", "CVS", "AES", "PNC", "MSCI", "KLA", "NRG", "DTE"}
_NAME_KEEP_LOWER = {"of", "and", "the", "for", "de", "&"}


def pretty_company_name(name: str) -> str:
    """The SEC writes many names in capitals: "AMERICAN EXPRESS CO" -> "American Express Co".
    Names already in mixed case ("Apple Inc.") are left alone. State tags the SEC adds,
    like "/DE/" (incorporated in Delaware), are removed."""
    name = re.sub(r"\s*[/\\][A-Za-z]{2,3}[/\\]?\s*$", "", name or "").strip()
    if not name or not name.isupper():
        return name
    words = []
    for i, word in enumerate(name.split()):
        bare = word.strip(".,/")
        if bare in _NAME_KEEP_UPPER:
            words.append(word)
        elif i > 0 and word.lower() in _NAME_KEEP_LOWER:
            words.append(word.lower())
        else:
            words.append(word.capitalize())
    return " ".join(words)


def build_search_options(table: dict[str, dict]) -> list[dict]:
    """One searchable entry per ticker, e.g. "American Express Co (AXP)".
    Lets people search by company name or by ticker in the same box."""
    options = [
        {"label": f"{pretty_company_name(row['name'])} ({ticker})", "ticker": ticker,
         "cik": row["cik"]}
        for ticker, row in table.items()
    ]
    return sorted(options, key=lambda o: o["label"].lower())


def primary_ticker_by_cik(raw: dict) -> dict[str, str]:
    """A company can have several tickers (BRK-A, BRK-B). The SEC lists the main one
    first, so keep the first ticker seen for each company."""
    result: dict[str, str] = {}
    for row in raw.values():
        result.setdefault(format_cik(row["cik_str"]), row["ticker"].upper())
    return result


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
        return self._download(url).json()

    def _download(self, url: str, params: dict | None = None) -> requests.Response:
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.time() - self._last_request_time)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.session.get(url, params=params, timeout=30)
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
        return response

    # --- public functions used by the dashboard ---------------------------

    def _raw_tickers(self) -> dict:
        return self._get_json(TICKERS_URL, "company_tickers.json", TICKERS_MAX_AGE_HOURS)

    def ticker_table(self) -> dict[str, dict]:
        return build_ticker_table(self._raw_tickers())

    def search_options(self) -> list[dict]:
        return build_search_options(self.ticker_table())

    def primary_tickers(self) -> dict[str, str]:
        return primary_ticker_by_cik(self._raw_tickers())

    def companies_in_industry(self, sic_code: str) -> list[str]:
        """CIKs of every company registered under an SEC industry (SIC) code.
        The SEC's list comes 100 companies per page, so we read pages until one is short."""
        cache_file = self.cache_dir / f"industry_{sic_code}.json"
        if cache_file.exists():
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            if age_hours < INDUSTRY_LIST_MAX_AGE_HOURS:
                return json.loads(cache_file.read_text(encoding="utf-8"))
        ciks: list[str] = []
        for start in range(0, 5000, 100):
            page = self._download(INDUSTRY_LIST_URL, params={
                "action": "getcompany", "SIC": sic_code, "type": "10-K", "dateb": "",
                "owner": "include", "count": 100, "start": start, "output": "atom",
            }).text
            found = re.findall(r"<cik>(\d+)</cik>", page)
            ciks.extend(format_cik(c) for c in found)
            if len(found) < 100:
                break
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(ciks), encoding="utf-8")
        return ciks

    def frame(self, concept: str, unit: str, period: str) -> dict:
        """One figure for every company for one period, e.g. Assets at CY2025Q4I."""
        return self._get_json(
            FRAMES_URL.format(concept=concept, unit=unit, period=period),
            f"frame_{concept}_{unit.replace('/', '-')}_{period}.json",
            FRAMES_MAX_AGE_HOURS,
        )

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
        mmdd = details.get("fiscalYearEnd", "") or ""
        company.fiscal_year_end = format_fiscal_year_end(mmdd)
        if company.fiscal_year_end:
            company.fiscal_year_end_month = int(mmdd[:2])
        company.filer_category = details.get("category", "") or ""
        return company

    def company_facts(self, cik: str) -> dict:
        """Every number the company has tagged in its filings (the SEC's "XBRL" data)."""
        cik = format_cik(cik)
        return self._get_json(
            COMPANY_FACTS_URL.format(cik=cik),
            f"companyfacts_{cik}.json",
            COMPANY_FACTS_MAX_AGE_HOURS,
        )
