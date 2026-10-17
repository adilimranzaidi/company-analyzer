"""Side-by-side numbers for comparing companies and summarizing an industry.

Companies have different fiscal years (Apple's ends in September, AmEx's in December),
so each snapshot uses that company's own latest fiscal year and labels it. Growth rates
and ratios still compare fairly across different year-ends; dollar sizes are shown
as-is.
"""

from statistics import median

import pandas as pd

from analyzer.financials import MetricData
from analyzer.metrics import add_growth, margin_tables, roe_annual, roe_trailing


def _latest(df: pd.DataFrame):
    return df.iloc[-1] if df is not None and not df.empty else None


def snapshot(metrics: dict[str, MetricData]) -> dict:
    """Key latest figures for one company. Missing items are None, never guessed."""
    out = {
        "fiscal_year": None, "revenue": None, "revenue_growth": None,
        "net_income": None, "net_income_growth": None, "eps": None, "eps_growth": None,
        "net_margin": None, "operating_margin": None, "roe": None, "total_assets": None,
        "latest_quarter": None, "quarter_revenue_growth": None,
    }

    def annual(key):
        md = metrics.get(key)
        return add_growth(md.annual, quarterly=False) if md and md.available else None

    rev, ni, eps = annual("revenue"), annual("net_income"), annual("eps_diluted")
    if (last := _latest(rev)) is not None:
        out.update(fiscal_year=last["period"], revenue=last["value"],
                   revenue_growth=last["yoy_growth"])
    if (last := _latest(ni)) is not None:
        out.update(net_income=last["value"], net_income_growth=last["yoy_growth"])
        out["fiscal_year"] = out["fiscal_year"] or last["period"]
    if (last := _latest(eps)) is not None:
        out.update(eps=last["value"], eps_growth=last["yoy_growth"])

    margins = margin_tables(metrics, quarterly=False)
    for key in ("net_margin", "operating_margin"):
        if key in margins and (last := _latest(margins[key][1])) is not None:
            # Only use the margin if it's for the same year as the headline figures.
            if last["period"] == out["fiscal_year"]:
                out[key] = last["value"]

    ni_md, eq_md = metrics.get("net_income"), metrics.get("equity")
    if ni_md and eq_md and ni_md.available and eq_md.available:
        roe = _latest(roe_annual(ni_md.annual, eq_md.annual))
        if roe is not None and roe["period"] == out["fiscal_year"]:
            out["roe"] = roe["value"]

    assets = metrics.get("total_assets")
    if assets and assets.available and (last := _latest(assets.annual)) is not None:
        out["total_assets"] = last["value"]

    rev_md = metrics.get("revenue")
    if rev_md and rev_md.available:
        q = _latest(add_growth(rev_md.quarterly, quarterly=True))
        if q is not None:
            out.update(latest_quarter=q["period"], quarter_revenue_growth=q["yoy_growth"])
    return out


def trailing_roe_latest(metrics: dict[str, MetricData]):
    ni, eq = metrics.get("net_income"), metrics.get("equity")
    if not (ni and eq and ni.available and eq.available):
        return None
    return _latest(roe_trailing(ni.quarterly, eq.quarterly))


def industry_medians(snapshots: list[dict]) -> dict:
    """The middle value of each growth rate and ratio across a group of companies.
    The median is used rather than the average so one unusual company can't skew it."""
    keys = ["revenue_growth", "net_income_growth", "eps_growth", "net_margin",
            "operating_margin", "roe", "quarter_revenue_growth"]
    result = {}
    for key in keys:
        values = [s[key] for s in snapshots if s.get(key) is not None and not pd.isna(s[key])]
        result[key] = median(values) if values else None
        result[f"{key}_count"] = len(values)
    return result


def rank_in_group(value, others: list) -> tuple[int, int] | None:
    """Where a value ranks in a group, highest first: (2, 7) means 2nd of 7."""
    pool = [v for v in others if v is not None and not pd.isna(v)]
    if value is None or pd.isna(value):
        return None
    pool.append(value)
    return sorted(pool, reverse=True).index(value) + 1, len(pool)


def growth_series(md: MetricData, quarterly: bool) -> pd.DataFrame:
    """Year-over-year growth over time for one metric: used for comparison charts, where
    growth (not dollar size) makes companies of very different sizes comparable."""
    if md is None or not md.available:
        return pd.DataFrame(columns=["period", "end", "value"])
    df = add_growth(md.quarterly if quarterly else md.annual, quarterly)
    df = df.dropna(subset=["yoy_growth"])
    return df.assign(value=df["yoy_growth"])[["period", "end", "value"]]
