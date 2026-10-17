"""Price source backed by CSV files with the same tables as the materials database (task 5.4).

Used by tests and until the database is available. Prices are never overwritten: each row has a
valid_from date and the lookup takes the latest one on or before the requested date (task 5.3).
"""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from core import config


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _latest(history: list[tuple[str, float]], as_of: date) -> tuple[float, str] | None:
    valid = [(d, v) for d, v in history if d <= as_of.isoformat()]
    if not valid:
        return None
    d, v = max(valid)
    return v, d


class CsvPriceSource:
    def __init__(self, folder: Path | None = None):
        folder = Path(folder) if folder else config.path("prices_csv")
        self.materials = {int(r["id"]): r for r in _read(folder / "materials.csv")}
        self.work_materials = defaultdict(list)
        for r in _read(folder / "work_materials.csv"):
            self.work_materials[r["work_type"]].append((int(r["material_id"]), float(r["quantity_per_unit"])))
        self.prices = defaultdict(list)
        for r in _read(folder / "prices.csv"):
            self.prices[int(r["material_id"])].append((r["valid_from"], float(r["value"])))
        self.labour = defaultdict(list)
        for r in _read(folder / "labour_prices.csv"):
            self.labour[r["work_type"]].append((r["valid_from"], float(r["value"])))

    def get_items_by_work_type(self, work_type: str, limit: int) -> list[dict]:
        items = [{"id": mid, "name": self.materials[mid]["name"], "unit": self.materials[mid]["unit"],
                  "quantity_per_unit": qty} for mid, qty in self.work_materials.get(work_type, [])]
        return items[:limit]

    def get_price_as_of(self, item_id: int, as_of: date) -> tuple[float, str] | None:
        return _latest(self.prices.get(item_id, []), as_of)

    def get_labour_price_as_of(self, work_type: str, as_of: date) -> tuple[float, str] | None:
        return _latest(self.labour.get(work_type, []), as_of)
