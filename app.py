"""Company Analyzer: the dashboard page.

This file only handles layout. Data fetching and math live in the analyzer/ folder
(added in later steps).
"""

import streamlit as st

st.set_page_config(page_title="Company Analyzer", layout="wide")

st.title("Company Analyzer")
st.caption("Financial position of public companies, from SEC EDGAR filings.")

st.subheader("Setup check")


def secret_is_set(name: str) -> bool:
    """True if the secret exists and isn't blank. Never displays the value itself."""
    try:
        return bool(str(st.secrets[name]).strip())
    except (KeyError, FileNotFoundError):
        return False


checks = {
    "SEC contact (User-Agent)": secret_is_set("SEC_USER_AGENT"),
    "Anthropic API key": secret_is_set("ANTHROPIC_API_KEY"),
}
for label, ok in checks.items():
    if ok:
        st.success(f"{label}: configured")
    else:
        st.warning(f"{label}: missing. Add it to .streamlit/secrets.toml")
