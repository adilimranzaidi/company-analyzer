"""Checks for the data-cleaning rules in analyzer/financials.py.

Each test builds a tiny, made-up version of the SEC's data where the right answer is
known in advance, then checks the code gets exactly that answer.
"""

from datetime import date

import pytest

from analyzer.financials import (
    Metric,
    build_flow_tables,
    build_instant_tables,
    choose_label,
    fiscal_period,
    load_all_metrics,
)


def fact(start, end, value, filed="2026-01-01", form="10-Q", accn="0001"):
    """One SEC fact row, in the same shape as the real data."""
    row = {"end": end, "val": value, "filed": filed, "form": form, "accn": accn}
    if start:
        row["start"] = start
    return row


def facts_with(labels: dict[str, list[dict]], unit="USD") -> dict:
    """A minimal 'company facts' file containing the given labels."""
    return {"facts": {"us-gaap": {lbl: {"units": {unit: rows}} for lbl, rows in labels.items()}}}


# A full calendar year 2025: three reported quarters plus the annual total.
YEAR_2025 = [
    fact("2025-01-01", "2025-03-31", 100),                         # Q1
    fact("2025-04-01", "2025-06-30", 110),                         # Q2
    fact("2025-07-01", "2025-09-30", 120),                         # Q3
    fact("2025-01-01", "2025-12-31", 450, form="10-K", filed="2026-02-10"),  # full year
]


# --- Choosing a label -------------------------------------------------------

REVENUE = Metric("revenue", "Revenue", ("Revenues", "RevenuesNetOfInterestExpense"), "flow")


def test_label_with_most_recent_data_wins():
    # Like AmEx: "Revenues" stops in 2010, the newer label is current.
    facts = facts_with({
        "Revenues": [fact("2010-01-01", "2010-12-31", 1)],
        "RevenuesNetOfInterestExpense": [fact("2025-01-01", "2025-12-31", 2)],
    })
    choice = choose_label(facts, REVENUE)
    assert choice.label == "RevenuesNetOfInterestExpense"
    assert choice.passed_over == [("Revenues", "2010-12-31")]


def test_tie_goes_to_the_preferred_label():
    facts = facts_with({
        "Revenues": [fact("2025-01-01", "2025-12-31", 1)],
        "RevenuesNetOfInterestExpense": [fact("2025-01-01", "2025-12-31", 2)],
    })
    assert choose_label(facts, REVENUE).label == "Revenues"


def test_no_matching_label_returns_none():
    assert choose_label(facts_with({"SomethingElse": [fact(None, "2025-12-31", 1)]}), REVENUE) is None


# --- Fiscal quarter labels --------------------------------------------------

@pytest.mark.parametrize("end, fye_month, expected", [
    (date(2025, 3, 31), 12, (2025, 1)),    # calendar-year company (AmEx)
    (date(2025, 12, 31), 12, (2025, 4)),
    (date(2025, 12, 27), 9, (2026, 1)),    # Apple: FY ends in September
    (date(2026, 6, 27), 9, (2026, 3)),
    (date(2025, 9, 27), 9, (2025, 4)),
    (date(2022, 10, 1), 9, (2022, 4)),     # 53-week year ending just into October
])
def test_fiscal_period(end, fye_month, expected):
    assert fiscal_period(end, fye_month) == expected


# --- Flow metrics (revenue, income) ----------------------------------------

def test_q4_is_derived_as_full_year_minus_three_quarters():
    annual, quarterly = build_flow_tables(YEAR_2025, 12, derive_q4=True)
    q4 = quarterly[quarterly["period"] == "Q4 FY2025"].iloc[0]
    assert q4["value"] == 450 - (100 + 110 + 120)   # = 120
    assert q4["source"].startswith("Derived")
    assert list(annual["value"]) == [450]


def test_year_to_date_totals_are_not_treated_as_quarters():
    # A Q2 10-Q also reports the 6-month total. It must not appear as a quarter.
    rows = YEAR_2025 + [fact("2025-01-01", "2025-06-30", 210)]
    _, quarterly = build_flow_tables(rows, 12, derive_q4=True)
    assert 210 not in list(quarterly["value"])
    assert len(quarterly) == 4


def test_most_recently_filed_value_wins_for_revised_numbers():
    rows = YEAR_2025 + [fact("2025-01-01", "2025-03-31", 105, filed="2026-04-30", accn="0002")]
    _, quarterly = build_flow_tables(rows, 12, derive_q4=True)
    assert quarterly[quarterly["period"] == "Q1 FY2025"]["value"].iloc[0] == 105
    # ...and the derived Q4 uses the revised Q1: 450 - (105 + 110 + 120) = 115
    assert quarterly[quarterly["period"] == "Q4 FY2025"]["value"].iloc[0] == 115


def test_q4_not_derived_when_a_quarter_is_missing():
    rows = [r for r in YEAR_2025 if r["end"] != "2025-06-30"]   # drop Q2
    _, quarterly = build_flow_tables(rows, 12, derive_q4=True)
    assert "Q4 FY2025" not in list(quarterly["period"])


def test_q4_not_derived_for_per_share_figures():
    _, quarterly = build_flow_tables(YEAR_2025, 12, derive_q4=False)
    assert "Q4 FY2025" not in list(quarterly["period"])


def test_reported_q4_is_used_instead_of_derived():
    rows = YEAR_2025 + [fact("2025-10-01", "2025-12-31", 121, form="10-K")]
    _, quarterly = build_flow_tables(rows, 12, derive_q4=True)
    q4 = quarterly[quarterly["period"] == "Q4 FY2025"]
    assert len(q4) == 1
    assert q4["value"].iloc[0] == 121
    assert q4["source"].iloc[0] == "Reported"


# --- Balance-sheet metrics --------------------------------------------------

def test_balance_sheet_annual_values_are_fiscal_year_end_values():
    rows = [
        fact(None, "2025-03-31", 10), fact(None, "2025-06-30", 20),
        fact(None, "2025-09-30", 30), fact(None, "2025-12-31", 40, form="10-K"),
    ]
    annual, quarterly = build_instant_tables(rows, 12)
    assert list(annual["value"]) == [40]
    assert list(quarterly["period"]) == ["Q1 FY2025", "Q2 FY2025", "Q3 FY2025", "Q4 FY2025"]


def test_balance_sheet_ignores_dates_that_are_not_quarter_ends():
    rows = [fact(None, "2025-03-31", 10), fact(None, "2025-05-15", 99)]
    _, quarterly = build_instant_tables(rows, 12)
    assert list(quarterly["value"]) == [10]


# --- Discontinued metrics ---------------------------------------------------

def test_metric_that_stopped_long_ago_is_marked_discontinued():
    # Like AmEx's operating income: last reported in 2010.
    facts = facts_with({
        "NetIncomeLoss": YEAR_2025,
        "OperatingIncomeLoss": [fact("2010-01-01", "2010-12-31", 5, form="10-K")],
    })
    results = load_all_metrics(facts, 12)
    assert results["net_income"].available
    assert results["operating_income"].discontinued
    assert not results["operating_income"].available
    assert not results["gross_profit"].has_data   # never reported at all


def test_original_filing_is_remembered_when_a_number_is_re_reported():
    # Q1 2025 first appears in the Q1 10-Q, then again a year later as a comparison.
    rows = YEAR_2025 + [fact("2025-01-01", "2025-03-31", 100, filed="2026-04-30",
                             accn="0002")]
    _, quarterly = build_flow_tables(rows, 12, derive_q4=True)
    q1 = quarterly[quarterly["period"] == "Q1 FY2025"].iloc[0]
    assert str(q1["filed"]) == "2026-04-30"        # latest filing supplies the value
    assert str(q1["orig_filed"]) == "2026-01-01"   # original filing is kept for context
    assert q1["orig_accn"] == "0001"


def test_derived_q4_points_to_the_annual_report():
    _, quarterly = build_flow_tables(YEAR_2025, 12, derive_q4=True)
    q4 = quarterly[quarterly["period"] == "Q4 FY2025"].iloc[0]
    assert q4["orig_form"] == "10-K"


def test_lender_revenue_is_calculated_when_not_reported():
    # Like Synchrony: no revenue label, but net interest income and noninterest income.
    def year(nii_scale):
        return [fact("2025-01-01", "2025-03-31", 10 * nii_scale),
                fact("2025-04-01", "2025-06-30", 11 * nii_scale),
                fact("2025-07-01", "2025-09-30", 12 * nii_scale),
                fact("2025-01-01", "2025-12-31", 46 * nii_scale, form="10-K",
                     filed="2026-02-10")]
    facts = facts_with({"InterestIncomeExpenseNet": year(1),
                        "NoninterestIncome": year(0.5),
                        "NetIncomeLoss": YEAR_2025})
    revenue = load_all_metrics(facts, 12)["revenue"]
    assert revenue.available
    assert list(revenue.annual["value"]) == [46 + 23]               # 46 + 46 * 0.5
    q4 = revenue.quarterly[revenue.quarterly["period"] == "Q4 FY2025"].iloc[0]
    assert q4["value"] == pytest.approx((46 - 33) + (23 - 16.5))     # derived Q4s added
    assert "Calculated" in revenue.annual["source"].iloc[0]
    assert revenue.choice.label == "InterestIncomeExpenseNet + NoninterestIncome"


def test_reported_revenue_is_never_replaced_by_the_calculation():
    facts = facts_with({"Revenues": YEAR_2025, "InterestIncomeExpenseNet": YEAR_2025,
                        "NoninterestIncome": YEAR_2025})
    revenue = load_all_metrics(facts, 12)["revenue"]
    assert revenue.choice.label == "Revenues"
    assert list(revenue.annual["value"]) == [450]
