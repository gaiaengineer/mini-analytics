from dataclasses import dataclass, field
from pathlib import Path

import yaml

KPI = "kpi"
LINE = "line"
AREA_STACKED = "area_stacked"
BAR = "bar"
HISTOGRAM = "histogram"
TABLE = "table"
SCATTER = "scatter"
NOTE = "note"

BLOCK_TYPES = frozenset({KPI, LINE, AREA_STACKED, BAR, HISTOGRAM, TABLE, SCATTER, NOTE})


@dataclass(frozen=True)
class Block:
    id: str
    type: str
    title: str
    sql: str = ""                     # required for data blocks; empty for notes
    body: str | None = None           # note: the markdown-ish body to render
    description: str | None = None
    # chart axes / encoding (type-specific; not all used by every type)
    x: str | None = None
    y: str | None = None
    color: str | None = None
    # presentation
    format: str | None = None  # "currency" | "number" | "percent" | "integer" | None
    subtitle: str | None = None
    orientation: str | None = None   # bar: 'h' or 'v'
    height: int | None = None        # override chart pixel height
    nbins: int | None = None         # histogram bin count
    wide: bool = False               # force full-width cell in the grid
    size: str | None = None          # scatter: column to drive marker size
    color_map: dict[str, str] | None = None   # explicit category -> hex color overrides
    barmode: str | None = None       # bar/histogram: 'stack', 'group', 'relative', 'overlay'


@dataclass(frozen=True)
class Dashboard:
    id: str
    title: str
    description: str
    blocks: tuple[Block, ...] = field(default_factory=tuple)


def load(path: Path) -> Dashboard:
    raw = yaml.safe_load(path.read_text())
    blocks = tuple(Block(**b) for b in raw.get("blocks", []))
    for b in blocks:
        if b.type not in BLOCK_TYPES:
            raise ValueError(f"Block {b.id!r}: unknown type {b.type!r}")
        if b.type == NOTE:
            if not b.body:
                raise ValueError(f"Note block {b.id!r}: 'body' is required")
        else:
            if not b.sql:
                raise ValueError(f"Block {b.id!r}: 'sql' is required")
    return Dashboard(
        id=raw["id"],
        title=raw["title"],
        description=raw.get("description", ""),
        blocks=blocks,
    )


def load_all(directory: Path) -> list[Dashboard]:
    return [load(p) for p in sorted(directory.glob("*.yml"))]
