# Company Analyzer

A web dashboard for understanding a public company's financial position, built with
Python and Streamlit. It starts with American Express (AXP) and works for any company
that files with the U.S. Securities and Exchange Commission (SEC).

> **Status:** in development. See [BUILD_LOG.md](BUILD_LOG.md) for progress.

## The core rule: code does the numbers, AI does the words

- **Every number** (revenue, net income, EPS, growth rates, margins) comes straight from
  the SEC's structured XBRL data and is calculated in plain, tested Python.
- **The AI (Anthropic's Claude)** is used only to read filing text and answer questions,
  and it must cite the filing and section behind each point. If the filings don't answer
  a question, it says so instead of guessing. It never sees or calculates the financials.

## Roadmap

**Version 1 (in progress)**
1. ✅ Ticker input (defaults to AXP)
2. ✅ Key financials from SEC EDGAR, with quarterly and annual charts. The exact EDGAR
   label used for each metric is shown on screen.
3. ✅ Growth rates, margins, and return on equity calculated in Python, plus automatic
   flagging of unusual changes ("notable events")
3b. ✅ Redesign: EB Garamond theme; calm Overview with charts on request; search by
   company name or ticker; Industry section (editable peer group, peer medians, ranking);
   Compare up to five companies; Headlines from Finnhub
4. ✅ Filings list: latest 10-K, 10-Q and 8-K filings with links, and 8-K event types in
   plain English
5. ✅ Ask: a chat assistant that answers from the filings and the dashboard's own figures,
   with numbered, quoted sources (Claude Haiku 5.5 with the Citations feature)
   - 5b. ✅ "Explain from filing": management's own explanation of each unusual change and
     notable event, from the filing that covers it (including 8-K press releases), cited
   - 5c. Company synopsis: what the company does, its latest quarter, recent 8-K events,
     key risks and interview talking points, all cited

**Version 2: macro layer and segments**
- Macro data from FRED (interest rates, oil, consumer credit, card delinquencies)
- The company's own disclosed sensitivity to those factors (10-K Item 7A and risk factors)
- Historical news from GDELT's bulk data files (for the Version 3 model), not website scraping
- Business segment breakdowns pulled from the filings

**Version 3: predictive model**
- Direction of a company or industry from macro trends and fundamentals, backtested on
  past data, shown as probabilities with their main drivers (criteria to be defined)

## Running it yourself

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate          # on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in:
- `SEC_USER_AGENT`: your name and email (the SEC requires this on every request)
- `ANTHROPIC_API_KEY`: your key from the Anthropic Console
- `FINNHUB_API_KEY`: a free key from finnhub.io (for headlines)
- `TIINGO_API_KEY`: a free token from tiingo.com (for daily stock prices)

Then start the dashboard:

```bash
streamlit run app.py
```

On Windows you can also double-click `start_dashboard.bat`, which starts the dashboard and
opens it at http://127.0.0.1:8501. Keep its window open while you use the dashboard.

## Checking the code

```bash
pip install -r requirements-dev.txt
python -m pytest          # automated tests
ruff check .              # linter (settings in ruff.toml)
```

## Project layout

```
app.py                 the page frame: search, company header, section menu
ui/                    one file per section (Overview, Company trends, Industry,
                       Compare, Headlines, Filings, Ask); layout only
analyzer/              all data and math: SEC client, data cleaning, metrics,
                       peers, comparisons, headlines, filing reader, search, assistant
tests/                 automated checks for every calculation and cleaning rule
.streamlit/            theme (EB Garamond) and settings; private secrets (never uploaded)
BUILD_LOG.md           what was built, what broke, and how it was fixed
```

## Data sources

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces):
  company facts (XBRL), submissions, industry lists, and "frames" (one figure for every company)
- [Finnhub](https://finnhub.io/): company news by ticker, for headlines (free key)
- [Tiingo](https://www.tiingo.com/): daily stock prices, for big-move detection (free key)
- [Anthropic Claude API](https://docs.anthropic.com/): the Ask assistant (Claude Haiku 5.5, Citations)
