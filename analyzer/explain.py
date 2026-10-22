"""'Explain from filing': management's own explanation of an unusual change or a notable
event, answered by the Ask assistant from the filing(s) that cover it.

Which documents are read
- Unusual change (a metric's big year-over-year move): the 10-Q or 10-K that first
  reported the number, which is where management discussed it at the time.
- 8-K event (e.g. a CEO departure): that 8-K, plus the next 10-Q or 10-K, which often
  discusses the impact.
- Stock move: 8-Ks filed within three days, the next 10-Q or 10-K, and news headlines
  from those days (labelled as headlines, not filings).

Answers are saved to disk, so each explanation costs a fraction of a cent once and is
free to open again.
"""

import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

from analyzer.assistant import MODEL, Answer, Source

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "explanations"
REPORT_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F"}


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def change_question(metric: str, period: str, change: str) -> str:
    return (f"Why did {metric.lower()} change {change} in {period} compared with the same "
            f"period a year earlier? Use management's own explanation from the filing, and "
            f"name the main drivers. If the filing doesn't explain it, say so.")


def event_question(title: str, day: date, evidence: str = "") -> str:
    context = f' (the filing says: "{evidence[:300]}")' if evidence else ""
    return (f"On {day:%B %d, %Y}: {title}{context}. What happened, and what does the company "
            f"say about why or about its impact? If the documents don't explain it, say so.")


# ---------------------------------------------------------------------------
# Which filings to read
# ---------------------------------------------------------------------------

def filing_by_accession(filings: pd.DataFrame, accession: str) -> dict | None:
    hit = filings[filings["accession"] == accession]
    return hit.iloc[0].to_dict() if not hit.empty else None


def next_report_after(filings: pd.DataFrame, day: date) -> dict | None:
    """The first 10-Q or 10-K filed on or after a date (it usually discusses what happened)."""
    reports = filings[filings["form"].isin(REPORT_FORMS) & (filings["filed"] >= day)]
    return reports.sort_values("filed").iloc[0].to_dict() if not reports.empty else None


def eight_ks_near(filings: pd.DataFrame, day: date, days: int = 3) -> list[dict]:
    near = filings[filings["form"].isin(["8-K", "8-K/A"])
                   & filings["filed"].apply(lambda d: abs((d - day).days) <= days)]
    return near.sort_values("filed").to_dict("records")


def filings_for_change(filings: pd.DataFrame, orig_accession: str) -> list[dict]:
    first = filing_by_accession(filings, orig_accession)
    return [first] if first else []


def filings_for_event(filings: pd.DataFrame, url: str, day: date) -> list[dict]:
    own = filings[filings["url"] == url].to_dict("records")
    follow_up = next_report_after(filings, day)
    return own + ([follow_up] if follow_up and follow_up["url"] != url else [])


def filings_for_stock_move(filings: pd.DataFrame, day: date) -> list[dict]:
    chosen = eight_ks_near(filings, day)
    follow_up = next_report_after(filings, day)
    return chosen + ([follow_up] if follow_up else [])


def headlines_document(articles: list[dict], ticker: str, day: date) -> tuple[str, str, str]:
    lines = [f"Headlines about {ticker} from the days around {day:%B %d, %Y} (titles only):"]
    for a in articles[:15]:
        when = a["date"].strftime("%b %d") if a.get("date") else ""
        lines.append(f"{when}, {a.get('source', '')}: {a['title']}")
    return (f"News headlines around {day:%b %d, %Y}", "\n".join(lines),
            articles[0]["url"] if articles else "")


# ---------------------------------------------------------------------------
# Saving answers
# ---------------------------------------------------------------------------

def cache_key(cik: str, kind: str, identifier: str) -> str:
    raw = f"{cik}|{kind}|{identifier}|{MODEL}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def load_saved(key: str, cache_dir: Path = CACHE_DIR) -> Answer | None:
    path = Path(cache_dir) / f"{key}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sources"] = [Source(**s) for s in data["sources"]]
    return Answer(**data)


def save(key: str, answer: Answer, cache_dir: Path = CACHE_DIR) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    data = asdict(answer)
    (Path(cache_dir) / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
