"""Plotly figure builders per block type."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from mini_analytics.rendering.spec import (
    AREA_STACKED,
    BAR,
    HISTOGRAM,
    LINE,
    SCATTER,
    Block,
)

_NEUTRAL_PALETTE = [
    "#4f46e5",
    "#0ea5e9",
    "#10b981",
    "#f59e0b",
    "#ef4444",
    "#a855f7",
    "#64748b",
]


def _apply_axis_format(fig: go.Figure, axis: str, fmt: str | None) -> None:
    updater = fig.update_yaxes if axis == "y" else fig.update_xaxes
    if fmt == "currency":
        updater(tickprefix="$", tickformat=",.0f")
    elif fmt == "percent":
        updater(tickformat=".0%")
    elif fmt in ("number", "integer"):
        updater(tickformat=",.0f")


def build(block: Block, df: pd.DataFrame) -> go.Figure:
    color_kwargs: dict = {}
    if block.color_map:
        color_kwargs["color_discrete_map"] = block.color_map

    if block.type == LINE:
        fig = px.line(df, x=block.x, y=block.y, color=block.color, markers=True, **color_kwargs)
    elif block.type == AREA_STACKED:
        fig = px.area(df, x=block.x, y=block.y, color=block.color, groupnorm=None, **color_kwargs)
    elif block.type == BAR:
        fig = px.bar(
            df,
            x=block.x,
            y=block.y,
            color=block.color,
            orientation=block.orientation or "v",
            **color_kwargs,
        )
    elif block.type == HISTOGRAM:
        fig = px.histogram(df, x=block.x, color=block.color, nbins=block.nbins, **color_kwargs)
    elif block.type == SCATTER:
        fig = px.scatter(
            df,
            x=block.x,
            y=block.y,
            color=block.color,
            size=block.size,
            size_max=28,
            opacity=0.7,
            **color_kwargs,
        )
    else:
        raise ValueError(f"No chart builder for block type {block.type!r}")

    fig.update_layout(
        margin=dict(l=16, r=16, t=12, b=24),
        height=block.height or 320,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="ui-sans-serif, system-ui, sans-serif", size=12, color="#1f2937"),
        colorway=_NEUTRAL_PALETTE,
        legend=dict(orientation="h", y=-0.2, x=0),
        hoverlabel=dict(bgcolor="white", font_size=12),
        barmode=(
            block.barmode
            if block.barmode is not None
            else ("overlay" if block.type == HISTOGRAM and block.color else None)
        ),
    )
    fig.update_xaxes(showgrid=False, linecolor="#e5e7eb", ticks="outside", tickcolor="#e5e7eb")
    fig.update_yaxes(gridcolor="#f1f5f9", linecolor="#e5e7eb", zerolinecolor="#e5e7eb")

    # Histograms bin a value on x; the "format" describes that value.
    # Horizontal bars have the numeric measure on x as well.
    value_on_x = block.type == HISTOGRAM or (
        block.type == BAR and (block.orientation or "v") == "h"
    )
    _apply_axis_format(fig, "x" if value_on_x else "y", block.format)

    if block.type == HISTOGRAM and block.color:
        fig.update_traces(opacity=0.65)
    return fig


def format_scalar(value, fmt: str | None) -> str:
    if value is None:
        return "—"
    if fmt == "currency":
        return f"${value:,.2f}"
    if fmt == "percent":
        return f"{value * 100:,.1f}%"
    if fmt == "integer":
        return f"{int(value):,}"
    if fmt == "number":
        return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
    return str(value)
