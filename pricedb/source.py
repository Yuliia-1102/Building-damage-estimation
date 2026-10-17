"""Concrete PriceSource implementations (epic 5.4).

MaterialsDbPriceSource implements core.interfaces.PriceSource exactly:
    get_items_by_work_type(work_type: str, limit: int) -> list[dict]
    get_price_as_of(item_id: int, as_of: date) -> (value, valid_from ISO date) or None
    get_labour_price_as_of(work_type: str, as_of: date) -> (UAH per m2 of work, valid_from) or None

CsvPriceSource is the same contract backed by CSV files, for tests without a DB.
Returned dicts carry id, name, unit and quantity_per_unit (material per 1 m2 of work).
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Material, WorkMaterial, WorkType
from .prices import get_labour_rate_as_of
from .prices import get_price_as_of as _db_price_as_of


class MaterialsDbPriceSource:
    """PriceSource backed by the SQLite materials database."""

    label = "materials database"

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_items_by_work_type(self, work_type: str, limit: int) -> list[dict]:
        stmt = (
            select(WorkMaterial, Material)
            .join(WorkType, WorkType.id == WorkMaterial.work_type_id)
            .join(Material, Material.id == WorkMaterial.material_id)
            .where(WorkType.code == work_type)
            .order_by(Material.name)
            .limit(limit)
        )
        return [
            {
                "id": material.id,
                "name": material.name,
                "unit": material.unit,
                "quantity_per_unit": link.quantity_per_unit,
            }
            for link, material in self._session.execute(stmt)
        ]

    def get_price_as_of(self, item_id: int, as_of: date) -> tuple[float, str] | None:
        """The price and the date it is valid from, so the estimate shows which price was used."""
        price = _db_price_as_of(self._session, item_id, as_of)
        if price is None:
            return None
        return price.value, price.valid_from.isoformat()

    def get_labour_price_as_of(self, work_type: str, as_of: date) -> tuple[float, str] | None:
        rate = get_labour_rate_as_of(self._session, work_type, as_of)
        if rate is None:
            return None
        return rate.value, rate.valid_from.isoformat()


class CsvPriceSource:
    """Same contract, backed by two CSV files (tests without a database).

    items.csv:  work_type, id, name, unit, quantity_per_unit
    prices.csv: material_id, value, currency, valid_from
    """

    def __init__(self, items_csv: str | Path, prices_csv: str | Path) -> None:
        self._items: dict[str, list[dict]] = {}
        with open(items_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self._items.setdefault(row["work_type"], []).append({
                    "id": int(row["id"]),
                    "name": row["name"],
                    "unit": row["unit"],
                    "quantity_per_unit": float(row["quantity_per_unit"]),
                })

        self._prices: dict[int, list[tuple[date, float]]] = {}
        with open(prices_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mid = int(row["material_id"])
                self._prices.setdefault(mid, []).append(
                    (date.fromisoformat(row["valid_from"]), float(row["value"])))
        for lst in self._prices.values():
            lst.sort()

    def get_items_by_work_type(self, work_type: str, limit: int) -> list[dict]:
        return self._items.get(work_type, [])[:limit]

    def get_price_as_of(self, item_id: int, as_of: date) -> tuple[float, str] | None:
        valid = [(d, v) for d, v in self._prices.get(item_id, []) if d <= as_of]
        if not valid:
            return None
        d, v = valid[-1]
        return v, d.isoformat()

    def get_labour_price_as_of(self, work_type: str, as_of: date) -> tuple[float, str] | None:
        return None


def export_csv(session: Session, items_csv: str | Path, prices_csv: str | Path) -> None:
    """Dump the DB into the two CSV files a CsvPriceSource reads."""
    from .models import Price

    with open(items_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["work_type", "id", "name", "unit", "quantity_per_unit"])
        rows = session.execute(
            select(WorkType.code, Material, WorkMaterial.quantity_per_unit)
            .join(WorkMaterial, WorkMaterial.work_type_id == WorkType.id)
            .join(Material, Material.id == WorkMaterial.material_id)
            .order_by(WorkType.code, Material.name))
        for code, material, qty in rows:
            w.writerow([code, material.id, material.name, material.unit, qty])

    with open(prices_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["material_id", "value", "currency", "valid_from"])
        for p in session.scalars(select(Price).order_by(Price.material_id, Price.valid_from)):
            w.writerow([p.material_id, p.value, p.currency, p.valid_from.isoformat()])
