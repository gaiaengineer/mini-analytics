from dataclasses import dataclass
from pathlib import Path

import duckdb

from mini_analytics import config as config_mod
from mini_analytics import loaders

MODELS: tuple[str, ...] = (
    "fct_token_purchase",
    "dim_book",
    "dim_author",
)


@dataclass(frozen=True)
class Warehouse:
    con: duckdb.DuckDBPyConnection

    def query(self, sql: str) -> duckdb.DuckDBPyRelation:
        return self.con.sql(sql)

    def views(self) -> list[tuple[str, list[tuple[str, str]]]]:
        out: list[tuple[str, list[tuple[str, str]]]] = []
        names = [
            row[0]
            for row in self.con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        ]
        for name in names:
            cols = self.con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? "
                "ORDER BY ordinal_position",
                [name],
            ).fetchall()
            out.append((name, [(c[0], c[1]) for c in cols]))
        return out


def _models_dir() -> Path:
    return Path(__file__).parent / "models"


def _register_models(con: duckdb.DuckDBPyConnection) -> None:
    for name in MODELS:
        sql = (_models_dir() / f"{name}.sql").read_text()
        con.execute(sql)


def open(sources_yml: Path, db_path: Path | None = None) -> Warehouse:
    cfg = config_mod.load(sources_yml)
    loader = loaders.build(cfg)
    con = duckdb.connect(str(db_path) if db_path else ":memory:")
    loader.register(con)
    _register_models(con)
    return Warehouse(con=con)
