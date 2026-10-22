from analyzer.filing_text import Passage
from analyzer.synopsis import REQUEST, SECTIONS, identifier, in_item, pick_passages


def _p(section, text, form="10-K"):
    return Passage("filing", section, text, "url", form)


def test_in_item_matches_only_that_item():
    assert in_item("Item 1. Business", "1")
    assert in_item("Item 1", "1")
    assert not in_item("Item 1A. Risk factors", "1")
    assert not in_item("Item 10. Directors", "1")
    assert in_item("Item 1A. Risk factors › Credit risk", "1A")
    assert not in_item("Part II, Item 2. Unregistered sales", "2")


def test_pick_passages_takes_business_risks_and_10q_mdna():
    annual = [_p("Item 1. Business", "We earn revenue from card fees and customers."),
              _p("Item 1A. Risk factors", "These risks could adversely affect us."),
              _p("Item 7. Management's discussion", "Results increased primarily due to fees."),
              _p("Item 10. Directors", "Board members and governance.")]
    quarterly = [_p("Item 2. Management's discussion", "Revenue increased primarily due to "
                    "higher spending compared with last quarter.", "10-Q"),
                 _p("Part II, Item 2. Unregistered sales", "Share repurchases.", "10-Q")]
    chosen = [p.section for p in pick_passages(annual, quarterly)]
    assert chosen == ["Item 1. Business", "Item 1A. Risk factors",
                      "Item 2. Management's discussion"]


def test_pick_passages_uses_10k_mdna_when_10k_is_newest():
    annual = [_p("Item 1. Business", "Card fees."),
              _p("Item 7. Management's discussion", "Results increased primarily due to fees.")]
    chosen = [p.section for p in pick_passages(annual, annual)]
    assert chosen == ["Item 1. Business", "Item 7. Management's discussion"]


def test_pick_passages_limits_and_keeps_filing_order():
    annual = [_p("Item 1A. Risk factors", f"risk {i} " + ("could adversely affect " * (i % 3)))
              for i in range(12)]
    chosen = pick_passages(annual, [])
    assert len(chosen) == 5
    assert chosen == sorted(chosen, key=annual.index)


def test_identifier_changes_with_new_filing():
    assert identifier("a", "b") != identifier("a", "c")


def test_request_names_every_heading():
    text = REQUEST.format(name="Example Corp")
    for heading in SECTIONS:
        assert f"### {heading}" in text
