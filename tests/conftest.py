import subprocess
import sys
from pathlib import Path

import pytest

from mini_analytics import warehouse as wh


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def sources_yml(project_root: Path) -> Path:
    # A fresh clone has no data yet: generate the fictional demo dataset once.
    if not (project_root / "data" / "raw" / "token_purchases.csv").exists():
        subprocess.run([sys.executable, str(project_root / "scripts" / "make_demo_data.py")], check=True)
    return project_root / "sources.yml"


@pytest.fixture
def warehouse(sources_yml: Path):
    return wh.open(sources_yml)
