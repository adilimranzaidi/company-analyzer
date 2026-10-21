"""Company trends: one chart at a time by default, with the option to show them all."""

from datetime import timedelta

import pandas as pd
import streamlit as st

from analyzer.charts import bar_chart, format_pct, format_ratio, format_value, ratio_chart
from analyzer.edgar_client import Company
from analyzer.filings import index_url
from analyzer.financials import MetricData
from analyzer.glossary import short
from analyzer.metrics import add_growth, margin_tables, roe_annual, roe_trailing, unusual_changes
from ui.terms import explain

SENSITIVITY = {"High": 2.5, "Medium": 3.0, "Low": 4.0}
VIEWS = ["Financials", "Growth and margins", "Unusual changes"]


def _recent(df: pd.DataFrame, years: int) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = df["end"].max() - timedelta(days=round(365.25 * years))
    return df[df["end"] > cutoff]


def render(company: Company, metrics: dict[str, MetricData]) -> None:
    shown = [md for md in metrics.values() if md.available]
    if not shown:
        st.warning("This company has no current XBRL financial data for the metrics we track.")
        return

    # --- Settings (one row, applies to everything below) --------------------
    st.session_state.setdefault("trends_view", VIEWS[0])
    view = st.segmented_control("View", VIEWS, key="trends_view", label_visibility="collapsed")
    view = view or VIEWS[0]
    with st.expander("Chart settings", expanded=False):
        c1, c2, c3 = st.columns(3)
        period = c1.radio("Period", ["Quarterly", "Annual"], horizontal=True, key="tr_period")
        years = c2.slider("Years of history", 2, 15, 5, key="tr_years")
        sens = c3.select_slider("Notable-event sensitivity", list(SENSITIVITY), "Medium",
                                key="tr_sens",
                                help="How unusual a change must be, against the company's own "
                                     "history, to be flagged. High flags more.")
    quarterly = period == "Quarterly"
    threshold = SENSITIVITY[sens]
    st.markdown(f'<div class="ca-muted">{period} · last {years} years · '
                f'{sens.lower()} sensitivity (change in Chart settings)</div>',
                unsafe_allow_html=True)

    events = unusual_changes(metrics, quarterly, threshold=threshold)
    events = _recent(events, years) if not events.empty else events
    unusual = (events.groupby("metric_key")["period"].apply(set).to_dict()
               if not events.empty else {})

    if view == "Financials":
        _financials(shown, metrics, quarterly, years, unusual, company)
    elif view == "Growth and margins":
        _growth(shown, metrics, quarterly, years)
    else:
        _events(events, period, years, sens, company.cik)


# -----------------------------------------------------------------------------

def _metric_chart(md: MetricData, quarterly: bool, years: int, unusual: dict, key: str,
                  cik: str):
    df = _recent(md.quarterly if quarterly else md.annual, years)
    if df.empty:
        st.info(md.note or f"{md.metric.name}: no {'quarterly' if quarterly else 'annual'} "
                "data reported.")
        return
    st.plotly_chart(bar_chart(df, md.metric.name, md.metric.unit,
                              unusual=unusual.get(md.metric.key)),
                    config={"displayModeBar": False}, width="stretch", key=key)
    definition = explain(md.metric.name) or md.metric.description
    st.caption(f"{definition} EDGAR label: `{md.choice.label}`"
               + (f"  \n{md.note}" if md.note else ""))
    notes = set(df["source"]) - {"Reported"}
    if md.metric.key == "eps_diluted":
        split_notes = [n for n in notes if n.startswith("Adjusted")]
        if split_notes:
            st.caption("Restated onto today's share count: " + "; ".join(sorted(split_notes)) + ".")
        if quarterly:
            st.caption("Q4 EPS isn't derived: per-share figures can't be subtracted, because "
                       "the share count changes during the year.")
    with st.expander("Data table and sources"):
        t = df[["period", "end", "value", "source", "form", "filed", "orig_form",
                "orig_filed", "orig_accn"]].copy()
        t["value"] = t["value"].apply(lambda v: format_value(v, md.metric.unit))
        t["latest"] = t["form"] + " filed " + t["filed"].astype(str)
        t["first"] = t["orig_form"] + " filed " + t["orig_filed"].astype(str)
        t["link"] = [index_url(cik, a) for a in t["orig_accn"]]
        t = t[["period", "end", "value", "source", "latest", "first", "link"]]
        t.columns = ["Period", "Period end", "Value", "Source", "Value taken from",
                     "First reported in", "Filing"]
        st.dataframe(t.iloc[::-1], hide_index=True, width="stretch",
                     column_config={"Filing": st.column_config.LinkColumn(
                         "Filing", display_text="Open")})
        if md.choice.passed_over:
            st.markdown("Other EDGAR labels found but not used (less recent data): "
                        + ", ".join(f"`{label}` (to {end})"
                                    for label, end in md.choice.passed_over))


def _financials(shown, metrics, quarterly, years, unusual, company):
    names = [md.metric.name for md in shown]
    c1, c2 = st.columns([3, 1])
    choice = c1.selectbox("Metric", names, key="tr_metric")
    show_all = c2.toggle("Show all charts", key="tr_all")

    if not show_all:
        md = next(m for m in shown if m.metric.name == choice)
        _metric_chart(md, quarterly, years, unusual, key=f"one_{md.metric.key}", cik=company.cik)
    else:
        for i in range(0, len(shown), 2):
            cols = st.columns(2)
            for col, md in zip(cols, shown[i:i + 2], strict=False):   # the last row may have one
                with col:
                    _metric_chart(md, quarterly, years, unusual, key=f"all_{md.metric.key}",
                                  cik=company.cik)

    with st.expander("All latest figures, and metrics not shown"):
        rows = []
        for md in shown:
            q = md.quarterly.iloc[-1] if not md.quarterly.empty else None
            y = md.annual.iloc[-1] if not md.annual.empty else None
            rows.append({
                "Metric": md.metric.name,
                "Latest quarter": f"{format_value(q['value'], md.metric.unit)} ({q['period']})"
                                  if q is not None else "-",
                "Latest fiscal year": f"{format_value(y['value'], md.metric.unit)} ({y['period']})"
                                      if y is not None else "-",
                "EDGAR label used": md.choice.label,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for md in (m for m in metrics.values() if not m.available):
            if md.discontinued:
                st.markdown(f"- **{md.metric.name}**: no longer reported (last data "
                            f"{md.choice.latest_end}, `{md.choice.label}`).")
            elif md.metric.key == "eps_diluted":
                st.markdown(f"- **{md.metric.name}**: not reported as a single figure. "
                            "Companies with several share classes (like Visa or Berkshire "
                            "Hathaway) tag EPS separately for each class.")
            else:
                st.markdown(f"- **{md.metric.name}**: not reported by {company.ticker}.")
        st.caption("Normal: banks and card issuers don't report gross profit or operating "
                   "income, and non-lenders don't report net interest income or credit provisions.")


def _growth(shown, metrics, quarterly, years):
    rows = []
    for md in shown:
        g = add_growth(md.quarterly if quarterly else md.annual, quarterly)
        if g.empty:
            continue
        last = g.iloc[-1]
        row = {"Metric": md.metric.name, "Latest period": last["period"],
               "Value": format_value(last["value"], md.metric.unit),
               "vs. a year earlier": format_pct(last["yoy_growth"])}
        if quarterly:
            row["vs. previous quarter"] = format_pct(last["qoq_growth"])
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
        "vs. a year earlier": st.column_config.TextColumn(help=short("Year-over-year growth")),
        "vs. previous quarter": st.column_config.TextColumn(
            help=short("Quarter-over-quarter growth")),
    })
    st.caption("n/m = not meaningful (the earlier figure was zero, negative or missing).")

    charts = [(r.name, r.formula, df) for r, df in margin_tables(metrics, quarterly).values()]
    ni, eq = metrics["net_income"], metrics["equity"]
    if ni.available and eq.available:
        if quarterly:
            charts.append(("Return on equity (trailing 12 months)",
                           "Last 4 quarters' net income ÷ average equity",
                           roe_trailing(ni.quarterly, eq.quarterly)))
        else:
            charts.append(("Return on equity", "Net income ÷ average equity",
                           roe_annual(ni.annual, eq.annual)))
    charts = [(n, f, _recent(df, years)) for n, f, df in charts if not df.empty]
    if not charts:
        st.info("Not enough data to calculate margins for this company.")
        return

    c1, c2 = st.columns([3, 1])
    choice = c1.selectbox("Ratio", [n for n, _, _ in charts], key="tr_ratio")
    show_all = c2.toggle("Show all charts", key="tr_ratio_all")
    selected = charts if show_all else [c for c in charts if c[0] == choice]
    for i in range(0, len(selected), 2 if show_all else 1):
        cols = st.columns(2 if show_all else 1)
        for col, (name, formula, df) in zip(cols, selected[i:i + 2], strict=False):
            with col:
                st.plotly_chart(ratio_chart(df, name, formula),
                                config={"displayModeBar": False}, width="stretch",
                                key=f"ratio_{name}_{show_all}")
                note = f"{short(name.split(' (')[0])} Formula: {formula}."
                derived = set(df["source"]) - {"Reported inputs"}
                if derived:
                    note += " Some periods: " + "; ".join(sorted(derived)) + "."
                st.caption(note)
    latest = {n: format_ratio(df.iloc[-1]["value"]) for n, _, df in charts}
    st.markdown('<div class="ca-muted">Latest: ' + " · ".join(f"{k} {v}" for k, v in latest.items())
                + "</div>", unsafe_allow_html=True)


def _events(events, period, years, sens, cik):
    st.markdown(
        '<div class="ca-muted">Changes that were unusual <i>for this company</i>, judged '
        "against its own history. Python does the flagging. In Step 5b, each event gets an "
        "\"Explain from filing\" button with management's own explanation, cited.</div>",
        unsafe_allow_html=True)
    if events.empty:
        st.info(f"No unusual {period.lower()} changes in the last {years} years at "
                f"{sens.lower()} sensitivity.")
        return
    names = sorted(events["metric"].unique())
    chosen = st.multiselect("Metrics", names, default=names, key="ev_metrics")
    ev = events[events["metric"].isin(chosen)]
    st.dataframe(pd.DataFrame({
        "Period": ev["period"], "Metric": ev["metric"],
        "Value": [format_value(v, u) for v, u in zip(ev["value"], ev["unit"], strict=True)],
        "A year earlier": [format_value(v, u) for v, u in
                           zip(ev["prior_year_value"], ev["unit"], strict=True)],
        "Change": [format_pct(g) for g in ev["yoy_growth"]],
        "Typical change": [format_pct(g) for g in ev["typical_growth"]],
        "First reported in": [f"{f} filed {d}" for f, d in
                              zip(ev["orig_form"], ev["orig_filed"], strict=True)],
        "Filing": [index_url(cik, a) for a in ev["orig_accn"]],
    }), hide_index=True, width="stretch",
        column_config={"Filing": st.column_config.LinkColumn("Filing", display_text="Open")})
    st.caption("\"Typical change\" is the company's median year-over-year change for that "
               "metric. Several metrics flagged in one period usually share one cause, such "
               "as COVID-19 in 2020-21.")
