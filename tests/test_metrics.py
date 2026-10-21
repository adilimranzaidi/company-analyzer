"""Checks for growth rates, margins, ROE, unusual-change detection and stock splits.

Every expected answer is worked out by hand in the comments, so each test doubles as an
explanation of the formula.
"""

from datetime import date

import pandas as pd
import pytest

from analyzer.financials import adjust_for_splits, build_flow_tables, detect_splits
from analyzer.metrics import (
    add_growth,
    flag_outliers,
    growth_rate,
    ratio_table,
    roe_annual,
    roe_trailing,
)


def table(rows, quarterly=True):
    """Build a cleaned table like financials.py produces. rows: (fy, q, value[, end])."""
    out = []
    for r in rows:
        fy, q, value = r[:3]
        end = r[3] if len(r) > 3 else date(fy, q * 3, 28)
        out.append({
            "period": f"Q{q} FY{fy}" if quarterly else f"FY{fy}",
            "fiscal_year": fy, "fiscal_quarter": q, "start": None, "end": end,
            "value": value, "source": "Reported", "form": "10-Q", "filed": end,
        })
    return pd.DataFrame(out)


# --- Growth ---------------------------------------------------------------

def test_growth_rate_basic():
    assert growth_rate(110, 100) == pytest.approx(0.10)    # +10%
    assert growth_rate(90, 100) == pytest.approx(-0.10)    # -10%


@pytest.mark.parametrize("prior", [0, -5, None, float("nan")])
def test_growth_not_meaningful_from_zero_negative_or_missing(prior):
    assert growth_rate(10, prior) is None


def test_yoy_compares_same_quarter_last_year():
    df = add_growth(table([(2024, 1, 100), (2024, 2, 120), (2025, 1, 110), (2025, 2, 150)]), True)
    q2_2025 = df[df["period"] == "Q2 FY2025"].iloc[0]
    assert q2_2025["yoy_growth"] == pytest.approx(0.25)   # 150 vs 120
    assert q2_2025["qoq_growth"] == pytest.approx(150 / 110 - 1)


def test_q1_qoq_compares_with_previous_years_q4():
    df = add_growth(table([(2024, 4, 200), (2025, 1, 180)]), True)
    assert df.iloc[-1]["qoq_growth"] == pytest.approx(-0.10)  # 180 vs 200


def test_missing_quarter_gives_no_growth_rather_than_wrong_growth():
    # Q2 FY2024 is missing, so Q2 FY2025 must NOT be compared with some other quarter.
    df = add_growth(table([(2024, 1, 100), (2025, 1, 110), (2025, 2, 150)]), True)
    assert pd.isna(df[df["period"] == "Q2 FY2025"].iloc[0]["yoy_growth"])


def test_annual_growth():
    df = add_growth(table([(2023, 4, 50), (2024, 4, 60)], quarterly=False), False)
    assert df.iloc[-1]["yoy_growth"] == pytest.approx(0.20)


# --- Margins --------------------------------------------------------------

def test_margin_is_numerator_over_denominator_for_same_period():
    revenue = table([(2025, 1, 200), (2025, 2, 250)])
    net_income = table([(2025, 1, 30), (2025, 2, 50)])
    df = ratio_table(net_income, revenue, quarterly=True)
    assert list(df["value"]) == pytest.approx([0.15, 0.20])   # 30/200, 50/250


def test_margin_skipped_when_a_period_is_missing_or_revenue_not_positive():
    revenue = table([(2025, 1, 200), (2025, 2, 0)])
    net_income = table([(2025, 1, 30), (2025, 2, 5), (2025, 3, 9)])
    df = ratio_table(net_income, revenue, quarterly=True)
    assert list(df["period"]) == ["Q1 FY2025"]


def test_margin_marks_derived_inputs():
    revenue = table([(2025, 4, 200)])
    revenue.loc[0, "source"] = "Derived (FY − Q1 − Q2 − Q3)"
    df = ratio_table(table([(2025, 4, 20)]), revenue, quarterly=True)
    assert "Derived" in df.iloc[0]["source"]


# --- Return on equity -----------------------------------------------------

def test_annual_roe_uses_average_equity():
    ni = table([(2025, 4, 10)], quarterly=False)
    eq = table([(2024, 4, 40), (2025, 4, 60)], quarterly=False)
    # 10 / ((40 + 60) / 2) = 10 / 50 = 20%
    assert roe_annual(ni, eq).iloc[0]["value"] == pytest.approx(0.20)


def test_trailing_roe_sums_four_quarters():
    ni = table([(2024, 3, 1), (2024, 4, 2), (2025, 1, 3), (2025, 2, 4)])
    eq = table([(2024, 2, 45), (2025, 2, 55)])
    # (1+2+3+4) / ((55 + 45) / 2) = 10 / 50 = 20%
    df = roe_trailing(ni, eq)
    assert len(df) == 1
    assert df.iloc[0]["value"] == pytest.approx(0.20)


def test_trailing_roe_needs_all_four_quarters():
    ni = table([(2024, 3, 1), (2025, 1, 3), (2025, 2, 4)])   # Q4 FY2024 missing
    eq = table([(2024, 2, 45), (2025, 2, 55)])
    assert roe_trailing(ni, eq).empty


# --- Unusual changes ------------------------------------------------------

def steady_with_spike(spike):
    """Ten years of ~5% growth, then one year of `spike` growth."""
    growth = [0.04, 0.05, 0.06, 0.05, 0.04, 0.06, 0.05, 0.05, 0.04, 0.06, spike]
    return pd.DataFrame({"yoy_growth": growth})


def test_big_spike_is_flagged():
    df = flag_outliers(steady_with_spike(0.60))
    assert bool(df.iloc[-1]["is_unusual"])
    assert df["is_unusual"].sum() == 1


def test_normal_year_is_not_flagged():
    assert not flag_outliers(steady_with_spike(0.055))["is_unusual"].any()


def test_tiny_change_in_a_very_steady_metric_is_not_flagged():
    # Statistically unusual (steady series) but only ~3 points from normal: below the
    # 10-point minimum, so not worth flagging.
    assert not flag_outliers(steady_with_spike(0.08))["is_unusual"].any()


def test_not_enough_history_means_no_flags():
    assert not flag_outliers(pd.DataFrame({"yoy_growth": [0.05, 0.05, 0.9]}))["is_unusual"].any()


def test_higher_threshold_flags_less():
    df = steady_with_spike(0.18)   # 13 points above normal: unusual at 3, not at 10
    assert flag_outliers(df, threshold=3)["is_unusual"].any()
    assert not flag_outliers(df, threshold=10)["is_unusual"].any()


# --- Stock splits ---------------------------------------------------------

def eps_row(start, end, value, filed):
    return {"start": date.fromisoformat(start), "end": date.fromisoformat(end),
            "value": value, "filed": date.fromisoformat(filed), "accn": filed, "form": "10-Q"}


def split_history():
    """EPS for four quarters filed before a 4-for-1 split, three re-filed after it."""
    rows = []
    quarters = [("2019-01-01", "2019-03-31"), ("2019-04-01", "2019-06-30"),
                ("2019-07-01", "2019-09-30"), ("2019-10-01", "2019-12-31")]
    for (s, e), eps in zip(quarters, [4.0, 4.4, 4.8, 5.2], strict=True):
        rows.append(eps_row(s, e, eps, "2020-01-15"))            # original, pre-split
    for (s, e), eps in zip(quarters[1:], [4.4, 4.8, 5.2], strict=True):
        rows.append(eps_row(s, e, eps / 4, "2020-10-15"))        # restated after split
    return pd.DataFrame(rows)


def test_split_is_detected_from_restated_figures():
    splits = detect_splits(split_history())
    assert len(splits) == 1
    assert splits[0].factor == 4
    assert splits[0].label == "4-for-1 stock split"


def test_single_coincidence_is_not_called_a_split():
    one = split_history().iloc[[1, 4]]    # only one period filed twice
    assert detect_splits(one) == []


def test_pre_split_figures_are_adjusted_and_labelled():
    df = pd.DataFrame([{"value": 4.0, "filed": date(2020, 1, 15), "source": "Reported"},
                       {"value": 1.3, "filed": date(2020, 10, 15), "source": "Reported"}])
    splits = detect_splits(split_history())
    adjusted = adjust_for_splits(df, splits)
    assert adjusted.iloc[0]["value"] == pytest.approx(1.0)      # 4.0 / 4
    assert "4-for-1" in adjusted.iloc[0]["source"]
    assert adjusted.iloc[1]["value"] == pytest.approx(1.3)      # filed after: unchanged


def test_eps_table_is_split_adjusted_end_to_end():
    raw = split_history().rename(columns={"value": "val"})
    raw["start"] = raw["start"].astype(str)
    raw["end"] = raw["end"].astype(str)
    raw["filed"] = raw["filed"].astype(str)
    _, quarterly = build_flow_tables(raw.to_dict("records"), 12, derive_q4=False, per_share=True)
    # Q1 2019 was never re-filed: 4.0 pre-split -> 1.0 on today's basis.
    assert quarterly.iloc[0]["value"] == pytest.approx(1.0)
    assert list(quarterly["value"]) == pytest.approx([1.0, 1.1, 1.2, 1.3])
