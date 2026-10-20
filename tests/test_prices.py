"""Checks for big one-day stock moves. No internet: prices are made up so the right
answer is known in advance."""

from datetime import date, timedelta

import pandas as pd
import pytest

from analyzer.prices import PriceClient, PriceError, big_moves, describe_move, parse_prices


def series(daily_returns, start=100.0):
    """Prices built from a list of daily returns, one per business day."""
    prices, day = [start], date(2025, 1, 1)
    for r in daily_returns:
        prices.append(prices[-1] * (1 + r))
    days = [day + timedelta(days=i) for i in range(len(prices))]
    return pd.DataFrame({"date": days, "close": prices, "adj_close": prices})


QUIET = [0.01, -0.01, 0.005, -0.005, 0.008, -0.008] * 20     # 120 ordinary days
# The market's ordinary days differ a little from the stock's, as in real life.
MARKET_QUIET = [0.006, -0.004, 0.002, -0.007, 0.004, -0.003] * 20


def test_company_specific_crash_is_flagged():
    stock = series(QUIET + [-0.12] + QUIET[:10])               # stock falls 12%...
    market = series(MARKET_QUIET + [0.002] + MARKET_QUIET[:10])  # ...while the market is flat
    moves = big_moves(stock, market)
    assert len(moves) == 1
    assert moves.iloc[0]["return"] == pytest.approx(-0.12)
    assert moves.iloc[0]["excess"] == pytest.approx(-0.122)


def test_market_wide_crash_is_not_company_news():
    stock = series(QUIET + [-0.08] + QUIET[:10])                # stock falls 8%...
    market = series(MARKET_QUIET + [-0.075] + MARKET_QUIET[:10])  # ...because everything did
    assert big_moves(stock, market).empty


def test_small_moves_are_ignored_even_in_a_very_quiet_stock():
    calm = [0.001, -0.001] * 60
    market_calm = [0.0005, -0.0015] * 60
    stock = series(calm + [0.03] + calm[:10])                   # 3%: unusual but under 4%
    market = series(market_calm + [0.0] + market_calm[:10])
    assert big_moves(stock, market).empty


def test_not_enough_history_means_no_flags():
    assert big_moves(series([0.01, -0.2, 0.01]), series([0.0, 0.0, 0.0])).empty


def test_describe_move_explains_in_plain_english():
    row = {"return": -0.098, "market_return": -0.004, "excess": -0.094, "typical": 0.012,
           "close": 287.5}
    title, severity, text = describe_move(row, "AXP")
    assert title == "Stock fell 9.8% in one day"
    assert severity == "medium"
    assert text.startswith("AXP fell 9.8% while the S&P 500 (SPY) fell 0.4%.")


def test_parse_prices_uses_dates_and_adjusted_close():
    rows = [{"date": "2025-01-03T00:00:00.000Z", "close": 10, "adjClose": 9.5},
            {"date": "2025-01-02T00:00:00.000Z", "close": 11, "adjClose": 10.4}]
    df = parse_prices(rows)
    assert list(df["date"]) == [date(2025, 1, 2), date(2025, 1, 3)]
    assert list(df["adj_close"]) == [10.4, 9.5]


def test_missing_key_gives_setup_instructions():
    with pytest.raises(PriceError, match="TIINGO_API_KEY"):
        PriceClient("")


def test_key_is_sent_as_a_header_not_in_the_address():
    assert PriceClient("abc").session.headers["Authorization"] == "Token abc"
