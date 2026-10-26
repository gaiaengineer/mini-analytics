from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from mini_analytics.config import S3Config
from mini_analytics.fetch import fetch_all


def _make_cfg(tmp_path: Path) -> S3Config:
    return S3Config(
        bucket="test-bucket",
        region="us-east-1",
        profile=None,                       # tests don't need a real profile
        prefixes={
            "authors": "exports/authors/",
            "books":   "exports/books/",
        },
        download_to=tmp_path,
    )


@mock_aws
def test_fetch_all_picks_latest_csv_per_prefix(tmp_path: Path):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # authors/: three CSVs, the middle one should NOT win.
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/20260101-000000.csv", Body=b"id,name\n1,A\n")
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/20260301-000000.csv", Body=b"id,name\n1,A\n2,B\n3,C\n")
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/20260201-000000.csv", Body=b"id,name\n1,A\n2,B\n")

    # Plus a non-CSV that must be ignored even if it's the most recent.
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/manifest.json", Body=b"{}")

    s3.put_object(Bucket="test-bucket",
                  Key="exports/books/20260101-000000.csv", Body=b"id,author_id,title\n1,1,B1\n")
    s3.put_object(Bucket="test-bucket",
                  Key="exports/books/20260415-000000.csv", Body=b"id,author_id,title\n1,1,B1\n2,1,B2\n")

    cfg = _make_cfg(tmp_path)
    results = fetch_all(cfg, s3_client=s3)

    assert {r.table for r in results} == {"authors", "books"}

    by_table = {r.table: r for r in results}
    # Authors picks the March file (latest), not Jan / Feb / non-csv.
    assert by_table["authors"].s3_key == "exports/authors/20260301-000000.csv"
    # Books picks the April file (latest).
    assert by_table["books"].s3_key == "exports/books/20260415-000000.csv"

    # Local files exist with the right contents (sanity-check via line count).
    assert (tmp_path / "authors.csv").read_text().count("\n") == 3 + 1  # 3 rows + header
    assert (tmp_path / "books.csv").read_text().count("\n") == 2 + 1


@mock_aws
def test_fetch_all_raises_when_prefix_is_empty(tmp_path: Path):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    # authors has data; books has nothing.
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/20260101-000000.csv", Body=b"id,name\n1,A\n")

    cfg = _make_cfg(tmp_path)
    with pytest.raises(FileNotFoundError, match="exports/books/"):
        fetch_all(cfg, s3_client=s3)


@mock_aws
def test_fetch_all_ignores_non_csv_objects(tmp_path: Path):
    """A prefix containing only non-CSV files is treated as empty."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/20260101-000000.json", Body=b"[]")
    s3.put_object(Bucket="test-bucket",
                  Key="exports/authors/_SUCCESS",            Body=b"")

    cfg = S3Config(
        bucket="test-bucket", region="us-east-1", profile=None,
        prefixes={"authors": "exports/authors/"},
        download_to=tmp_path,
    )
    with pytest.raises(FileNotFoundError):
        fetch_all(cfg, s3_client=s3)


@mock_aws
def test_fetch_all_downloads_every_object_for_fetch_all_table(tmp_path: Path):
    """When a table is listed in `fetch_all`, every matching object lands under
    data/raw/<table>/ — not just the latest one — so multi-day slices can be
    read together as a glob."""
    import gzip

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # Three daily slices, plus a non-CSV that must be ignored.
    s3.put_object(
        Bucket="test-bucket",
        Key="imports/ga_events/20260101_20260101__20260102-000000.csv.gz",
        Body=gzip.compress(b"event_name,n\nclick,1\n"),
    )
    s3.put_object(
        Bucket="test-bucket",
        Key="imports/ga_events/20260102_20260102__20260103-000000.csv.gz",
        Body=gzip.compress(b"event_name,n\nclick,1\nview,2\n"),
    )
    s3.put_object(
        Bucket="test-bucket",
        Key="imports/ga_events/20260103_20260103__20260104-000000.csv.gz",
        Body=gzip.compress(b"event_name,n\nclick,1\nview,2\nscroll,3\n"),
    )
    s3.put_object(Bucket="test-bucket",
                  Key="imports/ga_events/manifest.json", Body=b"{}")

    cfg = S3Config(
        bucket="test-bucket",
        region="us-east-1",
        profile=None,
        prefixes={"ga_events": "imports/ga_events/"},
        download_to=tmp_path,
        fetch_all=frozenset({"ga_events"}),
    )
    results = fetch_all(cfg, s3_client=s3)

    # All three CSV.gz objects came back. The non-CSV was ignored.
    assert len(results) == 3
    assert all(r.table == "ga_events" for r in results)
    assert all(r.s3_key.endswith(".csv.gz") for r in results)

    # Files are nested under data/raw/ga_events/ and keep their original basenames.
    local_dir = tmp_path / "ga_events"
    assert local_dir.is_dir()
    filenames = sorted(p.name for p in local_dir.iterdir())
    assert filenames == [
        "20260101_20260101__20260102-000000.csv.gz",
        "20260102_20260102__20260103-000000.csv.gz",
        "20260103_20260103__20260104-000000.csv.gz",
    ]


@mock_aws
def test_fetch_all_cleans_up_legacy_single_file_when_switching_modes(tmp_path: Path):
    """A pre-existing data/raw/<table>.csv.gz from an earlier 'latest'-mode run
    is removed when the same table is later fetched in fetch_all mode."""
    import gzip

    legacy = tmp_path / "ga_events.csv.gz"
    legacy.write_bytes(gzip.compress(b"x,y\n1,2\n"))
    assert legacy.exists()

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    s3.put_object(
        Bucket="test-bucket",
        Key="imports/ga_events/20260101_20260101__20260102-000000.csv.gz",
        Body=gzip.compress(b"event_name,n\nclick,1\n"),
    )

    cfg = S3Config(
        bucket="test-bucket",
        region="us-east-1",
        profile=None,
        prefixes={"ga_events": "imports/ga_events/"},
        download_to=tmp_path,
        fetch_all=frozenset({"ga_events"}),
    )
    fetch_all(cfg, s3_client=s3)

    assert not legacy.exists()
    assert (tmp_path / "ga_events" / "20260101_20260101__20260102-000000.csv.gz").exists()


@mock_aws
def test_fetch_all_handles_csv_gz(tmp_path: Path):
    """`.csv.gz` objects are picked up, preserve their extension locally, and the
    picker prefers the latest among a mixed `.csv` + `.csv.gz` prefix."""
    import gzip

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    # Mixed prefix: an older plain CSV and a newer gzipped CSV. Gzipped must win.
    s3.put_object(
        Bucket="test-bucket",
        Key="imports/ga_events/20260101_20260101__20260102-000000.csv",
        Body=b"event,count\nclick,1\n",
    )
    s3.put_object(
        Bucket="test-bucket",
        Key="imports/ga_events/20260301_20260301__20260302-000000.csv.gz",
        Body=gzip.compress(b"event,count\nclick,1\nview,2\nscroll,3\n"),
    )

    cfg = S3Config(
        bucket="test-bucket",
        region="us-east-1",
        profile=None,
        prefixes={"ga_events": "imports/ga_events/"},
        download_to=tmp_path,
    )
    results = fetch_all(cfg, s3_client=s3)

    assert len(results) == 1
    r = results[0]
    assert r.table == "ga_events"
    # The gzipped (newer) object should win, and the extension is preserved.
    assert r.s3_key.endswith(".csv.gz")
    assert r.local_path.name == "ga_events.csv.gz"
    assert r.local_path.exists()

    # Round-trip: file on disk decompresses to the expected body.
    with gzip.open(r.local_path, "rt") as f:
        body = f.read()
    assert "scroll,3" in body
