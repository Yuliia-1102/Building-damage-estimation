"""Admin helpers for the materials screen (epic 5.6).

Pure, testable functions. The Streamlit page (ui/pages/1_Materials_admin.py) only
calls these — it holds no database logic of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Material
from .prices import get_price_as_of, set_price


@dataclass(frozen=True)
class MaterialRow:
    id: int
    name: str
    unit: str
    price: float | None
    currency: str | None
    valid_from: date | None
    source: str | None


def list_materials_with_price(session: Session, as_of: date | None = None) -> list[MaterialRow]:
    if as_of is None:
        as_of = date.today()
    rows: list[MaterialRow] = []
    for m in session.scalars(select(Material).order_by(Material.name)):
        p = get_price_as_of(session, m.id, as_of)
        rows.append(MaterialRow(m.id, m.name, m.unit,
                                p.value if p else None,
                                p.currency if p else None,
                                p.valid_from if p else None,
                                p.source if p else None))
    return rows


def add_material(session: Session, name: str, unit: str) -> Material:
    name, unit = name.strip(), unit.strip()
    if not name or not unit:
        raise ValueError("name and unit are required")
    if session.scalar(select(Material).where(Material.name == name)):
        raise ValueError(f"material {name!r} already exists")
    material = Material(name=name, unit=unit)
    session.add(material)
    session.commit()
    return material


def update_price(session: Session, material_id: int, value: float,
                 valid_from: date | None = None, source: str = "manual",
                 source_url: str | None = None, currency: str = "UAH"):
    """Save a price, preserving history (delegates to set_price)."""
    if value < 0:
        raise ValueError("price must be >= 0")
    return set_price(session, material_id, value, valid_from, source, source_url, currency)
