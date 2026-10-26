from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mini_analytics import config as config_mod
from mini_analytics import fetch as fetch_mod
from mini_analytics import warehouse as wh
from mini_analytics.loaders.base import LOGICAL_TABLES
from mini_analytics.rendering import renderer, spec
from mini_analytics.warehouse import MODELS

DASHBOARDS_DIR = Path(__file__).parent / "dashboards"

app = typer.Typer(add_completion=False, help="Mini Analytics — ingest CSVs and run ad-hoc queries.")
console = Console()

SourcesOpt = Annotated[
    Path, typer.Option("--sources", "-s", help="Path to sources.yml.", exists=True)
]
DbOpt = Annotated[
    Path | None,
    typer.Option("--db", help="Persist to this DuckDB file instead of running in-memory."),
]


@app.command()
def ingest(
    sources: SourcesOpt = Path("sources.yml"),
    db: DbOpt = None,
) -> None:
    """Load the configured source into DuckDB and register model views."""
    warehouse = wh.open(sources, db_path=db)
    table = Table(title="Ingested views", show_lines=False)
    table.add_column("view")
    table.add_column("kind")
    table.add_column("rows", justify="right")
    for name in LOGICAL_TABLES:
        n = warehouse.con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        table.add_row(name, "source", f"{n:,}")
    for name in MODELS:
        n = warehouse.con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        table.add_row(name, "model", f"{n:,}")
    console.print(table)


@app.command()
def tables(sources: SourcesOpt = Path("sources.yml")) -> None:
    """List every registered view and its columns."""
    warehouse = wh.open(sources)
    for name, cols in warehouse.views():
        t = Table(title=name, show_header=True)
        t.add_column("column")
        t.add_column("type")
        for col, dtype in cols:
            t.add_row(col, dtype)
        console.print(t)


@app.command()
def query(
    sql: Annotated[str, typer.Argument(help="SQL to run against the registered views.")],
    sources: SourcesOpt = Path("sources.yml"),
) -> None:
    """Run ad-hoc SQL against the registered views."""
    warehouse = wh.open(sources)
    rel = warehouse.query(sql)
    rows = rel.fetchall()
    columns = [d[0] for d in rel.description]
    t = Table(show_header=True)
    for col in columns:
        t.add_column(col)
    for row in rows:
        t.add_row(*[("" if v is None else str(v)) for v in row])
    console.print(t)
    console.print(f"[dim]{len(rows)} row(s)[/dim]")


def _fetch_and_print(sources: Path) -> None:
    """Shared helper: fetch from S3 and print a summary table.

    Multi-file tables (e.g. ga_events) are summarised as one row: file count,
    total bytes, and the most recent S3 key. Single-file tables show one row
    each, same as before.
    """
    cfg = config_mod.load(sources)
    if cfg.s3 is None:
        console.print(
            "[red]Cannot fetch: no [s3] block in sources.yml. Add one first.[/red]"
        )
        raise typer.Exit(1)
    results = fetch_mod.fetch_all(cfg.s3)

    # Group by table so multi-file fetches don't flood the output.
    grouped: dict[str, list[fetch_mod.FetchResult]] = {}
    for r in results:
        grouped.setdefault(r.table, []).append(r)

    table = Table(title="Fetched from S3")
    table.add_column("table")
    table.add_column("s3 key")
    table.add_column("last modified", justify="right")
    table.add_column("bytes", justify="right")
    for table_name, items in grouped.items():
        if len(items) == 1:
            r = items[0]
            table.add_row(
                r.table,
                r.s3_key,
                r.last_modified.strftime("%Y-%m-%d %H:%M UTC"),
                f"{r.size_bytes:,}",
            )
        else:
            latest = max(items, key=lambda r: (r.last_modified, r.s3_key))
            total = sum(r.size_bytes for r in items)
            table.add_row(
                f"{table_name} ({len(items)} files)",
                f"{latest.s3_key} (latest)",
                latest.last_modified.strftime("%Y-%m-%d %H:%M UTC"),
                f"{total:,}",
            )
    console.print(table)


@app.command()
def fetch(sources: SourcesOpt = Path("sources.yml")) -> None:
    """Pull the latest CSV from each configured S3 prefix into the local data dir."""
    _fetch_and_print(sources)


@app.command()
def build(
    sources: SourcesOpt = Path("sources.yml"),
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory.")] = Path("build"),
    dashboards: Annotated[
        Path, typer.Option("--dashboards", help="Directory of dashboard YAML specs.")
    ] = DASHBOARDS_DIR,
    refresh: Annotated[
        bool,
        typer.Option(
            "--refresh",
            help="Fetch fresh CSVs from S3 before building. Requires the [s3] block in sources.yml.",
        ),
    ] = False,
) -> None:
    """Render every dashboard YAML to static HTML under --out."""
    if refresh:
        _fetch_and_print(sources)
    warehouse = wh.open(sources)
    specs = spec.load_all(dashboards)
    if not specs:
        console.print(f"[yellow]No dashboards found under {dashboards}[/yellow]")
        raise typer.Exit(1)
    out.mkdir(parents=True, exist_ok=True)
    for d in specs:
        page = renderer.render_dashboard(warehouse, d, out)
        console.print(f"[green]rendered[/green] {d.id} → {page}")
    index = renderer.render_index(specs, out)
    console.print(f"[green]index[/green]    → {index}")


if __name__ == "__main__":
    app()
