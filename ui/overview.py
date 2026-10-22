"""Overview: the calm landing page. A few key figures and the latest notable events;
charts only when asked for."""

import html
from dataclasses import replace

import streamlit as st

from analyzer.assistant import ask, dashboard_figures, friendly_error
from analyzer.charts import bar_chart, format_pct, format_ratio, format_value
from analyzer.compare import trailing_roe_latest
from analyzer.edgar_client import Company, EdgarError, pretty_company_name
from analyzer.explain import cache_key, load_saved, save
from analyzer.filings import latest_reports
from analyzer.financials import MetricData
from analyzer.glossary import short
from analyzer.metrics import add_growth, unusual_changes
from analyzer.synopsis import LENGTH_RULE, REQUEST, identifier, pick_passages
from ui import data
from ui.ask import _filing_label, _show_answer
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


def _synopsis(company: Company, metrics: dict[str, MetricData]) -> None:
    """The company briefing: shown if already written for the latest filings, otherwise a
    button that writes it (once per new 10-K or 10-Q, then saved)."""
    try:
        reports = latest_reports(data.filings(data.user_agent(), company.cik))
    except EdgarError:
        placeholder("The company's filings couldn't be loaded, so there's no synopsis yet.")
        return
    annual, quarterly = reports.annual, reports.quarterly
    if not annual:
        placeholder("No annual report (10-K) was found, so a synopsis can't be written.")
        return
    # The newest periodic report explains the latest results: usually a 10-Q, but right
    # after the fiscal year ends it's the 10-K itself.
    recent = quarterly if quarterly and quarterly["filed"] > annual["filed"] else annual
    key = cache_key(company.cik, "synopsis", identifier(annual["accession"], recent["accession"]))

    saved = load_saved(key)
    if saved:
        # The briefing's own headings sit one level below the page's section headings.
        _show_answer(replace(saved, text=saved.text.replace("### ", "#### ")),
                     show_cost=False)
        st.caption(f"Written from the {annual['form']} filed {annual['filed']:%b %d, %Y}"
                   + (f" and the {recent['form']} filed {recent['filed']:%b %d, %Y}"
                      if recent is not annual else "")
                   + ". A new synopsis can be written when the company files its next report.")
        return
    st.markdown('<div class="ca-muted">A short briefing on what the company does, how it '
                "makes money, its latest quarter, recent events, key risks and interview "
                "talking points, written from its own filings with sources.</div>",
                unsafe_allow_html=True)
    if not data.get_secret("ANTHROPIC_API_KEY"):
        st.caption("Add an Anthropic API key to write the synopsis.")
        return
    if not st.button("Write synopsis", key=f"synopsis_{key}",
                     help="Reads the latest 10-K and 10-Q (about 15 seconds, under 1¢). "
                          "Saved afterwards, so reopening it is free."):
        return

    with st.spinner("Reading the latest 10-K and 10-Q and writing the synopsis..."):
        try:
            agent = data.user_agent()
            annual_passages = data.filing_row_passages(agent, annual, _filing_label(annual))
            recent_passages = (annual_passages if recent is annual else
                               data.filing_row_passages(agent, recent, _filing_label(recent)))
            passages = pick_passages(annual_passages, recent_passages)
            events = data.all_events(agent, company.cik, company.ticker)[0]
            searched = (f"the {annual['form']} filed {annual['filed']:%b %Y}"
                        + (f" and the {recent['form']} filed {recent['filed']:%b %Y}"
                           if recent is not annual else ""))
            answer = ask(data.get_secret("ANTHROPIC_API_KEY"), company,
                         REQUEST.format(name=pretty_company_name(company.name)), passages,
                         dashboard_figures(company, metrics, events), [],
                         searched=searched, length_rule=LENGTH_RULE)
        except Exception as err:            # shown to the user, never a crash
            st.error(friendly_error(err))
            return
    save(key, answer)
    st.rerun()                              # show it the same way a saved synopsis is shown


def render(company: Company, metrics: dict[str, MetricData]) -> None:
    # Order: the most important, quickest-to-read things first (figures, events), then the
    # longer written briefing.

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
        for col, (label, value, change, p) in zip(cols, tiles, strict=True):
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
        st.markdown(f'<div class="ca-muted" style="margin-top:0.5rem">Latest unusual change '
                    f"in the financials: {html.escape(latest['metric'])}, {latest['period']}."
                    "</div>", unsafe_allow_html=True)

    c1, c2, c3, _ = st.columns([1.1, 1.1, 1, 1.5])
    c1.button("All notable events", on_click=_go_to, args=("News and events",),
              width="stretch")
    c2.button("Unusual changes", on_click=_go_to, args=("Company trends", "Unusual changes"),
              width="stretch")
    show = c3.toggle("Show key charts", value=False)

    if show:
        cols = st.columns(2)
        for col, key in zip(cols, ["revenue", "net_income"], strict=True):
            md = metrics.get(key)
            if md and md.available and not md.quarterly.empty:
                df = md.quarterly.tail(12)
                col.plotly_chart(bar_chart(df, md.metric.name, md.metric.unit),
                                 config={"displayModeBar": False}, width="stretch", key=f"ov_{key}")
        st.markdown('<div class="ca-muted">Last 12 quarters. More in Company trends.</div>',
                    unsafe_allow_html=True)

    # --- Written briefing ------------------------------------------------------
    st.subheader("Company briefing")
    _synopsis(company, metrics)
