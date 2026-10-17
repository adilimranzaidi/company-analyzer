"""The company's SEC filings: 10-K (annual report), 10-Q (quarterly report) and
8-K (current report, filed within days of a major event), with links.

8-K item codes are translated into plain English using the SEC's official list of items
(Form 8-K General Instructions). No AI is involved: the code is a fixed lookup.
"""

from dataclasses import dataclass

import pandas as pd

ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{document}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.htm"

FORM_NAMES = {
    "10-K": "Annual report", "10-K/A": "Annual report (amended)",
    "10-Q": "Quarterly report", "10-Q/A": "Quarterly report (amended)",
    "8-K": "Current report (event)", "8-K/A": "Current report (amended)",
    "20-F": "Annual report (foreign company)", "40-F": "Annual report (Canadian company)",
    "6-K": "Current report (foreign company)",
}

# The SEC's 8-K items, in plain English.
EIGHT_K_ITEMS = {
    "1.01": "Signed a major agreement",
    "1.02": "Ended a major agreement",
    "1.03": "Bankruptcy or receivership",
    "1.04": "Mine safety violation",
    "1.05": "Material cybersecurity incident",
    "2.01": "Completed an acquisition or sale of assets",
    "2.02": "Quarterly or annual results (earnings release)",
    "2.03": "Took on a major debt or obligation",
    "2.04": "Event that speeds up or increases a debt",
    "2.05": "Restructuring or exit costs (e.g. layoffs, closures)",
    "2.06": "Material impairment (write-down of assets)",
    "3.01": "Stock exchange listing issue or transfer",
    "3.02": "Sold unregistered shares",
    "3.03": "Changed shareholders' rights",
    "4.01": "Changed auditor",
    "4.02": "Past financial statements can no longer be relied on",
    "5.01": "Change in control of the company",
    "5.02": "Director or executive officer change, or executive pay",
    "5.03": "Changed bylaws or fiscal year",
    "5.04": "Suspended trading in employee benefit plans",
    "5.05": "Changed or waived the code of ethics",
    "5.06": "Change in shell-company status",
    "5.07": "Results of a shareholder vote",
    "5.08": "Shareholder director nominations",
    "6.01": "Asset-backed securities: informational material",
    "6.02": "Asset-backed securities: change of servicer or trustee",
    "6.03": "Asset-backed securities: change in credit enhancement",
    "6.04": "Asset-backed securities: missed distribution",
    "6.05": "Asset-backed securities: pool characteristics changed",
    "6.06": "Asset-backed securities: static pool",
    "7.01": "Shared information with investors (e.g. presentation)",
    "8.01": "Other events",
    "9.01": "Financial statements and exhibits attached",
}

# Items that usually matter most to an analyst. 9.01 (exhibits) and 7.01 (investor
# materials) are routine, so they don't make an 8-K "significant" on their own.
SIGNIFICANT_ITEMS = {"1.01", "1.02", "1.03", "1.05", "2.01", "2.02", "2.03", "2.05", "2.06",
                     "3.01", "4.01", "4.02", "5.01", "5.02"}

MAIN_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "20-F", "40-F", "6-K"}


def filing_url(cik: str, accession: str, document: str) -> str:
    folder = accession.replace("-", "")
    return ARCHIVE_URL.format(cik=int(cik), folder=folder, document=document)


def index_url(cik: str, accession: str) -> str:
    """The filing's index page, which lists every document in it. Needs only the
    accession number, so it works for any filing we know the number of."""
    folder = accession.replace("-", "")
    return INDEX_URL.format(cik=int(cik), folder=folder, accession=accession)


def describe_items(items: str) -> list[str]:
    """"2.02,9.01" -> ["Quarterly or annual results (earnings release)", "Financial ..."]."""
    codes = [c.strip() for c in (items or "").split(",") if c.strip()]
    return [EIGHT_K_ITEMS.get(c, f"Item {c}") for c in codes]


def is_significant(items: str) -> bool:
    return any(c.strip() in SIGNIFICANT_ITEMS for c in (items or "").split(","))


@dataclass
class LatestReports:
    annual: dict | None
    quarterly: dict | None


def filings_table(submissions: dict, cik: str) -> pd.DataFrame:
    """The company's recent 10-K, 10-Q and 8-K filings (and amendments), newest first."""
    recent = submissions.get("filings", {}).get("recent", {})
    columns = ["form", "form_name", "filed", "period", "accession", "url", "index_url",
               "about", "items", "significant"]
    rows = []
    for i, form in enumerate(recent.get("form", [])):
        if form not in MAIN_FORMS:
            continue
        accession = recent["accessionNumber"][i]
        document = recent["primaryDocument"][i]
        items = recent.get("items", [""] * (i + 1))[i] or ""
        about = "; ".join(describe_items(items)) if form.startswith(("8-K", "6-K")) else ""
        rows.append({
            "form": form,
            "form_name": FORM_NAMES.get(form, form),
            "filed": pd.to_datetime(recent["filingDate"][i]).date(),
            "period": recent.get("reportDate", [""] * (i + 1))[i] or "",
            "accession": accession,
            "url": filing_url(cik, accession, document) if document else index_url(cik, accession),
            "index_url": index_url(cik, accession),
            "about": about,
            "items": items,
            "significant": form.startswith("8-K") and is_significant(items),
        })
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values("filed", ascending=False) \
        .reset_index(drop=True)


def latest_reports(table: pd.DataFrame) -> LatestReports:
    """The newest annual and quarterly report (originals preferred over amendments)."""
    def newest(forms):
        hit = table[table["form"].isin(forms)]
        return hit.iloc[0].to_dict() if not hit.empty else None
    return LatestReports(annual=newest({"10-K", "20-F", "40-F"}) or newest({"10-K/A"}),
                         quarterly=newest({"10-Q"}) or newest({"10-Q/A"}))
