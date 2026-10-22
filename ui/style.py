"""Small visual touches on top of the theme in .streamlit/config.toml."""

import re

import pandas as pd
import streamlit as st

CSS = """
<style>
/* Load EB Garamond directly too: Streamlit's own theme font loading sometimes doesn't run,
   and the page then fell back to a plain sans-serif. (@import must come first.) */
@import url("https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500;600&display=swap");
/* The browser is told this is a light page (form controls, scrollbars). */
:root { color-scheme: light; }
/* Heading scale (h1 company, h2 sections, h3 parts of a section). App screens keep titles
   modest (under 32px). Letter-spacing depends on size: large type tightened, small type not. */
h1, h2, h3 { font-weight: 500 !important; }
h1 { font-size: 1.85rem !important; line-height: 1.1 !important; letter-spacing: -0.015em; }
h2 { font-size: 1.4rem !important; line-height: 1.2 !important; letter-spacing: -0.005em;
     padding: 1.6rem 0 0.5rem !important; }
h3 { font-size: 1.06rem !important; font-weight: 600 !important; letter-spacing: 0;
     padding: 1rem 0 0.2rem !important; }
@media (max-width: 640px) { h1 { font-size: 1.45rem !important; } }
/* Comfortable reading line height for written text */
[data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] p {
  line-height: 1.55; }
/* Written text stops at a comfortable reading width (about 80 characters a line). */
[data-testid="stMarkdownContainer"] > p, [data-testid="stMarkdownContainer"] li,
[data-testid="stCaptionContainer"], .ca-muted { max-width: 80ch; }
/* Figures: even-height, equal-width numerals wherever numbers are compared, so they line up
   (Garamond's default numerals vary in height and width). */
[data-testid="stMetricValue"], [data-testid="stMetricDelta"], [data-testid="stDataFrame"],
.ca-row, .ca-event-date, table { font-variant-numeric: lining-nums tabular-nums; }
/* Key figures: one ruled band split by thin lines, like the highlights strip of an annual
   report, instead of four tinted tiles. */
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
  gap: 0 !important; border-top: 1px solid #d9d5ca; border-bottom: 1px solid #d9d5ca; }
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"]
  + [data-testid="stColumn"] { border-left: 1px solid #e6e3da; }
[data-testid="stMetric"] { padding: 14px 18px 12px; }
/* On a phone the four figures form a 2 x 2 grid instead of one long column. */
@media (max-width: 640px) {
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {
    display: grid !important; grid-template-columns: 1fr 1fr; }
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
    width: auto !important; min-width: 0 !important; border-left: none !important; }
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])
    > [data-testid="stColumn"]:nth-child(even) { border-left: 1px solid #e6e3da !important; }
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])
    > [data-testid="stColumn"]:nth-child(n+3) { border-top: 1px solid #e6e3da; }
  [data-testid="stMetric"] { padding: 12px 12px 10px; }
  [data-testid="stMetricValue"] { font-size: 1.5rem !important; }
}
[data-testid="stMetricLabel"] p { font-size: 0.95rem; color: #5f5e58; }
[data-testid="stMetricValue"] { font-size: 1.85rem; font-weight: 500; }
/* The change under each figure: text in a dark, readable green or red, not a pale pill. */
[data-testid="stMetricDelta"] { background: none !important; padding: 0 !important; }
[data-testid="stMetricDelta"] div, [data-testid="stMetricDelta"] svg { font-size: 0.92rem; }
[data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Up"]) {
  color: #1f6b45 !important; }
[data-testid="stMetricDelta"]:has(svg[data-testid="stMetricDeltaIcon-Down"]) {
  color: #9b2c1f !important; }
/* Keyboard focus is always visible (mouse clicks don't show it). */
a:focus-visible, button:focus-visible, [role="radio"]:focus-visible {
  outline: 2px solid #1f4e79 !important; outline-offset: 2px; }
/* Buttons respond the moment they're pressed. */
button:active { transform: scale(0.98); transition: transform 80ms ease-out; }
@media (prefers-reduced-motion: reduce) { button:active { transform: none; } }
/* Muted helper text */
.ca-muted { color: #5f5e58; font-size: 0.95rem; }
.ca-meta { color: #5b5a55; font-size: 1rem; margin: -0.6rem 0 0.9rem; }
.ca-row { display: flex; justify-content: space-between; gap: 1rem;
          padding: 0.45rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-row span:last-child { color: #5b5a55; white-space: nowrap; }
.ca-headline { padding: 0.55rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-headline a { color: #1d1d1b; text-decoration: none; font-size: 1.05rem; }
.ca-headline a:hover, .ca-headline a:focus-visible { text-decoration: underline; }
.ca-headline div { color: #6b6a64; font-size: 0.9rem; }
.ca-placeholder { border: 1px dashed #d6d2c4; border-radius: 6px; padding: 1rem 1.2rem;
                  color: #5b5a55; background: #faf9f5; }
/* Cards for the latest reports */
.ca-card { background: #f3f1ea; border-radius: 6px; padding: 0.9rem 1.1rem; height: 100%; }
.ca-card-title { font-size: 1.2rem; margin: 0.15rem 0; }
/* Answer sources */
.ca-source { margin: 0.4rem 0 0.8rem; }
.ca-source blockquote { margin: 0.3rem 0 0 0; padding: 0.2rem 0 0.2rem 0.8rem;
  border-left: 3px solid #d6d2c4; color: #4a4944; font-size: 0.95rem; white-space: pre-wrap; }
/* Notable events timeline */
.ca-event { display: flex; gap: 1rem; padding: 0.6rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-event-date { min-width: 6.5rem; color: #5b5a55; }
.ca-event blockquote { margin: 0.35rem 0 0.15rem; padding-left: 0.8rem;
  border-left: 3px solid #d6d2c4; color: #4a4944; font-size: 0.95rem; }
.ca-badge { font-size: 0.8rem; padding: 0.05rem 0.45rem; border-radius: 4px; }
.ca-badge-high { background: #f6e0dc; color: #7a2617; }
.ca-badge-medium { background: #e6ecf3; color: #1f4e79; }
/* While the page updates, Streamlit leaves the previous page's content on screen, faded,
   under the new content (it looked like two sections mixed together). Clear it instead,
   but only if the update takes longer than half a second, so quick clicks don't flicker. */
[data-stale="true"] { opacity: 0 !important; transition: opacity 0.15s ease 0.5s !important; }
@media (prefers-reduced-motion: reduce) {
  [data-stale="true"] { transition: none !important; }
}
/* No link icons next to headings */
[data-testid="stHeaderActionElements"] { display: none !important; }
/* App name: one line, quieter than the company name */
.ca-brand { font-size: 1.35rem; font-weight: 500; white-space: nowrap; margin: 0 !important;
            line-height: 2.53rem !important; letter-spacing: -0.005em; }  /* = search box height */
/* Text blocks get a negative bottom margin from Streamlit, which pushed the app name 9px
   below the search box it sits beside. */
[data-testid="stMarkdownContainer"]:has(.ca-brand) { margin-bottom: 0 !important; }
/* Chosen companies in pickers: a pale tint with navy text, not solid navy chips (strong
   colour belongs on data and the selected section, not on every control). */
span[data-tag] { background: #e6ecf3 !important; color: #1f4e79 !important; }
span[data-tag] svg { fill: #1f4e79 !important; color: #1f4e79 !important; }
/* Tighter page top */
.block-container { padding-top: 3.2rem; max-width: 1200px; }
/* Section menu: a quiet line under it instead of a heavy divider with a big gap */
.st-key-section { padding-bottom: 0.9rem; border-bottom: 1px solid #e3e0d6;
                  margin-bottom: 0.4rem; width: 100% !important; }
/* On a phone, keep the seven sections on one line that scrolls sideways, instead of
   wrapping into three rows that push the page down. */
@media (max-width: 640px) {
  .st-key-section [role="radiogroup"] { flex-wrap: nowrap !important; overflow-x: auto;
                                        scrollbar-width: none; }
  .st-key-section [role="radiogroup"] button { flex: 0 0 auto; white-space: nowrap; }
}
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# A formatted figure, optionally followed by a note in brackets: "$19.6B", "+10.0%", "n/m",
# "-", "34.4% (Q2 FY2026)".
_FIGURE = re.compile(r"^(?:[+\-−]?\$?[\d.,]+[%BMKTx]?|n/m|-|—)(?: \(.*\))?$")


def number_columns(df: pd.DataFrame, config: dict | None = None) -> dict:
    """Table column settings that right-align every column holding figures, so digits line
    up in place value. Columns already configured keep their settings, plus the alignment."""
    config = dict(config or {})
    for col in df.columns:
        values = [str(v) for v in df[col] if str(v) not in ("", "nan", "None")]
        if not values or not all(_FIGURE.match(v) for v in values):
            continue
        if all(v in ("-", "—", "n/m") for v in values):
            continue
        setting = dict(config.get(col) or st.column_config.TextColumn())
        setting["alignment"] = "right"
        config[col] = setting
    return config


def placeholder(text: str) -> None:
    """A gentle box for sections that arrive in a later step."""
    st.markdown(f'<div class="ca-placeholder">{text}</div>', unsafe_allow_html=True)
