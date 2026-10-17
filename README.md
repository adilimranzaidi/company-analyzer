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

## Planned features (Version 1)

1. Ticker input (defaults to AXP)
2. Key financials from SEC EDGAR, with quarterly and annual charts. The exact EDGAR label
   used for each metric is shown on screen.
3. Growth rates and margins calculated in Python
4. Links to the latest 10-K (annual) and 10-Q (quarterly) filings
5. A question box answered from the filings themselves, with citations

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
