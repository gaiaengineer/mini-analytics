from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CsvConfig:
    root: Path


@dataclass(frozen=True)
class S3Config:
    bucket: str
    region: str
    profile: str | None
    prefixes: dict[str, str]   # logical-table-name → S3 prefix
    download_to: Path           # where `mini-analytics fetch` writes CSVs
    # Logical tables for which fetch downloads *every* matching object instead
    # of just the latest one. Used when each file in a prefix represents a
    # different slice of data (e.g. one day of GA events per file).
    fetch_all: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SourcesConfig:
    loader: str
    csv: CsvConfig | None
    s3: S3Config | None


def load(path: Path) -> SourcesConfig:
    raw = yaml.safe_load(path.read_text())
    loader = raw["loader"]

    csv_cfg = None
    if "csv" in raw:
        root = Path(raw["csv"]["root"])
        if not root.is_absolute():
            root = (path.parent / root).resolve()
        csv_cfg = CsvConfig(root=root)

    s3_cfg = None
    if "s3" in raw:
        s3raw = raw["s3"]
        download_to = Path(s3raw.get("download_to", "data/raw"))
        if not download_to.is_absolute():
            download_to = (path.parent / download_to).resolve()
        s3_cfg = S3Config(
            bucket=s3raw["bucket"],
            region=s3raw.get("region", "us-east-1"),
            profile=s3raw.get("profile"),
            prefixes=dict(s3raw["prefixes"]),
            download_to=download_to,
            fetch_all=frozenset(s3raw.get("fetch_all", []) or []),
        )

    return SourcesConfig(loader=loader, csv=csv_cfg, s3=s3_cfg)
