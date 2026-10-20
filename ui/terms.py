"""The Glossary panel and helpers for showing definitions next to figures."""

import streamlit as st

from analyzer.glossary import GLOSSARY, search


def explain(term: str) -> str:
    """The full definition, for captions under charts ("" if the term isn't in the glossary)."""
    entry = GLOSSARY.get(term)
    return entry["long"] if entry else ""


def glossary_panel() -> None:
    query = st.text_input("Look up a term", placeholder="e.g. return on equity",
                          key="glossary_query")
    results = search(query)
    if not results:
        st.caption("No matching terms. Try a shorter word, or ask in the Ask section.")
    for term, entry in results:
        st.markdown(f"**{term}**  \n{entry['long']}")
