"""Filings and Q&A: arrives in Steps 4, 5 and 5b."""

import streamlit as st

from analyzer.edgar_client import Company
from ui.style import placeholder


def render(company: Company) -> None:
    placeholder(
        "<b>Coming in the next steps:</b><br>"
        "• <b>Step 4:</b> the latest 10-K (annual), 10-Q (quarterly) and 8-K (current event) "
        "filings, with links.<br>"
        "• <b>Step 5:</b> ask questions about the company, answered from its filings with "
        "citations, or a clear \"the filings don't say\".<br>"
        "• <b>Step 5b:</b> \"Explain from filing\" for each notable event."
    )
    st.markdown(f"Meanwhile, every filing is on [SEC EDGAR]({company.edgar_url}).")
