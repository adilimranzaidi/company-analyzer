"""Small visual touches on top of the theme in .streamlit/config.toml."""

import streamlit as st

CSS = """
<style>
/* Calmer headings */
h1, h2, h3 { font-weight: 500 !important; letter-spacing: 0.005em; }
h1 { font-size: 2.3rem !important; }
/* Key-figure cards */
[data-testid="stMetric"] {
  background: #f3f1ea; border-radius: 6px; padding: 14px 16px 12px;
}
[data-testid="stMetricLabel"] p { font-size: 0.95rem; color: #5b5a55; }
[data-testid="stMetricValue"] { font-size: 1.9rem; font-weight: 500; }
/* Muted helper text */
.ca-muted { color: #6b6a64; font-size: 0.95rem; }
.ca-meta { color: #5b5a55; font-size: 1rem; margin-top: -0.6rem; }
.ca-row { display: flex; justify-content: space-between; gap: 1rem;
          padding: 0.45rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-row span:last-child { color: #5b5a55; white-space: nowrap; }
.ca-headline { padding: 0.55rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-headline a { color: #1d1d1b; text-decoration: none; font-size: 1.05rem; }
.ca-headline a:hover { text-decoration: underline; }
.ca-headline div { color: #6b6a64; font-size: 0.9rem; }
.ca-placeholder { border: 1px dashed #d6d2c4; border-radius: 6px; padding: 1rem 1.2rem;
                  color: #5b5a55; background: #faf9f5; }
/* No link icons next to headings */
[data-testid="stHeaderActionElements"] { display: none !important; }
/* App name: one line, quieter than the company name */
.ca-brand { font-size: 1.5rem; font-weight: 500; white-space: nowrap; margin: 0; }
/* Tighter page top */
.block-container { padding-top: 2.2rem; max-width: 1200px; }
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def placeholder(text: str) -> None:
    """A gentle box for sections that arrive in a later step."""
    st.markdown(f'<div class="ca-placeholder">{text}</div>', unsafe_allow_html=True)
