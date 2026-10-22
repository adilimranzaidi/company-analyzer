"""Checks for the web dashboard's data layer: every number it shows is calculated here,
in Python, so these rules are tested like the rest of the analyzer."""

import threading
import time

import pytest

from analyzer.financials import load_all_metrics
from tests.test_financials import fact, facts_with
from webapp import payloads, service


def test_num_turns_missing_values_into_none():
    assert payloads.num(1.5) == 1.5
    assert payloads.num(None) is None
    assert payloads.num(float("nan")) is None
    assert payloads.num("abc") is None


def test_year_earlier_label():
    assert payloads._year_earlier("Q2 FY2026") == "Q2 FY2025"
    assert payloads._year_earlier("FY2026") == ""


def _quarters(values: list[float], start_year: int = 2023):
    """Quarterly revenue facts, Q1 of start_year onwards (one value per quarter)."""
    rows, year, q = [], start_year, 1
    month_ends = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    month_starts = {1: "01-01", 2: "04-01", 3: "07-01", 4: "10-01"}
    for v in values:
        rows.append(fact(f"{year}-{month_starts[q]}", f"{year}-{month_ends[q]}", v))
        q += 1
        if q == 5:
            q, year = 1, year + 1
    return rows


def test_takeaway_counts_the_current_growth_streak():
    # 2023: 100,100,100,100; 2024: 90 (down), then 3 quarters up vs 2023.
    facts = facts_with({"Revenues": _quarters([100, 100, 100, 100, 90, 110, 120, 130])})
    metrics = load_all_metrics(facts, 12)
    series = {"revenue": {"quarterly": payloads._rows(metrics["revenue"].quarterly, True)}}
    first = payloads._takeaways(metrics, series)[0]
    assert first["title"] == "3 straight quarters of revenue growth"
    assert "Q2 FY2024" in first["detail"]


def test_money_flow_parts_add_up_to_revenue():
    facts = facts_with({
        "Revenues": [fact("2026-04-01", "2026-06-30", 1000)],
        "CostOfRevenue": [fact("2026-04-01", "2026-06-30", 400)],
        "NetIncomeLoss": [fact("2026-04-01", "2026-06-30", 150)],
    })
    flow = payloads._flow(load_all_metrics(facts, 12))
    parts = {p["name"]: p["value"] for p in flow["parts"]}
    assert parts == {"Cost of revenue": 400, "Other costs and taxes": 450, "Net income": 150}
    assert sum(parts.values()) == flow["revenue"] == 1000


def test_money_flow_skipped_for_a_loss():
    facts = facts_with({
        "Revenues": [fact("2026-04-01", "2026-06-30", 1000)],
        "NetIncomeLoss": [fact("2026-04-01", "2026-06-30", -50)],
    })
    assert payloads._flow(load_all_metrics(facts, 12)) is None


def test_remembered_reuses_results_and_retries_errors():
    calls = []

    @service.remembered(60)
    def work(x):
        calls.append(x)
        if x == "bad":
            raise ValueError("no")
        return x * 2

    assert work("a") == "aa" and work("a") == "aa"
    assert calls == ["a"]
    for _ in range(2):
        with pytest.raises(ValueError):
            work("bad")
    assert calls.count("bad") == 2          # a failure isn't remembered


def test_remembered_does_the_work_once_for_simultaneous_requests():
    calls = []

    @service.remembered(60)
    def slow(x):
        calls.append(x)
        time.sleep(0.2)
        return x

    threads = [threading.Thread(target=slow, args=("k",)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls == ["k"]
