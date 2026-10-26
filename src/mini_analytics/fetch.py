"""S3 fetch — pull data from each configured prefix into a local directory.

Two modes per logical table:

* **Latest only** (default): pick the most-recently-modified `*.csv`/`*.csv.gz`
  under the prefix and download it to `data/raw/<table>.<ext>`. The four
  warehouse exports use this — each file is a full snapshot of the table.

* **Fetch all**: download *every* matching object to `data/raw/<table>/`,
  preserving the original S3 key's basename. The CSV loader then reads them
  via a glob. Used when each file is a *slice* (e.g. one calendar day of GA
  events per file).

This module is deliberately separate from `loaders/` because fetching is
delivery (getting bytes onto disk), while a Loader is registration (turning
bytes into DuckDB views). Both `.csv` and `.csv.gz` source objects are
accepted; DuckDB's `read_csv` reads gzipped CSVs natively so there is no
decompression step.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import boto3

from mini_analytics.config import S3Config


CSV_SUFFIXES: tuple[str, ...] = (".csv", ".csv.gz")


@dataclass(frozen=True)
class FetchResult:
    table: str
    s3_key: str
    last_modified: datetime
    size_bytes: int
    local_path: Path


def _suffix_for(key: str) -> str:
    """Return the matching CSV suffix for an S3 key, or '' if none match.

    Order matters — `.csv.gz` must be checked before `.csv` because the latter
    is a prefix of the former.
    """
    for suffix in (".csv.gz", ".csv"):
        if key.endswith(suffix):
            return suffix
    return ""


def _iter_csv_objects(
    s3_client: Any, bucket: str, prefix: str
) -> Iterable[dict]:
    """Yield every `*.csv` or `*.csv.gz` object directly under `prefix`."""
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if _suffix_for(obj["Key"]):
                yield obj


def _pick_latest(s3_client: Any, bucket: str, prefix: str) -> dict | None:
    """Return the most-recently-modified CSV-ish object under `prefix`, or None.

    Ties on `LastModified` (rare in production, common in tests) are broken by
    descending key — which lines up with how the upstream job names files
    `YYYYMMDD-HHMMSS.csv[.gz]`, so lexicographic order approximates chronological.
    """
    candidates = list(_iter_csv_objects(s3_client, bucket, prefix))
    if not candidates:
        return None
    return max(candidates, key=lambda o: (o["LastModified"], o["Key"]))


def _build_client(cfg: S3Config) -> Any:
    """Create a boto3 S3 client honouring the configured profile + region.

    Profile is optional — if None, falls back to the default AWS chain
    (env vars, instance role, etc.).
    """
    session = (
        boto3.Session(profile_name=cfg.profile)
        if cfg.profile
        else boto3.Session()
    )
    return session.client("s3", region_name=cfg.region)


def _fetch_latest(
    s3_client: Any, cfg: S3Config, table: str, prefix: str
) -> FetchResult:
    latest = _pick_latest(s3_client, cfg.bucket, prefix)
    if latest is None:
        raise FileNotFoundError(
            f"No *.csv or *.csv.gz objects found under s3://{cfg.bucket}/{prefix}"
        )
    suffix = _suffix_for(latest["Key"])
    local_path = cfg.download_to / f"{table}{suffix}"
    s3_client.download_file(cfg.bucket, latest["Key"], str(local_path))
    return FetchResult(
        table=table,
        s3_key=latest["Key"],
        last_modified=latest["LastModified"],
        size_bytes=latest["Size"],
        local_path=local_path,
    )


def _fetch_all(
    s3_client: Any, cfg: S3Config, table: str, prefix: str
) -> list[FetchResult]:
    objects = list(_iter_csv_objects(s3_client, cfg.bucket, prefix))
    if not objects:
        raise FileNotFoundError(
            f"No *.csv or *.csv.gz objects found under s3://{cfg.bucket}/{prefix}"
        )

    # Clean up any legacy single-file artifacts from a previous "latest" run.
    for legacy_ext in (".csv", ".csv.gz"):
        legacy = cfg.download_to / f"{table}{legacy_ext}"
        if legacy.is_file():
            legacy.unlink()

    # Recreate the per-table directory so local state mirrors the bucket
    # exactly (no stale files left over from older runs).
    local_dir = cfg.download_to / table
    if local_dir.exists():
        for f in local_dir.iterdir():
            if f.is_file():
                f.unlink()
    local_dir.mkdir(parents=True, exist_ok=True)

    results: list[FetchResult] = []
    for obj in sorted(objects, key=lambda o: (o["LastModified"], o["Key"])):
        basename = obj["Key"].rsplit("/", 1)[-1]
        local_path = local_dir / basename
        s3_client.download_file(cfg.bucket, obj["Key"], str(local_path))
        results.append(
            FetchResult(
                table=table,
                s3_key=obj["Key"],
                last_modified=obj["LastModified"],
                size_bytes=obj["Size"],
                local_path=local_path,
            )
        )
    return results


def fetch_all(cfg: S3Config, *, s3_client: Any | None = None) -> list[FetchResult]:
    """Download from every prefix in `cfg.prefixes`.

    Tables in `cfg.fetch_all` download every matching object to
    `<download_to>/<table>/`. Other tables download only the latest matching
    object to `<download_to>/<table>.<ext>`.

    Raises `FileNotFoundError` if any prefix has zero CSV-ish objects.
    """
    client = s3_client if s3_client is not None else _build_client(cfg)
    cfg.download_to.mkdir(parents=True, exist_ok=True)

    results: list[FetchResult] = []
    for table, prefix in cfg.prefixes.items():
        if table in cfg.fetch_all:
            results.extend(_fetch_all(client, cfg, table, prefix))
        else:
            results.append(_fetch_latest(client, cfg, table, prefix))
    return results
