from mini_analytics.config import SourcesConfig
from mini_analytics.loaders.base import Loader
from mini_analytics.loaders.csv_loader import CsvLoader


def build(config: SourcesConfig) -> Loader:
    if config.loader == "csv":
        if config.csv is None:
            raise ValueError("sources.yml selects loader=csv but has no `csv:` block")
        return CsvLoader(root=config.csv.root)
    raise ValueError(
        f"Unknown loader {config.loader!r}. "
        f"Known loaders: csv. (Stage-2 loaders like 'postgres' not implemented yet.)"
    )


__all__ = ["Loader", "CsvLoader", "build"]
