"""Turn the SEC's raw XBRL data into clean annual and quarterly tables.

The SEC's "company facts" file lists every number a company has tagged, under labels
such as "NetIncomeLoss". This file:
1. picks which label to use for each metric, and records that choice so it can be shown;
2. keeps only true 3-month (quarterly) and ~12-month (annual) figures, since 10-Qs also
   report year-to-date totals;
3. when the same period was reported more than once, keeps the most recently filed value
   (later filings carry any revisions);
4. derives the 4th quarter as Full year - Q1 - Q2 - Q3, because companies file a 10-K
   for the year rather than a separate Q4 report. Derived values are always labelled.

Only subtraction is done here. Growth rates and margins live in metrics.py.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

# How many days a period must span to count as a quarter or a year.
# Real quarters run 89-98 days (some companies use 13- or 14-week quarters),
# and years run 364-371 days (52- or 53-week years).
QUARTER_DAYS = (80, 100)
YEAR_DAYS = (350, 380)


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    labels: tuple[str, ...]   # EDGAR labels to try; earlier = preferred when tied
    kind: str                 # "flow" = over a period (income); "instant" = at a date (balance sheet)
    unit: str = "USD"
    description: str = ""
    derive_q4: bool = True    # can Q4 be calculated as FY - Q1 - Q2 - Q3?


METRICS: tuple[Metric, ...] = (
    Metric(
        "revenue", "Revenue",
        ("Revenues", "RevenuesNetOfInterestExpense",
         "RevenueFromContractWithCustomerExcludingAssessedTax",
         "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"),
        "flow",
        description="Total revenue. Banks and card issuers report it net of interest expense.",
    ),
    Metric(
        "net_income", "Net income", ("NetIncomeLoss",), "flow",
        description="Profit after all expenses and taxes, attributable to the company's owners.",
    ),
    Metric(
        "eps_diluted", "Diluted EPS",
        ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
        "flow", unit="USD/shares",
        description="Net income per share, counting options and other securities that could become shares.",
        # Per-share figures can't be subtracted: the share count changes each quarter.
        derive_q4=False,
    ),
    Metric(
        "gross_profit", "Gross profit", ("GrossProfit",), "flow",
        description="Revenue minus the direct cost of the products or services sold.",
    ),
    Metric(
        "cost_of_revenue", "Cost of revenue",
        ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"), "flow",
        description="The direct cost of the products or services sold.",
    ),
    Metric(
        "operating_income", "Operating income", ("OperatingIncomeLoss",), "flow",
        description="Profit from the core business, before interest and taxes.",
    ),
    Metric(
        "net_interest_income", "Net interest income", ("InterestIncomeExpenseNet",), "flow",
        description="Interest earned on loans minus interest paid on deposits and debt (lenders).",
    ),
    Metric(
        "credit_provision", "Provision for credit losses",
        ("ProvisionForLoanLossesExpensed", "ProvisionForLoanLeaseAndOtherLosses",
         "ProvisionForLoanAndLeaseLosses", "ProvisionForCreditLosses"),
        "flow",
        description="Money set aside for loans and card balances expected not to be repaid (lenders).",
    ),
    Metric(
        "total_assets", "Total assets", ("Assets",), "instant",
        description="Everything the company owns, at the end of the period.",
    ),
    Metric(
        "equity", "Shareholders' equity", ("StockholdersEquity",), "instant",
        description="Assets minus liabilities: the owners' stake in the company.",
    ),
    Metric(
        "cash", "Cash & equivalents",
        ("CashAndCashEquivalentsAtCarryingValue",
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        "instant",
        description="Cash and near-cash investments. Some companies only report a figure that includes restricted cash.",
    ),
)


@dataclass
class LabelChoice:
    label: str
    latest_end: str                                   # most recent period end for this label
    passed_over: list[tuple[str, str]] = field(default_factory=list)  # (label, latest_end)


@dataclass
class MetricData:
    metric: Metric
    choice: LabelChoice | None
    annual: pd.DataFrame
    quarterly: pd.DataFrame
    discontinued: bool = False   # data exists but stopped long ago (e.g. AmEx operating income, 2010)

    @property
    def has_data(self) -> bool:
        return self.choice is not None and not (self.annual.empty and self.quarterly.empty)

    @property
    def available(self) -> bool:
        """Has data that is current enough to chart."""
        return self.has_data and not self.discontinued


# form/filed/accn = the latest filing to report the number (its value is the one we use).
# orig_* = the filing that FIRST reported it: where management discussed it at the time.
COLUMNS = ["period", "fiscal_year", "fiscal_quarter", "start", "end", "value",
           "source", "form", "filed", "accn", "orig_form", "orig_filed", "orig_accn"]


# ---------------------------------------------------------------------------
# Step 1: choose a label
# ---------------------------------------------------------------------------

def _rows_for(facts: dict, label: str, unit: str) -> list[dict]:
    return facts.get("facts", {}).get("us-gaap", {}).get(label, {}).get("units", {}).get(unit, [])


def choose_label(facts: dict, metric: Metric) -> LabelChoice | None:
    """Pick the label with the most recent data. Ties go to the earlier label in the list.

    Why "most recent" rather than "first that exists": companies switch labels over time.
    AmEx has old "Revenues" data that stops in 2010, then "RevenuesNetOfInterestExpense".
    """
    found = []
    for priority, label in enumerate(metric.labels):
        rows = _rows_for(facts, label, metric.unit)
        if rows:
            found.append((max(r["end"] for r in rows), -priority, label))
    if not found:
        return None
    found.sort(reverse=True)
    latest_end, _, label = found[0]
    passed_over = [(lbl, end) for end, _, lbl in found[1:]]
    return LabelChoice(label, latest_end, passed_over)


# ---------------------------------------------------------------------------
# Step 2: fiscal labels ("Q2 FY2026")
# ---------------------------------------------------------------------------

def fiscal_period(end: date, fye_month: int) -> tuple[int, int]:
    """Which fiscal year and quarter a period ending on `end` belongs to.

    Example, fiscal year ending in September (Apple): a quarter ending 2025-12-27
    is Q1 of FY2026. Companies with 52/53-week years sometimes end a few days into
    the next month (e.g. Oct 1), so dates in the first week count as the prior month.
    """
    month, year = end.month, end.year
    if end.day <= 7:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    months_until_year_end = (fye_month - month) % 12
    quarter = 4 - round(months_until_year_end / 3)
    fiscal_year = year if month <= fye_month else year + 1
    return fiscal_year, quarter


def is_quarter_end(end: date, fye_month: int) -> bool:
    """True if a date falls at the end of one of the company's fiscal quarters."""
    month = end.month - 1 if end.day <= 7 else end.month
    return (fye_month - month) % 3 == 0


# ---------------------------------------------------------------------------
# Step 3: clean the rows
# ---------------------------------------------------------------------------

def _to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={"val": "value"})  # the SEC calls the number "val"
    df["end"] = pd.to_datetime(df["end"]).dt.date
    if "start" in df:
        df["start"] = pd.to_datetime(df["start"]).dt.date
    df["filed"] = pd.to_datetime(df["filed"]).dt.date
    return df


def _latest_filed(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """When a period appears in several filings, keep the most recently filed value,
    and remember which filing reported it first."""
    ordered = df.sort_values(["filed", "accn"])
    first = (ordered.drop_duplicates(subset=keys, keep="first")
                    [keys + ["form", "filed", "accn"]]
                    .rename(columns={"form": "orig_form", "filed": "orig_filed",
                                     "accn": "orig_accn"}))
    latest = ordered.drop_duplicates(subset=keys, keep="last")
    return latest.merge(first, on=keys).sort_values("end").reset_index(drop=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _finish(df: pd.DataFrame, is_annual: bool) -> pd.DataFrame:
    if df.empty:
        return _empty()
    if is_annual:
        df["period"] = "FY" + df["fiscal_year"].astype(str)
    else:
        df["period"] = "Q" + df["fiscal_quarter"].astype(str) + " FY" + df["fiscal_year"].astype(str)
    return df[COLUMNS].sort_values("end").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Stock splits (per-share figures only)
# ---------------------------------------------------------------------------
# After a 7-for-1 split, a company's new filings restate old EPS divided by 7. But
# periods that were never re-filed keep their old, pre-split EPS, so the history mixes
# two bases (Apple's EPS looked like it fell 86% in 2013). We find splits from the data
# itself: when the same period was filed twice and the two EPS figures differ by an exact
# split ratio, a split happened between those two filing dates.

SPLIT_RATIOS = (1.5, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 40, 50, 100)
SPLIT_TOLERANCE = 0.01   # the two figures must match a split ratio within 1%
# A real split restates many periods at once. Requiring several to agree stops a single
# accounting restatement that happens to land near a ratio (Apple, 2009: 1.5x) counting.
SPLIT_MIN_EVIDENCE = 3


@dataclass(frozen=True)
class Split:
    factor: float     # old figure ÷ new figure: 7 for a 7-for-1 split, 0.1 for 1-for-10
    after: date       # the split happened after this filing date...
    before: date      # ...and on or before this one

    @property
    def label(self) -> str:
        if self.factor >= 1:
            return f"{self.factor:g}-for-1 stock split"
        return f"1-for-{1 / self.factor:g} reverse stock split"


def _as_split_ratio(ratio: float) -> float | None:
    for candidate in SPLIT_RATIOS:
        for target in (candidate, 1 / candidate):
            if abs(ratio / target - 1) <= SPLIT_TOLERANCE:
                return target
    return None


def detect_splits(df: pd.DataFrame) -> list[Split]:
    """Find splits by comparing the same period's per-share figure across filings."""
    evidence = []
    period_cols = ["start", "end"] if "start" in df else ["end"]
    for _, group in df.groupby(period_cols):
        group = group.sort_values("filed")
        for older, newer in zip(group.to_dict("records"), group.to_dict("records")[1:]):
            if older["filed"] == newer["filed"] or not older["value"] or not newer["value"]:
                continue
            factor = _as_split_ratio(older["value"] / newer["value"])
            if factor:
                evidence.append(Split(factor, older["filed"], newer["filed"]))

    # Many periods give evidence of the same split; narrow it to the tightest window.
    splits: list[Split] = []
    counts: list[int] = []
    for ev in sorted(evidence, key=lambda s: s.before):
        for i, s in enumerate(splits):
            overlaps = max(s.after, ev.after) < min(s.before, ev.before)
            if s.factor == ev.factor and overlaps:
                splits[i] = Split(s.factor, max(s.after, ev.after), min(s.before, ev.before))
                counts[i] += 1
                break
        else:
            splits.append(ev)
            counts.append(1)
    return [s for s, n in zip(splits, counts) if n >= SPLIT_MIN_EVIDENCE]


def adjust_for_splits(df: pd.DataFrame, splits: list[Split]) -> pd.DataFrame:
    """Restate per-share figures filed before a split onto today's share basis."""
    if not splits:
        return df
    df = df.copy()
    for idx, row in df.iterrows():
        applied = [s for s in splits if row["filed"] <= s.after]
        if applied:
            total = 1.0
            for s in applied:
                total *= s.factor
            df.at[idx, "value"] = row["value"] / total
            df.at[idx, "source"] = "Adjusted for " + " and ".join(s.label for s in applied)
    return df


def build_flow_tables(rows: list[dict], fye_month: int, derive_q4: bool,
                      per_share: bool = False):
    """Annual and quarterly tables for a "flow" metric (revenue, income, EPS...)."""
    df = _to_frame(rows)
    if df.empty or "start" not in df:
        return _empty(), _empty()
    df["days"] = (pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])).dt.days + 1
    splits = detect_splits(df) if per_share else []
    df = _latest_filed(df, ["start", "end"])
    labels = df["end"].apply(lambda d: fiscal_period(d, fye_month))
    df["fiscal_year"] = labels.str[0]
    df["fiscal_quarter"] = labels.str[1]
    df["source"] = "Reported"
    df = adjust_for_splits(df, splits)

    annual = df[df["days"].between(*YEAR_DAYS)].copy()
    annual = annual.drop_duplicates(subset=["fiscal_year"], keep="last")
    quarterly = df[df["days"].between(*QUARTER_DAYS)].copy()
    quarterly = quarterly.drop_duplicates(subset=["fiscal_year", "fiscal_quarter"], keep="last")

    if derive_q4:
        quarterly = pd.concat([quarterly, _derive_q4(annual, quarterly)], ignore_index=True)

    return _finish(annual, True), _finish(quarterly, False)


def _derive_q4(annual: pd.DataFrame, quarterly: pd.DataFrame) -> pd.DataFrame:
    """Q4 = Full year - (Q1 + Q2 + Q3), only when all three quarters are known
    and the company didn't report Q4 directly."""
    derived = []
    for _, year in annual.iterrows():
        fy = year["fiscal_year"]
        same_year = quarterly[quarterly["fiscal_year"] == fy]
        if 4 in set(same_year["fiscal_quarter"]):
            continue  # Q4 was reported directly; use that instead
        q123 = same_year[same_year["fiscal_quarter"].isin([1, 2, 3])]
        if len(q123) != 3:
            continue  # can't derive without all three quarters
        # The quarters must sit inside this fiscal year (allow a week of slack).
        if (q123["start"].min() < year["start"] - timedelta(days=7)
                or q123["end"].max() > year["end"]):
            continue
        q3_end = q123["end"].max()
        derived.append({
            "fiscal_year": fy, "fiscal_quarter": 4,
            "start": q3_end + timedelta(days=1), "end": year["end"],
            "value": year["value"] - q123["value"].sum(),
            "source": "Derived (FY − Q1 − Q2 − Q3)",
            "form": year["form"], "filed": year["filed"], "accn": year["accn"],
            # A derived Q4 is first discussed in the 10-K for that year.
            "orig_form": year["orig_form"], "orig_filed": year["orig_filed"],
            "orig_accn": year["orig_accn"],
        })
    return pd.DataFrame(derived)


def build_instant_tables(rows: list[dict], fye_month: int):
    """Annual and quarterly tables for a balance-sheet metric (a value at a date)."""
    df = _to_frame(rows)
    if df.empty:
        return _empty(), _empty()
    df = _latest_filed(df, ["end"])
    df = df[df["end"].apply(lambda d: is_quarter_end(d, fye_month))].copy()
    labels = df["end"].apply(lambda d: fiscal_period(d, fye_month))
    df["fiscal_year"] = labels.str[0]
    df["fiscal_quarter"] = labels.str[1]
    df["start"] = None
    df["source"] = "Reported"
    quarterly = df.drop_duplicates(subset=["fiscal_year", "fiscal_quarter"], keep="last")
    annual = quarterly[quarterly["fiscal_quarter"] == 4].copy()
    return _finish(annual, True), _finish(quarterly.copy(), False)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_metric(facts: dict, metric: Metric, fye_month: int) -> MetricData:
    choice = choose_label(facts, metric)
    if choice is None:
        return MetricData(metric, None, _empty(), _empty())
    rows = _rows_for(facts, choice.label, metric.unit)
    if metric.kind == "flow":
        annual, quarterly = build_flow_tables(rows, fye_month, metric.derive_q4,
                                              per_share=metric.unit == "USD/shares")
    else:
        annual, quarterly = build_instant_tables(rows, fye_month)
    return MetricData(metric, choice, annual, quarterly)


# A metric whose latest data is this far behind the company's newest data is treated as
# "no longer reported" rather than shown as if it were current.
DISCONTINUED_AFTER_DAYS = 400


def mark_discontinued(results: dict[str, MetricData]) -> None:
    ends = [date.fromisoformat(md.choice.latest_end) for md in results.values() if md.choice]
    if not ends:
        return
    newest = max(ends)
    for md in results.values():
        if md.choice:
            gap = (newest - date.fromisoformat(md.choice.latest_end)).days
            md.discontinued = gap > DISCONTINUED_AFTER_DAYS


def load_all_metrics(facts: dict, fye_month: int) -> dict[str, MetricData]:
    results = {m.key: load_metric(facts, m, fye_month) for m in METRICS}
    mark_discontinued(results)
    return results
