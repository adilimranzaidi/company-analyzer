"""Every figure on the dashboard must have a plain-English explanation."""

from analyzer.financials import METRICS
from analyzer.glossary import GLOSSARY, search, short
from analyzer.metrics import MARGINS


def test_every_metric_and_ratio_is_explained():
    names = [m.name for m in METRICS] + [r.name for r in MARGINS] + ["Return on equity"]
    missing = [n for n in names if n not in GLOSSARY]
    assert missing == []


def test_every_entry_has_a_short_and_a_long_version():
    for term, entry in GLOSSARY.items():
        assert entry["short"] and entry["long"], term
        assert len(entry["short"]) < 120, f"{term}: hover tips should be one short line"


def test_search_finds_names_first_then_explanations():
    results = [term for term, _ in search("equity")]
    assert results[:2] == ["Return on equity", "Shareholders' equity"]
    assert "Stock split" not in results
    assert [t for t, _ in search("reserve release")] == ["Provision for credit losses"]


def test_unknown_term_is_empty_not_an_error():
    assert short("Not a real term") == ""
