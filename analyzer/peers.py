"""Suggest peer companies: same SEC industry code, publicly traded, ranked by size.

How it works
1. The SEC lists every company registered under an industry (SIC) code.
2. We keep only companies with a stock ticker (many registrants are private funds or shells).
3. We rank them by total assets, which every company reports (unlike revenue, whose
   label varies), using the SEC's "frames" data: one download with every company's figure.
The suggestions are a starting point. The person using the app can add or remove peers,
because SEC codes are broad (AmEx's "Finance services" code includes very different firms).
"""

from dataclasses import dataclass
from datetime import date

from analyzer.edgar_client import EdgarClient, EdgarError, pretty_company_name


@dataclass(frozen=True)
class Peer:
    cik: str
    ticker: str
    name: str
    total_assets: float


def recent_balance_sheet_periods(today: date, count: int = 4) -> list[str]:
    """SEC frame names for the most recent quarter-ends, newest first, e.g. "CY2026Q2I".

    The current quarter is skipped: companies file 1-3 months after a quarter ends,
    so its frame would be nearly empty.
    """
    year, quarter = today.year, (today.month - 1) // 3 + 1
    periods = []
    for _ in range(count):
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
        periods.append(f"CY{year}Q{quarter}I")
    return periods


def rank_peers(industry_ciks: list[str], assets_by_cik: dict[str, float],
               ticker_by_cik: dict[str, str], names: dict[str, str],
               exclude_cik: str, limit: int) -> list[Peer]:
    """Publicly traded companies from the industry list, largest first."""
    peers = [
        Peer(cik, ticker_by_cik[cik], pretty_company_name(names.get(cik, ticker_by_cik[cik])),
             assets_by_cik[cik])
        for cik in dict.fromkeys(industry_ciks)          # drop duplicates, keep order
        if cik != exclude_cik and cik in ticker_by_cik and cik in assets_by_cik
    ]
    return sorted(peers, key=lambda p: p.total_assets, reverse=True)[:limit]


def suggest_peers(client: EdgarClient, cik: str, sic_code: str, limit: int = 6,
                  today: date | None = None) -> list[Peer]:
    if not sic_code:
        return []
    industry = client.companies_in_industry(sic_code)

    assets: dict[str, float] = {}
    for period in recent_balance_sheet_periods(today or date.today()):
        try:
            frame = client.frame("Assets", "USD", period)
        except EdgarError:
            continue
        if len(frame.get("data", [])) > 1000:   # a well-populated quarter
            assets = {str(row["cik"]).zfill(10): row["val"] for row in frame["data"]}
            break

    tickers = client.primary_tickers()
    names = {row["cik"]: row["name"] for row in client.ticker_table().values()}
    return rank_peers(industry, assets, tickers, names, cik, limit)
