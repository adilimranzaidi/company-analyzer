"""Plain-English definitions of the terms used in the dashboard.

Written once and stored here, so explanations are instant and free (no AI involved).
Each entry has a one-line "short" version (used in hover tips) and a fuller "long" one
(used on the Glossary panel). Where the dashboard calculates something, the long version
says exactly how, matching analyzer/metrics.py.
"""

GLOSSARY: dict[str, dict[str, str]] = {
    # --- Income statement ----------------------------------------------------------------
    "Revenue": {
        "short": "Total money a company brings in from its business before any costs.",
        "long": "The top line of the income statement: what customers paid for products and "
                "services. Banks and card companies usually report it 'net of interest "
                "expense', meaning interest they pay on deposits and debt is already subtracted.",
    },
    "Net income": {
        "short": "Profit left after every expense, interest payment and tax.",
        "long": "The bottom line of the income statement. It's what belongs to the company's "
                "owners for the period. A negative figure is a net loss.",
    },
    "Diluted EPS": {
        "short": "Net income divided by the number of shares, counting shares that could be created from options.",
        "long": "Earnings per share (EPS) shows how much profit each share earned. 'Diluted' "
                "assumes stock options and similar securities were turned into shares, which "
                "gives a slightly lower, more conservative figure. It's the per-share number "
                "analysts quote most often.",
    },
    "Gross profit": {
        "short": "Revenue minus the direct cost of making or delivering what was sold.",
        "long": "For a manufacturer or retailer: sales minus the cost of the goods sold. It "
                "shows how much is left to pay for everything else (staff, marketing, "
                "research). Banks and card companies usually don't report it.",
    },
    "Cost of revenue": {
        "short": "The direct cost of the products or services a company sold.",
        "long": "Also called cost of goods sold: materials, manufacturing, or the direct "
                "cost of delivering a service. Revenue minus cost of revenue is gross profit.",
    },
    "Operating income": {
        "short": "Profit from the core business, before interest and taxes.",
        "long": "Revenue minus the costs of running the business (cost of revenue, salaries, "
                "marketing, research and so on), before interest and taxes. It shows how "
                "profitable the main business is on its own.",
    },
    "Net interest income": {
        "short": "Interest a lender earns on loans minus the interest it pays on deposits and debt.",
        "long": "A core profit source for banks and card lenders. For example, AmEx earns "
                "interest on card balances that customers carry and pays interest to savers "
                "and lenders. The difference is net interest income.",
    },
    "Noninterest income": {
        "short": "Income from fees and services rather than from interest.",
        "long": "For a card company: merchant fees (the 'discount revenue' a store pays on "
                "each card purchase), annual card fees, and service fees. For AmEx this is "
                "the larger part of revenue.",
    },
    "Provision for credit losses": {
        "short": "Money a lender sets aside for loans it expects won't be repaid.",
        "long": "An expense recorded in advance for expected losses on loans and card "
                "balances. It rises when a lender expects more defaults (for example in a "
                "recession) and falls when credit quality improves. A 'reserve build' means "
                "the provision is larger than actual write-offs; a 'reserve release' means "
                "it's smaller.",
    },
    "Net write-off": {
        "short": "Debt a lender gives up on collecting, minus anything later recovered.",
        "long": "When a borrower stops paying, the lender eventually 'writes off' the "
                "balance as a loss. Net write-offs subtract any money recovered afterwards. "
                "The net write-off rate divides them by total loans.",
    },
    "Delinquency": {
        "short": "A payment that is late (for example 30 or 90 days past due).",
        "long": "Delinquency rates show the share of balances with late payments. Rising "
                "delinquencies are often an early warning of future write-offs.",
    },
    # --- Balance sheet -------------------------------------------------------------------
    "Total assets": {
        "short": "Everything the company owns, at a point in time.",
        "long": "Cash, investments, loans to customers, buildings, equipment and so on, as "
                "of the end of the period. For a lender, most assets are the loans it has made.",
    },
    "Shareholders' equity": {
        "short": "What the owners' stake is worth on paper: assets minus everything owed.",
        "long": "Also called book value. It grows with profits the company keeps and shrinks "
                "with losses, dividends and share buybacks. Companies that buy back a lot of "
                "stock (like Apple or Mastercard) can have small equity, which makes return "
                "on equity look very high.",
    },
    "Cash & equivalents": {
        "short": "Cash plus investments that can be turned into cash almost immediately.",
        "long": "Bank deposits and very short-term, safe investments. Some companies only "
                "report a figure that also includes 'restricted' cash set aside for specific "
                "purposes; the dashboard shows which label was used.",
    },
    # --- Ratios and growth -----------------------------------------------------------------
    "Gross margin": {
        "short": "Gross profit as a percentage of revenue.",
        "long": "Gross profit ÷ revenue, for the same period. A 45% gross margin means 45 "
                "cents of every sales dollar is left after the direct cost of what was sold.",
    },
    "Operating margin": {
        "short": "Operating income as a percentage of revenue.",
        "long": "Operating income ÷ revenue, for the same period. It shows how much of each "
                "sales dollar the core business turns into profit before interest and taxes.",
    },
    "Net margin": {
        "short": "Net income as a percentage of revenue.",
        "long": "Net income ÷ revenue, for the same period. A 15% net margin means 15 cents "
                "of profit for every dollar of revenue.",
    },
    "Return on equity": {
        "short": "Profit earned for every dollar of shareholders' equity (ROE).",
        "long": "Net income ÷ average shareholders' equity. A 34% ROE means about 34 cents of "
                "yearly profit for each dollar of equity. The dashboard's annual figure uses "
                "the average of equity at the start and end of the year; the quarterly view "
                "uses the last four quarters' net income and the average of equity now and a "
                "year earlier. Companies' own figures can differ slightly because they "
                "average equity differently.",
    },
    "Year-over-year growth": {
        "short": "Change compared with the same period a year earlier.",
        "long": "(This period − the same period a year earlier) ÷ the same period a year "
                "earlier. Comparing Q2 with last year's Q2 avoids seasonal swings, such as "
                "holiday spending. Shown as n/m when the earlier figure was zero or negative.",
    },
    "Quarter-over-quarter growth": {
        "short": "Change compared with the previous quarter.",
        "long": "(This quarter − last quarter) ÷ last quarter. Useful for spotting turning "
                "points, but it includes normal seasonal swings.",
    },
    "n/m": {
        "short": "Not meaningful: a growth rate can't be calculated sensibly here.",
        "long": "Shown when the earlier figure was zero, negative or missing. For example, "
                "going from a $1M loss to a $1M profit isn't '+200% growth'.",
    },
    "Peer median": {
        "short": "The middle value among the chosen peer companies.",
        "long": "Half the peers are above it and half below. The median is used instead of "
                "the average so one unusual company can't distort the comparison.",
    },
    # --- Reporting concepts ----------------------------------------------------------------
    "Fiscal year": {
        "short": "The 12-month period a company uses for its accounts.",
        "long": "Many companies use the calendar year, but not all: Apple's fiscal year ends "
                "in late September, so 'Q1 FY2026' is October to December 2025.",
    },
    "Derived Q4": {
        "short": "A fourth-quarter figure calculated as full year minus Q1, Q2 and Q3.",
        "long": "Companies file quarterly reports for Q1 to Q3 and an annual report for the "
                "full year, so there's no separate Q4 report. The dashboard subtracts the "
                "first three quarters from the year and marks the result as derived. It's not "
                "done for EPS, because per-share figures can't be subtracted when the share "
                "count changes.",
    },
    "Stock split": {
        "short": "Dividing each share into several, so each is worth proportionally less.",
        "long": "After a 4-for-1 split, one $400 share becomes four $100 shares. Nothing "
                "about the company changes, but per-share figures like EPS must be divided by "
                "4 to compare with the past. The dashboard detects splits and restates older "
                "per-share figures.",
    },
    "Unusual change": {
        "short": "A period whose year-over-year change was far outside the company's normal range.",
        "long": "Flagged by Python when a change is more than three 'typical deviations' "
                "from the company's own median change and at least 10 percentage points "
                "away. It points to something worth investigating, such as COVID in 2020.",
    },
    "Notable event": {
        "short": "Something that happened to the company: an executive change, restatement, deal or big stock move.",
        "long": "Built from the 8-K reports a company must file within four business days "
                "of a major event, using the SEC's official event types (restatements, "
                "cybersecurity incidents, listing problems, acquisitions, write-downs). "
                "Executive changes are confirmed from the 8-K's own text, and the sentence "
                "is shown. Routine 8-Ks such as quarterly earnings releases are left out.",
    },
    "10-K": {
        "short": "A company's annual report to the SEC.",
        "long": "The most complete yearly picture: the business description, risk factors, "
                "management's discussion and analysis (MD&A) and audited financial statements.",
    },
    "10-Q": {
        "short": "A company's quarterly report to the SEC.",
        "long": "Filed for the first three quarters of each fiscal year: unaudited financial "
                "statements plus management's discussion of the quarter.",
    },
    "8-K": {
        "short": "A 'current report' filed within four business days of a major event.",
        "long": "Required for events such as earnings releases, executive departures, major "
                "agreements, acquisitions, auditor changes or restatements. Each 8-K lists "
                "official item codes describing the type of event.",
    },
    "MD&A": {
        "short": "Management's discussion and analysis: the section where management explains results.",
        "long": "Part of every 10-K and 10-Q, written by management: what drove revenue, "
                "costs and credit quality, and what they expect. It's the best place to find "
                "out why a number moved.",
    },
    "XBRL": {
        "short": "Tags that make numbers in SEC filings machine-readable.",
        "long": "Companies tag each figure in their filings with a standard label, such as "
                "NetIncomeLoss. The dashboard reads these tags, and shows which label it used "
                "for each metric, because companies don't always use the same one.",
    },
    "EDGAR label": {
        "short": "The standard XBRL name a company used to tag a number.",
        "long": "For example RevenuesNetOfInterestExpense or NetIncomeLoss. Several labels "
                "can mean similar things, so the dashboard picks the one with the most recent "
                "data and shows it on screen.",
    },
}


def short(term: str) -> str:
    return GLOSSARY.get(term, {}).get("short", "")


def search(query: str) -> list[tuple[str, dict]]:
    """Terms whose name or explanation contains the query (case-insensitive)."""
    q = query.strip().lower()
    items = sorted(GLOSSARY.items(), key=lambda kv: kv[0].lower())
    if not q:
        return items
    name_hits = [kv for kv in items if q in kv[0].lower()]
    text_hits = [kv for kv in items if kv not in name_hits and
                 (q in kv[1]["short"].lower() or q in kv[1]["long"].lower())]
    return name_hits + text_hits
