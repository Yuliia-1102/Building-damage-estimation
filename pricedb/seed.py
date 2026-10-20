"""Load initial data into the database (epic 5.2). Safe to run repeatedly."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.reference import WORK_TYPES_BY_CODE

from . import seed_data
from .models import DamageClass, Material, Price, WorkMaterial, WorkType
from .prices import set_labour_rate, set_price


def _get_or_create_material(session: Session, name: str, unit: str) -> Material:
    material = session.scalar(select(Material).where(Material.name == name))
    if material is None:
        material = Material(name=name, unit=unit)
        session.add(material)
        session.flush()
    return material


def load_seed(session: Session) -> None:
    materials = {
        name: _get_or_create_material(session, name, unit)
        for name, unit in seed_data.MATERIALS.items()
    }

    for name, material in materials.items():
        if name not in seed_data.PRICES:          # added later: first price comes from PRICE_REVISIONS
            continue
        if session.scalar(select(Price).where(
                Price.material_id == material.id,
                Price.valid_from == seed_data.PRICE_DATE)) is None:
            source, url = seed_data.SOURCES.get(name, (seed_data.DEFAULT_SOURCE, None))
            session.add(Price(material=material, value=seed_data.PRICES[name],
                              currency="UAH", valid_from=seed_data.PRICE_DATE,
                              source=source, source_url=url))

    classes = {c.code: c for c in session.scalars(select(DamageClass))}
    for code, (name, class_code, used) in seed_data.WORKS.items():
        unit = WORK_TYPES_BY_CODE[code].unit
        work = session.scalar(select(WorkType).where(WorkType.code == code))
        if work is None:
            work = WorkType(code=code, name=name, unit=unit, damage_class=classes[class_code])
            session.add(work)
            session.flush()
        work.unit = unit                 # the bill of quantities follows the seed: unit and quantities
        wanted = {materials[m].id: q for m, q in used.items()}
        for link in list(work.materials):
            if link.material_id not in wanted:
                session.delete(link)
        for material_id, qty in wanted.items():
            link = session.get(WorkMaterial, (work.id, material_id))
            if link is None:
                session.add(WorkMaterial(work_type=work, material_id=material_id, quantity_per_unit=qty))
            else:
                link.quantity_per_unit = qty

    session.commit()

    # set_price / set_labour_rate add a row only if that date has no such value yet, so this is repeatable
    for name, (value, source, url) in seed_data.PRICE_REVISIONS.items():
        set_price(session, materials[name].id, value, seed_data.REVISION_DATE, source, url)
    for code, (value, source, url) in seed_data.LABOUR.items():
        set_labour_rate(session, code, value, seed_data.LABOUR_DATE, source, url)
