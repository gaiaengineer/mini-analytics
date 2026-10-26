from dataclasses import dataclass
from glob import glob as _glob
from pathlib import Path

import duckdb

CSV_FILES: dict[str, str] = {
    "authors": "authors.csv",
    "books": "books.csv",
    "tokens": "tokens.csv",
    "token_purchases": "token_purchases.csv",
    # ga_events ships one gzipped CSV per day; fetch downloads them all to
    # data/raw/ga_events/, and DuckDB's read_csv unions them through this glob.
    "ga_events": "ga_events/*.csv.gz",
}

COLUMN_TYPES: dict[str, dict[str, str]] = {
    "authors": {"id": "INTEGER", "name": "VARCHAR"},
    "books": {"id": "INTEGER", "author_id": "INTEGER", "title": "VARCHAR"},
    "tokens": {"id": "INTEGER", "book_id": "INTEGER"},
    "token_purchases": {
        "id": "INTEGER",
        "token_id": "INTEGER",
        "state": "VARCHAR",
        "price_cents": "INTEGER",
        "flow_type": "VARCHAR",
        "purchase_date": "TIMESTAMP",
        "created_at": "TIMESTAMP",
    },
    "ga_events": {
        "event_date":       "DATE",
        "event_timestamp":  "TIMESTAMP WITH TIME ZONE",
        "event_name":       "VARCHAR",
        # user_pseudo_id can exceed BIGINT range and arrives with a trailing ".0"
        # in the CSV. Treat it as an opaque identifier (VARCHAR) — we never do
        # arithmetic on it, only COUNT(DISTINCT).
        "user_pseudo_id":   "VARCHAR",
        "session_id":       "BIGINT",
        "page_location":    "VARCHAR",
        "page_title":       "VARCHAR",
        "device_category":  "VARCHAR",
        "device_os":        "VARCHAR",
        "country":          "VARCHAR",
        "city":             "VARCHAR",
        "traffic_source":   "VARCHAR",
        "traffic_medium":   "VARCHAR",
        "traffic_campaign": "VARCHAR",
    },
}


_GLOB_CHARS = "*?["


@dataclass(frozen=True)
class CsvLoader:
    root: Path

    def register(self, con: duckdb.DuckDBPyConnection) -> None:
        for logical, pattern in CSV_FILES.items():
            path = self.root / pattern
            is_glob = any(ch in pattern for ch in _GLOB_CHARS)

            if is_glob:
                # If the glob doesn't match anything (e.g. fetch hasn't run for
                # this table yet), register an empty view with the expected
                # schema rather than blowing up — downstream queries return
                # cleanly and the missing data is visible as zero rows.
                if not _glob(str(path)):
                    self._register_empty_view(con, logical)
                    continue
            elif not path.exists():
                raise FileNotFoundError(f"CSV not found for {logical!r}: {path}")

            types_sql = ", ".join(
                f"'{col}': '{dtype}'" for col, dtype in COLUMN_TYPES[logical].items()
            )
            # union_by_name=true keeps a multi-file read robust to harmless
            # schema drift across days. It's a no-op for single-file reads.
            con.execute(
                f"CREATE OR REPLACE VIEW {logical} AS "
                f"SELECT * FROM read_csv('{path.as_posix()}', "
                f"header=true, union_by_name=true, types={{{types_sql}}})"
            )

    @staticmethod
    def _register_empty_view(con: duckdb.DuckDBPyConnection, logical: str) -> None:
        cols = ", ".join(
            f"CAST(NULL AS {dtype}) AS {col}"
            for col, dtype in COLUMN_TYPES[logical].items()
        )
        con.execute(
            f"CREATE OR REPLACE VIEW {logical} AS SELECT {cols} WHERE FALSE"
        )
