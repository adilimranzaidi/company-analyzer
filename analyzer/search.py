"""Find the filing passages most relevant to a question, with BM25 keyword scoring.

BM25 is the standard formula behind many search engines. A passage scores higher when
it contains the question's words, especially rare ones ("delinquency" counts for more than
"company"), with diminishing returns for repeating a word and a correction so long passages
aren't favored just for being long. It runs in plain Python: no extra installs, and no AI.
"""

import math
import re
from collections import Counter

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further
had has have having he her here hers him his how i if in into is it its itself just me more
most my no nor not now of off on once only or other our ours out over own same she should so
some such than that the their theirs them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you
your yours company companys tell explain please show give describe say says
""".split())


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", text.lower().replace("’", "'"))
    out = []
    for w in words:
        w = w.replace("'s", "")
        if len(w) < 2 or w in STOPWORDS:
            continue
        # Light plural handling so "losses" matches "loss" and "rates" matches "rate".
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith("ses"):
            w = w[:-2]
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.docs else 0
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = set(tokenize(query))
        result = []
        for doc, length in zip(self.docs, self.lengths):
            score = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1))
                    score += self.idf.get(t, 0) * tf * (self.k1 + 1) / norm
            result.append(score)
        return result


def top_passages(passages: list, query: str, k: int = 18) -> list:
    """The k best-matching passages (each passage's section label counts too), in their
    original order so related passages stay together.

    Each filing is guaranteed a fair share (up to k / number of filings), so a long 10-K
    can't crowd out the most recent 10-Q, which often holds the latest explanation."""
    if not passages:
        return []
    index = BM25([f"{p.section}\n{p.text}" for p in passages])
    scores = index.scores(query)
    ranked = [i for i in sorted(range(len(passages)), key=lambda i: scores[i], reverse=True)
              if scores[i] > 0]
    filings = list(dict.fromkeys(p.filing for p in passages))
    share = max(1, k // len(filings))
    chosen: list[int] = []
    for filing in filings:
        chosen += [i for i in ranked if passages[i].filing == filing][:share]
    for i in ranked:                       # fill any remaining room with the best of the rest
        if len(chosen) >= k:
            break
        if i not in chosen:
            chosen.append(i)
    return [passages[i] for i in sorted(chosen[:k])]


# ---------------------------------------------------------------------------
# Searching every 10-K and 10-Q at once, with attention to time
# ---------------------------------------------------------------------------

_QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def time_hints(question: str) -> tuple[set[int], set[tuple[int, int]]]:
    """Fiscal years and (year, quarter) pairs a question mentions.

    "Q2 2023", "Q2 FY2023", "second quarter of 2023" -> quarter (2023, 2)
    "2023", "FY2023", "fiscal 2023"                  -> year 2023
    """
    text = question.replace("’", "'")
    quarters: set[tuple[int, int]] = set()
    for q, y in re.findall(r"\bQ([1-4])\s*(?:of\s+)?(?:FY|fiscal\s+)?'?(\d{4}|\d{2})\b", text, re.I):
        quarters.add((_full_year(y), int(q)))
    for word, y in re.findall(r"\b(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:fiscal\s+)?"
                              r"(?:year\s+)?(\d{4})\b", text, re.I):
        quarters.add((int(y), _QUARTER_WORDS[word.lower()]))
    years = {int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)}   # also "FY2024"
    years |= {fy for fy, _ in quarters}
    return years, quarters


def _full_year(y: str) -> int:
    return int(y) if len(y) == 4 else 2000 + int(y)


class FilingSearch:
    """BM25 search over every passage of every 10-K and 10-Q, built once per company.

    Scores are adjusted for time:
    - the question names a quarter ("Q2 2023"): passages from that quarter's filing count
      2.5x, from the same fiscal year 1.5x;
    - the question names a year: passages from that fiscal year's filings count 2x;
    - no time mentioned: recent filings get a mild boost (up to 1.4x for the newest),
      since most questions are about the company today.
    No single filing may take more than `per_filing` of the passages sent to Claude.
    """

    def __init__(self, passages: list, fiscal_period_of, today):
        """fiscal_period_of(date) -> (fiscal_year, quarter); today: date."""
        from datetime import date as _date
        self.passages = passages
        self.index = BM25([f"{p.section}\n{p.text}" for p in passages])
        self.fiscal: list[tuple[int, int] | None] = []
        self.age_years: list[float] = []
        for p in passages:
            try:
                end = _date.fromisoformat(p.period)
                self.fiscal.append(fiscal_period_of(end))
                self.age_years.append(max(0.0, (today - end).days / 365.25))
            except (TypeError, ValueError):
                self.fiscal.append(None)
                self.age_years.append(99.0)
        self.filings = list(dict.fromkeys(p.filing for p in passages))

    def search(self, query: str, k: int = 18, per_filing: int = 6) -> list:
        years, quarters = time_hints(query)
        scores = self.index.scores(query)
        # "Why" questions are answered in management's discussion (MD&A), not in the
        # financial-statement tables, so MD&A passages get a modest boost for them.
        asks_why = bool(re.search(r"\b(why|drove|driv|caus|reason|explain|behind)\w*", query, re.I))
        boosted = []
        for i, score in enumerate(scores):
            if score <= 0:
                continue
            if asks_why and "MD&A" in self.passages[i].section:
                score *= 1.4
            fiscal = self.fiscal[i]
            if quarters and fiscal in quarters:
                score *= 2.5
            elif (quarters or years) and fiscal and fiscal[0] in years:
                score *= 2.0 if not quarters else 1.5
            elif not (quarters or years):
                score *= 1.0 + 0.4 * max(0.0, 1.0 - self.age_years[i] / 3.0)
            boosted.append((score, i))
        boosted.sort(reverse=True)
        chosen, per = [], {}
        for _, i in boosted:
            filing = self.passages[i].filing
            if per.get(filing, 0) >= per_filing:
                continue
            per[filing] = per.get(filing, 0) + 1
            chosen.append(i)
            if len(chosen) >= k:
                break
        # Newest filing first, and each filing's passages in their original order.
        chosen.sort(key=lambda i: (-(self.fiscal[i] or (0, 0))[0], -(self.fiscal[i] or (0, 0))[1], i))
        return [self.passages[i] for i in chosen]

    def coverage(self) -> str:
        """e.g. "26 filings (10-K and 10-Q) for periods from 2019-09-30 to 2026-06-30"."""
        periods = sorted({p.period for p in self.passages if p.period})
        span = f" for periods from {periods[0]} to {periods[-1]}" if periods else ""
        return f"{len(self.filings)} filings (10-K and 10-Q){span}"
