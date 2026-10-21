"""Notable events: things that happened to the company, not just numbers that moved.

Source: 8-K "current reports", which companies must file within four business days of a
major event, each tagged with official SEC item codes. We keep the serious types and skip
routine ones (quarterly earnings releases, investor presentations, exhibits).

Executive changes (item 5.02) need a closer look, because the same item also covers
routine pay arrangements and board elections. For those, the app reads the 8-K's own
text and only reports a departure or appointment of a senior officer when a sentence
says so (for example "... will retire as Chief Executive Officer ..."). That sentence is
shown as evidence. This is plain text matching: no AI is involved.
"""

import re
from dataclasses import dataclass
from datetime import date

import pandas as pd

# Item code -> (category, plain-English title, severity). "high" items are rare and serious.
EVENT_ITEMS = {
    "4.02": ("Restatement", "Past financial statements can no longer be relied on "
                            "(a restatement)", "high"),
    "1.03": ("Bankruptcy", "Bankruptcy or receivership", "high"),
    "1.05": ("Cybersecurity", "Material cybersecurity incident", "high"),
    "5.01": ("Change in control", "Change in control of the company", "high"),
    "3.01": ("Listing", "Stock exchange listing problem or transfer", "high"),
    "4.01": ("Auditor change", "Changed its outside auditor", "medium"),
    "2.06": ("Impairment", "Material write-down of assets (impairment)", "medium"),
    "2.05": ("Restructuring", "Restructuring or exit costs (for example layoffs or closures)",
             "medium"),
    "2.01": ("Acquisition or sale", "Completed an acquisition or sale of assets", "medium"),
    "1.02": ("Agreement ended", "Ended a major agreement", "medium"),
}
OFFICER_ITEM = "5.02"

# Senior company-wide roles, most senior first. ("President" is left out: it appears in
# many divisional titles such as "Vice President and Chief Accounting Officer".)
ROLES = [
    ("Chief Executive Officer", r"chief executive officer|\bCEO\b"),
    ("Chief Financial Officer", r"chief financial officer|\bCFO\b"),
    ("Chief Operating Officer", r"chief operating officer|\bCOO\b"),
    ("Chair of the Board", r"chair(?:man|woman|person)? of the board|executive chair(?:man)?"),
]
DEPARTURE = (r"resign|retire|step(?:s|ped|ping)? down|depart|terminat|separat|"
             r"leave the company|will leave|cease(?:s|d)? (?:to serve|serving)|no longer serve")
APPOINTMENT = (r"appoint|\bnamed\b(?! executive officer)|\belect(?:ed)?\b(?! officers)|promot|"
               r"will succeed|to succeed|will become|has been hired")
# Sentences describing someone's past, or a new director's career elsewhere.
BIOGRAPHY = (r"\b(previously|formerly|prior to (?:joining|that)|has served as|served as|"
             r"was selected as a director|biograph|from \d{4} (?:to|until)|check mark|"
             r"emerging growth company)\b")      # the last two: 8-K cover-page text
# How close (in characters) the action word must be to the role.
NEAR = 150


@dataclass
class Event:
    date: date
    category: str
    title: str
    severity: str           # "high" or "medium"
    evidence: str           # a sentence from the filing, when the text was read
    url: str
    form: str


def item_events(items: str) -> list[tuple[str, str, str]]:
    """Serious event types listed in an 8-K's item codes (excluding 5.02, read separately)."""
    codes = [c.strip() for c in (items or "").split(",")]
    return [EVENT_ITEMS[c] for c in codes if c in EVENT_ITEMS]


def _company_role(sentence: str, m: re.Match) -> bool:
    """Is this mention of a role the company's own top job (not a division's, another
    company's, or a reporting line like "advisor to the CEO")?"""
    after = sentence[m.end():m.end() + 45]
    if re.match(r"\s+of\s+(?!the\s+(?:company|corporation|bank|board)\b)", after, re.IGNORECASE):
        return False              # "CEO of Boeing Defense", "CFO of Acme Corp"
    before = sentence[max(0, m.start() - 12):m.start()]
    if re.search(r"\b[A-Z]{2,5}\s+$", before):
        return False              # a division acronym: "PSG Chief Executive Officer"
    return not before.lower().endswith(("to the ", "to our ", "reporting to "))


def officer_change(lines: list[str]) -> tuple[str, str, str] | None:
    """(category, title, evidence sentence) if an 8-K's text reports a senior officer
    leaving or being appointed; None for routine 5.02 filings (pay plans, board seats).

    Rules, each learned from a real false alarm: table rows are ignored (pay tables say
    "Named Executive Officer"); biographies are ignored ("previously appointed CEO in
    2010"); the role must be the company's own ("CEO of Intel Products" isn't); and the
    action word must be close to the role."""
    text = " ".join(line for line in lines if " | " not in line)
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z])", text)
    found = []
    for sentence in sentences:
        if len(sentence) > 500 or re.search(BIOGRAPHY, sentence, re.IGNORECASE):
            continue
        for rank, (role, pattern) in enumerate(ROLES):
            for m in re.finditer(pattern, sentence, re.IGNORECASE):
                if not _company_role(sentence, m):
                    continue
                window = sentence[max(0, m.start() - NEAR):m.end() + NEAR]
                leaving = re.search(DEPARTURE, window, re.IGNORECASE)
                joining = re.search(APPOINTMENT, window, re.IGNORECASE)
                if leaving and joining:
                    kind = "transition"
                elif leaving:
                    kind = "departure announced"
                elif joining:
                    kind = "appointed"
                else:
                    continue
                found.append((rank, role, kind, sentence.strip()))
                break
    if not found:
        return None
    rank, role, kind, sentence = min(found, key=lambda f: f[0])   # most senior role
    return ("Executive change", f"{role} {kind}", sentence)


def build_events(filings: pd.DataFrame, read_lines, since: date) -> list[Event]:
    """Notable events from the company's 8-Ks since a date, newest first.

    read_lines(url) -> list[str] fetches an 8-K's text; it's only called for 5.02 filings.
    """
    events: list[Event] = []
    eight_ks = filings[filings["form"].isin(["8-K", "8-K/A"]) & (filings["filed"] >= since)]
    for _, row in eight_ks.iterrows():
        for category, title, severity in item_events(row["items"]):
            events.append(Event(row["filed"], category, title, severity, "", row["url"],
                                row["form"]))
        if OFFICER_ITEM in [c.strip() for c in (row["items"] or "").split(",")]:
            try:
                change = officer_change(read_lines(row["url"]))
            except Exception:          # an unreadable filing shouldn't hide the others
                change = None
            if change:
                category, title, evidence = change
                events.append(Event(row["filed"], category, title, "medium",
                                    evidence[:400], row["url"], row["form"]))
    return sorted(events, key=lambda e: e.date, reverse=True)
