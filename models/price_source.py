"""The price source named in config.toml [prices] source: the materials database or the sample CSV files."""
from functools import lru_cache

from core import config


@lru_cache
def _sessions():
    from pricedb import open_db
    return open_db(config.path("materials_db"))


def default_price_source():
    """A new source on each call: a SQLite session must stay in the thread that made it (Streamlit)."""
    if config.get("prices", "source") == "db":
        from pricedb import MaterialsDbPriceSource
        return MaterialsDbPriceSource(_sessions()())
    from models.csv_prices import CsvPriceSource
    return CsvPriceSource()
