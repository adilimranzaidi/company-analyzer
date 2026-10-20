"""Industry: suggested peers (editable), how the industry is trending, where this
company ranks, and the drivers to explore."""

from statistics import median

import pandas as pd
import streamlit as st

from analyzer.charts import format_pct, format_ratio, multi_line_chart
from analyzer.compare import industry_medians, rank_in_group
from analyzer.edgar_client import Company
from analyzer.financials import MetricData
from ui import data
from ui.peer_tables import (SERIES_CHOICES, column_help, load_many, series_for, snapshot_row,
                             snapshots)
from ui.style import placeholder


def render(company: Company, metrics: dict[str, MetricData], options: list[dict]) -> None:
    by_label = {o["label"]: o for o in options}
    self_label = next((o["label"] for o in options if o["ticker"] == company.ticker), company.ticker)

    with st.spinner("Finding competitors (reading the 10-K the first time)..."):
        suggested = data.peers(data.user_agent(), company.cik, company.sic_code)
    suggested_labels = [f"{p.name} ({p.ticker})" for p in suggested]
    suggested_labels = [l for l in suggested_labels if l in by_label]

    named = [p for p in suggested if p.source == "Named in the 10-K"]
    by_code = [p for p in suggested if p.source != "Named in the 10-K"]
    explain = []
    if named:
        explain.append(f"<b>Named as competitors in {company.ticker}'s 10-K:</b> "
                       + ", ".join(p.ticker for p in named))
    if by_code:
        explain.append(f"<b>Same SEC industry code</b> ({company.sic_code}, {company.industry}), "
                       "largest first: " + ", ".join(p.ticker for p in by_code))
    explain.append("Edit the list to fit: remove companies that aren't true peers, and "
                   "search to add others.")
    st.markdown('<div class="ca-muted">' + "<br>".join(explain) + "</div>",
                unsafe_allow_html=True)
    if named:
        with st.expander("Where the 10-K names them"):
            for p in named:
                st.markdown(f"**{p.ticker}** ({p.name}): “{p.evidence}”")

    key = f"peers_{company.ticker}"
    st.session_state.setdefault(key, suggested_labels)
    chosen = st.multiselect("Peer group", [o["label"] for o in options], key=key,
                            max_selections=10, placeholder="Search to add a company")
    if not chosen:
        st.info("Add at least one peer to see industry trends.")
        _drivers()
        return

    loaded = load_many([self_label] + [c for c in chosen if c != self_label], by_label)
    snaps = snapshots(loaded)
    peer_snaps = [s for label, s in snaps.items() if label != self_label]
    med = industry_medians(peer_snaps)

    # --- Snapshot table ---------------------------------------------------------
    st.subheader("Industry snapshot")
    rows = [snapshot_row(label, s) for label, s in snaps.items()]
    rows.append({
        "Company": f"Peer median ({len(peer_snaps)} companies)", "Fiscal year": "",
        "Revenue": "", "Revenue growth": format_pct(med["revenue_growth"]),
        "Net margin": format_ratio(med["net_margin"]), "Return on equity": format_ratio(med["roe"]),
        "EPS growth": format_pct(med["eps_growth"]),
        "Latest quarter revenue growth": format_pct(med["quarter_revenue_growth"]),
    })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=column_help())
    st.caption("Each company's own latest fiscal year; year-ends differ between companies. "
               "The median (middle value) is used so one unusual company can't skew it.")

    # --- Where this company ranks ------------------------------------------------
    if self_label in snaps:
        me = snaps[self_label]
        lines = []
        for k, label in [("revenue_growth", "Revenue growth"), ("net_margin", "Net margin"),
                         ("roe", "Return on equity"), ("eps_growth", "EPS growth")]:
            r = rank_in_group(me[k], [s[k] for s in peer_snaps])
            if r:
                fmt = format_pct if k.endswith("growth") else format_ratio
                vs = med[k]
                comparison = ("above" if vs is not None and me[k] > vs else
                              "below" if vs is not None and me[k] < vs else "at")
                lines.append(f'<div class="ca-row"><span>{label}: {fmt(me[k])}, '
                             f'{comparison} the peer median of {fmt(vs)}</span>'
                             f'<span>{_ordinal(r[0])} of {r[1]}</span></div>')
        if lines:
            st.subheader(f"Where {company.ticker} ranks")
            st.markdown("".join(lines), unsafe_allow_html=True)

    # --- Industry trend chart -----------------------------------------------------
    st.subheader("Industry trends")
    choice = st.selectbox("Measure", SERIES_CHOICES, key="ind_measure")
    company_series = series_for(choice, loaded[self_label][1]) if self_label in loaded \
        else pd.DataFrame()
    peer_series = [series_for(choice, m) for label, (_, m) in loaded.items() if label != self_label]
    median_series = _median_by_period(peer_series)
    series = {company.ticker: company_series.tail(10), "Peer median": median_series.tail(10)}
    st.plotly_chart(multi_line_chart(series, f"{choice}: {company.ticker} vs. peers",
                                     dashed={"Peer median"}), config={"displayModeBar": False}, width="stretch", key="ind_chart")
    st.caption("By fiscal year (each company's own). The peer median for a year uses every "
               "peer with data for that year, and needs at least two.")

    _drivers()


def _median_by_period(frames: list[pd.DataFrame]) -> pd.DataFrame:
    values: dict[str, list[float]] = {}
    ends: dict[str, object] = {}
    for df in frames:
        for _, r in df.iterrows():
            values.setdefault(r["period"], []).append(r["value"])
            ends.setdefault(r["period"], r["end"])
    rows = [{"period": p, "end": ends[p], "value": median(v)} for p, v in values.items()
            if len(v) >= 2]   # a "median" of one company isn't an industry figure
    return pd.DataFrame(rows, columns=["period", "end", "value"]).sort_values("end") \
        if rows else pd.DataFrame(columns=["period", "end", "value"])


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _drivers() -> None:
    st.subheader("Industry drivers")
    placeholder(
        "<b>Coming next.</b> An explorable list of what moves this industry, from two "
        "sources:<br>• <b>What the company says drives its results</b>: pulled from its "
        "10-K risk factors and market-risk disclosures, with citations (after Step 5).<br>"
        "• <b>Macro data</b>: interest rates, consumer credit, card delinquencies, oil and "
        "more from the Federal Reserve's FRED database, charted alongside the company "
        "(Version 2)."
    )
