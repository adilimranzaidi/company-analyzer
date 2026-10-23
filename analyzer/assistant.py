"""The chat assistant: answers questions from SEC filing passages and the dashboard's own
figures, with citations, using Anthropic's Claude API.

How accuracy is protected
- Claude only receives text: filing passages, plus "Dashboard figures" that our Python code
  calculated, plus "How the dashboard works". It is told never to calculate.
- The Citations feature makes every cited claim point at an exact sentence in one of those
  documents; the API guarantees the quoted text really is in the document.
- If the documents don't answer the question, Claude is told to say so, not guess.
"""

import importlib
import sys
import threading
from dataclasses import dataclass, field

import pandas as pd

from analyzer.charts import format_pct, format_ratio, format_value
from analyzer.compare import snapshot, trailing_roe_latest
from analyzer.edgar_client import Company, pretty_company_name
from analyzer.filing_text import Passage
from analyzer.financials import MetricData
from analyzer.metrics import add_growth, unusual_changes

# Claude Haiku 5.5: the smallest current Claude model, chosen to keep questions to a
# fraction of a cent (Opus 5.5 was ~13 cents a question). The accuracy safeguards don't
# depend on the model: citations are still guaranteed to quote the documents.
MODEL = "claude-haiku-5-5"
EFFORT = "medium"            # Haiku's standard level: ~3 seconds faster than "high" (measured)
MAX_TOKENS = 16000
HISTORY_TURNS = 4            # earlier questions and answers sent for follow-up context
# Price per million tokens for Claude Haiku 5.5 (prompts up to 100K tokens), used only to
# show an estimated cost. Our prompts are about 15-25K tokens.
PRICE_IN, PRICE_OUT = 0.10, 0.50

SYSTEM_PROMPT = """You are the research assistant inside Company Analyzer, a dashboard about {name} ({ticker}). \
The person asking is learning finance for job interviews: explain in plain English and briefly define any jargon you use.

In each question you receive documents:
- passages from {ticker}'s SEC filings (titled with the filing and section): the best matches from a \
search of {searched},
- "Dashboard figures": numbers calculated by the dashboard's Python code from {ticker}'s SEC data,
- "How the dashboard works": the dashboard's methods and definitions,
- sometimes "News headlines": article titles from news outlets around a date. They are not company filings and \
are not verified: attribute them ("a headline from Reuters said ..."), and prefer the filings when both cover a point.

Rules:
1. Facts about {ticker} must come from these documents, cited. If the documents don't answer the question, \
say so plainly ("The filings I searched don't address ..."), mention what was searched, and suggest \
rephrasing (for example, naming the quarter or year). Never fill gaps from memory or guess.
2. Numbers: only state numbers that appear in the documents. Never calculate new figures (no growth rates, \
ratios, sums, differences or estimates). If a calculation would help, point to the dashboard section that shows it.
3. Periods: say exactly which period a number covers, as shown in the table's column headings. In 10-Qs, the \
cash-flow statement and many other tables cover the year to date (for example "six months ended June 30"), \
not the quarter alone. Never call a year-to-date figure a quarter's figure. If a table passage doesn't show \
its column headings, say the period isn't shown rather than guessing.
4. General finance concepts (for example, what return on equity means) may be explained from general knowledge. \
Start such a sentence with "In general," and keep it separate from claims about {ticker}.
5. No investment advice, price targets or predictions.
6. {length_rule}"""
CHAT_LENGTH = "Be concise: answer directly first, then up to five short bullet points if useful."

METHODS_GUIDE = """Company Analyzer: how the dashboard's figures are calculated.
All financial figures come from companies' XBRL-tagged SEC filings (10-K annual reports and 10-Q quarterly reports and their amendments). Numbers tagged in other documents, such as proxy statements or 8-K press releases, are ignored.
Each metric can be tagged under several EDGAR labels. The dashboard uses the label with the most recent data, preferring the first label in its list when two are equally recent, and shows which label it used.
When the same period was reported in several filings, the most recently filed value is used, because later filings include any revisions. The filing that first reported each number is also recorded, because that is where management discussed it at the time.
Quarterly figures are periods of 80 to 100 days; year-to-date totals in 10-Qs are excluded. Annual figures are periods of 350 to 380 days.
Companies do not file a separate fourth-quarter report, so Q4 is derived as the full-year figure minus Q1, Q2 and Q3, and is labelled as derived. Q4 is not derived for earnings per share, because per-share figures cannot be subtracted when the share count changes during the year.
Per-share figures are restated for stock splits: when the same period's figure was re-filed at an exact split ratio (for example 7-for-1), older figures are divided by that ratio and labelled.
A metric or table whose latest data is more than about 400 days behind the company's newest data is treated as no longer reported and is not charted.
For lenders that do not tag total revenue, revenue is calculated as net interest income plus noninterest income, and labelled as calculated. Net income uses the label NetIncomeLoss, or ProfitLoss when that is what the company reports; ProfitLoss includes any small share owned by minority (noncontrolling) investors.
Year-over-year growth compares a period with the same fiscal period a year earlier: (this period minus a year earlier) divided by a year earlier. Growth is shown as n/m (not meaningful) when the earlier figure is zero, negative or missing.
Margins divide a profit measure by revenue for the same period: gross margin uses gross profit, operating margin uses operating income, and net margin uses net income.
Return on equity (annual) is fiscal-year net income divided by the average of shareholders' equity at the start and end of the year. Return on equity in the quarterly view uses the last four quarters' net income divided by the average of equity now and four quarters earlier.
Unusual changes flag a period when its year-over-year change is far from the company's typical change for that metric: more than three typical deviations from the median change (using the median absolute deviation, which extreme years do not distort) and at least 10 percentage points away. Sensitivity can be set to high (2.5), medium (3) or low (4).
Industry peers are suggested from companies sharing the SEC industry (SIC) code, limited to listed companies and ranked by total assets; the user can edit the list. Industry figures use the median of the peers.
Headlines come from Finnhub, matched by stock ticker, and are not checked by the dashboard."""


# ---------------------------------------------------------------------------
# The "Dashboard figures" document (numbers from our Python code, as sentences)
# ---------------------------------------------------------------------------

def dashboard_figures(company: Company, metrics: dict[str, MetricData],
                      events: list | None = None) -> str:
    name = pretty_company_name(company.name)
    lines = [f"Dashboard figures for {name} ({company.ticker}), calculated by Company Analyzer's "
             "Python code from the company's SEC filings. Amounts are in US dollars."]
    for md in metrics.values():
        if not md.available:
            continue
        unit = md.metric.unit
        q = add_growth(md.quarterly, True)
        if not q.empty:
            r = q.iloc[-1]
            lines.append(f"{md.metric.name} for {r['period']} (quarter ending {r['end']}) was "
                         f"{format_value(r['value'], unit)}, {format_pct(r['yoy_growth'])} versus "
                         f"the same quarter a year earlier ({r['source'].lower()}; EDGAR label "
                         f"{md.choice.label}).")
        a = add_growth(md.annual, False)
        if not a.empty:
            r = a.iloc[-1]
            lines.append(f"{md.metric.name} for {r['period']} was {format_value(r['value'], unit)}, "
                         f"{format_pct(r['yoy_growth'])} versus the prior fiscal year.")
    snap = snapshot(metrics)
    for key, label in [("net_margin", "Net margin"), ("operating_margin", "Operating margin"),
                       ("roe", "Return on equity")]:
        if snap.get(key) is not None:
            lines.append(f"{label} for {snap['fiscal_year']} was {format_ratio(snap[key])}.")
    roe = trailing_roe_latest(metrics)
    if roe is not None:
        lines.append(f"Return on equity over the four quarters ending {roe['period']} was "
                     f"{format_ratio(roe['value'])}.")
    changes = unusual_changes(metrics, quarterly=True)
    if not changes.empty:
        lines.append("Unusual changes (quarters whose year-over-year change was unusual for this "
                     "company), most recent first:")
        for _, e in changes.head(10).iterrows():
            lines.append(f"{e['metric']} in {e['period']}: {format_value(e['value'], e['unit'])}, "
                         f"{format_pct(e['yoy_growth'])} versus a year earlier; the typical change "
                         f"is {format_pct(e['typical_growth'])}. First reported in the "
                         f"{e['orig_form']} filed {e['orig_filed']}.")
    if events:
        lines.append("Notable events, most recent first (from 8-K filings, and big one-day "
                     "stock moves calculated by the dashboard from daily prices):")
        for e in events[:20]:
            if e.category == "Stock move":
                lines.append(f"On {e.date}: {e.title}. {e.evidence}")
            else:
                detail = f" The 8-K says: {e.evidence}" if e.evidence else ""
                lines.append(f"On {e.date}, an 8-K reported: {e.title}.{detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Building the request and reading the answer
# ---------------------------------------------------------------------------

@dataclass
class Source:
    number: int
    title: str           # filing and section, or a dashboard document
    quote: str           # the exact cited text
    url: str = ""


@dataclass
class Answer:
    text: str                                   # markdown with [1]-style source markers
    sources: list[Source] = field(default_factory=list)
    cost: float = 0.0                           # estimated, in US dollars
    note: str = ""                              # e.g. a refusal, or the answer was cut off
    plain_text: str = ""                        # answer without markers, for follow-up context


def _document(title: str, text: str, context: str = "") -> dict:
    block = {"type": "document",
             "source": {"type": "text", "media_type": "text/plain", "data": text},
             "title": title[:250], "citations": {"enabled": True}}
    if context:
        block["context"] = context
    return block


def build_documents(passages: list[Passage], figures: str,
                    extra: list[tuple[str, str, str]] | None = None) -> tuple[list[dict], list[dict]]:
    """Request documents, plus what each one is (for turning citations into sources).
    extra: additional (title, text, url) documents, such as news headlines."""
    docs = [_document("Dashboard figures", figures,
                      "Numbers calculated by the dashboard's Python code."),
            _document("How the dashboard works", METHODS_GUIDE)]
    meta = [{"title": "Dashboard figures (calculated by this app)", "url": ""},
            {"title": "How the dashboard works", "url": ""}]
    for title, text, url in extra or []:
        docs.append(_document(title, text, "News headlines, not company filings."))
        meta.append({"title": title, "url": url})
    for p in passages:
        docs.append(_document(f"{p.filing}, {p.section}", p.text, f"From {p.filing}. Link: {p.url}"))
        meta.append({"title": f"{p.filing}, {p.section}", "url": p.url})
    return docs, meta


def parse_answer(content, meta: list[dict]) -> tuple[str, str, list[Source]]:
    """Join the answer's text blocks, adding [n] markers where citations are attached."""
    numbered: dict[tuple[int, str], Source] = {}
    marked, plain = [], []
    for block in content:
        if getattr(block, "type", "") != "text":
            continue
        marked.append(block.text)
        plain.append(block.text)
        refs = []
        for c in getattr(block, "citations", None) or []:
            idx = getattr(c, "document_index", None)
            quote = (getattr(c, "cited_text", "") or "").strip()
            if idx is None or idx >= len(meta):
                continue
            key = (idx, quote)
            if key not in numbered:
                numbered[key] = Source(len(numbered) + 1, meta[idx]["title"], quote, meta[idx]["url"])
            if numbered[key].number not in refs:
                refs.append(numbered[key].number)
        if refs:
            marked.append("".join(f" [{n}]" for n in refs))
    return "".join(marked).strip(), "".join(plain).strip(), list(numbered.values())


def _anthropic():
    """Anthropic's library, loaded on first use. It takes about 16 seconds to load on this
    computer (it has over 2,000 files), so the dashboard doesn't load it until it's needed."""
    return importlib.import_module("anthropic")


def warm_up() -> None:
    """Load Anthropic's library in the background, so it's ready before the first question
    without making the first page wait for it."""
    if "anthropic" not in sys.modules:
        threading.Thread(target=_anthropic, daemon=True).start()


def ask(api_key: str, company: Company, question: str, passages: list[Passage],
        figures: str, history: list[tuple[str, str]],
        searched: str = "the filings chosen in the dashboard", on_text=None,
        extra: list[tuple[str, str, str]] | None = None,
        length_rule: str = CHAT_LENGTH) -> Answer:
    client = _anthropic().Anthropic(api_key=api_key)
    docs, meta = build_documents(passages, figures, extra)
    messages = []
    for q, a in history[-HISTORY_TURNS:]:
        messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    messages.append({"role": "user", "content": docs + [{"type": "text", "text": question}]})

    # Streamed, so the answer's words can be shown as they're written (on_text) instead of
    # after a 10-second wait; the final message still carries every citation.
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT.format(name=pretty_company_name(company.name), ticker=company.ticker,
                                    searched=searched, length_rule=length_rule),
        messages=messages,
        output_config={"effort": EFFORT},
    ) as stream:
        for chunk in stream.text_stream:
            if on_text:
                on_text(chunk)
        response = stream.get_final_message()

    usage = response.usage
    cost = ((usage.input_tokens + (getattr(usage, "cache_creation_input_tokens", 0) or 0))
            * PRICE_IN + usage.output_tokens * PRICE_OUT) / 1_000_000
    if response.stop_reason == "refusal":
        return Answer("I can't answer that one. Safety checks occasionally decline harmless "
                      "questions; try rephrasing it as a question about the company's filings "
                      "or the dashboard's figures.", cost=cost,
                      note="The request was declined by Claude's safety checks.")
    text, plain, sources = parse_answer(response.content, meta)
    note = ""
    if response.stop_reason == "max_tokens":
        note = "The answer was cut off because it reached the length limit."
    return Answer(text or "(No answer was returned.)", sources, cost, note, plain)


# ---------------------------------------------------------------------------
# Today's industry update: current events from a web search, every point cited
# ---------------------------------------------------------------------------

# The basic web search tool: the newer version (with filtering) isn't available for Haiku.
WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 6}
SEARCH_PRICE = 0.01           # US$ per web search ($10 per 1,000)

UPDATE_PROMPT = """Today is {today}. Brief someone preparing for a finance job interview about {name} ({ticker}), which is in the {industry} industry ({sec_industry}).
Search the web for the most important events and trends of the last 30 days affecting this industry and company. Look into: {topics}.
You have 6 searches; plan them so none is wasted, roughly one each for: news about {name} this month; the biggest industry story; policy, trade and tariffs for this industry; the economy as it affects this industry; competitors at home and abroad; one more for the most important gap. Search using the name "{name}" (and the ticker {ticker}), which is how the news refers to the company.
Use exactly these Markdown headings, each followed by 2-4 short bullet points:
### What's moving the industry now
### Policy, trade and the economy
### Competitors, at home and abroad
### What it could mean for {name}
Rules:
1. Every fact must come from a search result and be cited. Say when each event happened.
2. Use numbers only as the sources report them. Never calculate, estimate or round figures yourself.
3. Mark forecasts and opinions as such ("analysts at X expect ...").
4. If sources disagree, say so. If you found nothing reliable for a heading, write "Nothing reliable found in this search."
5. Prefer established news outlets and official sources over press releases and blogs.
6. Under the last heading, connect the events to {name} only as far as the sources support; start any reasoning of your own with "In general,".
7. Plain English, no jargon without a short definition. No investment advice."""


def industry_update(api_key: str, company: Company, industry: str, sec_industry: str,
                    topics: str, today: str, on_text=None, common_name: str = "") -> Answer:
    """A cited briefing on current events in the company's industry, from a web search."""
    client = _anthropic().Anthropic(api_key=api_key)
    # The short brand name the news uses ("Exxonmobil", not "ExxonMobil Holdings Corp").
    prompt = UPDATE_PROMPT.format(today=today, name=common_name or pretty_company_name(company.name),
                                  ticker=company.ticker, industry=industry,
                                  sec_industry=sec_industry, topics=topics)
    messages = [{"role": "user", "content": prompt}]
    content, cost, stop = [], 0.0, None
    for _ in range(3):              # a long search can pause; resume it up to twice
        with client.messages.stream(model=MODEL, max_tokens=MAX_TOKENS, tools=[WEB_SEARCH],
                                    messages=messages, output_config={"effort": EFFORT}) as stream:
            for chunk in stream.text_stream:
                if on_text:
                    on_text(chunk)
            response = stream.get_final_message()
        usage = response.usage
        searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
        cost += (usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT) / 1_000_000 \
            + searches * SEARCH_PRICE
        content += list(response.content)
        stop = response.stop_reason
        if stop != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": response.content}]
    if stop == "refusal":
        return Answer("The update couldn't be written: the request was declined by Claude's "
                      "safety checks. Try again later.", cost=cost)
    text, plain, sources = parse_web_answer(content)
    note = "The update was cut off at the length limit." if stop == "max_tokens" else ""
    return Answer(text or "(No update was returned.)", sources, cost, note, plain)


def parse_web_answer(content) -> tuple[str, str, list[Source]]:
    """Join the text, adding [n] after each cited passage; one numbered source per web page."""
    numbered: dict[str, Source] = {}
    marked, plain = [], []
    for block in content:
        if getattr(block, "type", "") != "text":
            continue
        marked.append(block.text)
        plain.append(block.text)
        refs = []
        for c in getattr(block, "citations", None) or []:
            if getattr(c, "type", "") != "web_search_result_location":
                continue
            if c.url not in numbered:
                numbered[c.url] = Source(len(numbered) + 1, c.title or c.url,
                                         c.cited_text or "", c.url)
            if numbered[c.url].number not in refs:
                refs.append(numbered[c.url].number)
        if refs:
            marked.append("".join(f" [{n}]" for n in refs))
    return "".join(marked).strip(), "".join(plain).strip(), list(numbered.values())


def search_query(question: str, history: list[tuple[str, str]]) -> str:
    """Follow-ups like "why?" need the previous question's words to find passages."""
    previous = history[-1][0] if history else ""
    return f"{question} {previous}".strip()


def friendly_error(err: Exception) -> str:
    anthropic = sys.modules.get("anthropic")
    if anthropic is None:                 # the error came before the library was loaded
        return f"Something went wrong: {err}"
    if isinstance(err, anthropic.AuthenticationError):
        return "The Anthropic API key wasn't accepted. Check ANTHROPIC_API_KEY in .streamlit/secrets.toml."
    if isinstance(err, anthropic.PermissionDeniedError):
        return "The Anthropic API key doesn't have permission for this model."
    if isinstance(err, anthropic.RateLimitError):
        return "Too many requests to the Anthropic API right now. Wait a minute and try again."
    if isinstance(err, anthropic.BadRequestError):
        message = str(getattr(err, "message", err))
        if "credit" in message.lower() or "balance" in message.lower():
            return "Your Anthropic account is out of credit. Add credit in the Console under Billing."
        return f"The Anthropic API rejected the request: {message[:200]}"
    if isinstance(err, anthropic.APIConnectionError):
        return "Couldn't reach the Anthropic API. Check your internet connection."
    if isinstance(err, anthropic.APIStatusError):
        return f"The Anthropic API returned an error ({err.status_code}). Try again shortly."
    return f"Something went wrong: {err}"


def passages_table(passages: list[Passage]) -> pd.DataFrame:
    return pd.DataFrame([{"Filing": p.filing, "Section": p.section,
                          "Words": len(p.text.split())} for p in passages])
