# Build Log

A running record of what was built, what broke, and how it was fixed.

---

## Step 0: Project setup (2026-10-17)

**What we did**
- Chose the project location `C:\Users\hrzai\Documents\company-analyzer`, outside OneDrive.
  Syncing tools and coding projects clash: thousands of small, changing files, plus Git's
  history. GitHub serves as the backup instead.
- Created a virtual environment (`.venv`), a private package folder for this project only,
  and installed streamlit, requests, pandas, plotly, beautifulsoup4, anthropic and pytest.
  Exact versions are pinned in `requirements.txt` so the project installs the same way later.
- Started Git with a `.gitignore` written **before** the first commit, so the secrets file,
  downloaded data and `.venv` can never be uploaded by accident.
- Set this project's commit email to the GitHub "noreply" address, so commits link to the
  GitHub profile without publishing a personal email.
- Stored the SEC contact (User-Agent) and the Anthropic API key in `.streamlit/secrets.toml`
  (private), with a blank `secrets.toml.example` template for anyone cloning the repo.
- Built a starter `app.py` that confirms each secret is present **without displaying it**.
- Chose Claude Opus 5.5 for the question box: accuracy and careful citation matter more than
  the per-question cost for a personal tool.

**What broke / how we fixed it**
- **API key format confusion.** The Console's default key type ("linked to your account")
  starts with `sk-ant-usr-`, not the older `sk-ant-api` style. Both are valid; we confirmed
  the key with a free "list models" request. The first key was accidentally pasted into a
  chat, so it was deleted and replaced. Rule: keys go only in `secrets.toml`.
- **First GitHub push failed** ("Invalid username or token"). Git's sign-in window can't
  open from a background process. Fix: run `git push` in a visible terminal so the GitHub
  browser sign-in can appear.

---

## Step 1: Ticker lookup (2026-10-17)

**What we did**
- Added `analyzer/edgar_client.py`, the only file that contacts the SEC. It:
  - converts a ticker to the SEC's company ID (CIK) using the SEC's official ticker list
  - fetches the company's "submissions" record for industry, exchange, fiscal year end
    and filer category
  - sends the User-Agent on every request, waits 0.15s between requests (the SEC allows
    10 per second), and saves downloads to `data/cache/` (ticker list refreshed daily,
    company records every 6 hours)
  - turns technical failures (no internet, SEC refusal, unknown ticker) into plain-English
    messages
- The dashboard now has a ticker box (default AXP) and a company card.
- Added 15 automated tests (`tests/test_edgar_client.py`) that run without internet.

**Things learned about EDGAR**
- The SEC writes share classes with a dash (`BRK-B`), so the app converts `BRK.B` to `BRK-B`.
- CIKs must be padded to 10 digits in SEC web addresses (`4962` → `0000004962`).
- The SEC classifies AmEx as "Finance Services" (SIC 6199). We'll use this code later to
  decide which metrics to highlight for banks versus other companies.

**What broke / how we fixed it**
- **Berkshire showed "NYSE, NYSE".** The SEC lists the exchange once per share class.
  Fix: remove repeats while keeping the order.

---

## Step 2: Key financials and charts (2026-10-17)

**What we did**
- `analyzer/financials.py` turns the SEC's "company facts" (every XBRL-tagged number)
  into clean annual and quarterly tables for 10 metrics: revenue, net income, diluted EPS,
  gross profit, operating income, net interest income, provision for credit losses, total
  assets, shareholders' equity, and cash.
- `analyzer/charts.py` draws one bar chart per metric. Derived Q4 bars are a lighter blue
  with their own legend entry, and hovering shows the source filing.
- The dashboard has a Quarterly/Annual switch, a years-of-history slider, a summary table
  (latest values and the EDGAR label used), a data table under each chart, and a
  "Not shown" list explaining every missing metric.
- Added 18 tests for the data-cleaning rules (33 total).
- Checked against published results: AXP FY2024 revenue $65.9B, net income $10.1B, diluted
  EPS $14.01; Apple FY2024 revenue $391.0B, net income $93.7B. All match.

**The data-cleaning rules (and why)**
1. **Label choice: most recent data wins.** AmEx has a "Revenues" label whose data stops
   in 2010, and a current `RevenuesNetOfInterestExpense`. "First label that exists" would
   have charted 2010 data. Ties go to the preferred label, because AmEx's current
   `RevenueFromContractWithCustomer...` covers only part of its revenue (mostly card fees).
2. **Only true quarters.** A Q2 10-Q also reports the 6-month total. We keep periods of
   80-100 days as quarters and 350-380 days as years.
3. **Latest filing wins.** The same quarter appears in several filings; the newest one
   carries any revisions.
4. **Q4 is derived** as Full year − Q1 − Q2 − Q3, labelled "Derived" everywhere it appears.
   It's skipped if any quarter is missing, or if the company reported Q4 directly.
5. **No Q4 EPS.** EPS can't be subtracted, because the share count changes during the year.
6. **Fiscal labels** come from the company's fiscal year end (Apple's Q1 FY2026 ends in
   December 2025).

**What broke / how we fixed it**
- **AmEx "operating income" showed data from 2007-2010** as if it were current. Fix: a
  metric whose latest data is more than ~400 days behind the company's newest data is
  marked "no longer reported" and kept off the charts.
- **The credit-loss label changed in 2020** (`ProvisionForLoanLeaseAndOtherLosses` →
  `ProvisionForLoanLossesExpensed`). The most-recent rule handles it, and the old label
  is listed under "not used".
- **AmEx has no plain cash label** after 2023, only cash *including restricted cash*. We
  use it and show the label so the difference is visible.
- **"AttributeError" crash after adding a new field:** the running dashboard had the old
  code in memory. Fix: restart the dashboard after changing files in `analyzer/`.
- **Company facts cut off ("00000...")** on narrow screens. Fix: plain text instead of
  Streamlit's big-number boxes.
- **Plotly labelled billions as "G"** (giga). Fix: we scale the axis ourselves and add "B".

---

## Roadmap decisions (2026-10-17)

- **Notable events** (new): Python flags unusually large changes; Claude explains each one
  from the matching filing's MD&A, with citations, only when asked (cached after the
  first time). Detection is in Step 3; explanations are Step 5b, because they reuse the
  question box's filing reader.
- **Company synopsis tab** (new, Step 5c): built from the 10-K business section, the latest
  10-Q, recent 8-Ks and risk factors. Numbers shown come from our code; the AI's text is cited.
- **Macro layer moved to Version 2.** Headlines come from feeds and APIs (GDELT, RSS, news
  APIs, Claude web search), **not** scraping. Scraping breaks site terms, hits paywalls, is
  fragile, and can't provide the dated history a predictive model needs.
- **Predictive model is Version 3.** It must be backtested (trained on older years, tested
  on later ones) and shown as probabilities with drivers. Criteria to be set together.
- **Open-source libraries** (fredapi, gdeltdoc, feedparser) will be used for the new
  layers after checking each one. We keep our own EDGAR code, because it enforces this
  project's accuracy rules and is fully tested.

---

## Step 3: Growth, margins, ROE and notable events (2026-10-17)

**What we did**
- `analyzer/metrics.py` holds every calculation: year-over-year and quarter-over-quarter
  growth, gross/operating/net margins, and return on equity (annual, plus trailing 12
  months in the quarterly view). Periods are matched by fiscal label, never by row
  position, so a missing quarter gives a blank rather than a wrong comparison.
- Growth from a zero or negative starting point shows "n/m" (not meaningful).
- Gross profit is **calculated** (revenue − cost of revenue) for companies that report
  both but not gross profit, and labelled as calculated.
- **Notable events:** a period is flagged when its year-over-year change is far from the
  company's own typical change: more than 3 "typical deviations" (median absolute
  deviation, which isn't distorted by a few extreme years) **and** at least 10 percentage
  points. A High/Medium/Low sensitivity setting adjusts this.
- The dashboard now has three tabs: Financials, Growth & margins, Notable events. Flagged
  periods get an orange diamond (with a legend label) on the Financials charts.
- Added `.streamlit/config.toml`: the dashboard is reachable only from this computer
  (it was visible to the local network), and Streamlit's usage statistics are off.
- 26 new tests (59 total). Checked: AXP FY2024 net margin 15.4% and ROE ~35%; Apple FY2024
  gross margin 46.2%. All match published figures.

**What broke / how we fixed it**
- **Stock splits made Apple's EPS look like it fell 86% in 2013.** After Apple's 7-for-1
  (2014) and 4-for-1 (2020) splits, re-filed periods were restated but older ones weren't,
  so the history mixed two share bases. Fix: detect splits from the data itself (the same
  period filed twice, differing by an exact split ratio), then restate older per-share
  figures and label them "Adjusted for 7-for-1 stock split". Apple's FY2012 EPS now reads
  $1.58, its published split-adjusted figure.
- **A false "3-for-2 split" in 2009.** Apple restated 2009 for an accounting change, and
  one figure happened to land on a 1.5 ratio. Fix: require at least 3 periods to agree
  (Apple's real splits have 8-11 each).
- **Events pointed to the wrong filing for explanations.** We keep the latest filing of
  each number, which is often next year's comparison column. Fix: also track the filing
  that *first* reported each number. Step 5b will read that one, because that's where
  management explained it at the time.
- **Two test mistakes (not app bugs):** a missing growth value is NaN rather than None, and
  one test spike was smaller than the 10-point minimum on purpose. Fixed the tests.
- **My browser pane can't reach the dashboard** now that it's local-only. Checked the app
  with Streamlit's built-in test runner instead (AXP, AAPL, JPM; quarterly and annual; no
  errors). The visual check of the charts is left to the person running it.
