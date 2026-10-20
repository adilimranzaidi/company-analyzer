"""Overview: the calm landing page. A few key figures and the latest notable events;
charts only when asked for."""

import html

import streamlit as st

from analyzer.charts import bar_chart, format_pct, format_ratio, format_value
from analyzer.compare import trailing_roe_latest
from analyzer.edgar_client import Company
from analyzer.glossary import short
from analyzer.financials import MetricData
from analyzer.metrics import add_growth, unusual_changes
from ui import data
from ui.style import placeholder


def _go_to(section: str, sub: str | None = None) -> None:
    st.session_state["section"] = section
    if sub:
        st.session_state["trends_view"] = sub
    if section == "News and events":
        st.session_state["news_view"] = "Notable events"


def _figure(md: MetricData | None):
    """(label, value, change vs last year, period) for the latest quarter."""
    if md is None or not md.available or md.quarterly.empty:
        return None
    last = add_growth(md.quarterly, quarterly=True).iloc[-1]
    return last


def render(company: Company, metrics: dict[str, MetricData]) -> None:
    st.subheader("About")
    placeholder(
        "A plain-English synopsis of what the company does, how it makes money, its "
        "latest quarter, recent events and key risks, written from its own filings with "
        "citations, arrives in <b>Step 5c</b>."
    )

    # --- Key figures -------------------------------------------------------
    rev = _figure(metrics.get("revenue"))
    period = rev["period"] if rev is not None else None
    st.subheader(f"Latest quarter{f' · {period}' if period else ''}")

    tiles = []
    for key, label in [("revenue", "Revenue"), ("net_income", "Net income"),
                       ("eps_diluted", "Diluted EPS")]:
        last = _figure(metrics.get(key))
        if last is not None:
            tiles.append((label, format_value(last["value"], metrics[key].metric.unit),
                          format_pct(last["yoy_growth"]), last["period"]))
    roe = trailing_roe_latest(metrics)
    if roe is not None:
        tiles.append(("Return on equity", format_ratio(roe["value"]), None, roe["period"]))

    if tiles:
        cols = st.columns(len(tiles))
        for col, (label, value, change, p) in zip(cols, tiles):
            delta = None if change in (None, "n/m") else f"{change} vs. a year ago"
            col.metric(label, value, delta=delta,
                       help=f"{short(label)} ({p}" + (", last 4 quarters" if label ==
                                                      "Return on equity" else "") + ")")
        src = metrics["revenue"].quarterly.iloc[-1] if rev is not None else None
        if src is not None:
            st.markdown(f'<div class="ca-muted">From the {src["form"]} filed {src["filed"]}. '
                        "All figures come from SEC filings; changes are calculated in Python."
                        "</div>", unsafe_allow_html=True)
    else:
        st.info("No recent quarterly figures are available for this company.")

    # --- Latest notable events (from 8-K filings) ----------------------------
    st.subheader("Latest notable events")
    with st.spinner("Reading 8-K filings and daily prices (first time only)..."):
        events, _ = data.all_events(data.user_agent(), company.cik, company.ticker)
    if not events:
        st.markdown(f'<div class="ca-muted">No notable 8-K events in the last '
                    f'{data.EVENT_YEARS} years.</div>', unsafe_allow_html=True)
    else:
        rows = []
        for e in events[:4]:
            link = (f' · <a href="{html.escape(e.url, quote=True)}" target="_blank">{e.form}</a>'
                    if e.url else "")
            rows.append(f'<div class="ca-row"><span>{html.escape(e.title)}</span>'
                        f'<span>{e.date:%b %d, %Y}{link}</span></div>')
        st.markdown("".join(rows), unsafe_allow_html=True)

    changes = unusual_changes(metrics, quarterly=True)
    if not changes.empty:
        latest = changes.iloc[0]
        st.markdown(f'<div class="ca-muted" style="margin-top:0.5rem">Also: {len(changes)} '
                    f"unusual changes in the financials (latest: {html.escape(latest['metric'])}, "
                    f"{latest['period']}). See Company trends › Unusual changes.</div>",
                    unsafe_allow_html=True)

    c1, c2, c3, _ = st.columns([1.1, 1.1, 1, 1.5])
    c1.button("All notable events", on_click=_go_to, args=("News and events",),
              width="stretch")
    c2.button("Unusual changes", on_click=_go_to, args=("Company trends", "Unusual changes"),
              width="stretch")
    show = c3.toggle("Show key charts", value=False)

    if show:
        cols = st.columns(2)
        for col, key in zip(cols, ["revenue", "net_income"]):
            md = metrics.get(key)
            if md and md.available and not md.quarterly.empty:
                df = md.quarterly.tail(12)
                col.plotly_chart(bar_chart(df, md.metric.name, md.metric.unit),
                                 config={"displayModeBar": False}, width="stretch", key=f"ov_{key}")
        st.markdown('<div class="ca-muted">Last 12 quarters. More in Company trends.</div>',
                    unsafe_allow_html=True)
