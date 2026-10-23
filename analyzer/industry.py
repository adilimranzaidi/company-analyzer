"""What drives each industry: its sector index, the economic indicators that move it, and
the topics worth watching. Chosen from the company's SEC industry code (SIC).

Indicators come from FRED (the St. Louis Federal Reserve's free data service). All changes
are calculated here in Python; the AI never sees or computes these numbers.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "fred"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_MAX_AGE_HOURS = 12


@dataclass(frozen=True)
class Indicator:
    series: str          # FRED series ID
    name: str
    unit: str            # "usd", "pct" (already a percent), "index"
    why: str             # one line: how it affects the industry
    yoy: bool = False    # show as % change from a year earlier (e.g. a price index -> inflation)


@dataclass(frozen=True)
class Profile:
    name: str
    sector_etf: str      # an exchange-traded fund that tracks the sector
    sector_name: str
    indicators: tuple[Indicator, ...]
    topics: str          # what the web-search update should look into
    sic: tuple[tuple[int, int], ...] = field(default=())   # SIC code ranges (inclusive)


MACRO = (
    Indicator("DGS10", "10-year Treasury yield", "pct",
              "Higher long-term rates raise borrowing costs and lower what investors pay for "
              "future profits."),
    Indicator("CPIAUCSL", "Inflation (consumer prices)", "pct",
              "Rising prices squeeze costs and push the Federal Reserve to keep rates high.",
              yoy=True),
    Indicator("UNRATE", "Unemployment rate", "pct",
              "More people out of work means weaker spending and more unpaid loans."),
)

PROFILES = (
    Profile("Oil and gas", "XLE", "Energy Select Sector fund (XLE)", (
        Indicator("DCOILBRENTEU", "Brent crude, spot price", "usd",
                  "The world price of oil; it sets most of an oil producer's revenue. (Spot is "
                  "physical oil; the news usually quotes futures, which can differ.)"),
        Indicator("DCOILWTICO", "WTI crude (US), spot price", "usd",
                  "The US oil price; the gap to Brent matters for US producers and refiners."),
        Indicator("DHHNGSP", "Natural gas, spot price (Henry Hub)", "usd",
                  "Drives revenue from gas production and costs for refiners and chemicals."),
    ), "oil and gas prices; OPEC+ supply decisions; conflict and shipping in the Middle East "
       "(Strait of Hormuz, Red Sea); sanctions; US tariffs and trade policy and how they affect "
       "US producers; US production; demand from China; the shift to renewables",
       sic=((1300, 1399), (2900, 2999), (4920, 4925), (5170, 5172))),
    Profile("Semiconductors", "SOXX", "iShares Semiconductor fund (SOXX)", (
        Indicator("IPG3344S", "US semiconductor production", "index",
                  "How much the US chip industry is producing; a gauge of demand.", yoy=True),
        Indicator("PCU33443344", "Semiconductor producer prices", "index",
                  "What chipmakers can charge; rising prices mean tight supply.", yoy=True),
    ), "demand for chips (AI data centers, phones, PCs, cars); US export controls on China; "
       "tariffs; the CHIPS Act; how Chinese chipmakers (SMIC, Huawei and others) compare in "
       "technology and manufacturing; Taiwan (TSMC) and supply-chain risk",
       sic=((3670, 3679), (3559, 3559))),
    Profile("Banks", "KBE", "SPDR S&P Bank fund (KBE)", (
        Indicator("FEDFUNDS", "Federal funds rate", "pct",
                  "The Fed's key rate; sets what banks pay on deposits and earn on loans."),
        Indicator("T10Y2Y", "Yield curve (10-year minus 2-year)", "pct",
                  "Banks borrow short and lend long; a wider gap means fatter margins."),
        Indicator("DRALACBS", "Loan delinquency rate (all banks)", "pct",
                  "The share of loans behind on payments; rising means more losses ahead."),
    ), "interest rates and the Federal Reserve; loan demand; credit quality and defaults; "
       "bank regulation and capital rules; deposit competition; commercial real estate",
       sic=((6020, 6036), (6710, 6712))),
    Profile("Card issuers and consumer lending", "XLF", "Financial Select Sector fund (XLF)", (
        Indicator("DRCCLACBS", "Credit card delinquency rate", "pct",
                  "The share of card balances behind on payments; it drives credit losses."),
        Indicator("REVOLSL", "Revolving consumer credit", "usd",
                  "How much people carry on credit cards; more balances, more interest income.",
                  yoy=True),
        Indicator("RSAFS", "US retail sales", "usd",
                  "Consumer spending; card networks earn fees on every purchase.", yoy=True),
    ), "consumer spending; credit card delinquencies and defaults; interest rates; regulation "
       "of card fees (the Credit Card Competition Act, interchange caps, late-fee rules); "
       "travel spending; competition from fintechs and buy-now-pay-later",
       sic=((6140, 6159), (6199, 6199), (7389, 7389))),
    Profile("Software and internet", "IGV", "iShares Expanded Tech-Software fund (IGV)", (
        Indicator("DGS10", "10-year Treasury yield", "pct",
                  "Tech valuations lean on future profits, so they're sensitive to rates."),
    ), "enterprise IT and cloud spending; AI investment and competition; antitrust and "
       "privacy regulation; digital advertising; competition from abroad",
       sic=((7370, 7379),)),
    Profile("Computer and electronics hardware", "XLK", "Technology Select Sector fund (XLK)", (
        Indicator("IPG334S", "US computer and electronics production", "index",
                  "Output of the US electronics industry; a gauge of demand.", yoy=True),
    ), "consumer electronics demand; tariffs on imports from China; supply chains in Asia; "
       "AI hardware demand; competition from Chinese manufacturers",
       sic=((3570, 3579), (3660, 3669), (3810, 3829))),
    Profile("Restaurants", "PEJ", "Invesco Leisure and Entertainment fund (PEJ)", (
        Indicator("RSFSDP", "Restaurant and bar sales", "usd",
                  "How much Americans spend eating out.", yoy=True),
        Indicator("CUSR0000SEFV", "Menu prices (food away from home)", "index",
                  "Restaurant price inflation; high prices can push customers away.", yoy=True),
    ), "consumer spending and lower-income diners; menu price inflation; food and labor "
       "costs; minimum wage changes; competition and value meals; weight-loss drugs",
       sic=((5810, 5813),)),
    Profile("Retail", "XRT", "SPDR S&P Retail fund (XRT)", (
        Indicator("RSAFS", "US retail sales", "usd", "Overall consumer spending.", yoy=True),
        Indicator("UMCSENT", "Consumer sentiment", "index",
                  "How confident shoppers feel; it leads spending."),
    ), "consumer spending; tariffs on imported goods; inflation; e-commerce competition; "
       "inventory and shipping costs",
       sic=((5200, 5799), (5900, 5999))),
    Profile("Pharmaceuticals and biotech", "XLV", "Health Care Select Sector fund (XLV)", (
        Indicator("PCU325412325412", "Drug producer prices", "index",
                  "What drugmakers can charge.", yoy=True),
    ), "drug pricing rules (Medicare negotiation); FDA approvals; patent expiries and "
       "generics; tariffs on imported drugs; competition from China in biotech",
       sic=((2830, 2836), (8731, 8731))),
    Profile("Aerospace and defense", "ITA", "iShares US Aerospace and Defense fund (ITA)", (
        Indicator("IPG3364S", "US aerospace production", "index",
                  "Output of aircraft and parts.", yoy=True),
    ), "defense budgets and conflicts; airline aircraft orders; supply chain and quality "
       "problems; FAA oversight; tariffs and trade",
       sic=((3720, 3729), (3760, 3769), (3812, 3812))),
    Profile("Autos", "CARZ", "First Trust Global Auto fund (CARZ)", (
        Indicator("TOTALSA", "US vehicle sales", "index", "Cars and light trucks sold.",),
    ), "car demand and loan rates; tariffs on imported cars and parts; electric vehicles and "
       "subsidies; competition from Chinese automakers",
       sic=((3710, 3716),)),
    Profile("Utilities", "XLU", "Utilities Select Sector fund (XLU)", (
        Indicator("DHHNGSP", "Natural gas price (Henry Hub)", "usd",
                  "A major fuel cost for power plants."),
    ), "power demand (including AI data centers); interest rates; regulation and rate cases; "
       "natural gas prices; renewables",
       sic=((4900, 4991),)),
    Profile("Insurance", "KIE", "SPDR S&P Insurance fund (KIE)", (), "natural catastrophes; "
       "interest rates and investment income; pricing; regulation",
       sic=((6300, 6411),)),
)

GENERAL = Profile("General", "SPY", "S&P 500 (SPY)", (), "the company's industry, customers, "
                  "competitors, regulation and the economy")


def profile_for(sic_code: str) -> Profile:
    try:
        sic = int(sic_code)
    except (TypeError, ValueError):
        return GENERAL
    for p in PROFILES:
        if any(lo <= sic <= hi for lo, hi in p.sic):
            return p
    return GENERAL


# ---------------------------------------------------------------------------
# FRED data
# ---------------------------------------------------------------------------

class FredError(Exception):
    pass


def fred_series(series: str, api_key: str, years: int = 6) -> pd.DataFrame:
    """Observations (date, value) for a FRED series, saved for 12 hours. Raises FredError."""
    if not api_key:
        raise FredError("Add FRED_API_KEY to .streamlit/secrets.toml to see the industry's "
                        "economic indicators (a free key from fredaccount.stlouisfed.org).")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{series}.json"
    if path.exists() and (time.time() - path.stat().st_mtime) / 3600 < FRED_MAX_AGE_HOURS:
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        start = (date.today() - timedelta(days=365 * years + 40)).isoformat()
        try:
            r = requests.get(FRED_URL, timeout=20, params={
                "series_id": series, "api_key": api_key, "file_type": "json",
                "observation_start": start})
        except requests.RequestException as err:
            raise FredError(f"Couldn't reach FRED: {err}") from err
        if r.status_code != 200:
            raise FredError(f"FRED didn't return {series} (status {r.status_code}).")
        rows = [[o["date"], o["value"]] for o in r.json().get("observations", [])]
        path.write_text(json.dumps(rows), encoding="utf-8")
    df = pd.DataFrame(rows, columns=["date", "value"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")       # FRED uses "." for missing
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.dropna().reset_index(drop=True)


def _frequency(df: pd.DataFrame) -> str:
    gap = pd.to_datetime(df["date"]).diff().dt.days.median()
    return "daily" if gap <= 8 else "monthly" if gap <= 45 else "quarterly"


def indicator_summary(ind: Indicator, df: pd.DataFrame) -> dict:
    """Latest value with its real date, the change from a year earlier, and monthly averages
    for a chart. For yoy indicators the value IS the % change from a year earlier."""
    if df.empty:
        return {"series": ind.series, "name": ind.name, "error": "No data."}
    s = df.set_index(pd.to_datetime(df["date"]))["value"]
    monthly = s.resample("MS").mean().dropna()
    freq = _frequency(df)
    if ind.yoy:
        series = (monthly / monthly.shift(12) - 1).dropna() * 100
        monthly, unit = series, "pct"
    else:
        series, unit = s, ind.unit         # the latest actual reading, not a month's average
    if series.empty:
        return {"series": ind.series, "name": ind.name, "error": "Not enough data."}
    last_date, last = series.index[-1], float(series.iloc[-1])
    year_ago = series[series.index <= last_date - pd.DateOffset(years=1)]
    prior = float(year_ago.iloc[-1]) if not year_ago.empty else None
    if prior is None:
        change = None
    elif unit == "pct":
        change = {"kind": "points", "value": last - prior}
    else:
        change = {"kind": "pct", "value": (last / prior - 1) * 100 if prior else None}
    return {"series": ind.series, "name": ind.name + (" (change from a year earlier)"
                                                      if ind.yoy else ""),
            "unit": unit, "why": ind.why, "value": last, "as_of": last_date.date().isoformat(),
            "freq": "monthly" if ind.yoy else freq, "change": change,
            "points": [[d.date().isoformat(), round(float(v), 3)]
                       for d, v in monthly.tail(60).items()],
            "source_url": f"https://fred.stlouisfed.org/series/{ind.series}"}
