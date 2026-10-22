"""Small visual touches on top of the theme in .streamlit/config.toml."""

import streamlit as st

CSS = """
<style>
/* Heading scale: each level clearly smaller than the one above. Letter-spacing depends on
   size: large type is tightened, small labels get a touch more room (as Apple's type does). */
h1, h2, h3, h4 { font-weight: 500 !important; }
h1 { font-size: 2.4rem !important; line-height: 1.1 !important; letter-spacing: -0.015em; }
h3 { font-size: 1.6rem !important; line-height: 1.2 !important; letter-spacing: -0.005em;
     padding-top: 1.4rem !important; }
h4 { font-size: 1.15rem !important; font-weight: 600 !important; letter-spacing: 0.01em;
     padding: 1rem 0 0.2rem !important; }
/* Comfortable reading line height for written text */
[data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] p {
  line-height: 1.55; }
/* Key-figure cards */
[data-testid="stMetric"] {
  background: #f3f1ea; border-radius: 6px; padding: 14px 16px 12px;
}
[data-testid="stMetricLabel"] p { font-size: 0.95rem; color: #5b5a55; }
[data-testid="stMetricValue"] { font-size: 1.9rem; font-weight: 500; }
/* Muted helper text */
.ca-muted { color: #6b6a64; font-size: 0.95rem; }
.ca-meta { color: #5b5a55; font-size: 1rem; margin: -0.6rem 0 0.9rem; }
.ca-row { display: flex; justify-content: space-between; gap: 1rem;
          padding: 0.45rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-row span:last-child { color: #5b5a55; white-space: nowrap; }
.ca-headline { padding: 0.55rem 0; border-bottom: 1px solid #e3e0d6; }
.ca-headline a { color: #1d1d1b; text-decoration: none; font-size: 1.05rem; }
.ca-headline a:hover { text-decoration: underline; }
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
            line-height: 2.5rem; letter-spacing: -0.005em; }
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


def placeholder(text: str) -> None:
    """A gentle box for sections that arrive in a later step."""
    st.markdown(f'<div class="ca-placeholder">{text}</div>', unsafe_allow_html=True)
