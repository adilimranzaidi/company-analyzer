"""Company Analyzer: the dashboard page.

This file only handles layout. Data fetching and math live in the analyzer/ folder.
"""

import streamlit as st

from analyzer.edgar_client import EdgarClient, EdgarError

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

col1, col2, col3, col4 = st.columns(4)
col1.metric("SEC CIK number", company.cik)
col2.metric("Exchange", ", ".join(company.exchanges) or "Not listed")
col3.metric("Fiscal year ends", company.fiscal_year_end or "Unknown")
col4.metric("Filer category", company.filer_category or "Unknown")

st.markdown(
    f"**Industry (SEC classification):** {company.industry or 'Not provided'}"
    f"{f' · SIC code {company.sic_code}' if company.sic_code else ''}  \n"
    f"[View all filings on SEC EDGAR]({company.edgar_url})"
)
