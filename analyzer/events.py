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

# Item names that are too generic to stand alone, so the 8-K's own words are read and the
# first real sentence about the item is shown as evidence. (Exxon's 2026 move to a new
# holding company was filed under 2.01 "acquisition or sale" and 3.01 "listing".)
READ_ITEMS = {"2.01", "3.01", "5.01", "1.02"}
# A company moving under a new parent or a new state of incorporation. One such 8-K ticks
# several item boxes; it's shown as one event in its own words instead.
REORGANIZATION = r"redomicil|reincorporat|holding company reorganization"
# Sentences that only point elsewhere ("The information set forth in ... is incorporated").
POINTER = r"incorporated (?:herein )?by reference|set forth (?:in|under|above|below)"

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


def _sentences(text: str) -> list[str]:
    return [x.strip(" |") for x in re.split(r"(?<=[.;])\s+(?=[A-Z“\"(])", text)]


def reorganization(lines: list[str]) -> str | None:
    """The sentence describing a reorganization under a new parent company or state of
    incorporation, or None."""
    for sentence in _sentences(" ".join(line for line in lines if " | " not in line)):
        if 40 < len(sentence) < 600 and re.search(REORGANIZATION, sentence, re.IGNORECASE):
            return sentence
    return None


def item_evidence(lines: list[str], code: str) -> str:
    """The first real sentence under an item heading ("Item 2.01 ..."), skipping the heading
    itself and sentences that only point to another section. "" if none."""
    text = " ".join(lines)
    m = re.search(rf"Item\s+{re.escape(code)}(?!\d)", text)
    if not m:
        return ""
    section = text[m.end():m.end() + 3000]
    # Stop at the next item's heading (not a mention like "set forth in Item 1.01").
    nxt = re.search(r"(?<!in )(?<!under )(?<!of )(?<!to )Item\s+\d\.\d\d", section)
    for sentence in _sentences(section[:nxt.start()] if nxt else section)[:8]:
        sentence = sentence.strip(" |.")
        words = sentence.split()
        heading = len(words) <= 10 and sum(w[:1].isupper() for w in words) >= len(words) * .5
        if len(sentence) > 40 and not heading and not re.search(POINTER, sentence, re.IGNORECASE):
            return sentence[:400]
    return ""


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

    read_lines(url) -> list[str] fetches an 8-K's text; it's only called for filings whose
    item codes need their own words (5.02 and READ_ITEMS).
    """
    events: list[Event] = []
    eight_ks = filings[filings["form"].isin(["8-K", "8-K/A"]) & (filings["filed"] >= since)]
    for _, row in eight_ks.iterrows():
        codes = [c.strip() for c in (row["items"] or "").split(",")]
        lines: list[str] = []
        if OFFICER_ITEM in codes or READ_ITEMS & set(codes):
            try:
                lines = read_lines(row["url"])
            except Exception:          # an unreadable filing shouldn't hide the others
                lines = []
        reorg = reorganization(lines) if READ_ITEMS & set(codes) else None
        if reorg:
            events.append(Event(row["filed"], "Reorganization",
                                "Reorganized under a new parent company (not an acquisition)",
                                "medium", reorg[:400], row["url"], row["form"]))
            continue                   # its other item boxes describe the same move
        for code in codes:
            if code in EVENT_ITEMS:
                category, title, severity = EVENT_ITEMS[code]
                evidence = item_evidence(lines, code) if code in READ_ITEMS else ""
                events.append(Event(row["filed"], category, title, severity, evidence,
                                    row["url"], row["form"]))
        if OFFICER_ITEM in codes:
            change = officer_change(lines) if lines else None
            if change:
                category, title, evidence = change
                events.append(Event(row["filed"], category, title, "medium",
                                    evidence[:400], row["url"], row["form"]))
    return sorted(events, key=lambda e: e.date, reverse=True)
