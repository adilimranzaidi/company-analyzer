"""The assistant's three jobs for the web dashboard: the company briefing, "explain this"
for unusual changes and events, and the chat. Same rules as before: answers come only
from the filings and the dashboard's own figures, with sources; the AI never calculates.

Each job reports progress through send(kind, **data):
  status  -> a short line for the page ("Reading the 10-K…")
  text    -> the answer's words as they're written
  answer  -> the final answer with its numbered sources (and whether it was saved)
"""

from dataclasses import asdict
from datetime import date, timedelta

from analyzer.assistant import (
    ask,
    dashboard_figures,
    friendly_error,
    industry_update,
    search_query,
)
from analyzer.charts import format_pct
from analyzer.explain import (
    cache_key,
    change_question,
    event_question,
    filings_for_change,
    filings_for_event,
    filings_for_stock_move,
    headlines_document,
    load_saved,
    save,
)
from analyzer.filings import latest_reports
from analyzer.financials import fiscal_period
from analyzer.metrics import unusual_changes
from analyzer.peers import brand_name
from analyzer.search import choose_filings
from analyzer.synopsis import LENGTH_RULE, REQUEST, identifier, pick_passages
from webapp import service


def friendly(err: Exception) -> str:
    return friendly_error(err)


def _key() -> str:
    key = service.secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Add ANTHROPIC_API_KEY to .streamlit/secrets.toml to use the assistant.")
    return key


def _answer_json(answer, saved: bool) -> dict:
    data = asdict(answer)
    data["saved"] = saved
    return data


def _figures(ticker: str) -> str:
    co, metrics = service.company(ticker), service.metrics(ticker)
    return dashboard_figures(co, metrics, service.all_events(ticker)[0])


# ---------------------------------------------------------------------------
# Company briefing
# ---------------------------------------------------------------------------

def _briefing_sources(ticker: str):
    reports = latest_reports(service.filings(ticker))
    annual, quarterly = reports.annual, reports.quarterly
    if not annual:
        return None, None, None
    recent = quarterly if quarterly and quarterly["filed"] > annual["filed"] else annual
    co = service.company(ticker)
    key = cache_key(co.cik, "synopsis", identifier(annual["accession"], recent["accession"]))
    return annual, recent, key


def briefing_status(ticker: str) -> dict:
    annual, recent, key = _briefing_sources(ticker)
    if not annual:
        return {"available": False, "reason": "No annual report (10-K) was found."}
    based_on = f"{annual['form']} filed {annual['filed']:%b %d, %Y}" + (
        f" and {recent['form']} filed {recent['filed']:%b %d, %Y}" if recent is not annual else "")
    saved = load_saved(key)
    return {"available": True, "based_on": based_on,
            "answer": _answer_json(saved, True) if saved else None,
            "can_write": bool(service.secret("ANTHROPIC_API_KEY"))}


def write_briefing(ticker: str, send) -> None:
    annual, recent, key = _briefing_sources(ticker)
    if not annual:
        send("error", message="No annual report (10-K) was found, so a briefing can't be written.")
        return
    saved = load_saved(key)
    if saved:
        send("answer", answer=_answer_json(saved, True))
        return
    send("status", message=f"Reading the {annual['form']} and the latest report…")
    rows = [annual] if recent is annual else [annual, recent]
    groups = [service.row_passages(r) for r in rows]
    annual_p = groups[0]
    recent_p = annual_p if recent is annual else groups[1]
    co = service.company(ticker)
    searched = f"the {annual['form']} filed {annual['filed']:%b %Y}" + (
        f" and the {recent['form']} filed {recent['filed']:%b %Y}" if recent is not annual else "")
    send("status", message="Writing the briefing…")
    answer = ask(_key(), co, REQUEST.format(name=co.name), pick_passages(annual_p, recent_p),
                 _figures(ticker), [], searched=searched, length_rule=LENGTH_RULE,
                 on_text=lambda chunk: send("text", chunk=chunk))
    save(key, answer)
    send("answer", answer=_answer_json(answer, False))


# ---------------------------------------------------------------------------
# Explain an unusual change or an event
# ---------------------------------------------------------------------------

def _explain_job(ticker: str, kind: str, ident: str):
    """(question, filing rows, extra documents) for a change or an event."""
    table = service.filings(ticker)
    if kind == "change":
        metric_key, period = ident.split("|", 1)
        metrics = service.metrics(ticker)
        for quarterly in (True, False):
            changes = unusual_changes(metrics, quarterly)
            hit = changes[(changes["metric_key"] == metric_key) & (changes["period"] == period)]
            if not hit.empty:
                r = hit.iloc[0]
                return (change_question(r["metric"], r["period"], format_pct(r["yoy_growth"])),
                        filings_for_change(table, r["orig_accn"]), None)
        raise LookupError("That change is no longer flagged.")
    day_s, category, title = ident.split("|", 2)
    day = date.fromisoformat(day_s)
    event = next((e for e in service.all_events(ticker)[0]
                  if e.date == day and e.category == category and e.title == title), None)
    if event is None:
        raise LookupError("That event wasn't found.")
    if category == "Stock move":
        articles, _ = service.headlines_around(ticker, day)
        extra = [headlines_document(articles, ticker, day)] if articles else None
        return event_question(title, day), filings_for_stock_move(table, day), extra
    question = event_question(title, day, event.evidence)
    return question, filings_for_event(table, event.url, day), None


def explain_status(ticker: str, kind: str, ident: str) -> dict:
    saved = load_saved(cache_key(service.company(ticker).cik, kind, ident))
    return {"answer": _answer_json(saved, True) if saved else None,
            "can_write": bool(service.secret("ANTHROPIC_API_KEY"))}


def explain(ticker: str, kind: str, ident: str, send) -> None:
    co = service.company(ticker)
    key = cache_key(co.cik, kind, ident)
    saved = load_saved(key)
    if saved:
        send("answer", answer=_answer_json(saved, True))
        return
    question, rows, extra = _explain_job(ticker, kind, ident)
    if not rows:
        send("error", message="No filing covering this period is in the SEC's recent list.")
        return
    send("status", message=f"Reading {len(rows)} filing{'s' if len(rows) > 1 else ''}…")
    searcher = service.filing_search(ticker, rows)
    send("status", message="Asking the assistant…")
    answer = ask(_key(), co, question, searcher.search(question, k=14), _figures(ticker), [],
                 searched=searcher.coverage(), extra=extra,
                 on_text=lambda chunk: send("text", chunk=chunk))
    save(key, answer)
    send("answer", answer=_answer_json(answer, False))


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def reports_for(ticker: str) -> list[dict]:
    table = service.filings(ticker)
    return table[table["form"].isin(["10-K", "10-Q", "20-F", "40-F"])].to_dict("records")


def prefetch_for_chat(ticker: str) -> None:
    """Start reading the filings a first question usually needs."""
    fye = service.company(ticker).fiscal_year_end_month
    service.prefetch(choose_filings(reports_for(ticker), "", lambda d: fiscal_period(d, fye)))


def ask_question(ticker: str, question: str, history: list[tuple[str, str]], send) -> None:
    co = service.company(ticker)
    rows = reports_for(ticker)
    if not rows:
        send("error", message="No 10-K or 10-Q filings are available to read.")
        return
    fye = co.fiscal_year_end_month
    query = search_query(question, history)
    to_read = choose_filings(rows, query, lambda d: fiscal_period(d, fye))
    send("status", message=f"Reading {len(to_read)} filings (saved after the first time)…")
    searcher = service.filing_search(ticker, to_read)
    send("status", message="Thinking…")
    answer = ask(_key(), co, question, searcher.search(query), _figures(ticker), history,
                 searched=searcher.coverage(), on_text=lambda chunk: send("text", chunk=chunk))
    send("answer", answer=_answer_json(answer, False))


# ---------------------------------------------------------------------------
# Industry drivers, in the company's own words (latest 10-K)
# ---------------------------------------------------------------------------

DRIVERS_REQUEST = """Which outside forces drive {name}'s results, according to its latest 10-K?
Use one Markdown heading per driver ("### " and a short plain-English name), 4 to 6 drivers, most important first. Under each heading, 2-3 short bullet points:
- how it affects revenue, costs or profit, and in which direction;
- what the company says about it now (for example a price level, a policy, a competitor).
Only outside forces: prices, demand, interest rates, regulation, trade and tariffs, competition, geopolitics, technology, weather. Not the company's own decisions.
Use only the 10-K passages and cite every point. If the 10-K doesn't cover something, leave it out rather than guess."""

DRIVERS_LENGTH = "Be compact: the requested headings with 2-3 short bullet points each."
DRIVER_WORDS = ("prices demand competition regulation tariffs trade interest rates economic "
                "conditions geopolitical supply market risk factors affect results")


def _drivers_sources(ticker: str):
    annual = latest_reports(service.filings(ticker)).annual
    if not annual:
        return None, None
    return annual, cache_key(service.company(ticker).cik, "drivers", annual["accession"])


def drivers_status(ticker: str) -> dict:
    annual, key = _drivers_sources(ticker)
    if not annual:
        return {"available": False, "reason": "No annual report (10-K) was found."}
    saved = load_saved(key)
    return {"available": True, "based_on": f"{annual['form']} filed {annual['filed']:%b %d, %Y}",
            "answer": _answer_json(saved, True) if saved else None,
            "can_write": bool(service.secret("ANTHROPIC_API_KEY"))}


def _driver_passages(passages: list) -> list:
    """The parts of a 10-K that discuss outside forces: risk factors (1A), market risk (7A),
    management's discussion (7) and the business overview (1)."""
    from analyzer.search import BM25
    from analyzer.synopsis import in_item
    chosen = []
    for item, k in (("1A", 6), ("7A", 3), ("7", 5), ("1", 3)):
        pool = [p for p in passages if in_item(p.section, item)]
        if pool:
            scores = BM25([f"{p.section}\n{p.text}" for p in pool]).scores(DRIVER_WORDS)
            best = sorted(range(len(pool)), key=lambda i: scores[i], reverse=True)[:k]
            chosen += [pool[i] for i in sorted(best)]
    return chosen


def write_drivers(ticker: str, send) -> None:
    annual, key = _drivers_sources(ticker)
    if not annual:
        send("error", message="No annual report (10-K) was found.")
        return
    saved = load_saved(key)
    if saved:
        send("answer", answer=_answer_json(saved, True))
        return
    send("status", message=f"Reading the {annual['form']}…")
    co = service.company(ticker)
    passages = _driver_passages(service.row_passages(annual))
    send("status", message="Finding the drivers…")
    answer = ask(_key(), co, DRIVERS_REQUEST.format(name=co.name), passages, _figures(ticker), [],
                 searched=f"the {annual['form']} filed {annual['filed']:%b %Y}",
                 length_rule=DRIVERS_LENGTH, on_text=lambda chunk: send("text", chunk=chunk))
    save(key, answer)
    send("answer", answer=_answer_json(answer, False))


# ---------------------------------------------------------------------------
# Today's industry update (web search), saved for the day
# ---------------------------------------------------------------------------

def _update_key(ticker: str, day: date) -> str:
    return cache_key(service.company(ticker).cik, "industry_update", day.isoformat())


def update_status(ticker: str) -> dict:
    """Today's update if written; otherwise the most recent one from the last two weeks."""
    today = date.today()
    for back in range(15):
        day = today - timedelta(days=back)
        saved = load_saved(_update_key(ticker, day))
        if saved:
            return {"answer": _answer_json(saved, True), "date": day.isoformat(),
                    "is_today": back == 0, "can_write": bool(service.secret("ANTHROPIC_API_KEY"))}
    return {"answer": None, "date": None, "is_today": False,
            "can_write": bool(service.secret("ANTHROPIC_API_KEY"))}


def write_update(ticker: str, send) -> None:
    from webapp.payloads import industry_payload
    today = date.today()
    key = _update_key(ticker, today)
    saved = load_saved(key)
    if saved:
        send("answer", answer=_answer_json(saved, True))
        return
    ind = industry_payload(ticker)
    send("status", message="Searching the news…")
    answer = industry_update(_key(), service.company(ticker), ind["industry"],
                             ind["sec_industry"], ind["topics"], f"{today:%B %d, %Y}",
                             on_text=lambda chunk: send("text", chunk=chunk),
                             common_name=brand_name(service.company(ticker).name))
    if answer.sources:              # an update with no sources isn't worth keeping
        save(key, answer)
    send("answer", answer=_answer_json(answer, False))
