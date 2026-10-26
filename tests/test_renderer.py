from pathlib import Path

import pytest

from mini_analytics.cli import DASHBOARDS_DIR
from mini_analytics.rendering import renderer, spec


def test_revenue_overview_spec_loads():
    dashboards = spec.load_all(DASHBOARDS_DIR)
    ids = [d.id for d in dashboards]
    assert "revenue_overview" in ids


def test_render_revenue_overview(warehouse, tmp_path: Path):
    dashboards = spec.load_all(DASHBOARDS_DIR)
    d = next(x for x in dashboards if x.id == "revenue_overview")

    page_path = renderer.render_dashboard(warehouse, d, tmp_path)

    assert page_path.exists()
    html = page_path.read_text()
    # KPI values made it into the page
    assert "Total GMV" in html
    assert "Tokens purchased" in html
    # Plotly injected (at least one chart div + CDN script)
    assert "plotly" in html.lower()
    # One CSV per block was emitted
    exports_dir = page_path.parent / "exports"
    expected = {f"{b.id}.csv" for b in d.blocks}
    actual = {p.name for p in exports_dir.iterdir()}
    assert expected == actual
    # Download buttons for non-KPI blocks point at those CSVs
    for b in d.blocks:
        if b.type != "kpi":
            assert f'href="exports/{b.id}.csv"' in html


def test_render_index(warehouse, tmp_path: Path):
    dashboards = spec.load_all(DASHBOARDS_DIR)
    path = renderer.render_index(dashboards, tmp_path)
    html = path.read_text()
    assert "Dashboards" in html
    for d in dashboards:
        assert f'href="{d.id}/index.html"' in html


@pytest.mark.parametrize(
    "dashboard_id",
    [
        "conversion_funnel",
        "token_issuance",
        "catalog_concentration",
        "author_segmentation",
    ],
)
def test_tier1_dashboards_render(warehouse, tmp_path: Path, dashboard_id: str):
    """Each Tier-1 dashboard compiles, renders, and emits one CSV per block."""
    dashboards = spec.load_all(DASHBOARDS_DIR)
    d = next(x for x in dashboards if x.id == dashboard_id)
    page = renderer.render_dashboard(warehouse, d, tmp_path)
    assert page.exists()
    html = page.read_text()
    # Titles with special chars (&, <) get HTML-escaped; compare against the first plain word
    assert d.title.split()[0] in html
    exports = {p.name for p in (page.parent / "exports").iterdir()}
    # Notes don't emit CSVs; everything else does
    expected_csvs = {f"{b.id}.csv" for b in d.blocks if b.type != "note"}
    assert exports == expected_csvs


def test_token_issuance_scatter_block(warehouse, tmp_path: Path):
    """Regression: the scatter chart type renders (Plotly embed + non-empty data)."""
    dashboards = spec.load_all(DASHBOARDS_DIR)
    d = next(x for x in dashboards if x.id == "token_issuance")
    page = renderer.render_dashboard(warehouse, d, tmp_path)
    html = page.read_text()
    # Plotly embedded for the scatter div
    assert "plotly" in html.lower()
    # The scatter block's CSV has data (not just a header)
    csv = (page.parent / "exports" / "issuance_vs_purchases_scatter.csv").read_text()
    assert len(csv.strip().splitlines()) > 1


def test_note_block_renders_and_skips_csv(warehouse, tmp_path: Path):
    """Note blocks render as warm-ivory callouts, render their body, and do not emit CSVs."""
    dashboards = spec.load_all(DASHBOARDS_DIR)
    d = next(x for x in dashboards if x.id == "token_issuance")
    page = renderer.render_dashboard(warehouse, d, tmp_path)
    html = page.read_text()
    # Note class + note title rendered
    assert 'class="note"' in html
    assert "How to read this dashboard" in html
    # The business-model caveat body text is present
    assert "numbered digital copy" in html.lower()
    assert "payment provider" in html.lower()
    # No CSV emitted for the note block
    exports = {p.name for p in (page.parent / "exports").iterdir()}
    assert "note_issuance_semantics.csv" not in exports


def test_note_block_requires_body():
    """Loading a note without `body` must raise a clear validation error."""
    from mini_analytics.rendering.spec import Block, NOTE
    import yaml
    bad_yaml = """
id: bad_dashboard
title: bad
description: bad
blocks:
  - id: n
    type: note
    title: no body here
"""
    data = yaml.safe_load(bad_yaml)
    # Mimic spec.load's validation
    blocks = [Block(**b) for b in data["blocks"]]
    b = blocks[0]
    assert b.type == NOTE
    assert b.body is None
    # spec.load would raise; verify directly
    tmp = Path("/tmp/__mini_analytics_bad_note__.yml")
    tmp.write_text(bad_yaml)
    with pytest.raises(ValueError, match="'body' is required"):
        spec.load(tmp)
    tmp.unlink()


def test_conversion_funnel_matches_raw_data(warehouse):
    """The conversion-funnel KPIs must match a direct count over token_purchases."""
    purchased = warehouse.con.execute(
        "SELECT COUNT(DISTINCT token_id) FROM token_purchases WHERE state = 'purchased'"
    ).fetchone()[0]
    attempted = warehouse.con.execute(
        "SELECT COUNT(DISTINCT token_id) FROM token_purchases"
    ).fetchone()[0]
    d = next(x for x in spec.load_all(DASHBOARDS_DIR) if x.id == "conversion_funnel")
    kpis = {b.id: warehouse.con.execute(b.sql).fetchone()[0] for b in d.blocks if b.type == "kpi"}
    assert kpis["kpi_tokens_attempted"] == attempted
    assert kpis["kpi_tokens_purchased"] == purchased
    assert 0 < purchased <= attempted
