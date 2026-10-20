"""Suggest peer companies, from two sources:

1. **Competitors the company names itself.** Most 10-Ks have a "Competition" section. We
   look there for the names of listed companies ("Visa", "Mastercard", "Capital One") by
   exact, whole-word text matching. No AI: it's the company's own list, in its own words.
2. **The same SEC industry (SIC) code**, as a backup. Companies registered under the same
   code, kept to those with a stock ticker and ranked by total assets (which every company
   reports), using the SEC's "frames" data: everyone's figure in one download.

SEC codes are broad and split real competitors apart (AmEx is "finance services", Visa and
Mastercard are "business services"), which is why the 10-K's own list comes first. The
person using the app can still add or remove peers.
"""

import re
from dataclasses import dataclass
from datetime import date

from analyzer.edgar_client import EdgarClient, EdgarError, pretty_company_name

# Words dropped from SEC names to get the name a filing would use: "Capital One Financial
# Corp" is written "Capital One"; "PayPal Holdings, Inc." is written "PayPal".
_GENERIC_WORDS = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc",
    "llc", "lp", "nv", "sa", "ag", "se", "holdings", "holding", "group", "financial",
    "services", "global", "international", "technologies", "technology", "the", "&", "de",
    "new", "class", "a", "b", "bancorp", "trust",
}
# Brand names that are also ordinary English words; matching them would find sentences
# like "we block fraudulent transactions", so they are skipped.
# (Interface Inc. matched "Application Programming Interface" in Visa's 10-K.)
_COMMON_WORDS = {"block", "target", "square", "gap", "match", "apple", "discovery",
                 "progressive", "general", "united", "american", "first", "national",
                 "capital", "global", "best", "chase", "focus", "cash", "trade", "service",
                 "interface", "principal", "customers", "columbia", "community", "premier"}
MIN_ASSETS = 1e9   # ignore tiny listed shells whose names happen to match


@dataclass(frozen=True)
class Peer:
    cik: str
    ticker: str
    name: str
    total_assets: float
    source: str = "SEC industry code"   # or "Named in the 10-K"
    evidence: str = ""                  # for 10-K matches: the sentence that names them


def brand_name(sec_name: str) -> str:
    """"CAPITAL ONE FINANCIAL CORP" -> "Capital One"; "Visa Inc." -> "Visa"."""
    name = pretty_company_name(sec_name)
    words = re.sub(r"[,.]", " ", name).split()
    while words and words[-1].lower() in _GENERIC_WORDS:
        words.pop()
    while words and words[0].lower() == "the":
        words.pop(0)
    return " ".join(words)


def find_named_competitors(text: str, companies: list[dict], exclude_cik: str,
                           assets_by_cik: dict[str, float], limit: int = 8) -> list[Peer]:
    """Listed companies named (exactly, as whole words) in a Competition section.

    companies: [{"cik", "ticker", "name"}]. When several listed companies share a brand
    name, the largest by total assets is used.
    """
    sentences = re.split(r"(?<=[.;])\s+", text)
    best: dict[str, Peer] = {}
    for c in companies:
        cik = c["cik"]
        if cik == exclude_cik or assets_by_cik.get(cik, 0) < MIN_ASSETS:
            continue
        brand = brand_name(c["name"])
        if len(brand) < 3 or (" " not in brand and brand.lower() in _COMMON_WORDS):
            continue
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(brand)}(?![A-Za-z])")
        hit = next((s for s in sentences if _names_company(pattern, brand, s, text)), None)
        if hit is None:
            continue
        peer = Peer(cik, c["ticker"], pretty_company_name(c["name"]), assets_by_cik[cik],
                    "Named in the 10-K", hit.strip()[:300])
        if brand not in best or peer.total_assets > best[brand].total_assets:
            best[brand] = peer
    found = sorted(best.values(), key=lambda p: p.total_assets, reverse=True)
    return found[:limit]


def _names_company(pattern: re.Pattern, brand: str, sentence: str, text: str) -> bool:
    """Does this sentence name the company, rather than use the same word another way?

    Multi-word names ("Capital One", "Keurig Dr Pepper") are distinctive enough as they are.
    Single-word names get three extra checks, learned from real mistakes:
    - not the first word of the sentence ("Principal competitive factors include..."),
    - the word never appears in lower case in the text, which would make it an ordinary
      word ("Customers are using..." when "customers" appears elsewhere),
    - not right after "of" ("District of Columbia")."""
    for m in pattern.finditer(sentence):
        if " " in brand:
            return True
        before = sentence[:m.start()].rstrip()
        if not before or before.endswith((".", ":", "•")):
            continue                                    # start of a sentence or bullet
        if re.search(rf"(?<![A-Za-z]){re.escape(brand.lower())}(?![A-Za-z])", text):
            continue                                    # also used as an ordinary word
        if before.lower().endswith((" of", "of")):
            continue
        return True
    return False


def competition_text(passages: list) -> str:
    """The Competition section of a 10-K (passages are from analyzer.filing_text).

    If no passage is labelled "Competition" (many 10-Ks write that heading in normal
    capitalization, which isn't detected as a heading), fall back to every sentence that
    mentions competing in the Business and Risk factors sections."""
    parts = [p.text for p in passages if "competition" in p.section.lower()]
    if parts:
        return "\n".join(parts)
    sentences = []
    for p in passages:
        if p.section.startswith(("Item 1. ", "Item 1A. ")):
            sentences += [s for s in re.split(r"(?<=[.;])\s+", p.text)
                          if re.search(r"(?i)\bcompet(e|es|ing|ition|itor|itors|itive)\b", s)]
    return "\n".join(sentences)


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


def assets_by_cik(client: EdgarClient, today: date | None = None) -> dict[str, float]:
    for period in recent_balance_sheet_periods(today or date.today()):
        try:
            frame = client.frame("Assets", "USD", period)
        except EdgarError:
            continue
        if len(frame.get("data", [])) > 1000:   # a well-populated quarter
            return {str(row["cik"]).zfill(10): row["val"] for row in frame["data"]}
    return {}


def suggest_peers(client: EdgarClient, cik: str, sic_code: str, limit: int = 6,
                  today: date | None = None, competition: str = "") -> list[Peer]:
    """Competitors named in the 10-K first (if `competition` text is given), then
    same-industry companies to fill up to `limit`."""
    assets = assets_by_cik(client, today)
    tickers = client.primary_tickers()
    names = {row["cik"]: row["name"] for row in client.ticker_table().values()}

    named: list[Peer] = []
    if competition:
        companies = [{"cik": c, "ticker": t, "name": names.get(c, t)} for c, t in tickers.items()]
        named = find_named_competitors(competition, companies, cik, assets, limit=limit)

    industry: list[Peer] = []
    if sic_code and len(named) < limit:
        taken = {p.cik for p in named}
        ranked = rank_peers(client.companies_in_industry(sic_code), assets, tickers, names,
                            cik, limit + len(taken))
        industry = [p for p in ranked if p.cik not in taken][:limit - len(named)]
    return named + industry
