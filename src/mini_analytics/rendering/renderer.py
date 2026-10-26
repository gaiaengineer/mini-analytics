from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from html import escape as html_escape

from mini_analytics.rendering import charts
from mini_analytics.rendering.spec import KPI, NOTE, TABLE, Block, Dashboard
from mini_analytics.warehouse import Warehouse

TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class RenderedBlock:
    block: Block
    html: str            # inner HTML of the block body (chart div, KPI, or table)
    csv_path: str | None  # relative path from the dashboard page


def _run(warehouse: Warehouse, block: Block) -> pd.DataFrame:
    return warehouse.con.sql(block.sql).df()


def _block_html_kpi(block: Block, df: pd.DataFrame) -> str:
    value = None
    if not df.empty:
        value = df.iloc[0, 0]
    formatted = charts.format_scalar(value, block.format)
    subtitle = f'<div class="kpi-subtitle">{block.subtitle}</div>' if block.subtitle else ""
    return (
        f'<div class="kpi">'
        f'<div class="kpi-label">{block.title}</div>'
        f'<div class="kpi-value">{formatted}</div>'
        f"{subtitle}"
        f"</div>"
    )


def _block_html_table(df: pd.DataFrame) -> str:
    df = df.copy()
    # Datetime columns render NaT even with na_rep, so coerce them to blank strings up front.
    for col in df.select_dtypes(include=["datetime", "datetimetz"]).columns:
        df[col] = df[col].dt.strftime("%Y-%m-%d").where(df[col].notna(), "")
    # convert_dtypes promotes int-with-possible-nulls out of float64 so we don't show "645.0"
    df = df.convert_dtypes()
    return df.to_html(index=False, classes="data-table", border=0, na_rep="")


def _block_html_chart(block: Block, df: pd.DataFrame) -> str:
    fig = charts.build(block, df)
    return fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={"displayModeBar": False, "responsive": True},
    )


def _block_html_note(block: Block) -> str:
    """Render a note block's body as paragraphs. Lightweight: paragraphs split on
    blank lines; **bold** and `code` are recognised. Other markdown is not."""
    body = block.body or ""
    paragraphs = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    rendered_paras = []
    for p in paragraphs:
        escaped = html_escape(p)
        # **bold** → <strong>
        while "**" in escaped:
            escaped = escaped.replace("**", "<strong>", 1)
            escaped = escaped.replace("**", "</strong>", 1)
        # `code` → <code>
        while "`" in escaped:
            escaped = escaped.replace("`", "<code>", 1)
            escaped = escaped.replace("`", "</code>", 1)
        # Preserve single line breaks within a paragraph
        escaped = escaped.replace("\n", "<br>")
        rendered_paras.append(f"<p>{escaped}</p>")
    return "\n".join(rendered_paras)


def _render_block(
    warehouse: Warehouse,
    dashboard: Dashboard,
    block: Block,
    exports_dir: Path,
) -> RenderedBlock:
    # Notes have no SQL / no CSV — just a body to render.
    if block.type == NOTE:
        return RenderedBlock(block=block, html=_block_html_note(block), csv_path=None)

    df = _run(warehouse, block)

    csv_name = f"{block.id}.csv"
    csv_abs = exports_dir / csv_name
    csv_abs.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_abs, index=False)
    csv_rel = f"exports/{csv_name}"

    if block.type == KPI:
        html = _block_html_kpi(block, df)
    elif block.type == TABLE:
        html = _block_html_table(df)
    else:
        html = _block_html_chart(block, df)

    return RenderedBlock(block=block, html=html, csv_path=csv_rel)


def render_dashboard(
    warehouse: Warehouse,
    dashboard: Dashboard,
    out_dir: Path,
) -> Path:
    page_dir = out_dir / dashboard.id
    exports_dir = page_dir / "exports"
    page_dir.mkdir(parents=True, exist_ok=True)

    rendered = [_render_block(warehouse, dashboard, b, exports_dir) for b in dashboard.blocks]

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tmpl = env.get_template("dashboard.html.j2")
    html = tmpl.render(
        dashboard=dashboard,
        rendered=rendered,
        kpi_type=KPI,
        built_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    page_path = page_dir / "index.html"
    page_path.write_text(html)
    return page_path


def render_index(dashboards: list[Dashboard], out_dir: Path) -> Path:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    tmpl = env.get_template("index.html.j2")
    html = tmpl.render(
        dashboards=dashboards,
        built_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    path = out_dir / "index.html"
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    return path
