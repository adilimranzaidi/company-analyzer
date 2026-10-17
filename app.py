"""Company Analyzer: the dashboard page.

This file only handles layout. Data fetching and math live in the analyzer/ folder.
"""

from datetime import timedelta

import pandas as pd
import streamlit as st

from analyzer.charts import bar_chart, format_value
from analyzer.edgar_client import EdgarClient, EdgarError
from analyzer.financials import MetricData, load_all_metrics

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

# --- Key financials ---------------------------------------------------------
st.divider()
st.header("Key financials")
st.caption(
    "Every number comes from the company's own XBRL-tagged SEC filings. "
    "The EDGAR label used for each metric is shown under its chart."
)

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

# Filters: one row, applying to every chart below.
f1, f2 = st.columns([1, 2])
view = f1.radio("Period", ["Quarterly", "Annual"], horizontal=True)
years = f2.slider("Years of history", min_value=2, max_value=15, value=5)


def recent(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cutoff = df["end"].max() - timedelta(days=round(365.25 * years))
    return df[df["end"] > cutoff]


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

# Charts, two per row.
for i in range(0, len(shown), 2):
    cols = st.columns(2)
    for col, md in zip(cols, shown[i:i + 2]):
        with col:
            df = recent(md.quarterly if view == "Quarterly" else md.annual)
            if df.empty:
                st.info(f"{md.metric.name}: no {view.lower()} data reported.")
                continue
            st.plotly_chart(bar_chart(df, md.metric.name, md.metric.unit),
                            width="stretch")
            st.caption(f"{md.metric.description}  \nEDGAR label: `{md.choice.label}`")
            if md.metric.key == "eps_diluted" and view == "Quarterly":
                st.caption(
                    "Q4 EPS isn't derived: per-share figures can't be subtracted "
                    "because the number of shares changes during the year."
                )
            with st.expander("Data table and label details"):
                table = df[["period", "end", "value", "source", "form", "filed"]].copy()
                table["value"] = table["value"].apply(lambda v: format_value(v, md.metric.unit))
                table.columns = ["Period", "Period end", "Value", "Source",
                                 "From filing", "Filed on"]
                st.dataframe(table.iloc[::-1], hide_index=True, width="stretch")
                if md.choice.passed_over:
                    st.markdown("Other labels found but **not used** (less recent data):")
                    for label, end in md.choice.passed_over:
                        st.markdown(f"- `{label}`: data through {end}")

# Metrics we track but can't show, with the reason.
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
            "This is normal: banks and card issuers don't report gross profit or operating "
            "income, and non-lenders don't report net interest income or credit provisions."
        )
