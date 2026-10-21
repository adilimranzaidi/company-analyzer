"""Headlines: recent news about the company and its peers, from Finnhub, by ticker.

Shown as links to the original articles. Nothing is summarized or interpreted by AI here.
"""

import html

import streamlit as st

from analyzer.edgar_client import Company
from ui import data
from ui.style import placeholder

SPANS = {"Past week": 7, "Past month": 30, "Past 3 months": 90}


def render(company: Company) -> None:
    if not data.get_secret("FINNHUB_API_KEY"):
        placeholder(
            "<b>Headlines need a free Finnhub key.</b><br>1. Create an account at "
            "finnhub.io/register and copy your API key.<br>2. Add this line to "
            "<code>.streamlit/secrets.toml</code>: "
            "<code>FINNHUB_API_KEY = \"your-key\"</code><br>3. Restart the dashboard."
        )
        return

    c1, c2 = st.columns([2, 1])
    scope = c1.segmented_control("Show", ["Company", "Industry peers"], default="Company",
                                 key="hl_scope") or "Company"
    span_label = c2.selectbox("Time range", list(SPANS), index=1, key="hl_span")

    if scope == "Company":
        tickers = (company.ticker,)
    else:
        peer_labels = st.session_state.get(f"peers_{company.ticker}")
        if peer_labels is None:
            suggested = data.peers(data.user_agent(), company.cik, company.sic_code)
            tickers = tuple(p.ticker for p in suggested[:5])
        else:
            tickers = tuple(label.rsplit("(", 1)[-1].rstrip(")") for label in peer_labels[:5])
        if not tickers:
            st.info("No peers yet. Choose some in the Industry section.")
            return
        st.markdown(f'<div class="ca-muted">Peers: {html.escape(", ".join(tickers))} '
                    "(edit them in the Industry section)</div>", unsafe_allow_html=True)

    with st.spinner("Fetching headlines from Finnhub..."):
        articles, error, saved_hours_ago = data.headlines(tickers, SPANS[span_label])
    if error:
        st.warning(error)
        if st.button("Try again"):
            st.rerun()
        return
    if saved_hours_ago is not None:
        ago = (f"{saved_hours_ago:.0f} hours" if saved_hours_ago >= 1.5
               else f"{saved_hours_ago * 60:.0f} minutes")
        st.info(f"Finnhub couldn't be reached, so these are the headlines saved {ago} ago.")
    if not articles:
        st.info(f"No headlines found for {', '.join(tickers)} in the {span_label.lower()}.")
        return

    rows = []
    for a in articles[:30]:
        when = a["date"].strftime("%b %d, %Y") if a["date"] else ""
        tag = f" · {a['ticker']}" if scope != "Company" else ""
        rows.append(
            f'<div class="ca-headline"><a href="{html.escape(a["url"], quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(a["title"])}</a>'
            f'<div>{html.escape(a["source"])} · {when}{html.escape(tag)}</div></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption("Source: Finnhub, matched by ticker. Headlines link to the original articles; "
               "some only mention the company in passing, and they aren't checked by this app.")
