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
    def __init__(self, folder: Path | None = None, label: str | None = None):
        folder = Path(folder) if folder else config.path("prices_csv")
        self.folder = folder
        self.label = label or ("тестові ціни, не реальний кошторис" if folder.name == "prices_sample"
                               else f"CSV: {folder.name}")
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

    # ---- administration (task 5.6): prices are appended with a new date, never overwritten (task 5.3) ----

    def current_prices(self, as_of: date | None = None) -> list[dict]:
        as_of = as_of or date.today()
        rows = []
        for mid, m in sorted(self.materials.items()):
            latest = self.get_price_as_of(mid, as_of)
            rows.append({"id": mid, "name": m["name"], "unit": m["unit"],
                         "price": latest[0] if latest else None, "valid_from": latest[1] if latest else None,
                         "history": len(self.prices.get(mid, []))})
        return rows

    def price_history(self, material_id: int) -> list[tuple[str, float]]:
        return sorted(self.prices.get(material_id, []), reverse=True)

    def add_price(self, material_id: int, value: float, valid_from: date, source: str) -> None:
        with open(self.folder / "prices.csv", "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([material_id, value, "UAH", valid_from.isoformat(), source])
        self.prices[material_id].append((valid_from.isoformat(), float(value)))

    def add_material(self, name: str, unit: str) -> int:
        new_id = max(self.materials, default=0) + 1
        with open(self.folder / "materials.csv", "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([new_id, name, unit])
        self.materials[new_id] = {"id": str(new_id), "name": name, "unit": unit}
        return new_id
