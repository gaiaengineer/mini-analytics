from typing import Protocol

import duckdb

LOGICAL_TABLES: tuple[str, ...] = (
    "authors",
    "books",
    "tokens",
    "token_purchases",
    "ga_events",
)


class Loader(Protocol):
    def register(self, con: duckdb.DuckDBPyConnection) -> None:
        """Create one view per logical table name in LOGICAL_TABLES."""
        ...
