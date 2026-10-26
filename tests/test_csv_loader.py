import duckdb
import pytest

from mini_analytics import config as config_mod
from mini_analytics import loaders
from mini_analytics.loaders.base import LOGICAL_TABLES
from mini_analytics.loaders.csv_loader import CSV_FILES


def _csv_row_count(path) -> int:
    """Count data rows in a CSV (excluding the header).

    Uses `csv.reader` so quoted fields containing embedded newlines count as
    a single row (naive line-counting splits them). Handles plain `.csv`,
    gzipped `.csv.gz`, and glob patterns (sum across matches).
    """
    import csv
    import glob as _glob
    import gzip
    path_str = str(path)
    if any(ch in path_str for ch in "*?["):
        matched = _glob.glob(path_str)
        if not matched:
            return 0
        return sum(_csv_row_count(p) for p in matched)
    opener = gzip.open if path_str.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        return sum(1 for _ in reader)


def test_csv_loader_registers_all_logical_tables(sources_yml):
    """The loader's view counts must match the underlying CSV files exactly.
    No hardcoded numbers — the data grows as new exports land in `data/raw/`."""
    cfg = config_mod.load(sources_yml)
    loader = loaders.build(cfg)
    con = duckdb.connect(":memory:")
    loader.register(con)

    for name in LOGICAL_TABLES:
        expected = _csv_row_count(cfg.csv.root / CSV_FILES[name])
        count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert count == expected, f"{name}: view {count} rows vs CSV {expected} rows"
    # The four always-on-disk warehouse exports must have rows. Multi-file
    # tables (e.g. ga_events) are allowed to be empty if fetch hasn't been
    # run in `fetch_all` mode yet — the loader registers them as empty views.
    for name in ("authors", "books", "tokens", "token_purchases"):
        count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        assert count > 0, f"{name}: no rows registered (empty CSV?)"


def test_unknown_loader_raises(tmp_path):
    bad = tmp_path / "sources.yml"
    bad.write_text("loader: nonexistent\n")
    cfg = config_mod.load(bad)
    with pytest.raises(ValueError, match="Unknown loader"):
        loaders.build(cfg)


def test_types_are_pinned(warehouse):
    cols = dict(
        warehouse.con.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'token_purchases'"
        ).fetchall()
    )
    assert cols["price_cents"] == "INTEGER"
    assert cols["purchase_date"] == "TIMESTAMP"
    assert cols["created_at"] == "TIMESTAMP"
