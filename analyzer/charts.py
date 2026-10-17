"""Chart and number-formatting helpers for the dashboard. No calculations happen here."""

import pandas as pd
import plotly.graph_objects as go

# One metric per chart, so one color. Derived Q4 bars use a lighter step of the same
# blue and get their own legend entry, so "derived" is never shown by color alone.
REPORTED_COLOR = "#2a78d6"
DERIVED_COLOR = "#86b6ef"
UNUSUAL_COLOR = "#eb6834"   # orange marker, always paired with a legend label
GRID_COLOR = "rgba(137, 135, 129, 0.25)"


def format_pct(value) -> str:
    """0.1234 -> "12.3%". None (not meaningful) -> "n/m"."""
    if value is None or pd.isna(value):
        return "n/m"
    return f"{value * 100:+,.1f}%"


def format_ratio(value) -> str:
    """Margins and ROE: 0.154 -> "15.4%" (no plus sign)."""
    if value is None or pd.isna(value):
        return "-"
    return f"{value * 100:.1f}%"


def format_value(value: float, unit: str) -> str:
    """$65.9B, $412.3M, or $14.01 for per-share figures."""
    if value is None or pd.isna(value):
        return "-"
    if unit == "USD/shares":
        return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"
    sign = "-" if value < 0 else ""
    v = abs(value)
    for size, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if v >= size:
            return f"{sign}${v / size:,.1f}{suffix}"
    return f"{sign}${v:,.0f}"


def _axis_scale(df: pd.DataFrame, unit: str) -> tuple[float, str]:
    """Pick one scale for the y-axis so ticks read "$60B" rather than "$60G"."""
    if unit == "USD/shares":
        return 1.0, ""
    biggest = df["value"].abs().max()
    for size, suffix in [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]:
        if biggest >= size:
            return size, suffix
    return 1.0, ""


def bar_chart(df: pd.DataFrame, title: str, unit: str,
              unusual: set[str] | None = None) -> go.Figure:
    """Bar chart of one metric over time. Derived Q4 values are a lighter blue; periods
    in `unusual` get an orange marker on top of the bar."""
    scale, suffix = _axis_scale(df, unit)
    fig = go.Figure()
    is_derived = df["source"].str.startswith("Derived")
    for name, part, color in [("Reported", df[~is_derived], REPORTED_COLOR),
                              ("Derived Q4 (FY − Q1 − Q2 − Q3)", df[is_derived], DERIVED_COLOR)]:
        if part.empty:
            continue
        hover = [
            f"<b>{p}</b><br>{format_value(v, unit)}<br>{s}<br>From {f} filed {d}"
            for p, v, s, f, d in zip(part["period"], part["value"], part["source"],
                                     part["form"], part["filed"])
        ]
        fig.add_bar(
            x=part["period"], y=part["value"] / scale, name=name,
            marker_color=color, hovertext=hover, hoverinfo="text",
        )

    flagged = df[df["period"].isin(unusual or set())]
    if not flagged.empty:
        fig.add_scatter(
            x=flagged["period"], y=flagged["value"] / scale, mode="markers",
            name="Unusual change (see Notable events)",
            marker=dict(symbol="diamond", size=11, color=UNUSUAL_COLOR),
            hovertext=[f"<b>{p}</b>: unusual year-over-year change" for p in flagged["period"]],
            hoverinfo="text",
        )

    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        barmode="overlay", bargap=0.25, barcornerradius=4,
        height=320, margin=dict(l=10, r=10, t=45, b=10),
        showlegend=bool(is_derived.any() or not flagged.empty),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1,
                    font=dict(size=11)),
        xaxis=dict(categoryorder="array", categoryarray=list(df["period"]),
                   showgrid=False, tickangle=-45 if len(df) > 8 else 0),
        yaxis=dict(gridcolor=GRID_COLOR, zeroline=True, zerolinecolor=GRID_COLOR,
                   tickprefix="$", ticksuffix=suffix,
                   tickformat=".2f" if unit == "USD/shares" else ",.1~f"),
        hoverlabel=dict(align="left"),
    )
    return fig


def ratio_chart(df: pd.DataFrame, title: str, formula: str) -> go.Figure:
    """Line chart of a percentage (margin or ROE) over time, one series."""
    hover = [
        f"<b>{p}</b><br>{format_ratio(v)}<br>{formula}: "
        f"{format_value(n, 'USD')} ÷ {format_value(d, 'USD')}<br>{s}"
        for p, v, n, d, s in zip(df["period"], df["value"], df["numerator"],
                                 df["denominator"], df["source"])
    ]
    fig = go.Figure(go.Scatter(
        x=df["period"], y=df["value"] * 100, mode="lines+markers",
        line=dict(color=REPORTED_COLOR, width=2), marker=dict(size=8, color=REPORTED_COLOR),
        hovertext=hover, hoverinfo="text", name=title,
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=15)),
        height=300, margin=dict(l=10, r=10, t=45, b=10), showlegend=False,
        xaxis=dict(categoryorder="array", categoryarray=list(df["period"]),
                   showgrid=False, tickangle=-45 if len(df) > 8 else 0),
        yaxis=dict(gridcolor=GRID_COLOR, ticksuffix="%", zeroline=True,
                   zerolinecolor=GRID_COLOR),
        hoverlabel=dict(align="left"),
    )
    return fig
