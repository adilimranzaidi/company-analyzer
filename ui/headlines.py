"""Headlines: recent news about the company and its peers, from the GDELT Project.

Shown as links to the original articles. Nothing is summarized or interpreted by AI here,
and GDELT matches on names, so an occasional irrelevant article can appear.
"""

import html

import streamlit as st

from analyzer.edgar_client import Company
from analyzer.news import build_query, news_name
from ui import data

TIMESPANS = {"Past week": "1week", "Past month": "1month", "Past 3 months": "3months"}


def render(company: Company) -> None:
    c1, c2 = st.columns([2, 1])
    scope = c1.segmented_control("Show", ["Company", "Industry peers"], default="Company",
                                 key="hl_scope") or "Company"
    span_label = c2.selectbox("Time range", list(TIMESPANS), index=1, key="hl_span")
    span = TIMESPANS[span_label]

    if scope == "Company":
        names = [news_name(company.name)]
    else:
        peer_labels = st.session_state.get(f"peers_{company.ticker}")
        if peer_labels is None:
            suggested = data.peers(data.user_agent(), company.cik, company.sic_code)
            names = [news_name(p.name) for p in suggested[:5]]
        else:
            names = [news_name(l.rsplit(" (", 1)[0]) for l in peer_labels[:5]]
        if not names:
            st.info("No peers yet. Choose some in the Industry section.")
            return
        st.markdown(f'<div class="ca-muted">Peers: {html.escape(", ".join(names))} '
                    "(edit them in the Industry section)</div>", unsafe_allow_html=True)

    query = build_query(names)
    with st.spinner("Fetching headlines from GDELT..."):
        articles, error, saved_hours_ago = data.headlines(data.user_agent(), query, span)
    if saved_hours_ago is not None:
        ago = (f"{saved_hours_ago:.0f} hours" if saved_hours_ago >= 1.5
               else f"{saved_hours_ago * 60:.0f} minutes")
        st.info(f"GDELT is busy for your network, so these are the headlines saved {ago} ago.")
    if error:
        st.warning(error)
        if st.button("Try again"):
            st.rerun()
        return
    if not articles:
        st.info(f"No English-language headlines found for {html.escape(', '.join(names))} "
                f"in the {span_label.lower()}.")
        return

    rows = []
    for a in articles[:25]:
        when = a["date"].strftime("%b %d, %Y") if a["date"] else ""
        rows.append(
            f'<div class="ca-headline"><a href="{html.escape(a["url"], quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(a["title"])}</a>'
            f'<div>{html.escape(a["source"])} · {when}</div></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption(f"Search: {query}. Source: the GDELT Project, an open index of worldwide news. "
               "Headlines link to the original articles and aren't checked by this app.")
