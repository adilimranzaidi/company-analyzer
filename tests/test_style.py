import pandas as pd

from ui.style import number_columns


def test_figure_columns_are_right_aligned():
    table = pd.DataFrame({
        "Company": ["Visa Inc. (V)", "Mastercard Inc (MA)"],
        "Fiscal year": ["FY2025", "FY2025"],
        "Revenue": ["$40.0B", "$32.8B"],
        "Revenue growth": ["+11.3%", "-2.8%"],
        "Return on equity": ["-", "210.5%"],
        "Latest quarter": ["+17.1% (Q2 FY2026)", "+14.1% (Q2 FY2026)"],
    })
    config = number_columns(table)
    assert {k for k, v in config.items() if v["alignment"] == "right"} == {
        "Revenue", "Revenue growth", "Return on equity", "Latest quarter"}


def test_existing_column_settings_are_kept():
    table = pd.DataFrame({"EPS growth": ["n/m", "+9.8%"]})
    config = number_columns(table, {"EPS growth": {"help": "Diluted EPS", "alignment": None}})
    assert config["EPS growth"]["help"] == "Diluted EPS"
    assert config["EPS growth"]["alignment"] == "right"


def test_column_of_only_dashes_is_left_alone():
    assert number_columns(pd.DataFrame({"Note": ["-", "n/m"]})) == {}
