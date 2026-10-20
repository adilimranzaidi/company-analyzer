"""Filings: the company's 10-K, 10-Q and 8-K filings with links."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from analyzer.edgar_client import Company
from analyzer.filings import filings_table, latest_reports
from ui import data

TYPES = {"Annual (10-K)": ("10-K", "10-K/A", "20-F", "40-F"),
         "Quarterly (10-Q)": ("10-Q", "10-Q/A"),
         "Current events (8-K)": ("8-K", "8-K/A", "6-K")}
SPANS = {"Past year": 365, "Past 3 years": 3 * 365, "All available": None}


def render(company: Company) -> None:
    table = data.filings(data.user_agent(), company.cik)
    if table.empty:
        st.info("No 10-K, 10-Q or 8-K filings found for this company.")
        return

    # --- Latest reports, front and center ------------------------------------------
    latest = latest_reports(table)
    cols = st.columns(2)
    for col, report, label in [(cols[0], latest.annual, "Latest annual report"),
                               (cols[1], latest.quarterly, "Latest quarterly report")]:
        with col:
            if report:
                st.markdown(
                    f'<div class="ca-card"><div class="ca-muted">{label}</div>'
                    f'<div class="ca-card-title">{report["form"]} for the period ending '
                    f'{report["period"] or "n/a"}</div>'
                    f'<div class="ca-muted">Filed {report["filed"]} · '
                    f'<a href="{report["url"]}" target="_blank">Open document</a> · '
                    f'<a href="{report["index_url"]}" target="_blank">All files</a></div></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="ca-card"><div class="ca-muted">{label}</div>'
                            "<div>None in the SEC's recent filings list.</div></div>",
                            unsafe_allow_html=True)

    # --- Filters ------------------------------------------------------------------
    st.subheader("All filings")
    c1, c2, c3 = st.columns([3, 1.4, 1.6])
    chosen = c1.multiselect("Types", list(TYPES), default=list(TYPES), key="fl_types")
    span = c2.selectbox("Time range", list(SPANS), index=1, key="fl_span")
    significant_only = c3.toggle("Only significant 8-Ks", key="fl_sig",
                                 help="Hides routine 8-Ks such as investor presentations "
                                      "(item 7.01) and exhibit-only filings (item 9.01).")

    forms = {f for t in chosen for f in TYPES[t]}
    view = table[table["form"].isin(forms)]
    if SPANS[span]:
        view = view[view["filed"] >= date.today() - timedelta(days=SPANS[span])]
    if significant_only:
        view = view[~view["form"].str.startswith("8-K") | view["significant"]]

    if view.empty:
        st.info("No filings match these filters.")
    else:
        st.dataframe(
            pd.DataFrame({
                "Filed": view["filed"], "Form": view["form"], "Type": view["form_name"],
                "Period": view["period"], "What it's about": view["about"],
                "Document": view["url"],
            }),
            hide_index=True, width="stretch",
            column_config={
                "Document": st.column_config.LinkColumn("Document", display_text="Open"),
                "What it's about": st.column_config.TextColumn(width="large"),
            },
        )
        st.caption(f"{len(view)} filings. \"What it's about\" translates the 8-K item codes "
                   "the company selected, using the SEC's official list. It describes the "
                   "type of event, not its details. The SEC's recent list covers about the "
                   "last 1,000 filings of all kinds.")

    st.markdown('<div class="ca-muted">Questions about these filings? Use the <b>Ask</b> '
                "section: it reads the latest 10-K and 10-Q (or any you choose) and answers "
                "with citations.</div>", unsafe_allow_html=True)
