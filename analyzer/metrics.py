"""Growth rates, margins, return on equity, and unusual-change detection.

Every ratio in the app is calculated here, in plain Python, from the cleaned tables that
financials.py produces. Periods are always matched by their fiscal labels (e.g. Q2 FY2025
against Q2 FY2024), never by row position, so a missing quarter can't shift a comparison.

Formulas
- Year-over-year growth   = (this period - same period last year) / same period last year
- Quarter-over-quarter    = (this quarter - previous quarter) / previous quarter
- Margin                  = profit measure / revenue, for the same period
- Return on equity (ROE)  = net income / average shareholders' equity
    annual:    fiscal-year net income / average of equity at the start and end of the year
    quarterly: last four quarters' net income / average of equity now and four quarters ago

Growth is "not meaningful" (shown as n/m) when the earlier value is zero or negative:
going from a $1M loss to a $1M profit isn't "+200% growth".
"""

import math
from dataclasses import dataclass

import pandas as pd

from analyzer.financials import MetricData


def growth_rate(current: float, prior: float) -> float | None:
    """Percentage change as a decimal (0.12 = +12%), or None when not meaningful."""
    if current is None or prior is None or pd.isna(current) or pd.isna(prior) or prior <= 0:
        return None
    return (current - prior) / prior


def _key(row) -> tuple[int, int]:
    return int(row["fiscal_year"]), int(row["fiscal_quarter"])


def _previous_quarter(fy: int, q: int) -> tuple[int, int]:
    return (fy, q - 1) if q > 1 else (fy - 1, 4)


# ---------------------------------------------------------------------------
# Growth
# ---------------------------------------------------------------------------

def add_growth(df: pd.DataFrame, quarterly: bool) -> pd.DataFrame:
    """Add year-over-year (and, for quarters, quarter-over-quarter) growth columns."""
    out = df.copy()
    if out.empty:
        for col in ["prior_year_value", "yoy_growth", "prior_quarter_value", "qoq_growth"]:
            out[col] = pd.Series(dtype="float64")
        return out

    if quarterly:
        values = {_key(r): r["value"] for _, r in out.iterrows()}
        out["prior_year_value"] = [values.get((fy - 1, q)) for fy, q in map(_key, out.to_dict("records"))]
        out["prior_quarter_value"] = [values.get(_previous_quarter(*_key(r))) for r in out.to_dict("records")]
        out["qoq_growth"] = [growth_rate(c, p) for c, p in zip(out["value"], out["prior_quarter_value"])]
    else:
        values = {int(r["fiscal_year"]): r["value"] for _, r in out.iterrows()}
        out["prior_year_value"] = [values.get(int(fy) - 1) for fy in out["fiscal_year"]]
        out["prior_quarter_value"] = None
        out["qoq_growth"] = None
    out["yoy_growth"] = [growth_rate(c, p) for c, p in zip(out["value"], out["prior_year_value"])]
    return out


# ---------------------------------------------------------------------------
# Unusual changes ("notable events")
# ---------------------------------------------------------------------------

# Defaults, explained:
# - THRESHOLD: how many "typical deviations" away from normal a change must be. 3 is a
#   common statistical cut-off for "rare" (roughly the outer 0.3% for normal data).
# - MIN_HISTORY: need at least this many growth figures to know what "normal" is.
# - MIN_GAP: also require the change to differ from normal by at least 10 percentage
#   points, so very steady metrics don't flag tiny wiggles.
OUTLIER_THRESHOLD = 3.0
OUTLIER_MIN_HISTORY = 8
OUTLIER_MIN_GAP = 0.10


def flag_outliers(df: pd.DataFrame, threshold: float = OUTLIER_THRESHOLD,
                  min_history: int = OUTLIER_MIN_HISTORY,
                  min_gap: float = OUTLIER_MIN_GAP) -> pd.DataFrame:
    """Mark periods whose year-over-year growth is unusual for this company.

    "Normal" is the median growth across the company's history. "Typical deviation" is
    the median absolute deviation (MAD), scaled so it's comparable to a standard
    deviation. The median and MAD are used instead of the average and standard
    deviation because a few extreme years (like 2020) would otherwise distort what
    counts as normal, and hide the very outliers we're looking for.
    """
    out = df.copy()
    out["typical_growth"] = None
    out["unusual_score"] = None
    out["is_unusual"] = False
    growth = pd.to_numeric(out.get("yoy_growth"), errors="coerce").dropna()
    if len(growth) < min_history:
        return out

    median = growth.median()
    mad = (growth - median).abs().median() * 1.4826
    out["typical_growth"] = median
    for idx, g in growth.items():
        gap = abs(g - median)
        score = gap / mad if mad > 0 else math.inf
        out.at[idx, "unusual_score"] = score
        out.at[idx, "is_unusual"] = bool(score > threshold and gap >= min_gap)
    return out


# ---------------------------------------------------------------------------
# Margins
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Ratio:
    key: str
    name: str
    numerator: str
    denominator: str
    formula: str


MARGINS: tuple[Ratio, ...] = (
    Ratio("gross_margin", "Gross margin", "gross_profit", "revenue", "Gross profit ÷ Revenue"),
    Ratio("operating_margin", "Operating margin", "operating_income", "revenue",
          "Operating income ÷ Revenue"),
    Ratio("net_margin", "Net margin", "net_income", "revenue", "Net income ÷ Revenue"),
)

RATIO_COLUMNS = ["period", "fiscal_year", "fiscal_quarter", "end", "value",
                 "numerator", "denominator", "source"]


def _source(*sources: str) -> str:
    """A ratio inherits "derived" if any input was derived."""
    notes = sorted({s for s in sources if s and s != "Reported"})
    return "Reported inputs" if not notes else "Uses " + "; ".join(notes)


def ratio_table(num: pd.DataFrame, den: pd.DataFrame, quarterly: bool) -> pd.DataFrame:
    """Divide two metrics period by period. Skips periods where either is missing or the
    denominator isn't positive."""
    if num.empty or den.empty:
        return pd.DataFrame(columns=RATIO_COLUMNS)
    keys = ["fiscal_year", "fiscal_quarter"] if quarterly else ["fiscal_year"]
    merged = num.merge(den, on=keys, suffixes=("_num", "_den"))
    merged = merged[merged["value_den"] > 0]
    rows = []
    for _, r in merged.iterrows():
        # Same period end, give or take a few days, or the pair isn't comparable.
        if abs((r["end_num"] - r["end_den"]).days) > 7:
            continue
        rows.append({
            "period": r["period_num"], "fiscal_year": r["fiscal_year"],
            "fiscal_quarter": r["fiscal_quarter_num"] if not quarterly else r["fiscal_quarter"],
            "end": r["end_num"], "value": r["value_num"] / r["value_den"],
            "numerator": r["value_num"], "denominator": r["value_den"],
            "source": _source(r["source_num"], r["source_den"]),
        })
    return pd.DataFrame(rows, columns=RATIO_COLUMNS).sort_values("end").reset_index(drop=True)


def calculated_gross_profit(metrics: dict[str, MetricData], quarterly: bool) -> pd.DataFrame:
    """Revenue - Cost of revenue, for companies that report both but not gross profit."""
    rev, cost = metrics.get("revenue"), metrics.get("cost_of_revenue")
    if not (rev and cost and rev.available and cost.available):
        return pd.DataFrame()
    r = rev.quarterly if quarterly else rev.annual
    c = cost.quarterly if quarterly else cost.annual
    keys = ["fiscal_year", "fiscal_quarter"] if quarterly else ["fiscal_year"]
    m = r.merge(c, on=keys, suffixes=("", "_cost"))
    m = m[(m["end"] - m["end_cost"]).apply(lambda d: abs(d.days) <= 7)]
    if m.empty:
        return pd.DataFrame()
    m["value"] = m["value"] - m["value_cost"]
    m["source"] = "Calculated: Revenue − Cost of revenue"
    return m[["period", "fiscal_year", "fiscal_quarter", "end", "value", "source"]]


def margin_tables(metrics: dict[str, MetricData], quarterly: bool) -> dict[str, tuple[Ratio, pd.DataFrame]]:
    """Every margin that can be calculated for this company."""
    def table(key: str) -> pd.DataFrame:
        md = metrics.get(key)
        if md is None or not md.available:
            if key == "gross_profit":
                return calculated_gross_profit(metrics, quarterly)
            return pd.DataFrame()
        return md.quarterly if quarterly else md.annual

    results = {}
    for ratio in MARGINS:
        num, den = table(ratio.numerator), table(ratio.denominator)
        if num.empty or den.empty:
            continue
        df = ratio_table(num, den, quarterly)
        if not df.empty:
            results[ratio.key] = (ratio, df)
    return results


# ---------------------------------------------------------------------------
# Return on equity
# ---------------------------------------------------------------------------

def roe_annual(net_income: pd.DataFrame, equity: pd.DataFrame) -> pd.DataFrame:
    """Fiscal-year net income / average of equity at the start and end of the year."""
    if net_income.empty or equity.empty:
        return pd.DataFrame(columns=RATIO_COLUMNS)
    eq = {int(r["fiscal_year"]): r["value"] for _, r in equity.iterrows()}
    rows = []
    for _, r in net_income.iterrows():
        fy = int(r["fiscal_year"])
        if fy in eq and fy - 1 in eq:
            avg = (eq[fy] + eq[fy - 1]) / 2
            if avg > 0:
                rows.append({"period": r["period"], "fiscal_year": fy, "fiscal_quarter": 4,
                             "end": r["end"], "value": r["value"] / avg,
                             "numerator": r["value"], "denominator": avg,
                             "source": _source(r["source"])})
    return pd.DataFrame(rows, columns=RATIO_COLUMNS)


def roe_trailing(net_income_q: pd.DataFrame, equity_q: pd.DataFrame) -> pd.DataFrame:
    """Last four quarters' net income / average of equity now and four quarters ago."""
    if net_income_q.empty or equity_q.empty:
        return pd.DataFrame(columns=RATIO_COLUMNS)
    ni = {_key(r): (r["value"], r["source"]) for r in net_income_q.to_dict("records")}
    eq = {_key(r): r["value"] for r in equity_q.to_dict("records")}
    rows = []
    for r in net_income_q.to_dict("records"):
        k = _key(r)
        window = [k]
        for _ in range(3):
            window.append(_previous_quarter(*window[-1]))
        year_ago = _previous_quarter(*window[-1])
        if not all(w in ni for w in window) or k not in eq or year_ago not in eq:
            continue
        ttm = sum(ni[w][0] for w in window)
        avg = (eq[k] + eq[year_ago]) / 2
        if avg > 0:
            rows.append({"period": r["period"], "fiscal_year": k[0], "fiscal_quarter": k[1],
                         "end": r["end"], "value": ttm / avg, "numerator": ttm,
                         "denominator": avg, "source": _source(*(ni[w][1] for w in window))})
    return pd.DataFrame(rows, columns=RATIO_COLUMNS)


# ---------------------------------------------------------------------------
# Notable events: all unusual changes across metrics, newest first
# ---------------------------------------------------------------------------

def notable_events(metrics: dict[str, MetricData], quarterly: bool,
                   threshold: float = OUTLIER_THRESHOLD) -> pd.DataFrame:
    rows = []
    for md in metrics.values():
        if not md.available:
            continue
        df = md.quarterly if quarterly else md.annual
        flagged = flag_outliers(add_growth(df, quarterly), threshold=threshold)
        for _, r in flagged[flagged["is_unusual"]].iterrows():
            rows.append({
                "metric_key": md.metric.key, "metric": md.metric.name, "unit": md.metric.unit,
                "period": r["period"], "end": r["end"], "value": r["value"],
                "prior_year_value": r["prior_year_value"], "yoy_growth": r["yoy_growth"],
                "typical_growth": r["typical_growth"], "unusual_score": r["unusual_score"],
                "source": r["source"], "form": r["form"], "filed": r["filed"],
                "orig_form": r["orig_form"], "orig_filed": r["orig_filed"],
                "orig_accn": r["orig_accn"],
            })
    cols = ["metric_key", "metric", "unit", "period", "end", "value", "prior_year_value",
            "yoy_growth", "typical_growth", "unusual_score", "source", "form", "filed",
            "orig_form", "orig_filed", "orig_accn"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols).sort_values("end", ascending=False).reset_index(drop=True)
