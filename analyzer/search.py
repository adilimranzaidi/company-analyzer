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
