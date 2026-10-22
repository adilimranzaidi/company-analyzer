"""The company synopsis on the Overview: a plain-English briefing written by the assistant
from the company's own filings, with every point cited.

Sources for each section
- What the company does and how it makes money: latest 10-K, Item 1 (Business).
- The latest quarter: latest 10-Q, MD&A (the reasons); numbers only from "Dashboard figures".
- Recent notable events: the dashboard's 8-K events and stock moves ("Dashboard figures").
- Key risks: latest 10-K, Item 1A (Risk factors).
- Interview talking points: drawn only from the above.

A synopsis is saved and reused until the company files a new 10-K or 10-Q.
"""

import re

from analyzer.search import BM25

SECTIONS = ["What the company does", "How it makes money", "The latest quarter",
            "Recent notable events", "Key risks", "Interview talking points"]

REQUEST = """Write a briefing on {name} for someone preparing for a finance job interview.
Use exactly these Markdown headings, in this order, each followed by 2-5 short bullet points:
### What the company does
### How it makes money
### The latest quarter
### Recent notable events
### Key risks
### Interview talking points

Guidance:
- "What the company does" and "How it makes money": from the 10-K's Business section (products, \
customers, segments, main revenue sources).
- "The latest quarter": the period and headline figures from "Dashboard figures", and the reasons \
management gives in the latest report's Management's discussion (MD&A).
- "Recent notable events": from the notable events listed in "Dashboard figures" (most recent first); \
if there are none, say so.
- "Key risks": the 3-5 most important risks from the 10-K's Risk factors, in plain English.
- "Interview talking points": 3-5 points someone could raise in an interview. Each must reuse facts \
already stated above, cite the same sources, and add no new facts or details.
If a section can't be supported by the documents, write "Not covered in the filings searched." under it."""

LENGTH_RULE = ("Be clear and compact: follow the requested headings, with 2-5 short bullet points "
               "under each.")

# What each part of the synopsis searches for: (item number, search words, how many passages).
BUSINESS = ("1", "business overview products services customers segments revenue fees how we "
                 "generate revenue competition", 7)
RISKS = ("1A", "risk factors significant risks could adversely affect", 5)
RESULTS = "results of operations compared increase decrease primarily due to drivers quarter"
RESULTS_COUNT = 6


def in_item(section: str, number: str) -> bool:
    """True if a passage's section label is that Item (so "1" matches Item 1, not 1A or 10)."""
    return re.match(rf"Item {re.escape(number)}\b", section) is not None


def _best(pool: list, words: str, k: int) -> list:
    if not pool:
        return []
    scores = BM25([f"{p.section}\n{p.text}" for p in pool]).scores(words)
    best = sorted(range(len(pool)), key=lambda i: scores[i], reverse=True)[:k]
    return [pool[i] for i in sorted(best)]             # keep the filing's own order


def pick_passages(annual: list, recent: list) -> list:
    """The passages each synopsis section needs.

    annual: the latest 10-K's passages (business and risks).
    recent: the newest periodic report's passages (a 10-Q, or the 10-K itself when it's newer),
    for management's explanation of the latest results: MD&A is Item 2 in a 10-Q, Item 7 in a 10-K.
    """
    chosen = []
    for number, words, k in (BUSINESS, RISKS):
        chosen += _best([p for p in annual if in_item(p.section, number)], words, k)
    mdna = [p for p in recent
            if in_item(p.section, "2" if str(p.form).startswith("10-Q") else "7")]
    chosen += [p for p in _best(mdna, RESULTS, RESULTS_COUNT) if p not in chosen]
    return chosen


def identifier(annual_accession: str, recent_accession: str) -> str:
    """Names a synopsis by the filings it's based on, so a new filing means a new synopsis."""
    return f"{annual_accession}|{recent_accession}"
