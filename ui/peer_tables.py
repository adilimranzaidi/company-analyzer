"""Shared pieces for the Industry and Compare sections."""

import pandas as pd
import streamlit as st

from analyzer.charts import format_pct, format_ratio, format_value
from analyzer.compare import growth_series, snapshot
from analyzer.financials import MetricData
from analyzer.glossary import short
from analyzer.metrics import margin_tables, roe_annual
from ui import data

# Charts that compare fairly across companies of very different sizes.
SERIES_CHOICES = ["Revenue growth", "Net income growth", "EPS growth", "Net margin",
                  "Operating margin", "Return on equity"]


def load_many(labels: list[str], options_by_label: dict[str, dict]) -> dict[str, tuple]:
    """label -> (company, metrics) for each chosen company that has data."""
    loaded = {}
    progress = st.progress(0.0, text="Loading companies from SEC EDGAR...")
    for i, label in enumerate(labels):
        opt = options_by_label.get(label)
        result = data.company_and_metrics(opt["ticker"]) if opt else None
        if result:
            loaded[label] = result
        progress.progress((i + 1) / max(len(labels), 1),
                          text=f"Loading companies from SEC EDGAR... ({i + 1} of {len(labels)})")
    progress.empty()
    return loaded


def snapshot_row(name: str, snap: dict) -> dict:
    return {
        "Company": name,
        "Fiscal year": snap["fiscal_year"] or "-",
        "Revenue": format_value(snap["revenue"], "USD") if snap["revenue"] is not None else "-",
        "Revenue growth": format_pct(snap["revenue_growth"]),
        "Net margin": format_ratio(snap["net_margin"]),
        "Return on equity": format_ratio(snap["roe"]),
        "EPS growth": format_pct(snap["eps_growth"]),
        "Latest quarter revenue growth":
            f"{format_pct(snap['quarter_revenue_growth'])} ({snap['latest_quarter']})"
            if snap["latest_quarter"] else "-",
    }


def series_for(choice: str, metrics: dict[str, MetricData]) -> pd.DataFrame:
    """Annual series for one comparison chart choice."""
    if choice.endswith("growth"):
        key = {"Revenue growth": "revenue", "Net income growth": "net_income",
               "EPS growth": "eps_diluted"}[choice]
        return growth_series(metrics.get(key), quarterly=False)
    if choice == "Return on equity":
        ni, eq = metrics.get("net_income"), metrics.get("equity")
        if ni and eq and ni.available and eq.available:
            return roe_annual(ni.annual, eq.annual)[["period", "end", "value"]]
        return pd.DataFrame(columns=["period", "end", "value"])
    key = {"Net margin": "net_margin", "Operating margin": "operating_margin"}[choice]
    tables = margin_tables(metrics, quarterly=False)
    if key in tables:
        return tables[key][1][["period", "end", "value"]]
    return pd.DataFrame(columns=["period", "end", "value"])


def snapshots(loaded: dict[str, tuple]) -> dict[str, dict]:
    return {label: snapshot(m) for label, (_, m) in loaded.items()}


def column_help() -> dict:
    """Hover explanations for the snapshot table's columns."""
    return {
        "Revenue growth": st.column_config.TextColumn(help=short("Year-over-year growth")),
        "Net margin": st.column_config.TextColumn(help=short("Net margin")),
        "Return on equity": st.column_config.TextColumn(help=short("Return on equity")),
        "EPS growth": st.column_config.TextColumn(help=short("Diluted EPS")),
        "Fiscal year": st.column_config.TextColumn(help=short("Fiscal year")),
    }
