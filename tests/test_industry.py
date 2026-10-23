"""Checks for the Industry and world panel's Python side: which industry a company is in,
the indicator changes (calculated here, never by the AI), and how web sources are numbered."""

from types import SimpleNamespace as NS

import pandas as pd

from analyzer.assistant import parse_web_answer
from analyzer.industry import GENERAL, Indicator, indicator_summary, profile_for


def test_profiles_by_industry_code():
    assert profile_for("2911").name == "Oil and gas"        # Exxon: petroleum refining
    assert profile_for("3674").name == "Semiconductors"     # Nvidia, Intel
    assert profile_for("6021").name == "Banks"              # JPMorgan
    assert profile_for("5812").name == "Restaurants"        # McDonald's
    assert profile_for("9999") is GENERAL
    assert profile_for("") is GENERAL


def _monthly(values, start="2024-01-01"):
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates.date, "value": values})


def test_rate_indicator_change_is_in_points():
    ind = Indicator("DGS10", "10-year yield", "pct", "why")
    s = indicator_summary(ind, _monthly([4.0] * 12 + [4.5]))
    assert s["value"] == 4.5
    assert s["change"] == {"kind": "points", "value": 0.5}


def test_price_indicator_change_is_in_percent():
    ind = Indicator("DCOILBRENTEU", "Brent", "usd", "why")
    s = indicator_summary(ind, _monthly([80.0] * 12 + [100.0]))
    assert s["change"]["kind"] == "pct" and round(s["change"]["value"], 6) == 25.0


def test_index_indicator_shown_as_change_from_a_year_earlier():
    ind = Indicator("CPIAUCSL", "Inflation", "pct", "why", yoy=True)
    s = indicator_summary(ind, _monthly([100.0] * 12 + [103.0]))
    assert round(s["value"], 6) == 3.0                    # +3% from a year earlier
    assert s["unit"] == "pct" and "change from a year earlier" in s["name"]


def test_web_sources_numbered_once_per_page():
    cite = lambda url: NS(type="web_search_result_location", url=url, title="T " + url,  # noqa: E731
                          cited_text="quoted")
    content = [NS(type="server_tool_use"),
               NS(type="text", text="Oil rose.", citations=[cite("a"), cite("b")]),
               NS(type="text", text=" Again.", citations=[cite("a")]),
               NS(type="text", text=" No source.", citations=None)]
    text, plain, sources = parse_web_answer(content)
    assert text == "Oil rose. [1] [2] Again. [1] No source."
    assert plain == "Oil rose. Again. No source."
    assert [(s.number, s.url) for s in sources] == [(1, "a"), (2, "b")]
