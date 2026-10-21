"""Compare: pick up to five companies and see them side by side."""

import pandas as pd
import streamlit as st

from analyzer.charts import multi_line_chart
from analyzer.edgar_client import Company
from ui import data
from ui.peer_tables import SERIES_CHOICES, load_many, series_for, snapshot_row, snapshots

MAX_COMPANIES = 5


def render(company: Company, options: list[dict]) -> None:
    by_label = {o["label"]: o for o in options}
    self_label = next((o["label"] for o in options if o["ticker"] == company.ticker), None)

    key = f"compare_{company.ticker}"
    if key not in st.session_state:
        suggested = data.peers(data.user_agent(), company.cik, company.sic_code)
        defaults = [self_label] + [f"{p.name} ({p.ticker})" for p in suggested[:2]]
        st.session_state[key] = [d for d in defaults if d in by_label]

    chosen = st.multiselect(f"Companies (up to {MAX_COMPANIES})", list(by_label), key=key,
                            max_selections=MAX_COMPANIES,
                            placeholder="Search by company name or ticker")
    if len(chosen) < 2:
        st.info("Choose at least two companies to compare.")
        return

    loaded = load_many(chosen, by_label)
    missing = [c for c in chosen if c not in loaded]
    if missing:
        st.warning("No financial data available for: " + ", ".join(missing))
    snaps = snapshots(loaded)

    # Side-by-side table: companies as columns reads naturally for 2-5 companies.
    table = pd.DataFrame([snapshot_row(label, s) for label, s in snaps.items()])
    table = table.set_index("Company").T
    table.columns = [_short(c) for c in table.columns]
    st.dataframe(table, width="stretch")
    st.caption("Each company's own latest fiscal year (year-ends differ). All figures from "
               "SEC filings; growth rates and ratios calculated in Python.")

    choice = st.selectbox("Chart", SERIES_CHOICES, key="cmp_measure")
    series = {_short(label): series_for(choice, m).tail(10) for label, (_, m) in loaded.items()}
    empty = [n for n, df in series.items() if df.empty]
    st.plotly_chart(multi_line_chart(series, choice), config={"displayModeBar": False},
                    width="stretch", key="cmp_chart")
    if empty:
        st.caption(f"Not available for {', '.join(empty)} (not reported, or the figures "
                   "aren't comparable).")
    st.caption("Growth rates and ratios are shown instead of dollar amounts, so companies "
               "of very different sizes can be compared on one chart.")


def _short(label: str) -> str:
    """"American Express Co (AXP)" -> "AXP" for compact column headers and legends."""
    return label.rsplit("(", 1)[-1].rstrip(")") if label.endswith(")") else label
