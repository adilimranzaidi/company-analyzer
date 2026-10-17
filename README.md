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
3. Growth rates, margins, and return on equity calculated in Python, plus automatic
   flagging of unusual changes ("notable events")
4. Links to the latest 10-K (annual), 10-Q (quarterly) and 8-K (current event) filings
5. A question box answered from the filings themselves, with citations
   - 5b. "Explain from filing": management's own explanation of each notable event, cited
   - 5c. Company synopsis: what the company does, its latest quarter, recent 8-K events,
     key risks and interview talking points, all cited

**Version 2: macro layer and segments**
- Macro data from FRED (interest rates, oil, consumer credit, card delinquencies)
- The company's own disclosed sensitivity to those factors (10-K Item 7A and risk factors)
- Headlines from feeds and APIs (GDELT, RSS, news APIs), not website scraping
- Business segment breakdowns pulled from the filings

**Version 3: predictive model**
- Direction of a company or industry from macro trends and fundamentals, backtested on
  past data, shown as probabilities with their main drivers (criteria to be defined)

## Data sources

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  (free, public)
- [Anthropic Claude API](https://docs.anthropic.com/) for the question box

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

Then start the dashboard:

```bash
streamlit run app.py
```

## Project layout

```
app.py                 the dashboard page (layout only)
analyzer/              data fetching, cleaning, math, and AI Q&A (added step by step)
tests/                 automated checks for the calculations
.streamlit/            settings and private secrets (secrets are never uploaded)
BUILD_LOG.md           what was built, what broke, and how it was fixed
```
