"""Company Analyzer: the dashboard page.

This file only handles layout. Data fetching and math live in the analyzer/ folder.
"""

from datetime import timedelta

import pandas as pd
import streamlit as st

from analyzer.charts import bar_chart, format_pct, format_value, ratio_chart
from analyzer.edgar_client import EdgarClient, EdgarError
from analyzer.financials import MetricData, load_all_metrics
from analyzer.metrics import (
    add_growth,
    margin_tables,
    notable_events,
    roe_annual,
    roe_trailing,
)

st.set_page_config(page_title="Company Analyzer", layout="wide")


def get_secret(name: str) -> str:
    """Read a secret, returning "" if it's missing. Never displays the value."""
    try:
        return str(st.secrets[name]).strip()
    except (KeyError, FileNotFoundError):
        return ""


@st.cache_resource
def get_edgar_client(user_agent: str) -> EdgarClient:
    # Created once and reused, so the pause between SEC requests is respected.
    return EdgarClient(user_agent)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_financials(cik: str, fye_month: int, user_agent: str) -> dict[str, MetricData]:
    facts = get_edgar_client(user_agent).company_facts(cik)
    return load_all_metrics(facts, fye_month)


# --- Sidebar: setup check ---------------------------------------------------
with st.sidebar:
    st.header("Setup check")
    for label, secret in [("SEC contact (User-Agent)", "SEC_USER_AGENT"),
                          ("Anthropic API key", "ANTHROPIC_API_KEY")]:
        if get_secret(secret):
            st.success(f"{label}: configured")
        else:
            st.warning(f"{label}: missing. Add it to .streamlit/secrets.toml")

# --- Header and ticker input ------------------------------------------------
st.title("Company Analyzer")
st.caption("Financial position of public companies, from SEC EDGAR filings.")

ticker = st.text_input(
    "Ticker symbol",
    value="AXP",
    max_chars=10,
    help="The stock ticker, e.g. AXP, AAPL, JPM. For share classes use BRK.B or BRK-B.",
)

try:
    client = get_edgar_client(get_secret("SEC_USER_AGENT"))
    with st.spinner("Looking up the company on SEC EDGAR..."):
        company = client.lookup_company(ticker)
except EdgarError as err:
    st.error(str(err))
    st.stop()

# --- Company card -----------------------------------------------------------
st.header(f"{company.name} ({company.ticker})")

# Plain text (not st.metric) so long values wrap instead of being cut off on narrow screens.
st.markdown(
    f"**SEC CIK:** {company.cik} · "
    f"**Exchange:** {', '.join(company.exchanges) or 'Not listed'} · "
    f"**Fiscal year ends:** {company.fiscal_year_end or 'Unknown'} · "
    f"**Filer category:** {company.filer_category or 'Unknown'}  \n"
    f"**Industry (SEC classification):** {company.industry or 'Not provided'}"
    f"{f' (SIC code {company.sic_code})' if company.sic_code else ''}  \n"
    f"[View all filings on SEC EDGAR]({company.edgar_url})"
)

# --- Load the financial data ------------------------------------------------
st.divider()
try:
    with st.spinner("Downloading financial data from SEC EDGAR..."):
        metrics = get_financials(company.cik, company.fiscal_year_end_month,
                                 get_secret("SEC_USER_AGENT"))
except EdgarError as err:
    st.error(
        "Couldn't load structured financial data for this company. Some filers "
        f"(for example, many funds and recent IPOs) don't have it yet. Details: {err}"
    )
    st.stop()

shown = [md for md in metrics.values() if md.available]
if not shown:
    st.warning("This company has no current XBRL financial data for the metrics we track.")
    st.stop()

# --- Filters: one row, applying to every tab below --------------------------
f1, f2, f3 = st.columns([1, 2, 2])
view = f1.radio("Period", ["Quarterly", "Annual"], horizontal=True)
quarterly = view == "Quarterly"
years = f2.slider("Years of history", min_value=2, max_value=15, value=5)
SENSITIVITY = {"High (more flags)": 2.5, "Medium": 3.0, "Low (fewer flags)": 4.0}
sensitivity = f3.select_slider(
    "Notable-event sensitivity", options=list(SENSITIVITY), value="Medium",
    help="How unusual a year-over-year change must be, compared with the company's own "
         "history, to be flagged. Medium = more than 3 typical deviations from normal.",
)
threshold = SENSITIVITY[sensitivity]


def recent(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = df["end"].max() - timedelta(days=round(365.25 * years))
    return df[df["end"] > cutoff]


def table_for(md: MetricData) -> pd.DataFrame:
    return md.quarterly if quarterly else md.annual


# Unusual changes are measured against the FULL history (so "normal" is stable),
# then limited to the years being viewed.
events = notable_events(metrics, quarterly, threshold=threshold)
events = recent(events) if not events.empty else events
unusual_by_metric = events.groupby("metric_key")["period"].apply(set).to_dict() if not events.empty else {}

tab_fin, tab_growth, tab_events = st.tabs(
    ["Financials", "Growth & margins", f"Notable events ({len(events)})"]
)

# =============================================================================
# Tab 1: Financials
# =============================================================================
with tab_fin:
    st.caption(
        "Every number comes from the company's own XBRL-tagged SEC filings. "
        "The EDGAR label used for each metric is shown under its chart."
    )

    # Summary table: latest values at a glance (also the text version of the charts).
    summary = []
    for md in shown:
        unit = md.metric.unit
        last_q = md.quarterly.iloc[-1] if not md.quarterly.empty else None
        last_y = md.annual.iloc[-1] if not md.annual.empty else None
        summary.append({
            "Metric": md.metric.name,
            "Latest quarter": f"{format_value(last_q['value'], unit)} ({last_q['period']})"
                              if last_q is not None else "-",
            "Latest fiscal year": f"{format_value(last_y['value'], unit)} ({last_y['period']})"
                                  if last_y is not None else "-",
            "EDGAR label used": md.choice.label,
        })
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")

    for i in range(0, len(shown), 2):
        cols = st.columns(2)
        for col, md in zip(cols, shown[i:i + 2]):
            with col:
                df = recent(table_for(md))
                if df.empty:
                    st.info(f"{md.metric.name}: no {view.lower()} data reported.")
                    continue
                st.plotly_chart(
                    bar_chart(df, md.metric.name, md.metric.unit,
                              unusual=unusual_by_metric.get(md.metric.key)),
                    width="stretch", key=f"bar_{md.metric.key}",
                )
                st.caption(f"{md.metric.description}  \nEDGAR label: `{md.choice.label}`")
                if md.metric.key == "eps_diluted":
                    notes = set(df["source"]) - {"Reported"}
                    if notes:
                        st.caption("Per-share history is restated onto today's share count: "
                                   + "; ".join(sorted(notes)) + ".")
                    if quarterly:
                        st.caption(
                            "Q4 EPS isn't derived: per-share figures can't be subtracted "
                            "because the number of shares changes during the year."
                        )
                with st.expander("Data table and label details"):
                    t = df[["period", "end", "value", "source", "form", "filed",
                            "orig_form", "orig_filed"]].copy()
                    t["value"] = t["value"].apply(lambda v: format_value(v, md.metric.unit))
                    t["latest"] = t["form"] + " filed " + t["filed"].astype(str)
                    t["first"] = t["orig_form"] + " filed " + t["orig_filed"].astype(str)
                    t = t[["period", "end", "value", "source", "latest", "first"]]
                    t.columns = ["Period", "Period end", "Value", "Source",
                                 "Value taken from", "First reported in"]
                    st.dataframe(t.iloc[::-1], hide_index=True, width="stretch")
                    if md.choice.passed_over:
                        st.markdown("Other labels found but **not used** (less recent data):")
                        for label, end in md.choice.passed_over:
                            st.markdown(f"- `{label}`: data through {end}")

    missing = [md for md in metrics.values() if not md.available]
    if missing:
        with st.expander(f"Not shown for {company.ticker} ({len(missing)} metrics)"):
            for md in missing:
                if md.discontinued:
                    st.markdown(
                        f"- **{md.metric.name}**: no longer reported. Last data "
                        f"{md.choice.latest_end} under `{md.choice.label}`."
                    )
                else:
                    st.markdown(
                        f"- **{md.metric.name}**: not reported. None of these EDGAR labels "
                        f"appear: {', '.join(f'`{l}`' for l in md.metric.labels)}"
                    )
            st.caption(
                "This is normal: banks and card issuers don't report gross profit or "
                "operating income, and non-lenders don't report net interest income or "
                "credit provisions."
            )

# =============================================================================
# Tab 2: Growth & margins
# =============================================================================
with tab_growth:
    st.caption("All growth rates and ratios are calculated in Python from the figures on "
               "the Financials tab. Hover over a point to see the exact inputs.")

    st.subheader("Growth")
    growth_rows = []
    for md in shown:
        g = add_growth(table_for(md), quarterly)
        if g.empty:
            continue
        last = g.iloc[-1]
        row = {"Metric": md.metric.name, "Latest period": last["period"],
               "Value": format_value(last["value"], md.metric.unit),
               "vs. same period last year": format_pct(last["yoy_growth"])}
        if quarterly:
            row["vs. previous quarter"] = format_pct(last["qoq_growth"])
        growth_rows.append(row)
    st.dataframe(pd.DataFrame(growth_rows), hide_index=True, width="stretch")
    st.caption(
        "n/m = not meaningful (the earlier figure was zero, negative, or missing). "
        + ("Quarter-over-quarter changes include normal seasonal swings; year-over-year "
           "is usually the better comparison." if quarterly else "")
    )

    st.subheader("Margins and return on equity")
    ratio_charts = [(r.name, r.formula, df) for r, df in margin_tables(metrics, quarterly).values()]
    ni, eq = metrics["net_income"], metrics["equity"]
    if ni.available and eq.available:
        if quarterly:
            roe = roe_trailing(ni.quarterly, eq.quarterly)
            ratio_charts.append(("Return on equity (trailing 12 months)",
                                 "Last 4 quarters' net income ÷ average equity", roe))
        else:
            roe = roe_annual(ni.annual, eq.annual)
            ratio_charts.append(("Return on equity", "Net income ÷ average equity", roe))

    ratio_charts = [(n, f, recent(df)) for n, f, df in ratio_charts if not df.empty]
    if not ratio_charts:
        st.info("Not enough data to calculate margins for this company.")
    for i in range(0, len(ratio_charts), 2):
        cols = st.columns(2)
        for col, (name, formula, df) in zip(cols, ratio_charts[i:i + 2]):
            with col:
                st.plotly_chart(ratio_chart(df, name, formula), width="stretch",
                                key=f"ratio_{name}")
                caption = f"Formula: {formula}"
                notes = set(df["source"]) - {"Reported inputs"}
                if notes:
                    caption += "  \nSome periods: " + "; ".join(sorted(notes))
                st.caption(caption)

    if not metrics["gross_profit"].available:
        st.caption("Gross and operating margins only appear for companies that report "
                   "those figures. Banks and card issuers generally don't.")

    with st.expander("How these are calculated"):
        st.markdown(
            "- **Year-over-year growth** = (this period − same period last year) ÷ same "
            "period last year. Periods are matched by fiscal label, never by position.\n"
            "- **Margin** = profit measure ÷ revenue for the same period.\n"
            "- **Return on equity (annual)** = fiscal-year net income ÷ average of "
            "shareholders' equity at the start and end of the year.\n"
            "- **Return on equity (quarterly view)** = the last four quarters' net income "
            "÷ average of equity now and four quarters earlier.\n"
            "- If any input was derived (for example a calculated Q4), the chart says so."
        )

# =============================================================================
# Tab 3: Notable events
# =============================================================================
with tab_events:
    st.caption(
        "Periods where a metric's year-over-year change was unusual **for this company**, "
        "judged against its own history. Python does the flagging. In Step 5b, each event "
        "will get an \"Explain from filing\" button that shows management's explanation "
        "from the 10-Q or 10-K, with citations."
    )
    if events.empty:
        st.info(f"No unusual {view.lower()} changes in the last {years} years at "
                f"{sensitivity.lower()} sensitivity.")
    else:
        names = sorted(events["metric"].unique())
        chosen = st.multiselect("Show metrics", names, default=names)
        ev = events[events["metric"].isin(chosen)]
        display = pd.DataFrame({
            "Period": ev["period"],
            "Metric": ev["metric"],
            "Value": [format_value(v, u) for v, u in zip(ev["value"], ev["unit"])],
            "Same period last year": [format_value(v, u) for v, u in
                                      zip(ev["prior_year_value"], ev["unit"])],
            "Change": [format_pct(g) for g in ev["yoy_growth"]],
            "Typical change": [format_pct(g) for g in ev["typical_growth"]],
            "First reported in": [f"{f} filed {d}" for f, d in
                                  zip(ev["orig_form"], ev["orig_filed"])],
        })
        st.dataframe(display, hide_index=True, width="stretch")
        st.caption(
            "\"Typical change\" is the median year-over-year change across all of this "
            "company's history for that metric. A period is flagged when its change is far "
            "from typical (more than "
            f"{threshold:g} typical deviations, and at least 10 percentage points). "
            "Several metrics flagged in the same period usually point to one underlying "
            "event, such as COVID-19 in 2020-21."
        )
