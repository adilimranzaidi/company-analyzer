"""Daily stock prices from Tiingo (tiingo.com), and detection of unusually large one-day moves.

How a "big move" is decided (all plain Python math)
1. Daily return = today's adjusted close ÷ yesterday's − 1. "Adjusted" prices account for
   splits and dividends, so a 4-for-1 split doesn't look like a 75% crash.
2. Market-adjusted ("abnormal") return = the stock's return − beta × the market's return
   that day, using SPY (a fund that tracks the S&P 500). Beta is how strongly the stock
   usually moves with the market, estimated from its own history (the "market model" used
   in finance event studies). A 6% drop on a day the whole market fell 6% isn't about the
   company; a 9% drop on a day the market rose is.
3. A day is flagged when the abnormal return is more than 4 "typical deviations" from normal
   (median absolute deviation, as in Unusual changes) AND the stock moved at least 4%.

Free-plan limits (approximate): about 50 requests an hour, 1,000 a day and 500 different
symbols a month. Each company uses two requests (its own prices and SPY's), saved for 12 hours.
"""

import hashlib
import json
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "prices"
CACHE_HOURS = 12
MARKET = "SPY"

MOVE_THRESHOLD = 4.0     # typical deviations from normal
MIN_MOVE = 0.04          # and at least a 4% move in the stock itself
MIN_HISTORY = 60         # trading days needed to know what "normal" is


class PriceError(Exception):
    """A problem fetching prices, with a message written for the dashboard user."""


class PriceClient:
    def __init__(self, api_key: str, cache_dir: Path = CACHE_DIR):
        if not api_key:
            raise PriceError("Add TIINGO_API_KEY to .streamlit/secrets.toml to see stock moves.")
        self.cache_dir = Path(cache_dir)
        self.session = requests.Session()
        # Sent as a header, not in the web address, so the key doesn't end up in logs.
        self.session.headers.update({"Authorization": f"Token {api_key}",
                                     "Content-Type": "application/json"})

    def daily(self, ticker: str, start: date) -> pd.DataFrame:
        """Daily prices since `start`: columns date, close, adj_close."""
        key = hashlib.sha1(f"{ticker}|{start}".encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"tiingo_{key}.json"
        if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < CACHE_HOURS * 3600:
            rows = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            rows = self._fetch(ticker, start)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(rows), encoding="utf-8")
        return parse_prices(rows)

    def _fetch(self, ticker: str, start: date) -> list[dict]:
        try:
            response = self.session.get(TIINGO_URL.format(ticker=ticker.lower()), timeout=30,
                                        params={"startDate": start.isoformat(), "format": "json"})
        except requests.RequestException as exc:
            raise PriceError("Couldn't reach Tiingo. Check your internet connection.") from exc
        if response.status_code in (401, 403):
            raise PriceError("Tiingo didn't accept the API key. Check TIINGO_API_KEY in "
                             ".streamlit/secrets.toml.")
        if response.status_code == 404:
            raise PriceError(f"Tiingo has no daily prices for {ticker}.")
        if response.status_code == 429 or "allocation" in response.text[:200].lower():
            raise PriceError("Tiingo's free-plan limit was reached (about 50 requests an hour). "
                             "Try again later; results already loaded are saved.")
        if not response.ok:
            raise PriceError(f"Tiingo returned an error ({response.status_code}).")
        try:
            rows = response.json()
        except ValueError as exc:
            raise PriceError("Tiingo sent a reply the app couldn't read.") from exc
        if not isinstance(rows, list):
            raise PriceError(f"Tiingo returned an unexpected reply for {ticker}.")
        return rows


def parse_prices(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{"date": datetime.fromisoformat(r["date"][:10]).date(),
                        "close": r.get("close"), "adj_close": r.get("adjClose")}
                       for r in rows if r.get("date") and r.get("adjClose")],
                      columns=["date", "close", "adj_close"])
    return df.sort_values("date").drop_duplicates("date").reset_index(drop=True)


def big_moves(stock: pd.DataFrame, market: pd.DataFrame,
              threshold: float = MOVE_THRESHOLD, min_move: float = MIN_MOVE) -> pd.DataFrame:
    """Days the stock moved far more than usual, after allowing for the market's move."""
    columns = ["date", "return", "market_return", "excess", "typical", "score", "close", "beta"]
    if stock.empty or market.empty:
        return pd.DataFrame(columns=columns)
    s = stock.assign(ret=stock["adj_close"].pct_change())
    m = market.assign(mret=market["adj_close"].pct_change())[["date", "mret"]]
    df = s.merge(m, on="date").dropna(subset=["ret", "mret"])
    if len(df) < MIN_HISTORY:
        return pd.DataFrame(columns=columns)
    # The "market model": how strongly this stock usually moves with the market (its beta),
    # estimated from its own history. Apple's beta is above 1, so on a day the market jumps
    # 10%, Apple jumping 15% is mostly the market, not Apple news.
    # Estimated in two passes, leaving out the unusual days themselves (as event studies
    # do): one extreme day can otherwise pull beta far off.
    beta = df["ret"].cov(df["mret"]) / df["mret"].var()
    first = df["ret"] - beta * df["mret"]
    spread = (first - first.median()).abs().median() * 1.4826
    if spread > 0:
        normal = df[(first - first.median()).abs() <= threshold * spread]
        if len(normal) >= MIN_HISTORY and normal["mret"].var() > 0:
            beta = normal["ret"].cov(normal["mret"]) / normal["mret"].var()
    df["excess"] = df["ret"] - beta * df["mret"]
    median = df["excess"].median()
    typical = (df["excess"] - median).abs().median() * 1.4826
    if typical <= 0:
        return pd.DataFrame(columns=columns)
    df["score"] = (df["excess"] - median).abs() / typical
    flagged = df[(df["score"] > threshold) & (df["ret"].abs() >= min_move)]
    out = pd.DataFrame({"date": flagged["date"], "return": flagged["ret"],
                        "market_return": flagged["mret"], "excess": flagged["excess"],
                        "typical": typical, "score": flagged["score"],
                        "close": flagged["close"], "beta": beta}, columns=columns)
    return out.sort_values("date", ascending=False).reset_index(drop=True)


def describe_move(row, ticker: str) -> tuple[str, str, str]:
    """(title, severity, explanation) for one flagged day."""
    direction = "rose" if row["return"] > 0 else "fell"
    title = f"Stock {direction} {abs(row['return']) * 100:.1f}% in one day"
    severity = "high" if abs(row["excess"]) >= 0.10 else "medium"
    market = row["market_return"] * 100
    beta = row.get("beta", 1.0) if hasattr(row, "get") else 1.0
    explanation = (f"{ticker} {direction} {abs(row['return']) * 100:.1f}% while the S&P 500 "
                   f"(SPY) {'rose' if market >= 0 else 'fell'} {abs(market):.1f}%. Given how "
                   f"{ticker} usually moves with the market (beta {beta:.2f}), that's "
                   f"{abs(row['excess']) * 100:.1f} percentage points "
                   f"{'above' if row['excess'] > 0 else 'below'} what the market's move would "
                   f"predict; on a typical day the gap is about "
                   f"{row['typical'] * 100:.1f}%. Closing price: ${row['close']:,.2f}.")
    return title, severity, explanation
