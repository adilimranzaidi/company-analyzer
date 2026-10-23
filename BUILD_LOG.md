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

---

## Step 3b: Redesign, search, industry, compare and headlines (2026-10-17)

**What we did**
- **Look:** EB Garamond (a free, faithful version of the classic Garamond typeface) on a
  warm off-white background, set in `.streamlit/config.toml`. Charts use the same font,
  Plotly's hover toolbar is hidden, and heading link icons are off.
- **Layout:** one section menu (Overview, Company trends, Industry, Compare, Headlines,
  Filings and Q&A) instead of everything on one page. Only the chosen section loads.
  The page code moved into `ui/` (one file per section); `app.py` is only the frame.
- **Overview:** four key figures with year-over-year change, the latest notable events,
  and charts only when "Show key charts" is switched on. Synopsis placeholder (Step 5c).
- **Company trends:** one chart at a time from a dropdown, with "Show all charts".
- **Search by name or ticker** across all ~10,400 SEC tickers. SEC names are tidied for
  display ("AMERICAN EXPRESS CO /DE/" → "American Express Co").
- **Industry:** peers suggested from the SEC industry (SIC) list, kept to listed
  companies, ranked by total assets using the SEC "frames" data (everyone's figure in one
  download). The list is editable. Shows a snapshot table, peer medians, where the
  company ranks, and a company-vs-peer-median trend chart. Drivers placeholder (Step 5 / V2).
- **Compare:** up to five companies side by side, plus growth and ratio charts (growth
  rather than dollars, so different-sized companies fit on one chart).
- **Headlines:** company or peer news from the GDELT API, as links, cached for an hour.
- 21 new tests (81 total). Every section checked headlessly for AXP, SYF, MSFT, JPM, AAPL;
  Overview, Industry and Compare also checked visually.

**What broke / how we fixed it**
- **Synchrony had no revenue.** It never tags a total-revenue figure, only net interest
  income and noninterest income. Fix: for lenders without a revenue label, calculate
  revenue as the sum of those two (the standard bank definition, and how AmEx's reported
  revenue is built), labelled "Calculated". Never replaces a reported figure (tested).
- **"US Bancorp de":** the SEC sometimes writes state tags with backslashes (`\DE\`).
  Names now drop both `/DE/` and `\DE\`.
- **SEC industry codes are broad:** AmEx's code (6199, finance services) suggests crypto
  firms (Coinbase, Circle, Strategy) alongside Synchrony. Expected; that's why the peer
  list is editable.
- **GDELT rate-limits this network** ("one request every 5 seconds") even on the first
  request; probably a shared internet address. The app paces requests, caches results for
  an hour, and shows a "try again" message instead of failing. If it stays blocked, the
  fallbacks are Finnhub or Claude web search.
- **JPMorgan Q2 2026 revenue +27.7%** looked like a bug but matches JPM's 10-Q ($57.35B vs
  $44.91B), likely a one-time item, as in Q2 2024 (Visa share gain). Flagged by notable
  events; Step 5b will explain it from the filing.
- **Font looked wrong in the first screenshot:** EB Garamond was still downloading.
- **Visual check:** the browser pane can't reach the local-only dashboard, so a temporary
  copy ran on port 8502 for screenshots, then was shut down.
- **Industry is slow the first time** (MSFT: ~35s, since its industry list is ~15 pages
  and each peer's data downloads once); after that it's cached.

---

## Fix: Mastercard's net income stuck in 2014 (2026-10-17)

**Reported by:** testing the dashboard. Mastercard's latest net income showed as Q1 FY2014.

**Cause 1: non-financial-statement documents were counted.** The SEC's data includes
numbers tagged in proxy statements (DEF 14A) and 8-K press releases. Since 2022, proxies
tag five years of net income for executive-pay tables. Mastercard's proxy used
`NetIncomeLoss`, so that label looked current, but its 10-Ks and 10-Qs switched to
`ProfitLoss` in 2014, leaving quarterly figures that ended in 2014.
**Fix:** only figures from periodic reports count (10-K, 10-Q, their amendments, and the
foreign equivalents 20-F and 40-F). About 12,900 cached rows from other documents are now ignored.

**Cause 2: net income had only one label.** Added `ProfitLoss` as a fallback
(`NetIncomeLoss` stays preferred when both are current). For Mastercard it matches the
company's own reported net income exactly ($14.968B for 2025); Caterpillar also uses it.

**Cause 3: staleness was checked per metric, not per table.** A label can stay current in
10-Ks but stop in 10-Qs (Citigroup's credit provisions: quarterly tags stop after 2022).
**Fix:** a quarterly or annual table more than ~400 days behind the company's newest data
is hidden, with a note explaining why, instead of showing old figures as the latest.

**Checked:** scanned 40 large companies across industries. No stale tables remain;
Citigroup and Boeing (credit provisions) show the note. Also found that Visa and Berkshire
Hathaway tag EPS separately for each share class, so no single EPS exists; the app now
says so instead of a plain "not reported". 3 new tests (84 total).

---

## Headlines: GDELT retries, and why GDELT doesn't fit live headlines (2026-10-17)

**What we did**
- When GDELT refuses ("one request every 5 seconds"), the app now waits and retries up to
  3 times, then falls back to the last saved headlines with a note ("saved 3 hours ago").
- Stopped Streamlit from caching *failures* for an hour (only successful results are
  saved, by the news module itself). 3 new tests (87 total).

**What we learned (testing live)**
- GDELT's limit is shared by everyone on the same internet address; on this network it
  refuses most requests even 7 seconds apart. Sometimes one gets through.
- Name matching is too loose for company news: "Strategy" (Strategy Inc.) matched an
  unrelated article about a politician's memoir, and "Coinbase Global" (the legal
  name) matched nothing, because the press writes "Coinbase". Visa, Target or Apple
  would have the same problem.
- **Decision pending:** switch live headlines to a ticker-based source (e.g. Finnhub),
  and keep GDELT's free bulk data files (no rate limit) for the Version 3 model's history.

---

## Headlines switched to Finnhub (2026-10-17)

**Why:** GDELT matched news by company name (loose and often wrong) and was refused most of
the time on this network. Finnhub looks news up by ticker, so "V" means Visa the company.

**What we did**
- `analyzer/news.py` now uses Finnhub's company-news endpoint. The key goes in
  `.streamlit/secrets.toml` as `FINNHUB_API_KEY` and is sent as a request header, not in
  the web address, so it doesn't appear in logs.
- Industry headlines merge news for up to 5 peer tickers, newest first, without repeats,
  each tagged with its ticker.
- Results are saved for an hour; if Finnhub can't be reached, saved headlines are shown
  with their age. Clear messages for a missing key, a rejected key, or the free-plan limit.
- Free-plan limits: about 60 requests a minute, about a year of history, personal and
  non-commercial use. GDELT's bulk data files stay in the plan for the Version 3 model.
- Tests rewritten for Finnhub (84 total). Checked: no key shows setup steps, and a fake key
  reaches Finnhub and gets a clear "key not accepted" message. **Not yet checked with a
  real key.**

---

## Step 4: Filings list (2026-10-17)

**What we did**
- `analyzer/filings.py` reads the SEC's list of the company's filings (already downloaded
  for the company header) and keeps 10-K, 10-Q and 8-K filings plus amendments and
  foreign equivalents (20-F, 40-F, 6-K), newest first, with links to each document and
  its index page.
- 8-K "item" codes are translated into plain English with a fixed lookup of the SEC's
  official item list ("2.02" → "Quarterly or annual results (earnings release)"). No AI;
  unknown codes are shown as "Item x.xx" rather than guessed.
- "Significant" 8-Ks: an analyst-relevant item such as earnings, a major agreement, an
  executive change, an auditor change or an impairment. Routine ones (investor
  presentations, 7.01; exhibits only, 9.01) can be hidden with a toggle.
- The Filings section shows the latest annual and quarterly reports as cards, then a
  filterable table (type, time range, significant only) with "Open" links.
- **Clickable sources:** every notable event (Overview and Company trends) and every row
  in the chart data tables now links to the filing that *first* reported the number.
- 5 new tests (89 total). Checked AXP, MA, JPM, AAPL; generated links open on sec.gov
  (HTTP 200).

**Notes**
- The SEC's "recent" list holds about the last 1,000 filings of all kinds (for AmEx, back
  to December 2019). Older filings are in extra files we don't load yet.
- An 8-K's item codes describe the *type* of event, not its details. Reading the
  documents is Step 5's job.

---

## Step 5: The Ask assistant (2026-10-20)

**How it works**
1. **Filing reader** (`analyzer/filing_text.py`): downloads the chosen 10-K/10-Q (once,
   then cached), strips the HTML and hidden XBRL data, keeps each table row on one line
   ("Provisions | 1,100 | 900"), follows "Item 7." headings and ALL-CAPS subheadings, and
   cuts the text into ~450-word passages labelled like "Item 7. MD&A › Provisions for
   credit losses". AmEx's 10-K becomes about 305 passages.
2. **Search** (`analyzer/search.py`): BM25 keyword scoring, a standard search-engine
   formula, in plain Python with no new installs and no AI. It picks ~18 passages per
   question, with each chosen filing guaranteed a fair share. Follow-up questions also
   use the previous question's words.
3. **Claude** (`analyzer/assistant.py`): Claude Opus 5.5 at high effort, with the
   **Citations** feature. Every passage is a separate document; Anthropic guarantees cited
   text really appears in it. Claude also receives "Dashboard figures" (numbers calculated
   by our Python code, as sentences) and "How the dashboard works" (our methods), so it can
   explain the dashboard, with citations too.
4. **Rules given to Claude:** company facts only from the documents; never calculate;
   label general finance knowledge with "In general,"; say plainly when the documents
   don't answer, and where to look; no investment advice.
5. **Server-side fallback** is enabled (`fallbacks: "default"`): if Claude's safety
   filter wrongly declines a harmless question, Anthropic re-runs it on a recommended
   backup model, and the answer is labelled.
6. **The Ask section:** starter questions, a chat with follow-ups, numbered [n] markers,
   a Sources panel (filing, section, exact quote, link), an estimated cost per answer, and
   a chooser for which filings to read (default: latest 10-K and 10-Q, up to four).

**Tested with real questions** (about $0.13 each, 10-25 seconds):
- Credit losses: cited the 10-Q's explanation (a reserve release driven by lower
  delinquencies) and the dashboard's -22.8%.
- Return on equity: labelled the general explanation, cited the dashboard's 34.0% / 34.4%,
  and found AmEx's own 33.9% in the 10-K, explaining why the two differ.
- "Market share in Japan in 1995": said the filings don't address it, listed what was
  searched, and invented nothing.

**What broke / how we fixed it**
- **Search favored the long 10-K** and missed the 10-Q's company-wide explanation. Fix:
  each filing gets a fair share of passages. Confirmed: the next answer found it.
- **Table numbers lost their column headings** ("33.9 | 34.6 | 31.5" without the years)
  when a passage ended mid-table. Fix: passages avoid ending inside a table, and a very
  long table's next passage repeats its heading row. Confirmed on AmEx's 10-K.
- **Page headers leaked into passages** ("Table of / Contents"). Now filtered.
- **Dollar signs:** Streamlit reads text between two "$" as a maths formula, so dollar
  signs in answers are escaped.
- **Two test-setup mistakes** (sample text shorter than the 30-word passage minimum; an
  unrealistic table test). Fixed the tests, and the second led to the heading-row fix.
- 15 new tests (99 total).

---

## Feedback round: costs, glossary, competitors, real notable events (2026-10-20)

**Assistant cost.** Switched the Ask assistant from Claude Opus 5.5 (~13¢ a question) to
**Claude Haiku 5.5 (~0.4¢)**. The safeguards don't depend on the model: citations are still
guaranteed to quote the documents, and it still says when the filings don't answer
(re-tested). Haiku has no server-side fallback, so a declined question shows a message.

**Glossary (free, no AI).** `analyzer/glossary.py` holds ~35 plain-English definitions,
written once. They appear in a Glossary panel next to the search box (searchable), as
hover tips on the Overview figures and table columns, and under each chart. A test
requires every metric and ratio on the dashboard to have an entry.

**Competitors from the 10-K.** SEC industry codes split real competitors apart (AmEx is
"finance services", Visa and Mastercard "business services", Capital One "national
banks"). The app now reads the 10-K's Competition section and matches listed companies'
names: exact, whole word, capitalized. AmEx gets Capital One, Visa, PayPal and Mastercard,
with the sentence that names them. SEC-code peers fill any remaining slots.
- What broke: single-word names that are ordinary words. "Principal competitive factors"
  matched Principal Financial, "Customers are using…" matched Customers Bancorp, "District
  of Columbia" matched Columbia Financial, and "Application Programming Interface" matched
  Interface Inc. Fix: single-word names must not start a sentence, must never appear in
  lower case in the same text, must not follow "of", and a short list of ordinary words is
  excluded.
- Many 10-Ks (Apple, JPMorgan) name no competitors; they keep SEC-code peers.

**"Notable events" redefined.** The old list (big changes in the financials) is now
**"Unusual changes"** in Company trends. **Notable events** are now things that happened,
from 8-K filings: restatements, bankruptcy, cybersecurity incidents, change of control,
listing problems, auditor changes, impairments, restructurings, completed acquisitions, and
senior executive changes. Routine 8-Ks (earnings releases, investor presentations) are left out.
- Executive changes (item 5.02, which also covers routine pay plans) are confirmed by
  reading the 8-K's own text, and the sentence is shown as evidence. Rules learned from
  false alarms: ignore table rows ("Named Executive Officer | Base Salary"), biographies
  ("previously appointed CEO in 2010"), division roles ("CEO of Intel Products", "PSG Chief
  Executive Officer"), reporting lines ("Advisor to the CEO"), bylaw text ("elected
  officers") and cover-page text. A few imperfect detections remain (for example "CEO,
  Boeing Defense"), which is why the quote is always shown.
- Found correctly: Boeing (Calhoun stepping down, Ortberg appointed), Intel (Gelsinger's
  resignation), Disney (CEO and CFO changes), Super Micro (three listing-problem filings
  in late 2024, during its accounting scandal), AmEx (CFO retirement).
- Each event in the last year shows "Headlines around that day" (Finnhub).
- The Ask assistant now also receives the notable events, so it can answer questions like
  "Has Boeing had any CEO changes recently?" with citations.
- The section menu's "Headlines" is now **"News and events"** (Notable events | Headlines).

**What else broke**
- **Stooq** (free stock prices) now demands a "verify you're a browser" check. We won't
  bypass bot checks, so it's not used. **Finnhub's free plan has no price history**
  ("You don't have access to this resource"). Stock-move events wait for a free price source.
- **Scripted edits mangled regex symbols:** `\b` (word boundary) became an invisible
  control character in several patterns, silently breaking the biography rule. Fixed, and
  checked that no source file contains control characters. Lesson: write regex-heavy edits
  from plain text files, not inside other code.
- **Name clash** in the assistant's "Dashboard figures": two different lists were both
  called `events`. Renamed.
- 10 new tests (113 total).

---

## Stock moves from Tiingo (2026-10-20)

**Why Tiingo:** Finnhub's free plan has no price history, and Stooq now requires a
"verify you're a browser" check (which we don't bypass). Tiingo is an official API with a
free plan (approximately 50 requests an hour, 1,000 a day, 500 symbols a month).

**What we did** (`analyzer/prices.py`)
- Daily **adjusted** closing prices (adjusted for splits and dividends) for the company and
  for SPY (S&P 500), saved for 12 hours. The token is sent as a request header, not in the
  web address.
- **Market-adjusted return** = the stock's daily return − SPY's daily return. A day is flagged
  when that is more than 4 typical deviations from normal (median absolute deviation) **and**
  the stock itself moved at least 4%. So a market-wide crash isn't reported as company news.
- Each flagged day becomes a "Stock move" notable event, with a plain-English explanation
  ("AXP fell 9.8% while the S&P 500 fell 0.4%...") and any 8-K filed within three days
  listed as a likely cause. Headlines for that day appear for events in the last year.
- Stock moves also appear on the Overview and are given to the Ask assistant.
- New glossary entry: Market-adjusted return. New setup-check line and secrets-template line.
- 8 new tests (121 total): company-specific crash flagged, market-wide crash not flagged,
  small moves ignored, too little history means no flags.

**What broke / how we fixed it**
- A test failed because the made-up stock and market moved identically every ordinary day,
  so the "typical deviation" was exactly zero, and the code correctly refuses to divide by
  zero. Real prices never behave like that; the test data now has a slightly different
  market path.
- **Not yet tested with real prices**: waiting for a Tiingo token.

**Tested with real prices (after the Tiingo token was added)**
- Five years of daily prices for each stock and SPY loaded correctly.
- Checked against a known event: Boeing fell 8.0% on January 8, 2024, the first trading
  day after the Alaska Airlines door-plug incident, and it's flagged (plus the follow-on
  moves that month).

**What we changed after seeing real results**
- **From simple excess return to the "market model".** Apple rose 15.3% on April 9, 2025
  (the tariff-pause rally) while SPY rose 10.5%, and was flagged as company news, but
  Apple normally moves more than the market. Now each stock's **beta** is estimated from
  its own history and a move is judged against beta × the market's move. Apple's April
  2025 day is no longer flagged. Betas found: AXP 1.13, AAPL 1.17, BA 1.14, SMCI 1.88.
- **Beta is estimated leaving out the unusual days**, in two passes, as event studies do.
  A test showed one crash day could pull beta far off.
- **Earnings days now get their explanation:** for stock moves, every 8-K filed within
  three days is listed, including routine earnings releases (Apple −7.4% on July 31, 2026
  and AmEx −4.3% on July 24, 2026 both line up with earnings releases).
- Clearer wording: "9.3 percentage points below what the market's move would predict".
- Test data made realistic (a stock = the market's move + its own uncorrelated noise).
  Earlier made-up data had zero or correlated noise, which isn't how real prices behave.
- New glossary entry: Beta. 1 new test (122 total): a high-beta stock on a big market day
  isn't flagged.

---

## Ask searches every 10-K and 10-Q (2026-10-21)

**Reported:** a question about Q2 2023 got "that filing isn't among the passages I was
given". The assistant only searched the latest 10-K and 10-Q unless filings were added by hand.

**What we did**
- **All filings, by default.** The Ask section now indexes every 10-K and 10-Q in the SEC's
  recent list (AmEx: 27 filings, 3,945 passages, periods from December 2019 to June 2026).
  The first time per company takes a few minutes (about 3 for AmEx) while filings download;
  the text is saved permanently (filings never change) and later searches take ~0.04s.
  The cost per question is unchanged, because Claude still receives only the ~18 best passages.
  "Only the filings I choose" remains as an option.
- **Time-aware search** (`FilingSearch` in `analyzer/search.py`): a question naming a quarter
  ("Q2 2023", "second quarter of 2023") boosts that quarter's filing 2.5x and the same
  fiscal year 1.5x; a named year ("2023", "FY2024") boosts that year 2x; with no date,
  recent filings get a mild boost. Fiscal years use each company's own year-end.
- **"Why" questions favor MD&A**, where management explains changes (1.4x).
- **Variety:** at most 6 passages from any one filing.
- **Claude is told what was searched** ("27 filings (10-K and 10-Q) for periods from 2019-12-31
  to 2026-06-30"), so "not found" answers describe the real search and suggest naming a period.

**Result:** "Why did provisions for credit losses jump in Q2 2023?" is now answered from the
Q2 2023 10-Q's MD&A (higher net write-offs and reserve builds driven by loan growth), every
point cited, for 0.48¢.

**Notes:** passages now record their filing's form and period end. 5 new tests (127 total):
reading quarters and years from questions, the named quarter beating newer filings, recent
filings preferred when no date is given, the per-filing cap, and the coverage description.
- **"Cannot serialize the return value (Company)"** appeared in the running dashboard after
  code files changed underneath it: Streamlit reloads changed modules, and objects already
  cached no longer match the reloaded classes. Fix: `fileWatcherType = "none"` in
  `.streamlit/config.toml` (no live reloading; restart to pick up changes).

---

## Faster, more careful Ask answers, and linting (2026-10-21)

**Reported:** an answer about McDonald's Q2 FY25 cash couldn't explain the jump, and Ask was slow.

**Where the time went (measured):** reading one filing took ~3-4s (plus ~3s to download), and
the first question read *every* 10-K/10-Q (39 for McDonald's), so it took minutes. Claude's
answer took ~12s with nothing on screen until the end.

**What we changed**
- **Only the filings a question needs.** A question naming a period ("Q2 FY25", "2023")
  reads that fiscal year's filings; otherwise the latest 6 filings plus the latest 10-K.
  "Every 10-K and 10-Q" and "only the filings I choose" remain as options.
- **Background pre-loading:** opening Ask starts reading the recent filings straight away.
- **Streaming:** the answer's words appear as they're written.
- **Effort "medium"** (Haiku's standard level), measured ~3s faster than "high".
- Result: questions in an open dashboard take ~7-9s, with words appearing within seconds.
- **We tried a faster web-page reader (lxml) and removed it:** on these SEC files it was only
  ~10% faster (2.9s vs 3.1s), not worth an extra dependency. The real cost was reading
  too many filings.

**Accuracy**
- New rule for Claude: name the exact period of every number, as the table headings show.
  10-Q cash-flow statements usually cover the year to date, so a year-to-date figure must
  never be called a quarter's figure.
- Correction: I first said the earlier McDonald's answer had mislabelled six-month figures as
  quarterly. That was wrong. McDonald's cash-flow statement has a separate "Quarters Ended"
  column, and the figures reconcile ($1,238M → $1,876M, +638). The new answer names the period
  explicitly and keeps the six-month MD&A figures separate.
- **Finance-term expansion:** a question about "cash" also searches "cash flows, liquidity,
  operating/investing/financing activities"; "why" questions favor MD&A and liquidity sections.
- Why there's no single cause: the 10-Q doesn't say why cash rose. The assistant now
  assembles it from the cash-flow lines (mostly new long- and short-term borrowing on top of
  operating cash) and says so.

**Linting** (`ruff`, settings in `ruff.toml`; `requirements-dev.txt`)
- 107 findings at first; now "All checks passed!".
- Possible bugs reviewed: 19 places pair lists with `zip()`. Where the lists must line up
  (15), `strict=True` now raises an error instead of silently dropping data; where lengths
  differ on purpose (4: consecutive-filing pairs, the last row of a chart grid, one test
  pattern), `strict=False` with a comment. All tests still pass, so no list was
  silently mismatched.
- A "loop variable inside a function" warning (B023) was not a real bug (the function runs
  immediately), but is now explicit. Removed an unused import and an unused loop counter.
- Style: variables named `l` renamed, imports moved to the top, long lines wrapped. The
  instructions sent to Claude stay one sentence per line (exempted in `ruff.toml`, with the reason).
- Cleaned up two test lines damaged by an earlier escaping mistake.
- 4 new tests (131 total). All 20 section views checked for AXP and MCD.

---

## Step 5b: Explain from filing (2026-10-22)

**What we did** (`analyzer/explain.py`, `ui/explain_ui.py`)
- **Company trends › Unusual changes:** choose a change and press "Explain from filing". The
  assistant reads the 10-Q/10-K that first reported the number (where management discussed
  it at the time) and gives management's explanation, cited.
- **News and events › Notable events:** every event has an "Explain this event" button.
  - 8-K events read that 8-K and the next 10-Q/10-K.
  - Stock moves read 8-Ks filed within three days, the next 10-Q/10-K, and (for the last
    year) that day's headlines, which Claude is told to attribute as news, not filings.
- **Saved answers:** each explanation is saved to `data/cache/explanations/` after the first
  click, so reopening it is free and instant. About 0.25¢ per new explanation.

**What broke / how we fixed it**
- **8-K press releases were missing.** An 8-K's main document is often just a cover note;
  the substance (an earnings or leadership press release) is in an attached Exhibit 99. The
  assistant itself said so: "That press release is furnished as Exhibit 99.1… Its text isn't
  in the documents I have." Fix: read each 8-K's Exhibit 99 attachments, found through the
  SEC's official file listing for the filing (`index.json`, saved permanently).
- **My test clicked the wrong buttons**, matching buttons to events by position (some events
  have no button). Fixed by targeting each button by its unique ID. The answers it saved
  during that faulty run were deleted and regenerated.

**Tested on real events**
- AmEx Q2 2023 provisions +192%: management's explanation from the Q2 2023 10-Q (higher net
  write-offs and reserve builds tied to strong loan growth), cited.
- Boeing −8.0% on January 8, 2024: found the Alaska Airlines door-plug accident and the FAA
  grounding in the 10-K's subsequent-events note, and said plainly that the filing doesn't
  link them to the stock move ("any link would be my inference").
- Boeing CEO departure (March 2024): explained from the 8-K and its press release.
- 7 new tests (138 total); linter clean.

---

## Step 5c: Company synopsis on the Overview (2026-10-22)

**What we did** (`analyzer/synopsis.py`, `ui/overview.py`)
- The Overview's "About" section now holds a briefing with six headings: what the company
  does, how it makes money, the latest quarter, recent notable events, key risks, and
  interview talking points. Every point cites its source.
- **Where each part comes from:** business and revenue from the latest 10-K's Item 1; risks
  from Item 1A; the reasons behind the latest results from the newest report's MD&A (Item 2
  of a 10-Q, or Item 7 of the 10-K when the 10-K is newer); every number and event from the
  dashboard's own figures, never calculated by the AI.
- Written only when you press "Write synopsis" (about 25-40 seconds, about 0.6¢), then saved.
  It is offered again only when the company files a new 10-K or 10-Q.
- The assistant's length rule can now be swapped per task: short for chat, structured for
  the synopsis.

**What broke / how we fixed it**
- Item labels differ: an Item without a title on the same line is labelled "Item 1" (no
  dot), and "Item 1" must not match "Item 1A" or "Item 10". Fixed with an exact item-number
  match, covered by tests.
- The first AmEx draft's talking points were uncited and added one detail not in the
  quoted text. The instructions now require talking points to reuse facts already stated,
  with the same sources, and add nothing new.
- The shell's escaping garbled `\b` and `\n` in a script again; repaired with a separate
  fix script and checked for control characters.

**Tested on real companies**
- AmEx (10-K Feb 2026 + 10-Q Jul 2026): segments, revenue model, Q2 2026 drivers (billed
  business, card fees, reserve release) and risks all matched the cited text. 0.58¢.
- Microsoft (10-K Jul 2026 is the newest report): used the 10-K's MD&A, noted that Q4 is
  derived and Q4 EPS isn't, and flagged the OpenAI investment gains in fiscal 2026 profit. 0.55¢.
- 6 new tests (144 total); linter clean.

---

## Speed-up (2026-10-22)

**How we measured:** every section timed with Streamlit's test runner for AmEx, on the
first visit after starting the dashboard and on a repeat visit (a click). Then profiled
to see where the time went.

| | Before | After (first start) | After (typical, tables saved) |
|---|---|---|---|
| Overview, first visit | 26.5s | 9.9s | 7.7s |
| Industry, first visit | 22.4s | 14.9s | 3.5s |
| News and events, first visit | 3.5s | 1.0s | 0.8s |
| Overview, each click | 1.2s | 0.7s | 0.7s |
| Industry, each click | 1.7s | 1.2s | 0.7s |

**The five causes and fixes**
1. **The AI library loaded with the page.** Anthropic's library has 2,300+ files and took
   ~16s to load, though only Ask and the explain buttons use it. Now it loads only when
   needed, in the background after the first page is drawn.
2. **Turning SEC data into tables took 2-5s per company, every restart.** Two wasteful
   steps sped up (stock-split checks and Q4 calculation, ~25% faster). The finished tables
   are now saved to disk (`data/cache/metrics/`), rebuilt only when the SEC data is
   re-downloaded or the cleaning rules change. Checked: identical results for all 144
   tables across 12 companies.
3. **Industry rebuilt every peer's figures.** Peers now use the saved tables, and each
   peer's snapshot row is remembered instead of recalculated on every click.
4. **Work redone on every click.** Growth rates were calculated row by row, dozens of
   times per page: now 5x faster (identical results). The events list (8-Ks plus stock
   moves) is remembered for an hour; a price-service failure is not remembered.
5. **Competitor matching checked thousands of company names sentence by sentence.** A
   quick "is the name in the text at all?" check first: 2-5s down to ~0.3s, same peers.

**What's left:** about 7s on the very first page after starting the dashboard is mostly
loading Python's data libraries (pandas, Streamlit, Plotly), once per start. Ask answers
still take ~7-9s, which is Claude writing the answer.
- 1 new test (145 total); linter clean.

---

## Design review against Apple's design principles (2026-10-22)

Reviewed with the `apple-design` skill (Apple's WWDC design guidance), on desktop and a
phone-sized screen. The motion and gesture guidance mostly doesn't apply (the dashboard has
no dragging or animation), so the fixes come from the hierarchy, typography, feedback and
flexibility principles.

**Six fixes**
1. **Most important first (Simplicity):** the Overview opened with three screens of written
   briefing, pushing the key figures below the fold. Now: key figures, then notable events,
   then the "Company briefing" at the end.
2. **Clear heading levels (Typography):** the briefing's headings were the same size as the
   page's section headings. They're now a smaller, bolder level. Letter-spacing depends on
   size (tighter on large titles, slightly looser on small labels) instead of one value.
3. **No mixed-up pages while loading (Response / spatial consistency):** when switching
   sections, the previous section stayed on screen, faded, under the new one. It's now
   cleared if the update takes longer than half a second (quick clicks don't flicker).
   Respects the "reduce motion" setting.
4. **Header craft:** the app name now lines up with the search box, the top of the page no
   longer clips on a phone, and the big gap plus heavy divider under the section menu is
   replaced by a thin line.
5. **Less noise (Purpose):** saved answers no longer show what they cost (reopening is
   free); "Also: 54 unusual changes" (a count so high "unusual" lost meaning) became the
   single latest one; the long explanation on News and events moved into a "What counts as
   a notable event?" expander.
6. **Phone layout (Flexibility):** the seven section buttons wrapped into three rows on a
   phone; they now stay on one line that scrolls sideways.

**What broke / how we fixed it**
- The first menu style applied to every button group on the site; scoped to the main menu.
- The shell garbled an apostrophe and a line break in a script again; fixed with the Edit tool.
- 145 tests pass; linter clean; every section opened without errors (AppTest).

---

## Step 6: Polish, with every installed design skill (2026-10-22)

Ran each design skill installed on this computer against the dashboard. ("find-skills" only
searches for other skills and "synced" is a sync folder, so neither applies.)

**What each one found, and the fix**
- **web-design-guidelines** (Vercel's interface rules):
  - Headings skipped a level (page title, then straight to level 3). Sections are now level 2,
    parts of a section level 3 (the company briefing's headings included).
  - Loading messages used "..." instead of a real ellipsis "…" (13 places).
  - Figures used Garamond's default numerals, which vary in width, so columns didn't line up.
    Figures now use even-height, equal-width numerals.
  - No visible keyboard focus on headline links; added for links, buttons and the menu.
  - The company and section weren't in the web address. Now `?ticker=AXP&section=Industry`
    opens that page directly and can be bookmarked or shared.
  - The page now tells the browser it's a light page.
- **design-taste-frontend** (app-screen rules, plus its inspector at phone width):
  - Key figures were four tinted tiles; now one ruled band split by thin lines, like an
    annual report's highlights strip, and a 2 x 2 grid on a phone.
  - The "+10.0% vs. a year ago" pills failed the contrast check (4.3:1, needs 4.5:1); now
    dark green (or dark red) text with no pill.
  - The company name was 41px on a phone; app titles stay at 20-32px.
  - Number columns in every table are right-aligned so digits line up.
  - Its inspector also flags the warm off-white page colour as "cream"; kept, because it's the
    paper look chosen for this project.
- **frontend-design**: solid navy chips in the company pickers put strong colour on controls;
  now a pale tint. Written text stops at about 80 characters a line.
- **apple-design** (second pass): buttons now respond the moment they're pressed, with a
  "reduce motion" fallback.

**What broke / how we fixed it**
- **The Garamond font sometimes didn't load at all**, and the page fell back to a plain
  sans-serif (found while checking the numerals: the browser had no Garamond loaded).
  Streamlit's own theme font loading doesn't always run. The stylesheet now also loads EB
  Garamond directly, so it can't be skipped.
- The design inspector can't wait for Streamlit to finish drawing (it measured an empty page
  at desktop width); its phone-width results were used, plus screenshots.
- README screenshots: Chrome's simple screenshot mode captured blank pages, and at 1.5x pixel
  density the charts didn't draw. A small script now waits for the page (and its charts) to
  finish, at normal density.
- The app name sat 9px below the search box because of a negative margin Streamlit puts on
  text blocks; removed for that one element.
- 3 new tests (148 total); linter clean; every section opened without errors for AXP and AAPL.

---

## Step 7: The web dashboard (2026-10-22)

**Why:** Streamlit redraws the whole page on every click, so it could never feel smooth.
The screen was rebuilt as a single web page; all the data, calculation and AI code
(`analyzer/`) is unchanged and shared. Every feature carried over, including the briefing.

**What we did** (`webapp/`)
- `service.py`: the same loading rules as before, without Streamlit. Results are
  remembered; when several requests ask for the same thing at once, the work runs once;
  rival companies load side by side.
- `payloads.py`: what each panel shows, all calculated in Python (growth, margins, takeaways,
  the money-flow split). The page only draws and formats.
- `server.py`: Starlette (already installed with Streamlit, so nothing new), local only,
  compressed replies, and live streams for the assistant.
- `ai.py`: the briefing, "explain this" and the chat, streaming the answer's words as they
  are written. Saved answers from the old version are reused.
- The page (`static/`): seven panels that glide sideways (Snapshot, Briefing, Trends, Where
  the money goes, Price and events, Rivals, Filings), an Ask drawer, a glossary drawer, and
  a company search (press `/`). Charts are hand-drawn SVG (no chart library): lines morph
  between measures, the price chart zooms smoothly, the money flow and bubbles grow in.
  Each company's logo comes from Finnhub, and its brand colour is read from the logo.
  Links like `#MSFT/rivals` open a company and panel directly.

**Design tools used**
- frontend-design: the plan (ledger-navy ground, Sora + Manrope, one bold element: the
  morphing chart in the company's colour).
- design-taste-frontend: app-screen rules; its inspector and code scanner both pass with
  no failures or warnings (fixed: white text on light brand buttons, invisible closed
  overlays counted as covering text, a stretched chart card, an emoji ✕, a resting shadow).
- apple-design: motion that starts from where it is and can be interrupted, press
  feedback, drawers that leave the way they came, reduced-motion support.
- web-design-guidelines: heading order, labels on icon buttons, visible focus, real
  ellipses, links for every view, screen-reader announcements for chat answers.

**Speed** (measured)

| | Streamlit | Web dashboard |
|---|---|---|
| Open a company: figures and chart on screen | 7.7s | 0.6s |
| Switch panel | 0.7-1.5s | 0.02-0.04s |
| Switch company | several seconds | 0.1s |
| A company's data, second request | ~1s | 0.016s |

**What broke / how we fixed it**
- **Re-opening a company took 18s, slower than the first time.** The company's data wasn't
  remembered, and reading filings for the chat in the background was competing with it
  (Python runs one thing at a time). Fixed: each panel's data is remembered, and the chat's
  filing reading waits until Ask is opened or the page has been quiet for a while.
- **Logo download failed once (34s, nothing).** The image host redirects and was briefly
  slow. Now: short timeouts, one retry, and the logo is saved; the page shows the ticker
  until it arrives.
- **Count-up numbers could flash a negative value** on the first frame (frame time a hair
  before the start). Clamped; and if a browser stops sending frames, a timer lands every
  animation on its final value.
- **McDonald's red** made rising lines look like falls (red means "down" here). When a
  logo's main colour is red and it has a second colour (McDonald's yellow), that's used.
- **McDonald's 398% return on equity** is right but misleading; the takeaway now explains
  that equity is small after years of buybacks.
- Bubble chart clipped its top bubbles: the axis now always reaches past the highest value.
- 7 new tests (155 total); linter clean.

---

## Fix: Exxon showed only two quarters of revenue (2026-10-22)

**Cause:** in 2026 Exxon moved under a new holding company, ExxonMobil Holdings Corp. The
SEC gave it a new record (CIK 0002115436) and the XOM ticker, but its history stayed on
the old Exxon Mobil Corp record (CIK 0000034088). The new record had filed one quarterly
report (Q2 2026 plus Q2 2025 for comparison), so the charts had two quarters.

**Fix:** a short list of known predecessor records (`PREDECESSORS` in
`analyzer/edgar_client.py`). A company on it gets its predecessor's figures and filings
combined with its own; where both report the same period, the most recently filed value
wins (the existing rule). Both dashboards use it. Exxon now has revenue from FY2009 and
quarters from 2017, and its latest 10-K is found for the briefing and the chat.
The SEC publishes no "successor of" link, so new cases are added to the list by hand.
- 1 new test (156 total); linter clean.

---

## Fix: a reorganization shown as an "acquisition" (2026-10-22)

**Reported:** Exxon's events said "Completed an acquisition or sale of assets" on July 1,
2026, which isn't what happened. The 8-K was filed under SEC item 2.01 (acquisitions) and
3.01 (listing), but described Exxon moving under a new Texas holding company, shares
swapped one-for-one. The dashboard showed the SEC's generic item names with no context.

**Fix** (`analyzer/events.py`): for items whose names are too generic (2.01, 3.01, 5.01,
1.02) the 8-K's own text is read. A reorganization ("redomiciliation", "reincorporation",
"holding company reorganization") becomes one event, "Reorganized under a new parent
company (not an acquisition)", quoting the filing. Other items now quote the first real
sentence under their heading (e.g. "consummated the previously announced acquisition of
Pioneer Natural Resources"). Checked on Exxon and Microsoft filings.
- 2 new tests (158 total); linter clean.

---

## Step 8: Industry and world (2026-10-22)

**Asked for:** the dashboard should explain a company's situation, not just its numbers:
big financials, industry performance, industry drivers, current events and macro trends,
big company events, explanations for unusual events, and definitions. The first, fifth,
sixth and seventh existed; this step adds the other three in a new panel.

**What we did**
- `analyzer/industry.py`: an industry profile from the SEC industry code: sector fund (for
  example XLE for oil and gas, SOXX for chips), the economic indicators that drive it
  (Brent and WTI oil, natural gas, chip production, card delinquencies, rates...), and the
  topics worth watching (Middle East shipping, OPEC+, tariffs, Chinese chipmakers...). FRED
  data is fetched with a free key, saved for 12 hours, and every change is calculated here.
- Industry performance (Python): total return with dividends over 1 and 5 years for the
  stock, its sector fund and the S&P 500, and lines starting at 100 for a comparison chart.
- Drivers in the company's own words: the AI reads the 10-K's risk factors, market risk and
  management's discussion, and lists the 4-6 outside forces that drive results, cited.
  Written automatically once per 10-K (under 1¢), then saved.
- "What's happening now": a cited news summary from Claude's web search (headings: what's
  moving the industry, policy and trade, competitors at home and abroad, what it could mean
  for the company). Only on request, saved for the day. Rules: every fact cited and dated,
  numbers only as sources report them, forecasts and opinions labelled, disagreements shown.

**Checked on real companies**
- Exxon drivers (0.40¢): commodity prices, OPEC+ supply, AI data-centre demand, rates,
  2025 tariffs (Exxon expects no material near-term impact), climate policy, Kazakhstan.
- Exxon news: Brent at $113 (highest since May), tanker attacks near the Strait of Hormuz,
  Houthi strikes on Saudi targets, Russia sanctions waiver, OPEC+ cuts and the UAE's exit.
- Intel news (7.25¢): China's new export restrictions, Taiwan aligning with US chip controls,
  the US-China tariff truce, how far SMIC and Huawei have caught up (sources disagree: one
  says SMIC is 3-5 years behind TSMC, another claims 5nm-class output at much lower yields).

**What broke / how we fixed it**
- **The cost was double my estimate.** The first Exxon update cost 6.0¢, not ~3¢: each web
  search is 1¢ and search results add reading costs. It also ran out of searches. Now: 6
  searches planned one per topic, and the button says "about 6-7¢".
- **Searching the wrong name.** It searched for "ExxonMobil Holdings Corp" (the new legal
  name), which news articles don't use. It now searches the short brand name ("Exxonmobil").
- **The newer web search tool returned nothing on Haiku**, quietly (errors come back inside
  the answer). The basic tool works and is used.
- **FRED's keyless download blocks automated requests** (it timed out), so a free key is
  needed. Until it's added, the panel says so and the rest still works.
- **The 5-year S&P return was missing**: its prices started exactly five years ago, a day
  short. Prices now include ten extra days.
- **Chart line ends didn't match the table** (Intel 223 vs +131.6%): the line started from
  the first weekly price, the table from the exact price a year earlier. Both now start
  from the same price.
- **"Font" shorthands reset equal-width digits** on big numbers; fixed for every element.
- The header's "+55% over the last year" (share price) vs the panel's +60% (with dividends)
  looked contradictory; the header now says "share price".
- Design inspector: passes on the Snapshot; on the new panel one "text at the edge" flag is
  the sideways-scrolling tab strip, which is allowed there.
- 5 new tests (163 total); linter clean.
