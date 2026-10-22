"""What each panel of the web dashboard receives, as plain JSON-ready data.

Every number here is calculated in Python (by the analyzer package). The page only draws
and formats what it is given; it never calculates a figure itself.
"""

import math
from datetime import date

import pandas as pd

from analyzer.compare import industry_medians, rank_in_group, trailing_roe_latest
from analyzer.edgar_client import pretty_company_name
from analyzer.filings import FORM_NAMES, index_url, latest_reports
from analyzer.financials import MetricData
from analyzer.glossary import GLOSSARY
from analyzer.metrics import add_growth, margin_tables, roe_annual, roe_trailing, unusual_changes
from webapp import service

GLOSSARY_NAME = {"Earnings per share": "Diluted EPS"}   # card label -> glossary term
KPI_KEYS = [("revenue", "Revenue"), ("net_income", "Net income"),
            ("net_margin", "Net margin"), ("eps_diluted", "Earnings per share")]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def num(v):
    """A plain float for JSON, or None for missing / not-a-number."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d or "")


def _rows(df: pd.DataFrame, quarterly: bool, unusual: set[str] | None = None) -> list[dict]:
    """A metric's table as compact rows, with growth (calculated in Python)."""
    if df is None or df.empty:
        return []
    g = add_growth(df, quarterly) if "yoy_growth" not in df else df
    out = []
    for r in g.to_dict("records"):
        out.append({"p": r["period"], "end": iso(r["end"]), "v": num(r["value"]),
                    "yoy": num(r.get("yoy_growth")), "qoq": num(r.get("qoq_growth")),
                    "src": r.get("source", ""), "flag": bool(unusual and r["period"] in unusual)})
    return out


def _ratio_rows(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{"p": r["period"], "end": iso(r["end"]), "v": num(r["value"]), "src": r["source"]}
            for r in df.to_dict("records")]


def _flags(changes: pd.DataFrame) -> dict[str, set[str]]:
    """metric key -> the periods flagged as unusual."""
    if changes.empty:
        return {}
    return changes.groupby("metric_key")["period"].apply(set).to_dict()


def _by_period(df: pd.DataFrame) -> dict:
    return {} if df is None or df.empty else {r["period"]: r for r in df.to_dict("records")}


# ---------------------------------------------------------------------------
# The company: header, figures, every series, takeaways, money flow
# ---------------------------------------------------------------------------

@service.remembered(6 * 3600)
def company_payload(ticker: str) -> dict:
    co = service.company(ticker)
    metrics = service.metrics(ticker)
    prof = service.profile(ticker)
    available = {k: md for k, md in metrics.items() if md.available}

    unusual_q = unusual_changes(metrics, quarterly=True)
    unusual_a = unusual_changes(metrics, quarterly=False)
    flags_q, flags_a = _flags(unusual_q), _flags(unusual_a)

    series = {}
    for key, md in available.items():
        series[key] = {
            "name": md.metric.name, "unit": md.metric.unit, "kind": "metric",
            "description": GLOSSARY.get(md.metric.name, {}).get("short") or md.metric.description,
            "label": md.choice.label if md.choice else "", "note": md.note,
            "quarterly": _rows(md.quarterly, True, flags_q.get(key)),
            "annual": _rows(md.annual, False, flags_a.get(key)),
        }
    for quarterly in (True, False):
        for key, (ratio, df) in margin_tables(metrics, quarterly).items():
            entry = series.setdefault(key, {
                "name": ratio.name, "unit": "ratio", "kind": "ratio",
                "description": GLOSSARY.get(ratio.name, {}).get("short", ""),
                "formula": ratio.formula, "quarterly": [], "annual": []})
            entry["quarterly" if quarterly else "annual"] = _ratio_rows(df)
    ni, eq = metrics.get("net_income"), metrics.get("equity")
    if ni and eq and ni.available and eq.available:
        series["roe"] = {"name": "Return on equity", "unit": "ratio", "kind": "ratio",
                         "description": GLOSSARY.get("Return on equity", {}).get("short", ""),
                         "formula": "Net income ÷ average shareholders' equity "
                                    "(quarterly: last 4 quarters)",
                         "quarterly": _ratio_rows(roe_trailing(ni.quarterly, eq.quarterly)),
                         "annual": _ratio_rows(roe_annual(ni.annual, eq.annual))}

    return {
        "company": {
            "ticker": co.ticker, "name": pretty_company_name(co.name), "cik": co.cik,
            "exchange": ", ".join(co.exchanges), "industry": co.industry, "sic": co.sic_code,
            "fiscal_year_end": co.fiscal_year_end, "edgar_url": co.edgar_url,
            "website": prof.get("weburl", ""), "market_cap": num(prof.get("market_cap")),
            "has_logo": bool(prof.get("logo")),
        },
        "kpis": _kpis(metrics, series),
        "series": series,
        "unusual": [_unusual_row(co.cik, r) for r in unusual_q.head(40).to_dict("records")],
        "unusual_annual": [_unusual_row(co.cik, r) for r in unusual_a.head(40).to_dict("records")],
        "takeaways": _takeaways(metrics, series),
        "flow": _flow(metrics),
        "missing": [md.metric.name for md in metrics.values() if not md.available],
    }


def _kpis(metrics: dict[str, MetricData], series: dict) -> dict:
    rev = series.get("revenue", {}).get("quarterly") or []
    period = rev[-1]["p"] if rev else None
    src = metrics["revenue"].quarterly.iloc[-1] if rev else None
    cards = []
    for key, label in KPI_KEYS:
        rows = (series.get(key) or {}).get("quarterly") or []
        if not rows:
            continue
        last = rows[-1]
        unit = series[key]["unit"]
        yoy = last.get("yoy")
        change = None
        if key == "net_margin":
            prior = next((r for r in rows if r["p"] == _year_earlier(last["p"])), None)
            if prior and prior["v"] is not None and last["v"] is not None:
                change = {"kind": "points", "value": (last["v"] - prior["v"]) * 100}
        elif yoy is not None:
            change = {"kind": "pct", "value": yoy * 100}
        cards.append({"key": key, "label": label, "unit": unit, "value": last["v"],
                      "period": last["p"], "change": change,
                      "spark": [r["v"] for r in rows[-12:]],
                      "help": GLOSSARY.get(GLOSSARY_NAME.get(label, label), {}).get("short", "")})
    roe = trailing_roe_latest(metrics)
    return {"period": period, "cards": cards,
            "roe": ({"value": num(roe["value"]), "period": roe["period"]}
                    if roe is not None else None),
            "source": f"{src['form']} filed {src['filed']}" if src is not None else ""}


def _year_earlier(period: str) -> str:
    """"Q2 FY2026" -> "Q2 FY2025"."""
    q, fy = period.split(" FY") if " FY" in period else (period, "")
    return f"{q} FY{int(fy) - 1}" if fy.isdigit() else ""


def _takeaways(metrics: dict[str, MetricData], series: dict) -> list[dict]:
    """Plain-English findings, each calculated here from the figures."""
    out = []
    rev = (series.get("revenue") or {}).get("quarterly") or []
    growth = [r["yoy"] for r in rev if r["yoy"] is not None]
    if growth:
        up = growth[-1] > 0
        streak = 0
        for g in reversed(growth):
            if (g > 0) == up:
                streak += 1
            else:
                break
        first = rev[-streak]["p"]
        out.append({"tone": "up" if up else "down", "fill": 100,
                    "title": f"{streak} straight quarter{'s' if streak != 1 else ''} of revenue "
                             f"{'growth' if up else 'decline'}",
                    "detail": f"Every quarter since {first} was {'above' if up else 'below'} the "
                              "same quarter a year before."})
    nm = (series.get("net_margin") or {}).get("quarterly") or []
    if nm and nm[-1]["v"] is not None:
        v = nm[-1]["v"] * 100
        out.append({"tone": "brand", "fill": max(0, min(100, v)),
                    "title": f"Keeps {v:.1f}¢ of each revenue dollar as profit",
                    "detail": f"Net income as a share of revenue in {nm[-1]['p']}."})
    roe = trailing_roe_latest(metrics)
    if roe is not None and num(roe["value"]) is not None:
        v = roe["value"] * 100
        detail = "Net income over the last four quarters, divided by average equity."
        if v > 100:
            # Above 100% means equity is small next to profit, usually after years of buybacks
            # (Apple, McDonald's), so the figure says more about the balance sheet than returns.
            detail += (" Unusually high because shareholders' equity is small compared with "
                       "profit, often after years of share buybacks.")
        out.append({"tone": "brand", "fill": max(0, min(100, v)),
                    "title": f"{v:.1f}% return on shareholders' money", "detail": detail})
    return out


def _flow(metrics: dict[str, MetricData]) -> dict | None:
    """Where the latest quarter's revenue went: costs the company reports separately, then
    everything else, then profit. All amounts from the same quarter; the "everything else"
    part is revenue minus the others (calculated here)."""
    rev, ni = metrics.get("revenue"), metrics.get("net_income")
    if not (rev and ni and rev.available and ni.available) or rev.quarterly.empty:
        return None
    period = rev.quarterly.iloc[-1]["period"]
    r = _by_period(rev.quarterly).get(period)
    n = _by_period(ni.quarterly).get(period)
    if not r or not n or r["value"] <= 0 or n["value"] <= 0:
        return None
    parts = []
    for key, name in [("cost_of_revenue", "Cost of revenue"),
                      ("credit_provision", "Credit losses")]:
        md = metrics.get(key)
        row = _by_period(md.quarterly).get(period) if md and md.available else None
        if row and row["value"] > 0:
            parts.append({"name": name, "value": num(row["value"]), "key": key})
    other = r["value"] - n["value"] - sum(p["value"] for p in parts)
    if other < 0:
        return None
    parts.append({"name": "Other costs and taxes", "value": num(other), "key": "other",
                  "calculated": True})
    parts.append({"name": "Net income", "value": num(n["value"]), "key": "net_income"})
    return {"period": period, "revenue": num(r["value"]), "parts": parts}


def _unusual_row(cik: str, r: dict) -> dict:
    return {"metric_key": r["metric_key"], "metric": r["metric"], "unit": r["unit"],
            "period": r["period"], "value": num(r["value"]), "prior": num(r["prior_year_value"]),
            "yoy": num(r["yoy_growth"]), "typical": num(r["typical_growth"]),
            "first_reported": f"{r['orig_form']} filed {r['orig_filed']}",
            "filing_url": index_url(cik, r["orig_accn"]), "accession": r["orig_accn"]}


# ---------------------------------------------------------------------------
# Share price
# ---------------------------------------------------------------------------

@service.remembered(3600)
def price_payload(ticker: str) -> dict:
    try:
        stock, _ = service.prices(ticker)
    except service.PriceError as err:
        return {"error": str(err), "series": []}
    if stock.empty:
        return {"error": "No price data.", "series": []}
    closes = stock[["date", "close"]].dropna()
    last = closes.iloc[-1]
    year_ago_day = last["date"].replace(year=last["date"].year - 1)
    before = closes[closes["date"] <= year_ago_day]
    change_1y = (last["close"] / before.iloc[-1]["close"] - 1) if not before.empty else None
    series = [[iso(d), round(float(c), 2)]
              for d, c in zip(closes["date"], closes["close"], strict=True)]
    return {"series": series,
            "last": num(last["close"]), "last_date": iso(last["date"]), "change_1y": num(change_1y)}


# ---------------------------------------------------------------------------
# Events and headlines
# ---------------------------------------------------------------------------

@service.remembered(3600)
def events_payload(ticker: str) -> dict:
    events, note = service.all_events(ticker)
    news, news_error = service.headlines(ticker)
    return {
        "events": [{"date": iso(e.date), "category": e.category, "title": e.title,
                    "severity": e.severity, "detail": e.evidence, "url": e.url, "form": e.form,
                    "id": f"{e.date}|{e.category}|{e.title}"} for e in events],
        "price_note": note,
        "headlines": [_article(a) for a in news], "headlines_error": news_error,
    }


def _article(a: dict) -> dict:
    return {"title": a["title"], "url": a["url"], "source": a.get("source", ""),
            "date": iso(a["date"]) if a.get("date") else ""}


def headlines_around_payload(ticker: str, day: date) -> dict:
    articles, error = service.headlines_around(ticker, day)
    return {"headlines": [_article(a) for a in articles[:8]], "error": error}


# ---------------------------------------------------------------------------
# Rivals
# ---------------------------------------------------------------------------

@service.remembered(3600)
def peers_payload(ticker: str, chosen: tuple[str, ...] | None) -> dict:
    suggested = service.peers(ticker)
    names = {t: n for t, n in service.search_index()}
    tickers = list(chosen) if chosen else [p.ticker for p in suggested]
    tickers = [t for t in dict.fromkeys([ticker] + tickers) if t in names][:11]
    loaded = service.load_many(tickers)
    snaps = {t: service.peer_snapshot(t) for t in loaded}
    rows = []
    for t in tickers:
        s = snaps.get(t)
        if not s:
            continue
        rows.append({"ticker": t, "name": names.get(t, t),
                     **{k: (num(v) if not isinstance(v, str) else v) for k, v in s.items()}})
    others = [s for t, s in snaps.items() if t != ticker and s]
    med = industry_medians(others)
    me = snaps.get(ticker) or {}
    ranks = {}
    for k in ("revenue_growth", "net_margin", "roe", "eps_growth"):
        r = rank_in_group(me.get(k), [s.get(k) for s in others])
        if r:
            ranks[k] = {"rank": r[0], "of": r[1], "median": num(med.get(k))}
    trends = {}
    for t, (_, m) in loaded.items():
        trends[t] = {
            "revenue_growth": [[r["period"], num(r["yoy_growth"])] for r in add_growth(
                m["revenue"].annual, False).to_dict("records")
                if m["revenue"].available and r["yoy_growth"] is not None][-8:],
            "net_margin": [[p, num(v)] for p, v in _annual_ratio(m, "net_margin")][-8:],
        }
    return {
        "suggested": [{"ticker": p.ticker, "name": p.name, "source": p.source,
                       "evidence": p.evidence} for p in suggested],
        "rows": rows, "medians": {k: num(v) for k, v in med.items()}, "ranks": ranks,
        "trends": trends,
    }


def _annual_ratio(metrics: dict[str, MetricData], key: str) -> list[tuple[str, float]]:
    tables = margin_tables(metrics, quarterly=False)
    if key not in tables:
        return []
    return [(r["period"], r["value"]) for r in tables[key][1].to_dict("records")]


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------

@service.remembered(6 * 3600)
def filings_payload(ticker: str) -> dict:
    table = service.filings(ticker)
    latest = latest_reports(table)

    def row(r: dict) -> dict:
        return {"form": r["form"], "form_name": r["form_name"], "filed": iso(r["filed"]),
                "period": iso(r["period"]) if r["period"] else "", "about": r["about"],
                "url": r["url"], "index_url": r["index_url"], "significant": bool(r["significant"])}

    return {"latest": [row(r) for r in (latest.annual, latest.quarterly) if r],
            "rows": [row(r) for r in table.head(400).to_dict("records")],
            "form_names": FORM_NAMES}


def glossary_payload() -> dict:
    return GLOSSARY
